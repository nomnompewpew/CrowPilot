"""
Linux + QEMU server statistics.

Collects system metrics from /proc, /sys, and the QEMU guest agent (if present).
All functions are safe to call regardless of whether the feature is available —
they return None or partial data on any error rather than raising.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Network interfaces
# ---------------------------------------------------------------------------

def _get_network_interfaces() -> list[dict]:
    """
    Return all IPv4 interfaces via `ip -4 addr show`.
    Falls back to socket-based detection if `ip` is unavailable.
    """
    ifaces: list[dict] = []
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        current_iface: str | None = None
        for line in result.stdout.splitlines():
            m_iface = re.match(r"^\d+:\s+(\S+?)[@:]?\s", line)
            if m_iface:
                current_iface = m_iface.group(1)
            m_addr = re.match(r"\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
            if m_addr and current_iface:
                ifaces.append(
                    {
                        "interface": current_iface,
                        "ip": m_addr.group(1),
                        "prefix": int(m_addr.group(2)),
                        "is_loopback": m_addr.group(1).startswith("127."),
                    }
                )
        if ifaces:
            return ifaces
    except Exception:
        pass

    # Fallback: socket hostname resolution
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            ifaces.append(
                {
                    "interface": "unknown",
                    "ip": addr,
                    "prefix": 24,
                    "is_loopback": addr.startswith("127."),
                }
            )
    except Exception:
        pass
    return ifaces


def _pick_primary_lan_ip(ifaces: list[dict]) -> str | None:
    """
    Choose the best LAN IP to advertise — prefer RFC-1918 ranges over loopback.
    Priority: 192.168.x.x > 10.x.x.x > 172.16-31.x.x > 127.x.x.x
    """
    def _score(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        parts = ip.split(".")
        if ip.startswith("172.") and len(parts) > 1 and 16 <= int(parts[1]) <= 31:
            return 2
        if ip.startswith("127."):
            return 10
        return 5  # public / link-local

    non_lo = [i for i in ifaces if not i["is_loopback"]]
    pool = non_lo or ifaces
    if not pool:
        return None
    return min(pool, key=lambda i: _score(i["ip"]))["ip"]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def _read_meminfo() -> dict:
    values: dict[str, int] = {}
    try:
        text = Path("/proc/meminfo").read_text()
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                values[key] = int(parts[1])  # always kB
    except Exception:
        return {}

    total_kb = values.get("MemTotal", 0)
    avail_kb = values.get("MemAvailable", values.get("MemFree", 0))
    used_kb = total_kb - avail_kb

    def to_mb(kb: int) -> float:
        return round(kb / 1024, 1)

    return {
        "total_mb": to_mb(total_kb),
        "available_mb": to_mb(avail_kb),
        "used_mb": to_mb(used_kb),
        "used_pct": round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        "buffers_mb": to_mb(values.get("Buffers", 0)),
        "cached_mb": to_mb(values.get("Cached", 0)),
    }


# ---------------------------------------------------------------------------
# CPU / load
# ---------------------------------------------------------------------------

def _read_cpu_info() -> dict:
    model = "Unknown"
    try:
        text = Path("/proc/cpuinfo").read_text()
        for line in text.splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass

    load_1, load_5, load_15 = 0.0, 0.0, 0.0
    try:
        parts = Path("/proc/loadavg").read_text().split()
        load_1, load_5, load_15 = float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        pass

    return {
        "count": os.cpu_count() or 1,
        "model": model,
        "load_1m": load_1,
        "load_5m": load_5,
        "load_15m": load_15,
        "arch": platform.machine(),
    }


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

def _read_disk_usage(path: str = "/") -> dict:
    try:
        usage = shutil.disk_usage(path)
        total_gb = round(usage.total / 1e9, 1)
        used_gb = round(usage.used / 1e9, 1)
        free_gb = round(usage.free / 1e9, 1)
        return {
            "path": path,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------

def _read_uptime() -> dict:
    try:
        uptime_secs = float(Path("/proc/uptime").read_text().split()[0])
        td = datetime.timedelta(seconds=int(uptime_secs))
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        human = ""
        if days:
            human += f"{days}d "
        human += f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return {"seconds": int(uptime_secs), "human": human.strip()}
    except Exception:
        return {"seconds": 0, "human": "unknown"}


# ---------------------------------------------------------------------------
# QEMU / hypervisor detection
# ---------------------------------------------------------------------------

_QEMU_GA_PATHS = [
    "/dev/virtio-ports/org.qemu.guest_agent.0",
    "/dev/vport0p1",
]


def _detect_qemu() -> dict:
    info: dict = {
        "detected": False,
        "hypervisor": None,
        "vendor": None,
        "product": None,
        "guest_agent_available": False,
        "guest_agent_path": None,
        "guest_agent_version": None,
    }

    # DMI-based detection (reliable inside KVM/QEMU VMs)
    dmi_fields = {
        "sys_vendor": "/sys/class/dmi/id/sys_vendor",
        "product_name": "/sys/class/dmi/id/product_name",
        "board_vendor": "/sys/class/dmi/id/board_vendor",
    }
    dmi: dict[str, str] = {}
    for key, path in dmi_fields.items():
        try:
            dmi[key] = Path(path).read_text(errors="replace").strip()
        except Exception:
            dmi[key] = ""

    vendor = dmi.get("sys_vendor", "")
    product = dmi.get("product_name", "")
    if "QEMU" in vendor or "QEMU" in product or "KVM" in vendor:
        info["detected"] = True
        info["hypervisor"] = "QEMU/KVM"
        info["vendor"] = vendor
        info["product"] = product
    elif "VMware" in vendor:
        info["detected"] = True
        info["hypervisor"] = "VMware"
        info["vendor"] = vendor
    elif "VirtualBox" in vendor or "innotek" in vendor:
        info["detected"] = True
        info["hypervisor"] = "VirtualBox"
        info["vendor"] = vendor

    # Fallback: check /proc/cpuinfo for QEMU virtual CPU
    if not info["detected"]:
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            if "QEMU" in cpuinfo:
                info["detected"] = True
                info["hypervisor"] = "QEMU/KVM"
        except Exception:
            pass

    # Guest agent detection
    for ga_path in _QEMU_GA_PATHS:
        if os.path.exists(ga_path):
            info["guest_agent_available"] = True
            info["guest_agent_path"] = ga_path
            # Try querying guest-info for version
            info["guest_agent_version"] = _qemu_ga_guest_info(ga_path)
            break

    return info


def _qemu_ga_guest_info(ga_path: str, timeout: float = 1.5) -> str | None:
    """
    Send `guest-info` to the QEMU guest agent character device.
    Returns version string on success, None on timeout or error.
    Uses a daemon thread to enforce the timeout safely.
    """
    result: list[str | None] = [None]

    def _run() -> None:
        try:
            request = json.dumps({"execute": "guest-info"}).encode() + b"\n"
            with open(ga_path, "r+b", buffering=0) as fd:
                fd.write(request)
                buf = b""
                for _ in range(32):  # read up to 32 chunks
                    chunk = os.read(fd.fileno(), 2048)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break
            line = buf.decode(errors="replace").strip().split("\n")[-1]
            data = json.loads(line)
            result[0] = data.get("return", {}).get("version")
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_server_stats(port: int = 8787) -> dict:
    """
    Collect and return a complete snapshot of server statistics.
    Safe to call from any async route handler (all I/O is synchronous but fast).
    """
    ifaces = _get_network_interfaces()
    primary_ip = _pick_primary_lan_ip(ifaces)

    network = {
        "hostname": socket.gethostname(),
        "interfaces": ifaces,
        "primary_lan_ip": primary_ip,
        "mcp_relay_url": f"http://{primary_ip}:{port}/mcp" if primary_ip else None,
        "ui_url": f"http://{primary_ip}:{port}" if primary_ip else None,
    }

    return {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "kernel": platform.release(),
        "platform_full": platform.platform(),
        "python_version": platform.python_version(),
        "uptime": _read_uptime(),
        "cpu": _read_cpu_info(),
        "memory": _read_meminfo(),
        "disk": _read_disk_usage("/"),
        "network": network,
        "qemu": _detect_qemu(),
    }
