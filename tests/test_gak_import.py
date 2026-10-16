import sqlite3
import tempfile
import unittest
from pathlib import Path

from gak_catalog import GAK_SECTIONS, GAK_SUBJECTS_BY_SECTION
from gak_import import import_gak_surgery_questions, import_question_files, parse_question_text


class GakImportTests(unittest.TestCase):
    def test_parse_question_text_accepts_markdown_escaped_markers(self):
        source = r"""\[Q\] Вопрос?  
\[A-\] Неверный ответ  
\[A+\] Верный ответ  
\[E\] Объяснение с точкой\.  
\[/\]"""

        self.assertEqual(parse_question_text(source), [
            {
                "question": "Вопрос?",
                "options": ["Неверный ответ", "Верный ответ", None, None, None],
                "correct_option": 2,
                "explanation": "Объяснение с точкой.",
            }
        ])

    def test_import_is_repeatable_without_duplicate_questions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "questions.db"
            source_path = Path(temp_dir) / "Хирургия.md"
            source_path.write_text(
                "[Q] Вопрос?\n[A+] Ответ\n[A-] Дистрактор\n[/]",
                encoding="utf-8",
            )
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE questions (id INTEGER PRIMARY KEY, subject TEXT, question TEXT, "
                "option1 TEXT, option2 TEXT, option3 TEXT, option4 TEXT, option5 TEXT, "
                "correct_option INTEGER, explanation TEXT)"
            )
            conn.commit()
            conn.close()

            import_question_files(db_path, [(source_path, "gak_lech6_surg_test")])
            import_question_files(db_path, [(source_path, "gak_lech6_surg_test")])

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT subject, question, correct_option FROM questions"
            ).fetchall()
            conn.close()
            self.assertEqual(rows, [("gak_lech6_surg_test", "Вопрос?", 1)])

    def test_catalog_keeps_the_requested_five_section_hierarchy(self):
        self.assertEqual(
            [section["key"] for section in GAK_SECTIONS],
            ["surgery", "therapy", "ozz", "pediatrics", "aig"],
        )
        self.assertEqual(len(GAK_SUBJECTS_BY_SECTION["surgery"]), 14)
        self.assertTrue(all(not GAK_SUBJECTS_BY_SECTION[key] for key in ("therapy", "ozz", "pediatrics", "aig")))

    def test_all_surgery_files_parse_to_the_expected_question_count(self):
        from gak_import import DATA_DIR
        from gak_catalog import GAK_SURGERY_SUBJECTS

        total = 0
        for subject in GAK_SURGERY_SUBJECTS:
            path = DATA_DIR / subject["file"]
            self.assertTrue(path.exists(), path)
            questions = parse_question_text(path.read_text(encoding="utf-8-sig"))
            self.assertTrue(questions, subject["file"])
            total += len(questions)
        self.assertEqual(total, 1159)

    def test_startup_import_adds_all_surgery_questions_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "questions.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE questions (id INTEGER PRIMARY KEY, subject TEXT, question TEXT, "
                "option1 TEXT, option2 TEXT, option3 TEXT, option4 TEXT, option5 TEXT, "
                "correct_option INTEGER, explanation TEXT)"
            )
            conn.commit()
            conn.close()

            self.assertEqual(import_gak_surgery_questions(db_path), 1159)
            self.assertEqual(import_gak_surgery_questions(db_path), 0)

            conn = sqlite3.connect(db_path)
            total, subject_count = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT subject) FROM questions"
            ).fetchone()
            conn.close()
            self.assertEqual((total, subject_count), (1159, 14))


if __name__ == "__main__":
    unittest.main()
