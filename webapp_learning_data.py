from datetime import date, datetime, timedelta, timezone
import sqlite3

from webapp_catalog import FACULTIES
from webapp_sessions import WebIdentity


def _subject_names():
    names = {}
    for faculty in FACULTIES.values():
        for subjects in faculty["subjects"].values():
            for subject in subjects:
                names[subject["key"].lower()] = subject["name"]
    return names


def _owner(identity):
    if identity.provider not in {"telegram", "google"} or not identity.account_key:
        raise ValueError("A valid web identity is required")
    return identity.provider, str(identity.account_key)


def _result_dict(row):
    return {
        "id": row[0], "subject": row[1], "started_at": row[2], "completed_at": row[3],
        "elapsed_seconds": row[4], "total": row[5], "answered": row[6],
        "correct": row[7], "score": row[8], "max_score": row[9],
        "time_expired": bool(row[10]),
    }


def save_exam_result(db_path: str, identity: WebIdentity, summary: dict, answers: list[dict]) -> int:
    provider, account_key = _owner(identity)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT OR IGNORE INTO web_exam_results "
            "(provider, account_key, exam_session_key, subject, started_at, completed_at, "
            "elapsed_seconds, total, answered, correct, score, max_score, time_expired) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (provider, account_key, summary["exam_session_key"], summary["subject"].lower(),
             summary["started_at"], summary["completed_at"], int(summary["elapsed_seconds"]),
             int(summary["total"]), int(summary["answered"]), int(summary["correct"]),
             int(summary["score"]), int(summary["max_score"]), int(bool(summary["time_expired"]))),
        )
        row = conn.execute(
            "SELECT id FROM web_exam_results WHERE provider=? AND account_key=? AND exam_session_key=?",
            (provider, account_key, summary["exam_session_key"]),
        ).fetchone()
        result_id = row[0]
        if conn.execute("SELECT changes()").fetchone()[0]:
            conn.executemany(
                "INSERT INTO web_exam_answers "
                "(result_id, question_id, question_order, selected_option, correct_option, is_correct, explanation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(result_id, int(answer["question_id"]), int(answer["question_order"]),
                  answer.get("selected_option"), answer.get("correct_option"),
                  int(bool(answer.get("is_correct"))), answer.get("explanation", ""))
                 for answer in answers],
            )
    return result_id


def record_activity_event(
    db_path: str, identity: WebIdentity, subject: str, event_type: str, event_key: str,
    occurred_at: str | None = None,
) -> bool:
    provider, account_key = _owner(identity)
    timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO web_activity_events "
            "(provider, account_key, subject, event_type, event_key, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider, account_key, subject.lower(), event_type, event_key, timestamp),
        )
        return cursor.rowcount == 1


def _load_activity(conn, provider, account_key):
    rows = conn.execute(
        "SELECT occurred_at FROM web_activity_events WHERE provider=? AND account_key=? ORDER BY occurred_at",
        (provider, account_key),
    ).fetchall()
    days = set()
    for (occurred_at,) in rows:
        try:
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            days.add(parsed.astimezone(timezone.utc).date())
        except (TypeError, ValueError):
            continue
    today = datetime.now(timezone.utc).date()
    streak = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return rows, days, streak


def _access_subjects(conn, identity):
    provider, account_key = _owner(identity)
    if provider == "telegram":
        try:
            user_id = int(account_key)
        except ValueError:
            return set()
        rows = conn.execute(
            "SELECT subject, expires_at FROM purchases WHERE user_id=?", (user_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT subject, expires_at FROM web_google_access_grants WHERE google_subject=?", (account_key,)
        ).fetchall()
    now = datetime.now()
    active = set()
    for subject, expires_at in rows:
        if expires_at is None:
            active.add(subject.lower())
            continue
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo:
                expiry = expiry.astimezone().replace(tzinfo=None)
            if expiry >= now:
                active.add(subject.lower())
        except (TypeError, ValueError):
            active.add(subject.lower())
    return active


def get_dashboard_data(db_path: str, identity: WebIdentity) -> dict:
    provider, account_key = _owner(identity)
    names = _subject_names()
    with sqlite3.connect(db_path) as conn:
        catalog_rows = conn.execute(
            "SELECT LOWER(subject), COUNT(*) FROM questions WHERE COALESCE(subject, '')<>'' "
            "GROUP BY LOWER(subject) ORDER BY LOWER(subject)"
        ).fetchall()
        activity_rows, days, streak = _load_activity(conn, provider, account_key)
        today = datetime.now(timezone.utc).date()
        last_week = today - timedelta(days=6)
        today_count = sum(
            1 for (stamp,) in activity_rows
            if _utc_date(stamp) == today
        )
        active_days = sum(1 for day in days if last_week <= day <= today)
        access = _access_subjects(conn, identity)
        summaries = conn.execute(
            "SELECT id, subject, started_at, completed_at, elapsed_seconds, total, answered, correct, "
            "score, max_score, time_expired FROM web_exam_results "
            "WHERE provider=? AND account_key=? ORDER BY completed_at DESC LIMIT 5",
            (provider, account_key),
        ).fetchall()
    subjects = [{
        "key": key, "name": names.get(key, key.replace("_", " ").title()),
        "question_count": count, "access": key in access,
    } for key, count in catalog_rows]
    return {
        "catalog": {"question_count": sum(count for _, count in catalog_rows), "subject_count": len(catalog_rows)},
        "access": {"subject_count": sum(1 for subject in subjects if subject["access"])},
        "activity": {"answers_today": today_count, "active_days_7": active_days, "streak_days": streak},
        "recent_exams": [_result_dict(row) for row in summaries],
        "subjects": subjects,
    }


def _utc_date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date()
    except (TypeError, ValueError):
        return None


def get_progress_data(db_path: str, identity: WebIdentity) -> dict:
    provider, account_key = _owner(identity)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, subject, started_at, completed_at, elapsed_seconds, total, answered, correct, "
            "score, max_score, time_expired FROM web_exam_results "
            "WHERE provider=? AND account_key=? ORDER BY completed_at DESC",
            (provider, account_key),
        ).fetchall()
        activity = conn.execute(
            "SELECT occurred_at, subject FROM web_activity_events WHERE provider=? AND account_key=?",
            (provider, account_key),
        ).fetchall()
    by_day = {}
    for occurred_at, _ in activity:
        day = _utc_date(occurred_at)
        if day:
            key = day.isoformat()
            by_day[key] = by_day.get(key, 0) + 1
    by_subject = {}
    for row in rows:
        item = by_subject.setdefault(row[1], {"key": row[1], "exam_count": 0, "answered": 0, "correct": 0})
        item["exam_count"] += 1
        item["answered"] += row[6]
        item["correct"] += row[7]
    for item in by_subject.values():
        item["accuracy_percent"] = round(item["correct"] * 100 / item["answered"]) if item["answered"] else None
    answered = sum(row[6] for row in rows)
    correct = sum(row[7] for row in rows)
    exams = [_result_dict(row) for row in rows]
    return {
        "summary": {
            "exam_count": len(rows), "answered": answered, "correct": correct,
            "accuracy_percent": round(correct * 100 / answered) if answered else None,
        },
        "activity_by_day": [{"date": day, "count": by_day[day]} for day in sorted(by_day)],
        "subjects": sorted(by_subject.values(), key=lambda item: item["key"]),
        "exams": exams,
    }
