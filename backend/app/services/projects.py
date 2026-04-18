from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from ..state import g
from ..utils import slugify_name
from .serializers import serialize_project_row


def projects_root() -> Path:
    root = Path(settings.projects_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_child_path(base: Path, relative: str) -> Path:
    child = (base / (relative or "")).resolve()
    if child == base or base in child.parents:
        return child
    raise HTTPException(status_code=400, detail="Path escapes the project root")


def project_row_and_path(project_id: int):
    row = g.db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project_path = Path(row["path"]).resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Project path is missing or not a directory")
    return row, project_path


def next_project_slug(base_name: str) -> str:
    base_slug = slugify_name(base_name, "project")
    root = projects_root()
    for idx in range(0, 200):
        candidate = base_slug if idx == 0 else f"{base_slug}-{idx + 1}"
        exists = g.db.execute("SELECT 1 FROM projects WHERE slug = ?", (candidate,)).fetchone()
        if not exists and not (root / candidate).exists():
            return candidate
    raise HTTPException(status_code=409, detail="Unable to generate unique project slug")


def project_tree_entry(path: Path, project_root: Path) -> dict:
    rel = str(path.relative_to(project_root)) if path != project_root else "."
    stat = path.stat()
    return {
        "name": path.name if path != project_root else project_root.name,
        "relative_path": rel,
        "is_dir": path.is_dir(),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def upsert_project_from_path(path_text: str, *, name: str | None = None, kind: str = "workspace") -> dict:
    project_path = Path(path_text).expanduser().resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Selected path must be an existing directory")

    row = g.db.execute("SELECT * FROM projects WHERE path = ?", (str(project_path),)).fetchone()
    project_name = (name or project_path.name or "workspace").strip()
    if row:
        g.db.execute(
            "UPDATE projects SET name = ?, kind = ?, last_opened_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (project_name, kind, row["id"]),
        )
        g.db.commit()
        updated = g.db.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone()
        return serialize_project_row(updated)

    slug = next_project_slug(project_name)
    cur = g.db.execute(
        """
        INSERT INTO projects(name, slug, path, kind, status, stack_json, last_opened_at)
        VALUES (?, ?, ?, ?, 'active', '{}', datetime('now'))
        """,
        (project_name, slug, str(project_path), kind),
    )
    g.db.commit()
    created = g.db.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize_project_row(created)


def discover_projects_from_root() -> list[dict]:
    root = projects_root()
    imported: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        imported.append(upsert_project_from_path(str(child), name=child.name, kind="workspace"))
    return imported


def open_native_directory_picker() -> str | None:
    system = platform.system().lower()
    try:
        if system == "linux":
            if shutil.which("zenity"):
                proc = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title=Select CrowPilot Workspace Folder"],
                    capture_output=True, text=True, check=False,
                )
                if proc.returncode == 0:
                    return proc.stdout.strip() or None
            if shutil.which("kdialog"):
                proc = subprocess.run(
                    ["kdialog", "--getexistingdirectory", str(projects_root())],
                    capture_output=True, text=True, check=False,
                )
                if proc.returncode == 0:
                    return proc.stdout.strip() or None
        elif system == "darwin":
            proc = subprocess.run(
                ["osascript", "-e",
                 'set theFolder to choose folder with prompt "Select CrowPilot Workspace Folder"',
                 "-e", "POSIX path of theFolder"],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip() or None
        elif system == "windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$f.Description='Select CrowPilot Workspace Folder';"
                "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip() or None
    except Exception:
        return None
    return None


def detect_package_manager(folder: Path) -> str:
    if (folder / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (folder / "yarn.lock").exists():
        return "yarn"
    if (folder / "bun.lockb").exists() or (folder / "bun.lock").exists():
        return "bun"
    return "npm"


def command_for_script(manager: str, script_name: str) -> list[str]:
    if manager == "pnpm":
        return ["pnpm", "run", script_name]
    if manager == "yarn":
        return ["yarn", script_name]
    if manager == "bun":
        return ["bun", "run", script_name]
    return ["npm", "run", script_name]


def discover_project_scripts(project_path: Path) -> list[dict]:
    import json

    package_files: list[Path] = []
    max_depth = 4
    for root, dirs, files in os.walk(project_path):
        current = Path(root)
        rel_depth = len(current.relative_to(project_path).parts)
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", ".next", "dist", "build", ".turbo"}]
        if rel_depth > max_depth:
            dirs[:] = []
            continue
        if "package.json" in files:
            package_files.append(current / "package.json")

    results: list[dict] = []
    for pkg in sorted(package_files):
        try:
            payload = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            continue
        scripts = payload.get("scripts") or {}
        if not isinstance(scripts, dict):
            continue
        manager = detect_package_manager(pkg.parent)
        rel_dir = str(pkg.parent.relative_to(project_path)) if pkg.parent != project_path else "."
        package_name = payload.get("name") or rel_dir
        for script_name, raw_cmd in scripts.items():
            key = f"{rel_dir}::{script_name}"
            results.append(
                {
                    "key": key,
                    "package": package_name,
                    "relative_dir": rel_dir,
                    "script": script_name,
                    "raw": str(raw_cmd),
                    "package_manager": manager,
                    "command": command_for_script(manager, script_name),
                }
            )
    return results


def detect_copilot_cli() -> dict:
    from ..config import settings as cfg

    configured = (cfg.copilot_cli_command or "gh").strip()
    parts = shlex.split(configured) if configured else ["gh"]
    exe = parts[0] if parts else "gh"
    if shutil.which(exe) is None:
        return {
            "available": False,
            "configured": configured,
            "reason": f"Executable not found in PATH: {exe}",
        }
    return {"available": True, "configured": configured, "parts": parts, "exe": exe}


def build_copilot_cli_args(prompt: str, target: str) -> list[str]:
    info = detect_copilot_cli()
    if not info.get("available"):
        raise HTTPException(status_code=400, detail=info.get("reason") or "Copilot CLI is unavailable")

    parts: list[str] = info["parts"]
    exe = info["exe"]
    if exe == "gh":
        if target == "shell":
            return parts + ["copilot", "suggest", "-t", "shell", prompt]
        return parts + ["copilot", "explain", prompt]
    if exe == "copilot":
        return parts + [prompt]
    return parts + [prompt]
