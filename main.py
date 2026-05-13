import asyncio
import os
import random
import sqlite3
import pickle
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiohttp import web
import config
import init_db  # создаёт таблицы при старте
from webapp_server import create_app, _save_session, _load_session, _delete_session

WEBAPP_URL = "https://ameba-app.uk"

# --- КОНФИГУРАЦИЯ ---
CODER_CHAT_ID = 1427715527

# --- АДМИНЫ ---
SUPER_ADMIN_IDS = {1427715527, 1347147831, 905937261}  # получают уведомления о покупках и квитанции
ADMIN_IDS = {1427715527, 905937261, 8113642902, 771714551, 1347147831, 751240103, 1238729309, 6586083917, 921010964, 1333298810, 942664226, 1239722079}  # доступ к /admin панели
QR_FILE = os.path.join(os.path.dirname(__file__), "qr.png")  # QR-код из локального файла
QR_ID = None  # Кэшируется после первой отправки

bot = Bot(token=config.API_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ ---
exam_sessions = {}
test_sessions = {}
review_sessions = {}  # Работа над ошибками после экзамена
feedback_waiting = set()
message_waiting = {}  # admin_id → target_user_id (int) или "all" для рассылки

# --- КОНСТАНТЫ ---
EXAM_DURATION_MINUTES = 75  # 1 час 15 минут

ACCESS_OPTIONS = {
    "forever": {"days": None}
}

# --- СТРУКТУРА: ФАКУЛЬТЕТ → КУРС → ПРЕДМЕТ ---
FACULTIES = {
    "lech": {
        "name": "🏥 Лечебное дело",
        "courses": 6,
        "subjects": {
            2: [
                {"key": "histology", "name": "🔬 Гистология"},
                {"key": "microbiology", "name": "🦠 Микробиология"},
                {"key": "biochemistry", "name": "⚗️ Биохимия"},
            ],
            3: [
                {"key": "pharmacology", "name": "💊 Фармакология"},
                {"key": "therapy3", "name": "🩻 Терапия 3"},
                {"key": "pediatrics3", "name": "👶 Педиатрия"},
                {"key": "surgery3", "name": "🩺 Хирургия 3"},
                {"key": "hygiene", "name": "🧼 Гигиена"},
                {"key": "pathophysiology", "name": "🫀 Патфиз"},
            ],
            4: [
                {"key": "obstetrics", "name": "🤰 Акушерство и Гинекология"},
                {"key": "therapy4", "name": "🩻 Терапия 4"},
                {"key": "dermatology", "name": "🧴 Дерматовенерология"},
                {"key": "lor", "name": "👂 ЛОР"},
                {"key": "neurology", "name": "🧠 Неврология"},
                {"key": "mmp", "name": "💉 ВМП"},
                {"key": "ophthalmology", "name": "👁 Офтальмология"},
            ],
            5: [
                {"key": "surgery5", "name": "🩺 Хирургия 5"},
                {"key": "psychiatry", "name": "🧠 Психиатрия"},
                {"key": "infections", "name": "🦠 Инфекционные болезни"},
                {"key": "therapy5", "name": "🩻 Терапия 5"},
                {"key": "pediatrics5", "name": "👶 Педиатрия 5"},
            ],
        }
    }
}

# --- Все ключи предметов для валидации ---
ALL_SUBJECT_KEYS = {
    subj["key"]
    for fac in FACULTIES.values()
    for subjects in fac["subjects"].values()
    for subj in subjects
}

# Маппинг коротких ключей факультетов к полным названиям
FACULTY_NAMES = {k: v["name"] for k, v in FACULTIES.items()}

# ---------------- Функции для таймера ----------------
def get_time_remaining(start_time):
    """Возвращает оставшееся время в формате (minutes, seconds, is_expired)"""
    elapsed = datetime.now() - start_time
    total_seconds = EXAM_DURATION_MINUTES * 60 - int(elapsed.total_seconds())

    if total_seconds <= 0:
        return 0, 0, True

    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return minutes, seconds, False

def format_time_remaining(minutes, seconds):
    """Форматирует оставшееся время для отображения"""
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"⏱ Осталось времени: {hours:01d}:{mins:02d}:{seconds:02d}"
    return f"⏱ Осталось времени: {minutes:02d}:{seconds:02d}"

# ---------------- Работа с базой ----------------

def get_recent_question_ids(user_id, subject, limit=200):
    """Возвращает список ID последних N вопросов, показанных пользователю"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT question_id FROM question_history "
        "WHERE user_id=? AND subject=? "
        "ORDER BY asked_at DESC LIMIT ?",
        (user_id, subject.lower(), limit)
    )
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids

def save_question_to_history(user_id, subject, question_id):
    """Сохраняет показанный вопрос в историю"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        (user_id, subject.lower(), question_id)
    )
    conn.commit()
    conn.close()

def save_questions_to_history(user_id, subject, question_ids):
    """Сохраняет список показанных вопросов в историю"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        [(user_id, subject.lower(), qid) for qid in question_ids]
    )
    conn.commit()
    conn.close()

def get_questions(subject, limit=500):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    questions = cursor.fetchall()
    conn.close()
    if not questions:
        return []
    return random.sample(questions, min(limit, len(questions)))

def get_questions_excluding(subject, exclude_ids, limit=1):
    """Получает случайные вопросы, исключая указанные ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    all_questions = cursor.fetchall()
    conn.close()
    if not all_questions:
        return []
    # Фильтруем вопросы, которые были недавно показаны
    filtered = [q for q in all_questions if q[0] not in exclude_ids]
    # Если все вопросы были показаны, сбрасываем фильтр
    if not filtered:
        filtered = all_questions
    return random.sample(filtered, min(limit, len(filtered)))

def question_to_inline(question, mode="exam"):
    # question[3:8] - это option1..option5
    options = [opt for opt in question[3:8] if opt and isinstance(opt, str)]
    inline_keyboard = []
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    for i, opt in enumerate(options):
        # callback_data: ans_e_1_123 или ans_t_1_123 (до 64 байт)
        cb_mode = "e" if mode == "exam" else "t"
        inline_keyboard.append(
            [InlineKeyboardButton(text=emojis[i], callback_data=f"ans_{cb_mode}_{i + 1}_{question[0]}")]
        )

    # Добавляем кнопку "Вернуться в меню"
    inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_menu")]
    )

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def format_question_text(question, question_number=None, total_questions=None):
    """Форматирует текст вопроса с вариантами ответов"""
    # question[2] - текст вопроса
    # question[3:8] - варианты ответов
    options = [opt for opt in question[3:8] if opt and isinstance(opt, str)]

    text = ""
    if question_number and total_questions:
        text += f"Вопрос {question_number}/{total_questions}\n\n"

    text += f"{question[2]}\n\n"

    for i, opt in enumerate(options):
        text += f"{i + 1}. {opt}\n\n"

    return text.strip()

