import os
import re
from dataclasses import dataclass


class SettingsError(ValueError):
    pass


def _required(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise SettingsError(f"{key} is required")
    return value


@dataclass(frozen=True)
class WebSettings:
    db_path: str
    session_secret: bytes
    telegram_login_bot_token: str
    telegram_login_bot_username: str
    google_client_id: str
    environment: str
    session_ttl_seconds: int
    admin_ids: frozenset[int]
    base_url: str
    host: str
    port: int
    staging_gate_user: str | None = None
    staging_gate_password: str | None = None

    @classmethod
    def from_env(cls) -> "WebSettings":
        env = dict(os.environ)
        db_path = _required(env, "AMEBA_WEB_DB_PATH")
        if os.path.realpath(db_path) == os.path.realpath("/data/questions.db"):
            raise SettingsError("The production database path is not allowed in web development or staging")
        secret = _required(env, "AMEBA_WEB_SESSION_SECRET").encode("utf-8")
        if len(secret) < 32:
            raise SettingsError("AMEBA_WEB_SESSION_SECRET must be at least 32 bytes")

        bot_token = _required(env, "AMEBA_TELEGRAM_LOGIN_BOT_TOKEN")
        bot_username = _required(env, "AMEBA_TELEGRAM_LOGIN_BOT_USERNAME").lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot_username):
            raise SettingsError("AMEBA_TELEGRAM_LOGIN_BOT_USERNAME must be a valid public bot username")
        google_client_id = _required(env, "AMEBA_GOOGLE_CLIENT_ID")
        environment = env.get("AMEBA_WEB_ENV", "local").strip().lower()
        if environment not in {"local", "staging"}:
            raise SettingsError("AMEBA_WEB_ENV must be 'local' or 'staging'")

        try:
            ttl = int(env.get("AMEBA_WEB_SESSION_TTL_SECONDS", "2592000"))
        except ValueError as exc:
            raise SettingsError("AMEBA_WEB_SESSION_TTL_SECONDS must be an integer") from exc
        if ttl <= 0:
            raise SettingsError("AMEBA_WEB_SESSION_TTL_SECONDS must be positive")

        try:
            port = int(env.get("AMEBA_WEB_PORT", "8080"))
        except ValueError as exc:
            raise SettingsError("AMEBA_WEB_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise SettingsError("AMEBA_WEB_PORT must be between 1 and 65535")

        try:
            admin_ids = frozenset(
                int(item.strip())
                for item in env.get("AMEBA_WEB_ADMIN_IDS", "").split(",")
                if item.strip()
            )
        except ValueError as exc:
            raise SettingsError("AMEBA_WEB_ADMIN_IDS must contain comma-separated integers") from exc
        if any(user_id <= 0 for user_id in admin_ids):
            raise SettingsError("AMEBA_WEB_ADMIN_IDS must contain positive Telegram IDs")

        gate_user = env.get("AMEBA_STAGING_GATE_USER", "").strip() or None
        gate_password = env.get("AMEBA_STAGING_GATE_PASSWORD", "") or None
        if (gate_user is None) != (gate_password is None):
            raise SettingsError("Both staging gate credentials are required together")
        if environment == "staging" and (gate_user is None or gate_password is None):
            raise SettingsError("Staging requires HTTP Basic gate credentials")

        return cls(
            db_path=db_path,
            session_secret=secret,
            telegram_login_bot_token=bot_token,
            telegram_login_bot_username=bot_username,
            google_client_id=google_client_id,
            environment=environment,
            session_ttl_seconds=ttl,
            admin_ids=admin_ids,
            base_url=env.get("AMEBA_WEB_BASE_URL", "http://localhost:8080").rstrip("/"),
            host=env.get("AMEBA_WEB_HOST", "0.0.0.0"),
            port=port,
            staging_gate_user=gate_user,
            staging_gate_password=gate_password,
        )
