from __future__ import annotations

import re

from ..state import g
from ..db import rows_to_dicts


def fetch_memory_context(query: str, limit: int = 3) -> list[dict]:
    """Search the notes FTS index for chunks relevant to the query."""
    try:
        safe = re.sub(r"[^\w\s]", " ", query).strip()
        if not safe:
            return []
        rows = g.db.execute(
            """
            SELECT n.title, nc.chunk_text, bm25(note_chunks_fts) AS score
            FROM note_chunks_fts
            JOIN note_chunks nc ON nc.id = note_chunks_fts.rowid
            JOIN notes n ON n.id = nc.note_id
            WHERE note_chunks_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
            """,
            (safe, limit),
        ).fetchall()
        return rows_to_dicts(rows)
    except Exception:
        return []


def conversation_rows_for_sidebar(where_clause: str, params: tuple, limit: int) -> list[dict]:
    from .serializers import serialize_conversation_row

    rows = g.db.execute(
        f"""
        SELECT
            c.id,
            c.title,
            c.created_at,
            c.sidebar_state,
            c.archive_bucket,
            c.archive_summary,
            c.archive_note,
            c.archived_at,
            (
                SELECT COUNT(*)
                FROM messages m
                WHERE m.conversation_id = c.id
            ) AS message_count
        FROM conversations c
        {where_clause}
        ORDER BY c.id DESC
        LIMIT ?
        """,
        params + (limit,),
    ).fetchall()
    return [serialize_conversation_row(r) for r in rows]
