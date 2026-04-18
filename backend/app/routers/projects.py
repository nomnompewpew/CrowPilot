from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import (
    ProjectCommandRequest,
    ProjectCopilotCliRequest,
    ProjectCreateRequest,
    ProjectImportRequest,
    ProjectMkdirRequest,
    ProjectPreviewUpdateRequest,
    ProjectScriptRunRequest,
)
from ..services.project_runtime import (
    get_runtime_logs,
    list_project_runtimes,
    start_project_runtime,
    stop_runtime,
)
from ..services.projects import (
    build_copilot_cli_args,
    detect_copilot_cli,
    discover_project_scripts,
    discover_projects_from_root,
    next_project_slug,
    open_native_directory_picker,
    project_row_and_path,
    project_tree_entry,
    projects_root,
    safe_child_path,
    upsert_project_from_path,
)
from ..services.serializers import serialize_project_row
from ..state import g
from ..utils import discover_local_ipv4

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/capabilities")
def project_capabilities() -> dict:
    cli = detect_copilot_cli()
    system = platform.system().lower()
    picker_available = False
    if system == "linux":
        picker_available = bool(shutil.which("zenity") or shutil.which("kdialog"))
    elif system in ("darwin", "windows"):
        picker_available = True
    return {
        "projects_root": str(projects_root()),
        "copilot_cli": cli,
        "supported_kinds": ["app", "website", "service", "library", "workspace"],
        "folder_picker_available": picker_available,
        "preview_allowed_hosts": ["localhost"] + discover_local_ipv4(),
    }


@router.get("")
def list_projects() -> list[dict]:
    rows = g.db.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [serialize_project_row(r) for r in rows]


@router.post("/discover")
def discover_projects() -> dict:
    imported = discover_projects_from_root()
    return {"imported": imported, "count": len(imported), "root": str(projects_root())}


@router.post("")
def create_project(payload: ProjectCreateRequest) -> dict:
    root = projects_root()
    slug = next_project_slug(payload.name)
    project_path = (root / slug).resolve()
    project_path.mkdir(parents=True, exist_ok=False)

    cur = g.db.execute(
        """
        INSERT INTO projects(name, slug, path, kind, status, stack_json, last_opened_at)
        VALUES (?, ?, ?, ?, 'active', ?, datetime('now'))
        """,
        (payload.name.strip(), slug, str(project_path), payload.kind, json.dumps(payload.stack or {})),
    )
    g.db.commit()
    row = g.db.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize_project_row(row)


@router.post("/import")
def import_project(payload: ProjectImportRequest) -> dict:
    return upsert_project_from_path(payload.path, name=payload.name, kind=payload.kind)


@router.post("/browse")
def browse_and_import_project() -> dict:
    selected = open_native_directory_picker()
    if not selected:
        raise HTTPException(status_code=400, detail="No folder selected")
    project = upsert_project_from_path(selected, kind="workspace")
    return {"selected_path": selected, "project": project}


@router.get("/{project_id}")
def get_project(project_id: int) -> dict:
    row, _ = project_row_and_path(project_id)
    g.db.execute(
        "UPDATE projects SET last_opened_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (project_id,),
    )
    g.db.commit()
    return serialize_project_row(row)


