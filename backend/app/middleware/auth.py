from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..services.auth import get_session_user

_AUTH_PUBLIC_PREFIXES = (
    "/api/auth/",
    "/api/wizard/",
    "/static/",
    "/docs",
    "/openapi",
    "/redoc",
)
_AUTH_PUBLIC_EXACT = {"/", "/favicon.ico", "/mcp"}


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_PUBLIC_EXACT or any(path.startswith(p) for p in _AUTH_PUBLIC_PREFIXES):
        return await call_next(request)
    token = request.cookies.get("crowpilot_session")
    if not token or not get_session_user(token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)
