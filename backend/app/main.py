from __future__ import annotations

import asyncio
import datetime
import json
import os
import platform
import re
import shlex
import shutil
import sqlite3
import socket
import subprocess
import threading
import uuid
import webbrowser
import zlib
from base64 import b64encode
from contextlib import asynccontextmanager
from collections import deque
from io import StringIO
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .chunking import split_into_chunks
from .config import settings
from .db import get_connection, init_db, rows_to_dicts
from .providers import OpenAICompatProvider, ProviderConfig
from .schemas import (
    AddNoteRequest,
    AutomationTaskCreateRequest,
    AutomationTaskUpdateRequest,
    ChatRequest,
    CopilotTaskCreateRequest,
    CopilotTaskUpdateRequest,
    ConversationOut,
    ConversationUpdateRequest,
    ConnectorLaunchRequest,
    CredentialCreateRequest,
    CredentialEnvImportRequest,
    CredentialUpdateRequest,
    CreateConversationRequest,
    IntegrationCreateRequest,
    IntegrationUpdateRequest,
    McpOnboardRequest,
    McpServerCreateRequest,
    McpServerUpdateRequest,
    MessageOut,
    ProjectCommandRequest,
    ProjectCopilotCliRequest,
    ProjectCreateRequest,
    ProjectImportRequest,
    ProjectMkdirRequest,
    ProjectPreviewUpdateRequest,
    ProjectScriptRunRequest,
    SearchNotesRequest,
    SensitiveRedactApplyRequest,
    SensitiveRedactPreviewRequest,
    SkillCreateRequest,
    SkillUpdateRequest,
    WidgetCreateRequest,
    WidgetUpdateRequest,
    ZenActionRequest,
)


DB_CONN: sqlite3.Connection | None = None
PROVIDERS: dict[str, OpenAICompatProvider] = {}
CREDENTIAL_CIPHER: Fernet | None = None
MCP_TOOL_ROUTE_MAP: dict[str, str] = {}
PROJECT_RUNTIMES: dict[str, dict[str, Any]] = {}
PROJECT_RUNTIME_LOCK = threading.Lock()

CRED_REF_PATTERN = re.compile(r"^\{\{cred:([^}]+)\}\}$")


SENSITIVE_PATTERNS = {
    "OPENAI_KEY": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    "AWS_ACCESS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "GENERIC_SECRET": re.compile(r"\b(secret|token|api[_-]?key|password)\s*[:=]\s*['\"]?([^\s'\",;]+)", re.IGNORECASE),
}


MCP_ONBOARDING_CATALOG = {
    "github": {
        "name": "github-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @modelcontextprotocol/server-github",
        "args": [],
        "env": {"GITHUB_TOKEN": "<required>"},
        "docs": [
            "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
            "https://modelcontextprotocol.io",
        ],
        "notes": "Requires a GitHub token with scopes matching requested operations.",
    },
    "stripe": {
        "name": "stripe-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @stripe/mcp",
        "args": [],
        "env": {"STRIPE_API_KEY": "<required>"},
        "docs": [
            "https://docs.stripe.com",
            "https://modelcontextprotocol.io",
        ],
        "notes": "Use restricted Stripe keys where possible.",
    },
    "cloudflare": {
        "name": "cloudflare-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @cloudflare/mcp-server",
        "args": [],
        "env": {"CLOUDFLARE_API_TOKEN": "<required>"},
        "docs": [
            "https://developers.cloudflare.com",
            "https://modelcontextprotocol.io",
        ],
        "notes": "Token should be scoped to required Cloudflare resources.",
    },
    "astro": {
        "name": "astro-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @astrojs/mcp-server",
        "args": [],
        "env": {},
        "docs": [
            "https://docs.astro.build",
            "https://modelcontextprotocol.io",
        ],
        "notes": "May require project-local context when used for code operations.",
    },
}


BUILTIN_MCP_SERVERS = [
    {
        "name": "github-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @modelcontextprotocol/server-github",
        "args": [],
        "env": {"GITHUB_TOKEN": "<required>"},
    },
    {
        "name": "filesystem-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @modelcontextprotocol/server-filesystem",
        "args": [str(Path(settings.projects_root).resolve())],
        "env": {},
    },
    {
        "name": "fetch-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @modelcontextprotocol/server-fetch",
        "args": [],
        "env": {},
    },
    {
        "name": "playwright-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @playwright/mcp",
        "args": [],
        "env": {},
    },
    {
        "name": "astro-mcp",
        "transport": "stdio",
        "url": None,
        "command": "npx -y @astrojs/mcp-server",
        "args": [],
        "env": {},
    },
]


CREDENTIAL_CONNECTOR_CATALOG = {
    "cloudflare": {
        "title": "Cloudflare API token setup",
        "auth_url": "https://dash.cloudflare.com/profile/api-tokens",
        "credential_type": "api_key",
        "suggested_env": "CLOUDFLARE_API_TOKEN",
    },
    "stripe": {
        "title": "Stripe API key setup",
        "auth_url": "https://dashboard.stripe.com/apikeys",
        "credential_type": "api_key",
        "suggested_env": "STRIPE_API_KEY",
    },
    "github": {
        "title": "GitHub token setup",
        "auth_url": "https://github.com/settings/tokens",
        "credential_type": "api_key",
        "suggested_env": "GITHUB_TOKEN",
    },
    "openrouter": {
        "title": "OpenRouter API key setup",
        "auth_url": "https://openrouter.ai/keys",
        "credential_type": "api_key",
        "suggested_env": "OPENROUTER_API_KEY",
    },
}


def _build_base_providers() -> dict[str, OpenAICompatProvider]:
    providers = {
        "copilot_proxy": OpenAICompatProvider(
            ProviderConfig(
                name="copilot_proxy",
                base_url=settings.copilot_base_url.rstrip("/"),
                default_model=settings.copilot_model,
                api_key=settings.copilot_api_key,
            )
        )
    }

    if settings.local_base_url.strip():
        providers["local_openai"] = OpenAICompatProvider(
            ProviderConfig(
                name="local_openai",
                base_url=settings.local_base_url.rstrip("/"),
                default_model=settings.local_model,
                api_key=settings.local_api_key,
            )
        )

    return providers


def _normalize_existing_mcp_servers() -> None:
    rows = DB_CONN.execute(
        "SELECT id, name, transport, url, command, env_json FROM mcp_servers"
    ).fetchall()

    catalog_by_name = {entry["name"]: entry for entry in MCP_ONBOARDING_CATALOG.values()}
    changed = False

    for row in rows:
        current = dict(row)
        name = (current.get("name") or "").strip()
        transport = current.get("transport")
        url = current.get("url") or ""
        command = current.get("command")
        env = _decode_json_field(current.get("env_json"), {})

        next_transport = transport
        next_url = current.get("url")
        next_command = command
        next_env = dict(env)

        # Repair older fallback records that were incorrectly set to HTTP /health for stdio tools.
        if transport == "http" and command and url.endswith("/health") and name.endswith("-mcp"):
            next_transport = "stdio"
            next_url = None

        # Fill missing stdio command/env for known catalog entries.
        catalog_entry = catalog_by_name.get(name)
        if catalog_entry and next_transport == "stdio":
            if not next_command:
                next_command = catalog_entry.get("command")
            for k, v in (catalog_entry.get("env") or {}).items():
                if k not in next_env:
                    next_env[k] = v

        if (
            next_transport != transport
            or next_url != current.get("url")
            or next_command != command
            or next_env != env
        ):
            DB_CONN.execute(
                """
                UPDATE mcp_servers
                SET transport = ?, url = ?, command = ?, env_json = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (next_transport, next_url, next_command, json.dumps(next_env), current["id"]),
            )
            changed = True

    if changed:
        DB_CONN.commit()


def _reload_providers_from_integrations() -> None:
    global PROVIDERS
    PROVIDERS = _build_base_providers()

    rows = DB_CONN.execute(
        """
        SELECT id, name, base_url, api_key, default_model, status
        FROM integrations
        WHERE status = 'connected' AND base_url IS NOT NULL AND trim(base_url) != ''
        """
    ).fetchall()

    for row in rows:
        api_key, err = _resolve_credential_secret_by_ref(row["api_key"] or "")
        if err:
            continue
        provider_name = f"integration_{row['id']}"
        PROVIDERS[provider_name] = OpenAICompatProvider(
            ProviderConfig(
                name=provider_name,
                base_url=row["base_url"].rstrip("/"),
                default_model=(row["default_model"] or "auto"),
                api_key=api_key or "",
            )
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    global DB_CONN, PROVIDERS

    DB_CONN = get_connection(settings.db_path)
    init_db(DB_CONN)
    _normalize_existing_mcp_servers()
    _ensure_builtin_mcp_servers()
    _reload_providers_from_integrations()

    yield

    if DB_CONN:
        DB_CONN.close()


app = FastAPI(title="CrowPilot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _decode_json_field(raw: str | None, fallback):
    if raw is None or not raw.strip():
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _serialize_mcp_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["args"] = _decode_json_field(out.pop("args_json", "[]"), [])
    out["env"] = _decode_json_field(out.pop("env_json", "{}"), {})
    out["is_builtin"] = bool(out.get("is_builtin"))
    return out


def _serialize_widget_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["config"] = _decode_json_field(out.pop("config_json", "{}"), {})
    return out


def _serialize_copilot_task_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["context"] = _decode_json_field(out.pop("context_json", "{}"), {})
    return out


def _serialize_automation_task_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["local_context"] = _decode_json_field(out.pop("local_context_json", "{}"), {})
    return out


def _serialize_skill_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["local_only"] = bool(out["local_only"])
    out["input_schema"] = _decode_json_field(out.pop("input_schema_json", "{}"), {})
    out["output_schema"] = _decode_json_field(out.pop("output_schema_json", "{}"), {})
    out["tool_contract"] = _decode_json_field(out.pop("tool_contract_json", "{}"), {})
    return out


def _serialize_conversation_row(row: sqlite3.Row) -> dict:
    return dict(row)


def _serialize_integration_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["models"] = _decode_json_field(out.pop("models_json", "[]"), [])
    out["meta"] = _decode_json_field(out.pop("meta_json", "{}"), {})
    raw_key = out.pop("api_key", None)
    out["has_api_key"] = bool(raw_key)
    out["api_key_is_reference"] = bool(raw_key and isinstance(raw_key, str) and CRED_REF_PATTERN.match(raw_key.strip()))
    return out


def _serialize_credential_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["meta"] = _decode_json_field(out.pop("meta_json", "{}"), {})
    out.pop("secret_encrypted", None)
    return out


def _serialize_project_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["stack"] = _decode_json_field(out.pop("stack_json", "{}"), {})
    return out


def _projects_root() -> Path:
    root = Path(settings.projects_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_child_path(base: Path, relative: str) -> Path:
    child = (base / (relative or "")).resolve()
    if child == base or base in child.parents:
        return child
    raise HTTPException(status_code=400, detail="Path escapes the project root")


def _project_row_and_path(project_id: int) -> tuple[sqlite3.Row, Path]:
    row = DB_CONN.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project_path = Path(row["path"]).resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Project path is missing or not a directory")
    return row, project_path


def _next_project_slug(base_name: str) -> str:
    base_slug = _slugify_name(base_name, "project")
    root = _projects_root()
    for idx in range(0, 200):
        candidate = base_slug if idx == 0 else f"{base_slug}-{idx + 1}"
        exists = DB_CONN.execute("SELECT 1 FROM projects WHERE slug = ?", (candidate,)).fetchone()
        if not exists and not (root / candidate).exists():
            return candidate
    raise HTTPException(status_code=409, detail="Unable to generate unique project slug")


def _project_tree_entry(path: Path, project_root: Path) -> dict:
    rel = str(path.relative_to(project_root)) if path != project_root else "."
    stat = path.stat()
    return {
        "name": path.name if path != project_root else project_root.name,
        "relative_path": rel,
        "is_dir": path.is_dir(),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def _detect_copilot_cli() -> dict:
    configured = (settings.copilot_cli_command or "gh").strip()
    parts = shlex.split(configured) if configured else ["gh"]
    exe = parts[0] if parts else "gh"
    if shutil.which(exe) is None:
        return {
            "available": False,
            "configured": configured,
            "reason": f"Executable not found in PATH: {exe}",
        }
    return {
        "available": True,
        "configured": configured,
        "parts": parts,
        "exe": exe,
    }


def _build_copilot_cli_args(prompt: str, target: str) -> list[str]:
    info = _detect_copilot_cli()
    if not info.get("available"):
        raise HTTPException(status_code=400, detail=info.get("reason") or "Copilot CLI is unavailable")

    parts: list[str] = info["parts"]
    exe = info["exe"]
    if exe == "gh":
        # GitHub CLI Copilot integration.
        if target == "shell":
            return parts + ["copilot", "suggest", "-t", "shell", prompt]
        return parts + ["copilot", "explain", prompt]
    if exe == "copilot":
        return parts + [prompt]
    return parts + [prompt]


def _ensure_builtin_mcp_servers() -> None:
    changed = False
    for server in BUILTIN_MCP_SERVERS:
        existing = DB_CONN.execute("SELECT * FROM mcp_servers WHERE name = ?", (server["name"],)).fetchone()
        if existing:
            env = _decode_json_field(existing["env_json"], {})
            merged_env = {**(server.get("env") or {}), **(env or {})}
            DB_CONN.execute(
                """
                UPDATE mcp_servers
                SET is_builtin = 1,
                    transport = COALESCE(NULLIF(transport, ''), ?),
                    command = COALESCE(command, ?),
                    url = COALESCE(url, ?),
                    args_json = CASE WHEN args_json IS NULL OR trim(args_json) = '' THEN ? ELSE args_json END,
                    env_json = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    server["transport"],
                    server["command"],
                    server.get("url"),
                    json.dumps(server.get("args") or []),
                    json.dumps(merged_env),
                    existing["id"],
                ),
            )
            changed = True
            continue

        DB_CONN.execute(
            """
            INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json, is_builtin, status)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'unknown')
            """,
            (
                server["name"],
                server["transport"],
                server.get("url"),
                server.get("command"),
                json.dumps(server.get("args") or []),
                json.dumps(server.get("env") or {}),
            ),
        )
        changed = True

    if changed:
        DB_CONN.commit()


