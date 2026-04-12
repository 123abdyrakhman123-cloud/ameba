import asyncio
import json
import os
import random
import sqlite3
from datetime import datetime

from aiohttp import web

import config
from webapp_auth import validate_init_data

# Lock for pickle file access
pkl_lock = asyncio.Lock()

# Reference to shared state (set in create_app)
SHARED = {}


def get_user_id(request):
    """Extract and validate Telegram user from initData."""
    init_data = request.headers.get("Authorization", "")
    user = validate_init_data(init_data, config.API_TOKEN)
    if not user:
        return None, None
    return user.get("id"), user


def json_response(data, status=200):
    return web.json_response(data, status=status)


def error_response(msg, status=400):
    return web.json_response({"error": msg}, status=status)


# ==================== DB helpers (sync, run in thread) ====================

def db_get_questions(subject, limit=500):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    questions = cursor.fetchall()
    conn.close()
    if not questions:
        return []
    return random.sample(questions, min(limit, len(questions)))


def db_get_questions_excluding(subject, exclude_ids, limit=1):
    conn = sqlite3.connect("questions.db")
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
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT question_id FROM question_history "
        "WHERE user_id=? AND subject=? ORDER BY asked_at DESC LIMIT ?",
        (user_id, subject.lower(), limit)
    )
    ids = [r[0] for r in cursor.fetchall()]
    conn.close()
    return ids


def db_save_history(user_id, subject, question_id):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        (user_id, subject.lower(), question_id)
    )
    conn.commit()
    conn.close()


def db_save_history_batch(user_id, subject, question_ids):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        [(user_id, subject.lower(), qid) for qid in question_ids]
    )
    conn.commit()
    conn.close()