# ---------------- Inline кнопки ----------------
def faculty_menu_inline():
    """Меню выбора факультета"""
    buttons = []
    for fac_key, fac_data in FACULTIES.items():
        buttons.append([InlineKeyboardButton(text=fac_data["name"], callback_data=f"fac_{fac_key}")])
    buttons.append([InlineKeyboardButton(text="📩 Поддержка", callback_data="support")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_start")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def course_menu_inline(fac_key):
    """Меню выбора курса для факультета"""
    fac = FACULTIES[fac_key]
    buttons = []
    for course_num in range(1, fac["courses"] + 1):
        # Показываем есть ли предметы на курсе
        has_subjects = course_num in fac["subjects"] and len(fac["subjects"][course_num]) > 0
        label = f"📚 {course_num} курс"
        if not has_subjects:
            label += " (скоро)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"course_{fac_key}_{course_num}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к факультетам", callback_data="show_faculties")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def subject_menu_inline(fac_key, course_num):
    """Меню выбора предмета для курса"""
    fac = FACULTIES[fac_key]
    subjects = fac["subjects"].get(course_num, [])
    buttons = []
    for subj in subjects:
        buttons.append([InlineKeyboardButton(text=subj["name"], callback_data=f"subj_{fac_key}_{course_num}_{subj['key']}")])
    buttons.append([InlineKeyboardButton(text=f"⬅️ Назад к курсам", callback_data=f"fac_{fac_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def mode_inline(subject, fac_key, course_num, has_acc=False):
    """Меню выбора режима для предмета"""
    buttons = [
        [InlineKeyboardButton(text="📝 Симуляция экзамена", callback_data=f"mode_exam_{subject}")],
        [InlineKeyboardButton(text="📖 Решать тесты", callback_data=f"mode_tests_{subject}")],
    ]
    if not has_acc:
        buttons.append([InlineKeyboardButton(text="💳 Купить доступ", callback_data=f"buy_access_{subject}")])
    buttons.append([InlineKeyboardButton(text=f"⬅️ Назад к предметам", callback_data=f"course_{fac_key}_{course_num}")])
    buttons.append([InlineKeyboardButton(text="📩 Поддержка", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------- Отправка QR-кода ----------------
async def send_qr_photo(chat_id, caption, reply_markup=None, parse_mode=None):
    """Отправляет QR-код: сначала пробует кэшированный file_id, иначе из файла."""
    global QR_ID
    if QR_ID:
        try:
            msg = await bot.send_photo(
                chat_id=chat_id, photo=QR_ID,
                caption=caption, parse_mode=parse_mode, reply_markup=reply_markup
            )
            return msg
        except Exception:
            QR_ID = None  # file_id не работает, отправим из файла

    # Отправляем из файла
    msg = await bot.send_photo(
        chat_id=chat_id, photo=FSInputFile(QR_FILE),
        caption=caption, parse_mode=parse_mode, reply_markup=reply_markup
    )
    # Кэшируем file_id для следующих отправок
    if msg.photo:
        QR_ID = msg.photo[-1].file_id
    return msg

# ---------------- Работа с доступами и пользователями (SQLite) ----------------
DB_PATH = "/data/questions.db"

def db_conn():
    return sqlite3.connect(DB_PATH)

def register_user(user_id: int, username: str = None, full_name: str = None):
    """Сохраняет пользователя в таблицу users при /start"""
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            last_seen=CURRENT_TIMESTAMP
    """, (user_id, username, full_name))
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# РЕФЕРАЛЬНАЯ СИСТЕМА — вспомогательные функции
# ──────────────────────────────────────────────

REFERRAL_LEVEL_THRESHOLDS = [
    (0,  "🟢 Новичок",     30, 100),   # 0-9  купивших → +30 бонус, лимит 100
    (10, "🔵 Продвинутый", 40, 200),  # 10-19 купивших → +40 бонус, лимит 200
    (20, "🟣 Мессия",      50, 300),  # 20+  купивших → +50 бонус, лимит 300
]

POINTS_REGISTRATION    = 5   # новый пользователь запустил бота
POINTS_REF_TRIAL_SELF  = 15  # прошёл 5 вопросов будучи рефералом (пришёл по ссылке)
POINTS_REF_JOIN        = 10  # кто-то перешёл по твоей ссылке и запустил бота
POINTS_OWN_PURCHASE    = 40  # купил предмет сам


def get_referral_level(referral_count: int) -> tuple:
    """Возвращает (название уровня, бонус за покупку реферала, лимит списания)"""
    level_name, bonus, limit = "🟢 Новичок", 30, 100
    for threshold, name, b, lim in REFERRAL_LEVEL_THRESHOLDS:
        if referral_count >= threshold:
            level_name, bonus, limit = name, b, lim
    return level_name, bonus, limit


def get_points_balance(user_id: int) -> int:
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT points_balance FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def get_reserved_points(user_id: int) -> int:
    """Баллы зарезервированные под ожидающие подтверждения покупки"""
    conn = db_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(SUM(points),0) FROM points_reserved WHERE user_id=? AND status='pending'",
        (user_id,)
    )
    val = c.fetchone()[0]
    conn.close()
    return val


def add_points(user_id: int, delta: int, reason: str,
               related_user_id: int = None, subject: str = None):
    """Начислить или списать баллы. delta > 0 — начисление, < 0 — списание."""
    conn = db_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET points_balance = points_balance + ? WHERE user_id=?",
        (delta, user_id)
    )
    c.execute(
        "INSERT INTO points_log (user_id, delta, reason, related_user_id, subject) VALUES (?,?,?,?,?)",
        (user_id, delta, reason, related_user_id, subject)
    )
    conn.commit()
    conn.close()


def get_referrer_id(user_id: int):
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_referrer(user_id: int, referrer_id: int):
    """Привязать реферера к новому пользователю (только один раз)"""
    conn = db_conn()
    c = conn.cursor()
    # Проверяем что реферер не привязан и не пытается пригласить сам себя
    c.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0] is None and user_id != referrer_id:
        c.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id))
        # Создаём запись в referrals
        c.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referee_id) VALUES (?,?)",
            (referrer_id, user_id)
        )
        conn.commit()
    conn.close()


def get_referral_stats(user_id: int) -> dict:
    """Статистика реферера: количество рефералов, уровень, баллы"""
    conn = db_conn()
    c = conn.cursor()
    # Количество рефералов которые купили (для уровня)
    c.execute(
        "SELECT referral_count, points_balance FROM users WHERE user_id=?",
        (user_id,)
    )
    row = c.fetchone()
    referral_count = row[0] if row else 0
    points = row[1] if row else 0

    # Всего приглашённых (не обязательно купили)
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    total_invited = c.fetchone()[0]

    conn.close()

    level_name, bonus, limit = get_referral_level(referral_count)

    # До следующего уровня
    next_level_info = None
    for threshold, name, b, lim in REFERRAL_LEVEL_THRESHOLDS:
        if referral_count < threshold:
            next_level_info = (threshold - referral_count, name, b, lim)
            break

    return {
        "referral_count": referral_count,    # купили
        "total_invited": total_invited,       # всего приглашено
        "points_balance": points,
        "level_name": level_name,
        "bonus_per_purchase": bonus,
        "spend_limit": limit,                 # лимит списания по уровню
        "next_level_info": next_level_info,   # (осталось, название, бонус, лимит)
    }


def log_exam_start(user_id: int, subject: str):
    """Записывает факт запуска симуляции экзамена"""
    conn = db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO exam_log (user_id, subject) VALUES (?, ?)",
            (user_id, subject.lower())
        )
        conn.commit()
    except Exception:
        pass
    conn.close()

def get_all_user_ids() -> list:
    """Возвращает всех пользователей: из таблицы users + из истории + из покупок"""
    conn = db_conn()
    cursor = conn.cursor()
    ids = set()
    # Из таблицы users (если есть)
    try:
        cursor.execute("SELECT user_id FROM users")
        ids.update(r[0] for r in cursor.fetchall())
    except Exception:
        pass
    # Из истории вопросов
    try:
        cursor.execute("SELECT DISTINCT user_id FROM question_history")
        ids.update(r[0] for r in cursor.fetchall())
    except Exception:
        pass
    # Из покупок
    try:
        cursor.execute("SELECT DISTINCT user_id FROM purchases")
        ids.update(r[0] for r in cursor.fetchall())
    except Exception:
        pass
    conn.close()
    return list(ids)

def has_access(user_id: int, subject: str) -> bool:
    conn = db_conn()
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
        exp_dt = datetime.fromisoformat(expires_at)
        return datetime.now() <= exp_dt
    except Exception:
        return True

def grant_access_db(user_id: int, subject: str, expires_at=None):
    """Выдать доступ. expires_at=None → навсегда."""
    conn = db_conn()
    cursor = conn.cursor()
    exp_str = expires_at.isoformat() if expires_at else None
    cursor.execute(
        "INSERT OR REPLACE INTO purchases (user_id, subject, expires_at) VALUES (?, ?, ?)",
        (user_id, subject.lower(), exp_str)
    )
    conn.commit()
    conn.close()

def revoke_access_db(user_id: int, subject: str):
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM purchases WHERE user_id=? AND subject=?",
        (user_id, subject.lower())
    )
    conn.commit()
    conn.close()

def load_purchases():
    """Совместимость — возвращает dict {user_id: {subject: expires}}"""
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subject, expires_at FROM purchases")
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for user_id, subject, expires_at in rows:
        if user_id not in result:
            result[user_id] = {}
        result[user_id][subject] = None if expires_at is None else datetime.fromisoformat(expires_at)
    return result

def save_purchases(purchases):
    """Совместимость — сохраняет dict в SQLite."""
    conn = db_conn()
    cursor = conn.cursor()
    for user_id, subjects in purchases.items():
        for subject, expires_at in subjects.items():
            exp_str = expires_at.isoformat() if isinstance(expires_at, datetime) else None
            cursor.execute(
                "INSERT OR REPLACE INTO purchases (user_id, subject, expires_at) VALUES (?, ?, ?)",
                (user_id, subject.lower(), exp_str)
            )
    conn.commit()
    conn.close()

# ---------- ПРОБНЫЙ ДОСТУП (SQLite) ----------
def load_trials():
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, subject, count FROM trials")
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for user_id, subject, count in rows:
        if user_id not in result:
            result[user_id] = {}
        result[user_id][subject] = count
    return result

def save_trials(data):
    conn = db_conn()
    cursor = conn.cursor()
    for user_id, subjects in data.items():
        for subject, count in subjects.items():
            cursor.execute(
                "INSERT OR REPLACE INTO trials (user_id, subject, count) VALUES (?, ?, ?)",
                (user_id, subject.lower(), count)
            )
    conn.commit()
    conn.close()

def increment_trial(user_id: int, subject: str) -> int:
    """Увеличивает счётчик триала и возвращает новое значение."""
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO trials (user_id, subject, count) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, subject) DO UPDATE SET count=count+1",
        (user_id, subject.lower())
    )
    conn.commit()
    cursor.execute("SELECT count FROM trials WHERE user_id=? AND subject=?", (user_id, subject.lower()))
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ---------- АКЦИИ ----------
PROMO_FILE = "promo.txt"

def load_promo():
    if not os.path.exists(PROMO_FILE):
        return ""
    with open(PROMO_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def save_promo(text):
    with open(PROMO_FILE, "w", encoding="utf-8") as f:
        f.write(text.strip())

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Выбрать предмет"), KeyboardButton(text="💡 Как заработать баллы")],
            [KeyboardButton(text="💎 Баллы и рефералка"), KeyboardButton(text="🆘 Поддержка")],
            [KeyboardButton(text="📱 Открыть приложение")],
        ],
        resize_keyboard=True,
        persistent=True,
    )

@dp.callback_query(F.data == "show_promo")
async def show_promo_callback(callback: CallbackQuery):
    promo_text = load_promo()
    info_text = (
        "💎 Как заработать и потратить баллы\n\n"
        f"🎯 За себя:\n"
        f"• Зарегистрировался в боте → +{POINTS_REGISTRATION} баллов\n"
        f"• Купил предмет → +{POINTS_OWN_PURCHASE} баллов\n\n"
        f"👥 За рефералов (по твоей ссылке):\n"
        f"• Друг запустил бота → +{POINTS_REF_JOIN} баллов тебе\n"
        f"• Друг прошёл 5 вопросов → +{POINTS_REF_TRIAL_SELF} баллов ему\n"
        f"• Друг купил предмет → +30/40/50 тебе (по уровню)\n\n"
        f"🏆 Уровни:\n"
        f"🟢 Новичок (0–9 покупок) → +30, лимит 100 сом\n"
        f"🔵 Продвинутый (10–19) → +40, лимит 200 сом\n"
        f"🟣 Мессия (20+) → +50, лимит 300 сом\n\n"
        f"💰 Трата баллов:\n"
        f"1 балл = 1 сом скидки при покупке предмета.\n"
        f"Лимит зависит от уровня (100/200/300 сом).\n\n"
        f"🔗 Твоя ссылка и баланс — кнопка «💎 Баллы и рефералка»"
    )
    if promo_text:
        info_text += f"\n\n{'—' * 20}\n\n{promo_text}"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Мои баллы и ссылка", callback_data="show_ref")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_start")]
    ])
    await callback.message.edit_text(info_text, reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "show_ref")
async def show_ref_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        stats = get_referral_stats(user_id)
        next_info = stats["next_level_info"]
        if next_info:
            next_text = (
                f"\n📈 Осталось {next_info[0]} покупок рефералов до {next_info[1]}\n"
                f"   бонус вырастет до +{next_info[2]}, лимит до {next_info[3]} баллов"
            )
        else:
            next_text = "\n🏆 Вы на максимальном уровне!"
        text = (
            f"👥 Ваша реферальная программа\n\n"
            f"🔗 Ваша ссылка:\n{ref_link}\n\n"
            f"📊 Статистика:\n"
            f"• Приглашено всего: {stats['total_invited']} чел.\n"
            f"• Из них купили: {stats['referral_count']} чел.\n\n"
            f"🎖 Уровень: {stats['level_name']}\n"
            f"💰 Бонус за покупку реферала: +{stats['bonus_per_purchase']} баллов\n"
            f"🔒 Ваш лимит скидки: {stats['spend_limit']} баллов"
            f"{next_text}\n\n"
            f"💎 Ваш баланс: {stats['points_balance']} баллов"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_promo")]
        ]))
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == "back_to_start")
async def back_to_start_callback(callback: CallbackQuery):
    text = (
        "👋 Привет! Это Амёба!\n\n"
        "Добро пожаловать в бот для подготовки к экзаменам.\n"
        "Здесь вы сможете проходить тесты и симуляции экзамена по разным предметам.\n\n"
        "Нажмите кнопку - квадартик, чтобы продолжить 🔥"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💡 Как заработать баллы", callback_data="show_promo")],
            [InlineKeyboardButton(text="➡️ Продолжить в боте", callback_data="show_faculties")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()

# ---------------- Старт ----------------
@dp.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    is_new_user = False

    # Проверяем новый ли пользователь (до регистрации)
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    is_new_user = c.fetchone() is None
    conn.close()

    # Регистрируем пользователя в БД
    try:
        register_user(
            user_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
    except Exception:
        pass

    # Начисляем баллы за регистрацию (только новым)
    if is_new_user:
        add_points(user_id, POINTS_REGISTRATION, "registration")

    # Обрабатываем реферальный параметр (только для новых пользователей)
    args = message.text.split(maxsplit=1)
    if is_new_user and len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            set_referrer(user_id, referrer_id)
            # +10 пригласившему сразу при переходе по ссылке
            if referrer_id != user_id:
                add_points(referrer_id, POINTS_REF_JOIN, "referral_join", related_user_id=user_id)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 Кто-то перешёл по вашей реферальной ссылке!\n"
                        f"Вам начислено +{POINTS_REF_JOIN} баллов."
                    )
                except Exception:
                    pass
        except (ValueError, IndexError):
            pass

    text = (
        "👋 Привет! Это Амёба!\n\n"
        "Добро пожаловать в бот для подготовки к экзаменам.\n"
        "Здесь вы сможете проходить тесты и симуляции экзамена по разным предметам.\n\n"
        "Нажмите кнопку - квадартик, чтобы продолжить 🔥"
    )
    await message.answer(text, reply_markup=main_reply_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "show_faculties")
async def show_faculties_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏛 Выберите факультет:", reply_markup=faculty_menu_inline()
    )
    await callback.answer()

async def show_faculties_callback_from_message(message: Message):
    await message.answer("🏛 Выберите факультет:", reply_markup=faculty_menu_inline())

# ---------------- Выбор факультета → курсы ----------------
@dp.callback_query(lambda c: c.data.startswith("fac_"))
async def handle_faculty_click(callback: CallbackQuery):
    fac_key = callback.data.split("_", 1)[1]
    if fac_key not in FACULTIES:
        await callback.answer("Факультет не найден.")
        return
    fac_name = FACULTIES[fac_key]["name"]
    await callback.message.edit_text(
        f"{fac_name}\n\n📚 Выберите курс:",
        reply_markup=course_menu_inline(fac_key)
    )
    await callback.answer()

# ---------------- Выбор курса → предметы ----------------
@dp.callback_query(lambda c: c.data.startswith("course_"))
async def handle_course_click(callback: CallbackQuery):
    parts = callback.data.split("_")
    fac_key = parts[1]
    course_num = int(parts[2])

    if fac_key not in FACULTIES:
        await callback.answer("Факультет не найден.")
        return

    fac = FACULTIES[fac_key]
    subjects = fac["subjects"].get(course_num, [])

    if not subjects:
        await callback.answer("🔜 Предметы для этого курса скоро появятся!", show_alert=True)
        return

    fac_name = fac["name"]
    await callback.message.edit_text(
        f"{fac_name} — {course_num} курс\n\n📖 Выберите предмет:",
        reply_markup=subject_menu_inline(fac_key, course_num)
    )
    await callback.answer()

# ---------------- Выбор предмета → режимы ----------------
@dp.callback_query(lambda c: c.data.startswith("subj_"))
async def handle_subject_click(callback: CallbackQuery):
    # subj_lech_2_histology
    parts = callback.data.split("_")
    fac_key = parts[1]
    course_num = int(parts[2])
    subject = parts[3]
    user_id = callback.from_user.id

    await show_subject_modes(callback, subject, fac_key, course_num)

    if has_access(user_id, subject):
        await callback.answer(f"Полный доступ к {subject.capitalize()}!")
    else:
        # Проверяем сколько осталось пробных
        trials = load_trials()
        user_trials = trials.get(user_id, {}).get(subject, 0)
        remaining = max(0, 5 - user_trials)
        if remaining > 0:
            await callback.answer(f"Пробный режим: {remaining} вопросов бесплатно")
        else:
            await callback.answer("Пробный период закончился")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню (факультеты) с завершением сессий"""
    user_id = callback.from_user.id

    # Завершаем активные сессии, если они есть
    _delete_session(user_id, 'exam')
    _delete_session(user_id, 'test')
    _delete_session(user_id, 'review')

    try:
        await callback.message.edit_text("🏛 Выберите факультет:", reply_markup=faculty_menu_inline())
    except:
        await callback.message.delete()
        await bot.send_message(callback.from_user.id, "🏛 Выберите факультет:", reply_markup=faculty_menu_inline())

    await callback.answer("Возвращаемся в главное меню")

# ---------------- Показ режимов ----------------
async def show_subject_modes(callback_or_message, subject, fac_key, course_num):
    user_id = callback_or_message.from_user.id if isinstance(callback_or_message, CallbackQuery) else callback_or_message.from_user.id
    has_acc = has_access(user_id, subject)
    markup = mode_inline(subject, fac_key, course_num, has_acc=has_acc)

    # Найдём красивое название предмета
    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    text = f"Вы выбрали предмет: *{subj_name}*.\nВыберите режим, чтобы начать обучение:"
    if isinstance(callback_or_message, CallbackQuery):
        try:
            await callback_or_message.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            await callback_or_message.answer("Режимы доступны.", show_alert=True)
    elif isinstance(callback_or_message, Message):
        await callback_or_message.answer(text, parse_mode="Markdown", reply_markup=markup)

# ---------------- Админ команды ----------------
ADMIN_ID = 1427715527  # главный админ (для обратной совместимости)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚙️ Открыть админ панель",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin")
        )]
    ])
    await message.answer("⚙️ *Админ панель*\n\nРедактирование вопросов базы данных.", parse_mode="Markdown", reply_markup=markup)

@dp.message(Command("setpromo"))
async def set_promo_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚙️ Использование: `/setpromo <текст акции>`\nПример: `/setpromo Скидка 50% на все!`", parse_mode="Markdown")
        return
    promo_text = parts[1]
    save_promo(promo_text)
    await message.answer("✅ Текст акций успешно обновлён! Можно проверить в разделе '🎁 Акции'.")

@dp.message(Command("delpromo"))
async def del_promo_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    save_promo("")
    await message.answer("✅ Раздел акций очищен.")

@dp.message(Command("grant"))
async def grant_access(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    try:
        _, user_id_str, subject = message.text.split()
        user_id = int(user_id_str)
    except ValueError:
        await message.answer(
            "⚙️ Использование: `/grant <user_id> <subject>`\nПример: `/grant 123456789 surgery5`",
            parse_mode="Markdown"
        )
        return

    # Валидация предмета
    if subject not in ALL_SUBJECT_KEYS:
        subjects_list = "\n".join(f"• `{k}`" for k in sorted(ALL_SUBJECT_KEYS))
        await message.answer(
            f"❌ Предмет `{subject}` не найден\\!\n\n"
            f"Доступные предметы:\n{subjects_list}",
            parse_mode="MarkdownV2"
        )
        return

    grant_access_db(user_id, subject)
    print(f"[GRANT] user_id={user_id}, subject={subject}")

    # Найдём красивое название предмета
    subj_name = subject
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    await message.answer(
        f"✅ Доступ к *{subj_name}* выдан пользователю `{user_id}` навсегда\\.",
        parse_mode="MarkdownV2"
    )
    try:
        continue_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Начать тесты", callback_data="show_faculties")]
            ]
        )
        await bot.send_message(
            user_id,
            f"🎉 Вам открыт доступ к тестам по *{subj_name}*\\!\n\n"
            f"Теперь вы можете проходить тесты и экзамены без ограничений\\!",
            parse_mode="MarkdownV2",
            reply_markup=continue_markup
        )
    except:
        await message.answer("⚠️ Не удалось уведомить пользователя — он не писал боту.")

@dp.message(Command("revoke"))
async def revoke_access(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    try:
        _, user_id_str, subject = message.text.split()
        user_id = int(user_id_str)
    except ValueError:
        await message.answer("⚙️ Использование: `/revoke <user_id> <subject>`", parse_mode="Markdown")
        return

    if has_access(user_id, subject):
        revoke_access_db(user_id, subject)
        await message.answer(f"✅ Доступ к *{subject.capitalize()}* у пользователя `{user_id}` отменён.", parse_mode="Markdown")
        try:
            await bot.send_message(user_id, f"❌ Ваш доступ к *{subject.capitalize()}* был отменён.", parse_mode="Markdown")
        except:
            pass
    else:
        await message.answer(f"❌ У пользователя нет доступа к *{subject.capitalize()}*.", parse_mode="Markdown")

@dp.message(F.photo, F.from_user.id.in_(ADMIN_IDS))
async def get_photo(message: Message):
    file_id = message.photo[-1].file_id
    await message.answer(f"ID фото:\n`{file_id}`", parse_mode="Markdown")

SUBJECT_PRICE = 300  # стоимость предмета в сомах

# ---------------- Страница покупки ----------------
@dp.callback_query(lambda c: c.data.startswith("buy_access_"))
async def show_purchase_page(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id
    user = callback.from_user
    sender = f"@{user.username}" if user.username else user.full_name

    # Найдём красивое название предмета
    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    # Проверяем баланс баллов и лимит по уровню
    balance = get_points_balance(user_id)
    reserved = get_reserved_points(user_id)
    available_points = balance - reserved
    stats = get_referral_stats(user_id)
    spend_limit = stats["spend_limit"]
    points_to_use = min(available_points, spend_limit)
    cash_to_pay = max(0, SUBJECT_PRICE - points_to_use)

    buttons = [
        [InlineKeyboardButton(text="✅ Я оплатил (без баллов)", callback_data=f"qr_paid_{subject}_forever")],
    ]
    if points_to_use > 0:
        buttons.insert(0, [InlineKeyboardButton(
            text=f"💎 Оплатить баллами ({points_to_use} б. + {cash_to_pay} сом)",
            callback_data=f"pay_points_{subject}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_menu")])

    points_info = ""
    if available_points > 0:
        points_info = (
            f"\n💎 У вас {available_points} баллов (= {available_points} сом)\n"
            f"Можно списать до {spend_limit} баллов ({stats['level_name']}).\n"
        )

    await callback.answer()

    # Отправляем QR код пользователю
    try:
        await send_qr_photo(
            chat_id=callback.message.chat.id,
            caption=(
                f"💳 Покупка доступа к {subj_name}\n\n"
                f"Стоимость доступа: {SUBJECT_PRICE} сом навсегда\n"
                f"{points_info}\n"
                f"Оплатите по QR-коду и нажмите «Я оплатил».\n"
                f"После проверки доступ откроем вручную.\n\n"
                f"По вопросам: @Ameba_admin"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        print(f"[ERROR] send_qr_photo failed: {e}")
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text=(
                f"💳 Покупка доступа к {subj_name}\n\n"
                f"Стоимость доступа: {SUBJECT_PRICE} сом навсегда\n"
                f"{points_info}\n"
                f"Для оплаты напишите @Ameba_admin\n\n"
                f"Оплатите и нажмите «Я оплатил»."
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    # Уведомляем суперадминов при показе QR
    for admin_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📲 *Запрос на покупку QR*\n\n"
                f"👤 {sender} \\(id: `{user_id}`\\)\n"
                f"📚 Предмет: *{subj_name}*\n\n"
                f"Пользователь открыл QR\\-код для оплаты\\.",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Выдать доступ",
                        callback_data=f"admin_grant_{user_id}_{subject}"
                    )]
                ])
            )
        except Exception:
            pass

    await callback.answer()


# ---------------- Оплата баллами ----------------
@dp.callback_query(lambda c: c.data and c.data.startswith("pay_points_"))
async def pay_with_points(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id
    user = callback.from_user
    sender = f"@{user.username}" if user.username else user.full_name

    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    # Считаем сколько баллов списать (с учётом лимита уровня)
    balance = get_points_balance(user_id)
    reserved = get_reserved_points(user_id)
    available_points = balance - reserved

    if available_points <= 0:
        await callback.answer("У вас нет доступных баллов!", show_alert=True)
        return

    stats = get_referral_stats(user_id)
    spend_limit = stats["spend_limit"]
    points_to_use = min(available_points, spend_limit)
    cash_to_pay = max(0, SUBJECT_PRICE - points_to_use)

    # Резервируем баллы
    conn = db_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO points_reserved (user_id, subject, points, status) VALUES (?,?,?,'pending')",
        (user_id, subject, points_to_use)
    )
    reservation_id = c.lastrowid
    conn.commit()
    conn.close()

    # Уведомляем пользователя
    if cash_to_pay > 0:
        pay_note = f"Оплатите оставшиеся {cash_to_pay} сом по QR-коду и отправьте квитанцию."
    else:
        pay_note = "Оплата полностью баллами — квитанция не нужна."

    await callback.message.answer(
        f"💎 Запрос на оплату баллами отправлен!\n\n"
        f"Предмет: {subj_name}\n"
        f"Спишется баллов: {points_to_use} (= {points_to_use} сом скидки)\n"
        f"Доплатить сомами: {cash_to_pay} сом\n\n"
        f"{pay_note}\n\n"
        f"⏳ {points_to_use} баллов зарезервированы до подтверждения администратором."
    )

    # Уведомляем суперадминов
    for admin_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💎 Запрос на покупку с баллами\n\n"
                f"👤 {sender} (id: {user_id})\n"
                f"📚 Предмет: {subj_name}\n"
                f"💎 Спишется баллов: {points_to_use} (= {points_to_use} сом скидки)\n"
                f"💵 Доплата сомами: {cash_to_pay} сом",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Подтвердить и выдать доступ",
                        callback_data=f"admin_grant_points_{user_id}_{subject}_{reservation_id}"
                    )],
                    [InlineKeyboardButton(
                        text="❌ Отклонить (вернуть баллы)",
                        callback_data=f"admin_cancel_points_{user_id}_{subject}_{reservation_id}"
                    )]
                ])
            )
        except Exception:
            pass

    await callback.answer()


