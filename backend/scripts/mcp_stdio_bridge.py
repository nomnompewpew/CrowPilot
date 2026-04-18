#!/usr/bin/env python3
"""
CrowPilot MCP stdio bridge.

VS Code's LocalWebWorker extension host (browser web worker) cannot make
fetch() calls to localhost on a remote tunnel host.  This script runs as a
subprocess on the remote machine via the stdio transport, so it CAN reach
127.0.0.1:8787 freely.

Protocol: newline-delimited JSON-RPC on stdin/stdout (MCP stdio transport).
Each line in → POST to /mcp → one line out.

If PANTHEON_MCP_TOKEN is set in the environment, it is forwarded as
Authorization: Bearer <token> on every request.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PANTHEON_URL = "http://127.0.0.1:8787/mcp"
_TOKEN = os.environ.get("PANTHEON_MCP_TOKEN", "")


def _post(msg: dict) -> dict:
    data = json.dumps(msg).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    req = urllib.request.Request(
        PANTHEON_URL,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32603, "message": f"HTTP {exc.code}: {body[:200]}"},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32603, "message": str(exc)},
        }


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue  # ignore malformed input

        response = _post(msg)

        # Notifications (no id, method starts with notifications/) expect no reply
        # but writing {} is harmless and keeps the protocol happy.
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32603, "message": f"HTTP {exc.code}: {body[:200]}"},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32603, "message": str(exc)},
        }


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue  # ignore malformed input

        response = _post(msg)

        # Notifications (no id, method starts with notifications/) expect no reply
        # but writing {} is harmless and keeps the protocol happy.
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
