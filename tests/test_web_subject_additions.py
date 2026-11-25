import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp_subject_additions import BANKS, migrate_subject_additions


class WebSubjectAdditionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "web.sqlite3")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT,
                    question TEXT,
                    option1 TEXT,
                    option2 TEXT,
                    option3 TEXT,
                    option4 TEXT,
                    option5 TEXT,
                    correct_option INTEGER,
                    explanation TEXT,
                    option6 TEXT
                )
            """)

    def tearDown(self):
        self.tmp.cleanup()

    def test_imports_all_banks_and_is_idempotent(self):
        inserted = migrate_subject_additions(self.db_path)
        second = migrate_subject_additions(self.db_path)

        self.assertEqual(inserted, {subject: expected for subject, _, expected in BANKS})
        self.assertEqual(second, {subject: 0 for subject, _, _ in BANKS})
        with sqlite3.connect(self.db_path) as conn:
            counts = dict(conn.execute(
                "SELECT subject, COUNT(*) FROM questions GROUP BY subject"
            ).fetchall())
        self.assertEqual(counts, {subject: expected for subject, _, expected in BANKS})

    def test_partial_bank_is_rejected_without_changing_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO questions (subject, question) VALUES (?, ?)",
                (BANKS[0][0], "existing partial row"),
            )

        with self.assertRaisesRegex(ValueError, "is partial"):
            migrate_subject_additions(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)

    def test_existing_bank_with_different_content_is_rejected(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO questions (subject, question) VALUES (?, ?)",
                [(BANKS[0][0], f"placeholder {n}") for n in range(BANKS[0][2])],
            )

        with self.assertRaisesRegex(ValueError, "content different"):
            migrate_subject_additions(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], BANKS[0][2])


if __name__ == "__main__":
    unittest.main()
