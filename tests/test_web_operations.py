import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_schema import init_web_database
from webapp_sessions import WebIdentity, create_session


class WebOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "operations.db"
        init_web_database(str(self.db))
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (123, 'admin', 'Admin')")
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (456, 'learner', 'Learner')")
            conn.execute("INSERT INTO web_google_accounts(subject, display_name) VALUES ('google-user', 'Google User')")
        self.settings = make_settings(self.db, AMEBA_WEB_ADMIN_IDS="123")
        self.tokens = {
            "admin": create_session(str(self.db), WebIdentity("telegram", "123", "Admin", True), self.settings.session_secret, 3600),
            "telegram": create_session(str(self.db), WebIdentity("telegram", "456", "Learner", False), self.settings.session_secret, 3600),
            "google": create_session(str(self.db), WebIdentity("google", "google-user", "Google User", False), self.settings.session_secret, 3600),
            "other": create_session(str(self.db), WebIdentity("google", "other-user", "Other User", False), self.settings.session_secret, 3600),
        }
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def cookies(self, account):
        return {"ameba_session": self.tokens[account]}

    async def test_support_tickets_are_private_and_admin_replies_are_visible(self):
        response = await self.client.post(
            "/api/support/send", json={"message": "Please help"}, cookies=self.cookies("telegram")
        )
        self.assertEqual(response.status, 200)
        ticket_id = (await response.json())["ticket_id"]
        response = await self.client.get("/api/support", cookies=self.cookies("other"))
        self.assertEqual((await response.json())["tickets"], [])
        response = await self.client.get("/api/admin/support", cookies=self.cookies("admin"))
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            f"/api/admin/support/{ticket_id}/reply", json={"message": "We received your request"},
            cookies=self.cookies("admin"),
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/support", cookies=self.cookies("telegram"))
        tickets = (await response.json())["tickets"]
        self.assertEqual(tickets[0]["replies"][0]["message"], "We received your request")

    async def test_announcements_and_promo_are_web_managed(self):
        response = await self.client.post(
            "/api/admin/announcements", json={"title": "Update", "body": "New practice set"},
            cookies=self.cookies("admin"),
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/admin/promo", json={"text": "Welcome to AMEBA"}, cookies=self.cookies("admin")
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/announcements", cookies=self.cookies("google"))
        self.assertEqual((await response.json())["announcements"][0]["title"], "Update")
        response = await self.client.get("/api/promo", cookies=self.cookies("google"))
        self.assertEqual((await response.json())["text"], "Welcome to AMEBA")

    async def test_google_support_is_private_and_foreign_origin_cannot_submit(self):
        response = await self.client.post(
            "/api/support/send", json={"message": "Google account help"}, cookies=self.cookies("google")
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/support", cookies=self.cookies("telegram"))
        self.assertEqual((await response.json())["tickets"], [])
        response = await self.client.post(
            "/api/support/send", json={"message": "cross origin"}, cookies=self.cookies("google"),
            headers={"Origin": "https://attacker.invalid"},
        )
        self.assertEqual(response.status, 403)

    async def test_referrals_keep_telegram_and_google_ledgers_separate(self):
        response = await self.client.get("/api/referral", cookies=self.cookies("admin"))
        code = (await response.json())["ref_link"].split("ref=")[-1]
        response = await self.client.post(
            "/api/referral/claim", json={"code": code}, cookies=self.cookies("telegram")
        )
        self.assertTrue((await response.json())["claimed"])
        response = await self.client.post(
            "/api/referral/claim", json={"code": code}, cookies=self.cookies("telegram")
        )
        self.assertFalse((await response.json())["claimed"])

        response = await self.client.get("/api/referral", cookies=self.cookies("google"))
        google_code = (await response.json())["ref_link"].split("ref=")[-1]
        response = await self.client.post(
            "/api/referral/claim", json={"code": google_code}, cookies=self.cookies("other")
        )
        self.assertTrue((await response.json())["claimed"])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT points_balance FROM users WHERE user_id=123").fetchone()[0], 10)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_referrals").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_points_log").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