# Подтверждение покупки с баллами
@dp.callback_query(lambda c: c.data and c.data.startswith("admin_grant_points_"))
async def admin_grant_with_points(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    # admin_grant_points_{user_id}_{subject}_{reservation_id}
    parts = callback.data.split("_")
    # ["admin","grant","points",user_id,subject,reservation_id]
    target_user_id = int(parts[3])
    subject = parts[4]
    reservation_id = int(parts[5])

    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    # Получаем сколько баллов зарезервировано
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT points, status FROM points_reserved WHERE id=?", (reservation_id,))
    row = c.fetchone()
    conn.close()

    if not row or row[1] != "pending":
        await callback.answer("Резерв не найден или уже обработан!", show_alert=True)
        return

    points_to_deduct = row[0]

    # Списываем баллы и закрываем резерв
    conn = db_conn()
    c = conn.cursor()
    c.execute("UPDATE points_reserved SET status='confirmed' WHERE id=?", (reservation_id,))
    conn.commit()
    conn.close()

    add_points(target_user_id, -points_to_deduct, "spend", subject=subject)

    # Выдаём доступ
    grant_access_db(target_user_id, subject)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Доступ к *{subj_name}* выдан\\. Списано *{points_to_deduct} баллов*\\.",
        parse_mode="MarkdownV2"
    )

    # Начисляем бонусные +40 за покупку и рефереру
    add_points(target_user_id, POINTS_OWN_PURCHASE, "own_purchase", subject=subject)
    referrer_id = get_referrer_id(target_user_id)
    if referrer_id:
        conn = db_conn()
        c = conn.cursor()
        c.execute(
            "SELECT purchase_bonus_paid FROM referrals WHERE referrer_id=? AND referee_id=?",
            (referrer_id, target_user_id)
        )
        ref_row = c.fetchone()
        c.execute("SELECT referral_count FROM users WHERE user_id=?", (referrer_id,))
        rc_row = c.fetchone()
        ref_count = rc_row[0] if rc_row else 0
        conn.close()

        if ref_row and ref_row[0] == 0:
            _, referrer_bonus, _ = get_referral_level(ref_count)
            add_points(referrer_id, referrer_bonus, "referral_purchase",
                       related_user_id=target_user_id, subject=subject)
            conn = db_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET referral_count=referral_count+1 WHERE user_id=?", (referrer_id,))
            c.execute("UPDATE referrals SET purchase_bonus_paid=1 WHERE referrer_id=? AND referee_id=?",
                      (referrer_id, target_user_id))
            conn.commit()
            conn.close()
            # Проверяем повышение уровня
            _, new_bonus, new_limit = get_referral_level(ref_count + 1)
            old_name, _, _ = get_referral_level(ref_count)
            new_name, _, _ = get_referral_level(ref_count + 1)
            level_up_text = ""
            if new_name != old_name:
                level_up_text = f"\n\n🎊 Поздравляем! Новый уровень: {new_name}\nЛимит списания: {new_limit} баллов"
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 Ваш реферал купил предмет {subj_name}!\n"
                    f"Вам начислено +{referrer_bonus} баллов.{level_up_text}"
                )
            except Exception:
                pass

    try:
        await bot.send_message(
            target_user_id,
            f"🎉 Вам открыт доступ к {subj_name}!\n\n"
            f"Списано: {points_to_deduct} баллов\n"
            f"Начислено за покупку: +{POINTS_OWN_PURCHASE} баллов\n\n"
            f"Нажми «💎 Мой баланс» чтобы проверить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Начать тесты", callback_data="show_faculties")]
            ])
        )
    except Exception:
        pass
    await callback.answer("✅ Доступ выдан, баллы списаны!")


