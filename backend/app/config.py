from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("PANTHEON_DB_PATH", "./data/pantheon.db")
    host: str = os.getenv("PANTHEON_HOST", "0.0.0.0")
    port: int = int(os.getenv("PANTHEON_PORT", "8787"))
    edition: str = os.getenv("PANTHEON_EDITION", "crowpilot-developer")

    default_provider: str = os.getenv("PANTHEON_DEFAULT_PROVIDER", "copilot_proxy")

    copilot_base_url: str = os.getenv("PANTHEON_COPILOT_BASE_URL", "http://127.0.0.1:8080/v1")
    copilot_model: str = os.getenv("PANTHEON_COPILOT_MODEL", "gpt-5.3-codex")
    copilot_api_key: str = os.getenv("PANTHEON_COPILOT_API_KEY", "")

    # Local llama.cpp chat model (used for general local chat)
    local_base_url: str = os.getenv("PANTHEON_LOCAL_BASE_URL", "")
    local_model: str = os.getenv("PANTHEON_LOCAL_MODEL", "local-model")
    local_api_key: str = os.getenv("PANTHEON_LOCAL_API_KEY", "")

    # Security gate model — separate lightweight scanner, independent from the main chat model.
    # Drop-in llama.cpp default: Llama-3.2-1B-Instruct GGUF with prompt-driven redaction.
    #   Repo: https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF
    #   Recommended Pi quant: Llama-3.2-1B-Instruct-Q4_0_4_4.gguf
    # Optional dedicated fine-tune: OpenPipe/PII-Redact-General, but that repo ships
    # safetensors rather than GGUF, so it needs a different serving stack.
    # If left blank, falls back to local_base_url / local_model.
    scan_base_url: str = os.getenv("PANTHEON_SCAN_BASE_URL", "")
    scan_model: str = os.getenv("PANTHEON_SCAN_MODEL", "")
    scan_api_key: str = os.getenv("PANTHEON_SCAN_API_KEY", "")
    scan_prompt_mode: str = os.getenv("PANTHEON_SCAN_PROMPT_MODE", "auto")

    # Local embedding model (used for knowledge base semantic search)
    embedding_base_url: str = os.getenv("PANTHEON_EMBEDDING_BASE_URL", "")
    embedding_model: str = os.getenv("PANTHEON_EMBEDDING_MODEL", "")

    chunk_size: int = int(os.getenv("PANTHEON_CHUNK_SIZE", "700"))
    chunk_overlap: int = int(os.getenv("PANTHEON_CHUNK_OVERLAP", "120"))

    credential_key: str = os.getenv("PANTHEON_CREDENTIAL_KEY", "")
    projects_root: str = os.getenv("PANTHEON_PROJECTS_ROOT", "./projects")
    copilot_cli_command: str = os.getenv("PANTHEON_COPILOT_CLI_COMMAND", "gh")
    agent_home: str = os.getenv("PANTHEON_AGENT_HOME", "../.corbin")
    runtime_profile: str = os.getenv("PANTHEON_RUNTIME_PROFILE", "desktop")

    # MCP relay token — if set, POST /mcp requires Authorization: Bearer <token>.
    # Leave empty to keep the relay open (default, compatible with VS Code without extra config).
    mcp_token: str = os.getenv("PANTHEON_MCP_TOKEN", "")

    # Passive embed mode: 'realtime' processes all jobs as they arrive (small delay between
    # background-priority items). 'overnight' removes the delay — use when the user is away.
    embed_mode: str = os.getenv("PANTHEON_EMBED_MODE", "realtime")


settings = Settings()
