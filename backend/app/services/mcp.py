from __future__ import annotations

import json
import re
import shutil

from fastapi import HTTPException

from ..catalogs import BUILTIN_MCP_SERVERS, MCP_ONBOARDING_CATALOG
from ..state import g
from ..utils import decode_json_field
from .credential_vault import resolve_env_credentials


def normalize_existing_mcp_servers() -> None:
    """Migrate stale transport/url values for existing MCP server rows."""
    rows = g.db.execute(
        "SELECT id, name, transport, url, command, env_json FROM mcp_servers"
    ).fetchall()

    catalog_by_name = {entry["name"]: entry for entry in MCP_ONBOARDING_CATALOG.values()}
    changed = False

    for row in rows:
        current = dict(row)
        name = (current.get("name") or "").strip()
        transport = current.get("transport")
        url = current.get("url") or ""
        command = current.get("command")
        env = decode_json_field(current.get("env_json"), {})

        next_transport = transport
        next_url = current.get("url")
        next_command = command
        next_env = dict(env)

        catalog_entry = catalog_by_name.get(name)
        if catalog_entry and next_transport == "stdio":
            if not next_command:
                next_command = catalog_entry.get("command")
            for k, v in (catalog_entry.get("env") or {}).items():
                if k not in next_env:
                    next_env[k] = v

        if (
            next_transport != transport
            or next_url != current.get("url")
            or next_command != command
            or next_env != env
        ):
            g.db.execute(
                """
                UPDATE mcp_servers
                SET transport = ?, url = ?, command = ?, env_json = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (next_transport, next_url, next_command, json.dumps(next_env), current["id"]),
            )
            changed = True

    if changed:
        g.db.commit()


def ensure_builtin_mcp_servers() -> None:
    """Seed or update builtin MCP server rows in the database."""
    changed = False
    for server in BUILTIN_MCP_SERVERS:
        existing = g.db.execute(
            "SELECT * FROM mcp_servers WHERE name = ?", (server["name"],)
        ).fetchone()
        if existing:
            env = decode_json_field(existing["env_json"], {})
            merged_env = {**(server.get("env") or {}), **(env or {})}
            g.db.execute(
                """
                UPDATE mcp_servers
                SET is_builtin = 1,
                    transport = COALESCE(NULLIF(transport, ''), ?),
                    command = COALESCE(command, ?),
                    url = COALESCE(url, ?),
                    args_json = CASE WHEN args_json IS NULL OR trim(args_json) = '' THEN ? ELSE args_json END,
                    env_json = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    server["transport"],
                    server["command"],
                    server.get("url"),
                    json.dumps(server.get("args") or []),
                    json.dumps(merged_env),
                    existing["id"],
                ),
            )
            changed = True
            continue

        g.db.execute(
            """
            INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json, is_builtin, status)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'unknown')
            """,
            (
                server["name"],
                server["transport"],
                server.get("url"),
                server.get("command"),
                json.dumps(server.get("args") or []),
                json.dumps(server.get("env") or {}),
            ),
        )
        changed = True

    if changed:
        g.db.commit()


def insert_mcp_server_with_unique_name(parsed: dict):
    """Insert an MCP server row, appending a numeric suffix if the name conflicts."""
    import sqlite3

    base_name = ((parsed.get("name") or "zen-mcp").strip() or "zen-mcp")[:64]
    for attempt in range(0, 25):
        if attempt == 0:
            candidate = base_name
        else:
            suffix = f"-{attempt + 1}"
            candidate = f"{base_name[: max(1, 64 - len(suffix))]}{suffix}"

        try:
            cur = g.db.execute(
                """
                INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate,
                    parsed.get("transport") or "http",
                    parsed.get("url"),
                    parsed.get("command"),
                    json.dumps(parsed.get("args") or []),
                    json.dumps(parsed.get("env") or {}),
                ),
            )
            g.db.commit()
            return g.db.execute(
                "SELECT * FROM mcp_servers WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        except sqlite3.IntegrityError:
            continue

    raise HTTPException(
        status_code=409, detail="Unable to create MCP server: generated names already exist"
    )


def derive_onboarding_from_prompt(prompt: str, include_catalog: bool) -> dict:
    text = (prompt or "").strip()
    lower = text.lower()
    matched = [key for key in MCP_ONBOARDING_CATALOG.keys() if key in lower]

    url_match = re.search(r"https?://[^\s,]+", text)
    explicit_url = url_match.group(0) if url_match else None

    suggestions: list[dict] = []
    if matched:
        for key in matched:
            base = dict(MCP_ONBOARDING_CATALOG[key])
            if explicit_url and not base.get("url"):
                base["url"] = explicit_url
                base["transport"] = "http"
                base["command"] = None
            suggestions.append({"id": key, **base})
    elif explicit_url:
        host_hint = re.sub(r"^https?://", "", explicit_url).split("/")[0]
        suggestions.append(
            {
                "id": "custom-http",
                "name": f"{host_hint}-mcp".replace(":", "-"),
                "transport": "http",
                "url": explicit_url,
                "command": None,
                "args": [],
                "env": {},
                "docs": ["https://modelcontextprotocol.io"],
                "notes": "Custom endpoint detected from prompt URL.",
            }
        )
    else:
        suggestions.append(
            {
                "id": "generic",
                "name": "custom-mcp",
                "transport": "http",
                "url": None,
                "command": None,
                "args": [],
                "env": {},
                "docs": ["https://modelcontextprotocol.io"],
                "notes": "No known provider matched. Provide endpoint URL or command.",
            }
        )

    primary = suggestions[0]
    response: dict = {
        "prompt": text,
        "matched": matched,
        "primary_suggestion": {
            "name": primary.get("name"),
            "transport": primary.get("transport"),
            "url": primary.get("url"),
            "command": primary.get("command"),
            "args": primary.get("args") or [],
            "env": primary.get("env") or {},
        },
        "suggestions": suggestions,
        "next_steps": [
            "Apply suggestion into form fields.",
            "Fill any <required> env variables.",
            "Add server and run protocol check.",
        ],
    }
    if include_catalog:
        response["catalog"] = MCP_ONBOARDING_CATALOG
    return response
