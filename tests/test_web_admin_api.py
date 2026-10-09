import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_schema import init_web_database
from webapp_sessions import WebIdentity, create_session


class WebAdminApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "admin.db"
        init_web_database(str(self.db))
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (123, 'admin', 'Admin')")
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (456, 'learner', 'Learner')")
            conn.execute("INSERT INTO questions(subject, question, option1, option2, correct_option) "
                         "VALUES ('histology', 'Cell question', 'A', 'B', 1)")
            conn.execute("INSERT INTO web_google_accounts(subject, email, display_name) "
                         "VALUES ('google-user', 'g@example.test', 'Google User')")
        self.settings = make_settings(self.db, AMEBA_WEB_ADMIN_IDS="123")
        self.tokens = {
            "admin": create_session(str(self.db), WebIdentity("telegram", "123", "Admin", True), self.settings.session_secret, 3600),
            "learner": create_session(str(self.db), WebIdentity("telegram", "456", "Learner", False), self.settings.session_secret, 3600),
            "google": create_session(str(self.db), WebIdentity("google", "google-user", "Google User", False), self.settings.session_secret, 3600),
        }
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def cookies(self, account):
        return {"ameba_session": self.tokens[account]}

    async def test_non_admin_cannot_call_admin_api(self):
        for account in ("learner", "google"):
            response = await self.client.get("/api/admin/questions", cookies=self.cookies(account))
            self.assertEqual(response.status, 403)
            response = await self.client.get("/api/admin/check", cookies=self.cookies(account))
            self.assertFalse((await response.json())["is_admin"])

    async def test_admin_searches_and_edits_questions_and_reads_stats(self):
        response = await self.client.get("/api/admin/questions?q=Cell", cookies=self.cookies("admin"))
        self.assertEqual(response.status, 200)
        questions = (await response.json())["questions"]
        self.assertEqual(len(questions), 1)
        response = await self.client.post(
            f"/api/admin/question/{questions[0]['id']}",
            json={"question": "Edited question", "correct_option": 1},
            cookies=self.cookies("admin"),
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/admin/stats", cookies=self.cookies("admin"))
        self.assertEqual(response.status, 200)
        self.assertGreaterEqual((await response.json())["total_questions"], 1)

    async def test_admin_access_grants_are_provider_scoped(self):
        for provider, account_key in (("telegram", "456"), ("google", "google-user")):
            response = await self.client.post(
                "/api/admin/access",
                json={"provider": provider, "account_key": account_key, "subject": "histology", "action": "grant"},
                cookies=self.cookies("admin"),
            )
            self.assertEqual(response.status, 200)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=456 AND subject='histology'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_access_grants WHERE google_subject='google-user'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=0").fetchone()[0], 0)
        response = await self.client.post(
            "/api/admin/access",
            json={"provider": "google", "account_key": "google-user", "subject": "histology", "action": "revoke"},
            cookies=self.cookies("admin"),
        )
        self.assertEqual(response.status, 200)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_access_grants WHERE google_subject='google-user'").fetchone()[0], 0)

    async def test_admin_account_search_and_every_admin_write_is_protected(self):
        response = await self.client.get("/api/admin/accounts?q=learner", cookies=self.cookies("admin"))
        self.assertEqual(response.status, 200)
        accounts = (await response.json())["accounts"]
        self.assertEqual(accounts[0]["account_key"], "456")
        response = await self.client.post(
            "/api/admin/promo", json={"text": "forbidden"}, cookies=self.cookies("learner")
        )
        self.assertEqual(response.status, 403)

    async def test_admin_question_mutations_reject_foreign_origins(self):
        response = await self.client.post(
            "/api/admin/question/1", json={"question": "Changed", "correct_option": 1},
            cookies=self.cookies("admin"), headers={"Origin": "https://attacker.invalid"},
        )
        self.assertEqual(response.status, 403)

    async def test_invalid_access_expiration_is_rejected(self):
        response = await self.client.post(
            "/api/admin/access",
            json={"provider": "telegram", "account_key": "456", "subject": "histology",
                  "action": "grant", "expires_at": "not-a-date"},
            cookies=self.cookies("admin"),
        )
        self.assertEqual(response.status, 400)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=456").fetchone()[0], 0)
        response = await self.client.post(
            "/api/admin/announcements", json={"title": "bad", "body": "bad"},
            cookies=self.cookies("google"),
        )
        self.assertEqual(response.status, 403)


if __name__ == "__main__":
    unittest.main()
