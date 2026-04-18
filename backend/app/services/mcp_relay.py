from __future__ import annotations

import json
import shutil

import httpx

from ..state import g
from ..utils import decode_json_field
from .credential_vault import resolve_env_credentials


def _build_auth_headers(resolved_env: dict[str, str]) -> dict[str, str]:
    """Return Authorization header built from the first non-empty resolved env value.

    Covers bearer tokens, API keys, and OAuth access tokens — all three patterns
    used by GitHub, Cloudflare, Stripe, Neon, Sentry, etc.
    """
    for value in resolved_env.values():
        if value and value.strip() and value.strip() != "<required>":
            return {"Authorization": f"Bearer {value.strip()}"}
    return {}


def _resolved_env_for_row(row) -> dict[str, str]:
    env_key = "env_json" if "env_json" in row.keys() else None
    env = decode_json_field(row[env_key] if env_key else "{}", {})
    resolved, _ = resolve_env_credentials(env)
    return resolved


async def run_protocol_checks(row) -> tuple[str, str | None, dict]:
    """Run reachability and MCP protocol checks against a server row.

    Returns (status, last_error, report).
    """
    transport = row["transport"]
    url = row["url"]
    command = row["command"]
    env_key = "env_json" if "env_json" in row.keys() else None
    env = decode_json_field(row[env_key] if env_key else "{}", {})
    resolved_env, env_resolution_errors = resolve_env_credentials(env)
    auth_headers = _build_auth_headers(resolved_env)
    checks: list[dict] = []
    discovered_tools: list[str] = []

    async def _post_jsonrpc(
        client: httpx.AsyncClient, target_url: str, method: str, params: dict, req_id: str,
        extra_headers: dict | None = None,
    ) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if extra_headers:
            headers.update(extra_headers)
        resp = await client.post(
            target_url,
            json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
            headers=headers,
        )
        ct = resp.headers.get("content-type", "")
        if ct.startswith("application/json") or "json" in ct:
            try:
                payload = resp.json()
            except Exception:
                payload = {}
        else:
            payload = {}
        return {"status": resp.status_code, "payload": payload}

    if transport in ("http", "sse"):
        if not url:
            report = {
                "transport": transport,
                "checks": [{"step": "configuration", "ok": False, "detail": "Missing URL for HTTP/SSE transport"}],
                "tools": [],
            }
            return "offline", "Missing URL for HTTP/SSE transport", report

        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                get_resp = await client.get(url, headers={"Accept": "application/json, text/event-stream", **auth_headers})
                checks.append(
                    {"step": "reachability", "ok": get_resp.status_code < 500, "detail": f"HTTP {get_resp.status_code}"}
                )

                if transport == "sse":
                    ct = get_resp.headers.get("content-type", "")
                    checks.append(
                        {"step": "sse_content_type", "ok": "text/event-stream" in ct, "detail": ct or "not provided"}
                    )

                init_result = await _post_jsonrpc(
                    client,
                    url,
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "crowpilot", "version": "0.1.0"},
                    },
                    "crowpilot-init",
                    extra_headers=auth_headers,
                )
                init_payload = init_result["payload"] if isinstance(init_result["payload"], dict) else {}
                init_ok = (
                    200 <= init_result["status"] < 300
                    and not init_payload.get("error")
                    and isinstance(init_payload.get("result"), dict)
                )
                checks.append(
                    {
                        "step": "mcp_initialize",
                        "ok": init_ok,
                        "detail": (
                            f"HTTP {init_result['status']}"
                            if init_ok
                            else (json.dumps(init_payload)[:220] or f"HTTP {init_result['status']}")
                        ),
                    }
                )

                if init_ok:
                    tools_result = await _post_jsonrpc(client, url, "tools/list", {}, "crowpilot-tools", extra_headers=auth_headers)
                    tools_payload = (
                        tools_result["payload"].get("result", {})
                        if isinstance(tools_result["payload"], dict)
                        else {}
                    )
                    tools = tools_payload.get("tools", []) if isinstance(tools_payload, dict) else []
                    discovered_tools = [
                        t.get("name") for t in tools if isinstance(t, dict) and t.get("name")
                    ]
                    tools_ok = (
                        200 <= tools_result["status"] < 300
                        and isinstance(tools_result["payload"], dict)
                        and not tools_result["payload"].get("error")
                        and isinstance(tools_payload, dict)
                    )
                    checks.append(
                        {"step": "mcp_tools_list", "ok": tools_ok, "detail": f"found {len(discovered_tools)} tools"}
                    )
                else:
                    checks.append(
                        {"step": "mcp_tools_list", "ok": False, "detail": "Skipped because initialize failed"}
                    )
        except Exception as exc:
            checks.append({"step": "exception", "ok": False, "detail": str(exc)})

    elif transport == "stdio":
        if not command:
            checks.append({"step": "configuration", "ok": False, "detail": "Missing command for stdio transport"})
        else:
            if env_resolution_errors:
                checks.append(
                    {"step": "credential_refs", "ok": False, "detail": "; ".join(env_resolution_errors[:3])}
                )

            missing_env = [
                k
                for k, v in (resolved_env or {}).items()
                if not isinstance(v, str) or not v.strip() or v.strip() == "<required>"
            ]
            if missing_env:
                checks.append(
                    {
                        "step": "required_env",
                        "ok": False,
                        "detail": f"Missing concrete values for: {', '.join(missing_env)}",
                    }
                )

            exe = command.strip().split()[0]
            found = shutil.which(exe) is not None
            checks.append(
                {"step": "binary_present", "ok": found, "detail": f"{exe} {'found' if found else 'not found in PATH'}"}
            )
            if exe in ("npx", "node"):
                checks.append(
                    {
                        "step": "runtime_hint",
                        "ok": found,
                        "detail": "Node-based MCP server declared; runtime availability checked only.",
                    }
                )
    else:
        checks.append({"step": "transport", "ok": False, "detail": f"Unsupported transport: {transport}"})

    all_ok = bool(checks) and all(c.get("ok") for c in checks)
    status = "online" if all_ok else "offline"
    failing = [c for c in checks if not c.get("ok")]
    last_error = None if all_ok else "; ".join(c.get("detail", "failed") for c in failing[:3])
    report = {"transport": transport, "checks": checks, "tools": discovered_tools}
    return status, last_error, report


