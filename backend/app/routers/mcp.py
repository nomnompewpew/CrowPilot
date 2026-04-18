from __future__ import annotations

import asyncio
import json

import sqlite3
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..catalogs import MCP_ONBOARDING_CATALOG
from ..schemas import McpOnboardRequest, McpServerCreateRequest, McpServerUpdateRequest
from ..services.mcp import derive_onboarding_from_prompt, insert_mcp_server_with_unique_name
from ..services.mcp_relay import relay_call_tool, relay_list_tools, run_protocol_checks
from ..services.native_tools import (
    ASYNC_NATIVE_TOOL_NAMES,
    ASYNC_NATIVE_TOOLS,
    NATIVE_TOOLS,
    NATIVE_TOOL_NAMES,
    call_async_native_tool,
    call_native_tool,
)
from ..services.serializers import serialize_mcp_row
from ..services.credential_vault import encrypt_secret
from ..state import g
from ..utils import discover_local_ipv4
from ..config import settings

router = APIRouter(tags=["mcp"])


@router.get("/api/mcp/servers")
def list_mcp_servers() -> list[dict]:
    rows = g.db.execute(
        """
        SELECT id, name, transport, url, command, args_json, env_json,
               status, last_error, last_checked_at, created_at, updated_at
        FROM mcp_servers ORDER BY id DESC
        """
    ).fetchall()
    return [serialize_mcp_row(r) for r in rows]


@router.post("/api/mcp/servers")
async def create_mcp_server(payload: McpServerCreateRequest) -> dict:
    try:
        cur = g.db.execute(
            """
            INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.transport,
                payload.url,
                payload.command,
                json.dumps(payload.args),
                json.dumps(payload.env),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Server name already exists") from exc

    g.db.commit()
    row = g.db.execute(
        """
        SELECT id, name, transport, url, command, args_json, env_json,
               is_builtin, status, last_error, last_checked_at, created_at, updated_at
        FROM mcp_servers WHERE id = ?
        """,
        (cur.lastrowid,),
    ).fetchone()
    status, last_error, report = await run_protocol_checks(row)
    g.db.execute(
        """
        UPDATE mcp_servers
        SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, last_error, cur.lastrowid),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (cur.lastrowid,)).fetchone()
    out = serialize_mcp_row(updated)
    out["validation_report"] = report
    return out


@router.post("/api/mcp/onboard")
def mcp_onboard(payload: McpOnboardRequest) -> dict:
    return derive_onboarding_from_prompt(payload.prompt, payload.include_catalog)


@router.patch("/api/mcp/servers/{server_id}")
def update_mcp_server(server_id: int, payload: McpServerUpdateRequest) -> dict:
    existing = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="MCP server not found")

    next_values = dict(existing)
    patch = payload.model_dump(exclude_unset=True)
    if "args" in patch:
        next_values["args_json"] = json.dumps(patch.pop("args"))
    if "env" in patch:
        next_values["env_json"] = json.dumps(patch.pop("env"))
    for k, v in patch.items():
        next_values[k] = v

    g.db.execute(
        """
        UPDATE mcp_servers
        SET name = ?, transport = ?, url = ?, command = ?, args_json = ?, env_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["transport"],
            next_values["url"],
            next_values["command"],
            next_values["args_json"],
            next_values["env_json"],
            server_id,
        ),
    )
    g.db.commit()
    row = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    return serialize_mcp_row(row)


@router.delete("/api/mcp/servers/{server_id}")
def delete_mcp_server(server_id: int) -> dict:
    row = g.db.execute("SELECT id, is_builtin FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if row["is_builtin"]:
        raise HTTPException(status_code=403, detail="Built-in MCP servers are locked and cannot be deleted")
    g.db.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    g.db.commit()
    return {"deleted": True, "id": server_id}


@router.post("/api/mcp/servers/{server_id}/check")
async def check_mcp_server(server_id: int) -> dict:
    row = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    status, last_error, report = await run_protocol_checks(row)
    g.db.execute(
        """
        UPDATE mcp_servers
        SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, last_error, server_id),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    out = serialize_mcp_row(updated)
    out["validation_report"] = report
    return out


@router.get("/api/mcp/vscode-config")
def mcp_vscode_config() -> dict:
    addresses = discover_local_ipv4()
    relay_url = f"http://{addresses[0] if addresses else '127.0.0.1'}:{settings.port}/mcp"
    snippet = json.dumps(
        {"mcp": {"servers": {"crowpilot-relay": {"type": "http", "url": relay_url}}}}, indent=2
    )
    return {
        "relay_url": relay_url,
        "instructions": (
            "Paste 'snippet' into VS Code settings.json (or workspace .vscode/settings.json). "
            "CrowPilot aggregates all HTTP/SSE MCP backends through this single relay endpoint. "
            "Add new HTTP/SSE MCP servers via the MCP Forge tab and they appear here automatically."
        ),
        "snippet": snippet,
    }


