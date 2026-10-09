import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_sessions import WebIdentity, create_session
from webapp_schema import init_web_database


class WebLearningApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "learning.db"
        init_web_database(str(self.db_path))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO questions(subject, question, option1, option2, correct_option, explanation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("histology", "Question one", "A", "B", 1, "Because A"),
                    ("histology", "Question two", "A", "B", 2, "Because B"),
                ],
            )
            conn.execute(
                "INSERT INTO users(user_id, username, full_name) VALUES (101, 'telegram101', 'Telegram One')"
            )
            conn.execute(
                "INSERT INTO purchases(user_id, subject, expires_at) VALUES (101, 'histology', '2099-01-01')"
            )
            conn.execute(
                "INSERT INTO web_google_accounts(subject, email, display_name) VALUES ('google-a', 'a@example.test', 'Google A')"
            )
        self.settings = make_settings(self.db_path)
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()
        self.tokens = {
            "telegram-a": create_session(
                str(self.db_path), WebIdentity("telegram", "101", "Telegram One", False),
                self.settings.session_secret, 3600,
            ),
            "telegram-b": create_session(
                str(self.db_path), WebIdentity("telegram", "202", "Telegram Two", False),
                self.settings.session_secret, 3600,
            ),
            "google-a": create_session(
                str(self.db_path), WebIdentity("google", "google-a", "Google A", False),
                self.settings.session_secret, 3600,
            ),
            "google-b": create_session(
                str(self.db_path), WebIdentity("google", "google-b", "Google B", False),
                self.settings.session_secret, 3600,
            ),
        }

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def cookies(self, account):
        return {"ameba_session": self.tokens[account]}

    async def test_verified_telegram_id_uses_existing_purchase(self):
        response = await self.client.get(
            "/api/access?subject=histology", cookies=self.cookies("telegram-a")
        )
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["has_access"])
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=101").fetchone()[0], 1)

    async def test_google_profile_isolated_from_telegram_tables(self):
        response = await self.client.get("/api/access?subject=histology", cookies=self.cookies("google-a"))
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["has_access"])
        response = await self.client.post(
            "/api/test/start", json={"subject": "histology", "user_id": 101},
            cookies=self.cookies("google-a"),
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/test/answer",
            json={"selected": 1, "question_id": 999999, "user_id": 101},
            cookies=self.cookies("google-a"),
        )
        self.assertEqual(response.status, 200)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_history WHERE google_subject='google-a'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_trials WHERE google_subject='google-a'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_learning_sessions WHERE google_subject='google-a'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_history WHERE user_id=101").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id=101").fetchone()[0], 1)
        response = await self.client.get("/api/test/next", cookies=self.cookies("google-b"))
        self.assertEqual(response.status, 400)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_history WHERE google_subject='google-b'").fetchone()[0], 0)

    async def test_learning_data_is_scoped_to_verified_telegram_id(self):
        response = await self.client.post(
            "/api/test/start", json={"subject": "histology", "user_id": 202},
            cookies=self.cookies("telegram-a"),
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/test/answer", json={"selected": 1, "question_id": 1, "user_id": 101},
            cookies=self.cookies("telegram-b"),
        )
        self.assertEqual(response.status, 400)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_history WHERE user_id=101").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_history WHERE user_id=202").fetchone()[0], 0)

    async def test_catalog_exam_review_and_missing_session_contract(self):
        response = await self.client.get("/api/access?subject=histology")
        self.assertEqual(response.status, 401)
        response = await self.client.post(
            "/api/purchase/select", json={"subject": "histology", "period": "forever"},
            cookies=self.cookies("telegram-a"),
        )
        self.assertEqual(response.status, 404)
        response = await self.client.get("/api/config", cookies=self.cookies("telegram-a"))
        self.assertEqual(response.status, 200)
        catalog = await response.json()
        self.assertIn("histology", catalog["access"])
        response = await self.client.post(
            "/api/exam/start", json={"subject": "histology"}, cookies=self.cookies("telegram-a")
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/exam/question", cookies=self.cookies("telegram-a"))
        self.assertEqual(response.status, 200)
        question = (await response.json())["question"]
        response = await self.client.post(
            "/api/exam/answer", json={"selected": 1}, cookies=self.cookies("telegram-a")
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/exam/finish", cookies=self.cookies("telegram-a"))
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/review", cookies=self.cookies("telegram-a"))
        self.assertEqual(response.status, 200)
        self.assertGreaterEqual((await response.json())["total"], 1)


if __name__ == "__main__":
    unittest.main()