def _upsert_project_from_path(path_text: str, *, name: str | None = None, kind: str = "workspace") -> dict:
    project_path = Path(path_text).expanduser().resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Selected path must be an existing directory")

    row = DB_CONN.execute("SELECT * FROM projects WHERE path = ?", (str(project_path),)).fetchone()
    project_name = (name or project_path.name or "workspace").strip()
    if row:
        DB_CONN.execute(
            "UPDATE projects SET name = ?, kind = ?, last_opened_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (project_name, kind, row["id"]),
        )
        DB_CONN.commit()
        updated = DB_CONN.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone()
        return _serialize_project_row(updated)

    slug = _next_project_slug(project_name)
    cur = DB_CONN.execute(
        """
        INSERT INTO projects(name, slug, path, kind, status, stack_json, last_opened_at)
        VALUES (?, ?, ?, ?, 'active', '{}', datetime('now'))
        """,
        (project_name, slug, str(project_path), kind),
    )
    DB_CONN.commit()
    created = DB_CONN.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_project_row(created)


def _discover_projects_from_root() -> list[dict]:
    root = _projects_root()
    imported: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        imported.append(_upsert_project_from_path(str(child), name=child.name, kind="workspace"))
    return imported


def _open_native_directory_picker() -> str | None:
    system = platform.system().lower()
    try:
        if system == "linux":
            if shutil.which("zenity"):
                proc = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title=Select CrowPilot Workspace Folder"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    return proc.stdout.strip() or None
            if shutil.which("kdialog"):
                proc = subprocess.run(
                    ["kdialog", "--getexistingdirectory", str(_projects_root())],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0:
                    return proc.stdout.strip() or None
        elif system == "darwin":
            proc = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'set theFolder to choose folder with prompt "Select CrowPilot Workspace Folder"',
                    "-e",
                    "POSIX path of theFolder",
                ],
                capture_output=True,
                text=True,
                check=False,
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
            proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return proc.stdout.strip() or None
    except Exception:
        return None
    return None


def _detect_package_manager(folder: Path) -> str:
    if (folder / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (folder / "yarn.lock").exists():
        return "yarn"
    if (folder / "bun.lockb").exists() or (folder / "bun.lock").exists():
        return "bun"
    return "npm"


def _command_for_script(manager: str, script_name: str) -> list[str]:
    if manager == "pnpm":
        return ["pnpm", "run", script_name]
    if manager == "yarn":
        return ["yarn", script_name]
    if manager == "bun":
        return ["bun", "run", script_name]
    return ["npm", "run", script_name]


def _discover_project_scripts(project_path: Path) -> list[dict]:
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
        manager = _detect_package_manager(pkg.parent)
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
                    "command": _command_for_script(manager, script_name),
                }
            )
    return results


