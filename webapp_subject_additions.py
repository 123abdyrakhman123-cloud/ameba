"""Idempotently add the four recently approved subject banks to the web DB."""

import argparse
from collections import Counter
import os
from pathlib import Path
import re
import sqlite3

from import_questions import parse_file


DATA_DIR = Path(__file__).parent / "web_question_data" / "subject_additions"
BANKS = (
    ("ped_hygiene_children", "hygiene_children_adolescents.txt", 490),
    ("mpd_hygiene_children", "hygiene_children_adolescents.txt", 490),
    ("ped_faculty_pediatrics", "faculty_pediatrics.txt", 95),
    ("ped_epidemiology", "epidemiology.txt", 494),
    ("mpd_epidemiology", "epidemiology.txt", 494),
    ("pharm_analytical_chemistry", "analytical_chemistry.txt", 419),
)


def _normalized_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (value or "").casefold())


def _repair_existing_bank_rows(conn, subject: str, expected_rows: list[tuple]) -> int | None:
    """Safely repair rows whose final option absorbed an unmarked explanation."""
    existing = conn.execute(
        """SELECT id, question, option1, option2, option3, option4, option5,
                  correct_option, explanation
           FROM questions WHERE LOWER(subject)=LOWER(?)""",
        (subject,),
    ).fetchall()

    def existing_key(row):
        return (*row[1:6], row[7])

    def expected_key(row):
        return (*row[:5], row[6])

    expected_by_key = {}
    existing_by_key = {}
    for row in expected_rows:
        expected_by_key.setdefault(expected_key(row), []).append((row[5], row[7]))
    for row in existing:
        existing_by_key.setdefault(existing_key(row), []).append(row)

    if Counter({key: len(rows) for key, rows in expected_by_key.items()}) != Counter(
        {key: len(rows) for key, rows in existing_by_key.items()}
    ):
        return None

    updates = []
    for key, expected_values in expected_by_key.items():
        remaining = list(expected_values)
        for row in existing_by_key[key]:
            _, _, _, _, _, _, old_option5, _, old_explanation = row
            matches = []
            for value in set(remaining):
                expected_option5, expected_explanation = value
                if old_option5 == expected_option5 and old_explanation == expected_explanation:
                    matches.append(value)
                elif old_explanation in (None, "") and expected_explanation:
                    if old_option5 == expected_option5 or _normalized_text(old_option5) == _normalized_text(
                        f"{expected_option5} {expected_explanation}"
                    ):
                        matches.append(value)
            if len(matches) != 1:
                return None
            expected_option5, expected_explanation = matches[0]
            remaining.remove(matches[0])
            if old_option5 != expected_option5 or old_explanation != expected_explanation:
                updates.append((expected_option5, expected_explanation, row[0]))
        if remaining:
            return None

    conn.executemany(
        "UPDATE questions SET option5=?, explanation=? WHERE id=?",
        updates,
    )
    return len(updates)


def migrate_subject_additions(db_path: str) -> dict[str, int]:
    """Insert only empty banks; reject partial banks instead of duplicating them."""
    db_path = os.path.realpath(db_path)
    if db_path == os.path.realpath("/data/questions.db"):
        raise ValueError("Refusing to modify the production bot database")

    parsed_by_file = {}
    for _, filename, expected_count in BANKS:
        if filename not in parsed_by_file:
            questions = parse_file(str(DATA_DIR / filename))
            if len(questions) != expected_count:
                raise ValueError(
                    f"{filename} contains {len(questions)} questions; expected {expected_count}"
                )
            parsed_by_file[filename] = questions

    conn = sqlite3.connect(db_path, timeout=30)
    inserted_by_bank = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)")}
        required = {
            "subject", "question", "option1", "option2", "option3", "option4",
            "option5", "correct_option", "explanation",
        }
        if not required.issubset(columns):
            raise ValueError("Web question table does not have the expected schema")

        for subject, filename, expected_count in BANKS:
            questions = parsed_by_file[filename]
            expected_rows = [
                (
                    question["question"], question["option1"], question["option2"],
                    question["option3"], question["option4"], question["option5"],
                    question["correct_option"], question["explanation"],
                )
                for question in questions
            ]
            present = conn.execute(
                "SELECT COUNT(*) FROM questions WHERE LOWER(subject)=LOWER(?)",
                (subject,),
            ).fetchone()[0]
            if present == expected_count:
                existing_rows = conn.execute(
                    """SELECT question, option1, option2, option3, option4, option5,
                              correct_option, explanation
                       FROM questions WHERE LOWER(subject)=LOWER(?)""",
                    (subject,),
                ).fetchall()
                if Counter(existing_rows) != Counter(expected_rows):
                    repaired = _repair_existing_bank_rows(conn, subject, expected_rows)
                    if repaired is None:
                        raise ValueError(f"Bank {subject} exists with content different from this release")
                inserted_by_bank[subject] = 0
                continue
            if present:
                raise ValueError(
                    f"Bank {subject} is partial ({present}/{expected_count}); refusing to append"
                )

            conn.executemany(
                """INSERT INTO questions (
                    subject, question, option1, option2, option3, option4, option5,
                    correct_option, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(subject, *row) for row in expected_rows],
            )
            inserted_by_bank[subject] = expected_count

        conn.commit()
        return inserted_by_bank
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("AMEBA_WEB_DB_PATH"), required=False)
    args = parser.parse_args()
    if not args.db:
        parser.error("--db or AMEBA_WEB_DB_PATH is required")
    result = migrate_subject_additions(args.db)
    print("Subject bank migration complete:")
    for subject, count in result.items():
        print(f"{subject}: {'inserted' if count else 'already present'} ({count or 'no changes'})")


if __name__ == "__main__":
    main()
