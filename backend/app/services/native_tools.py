"""
CrowPilot native MCP tools — always available, no external dependencies or API keys.

These tools expose the app's own capabilities (knowledge base, task queue) directly
through the /mcp relay endpoint.  They appear first in tools/list so the AI always
has memory and task-management primitives regardless of which external servers are
connected.

Agent tools (fs_list, fs_read, fs_write, shell_exec) are separate — they are passed
directly to the model in the chat agentic loop, not exposed via MCP.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx

from ..chunking import split_into_chunks
from ..config import settings
from ..state import g

# ---------------------------------------------------------------------------
# Agent filesystem / shell tools — security-scoped to home + /tmp
# ---------------------------------------------------------------------------

_HOME = Path.home()
_BLOCKED = ("/proc", "/sys", "/dev", "/run/secrets")


def _safe_path(raw: str, must_exist: bool = False) -> tuple[Path | None, str | None]:
    if not raw or not raw.strip():
        return None, "path is required"
    try:
        p = Path(raw).expanduser().resolve()
    except Exception as exc:
        return None, f"invalid path: {exc}"
    sp = str(p)
    if not any(sp.startswith(root) for root in (str(_HOME), "/tmp", "/home")):
        return None, f"path must be under home directory or /tmp (got {sp})"
    for blocked in _BLOCKED:
        if sp.startswith(blocked):
            return None, f"access denied: {blocked}"
    if must_exist and not p.exists():
        return None, f"path does not exist: {p}"
    return p, None


def _fs_list(args: dict) -> str:
    raw = (args.get("path") or str(_HOME)).strip()
    p, err = _safe_path(raw, must_exist=True)
    if err:
        return f"Error: {err}"
    if p.is_file():
        return f"{p} is a file — use fs_read to read it."
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return f"Permission denied: {p}"
    if not entries:
        return f"{p}/  (empty directory)"
    lines = [f"{p}/"]
    for e in entries[:300]:
        tag = "/" if e.is_dir() else ""
        size_str = ""
        if e.is_file():
            try:
                size_str = f"  {e.stat().st_size:,}B"
            except Exception:
                pass
        lines.append(f"  {'[dir] ' if e.is_dir() else '      '}{e.name}{tag}{size_str}")
    if len(entries) > 300:
        lines.append(f"  ... and {len(entries) - 300} more entries")
    return "\n".join(lines)


def _fs_read(args: dict) -> str:
    raw = (args.get("path") or "").strip()
    p, err = _safe_path(raw, must_exist=True)
    if err:
        return f"Error: {err}"
    if not p.is_file():
        return f"Error: {p} is not a file"
    try:
        with open(p, "rb") as f:
            sample = f.read(512)
        if b"\x00" in sample:
            return f"Error: {p} appears to be a binary file"
    except PermissionError:
        return f"Permission denied: {p}"
    try:
        text = p.read_text(errors="replace")
    except Exception as exc:
        return f"Error reading {p}: {exc}"
    all_lines = text.splitlines(keepends=True)
    total = len(all_lines)
    start = max(0, int(args.get("start_line") or 1) - 1)
    end = min(total, int(args.get("end_line") or total))
    selected = all_lines[start:end]
    MAX_LINES = 500
    MAX_BYTES = 40_000
    truncated = False
    if len(selected) > MAX_LINES:
        selected = selected[:MAX_LINES]
        truncated = True
    result = "".join(selected)
    if len(result) > MAX_BYTES:
        result = result[:MAX_BYTES]
        truncated = True
    shown_end = min(start + MAX_LINES, end)
    header = f"# {p}  (lines {start + 1}–{shown_end} of {total})\n"
    suffix = "\n... (truncated)" if truncated else ""
    return f"```\n{header}{result}{suffix}\n```"


def _fs_write(args: dict) -> str:
    raw = (args.get("path") or "").strip()
    content = args.get("content", "")
    mode = (args.get("mode") or "overwrite").strip().lower()
    p, err = _safe_path(raw, must_exist=False)
    if err:
        return f"Error: {err}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, "a") as f:
                f.write(content)
            return f"✓ Appended {len(content):,} bytes to {p}"
        else:
            p.write_text(content)
            return f"✓ Wrote {len(content):,} bytes to {p}"
    except PermissionError:
        return f"Permission denied: {p}"
    except Exception as exc:
        return f"Error writing {p}: {exc}"


def _shell_exec(args: dict) -> str:
    command = (args.get("command") or "").strip()
    if not command:
        return "Error: command is required"
    raw_cwd = (args.get("cwd") or str(_HOME)).strip()
    cwd_path, err = _safe_path(raw_cwd, must_exist=True)
    if err:
        return f"Error (cwd): {err}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        parts = [f"$ {command}", f"exit: {result.returncode}"]
        if result.stdout:
            out = result.stdout
            if len(out) > 12_000:
                out = out[:12_000] + "\n... (stdout truncated)"
            parts.append("stdout:\n" + out.rstrip())
        if result.stderr:
            serr = result.stderr
            if len(serr) > 6_000:
                serr = serr[:6_000] + "\n... (stderr truncated)"
            parts.append("stderr:\n" + serr.rstrip())
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after 30 seconds\n$ {command}"
    except Exception as exc:
        return f"Error running command: {exc}"


_AGENT_HANDLERS: dict[str, callable] = {
    "fs_list": _fs_list,
    "fs_read": _fs_read,
    "fs_write": _fs_write,
    "shell_exec": _shell_exec,
}

# OpenAI function-calling format — passed as `tools` to the model in chat.py
AGENT_TOOLS_OPENAI: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": (
                "List files and directories at a path on the server filesystem. "
                "Use this to explore project structure before reading files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to list. Must be under the home directory.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": (
                "Read the contents of a file on the server. "
                "Optionally specify start_line and end_line (1-based) to read a slice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "start_line": {"type": "integer", "description": "1-based start line (optional)."},
                    "end_line": {"type": "integer", "description": "1-based end line inclusive (optional)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": (
                "Write or overwrite a file on the server with the given content. "
                "Creates parent directories if needed. Use mode=append to add to existing files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to write."},
                    "content": {"type": "string", "description": "Full file content to write."},
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "description": "Write mode. Default overwrite.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": (
                "Execute a shell command in the given working directory. "
                "Returns stdout and stderr. Hard 30-second timeout. "
                "Use this to run tests, install packages, check git status, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                    "cwd": {
                        "type": "string",
                        "description": "Working directory. Must be under home. Defaults to home directory.",
                    },
                },
                "required": ["command"],
            },
        },
    },
]

AGENT_TOOL_NAMES: frozenset[str] = frozenset(_AGENT_HANDLERS)


def call_agent_tool(tool_name: str, arguments: dict) -> str:
    """Dispatch an agent tool call. Returns plain string result."""
    handler = _AGENT_HANDLERS.get(tool_name)
    if not handler:
        return f"Unknown agent tool: {tool_name}"
    try:
        return handler(arguments)
    except Exception as exc:
        return f"Tool error in {tool_name}: {exc}"

# ---------------------------------------------------------------------------
# Tool descriptors (returned verbatim in tools/list responses)
# ---------------------------------------------------------------------------

NATIVE_TOOLS: list[dict] = [
    {
        "name": "pantheon_remember",
        "description": (
            "Save information, context, code snippets, decisions, or notes to the "
            "CrowPilot persistent knowledge base.  Everything saved here is "
            "full-text-searchable and persists across all sessions.  Use this "
            "whenever the user asks you to remember something or whenever you want "
            "to preserve important context for the future."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The text to save.  Plain text, Markdown, or code all work."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Optional short title.  If omitted, a title is auto-generated "
                        "from the first line of content."
                    ),
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "pantheon_recall",
        "description": (
            "Search the CrowPilot knowledge base with full-text search and return "
            "the most relevant notes and excerpts.  Use this to retrieve previously "
            "saved facts, code patterns, decisions, or any persisted knowledge before "
            "answering questions that might already have a stored answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return.  Default 5, max 20.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "pantheon_note_list",
        "description": (
            "List the most recently saved notes in the CrowPilot knowledge base.  "
            "Returns title, a short preview, and timestamp.  Useful for browsing "
            "what has been remembered without a specific search query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of notes to return.  Default 10, max 50.",
                },
            },
        },
    },
    {
        "name": "pantheon_create_task",
        "description": (
            "Add a task to the CrowPilot task queue.  Useful for tracking work items, "
            "coding tasks, TODOs, or anything that needs follow-up.  Tasks are visible "
            "in the CrowPilot Tasks tab and persist across sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short, descriptive title for the task.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description.  Markdown is supported.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "pantheon_task_list",
        "description": (
            "List tasks from the CrowPilot task queue.  Check this before creating a "
            "new task to avoid duplicates, or to give the user a status overview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["queued", "in_progress", "done", "all"],
                    "description": (
                        "Filter by task status.  Defaults to 'queued' to show pending work."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max tasks to return.  Default 10.",
                },
            },
        },
    },
]

# Fast lookup set used in the relay to decide local vs proxy routing.
NATIVE_TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in NATIVE_TOOLS)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


# ---------------------------------------------------------------------------
# Handlers (one per tool)
# ---------------------------------------------------------------------------

def _remember(args: dict) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return _err("content is required and cannot be empty.")

    title = (args.get("title") or "").strip()
    if not title:
        first_line = content.splitlines()[0].strip()
        title = (first_line[:57] + "…") if len(first_line) > 60 else (first_line or "Note")

    cur = g.db.execute(
        "INSERT INTO notes(title, body) VALUES (?, ?)", (title, content)
    )
    note_id = cur.lastrowid
    chunks = split_into_chunks(content, settings.chunk_size, settings.chunk_overlap)
    for idx, chunk in enumerate(chunks):
        g.db.execute(
            "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            (note_id, idx, chunk),
        )
    g.db.commit()
    n = len(chunks)
    return _text(
        f"✓ Saved to knowledge base — note #{note_id} \"{title}\" "
        f"({n} chunk{'s' if n != 1 else ''} indexed for search)."
    )


def _recall(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return _err("query is required.")
    limit = min(int(args.get("limit") or 5), 20)

    safe = re.sub(r"[^\w\s]", " ", query).strip()
    if not safe:
        return _err("Query contains no searchable words.")

    try:
        rows = g.db.execute(
            """
            SELECT n.id, n.title, nc.chunk_text, bm25(note_chunks_fts) AS score
            FROM note_chunks_fts
            JOIN note_chunks nc ON nc.id = note_chunks_fts.rowid
            JOIN notes n ON n.id = nc.note_id
            WHERE note_chunks_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
            """,
            (safe, limit),
        ).fetchall()
    except Exception as exc:
        return _err(f"Search error: {exc}")

    if not rows:
        return _text(f"No knowledge base entries found matching '{query}'.")

    parts = [f"Found {len(rows)} result(s) for '{query}':\n"]
    for row in rows:
        parts.append(f"── Note #{row['id']}: {row['title']}\n{row['chunk_text']}\n")
    return _text("\n".join(parts))


def _note_list(args: dict) -> dict:
    limit = min(int(args.get("limit") or 10), 50)
    rows = g.db.execute(
        "SELECT id, title, body, created_at FROM notes ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()

    if not rows:
        return _text(
            "Knowledge base is empty.  Use pantheon_remember to save your first note."
        )

    parts = [f"Most recent {len(rows)} note(s):\n"]
    for row in rows:
        body = row["body"] or ""
        preview = body[:120].replace("\n", " ")
        if len(body) > 120:
            preview += "…"
        parts.append(f"#{row['id']} [{row['created_at']}] {row['title']}\n  {preview}\n")
    return _text("\n".join(parts))


def _create_task(args: dict) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return _err("title is required.")
    description = (args.get("description") or "").strip()

    cur = g.db.execute(
        """
        INSERT INTO copilot_tasks(title, description, status, context_json)
        VALUES (?, ?, 'queued', '{}')
        """,
        (title, description),
    )
    g.db.commit()
    return _text(f"✓ Task #{cur.lastrowid} queued: \"{title}\"")


def _task_list(args: dict) -> dict:
    status_filter = (args.get("status") or "queued").strip().lower()
    limit = min(int(args.get("limit") or 10), 50)

    if status_filter == "all":
        rows = g.db.execute(
            "SELECT id, title, description, status, created_at FROM copilot_tasks "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = g.db.execute(
            "SELECT id, title, description, status, created_at FROM copilot_tasks "
            "WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status_filter, limit),
        ).fetchall()

    if not rows:
        return _text(f"No tasks found with status '{status_filter}'.")

    parts = [f"{len(rows)} task(s) [{status_filter}]:\n"]
    for row in rows:
        desc = (row["description"] or "")[:80].replace("\n", " ")
        line = f"#{row['id']} [{row['status']}] {row['title']}"
        if desc:
            line += f"\n  {desc}"
        parts.append(line)
    return _text("\n".join(parts))


# ---------------------------------------------------------------------------
# Public dispatch function
# ---------------------------------------------------------------------------

_HANDLERS = {
    "pantheon_remember": _remember,
    "pantheon_recall": _recall,
    "pantheon_note_list": _note_list,
    "pantheon_create_task": _create_task,
    "pantheon_task_list": _task_list,
}


def call_native_tool(tool_name: str, arguments: dict) -> dict:
    """Dispatch a tools/call request to the appropriate native handler."""
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return _err(f"Native tool '{tool_name}' is not implemented.")
    try:
        return handler(arguments)
    except Exception as exc:
        return _err(f"Tool error in {tool_name}: {exc}")


# ---------------------------------------------------------------------------
# Async native tools — require httpx async calls to local model backends
# ---------------------------------------------------------------------------

# Prepend to system prompts for Qwen3 to disable chain-of-thought mode so the
# response arrives in `content` rather than `reasoning_content`.
_NO_THINK = "/no_think\n"

ASYNC_NATIVE_TOOLS: list[dict] = [
    {
        "name": "qwen_chat",
        "description": (
            "Send a prompt to the local Qwen3 language model running on this machine "
            "and return its response.  Use this when you need offline reasoning, code "
            "generation, or analysis that must stay completely local and private — "
            "nothing is sent to any cloud provider.  Supports an optional system "
            "prompt and temperature control."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The user message / task to send to Qwen3.",
                },
                "system": {
                    "type": "string",
                    "description": (
                        "Optional system prompt.  Overrides the default.  "
                        "Keep it concise — the model runs locally so context is limited."
                    ),
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature 0.0–1.0.  Default 0.7.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens to generate.  Default 1024.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "qwen_semantic_search",
        "description": (
            "Search the CrowPilot knowledge base using the local Qwen3 embedding "
            "model for semantic / meaning-based retrieval.  Unlike pantheon_recall "
            "(which uses keyword matching), this finds conceptually related content "
            "even when exact words don't match.  Use it when keyword search returns "
            "nothing or the query is phrased differently from stored notes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question or description to search for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return.  Default 5, max 20.",
                },
            },
            "required": ["query"],
        },
    },
]

ASYNC_NATIVE_TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in ASYNC_NATIVE_TOOLS)


async def _qwen_chat(args: dict) -> dict:
    base = (settings.local_base_url or "").rstrip("/")
    model = settings.local_model
    if not base:
        return _err(
            "Local model not configured.  Set PANTHEON_LOCAL_BASE_URL in .env "
            "pointing to your llama.cpp server (e.g. http://127.0.0.1:8082/v1)."
        )

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return _err("prompt is required.")

    raw_system = (args.get("system") or "You are a helpful local AI assistant.").strip()
    # Always prepend /no_think so Qwen3 returns in content, not reasoning_content
    system_prompt = _NO_THINK + raw_system

    temperature = float(args.get("temperature") or 0.7)
    max_tokens = int(args.get("max_tokens") or 1024)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": max(0.0, min(1.0, temperature)),
        "max_tokens": min(max_tokens, 4096),
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{base}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        return _err(
            f"Cannot connect to local model at {base}.  "
            "Is the llama.cpp server running?"
        )
    except Exception as exc:
        return _err(f"Local model request failed: {exc}")

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    if not text:
        # Qwen3 thinking mode fallback — should not happen with /no_think
        text = message.get("reasoning_content") or ""
    if not text:
        return _err("Local model returned an empty response.")

    return _text(text.strip())


async def _qwen_semantic_search(args: dict) -> dict:
    from .memory import retrieve_semantic  # local import to avoid circular

    query = (args.get("query") or "").strip()
    if not query:
        return _err("query is required.")
    limit = min(int(args.get("limit") or 5), 20)

    if not settings.embedding_base_url or not settings.embedding_model:
        return _err(
            "Embedding model not configured.  Set PANTHEON_EMBEDDING_BASE_URL "
            "and PANTHEON_EMBEDDING_MODEL in .env."
        )

    results = await retrieve_semantic(query, limit=limit)
    if not results:
        return _text(
            f"No semantically similar knowledge found for: '{query}'.  "
            "Either the knowledge base is empty, embeddings haven't been generated yet "
            "(check the embed badge in the sidebar), or the query is too dissimilar "
            "from stored content."
        )

    parts = [f"Semantic search found {len(results)} result(s) for '{query}':\n"]
    for r in results:
        source_type = r.get("source_type", "note")
        source_id = r.get("note_id") or r.get("source_id", "?")
        label = r.get("title") or source_type.capitalize()
        parts.append(
            f"── {label} #{source_id} (score {r['score']})\n{r['chunk_text']}\n"
        )
    return _text("\n".join(parts))


async def call_async_native_tool(tool_name: str, arguments: dict) -> dict:
    """Dispatch an async tools/call to the appropriate async native handler."""
    try:
        if tool_name == "qwen_chat":
            return await _qwen_chat(arguments)
        if tool_name == "qwen_semantic_search":
            return await _qwen_semantic_search(arguments)
    except Exception as exc:
        return _err(f"Tool error in {tool_name}: {exc}")
    return _err(f"Async native tool '{tool_name}' is not implemented.")