async def relay_list_tools() -> list[dict]:
    """Fetch tools from all online HTTP/SSE MCP servers and rebuild the routing map."""
    rows = g.db.execute(
        """SELECT id, name, url, env_json FROM mcp_servers
           WHERE transport IN ('http', 'sse') AND status = 'online' AND url IS NOT NULL"""
    ).fetchall()

    all_tools: list[dict] = []
    new_map: dict[str, tuple[str, str]] = {}  # tool_name -> (url, server_name)

    async with httpx.AsyncClient(timeout=5.0) as client:
        for row in rows:
            url = row["url"]
            auth_headers = _build_auth_headers(_resolved_env_for_row(row))
            try:
                resp = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": "relay-tools", "method": "tools/list", "params": {}},
                    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **auth_headers},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tools = (
                        (data.get("result") or {}).get("tools", [])
                        if isinstance(data.get("result"), dict)
                        else []
                    )
                    for tool in tools:
                        if isinstance(tool, dict) and tool.get("name"):
                            new_map[tool["name"]] = (url, row["name"])
                            all_tools.append(tool)
            except Exception:
                pass

    g.mcp_tool_route_map = {name: entry[0] for name, entry in new_map.items()}
    g.mcp_server_name_map = {entry[0]: entry[1] for entry in new_map.values()}
    return all_tools


async def relay_call_tool(tool_name: str, arguments: dict) -> dict:
    """Route a tool call to the appropriate backend MCP server."""
    server_url = g.mcp_tool_route_map.get(tool_name)
    if not server_url:
        await relay_list_tools()
        server_url = g.mcp_tool_route_map.get(tool_name)

    if not server_url:
        return {
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not found in any connected MCP server."}],
            "isError": True,
        }

    # Look up auth headers for this server by URL
    row = g.db.execute(
        "SELECT env_json FROM mcp_servers WHERE url = ? AND status = 'online'", (server_url,)
    ).fetchone()
    auth_headers = _build_auth_headers(_resolved_env_for_row(row)) if row else {}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "relay-call",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **auth_headers},
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data.get("result"), dict):
                    return data["result"]
                if data.get("error"):
                    return {"content": [{"type": "text", "text": json.dumps(data["error"])}], "isError": True}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Relay error: {exc}"}], "isError": True}

    return {"content": [{"type": "text", "text": "No response from backend server."}], "isError": True}
