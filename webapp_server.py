import asyncio
import contextvars
import hmac
import json
import os
import random
import secrets
import sqlite3
import time
from datetime import datetime
from urllib.parse import urlsplit

from aiohttp import BasicAuth, web

from webapp_auth import validate_init_data, validate_telegram_login
from webapp_google_auth import validate_google_id_token
from webapp_sessions import WebIdentity, create_session, resolve_session, revoke_session
import webapp_operations as web_operations
import webapp_learning_data as learning_data

# Lock for pickle file access
pkl_lock = asyncio.Lock()

# Reference to shared state (set in create_app)
SHARED = {}

DB_PATH = "/data/questions.db"
_REQUEST_DB_PATH = contextvars.ContextVar("webapp_db_path", default=DB_PATH)
_REQUEST_WEB_IDENTITY = contextvars.ContextVar("webapp_identity", default=None)
WEB_SETTINGS_KEY = web.AppKey("web_settings", object)


def _legacy_api_token():
    import config
    return config.API_TOKEN


def _run_in_executor(loop, function):
    context = contextvars.copy_context()
    return loop.run_in_executor(None, context.run, function)


def get_user_id(request):
    """Extract and validate Telegram user from initData."""
    identity = _REQUEST_WEB_IDENTITY.get()
    if request.app.get(WEB_SETTINGS_KEY) is not None:
        if not identity:
            return None, None
        if identity.provider == "telegram":
            user_id = int(identity.account_key)
        else:
            user_id = identity.account_key
        return user_id, {"id": user_id, "first_name": identity.display_name}
    init_data = request.headers.get("Authorization", "")
    user = validate_init_data(init_data, _legacy_api_token())
    if not user:
        return None, None
    return user.get("id"), user


def json_response(data, status=200):
    return web.json_response(data, status=status)


def error_response(msg, status=400):
    return web.json_response({"error": msg}, status=status)


# ==================== DB helpers (sync, run in thread) ====================

def db_get_questions(subject, limit=500):
    conn = _db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    questions = cursor.fetchall()
    conn.close()
    if not questions:
        return []
    return random.sample(questions, min(limit, len(questions)))


def db_get_questions_excluding(subject, exclude_ids, limit=1):
    conn = _db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    all_q = cursor.fetchall()
    conn.close()
    if not all_q:
        return []
    filtered = [q for q in all_q if q[0] not in exclude_ids]
    if not filtered:
        filtered = all_q
    return random.sample(filtered, min(limit, len(filtered)))


def db_get_recent_ids(user_id, subject, limit=100):
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        cursor.execute(
            "SELECT question_id FROM web_google_history WHERE google_subject=? AND subject=? "
            "ORDER BY asked_at DESC LIMIT ?",
            (identity.account_key, subject.lower(), limit),
        )
    else:
        cursor.execute(
            "SELECT question_id FROM question_history "
            "WHERE user_id=? AND subject=? ORDER BY asked_at DESC LIMIT ?",
            (user_id, subject.lower(), limit)
        )
    ids = [r[0] for r in cursor.fetchall()]
    conn.close()
    return ids


def db_save_history(user_id, subject, question_id):
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        cursor.execute(
            "INSERT INTO web_google_history (google_subject, subject, question_id) VALUES (?, ?, ?)",
            (identity.account_key, subject.lower(), question_id),
        )
    else:
        cursor.execute(
            "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
            (user_id, subject.lower(), question_id)
        )
    conn.commit()
    conn.close()


def db_save_history_batch(user_id, subject, question_ids):
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        cursor.executemany(
            "INSERT INTO web_google_history (google_subject, subject, question_id) VALUES (?, ?, ?)",
            [(identity.account_key, subject.lower(), qid) for qid in question_ids],
        )
    else:
        cursor.executemany(
            "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
            [(user_id, subject.lower(), qid) for qid in question_ids]
        )
    conn.commit()
    conn.close()


