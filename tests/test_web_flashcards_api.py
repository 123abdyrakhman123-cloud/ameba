import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.test_webapp_runtime import make_settings
from webapp_schema import init_web_database
from webapp_sessions import WebIdentity, create_session


class WebFlashcardsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "cards.db"
        init_web_database(str(self.db_path))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO questions(subject, question, option1, option2, correct_option, explanation) "
                "VALUES ('histology', 'Cell membrane', 'Lipid bilayer', 'Protein wall', 1, 'Phospholipids')"
            )
            conn.execute("INSERT INTO purchases(user_id, subject) VALUES (41, 'histology')")
            conn.execute("INSERT INTO purchases(user_id, subject) VALUES (42, 'histology')")
            conn.execute("INSERT INTO web_google_access_grants(google_subject, subject) VALUES ('google-card', 'histology')")
            conn.execute("INSERT INTO web_google_access_grants(google_subject, subject) VALUES ('google-card', 'empty-subject')")
        self.settings = make_settings(self.db_path)
        from webapp_server import create_web_app
        self.client = TestClient(TestServer(create_web_app(self.settings)))
        await self.client.start_server()
        self.tokens = {
            "telegram": create_session(str(self.db_path), WebIdentity("telegram", "41", "T", False), self.settings.session_secret, 3600),
            "other-telegram": create_session(str(self.db_path), WebIdentity("telegram", "42", "Other", False), self.settings.session_secret, 3600),
            "no-access": create_session(str(self.db_path), WebIdentity("telegram", "43", "No access", False), self.settings.session_secret, 3600),
            "google": create_session(str(self.db_path), WebIdentity("google", "google-card", "G", False), self.settings.session_secret, 3600),
        }

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def cookies(self, name="telegram"):
        return {"ameba_session": self.tokens[name]}

    async def test_flashcard_front_hides_answer_until_reveal(self):
        response = await self.client.get("/api/flashcards?subject=histology", cookies=self.cookies())
        self.assertEqual(response.status, 200)
        card = (await response.json())["cards"][0]
        self.assertEqual(card["question"], "Cell membrane")
        self.assertNotIn("options", card)
        self.assertNotIn("correct_option", card)
        response = await self.client.get(f"/api/flashcards/{card['question_id']}/reveal", cookies=self.cookies())
        self.assertEqual(response.status, 200)
        reveal = await response.json()
        self.assertEqual(reveal["answer"], "Lipid bilayer")
        self.assertEqual(reveal["explanation"], "Phospholipids")

    async def test_flashcard_review_state_survives_reload(self):
        cards = await self.client.get("/api/flashcards?subject=histology", cookies=self.cookies())
        question_id = (await cards.json())["cards"][0]["question_id"]
        response = await self.client.post(
            f"/api/flashcards/{question_id}/review", json={"state": "known", "review_key": "review-one"},
            cookies=self.cookies(),
        )
        self.assertEqual(response.status, 200)
        cards = await self.client.get("/api/flashcards?subject=histology&state=known", cookies=self.cookies())
        self.assertEqual((await cards.json())["cards"][0]["state"], "known")

    async def test_flashcard_state_isolated_between_providers_and_accounts(self):
        cards = await self.client.get("/api/flashcards?subject=histology", cookies=self.cookies())
        question_id = (await cards.json())["cards"][0]["question_id"]
        await self.client.post(
            f"/api/flashcards/{question_id}/review", json={"state": "repeat"}, cookies=self.cookies()
        )
        for account in ("other-telegram", "google"):
            cards = await self.client.get(
                "/api/flashcards?subject=histology", cookies=self.cookies(account)
            )
            self.assertEqual((await cards.json())["cards"][0]["state"], "new")

    async def test_flashcard_access_is_enforced(self):
        response = await self.client.get(
            "/api/flashcards?subject=histology", cookies=self.cookies("no-access")
        )
        self.assertEqual(response.status, 403)

    async def test_flashcards_empty_catalog_and_invalid_state(self):
        response = await self.client.get(
            "/api/flashcards?subject=empty-subject", cookies=self.cookies("google")
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["cards"], [])
        response = await self.client.get(
            "/api/flashcards?subject=histology&state=wrong", cookies=self.cookies()
        )
        self.assertEqual(response.status, 422)
        response = await self.client.post(
            "/api/flashcards/1/review", json={"state": "wrong"}, cookies=self.cookies()
        )
        self.assertEqual(response.status, 422)


if __name__ == "__main__":
    unittest.main()
