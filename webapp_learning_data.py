from datetime import date, datetime, timedelta, timezone
import sqlite3
import unicodedata

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
        "SELECT occurred_at, event_type FROM web_activity_events WHERE provider=? AND account_key=? ORDER BY occurred_at",
        (provider, account_key),
    ).fetchall()
    days = set()
    for occurred_at, _event_type in rows:
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
            1 for stamp, event_type in activity_rows
            if _utc_date(stamp) == today and event_type in {"exam_answer", "practice_answer", "flashcard_review"}
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


def get_exam_result(db_path: str, identity: WebIdentity, result_id: int) -> dict | None:
    provider, account_key = _owner(identity)
    with sqlite3.connect(db_path) as conn:
        result = conn.execute(
            "SELECT id, subject, started_at, completed_at, elapsed_seconds, total, answered, correct, "
            "score, max_score, time_expired FROM web_exam_results "
            "WHERE id=? AND provider=? AND account_key=?",
            (int(result_id), provider, account_key),
        ).fetchone()
        if not result:
            return None
        answers = conn.execute(
            "SELECT a.question_id, a.question_order, a.selected_option, a.correct_option, "
            "a.is_correct, a.explanation, q.question, q.option1, q.option2, q.option3, q.option4, q.option5 "
            "FROM web_exam_answers a LEFT JOIN questions q ON q.id=a.question_id "
            "WHERE a.result_id=? ORDER BY a.question_order",
            (int(result_id),),
        ).fetchall()
    summary = _result_dict(result)
    summary.update({
        "result_id": summary["id"],
        "errors": max(0, summary["answered"] - summary["correct"]),
        "percentage": round(summary["score"] * 100 / summary["max_score"], 1) if summary["max_score"] else 0,
        "answers": [{
            "question_id": row[0], "question_order": row[1], "selected_option": row[2],
            "correct_option": row[3], "is_correct": bool(row[4]), "explanation": row[5],
            "question_text": row[6] or "", "options": [option for option in row[7:12] if option],
        } for row in answers],
    })
    return summary


def save_leaderboard_profile(db_path: str, identity: WebIdentity, enabled: bool, display_name: str) -> str:
    provider, account_key = _owner(identity)
    safe_name = "".join(char for char in display_name.strip() if not unicodedata.category(char).startswith("C"))
    safe_name = " ".join(safe_name.split())
    if enabled and (not safe_name or len(safe_name) > 24):
        raise ValueError("Display name must contain 1 to 24 characters")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO web_leaderboard_profiles(provider, account_key, enabled, display_name) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(provider, account_key) DO UPDATE SET "
            "enabled=excluded.enabled, display_name=excluded.display_name",
            (provider, account_key, int(enabled), safe_name),
        )
    return safe_name


def get_leaderboard_data(db_path: str, identity: WebIdentity, limit: int = 10) -> dict:
    provider, account_key = _owner(identity)
    limit = max(1, min(int(limit), 10))
    with sqlite3.connect(db_path) as conn:
        own = conn.execute(
            "SELECT enabled, display_name FROM web_leaderboard_profiles WHERE provider=? AND account_key=?",
            (provider, account_key),
        ).fetchone()
        profiles = conn.execute(
            "SELECT provider, account_key, display_name FROM web_leaderboard_profiles "
            "WHERE enabled=1 AND display_name<>''",
        ).fetchall()
        candidates = []
        for entry_provider, entry_key, display_name in profiles:
            if entry_provider == "telegram":
                points_row = conn.execute(
                    "SELECT points_balance FROM users WHERE user_id=?", (entry_key,)
                ).fetchone()
                points = int(points_row[0] or 0) if points_row else 0
            else:
                points = int(conn.execute(
                    "SELECT COALESCE(SUM(delta),0) FROM web_points_log WHERE provider='google' AND account_key=?",
                    (entry_key,),
                ).fetchone()[0])
            candidates.append({
                "provider": entry_provider, "account_key": entry_key,
                "display_name": display_name, "points": points,
            })
    candidates.sort(key=lambda item: (-item["points"], item["display_name"].casefold()))
    own_enabled = bool(own and own[0])
    own_name = own[1] if own else ""
    rank = next((index + 1 for index, item in enumerate(candidates)
                 if own_enabled and (item["provider"], item["account_key"]) == (provider, account_key)), None)
    entries = [{"rank": index + 1, "display_name": item["display_name"], "points": item["points"]}
               for index, item in enumerate(candidates[:limit])]
    return {"enabled": own_enabled, "display_name": own_name, "rank": rank, "entries": entries}


