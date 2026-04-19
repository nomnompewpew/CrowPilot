from __future__ import annotations

import datetime
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..schemas import LoginRequest
from ..services.auth import get_session_user, hash_password, verify_password
from ..state import g

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def auth_login(payload: LoginRequest, response: Response) -> dict:
    if not g.db:
        raise HTTPException(status_code=503, detail="Database not ready")
    user = g.db.execute(
        "SELECT id, username, password_hash, salt, role FROM users WHERE username = ?",
        (payload.username,),
    ).fetchone()
    if not user or not verify_password(payload.password, user["salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    expires = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    ).isoformat()
    g.db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user["id"], expires),
    )
    g.db.commit()
    response.set_cookie(
        "crowpilot_session", token, httponly=True, samesite="lax", max_age=604800
    )
    return {"ok": True, "username": user["username"], "role": user["role"]}


@router.post("/logout")
def auth_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get("crowpilot_session")
    if token and g.db:
        g.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        g.db.commit()
    response.delete_cookie("crowpilot_session")
    return {"ok": True}


@router.get("/me")
def auth_me(request: Request) -> dict:
    token = request.cookies.get("crowpilot_session")
    user = get_session_user(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": user["username"], "role": user["role"]}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def auth_change_password(payload: ChangePasswordRequest, request: Request) -> dict:
    token = request.cookies.get("crowpilot_session", "")
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not verify_password(payload.current_password, user["salt"], user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    new_salt = secrets.token_hex(16)
    new_hash = hash_password(payload.new_password, new_salt)
    g.db.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
        (new_hash, new_salt, user["id"]),
    )
    g.db.commit()
    return {"ok": True}
