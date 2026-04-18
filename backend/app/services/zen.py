from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException

from ..config import settings
from ..state import g
from ..utils import slugify_name
from .mcp import derive_onboarding_from_prompt


def get_zen_provider(provider_name: str | None):
    if provider_name:
        provider = g.providers.get(provider_name)
        if not provider:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")
        return provider
    return g.providers.get("local_openai") or g.providers[settings.default_provider]


def build_zen_messages(domain: str, prompt: str, source_text: str | None) -> list[dict[str, str]]:
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
        "credential_create": {
            "shape": {
                "name": "string",
                "credential_type": "api_key|password|oauth_token|session_token|other",
                "provider": "string|null",
                "username": "string|null",
                "secret": "string",
                "assistant_summary": "string",
            },
            "guidance": "Create a credential vault entry from the user's description. Infer the provider and type. Use 'REDACTED' as the secret placeholder if the user didn't provide the actual value.",
        },
        "integration_create": {
            "shape": {
                "name": "string",
                "provider_kind": "string",
                "base_url": "string|null",
                "auth_type": "api_key|oauth|adc|none",
                "api_key": "string|null",
                "default_model": "string|null",
                "status": "draft|connected",
                "assistant_summary": "string",
            },
            "guidance": "Register an AI provider integration. Infer base_url and provider_kind from known services (OpenRouter=https://openrouter.ai/api/v1, Anthropic=https://api.anthropic.com/v1, etc). Leave api_key null if not provided.",
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
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_json_object(raw: str) -> dict:
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


def fallback_zen_plan(domain: str, prompt: str, source_text: str | None) -> tuple[dict, str]:
    text = " ".join((prompt or "").split())
    source = (source_text or "").strip()

    if domain == "task_create":
        lower = text.lower()
        sensitive = any(
            token in lower for token in ["secret", "token", "password", "credential", "api key"]
        )
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
            "name": slugify_name(seed, "zen-skill"),
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
        parsed = {"title": (text[:72] or "Zen note").strip(), "body": source or text or ""}
        return parsed, "Zen fallback captured the note because model planning was unavailable."

    if domain == "mcp_create":
        onboarding = derive_onboarding_from_prompt(text, include_catalog=False)
        suggestion = onboarding.get("primary_suggestion") or {}
        parsed = {
            "name": slugify_name(suggestion.get("name") or "zen-mcp", "zen-mcp"),
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

    if domain == "credential_create":
        parsed = {
            "name": slugify_name(text[:48] or "zen-cred", "zen-cred"),
            "credential_type": "api_key",
            "provider": None,
            "username": None,
            "secret": "REDACTED",
        }
        return parsed, "Zen fallback created a credential draft. Fill in the actual secret value."

    if domain == "integration_create":
        parsed = {
            "name": slugify_name(text[:48] or "zen-integration", "zen-integration"),
            "provider_kind": "openai_compat",
            "base_url": None,
            "auth_type": "api_key",
            "api_key": None,
            "default_model": None,
            "status": "draft",
        }
        return parsed, "Zen fallback created an integration draft. Set the base_url and API key."

    return {}, "Zen fallback could not map the request."
