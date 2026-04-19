#!/usr/bin/env python3
"""
crow_agent.py — Pantheon read-only LAN agent
=============================================
Drop this on any machine you want Pantheon to be able to read from.
stdlib-only; no pip install required beyond Python 3.8+.

Usage:
  python3 crow_agent.py [--port 8788] [--key YOUR_SECRET_KEY]

Install as systemd service (Linux):
  sudo python3 crow_agent.py --install

Then on your Pantheon instance: add the device IP and the same key.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_PORT = 8788
CROW_VERSION = "0.2.0"

# Paths the agent will never expose (always blocked regardless of request)
_BLOCKED_PREFIXES = ("/proc", "/sys", "/dev", "/boot", "/etc/shadow", "/etc/passwd", "/root/.ssh")

# Max bytes returned for file reads
_MAX_READ_BYTES = 256 * 1024  # 256 KB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_path(raw: str) -> tuple[Path | None, str | None]:
    try:
        p = Path(raw).expanduser().resolve()
    except Exception as e:
        return None, str(e)
    sp = str(p)
    for blocked in _BLOCKED_PREFIXES:
        if sp.startswith(blocked):
            return None, f"access denied: {blocked}"
    return p, None


def _system_info() -> dict:
    info: dict = {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "crow_version": CROW_VERSION,
    }
    # CPU / RAM (Linux)
    try:
        with open("/proc/cpuinfo") as f:
            cores = sum(1 for l in f if l.startswith("processor"))
        info["cpu_cores"] = cores
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    info["ram_kb"] = int(line.split()[1])
                    break
    except Exception:
        pass
    # Disk
    try:
        total, used, free = shutil.disk_usage("/")
        info["disk_total_gb"] = round(total / 1e9, 1)
        info["disk_free_gb"] = round(free / 1e9, 1)
    except Exception:
        pass
    # IP addresses
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
        info["ip_addresses"] = result.stdout.strip().split()
    except Exception:
        pass
    return info


def _vscode_copilot_history() -> list[dict]:
    """Return metadata about VS Code Copilot chat sessions on this machine."""
    base_dirs = [
        Path.home() / ".config/Code/User/workspaceStorage",
        Path.home() / "Library/Application Support/Code/User/workspaceStorage",
        Path(os.environ.get("APPDATA", "")) / "Code/User/workspaceStorage",
    ]
    results = []
    for base in base_dirs:
        if not base.exists():
            continue
        for ws_dir in base.iterdir():
            chat_db = ws_dir / "GitHub.copilot-chat" / "copilotMcpChatHistory.json"
            if not chat_db.exists():
                chat_db = ws_dir / "GitHub.copilot-chat" / "chatSessions.json"
            if not chat_db.exists():
                # look for any .json in the copilot dir
                copilot_dir = ws_dir / "GitHub.copilot-chat"
                if copilot_dir.is_dir():
                    for f in copilot_dir.glob("*.json"):
                        results.append({
                            "workspace": ws_dir.name,
                            "file": str(f),
                            "size": f.stat().st_size,
                            "mtime": f.stat().st_mtime,
                        })
                continue
            results.append({
                "workspace": ws_dir.name,
                "file": str(chat_db),
                "size": chat_db.stat().st_size,
                "mtime": chat_db.stat().st_mtime,
            })
    return results


def _vscode_extensions() -> list[str]:
    ext_dir = Path.home() / ".vscode/extensions"
    if not ext_dir.exists():
        ext_dir = Path.home() / ".vscode-server/extensions"
    if not ext_dir.exists():
        return []
    return sorted(d.name for d in ext_dir.iterdir() if d.is_dir())


def _running_services() -> list[str]:
    """Return list of listening ports (Linux)."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()[1:]  # skip header
        return lines
    except Exception:
        return []


# ── Request handler ───────────────────────────────────────────────────────────

