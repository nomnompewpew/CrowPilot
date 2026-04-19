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
# Background watcher task
# ---------------------------------------------------------------------------

async def session_watcher_task() -> None:
    """Runs forever, scanning every POLL_INTERVAL seconds."""
    log.info("Copilot session watcher started (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            await scan_sessions()
        except Exception as exc:
            log.warning("Session watcher error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL)
