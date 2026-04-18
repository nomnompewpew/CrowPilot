from __future__ import annotations

import json
import re
import socket
import subprocess


def decode_json_field(raw: str | None, fallback):
    """Safely parse a JSON column value, returning fallback on error."""
    if raw is None or not raw.strip():
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def slugify_name(value: str, fallback: str) -> str:
    """Convert an arbitrary string to a lowercase slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:64] or fallback


def discover_local_ipv4() -> list[str]:
    """
    Return all local non-loopback IPv4 addresses via `ip addr`, falling back to
    socket-based hostname resolution.  LAN addresses (192.168/10/172.16-31) come
    first so callers that take [0] get the most useful address.
    """
    hosts: set[str] = set()

    # Primary: parse `ip -4 addr show`
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        for line in result.stdout.splitlines():
            m = re.match(r"\s+inet\s+(\d+\.\d+\.\d+\.\d+)/\d+", line)
            if m:
                hosts.add(m.group(1))
    except Exception:
        pass

    # Fallback: socket
    if not hosts:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addr = info[4][0]
                if addr:
                    hosts.add(addr)
        except Exception:
            pass

    hosts.add("127.0.0.1")

    def _lan_priority(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        parts = ip.split(".")
        if ip.startswith("172.") and len(parts) > 1 and 16 <= int(parts[1]) <= 31:
            return 2
        if ip.startswith("127."):
            return 10
        return 5

    return sorted(hosts, key=_lan_priority)
