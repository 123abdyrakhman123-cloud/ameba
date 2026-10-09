"""Create an isolated staging database from a sanitized question catalog."""

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

from webapp_schema import init_web_database


PRODUCTION_DB = os.path.realpath("/data/questions.db")
TELEGRAM_TEST_USER_ID = 900000001
GOOGLE_TEST_SUBJECT = "staging-google-subject"


def _check_path(path: str) -> str:
    resolved = os.path.realpath(os.path.abspath(path))
    if resolved == PRODUCTION_DB:
        raise ValueError("The production bot database is never a staging seed source or destination")
    return resolved


def seed_database(source_path: str, destination_path: str) -> dict[str, int]:
    source = _check_path(source_path)
    destination = _check_path(destination_path)
    if source == destination:
        raise ValueError("Seed source and destination must be different databases")
    if not os.path.isfile(source):
        raise ValueError("Seed source database does not exist")
    if os.path.exists(destination) and os.path.getsize(destination) > 0:
        raise ValueError("Destination must be a new or empty file; refusing to overwrite existing data")

    destination_dir = os.path.dirname(destination)
    os.makedirs(destination_dir, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".ameba-web-seed-", suffix=".db", dir=destination_dir)
    os.close(fd)
    try:
        with sqlite3.connect(Path(source).as_uri() + "?mode=ro", uri=True) as source_db:
            columns = {row[1] for row in source_db.execute("PRAGMA table_info(questions)")}
            required = {
                "id", "subject", "question", "option1", "option2", "option3", "option4",
                "option5", "correct_option", "explanation",
            }
            if not required <= columns:
                raise ValueError("Source database must contain the full questions catalog schema")
            questions = source_db.execute(
                "SELECT id, subject, question, option1, option2, option3, option4, option5, "
                "correct_option, explanation FROM questions ORDER BY id"
            ).fetchall()
        if not questions:
            raise ValueError("Source database contains no questions")

        init_web_database(temporary_path)
        subjects = sorted({str(row[1]).strip().lower() for row in questions if row[1]})
        fixture_subject = "histology" if "histology" in subjects else subjects[0]
        fixture_question = next(row for row in questions if str(row[1] or "").lower() == fixture_subject)
        with sqlite3.connect(temporary_path) as destination_db:
            destination_db.executemany(
                "INSERT INTO questions(id, subject, question, option1, option2, option3, option4, option5, "
                "correct_option, explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                questions,
            )
            destination_db.execute(
                "INSERT INTO users(user_id, username, full_name) VALUES (?, ?, ?)",
                (TELEGRAM_TEST_USER_ID, "staging_learner", "Staging Telegram Learner"),
            )
            destination_db.execute(
                "INSERT INTO purchases(user_id, subject, expires_at) VALUES (?, ?, NULL)",
                (TELEGRAM_TEST_USER_ID, fixture_subject),
            )
            destination_db.execute(
                "INSERT INTO web_google_accounts(subject, email, display_name) VALUES (?, ?, ?)",
                (GOOGLE_TEST_SUBJECT, "staging-google@example.invalid", "Staging Google Learner"),
            )
            destination_db.execute(
                "INSERT INTO web_google_access_grants(google_subject, subject) VALUES (?, ?)",
                (GOOGLE_TEST_SUBJECT, fixture_subject),
            )
            destination_db.execute(
                "INSERT INTO web_google_history(google_subject, subject, question_id) VALUES (?, ?, ?)",
                (GOOGLE_TEST_SUBJECT, fixture_subject, fixture_question[0]),
            )
        os.replace(temporary_path, destination)
        return {"questions_copied": len(questions), "synthetic_telegram_users": 1, "synthetic_google_users": 1}
    except Exception:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Path to a sanitized database containing questions")
    parser.add_argument("--destination", required=True, help="New isolated staging database path")
    args = parser.parse_args()
    result = seed_database(args.source, args.destination)
    print(
        f"Seeded {result['questions_copied']} questions, "
        f"{result['synthetic_telegram_users']} synthetic Telegram user, "
        f"{result['synthetic_google_users']} synthetic Google user."
    )


if __name__ == "__main__":
    main()
