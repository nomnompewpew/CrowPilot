from __future__ import annotations

import json
import sqlite3
import webbrowser
from io import StringIO

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException

from ..catalogs import CREDENTIAL_CONNECTOR_CATALOG
from ..schemas import (
    ConnectorLaunchRequest,
    CredentialCreateRequest,
    CredentialEnvImportRequest,
    CredentialUpdateRequest,
)
from ..services.credential_vault import encrypt_secret, slug_for_credential_name
from ..services.serializers import serialize_credential_row
from ..state import g

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


@router.get("")
def list_credentials(limit: int = 300) -> list[dict]:
    limit = max(1, min(limit, 1000))
    rows = g.db.execute("SELECT * FROM credentials ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [serialize_credential_row(r) for r in rows]


@router.post("")
def create_credential(payload: CredentialCreateRequest) -> dict:
    name = slug_for_credential_name(payload.name, "credential")
    try:
        cur = g.db.execute(
            """
            INSERT INTO credentials(name, credential_type, provider, username, secret_encrypted, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                payload.credential_type,
                payload.provider.strip() if payload.provider else None,
                payload.username.strip() if payload.username else None,
                encrypt_secret(payload.secret.strip()),
                json.dumps(payload.meta),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Credential name already exists") from exc

    g.db.commit()
    row = g.db.execute("SELECT * FROM credentials WHERE id = ?", (cur.lastrowid,)).fetchone()
    return serialize_credential_row(row)


@router.patch("/{credential_id}")
def update_credential(credential_id: int, payload: CredentialUpdateRequest) -> dict:
    row = g.db.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")

    next_values = dict(row)
    patch = payload.model_dump(exclude_unset=True)

    if "name" in patch and patch["name"]:
        next_values["name"] = slug_for_credential_name(patch.pop("name"), next_values["name"])
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
        next_values["secret_encrypted"] = encrypt_secret(patch.pop("secret").strip())

    rotate = bool(patch.get("rotate"))
    if rotate and "secret" not in payload.model_fields_set:
        raise HTTPException(status_code=400, detail="Rotate requires a new secret value")

    try:
        g.db.execute(
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

    g.db.commit()
    updated = g.db.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    return serialize_credential_row(updated)


@router.delete("/{credential_id}")
def delete_credential(credential_id: int) -> dict:
    cur = g.db.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
    g.db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"deleted": True, "id": credential_id}


@router.post("/import-env")
def import_credentials_from_env(payload: CredentialEnvImportRequest) -> dict:
    env_pairs = dotenv_values(stream=StringIO(payload.env_text))
    imported: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []

    provider_slug = slug_for_credential_name(payload.provider or "env", "env")
    for key, raw_value in env_pairs.items():
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue

        cred_name = slug_for_credential_name(f"{provider_slug}-{key.lower()}", f"{provider_slug}-cred")
        existing = g.db.execute("SELECT * FROM credentials WHERE name = ?", (cred_name,)).fetchone()
        if existing and not payload.overwrite:
            skipped.append(cred_name)
            continue

        meta = {"source": "env_import", "source_env_key": key}
        if existing:
            g.db.execute(
                """
                UPDATE credentials
                SET credential_type = ?, provider = ?, secret_encrypted = ?, meta_json = ?,
                    last_rotated_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    payload.credential_type,
                    payload.provider,
                    encrypt_secret(value),
                    json.dumps(meta),
                    existing["id"],
                ),
            )
            updated.append(cred_name)
        else:
            g.db.execute(
                """
                INSERT INTO credentials(name, credential_type, provider, username, secret_encrypted, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cred_name,
                    payload.credential_type,
                    payload.provider,
                    None,
                    encrypt_secret(value),
                    json.dumps(meta),
                ),
            )
            imported.append(cred_name)

    g.db.commit()
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total_processed": len(imported) + len(updated) + len(skipped),
    }


@router.get("/connectors")
def list_credential_connectors() -> dict:
    return CREDENTIAL_CONNECTOR_CATALOG


@router.post("/connectors/launch")
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