# Отклонение покупки с баллами — возврат баллов
@dp.callback_query(lambda c: c.data and c.data.startswith("admin_cancel_points_"))
async def admin_cancel_points(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return

    parts = callback.data.split("_")
    # ["admin","cancel","points",user_id,subject,reservation_id]
    target_user_id = int(parts[3])
    subject = parts[4]
    reservation_id = int(parts[5])

    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    # Отменяем резерв
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT points, status FROM points_reserved WHERE id=?", (reservation_id,))
    row = c.fetchone()
    conn.close()

    if not row or row[1] != "pending":
        await callback.answer("Резерв уже обработан!", show_alert=True)
        return

    conn = db_conn()
    c = conn.cursor()
    c.execute("UPDATE points_reserved SET status='cancelled' WHERE id=?", (reservation_id,))
    conn.commit()
    conn.close()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"❌ Покупка *{subj_name}* отклонена\\. Баллы возвращены пользователю `{target_user_id}`\\.",
        parse_mode="MarkdownV2"
    )

    try:
        await bot.send_message(
            target_user_id,
            f"❌ Ваш запрос на покупку *{subj_name}* отклонён администратором\\.\n"
            f"Зарезервированные баллы возвращены\\.\n\n"
            f"По вопросам: @Ameba\\_admin",
            parse_mode="MarkdownV2"
        )
    except Exception:
        pass
    await callback.answer("❌ Покупка отклонена, баллы разморожены.")

