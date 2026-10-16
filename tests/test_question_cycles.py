import sqlite3
import unittest

from question_cycles import mark_question_shown, next_practice_question, select_exam_questions


class QuestionCycleTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY, subject TEXT, question TEXT,
                option1 TEXT, option2 TEXT, option3 TEXT, option4 TEXT,
                option5 TEXT, correct_option INTEGER, explanation TEXT
            );
            CREATE TABLE question_history (
                id INTEGER PRIMARY KEY, user_id INTEGER, subject TEXT,
                question_id INTEGER, asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE question_cycle_seen (
                provider TEXT NOT NULL, account_key TEXT NOT NULL, subject TEXT NOT NULL,
                question_id INTEGER NOT NULL, shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(provider, account_key, subject, question_id)
            );
        """)
        self.conn.executemany(
            "INSERT INTO questions(id, subject, question) VALUES (?, 'histology', ?)",
            [(1, "one"), (2, "two"), (3, "three")],
        )

    def tearDown(self):
        self.conn.close()

    def test_practice_exhausts_all_questions_before_starting_new_cycle(self):
        issued = [next_practice_question(self.conn, "telegram", "101", "histology")[0] for _ in range(3)]
        self.assertEqual(set(issued), {1, 2, 3})
        self.assertIn(next_practice_question(self.conn, "telegram", "101", "histology")[0], {1, 2, 3})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM question_history").fetchone()[0], 4)

    def test_exam_prioritizes_unseen_and_records_only_questions_marked_shown(self):
        seen_id = next_practice_question(self.conn, "telegram", "101", "histology")[0]
        exam = select_exam_questions(self.conn, "telegram", "101", "histology", limit=3)
        self.assertEqual(len({question[0] for question in exam}), 3)
        self.assertEqual(len([q for q in exam if q[0] != seen_id]), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM question_history").fetchone()[0], 1)

        new_id = next(question[0] for question in exam if question[0] != seen_id)
        mark_question_shown(self.conn, "telegram", "101", "histology", new_id)
        mark_question_shown(self.conn, "telegram", "101", "histology", new_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM question_history").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
