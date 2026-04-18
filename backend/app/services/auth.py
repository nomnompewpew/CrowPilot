from __future__ import annotations

import datetime
import hashlib
import secrets

from ..state import g


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return hash_password(password, salt) == stored_hash


def get_session_user(token: str) -> dict | None:
    if not g.db or not token:
        return None
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = g.db.execute(
        """
        SELECT u.id, u.username, u.role
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, now),
    ).fetchone()
    return dict(row) if row else None


def seed_default_user() -> None:
    """Insert the default admin user if it does not already exist."""
    existing = g.db.execute(
        "SELECT id FROM users WHERE username = 'nomnompewpew'"
    ).fetchone()
    if existing:
        return
    salt = secrets.token_hex(16)
    pw_hash = hash_password("Di@m0nd$ky", salt)
    g.db.execute(
        "INSERT INTO users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
        ("nomnompewpew", pw_hash, salt, "admin"),
    )
    g.db.commit()
