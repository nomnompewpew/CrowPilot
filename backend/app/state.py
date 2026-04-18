from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import deque
from typing import Any


class _AppState:
    """Mutable singleton holding all shared runtime state.

    Set fields inside the FastAPI lifespan context manager.
    Import `g` everywhere else and access g.db, g.providers, etc.
    """

    def __init__(self) -> None:
        self.db: sqlite3.Connection | None = None
        self.providers: dict[str, Any] = {}          # OpenAICompatProvider instances
        self.credential_cipher: Any | None = None    # Fernet at runtime
        self.mcp_tool_route_map: dict[str, str] = {}
        self.project_runtimes: dict[str, dict[str, Any]] = {}
        self.project_runtime_lock: threading.Lock = threading.Lock()
        # Log streaming: ring buffer holds last 500 formatted log lines.
        # log_queues is a list of asyncio.Queue objects, one per connected SSE client.
        self.log_ring: deque[str] = deque(maxlen=500)
        self.log_queues: list[asyncio.Queue[str]] = []


g = _AppState()
