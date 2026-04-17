from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("PANTHEON_DB_PATH", "./data/pantheon.db")
    host: str = os.getenv("PANTHEON_HOST", "127.0.0.1")
    port: int = int(os.getenv("PANTHEON_PORT", "8787"))

    default_provider: str = os.getenv("PANTHEON_DEFAULT_PROVIDER", "copilot_proxy")

    copilot_base_url: str = os.getenv("PANTHEON_COPILOT_BASE_URL", "http://127.0.0.1:8080/v1")
    copilot_model: str = os.getenv("PANTHEON_COPILOT_MODEL", "gpt-5.3-codex")
    copilot_api_key: str = os.getenv("PANTHEON_COPILOT_API_KEY", "")

    local_base_url: str = os.getenv("PANTHEON_LOCAL_BASE_URL", "")
    local_model: str = os.getenv("PANTHEON_LOCAL_MODEL", "local-model")
    local_api_key: str = os.getenv("PANTHEON_LOCAL_API_KEY", "")

    chunk_size: int = int(os.getenv("PANTHEON_CHUNK_SIZE", "700"))
    chunk_overlap: int = int(os.getenv("PANTHEON_CHUNK_OVERLAP", "120"))

    credential_key: str = os.getenv("PANTHEON_CREDENTIAL_KEY", "")
    projects_root: str = os.getenv("PANTHEON_PROJECTS_ROOT", "./projects")
    copilot_cli_command: str = os.getenv("PANTHEON_COPILOT_CLI_COMMAND", "gh")


settings = Settings()
