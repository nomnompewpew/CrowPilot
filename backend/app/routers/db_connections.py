"""
routers/db_connections.py — External database connections for RAG.

Allows users to connect Postgres, MySQL, SQLite, or pgvector databases.
Passwords are encrypted at rest using the credential vault cipher.

What this enables:
  • A data scientist can point CrowPilot at their Postgres warehouse.
  • Corbin gets the schema injected as context on every chat message for
    enabled connections, so it can write accurate queries without being
    asked to "figure out the schema" every time.
  • The native tool 'run_db_query' can execute SELECT-only queries against
    any enabled connection.

Security:
  • Passwords stored via Fernet encryption (same vault as credentials).
  • Only SELECT queries are executable through the tool interface.
  • Row cap of 500 rows per query enforced in the connector service.
  • Connections are opened per-request and immediately closed (no pooling
    in this version — keeps the trust boundary simple).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.credential_vault import encrypt_secret, decrypt_secret
from ..services.db_connector import build_connection, introspect_schema, run_select
from ..state import g

router = APIRouter(prefix="/api/db-connections", tags=["db_connections"])


# ── Request models ─────────────────────────────────────────────────────────────

class DbConnectionCreateRequest(BaseModel):
    name: str
    db_type: str          # 'postgres' | 'mysql' | 'sqlite' | 'pgvector'
    host: str = ""
    port: int = 0
    database_name: str = ""
    username: str = ""
    password: str = ""    # plaintext — encrypted before storage


class DbConnectionUpdateRequest(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None   # plaintext — encrypted before storage


class DbQueryRequest(BaseModel):
    sql: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "db_type": row["db_type"],
        "host": row["host"],
        "port": row["port"],
        "database_name": row["database_name"],
        "username": row["username"],
        # Never return password or encrypted DSN
        "schema": json.loads(row["schema_json"] or "{}"),
        "status": row["status"],
        "last_error": row["last_error"],
        "last_tested_at": row["last_tested_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_or_404(conn_id: int):
    row = g.db.execute(
        "SELECT * FROM db_connections WHERE id = ?", (conn_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="DB connection not found")
    return row


def _open_connection(row):
    """Decrypt the stored password and open a live DB connection."""
    password = ""
    if row["dsn_encrypted"]:
        password = decrypt_secret(row["dsn_encrypted"])
    return build_connection(dict(row), password)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_db_connections() -> list[dict]:
    rows = g.db.execute("SELECT * FROM db_connections ORDER BY id DESC").fetchall()
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
def create_db_connection(payload: DbConnectionCreateRequest) -> dict:
    db_type = payload.db_type.lower().strip()
    encrypted_pw = encrypt_secret(payload.password) if payload.password else None

    try:
        cur = g.db.execute(
            """
            INSERT INTO db_connections(name, db_type, host, port, database_name, username, dsn_encrypted, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'untested')
            """,
            (
                payload.name.strip(),
                db_type,
                payload.host.strip() or None,
                payload.port or None,
                payload.database_name.strip() or None,
                payload.username.strip() or None,
                encrypted_pw,
            ),
        )
        g.db.commit()
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail=f"A connection named '{payload.name}' already exists.")
        raise HTTPException(status_code=400, detail=str(exc))

    row = g.db.execute("SELECT * FROM db_connections WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize(row)


@router.patch("/{conn_id}")
def update_db_connection(conn_id: int, payload: DbConnectionUpdateRequest) -> dict:
    row = _get_or_404(conn_id)
    patch = payload.model_dump(exclude_unset=True)

    # Encrypt password before storing, remove plaintext from patch
    encrypted_pw = None
    if "password" in patch:
        pw = patch.pop("password")
        encrypted_pw = encrypt_secret(pw) if pw else None

    fields = []
    values = []
    for k, v in patch.items():
        if k in ("name", "host", "port", "database_name", "username"):
            fields.append(f"{k} = ?")
            values.append(v)
    if encrypted_pw is not None:
        fields.append("dsn_encrypted = ?")
        values.append(encrypted_pw)
    if not fields:
        return _serialize(row)

    fields.append("updated_at = datetime('now')")
    values.append(conn_id)
    g.db.execute(
        f"UPDATE db_connections SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    g.db.commit()
    return _serialize(g.db.execute("SELECT * FROM db_connections WHERE id = ?", (conn_id,)).fetchone())


@router.delete("/{conn_id}")
def delete_db_connection(conn_id: int) -> dict:
    cur = g.db.execute("DELETE FROM db_connections WHERE id = ?", (conn_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="DB connection not found")
    return {"deleted": True, "id": conn_id}


@router.post("/{conn_id}/test")
def test_db_connection(conn_id: int) -> dict:
    row = _get_or_404(conn_id)
    try:
        conn = _open_connection(row)
        conn.close()
        g.db.execute(
            """UPDATE db_connections
               SET status = 'connected', last_error = NULL, last_tested_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (conn_id,),
        )
        g.db.commit()
        return {"ok": True, "status": "connected"}
    except Exception as exc:
        error = str(exc)
        g.db.execute(
            """UPDATE db_connections
               SET status = 'error', last_error = ?, last_tested_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (error, conn_id),
        )
        g.db.commit()
        return {"ok": False, "status": "error", "error": error}


@router.post("/{conn_id}/introspect")
def introspect_db_schema(conn_id: int) -> dict:
    """
    Connect, fetch table/column metadata, cache it in schema_json.
    This schema is later injected as context in chat so the model can write
    accurate queries without asking the user to describe their database.
    """
    row = _get_or_404(conn_id)
    try:
        conn = _open_connection(row)
        schema = introspect_schema(conn, row["db_type"])
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Introspection failed: {exc}")

    g.db.execute(
        """UPDATE db_connections
           SET schema_json = ?, status = 'connected', last_error = NULL,
               last_tested_at = datetime('now'), updated_at = datetime('now')
           WHERE id = ?""",
        (json.dumps(schema), conn_id),
    )
    g.db.commit()
    return {"ok": True, "table_count": len(schema), "schema": schema}


@router.post("/{conn_id}/query")
def run_db_query(conn_id: int, payload: DbQueryRequest) -> dict:
    """
    Execute a SELECT-only query against the external database.
    Results are capped at 500 rows. No write operations are permitted.
    """
    row = _get_or_404(conn_id)
    try:
        conn = _open_connection(row)
        results = run_select(conn, payload.sql, row["db_type"])
        conn.close()
    except ValueError as exc:
        # Query validation failure — not a server error
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Query failed: {exc}")

    return {"rows": results, "count": len(results)}
