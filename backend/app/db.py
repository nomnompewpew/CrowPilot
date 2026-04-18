from __future__ import annotations

import os
import sqlite3
from typing import Any


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def get_connection(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS conversation_archive_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            archive_bucket TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS note_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS note_chunks_fts USING fts5(
            chunk_text,
            content='note_chunks',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS note_chunks_ai AFTER INSERT ON note_chunks BEGIN
            INSERT INTO note_chunks_fts(rowid, chunk_text)
            VALUES (new.id, new.chunk_text);
        END;

        CREATE TRIGGER IF NOT EXISTS note_chunks_ad AFTER DELETE ON note_chunks BEGIN
            INSERT INTO note_chunks_fts(note_chunks_fts, rowid, chunk_text)
            VALUES('delete', old.id, old.chunk_text);
        END;

        CREATE TRIGGER IF NOT EXISTS note_chunks_au AFTER UPDATE ON note_chunks BEGIN
            INSERT INTO note_chunks_fts(note_chunks_fts, rowid, chunk_text)
            VALUES('delete', old.id, old.chunk_text);
            INSERT INTO note_chunks_fts(rowid, chunk_text)
            VALUES (new.id, new.chunk_text);
        END;

        CREATE TABLE IF NOT EXISTS mcp_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            transport TEXT NOT NULL,
            url TEXT,
            command TEXT,
            args_json TEXT NOT NULL DEFAULT '[]',
            env_json TEXT NOT NULL DEFAULT '{}',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unknown',
            last_error TEXT,
            last_checked_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dashboard_widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            widget_type TEXT NOT NULL,
            layout_col INTEGER NOT NULL DEFAULT 1,
            layout_row INTEGER NOT NULL DEFAULT 1,
            layout_w INTEGER NOT NULL DEFAULT 3,
            layout_h INTEGER NOT NULL DEFAULT 2,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS copilot_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            context_json TEXT NOT NULL DEFAULT '{}',
            result_markdown TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS automation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            objective TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'draft',
            sensitive_mode TEXT NOT NULL DEFAULT 'off',
            local_context_json TEXT NOT NULL DEFAULT '{}',
            cloud_prompt_template TEXT,
            runbook_markdown TEXT,
            run_count INTEGER NOT NULL DEFAULT 0,
            last_run_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            local_only INTEGER NOT NULL DEFAULT 0,
            input_schema_json TEXT NOT NULL DEFAULT '{}',
            output_schema_json TEXT NOT NULL DEFAULT '{}',
            tool_contract_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            provider_kind TEXT NOT NULL,
            base_url TEXT,
            auth_type TEXT NOT NULL DEFAULT 'api_key',
            api_key TEXT,
            default_model TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            models_json TEXT NOT NULL DEFAULT '[]',
            meta_json TEXT NOT NULL DEFAULT '{}',
            last_sync_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            credential_type TEXT NOT NULL,
            provider TEXT,
            username TEXT,
            secret_encrypted TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            last_used_at TEXT,
            last_rotated_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'app',
            status TEXT NOT NULL DEFAULT 'active',
            stack_json TEXT NOT NULL DEFAULT '{}',
            dev_url TEXT,
            last_opened_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sensitive_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            local_provider TEXT NOT NULL,
            local_model TEXT NOT NULL,
            cloud_provider TEXT NOT NULL,
            cloud_model TEXT NOT NULL,
            approval_required INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- Universal passive-embed store for all non-note sources
        -- (messages, tasks, skills, zim articles, external DB rows, etc.)
        CREATE TABLE IF NOT EXISTS memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL,
            embedding BLOB,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_type, source_id, chunk_index)
        );

        -- Key/value store for runtime-editable settings (e.g. Corbin prompt)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- ZIM file registry (Project Nomad integration)
        CREATE TABLE IF NOT EXISTS zim_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            filesize_bytes INTEGER NOT NULL DEFAULT 0,
            article_count INTEGER NOT NULL DEFAULT 0,
            indexed_chunks INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'registered',
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- External database connections for RAG (Postgres, MySQL, SQLite, pgvector, etc.)
        -- Passwords / connection secrets are stored in the credential vault (credentials table).
        -- credential_id references credentials.id; leave NULL to use a raw DSN stored encrypted
        -- in dsn_encrypted (Fernet, same key as credential vault).
        CREATE TABLE IF NOT EXISTS db_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            db_type TEXT NOT NULL,
            host TEXT,
            port INTEGER,
            database_name TEXT,
            username TEXT,
            credential_id INTEGER,
            dsn_encrypted TEXT,
            schema_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'untested',
            last_error TEXT,
            last_tested_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    _ensure_column(conn, "conversations", "sidebar_state", "sidebar_state TEXT NOT NULL DEFAULT 'active'")
    _ensure_column(conn, "conversations", "archive_bucket", "archive_bucket TEXT")
    _ensure_column(conn, "conversations", "archive_summary", "archive_summary TEXT")
    _ensure_column(conn, "conversations", "archive_note", "archive_note TEXT")
    _ensure_column(conn, "conversations", "archived_at", "archived_at TEXT")
    _ensure_column(conn, "mcp_servers", "is_builtin", "is_builtin INTEGER NOT NULL DEFAULT 0")
    # Passive embed worker — vector storage
    _ensure_column(conn, "note_chunks", "embedding", "embedding BLOB")
    # Setup wizard — track per-user completion
    _ensure_column(conn, "users", "setup_complete", "setup_complete INTEGER NOT NULL DEFAULT 0")

    conn.commit()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
