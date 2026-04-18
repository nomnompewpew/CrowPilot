"""
Logging handler that captures all Python log records into the AppState ring buffer
and fans them out to all active SSE log-stream clients.

Install once in lifespan:
    from .services.log_handler import install_log_capture
    install_log_capture()
"""
from __future__ import annotations

import logging

from ..state import g


class _RingBufferHandler(logging.Handler):
    """Thread-safe logging.Handler that feeds g.log_ring and g.log_queues."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()

        g.log_ring.append(line)

        # Fan out to all connected SSE clients (put_nowait is safe from any thread).
        dead: list = []
        for q in g.log_queues:
            try:
                q.put_nowait(line)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                g.log_queues.remove(q)
            except ValueError:
                pass


_HANDLER: _RingBufferHandler | None = None
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def install_log_capture(level: int = logging.DEBUG) -> None:
    """Attach the ring-buffer handler to the root logger. Idempotent."""
    global _HANDLER
    if _HANDLER is not None:
        return
    _HANDLER = _RingBufferHandler()
    _HANDLER.setFormatter(_FORMATTER)
    _HANDLER.setLevel(level)
    root = logging.getLogger()
    root.addHandler(_HANDLER)
    # Ensure the root logger level doesn't swallow records we care about.
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
