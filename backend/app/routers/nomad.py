"""
routers/nomad.py — Project Nomad / ZIM file integration.

Endpoints:
  GET  /api/nomad/files          — list registered ZIM files
  POST /api/nomad/files          — register a local ZIM file path + start indexing
  POST /api/nomad/files/{id}/reindex — restart indexing for an existing file
  DELETE /api/nomad/files/{id}   — unregister (does not delete the file from disk)

  GET  /api/nomad/embed-mode     — get overnight/realtime mode
  POST /api/nomad/embed-mode     — set overnight/realtime mode

ZIM files must already exist on the server filesystem. This is intentional:
downloading 28GB files over an HTTP API endpoint is a background OS operation,
not something the server should mediate synchronously.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.memory import set_overnight_mode
from ..services.zim_indexer import index_zim_file
from ..state import g

router = APIRouter(prefix="/api/nomad", tags=["nomad"])

# ── Running indexer tasks (in-memory, not persisted) ──────────────────────────
_active_tasks: dict[int, asyncio.Task] = {}


# ── Request/response models ───────────────────────────────────────────────────

class ZimRegisterRequest(BaseModel):
    path: str           # absolute path to the .zim file on the server
    name: str = ""      # human label; defaults to filename stem


class EmbedModeRequest(BaseModel):
    overnight: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_zim(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "filesize_bytes": row["filesize_bytes"],
        "article_count": row["article_count"],
        "indexed_chunks": row["indexed_chunks"],
        "status": row["status"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _spawn_indexer(zim_id: int, zim_path: str) -> None:
    """Cancel any existing task for this file then start a fresh one."""
    existing = _active_tasks.get(zim_id)
    if existing and not existing.done():
        existing.cancel()
    task = asyncio.create_task(index_zim_file(zim_id, zim_path))
    _active_tasks[zim_id] = task


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/files")
def list_zim_files() -> list[dict]:
    rows = g.db.execute(
        "SELECT * FROM zim_files ORDER BY id DESC"
    ).fetchall()
    return [_serialize_zim(r) for r in rows]


@router.post("/files", status_code=201)
async def register_zim_file(payload: ZimRegisterRequest) -> dict:
    path = Path(payload.path.strip())
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    if not path.suffix.lower() == ".zim":
        raise HTTPException(status_code=400, detail="File must have a .zim extension")

    name = payload.name.strip() or path.stem
    filesize = path.stat().st_size

    existing = g.db.execute(
        "SELECT id FROM zim_files WHERE path = ?", (str(path),)
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"ZIM file already registered (id={existing['id']}). Use /reindex to re-index it.",
        )

    cur = g.db.execute(
        """INSERT INTO zim_files(name, path, filesize_bytes, status)
           VALUES (?, ?, ?, 'registered')""",
        (name, str(path), filesize),
    )
    g.db.commit()
    zim_id = cur.lastrowid

    # Start indexing in the background immediately
    _spawn_indexer(zim_id, str(path))

    row = g.db.execute("SELECT * FROM zim_files WHERE id = ?", (zim_id,)).fetchone()
    return _serialize_zim(row)


@router.post("/files/{zim_id}/reindex")
async def reindex_zim_file(zim_id: int) -> dict:
    row = g.db.execute("SELECT * FROM zim_files WHERE id = ?", (zim_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="ZIM file not found")

    g.db.execute(
        """UPDATE zim_files
           SET status = 'registered', indexed_chunks = 0, last_error = NULL,
               updated_at = datetime('now')
           WHERE id = ?""",
        (zim_id,),
    )
    g.db.commit()

    _spawn_indexer(zim_id, row["path"])
    return {"ok": True, "id": zim_id, "status": "indexing"}


@router.delete("/files/{zim_id}")
def unregister_zim_file(zim_id: int) -> dict:
    task = _active_tasks.pop(zim_id, None)
    if task and not task.done():
        task.cancel()

    cur = g.db.execute("DELETE FROM zim_files WHERE id = ?", (zim_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="ZIM file not found")

    # Remove memory_chunks for this ZIM file so stale embeddings don't pollute search
    g.db.execute(
        "DELETE FROM memory_chunks WHERE source_type = 'zim' AND source_id = ?", (zim_id,)
    )
    g.db.commit()
    return {"deleted": True, "id": zim_id}


@router.get("/embed-mode")
def get_embed_mode() -> dict:
    row = g.db.execute("SELECT value FROM settings WHERE key = 'embed_mode'").fetchone()
    overnight = (row["value"] == "overnight") if row else False
    return {"overnight": overnight}


@router.post("/embed-mode")
def set_embed_mode(payload: EmbedModeRequest) -> dict:
    mode = "overnight" if payload.overnight else "realtime"
    g.db.execute(
        """INSERT INTO settings(key, value) VALUES ('embed_mode', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                          updated_at = datetime('now')""",
        (mode,),
    )
    g.db.commit()
    set_overnight_mode(payload.overnight)
    return {"overnight": payload.overnight, "mode": mode}
