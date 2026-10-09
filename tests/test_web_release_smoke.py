import sqlite3
import tempfile
import tomllib
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_schema import init_web_database
from webapp_sessions import WebIdentity, create_session


ROOT = Path(__file__).resolve().parents[1]


class WebReleaseConfigTests(unittest.TestCase):
    def test_staging_app_volume_and_image_are_web_only(self):
        config = tomllib.loads((ROOT / "fly.staging.toml").read_text())
        self.assertIn("staging", config["app"])
        self.assertNotEqual(config["app"], "ameba-bot")
        mount = config["mounts"][0]
        self.assertEqual(mount["destination"], "/data-web")
        self.assertNotEqual(mount["source"], "ameba_data")
        self.assertEqual(config["env"]["AMEBA_WEB_DB_PATH"], "/data-web/web-staging.sqlite3")
        self.assertEqual(config["env"]["AMEBA_WEB_ENV"], "staging")
        self.assertEqual(config["http_service"]["checks"][0]["path"], "/healthz")

        dockerfile = (ROOT / "Dockerfile.web").read_text()
        self.assertIn('CMD ["python", "-u", "web_main.py"]', dockerfile)
        self.assertNotIn("COPY main.py", dockerfile)
        self.assertNotIn('CMD ["python", "-u", "main.py"]', dockerfile)
        self.assertNotIn("init_db.py", dockerfile)
        ignored = (ROOT / "Dockerfile.web.dockerignore").read_text()
        self.assertTrue(ignored.startswith("**\n"))
        self.assertIn("!web_static/**", ignored)
        self.assertNotIn("!main.py", ignored)
        self.assertNotIn("!static/**", ignored)


class WebReleaseSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "release-smoke.db"
        init_web_database(str(self.db))
        with sqlite3.connect(self.db) as conn:
            conn.executemany(
                "INSERT INTO questions(subject, question, option1, option2, correct_option, explanation) "
                "VALUES ('histology', ?, 'A', 'B', 1, 'Explanation')",
                [(f"Smoke question {index}",) for index in range(2)],
            )
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (900000001, 'staging_learner', 'Staging Learner')")
            conn.execute("INSERT INTO users(user_id, username, full_name) VALUES (900000002, 'staging_admin', 'Staging Admin')")
            conn.execute("INSERT INTO purchases(user_id, subject) VALUES (900000001, 'histology')")
            conn.execute("INSERT INTO web_google_accounts(subject, email, display_name) VALUES ('staging-google', 'staging@example.invalid', 'Staging Google')")
        self.settings = make_settings(self.db, AMEBA_WEB_ADMIN_IDS="900000002")
        tokens = {
            "telegram": WebIdentity("telegram", "900000001", "Staging Learner", False),
            "google": WebIdentity("google", "staging-google", "Staging Google", False),
            "admin": WebIdentity("telegram", "900000002", "Staging Admin", True),
        }
        self.cookies = {
            name: {"ameba_session": create_session(
                str(self.db), identity, self.settings.session_secret, 3600,
            )}
            for name, identity in tokens.items()
        }
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_staging_user_learning_support_referrals_and_admin_workflows(self):
        for provider in ("telegram", "google"):
            response = await self.client.get("/api/session", cookies=self.cookies[provider])
            self.assertTrue((await response.json())["authenticated"])

        response = await self.client.get("/api/access?subject=histology", cookies=self.cookies["telegram"])
        self.assertTrue((await response.json())["has_access"])
        response = await self.client.get("/api/access?subject=histology", cookies=self.cookies["google"])
        self.assertFalse((await response.json())["has_access"])
        response = await self.client.post(
            "/api/test/start", json={"subject": "histology"}, cookies=self.cookies["google"]
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/test/answer", json={"selected": 1, "question_id": 999999},
            cookies=self.cookies["google"],
        )
        self.assertEqual(response.status, 200)

        response = await self.client.get("/api/config", cookies=self.cookies["telegram"])
        self.assertIn("histology", (await response.json())["access"])
        response = await self.client.post(
            "/api/exam/start", json={"subject": "histology"}, cookies=self.cookies["telegram"]
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/exam/question", cookies=self.cookies["telegram"])
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/exam/answer", json={"selected": 1}, cookies=self.cookies["telegram"]
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/exam/finish", cookies=self.cookies["telegram"])
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/review", cookies=self.cookies["telegram"])
        self.assertEqual(response.status, 200)

        response = await self.client.post(
            "/api/support/send", json={"message": "Staging support check"}, cookies=self.cookies["google"]
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/admin/support", cookies=self.cookies["admin"])
        ticket = (await response.json())["tickets"][0]
        response = await self.client.post(
            f"/api/admin/support/{ticket['id']}/reply", json={"message": "Staging reply"},
            cookies=self.cookies["admin"],
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/support", cookies=self.cookies["google"])
        self.assertEqual((await response.json())["tickets"][0]["replies"][0]["message"], "Staging reply")

        response = await self.client.get("/api/referral", cookies=self.cookies["google"])
        self.assertIn("ref=web_", (await response.json())["ref_link"])
        response = await self.client.get("/api/admin/questions?q=Smoke", cookies=self.cookies["admin"])
        question = (await response.json())["questions"][0]
        response = await self.client.post(
            f"/api/admin/question/{question['id']}",
            json={"question": "Updated smoke question", "correct_option": 1},
            cookies=self.cookies["admin"],
        )
        self.assertEqual(response.status, 200)
        with sqlite3.connect(self.db) as conn:
            self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM question_history WHERE user_id=900000001").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_history WHERE google_subject='staging-google'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_history WHERE user_id=0").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