def db_get_correct(question_id):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT correct_option, COALESCE(explanation, '') FROM questions WHERE id=?",
        (question_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row


# ==================== Pickle helpers ====================

import pickle

def _load_purchases():
    try:
        with open("purchases.pkl", "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}

def _load_trials():
    try:
        with open("trial.pkl", "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}

def _save_trials(data):
    with open("trial.pkl", "wb") as f:
        pickle.dump(data, f)

def _has_access(user_id, subject):
    purchases = _load_purchases()
    up = purchases.get(user_id, {})
    if subject not in up:
        return False
    exp = up[subject]
    if exp is None:
        return True
    if isinstance(exp, datetime) and datetime.now() > exp:
        return False
    return True


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

    exam_sessions = SHARED["exam_sessions"]

    questions = await asyncio.to_thread(db_get_questions, subject, 50)
    if not questions:
        return error_response("No questions in database")

    # Deduplicate
    seen = set()
    unique = []
    for q in questions:
        if q[0] not in seen:
            seen.add(q[0])
            unique.append(q)
    questions = unique

    await asyncio.to_thread(db_save_history_batch, user_id, subject, [q[0] for q in questions])

    exam_sessions[user_id] = {
        "subject": subject,
        "questions": questions,
        "current": 0,
        "score": 0,
        "active": True,
        "start_time": datetime.now(),
        "answers": [],
    }

    return json_response({
        "total_questions": len(questions),
        "duration_minutes": 75,
    })


async def handle_exam_question(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    exam_sessions = SHARED["exam_sessions"]
    session = exam_sessions.get(user_id)
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
        "time_remaining": remaining,
    })


async def handle_exam_answer(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    exam_sessions = SHARED["exam_sessions"]
    session = exam_sessions.get(user_id)
    if not session or not session["active"]:
        return error_response("No active exam")

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    remaining = max(0, 75 * 60 - int(elapsed))
    if remaining <= 0:
        return json_response({"expired": True, "time_remaining": 0})

    data = await request.json()
    selected = data.get("selected")
    if not selected:
        return error_response("selected required")

    idx = session["current"]
    if idx >= len(session["questions"]):
        return error_response("Exam already finished")

    current_q = session["questions"][idx]
    row = await asyncio.to_thread(db_get_correct, current_q[0])

    correct_option = 0
    explanation = ""
    is_correct = False
    if row:
        correct_option = row[0]
        explanation = row[1]
        if selected == correct_option:
            is_correct = True
            session["score"] += 2

    session["answers"].append({
        "question": current_q,
        "selected": selected,
        "correct": correct_option,
        "is_correct": is_correct,
        "explanation": explanation,
    })
    session["current"] += 1

    has_next = session["current"] < len(session["questions"])

    return json_response({
        "has_next": has_next,
        "time_remaining": remaining,
    })


async def handle_exam_finish(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    exam_sessions = SHARED["exam_sessions"]
    review_sessions = SHARED["review_sessions"]
    session = exam_sessions.get(user_id)
    if not session:
        return error_response("No exam session")

    session["active"] = False
    answers = session.get("answers", [])
    score = session["score"]
    total = len(session["questions"])
    answered = session["current"]
    correct_count = sum(1 for a in answers if a["is_correct"])
    errors_count = sum(1 for a in answers if not a["is_correct"])

    elapsed = (datetime.now() - session["start_time"]).total_seconds()
    time_expired = elapsed >= 75 * 60

    # Save for review
    if answers:
        review_sessions[user_id] = {
            "subject": session["subject"],
            "answers": answers,
            "current": 0,
        }

    del exam_sessions[user_id]

    return json_response({
        "score": score,
        "max_score": total * 2,
        "answered": answered,
        "total": total,
        "percentage": round(score / (total * 2) * 100, 1) if total > 0 else 0,
        "correct": correct_count,
        "errors": errors_count,
        "time_expired": time_expired,
    })


async def handle_exam_status(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    exam_sessions = SHARED["exam_sessions"]
    session = exam_sessions.get(user_id)
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

    test_sessions = SHARED["test_sessions"]
    test_sessions[user_id] = {"subject": subject, "question": q, "active": True}

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

    test_sessions = SHARED["test_sessions"]
    session = test_sessions.get(user_id)
    if not session or not session["active"]:
        return error_response("No active test")

    subject = session["subject"]
    data = await request.json()
    selected = data.get("selected")
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

    return json_response({
        "is_correct": is_correct,
        "correct_option": correct_option,
        "explanation": explanation,
        "trial_remaining": trial_remaining,
        "trial_limit_reached": trial_limit_reached,
        "has_access": has,
    })


async def handle_test_next(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    test_sessions = SHARED["test_sessions"]
    session = test_sessions.get(user_id)
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
    session["question"] = q

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

    review_sessions = SHARED["review_sessions"]
    session = review_sessions.get(user_id)
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

    try:
        await bot.send_message(
            coder_chat_id,
            f"💳 Новый запрос (Mini App): {sender} (id: `{user_id}`)\n"
            f"Предмет: *{subject}*\nПериод: *{period}* ({prices[period]})",
            parse_mode="Markdown",
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

    try:
        await bot.send_message(
            coder_chat_id,
            f"🆘 Сообщение (Mini App) от {sender} (id:{user_id}):\n\n{message}",
        )
    except Exception:
        pass

    return json_response({"success": True})


# --- Static files ---
async def handle_index(request):
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return web.FileResponse(os.path.join(static_dir, "index.html"))


# ==================== APP FACTORY ====================

def create_app(bot, exam_sessions, test_sessions, review_sessions):
    SHARED["bot"] = bot
    SHARED["exam_sessions"] = exam_sessions
    SHARED["test_sessions"] = test_sessions
    SHARED["review_sessions"] = review_sessions

    app = web.Application()

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    app.router.add_get("/", handle_index)
    app.router.add_static("/static/", static_dir, name="static")

    # API routes
    app.router.add_get("/api/config", handle_config)
    app.router.add_get("/api/access", handle_access)

    app.router.add_post("/api/exam/start", handle_exam_start)
    app.router.add_get("/api/exam/question", handle_exam_question)
    app.router.add_post("/api/exam/answer", handle_exam_answer)
    app.router.add_post("/api/exam/finish", handle_exam_finish)
    app.router.add_get("/api/exam/status", handle_exam_status)

    app.router.add_post("/api/test/start", handle_test_start)
    app.router.add_post("/api/test/answer", handle_test_answer)
    app.router.add_get("/api/test/next", handle_test_next)

    app.router.add_get("/api/review", handle_review)

    app.router.add_post("/api/purchase/select", handle_purchase_select)
    app.router.add_post("/api/support/send", handle_support_send)

    return app
