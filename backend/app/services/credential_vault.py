from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from ..catalogs import CRED_REF_PATTERN
from ..config import settings
from ..state import g


def vault_key_path() -> Path:
    return Path(settings.db_path).resolve().parent / "credential_vault.key"


def get_cipher() -> Fernet:
    if g.credential_cipher is not None:
        return g.credential_cipher

    key_text = (settings.credential_key or "").strip()
    if key_text:
        key_bytes = key_text.encode("utf-8")
    else:
        key_path = vault_key_path()
        if key_path.exists():
            key_bytes = key_path.read_bytes().strip()
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_bytes = Fernet.generate_key()
            key_path.write_bytes(key_bytes)
            os.chmod(key_path, 0o600)

    g.credential_cipher = Fernet(key_bytes)
    return g.credential_cipher


def encrypt_secret(plaintext: str) -> str:
    token = get_cipher().encrypt((plaintext or "").encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        raw = get_cipher().decrypt((ciphertext or "").encode("utf-8"))
        return raw.decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Credential vault decrypt failed") from exc


def resolve_credential_by_ref(ref_value: str | None) -> tuple[str | None, str | None]:
    if not ref_value:
        return ref_value, None

    match = CRED_REF_PATTERN.match(ref_value.strip()) if isinstance(ref_value, str) else None
    if not match:
        return ref_value, None

    key = match.group(1).strip()
    row = None
    if key.isdigit():
        row = g.db.execute(
            "SELECT * FROM credentials WHERE id = ?", (int(key),)
        ).fetchone()
    if row is None:
        row = g.db.execute(
            "SELECT * FROM credentials WHERE lower(name) = lower(?)", (key,)
        ).fetchone()
    if row is None:
        return None, f"Credential not found for reference: {ref_value}"

    g.db.execute(
        "UPDATE credentials SET last_used_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    g.db.commit()
    return decrypt_secret(row["secret_encrypted"]), None


def resolve_env_credentials(env_map: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    errors: list[str] = []
    for key, value in (env_map or {}).items():
        resolved_value, err = resolve_credential_by_ref(value)
        if err:
            errors.append(f"{key}: {err}")
            resolved[key] = value
        else:
            resolved[key] = resolved_value
    return resolved, errors


def slug_for_credential_name(value: str, fallback: str = "credential") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:64] or fallback