def get_search_data(db_path: str, identity: WebIdentity, query: str) -> dict:
    normalized = query.strip().casefold()
    if not normalized:
        return {"subjects": [], "questions": []}
    names = _subject_names()
    escaped_query = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    needle = f"%{escaped_query}%"
    with sqlite3.connect(db_path) as conn:
        access = _access_subjects(conn, identity)
        subjects = conn.execute(
            "SELECT LOWER(subject), COUNT(*) FROM questions WHERE COALESCE(subject, '')<>'' "
            "GROUP BY LOWER(subject) ORDER BY LOWER(subject)"
        ).fetchall()
        subject_matches = [{
            "key": key, "name": names.get(key, key.replace("_", " ").title()),
            "question_count": count, "access": key in access,
        } for key, count in subjects if normalized in key.casefold() or normalized in names.get(key, key).casefold()]
        question_matches = conn.execute(
            "SELECT id, LOWER(subject), question FROM questions WHERE LOWER(question) LIKE ? ESCAPE '\\' "
            "ORDER BY id LIMIT 10",
            (needle,),
        ).fetchall()
    questions = [{
        "question_id": question_id, "subject": subject,
        "subject_name": names.get(subject, subject.replace("_", " ").title()),
        "snippet": text[:180],
    } for question_id, subject, text in question_matches if subject in access]
    return {"subjects": subject_matches[:10], "questions": questions[:10]}


def get_flashcards(db_path: str, identity: WebIdentity, subject: str, state: str | None = None) -> list[dict]:
    provider, account_key = _owner(identity)
    if state not in {None, "new", "known", "repeat"}:
        raise ValueError("Unsupported flashcard state")
    sql = (
        "SELECT q.id, LOWER(q.subject), q.question, fs.state FROM questions q "
        "LEFT JOIN web_flashcard_states fs ON fs.question_id=q.id AND fs.provider=? AND fs.account_key=? "
        "WHERE LOWER(q.subject)=?"
    )
    params = [provider, account_key, subject.lower()]
    if state == "new":
        sql += " AND fs.state IS NULL"
    elif state in {"known", "repeat"}:
        sql += " AND fs.state=?"
        params.append(state)
    sql += " ORDER BY q.id LIMIT 500"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"question_id": row[0], "subject": row[1], "question": row[2], "state": row[3] or "new"} for row in rows]


def get_flashcard_subject(db_path: str, question_id: int) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT LOWER(subject) FROM questions WHERE id=?", (int(question_id),)).fetchone()
    return row[0] if row else None


def get_flashcard_reveal(db_path: str, question_id: int) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT correct_option, option1, option2, option3, option4, option5, "
            "COALESCE(explanation, '') FROM questions WHERE id=?",
            (int(question_id),),
        ).fetchone()
    if not row:
        return None
    correct_option = row[0]
    answer = row[correct_option] if isinstance(correct_option, int) and 1 <= correct_option <= 5 else ""
    return {"correct_option": correct_option, "answer": answer or "", "explanation": row[6]}


def save_flashcard_state(
    db_path: str, identity: WebIdentity, question_id: int, state: str, updated_at: str | None = None,
) -> dict:
    provider, account_key = _owner(identity)
    if state not in {"known", "repeat"}:
        raise ValueError("State must be known or repeat")
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO web_flashcard_states(provider, account_key, question_id, state, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(provider, account_key, question_id) DO UPDATE SET "
            "state=excluded.state, updated_at=excluded.updated_at",
            (provider, account_key, int(question_id), state, timestamp),
        )
    return {"state": state, "updated_at": timestamp}
