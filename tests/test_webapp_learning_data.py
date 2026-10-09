import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp_schema import init_web_database
from webapp_sessions import WebIdentity


class WebLearningDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "web.db")
        init_web_database(self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO questions(subject, question, correct_option) VALUES (?, ?, ?)",
                [("histology", "Cell question", 1), ("pharmacology", "Drug question", 2)],
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_is_idempotent_and_stores_web_results(self):
        from webapp_learning_data import save_exam_result

        init_web_database(self.db_path)
        identity = WebIdentity("telegram", "101", "Ruslan", False)
        result_id = save_exam_result(self.db_path, identity, {
            "exam_session_key": "exam-one", "subject": "histology",
            "started_at": "2026-10-09T10:00:00+00:00", "completed_at": "2026-10-09T10:10:00+00:00",
            "elapsed_seconds": 600, "total": 2, "answered": 2, "correct": 1,
            "score": 2, "max_score": 4, "time_expired": False,
        }, [
            {"question_id": 1, "question_order": 0, "selected_option": 1,
             "correct_option": 1, "is_correct": True, "explanation": "Correct"},
            {"question_id": 2, "question_order": 1, "selected_option": 1,
             "correct_option": 2, "is_correct": False, "explanation": "Review"},
        ])

        with sqlite3.connect(self.db_path) as conn:
            summary = conn.execute(
                "SELECT provider, account_key, subject, total, answered, correct FROM web_exam_results WHERE id=?",
                (result_id,),
            ).fetchone()
            answers = conn.execute(
                "SELECT COUNT(*) FROM web_exam_answers WHERE result_id=?", (result_id,)
            ).fetchone()[0]
        self.assertEqual(summary, ("telegram", "101", "histology", 2, 2, 1))
        self.assertEqual(answers, 2)

    def test_exam_history_and_activity_are_scoped_by_provider_and_account(self):
        from webapp_learning_data import get_progress_data, record_activity_event, save_exam_result

        identities = [
            WebIdentity("telegram", "101", "Ruslan", False),
            WebIdentity("google", "google-a", "A", False),
            WebIdentity("google", "local-demo-account", "Demo", False),
        ]
        for idx, identity in enumerate(identities):
            save_exam_result(self.db_path, identity, {
                "exam_session_key": f"exam-{idx}", "subject": "histology",
                "started_at": "2026-10-09T10:00:00+00:00", "completed_at": "2026-10-09T10:10:00+00:00",
                "elapsed_seconds": 600, "total": 1, "answered": 1, "correct": 1,
                "score": 2, "max_score": 2, "time_expired": False,
            }, [])
            self.assertTrue(record_activity_event(
                self.db_path, identity, "histology", "exam", f"activity-{idx}",
                "2026-10-09T10:10:00+00:00",
            ))
            self.assertFalse(record_activity_event(
                self.db_path, identity, "histology", "exam", f"activity-{idx}",
                "2026-10-09T10:10:00+00:00",
            ))

        for identity in identities:
            progress = get_progress_data(self.db_path, identity)
            self.assertEqual(progress["summary"]["exam_count"], 1)
            self.assertEqual(len(progress["exams"]), 1)

    def test_empty_activity_does_not_claim_accuracy(self):
        from webapp_learning_data import get_progress_data

        progress = get_progress_data(
            self.db_path, WebIdentity("google", "empty-account", "Empty", False)
        )
        self.assertIsNone(progress["summary"]["accuracy_percent"])
        self.assertEqual(progress["summary"]["answered"], 0)


if __name__ == "__main__":
    unittest.main()
