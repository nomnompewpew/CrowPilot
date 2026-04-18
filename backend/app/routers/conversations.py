from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import rows_to_dicts
from ..schemas import ConversationOut, ConversationUpdateRequest, CreateConversationRequest, MessageOut
from ..services.knowledge import conversation_rows_for_sidebar
from ..services.serializers import serialize_conversation_row
from ..chunking import split_into_chunks
from ..state import g

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
def create_conversation(payload: CreateConversationRequest) -> dict:
    title = (payload.title or "New conversation").strip() or "New conversation"
    cur = g.db.execute("INSERT INTO conversations(title) VALUES (?)", (title,))
    g.db.commit()
    row = g.db.execute(
        "SELECT id, title, created_at FROM conversations WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


@router.get("")
def list_conversations(scope: str = "active", limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    if scope == "active":
        return conversation_rows_for_sidebar("WHERE c.sidebar_state = 'active'", (), limit)
    if scope == "hidden":
        return conversation_rows_for_sidebar("WHERE c.sidebar_state = 'hidden'", (), limit)
    if scope == "archived_good":
        return conversation_rows_for_sidebar(
            "WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'good'", (), limit
        )
    if scope == "archived_bad":
        return conversation_rows_for_sidebar(
            "WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'bad'", (), limit
        )
    if scope == "all":
        return conversation_rows_for_sidebar("", (), limit)
    raise HTTPException(status_code=400, detail="Unsupported conversation scope")


@router.get("/sidebar")
def conversation_sidebar(limit_per_bucket: int = 75) -> dict:
    limit_per_bucket = max(1, min(limit_per_bucket, 200))
    buckets = {
        "active": conversation_rows_for_sidebar("WHERE c.sidebar_state = 'active'", (), limit_per_bucket),
        "hidden": conversation_rows_for_sidebar("WHERE c.sidebar_state = 'hidden'", (), limit_per_bucket),
        "archived_good": conversation_rows_for_sidebar(
            "WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'good'", (), limit_per_bucket
        ),
        "archived_bad": conversation_rows_for_sidebar(
            "WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'bad'", (), limit_per_bucket
        ),
    }
    counts = {name: len(rows) for name, rows in buckets.items()}
    return {"buckets": buckets, "counts": counts}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int) -> dict:
    conv_row = g.db.execute(
        """
        SELECT id, title, created_at, sidebar_state, archive_bucket,
               archive_summary, archive_note, archived_at
        FROM conversations WHERE id = ?
        """,
        (conversation_id,),
    ).fetchone()
    if not conv_row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv_dict = dict(conv_row)
    msg_rows = g.db.execute(
        """
        SELECT id, conversation_id, role, content, provider, model, created_at
        FROM messages WHERE conversation_id = ? ORDER BY id ASC
        """,
        (conversation_id,),
    ).fetchall()
    conv_dict["messages"] = rows_to_dicts(msg_rows)
    return conv_dict


@router.patch("/{conversation_id}")
def update_conversation(conversation_id: int, payload: ConversationUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    action = payload.action
    if action == "restore":
        restore_state = "archived" if row["archive_bucket"] else "active"
        g.db.execute(
            """
            UPDATE conversations
            SET sidebar_state = ?, archive_bucket = ?, archived_at = ?,
                archive_summary = ?, archive_note = ?
            WHERE id = ?
            """,
            (
                restore_state,
                row["archive_bucket"] if restore_state == "archived" else None,
                row["archived_at"] if restore_state == "archived" else None,
                row["archive_summary"] if restore_state == "archived" else None,
                row["archive_note"] if restore_state == "archived" else None,
                conversation_id,
            ),
        )
        if restore_state == "active":
            g.db.execute(
                "DELETE FROM conversation_archive_chunks WHERE conversation_id = ?",
                (conversation_id,),
            )
    elif action == "hide":
        g.db.execute(
            "UPDATE conversations SET sidebar_state = 'hidden', archived_at = NULL WHERE id = ?",
            (conversation_id,),
        )
    else:
        archive_bucket = "good" if action == "archive_good" else "bad"
        msg_rows = g.db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        transcript = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in msg_rows)
        compressed = " ".join(transcript.split())
        chunks = split_into_chunks(compressed, settings.chunk_size, settings.chunk_overlap)
        summary = f"Archived {len(msg_rows)} messages as a {'good' if archive_bucket == 'good' else 'bad'} pattern example."

        g.db.execute(
            "DELETE FROM conversation_archive_chunks WHERE conversation_id = ?", (conversation_id,)
        )
        for idx, chunk in enumerate(chunks):
            g.db.execute(
                """
                INSERT INTO conversation_archive_chunks(conversation_id, archive_bucket, chunk_index, chunk_text)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, archive_bucket, idx, chunk),
            )

        g.db.execute(
            """
            UPDATE conversations
            SET sidebar_state = 'archived', archive_bucket = ?, archive_summary = ?,
                archive_note = ?, archived_at = datetime('now')
            WHERE id = ?
            """,
            (archive_bucket, summary, payload.note, conversation_id),
        )

    g.db.commit()
    updated = g.db.execute(
        """
        SELECT id, title, created_at, sidebar_state, archive_bucket,
               archive_summary, archive_note, archived_at
        FROM conversations WHERE id = ?
        """,
        (conversation_id,),
    ).fetchone()
    return serialize_conversation_row(updated)


@router.get("/{conversation_id}/archive-chunks")
def get_conversation_archive_chunks(conversation_id: int) -> dict:
    rows = g.db.execute(
        """
        SELECT archive_bucket, chunk_index, chunk_text, created_at
        FROM conversation_archive_chunks
        WHERE conversation_id = ? ORDER BY chunk_index ASC
        """,
        (conversation_id,),
    ).fetchall()
    return {"conversation_id": conversation_id, "chunks": rows_to_dicts(rows)}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict:
    cur = g.db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True, "id": conversation_id}


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(conversation_id: int) -> list[dict]:
    rows = g.db.execute(
        """
        SELECT id, conversation_id, role, content, provider, model, created_at
        FROM messages WHERE conversation_id = ? ORDER BY id ASC
        """,
        (conversation_id,),
    ).fetchall()
    return rows_to_dicts(rows)