# Выдача доступа прямо из уведомления админу
@dp.callback_query(lambda c: c.data and c.data.startswith("admin_grant_"))
async def admin_grant_from_notification(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    parts = callback.data.split("_", 3)
    # admin_grant_{user_id}_{subject}
    target_user_id = int(parts[2])
    subject = parts[3]

    subj_name = subject.capitalize()
    for fac in FACULTIES.values():
        for subj_list in fac["subjects"].values():
            for s in subj_list:
                if s["key"] == subject:
                    subj_name = s["name"]

    grant_access_db(target_user_id, subject)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Доступ к *{subj_name}* выдан пользователю `{target_user_id}`\\.",
        parse_mode="MarkdownV2"
    )

    # ── БАЛЛЫ за покупку ──
    # +40 баллов покупателю
    add_points(target_user_id, POINTS_OWN_PURCHASE, "own_purchase", subject=subject)

    # Проверяем реферера
    referrer_id = get_referrer_id(target_user_id)
    if referrer_id:
        conn = db_conn()
        c = conn.cursor()
        c.execute(
            "SELECT purchase_bonus_paid FROM referrals WHERE referrer_id=? AND referee_id=?",
            (referrer_id, target_user_id)
        )
        ref_row = c.fetchone()
        c.execute("SELECT referral_count FROM users WHERE user_id=?", (referrer_id,))
        rc_row = c.fetchone()
        ref_count = rc_row[0] if rc_row else 0
        conn.close()

        if ref_row and ref_row[0] == 0:
            old_name, _, _ = get_referral_level(ref_count)
            _, referrer_bonus, _ = get_referral_level(ref_count)
            add_points(referrer_id, referrer_bonus, "referral_purchase",
                       related_user_id=target_user_id, subject=subject)
            conn = db_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (referrer_id,))
            c.execute("UPDATE referrals SET purchase_bonus_paid=1 WHERE referrer_id=? AND referee_id=?",
                      (referrer_id, target_user_id))
            conn.commit()
            conn.close()

            new_name, _, new_limit = get_referral_level(ref_count + 1)
            level_up_text = ""
            if new_name != old_name:
                level_up_text = f"\n\n🎊 Поздравляем! Новый уровень: {new_name}\nЛимит списания: {new_limit} баллов"
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 Ваш реферал купил предмет {subj_name}!\n"
                    f"Вам начислено +{referrer_bonus} баллов.{level_up_text}"
                )
            except Exception:
                pass

    # Уведомляем покупателя
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 Вам открыт доступ к {subj_name}!\n\n"
            f"Теперь вы можете проходить тесты и экзамены без ограничений!\n\n"
            f"💎 За покупку вам начислено +{POINTS_OWN_PURCHASE} баллов!\n"
            f"Нажми «💎 Мой баланс» чтобы проверить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Начать тесты", callback_data="show_faculties")]
            ])
        )
    except Exception:
        pass
    await callback.answer("✅ Доступ выдан!")

# ---------------- Оплата ----------------
@dp.callback_query(lambda c: c.data.startswith("qr_paid_"))
async def qr_payment_confirm(callback: CallbackQuery):
    parts = callback.data.split("_")
    subject = parts[2]
    period = parts[3]
    user_id = callback.from_user.id
    await callback.message.answer(
        f"✅ Вы выбрали оплату доступа к *{subject.capitalize()}* ({period}).\n"
        f"Пожалуйста, оплатите по QR-коду и отправьте квитанцию в чат.\n"
        f"После проверки доступ будет открыт вручную.",
        parse_mode="Markdown"
    )
    await bot.send_message(
        CODER_CHAT_ID,
        f"💳 Новый запрос: {callback.from_user.full_name} (id: `{user_id}`)\n"
        f"Предмет: *{subject}*\nПериод: *{period}*",
        parse_mode="Markdown"
    )
    await callback.answer("Ожидайте подтверждения администратора.")

@dp.message(F.content_type.in_({"document", "photo"}))
async def handle_payment_receipt(message: Message):
    user_id = message.from_user.id
    sender = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    if message.document:
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_document(admin_id, message.document.file_id, caption=f"💳 Квитанция от {sender} (id:{user_id})")
            except Exception:
                pass
        await message.answer("✅ Квитанция отправлена администратору.")
    elif message.photo:
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=f"💳 Квитанция от {sender} (id:{user_id})")
            except Exception:
                pass
        await message.answer("✅ Квитанция отправлена администратору.")

# ---------------- Режимы ----------------
@dp.callback_query(lambda c: c.data and (c.data.startswith("mode_exam_") or c.data.startswith("mode_tests_")))
async def check_access_and_route(callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    mode = parts[1]
    subject = parts[2]

    # Экзамен — только с оплатой
    if mode == "exam":
        if not has_access(user_id, subject):
            await callback.message.edit_text(
                f"❌ Режим экзамена доступен только после оплаты.\n\n"
                f"Купите доступ к *{subject.capitalize()}*, чтобы проходить симуляцию экзамена.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Купить доступ", callback_data=f"buy_access_{subject}")],
                        [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_menu")]
                    ]
                )
            )
            await callback.answer("Экзамен доступен после оплаты!")
            return
        await mode_exam_real(callback)

    # Тесты — пробный доступ (5 вопросов) или полный доступ
    elif mode == "tests":
        if has_access(user_id, subject):
            # Полный доступ
            await mode_tests_real(callback)
        else:
            # Проверяем пробный лимит
            trials = load_trials()
            user_trials = trials.get(user_id, {}).get(subject, 0)
            if user_trials >= 5:
                await callback.message.edit_text(
                    f"⛔ Вы уже использовали 5 пробных вопросов по *{subject.capitalize()}*.\n\n"
                    f"Купите доступ, чтобы продолжить обучение.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="💳 Купить доступ", callback_data=f"buy_access_{subject}")],
                            [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_menu")]
                        ]
                    )
                )
                await callback.answer("Пробный период закончился!")
                return
            # Разрешаем пробный доступ
            remaining = 5 - user_trials
            await callback.message.answer(
                f"🎁 *Пробный режим*\n\nУ вас осталось {remaining} бесплатных вопросов.",
                parse_mode="Markdown"
            )
            await mode_tests_real(callback)

# ---------------- Экзамен ----------------
async def mode_exam_real(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id
    print(f"[mode_exam_real] subject={subject}, user_id={user_id}")

    # Показываем подтверждение перед началом экзамена
    confirmation_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, готов начать!", callback_data=f"confirm_exam_{subject}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
        ]
    )

    await callback.message.edit_text(
        f"📝 *Симуляция экзамена по {subject.capitalize()}*\n\n"
        f"Вы готовы начать экзамен?\n\n"
        f"• Количество вопросов: 50\n"
        f"• За каждый правильный ответ: 2 балла\n"
        f"• Вы можете вернуться в меню в любой момент",
        parse_mode="Markdown",
        reply_markup=confirmation_markup
    )
    await callback.answer()

