from __future__ import annotations

import datetime
import threading
import uuid
from collections import deque

from fastapi import HTTPException

from ..state import g
from .projects import project_row_and_path, safe_child_path


def start_project_runtime(project_id: int, script_row: dict) -> dict:
    import subprocess

    runtime_id = str(uuid.uuid4())
    row, project_path = project_row_and_path(project_id)
    cwd = safe_child_path(project_path, script_row["relative_dir"])
    command = script_row["command"]

    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    log_buffer: deque[str] = deque(maxlen=600)

    def _capture() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                with g.project_runtime_lock:
                    if runtime_id in g.project_runtimes:
                        g.project_runtimes[runtime_id]["logs"].append(line.rstrip())
        except Exception:
            return

    thread = threading.Thread(target=_capture, daemon=True)
    thread.start()

    with g.project_runtime_lock:
        g.project_runtimes[runtime_id] = {
            "id": runtime_id,
            "project_id": project_id,
            "project_name": row["name"],
            "script_key": script_row["key"],
            "script": script_row["script"],
            "package": script_row["package"],
            "cwd": str(cwd),
            "command": command,
            "pid": proc.pid,
            "started_at": datetime.datetime.utcnow().isoformat() + "Z",
            "proc": proc,
            "logs": log_buffer,
        }
        entry = g.project_runtimes[runtime_id]

    return {
        "id": entry["id"],
        "project_id": entry["project_id"],
        "script_key": entry["script_key"],
        "script": entry["script"],
        "package": entry["package"],
        "cwd": entry["cwd"],
        "command": entry["command"],
        "pid": entry["pid"],
        "started_at": entry["started_at"],
        "running": True,
    }


def list_project_runtimes(project_id: int) -> list[dict]:
    out: list[dict] = []
    with g.project_runtime_lock:
        for runtime_id, entry in list(g.project_runtimes.items()):
            if entry["project_id"] != project_id:
                continue
            proc = entry["proc"]
            running = proc.poll() is None
            out.append(
                {
                    "id": runtime_id,
                    "project_id": project_id,
                    "script_key": entry["script_key"],
                    "script": entry["script"],
                    "package": entry["package"],
                    "cwd": entry["cwd"],
                    "command": entry["command"],
                    "pid": entry["pid"],
                    "started_at": entry["started_at"],
                    "running": running,
                    "exit_code": None if running else proc.returncode,
                }
            )
    return out


def get_runtime_logs(project_id: int, runtime_id: str, lines: int = 200) -> dict:
    with g.project_runtime_lock:
        entry = g.project_runtimes.get(runtime_id)
        if not entry or entry["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime not found")
        proc = entry["proc"]
        running = proc.poll() is None
        logs = list(entry["logs"])[-max(1, min(lines, 600)):]
        return {
            "id": runtime_id,
            "running": running,
            "exit_code": None if running else proc.returncode,
            "logs": logs,
        }


def stop_runtime(project_id: int, runtime_id: str) -> dict:
    with g.project_runtime_lock:
        entry = g.project_runtimes.get(runtime_id)
        if not entry or entry["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime not found")
        proc = entry["proc"]
        if proc.poll() is None:
            proc.terminate()
        return {"id": runtime_id, "stopped": True}
