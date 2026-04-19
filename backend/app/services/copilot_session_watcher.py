"""
services/copilot_session_watcher.py — Copilot CLI session archiver.

Scans ~/.copilot/session-state/ for new / updated sessions, parses the
events.jsonl into a readable transcript, optionally generates an AI summary
via the local chat model, and queues chunks for embedding.

Background poll runs every POLL_INTERVAL seconds. Can also be triggered manually
via POST /api/copilot-history/scan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..state import g

log = logging.getLogger(__name__)

POLL_INTERVAL = 60          # seconds between scans
SESSION_STATE_DIR = Path.home() / ".copilot" / "session-state"
CHUNK_SIZE = 800            # characters per embedding chunk
CHUNK_OVERLAP = 120


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_events(events_path: Path) -> dict[str, Any]:
    """
    Parse events.jsonl and return a structured summary dict:
      {transcript, user_messages, assistant_turns, tool_calls}
    """
    lines: list[str] = []
    user_count = 0
    asst_count = 0
    tool_count = 0

    try:
        raw_events = []
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        for ev in raw_events:
            etype = ev.get("type", "")
            data = ev.get("data", {}) or {}

            if etype == "user.message":
                content = data.get("content", "").strip()
                if content:
                    lines.append(f"USER: {content}")
                    user_count += 1

            elif etype == "assistant.message":
                content = ""
                if isinstance(data, dict):
                    content = (data.get("content") or "").strip()
                # Skip pure tool-call messages (no visible text)
                if content:
                    lines.append(f"ASSISTANT: {content}")
                    asst_count += 1

            elif etype == "assistant.turn_start":
                # count turns (includes tool-only turns)
                asst_count_real = asst_count  # updated below

            elif etype in ("tool.execution_start",):
                tool_count += 1

        # deduplicate sequential assistant turns where text was streamed in parts
        # (the CLI sometimes emits multiple assistant.message events per turn)
        deduped: list[str] = []
        prev = None
        for line in lines:
            if line != prev:
                deduped.append(line)
            prev = line

    except Exception as exc:
        log.warning("Failed to parse %s: %s", events_path, exc)
        deduped = []

    return {
        "transcript": "\n\n".join(deduped),
        "user_messages": user_count,
        "assistant_turns": asst_count,
        "tool_calls": tool_count,
    }


def _parse_workspace_yaml(yaml_path: Path) -> dict[str, str]:
    """
    Minimal YAML parser for the flat workspace.yaml files.
    Returns a dict of string key→value (no deps on PyYAML).
    """
    result: dict[str, str] = {}
    try:
        for line in yaml_path.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith("#"):
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip()
    except Exception:
        pass
    return result


def _chunk_transcript(text: str) -> list[str]:
    """Split transcript into overlapping chunks for embedding."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ---------------------------------------------------------------------------
# AI summary
# ---------------------------------------------------------------------------

async def _generate_ai_summary(transcript: str, cli_title: str) -> str:
    """
    Ask local chat model for a 2-3 sentence summary of the session.
    Falls back to cli_title on any error.
    """
    if not transcript:
        return cli_title or ""

    # Take first 4000 chars of transcript to keep the prompt cheap
    excerpt = transcript[:4000]
    prompt = (
        f"Summarize this Copilot CLI conversation in 2-3 sentences. "
        f"Focus on what was built or solved, not the back-and-forth. "
        f"Be specific and terse.\n\n{excerpt}"
    )
    try:
        base = settings.chat_base_url.rstrip("/")
        payload = {
            "model": settings.chat_model,
            "messages": [
                {"role": "user", "content": f"/no_think {prompt}"},
            ],
            "max_tokens": 200,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.debug("AI summary failed for '%s': %s", cli_title, exc)
        return cli_title or ""


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

async def _embed_chunks(session_id: str, chunks: list[str]) -> None:
    """Embed chunks and store in copilot_cli_session_chunks."""
    if not chunks:
        return
    try:
        base = settings.embedding_base_url.rstrip("/")
        model = settings.embedding_model
        conn = g.db
        for idx, chunk in enumerate(chunks):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{base}/embeddings",
                        json={"model": model, "input": chunk},
                    )
                    resp.raise_for_status()
                    vec = resp.json()["data"][0]["embedding"]
                    import struct
                    blob = struct.pack(f"{len(vec)}f", *vec)
            except Exception:
                blob = None

            conn.execute(
                """
                INSERT INTO copilot_cli_session_chunks (session_id, chunk_index, chunk_text, embedding)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, chunk_index) DO UPDATE
                  SET chunk_text=excluded.chunk_text, embedding=excluded.embedding
                """,
                (session_id, idx, chunk, blob),
            )
        conn.execute(
            "UPDATE copilot_cli_sessions SET embedded=1 WHERE session_id=?",
            (session_id,),
        )
        conn.commit()
        log.info("Embedded %d chunks for session %s", len(chunks), session_id[:8])
    except Exception as exc:
        log.warning("Embedding failed for session %s: %s", session_id[:8], exc)