@router.get("/api/mcp/catalog")
def mcp_catalog() -> list[dict]:
    """Return the onboarding catalog enriched with installed/connected status."""
    installed = {
        row["name"]: row["status"]
        for row in g.db.execute("SELECT name, status FROM mcp_servers").fetchall()
    }
    result = []
    for key, entry in MCP_ONBOARDING_CATALOG.items():
        env_keys = list(entry.get("env", {}).keys())
        result.append({
            "key": key,
            "name": entry["name"],
            "transport": entry["transport"],
            "url": entry.get("url"),
            "command": entry.get("command"),
            "auth_type": entry.get("auth_type", "none"),
            "notes": entry.get("notes", ""),
            "capabilities": entry.get("capabilities", []),
            "docs": entry.get("docs", []),
            "env_keys": env_keys,
            "installed": entry["name"] in installed,
            "status": installed.get(entry["name"], "not_installed"),
        })
    return result


@router.post("/api/mcp/connect")
async def mcp_connect(payload: dict) -> dict:
    """
    One-click connect: given a catalog key + optional credential value,
    save the credential to the vault, install the MCP server, and check it.
    payload: { service: str, credential_value: str | None, env_key: str | None }
    """
    service = (payload.get("service") or "").strip()
    if not service or service not in MCP_ONBOARDING_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")

    entry = MCP_ONBOARDING_CATALOG[service]
    credential_value = (payload.get("credential_value") or "").strip()
    env_key = (payload.get("env_key") or "").strip()

    # If a credential is provided, save it to the vault and build the env ref
    env = {}
    if credential_value and env_key:
        # Check if credential already exists for this service
        existing = g.db.execute(
            "SELECT id FROM credentials WHERE name = ?", (f"{service}-key",)
        ).fetchone()
        if existing:
            from ..services.credential_vault import encrypt_secret
            g.db.execute(
                "UPDATE credentials SET secret_enc = ?, updated_at = datetime('now') WHERE id = ?",
                (encrypt_secret(credential_value), existing["id"]),
            )
        else:
            from ..services.credential_vault import encrypt_secret
            g.db.execute(
                "INSERT INTO credentials(name, secret_enc) VALUES (?, ?)",
                (f"{service}-key", encrypt_secret(credential_value)),
            )
        g.db.commit()
        cred_row = g.db.execute(
            "SELECT id FROM credentials WHERE name = ?", (f"{service}-key",)
        ).fetchone()
        env = {env_key: f"{{{{cred:{cred_row['id']}}}}}"}
    elif entry.get("env"):
        # No credential provided but env keys exist — leave them empty for now
        env = {k: "" for k in entry["env"]}

    # Check if already installed — update env; otherwise insert
    existing_server = g.db.execute(
        "SELECT id FROM mcp_servers WHERE name = ?", (entry["name"],)
    ).fetchone()

    if existing_server:
        g.db.execute(
            "UPDATE mcp_servers SET env_json = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(env), existing_server["id"]),
        )
        g.db.commit()
        server_id = existing_server["id"]
    else:
        cur = g.db.execute(
            "INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json) VALUES (?,?,?,?,?,?)",
            (
                entry["name"],
                entry["transport"],
                entry.get("url"),
                entry.get("command"),
                json.dumps(entry.get("args", [])),
                json.dumps(env),
            ),
        )
        g.db.commit()
        server_id = cur.lastrowid

    row = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    status, last_error, report = await run_protocol_checks(row)
    g.db.execute(
        "UPDATE mcp_servers SET status=?, last_error=?, last_checked_at=datetime('now') WHERE id=?",
        (status, last_error, server_id),
    )
    g.db.commit()
    out = serialize_mcp_row(g.db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,)).fetchone())
    out["validation_report"] = report
    return out


@router.get("/mcp")
async def mcp_relay_sse(request: Request) -> StreamingResponse:
    """
    MCP Streamable HTTP — SSE channel for server-to-client notifications.
    VS Code opens this GET to establish the session; we keep it alive with
    periodic heartbeats.  Server-initiated notifications can be pushed here.
    """
    async def _sse():
        # Send endpoint event so the client knows where to POST messages.
        yield f"event: endpoint\ndata: /mcp\n\n"
        # Keep the connection alive; VS Code reconnects on drop.
        try:
            while True:
                await asyncio.sleep(15)
                yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/mcp")
async def mcp_relay(request: Request):
    # Optional bearer token guard — only enforced when PANTHEON_MCP_TOKEN is set.
    if settings.mcp_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {settings.mcp_token}":
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "Unauthorized — valid MCP token required"},
            }

    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params") or {}

    if req_id is None and method.startswith("notifications/"):
        return {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "crowpilot-relay", "version": "1.0.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        # Native tools always come first so the AI always has memory + task primitives.
        external_tools = await relay_list_tools()
        # Deduplicate: external tools with the same name as a native tool are shadowed.
        seen = set(NATIVE_TOOL_NAMES) | set(ASYNC_NATIVE_TOOL_NAMES)
        deduped_external = [t for t in external_tools if t.get("name") not in seen]
        all_tools = NATIVE_TOOLS + ASYNC_NATIVE_TOOLS + deduped_external
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": all_tools}}

    if method == "tools/call":
        tool_name = (params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        if not tool_name:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing tool name"}}
        # Route: async native → sync native → external relay
        if tool_name in ASYNC_NATIVE_TOOL_NAMES:
            result = await call_async_native_tool(tool_name, arguments)
        elif tool_name in NATIVE_TOOL_NAMES:
            result = call_native_tool(tool_name, arguments)
        else:
            result = await relay_call_tool(tool_name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
