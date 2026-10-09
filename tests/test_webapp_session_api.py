import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_sessions import WebIdentity, create_session, resolve_session


class WebSessionTests(unittest.TestCase):
    def test_session_hash_expiry_revocation_and_admin_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "web.db"
            from webapp_schema import init_web_database
            init_web_database(str(db))
            identity = WebIdentity("telegram", "12345", "Ruslan", False)
            token = create_session(str(db), identity, b"x" * 32, 3600, now=1000)
            stored_hash = sqlite3.connect(db).execute("SELECT token_hash FROM web_sessions").fetchone()[0]
            self.assertNotEqual(token, stored_hash)
            self.assertEqual(resolve_session(str(db), token, b"x" * 32, now=1001), identity)
            self.assertIsNone(resolve_session(str(db), token, b"x" * 32, now=4600))


class WebSessionApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "web.db"
        self.settings = make_settings(
            self.db_path,
            AMEBA_WEB_ADMIN_IDS="123456789",
            AMEBA_WEB_BASE_URL="http://127.0.0.1",
        )
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_telegram_login_preserves_existing_access_and_sets_cookie(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (123456789, 'old', 'Old Name')")
            conn.execute("INSERT INTO purchases(user_id, subject, expires_at) VALUES (123456789, 'anatomy', '2099-01-01')")
        from webapp_auth import TelegramIdentity
        with patch("webapp_server.validate_telegram_login", return_value=TelegramIdentity(
            123456789, "Ruslan", "ruslan11", None
        )):
            response = await self.client.post("/api/session/telegram", json={"id": "signed"})
        self.assertEqual(response.status, 200)
        cookie = response.cookies["ameba_session"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=123456789").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT username FROM users WHERE user_id=123456789").fetchone()[0], "ruslan11")

    async def test_google_login_requires_csrf_and_only_writes_web_profile(self):
        response = await self.client.post("/api/session/google", data={
            "credential": "token", "g_csrf_token": "body-value"
        }, cookies={"g_csrf_token": "cookie-value"})
        self.assertEqual(response.status, 403)
        from webapp_google_auth import GoogleIdentity
        with patch("webapp_server.validate_google_id_token", return_value=GoogleIdentity(
            "google-sub-1", "same@example.test", "Google User", None
        )):
            response = await self.client.post("/api/session/google", data={
                "credential": "token", "g_csrf_token": "csrf"
            }, cookies={"g_csrf_token": "csrf"}, headers={"Origin": "https://accounts.google.com"})
        self.assertEqual(response.status, 200)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_accounts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 0)

    async def test_invalid_provider_credentials_create_no_profiles_or_sessions(self):
        with patch("webapp_server.validate_telegram_login", return_value=None):
            response = await self.client.post("/api/session/telegram", json={"id": "forged"})
        self.assertEqual(response.status, 401)
        with patch("webapp_server.validate_google_id_token", return_value=None):
            response = await self.client.post("/api/session/google", data={
                "credential": "invalid", "g_csrf_token": "csrf"
            }, cookies={"g_csrf_token": "csrf"})
        self.assertEqual(response.status, 401)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_accounts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_sessions").fetchone()[0], 0)

    async def test_session_restore_logout_and_cross_origin_rejection(self):
        identity = WebIdentity("google", "google-sub-2", "User", False)
        token = create_session(str(self.db_path), identity, self.settings.session_secret, 3600)
        self.client.session.cookie_jar.update_cookies({"ameba_session": token})
        response = await self.client.get("/api/session")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["provider"], "google")
        response = await self.client.post("/api/session/logout", headers={"Origin": "https://evil.test"})
        self.assertEqual(response.status, 403)
        response = await self.client.post("/api/session/logout")
        self.assertEqual(response.status, 200)
        self.assertIsNone(resolve_session(str(self.db_path), token, self.settings.session_secret, now=9999999999))

    async def test_web_config_exposes_only_public_google_client_id(self):
        response = await self.client.get("/api/config")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data, {"google_client_id": self.settings.google_client_id})


if __name__ == "__main__":
    unittest.main()
