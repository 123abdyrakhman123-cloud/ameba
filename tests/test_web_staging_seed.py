import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.seed_web_staging import seed_database


class WebStagingSeedTests(unittest.TestCase):
    def test_seed_copies_only_questions_and_adds_synthetic_provider_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            destination = Path(tmp) / "staging" / "web.db"
            with sqlite3.connect(source) as conn:
                conn.execute("CREATE TABLE questions(id INTEGER PRIMARY KEY, subject TEXT, question TEXT, option1 TEXT, option2 TEXT, option3 TEXT, option4 TEXT, option5 TEXT, correct_option INTEGER, explanation TEXT)")
                conn.execute("INSERT INTO questions VALUES (42, 'histology', 'Synthetic question', 'A', 'B', NULL, NULL, NULL, 1, 'Explain')")
                conn.execute("CREATE TABLE users(user_id INTEGER, username TEXT)")
                conn.execute("INSERT INTO users VALUES (123456, 'production-user-must-not-copy')")
                conn.execute("CREATE TABLE purchases(user_id INTEGER, subject TEXT, expires_at TEXT)")
                conn.execute("INSERT INTO purchases VALUES (123456, 'histology', NULL)")

            result = seed_database(str(source), str(destination))
            self.assertEqual(result["questions_copied"], 1)
            with sqlite3.connect(destination) as conn:
                self.assertEqual(conn.execute("SELECT question FROM questions").fetchall(), [("Synthetic question",)])
                self.assertEqual(conn.execute("SELECT user_id, username FROM users").fetchall(), [(900000001, "staging_learner")])
                self.assertEqual(conn.execute("SELECT user_id, subject FROM purchases").fetchall(), [(900000001, "histology")])
                self.assertEqual(conn.execute("SELECT subject FROM web_google_accounts").description[0][0], "subject")
                self.assertEqual(conn.execute("SELECT subject, question_id FROM web_google_history").fetchall(), [("histology", 42)])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_history").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM points_log").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_sessions").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_google_accounts").fetchone()[0], 1)

    def test_production_path_is_rejected_as_seed_source_or_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            source.touch()
            for db_path in ("/data/questions.db",):
                with self.assertRaises(ValueError):
                    seed_database(db_path, str(Path(tmp) / "out.db"))
                with self.assertRaises(ValueError):
                    seed_database(str(source), db_path)

    def test_non_empty_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            destination = Path(tmp) / "destination.db"
            source.touch()
            with sqlite3.connect(destination) as conn:
                conn.execute("CREATE TABLE user_data(value TEXT)")
            with self.assertRaises(ValueError):
                seed_database(str(source), str(destination))


if __name__ == "__main__":
    unittest.main()
