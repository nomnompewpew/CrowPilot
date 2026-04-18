"""
services/memory.py — Async passive-embed worker + semantic retrieval.

Design:
  • A single asyncio.Queue receives (text, note_id, chunk_index) work items.
  • embed_worker() runs as a background asyncio task during app lifespan.
  • Vectors are stored as raw float32 bytes in note_chunks.embedding.
  • retrieve_semantic() embeds a query on-demand and returns top-k chunks
    ranked by cosine similarity, falling back gracefully if the embedding
    model is unavailable.
"""
from __future__ import annotations

import asyncio
import struct
import math
from typing import NamedTuple

import httpx

from ..config import settings
from ..state import g

# ── Internal queue ─────────────────────────────────────────────────────────────

class _EmbedJob(NamedTuple):
    text: str
    note_id: int
    chunk_index: int


_embed_queue: asyncio.Queue[_EmbedJob | None] = asyncio.Queue()
_queue_size: int = 0  # approximate counter for the status badge


def queue_size() -> int:
    return _embed_queue.qsize()


def enqueue_for_embed(text: str, note_id: int, chunk_index: int) -> None:
    """Fire-and-forget: add a chunk to the background embed queue."""
    _embed_queue.put_nowait(_EmbedJob(text=text, note_id=note_id, chunk_index=chunk_index))


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
    Drains the embed queue and writes embeddings to note_chunks.embedding.
    """
    while True:
        job = await _embed_queue.get()
        if job is None:
            # Sentinel: shut down gracefully
            _embed_queue.task_done()
            break
        try:
            vec = await _embed_text(job.text)
            if vec is not None:
                raw = _vec_to_bytes(vec)
                g.db.execute(
                    "UPDATE note_chunks SET embedding = ? WHERE note_id = ? AND chunk_index = ?",
                    (raw, job.note_id, job.chunk_index),
                )
                g.db.commit()
        except Exception:
            pass
        finally:
            _embed_queue.task_done()


def stop_embed_worker() -> None:
    """Send the shutdown sentinel to the worker."""
    _embed_queue.put_nowait(None)


# ── Semantic retrieval ─────────────────────────────────────────────────────────

async def retrieve_semantic(query: str, limit: int = 5) -> list[dict]:
    """
    Embed the query and return the top-k note chunks ranked by cosine similarity.
    Returns an empty list if the embedding model is unavailable or no chunks
    have been embedded yet.
    """
    query_vec = await _embed_text(query)
    if query_vec is None:
        return []

    rows = g.db.execute(
        """
        SELECT nc.note_id, nc.chunk_index, nc.chunk_text, nc.embedding, n.title
        FROM note_chunks nc
        JOIN notes n ON n.id = nc.note_id
        WHERE nc.embedding IS NOT NULL
        """
    ).fetchall()

    if not rows:
        return []

    scored: list[tuple[float, dict]] = []
    for row in rows:
        vec = _bytes_to_vec(row["embedding"])
        score = _cosine(query_vec, vec)
        scored.append((score, {
            "note_id": row["note_id"],
            "chunk_index": row["chunk_index"],
            "chunk_text": row["chunk_text"],
            "title": row["title"],
            "score": round(score, 4),
        }))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:limit]]