@router.patch("/{project_id}/preview")
def update_project_preview(project_id: int, payload: ProjectPreviewUpdateRequest) -> dict:
    row, _ = project_row_and_path(project_id)
    g.db.execute(
        "UPDATE projects SET dev_url = ?, updated_at = datetime('now') WHERE id = ?",
        ((payload.dev_url or "").strip() or None, project_id),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return serialize_project_row(updated or row)


@router.get("/{project_id}/scripts")
def get_project_scripts(project_id: int) -> dict:
    _, project_path = project_row_and_path(project_id)
    scripts = discover_project_scripts(project_path)
    return {"project_id": project_id, "scripts": scripts}


@router.post("/{project_id}/scripts/run")
def run_project_script(project_id: int, payload: ProjectScriptRunRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(
            status_code=403,
            detail="System access is disabled. Set allow_system_access=true to run scripts.",
        )
    _, project_path = project_row_and_path(project_id)
    scripts = discover_project_scripts(project_path)
    script_row = next((s for s in scripts if s["key"] == payload.script_key), None)
    if not script_row:
        raise HTTPException(status_code=404, detail="Script not found")
    runtime = start_project_runtime(project_id, script_row)
    g.db.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    g.db.commit()
    return runtime


@router.get("/{project_id}/runtimes")
def list_runtimes(project_id: int) -> dict:
    project_row_and_path(project_id)
    return {"project_id": project_id, "runtimes": list_project_runtimes(project_id)}


@router.get("/{project_id}/runtimes/{runtime_id}/logs")
def get_runtime_logs_endpoint(project_id: int, runtime_id: str, lines: int = 200) -> dict:
    project_row_and_path(project_id)
    return get_runtime_logs(project_id, runtime_id, lines=lines)


@router.post("/{project_id}/runtimes/{runtime_id}/stop")
def stop_runtime_endpoint(project_id: int, runtime_id: str) -> dict:
    project_row_and_path(project_id)
    return stop_runtime(project_id, runtime_id)


@router.get("/{project_id}/tree")
def get_project_tree(
    project_id: int,
    relative_path: str = ".",
    depth: int = 1,
    limit: int = 200,
) -> dict:
    _, project_path = project_row_and_path(project_id)
    depth = max(1, min(depth, 4))
    limit = max(1, min(limit, 1000))

    start_path = safe_child_path(project_path, relative_path)
    if not start_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not start_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: list[dict] = []

    def walk(current: Path, level: int) -> None:
        if level > depth or len(entries) >= limit:
            return
        for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if len(entries) >= limit:
                return
            rel = child.relative_to(project_path)
            entries.append(
                {
                    **project_tree_entry(child, project_path),
                    "depth": level,
                    "parent": str(rel.parent) if str(rel.parent) != "." else ".",
                }
            )
            if child.is_dir() and level < depth:
                walk(child, level + 1)

    walk(start_path, 1)
    return {
        "project_id": project_id,
        "root": str(project_path),
        "relative_path": str(start_path.relative_to(project_path)) if start_path != project_path else ".",
        "entries": entries,
    }


@router.post("/{project_id}/mkdir")
def create_project_directory(project_id: int, payload: ProjectMkdirRequest) -> dict:
    _, project_path = project_row_and_path(project_id)
    target = safe_child_path(project_path, payload.relative_path)
    target.mkdir(parents=True, exist_ok=True)
    g.db.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    g.db.commit()
    return {
        "project_id": project_id,
        "created": True,
        "relative_path": str(target.relative_to(project_path)),
    }


@router.post("/{project_id}/run-command")
def run_project_command(project_id: int, payload: ProjectCommandRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(
            status_code=403,
            detail="System access is disabled. Set allow_system_access=true to run commands.",
        )
    _, project_path = project_row_and_path(project_id)
    args = shlex.split(payload.command)
    if not args:
        raise HTTPException(status_code=400, detail="Command is empty")
    try:
        result = subprocess.run(
            args,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=payload.timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=408, detail=f"Command timed out after {payload.timeout_sec}s") from exc
    g.db.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    g.db.commit()
    return {
        "project_id": project_id,
        "cwd": str(project_path),
        "command": payload.command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@router.post("/{project_id}/copilot-cli")
def run_project_copilot_cli(project_id: int, payload: ProjectCopilotCliRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(
            status_code=403,
            detail="System access is disabled. Set allow_system_access=true to run Copilot CLI.",
        )
    _, project_path = project_row_and_path(project_id)
    args = build_copilot_cli_args(payload.prompt, payload.target)
    try:
        result = subprocess.run(
            args,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=payload.timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=408, detail=f"Copilot CLI timed out after {payload.timeout_sec}s") from exc
    g.db.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    g.db.commit()
    return {
        "project_id": project_id,
        "cwd": str(project_path),
        "command": args,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@router.get("/{project_id}/context-summary")
def get_project_context_summary(project_id: int) -> dict:
    _, project_path = project_row_and_path(project_id)
    parts: list[str] = []

    for readme in ("README.md", "README.txt", "README", "readme.md"):
        p = project_path / readme
        if p.exists() and p.is_file():
            try:
                parts.append(f"## {readme}\n{p.read_text(encoding='utf-8', errors='replace')[:3000]}")
            except Exception:
                pass
            break

    pkg = project_path / "package.json"
    if pkg.exists() and pkg.is_file():
        try:
            raw = json.loads(pkg.read_text(encoding="utf-8"))
            keys = ("name", "version", "description", "scripts", "dependencies", "devDependencies")
            essential = {k: raw[k] for k in keys if k in raw}
            parts.append(f"## package.json\n{json.dumps(essential, indent=2)[:2000]}")
        except Exception:
            pass

    SKIP = {"node_modules", ".git", "__pycache__", "dist", "build", ".next", ".turbo", "coverage"}
    tree_lines: list[str] = []
    try:
        for child in sorted(project_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith(".") or child.name in SKIP:
                continue
            tree_lines.append(f"{'📁' if child.is_dir() else '📄'} {child.name}")
            if child.is_dir() and len(tree_lines) < 60:
                try:
                    for sub in sorted(child.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:10]:
                        if not sub.name.startswith(".") and sub.name not in SKIP:
                            tree_lines.append(f"  {'📁' if sub.is_dir() else '📄'} {sub.name}")
                except PermissionError:
                    pass
    except Exception:
        pass

    parts.append(f"## File Structure\n{chr(10).join(tree_lines[:80])}")
    context = "\n\n".join(parts)
    return {"project_id": project_id, "path": str(project_path), "context": context}
