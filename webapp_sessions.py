import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class WebIdentity:
    provider: Literal["telegram", "google"]
    account_key: str
    display_name: str
    is_admin: bool


def _token_hash(token: str, secret: bytes) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session(
    db_path: str, identity: WebIdentity, secret: bytes, ttl_seconds: int, now: int | None = None
) -> str:
    if identity.provider not in {"telegram", "google"} or not identity.account_key:
        raise ValueError("A valid provider and account key are required")
    current_time = int(time.time()) if now is None else int(now)
    token = secrets.token_urlsafe(32)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO web_sessions(token_hash, provider, account_key, display_name, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_token_hash(token, secret), identity.provider, identity.account_key, identity.display_name,
             current_time + ttl_seconds, current_time),
        )
    return token


def resolve_session(
    db_path: str,
    token: str,
    secret: bytes,
    now: int,
    admin_ids: frozenset[int] | set[int] = frozenset(),
) -> WebIdentity | None:
    if not token:
        return None
    digest = _token_hash(token, secret)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT provider, account_key, display_name FROM web_sessions "
            "WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
            (digest, int(now)),
        ).fetchone()
        if not row:
            return None
        provider, account_key, session_name = row
        if provider == "telegram":
            profile = conn.execute("SELECT full_name FROM users WHERE user_id=?", (int(account_key),)).fetchone()
            display_name = profile[0] if profile and profile[0] else session_name or account_key
            try:
                is_admin = int(account_key) in admin_ids
            except ValueError:
                is_admin = False
        else:
            profile = conn.execute(
                "SELECT display_name FROM web_google_accounts WHERE subject=?", (account_key,)
            ).fetchone()
            display_name = profile[0] if profile and profile[0] else session_name or account_key
            is_admin = False
    return WebIdentity(provider, account_key, display_name, is_admin)


def revoke_session(db_path: str, token: str, secret: bytes, now: int | None = None) -> None:
    if not token:
        return
    current_time = int(time.time()) if now is None else int(now)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE web_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (current_time, _token_hash(token, secret)),
        )
