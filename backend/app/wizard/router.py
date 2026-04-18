"""
wizard/router.py — Setup wizard backend.

Exposes:
  GET  /api/wizard/status   — run all health checks, return step results
  POST /api/wizard/complete — mark setup_complete = true for current user
"""
from __future__ import annotations

import asyncio
import subprocess

import httpx
from fastapi import APIRouter, Request

from ..config import settings
from ..services.auth import get_session_user
from ..state import g

router = APIRouter(prefix="/api/wizard", tags=["wizard"])

_DEFAULT_PASSWORD = "Di@m0nd$ky"


async def _check_local_chat() -> dict:
    base = settings.local_base_url.strip()
    if not base:
        return {"ok": False, "detail": "PANTHEON_LOCAL_BASE_URL not set"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base.rstrip('/')}/models")
            models = resp.json().get("data", [])
            name = models[0]["id"] if models else "unknown"
            return {"ok": True, "detail": f"Reachable — {name}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


async def _check_local_embed() -> dict:
    base = settings.embedding_base_url.strip()
    if not base:
        return {"ok": False, "detail": "PANTHEON_EMBEDDING_BASE_URL not set"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base.rstrip('/')}/models")
            models = resp.json().get("data", [])
            name = models[0]["id"] if models else "unknown"
            return {"ok": True, "detail": f"Reachable — {name}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _check_gh_installed() -> dict:
    try:
        result = subprocess.run(
            [settings.copilot_cli_command, "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            ver = result.stdout.strip().splitlines()[0]
            return {"ok": True, "detail": ver}
        return {"ok": False, "detail": result.stderr.strip() or "non-zero exit"}
    except FileNotFoundError:
        return {"ok": False, "detail": f"'{settings.copilot_cli_command}' not found on PATH"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _check_gh_authed() -> dict:
    try:
        result = subprocess.run(
            [settings.copilot_cli_command, "auth", "status"],
            capture_output=True, text=True, timeout=10
        )
        combined = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return {"ok": True, "detail": "Authenticated"}
        # gh auth status returns non-zero when not authed or keyring issue
        # "Active account: true" still means it works functionally
        if "Active account: true" in combined:
            return {"ok": True, "detail": "Active account found (keyring warning ignored)"}
        return {"ok": False, "detail": combined[:200]}
    except FileNotFoundError:
        return {"ok": False, "detail": "gh CLI not found"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def _check_password_changed(request: Request) -> dict:
    token = request.cookies.get("crowpilot_session", "")
    user = get_session_user(token)
    if not user:
        return {"ok": False, "detail": "Not authenticated"}
    from ..services.auth import verify_password
    still_default = verify_password(_DEFAULT_PASSWORD, user["salt"], user["password_hash"])
    if still_default:
        return {"ok": False, "detail": "Still using the default password — please change it"}
    return {"ok": True, "detail": "Password has been changed"}


def _check_first_note() -> dict:
    count = g.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    if count == 0:
        return {"ok": False, "detail": "No knowledge notes yet — save your first note in Knowledge Lab"}
    return {"ok": True, "detail": f"{count} note(s) in the knowledge base"}


@router.get("/status")
async def wizard_status(request: Request) -> dict:
    """Run all setup checks concurrently and return results."""
    chat_task, embed_task = await asyncio.gather(
        _check_local_chat(),
        _check_local_embed(),
    )
    gh_installed = _check_gh_installed()
    gh_authed = _check_gh_authed() if gh_installed["ok"] else {"ok": False, "detail": "gh CLI not installed"}
    pw_changed = _check_password_changed(request)
    first_note = _check_first_note()

    steps = [
        {"step": 1, "label": "Local chat model", "icon": "🧠", **chat_task},
        {"step": 2, "label": "Local embed model", "icon": "🔢", **embed_task},
        {"step": 3, "label": "GitHub CLI installed", "icon": "🛠", **gh_installed},
        {"step": 4, "label": "GitHub CLI authenticated", "icon": "🔑", **gh_authed},
        {"step": 5, "label": "Password changed", "icon": "🔒", **pw_changed},
        {"step": 6, "label": "First knowledge note", "icon": "📚", **first_note},
    ]

    all_ok = all(s["ok"] for s in steps)

    # Check setup_complete from DB
    token = request.cookies.get("crowpilot_session", "")
    user = get_session_user(token)
    setup_complete = bool(user and user.get("setup_complete"))

    return {
        "steps": steps,
        "all_ok": all_ok,
        "setup_complete": setup_complete,
    }


@router.post("/complete")
async def wizard_complete(request: Request) -> dict:
    """Mark setup as complete for the current user."""
    token = request.cookies.get("crowpilot_session", "")
    user = get_session_user(token)
    if not user:
        return {"ok": False, "detail": "Not authenticated"}
    g.db.execute(
        "UPDATE users SET setup_complete = 1 WHERE id = ?", (user["id"],)
    )
    g.db.commit()
    return {"ok": True}
