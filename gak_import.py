"""Import GAK question files into the bot's persistent SQLite database."""

import re
import sqlite3
from pathlib import Path

from gak_catalog import GAK_SURGERY_SUBJECTS


DATA_DIR = Path(__file__).parent / "question_data" / "gak" / "lech" / "6" / "surgery"


def _normalize_markers(text):
    text = re.sub(r"\\\[(Q|A\+|A-|E|/)\\\]", r"[\1]", text)
    return re.sub(r"\\([.!?()])", r"\1", text)


def parse_question_text(text):
    questions = []
    for block in _normalize_markers(text).split("[/]"):
        question = None
        options = []
        correct_option = None
        explanation = []
        in_explanation = False

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[Q]"):
                question = line[3:].strip()
                in_explanation = False
            elif line.startswith("[A+]"):
                options.append(line[4:].strip())
                correct_option = len(options)
                in_explanation = False
            elif line.startswith("[A-]"):
                options.append(line[4:].strip())
                in_explanation = False
            elif line.startswith("[E]"):
                explanation.append(line[3:].strip())
                in_explanation = True
            elif in_explanation:
                explanation.append(line)
            elif question and not options:
                question += " " + line

        if not question or len(options) < 2 or correct_option is None:
            continue
        options = options[:5]
        options.extend([None] * (5 - len(options)))
        questions.append({
            "question": question,
            "options": options,
            "correct_option": correct_option,
            "explanation": " ".join(explanation).strip() or None,
        })
    return questions


def import_question_files(db_path, files):
    """Import missing subject/question pairs; safe to call at every container start."""
    conn = sqlite3.connect(db_path)
    inserted = 0
    try:
        with conn:
            for filepath, subject in files:
                text = Path(filepath).read_text(encoding="utf-8-sig")
                seen_questions = set()
                for item in parse_question_text(text):
                    question = item["question"]
                    if question in seen_questions:
                        continue
                    seen_questions.add(question)
                    cursor = conn.execute(
                        """INSERT INTO questions (
                            subject, question, option1, option2, option3,
                            option4, option5, correct_option, explanation
                        ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM questions WHERE subject = ? AND question = ?
                        )""",
                        (
                            subject, question, *item["options"],
                            item["correct_option"], item["explanation"],
                            subject, question,
                        ),
                    )
                    inserted += cursor.rowcount
    finally:
        conn.close()
    return inserted


def import_gak_surgery_questions(db_path, data_dir=DATA_DIR):
    files = [
        (Path(data_dir) / subject["file"], subject["key"])
        for subject in GAK_SURGERY_SUBJECTS
    ]
    return import_question_files(db_path, files)
