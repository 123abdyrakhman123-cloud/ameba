import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_learning_data import record_activity_event, save_exam_result
from webapp_schema import init_web_database
from webapp_sessions import WebIdentity, create_session


class WebDashboardApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "dashboard.db"
        init_web_database(str(self.db_path))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO questions(subject, question, option1, option2, correct_option) VALUES (?, ?, ?, ?, ?)",
                [("histology", "Cell membrane question", "A", "B", 1),
                 ("pharmacology", "Drug dosage question", "A", "B", 2)],
            )
            conn.execute("INSERT INTO users(user_id, username, full_name, points_balance) VALUES (11, 'private_user', 'Nina', 42)")
            conn.execute("INSERT INTO purchases(user_id, subject) VALUES (11, 'histology')")
            conn.execute("INSERT INTO web_google_accounts(subject, email, display_name) VALUES ('private-google', 'private@example.test', 'Google User')")
            conn.execute("INSERT INTO web_google_access_grants(google_subject, subject) VALUES ('private-google', 'pharmacology')")
            conn.execute("INSERT INTO web_points_log(provider, account_key, delta, reason) VALUES ('google', 'private-google', 12, 'test')")
        self.settings = make_settings(self.db_path)
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()
        self.tokens = {
            "telegram": create_session(str(self.db_path), WebIdentity("telegram", "11", "Nina", False), self.settings.session_secret, 3600),
            "google": create_session(str(self.db_path), WebIdentity("google", "private-google", "Google User", False), self.settings.session_secret, 3600),
            "empty": create_session(str(self.db_path), WebIdentity("google", "empty", "Empty", False), self.settings.session_secret, 3600),
        }

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def cookies(self, name="telegram"):
        return {"ameba_session": self.tokens[name]}

    async def test_dashboard_uses_real_catalog_and_zero_activity_values(self):
        response = await self.client.get("/api/dashboard", cookies=self.cookies("empty"))
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["catalog"], {"question_count": 2, "subject_count": 2})
        self.assertEqual(data["activity"], {"answers_today": 0, "active_days_7": 0, "streak_days": 0})
        self.assertEqual(data["recent_exams"], [])
        self.assertEqual({item["key"] for item in data["subjects"]}, {"histology", "pharmacology"})

    async def test_exam_completion_is_not_counted_as_an_answer(self):
        record_activity_event(
            self.db_path, WebIdentity("telegram", "11", "Nina", False), "histology",
            "exam_completed", "completed-only", datetime.now(timezone.utc).isoformat(),
        )
        response = await self.client.get("/api/dashboard", cookies=self.cookies("telegram"))
        self.assertEqual((await response.json())["activity"]["answers_today"], 0)

    async def test_progress_returns_scoped_exam_history_and_streak(self):
        identity = WebIdentity("telegram", "11", "Nina", False)
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        for day in (yesterday, datetime.now(timezone.utc).date()):
            record_activity_event(self.db_path, identity, "histology", "practice_answer", day.isoformat() + ":event", day.isoformat() + "T12:00:00+00:00")
        save_exam_result(self.db_path, identity, {
            "exam_session_key": "progress-exam", "subject": "histology", "started_at": "2026-10-08T10:00:00+00:00",
            "completed_at": "2026-10-08T10:10:00+00:00", "elapsed_seconds": 600, "total": 2,
            "answered": 2, "correct": 1, "score": 2, "max_score": 4, "time_expired": False,
        }, [])
        response = await self.client.get("/api/progress", cookies=self.cookies("telegram"))
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["summary"]["exam_count"], 1)
        self.assertEqual(data["summary"]["accuracy_percent"], 50)
        self.assertEqual(len(data["activity_by_day"]), 2)
        self.assertEqual(data["exams"][0]["subject"], "histology")

    async def test_leaderboard_requires_opt_in_and_redacts_identity(self):
        response = await self.client.get("/api/leaderboard", cookies=self.cookies("telegram"))
        self.assertEqual((await response.json())["entries"], [])
        response = await self.client.post(
            "/api/leaderboard/visibility", json={"enabled": True, "display_name": "Nina Study"},
            cookies=self.cookies("telegram"), headers={"Origin": self.settings.base_url},
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/leaderboard", cookies=self.cookies("telegram"))
        data = await response.json()
        self.assertEqual(data["entries"][0]["display_name"], "Nina Study")
        encoded = json.dumps(data)
        self.assertNotIn("account_key", encoded)
        self.assertNotIn("private_user", encoded)
        self.assertNotIn("private-google", encoded)
        self.assertNotIn("private@example.test", encoded)

    async def test_leaderboard_name_is_validated_and_write_is_same_origin(self):
        response = await self.client.post(
            "/api/leaderboard/visibility", json={"enabled": True, "display_name": ""},
            cookies=self.cookies("telegram"),
        )
        self.assertEqual(response.status, 422)
        response = await self.client.post(
            "/api/leaderboard/visibility", json={"enabled": True, "display_name": "Nina"},
            cookies=self.cookies("telegram"), headers={"Origin": "https://evil.test"},
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/leaderboard/visibility", json={"enabled": True, "display_name": "  Nina   Study\x00 "},
            cookies=self.cookies("telegram"), headers={"Origin": self.settings.base_url},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["display_name"], "Nina Study")

    async def test_search_returns_question_snippets_without_answers(self):
        response = await self.client.get("/api/search?q=Cell", cookies=self.cookies("telegram"))
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertGreaterEqual(len(data["questions"]), 1)
        self.assertNotIn("correct_option", data["questions"][0])
        self.assertNotIn("option1", data["questions"][0])
        wildcard = await self.client.get("/api/search?q=%25", cookies=self.cookies("telegram"))
        self.assertEqual((await wildcard.json())["questions"], [])

    async def test_profile_returns_provider_and_access_without_secrets(self):
        response = await self.client.get("/api/profile", cookies=self.cookies("telegram"))
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["provider"], "telegram")
        self.assertEqual(data["display_name"], "Nina")
        self.assertTrue(next(item for item in data["access"] if item["subject"] == "histology")["active"])
        encoded = json.dumps(data)
        self.assertNotIn("account_key", encoded)
        self.assertNotIn("private_user", encoded)


if __name__ == "__main__":
    unittest.main()