class CrowHandler(http.server.BaseHTTPRequestHandler):
    api_key: str | None = None  # set at startup

    def log_message(self, format, *args):  # suppress default access log
        pass

    def _auth(self) -> bool:
        if not self.api_key:
            return True  # no key configured → open
        raw = self.headers.get("X-Crow-Key", "")
        # constant-time comparison
        return hmac.compare_digest(
            hashlib.sha256(raw.encode()).digest(),
            hashlib.sha256(self.api_key.encode()).digest(),
        )

    def _json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg: str, status: int = 400):
        self._json({"ok": False, "error": msg}, status)

    def do_GET(self):
        if not self._auth():
            self._err("unauthorized", 401)
            return

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path in ("/", "/health"):
            self._json({"ok": True, "hostname": socket.gethostname(), "version": CROW_VERSION})

        elif path == "/info":
            self._json({"ok": True, "info": _system_info()})

        elif path == "/copilot":
            self._json({"ok": True, "sessions": _vscode_copilot_history()})

        elif path == "/extensions":
            self._json({"ok": True, "extensions": _vscode_extensions()})

        elif path == "/services":
            self._json({"ok": True, "listeners": _running_services()})

        elif path == "/ls":
            raw = qs.get("path", [str(Path.home())])[0]
            p, err = _safe_path(raw)
            if err:
                self._err(err)
                return
            if not p.exists():
                self._err(f"path does not exist: {p}", 404)
                return
            if p.is_file():
                self._json({"ok": True, "type": "file", "path": str(p), "size": p.stat().st_size})
                return
            try:
                entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
                listing = []
                for e in entries[:500]:
                    entry = {"name": e.name, "is_dir": e.is_dir()}
                    if e.is_file():
                        try:
                            entry["size"] = e.stat().st_size
                        except Exception:
                            pass
                    listing.append(entry)
                self._json({"ok": True, "path": str(p), "entries": listing})
            except PermissionError:
                self._err("permission denied", 403)

        elif path == "/read":
            raw = qs.get("path", [""])[0]
            if not raw:
                self._err("path required")
                return
            p, err = _safe_path(raw)
            if err:
                self._err(err)
                return
            if not p.exists() or not p.is_file():
                self._err("file not found", 404)
                return
            try:
                data = p.read_bytes()
                try:
                    text = data[:_MAX_READ_BYTES].decode("utf-8")
                    truncated = len(data) > _MAX_READ_BYTES
                    self._json({"ok": True, "path": str(p), "content": text, "truncated": truncated, "size": len(data)})
                except UnicodeDecodeError:
                    self._err("binary file — not readable as text")
            except PermissionError:
                self._err("permission denied", 403)

        else:
            self._err("unknown endpoint", 404)


# ── Installer ─────────────────────────────────────────────────────────────────

def _install_systemd(port: int, key: str | None):
    script_path = Path(__file__).resolve()
    python = sys.executable
    key_arg = f" --key {key}" if key else ""
    service = textwrap.dedent(f"""
        [Unit]
        Description=Crow Agent (Pantheon read-only LAN agent)
        After=network.target

        [Service]
        Type=simple
        ExecStart={python} {script_path} --port {port}{key_arg}
        Restart=always
        RestartSec=10

        [Install]
        WantedBy=multi-user.target
    """).strip()

    svc_path = Path("/etc/systemd/system/crow-agent.service")
    svc_path.write_text(service)
    print(f"Wrote {svc_path}")
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", "crow-agent"])
    print(f"crow-agent started on port {port}")
    if key:
        print(f"API key: {key}")
    print("Add this device in Pantheon → Network tab.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Crow Agent — Pantheon read-only LAN agent")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--key", default=None, help="Optional API key (shared secret)")
    parser.add_argument("--install", action="store_true", help="Install as systemd service (Linux, run as root)")
    args = parser.parse_args()

    if args.install:
        if os.geteuid() != 0:
            print("--install requires root (sudo)")
            sys.exit(1)
        _install_systemd(args.port, args.key)
        return

    CrowHandler.api_key = args.key
    server = http.server.HTTPServer(("0.0.0.0", args.port), CrowHandler)
    print(f"Crow Agent {CROW_VERSION} listening on 0.0.0.0:{args.port}")
    if args.key:
        print(f"API key required: {args.key}")
    else:
        print("WARNING: No API key set — open to anyone on the network")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

