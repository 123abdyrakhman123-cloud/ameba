import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_questions import parse_file
from webapp_subject_additions import BANKS, DATA_DIR, migrate_subject_additions


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

    def test_epidemiology_bank_has_explanations_for_every_question(self):
        questions = parse_file(str(DATA_DIR / "epidemiology.txt"))

        self.assertEqual(len(questions), 494)
        self.assertTrue(all(question["explanation"] for question in questions))

    def test_repairs_legacy_epidemiology_option_with_appended_explanation(self):
        subject = "ped_epidemiology"
        questions = parse_file(str(DATA_DIR / "epidemiology.txt"))
        legacy_rows = []
        target = questions[402]
        for index, question in enumerate(questions):
            row = (
                question["question"], question["option1"], question["option2"],
                question["option3"], question["option4"], question["option5"],
                question["correct_option"], question["explanation"],
            )
            if index == 402:
                row = (*row[:5], f"{row[5]} {row[7]}", row[6], None)
            legacy_rows.append((subject, *row))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO questions (
                    subject, question, option1, option2, option3, option4, option5,
                    correct_option, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                legacy_rows,
            )

        migrate_subject_additions(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            repaired = conn.execute(
                """SELECT option5, explanation FROM questions
                   WHERE subject=? AND question=? AND option1=? AND option2=?
                     AND option3=? AND option4=?""",
                (subject, target["question"], target["option1"], target["option2"],
                 target["option3"], target["option4"]),
            ).fetchone()
        self.assertEqual(repaired, (target["option5"], target["explanation"]))
        self.assertEqual(migrate_subject_additions(self.db_path)[subject], 0)

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
