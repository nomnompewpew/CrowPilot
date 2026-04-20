from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..services.memory import queue_size
from ..services.native_tools import _safe_path
from ..services.server_stats import get_server_stats
from ..state import g
from ..utils import discover_local_ipv4

router = APIRouter(tags=["system"])


# ── Monaco Editor file endpoints ─────────────────────────────────────────────

class _FsReadReq(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None


class _FsWriteReq(BaseModel):
    path: str
    content: str


@router.post("/api/agent/fs/read")
def agent_fs_read(req: _FsReadReq) -> dict:
    p, err = _safe_path(req.path, must_exist=True)
    if err:
        return {"ok": False, "error": err}
    if not p.is_file():
        return {"ok": False, "error": "path is a directory"}
    try:
        raw = p.read_bytes()
        # Reject obvious binaries
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "error": "file appears to be binary"}
        lines = text.splitlines(keepends=True)
        if req.start_line or req.end_line:
            s = max(0, (req.start_line or 1) - 1)
            e = req.end_line or len(lines)
            lines = lines[s:e]
        if len(lines) > 5000:
            return {"ok": False, "error": f"file too large ({len(lines)} lines); use start_line/end_line"}
        return {"ok": True, "content": "".join(lines), "path": str(p)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/agent/fs/write")
def agent_fs_write(req: _FsWriteReq) -> dict:
    p, err = _safe_path(req.path)
    if err:
        return {"ok": False, "error": err}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(req.content, encoding="utf-8")
        return {"ok": True, "path": str(p), "bytes": len(req.content.encode())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/memory/queue-size")
def memory_queue_size() -> dict:
    return {"pending": queue_size()}


@router.get("/api/health")
async def health() -> dict:
    checks = {}
    for name, provider in g.providers.items():
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


@router.get("/api/hub/access")
def hub_access() -> dict:
    addresses = discover_local_ipv4()
    return {
        "configured_host": settings.host,
        "port": settings.port,
        "local_addresses": addresses,
        "reachable_urls": [f"http://{addr}:{settings.port}" for addr in addresses],
        "note": "Set PANTHEON_HOST=0.0.0.0 to allow other LAN devices to access this CrowPilot hub.",
    }


@router.get("/api/models")
async def list_models_for_provider(provider: str | None = None) -> dict:
    if provider:
        p = g.providers.get(provider)
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

    result = {}
    for name, p in g.providers.items():
        try:
            models = await p.list_models()
            model_ids = [m.get("id") for m in models if m.get("id")]
            if name == "copilot_proxy" and "auto" not in model_ids:
                model_ids.insert(0, "auto")
            result[name] = {"ok": True, "models": model_ids, "default_model": p.cfg.default_model}
        except Exception as exc:
            result[name] = {
                "ok": False,
                "error": str(exc),
                "models": [],
                "default_model": p.cfg.default_model,
            }
    return result


@router.get("/api/dashboard/summary")
async def dashboard_summary() -> dict:
    providers_status = (await health())["providers"]

    counts = {
        "conversations": g.db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
        "messages": g.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "notes": g.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
        "mcp_servers": g.db.execute("SELECT COUNT(*) FROM mcp_servers").fetchone()[0],
        "widgets": g.db.execute("SELECT COUNT(*) FROM dashboard_widgets").fetchone()[0],
        "copilot_tasks": g.db.execute("SELECT COUNT(*) FROM copilot_tasks").fetchone()[0],
        "automation_tasks": g.db.execute("SELECT COUNT(*) FROM automation_tasks").fetchone()[0],
        "skills": g.db.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
        "integrations": g.db.execute("SELECT COUNT(*) FROM integrations").fetchone()[0],
        "credentials": g.db.execute("SELECT COUNT(*) FROM credentials").fetchone()[0],
        "projects": g.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
    }

    return {
        "edition": settings.edition,
        "runtime_profile": settings.runtime_profile,
        "counts": counts,
        "providers": providers_status,
        "tagline": "CrowPilot command center for MCP, model routing, and local knowledge.",
    }


@router.get("/api/providers/{provider_name}/models")
async def list_provider_models(provider_name: str) -> dict:
    provider = g.providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")
    try:
        models = await provider.list_models()
        return {"provider": provider_name, "models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Server stats (Linux + QEMU)
# ---------------------------------------------------------------------------

@router.get("/api/system/server-stats")
def server_stats() -> dict:
    """
    Snapshot of the host machine: CPU, memory, disk, all network interfaces,
    primary LAN IP (great for building the MCP relay URL), and QEMU/KVM
    detection with guest agent status if the virtio port is present.
    """
    return get_server_stats(port=settings.port)


# ---------------------------------------------------------------------------
# Contextual help / on-rails guidance
# ---------------------------------------------------------------------------

@router.get("/api/system/help")
def system_help() -> dict:
    """
    Comprehensive feature guide returned as structured JSON.
    The frontend can surface this wherever context is needed — tooltips,
    empty states, Zen mode sidebar, onboarding wizard, etc.
    """
    addresses = discover_local_ipv4()
    primary_ip = next((a for a in addresses if not a.startswith("127.")), addresses[0] if addresses else "127.0.0.1")
    base_url = f"http://{primary_ip}:{settings.port}"

    return {
        "overview": {
            "title": "CrowPilot — Your Local AI Command Center",
            "description": (
                "CrowPilot is a self-hosted AI hub that runs on your own server. "
                "It routes chat requests to local and cloud AI models, aggregates MCP tool servers "
                "into a single relay endpoint, stores knowledge in a local FTS5 database, "
                "and orchestrates project runtimes and automation — all without sending your data "
                "to a third-party service unless you explicitly add one."
            ),
            "server_url": base_url,
            "mcp_relay_url": f"{base_url}/mcp",
            "access_from_lan": (
                f"Any device on your local network can reach this hub at {base_url}. "
                "The server must be started with PANTHEON_HOST=0.0.0.0 to accept LAN connections."
            ),
        },
        "sections": {
            "chat": {
                "title": "Chat",
                "description": (
                    "Talk directly to any configured AI provider. Conversations are stored locally "
                    "and can be searched, archived, or used as memory context in future chats. "
                    "The chat engine automatically injects relevant notes from your knowledge base."
                ),
                "how_to_use": [
                    "Select a provider and model from the top bar.",
                    "Type your message and press Enter (or the send button).",
                    "Conversations are auto-saved — find them in the sidebar.",
                    "Use the knowledge search (🔍) to pull relevant notes into context before sending.",
                ],
                "tips": [
                    "Long conversations are automatically chunked so context windows stay manageable.",
                    "Archive conversations you want to keep but not see in the main list.",
                    "Delete conversations to free up database space.",
                ],
            },
            "zen": {
                "title": "Zen Mode — AI-Powered One-Shot Creation",
                "description": (
                    "Describe what you want in plain language. Zen sends your description to the best "
                    "available AI provider and creates the record for you automatically — no forms, "
                    "no manual field-filling. It works for tasks, skills, MCP servers, notes, and widgets."
                ),
                "domains": [
                    {
                        "id": "task_create",
                        "label": "Create an Automation Task",
                        "description": "Turn a plain-language objective into a structured automation task with trigger type, runbook, and local context pre-filled.",
                        "example_prompt": "A weekly task that checks disk usage on this server and alerts if it's over 80%",
                        "what_gets_created": "An automation_task row with title, objective, trigger_type, runbook_markdown, and local_context.",
                    },
                    {
                        "id": "skill_create",
                        "label": "Create a Skill",
                        "description": "Define a reusable capability with input/output schemas and a tool contract. Skills are the building blocks for automation.",
                        "example_prompt": "A skill that takes a git diff and produces a conventional commit message",
                        "what_gets_created": "A skills row with name, category, description, input_schema, output_schema, and tool_contract.",
                    },
                    {
                        "id": "note_create",
                        "label": "Create a Knowledge Note",
                        "description": "Capture anything — procedures, references, context — and have it indexed for full-text search and RAG retrieval.",
                        "example_prompt": "Document how to restart the Pantheon server and update its MCP configuration",
                        "what_gets_created": "A note row + indexed FTS5 chunks for semantic retrieval in chat.",
                    },
                    {
                        "id": "mcp_create",
                        "label": "Add an MCP Server",
                        "description": "Register an HTTP or SSE MCP server by describing it. Zen fills in the transport, URL, and runs a protocol check automatically.",
                        "example_prompt": "Add an HTTP MCP server running locally at port 3000 called my-tools",
                        "what_gets_created": "An mcp_servers row. The server is immediately checked for connectivity.",
                    },
                    {
                        "id": "widget_create",
                        "label": "Add a Dashboard Widget",
                        "description": "Describe a widget and where it should go on the dashboard grid. Zen picks the type and layout.",
                        "example_prompt": "A server memory usage widget in the top-right corner of the dashboard",
                        "what_gets_created": "A dashboard_widgets row with name, widget_type, layout position, and config.",
                    },
                ],
                "tips": [
                    "Be specific about what the thing should DO, not how to build it.",
                    "You can paste existing JSON config snippets and say 'onboard this as an MCP server'.",
                    "If Zen picks the wrong domain, switch the selector manually before sending.",
                    "Zen uses your fastest responding provider. Add integrations (Groq, OpenRouter) for faster results.",
                    "Everything Zen creates can be edited normally afterwards — it's not locked.",
                ],
            },
            "mcp": {
                "title": "MCP Servers (Model Context Protocol)",
                "description": (
                    "MCP is an open protocol that lets AI models call external tools — file access, "
                    "web search, database queries, custom APIs. CrowPilot aggregates all registered "
                    "HTTP/SSE MCP servers behind a single relay endpoint. Point VS Code (or any MCP "
                    "client) at that one URL and get all your tools at once."
                ),
                "relay_url": f"{base_url}/mcp",
                "vscode_config_url": f"{base_url}/api/mcp/vscode-config",
                "transports_supported": ["http", "sse"],
                "how_to_add_a_server": [
                    "Go to MCP Forge tab.",
                    "Click Add Server and fill in the transport (HTTP or SSE), URL or command.",
                    "CrowPilot runs a protocol check — green means the tools are being relayed.",
                    "Or use Zen mode with domain 'mcp_create' to add by description.",
                ],
                "how_to_connect_vscode": [
                    f"Call GET {base_url}/api/mcp/vscode-config to get a ready-made settings.json snippet.",
                    "Paste the snippet into your VS Code settings.json (user or workspace level).",
                    "VS Code will show CrowPilot as an MCP server and list all aggregated tools.",
                    f"The relay URL is: {base_url}/mcp",
                ],
                "built_in_servers": [
                    "CrowPilot ships with built-in MCP servers for knowledge retrieval and task management.",
                    "Built-in servers cannot be deleted but can be disabled.",
                ],
            },
            "integrations": {
                "title": "AI Provider Integrations",
                "description": (
                    "Integrations connect CrowPilot to AI model providers beyond the built-in Copilot proxy. "
                    "Any OpenAI-compatible endpoint works: Groq, OpenRouter, Ollama, LM Studio, Vertex AI via "
                    "a gateway, or your own fine-tuned model server."
                ),
                "how_to_add": [
                    "Go to Integrations tab and click Add Integration.",
                    "Enter a name, the base URL (e.g. https://api.groq.com/openai/v1), and your API key.",
                    "Click Sync Models to fetch the provider's model list.",
                    "The integration will appear as a selectable provider in Chat.",
                ],
                "popular_providers": [
                    {
                        "name": "Groq",
                        "base_url": "https://api.groq.com/openai/v1",
                        "note": "Extremely fast inference, free tier available. Get key at console.groq.com.",
                    },
                    {
                        "name": "OpenRouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "note": "Aggregates 200+ models from many providers. Single API key.",
                    },
                    {
                        "name": "Ollama (local)",
                        "base_url": "http://localhost:11434/v1",
                        "note": "Run models locally. No API key needed. Install from ollama.ai.",
                    },
                    {
                        "name": "LM Studio (local)",
                        "base_url": "http://localhost:1234/v1",
                        "note": "GUI-based local model runner. Start the local server in LM Studio first.",
                    },
                ],
                "credential_refs": (
                    "API keys can be stored in the Credentials vault and referenced by name "
                    "(e.g. cred:my-groq-key) instead of pasting the raw key into the integration form."
                ),
            },
            "credentials": {
                "title": "Credentials Vault",
                "description": (
                    "Securely store API keys, tokens, and secrets. Values are encrypted with Fernet "
                    "symmetric encryption before being written to the database. Reference stored credentials "
                    "in integrations using the 'cred:name' syntax so the raw key is never stored in plaintext "
                    "alongside the integration config."
                ),
                "how_to_use": [
                    "Go to Credentials tab and click Add Credential.",
                    "Give it a name (becomes the slug, e.g. 'my-groq-key').",
                    "Enter the secret value — it is encrypted immediately.",
                    "In an integration's API key field, type 'cred:my-groq-key' to reference it.",
                    "Use Import from .env to bulk-import an existing .env file.",
                ],
                "connectors": [
                    "GitHub, HuggingFace, OpenAI, Anthropic connectors open the provider's API key page directly.",
                ],
            },
            "knowledge": {
                "title": "Knowledge Base (Notes + RAG)",
                "description": (
                    "Write notes in Markdown and they are automatically chunked and indexed in SQLite FTS5 "
                    "for full-text search. The chat engine retrieves relevant chunks and injects them as "
                    "context before sending your message to the AI — this is local Retrieval-Augmented Generation."
                ),
                "how_to_use": [
                    "Go to Knowledge tab and click Add Note.",
                    "Write in Markdown — headings, code blocks, and lists all work.",
                    "Use Search Notes to find existing content.",
                    "In Chat, the system automatically retrieves relevant notes for each message.",
                    "Or use Zen mode with domain 'note_create' to have AI draft the note for you.",
                ],
                "tips": [
                    "Store runbooks, procedures, API references, and architecture docs here.",
                    "The more specific and well-structured a note, the better it retrieves.",
                    "Notes are searchable by full-text — no need for exact phrasing.",
                ],
            },
            "projects": {
                "title": "Projects",
                "description": (
                    "Manage local code repositories and workspaces. CrowPilot can scan your projects "
                    "root directory, detect package managers, discover runnable scripts, launch dev servers "
                    "as tracked subprocesses, and feed the project's README and file tree into AI context."
                ),
                "how_to_use": [
                    "Go to Projects tab and click Discover to auto-import all projects under the projects root.",
                    "Click Import to add a project from an arbitrary path.",
                    "Click Browse to use a native folder picker (requires zenity on Linux).",
                    "From a project card, run scripts, view the file tree, or get a context summary for AI.",
                ],
                "runtime_management": [
                    "Start a dev server from the Scripts panel — it runs as a tracked subprocess.",
                    "View live logs from the Runtimes panel.",
                    "Stop the runtime when done.",
                ],
                "copilot_cli": (
                    "If GitHub Copilot CLI is installed, you can run 'gh copilot suggest' prompts "
                    "directly from the project context via the Copilot CLI panel."
                ),
            },
            "tasks": {
                "title": "Tasks",
                "description": (
                    "Two task systems live here: Automation Tasks (scheduled/triggered local jobs with "
                    "runbooks and local context) and Copilot Tasks (a queue of build objectives you work "
                    "through with AI assistance in VS Code)."
                ),
                "automation_tasks": [
                    "Create with Zen mode ('task_create') or the manual form.",
                    "Define trigger_type: manual, cron, webhook, or event.",
                    "Attach a runbook (Markdown) — the step-by-step instructions for execution.",
                    "local_context carries structured data available to the task at runtime.",
                    "Click Run to increment the run counter (execution engine is pluggable).",
                ],
                "copilot_tasks": [
                    "A simple kanban queue: queued → in_progress → done.",
                    "Each task has a title, description, and optional result markdown.",
                    "Use these to track what you're asking Copilot to build in your VS Code session.",
                ],
            },
            "skills": {
                "title": "Skills",
                "description": (
                    "Skills are typed, reusable capability definitions with formal input/output schemas "
                    "and an optional MCP-compatible tool contract. They serve as the registry of "
                    "what your system can do — referenced by automation tasks, Zen mode, and MCP tool routing."
                ),
                "how_to_use": [
                    "Create with Zen mode ('skill_create') or the manual form.",
                    "Define input_schema and output_schema as JSON Schema objects.",
                    "Set local_only=true for skills that must never leave this server.",
                    "Set status=active when the skill is implemented and ready to use.",
                ],
            },
            "widgets": {
                "title": "Dashboard Widgets",
                "description": (
                    "Configurable panels on the main dashboard. Each widget has a type, grid position "
                    "(col, row, width, height), and a free-form config JSON blob that the frontend "
                    "uses to render it."
                ),
                "how_to_use": [
                    "Go to Dashboard and click Add Widget.",
                    "Or use Zen mode ('widget_create') to describe a widget in plain language.",
                    "Drag and drop widgets to rearrange (if the frontend supports it).",
                    "Edit config_json to customize what data the widget shows.",
                ],
            },
            "server": {
                "title": "This Server",
                "description": (
                    "CrowPilot runs on your local machine or a dedicated Debian/Linux server. "
                    "If the server has QEMU/KVM, the /api/system/server-stats endpoint reports "
                    "full system metrics including the QEMU guest agent version and all network "
                    "interface IPs — useful for LAN access and MCP relay configuration."
                ),
                "endpoints": {
                    "server_stats": f"{base_url}/api/system/server-stats",
                    "hub_access": f"{base_url}/api/hub/access",
                    "mcp_relay": f"{base_url}/mcp",
                    "mcp_vscode_config": f"{base_url}/api/mcp/vscode-config",
                    "health": f"{base_url}/api/health",
                    "openapi_docs": f"{base_url}/docs",
                },
                "lan_access_setup": [
                    "Edit backend/.env and set PANTHEON_HOST=0.0.0.0",
                    "Restart the server: ./run.sh",
                    f"Access from any device on your network at {base_url}",
                    "The MCP relay is at {base_url}/mcp — paste this into VS Code on any LAN device.",
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Live log stream (SSE)
# ---------------------------------------------------------------------------

@router.get("/api/system/logs/stream")
async def stream_logs() -> StreamingResponse:
    """
    Server-Sent Events stream of CrowPilot server log lines.
    Replays the last 500 buffered lines on connect, then streams live.
    """
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=2000)
    g.log_queues.append(q)

    async def _generate():
        # Send backlog first so the UI shows history immediately.
        for line in list(g.log_ring):
            yield f"data: {json.dumps(line)}\n\n"

        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(line)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping so the browser connection stays open.
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                g.log_queues.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
