from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException

from ..chunking import split_into_chunks
from ..config import settings
from ..schemas import ZenActionRequest
from ..services.mcp import insert_mcp_server_with_unique_name
from ..services.mcp_relay import run_protocol_checks
from ..services.serializers import (
    serialize_automation_task_row,
    serialize_mcp_row,
    serialize_skill_row,
    serialize_widget_row,
)
from ..services.zen import build_zen_messages, extract_json_object, fallback_zen_plan, get_zen_provider
from ..state import g

router = APIRouter(prefix="/api/zen", tags=["zen"])


@router.post("/act")
async def zen_action(payload: ZenActionRequest) -> dict:
    provider = get_zen_provider(payload.provider)
    messages = build_zen_messages(payload.domain, payload.prompt, payload.source_text)

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
        parsed = extract_json_object(raw)
    except Exception as exc:
        parsed, fallback_summary = fallback_zen_plan(payload.domain, payload.prompt, payload.source_text)
        if not parsed:
            raise HTTPException(status_code=502, detail=f"Zen planning failed: {exc}") from exc
        reason = str(exc) or exc.__class__.__name__
        parsed["assistant_summary"] = f"{fallback_summary} (reason: {reason})"

    summary = parsed.pop("assistant_summary", "Zen action applied.")

    if payload.domain == "task_create":
        cur = g.db.execute(
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
        g.db.commit()
        row = g.db.execute("SELECT * FROM automation_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": serialize_automation_task_row(row)}

    if payload.domain == "skill_create":
        try:
            cur = g.db.execute(
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
        g.db.commit()
        row = g.db.execute("SELECT * FROM skills WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": serialize_skill_row(row)}

    if payload.domain == "note_create":
        title = (parsed.get("title") or "Zen note").strip()
        body = (parsed.get("body") or payload.prompt).strip()
        cur = g.db.execute("INSERT INTO notes(title, body) VALUES (?, ?)", (title, body))
        note_id = cur.lastrowid
        chunks = split_into_chunks(body, settings.chunk_size, settings.chunk_overlap)
        for idx, chunk in enumerate(chunks):
            g.db.execute(
                "INSERT INTO note_chunks(note_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
                (note_id, idx, chunk),
            )
        g.db.commit()
        return {
            "ok": True,
            "domain": payload.domain,
            "summary": summary,
            "record": {"id": note_id, "title": title, "body": body, "chunks_indexed": len(chunks)},
        }

    if payload.domain == "mcp_create":
        row = insert_mcp_server_with_unique_name(parsed)
        status, last_error, report = await run_protocol_checks(row)
        g.db.execute(
            """
            UPDATE mcp_servers
            SET status = ?, last_error = ?, last_checked_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, last_error, row["id"]),
        )
        g.db.commit()
        checked = g.db.execute("SELECT * FROM mcp_servers WHERE id = ?", (row["id"],)).fetchone()
        out = serialize_mcp_row(checked)
        out["validation_report"] = report
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": out}

    if payload.domain == "widget_create":
        cur = g.db.execute(
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
        g.db.commit()
        row = g.db.execute("SELECT * FROM dashboard_widgets WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": serialize_widget_row(row)}

    if payload.domain == "credential_create":
        cur = g.db.execute(
            """
            INSERT INTO credentials(name, credential_type, provider, username, secret)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (parsed.get("name") or "zen-cred").strip(),
                (parsed.get("credential_type") or "api_key").strip(),
                (parsed.get("provider") or None),
                (parsed.get("username") or None),
                (parsed.get("secret") or "REDACTED").strip(),
            ),
        )
        g.db.commit()
        row = g.db.execute("SELECT * FROM credentials WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": dict(row)}

    if payload.domain == "integration_create":
        cur = g.db.execute(
            """
            INSERT INTO integrations(name, provider_kind, base_url, auth_type, api_key, default_model, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (parsed.get("name") or "zen-integration").strip(),
                (parsed.get("provider_kind") or "openai_compat").strip(),
                (parsed.get("base_url") or None),
                (parsed.get("auth_type") or "api_key").strip(),
                (parsed.get("api_key") or None),
                (parsed.get("default_model") or None),
                (parsed.get("status") or "draft").strip(),
            ),
        )
        g.db.commit()
        row = g.db.execute("SELECT * FROM integrations WHERE id = ?", (cur.lastrowid,)).fetchone()
        return {"ok": True, "domain": payload.domain, "summary": summary, "record": dict(row)}

    raise HTTPException(status_code=400, detail="Unsupported Zen domain")
