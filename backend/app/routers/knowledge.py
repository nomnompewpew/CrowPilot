from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import rows_to_dicts
from ..schemas import AddNoteRequest, SearchNotesRequest
from ..chunking import split_into_chunks
from ..services.memory import enqueue_for_embed
from ..state import g

router = APIRouter(prefix="/api/notes", tags=["knowledge"])

_JINA_READER_BASE = "https://r.jina.ai/"
_JINA_SEARCH_BASE = "https://s.jina.ai/"
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _extract_title(markdown: str, fallback: str) -> str:
    m = _TITLE_RE.search(markdown)
    return m.group(1).strip()[:200] if m else fallback


@router.post("/fetch-url")
async def fetch_url_to_note(payload: dict) -> dict:
    """Fetch a URL via Jina Reader, convert to Markdown, and index it as a knowledge note."""
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    is_search = payload.get("search", False)
    api_key = (payload.get("api_key") or "").strip()

    if is_search:
        jina_url = _JINA_SEARCH_BASE + url
    else:
        # Ensure scheme
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        jina_url = _JINA_READER_BASE + url

    headers = {
        "Accept": "text/markdown, text/plain, */*",
        "X-Return-Format": "markdown",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(jina_url, headers=headers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Jina fetch failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Jina returned HTTP {resp.status_code}: {resp.text[:300]}",
        )

    markdown = resp.text.strip()
    if not markdown:
        raise HTTPException(status_code=502, detail="Jina returned empty content")

    title = payload.get("title") or _extract_title(markdown, url)

    cur = g.db.execute(
        "INSERT INTO notes(title, body) VALUES (?, ?)",
        (title[:200], markdown),
    )
    note_id = cur.lastrowid
    chunks = split_into_chunks(markdown, settings.chunk_size, settings.chunk_overlap)
    for idx, chunk in enumerate(chunks):
        g.db.execute(
            "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            (note_id, idx, chunk),
        )
        enqueue_for_embed(chunk, note_id, idx)
    g.db.commit()
    return {
        "note_id": note_id,
        "title": title,
        "chunks_indexed": len(chunks),
        "chars": len(markdown),
        "source_url": url,
        "jina_url": jina_url,
    }


@router.get("")
def list_notes(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 1000))
    rows = g.db.execute(
        "SELECT id, title, body, created_at FROM notes ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return rows_to_dicts(rows)


@router.post("")
def add_note(payload: AddNoteRequest) -> dict:
    cur = g.db.execute(
        "INSERT INTO notes(title, body) VALUES (?, ?)",
        (payload.title.strip(), payload.body.strip()),
    )
    note_id = cur.lastrowid
    chunks = split_into_chunks(payload.body, settings.chunk_size, settings.chunk_overlap)
    for idx, chunk in enumerate(chunks):
        g.db.execute(
            "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            (note_id, idx, chunk),
        )
        enqueue_for_embed(chunk, note_id, idx)
    g.db.commit()
    return {"note_id": note_id, "chunks_indexed": len(chunks)}


@router.post("/search")
def search_notes(payload: SearchNotesRequest) -> list[dict]:
    rows = g.db.execute(
        """
        SELECT
            n.id AS note_id,
            n.title AS note_title,
            nc.chunk_index,
            nc.chunk_text,
            bm25(note_chunks_fts) AS score
        FROM note_chunks_fts
        JOIN note_chunks nc ON nc.id = note_chunks_fts.rowid
        JOIN notes n ON n.id = nc.note_id
        WHERE note_chunks_fts MATCH ?
        ORDER BY score ASC
        LIMIT ?
        """,
        (payload.query, payload.limit),
    ).fetchall()
    return rows_to_dicts(rows)


@router.delete("/{note_id}")
def delete_note(note_id: int) -> dict:
    cur = g.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True, "id": note_id}