# ---------------------------------------------------------------------------
# Core ingest
# ---------------------------------------------------------------------------

async def ingest_session(session_dir: Path, force: bool = False) -> bool:
    """
    Parse and store a single session directory.
    Returns True if the session was newly ingested or updated.
    """
    session_id = session_dir.name
    workspace_yaml = session_dir / "workspace.yaml"
    events_jsonl = session_dir / "events.jsonl"

    if not events_jsonl.exists():
        return False

    ws = _parse_workspace_yaml(workspace_yaml)
    updated_at = ws.get("updated_at", "")

    conn = g.db
    existing = conn.execute(
        "SELECT session_updated_at, embedded FROM copilot_cli_sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()

    # Skip if unchanged and already embedded
    if existing and not force:
        if existing["session_updated_at"] == updated_at and existing["embedded"]:
            return False

    parsed = _parse_events(events_jsonl)
    cli_summary = ws.get("summary", "")
    ai_summary = await _generate_ai_summary(parsed["transcript"], cli_summary)

    conn.execute(
        """
        INSERT INTO copilot_cli_sessions
            (session_id, title, workspace, repository, branch, cli_summary, ai_summary,
             user_messages, assistant_turns, tool_calls, transcript,
             session_created_at, session_updated_at, embedded, last_scanned_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,datetime('now'))
        ON CONFLICT(session_id) DO UPDATE SET
            title=excluded.title,
            ai_summary=excluded.ai_summary,
            user_messages=excluded.user_messages,
            assistant_turns=excluded.assistant_turns,
            tool_calls=excluded.tool_calls,
            transcript=excluded.transcript,
            session_updated_at=excluded.session_updated_at,
            embedded=0,
            last_scanned_at=datetime('now')
        """,
        (
            session_id,
            cli_summary or session_id[:8],
            ws.get("cwd", ""),
            ws.get("repository", ""),
            ws.get("branch", ""),
            cli_summary,
            ai_summary,
            parsed["user_messages"],
            parsed["assistant_turns"],
            parsed["tool_calls"],
            parsed["transcript"],
            ws.get("created_at", ""),
            updated_at,
        ),
    )
    conn.commit()

    chunks = _chunk_transcript(parsed["transcript"])
    await _embed_chunks(session_id, chunks)

    return True


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

async def scan_sessions(force: bool = False) -> int:
    """
    Scan SESSION_STATE_DIR for all sessions and ingest new/updated ones.
    Returns count of sessions processed.
    """
    if not SESSION_STATE_DIR.exists():
        log.debug("No Copilot session-state dir at %s", SESSION_STATE_DIR)
        return 0

    count = 0
    for entry in SESSION_STATE_DIR.iterdir():
        if entry.is_dir():
            try:
                updated = await ingest_session(entry, force=force)
                if updated:
                    count += 1
            except Exception as exc:
                log.warning("Failed to ingest session %s: %s", entry.name, exc)

    if count:
        log.info("Copilot session watcher: ingested %d session(s)", count)
    return count


# ---------------------------------------------------------------------------
# VS Code transcript ingestion (local + crow-imported)
# ---------------------------------------------------------------------------

def _parse_vscode_transcript(jsonl_lines: list[str]) -> dict:
    """Parse a VS Code copilot transcript (same event format as CLI events.jsonl)."""
    lines: list[str] = []
    user_count = asst_count = tool_count = 0
    session_id = ""
    start_time = ""

    for raw in jsonl_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue

        etype = ev.get("type", "")
        data = ev.get("data", {}) or {}

        if etype == "session.start":
            session_id = data.get("sessionId", "")
            start_time = data.get("startTime", ev.get("timestamp", ""))

        elif etype == "user.message":
            content = data.get("content", "").strip()
            if content:
                lines.append(f"USER: {content}")
                user_count += 1

        elif etype == "assistant.message":
            content = (data.get("content") or "").strip()
            if content:
                lines.append(f"ASSISTANT: {content}")
                asst_count += 1

        elif etype == "tool.execution_start":
            tool_count += 1

    # deduplicate sequential identical lines (streaming artifacts)
    deduped: list[str] = []
    prev = None
    for l in lines:
        if l != prev:
            deduped.append(l)
        prev = l

    return {
        "session_id": session_id,
        "start_time": start_time,
        "transcript": "\n\n".join(deduped),
        "user_messages": user_count,
        "assistant_turns": asst_count,
        "tool_calls": tool_count,
    }


async def _ingest_vscode_transcript(
    jsonl_lines: list[str],
    fallback_session_id: str,
    workspace_id: str = "",
    source_type: str = "vscode",
    device_id: int | None = None,
    device_label: str = "",
    source_path: str = "",
    file_size: int = 0,
    force: bool = False,
) -> bool:
    """Parse a VS Code transcript and ingest into copilot_cli_sessions. Returns True if new/updated."""
    parsed = _parse_vscode_transcript(jsonl_lines)
    session_id = parsed["session_id"] or fallback_session_id

    if not session_id or not parsed["transcript"]:
        return False

    conn = g.db
    existing = conn.execute(
        "SELECT session_id, file_size, embedded FROM copilot_cli_sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()

    # Skip if file hasn't changed
    if existing and not force:
        if existing["file_size"] == file_size and existing["embedded"]:
            return False

    title = f"Session {session_id[:8]}"
    ai_summary = await _generate_ai_summary(parsed["transcript"], title)

    conn.execute(
        """
        INSERT INTO copilot_cli_sessions
            (session_id, title, workspace, repository, branch, cli_summary, ai_summary,
             user_messages, assistant_turns, tool_calls, transcript,
             session_created_at, session_updated_at, embedded, last_scanned_at,
             source_type, source_device_id, source_device_label, source_path, file_size)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,datetime('now'),?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET
            ai_summary=excluded.ai_summary,
            user_messages=excluded.user_messages,
            assistant_turns=excluded.assistant_turns,
            tool_calls=excluded.tool_calls,
            transcript=excluded.transcript,
            session_updated_at=excluded.session_updated_at,
            embedded=0,
            last_scanned_at=datetime('now'),
            source_type=excluded.source_type,
            source_device_id=excluded.source_device_id,
            source_device_label=excluded.source_device_label,
            source_path=excluded.source_path,
            file_size=excluded.file_size
        """,
        (
            session_id,
            title,
            workspace_id,
            "",  # repository
            "",  # branch
            "",  # cli_summary
            ai_summary,
            parsed["user_messages"],
            parsed["assistant_turns"],
            parsed["tool_calls"],
            parsed["transcript"],
            parsed["start_time"] or "",
            parsed["start_time"] or "",
            source_type,
            device_id,
            device_label,
            source_path,
            file_size,
        ),
    )
    conn.commit()

    chunks = _chunk_transcript(parsed["transcript"])
    await _embed_chunks(session_id, chunks)
    return True


async def scan_vscode_local(force: bool = False) -> int:
    """Scan local VS Code workspaceStorage directories for copilot transcripts."""
    import os
    import platform

    _sys = platform.system()
    candidates: list[Path] = []
    if _sys == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(Path(appdata) / "Code" / "User" / "workspaceStorage")
    elif _sys == "Darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage")
    else:
        candidates.append(Path.home() / ".config" / "Code" / "User" / "workspaceStorage")
        candidates.append(Path.home() / ".vscode-server" / "data" / "User" / "workspaceStorage")

    count = 0
    for base in candidates:
        if not base.exists():
            continue
        try:
            ws_dirs = [d for d in base.iterdir() if d.is_dir()]
        except PermissionError:
            continue

        for ws_dir in ws_dirs:
            transcripts_dir = ws_dir / "GitHub.copilot-chat" / "transcripts"
            if not transcripts_dir.is_dir():
                continue
            for f in transcripts_dir.glob("*.jsonl"):
                try:
                    size = f.stat().st_size
                    if size < 10:
                        continue
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                    updated = await _ingest_vscode_transcript(
                        jsonl_lines=lines,
                        fallback_session_id=f.stem,
                        workspace_id=ws_dir.name,
                        source_type="vscode",
                        source_path=str(f),
                        file_size=size,
                        force=force,
                    )
                    if updated:
                        count += 1
                except Exception as exc:
                    log.warning("Failed to ingest VS Code transcript %s: %s", f, exc)

    if count:
        log.info("VS Code local transcript scan: ingested %d session(s)", count)
    return count


async def harvest_crow_device(device_id: int, force: bool = False) -> int:
    """
    Pull all VS Code transcripts from a crow agent device and ingest them.
    Returns count of sessions ingested.
    """
    conn = g.db
    row = conn.execute("SELECT * FROM lan_devices WHERE id=?", (device_id,)).fetchone()
    if not row:
        return 0
    row = dict(row)
    ip, port, api_key, label = row["ip"], row["port"], row.get("api_key"), row["label"]
    headers = {"X-Crow-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"http://{ip}:{port}/copilot", headers=headers)
            if resp.status_code != 200:
                return 0
            data = resp.json()
    except Exception as exc:
        log.warning("Crow harvest: failed to connect to %s (%s): %s", label, ip, exc)
        return 0

    history = data.get("history", data)  # handle both new and old response shape
    sessions = history.get("vscode_sessions", [])
    transcript_sessions = [s for s in sessions if s.get("source") == "vscode-transcripts"]

    count = 0
    for session_meta in transcript_sessions:
        file_path = session_meta.get("file", "")
        file_size = session_meta.get("size", 0)
        fallback_id = session_meta.get("filename", "").replace(".jsonl", "").replace(".json", "")

        if not file_path:
            continue

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"http://{ip}:{port}/read",
                    params={"path": file_path},
                    headers=headers,
                )
                if resp.status_code != 200:
                    continue
                read_data = resp.json()
                if not read_data.get("ok"):
                    continue
                content = read_data.get("content", "")
                lines = content.splitlines()
        except Exception as exc:
            log.warning("Crow harvest: failed to read %s from %s: %s", file_path, label, exc)
            continue

        try:
            updated = await _ingest_vscode_transcript(
                jsonl_lines=lines,
                fallback_session_id=fallback_id,
                workspace_id=session_meta.get("workspace", ""),
                source_type="crow_vscode",
                device_id=device_id,
                device_label=label,
                source_path=file_path,
                file_size=file_size,
                force=force,
            )
            if updated:
                count += 1
        except Exception as exc:
            log.warning("Crow harvest: ingest failed for %s: %s", file_path, exc)

    log.info("Crow harvest %s: %d session(s) ingested", label, count)
    return count


async def harvest_all_crow_devices(force: bool = False) -> int:
    """Harvest copilot transcripts from all crow devices with auto_harvest=1."""
    conn = g.db
    rows = conn.execute(
        "SELECT id FROM lan_devices WHERE auto_harvest=1 AND status != 'offline'"
    ).fetchall()
    total = 0
    for row in rows:
        try:
            total += await harvest_crow_device(row["id"], force=force)
        except Exception as exc:
            log.warning("Crow harvest failed for device %d: %s", row["id"], exc)
    return total


# ---------------------------------------------------------------------------
# Background watcher task
# ---------------------------------------------------------------------------

HARVEST_INTERVAL = 300  # harvest crow devices every 5 minutes


async def session_watcher_task() -> None:
    """Runs forever, scanning every POLL_INTERVAL seconds."""
    log.info("Copilot session watcher started (interval=%ds)", POLL_INTERVAL)
    harvest_counter = 0
    while True:
        try:
            await scan_sessions()
        except Exception as exc:
            log.warning("Session watcher error (CLI): %s", exc)
        try:
            await scan_vscode_local()
        except Exception as exc:
            log.warning("Session watcher error (VS Code local): %s", exc)
        # Harvest crow devices every HARVEST_INTERVAL seconds
        harvest_counter += POLL_INTERVAL
        if harvest_counter >= HARVEST_INTERVAL:
            harvest_counter = 0
            try:
                await harvest_all_crow_devices()
            except Exception as exc:
                log.warning("Session watcher error (crow harvest): %s", exc)
        await asyncio.sleep(POLL_INTERVAL)
