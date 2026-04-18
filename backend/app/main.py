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
from .services.log_handler import install_log_capture
from .services.mcp import ensure_builtin_mcp_servers, normalize_existing_mcp_servers
from .services.memory import embed_worker, stop_embed_worker
from .services.providers import reload_providers_from_integrations
from .state import g

from .routers import (
    auth,
    chat,
    conversations,
    credentials,
    integrations,
    knowledge,
    mcp,
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
    g.db = get_connection(settings.db_path)
    init_db(g.db)
    normalize_existing_mcp_servers()
    ensure_builtin_mcp_servers()
    reload_providers_from_integrations()
    seed_default_user()
    # Start passive embed background worker
    _worker_task = asyncio.create_task(embed_worker())
    yield
    stop_embed_worker()
    try:
        await asyncio.wait_for(_worker_task, timeout=5.0)
    except asyncio.TimeoutError:
        pass
    if g.db:
        g.db.close()


app = FastAPI(title="CrowPilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    widgets,
    tasks,
    skills,
    zen,
    integrations,
    credentials,
    projects,
    sensitive,
]:
    app.include_router(_router_module.router)

app.include_router(wizard_router.router)