def _start_project_runtime(project_id: int, script_row: dict) -> dict:
    runtime_id = str(uuid.uuid4())
    row, project_path = _project_row_and_path(project_id)
    cwd = _safe_child_path(project_path, script_row["relative_dir"])
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
                with PROJECT_RUNTIME_LOCK:
                    if runtime_id in PROJECT_RUNTIMES:
                        PROJECT_RUNTIMES[runtime_id]["logs"].append(line.rstrip())
        except Exception:
            return

    thread = threading.Thread(target=_capture, daemon=True)
    thread.start()

    with PROJECT_RUNTIME_LOCK:
        PROJECT_RUNTIMES[runtime_id] = {
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
        entry = PROJECT_RUNTIMES[runtime_id]

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


def _list_project_runtimes(project_id: int) -> list[dict]:
    out: list[dict] = []
    with PROJECT_RUNTIME_LOCK:
        for runtime_id, entry in list(PROJECT_RUNTIMES.items()):
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


def _runtime_logs(project_id: int, runtime_id: str, lines: int = 200) -> dict:
    with PROJECT_RUNTIME_LOCK:
        entry = PROJECT_RUNTIMES.get(runtime_id)
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


def _stop_runtime(project_id: int, runtime_id: str) -> dict:
    with PROJECT_RUNTIME_LOCK:
        entry = PROJECT_RUNTIMES.get(runtime_id)
        if not entry or entry["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime not found")
        proc = entry["proc"]
        if proc.poll() is None:
            proc.terminate()
        return {
            "id": runtime_id,
            "stopped": True,
        }


def _vault_key_path() -> Path:
    return Path(settings.db_path).resolve().parent / "credential_vault.key"


def _get_credential_cipher() -> Fernet:
    global CREDENTIAL_CIPHER
    if CREDENTIAL_CIPHER is not None:
        return CREDENTIAL_CIPHER

    key_text = (settings.credential_key or "").strip()
    if key_text:
        key_bytes = key_text.encode("utf-8")
    else:
        key_path = _vault_key_path()
        if key_path.exists():
            key_bytes = key_path.read_bytes().strip()
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_bytes = Fernet.generate_key()
            key_path.write_bytes(key_bytes)
            os.chmod(key_path, 0o600)

    CREDENTIAL_CIPHER = Fernet(key_bytes)
    return CREDENTIAL_CIPHER


def _encrypt_secret(plaintext: str) -> str:
    token = _get_credential_cipher().encrypt((plaintext or "").encode("utf-8"))
    return token.decode("utf-8")


def _decrypt_secret(ciphertext: str) -> str:
    try:
        raw = _get_credential_cipher().decrypt((ciphertext or "").encode("utf-8"))
        return raw.decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Credential vault decrypt failed") from exc


def _resolve_credential_secret_by_ref(ref_value: str | None) -> tuple[str | None, str | None]:
    if not ref_value:
        return ref_value, None

    match = CRED_REF_PATTERN.match(ref_value.strip()) if isinstance(ref_value, str) else None
    if not match:
        return ref_value, None

    key = match.group(1).strip()
    row = None
    if key.isdigit():
        row = DB_CONN.execute("SELECT * FROM credentials WHERE id = ?", (int(key),)).fetchone()
    if row is None:
        row = DB_CONN.execute("SELECT * FROM credentials WHERE lower(name) = lower(?)", (key,)).fetchone()
    if row is None:
        return None, f"Credential not found for reference: {ref_value}"

    DB_CONN.execute(
        "UPDATE credentials SET last_used_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    DB_CONN.commit()
    return _decrypt_secret(row["secret_encrypted"]), None


def _resolve_env_credentials(env_map: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    errors: list[str] = []
    for key, value in (env_map or {}).items():
        resolved_value, err = _resolve_credential_secret_by_ref(value)
        if err:
            errors.append(f"{key}: {err}")
            resolved[key] = value
        else:
            resolved[key] = resolved_value
    return resolved, errors


def _slug_for_credential_name(value: str, fallback: str = "credential") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:64] or fallback


def _conversation_rows_for_sidebar(where_clause: str, params: tuple, limit: int) -> list[dict]:
    rows = DB_CONN.execute(
        f"""
        SELECT
            c.id,
            c.title,
            c.created_at,
            c.sidebar_state,
            c.archive_bucket,
            c.archive_summary,
            c.archive_note,
            c.archived_at,
            (
                SELECT COUNT(*)
                FROM messages m
                WHERE m.conversation_id = c.id
            ) AS message_count
        FROM conversations c
        {where_clause}
        ORDER BY c.id DESC
        LIMIT ?
        """,
        params + (limit,),
    ).fetchall()
    return [_serialize_conversation_row(r) for r in rows]


def _extract_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty model response")

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return json.loads(raw[start:end + 1])


def _get_zen_provider(provider_name: str | None) -> OpenAICompatProvider:
    if provider_name:
        provider = PROVIDERS.get(provider_name)
        if not provider:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
        return provider
    return PROVIDERS.get("local_openai") or PROVIDERS[settings.default_provider]


def _build_zen_messages(domain: str, prompt: str, source_text: str | None) -> list[dict[str, str]]:
    contracts = {
        "task_create": {
            "shape": {
                "title": "string",
                "objective": "string",
                "trigger_type": "manual|scheduled|event",
                "status": "draft|ready|active|archived",
                "sensitive_mode": "off|local_only|hybrid_redacted",
                "local_context": {},
                "cloud_prompt_template": "string|null",
                "runbook_markdown": "string|null",
                "assistant_summary": "string",
            },
            "guidance": "Create a reusable personal automation task. Prefer hybrid_redacted when the prompt implies credentials, portals, reports, or secrets.",
        },
        "skill_create": {
            "shape": {
                "name": "string",
                "category": "string",
                "description": "string",
                "status": "draft|active|disabled",
                "local_only": False,
                "input_schema": {},
                "output_schema": {},
                "tool_contract": {},
                "assistant_summary": "string",
            },
            "guidance": "Create a reusable skill contract. If the prompt includes source code or a URL, infer the skill purpose and required tools.",
        },
        "note_create": {
            "shape": {
                "title": "string",
                "body": "string",
                "assistant_summary": "string",
            },
            "guidance": "Turn the prompt into a structured knowledge note with a concise title and clean body.",
        },
        "mcp_create": {
            "shape": {
                "name": "string",
                "transport": "http|sse|stdio",
                "url": "string|null",
                "command": "string|null",
                "args": [],
                "env": {},
                "assistant_summary": "string",
            },
            "guidance": "Turn the prompt into an MCP server registration. Leave unknown fields null or empty instead of inventing secrets.",
        },
        "widget_create": {
            "shape": {
                "name": "string",
                "widget_type": "string",
                "layout_col": 1,
                "layout_row": 1,
                "layout_w": 4,
                "layout_h": 2,
                "config": {},
                "assistant_summary": "string",
            },
            "guidance": "Create a dashboard widget configuration. Keep config minimal and useful. Use sane layout defaults.",
        },
    }

    contract = contracts[domain]
    source_block = f"\n\nSOURCE TEXT:\n{source_text.strip()}" if source_text and source_text.strip() else ""
    system = (
        "You are CrowPilot's Zen mode planner. Convert the user's natural language request into one JSON object only. "
        "Do not wrap in markdown. Do not explain outside the JSON. Use safe defaults when details are missing. "
        f"{contract['guidance']} Required JSON shape: {json.dumps(contract['shape'])}"
    )
    user = f"USER REQUEST:\n{prompt.strip()}{source_block}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _slugify_name(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:64] or fallback


def _fallback_zen_plan(domain: str, prompt: str, source_text: str | None) -> tuple[dict, str]:
    text = " ".join((prompt or "").split())
    source = (source_text or "").strip()

    if domain == "task_create":
        lower = text.lower()
        sensitive = any(token in lower for token in ["secret", "token", "password", "credential", "api key"])
        parsed = {
            "title": (text[:72] or "Zen task").strip(),
            "objective": text or "Execute a repeatable automation task.",
            "trigger_type": "manual",
            "status": "draft",
            "sensitive_mode": "hybrid_redacted" if sensitive else "off",
            "local_context": {},
            "cloud_prompt_template": None,
            "runbook_markdown": None,
        }
        return parsed, "Zen fallback created a draft task because model planning was unavailable."

    if domain == "skill_create":
        seed = " ".join(text.split()[:6])
        parsed = {
            "name": _slugify_name(seed, "zen-skill"),
            "category": "general",
            "description": text or "Reusable skill contract.",
            "status": "draft",
            "local_only": False,
            "input_schema": {},
            "output_schema": {},
            "tool_contract": {},
        }
        return parsed, "Zen fallback created a draft skill because model planning was unavailable."

    if domain == "note_create":
        parsed = {
            "title": (text[:72] or "Zen note").strip(),
            "body": source or text or "",
        }
        return parsed, "Zen fallback captured the note because model planning was unavailable."

    if domain == "mcp_create":
        onboarding = _derive_onboarding_from_prompt(text, include_catalog=False)
        suggestion = onboarding.get("primary_suggestion") or {}
        parsed = {
            "name": _slugify_name(suggestion.get("name") or "zen-mcp", "zen-mcp"),
            "transport": suggestion.get("transport") or "stdio",
            "url": suggestion.get("url"),
            "command": suggestion.get("command"),
            "args": suggestion.get("args") or [],
            "env": suggestion.get("env") or {},
        }
        return parsed, "Zen fallback created an MCP draft because model planning was unavailable."

    if domain == "widget_create":
        parsed = {
            "name": (text[:64] or "Zen widget").strip(),
            "widget_type": "custom",
            "layout_col": 1,
            "layout_row": 1,
            "layout_w": 4,
            "layout_h": 2,
            "config": {},
        }
        return parsed, "Zen fallback created a widget draft because model planning was unavailable."

    return {}, "Zen fallback could not map the request."


def _insert_mcp_server_with_unique_name(parsed: dict) -> sqlite3.Row:
    base_name = ((parsed.get("name") or "zen-mcp").strip() or "zen-mcp")[:64]
    for attempt in range(0, 25):
        if attempt == 0:
            candidate = base_name
        else:
            suffix = f"-{attempt + 1}"
            candidate = f"{base_name[: max(1, 64 - len(suffix))]}{suffix}"

        try:
            cur = DB_CONN.execute(
                """
                INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate,
                    parsed.get("transport") or "http",
                    parsed.get("url"),
                    parsed.get("command"),
                    json.dumps(parsed.get("args") or []),
                    json.dumps(parsed.get("env") or {}),
                ),
            )
            DB_CONN.commit()
            return DB_CONN.execute("SELECT * FROM mcp_servers WHERE id = ?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            continue

    raise HTTPException(status_code=409, detail="Unable to create MCP server: generated names already exist")


def _derive_onboarding_from_prompt(prompt: str, include_catalog: bool) -> dict:
    text = (prompt or "").strip()
    lower = text.lower()
    matched = [key for key in MCP_ONBOARDING_CATALOG.keys() if key in lower]

    url_match = re.search(r"https?://[^\s,]+", text)
    explicit_url = url_match.group(0) if url_match else None

    suggestions: list[dict] = []
    if matched:
        for key in matched:
            base = dict(MCP_ONBOARDING_CATALOG[key])
            if explicit_url and not base.get("url"):
                base["url"] = explicit_url
                base["transport"] = "http"
                base["command"] = None
            suggestions.append({"id": key, **base})
    elif explicit_url:
        host_hint = re.sub(r"^https?://", "", explicit_url).split("/")[0]
        suggestions.append(
            {
                "id": "custom-http",
                "name": f"{host_hint}-mcp".replace(":", "-"),
                "transport": "http",
                "url": explicit_url,
                "command": None,
                "args": [],
                "env": {},
                "docs": ["https://modelcontextprotocol.io"],
                "notes": "Custom endpoint detected from prompt URL.",
            }
        )
    else:
        suggestions.append(
            {
                "id": "generic",
                "name": "custom-mcp",
                "transport": "http",
                "url": None,
                "command": None,
                "args": [],
                "env": {},
                "docs": ["https://modelcontextprotocol.io"],
                "notes": "No known provider matched. Provide endpoint URL or command.",
            }
        )

    primary = suggestions[0]
    response = {
        "prompt": text,
        "matched": matched,
        "primary_suggestion": {
            "name": primary.get("name"),
            "transport": primary.get("transport"),
            "url": primary.get("url"),
            "command": primary.get("command"),
            "args": primary.get("args") or [],
            "env": primary.get("env") or {},
        },
        "suggestions": suggestions,
        "next_steps": [
            "Apply suggestion into form fields.",
            "Fill any <required> env variables.",
            "Add server and run protocol check.",
        ],
    }
    if include_catalog:
        response["catalog"] = MCP_ONBOARDING_CATALOG
    return response


async def _run_protocol_checks_for_server(row: sqlite3.Row) -> tuple[str, str | None, dict]:
    transport = row["transport"]
    url = row["url"]
    command = row["command"]
    env = _decode_json_field(row["env_json"] if "env_json" in row.keys() else "{}", {})
    resolved_env, env_resolution_errors = _resolve_env_credentials(env)
    checks: list[dict] = []
    discovered_tools: list[str] = []

    async def _post_jsonrpc(client: httpx.AsyncClient, target_url: str, method: str, params: dict, req_id: str) -> dict:
        resp = await client.post(
            target_url,
            json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
            headers={"Content-Type": "application/json"},
        )
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return {"status": resp.status_code, "payload": payload}

    if transport in ("http", "sse"):
        if not url:
            report = {
                "transport": transport,
                "checks": [{"step": "configuration", "ok": False, "detail": "Missing URL for HTTP/SSE transport"}],
                "tools": [],
            }
            return "offline", "Missing URL for HTTP/SSE transport", report

        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                get_resp = await client.get(url)
                checks.append({"step": "reachability", "ok": get_resp.status_code < 500, "detail": f"HTTP {get_resp.status_code}"})

                if transport == "sse":
                    ct = get_resp.headers.get("content-type", "")
                    checks.append({"step": "sse_content_type", "ok": "text/event-stream" in ct, "detail": ct or "not provided"})

                init_result = await _post_jsonrpc(
                    client,
                    url,
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "crowpilot", "version": "0.1.0"},
                    },
                    "crowpilot-init",
                )
                init_payload = init_result["payload"] if isinstance(init_result["payload"], dict) else {}
                init_ok = (
                    200 <= init_result["status"] < 300
                    and not init_payload.get("error")
                    and isinstance(init_payload.get("result"), dict)
                )
                checks.append(
                    {
                        "step": "mcp_initialize",
                        "ok": init_ok,
                        "detail": f"HTTP {init_result['status']}" if init_ok else (json.dumps(init_payload)[:220] or f"HTTP {init_result['status']}"),
                    }
                )

                if init_ok:
                    tools_result = await _post_jsonrpc(client, url, "tools/list", {}, "crowpilot-tools")
                    tools_payload = tools_result["payload"].get("result", {}) if isinstance(tools_result["payload"], dict) else {}
                    tools = tools_payload.get("tools", []) if isinstance(tools_payload, dict) else []
                    discovered_tools = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
                    tools_ok = (
                        200 <= tools_result["status"] < 300
                        and isinstance(tools_result["payload"], dict)
                        and not tools_result["payload"].get("error")
                        and isinstance(tools_payload, dict)
                    )
                    checks.append(
                        {
                            "step": "mcp_tools_list",
                            "ok": tools_ok,
                            "detail": f"found {len(discovered_tools)} tools",
                        }
                    )
                else:
                    checks.append({"step": "mcp_tools_list", "ok": False, "detail": "Skipped because initialize failed"})

        except Exception as exc:
            checks.append({"step": "exception", "ok": False, "detail": str(exc)})

    elif transport == "stdio":
        if not command:
            checks.append({"step": "configuration", "ok": False, "detail": "Missing command for stdio transport"})
        else:
            if env_resolution_errors:
                checks.append(
                    {
                        "step": "credential_refs",
                        "ok": False,
                        "detail": "; ".join(env_resolution_errors[:3]),
                    }
                )

            missing_env = [
                k
                for k, v in (resolved_env or {}).items()
                if not isinstance(v, str) or not v.strip() or v.strip() == "<required>"
            ]
            if missing_env:
                checks.append(
                    {
                        "step": "required_env",
                        "ok": False,
                        "detail": f"Missing concrete values for: {', '.join(missing_env)}",
                    }
                )

            exe = command.strip().split()[0]
            found = shutil.which(exe) is not None
            checks.append(
                {
                    "step": "binary_present",
                    "ok": found,
                    "detail": f"{exe} {'found' if found else 'not found in PATH'}",
                }
            )
            if exe in ("npx", "node"):
                checks.append(
                    {
                        "step": "runtime_hint",
                        "ok": found,
                        "detail": "Node-based MCP server declared; runtime availability checked only.",
                    }
                )
    else:
        checks.append({"step": "transport", "ok": False, "detail": f"Unsupported transport: {transport}"})

    all_ok = bool(checks) and all(c.get("ok") for c in checks)
    status = "online" if all_ok else "offline"
    failing = [c for c in checks if not c.get("ok")]
    last_error = None if all_ok else "; ".join(c.get("detail", "failed") for c in failing[:3])
    report = {
        "transport": transport,
        "checks": checks,
        "tools": discovered_tools,
    }
    return status, last_error, report


def _fetch_memory_context(query: str, limit: int = 3) -> list[dict]:
    """Search the notes FTS index for chunks relevant to the query."""
    try:
        safe = re.sub(r"[^\w\s]", " ", query).strip()
        if not safe:
            return []
        rows = DB_CONN.execute(
            """
            SELECT n.title, nc.chunk_text, bm25(note_chunks_fts) AS score
            FROM note_chunks_fts
            JOIN note_chunks nc ON nc.id = note_chunks_fts.rowid
            JOIN notes n ON n.id = nc.note_id
            WHERE note_chunks_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
            """,
            (safe, limit),
        ).fetchall()
        return rows_to_dicts(rows)
    except Exception:
        return []


async def _relay_list_tools() -> list[dict]:
    """Fetch tools from all online HTTP MCP servers and update the routing map."""
    global MCP_TOOL_ROUTE_MAP
    rows = DB_CONN.execute(
        "SELECT name, url FROM mcp_servers WHERE transport IN ('http', 'sse') AND status = 'online' AND url IS NOT NULL"
    ).fetchall()

    all_tools: list[dict] = []
    new_map: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        for row in rows:
            url = row["url"]
            try:
                resp = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": "relay-tools", "method": "tools/list", "params": {}},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tools = (data.get("result") or {}).get("tools", []) if isinstance(data.get("result"), dict) else []
                    for tool in tools:
                        if isinstance(tool, dict) and tool.get("name"):
                            new_map[tool["name"]] = url
                            all_tools.append(tool)
            except Exception:
                pass

    MCP_TOOL_ROUTE_MAP = new_map
    return all_tools


async def _relay_call_tool(tool_name: str, arguments: dict) -> dict:
    """Route a tool call to the appropriate backend MCP server."""
    global MCP_TOOL_ROUTE_MAP
    server_url = MCP_TOOL_ROUTE_MAP.get(tool_name)
    if not server_url:
        # Refresh routing map and retry once
        await _relay_list_tools()
        server_url = MCP_TOOL_ROUTE_MAP.get(tool_name)

    if not server_url:
        return {
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not found in any connected MCP server."}],
            "isError": True,
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "relay-call",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data.get("result"), dict):
                    return data["result"]
                if data.get("error"):
                    return {"content": [{"type": "text", "text": json.dumps(data["error"])}], "isError": True}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Relay error: {exc}"}], "isError": True}

    return {"content": [{"type": "text", "text": "No response from backend server."}], "isError": True}


def _discover_local_ipv4() -> list[str]:
    hosts: set[str] = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if addr:
                hosts.add(addr)
    except Exception:
        pass
    return sorted(hosts)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(static_dir / "crowpilot-favicon.ico", media_type="image/x-icon")


@app.get("/api/health")
async def health() -> dict:
    checks = {}
    for name, provider in PROVIDERS.items():
        try:
            models = await provider.list_models()
            checks[name] = {
                "ok": True,
                "model_count": len(models),
                "default_model": provider.cfg.default_model,
                "base_url": provider.cfg.base_url,
            }
        except Exception as exc:
            checks[name] = {
                "ok": False,
                "error": str(exc),
                "default_model": provider.cfg.default_model,
                "base_url": provider.cfg.base_url,
            }
    return {"status": "ok", "providers": checks}


@app.get("/api/hub/access")
def hub_access() -> dict:
    addresses = _discover_local_ipv4()
    return {
        "configured_host": settings.host,
        "port": settings.port,
        "local_addresses": addresses,
        "reachable_urls": [f"http://{addr}:{settings.port}" for addr in addresses],
        "note": "Set PANTHEON_HOST=0.0.0.0 to allow other LAN devices to access this CrowPilot hub.",
    }


@app.get("/api/models")
async def list_models_for_provider(provider: str | None = None) -> dict:
    """List available models for a specific provider (or all providers if not specified)"""
    if provider:
        p = PROVIDERS.get(provider)
        if not p:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
        try:
            models = await p.list_models()
            model_ids = [m.get("id") for m in models if m.get("id")]
            if provider == "copilot_proxy" and "auto" not in model_ids:
                model_ids.insert(0, "auto")
            return {
                "provider": provider,
                "ok": True,
                "models": model_ids,
                "default_model": p.cfg.default_model,
            }
        except Exception as exc:
            return {
                "provider": provider,
                "ok": False,
                "error": str(exc),
                "models": [],
                "default_model": p.cfg.default_model,
            }
    else:
        # Return models for all providers
        result = {}
        for name, p in PROVIDERS.items():
            try:
                models = await p.list_models()
                model_ids = [m.get("id") for m in models if m.get("id")]
                if name == "copilot_proxy" and "auto" not in model_ids:
                    model_ids.insert(0, "auto")
                result[name] = {
                    "ok": True,
                    "models": model_ids,
                    "default_model": p.cfg.default_model,
                }
            except Exception as exc:
                result[name] = {
                    "ok": False,
                    "error": str(exc),
                    "models": [],
                    "default_model": p.cfg.default_model,
                }
        return result


@app.get("/api/dashboard/summary")
async def dashboard_summary() -> dict:
    providers = (await health())["providers"]

    counts = {
        "conversations": DB_CONN.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
        "messages": DB_CONN.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "notes": DB_CONN.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
        "mcp_servers": DB_CONN.execute("SELECT COUNT(*) FROM mcp_servers").fetchone()[0],
        "widgets": DB_CONN.execute("SELECT COUNT(*) FROM dashboard_widgets").fetchone()[0],
        "copilot_tasks": DB_CONN.execute("SELECT COUNT(*) FROM copilot_tasks").fetchone()[0],
        "automation_tasks": DB_CONN.execute("SELECT COUNT(*) FROM automation_tasks").fetchone()[0],
        "skills": DB_CONN.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
        "integrations": DB_CONN.execute("SELECT COUNT(*) FROM integrations").fetchone()[0],
        "credentials": DB_CONN.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],
        "projects": DB_CONN.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
    }

    return {
        "counts": counts,
        "providers": providers,
        "tagline": "CrowPilot command center for MCP, model routing, and local knowledge.",
    }


@app.get("/api/providers/{provider_name}/models")
async def list_provider_models(provider_name: str) -> dict:
    provider = PROVIDERS.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")

    try:
        models = await provider.list_models()
        return {"provider": provider_name, "models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/conversations", response_model=ConversationOut)
def create_conversation(payload: CreateConversationRequest) -> dict:
    title = (payload.title or "New conversation").strip() or "New conversation"
    cur = DB_CONN.execute(
        "INSERT INTO conversations(title) VALUES (?)",
        (title,),
    )
    DB_CONN.commit()
    row = DB_CONN.execute(
        "SELECT id, title, created_at FROM conversations WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return dict(row)


@app.get("/api/conversations")
def list_conversations(scope: str = "active", limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    if scope == "active":
        return _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'active'", (), limit)
    if scope == "hidden":
        return _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'hidden'", (), limit)
    if scope == "archived_good":
        return _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'good'", (), limit)
    if scope == "archived_bad":
        return _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'bad'", (), limit)
    if scope == "all":
        return _conversation_rows_for_sidebar("", (), limit)
    raise HTTPException(status_code=400, detail="Unsupported conversation scope")


@app.get("/api/conversations/sidebar")
def conversation_sidebar(limit_per_bucket: int = 75) -> dict:
    limit_per_bucket = max(1, min(limit_per_bucket, 200))
    buckets = {
        "active": _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'active'", (), limit_per_bucket),
        "hidden": _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'hidden'", (), limit_per_bucket),
        "archived_good": _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'good'", (), limit_per_bucket),
        "archived_bad": _conversation_rows_for_sidebar("WHERE c.sidebar_state = 'archived' AND c.archive_bucket = 'bad'", (), limit_per_bucket),
    }
    counts = {name: len(rows) for name, rows in buckets.items()}
    return {"buckets": buckets, "counts": counts}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int) -> dict:
    """Get a conversation with all its messages"""
    conv_row = DB_CONN.execute(
        """
        SELECT id, title, created_at, sidebar_state, archive_bucket, archive_summary, archive_note, archived_at
        FROM conversations WHERE id = ?
        """,
        (conversation_id,),
    ).fetchone()
    if not conv_row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv_dict = dict(conv_row)
    
    msg_rows = DB_CONN.execute(
        """
        SELECT id, conversation_id, role, content, provider, model, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,),
    ).fetchall()
    
    conv_dict["messages"] = rows_to_dicts(msg_rows)
    return conv_dict


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: int, payload: ConversationUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    action = payload.action
    if action == "restore":
        restore_state = "archived" if row["archive_bucket"] else "active"
        DB_CONN.execute(
            """
            UPDATE conversations
            SET sidebar_state = ?, archive_bucket = ?, archived_at = ?,
                archive_summary = ?, archive_note = ?
            WHERE id = ?
            """,
            (
                restore_state,
                row["archive_bucket"] if restore_state == "archived" else None,
                row["archived_at"] if restore_state == "archived" else None,
                row["archive_summary"] if restore_state == "archived" else None,
                row["archive_note"] if restore_state == "archived" else None,
                conversation_id,
            ),
        )
        if restore_state == "active":
            DB_CONN.execute("DELETE FROM conversation_archive_chunks WHERE conversation_id = ?", (conversation_id,))
    elif action == "hide":
        DB_CONN.execute(
            """
            UPDATE conversations
            SET sidebar_state = 'hidden', archived_at = NULL
            WHERE id = ?
            """,
            (conversation_id,),
        )
    else:
        archive_bucket = "good" if action == "archive_good" else "bad"
        msg_rows = DB_CONN.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        transcript = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in msg_rows)
        compressed = " ".join(transcript.split())
        chunks = split_into_chunks(compressed, settings.chunk_size, settings.chunk_overlap)
        summary = (
            f"Archived {len(msg_rows)} messages as a {'good' if archive_bucket == 'good' else 'bad'} pattern example."
        )

        DB_CONN.execute("DELETE FROM conversation_archive_chunks WHERE conversation_id = ?", (conversation_id,))
        for idx, chunk in enumerate(chunks):
            DB_CONN.execute(
                """
                INSERT INTO conversation_archive_chunks(conversation_id, archive_bucket, chunk_index, chunk_text)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, archive_bucket, idx, chunk),
            )

        DB_CONN.execute(
            """
            UPDATE conversations
            SET sidebar_state = 'archived', archive_bucket = ?, archive_summary = ?, archive_note = ?, archived_at = datetime('now')
            WHERE id = ?
            """,
            (archive_bucket, summary, payload.note, conversation_id),
        )

    DB_CONN.commit()
    updated = DB_CONN.execute(
        "SELECT id, title, created_at, sidebar_state, archive_bucket, archive_summary, archive_note, archived_at FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    return _serialize_conversation_row(updated)


@app.get("/api/conversations/{conversation_id}/archive-chunks")
def get_conversation_archive_chunks(conversation_id: int) -> dict:
    rows = DB_CONN.execute(
        "SELECT archive_bucket, chunk_index, chunk_text, created_at FROM conversation_archive_chunks WHERE conversation_id = ? ORDER BY chunk_index ASC",
        (conversation_id,),
    ).fetchall()
    return {"conversation_id": conversation_id, "chunks": rows_to_dicts(rows)}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True, "id": conversation_id}


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(conversation_id: int) -> list[dict]:
    rows = DB_CONN.execute(
        """
        SELECT id, conversation_id, role, content, provider, model, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,),
    ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest):
    provider_name = payload.provider or settings.default_provider
    provider = PROVIDERS.get(provider_name)
    if not provider:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    conversation_id = payload.conversation_id
    if conversation_id is None:
        cur = DB_CONN.execute(
            "INSERT INTO conversations(title) VALUES (?)",
            (payload.message[:80],),
        )
        DB_CONN.commit()
        conversation_id = cur.lastrowid

    DB_CONN.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?, ?, ?)",
        (conversation_id, "user", payload.message),
    )
    DB_CONN.commit()

    history_rows = DB_CONN.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    # Memory context injection — search knowledge base for relevant notes
    memory_hits = 0
    if payload.use_memory:
        memories = _fetch_memory_context(payload.message, limit=3)
        if memories:
            memory_hits = len(memories)
            context_text = "\n\n".join(
                f"[Memory: {m['title']}]\n{m['chunk_text']}" for m in memories
            )
            history = [
                {"role": "system", "content": f"Relevant context from your knowledge base:\n\n{context_text}"}
            ] + history

    async def event_stream() -> AsyncGenerator[str, None]:
        assistant_parts: list[str] = []

        yield "data: " + json.dumps({"type": "meta", "conversation_id": conversation_id, "memory_hits": memory_hits}) + "\n\n"

        try:
            async for token in provider.stream_chat(
                messages=history,
                model=None if payload.model == "auto" else payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
            ):
                assistant_parts.append(token)
                yield "data: " + json.dumps({"type": "token", "token": token}) + "\n\n"

            assistant_text = "".join(assistant_parts).strip()
            DB_CONN.execute(
                """
                INSERT INTO messages(conversation_id, role, content, provider, model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    "assistant",
                    assistant_text,
                    provider_name,
                    payload.model or provider.cfg.default_model,
                ),
            )
            DB_CONN.commit()

            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "error": str(exc)}) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/notes")
def add_note(payload: AddNoteRequest) -> dict:
    cur = DB_CONN.execute(
        "INSERT INTO notes(title, body) VALUES (?, ?)",
        (payload.title.strip(), payload.body.strip()),
    )
    note_id = cur.lastrowid

    chunks = split_into_chunks(payload.body, settings.chunk_size, settings.chunk_overlap)
    for idx, chunk in enumerate(chunks):
        DB_CONN.execute(
            "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            (note_id, idx, chunk),
        )

    DB_CONN.commit()
    return {"note_id": note_id, "chunks_indexed": len(chunks)}


@app.post("/api/notes/search")
def search_notes(payload: SearchNotesRequest) -> list[dict]:
    rows = DB_CONN.execute(
        """
        SELECT
            n.id AS note_id,
            n.title AS note_title,
            nc.chunk_index,
            nc.chunk_text,
            bm25(note_chunks_fts) AS score
        FROM note_chunks_fts
        JOIN note_chunks nc ON nc.id = note_chunks_fts.rowid
        JOIN notes n ON n.id = nc.note_id
        WHERE note_chunks_fts MATCH ?
        ORDER BY score ASC
        LIMIT ?
        """,
        (payload.query, payload.limit),
    ).fetchall()
    return rows_to_dicts(rows)


@app.get("/api/mcp/servers")
def list_mcp_servers() -> list[dict]:
    rows = DB_CONN.execute(
        """
        SELECT id, name, transport, url, command, args_json, env_json,
               status, last_error, last_checked_at, created_at, updated_at
        FROM mcp_servers
        ORDER BY id DESC
        """
    ).fetchall()
    return [_serialize_mcp_row(r) for r in rows]


@app.post("/api/mcp/servers")
async def create_mcp_server(payload: McpServerCreateRequest) -> dict:
    try:
        cur = DB_CONN.execute(
            """
            INSERT INTO mcp_servers(name, transport, url, command, args_json, env_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.transport,
                payload.url,
                payload.command,
                json.dumps(payload.args),
                json.dumps(payload.env),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Server name already exists") from exc

    DB_CONN.commit()
    row = DB_CONN.execute(
        """
        SELECT id, name, transport, url, command, args_json, env_json,
               is_builtin, status, last_error, last_checked_at, created_at, updated_at
        FROM mcp_servers WHERE id = ?
        """,
        (cur.lastrowid,),
    ).fetchone()
    status, last_error, report = await _run_protocol_checks_for_server(row)
    DB_CONN.execute(
        """
        UPDATE mcp_servers
        SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, last_error, cur.lastrowid),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM mcp_servers WHERE id = ?", (cur.lastrowid,)).fetchone()
    out = _serialize_mcp_row(updated)
    out["validation_report"] = report
    return out


@app.post("/api/mcp/onboard")
def mcp_onboard(payload: McpOnboardRequest) -> dict:
    return _derive_onboarding_from_prompt(payload.prompt, payload.include_catalog)


@app.patch("/api/mcp/servers/{server_id}")
def update_mcp_server(server_id: int, payload: McpServerUpdateRequest) -> dict:
    existing = DB_CONN.execute(
        "SELECT * FROM mcp_servers WHERE id = ?", (server_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="MCP server not found")

    next_values = dict(existing)
    patch = payload.model_dump(exclude_unset=True)
    if "args" in patch:
        next_values["args_json"] = json.dumps(patch.pop("args"))
    if "env" in patch:
        next_values["env_json"] = json.dumps(patch.pop("env"))
    for k, v in patch.items():
        next_values[k] = v

    DB_CONN.execute(
        """
        UPDATE mcp_servers
        SET name = ?, transport = ?, url = ?, command = ?, args_json = ?, env_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["transport"],
            next_values["url"],
            next_values["command"],
            next_values["args_json"],
            next_values["env_json"],
            server_id,
        ),
    )
    DB_CONN.commit()

    row = DB_CONN.execute(
        "SELECT * FROM mcp_servers WHERE id = ?", (server_id,)
    ).fetchone()
    return _serialize_mcp_row(row)


@app.delete("/api/mcp/servers/{server_id}")
def delete_mcp_server(server_id: int) -> dict:
    row = DB_CONN.execute("SELECT id, is_builtin FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if row["is_builtin"]:
        raise HTTPException(status_code=403, detail="Built-in MCP servers are locked and cannot be deleted")

    cur = DB_CONN.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    DB_CONN.commit()
    return {"deleted": True, "id": server_id}


@app.post("/api/mcp/servers/{server_id}/check")
async def check_mcp_server(server_id: int) -> dict:
    row = DB_CONN.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    status, last_error, report = await _run_protocol_checks_for_server(row)

    DB_CONN.execute(
        """
        UPDATE mcp_servers
        SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, last_error, server_id),
    )
    DB_CONN.commit()

    updated = DB_CONN.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    out = _serialize_mcp_row(updated)
    out["validation_report"] = report
    return out


@app.get("/api/widgets")
def list_widgets() -> list[dict]:
    rows = DB_CONN.execute(
        "SELECT * FROM dashboard_widgets ORDER BY id DESC"
    ).fetchall()
    return [_serialize_widget_row(r) for r in rows]


@app.post("/api/widgets")
def create_widget(payload: WidgetCreateRequest) -> dict:
    cur = DB_CONN.execute(
        """
        INSERT INTO dashboard_widgets(name, widget_type, layout_col, layout_row, layout_w, layout_h, config_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.name.strip(),
            payload.widget_type.strip(),
            payload.layout_col,
            payload.layout_row,
            payload.layout_w,
            payload.layout_h,
            json.dumps(payload.config),
        ),
    )
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_widget_row(row)


@app.patch("/api/widgets/{widget_id}")
def update_widget(widget_id: int, payload: WidgetUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (widget_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Widget not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "config" in patch:
        next_values["config_json"] = json.dumps(patch.pop("config"))
    for k, v in patch.items():
        next_values[k] = v

    DB_CONN.execute(
        """
        UPDATE dashboard_widgets
        SET name = ?, widget_type = ?, layout_col = ?, layout_row = ?, layout_w = ?, layout_h = ?,
            config_json = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["widget_type"],
            next_values["layout_col"],
            next_values["layout_row"],
            next_values["layout_w"],
            next_values["layout_h"],
            next_values["config_json"],
            widget_id,
        ),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (widget_id,)).fetchone()
    return _serialize_widget_row(updated)


@app.delete("/api/widgets/{widget_id}")
def delete_widget(widget_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM dashboard_widgets WHERE id = ?", (widget_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Widget not found")
    return {"deleted": True, "id": widget_id}


@app.get("/api/copilot/blueprint")
def copilot_blueprint() -> dict:
    return {
        "title": "Copilot Build Loop",
        "description": "Queue build tasks from the UI, then execute and iterate with Copilot in the same repo context.",
        "flow": [
            "Create task card from UI",
            "Refine in editor with Copilot",
            "Run checks and commit",
            "Attach result markdown to task",
        ],
        "note": "Direct tool invocation stays in VS Code/Copilot session, but this queue tracks and coordinates work.",
    }


@app.get("/api/copilot/tasks")
def list_copilot_tasks(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    rows = DB_CONN.execute(
        "SELECT * FROM copilot_tasks ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_serialize_copilot_task_row(r) for r in rows]


@app.post("/api/copilot/tasks")
def create_copilot_task(payload: CopilotTaskCreateRequest) -> dict:
    cur = DB_CONN.execute(
        """
        INSERT INTO copilot_tasks(title, description, status, context_json)
        VALUES (?, ?, 'queued', ?)
        """,
        (
            payload.title.strip(),
            payload.description.strip(),
            json.dumps(payload.context),
        ),
    )
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM copilot_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_copilot_task_row(row)


@app.patch("/api/copilot/tasks/{task_id}")
def update_copilot_task(task_id: int, payload: CopilotTaskUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM copilot_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    next_status = payload.status or row["status"]
    next_result = payload.result_markdown
    if next_result is None:
        next_result = row["result_markdown"]

    DB_CONN.execute(
        """
        UPDATE copilot_tasks
        SET status = ?, result_markdown = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (next_status, next_result, task_id),
    )
    DB_CONN.commit()

    updated = DB_CONN.execute("SELECT * FROM copilot_tasks WHERE id = ?", (task_id,)).fetchone()
    return _serialize_copilot_task_row(updated)


@app.get("/api/tasks")
def list_automation_tasks(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = DB_CONN.execute(
        "SELECT * FROM automation_tasks ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_serialize_automation_task_row(r) for r in rows]


@app.post("/api/tasks")
def create_automation_task(payload: AutomationTaskCreateRequest) -> dict:
    cur = DB_CONN.execute(
        """
        INSERT INTO automation_tasks(
            title, objective, trigger_type, status, sensitive_mode,
            local_context_json, cloud_prompt_template, runbook_markdown
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.title.strip(),
            payload.objective.strip(),
            payload.trigger_type,
            payload.status,
            payload.sensitive_mode,
            json.dumps(payload.local_context),
            payload.cloud_prompt_template,
            payload.runbook_markdown,
        ),
    )
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_automation_task_row(row)


@app.patch("/api/tasks/{task_id}")
def update_automation_task(task_id: int, payload: AutomationTaskUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "local_context" in patch:
        next_values["local_context_json"] = json.dumps(patch.pop("local_context"))
    for key, value in patch.items():
        next_values[key] = value

    DB_CONN.execute(
        """
        UPDATE automation_tasks
        SET title = ?, objective = ?, trigger_type = ?, status = ?, sensitive_mode = ?,
            local_context_json = ?, cloud_prompt_template = ?, runbook_markdown = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["title"],
            next_values["objective"],
            next_values["trigger_type"],
            next_values["status"],
            next_values["sensitive_mode"],
            next_values["local_context_json"],
            next_values["cloud_prompt_template"],
            next_values["runbook_markdown"],
            task_id,
        ),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    return _serialize_automation_task_row(updated)


@app.post("/api/tasks/{task_id}/run")
def run_automation_task(task_id: int) -> dict:
    row = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    DB_CONN.execute(
        """
        UPDATE automation_tasks
        SET run_count = run_count + 1, last_run_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (task_id,),
    )
    DB_CONN.commit()

    updated = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
    return {
        "ok": True,
        "task": _serialize_automation_task_row(updated),
        "note": "Run recorded. Wire this endpoint to local/cloud execution runtime next.",
    }


@app.delete("/api/tasks/{task_id}")
def delete_automation_task(task_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM automation_tasks WHERE id = ?", (task_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True, "id": task_id}


@app.get("/api/skills")
def list_skills(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = DB_CONN.execute(
        "SELECT * FROM skills ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_serialize_skill_row(r) for r in rows]


@app.post("/api/skills")
def create_skill(payload: SkillCreateRequest) -> dict:
    cur = DB_CONN.execute(
        """
        INSERT INTO skills(
            name, category, description, status, local_only,
            input_schema_json, output_schema_json, tool_contract_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.name.strip(),
            payload.category.strip(),
            payload.description.strip(),
            payload.status,
            1 if payload.local_only else 0,
            json.dumps(payload.input_schema),
            json.dumps(payload.output_schema),
            json.dumps(payload.tool_contract),
        ),
    )
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_skill_row(row)


@app.patch("/api/skills/{skill_id}")
def update_skill(skill_id: int, payload: SkillUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)
    if "local_only" in patch:
        next_values["local_only"] = 1 if patch.pop("local_only") else 0
    if "input_schema" in patch:
        next_values["input_schema_json"] = json.dumps(patch.pop("input_schema"))
    if "output_schema" in patch:
        next_values["output_schema_json"] = json.dumps(patch.pop("output_schema"))
    if "tool_contract" in patch:
        next_values["tool_contract_json"] = json.dumps(patch.pop("tool_contract"))
    for key, value in patch.items():
        next_values[key] = value

    DB_CONN.execute(
        """
        UPDATE skills
        SET name = ?, category = ?, description = ?, status = ?, local_only = ?,
            input_schema_json = ?, output_schema_json = ?, tool_contract_json = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["category"],
            next_values["description"],
            next_values["status"],
            next_values["local_only"],
            next_values["input_schema_json"],
            next_values["output_schema_json"],
            next_values["tool_contract_json"],
            skill_id,
        ),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    return _serialize_skill_row(updated)


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": True, "id": skill_id}


@app.post("/api/zen/act")
async def zen_action(payload: ZenActionRequest) -> dict:
    provider = _get_zen_provider(payload.provider)
    messages = _build_zen_messages(payload.domain, payload.prompt, payload.source_text)

    try:
        raw = await asyncio.wait_for(
            provider.complete_chat(
                messages=messages,
                model=payload.model,
                temperature=0.2,
                max_tokens=900,
            ),
            timeout=8.0,
        )
        parsed = _extract_json_object(raw)
    except Exception as exc:
        parsed, fallback_summary = _fallback_zen_plan(payload.domain, payload.prompt, payload.source_text)
        if not parsed:
            raise HTTPException(status_code=502, detail=f"Zen planning failed: {exc}") from exc
        reason = str(exc) or exc.__class__.__name__
        parsed["assistant_summary"] = f"{fallback_summary} (reason: {reason})"

    summary = parsed.pop("assistant_summary", "Zen action applied.")

    if payload.domain == "task_create":
        cur = DB_CONN.execute(
            """
            INSERT INTO automation_tasks(
                title, objective, trigger_type, status, sensitive_mode,
                local_context_json, cloud_prompt_template, runbook_markdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (parsed.get("title") or "Zen task").strip(),
                (parsed.get("objective") or payload.prompt).strip(),
                parsed.get("trigger_type") or "manual",
                parsed.get("status") or "draft",
                parsed.get("sensitive_mode") or "off",
                json.dumps(parsed.get("local_context") or {}),
                parsed.get("cloud_prompt_template"),
                parsed.get("runbook_markdown"),
            ),
        )
        DB_CONN.commit()
        row = DB_CONN.execute("SELECT * FROM automation_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": _serialize_automation_task_row(row)}

    if payload.domain == "skill_create":
        try:
            cur = DB_CONN.execute(
                """
                INSERT INTO skills(
                    name, category, description, status, local_only,
                    input_schema_json, output_schema_json, tool_contract_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (parsed.get("name") or "zen-skill").strip(),
                    (parsed.get("category") or "general").strip(),
                    (parsed.get("description") or payload.prompt).strip(),
                    parsed.get("status") or "draft",
                    1 if parsed.get("local_only") else 0,
                    json.dumps(parsed.get("input_schema") or {}),
                    json.dumps(parsed.get("output_schema") or {}),
                    json.dumps(parsed.get("tool_contract") or {}),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Skill name already exists") from exc
        DB_CONN.commit()
        row = DB_CONN.execute("SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": _serialize_skill_row(row)}

    if payload.domain == "note_create":
        title = (parsed.get("title") or "Zen note").strip()
        body = (parsed.get("body") or payload.prompt).strip()
        cur = DB_CONN.execute("INSERT INTO notes(title, body) VALUES (?, ?)", (title, body))
        note_id = cur.lastrowid
        chunks = split_into_chunks(body, settings.chunk_size, settings.chunk_overlap)
        for idx, chunk in enumerate(chunks):
            DB_CONN.execute(
                "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
                (note_id, idx, chunk),
            )
        DB_CONN.commit()
        return {
            "ok": True,
            "domain": payload.domain,
            "summary": summary,
            "record": {"id": note_id, "title": title, "body": body, "chunks_indexed": len(chunks)},
        }

    if payload.domain == "mcp_create":
        row = _insert_mcp_server_with_unique_name(parsed)
        status, last_error, report = await _run_protocol_checks_for_server(row)
        DB_CONN.execute(
            """
            UPDATE mcp_servers
            SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, last_error, row["id"]),
        )
        DB_CONN.commit()
        checked = DB_CONN.execute("SELECT * FROM mcp_servers WHERE id = ?", (row["id"],)).fetchone()
        out = _serialize_mcp_row(checked)
        out["validation_report"] = report
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": out}

    if payload.domain == "widget_create":
        cur = DB_CONN.execute(
            """
            INSERT INTO dashboard_widgets(name, widget_type, layout_col, layout_row, layout_w, layout_h, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (parsed.get("name") or "Zen widget").strip(),
                (parsed.get("widget_type") or "custom").strip(),
                max(1, int(parsed.get("layout_col") or 1)),
                max(1, int(parsed.get("layout_row") or 1)),
                max(1, int(parsed.get("layout_w") or 4)),
                max(1, int(parsed.get("layout_h") or 2)),
                json.dumps(parsed.get("config") or {}),
            ),
        )
        DB_CONN.commit()
        row = DB_CONN.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": _serialize_widget_row(row)}

    raise HTTPException(status_code=400, detail="Unsupported Zen domain")


@app.get("/api/integrations")
def list_integrations(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = DB_CONN.execute("SELECT * FROM integrations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_serialize_integration_row(r) for r in rows]


@app.post("/api/integrations")
def create_integration(payload: IntegrationCreateRequest) -> dict:
    if payload.api_key:
        _, key_error = _resolve_credential_secret_by_ref(payload.api_key)
        if key_error:
            raise HTTPException(status_code=400, detail=key_error)

    try:
        cur = DB_CONN.execute(
            """
            INSERT INTO integrations(name, provider_kind, base_url, auth_type, api_key, default_model, status, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.provider_kind.strip(),
                payload.base_url.strip() if payload.base_url else None,
                payload.auth_type,
                payload.api_key,
                payload.default_model,
                payload.status,
                json.dumps(payload.meta),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Integration name already exists") from exc
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM integrations WHERE id = ?", (cur.lastrowid,)).fetchone()
    _reload_providers_from_integrations()
    return _serialize_integration_row(row)


@app.patch("/api/integrations/{integration_id}")
def update_integration(integration_id: int, payload: IntegrationUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)

    if "api_key" in patch and patch["api_key"]:
        _, key_error = _resolve_credential_secret_by_ref(patch["api_key"])
        if key_error:
            raise HTTPException(status_code=400, detail=key_error)

    if "meta" in patch:
        next_values["meta_json"] = json.dumps(patch.pop("meta"))
    for key, value in patch.items():
        next_values[key] = value

    DB_CONN.execute(
        """
        UPDATE integrations
        SET name = ?, provider_kind = ?, base_url = ?, auth_type = ?, api_key = ?, default_model = ?,
            status = ?, meta_json = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            next_values["name"],
            next_values["provider_kind"],
            next_values["base_url"],
            next_values["auth_type"],
            next_values["api_key"],
            next_values["default_model"],
            next_values["status"],
            next_values["meta_json"],
            integration_id,
        ),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    _reload_providers_from_integrations()
    return _serialize_integration_row(updated)


@app.delete("/api/integrations/{integration_id}")
def delete_integration(integration_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Integration not found")
    _reload_providers_from_integrations()
    return {"deleted": True, "id": integration_id}


@app.post("/api/integrations/{integration_id}/sync-models")
async def sync_integration_models(integration_id: int) -> dict:
    row = DB_CONN.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not row["base_url"]:
        raise HTTPException(status_code=400, detail="Integration base_url is required for model sync")

    resolved_key, key_error = _resolve_credential_secret_by_ref(row["api_key"] or "")
    if key_error:
        raise HTTPException(status_code=400, detail=key_error)

    provider = OpenAICompatProvider(
        ProviderConfig(
            name=f"integration_{integration_id}",
            base_url=row["base_url"].rstrip("/"),
            default_model=row["default_model"] or "auto",
            api_key=resolved_key or "",
        )
    )

    try:
        models = await provider.list_models()
        model_ids = [m.get("id") for m in models if m.get("id")]
        status = "connected"
        error_note = None
    except Exception as exc:
        model_ids = []
        status = "error"
        error_note = str(exc)

    meta = _decode_json_field(row["meta_json"], {})
    if error_note:
        meta["last_error"] = error_note
    else:
        meta.pop("last_error", None)

    DB_CONN.execute(
        """
        UPDATE integrations
        SET models_json = ?, status = ?, meta_json = ?, last_sync_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (json.dumps(model_ids), status, json.dumps(meta), integration_id),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    _reload_providers_from_integrations()
    return _serialize_integration_row(updated)


@app.get("/api/integrations/oauth-templates")
def integration_oauth_templates() -> dict:
    return {
        "google": {
            "title": "Google / Vertex AI Bootstrap",
            "steps": [
                "gcloud auth login",
                "gcloud auth application-default login",
                "gcloud projects create <PROJECT_ID> --name=<PROJECT_NAME>",
                "gcloud config set project <PROJECT_ID>",
                "gcloud services enable aiplatform.googleapis.com",
                "Use ADC or service account creds, then register integration base_url as your gateway/litellm endpoint.",
            ],
        },
        "openrouter": {
            "title": "OpenRouter API key",
            "steps": [
                "Create API key in OpenRouter dashboard",
                "Set base_url to https://openrouter.ai/api/v1",
                "Store key in integration api_key field",
                "Sync models to populate model selector",
            ],
        },
        "groq": {
            "title": "Groq API key",
            "steps": [
                "Create API key in Groq console",
                "Set base_url to https://api.groq.com/openai/v1",
                "Sync models from integration card",
            ],
        },
    }


@app.get("/api/credentials")
def list_credentials(limit: int = 300) -> list[dict]:
    limit = max(1, min(limit, 1000))
    rows = DB_CONN.execute("SELECT * FROM credentials ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_serialize_credential_row(r) for r in rows]


@app.post("/api/credentials")
def create_credential(payload: CredentialCreateRequest) -> dict:
    name = _slug_for_credential_name(payload.name, "credential")
    try:
        cur = DB_CONN.execute(
            """
            INSERT INTO credentials(name, credential_type, provider, username, secret_encrypted, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                payload.credential_type,
                payload.provider.strip() if payload.provider else None,
                payload.username.strip() if payload.username else None,
                _encrypt_secret(payload.secret.strip()),
                json.dumps(payload.meta),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Credential name already exists") from exc

    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM credentials WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_credential_row(row)


@app.patch("/api/credentials/{credential_id}")
def update_credential(credential_id: int, payload: CredentialUpdateRequest) -> dict:
    row = DB_CONN.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)

    if "name" in patch and patch["name"]:
        next_values["name"] = _slug_for_credential_name(patch.pop("name"), next_values["name"])
    if "credential_type" in patch and patch["credential_type"]:
        next_values["credential_type"] = patch.pop("credential_type")
    if "provider" in patch:
        val = patch.pop("provider")
        next_values["provider"] = val.strip() if val else None
    if "username" in patch:
        val = patch.pop("username")
        next_values["username"] = val.strip() if val else None
    if "meta" in patch and patch["meta"] is not None:
        next_values["meta_json"] = json.dumps(patch.pop("meta"))
    if "secret" in patch and patch["secret"]:
        next_values["secret_encrypted"] = _encrypt_secret(patch.pop("secret").strip())
        next_values["last_rotated_at"] = "now"

    rotate = bool(patch.get("rotate"))
    if rotate and "secret" not in payload.model_fields_set:
        raise HTTPException(status_code=400, detail="Rotate requires a new secret value")

    try:
        DB_CONN.execute(
            """
            UPDATE credentials
            SET name = ?, credential_type = ?, provider = ?, username = ?, secret_encrypted = ?,
                meta_json = ?, last_rotated_at = CASE WHEN ? THEN datetime('now') ELSE last_rotated_at END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                next_values["name"],
                next_values["credential_type"],
                next_values["provider"],
                next_values["username"],
                next_values["secret_encrypted"],
                next_values["meta_json"],
                rotate or ("secret" in payload.model_fields_set and bool(payload.secret)),
                credential_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Credential name already exists") from exc

    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    return _serialize_credential_row(updated)


@app.delete("/api/credentials/{credential_id}")
def delete_credential(credential_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"deleted": True, "id": credential_id}


@app.post("/api/credentials/import-env")
def import_credentials_from_env(payload: CredentialEnvImportRequest) -> dict:
    env_pairs = dotenv_values(stream=StringIO(payload.env_text))
    imported: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []

    provider_slug = _slug_for_credential_name(payload.provider or "env", "env")
    for key, raw_value in env_pairs.items():
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue

        cred_name = _slug_for_credential_name(f"{provider_slug}-{key.lower()}", f"{provider_slug}-cred")
        existing = DB_CONN.execute("SELECT * FROM credentials WHERE name = ?", (cred_name,)).fetchone()
        if existing and not payload.overwrite:
            skipped.append(cred_name)
            continue

        meta = {
            "source": "env_import",
            "source_env_key": key,
        }
        if existing:
            DB_CONN.execute(
                """
                UPDATE credentials
                SET credential_type = ?, provider = ?, secret_encrypted = ?, meta_json = ?,
                    last_rotated_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    payload.credential_type,
                    payload.provider,
                    _encrypt_secret(value),
                    json.dumps(meta),
                    existing["id"],
                ),
            )
            updated.append(cred_name)
        else:
            DB_CONN.execute(
                """
                INSERT INTO credentials(name, credential_type, provider, username, secret_encrypted, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cred_name,
                    payload.credential_type,
                    payload.provider,
                    None,
                    _encrypt_secret(value),
                    json.dumps(meta),
                ),
            )
            imported.append(cred_name)

    DB_CONN.commit()
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total_processed": len(imported) + len(updated) + len(skipped),
    }


@app.get("/api/credentials/connectors")
def list_credential_connectors() -> dict:
    return CREDENTIAL_CONNECTOR_CATALOG


@app.post("/api/credentials/connectors/launch")
def launch_credential_connector(payload: ConnectorLaunchRequest) -> dict:
    provider = payload.provider.strip().lower()
    config = CREDENTIAL_CONNECTOR_CATALOG.get(provider)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown connector provider")

    launched = False
    launch_error = None
    if payload.open_browser:
        try:
            launched = bool(webbrowser.open(config["auth_url"], new=2, autoraise=True))
        except Exception as exc:
            launch_error = str(exc)

    return {
        "provider": provider,
        "title": config["title"],
        "auth_url": config["auth_url"],
        "suggested_env": config["suggested_env"],
        "credential_type": config["credential_type"],
        "launched": launched,
        "launch_error": launch_error,
    }


@app.get("/api/projects/capabilities")
def project_capabilities() -> dict:
    cli = _detect_copilot_cli()
    system = platform.system().lower()
    picker_available = False
    if system == "linux":
        picker_available = bool(shutil.which("zenity") or shutil.which("kdialog"))
    elif system == "darwin":
        picker_available = True
    elif system == "windows":
        picker_available = True
    return {
        "projects_root": str(_projects_root()),
        "copilot_cli": cli,
        "supported_kinds": ["app", "website", "service", "library", "workspace"],
        "folder_picker_available": picker_available,
        "preview_allowed_hosts": ["localhost"] + _discover_local_ipv4(),
    }


@app.get("/api/projects")
def list_projects() -> list[dict]:
    rows = DB_CONN.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [_serialize_project_row(r) for r in rows]


@app.post("/api/projects/discover")
def discover_projects_from_root() -> dict:
    imported = _discover_projects_from_root()
    return {
        "imported": imported,
        "count": len(imported),
        "root": str(_projects_root()),
    }


@app.post("/api/projects")
def create_project(payload: ProjectCreateRequest) -> dict:
    root = _projects_root()
    slug = _next_project_slug(payload.name)
    project_path = (root / slug).resolve()
    project_path.mkdir(parents=True, exist_ok=False)

    cur = DB_CONN.execute(
        """
        INSERT INTO projects(name, slug, path, kind, status, stack_json, last_opened_at)
        VALUES (?, ?, ?, ?, 'active', ?, datetime('now'))
        """,
        (payload.name.strip(), slug, str(project_path), payload.kind, json.dumps(payload.stack or {})),
    )
    DB_CONN.commit()
    row = DB_CONN.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _serialize_project_row(row)


@app.post("/api/projects/import")
def import_project(payload: ProjectImportRequest) -> dict:
    return _upsert_project_from_path(payload.path, name=payload.name, kind=payload.kind)


@app.post("/api/projects/browse")
def browse_and_import_project() -> dict:
    selected = _open_native_directory_picker()
    if not selected:
        raise HTTPException(status_code=400, detail="No folder selected")
    project = _upsert_project_from_path(selected, kind="workspace")
    return {
        "selected_path": selected,
        "project": project,
    }


@app.get("/api/projects/{project_id}")
def get_project(project_id: int) -> dict:
    row, _ = _project_row_and_path(project_id)
    DB_CONN.execute("UPDATE projects SET last_opened_at = datetime('now'), updated_at = datetime('now') WHERE id = ?", (project_id,))
    DB_CONN.commit()
    return _serialize_project_row(row)


@app.patch("/api/projects/{project_id}/preview")
def update_project_preview(project_id: int, payload: ProjectPreviewUpdateRequest) -> dict:
    row, _ = _project_row_and_path(project_id)
    DB_CONN.execute(
        "UPDATE projects SET dev_url = ?, updated_at = datetime('now') WHERE id = ?",
        ((payload.dev_url or "").strip() or None, project_id),
    )
    DB_CONN.commit()
    updated = DB_CONN.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _serialize_project_row(updated or row)


@app.get("/api/projects/{project_id}/scripts")
def get_project_scripts(project_id: int) -> dict:
    _, project_path = _project_row_and_path(project_id)
    scripts = _discover_project_scripts(project_path)
    return {
        "project_id": project_id,
        "scripts": scripts,
    }


@app.post("/api/projects/{project_id}/scripts/run")
def run_project_script(project_id: int, payload: ProjectScriptRunRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(status_code=403, detail="System access is disabled. Set allow_system_access=true to run scripts.")

    _, project_path = _project_row_and_path(project_id)
    scripts = _discover_project_scripts(project_path)
    script_row = next((s for s in scripts if s["key"] == payload.script_key), None)
    if not script_row:
        raise HTTPException(status_code=404, detail="Script not found")

    runtime = _start_project_runtime(project_id, script_row)
    DB_CONN.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    DB_CONN.commit()
    return runtime


@app.get("/api/projects/{project_id}/runtimes")
def list_project_runtimes(project_id: int) -> dict:
    _project_row_and_path(project_id)
    return {
        "project_id": project_id,
        "runtimes": _list_project_runtimes(project_id),
    }


@app.get("/api/projects/{project_id}/runtimes/{runtime_id}/logs")
def get_project_runtime_logs(project_id: int, runtime_id: str, lines: int = 200) -> dict:
    _project_row_and_path(project_id)
    return _runtime_logs(project_id, runtime_id, lines=lines)


@app.post("/api/projects/{project_id}/runtimes/{runtime_id}/stop")
def stop_project_runtime(project_id: int, runtime_id: str) -> dict:
    _project_row_and_path(project_id)
    return _stop_runtime(project_id, runtime_id)


@app.get("/api/projects/{project_id}/tree")
def get_project_tree(project_id: int, relative_path: str = ".", depth: int = 1, limit: int = 200) -> dict:
    _, project_path = _project_row_and_path(project_id)
    depth = max(1, min(depth, 4))
    limit = max(1, min(limit, 1000))

    start_path = _safe_child_path(project_path, relative_path)
    if not start_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not start_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: list[dict] = []

    def walk(current: Path, level: int) -> None:
        nonlocal entries
        if level > depth or len(entries) >= limit:
            return
        for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if len(entries) >= limit:
                return
            rel = child.relative_to(project_path)
            entries.append({
                **_project_tree_entry(child, project_path),
                "depth": level,
                "parent": str(rel.parent) if str(rel.parent) != "." else ".",
            })
            if child.is_dir() and level < depth:
                walk(child, level + 1)

    walk(start_path, 1)
    return {
        "project_id": project_id,
        "root": str(project_path),
        "relative_path": str(start_path.relative_to(project_path)) if start_path != project_path else ".",
        "entries": entries,
    }


@app.post("/api/projects/{project_id}/mkdir")
def create_project_directory(project_id: int, payload: ProjectMkdirRequest) -> dict:
    _, project_path = _project_row_and_path(project_id)
    target = _safe_child_path(project_path, payload.relative_path)
    target.mkdir(parents=True, exist_ok=True)
    DB_CONN.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    DB_CONN.commit()
    return {
        "project_id": project_id,
        "created": True,
        "relative_path": str(target.relative_to(project_path)),
    }


@app.post("/api/projects/{project_id}/run-command")
def run_project_command(project_id: int, payload: ProjectCommandRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(status_code=403, detail="System access is disabled. Set allow_system_access=true to run commands.")

    _, project_path = _project_row_and_path(project_id)
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
    DB_CONN.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    DB_CONN.commit()
    return {
        "project_id": project_id,
        "cwd": str(project_path),
        "command": payload.command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/projects/{project_id}/copilot-cli")
def run_project_copilot_cli(project_id: int, payload: ProjectCopilotCliRequest) -> dict:
    if not payload.allow_system_access:
        raise HTTPException(status_code=403, detail="System access is disabled. Set allow_system_access=true to run Copilot CLI.")

    _, project_path = _project_row_and_path(project_id)
    args = _build_copilot_cli_args(payload.prompt, payload.target)

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
    DB_CONN.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))
    DB_CONN.commit()
    return {
        "project_id": project_id,
        "cwd": str(project_path),
        "command": args,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/sensitive/redact-preview")
def sensitive_redact_preview(payload: SensitiveRedactPreviewRequest) -> dict:
    text = payload.text
    matches: list[tuple[int, int, str, str]] = []
    for kind, pattern in SENSITIVE_PATTERNS.items():
        for match in pattern.finditer(text):
            token_text = match.group(0)
            if kind == "GENERIC_SECRET" and match.lastindex and match.lastindex >= 2:
                token_text = match.group(2)
                start = match.start(2)
                end = match.end(2)
            else:
                start = match.start(0)
                end = match.end(0)
            matches.append((start, end, kind, token_text))

    for manual in payload.manual_tags:
        if manual:
            idx = text.find(manual)
            if idx != -1:
                matches.append((idx, idx + len(manual), "MANUAL_TAG", manual))

    approved: dict[str, str] = {}
    redacted = text
    dedup = []
    for start, end, kind, value in sorted(matches, key=lambda x: x[0], reverse=True):
        if any(start >= s and end <= e for s, e, _, _ in dedup):
            continue
        if value in payload.manual_untags:
            continue
        token = f"{{{kind}_{len(approved) + 1}}}"
        approved[token] = value
        redacted = redacted[:start] + token + redacted[end:]
        dedup.append((start, end, kind, value))

    return {
        "original": text,
        "redacted": redacted,
        "approved_tokens": approved,
        "detected_count": len(approved),
    }


@app.post("/api/sensitive/unredact")
def sensitive_unredact(payload: SensitiveRedactApplyRequest) -> dict:
    text = payload.text
    for token, value in payload.approved_tokens.items():
        text = text.replace(token, value)
    return {"text": text}


# ---------------------------------------------------------------------------
# Notes management
# ---------------------------------------------------------------------------

@app.get("/api/notes")
def list_notes(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 1000))
    rows = DB_CONN.execute(
        "SELECT id, title, body, created_at FROM notes ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return rows_to_dicts(rows)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    cur = DB_CONN.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    DB_CONN.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True, "id": note_id}


# ---------------------------------------------------------------------------
# MCP VS Code config export + HTTP relay
# ---------------------------------------------------------------------------

@app.get("/api/mcp/vscode-config")
def mcp_vscode_config() -> dict:
    """Generate a VS Code settings.json snippet for all registered MCP servers."""
    rows = DB_CONN.execute("SELECT * FROM mcp_servers ORDER BY id ASC").fetchall()
    servers: dict[str, dict] = {}

    for row in rows:
        s = _serialize_mcp_row(row)
        name = s["name"]
        env = s.get("env") or {}

        if s["transport"] == "stdio":
            cmd_str = (s.get("command") or "").strip()
            cmd_parts = shlex.split(cmd_str) if cmd_str else []
            if not cmd_parts:
                continue
            vscode_env: dict[str, str] = {}
            for k, v in env.items():
                is_ref = isinstance(v, str) and bool(CRED_REF_PATTERN.match(v.strip()))
                is_placeholder = isinstance(v, str) and v.strip() in ("<required>", "")
                vscode_env[k] = f"${{env:{k}}}" if (is_ref or is_placeholder) else v
            entry: dict = {"type": "stdio", "command": cmd_parts[0], "args": cmd_parts[1:] + (s.get("args") or [])}
            if vscode_env:
                entry["env"] = vscode_env
            servers[name] = entry

        elif s["transport"] in ("http", "sse"):
            url = s.get("url")
            if not url:
                continue
            servers[name] = {"type": "http", "url": url}

    addresses = _discover_local_ipv4()
    relay_url = f"http://{addresses[0] if addresses else '127.0.0.1'}:{settings.port}/mcp"

    return {
        "relay_url": relay_url,
        "instructions": (
            "Option A — Paste 'relay_only_snippet' into VS Code settings.json to route all HTTP MCP traffic "
            "through this CrowPilot hub in a single entry. "
            "Option B — Paste 'all_servers_snippet' to configure every server individually "
            "(stdio servers run as local subprocesses inside VS Code)."
        ),
        "relay_only_snippet": json.dumps(
            {"mcp": {"servers": {"crowpilot-relay": {"type": "http", "url": relay_url}}}}, indent=2
        ),
        "all_servers_snippet": json.dumps({"mcp": {"servers": servers}}, indent=2),
    }


@app.get("/mcp")
async def mcp_relay_info() -> dict:
    return {
        "name": "crowpilot-relay",
        "version": "1.0.0",
        "description": "CrowPilot MCP relay — aggregates HTTP-based MCP servers registered in this hub.",
        "protocol": "mcp-streamable-http",
        "tools_from_transport": ["http", "sse"],
        "note": "stdio servers must be configured individually in VS Code; see /api/mcp/vscode-config.",
    }


@app.post("/mcp")
async def mcp_relay(request: Request):
    """MCP Streamable HTTP relay. VS Code can point a single 'http' MCP server entry here."""
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params") or {}

    # Notifications have no id and require no response body
    if req_id is None and method.startswith("notifications/"):
        return {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "crowpilot-relay", "version": "1.0.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        tools = await _relay_list_tools()
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        tool_name = (params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        if not tool_name:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing tool name"}}
        result = await _relay_call_tool(tool_name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


# ---------------------------------------------------------------------------
# Project context summary
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/context-summary")
def get_project_context_summary(project_id: int) -> dict:
    """Return README, package.json, and top-level file tree for LLM context injection."""
    _, project_path = _project_row_and_path(project_id)

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
