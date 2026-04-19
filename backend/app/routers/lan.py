from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from datetime import datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from ..state import g

router = APIRouter(prefix="/api/lan", tags=["lan"])

_CROW_PORT = 8788
_PROBE_TIMEOUT = 1.5
_PING_TIMEOUT = 0.8


class DeviceCreate(BaseModel):
    label: str
    ip: str
    port: int = _CROW_PORT
    api_key: str | None = None
    notes: str | None = None
    auto_harvest: bool = False


class DeviceUpdate(BaseModel):
    label: str | None = None
    api_key: str | None = None
    notes: str | None = None
    auto_harvest: bool | None = None
    port: int | None = None


def _crow_headers(api_key: str | None) -> dict:
    return {"X-Crow-Key": api_key} if api_key else {}


async def _probe_crow(ip: str, port: int, api_key: str | None = None) -> dict | None:
    url = f"http://{ip}:{port}/health"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers=_crow_headers(api_key))
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


async def _fetch_crow(ip: str, port: int, api_key: str | None, endpoint: str) -> dict:
    url = f"http://{ip}:{port}/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_crow_headers(api_key))
            return resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _local_subnet() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        parts = ip.rsplit(".", 1)
        return f"{parts[0]}.0/24"
    except Exception:
        return None


def _read_arp_table() -> list[dict]:
    results = []
    try:
        with open("/proc/net/arp") as f:
            lines = f.readlines()[1:]
        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            ip, mac = parts[0], parts[3]
            if mac == "00:00:00:00:00:00":
                continue
            results.append({"ip": ip, "mac": mac})
    except Exception:
        pass
    return results


async def _ping_host(ip: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(int(_PING_TIMEOUT * 1000)), ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_PING_TIMEOUT + 0.5)
        return proc.returncode == 0
    except Exception:
        return False


async def _scan_subnet(subnet: str) -> list[dict]:
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    hosts = list(network.hosts())[:254]
    results_raw = await asyncio.gather(*[_ping_host(str(h)) for h in hosts])
    return [{"ip": str(h)} for h, alive in zip(hosts, results_raw) if alive]


@router.get("/devices")
def list_devices() -> dict:
    rows = g.db.execute("SELECT * FROM lan_devices ORDER BY label").fetchall()
    return {"ok": True, "devices": [dict(r) for r in rows]}


@router.post("/devices")
def add_device(req: DeviceCreate) -> dict:
    g.db.execute(
        "INSERT INTO lan_devices (label, ip, port, api_key, notes, auto_harvest) VALUES (?, ?, ?, ?, ?, ?)",
        (req.label, req.ip, req.port, req.api_key, req.notes, int(req.auto_harvest)),
    )
    g.db.commit()
    device_id = g.db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"ok": True, "id": device_id}


@router.patch("/devices/{device_id}")
def update_device(device_id: int, req: DeviceUpdate) -> dict:
    fields, vals = [], []
    if req.label is not None:
        fields.append("label = ?"); vals.append(req.label)
    if req.api_key is not None:
        fields.append("api_key = ?"); vals.append(req.api_key)
    if req.notes is not None:
        fields.append("notes = ?"); vals.append(req.notes)
    if req.auto_harvest is not None:
        fields.append("auto_harvest = ?"); vals.append(int(req.auto_harvest))
    if req.port is not None:
        fields.append("port = ?"); vals.append(req.port)
    if not fields:
        return {"ok": False, "error": "nothing to update"}
    fields.append("updated_at = datetime('now')")
    vals.append(device_id)
    g.db.execute(f"UPDATE lan_devices SET {', '.join(fields)} WHERE id = ?", vals)
    g.db.commit()
    return {"ok": True}


@router.delete("/devices/{device_id}")
def delete_device(device_id: int) -> dict:
    g.db.execute("DELETE FROM lan_devices WHERE id = ?", (device_id,))
    g.db.commit()
    return {"ok": True}


