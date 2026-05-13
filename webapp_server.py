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

DB_PATH = "/data/questions.db"


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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    questions = cursor.fetchall()
    conn.close()
    if not questions:
        return []
    return random.sample(questions, min(limit, len(questions)))


def db_get_questions_excluding(subject, exclude_ids, limit=1):
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        (user_id, subject.lower(), question_id)
    )
    conn.commit()
    conn.close()


def db_save_history_batch(user_id, subject, question_ids):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        [(user_id, subject.lower(), qid) for qid in question_ids]
    )
    conn.commit()
    conn.close()


def db_get_correct(question_id):
    conn = sqlite3.connect(DB_PATH)
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
    return _sqlite3.connect(DB_PATH)

def _save_session(user_id, session_type, data):
    """Сохраняет сессию в SQLite."""
    conn = _db_conn()
    c = conn.cursor()
    # Конвертируем datetime в строку для JSON
    def serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    c.execute(
        "INSERT OR REPLACE INTO sessions (user_id, session_type, data, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, session_type, _json.dumps(data, default=serialize), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def _load_session(user_id, session_type):
    """Загружает сессию из SQLite. Возвращает dict или None."""
    conn = _db_conn()
    c = conn.cursor()
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
    c.execute("DELETE FROM sessions WHERE user_id=? AND session_type=?", (user_id, session_type))
    conn.commit()
    conn.close()

def _has_access(user_id, subject):
    conn = _db_conn()
    cursor = conn.cursor()
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
    for user_id, subjects in data.items():
        for subject, count in subjects.items():
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
    }
    await asyncio.to_thread(_save_session, user_id, 'exam', session_data)

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
    await asyncio.to_thread(_save_session, user_id, 'exam', session)

    return json_response({
        "has_next": has_next,
        "time_remaining": remaining,
    })


async def handle_exam_finish(request):
    user_id, _ = get_user_id(request)
    if not user_id:
        return error_response("Unauthorized", 401)

    session = await asyncio.to_thread(_load_session, user_id, 'exam')
    if not session:
        return error_response("No exam session")

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
        review_data = {
            "subject": session["subject"],
            "answers": answers,
            "current": 0,
        }
        await asyncio.to_thread(_save_session, user_id, 'review', review_data)

    await asyncio.to_thread(_delete_session, user_id, 'exam')

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

    await asyncio.to_thread(_save_session, user_id, 'test', {"subject": subject, "question": list(q), "active": True})

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
    auth = request.headers.get("Authorization", "")
    # Accept session token (password login)
    if auth == ADMIN_SESSION_TOKEN:
        return True
    # Accept Telegram initData
    user = validate_init_data(auth, config.API_TOKEN)
    if user and user.get("id") in ADMIN_IDS:
        return True
    return False

async def handle_admin_check(request):
    """Returns whether current user is admin — used by frontend to show/hide panel."""
    from urllib.parse import parse_qs, unquote
    import json as _json

    init_data = request.headers.get("Authorization", "")
    print(f"[ADMIN_CHECK] init_data len={len(init_data)}, preview={init_data[:80]!r}")

    user = None

    # Try strict validation first
    user = validate_init_data(init_data, config.API_TOKEN)
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
    if not _is_admin(request):
        return error_response("Forbidden", 403)
    def _fetch():
        conn = _sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT id, subject, question, option1, option2, option3, option4, option5,
                   correct_option, COALESCE(explanation, '')
            FROM questions ORDER BY subject, id
        """)
        rows = c.fetchall()
        conn.close()
        return rows
    rows = await asyncio.get_event_loop().run_in_executor(None, _fetch)
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
    if not _is_admin(request):
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
        conn = _sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE questions SET question=?, option1=?, option2=?, option3=?, option4=?, option5=?,
            correct_option=?, explanation=? WHERE id=?
        """, (question, option1, option2, option3, option4, option5, correct, explanation, q_id))
        conn.commit()
        conn.close()
    await asyncio.get_event_loop().run_in_executor(None, _update)
    return json_response({"success": True})

async def handle_admin_question_delete(request):
    if not _is_admin(request):
        return error_response("Forbidden", 403)
    q_id = request.match_info.get("id")
    try:
        q_id = int(q_id)
    except (ValueError, TypeError):
        return error_response("Invalid id")
    def _delete():
        conn = _sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM questions WHERE id=?", (q_id,))
        conn.commit()
        conn.close()
    await asyncio.get_event_loop().run_in_executor(None, _delete)
    return json_response({"success": True})


# --- Stats ---
async def handle_admin_stats(request):
    if not _is_admin(request):
        return error_response("Forbidden", 403)

    def _get_stats():
        conn = _sqlite3.connect(DB_PATH)
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

    stats = await asyncio.get_event_loop().run_in_executor(None, _get_stats)
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


# ==================== APP FACTORY ====================

@web.middleware
async def ngrok_middleware(request, handler):
    response = await handler(request)
    response.headers["ngrok-skip-browser-warning"] = "1"
    return response


def create_app(bot):
    SHARED["bot"] = bot

    app = web.Application(middlewares=[ngrok_middleware])

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    app.router.add_get("/", handle_index)
    app.router.add_get("/admin", handle_admin_page)
    app.router.add_get("/static/{filename:.+}", handle_static)

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
    app.router.add_get("/api/referral", handle_referral)

    app.router.add_get("/api/admin/check", handle_admin_check)
    app.router.add_post("/api/admin/login", handle_admin_login)
    app.router.add_get("/api/admin/questions", handle_admin_questions)
    app.router.add_post("/api/admin/question/{id}", handle_admin_question_edit)
    app.router.add_post("/api/admin/question/{id}/delete", handle_admin_question_delete)
    app.router.add_get("/api/admin/stats", handle_admin_stats)

    return app
