from __future__ import annotations

import sqlite3

from ..catalogs import CRED_REF_PATTERN
from ..utils import decode_json_field


def serialize_mcp_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["args"] = decode_json_field(out.pop("args_json", "[]"), [])
    out["env"] = decode_json_field(out.pop("env_json", "{}"), {})
    out["is_builtin"] = bool(out.get("is_builtin"))
    return out


def serialize_widget_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["config"] = decode_json_field(out.pop("config_json", "{}"), {})
    return out


def serialize_copilot_task_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["context"] = decode_json_field(out.pop("context_json", "{}"), {})
    return out


def serialize_automation_task_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["local_context"] = decode_json_field(out.pop("local_context_json", "{}"), {})
    return out


def serialize_skill_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["local_only"] = bool(out["local_only"])
    out["input_schema"] = decode_json_field(out.pop("input_schema_json", "{}"), {})
    out["output_schema"] = decode_json_field(out.pop("output_schema_json", "{}"), {})
    out["tool_contract"] = decode_json_field(out.pop("tool_contract_json", "{}"), {})
    return out


def serialize_conversation_row(row: sqlite3.Row) -> dict:
    return dict(row)


def serialize_integration_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["models"] = decode_json_field(out.pop("models_json", "[]"), [])
    out["meta"] = decode_json_field(out.pop("meta_json", "{}"), {})
    raw_key = out.pop("api_key", None)
    out["has_api_key"] = bool(raw_key)
    out["api_key_is_reference"] = bool(
        raw_key and isinstance(raw_key, str) and CRED_REF_PATTERN.match(raw_key.strip())
    )
    return out


def serialize_credential_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["meta"] = decode_json_field(out.pop("meta_json", "{}"), {})
    out.pop("secret_encrypted", None)
    return out


def serialize_project_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["stack"] = decode_json_field(out.pop("stack_json", "{}"), {})
    return out