def db_get_correct(question_id):
    conn = _db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT correct_option, COALESCE(explanation, '') FROM questions WHERE id=?",
        (question_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row


# ==================== SQLite helpers ====================

import sqlite3 as _sqlite3
import json as _json

def _db_conn():
    return _sqlite3.connect(_REQUEST_DB_PATH.get())

def _save_session(user_id, session_type, data):
    """Сохраняет сессию в SQLite."""
    conn = _db_conn()
    c = conn.cursor()
    # Конвертируем datetime в строку для JSON
    def serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    serialized = _json.dumps(data, default=serialize)
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        c.execute(
            "INSERT OR REPLACE INTO web_google_learning_sessions "
            "(google_subject, session_type, data, updated_at) VALUES (?, ?, ?, ?)",
            (identity.account_key, session_type, serialized, datetime.now().isoformat()),
        )
    else:
        c.execute(
            "INSERT OR REPLACE INTO sessions (user_id, session_type, data, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, session_type, serialized, datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()

def _load_session(user_id, session_type):
    """Загружает сессию из SQLite. Возвращает dict или None."""
    conn = _db_conn()
    c = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        c.execute(
            "SELECT data FROM web_google_learning_sessions WHERE google_subject=? AND session_type=?",
            (identity.account_key, session_type),
        )
    else:
        c.execute("SELECT data FROM sessions WHERE user_id=? AND session_type=?", (user_id, session_type))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    data = _json.loads(row[0])
    # Восстанавливаем datetime для start_time
    if session_type == 'exam' and 'start_time' in data:
        try:
            data['start_time'] = datetime.fromisoformat(data['start_time'])
        except Exception:
            pass
    return data

def _delete_session(user_id, session_type):
    """Удаляет сессию из SQLite."""
    conn = _db_conn()
    c = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        c.execute(
            "DELETE FROM web_google_learning_sessions WHERE google_subject=? AND session_type=?",
            (identity.account_key, session_type),
        )
    else:
        c.execute("DELETE FROM sessions WHERE user_id=? AND session_type=?", (user_id, session_type))
    conn.commit()
    conn.close()

def _has_access(user_id, subject):
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        cursor.execute(
            "SELECT expires_at FROM web_google_access_grants WHERE google_subject=? AND subject=?",
            (identity.account_key, subject.lower()),
        )
    else:
        cursor.execute(
            "SELECT expires_at FROM purchases WHERE user_id=? AND subject=?",
            (user_id, subject.lower())
        )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return False
    expires_at = row[0]
    if expires_at is None:
        return True
    try:
        from datetime import datetime as _dt
        return _dt.now() <= _dt.fromisoformat(expires_at)
    except Exception:
        return True

def _load_purchases():
    conn = _db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subject, expires_at FROM purchases")
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for uid, subj, exp in rows:
        if uid not in result:
            result[uid] = {}
        result[uid][subj] = None if exp is None else exp
    return result

def _load_trials():
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity and identity.provider == "google":
        cursor.execute(
            "SELECT subject, count FROM web_google_trials WHERE google_subject=?",
            (identity.account_key,),
        )
        rows = [(identity.account_key, subject, count) for subject, count in cursor.fetchall()]
    else:
        cursor.execute("SELECT user_id, subject, count FROM trials")
        rows = cursor.fetchall()
    conn.close()
    result = {}
    for uid, subj, count in rows:
        if uid not in result:
            result[uid] = {}
        result[uid][subj] = count
    return result

def _save_trials(data):
    conn = _db_conn()
    cursor = conn.cursor()
    identity = _REQUEST_WEB_IDENTITY.get()
    for user_id, subjects in data.items():
        for subject, count in subjects.items():
            if identity and identity.provider == "google":
                cursor.execute(
                    "INSERT INTO web_google_trials(google_subject, subject, count) VALUES (?, ?, ?) "
                    "ON CONFLICT(google_subject, subject) DO UPDATE SET count=excluded.count",
                    (identity.account_key, subject.lower(), count),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO trials (user_id, subject, count) VALUES (?, ?, ?)",
                    (user_id, subject.lower(), count)
                )
    conn.commit()
    conn.close()


# ==================== Question serializer ====================

def question_to_dict(q):
    """Convert DB tuple to JSON-friendly dict."""
    options = [o for o in q[3:8] if o and isinstance(o, str)]
    return {
        "id": q[0],
        "subject": q[1],
        "text": q[2],
        "options": options,
        "options_count": len(options),
    }


# ==================== ROUTES ====================

# --- Config / navigation ---
async def handle_config(request):
    user_id, user = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    from main import FACULTIES

    # Build access info
    access_info = {}
    trial_info = {}
    async with pkl_lock:
        purchases = await asyncio.to_thread(_load_purchases)
        trials = await asyncio.to_thread(_load_trials)

    user_purchases = purchases.get(user_id, {})
    user_trials = trials.get(user_id, {})

    # Collect all subject keys
    for fac_data in FACULTIES.values():
        for course_subjects in fac_data["subjects"].values():
            for subj in course_subjects:
                key = subj["key"]
                has = False
                exp = user_purchases.get(key)
                if exp is None and key in user_purchases:
                    has = True
                elif isinstance(exp, datetime) and datetime.now() <= exp:
                    has = True
                access_info[key] = has
                trial_info[key] = user_trials.get(key, 0)

    # Serialize FACULTIES
    fac_serializable = {}
    for fk, fv in FACULTIES.items():
        subj_ser = {}
        for course_num, subj_list in fv["subjects"].items():
            subj_ser[str(course_num)] = subj_list
        fac_serializable[fk] = {
            "name": fv["name"],
            "courses": fv["courses"],
            "subjects": subj_ser,
        }

    return json_response({
        "faculties": fac_serializable,
        "access": access_info,
        "trials": trial_info,
        "user": {"id": user_id, "first_name": user.get("first_name", "")},
    })


async def handle_access(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)
    subject = request.query.get("subject", "")
    if not subject:
        return error_response("subject required")

    async with pkl_lock:
        has = await asyncio.to_thread(_has_access, user_id, subject)
        trials = await asyncio.to_thread(_load_trials)

    used = trials.get(user_id, {}).get(subject, 0)
    return json_response({
        "has_access": has,
        "trial_used": used,
        "trial_remaining": max(0, 5 - used),
    })


# --- Exam ---
async def handle_exam_start(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    data = await request.json()
    subject = data.get("subject", "")

    async with pkl_lock:
        if not await asyncio.to_thread(_has_access, user_id, subject):
            return error_response("No access", 403)

    questions = await asyncio.to_thread(db_get_questions, subject, 50)
    if not questions:
        return error_response("No questions in database")

    # Deduplicate and shuffle to guarantee no repeats within one exam session
    seen = set()
    unique = []
    for q in questions:
        if q[0] not in seen:
            seen.add(q[0])
            unique.append(q)
    questions = unique
    random.shuffle(questions)

    await asyncio.to_thread(db_save_history_batch, user_id, subject, [q[0] for q in questions])

    session_data = {
        "subject": subject,
        "questions": [list(q) for q in questions],
        "current": 0,
        "score": 0,
        "active": True,
        "start_time": datetime.now(),
        "answers": [],
        "answers_by_index": {},
        "exam_session_key": secrets.token_urlsafe(20),
    }
    await asyncio.to_thread(_save_session, user_id, 'exam', session_data)
    await asyncio.to_thread(_delete_session, user_id, 'exam_finished')

    return json_response({
        "total_questions": len(questions),
        "duration_minutes": 75,
    })


async def handle_exam_question(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session or not session["active"]:
        return error_response("No active exam")

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    remaining = max(0, 75 * 60 - int(elapsed))

    if remaining <= 0:
        return json_response({"expired": True, "time_remaining": 0})

    idx = session["current"]
    if idx >= len(session["questions"]):
        return json_response({"finished": True, "time_remaining": remaining})

    q = session["questions"][idx]
    return json_response({
        "question": question_to_dict(q),
        "question_number": idx + 1,
        "total": len(session["questions"]),
        "index": idx,
        "selected_option": session.get("answers_by_index", {}).get(str(idx), {}).get("selected"),
        "time_remaining": remaining,
    })


async def handle_exam_navigate(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)
    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session or not session.get("active"):
        return error_response("No active exam", 404)
    try:
        index = int((await request.json()).get("index"))
    except (TypeError, ValueError):
        return error_response("index must be an integer")
    if index < 0 or index >= len(session["questions"]):
        return error_response("Question index out of range", 422)
    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    remaining = max(0, 75 * 60 - int(elapsed))
    if remaining <= 0:
        return json_response({"expired": True, "time_remaining": 0})
    session["current"] = index
    await asyncio.to_thread(_save_session, user_id, 'exam', session)
    return json_response({
        "question": question_to_dict(session["questions"][index]),
        "index": index,
        "total": len(session["questions"]),
        "selected_option": session.get("answers_by_index", {}).get(str(index), {}).get("selected"),
        "time_remaining": remaining,
    })


async def handle_exam_answer(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session or not session["active"]:
        return error_response("No active exam")

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    remaining = max(0, 75 * 60 - int(elapsed))
    if remaining <= 0:
        return json_response({"expired": True, "time_remaining": 0})

    data = await request.json()
    selected = data.get("selected")
    if not isinstance(selected, int) or isinstance(selected, bool) or selected < 1 or selected > 5:
        return error_response("selected required")

    try:
        idx = int(data.get("index", session["current"]))
    except (TypeError, ValueError):
        return error_response("index must be an integer")
    answers_by_index = session.setdefault("answers_by_index", {})
    previous = answers_by_index.get(str(idx))
    if previous and idx != session["current"]:
        return json_response({"duplicate": True, "selected_option": previous["selected"]})
    if idx != session["current"]:
        return error_response("Stale question", 409)
    if idx >= len(session["questions"]):
        return error_response("Exam already finished")

    current_q = session["questions"][idx]
    if selected > sum(1 for option in current_q[3:8] if option):
        return error_response("selected option does not exist", 422)
    row = await asyncio.to_thread(db_get_correct, current_q[0])

    correct_option = 0
    explanation = ""
    is_correct = False
    if row:
        correct_option = row[0]
        explanation = row[1]
        if selected == correct_option:
            is_correct = True

    answer = {
        "question": current_q,
        "selected": selected,
        "correct": correct_option,
        "is_correct": is_correct,
        "explanation": explanation,
    }
    answers_by_index[str(idx)] = answer
    session["answers"] = [answers_by_index[str(i)] for i in sorted(map(int, answers_by_index))]
    session["score"] = sum(2 for answer in answers_by_index.values() if answer["is_correct"])
    session["current"] = idx + 1
    identity = _REQUEST_WEB_IDENTITY.get()
    await asyncio.to_thread(
        learning_data.record_activity_event, _REQUEST_DB_PATH.get(), identity,
        session["subject"], "exam_answer", f"{session['exam_session_key']}:{idx}",
    )

    has_next = session["current"] < len(session["questions"])
    await asyncio.to_thread(_save_session, user_id, 'exam', session)

    return json_response({
        "has_next": has_next,
        "index": idx,
        "selected_option": selected,
        "time_remaining": remaining,
    })


async def handle_exam_finish(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session or not session.get("active"):
        finished = await asyncio.to_thread(_load_session, user_id, 'exam_finished')
        if finished:
            return json_response(finished["result"])
        return error_response("No exam session", 404)

    answers_by_index = session.get("answers_by_index", {})
    answers = session.get("answers", [])
    score = sum(2 for answer in answers_by_index.values() if answer["is_correct"])
    total = len(session["questions"])
    answered = len(answers_by_index)
    correct_count = sum(1 for a in answers_by_index.values() if a["is_correct"])
    errors_count = max(0, answered - correct_count)

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    time_expired = elapsed >= 75 * 60
    completed_at = datetime.now().astimezone().isoformat()
    started_at = session["start_time"].astimezone().isoformat()
    identity = _REQUEST_WEB_IDENTITY.get()
    exam_summary = {
        "exam_session_key": session["exam_session_key"], "subject": session["subject"],
        "started_at": started_at, "completed_at": completed_at,
        "elapsed_seconds": int(elapsed), "total": total, "answered": answered,
        "correct": correct_count, "score": score, "max_score": total * 2,
        "time_expired": time_expired,
    }
    answer_rows = [{
        "question_id": answer["question"][0], "question_order": index,
        "selected_option": answer["selected"], "correct_option": answer["correct"],
        "is_correct": answer["is_correct"], "explanation": answer.get("explanation", ""),
    } for index, answer in sorted(((int(i), answer) for i, answer in answers_by_index.items()))]
    result_id = await asyncio.to_thread(
        learning_data.save_exam_result, _REQUEST_DB_PATH.get(), identity, exam_summary, answer_rows,
    )
    await asyncio.to_thread(
        learning_data.record_activity_event, _REQUEST_DB_PATH.get(), identity,
        session["subject"], "exam_completed", f"{session['exam_session_key']}:completed",
    )

    # Save for review
    if answers:
        review_data = {
            "subject": session["subject"],
            "answers": answers,
            "current": 0,
        }
        await asyncio.to_thread(_save_session, user_id, 'review', review_data)

    result = {
        "result_id": result_id, "subject": session["subject"], "score": score,
        "max_score": total * 2, "answered": answered, "total": total,
        "correct": correct_count, "errors": errors_count,
        "percentage": round(score / (total * 2) * 100, 1) if total > 0 else 0,
        "elapsed_seconds": int(elapsed), "time_expired": time_expired,
    }
    await asyncio.to_thread(_save_session, user_id, 'exam_finished', {"result": result})
    await asyncio.to_thread(_delete_session, user_id, 'exam')

    return json_response(result)


async def handle_exam_result(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)
    try:
        result_id = int(request.match_info["result_id"])
    except (TypeError, ValueError):
        return error_response("Invalid result id", 404)
    identity = _REQUEST_WEB_IDENTITY.get()
    result = await asyncio.to_thread(
        learning_data.get_exam_result, _REQUEST_DB_PATH.get(), identity, result_id,
    )
    if not result:
        return error_response("Result not found", 404)
    return json_response(result)


async def handle_exam_status(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session or not session["active"]:
        return json_response({"active": False})

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    remaining = max(0, 75 * 60 - int(elapsed))

    return json_response({
        "active": True,
        "time_remaining": remaining,
        "current": session["current"],
        "total": len(session["questions"]),
    })


# --- Test ---
async def handle_test_start(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    data = await request.json()
    subject = data.get("subject", "")

    async with pkl_lock:
        has = await asyncio.to_thread(_has_access, user_id, subject)
        trials = await asyncio.to_thread(_load_trials)

    used = trials.get(user_id, {}).get(subject, 0)
    if not has and used >= 5:
        return error_response("Trial limit reached", 403)

    recent = await asyncio.to_thread(db_get_recent_ids, user_id, subject, 100)
    questions = await asyncio.to_thread(db_get_questions_excluding, subject, set(recent), 1)
    if not questions:
        return error_response("No questions available")

    q = questions[0]
    await asyncio.to_thread(db_save_history, user_id, subject, q[0])

    await asyncio.to_thread(_save_session, user_id, 'test', {
        "subject": subject, "question": list(q), "active": True,
        "attempt_key": secrets.token_urlsafe(16), "answered": False,
    })

    return json_response({
        "question": question_to_dict(q),
        "trial_used": used,
        "trial_remaining": max(0, 5 - used) if not has else -1,
        "has_access": has,
    })


async def handle_test_answer(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'test')
    if not session or not session["active"]:
        return error_response("No active test")

    if session.get("answered"):
        return json_response({**session["answer_result"], "duplicate": True})

    subject = session["subject"]
    data = await request.json()
    selected = data.get("selected")
    if request.app.get(WEB_SETTINGS_KEY):
        question_id = session["question"][0]
    else:
        question_id = data.get("question_id")

    row = await asyncio.to_thread(db_get_correct, question_id)
    if not row:
        return error_response("Question not found")

    correct_option = row[0]
    explanation = row[1]
    is_correct = selected == correct_option

    # Update trial counter
    async with pkl_lock:
        has = await asyncio.to_thread(_has_access, user_id, subject)
        if not has:
            trials = await asyncio.to_thread(_load_trials)
            if user_id not in trials:
                trials[user_id] = {}
            if subject not in trials[user_id]:
                trials[user_id][subject] = 0
            trials[user_id][subject] += 1
            await asyncio.to_thread(_save_trials, trials)
            used = trials[user_id][subject]
            trial_remaining = max(0, 5 - used)
            trial_limit_reached = used >= 5
        else:
            used = 0
            trial_remaining = -1
            trial_limit_reached = False

    answer_result = {
        "is_correct": is_correct,
        "correct_option": correct_option,
        "explanation": explanation,
        "trial_remaining": trial_remaining,
        "trial_limit_reached": trial_limit_reached,
        "has_access": has,
    }
    session["answered"] = True
    session["answer_result"] = answer_result
    await asyncio.to_thread(_save_session, user_id, 'test', session)
    await asyncio.to_thread(
        learning_data.record_activity_event, _REQUEST_DB_PATH.get(), _REQUEST_WEB_IDENTITY.get(),
        subject, "practice_answer", session["attempt_key"],
    )
    return json_response(answer_result)


async def handle_test_next(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'test')
    if not session or not session["active"]:
        return error_response("No active test")

    subject = session["subject"]

    async with pkl_lock:
        has = await asyncio.to_thread(_has_access, user_id, subject)
        trials = await asyncio.to_thread(_load_trials)

    used = trials.get(user_id, {}).get(subject, 0)
    if not has and used >= 5:
        return json_response({"trial_limit_reached": True, "trial_remaining": 0})

    recent = await asyncio.to_thread(db_get_recent_ids, user_id, subject, 100)
    questions = await asyncio.to_thread(db_get_questions_excluding, subject, set(recent), 1)
    if not questions:
        return error_response("No more questions")

    q = questions[0]
    await asyncio.to_thread(db_save_history, user_id, subject, q[0])
    session["question"] = list(q)
    session["attempt_key"] = secrets.token_urlsafe(16)
    session["answered"] = False
    session.pop("answer_result", None)
    await asyncio.to_thread(_save_session, user_id, 'test', session)

    return json_response({
        "question": question_to_dict(q),
        "trial_remaining": max(0, 5 - used) if not has else -1,
        "has_access": has,
    })


# --- Review ---
async def handle_review(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'review')
    if not session or not session["answers"]:
        return error_response("No review data", 404)

    answers_out = []
    for a in session["answers"]:
        q = a["question"]
        options = [o for o in q[3:8] if o and isinstance(o, str)]
        answers_out.append({
            "question_text": q[2],
            "options": options,
            "selected": a["selected"],
            "correct": a["correct"],
            "is_correct": a["is_correct"],
            "explanation": a.get("explanation", ""),
        })

    return json_response({
        "subject": session["subject"],
        "answers": answers_out,
        "total": len(answers_out),
    })


# --- Purchase ---
async def handle_purchase_select(request):
    user_id, user = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    data = await request.json()
    subject = data.get("subject", "")
    period = data.get("period", "")

    prices = {"forever": "300с"}
    if period not in prices:
        return error_response("Invalid period")

    bot = SHARED["bot"]
    coder_chat_id = 1427715527
    first_name = user.get("first_name", "")
    username = user.get("username", "")
    sender = f"@{username}" if username else first_name

    from aiogram.types import InlineKeyboardMarkup as _IKM, InlineKeyboardButton as _IKB
    _admin_ids = {1427715527, 1347147831, 905937261}
    _subj_name = subject.capitalize()
    _grant_markup = _IKM(inline_keyboard=[
        [_IKB(text="✅ Выдать доступ", callback_data=f"admin_grant_{user_id}_{subject}")]
    ])
    for _admin_id in _admin_ids:
        try:
            await bot.send_message(
                _admin_id,
                f"📲 *Запрос на покупку* \\(Mini App\\)\n\n"
                f"👤 {sender} \\(id: `{user_id}`\\)\n"
                f"📚 Предмет: *{_subj_name}*\n"
                f"💰 Период: *{period}* \\({prices[period]}\\)",
                parse_mode="MarkdownV2",
                reply_markup=_grant_markup,
            )
        except Exception:
            pass

    # Отправляем QR из файла через функцию из main
    qr_url = ""
    try:
        from main import send_qr_photo
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"qr_paid_{subject}_{period}")],
            ]
        )
        msg = await send_qr_photo(
            chat_id=user_id,
            caption=(
                f"💳 *Покупка доступа к {subject.capitalize()}*\n\n"
                f"Стоимость доступа:\n"
                f"• {prices[period]}\n\n"
                f"Пожалуйста, оплатите по QR-коду и отправьте квитанцию в этот чат.\n\n"
                f"Обязательно нажмите кнопку «Я оплатил» после отправки чека!\n"
                f"В случае возникновения проблем с оплатой, вы можете обратиться к @Ameba\\_admin"
            ),
            reply_markup=markup
        )
        # Попробуем получить URL для показа в Mini App
        if msg and msg.photo:
            try:
                file = await bot.get_file(msg.photo[-1].file_id)
                qr_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
            except Exception:
                pass
    except Exception as e:
        print(f"Error sending QR to user: {e}")

    return json_response({"success": True, "price": prices[period], "period": period, "qr_url": qr_url})


# --- Support ---
async def handle_support_send(request):
    user_id, user = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    data = await request.json()
    message = data.get("message", "").strip()
    if not message:
        return error_response("Empty message")

    bot = SHARED["bot"]
    coder_chat_id = 1427715527
    username = user.get("username", "")
    sender = f"@{username}" if username else user.get("first_name", "")

    _admin_ids = {1427715527, 1347147831, 905937261}
    for _admin_id in _admin_ids:
        try:
            await bot.send_message(
                _admin_id,
                f"🆘 Сообщение поддержки (Mini App)\n👤 {sender} (id:{user_id}):\n\n{message}",
            )
        except Exception:
            pass

    return json_response({"success": True})


# ==================== ADMIN API ====================

ADMIN_IDS = {1427715527, 905937261, 8113642902, 771714551, 1347147831, 751240103, 1238729309, 6586083917, 921010964, 1333298810, 942664226, 1239722079}

def _is_admin(request):
    if request.app.get(WEB_SETTINGS_KEY) is not None:
        identity = _REQUEST_WEB_IDENTITY.get()
        return bool(identity and identity.provider == "telegram" and identity.is_admin)
    auth = request.headers.get("Authorization", "")
    # Accept session token (password login)
    if auth == ADMIN_SESSION_TOKEN:
        return True
    # Accept Telegram initData
    user = validate_init_data(auth, _legacy_api_token())
    if user and user.get("id") in ADMIN_IDS:
        return True
    return False


def require_admin(request):
    if request.app.get(WEB_SETTINGS_KEY) is not None:
        identity = _REQUEST_WEB_IDENTITY.get()
        return bool(identity and identity.provider == "telegram" and identity.is_admin)
    return _is_admin(request)


async def handle_web_admin_check(request):
    identity = _REQUEST_WEB_IDENTITY.get()
    return json_response({"is_admin": bool(identity and identity.provider == "telegram" and identity.is_admin)})


def _web_identity_or_unauthorized():
    return _REQUEST_WEB_IDENTITY.get()


async def handle_web_support_send(request):
    _require_same_origin(request)
    identity = _web_identity_or_unauthorized()
    if not identity:
        return error_response("Unauthorized", 401)
    try:
        data = await request.json()
        ticket_id = web_operations.create_support_ticket(
            _REQUEST_DB_PATH.get(), identity.provider, identity.account_key, data.get("message", "")
        )
    except (ValueError, TypeError) as exc:
        return error_response(str(exc))
    return json_response({"success": True, "ticket_id": ticket_id})


async def handle_web_support_list(request):
    identity = _web_identity_or_unauthorized()
    if not identity:
        return error_response("Unauthorized", 401)
    tickets = web_operations.list_support_tickets(
        _REQUEST_DB_PATH.get(), identity.provider, identity.account_key
    )
    return json_response({"tickets": tickets})


async def handle_web_admin_support(request):
    if not require_admin(request):
        return error_response("Forbidden", 403)
    return json_response({"tickets": web_operations.list_support_tickets(_REQUEST_DB_PATH.get())})


async def handle_web_admin_support_reply(request):
    _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    identity = _REQUEST_WEB_IDENTITY.get()
    try:
        ticket_id = int(request.match_info["id"])
        data = await request.json()
        saved = web_operations.add_support_reply(
            _REQUEST_DB_PATH.get(), ticket_id, identity.provider, identity.account_key,
            data.get("message", ""),
        )
    except (ValueError, TypeError) as exc:
        return error_response(str(exc))
    if not saved:
        return error_response("Ticket not found", 404)
    return json_response({"success": True})


async def handle_web_announcements(request):
    return json_response({"announcements": web_operations.list_announcements(_REQUEST_DB_PATH.get())})


async def handle_web_promo(request):
    return json_response({"text": web_operations.get_promo(_REQUEST_DB_PATH.get())})


async def handle_web_admin_announcement(request):
    _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    try:
        data = await request.json()
        item_id = web_operations.publish_announcement(
            _REQUEST_DB_PATH.get(), data.get("title", ""), data.get("body", "")
        )
    except (ValueError, TypeError) as exc:
        return error_response(str(exc))
    return json_response({"success": True, "id": item_id})


async def handle_web_admin_promo(request):
    _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    data = await request.json()
    web_operations.set_promo(_REQUEST_DB_PATH.get(), data.get("text", ""))
    return json_response({"success": True})


async def handle_web_referral(request):
    identity = _web_identity_or_unauthorized()
    if not identity:
        return error_response("Unauthorized", 401)
    from referral_domain import LEVELS, get_or_create_referral_code, referral_level

    db_path = _REQUEST_DB_PATH.get()
    code = get_or_create_referral_code(db_path, identity.provider, identity.account_key)
    with sqlite3.connect(db_path) as conn:
        if identity.provider == "telegram":
            row = conn.execute(
                "SELECT points_balance, referral_count FROM users WHERE user_id=?",
                (int(identity.account_key),),
            ).fetchone()
            balance, purchase_count = row or (0, 0)
            invited = conn.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (int(identity.account_key),)
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT delta, reason, subject, created_at FROM points_log WHERE user_id=? "
                "ORDER BY id DESC LIMIT 10", (int(identity.account_key),)
            ).fetchall()
            ref_link = f"{request.app[WEB_SETTINGS_KEY].base_url}/?ref={code}"
        else:
            balance = conn.execute(
                "SELECT COALESCE(SUM(delta),0) FROM web_points_log WHERE provider='google' AND account_key=?",
                (identity.account_key,),
            ).fetchone()[0]
            purchase_count = conn.execute(
                "SELECT COUNT(*) FROM web_referrals WHERE referrer_provider='google' AND referrer_key=?",
                (identity.account_key,),
            ).fetchone()[0]
            invited = purchase_count
            rows = conn.execute(
                "SELECT delta, reason, '', created_at FROM web_points_log WHERE provider='google' AND account_key=? "
                "ORDER BY id DESC LIMIT 10", (identity.account_key,),
            ).fetchall()
            ref_link = f"{request.app[WEB_SETTINGS_KEY].base_url}/?ref={code}"
    level_name, bonus, spend_limit = referral_level(purchase_count)
    upcoming = next((level for level in LEVELS if purchase_count < level[0]), None)
    next_level = None if upcoming is None else {
        "left": upcoming[0] - purchase_count, "name": upcoming[1],
        "bonus": upcoming[2], "limit": upcoming[3],
    }
    return json_response({
        "balance": balance, "reserved": 0, "available": balance, "spend_limit": spend_limit,
        "level_name": level_name, "bonus_per_purchase": bonus, "referral_count": purchase_count,
        "total_invited": invited, "next_level": next_level,
        "history": [{"delta": row[0], "reason": row[1], "subject": row[2] or "", "date": (row[3] or "")[:10]}
                    for row in rows],
        "ref_link": ref_link,
    })


async def handle_web_referral_claim(request):
    _require_same_origin(request)
    identity = _web_identity_or_unauthorized()
    if not identity:
        return error_response("Unauthorized", 401)
    try:
        data = await request.json()
    except (ValueError, json.JSONDecodeError):
        return error_response("Invalid request")
    from referral_domain import claim_referral

    claimed = claim_referral(
        _REQUEST_DB_PATH.get(), identity.provider, identity.account_key, data.get("code", "")
    )
    return json_response({"success": claimed, "claimed": claimed})


async def handle_web_admin_accounts(request):
    if not require_admin(request):
        return error_response("Forbidden", 403)
    query = request.query.get("q", "").strip()
    if not query:
        return json_response({"accounts": []})
    db_path = _REQUEST_DB_PATH.get()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        telegram_rows = conn.execute(
            "SELECT user_id, username, full_name FROM users WHERE CAST(user_id AS TEXT)=? "
            "OR username LIKE ? OR full_name LIKE ? LIMIT 50",
            (query.lstrip("@"), f"%{query.lstrip('@')}%", f"%{query}%"),
        ).fetchall()
        google_rows = conn.execute(
            "SELECT subject, email, display_name FROM web_google_accounts WHERE subject=? OR email LIKE ? "
            "OR display_name LIKE ? LIMIT 50", (query, f"%{query}%", f"%{query}%"),
        ).fetchall()
    accounts = [
        {"provider": "telegram", "account_key": str(row["user_id"]), "label": row["full_name"] or "",
         "username": row["username"] or ""} for row in telegram_rows
    ] + [
        {"provider": "google", "account_key": row["subject"], "label": row["display_name"] or "",
         "username": row["email"] or ""} for row in google_rows
    ]
    return json_response({"accounts": accounts})


async def handle_web_admin_access(request):
    _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    try:
        data = await request.json()
        provider, account_key = data.get("provider"), str(data.get("account_key", "")).strip()
        subject, action = str(data.get("subject", "")).strip().lower(), data.get("action")
        if provider not in {"telegram", "google"} or not account_key or not subject:
            raise ValueError("Provider, account and subject are required")
        if action not in {"grant", "revoke"}:
            raise ValueError("Action must be grant or revoke")
        from webapp_catalog import FACULTIES
        allowed_subjects = {
            item["key"] for faculty in FACULTIES.values()
            for subjects in faculty["subjects"].values() for item in subjects
        }
        if subject not in allowed_subjects:
            raise ValueError("Unknown subject")
        expires_at = data.get("expires_at")
        if expires_at:
            expires_at = datetime.fromisoformat(str(expires_at)).isoformat(sep=" ")
        db_path = _REQUEST_DB_PATH.get()
        with sqlite3.connect(db_path) as conn:
            if provider == "telegram":
                user_id = int(account_key)
                exists = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
                if not exists:
                    return error_response("Telegram account not found", 404)
                if action == "grant":
                    conn.execute("INSERT OR REPLACE INTO purchases(user_id, subject, expires_at) VALUES (?, ?, ?)",
                                 (user_id, subject, expires_at))
                else:
                    conn.execute("DELETE FROM purchases WHERE user_id=? AND subject=?", (user_id, subject))
            else:
                exists = conn.execute("SELECT 1 FROM web_google_accounts WHERE subject=?", (account_key,)).fetchone()
                if not exists:
                    return error_response("Google account not found", 404)
                if action == "grant":
                    admin = _REQUEST_WEB_IDENTITY.get()
                    conn.execute(
                        "INSERT OR REPLACE INTO web_google_access_grants(google_subject, subject, expires_at, granted_by) "
                        "VALUES (?, ?, ?, ?)", (account_key, subject, expires_at, int(admin.account_key)),
                    )
                else:
                    conn.execute("DELETE FROM web_google_access_grants WHERE google_subject=? AND subject=?",
                                 (account_key, subject))
    except (ValueError, TypeError) as exc:
        return error_response(str(exc))
    return json_response({"success": True})

async def handle_admin_check(request):
    """Returns whether current user is admin — used by frontend to show/hide panel."""
    from urllib.parse import parse_qs, unquote
    import json as _json

    init_data = request.headers.get("Authorization", "")
    print(f"[ADMIN_CHECK] init_data len={len(init_data)}, preview={init_data[:80]!r}")

    user = None

    # Try strict validation first
    user = validate_init_data(init_data, _legacy_api_token())
    print(f"[ADMIN_CHECK] strict_validate={user}")

    if not user:
        # Fallback: parse user from initData without signature/time check
        try:
            parsed = parse_qs(init_data, keep_blank_values=True)
            user_str = parsed.get("user", [None])[0]
            if user_str:
                user = _json.loads(unquote(user_str))
                print(f"[ADMIN_CHECK] fallback_user={user}")
        except Exception as e:
            print(f"[ADMIN_CHECK] fallback error: {e}")

    if not user:
        return json_response({"is_admin": False, "debug": "no_user"})

    uid = user.get("id")
    is_adm = uid in ADMIN_IDS
    print(f"[ADMIN_CHECK] uid={uid}, is_admin={is_adm}, ADMIN_IDS={ADMIN_IDS}")
    return json_response({"is_admin": is_adm, "user_id": uid})

ADMIN_PASSWORD = "ameba2024admin"
ADMIN_SESSION_TOKEN = "ameba_admin_session_9x7k2"  # static secret token

async def handle_admin_login(request):
    try:
        data = await request.json()
        pwd = data.get("password", "")
    except Exception:
        return error_response("bad request")
    if pwd == ADMIN_PASSWORD:
        return json_response({"success": True, "token": ADMIN_SESSION_TOKEN})
    return json_response({"success": False})

async def handle_admin_questions(request):
    if not require_admin(request):
        return error_response("Forbidden", 403)
    search = request.query.get("q", "").strip()
    subject = request.query.get("subject", "").strip()
    def _fetch():
        conn = _db_conn()
        clauses = []
        params = []
        if search:
            clauses.append("(question LIKE ? OR explanation LIKE ?)")
            params.extend((f"%{search}%", f"%{search}%"))
        if subject:
            clauses.append("subject=?")
            params.append(subject)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        c = conn.cursor()
        c.execute(f"""
            SELECT id, subject, question, option1, option2, option3, option4, option5,
                   correct_option, COALESCE(explanation, '')
            FROM questions {where} ORDER BY subject, id LIMIT 1000
        """, params)
        rows = c.fetchall()
        conn.close()
        return rows
    rows = await _run_in_executor(asyncio.get_event_loop(), _fetch)
    questions = [
        {
            "id": r[0], "subject": r[1], "question": r[2],
            "option1": r[3], "option2": r[4], "option3": r[5],
            "option4": r[6], "option5": r[7],
            "correct_option": r[8], "explanation": r[9]
        }
        for r in rows
    ]
    return json_response({"questions": questions})

async def handle_admin_question_edit(request):
    if request.app.get(WEB_SETTINGS_KEY) is not None:
        _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    q_id = request.match_info.get("id")
    try:
        q_id = int(q_id)
    except (ValueError, TypeError):
        return error_response("Invalid id")
    data = await request.json()
    question    = (data.get("question") or "").strip()
    option1     = (data.get("option1") or "").strip() or None
    option2     = (data.get("option2") or "").strip() or None
    option3     = (data.get("option3") or "").strip() or None
    option4     = (data.get("option4") or "").strip() or None
    option5     = (data.get("option5") or "").strip() or None
    correct     = data.get("correct_option")
    explanation = (data.get("explanation") or "").strip() or None
    if not question or not correct:
        return error_response("Missing fields")
    try:
        correct = int(correct)
    except (ValueError, TypeError):
        return error_response("Invalid correct_option")
    def _update():
        conn = _db_conn()
        c = conn.cursor()
        c.execute("""
            UPDATE questions SET question=?, option1=?, option2=?, option3=?, option4=?, option5=?,
            correct_option=?, explanation=? WHERE id=?
        """, (question, option1, option2, option3, option4, option5, correct, explanation, q_id))
        conn.commit()
        conn.close()
    await _run_in_executor(asyncio.get_event_loop(), _update)
    return json_response({"success": True})

async def handle_admin_question_delete(request):
    if request.app.get(WEB_SETTINGS_KEY) is not None:
        _require_same_origin(request)
    if not require_admin(request):
        return error_response("Forbidden", 403)
    q_id = request.match_info.get("id")
    try:
        q_id = int(q_id)
    except (ValueError, TypeError):
        return error_response("Invalid id")
    def _delete():
        conn = _db_conn()
        c = conn.cursor()
        c.execute("DELETE FROM questions WHERE id=?", (q_id,))
        conn.commit()
        conn.close()
    await _run_in_executor(asyncio.get_event_loop(), _delete)
    return json_response({"success": True})


# --- Stats ---
async def handle_admin_stats(request):
    if not require_admin(request):
        return error_response("Forbidden", 403)

    def _get_stats():
        conn = _db_conn()
        c = conn.cursor()

        # Всего пользователей
        try:
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users")
            total_users = c.fetchone()[0]
        except Exception:
            total_users = 0
        if not total_users:
            c.execute("SELECT COUNT(DISTINCT user_id) FROM question_history")
            total_users = c.fetchone()[0]

        # Всего ответов
        c.execute("SELECT COUNT(*) FROM question_history")
        total_answers = c.fetchone()[0]

        # Топ-5 предметов
        c.execute("""
            SELECT subject, COUNT(*) as cnt
            FROM question_history
            GROUP BY subject
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_subjects = [{"subject": r[0], "count": r[1]} for r in c.fetchall()]

        # Покупок
        c.execute("SELECT COUNT(*) FROM purchases")
        total_purchases = c.fetchone()[0]

        # Вопросов в базе
        c.execute("SELECT COUNT(*) FROM questions")
        total_questions = c.fetchone()[0]

        # Вопросов по предметам
        c.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject ORDER BY subject")
        questions_by_subject = [{"subject": r[0], "count": r[1]} for r in c.fetchall()]

        # Всего запусков экзамена
        try:
            c.execute("SELECT COUNT(*) FROM exam_log")
            total_exams = c.fetchone()[0]
        except Exception:
            total_exams = 0

        # Реферальная статистика
        c.execute("SELECT COUNT(*) FROM referrals")
        total_referrals = c.fetchone()[0]

        c.execute("SELECT COUNT(DISTINCT referrer_id) FROM referrals")
        total_referrers = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM referrals WHERE purchase_bonus_paid=1")
        referral_purchases = c.fetchone()[0]

        c.execute("""
            SELECT r.referrer_id, u.username, u.full_name, COUNT(*) as cnt,
                   SUM(r.purchase_bonus_paid) as purchases
            FROM referrals r
            LEFT JOIN users u ON u.user_id = r.referrer_id
            GROUP BY r.referrer_id
            ORDER BY cnt DESC
            LIMIT 10
        """)
        top_referrers = [
            {
                "label": f"@{r[1]}" if r[1] else (r[2] or str(r[0])),
                "invited": r[3],
                "purchases": r[4] or 0
            }
            for r in c.fetchall()
        ]

        conn.close()
        return {
            "total_users": total_users,
            "total_answers": total_answers,
            "total_purchases": total_purchases,
            "total_questions": total_questions,
            "total_exams": total_exams,
            "top_subjects": top_subjects,
            "questions_by_subject": questions_by_subject,
            "total_referrals": total_referrals,
            "total_referrers": total_referrers,
            "referral_purchases": referral_purchases,
            "top_referrers": top_referrers,
        }

    stats = await _run_in_executor(asyncio.get_event_loop(), _get_stats)
    return json_response(stats)


# --- Referral & Balance ---
async def handle_referral(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    def _get_data():
        conn = _db_conn()
        c = conn.cursor()

        # Баланс и инфо о пользователе
        c.execute("SELECT points_balance, referral_count FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        balance = row[0] if row else 0
        referral_count = row[1] if row else 0

        # Зарезервированные баллы
        c.execute(
            "SELECT COALESCE(SUM(points),0) FROM points_reserved WHERE user_id=? AND status='pending'",
            (user_id,)
        )
        reserved = c.fetchone()[0]

        # Всего приглашённых
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        total_invited = c.fetchone()[0]

        # Последние 10 операций
        c.execute(
            "SELECT delta, reason, subject, created_at FROM points_log "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        history_rows = c.fetchall()
        conn.close()
        return balance, reserved, referral_count, total_invited, history_rows

    balance, reserved, referral_count, total_invited, history_rows = await asyncio.to_thread(_get_data)
    available = balance - reserved

    # Уровень по referral_count
    level_name, bonus, spend_limit = "🟢 Новичок", 30, 100
    thresholds = [(0, "🟢 Новичок", 30, 100), (10, "🔵 Продвинутый", 40, 200), (20, "🟣 Мессия", 50, 300)]
    for thr, name, b, lim in thresholds:
        if referral_count >= thr:
            level_name, bonus, spend_limit = name, b, lim

    # До следующего уровня
    next_level = None
    for thr, name, b, lim in thresholds:
        if referral_count < thr:
            next_level = {"left": thr - referral_count, "name": name, "bonus": b, "limit": lim}
            break

    reason_names = {
        "registration":      "Регистрация",
        "referral_join":     "Переход по вашей ссылке",
        "own_trial":         "Прорешал бесплатные вопросы",
        "referral_purchase": "Реферал купил предмет",
        "own_purchase":      "Покупка предмета",
        "spend":             "Оплата баллами",
    }
    history = []
    for delta, reason, subject, created_at in history_rows:
        history.append({
            "delta": delta,
            "reason": reason_names.get(reason, reason),
            "subject": subject or "",
            "date": (created_at or "")[:10],
        })

    # Реферальная ссылка — берём username бота из SHARED
    bot = SHARED.get("bot")
    bot_username = ""
    try:
        info = await bot.get_me()
        bot_username = info.username
    except Exception:
        pass

    return json_response({
        "balance": balance,
        "reserved": reserved,
        "available": available,
        "spend_limit": spend_limit,
        "level_name": level_name,
        "bonus_per_purchase": bonus,
        "referral_count": referral_count,
        "total_invited": total_invited,
        "next_level": next_level,
        "history": history,
        "ref_link": f"https://t.me/{bot_username}?start=ref_{user_id}" if bot_username else "",
    })


# --- Static files ---
async def handle_index(request):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return web.FileResponse(os.path.join(static_dir, "index.html"), headers={"ngrok-skip-browser-warning": "1"})

async def handle_admin_page(request):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return web.FileResponse(os.path.join(static_dir, "admin.html"), headers={"ngrok-skip-browser-warning": "1"})

async def handle_static(request):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    filename = request.match_info.get("filename", "")
    filepath = os.path.join(static_dir, filename)
    if not os.path.exists(filepath):
        raise web.HTTPNotFound()
    return web.FileResponse(filepath, headers={"ngrok-skip-browser-warning": "1"})


async def handle_web_index(request):
    web_static_dir = os.path.join(os.path.dirname(__file__), "web_static")
    return web.FileResponse(
        os.path.join(web_static_dir, "index.html"),
        headers={"ngrok-skip-browser-warning": "1"},
    )


async def handle_web_admin_page(request):
    web_static_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "web_static"))
    filepath = os.path.join(web_static_dir, "admin.html")
    if not os.path.isfile(filepath):
        raise web.HTTPNotFound()
    return web.FileResponse(filepath, headers={"ngrok-skip-browser-warning": "1"})


async def handle_web_health(request):
    return web.Response(text="ok")


async def handle_web_static(request):
    web_static_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "web_static"))
    filename = request.match_info.get("filename", "")
    filepath = os.path.realpath(os.path.join(web_static_dir, filename))
    if os.path.commonpath((web_static_dir, filepath)) != web_static_dir or not os.path.isfile(filepath):
        raise web.HTTPNotFound()
    return web.FileResponse(filepath, headers={"ngrok-skip-browser-warning": "1"})


# ==================== APP FACTORY ====================

@web.middleware
async def ngrok_middleware(request, handler):
    response = await handler(request)
    response.headers["ngrok-skip-browser-warning"] = "1"
    return response


@web.middleware
async def request_database_middleware(request, handler):
    db_token = _REQUEST_DB_PATH.set(request.app.get("db_path", DB_PATH))
    identity_token = _REQUEST_WEB_IDENTITY.set(None)
    try:
        settings = request.app.get(WEB_SETTINGS_KEY)
        if settings:
            identity = resolve_session(
                settings.db_path, request.cookies.get("ameba_session", ""),
                settings.session_secret, now=int(time.time()), admin_ids=settings.admin_ids,
            )
            _REQUEST_WEB_IDENTITY.set(identity)
        return await handler(request)
    finally:
        _REQUEST_WEB_IDENTITY.reset(identity_token)
        _REQUEST_DB_PATH.reset(db_token)


@web.middleware
async def staging_gate_middleware(request, handler):
    if request.path == "/healthz" and request.method == "GET":
        return await handler(request)
    settings = request.app.get(WEB_SETTINGS_KEY)
    if settings and settings.environment == "staging":
        try:
            credentials = BasicAuth.decode(request.headers.get("Authorization", ""))
        except (ValueError, UnicodeDecodeError):
            credentials = None
        username_ok = bool(credentials) and hmac.compare_digest(
            credentials.login, settings.staging_gate_user
        )
        password_ok = bool(credentials) and hmac.compare_digest(
            credentials.password, settings.staging_gate_password
        )
        if not (username_ok and password_ok):
            raise web.HTTPUnauthorized(
                headers={"WWW-Authenticate": 'Basic realm="AMEBA staging"'}
            )
    return await handler(request)


def _origin_is_same_site(request):
    origin = request.headers.get("Origin")
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        settings = request.app.get(WEB_SETTINGS_KEY)
        if settings:
            public_origin = urlsplit(settings.base_url)
            return (
                public_origin.scheme in {"http", "https"}
                and bool(public_origin.netloc)
                and parsed.scheme.lower() == public_origin.scheme.lower()
                and parsed.netloc.lower() == public_origin.netloc.lower()
            )
        return parsed.scheme == request.scheme and parsed.netloc.lower() == request.host.lower()
    except ValueError:
        return False


def _require_same_origin(request):
    if not _origin_is_same_site(request):
        raise web.HTTPForbidden(text="Cross-origin request rejected")


def _session_token(request):
    return request.cookies.get("ameba_session", "")


def _set_session_cookie(response, request, settings, token):
    response.set_cookie(
        "ameba_session", token, max_age=settings.session_ttl_seconds,
        httponly=True, secure=request.secure or settings.environment == "staging",
        samesite="Lax", path="/",
    )


async def handle_telegram_session_login(request):
    _require_same_origin(request)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return error_response("Invalid login payload", 400)
    settings = request.app[WEB_SETTINGS_KEY]
    telegram = validate_telegram_login(
        payload, settings.telegram_login_bot_token, now=int(time.time())
    )
    if not telegram:
        return error_response("Telegram verification failed", 401)

    full_name = telegram.first_name.strip()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO users(user_id, username, full_name, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, "
            "full_name=excluded.full_name, last_seen=CURRENT_TIMESTAMP",
            (telegram.user_id, telegram.username, full_name),
        )
    identity = WebIdentity(
        "telegram", str(telegram.user_id), full_name or str(telegram.user_id),
        telegram.user_id in settings.admin_ids,
    )
    token = create_session(settings.db_path, identity, settings.session_secret, settings.session_ttl_seconds)
    response = json_response({"success": True, "provider": "telegram"})
    _set_session_cookie(response, request, settings, token)
    return response


async def handle_google_session_login(request):
    try:
        form = await request.post()
    except (ValueError, UnicodeDecodeError):
        return error_response("Invalid login payload", 400)
    body_csrf = form.get("g_csrf_token", "")
    cookie_csrf = request.cookies.get("g_csrf_token", "")
    if not body_csrf or not cookie_csrf or not hmac.compare_digest(body_csrf, cookie_csrf):
        return error_response("Google CSRF validation failed", 403)
    settings = request.app[WEB_SETTINGS_KEY]
    google = await asyncio.to_thread(
        validate_google_id_token, form.get("credential", ""), settings.google_client_id
    )
    if not google:
        return error_response("Google verification failed", 401)

    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO web_google_accounts(subject, email, display_name, picture, last_seen) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(subject) DO UPDATE SET "
            "email=excluded.email, display_name=excluded.display_name, picture=excluded.picture, "
            "last_seen=CURRENT_TIMESTAMP",
            (google.subject, google.email, google.display_name, google.picture),
        )
    identity = WebIdentity("google", google.subject, google.display_name or google.subject, False)
    token = create_session(settings.db_path, identity, settings.session_secret, settings.session_ttl_seconds)
    response = json_response({"success": True, "provider": "google"})
    _set_session_cookie(response, request, settings, token)
    return response


async def handle_demo_session_login(request):
    settings = request.app[WEB_SETTINGS_KEY]
    if not settings.demo_login_enabled or settings.environment != "local":
        raise web.HTTPNotFound()
    _require_same_origin(request)

    from webapp_catalog import FACULTIES

    account_key = "local-demo-account"
    display_name = "Демо-пользователь"
    subjects = {
        subject["key"]
        for faculty in FACULTIES.values()
        for course_subjects in faculty["subjects"].values()
        for subject in course_subjects
    }
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO web_google_accounts(subject, email, display_name, last_seen) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(subject) DO UPDATE SET "
            "display_name=excluded.display_name, last_seen=CURRENT_TIMESTAMP",
            (account_key, "local-demo@example.invalid", display_name),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO web_google_access_grants(google_subject, subject) VALUES (?, ?)",
            [(account_key, subject) for subject in subjects],
        )

    identity = WebIdentity("google", account_key, display_name, False)
    token = create_session(settings.db_path, identity, settings.session_secret, settings.session_ttl_seconds)
    response = json_response({"success": True, "provider": "demo"})
    _set_session_cookie(response, request, settings, token)
    return response


async def handle_web_session(request):
    settings = request.app[WEB_SETTINGS_KEY]
    identity = resolve_session(
        settings.db_path, _session_token(request), settings.session_secret,
        now=int(time.time()), admin_ids=settings.admin_ids,
    )
    if not identity:
        return error_response("Authentication required", 401)
    return json_response({
        "authenticated": True,
        "provider": identity.provider,
        "account_key": identity.account_key,
        "display_name": identity.display_name,
        "is_admin": identity.is_admin,
        "is_demo": (
            identity.account_key == "local-demo-account"
            and settings.environment == "local"
        ),
    })


async def handle_web_session_logout(request):
    _require_same_origin(request)
    settings = request.app[WEB_SETTINGS_KEY]
    revoke_session(settings.db_path, _session_token(request), settings.session_secret)
    response = json_response({"success": True})
    response.del_cookie("ameba_session", path="/")
    return response


def _web_learning_config(identity):
    from webapp_catalog import FACULTIES

    faculties = {}
    access = {}
    trial_info = {}
    trials = _load_trials()
    user_id = int(identity.account_key) if identity.provider == "telegram" else identity.account_key
    for faculty_key, faculty in FACULTIES.items():
        subjects_by_course = {}
        for course, subjects in faculty["subjects"].items():
            subjects_by_course[str(course)] = subjects
            for subject in subjects:
                key = subject["key"]
                access[key] = _has_access(user_id, key)
                trial_info[key] = trials.get(user_id, {}).get(key, 0)
        faculties[faculty_key] = {
            "name": faculty["name"], "courses": faculty["courses"], "subjects": subjects_by_course,
        }
    return {
        "faculties": faculties,
        "access": access,
        "trials": trial_info,
        "user": {"id": user_id, "first_name": identity.display_name},
    }


async def handle_web_public_config(request):
    settings = request.app[WEB_SETTINGS_KEY]
    config = {
        "google_client_id": settings.google_client_id,
        "telegram_bot_username": settings.telegram_login_bot_username,
        "demo_login_enabled": settings.demo_login_enabled,
    }
    identity = _REQUEST_WEB_IDENTITY.get()
    if identity:
        config.update(_web_learning_config(identity))
    response = json_response(config)
    response.set_cookie(
        "g_csrf_token", secrets.token_urlsafe(32), max_age=300,
        httponly=False, secure=request.secure or settings.environment == "staging",
        samesite="Lax", path="/",
    )
    return response


def create_app(bot):
    SHARED["bot"] = bot

    app = web.Application(middlewares=[request_database_middleware, ngrok_middleware])

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    app.router.add_get("/", handle_index)
    app.router.add_get("/admin", handle_admin_page)
    app.router.add_get("/static/{filename:.+}", handle_static)

    # API routes
    app.router.add_get("/api/config", handle_config)
    app.router.add_get("/api/access", handle_access)

    app.router.add_post("/api/exam/start", handle_exam_start)
    app.router.add_get("/api/exam/question", handle_exam_question)
    app.router.add_post("/api/exam/navigate", handle_exam_navigate)
    app.router.add_post("/api/exam/answer", handle_exam_answer)
    app.router.add_post("/api/exam/finish", handle_exam_finish)
    app.router.add_get("/api/exam/results/{result_id}", handle_exam_result)
    app.router.add_get("/api/exam/status", handle_exam_status)

    app.router.add_post("/api/test/start", handle_test_start)
    app.router.add_post("/api/test/answer", handle_test_answer)
    app.router.add_get("/api/test/next", handle_test_next)

    app.router.add_get("/api/review", handle_review)

    app.router.add_post("/api/purchase/select", handle_purchase_select)
    app.router.add_post("/api/support/send", handle_support_send)
    app.router.add_get("/api/referral", handle_referral)

    app.router.add_get("/api/admin/check", handle_admin_check)
    app.router.add_post("/api/admin/login", handle_admin_login)
    app.router.add_get("/api/admin/questions", handle_admin_questions)
    app.router.add_post("/api/admin/question/{id}", handle_admin_question_edit)
    app.router.add_post("/api/admin/question/{id}/delete", handle_admin_question_delete)
    app.router.add_get("/api/admin/stats", handle_admin_stats)

    return app


def create_web_app(settings):
    from webapp_schema import init_web_database

    if os.path.realpath(settings.db_path) == os.path.realpath(DB_PATH):
        raise ValueError("The production bot database cannot be used by the standalone web app")
    init_web_database(settings.db_path)
    app = web.Application(middlewares=[staging_gate_middleware, request_database_middleware, ngrok_middleware])
    app["db_path"] = settings.db_path
    app[WEB_SETTINGS_KEY] = settings

    app.router.add_get("/", handle_web_index)
    app.router.add_get("/admin", handle_web_admin_page)
    app.router.add_get("/healthz", handle_web_health)
    app.router.add_get("/static/{filename:.+}", handle_web_static)
    app.router.add_get("/api/config", handle_web_public_config)
    app.router.add_post("/api/session/telegram", handle_telegram_session_login)
    app.router.add_post("/api/session/google", handle_google_session_login)
    app.router.add_post("/api/session/demo", handle_demo_session_login)
    app.router.add_get("/api/session", handle_web_session)
    app.router.add_post("/api/session/logout", handle_web_session_logout)
    app.router.add_get("/api/access", handle_access)
    app.router.add_post("/api/exam/start", handle_exam_start)
    app.router.add_get("/api/exam/question", handle_exam_question)
    app.router.add_post("/api/exam/navigate", handle_exam_navigate)
    app.router.add_post("/api/exam/answer", handle_exam_answer)
    app.router.add_post("/api/exam/finish", handle_exam_finish)
    app.router.add_get("/api/exam/results/{result_id}", handle_exam_result)
    app.router.add_get("/api/exam/status", handle_exam_status)
    app.router.add_post("/api/test/start", handle_test_start)
    app.router.add_post("/api/test/answer", handle_test_answer)
    app.router.add_get("/api/test/next", handle_test_next)
    app.router.add_get("/api/review", handle_review)
    app.router.add_post("/api/support/send", handle_web_support_send)
    app.router.add_get("/api/support", handle_web_support_list)
    app.router.add_get("/api/announcements", handle_web_announcements)
    app.router.add_get("/api/promo", handle_web_promo)
    app.router.add_get("/api/referral", handle_web_referral)
    app.router.add_post("/api/referral/claim", handle_web_referral_claim)
    app.router.add_get("/api/admin/check", handle_web_admin_check)
    app.router.add_get("/api/admin/questions", handle_admin_questions)
    app.router.add_post("/api/admin/question/{id}", handle_admin_question_edit)
    app.router.add_post("/api/admin/question/{id}/delete", handle_admin_question_delete)
    app.router.add_get("/api/admin/stats", handle_admin_stats)
    app.router.add_get("/api/admin/support", handle_web_admin_support)
    app.router.add_post("/api/admin/support/{id}/reply", handle_web_admin_support_reply)
    app.router.add_post("/api/admin/announcements", handle_web_admin_announcement)
    app.router.add_post("/api/admin/promo", handle_web_admin_promo)
    app.router.add_get("/api/admin/accounts", handle_web_admin_accounts)
    app.router.add_post("/api/admin/access", handle_web_admin_access)
    return app
