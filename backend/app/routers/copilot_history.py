"""
routers/copilot_history.py — Copilot CLI session archive endpoints.

  GET  /api/copilot-history/sessions          — list all sessions (paginated)
  GET  /api/copilot-history/sessions/{id}     — full session with transcript
  POST /api/copilot-history/scan              — trigger immediate rescan
  DELETE /api/copilot-history/sessions/{id}  — remove from index
  GET  /api/copilot-history/search            — semantic search over sessions
"""
from __future__ import annotations

import struct
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..db import rows_to_dicts
from ..services.copilot_session_watcher import scan_sessions
from ..state import g

router = APIRouter(prefix="/api/copilot-history", tags=["copilot-history"])


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("/sessions")
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query(""),
):
    conn = g.db
    if q:
        rows = conn.execute(
            """
            SELECT id, session_id, title, workspace, repository, branch,
                   cli_summary, ai_summary, user_messages, assistant_turns,
                   tool_calls, session_created_at, session_updated_at, embedded
            FROM copilot_cli_sessions
            WHERE title LIKE ? OR ai_summary LIKE ? OR workspace LIKE ? OR repository LIKE ?
            ORDER BY session_updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, session_id, title, workspace, repository, branch,
                   cli_summary, ai_summary, user_messages, assistant_turns,
                   tool_calls, session_created_at, session_updated_at, embedded
            FROM copilot_cli_sessions
            ORDER BY session_updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM copilot_cli_sessions").fetchone()[0]
    return {"sessions": rows_to_dicts(rows), "total": total}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    conn = g.db
    row = conn.execute(
        "SELECT * FROM copilot_cli_sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

@router.post("/scan")
async def trigger_scan(force: bool = Query(False)):
    count = await scan_sessions(force=force)
    return {"ingested": count}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    conn = g.db
    conn.execute(
        "DELETE FROM copilot_cli_session_chunks WHERE session_id=?", (session_id,)
    )
    conn.execute(
        "DELETE FROM copilot_cli_sessions WHERE session_id=?", (session_id,)
    )
    conn.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

@router.get("/search")
async def semantic_search(q: str = Query(..., min_length=1)):
    import httpx
    from ..config import settings

    # Embed the query
    try:
        base = settings.embedding_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{base}/embeddings",
                json={"model": settings.embedding_model, "input": q},
            )
            resp.raise_for_status()
            qvec = resp.json()["data"][0]["embedding"]
    except Exception as exc:
        raise HTTPException(503, f"Embedding model unavailable: {exc}")

    # Pull all embedded chunks
    conn = g.db
    chunks = conn.execute(
        """
        SELECT c.session_id, c.chunk_index, c.chunk_text, c.embedding,
               s.title, s.ai_summary, s.workspace, s.session_updated_at
        FROM copilot_cli_session_chunks c
        JOIN copilot_cli_sessions s ON c.session_id = s.session_id
        WHERE c.embedding IS NOT NULL
        """
    ).fetchall()

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb + 1e-9)

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in chunks:
        raw = row["embedding"]
        if not raw:
            continue
        n = len(raw) // 4
        vec = list(struct.unpack(f"{n}f", raw))
        score = cosine(qvec, vec)
        scored.append((score, {
            "session_id": row["session_id"],
            "chunk_index": row["chunk_index"],
            "chunk_text": row["chunk_text"],
            "title": row["title"],
            "ai_summary": row["ai_summary"],
            "workspace": row["workspace"],
            "session_updated_at": row["session_updated_at"],
            "score": round(score, 4),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Deduplicate by session, keep best chunk per session, top 10
    seen: set[str] = set()
    results: list[dict] = []
    for _, item in scored:
        sid = item["session_id"]
        if sid not in seen:
            seen.add(sid)
            results.append(item)
        if len(results) >= 10:
            break

    return {"results": results}
