from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from .corbin import CORBIN_DEFAULT_PROMPT

_DIRECTORIES = ("memory", "env", "personality", "mcp", "skills", "hardware")

_WORKSPACE_MANIFEST = {
    "version": 1,
    "name": "Corbin workspace",
    "agent_home": ".corbin",
    "runtime_profile": "desktop",
    "directories": {
        "memory": "memory",
        "env": "env",
        "personality": "personality",
        "mcp": "mcp",
        "skills": "skills",
        "hardware": "hardware",
    },
    "notes": [
        "Use env/*.env.example as starting points, then copy to local files outside git.",
        "Keep secrets and host-specific overrides in *.local files only.",
        "Corbin falls back to personality/corbin-system-prompt.txt when the DB has no custom prompt.",
    ],
}

_HARDWARE_PROFILES = {
    "version": 1,
    "default_profile": "desktop",
    "profiles": [
        {
            "id": "raspberry-pi",
            "label": "Raspberry Pi / entry-level",
            "summary": "CPU-first deployment with deferred background embedding work.",
            "scan": {
                "base_url": "http://127.0.0.1:8083/v1",
                "model": "Llama-3.2-1B-Instruct-Q4_0_4_4.gguf",
                "prompt_mode": "instruction",
                "reason": "Drop-in llama.cpp scanner that actually ships as GGUF and stays light enough for Pi-class hardware.",
            },
            "embedding": {
                "base_url": "http://127.0.0.1:8081/v1",
                "model": "nomic-embed-text-v1.5.Q8_0.gguf",
                "reason": "Lighter CPU embedding path than Qwen3-Embedding-0.6B for entry-level hardware.",
            },
            "embed_mode": "overnight",
            "notes": [
                "Bias toward background indexing so live chat stays responsive.",
                "Upgrade the embedding model first when moving off entry-level hardware.",
            ],
        },
        {
            "id": "desktop",
            "label": "Desktop / balanced",
            "summary": "Good default for mixed local and proxied workloads.",
            "scan": {
                "base_url": "http://127.0.0.1:8083/v1",
                "model": "Llama-3.2-1B-Instruct-Q4_0_4_4.gguf",
                "prompt_mode": "instruction",
                "reason": "Keeps scanner latency low without requiring a non-llama.cpp serving stack.",
            },
            "embedding": {
                "base_url": "http://127.0.0.1:8081/v1",
                "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                "reason": "Better semantic recall when the host can absorb the extra footprint.",
            },
            "embed_mode": "realtime",
            "notes": [
                "Current project default profile.",
            ],
        },
        {
            "id": "workstation",
            "label": "Workstation / GPU-heavy",
            "summary": "Keep the higher-quality local stack hot at all times.",
            "scan": {
                "base_url": "http://127.0.0.1:8083/v1",
                "model": "Llama-3.2-1B-Instruct-Q4_0_4_4.gguf",
                "prompt_mode": "instruction",
                "reason": "Still small enough that there is no reason to waste the main chat model on redaction.",
            },
            "embedding": {
                "base_url": "http://127.0.0.1:8081/v1",
                "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                "reason": "Best fit when the box already has enough headroom for stronger embeddings.",
            },
            "embed_mode": "realtime",
            "notes": [
                "Use this when embedding latency is already hidden by available hardware.",
            ],
        },
    ],
}

_SELF_MCP = {
    "version": 1,
    "servers": [
        {
            "name": "crowpilot-self",
            "transport": "http",
            "url": "http://localhost:8787/mcp",
            "purpose": "Use the running CrowPilot instance as an MCP relay from external clients.",
            "auto_check": True,
        }
    ],
    "notes": [
        "Add host-specific overrides in mcp/servers.local.json.",
        "If PANTHEON_MCP_TOKEN is set, callers must send a bearer token.",
    ],
}

_SKILL_BOOTSTRAP = {
    "version": 1,
    "skills": [
        {
            "name": "hardware-profile-selection",
            "category": "deployment",
            "description": "Choose CrowPilot scan and embedding defaults from the repo-local hardware profiles.",
            "status": "draft",
            "local_only": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                },
                "required": ["profile"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "scan_model": {"type": "string"},
                    "embedding_model": {"type": "string"},
                    "embed_mode": {"type": "string"},
                },
            },
            "tool_contract": {
                "reads": [
                    ".corbin/hardware/profiles.json",
                    ".corbin/env/raspberry-pi.env.example",
                    ".corbin/env/desktop.env.example",
                    ".corbin/env/workstation.env.example",
                ],
                "writes": [],
            },
        }
    ],
}