# Обработчик подтверждения начала экзамена
@dp.callback_query(lambda c: c.data.startswith("confirm_exam_"))
async def confirm_exam_start(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id
    print(f"[confirm_exam_start] subject={subject}, user_id={user_id}")

    questions = get_questions(subject, 50)
    print(f"[confirm_exam_start] questions count: {len(questions)}")

    if not questions:
        await callback.message.answer("❌ В базе нет вопросов.")
        await callback.answer()
        return

    # Гарантируем уникальность вопросов внутри одной симуляции по ID
    seen_ids = set()
    unique_questions = []
    for q in questions:
        if q[0] not in seen_ids:
            seen_ids.add(q[0])
            unique_questions.append(q)
    questions = unique_questions
    # Перемешиваем ещё раз для надёжности
    random.shuffle(questions)

    # Логируем запуск экзамена
    log_exam_start(user_id, subject)

    # Сохраняем все вопросы экзамена в историю
    save_questions_to_history(user_id, subject, [q[0] for q in questions])

    _save_session(user_id, 'exam', {
        "subject": subject,
        "questions": [list(q) for q in questions],
        "current": 0,
        "score": 0,
        "active": True,
        "start_time": datetime.now().isoformat(),
        "answers": []
    })
    await callback.message.edit_text(f"📝 Начинаем экзамен по {subject.capitalize()}!\n⏱ У вас есть 1 час 15 минут.")
    await send_exam_question(callback.message, user_id)
    await callback.answer()

async def send_exam_question(message, user_id):
    session = _load_session(user_id, 'exam')
    if not session or not session["active"]:
        return

    # Проверяем, не истекло ли время
    start_time = datetime.fromisoformat(session["start_time"]) if isinstance(session["start_time"], str) else session["start_time"]
    minutes, seconds, is_expired = get_time_remaining(start_time)
    if is_expired:
        await message.answer("⏰ Время экзамена истекло!")
        await finish_exam(message, user_id, time_expired=True)
        return

    if session["current"] >= len(session["questions"]):
        await finish_exam(message, user_id)
        return

    q = session["questions"][session["current"]]
    markup = question_to_inline(q, mode="exam")
    session["current_q_id"] = q[0]
    _save_session(user_id, 'exam', session)

    # Форматируем текст вопроса с вариантами ответов и таймером
    time_str = format_time_remaining(minutes, seconds)
    question_text = f"{time_str}\n\n{format_question_text(q, session['current'] + 1, len(session['questions']))}"
    await message.answer(question_text, reply_markup=markup)

async def finish_exam(message, user_id, time_expired=False):
    session = _load_session(user_id, 'exam')
    if not session:
        return
    session["active"] = False
    score = session["score"]
    questions_count = len(session["questions"])
    answered_count = session["current"]
    answers = session.get("answers", [])

    # Считаем ошибки
    errors_count = sum(1 for a in answers if not a["is_correct"])
    correct_count = sum(1 for a in answers if a["is_correct"])

    if time_expired:
        result_text = (
            f"⏰ *Время экзамена истекло!*\n\n"
            f"📊 Ваш результат:\n"
            f"• Отвечено вопросов: {answered_count} из {questions_count}\n"
            f"• Набрано баллов: {score} из {questions_count*2}\n"
            f"• Процент: {(score / (questions_count*2) * 100):.1f}%\n"
            f"• ✅ Правильных: {correct_count}  ❌ Ошибок: {errors_count}"
        )
    else:
        result_text = (
            f"📊 *Экзамен завершён!*\n\n"
            f"Ваш результат:\n"
            f"• Отвечено вопросов: {answered_count} из {questions_count}\n"
            f"• Набрано баллов: {score} из {questions_count*2}\n"
            f"• Процент: {(score / (questions_count*2) * 100):.1f}%\n"
            f"• ✅ Правильных: {correct_count}  ❌ Ошибок: {errors_count}"
        )

    # Сохраняем результаты для работы над ошибками
    if answers:
        _save_session(user_id, 'review', {
            "subject": session["subject"],
            "answers": answers,
            "current": 0
        })

    # Кнопки после экзамена
    result_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Работа над ошибками", callback_data="review_start")],
            [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_menu")]
        ]
    )

    await message.answer(result_text, parse_mode="Markdown", reply_markup=result_markup)
    _delete_session(user_id, 'exam')

# ---------------- Тесты ----------------
async def mode_tests_real(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    # Показываем подтверждение перед началом тестов
    confirmation_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, начать решать!", callback_data=f"confirm_tests_{subject}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
        ]
    )

    await callback.message.edit_text(
        f"📖 *Решение тестов по {subject.capitalize()}*\n\n"
        f"Вы готовы начать решать тесты?\n\n"
        f"• Вопросы будут показываться по одному\n"
        f"• После ответа вы увидите правильный ответ и объяснение\n"
        f"• Вы можете вернуться в меню в любой момент",
        parse_mode="Markdown",
        reply_markup=confirmation_markup
    )
    await callback.answer()

# Обработчик подтверждения начала тестов
@dp.callback_query(lambda c: c.data.startswith("confirm_tests_"))
async def confirm_tests_start(callback: CallbackQuery):
    subject = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    # Получаем последние 100 показанных вопросов для исключения повторов
    recent_ids = set(get_recent_question_ids(user_id, subject, 100))
    questions = get_questions_excluding(subject, recent_ids, 1)
    if not questions:
        await callback.message.answer("❌ В базе нет вопросов.")
        await callback.answer()
        return

    q = questions[0]
    # Сохраняем вопрос в историю
    save_question_to_history(user_id, subject, q[0])

    _save_session(user_id, 'test', {"subject": subject, "question": list(q), "active": True})
    markup = question_to_inline(q, mode="test")

    # Форматируем текст вопроса с вариантами ответов
    question_text = f"📖 Тест по {subject.capitalize()}\n\n{format_question_text(q)}"
    await callback.message.edit_text(question_text, reply_markup=markup)
    await callback.answer()

# ---------------- Поддержка ----------------
@dp.callback_query(F.data == "support")
async def support_info(callback: CallbackQuery):
    text = "📩 Поддержка: напишите сообщение разработчику."
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Написать сообщение", callback_data="send_feedback")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_menu")]
        ]
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "send_feedback")
async def ask_for_feedback(callback: CallbackQuery):
    user_id = callback.from_user.id
    feedback_waiting.add(user_id)
    await callback.message.edit_text("✏️ Напишите сообщение для разработчика.")
    await callback.answer("Ожидаю ваше сообщение...")

