"""
services/db_connector.py — External database connection management.

Supports PostgreSQL (including pgvector), MySQL, and local SQLite.
Passwords are stored in the credentials vault (Fernet-encrypted).

Security constraints enforced here:
  • Only SELECT statements are allowed through the query interface.
  • Row results are capped at MAX_ROWS to prevent memory exhaustion.
  • Connection timeouts prevent hanging queries from blocking the server.
  • No DDL, DML, or stored-procedure calls through this interface.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import settings

MAX_ROWS = 500
CONNECT_TIMEOUT = 10  # seconds


_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|"
    r"CALL|GRANT|REVOKE|COPY|VACUUM|ATTACH|DETACH)\b",
    re.IGNORECASE,
)


def _assert_select_only(sql: str) -> None:
    """Raise ValueError if the query is not a safe SELECT statement."""
    if not _SELECT_ONLY.match(sql):
        raise ValueError("Only SELECT statements are permitted.")
    if _FORBIDDEN.search(sql):
        raise ValueError("Query contains a forbidden keyword.")


# ── Connection builders ────────────────────────────────────────────────────────

def _connect_postgres(host: str, port: int, database: str, username: str, password: str):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise RuntimeError("psycopg2-binary is not installed. Run: pip install psycopg2-binary")
    return psycopg2.connect(
        host=host,
        port=port or 5432,
        dbname=database,
        user=username,
        password=password,
        connect_timeout=CONNECT_TIMEOUT,
    )


def _connect_mysql(host: str, port: int, database: str, username: str, password: str):
    try:
        import pymysql
    except ImportError:
        raise RuntimeError("pymysql is not installed. Run: pip install pymysql")
    return pymysql.connect(
        host=host,
        port=port or 3306,
        database=database,
        user=username,
        password=password,
        connect_timeout=CONNECT_TIMEOUT,
        autocommit=True,
    )


def _connect_sqlite(database: str, **_kwargs):
    import sqlite3
    conn = sqlite3.connect(database, timeout=CONNECT_TIMEOUT)
    conn.row_factory = sqlite3.Row
    return conn


_DRIVERS = {
    "postgres": _connect_postgres,
    "postgresql": _connect_postgres,
    "pgvector": _connect_postgres,
    "mysql": _connect_mysql,
    "mariadb": _connect_mysql,
    "sqlite": _connect_sqlite,
}


def build_connection(row: dict, password: str):
    """
    Open a connection to an external database given a db_connections row and
    the decrypted password (or empty string for password-less connections).
    Raises RuntimeError on unknown db_type or missing driver.
    """
    db_type = (row.get("db_type") or "").lower()
    driver = _DRIVERS.get(db_type)
    if not driver:
        raise RuntimeError(
            f"Unsupported db_type: '{db_type}'. "
            f"Supported: {', '.join(sorted(_DRIVERS))}"
        )
    return driver(
        host=row.get("host") or "localhost",
        port=row.get("port") or 0,
        database=row.get("database_name") or "",
        username=row.get("username") or "",
        password=password,
    )


# ── Schema introspection ───────────────────────────────────────────────────────

def introspect_schema(conn, db_type: str) -> dict:
    """
    Return a dict mapping table names → list of column name/type dicts.
    This is injected as context so the model can generate accurate queries.
    """
    db_type = db_type.lower()
    if db_type in ("postgres", "postgresql", "pgvector"):
        return _introspect_postgres(conn)
    if db_type in ("mysql", "mariadb"):
        return _introspect_mysql(conn)
    if db_type == "sqlite":
        return _introspect_sqlite(conn)
    return {}


def _introspect_postgres(conn) -> dict:
    schema: dict[str, list] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            LIMIT 100
            """
        )
        tables = [r[0] for r in cur.fetchall()]
        for table in tables:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            schema[table] = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
    return schema


def _introspect_mysql(conn) -> dict:
    schema: dict[str, list] = {}
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        for table in tables[:100]:
            cur.execute(f"DESCRIBE `{table}`")
            schema[table] = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
    return schema


def _introspect_sqlite(conn) -> dict:
    schema: dict[str, list] = {}
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    for (table,) in cur.fetchall():
        cols = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        if hasattr(cols[0], 'keys') if cols else False:
            schema[table] = [{"name": c["name"], "type": c["type"]} for c in cols]
        else:
            schema[table] = [{"name": c[1], "type": c[2]} for c in cols]
    return schema


# ── Query execution ────────────────────────────────────────────────────────────

def run_select(conn, sql: str, db_type: str) -> list[dict[str, Any]]:
    """
    Execute a SELECT query and return rows as a list of dicts.
    Raises ValueError if the SQL is not a safe SELECT.
    Caps results at MAX_ROWS.
    """
    _assert_select_only(sql)
    db_type = db_type.lower()

    if db_type == "sqlite":
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    else:
        import psycopg2.extras as pge
        with conn.cursor(cursor_factory=pge.RealDictCursor if "psycopg2" in type(conn).__module__ else None) as cur:
            cur.execute(sql)
            rows = cur.fetchmany(MAX_ROWS)
            if rows and not isinstance(rows[0], dict):
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in rows]
            return [dict(r) for r in rows]