_MEMORY_MANIFEST = {
    "version": 1,
    "store": "jsonl",
    "files": {
        "working_set": "working-set.local.jsonl",
        "long_term": "long-term.local.jsonl",
    },
    "notes": [
        "Append one JSON object per line.",
        "Keep secrets out of these files; use the credential vault for sensitive values.",
    ],
}

_WORKSPACE_GITIGNORE = """env/*.local
memory/*.local.jsonl
mcp/*.local.json
skills/*.local.json
"""

_ENV_FILES = {
    "desktop.env.example": """PANTHEON_AGENT_HOME=../.corbin
PANTHEON_RUNTIME_PROFILE=desktop
PANTHEON_SCAN_BASE_URL=http://127.0.0.1:8083/v1
PANTHEON_SCAN_MODEL=Llama-3.2-1B-Instruct-Q4_0_4_4.gguf
PANTHEON_SCAN_PROMPT_MODE=instruction
PANTHEON_EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
PANTHEON_EMBEDDING_MODEL=Qwen3-Embedding-0.6B-Q8_0.gguf
PANTHEON_EMBED_MODE=realtime
""",
    "raspberry-pi.env.example": """PANTHEON_AGENT_HOME=../.corbin
PANTHEON_RUNTIME_PROFILE=raspberry-pi
PANTHEON_SCAN_BASE_URL=http://127.0.0.1:8083/v1
PANTHEON_SCAN_MODEL=Llama-3.2-1B-Instruct-Q4_0_4_4.gguf
PANTHEON_SCAN_PROMPT_MODE=instruction
PANTHEON_EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
PANTHEON_EMBEDDING_MODEL=nomic-embed-text-v1.5.Q8_0.gguf
PANTHEON_EMBED_MODE=overnight
""",
    "workstation.env.example": """PANTHEON_AGENT_HOME=../.corbin
PANTHEON_RUNTIME_PROFILE=workstation
PANTHEON_SCAN_BASE_URL=http://127.0.0.1:8083/v1
PANTHEON_SCAN_MODEL=Llama-3.2-1B-Instruct-Q4_0_4_4.gguf
PANTHEON_SCAN_PROMPT_MODE=instruction
PANTHEON_EMBEDDING_BASE_URL=http://127.0.0.1:8081/v1
PANTHEON_EMBEDDING_MODEL=Qwen3-Embedding-0.6B-Q8_0.gguf
PANTHEON_EMBED_MODE=realtime
""",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _agent_home() -> Path:
    base = Path(settings.agent_home)
    if not base.is_absolute():
        base = (_repo_root() / base).resolve()
    return base


def _write_text_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text)


def _write_json_if_missing(path: Path, payload: dict) -> None:
    _write_text_if_missing(path, json.dumps(payload, indent=2))


def ensure_agent_workspace() -> None:
    home = _agent_home()
    home.mkdir(parents=True, exist_ok=True)
    for directory in _DIRECTORIES:
        (home / directory).mkdir(parents=True, exist_ok=True)

    _write_text_if_missing(home / ".gitignore", _WORKSPACE_GITIGNORE)
    _write_json_if_missing(home / "workspace.json", _WORKSPACE_MANIFEST)
    _write_json_if_missing(home / "hardware" / "profiles.json", _HARDWARE_PROFILES)
    _write_json_if_missing(home / "mcp" / "servers.json", _SELF_MCP)
    _write_json_if_missing(home / "skills" / "bootstrap.json", _SKILL_BOOTSTRAP)
    _write_json_if_missing(home / "memory" / "persistence.json", _MEMORY_MANIFEST)
    _write_text_if_missing(home / "personality" / "corbin-system-prompt.txt", CORBIN_DEFAULT_PROMPT)
    for name, text in _ENV_FILES.items():
        _write_text_if_missing(home / "env" / name, text)
