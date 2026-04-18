from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException

from ..providers import OpenAICompatProvider, ProviderConfig
from ..schemas import IntegrationCreateRequest, IntegrationUpdateRequest
from ..services.credential_vault import resolve_credential_by_ref
from ..services.providers import reload_providers_from_integrations
from ..services.serializers import serialize_integration_row
from ..utils import decode_json_field
from ..state import g

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("")
def list_integrations(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    rows = g.db.execute("SELECT * FROM integrations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [serialize_integration_row(r) for r in rows]


@router.get("/oauth-templates")
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


@router.post("")
def create_integration(payload: IntegrationCreateRequest) -> dict:
    if payload.api_key:
        _, key_error = resolve_credential_by_ref(payload.api_key)
        if key_error:
            raise HTTPException(status_code=400, detail=key_error)

    try:
        cur = g.db.execute(
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

    g.db.commit()
    row = g.db.execute("SELECT * FROM integrations WHERE id = ?", (cur.lastrowid,)).fetchone()
    reload_providers_from_integrations()
    return serialize_integration_row(row)


@router.patch("/{integration_id}")
def update_integration(integration_id: int, payload: IntegrationUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)

    if "api_key" in patch and patch["api_key"]:
        _, key_error = resolve_credential_by_ref(patch["api_key"])
        if key_error:
            raise HTTPException(status_code=400, detail=key_error)
    if "meta" in patch:
        next_values["meta_json"] = json.dumps(patch.pop("meta"))
    for key, value in patch.items():
        next_values[key] = value

    g.db.execute(
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
    g.db.commit()
    updated = g.db.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    reload_providers_from_integrations()
    return serialize_integration_row(updated)


@router.delete("/{integration_id}")
def delete_integration(integration_id: int) -> dict:
    cur = g.db.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Integration not found")
    reload_providers_from_integrations()
    return {"deleted": True, "id": integration_id}


@router.post("/{integration_id}/sync-models")
async def sync_integration_models(integration_id: int) -> dict:
    row = g.db.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not row["base_url"]:
        raise HTTPException(status_code=400, detail="Integration base_url is required for model sync")

    resolved_key, key_error = resolve_credential_by_ref(row["api_key"] or "")
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

    meta = decode_json_field(row["meta_json"], {})
    if error_note:
        meta["last_error"] = error_note
    else:
        meta.pop("last_error", None)

    g.db.execute(
        """
        UPDATE integrations
        SET models_json = ?, status = ?, meta_json = ?, last_sync_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (json.dumps(model_ids), status, json.dumps(meta), integration_id),
    )
    g.db.commit()
    updated = g.db.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    reload_providers_from_integrations()
    return serialize_integration_row(updated)