# ---------------- Статистика ----------------
def get_stats() -> dict:
    conn = db_conn()
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

    # Топ-5 предметов по количеству ответов
    c.execute("""
        SELECT subject, COUNT(*) as cnt
        FROM question_history
        GROUP BY subject
        ORDER BY cnt DESC
        LIMIT 5
    """)
    top_subjects = c.fetchall()

    # Всего покупок (уникальных доступов)
    c.execute("SELECT COUNT(*) FROM purchases")
    total_purchases = c.fetchone()[0]

    # Всего вопросов в базе
    c.execute("SELECT COUNT(*) FROM questions")
    total_questions = c.fetchone()[0]

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
        SELECT r.referrer_id, u.username, u.full_name, COUNT(*) as cnt
        FROM referrals r
        LEFT JOIN users u ON u.user_id = r.referrer_id
        GROUP BY r.referrer_id
        ORDER BY cnt DESC
        LIMIT 5
    """)
    top_referrers = c.fetchall()

    conn.close()
    return {
        "total_users": total_users,
        "total_answers": total_answers,
        "top_subjects": top_subjects,
        "total_purchases": total_purchases,
        "total_questions": total_questions,
        "total_exams": total_exams,
        "total_referrals": total_referrals,
        "total_referrers": total_referrers,
        "referral_purchases": referral_purchases,
        "top_referrers": top_referrers,
    }

# Красивые названия предметов для статистики
SUBJECT_NAMES = {
    subj["key"]: subj["name"]
    for fac in FACULTIES.values()
    for subjects in fac["subjects"].values()
    for subj in subjects
}

@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return

    s = get_stats()

    top_lines = ""
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (subj, cnt) in enumerate(s["top_subjects"]):
        name = SUBJECT_NAMES.get(subj, subj.capitalize())
        top_lines += f"{medals[i]} {name} — {cnt:,} ответов\n"

    ref_lines = ""
    for i, (uid, uname, fname, cnt) in enumerate(s["top_referrers"]):
        label = f"@{uname}" if uname else (fname or str(uid))
        ref_lines += f"{medals[i]} {label} — {cnt} чел.\n"

    text = (
        f"📊 Статистика AMEBA\n\n"
        f"👥 Пользователей: {s['total_users']:,}\n"
        f"💳 Выдано доступов: {s['total_purchases']:,}\n"
        f"📝 Всего ответов: {s['total_answers']:,}\n"
        f"🎓 Симуляций экзамена: {s['total_exams']:,}\n"
        f"🗂 Вопросов в базе: {s['total_questions']:,}\n\n"
        f"🔥 Топ-5 предметов:\n{top_lines}\n"
        f"👥 Рефералки:\n"
        f"• Всего переходов: {s['total_referrals']}\n"
        f"• Активных рефереров: {s['total_referrers']}\n"
        f"• Покупок через рефералку: {s['referral_purchases']}\n\n"
        f"🏆 Топ рефереры:\n{ref_lines}"
    )
    await message.answer(text)


# ---------------- /ref — реферальная ссылка ----------------
@dp.message(Command("ref"))
async def ref_cmd(message: Message):
    try:
        user_id = message.from_user.id
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        stats = get_referral_stats(user_id)

        next_info = stats["next_level_info"]
        if next_info:
            next_text = (
                f"\n📈 Осталось {next_info[0]} покупок рефералов до {next_info[1]}\n"
                f"   бонус вырастет до +{next_info[2]}, лимит до {next_info[3]} баллов"
            )
        else:
            next_text = "\n🏆 Вы на максимальном уровне!"

        text = (
            f"👥 Ваша реферальная программа\n\n"
            f"🔗 Ваша ссылка:\n{ref_link}\n\n"
            f"📊 Статистика:\n"
            f"• Приглашено всего: {stats['total_invited']} чел.\n"
            f"• Из них купили: {stats['referral_count']} чел.\n\n"
            f"🎖 Уровень: {stats['level_name']}\n"
            f"💰 Бонус за покупку реферала: +{stats['bonus_per_purchase']} баллов\n"
            f"🔒 Ваш лимит скидки: {stats['spend_limit']} баллов"
            f"{next_text}\n\n"
            f"💎 Ваш баланс: {stats['points_balance']} баллов\n\n"
            f"За переход по вашей ссылке: +{POINTS_REF_JOIN} баллов вам\n"
            f"За реферала купившего предмет: +{stats['bonus_per_purchase']} баллов вам"
        )
        await message.answer(text)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ---------------- /balance — баланс баллов ----------------
@dp.message(Command("balance"))
async def balance_cmd(message: Message):
    try:
        user_id = message.from_user.id
        balance = get_points_balance(user_id)
        reserved = get_reserved_points(user_id)
        available = balance - reserved
        stats = get_referral_stats(user_id)

        # Последние 5 начислений
        conn = db_conn()
        c = conn.cursor()
        c.execute(
            "SELECT delta, reason, subject, created_at FROM points_log "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        history = c.fetchall()
        conn.close()

        reason_names = {
            "referral_trial":    "Реферал прорешал вопросы",
            "referral_purchase": "Реферал купил предмет",
            "own_trial":         "Прорешал бесплатные вопросы",
            "own_purchase":      "Покупка предмета",
            "spend":             "Оплата баллами",
        }

        history_text = ""
        for delta, reason, subject, created_at in history:
            sign = "+" if delta > 0 else ""
            subj = f" ({subject})" if subject else ""
            reason_str = reason_names.get(reason, reason)
            date_str = created_at[:10] if created_at else ""
            history_text += f"  {sign}{delta} — {reason_str}{subj} [{date_str}]\n"

        if not history_text:
            history_text = "  Пока нет операций\n"

        # Прогресс до следующего уровня
        next_info = stats["next_level_info"]
        if next_info:
            level_text = (
                f"🎖 Уровень: {stats['level_name']}\n"
                f"📈 До следующего уровня: {next_info[0]} покупок рефералов"
            )
        else:
            level_text = f"🎖 Уровень: {stats['level_name']} 🏆"

        spend_limit = stats["spend_limit"]
        text = (
            f"💎 Ваш баланс баллов\n\n"
            f"💰 Всего баллов: {balance}\n"
            f"✅ Доступно: {available} (= {available} сом скидки)\n"
            f"⏳ Зарезервировано: {reserved}\n\n"
            f"{level_text}\n"
            f"🔒 Лимит списания за покупку: {spend_limit} баллов\n\n"
            f"📋 Последние операции:\n{history_text}\n"
            f"ℹ️ Повышай уровень — увеличивай лимит скидки!"
        )
        await message.answer(text)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ---------------- Команды рассылки (только суперадмины) ----------------
@dp.message(Command("message"))
async def message_to_user_cmd(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "⚙️ Использование: `/message <user_id>`\nПример: `/message 123456789`\n\nПосле этого напишите сообщение.",
            parse_mode="Markdown"
        )
        return
    target_id = int(parts[1].strip())
    message_waiting[message.from_user.id] = target_id
    await message.answer(
        f"✏️ Напишите сообщение для пользователя `{target_id}`.\nСледующее ваше сообщение будет отправлено ему.",
        parse_mode="Markdown"
    )


@dp.message(Command("allmessage"))
async def allmessage_cmd(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды.")
        return
    message_waiting[message.from_user.id] = "all"
    total = len(get_all_user_ids())
    await message.answer(
        f"📢 Рассылка всем пользователям.\n\n"
        f"👥 Будет отправлено: ~{total} пользователям\n\n"
        f"✏️ Напишите сообщение для рассылки.\nСледующее ваше сообщение будет отправлено всем.",
        parse_mode="Markdown"
    )


@dp.message(F.text)
async def receive_feedback_text(message: Message):
    user_id = message.from_user.id
    text = message.text

    # --- Кнопки главного меню ---
    if text == "📚 Выбрать предмет":
        await message.answer("🏛 Выберите факультет:", reply_markup=faculty_menu_inline())
        return
    if text == "💡 Как заработать баллы":
        promo_text = load_promo()

        info_text = (
            "💎 Как заработать и потратить баллы\n\n"
            "🎯 За себя:\n"
            f"• Зарегистрировался в боте → +{POINTS_REGISTRATION} баллов\n"
            f"• Купил предмет → +{POINTS_OWN_PURCHASE} баллов\n\n"
            "👥 За рефералов (по твоей ссылке):\n"
            f"• Друг запустил бота → +{POINTS_REF_JOIN} баллов тебе\n"
            f"• Друг прошёл 5 вопросов → +{POINTS_REF_TRIAL_SELF} баллов ему\n"
            "• Друг купил предмет → +30/40/50 тебе (по уровню)\n\n"
            "🏆 Уровни:\n"
            "🟢 Новичок (0–9 покупок) → +30, лимит 100 сом\n"
            "🔵 Продвинутый (10–19) → +40, лимит 200 сом\n"
            "🟣 Мессия (20+) → +50, лимит 300 сом\n\n"
            "💰 Трата баллов:\n"
            "1 балл = 1 сом скидки при покупке предмета.\n"
            "Лимит зависит от уровня (100/200/300 сом).\n\n"
            "🔗 Твоя реферальная ссылка — в разделе\n«👥 Реферальная программа»"
        )

        if promo_text:
            info_text += f"\n\n{'—' * 20}\n\n{promo_text}"

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Мои баллы и ссылка", callback_data="show_ref")],
        ])
        await message.answer(info_text, reply_markup=markup)
        return
    if text == "💎 Баллы и рефералка":
        try:
            bot_info = await bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
            stats = get_referral_stats(user_id)
            balance = get_points_balance(user_id)
            reserved = get_reserved_points(user_id)
            available = balance - reserved
            spend_limit = stats["spend_limit"]

            # Уровень и прогресс
            next_info = stats["next_level_info"]
            if next_info:
                level_text = (
                    f"🎖 Уровень: {stats['level_name']}\n"
                    f"📈 Осталось {next_info[0]} покупок до {next_info[1]}\n"
                    f"   (бонус +{next_info[2]}, лимит {next_info[3]} сом)"
                )
            else:
                level_text = f"🎖 Уровень: {stats['level_name']} 🏆"

            # История операций
            conn = db_conn()
            c = conn.cursor()
            c.execute(
                "SELECT delta, reason, subject, created_at FROM points_log "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
                (user_id,)
            )
            history = c.fetchall()
            conn.close()
            reason_names = {
                "registration":      "Регистрация",
                "referral_join":     "Переход по вашей ссылке",
                "own_trial":         "Прорешал бесплатные вопросы",
                "referral_purchase": "Реферал купил предмет",
                "own_purchase":      "Покупка предмета",
                "spend":             "Оплата баллами",
            }
            history_text = ""
            for delta, reason, subject, created_at in history:
                sign = "+" if delta > 0 else ""
                subj = f" ({subject})" if subject else ""
                reason_str = reason_names.get(reason, reason)
                date_str = created_at[:10] if created_at else ""
                history_text += f"  {sign}{delta} — {reason_str}{subj} [{date_str}]\n"
            if not history_text:
                history_text = "  Пока нет операций\n"

            reply = (
                f"💎 Баллы и реферальная программа\n\n"
                f"━━━ Баланс ━━━\n"
                f"💰 Всего: {balance} баллов\n"
                f"✅ Доступно: {available} (= {available} сом скидки)\n"
                f"⏳ Зарезервировано: {reserved}\n"
                f"🔒 Лимит скидки за покупку: {spend_limit} сом\n\n"
                f"━━━ Уровень ━━━\n"
                f"{level_text}\n\n"
                f"━━━ Рефералка ━━━\n"
                f"🔗 Ваша ссылка:\n{ref_link}\n\n"
                f"• Приглашено: {stats['total_invited']} чел.\n"
                f"• Из них купили: {stats['referral_count']} чел.\n"
                f"• Бонус за покупку реферала: +{stats['bonus_per_purchase']} баллов\n\n"
                f"━━━ Последние операции ━━━\n"
                f"{history_text}"
            )
            await message.answer(reply)
        except Exception as e:
            await message.answer(f"Ошибка: {e}")
        return
    if text == "🆘 Поддержка":
        feedback_waiting.add(user_id)
        await message.answer("✍️ Напишите ваш вопрос или проблему, и мы ответим как можно скорее.")
        return

    if text == "📱 Открыть приложение":
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        await message.answer("Нажмите кнопку ниже:", reply_markup=markup)
        return

    # --- Суперадмин отправляет сообщение конкретному пользователю ---
    if user_id in message_waiting:
        target = message_waiting.pop(user_id)
        text_to_send = message.text

        if target == "all":
            # Рассылка всем пользователям
            all_ids = get_all_user_ids()
            sent = 0
            failed = 0
            for uid in all_ids:
                try:
                    await bot.send_message(uid, text_to_send)
                    sent += 1
                except Exception:
                    failed += 1
            await message.answer(
                f"📨 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Не доставлено: {failed}"
            )
        else:
            # Сообщение конкретному пользователю
            try:
                await bot.send_message(target, text_to_send)
                await message.answer(f"✅ Сообщение доставлено пользователю `{target}`.", parse_mode="Markdown")
            except Exception as e:
                await message.answer(f"❌ Не удалось отправить сообщение пользователю `{target}`.\nОшибка: {e}", parse_mode="Markdown")
        return

    # --- Обычная обратная связь ---
    if user_id not in feedback_waiting:
        return
    sender = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await bot.send_message(CODER_CHAT_ID, f"🆘 Сообщение от {sender} (id:{user_id}):\n\n{message.text}")
    feedback_waiting.discard(user_id)
    await message.answer("✅ Ваше сообщение отправлено.")

# ---------------- Обработка ответов ЭКЗАМЕН ----------------
@dp.callback_query(lambda c: c.data.startswith("ans_e_"))
async def handle_exam_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = _load_session(user_id, 'exam')

    if not session or not session["active"]:
        await callback.answer("Сессия устарела — начните экзамен заново.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # Проверяем, не истекло ли время
    start_time = datetime.fromisoformat(session["start_time"]) if isinstance(session["start_time"], str) else session["start_time"]
    minutes, seconds, is_expired = get_time_remaining(start_time)
    if is_expired:
        await callback.message.answer("⏰ Время экзамена истекло!")
        await finish_exam(callback.message, user_id, time_expired=True)
        await callback.answer("Время истекло!")
        return

    # ans_e_1_123 -> ["ans", "e", "1", "123"]
    parts = callback.data.split("_")
    selected = int(parts[2])
    question_id = int(parts[3])

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT correct_option, COALESCE(explanation, '') FROM questions WHERE id=?", (question_id,))
    row = cursor.fetchone()
    conn.close()

    is_correct = False
    correct_option = 0
    explanation = ""
    if row:
        correct_option = row[0]
        explanation = row[1]
        if selected == correct_option:
            is_correct = True
            session["score"] += 2

    # Сохраняем ответ для работы над ошибками
    current_question = session["questions"][session["current"]]
    session["answers"].append({
        "question": current_question,
        "selected": selected,
        "correct": correct_option,
        "is_correct": is_correct,
        "explanation": explanation
    })

    session["current"] += 1
    _save_session(user_id, 'exam', session)
    await send_exam_question(callback.message, user_id)
    await callback.answer()


# ---------------- Работа над ошибками ----------------
def format_review_question(answer_data, index, total):
    """Форматирует вопрос для режима работы над ошибками"""
    question = answer_data["question"]
    selected = answer_data["selected"]
    correct = answer_data["correct"]
    is_correct = answer_data["is_correct"]
    explanation = answer_data.get("explanation", "")

    # question[2] - текст, question[3:8] - варианты
    options = [opt for opt in question[3:8] if opt and isinstance(opt, str)]

    if is_correct:
        status = "✅ Вы ответили правильно"
    else:
        status = "❌ Вы ответили неправильно"

    text = f"📝 Вопрос {index + 1}/{total}\n"
    text += f"{status}\n\n"
    text += f"{question[2]}\n\n"

    for i, opt in enumerate(options):
        num = i + 1
        if num == correct and num == selected:
            # Правильный ответ, который выбрал пользователь
            text += f"✅ {num}. {opt}\n\n"
        elif num == correct:
            # Правильный ответ, который пользователь НЕ выбрал
            text += f"✅ {num}. {opt}  ← правильный ответ\n\n"
        elif num == selected:
            # Неправильный ответ, который выбрал пользователь
            text += f"❌ {num}. {opt}  ← ваш ответ\n\n"
        else:
            text += f"    {num}. {opt}\n\n"

    if explanation and explanation.strip():
        text += f"💡 *Объяснение:*\n{explanation}\n"

    return text.strip()

@dp.callback_query(F.data == "review_start")
async def review_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = _load_session(user_id, 'review')

    if not session or not session["answers"]:
        await callback.answer("Нет данных для работы над ошибками.", show_alert=True)
        return

    session["current"] = 0
    _save_session(user_id, 'review', session)
    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

async def send_review_question(message, user_id, edit=False):
    session = _load_session(user_id, 'review')
    if not session:
        return

    answers = session["answers"]
    current = session["current"]
    total = len(answers)

    if current < 0 or current >= total:
        return

    answer_data = answers[current]
    text = format_review_question(answer_data, current, total)

    nav_buttons = []
    if current > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="review_prev"))
    if current < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data="review_next"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except:
            await message.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(F.data == "review_next")
async def review_next(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = _load_session(user_id, 'review')
    if not session:
        await callback.answer("Сессия не найдена.", show_alert=True)
        return

    if session["current"] < len(session["answers"]) - 1:
        session["current"] += 1
    _save_session(user_id, 'review', session)

    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

@dp.callback_query(F.data == "review_prev")
async def review_prev(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = _load_session(user_id, 'review')
    if not session:
        await callback.answer("Сессия не найдена.", show_alert=True)
        return

    if session["current"] > 0:
        session["current"] -= 1
    _save_session(user_id, 'review', session)

    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

# ---------------- Обработка ответов ТЕСТЫ ----------------
@dp.callback_query(lambda c: c.data.startswith("ans_t_"))
async def handle_test_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = _load_session(user_id, 'test')

    if not session or not session["active"]:
        await callback.answer("Сессия устарела — начните тест заново.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    subject = session["subject"]

    # ---------- ПРОБНЫЙ ДОСТУП ----------
    trials = load_trials()
    if user_id not in trials:
        trials[user_id] = {}
    if subject not in trials[user_id]:
        trials[user_id][subject] = 0

    user_trials = trials[user_id][subject]

    # если нет доступа и лимит пробного исчерпан
    if not has_access(user_id, subject) and user_trials >= 5:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Купить доступ", callback_data=f"buy_access_{subject}")]
            ]
        )
        await callback.message.answer(
            "⛔ Вы использовали 5 пробных вопросов.\n"
            "Купите доступ, чтобы продолжить.",
            reply_markup=markup
        )
        session["active"] = False
        await callback.answer()
        return

    # ---------- обработка ответа ----------
    # ans_t_1_123 -> ["ans", "t", "1", "123"]
    parts = callback.data.split("_")
    selected = int(parts[2])
    question_id = int(parts[3])

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT correct_option, COALESCE(explanation, '') FROM questions WHERE id=?", (question_id,))
    correct_option, explanation = cursor.fetchone()
    conn.close()

    if selected == correct_option:
        result_msg = "✅ Верно!"
    else:
        result_msg = f"❌ Неверно!\n\nПравильный ответ: вариант {correct_option}"

    if explanation.strip():
        result_msg += f"\n\n{explanation}"

    await callback.message.answer(result_msg)

    # ---------- УВЕЛИЧИВАЕМ ПРОБНЫЙ СЧЁТЧИК ----------
    # ---------- ПРОБНЫЙ ДОСТУП ----------
    if not has_access(user_id, subject):

        # увеличить счетчик
        trials[user_id][subject] += 1
        save_trials(trials)

        # если достигнут лимит пробных вопросов
        if trials[user_id][subject] >= 5:

            # ── БАЛЛЫ за прорешивание 5 вопросов ──
            conn = db_conn()
            c = conn.cursor()
            c.execute("SELECT trial_bonus_subject FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            trial_bonus_subject = row[0] if row else None
            conn.close()

            # Начисляем только если ещё не получал бонус ни за один предмет
            if trial_bonus_subject is None:
                # Фиксируем предмет за который получил бонус
                conn = db_conn()
                c = conn.cursor()
                c.execute("UPDATE users SET trial_bonus_subject=? WHERE user_id=?", (subject, user_id))
                conn.commit()
                conn.close()

                # +15 только если пришёл по реферальной ссылке
                referrer_id = get_referrer_id(user_id)
                if referrer_id:
                    add_points(user_id, POINTS_REF_TRIAL_SELF, "own_trial", subject=subject)
                    await callback.message.answer(
                        f"🎉 +{POINTS_REF_TRIAL_SELF} баллов начислено за прохождение бесплатных вопросов!\n"
                        f"Нажми «💎 Мой баланс» чтобы проверить."
                    )

            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Купить доступ", callback_data=f"buy_access_{subject}")]
                ]
            )
            await callback.message.answer(
                "⛔ Вы использовали 5 пробных вопросов.\n"
                "Купите доступ, чтобы продолжить.",
                reply_markup=markup
            )
            session["active"] = False
            _save_session(user_id, 'test', session)
            await callback.answer()
            return

    # ---------- новый вопрос ----------
    recent_ids = set(get_recent_question_ids(user_id, subject, 100))
    new_q = get_questions_excluding(subject, recent_ids, 1)
    if not new_q:
        await callback.message.answer("✔️ Вопросы закончились.")
        session["active"] = False
        _save_session(user_id, 'test', session)
        return

    save_question_to_history(user_id, subject, new_q[0][0])

    session["question"] = list(new_q[0])
    _save_session(user_id, 'test', session)
    markup = question_to_inline(new_q[0], mode="test")

    question_text = f"━━━━━━━━━━━━━━━━\n▶️ Следующий вопрос:\n━━━━━━━━━━━━━━━━\n\n{format_question_text(new_q[0])}"
    await callback.message.answer(question_text, reply_markup=markup)

    await callback.answer()
# ---------------- ЗАПУСК ---------------
def get_users_without_purchase_and_referral() -> list:
    """Возвращает user_id тех, кто не купил ни одного предмета и не пригласил никого."""
    conn = db_conn()
    c = conn.cursor()
    # Все пользователи
    try:
        c.execute("SELECT user_id FROM users")
        all_users = {r[0] for r in c.fetchall()}
    except Exception:
        all_users = set()
    # Кто купил
    try:
        c.execute("SELECT DISTINCT user_id FROM purchases")
        buyers = {r[0] for r in c.fetchall()}
    except Exception:
        buyers = set()
    # Кто уже приглашал
    try:
        c.execute("SELECT DISTINCT referrer_id FROM referrals")
        referrers = {r[0] for r in c.fetchall()}
    except Exception:
        referrers = set()
    conn.close()
    # Только те кто не купил и не приглашал
    return list(all_users - buyers - referrers)


async def referral_reminder_loop():
    """Каждые 2 дня шлёт напоминание о рефералке тем кто не купил и не приглашал."""
    await asyncio.sleep(60)  # небольшая задержка после старта бота
    while True:
        try:
            bot_info = await bot.get_me()
            targets = get_users_without_purchase_and_referral()
            print(f"[REFERRAL REMINDER] Отправляем напоминание {len(targets)} пользователям")
            sent = 0
            failed = 0
            for user_id in targets:
                try:
                    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
                    await bot.send_message(
                        user_id,
                        f"💎 Знаешь про нашу реферальную программу?\n\n"
                        f"Приглашай друзей по своей ссылке → получай баллы → плати меньше за доступ к предметам!\n\n"
                        f"🔗 Твоя ссылка:\n{ref_link}\n\n"
                        f"⏳ Сезон скоро заканчивается — успей воспользоваться!",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text="💎 Баллы и рефералка",
                                web_app=WebAppInfo(url=WEBAPP_URL)
                            )
                        ]])
                    )
                    sent += 1
                    await asyncio.sleep(0.05)  # не спамим Telegram API
                except Exception:
                    failed += 1
            print(f"[REFERRAL REMINDER] Отправлено: {sent}, ошибок: {failed}")
        except Exception as e:
            print(f"[REFERRAL REMINDER] Ошибка: {e}")
        # Ждём 2 дня
        await asyncio.sleep(2 * 24 * 60 * 60)


async def main():
    # Запуск веб-сервера для Mini App
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("[WEB] Mini App сервер запущен на http://0.0.0.0:8080")
    print(f"🌍 WebApp URL: {WEBAPP_URL}")
    print("⚡ Убедитесь, что cloudflared tunnel запущен: cloudflared tunnel run ameba")

    # Запуск автоматической рассылки рефералки
    asyncio.create_task(referral_reminder_loop())

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