@router.post("/devices/{device_id}/ping")
async def ping_device(device_id: int) -> dict:
    row = g.db.execute("SELECT * FROM lan_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "device not found"}
    row = dict(row)
    result = await _probe_crow(row["ip"], row["port"], row["api_key"])
    status = "online" if result else "offline"
    now = datetime.utcnow().isoformat()
    g.db.execute(
        "UPDATE lan_devices SET status = ?, last_seen = ?, updated_at = datetime('now') WHERE id = ?",
        (status, now if result else row.get("last_seen"), device_id),
    )
    g.db.commit()
    return {"ok": True, "status": status, "response": result}


@router.get("/devices/{device_id}/info")
async def device_info(device_id: int) -> dict:
    row = g.db.execute("SELECT * FROM lan_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "device not found"}
    row = dict(row)
    data = await _fetch_crow(row["ip"], row["port"], row["api_key"], "/info")
    if data.get("ok"):
        info = data.get("info", {})
        g.db.execute(
            "UPDATE lan_devices SET info_json = ?, hostname = ?, platform = ?, status = 'online', last_seen = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (json.dumps(info), info.get("hostname"), info.get("platform"), device_id),
        )
        g.db.commit()
    return data


@router.get("/devices/{device_id}/copilot")
async def device_copilot(device_id: int) -> dict:
    row = g.db.execute("SELECT * FROM lan_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "device not found"}
    return await _fetch_crow(dict(row)["ip"], dict(row)["port"], dict(row)["api_key"], "/copilot")


@router.get("/devices/{device_id}/extensions")
async def device_extensions(device_id: int) -> dict:
    row = g.db.execute("SELECT * FROM lan_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "device not found"}
    return await _fetch_crow(dict(row)["ip"], dict(row)["port"], dict(row)["api_key"], "/extensions")


@router.get("/devices/{device_id}/ls")
async def device_ls(device_id: int, path: str = "~") -> dict:
    row = g.db.execute("SELECT * FROM lan_devices WHERE id = ?", (device_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "device not found"}
    return await _fetch_crow(dict(row)["ip"], dict(row)["port"], dict(row)["api_key"], f"/ls?path={path}")


@router.post("/scan")
async def scan_lan(subnet: str | None = None) -> dict:
    arp_hosts = _read_arp_table()
    arp_by_ip = {h["ip"]: h for h in arp_hosts}

    subnet = subnet or _local_subnet()
    if subnet:
        swept = await _scan_subnet(subnet)
        for h in swept:
            if h["ip"] not in arp_by_ip:
                arp_hosts.append(h)
                arp_by_ip[h["ip"]] = h

    async def _probe_and_record(host: dict) -> dict:
        ip = host["ip"]
        crow = await _probe_crow(ip, _CROW_PORT)
        has_agent = crow is not None
        hostname = None
        try:
            hostname = await asyncio.get_event_loop().run_in_executor(
                None, lambda: socket.gethostbyaddr(ip)[0]
            )
        except Exception:
            pass
        if crow and crow.get("hostname"):
            hostname = hostname or crow["hostname"]
        result = {
            "ip": ip,
            "mac": host.get("mac"),
            "hostname": hostname,
            "has_crow_agent": has_agent,
            "crow_info": crow,
        }
        g.db.execute(
            "INSERT OR REPLACE INTO lan_scan_results (ip, mac, hostname, has_crow_agent) VALUES (?, ?, ?, ?)",
            (ip, host.get("mac"), hostname, int(has_agent)),
        )
        g.db.commit()
        return result

    results = await asyncio.gather(*[_probe_and_record(h) for h in arp_hosts])
    return {
        "ok": True,
        "subnet": subnet,
        "total_found": len(results),
        "crow_agents": sum(1 for r in results if r["has_crow_agent"]),
        "devices": sorted(results, key=lambda r: r["ip"]),
    }


@router.get("/scan/history")
def scan_history() -> dict:
    rows = g.db.execute(
        "SELECT * FROM lan_scan_results ORDER BY scanned_at DESC LIMIT 200"
    ).fetchall()
    return {"ok": True, "results": [dict(r) for r in rows]}
