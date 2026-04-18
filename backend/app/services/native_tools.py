"""
CrowPilot native MCP tools — always available, no external dependencies or API keys.

These tools expose the app's own capabilities (knowledge base, task queue) directly
through the /mcp relay endpoint.  They appear first in tools/list so the AI always
has memory and task-management primitives regardless of which external servers are
connected.
"""
from __future__ import annotations

import re

from ..chunking import split_into_chunks
from ..config import settings
from ..state import g

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
