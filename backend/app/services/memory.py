"""
services/memory.py — Async passive-embed worker + semantic retrieval.

Design:
  • A priority asyncio.Queue drains two tiers of embed work:
      REALTIME (0) — current conversation messages; processed immediately.
      BACKGROUND (1) — tasks, skills, bulk imports; processed with a small
                        inter-job delay in normal mode (removed in overnight mode).
  • embed_worker() runs as a background asyncio task during app lifespan.
  • Notes (from the knowledge router) write to note_chunks.embedding as before.
  • All other sources (messages, tasks, skills, future ZIM / ext-DB) write to
    memory_chunks(source_type, source_id, chunk_index, chunk_text, embedding).
  • retrieve_semantic() queries BOTH tables and merges results by score.
  • set_overnight_mode(True) removes the inter-job delay so the worker drains
    as fast as the embedding model allows — useful when the user is away.
"""
from __future__ import annotations

import asyncio
import itertools
import struct
import math
from typing import NamedTuple

import httpx

from ..config import settings
from ..state import g

# ── Priority constants ─────────────────────────────────────────────────────────

REALTIME = 0    # user messages, current session — always processed first
BACKGROUND = 1  # tasks, skills, bulk imports — yield to REALTIME

# ── Internal types ─────────────────────────────────────────────────────────────

class _EmbedJob(NamedTuple):
    text: str
    source_type: str   # 'note' | 'message' | 'task' | 'skill' | 'zim' | ...
    source_id: int     # PK in the source table
    chunk_index: int
    # Legacy field — only used when source_type == 'note'
    note_id: int = -1


# PriorityQueue items are (priority, sequence, job | None).
# The sequence counter ensures FIFO order within a priority tier.
# The shutdown sentinel is (999, 999, None) so it sorts last.
_embed_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
_seq = itertools.count()         # monotonic sequence for tie-breaking
_overnight_mode: bool = False    # modified by set_overnight_mode()


def queue_size() -> int:
    return _embed_queue.qsize()


def set_overnight_mode(enabled: bool) -> None:
    """
    Toggle overnight (fast-drain) mode.
    When True the worker processes BACKGROUND jobs without inter-job delays.
    """
    global _overnight_mode
    _overnight_mode = enabled


def enqueue_for_embed(text: str, note_id: int, chunk_index: int) -> None:
    """
    Legacy shim — called by the knowledge router when indexing notes.
    Routes the job to the BACKGROUND tier; writes to note_chunks.
    """
    job = _EmbedJob(
        text=text,
        source_type="note",
        source_id=note_id,
        chunk_index=chunk_index,
        note_id=note_id,
    )
    _embed_queue.put_nowait((BACKGROUND, next(_seq), job))


def enqueue_message(
    text: str,
    source_type: str,
    source_id: int,
    chunk_index: int = 0,
    priority: int = BACKGROUND,
) -> None:
    """
    Enqueue any non-note content for passive embedding.

    source_type: 'message' | 'task' | 'skill' | 'zim' | 'ext_db' | ...
    source_id:   PK in the relevant source table (messages.id, tasks.id, etc.)
    priority:    REALTIME for current-session content, BACKGROUND for everything else.
    """
    if not text or not text.strip():
        return
    job = _EmbedJob(
        text=text,
        source_type=source_type,
        source_id=source_id,
        chunk_index=chunk_index,
    )
    _embed_queue.put_nowait((priority, next(_seq), job))


# ── Embedding calls ────────────────────────────────────────────────────────────

async def _embed_text(text: str) -> list[float] | None:
    """Call local embedding model and return a float vector, or None on failure."""
    base = settings.embedding_base_url.rstrip("/")
    model = settings.embedding_model
    if not base or not model:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/embeddings",
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception:
        return None


def _vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _bytes_to_vec(raw: bytes) -> list[float]:
    n = len(raw) // 4
    return list(struct.unpack(f"{n}f", raw))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Background worker ──────────────────────────────────────────────────────────

async def embed_worker() -> None:
    """
    Background asyncio task — started once in app lifespan.

    Drains the priority queue:
      • REALTIME jobs (priority=0) are always processed immediately.
      • BACKGROUND jobs (priority=1) get a small inter-job sleep in normal mode
        so they don't compete with live server work. Set overnight mode to remove
        that delay for bulk imports.
    """
    while True:
        priority, _, item = await _embed_queue.get()

        if item is None:
            # Shutdown sentinel
            _embed_queue.task_done()
            break

        job: _EmbedJob = item
        try:
            vec = await _embed_text(job.text)
            if vec is not None:
                raw = _vec_to_bytes(vec)

                if job.source_type == "note":
                    # Legacy path — update the pre-existing note_chunks row
                    g.db.execute(
                        "UPDATE note_chunks SET embedding = ? WHERE note_id = ? AND chunk_index = ?",
                        (raw, job.note_id, job.chunk_index),
                    )
                else:
                    # Universal path — upsert into memory_chunks
                    g.db.execute(
                        """
                        INSERT INTO memory_chunks
                            (source_type, source_id, chunk_index, chunk_text, embedding)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(source_type, source_id, chunk_index)
                            DO UPDATE SET embedding = excluded.embedding
                        """,
                        (job.source_type, job.source_id, job.chunk_index, job.text, raw),
                    )
                g.db.commit()
        except Exception:
            pass
        finally:
            _embed_queue.task_done()

        # Throttle background jobs in normal mode so we don't saturate the
        # embedding model during active use. Overnight mode removes this wait.
        if priority == BACKGROUND and not _overnight_mode:
            await asyncio.sleep(0.5)


def stop_embed_worker() -> None:
    """Send the shutdown sentinel to the worker."""
    _embed_queue.put_nowait((999, 999, None))


# ── Semantic retrieval ─────────────────────────────────────────────────────────

async def retrieve_semantic(query: str, limit: int = 5) -> list[dict]:
    """
    Embed the query and return the top-k chunks ranked by cosine similarity,
    drawing from both the notes knowledge base (note_chunks) and the passive
    memory store (memory_chunks: messages, tasks, skills, etc.).

    Returns an empty list if the embedding model is unavailable or no chunks
    have been embedded yet.
    """
    query_vec = await _embed_text(query)
    if query_vec is None:
        return []

    # ── Pull note_chunks (knowledge base) ──────────────────────────────────
    note_rows = g.db.execute(
        """
        SELECT nc.note_id AS source_id,
               'note'     AS source_type,
               nc.chunk_index,
               nc.chunk_text,
               nc.embedding,
               n.title
        FROM note_chunks nc
        JOIN notes n ON n.id = nc.note_id
        WHERE nc.embedding IS NOT NULL
        """
    ).fetchall()

    # ── Pull memory_chunks (passive everything-else store) ─────────────────
    mem_rows = g.db.execute(
        """
        SELECT source_id,
               source_type,
               chunk_index,
               chunk_text,
               embedding,
               NULL AS title
        FROM memory_chunks
        WHERE embedding IS NOT NULL
        """
    ).fetchall()

    all_rows = list(note_rows) + list(mem_rows)
    if not all_rows:
        return []

    scored: list[tuple[float, dict]] = []
    for row in all_rows:
        vec = _bytes_to_vec(row["embedding"])
        score = _cosine(query_vec, vec)
        result: dict = {
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "chunk_index": row["chunk_index"],
            "chunk_text": row["chunk_text"],
            "title": row["title"],
            "score": round(score, 4),
        }
        # Keep note_id for backward-compat with callers that reference it directly
        if row["source_type"] == "note":
            result["note_id"] = row["source_id"]
        scored.append((score, result))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:limit]]
