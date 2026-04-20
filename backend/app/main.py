from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import get_connection, init_db
from .middleware.auth import auth_middleware
from .services.auth import seed_default_user
from .services.agent_workspace import ensure_agent_workspace
from .services.log_handler import install_log_capture
from .services.copilot_session_watcher import session_watcher_task
from .services.mcp import ensure_builtin_mcp_servers, normalize_existing_mcp_servers, import_vscode_mcp_servers
from .services.memory import embed_worker, stop_embed_worker
from .services.providers import reload_providers_from_integrations
from .state import g
from .utils import discover_local_ipv4

from .routers import (
    auth,
    chat,
    conversations,
    copilot_history,
    credentials,
    db_connections,
    integrations,
    knowledge,
    lan,
    mcp,
    network_routers,
    nomad,
    projects,
    sensitive,
    skills,
    system,
    tasks,
    widgets,
    zen,
)
from .wizard import router as wizard_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    install_log_capture()
    ensure_agent_workspace()
    g.db = get_connection(settings.db_path)
    init_db(g.db)
    normalize_existing_mcp_servers()
    ensure_builtin_mcp_servers()
    import_vscode_mcp_servers()
    reload_providers_from_integrations()
    seed_default_user()
    # Start passive embed background worker
    _worker_task = asyncio.create_task(embed_worker())
    # Start background watcher (handles initial scan + periodic re-scans)
    _watcher_task = asyncio.create_task(session_watcher_task())
    yield
    stop_embed_worker()
    try:
        await asyncio.wait_for(_worker_task, timeout=5.0)
    except asyncio.TimeoutError:
        pass
    if g.db:
        g.db.close()


app = FastAPI(title="CrowPilot API", lifespan=lifespan)

# ── CORS: allow only the server itself and VS Code webviews ───────────────────
# "vscode-webview://" is the origin of VS Code's webview panel (local installs).
# For remote tunnel access, the tunnel proxy rewrites origins — we add the
# loopback/LAN origins so the browser-side UI still works when accessed directly.
_cors_origins = [
    f"http://127.0.0.1:{settings.port}",
    f"http://localhost:{settings.port}",
    "vscode-webview://",            # VS Code webview panels
    "vscode-file://vscode-app",     # VS Code desktop file origin
]
# Also allow LAN IPs so you can open the UI from a phone/tablet on the same network
for _lan_ip in discover_local_ipv4():
    _cors_origins.append(f"http://{_lan_ip}:{settings.port}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://[a-zA-Z0-9\-]+\.tunnel\.vscode\.dev",  # VS Code remote tunnels
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
)

app.middleware("http")(auth_middleware)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(static_dir / "crowpilot-favicon.ico", media_type="image/x-icon")


for _router_module in [
    auth,
    system,
    conversations,
    chat,
    knowledge,
    mcp,
    nomad,
    db_connections,
    widgets,
    tasks,
    skills,
    zen,
    integrations,
    credentials,
    projects,
    sensitive,
    copilot_history,
    lan,
    network_routers,
]:
    app.include_router(_router_module.router)

app.include_router(wizard_router.router)
