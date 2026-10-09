import os
import sqlite3
import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import BasicAuth
from aiohttp.test_utils import TestClient, TestServer

from webapp_settings import WebSettings


ROOT = Path(__file__).resolve().parents[1]


def make_settings(db_path, **overrides):
    env = {
        "AMEBA_WEB_DB_PATH": str(db_path),
        "AMEBA_WEB_SESSION_SECRET": "test-session-secret-with-enough-entropy",
        "AMEBA_TELEGRAM_LOGIN_BOT_TOKEN": "123456:test-token",
        "AMEBA_TELEGRAM_LOGIN_BOT_USERNAME": "ameba_test_bot",
        "AMEBA_GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
    } | overrides
    with patch.dict(os.environ, env, clear=True):
        return WebSettings.from_env()


class WebRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_schema_is_bot_compatible_and_idempotent(self):
        try:
            webapp_schema = importlib.import_module("webapp_schema")
        except ModuleNotFoundError:
            self.fail("webapp_schema is not implemented")
        init_web_database = getattr(webapp_schema, "init_web_database", None)
        self.assertTrue(callable(init_web_database), "init_web_database is not implemented")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "isolated" / "web.db"
            init_web_database(str(db_path))
            init_web_database(str(db_path))

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                users_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}

            self.assertTrue({"questions", "users", "purchases", "question_history", "sessions"} <= tables)
            self.assertTrue({"web_sessions", "web_google_accounts", "web_google_history"} <= tables)
            self.assertTrue({"user_id", "username", "points_balance", "referral_count"} <= users_columns)

    async def test_web_schema_upgrades_previous_session_table(self):
        from webapp_schema import init_web_database

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "older-web.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE web_sessions (
                        token_hash TEXT PRIMARY KEY, provider TEXT NOT NULL,
                        account_key TEXT NOT NULL, expires_at INTEGER NOT NULL,
                        created_at INTEGER NOT NULL, revoked_at INTEGER
                    )
                """)
            init_web_database(str(db_path))
            init_web_database(str(db_path))
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(web_sessions)")}
            self.assertIn("display_name", columns)

    async def test_standalone_app_uses_explicit_temporary_database(self):
        import webapp_server
        create_web_app = getattr(webapp_server, "create_web_app", None)
        self.assertTrue(callable(create_web_app), "create_web_app is not implemented")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "isolated" / "web.db"
            app = create_web_app(make_settings(db_path))

            self.assertEqual(app["db_path"], str(db_path))
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/")
                self.assertEqual(response.status, 200)
                self.assertIn("/static/app.js?v=1", await response.text())
                self.assertTrue(db_path.exists())
                response = await client.get("/static/app.js")
                self.assertEqual(response.status, 200)
                self.assertIn("credentials: 'same-origin'", await response.text())

            from dataclasses import replace
            with self.assertRaises(ValueError):
                create_web_app(replace(make_settings(db_path), db_path="/data/questions.db"))

    async def test_staging_gate_protects_pages_assets_and_api_routes(self):
        import webapp_server
        create_web_app = getattr(webapp_server, "create_web_app", None)
        self.assertTrue(callable(create_web_app), "create_web_app is not implemented")

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(
                Path(tmp) / "staging.db",
                AMEBA_WEB_ENV="staging",
                AMEBA_STAGING_GATE_USER="tester",
                AMEBA_STAGING_GATE_PASSWORD="gate-password",
            )
            app = create_web_app(settings)
            async with TestClient(TestServer(app)) as client:
                for path in ("/", "/admin", "/static/style.css", "/api/config"):
                    response = await client.get(path)
                    self.assertEqual(response.status, 401, path)

                response = await client.get("/", auth=BasicAuth("tester", "gate-password"))
                self.assertEqual(response.status, 200)

    async def test_web_entrypoint_does_not_import_bot_or_legacy_config(self):
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        code = "import sys, web_main; assert 'main' not in sys.modules; assert 'config' not in sys.modules"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
