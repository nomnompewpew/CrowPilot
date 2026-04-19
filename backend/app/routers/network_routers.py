from __future__ import annotations

import asyncio
import json
import urllib.parse
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from ..state import g

router = APIRouter(prefix="/api/routers", tags=["network_routers"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RouterCreate(BaseModel):
    label: str
    host: str
    router_type: str = "opnsense"  # opnsense | pfsense | generic
    port: int = 443
    api_key: str | None = None
    api_secret: str | None = None
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    use_https: bool = True
    allow_writes: bool = False
    notes: str | None = None


class RouterUpdate(BaseModel):
    label: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    ssh_user: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    allow_writes: bool | None = None
    notes: str | None = None
    port: int | None = None


class RouterCommand(BaseModel):
    command: str  # for pfSense SSH exec


# ---------------------------------------------------------------------------
# OPNsense REST client
# ---------------------------------------------------------------------------

def _opnsense_base(row: dict) -> str:
    scheme = "https" if row["use_https"] else "http"
    return f"{scheme}://{row['host']}:{row['port']}/api"


def _opnsense_auth(row: dict) -> tuple[str, str] | None:
    if row.get("api_key") and row.get("api_secret"):
        return (row["api_key"], row["api_secret"])
    return None


async def _opnsense_get(row: dict, path: str) -> dict:
    url = f"{_opnsense_base(row)}/{path.lstrip('/')}"
    auth = _opnsense_auth(row)
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            resp = await client.get(url, auth=auth)
            return {"ok": True, "status_code": resp.status_code, "data": resp.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _opnsense_post(row: dict, path: str, payload: dict) -> dict:
    if not row.get("allow_writes"):
        return {"ok": False, "error": "write access not enabled for this router"}
    url = f"{_opnsense_base(row)}/{path.lstrip('/')}"
    auth = _opnsense_auth(row)
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.post(url, auth=auth, json=payload)
            return {"ok": True, "status_code": resp.status_code, "data": resp.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# pfSense SSH client (read-only shell commands)
# ---------------------------------------------------------------------------

async def _pfsense_ssh(row: dict, command: str, allow_writes: bool = False) -> dict:
    """Run a command on pfSense over SSH. Wraps in executor since paramiko is sync."""
    import paramiko  # lazy import — only needed for pfSense

    SAFE_PREFIXES = (
        "ifconfig", "netstat", "arp -a", "pfctl -s", "cat /etc/version",
        "uname", "df ", "uptime", "ps ax", "route ", "ping -c",
        "host ", "dig ", "drill ",
    )

    if not allow_writes:
        stripped = command.strip()
        if not any(stripped.startswith(p) for p in SAFE_PREFIXES):
            return {
                "ok": False,
                "error": f"command blocked in read-only mode. Allowed prefixes: {', '.join(SAFE_PREFIXES)}",
            }

    def _run() -> dict:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs: dict[str, Any] = {
                "hostname": row["host"],
                "port": 22,
                "username": row["ssh_user"] or "admin",
                "timeout": 10,
            }
            if row.get("ssh_key_path"):
                connect_kwargs["key_filename"] = row["ssh_key_path"]
            elif row.get("ssh_password"):
                connect_kwargs["password"] = row["ssh_password"]
            client.connect(**connect_kwargs)
            _, stdout, stderr = client.exec_command(command, timeout=10)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return {"ok": True, "stdout": out, "stderr": err}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            client.close()

    return await asyncio.get_event_loop().run_in_executor(None, _run)


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------

def _save_snapshot(router_id: int, snapshot_type: str, data: dict) -> None:
    g.db.execute(
        "INSERT INTO router_snapshots (router_id, snapshot_type, data_json) VALUES (?, ?, ?)",
        (router_id, snapshot_type, json.dumps(data)),
    )
    g.db.commit()


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------

@router.get("")
def list_routers() -> dict:
    rows = g.db.execute(
        "SELECT id, label, host, router_type, port, use_https, allow_writes, status, last_seen, notes, created_at FROM network_routers ORDER BY label"
    ).fetchall()
    return {"ok": True, "routers": [dict(r) for r in rows]}


@router.post("")
def add_router(req: RouterCreate) -> dict:
    g.db.execute(
        """INSERT INTO network_routers
           (label, host, router_type, port, api_key, api_secret, ssh_user,
            ssh_key_path, ssh_password, use_https, allow_writes, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (req.label, req.host, req.router_type, req.port, req.api_key,
         req.api_secret, req.ssh_user, req.ssh_key_path, req.ssh_password,
         int(req.use_https), int(req.allow_writes), req.notes),
    )
    g.db.commit()
    rid = g.db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"ok": True, "id": rid}


@router.patch("/{router_id}")
def update_router(router_id: int, req: RouterUpdate) -> dict:
    fields, vals = [], []
    for attr, col in [
        ("label", "label"), ("api_key", "api_key"), ("api_secret", "api_secret"),
        ("ssh_user", "ssh_user"), ("ssh_key_path", "ssh_key_path"),
        ("ssh_password", "ssh_password"), ("notes", "notes"), ("port", "port"),
    ]:
        v = getattr(req, attr)
        if v is not None:
            fields.append(f"{col} = ?"); vals.append(v)
    if req.allow_writes is not None:
        fields.append("allow_writes = ?"); vals.append(int(req.allow_writes))
    if not fields:
        return {"ok": False, "error": "nothing to update"}
    fields.append("updated_at = datetime('now')")
    vals.append(router_id)
    g.db.execute(f"UPDATE network_routers SET {', '.join(fields)} WHERE id = ?", vals)
    g.db.commit()
    return {"ok": True}


@router.delete("/{router_id}")
def delete_router(router_id: int) -> dict:
    g.db.execute("DELETE FROM network_routers WHERE id = ?", (router_id,))
    g.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Connectivity test
# ---------------------------------------------------------------------------

@router.post("/{router_id}/ping")
async def ping_router(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)

    if row["router_type"] == "opnsense":
        result = await _opnsense_get(row, "core/firmware/status")
    else:
        result = await _pfsense_ssh(row, "uname -a")

    status = "online" if result.get("ok") else "offline"
    g.db.execute(
        "UPDATE network_routers SET status = ?, last_seen = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (status, router_id),
    )
    g.db.commit()
    return {"ok": True, "status": status, "detail": result}


# ---------------------------------------------------------------------------
# OPNsense — read data
# ---------------------------------------------------------------------------

@router.get("/{router_id}/opnsense/interfaces")
async def opnsense_interfaces(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    data = await _opnsense_get(row, "diagnostics/interface/getInterfaceStatistics")
    if data.get("ok"):
        _save_snapshot(router_id, "interfaces", data["data"])
    return data


@router.get("/{router_id}/opnsense/leases")
async def opnsense_leases(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    data = await _opnsense_get(row, "dhcpv4/leases/searchLease")
    if data.get("ok"):
        _save_snapshot(router_id, "dhcp_leases", data["data"])
    return data


@router.get("/{router_id}/opnsense/arp")
async def opnsense_arp(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    data = await _opnsense_get(row, "diagnostics/interface/getArp")
    if data.get("ok"):
        _save_snapshot(router_id, "arp_table", data["data"])
    return data


@router.get("/{router_id}/opnsense/firewall")
async def opnsense_firewall_rules(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    data = await _opnsense_get(row, "firewall/filter/searchRule")
    if data.get("ok"):
        _save_snapshot(router_id, "firewall_rules", data["data"])
    return data


@router.get("/{router_id}/opnsense/services")
async def opnsense_services(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    data = await _opnsense_get(row, "core/service/search")
    return data


@router.get("/{router_id}/opnsense/firmware")
async def opnsense_firmware(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    return await _opnsense_get(row, "core/firmware/info")


# ---------------------------------------------------------------------------
# OPNsense — write (requires allow_writes)
# ---------------------------------------------------------------------------

@router.post("/{router_id}/opnsense/firewall/apply")
async def opnsense_apply_firewall(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    return await _opnsense_post(dict(row), "firewall/filter/apply", {})


@router.post("/{router_id}/opnsense/raw")
async def opnsense_raw(router_id: int, path: str, payload: dict = {}) -> dict:
    """Call any OPNsense API endpoint directly. GET if no payload, POST if payload."""
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    if payload:
        return await _opnsense_post(row, path, payload)
    return await _opnsense_get(row, path)


# ---------------------------------------------------------------------------
# pfSense — SSH commands
# ---------------------------------------------------------------------------

@router.post("/{router_id}/pfsense/exec")
async def pfsense_exec(router_id: int, req: RouterCommand) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    row = dict(row)
    if row["router_type"] != "pfsense":
        return {"ok": False, "error": "this router is not pfSense type"}
    return await _pfsense_ssh(row, req.command, allow_writes=bool(row["allow_writes"]))


@router.get("/{router_id}/pfsense/interfaces")
async def pfsense_interfaces(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    result = await _pfsense_ssh(dict(row), "ifconfig")
    if result.get("ok"):
        _save_snapshot(router_id, "interfaces", {"raw": result["stdout"]})
    return result


@router.get("/{router_id}/pfsense/arp")
async def pfsense_arp(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    result = await _pfsense_ssh(dict(row), "arp -a")
    if result.get("ok"):
        _save_snapshot(router_id, "arp_table", {"raw": result["stdout"]})
    return result


@router.get("/{router_id}/pfsense/firewall")
async def pfsense_firewall(router_id: int) -> dict:
    row = g.db.execute("SELECT * FROM network_routers WHERE id = ?", (router_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    result = await _pfsense_ssh(dict(row), "pfctl -s rules")
    if result.get("ok"):
        _save_snapshot(router_id, "firewall_rules", {"raw": result["stdout"]})
    return result


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

@router.get("/{router_id}/snapshots")
def list_snapshots(router_id: int, snapshot_type: str | None = None) -> dict:
    if snapshot_type:
        rows = g.db.execute(
            "SELECT id, snapshot_type, captured_at FROM router_snapshots WHERE router_id = ? AND snapshot_type = ? ORDER BY captured_at DESC LIMIT 50",
            (router_id, snapshot_type),
        ).fetchall()
    else:
        rows = g.db.execute(
            "SELECT id, snapshot_type, captured_at FROM router_snapshots WHERE router_id = ? ORDER BY captured_at DESC LIMIT 50",
            (router_id,),
        ).fetchall()
    return {"ok": True, "snapshots": [dict(r) for r in rows]}


@router.get("/{router_id}/snapshots/{snapshot_id}")
def get_snapshot(router_id: int, snapshot_id: int) -> dict:
    row = g.db.execute(
        "SELECT * FROM router_snapshots WHERE id = ? AND router_id = ?",
        (snapshot_id, router_id),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "not found"}
    return {"ok": True, "snapshot": dict(row)}
