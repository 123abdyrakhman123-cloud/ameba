import asyncio
import os
import random
import sqlite3
import pickle
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile
from aiohttp import web
import config
from webapp_server import create_app

WEBAPP_URL = "https://ameba-app.uk"

# --- КОНФИГУРАЦИЯ ---
CODER_CHAT_ID = 1427715527

# --- АДМИНЫ ---
ADMIN_IDS = {1427715527, 905937261, 8113642902}
QR_FILE = os.path.join(os.path.dirname(__file__), "qr.png")  # QR-код из локального файла
QR_ID = None  # Кэшируется после первой отправки

bot = Bot(token=config.API_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ ---
exam_sessions = {}
test_sessions = {}
review_sessions = {}  # Работа над ошибками после экзамена
feedback_waiting = set()

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

def get_recent_question_ids(user_id, subject, limit=100):
    """Возвращает список ID последних N вопросов, показанных пользователю"""
    conn = sqlite3.connect("questions.db")
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
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        (user_id, subject.lower(), question_id)
    )
    conn.commit()
    conn.close()

def save_questions_to_history(user_id, subject, question_ids):
    """Сохраняет список показанных вопросов в историю"""
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
        [(user_id, subject.lower(), qid) for qid in question_ids]
    )
    conn.commit()
    conn.close()

def get_questions(subject, limit=500):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE LOWER(subject)=?", (subject.lower(),))
    questions = cursor.fetchall()
    conn.close()
    if not questions:
        return []
    return random.sample(questions, min(limit, len(questions)))

def get_questions_excluding(subject, exclude_ids, limit=1):
    """Получает случайные вопросы, исключая указанные ID"""
    conn = sqlite3.connect("questions.db")
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
async def send_qr_photo(chat_id, caption, reply_markup=None, parse_mode="Markdown"):
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

# ---------------- Работа с доступом ----------------
def load_purchases():
    try:
        with open("purchases.pkl", "rb") as f:
            return pickle.load(f)
    except:
        return {}

def save_purchases(purchases):
    with open("purchases.pkl", "wb") as f:
        pickle.dump(purchases, f)

def has_access(user_id: int, subject: str) -> bool:

    purchases = load_purchases()
    user_purchases = purchases.get(user_id, {})

    # Проверяем, есть ли вообще такой subject у пользователя
    if subject not in user_purchases:
        return False

    expires_at = user_purchases[subject]

    # None означает бессрочный доступ (forever)
    if expires_at is None:
        return True

    # Проверяем, не истек ли срок
    if isinstance(expires_at, datetime) and datetime.now() > expires_at:
        return False

    return True

# ---------- ПРОБНЫЙ ДОСТУП ----------
def load_trials():
    try:
        with open("trial.pkl", "rb") as f:
            return pickle.load(f)
    except:
        return {}

def save_trials(data):
    with open("trial.pkl", "wb") as f:
        pickle.dump(data, f)

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

@dp.callback_query(F.data == "show_promo")
async def show_promo_callback(callback: CallbackQuery):
    promo_text = load_promo()
    text = promo_text if promo_text else "Раздел пуст"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_start")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_start")
async def back_to_start_callback(callback: CallbackQuery):
    text = (
        "👋 Привет!\n\n"
        "Добро пожаловать в бот для подготовки к экзаменам.\n"
        "Здесь вы сможете проходить тесты и симуляции экзамена по разным предметам.\n\n"
        "Нажмите кнопку ниже, чтобы продолжить."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Акции", callback_data="show_promo")],
            [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))],
            [InlineKeyboardButton(text="➡️ Продолжить в боте", callback_data="show_faculties")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()

# ---------------- Старт ----------------
@dp.message(Command("start"))
async def start_handler(message: Message):
    text = (
        "👋 Привет!\n\n"
        "Добро пожаловать в бот для подготовки к экзаменам.\n"
        "Здесь вы сможете проходить тесты и симуляции экзамена по разным предметам.\n\n"
        "Нажмите кнопку ниже, чтобы продолжить."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Акции", callback_data="show_promo")],
            [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))],
            [InlineKeyboardButton(text="➡️ Продолжить в боте", callback_data="show_faculties")],
        ]
    )
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "show_faculties")
async def show_faculties_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏛 Выберите факультет:", reply_markup=faculty_menu_inline()
    )
    await callback.answer()

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
    if user_id in exam_sessions:
        exam_sessions[user_id]["active"] = False
        del exam_sessions[user_id]

    if user_id in test_sessions:
        test_sessions[user_id]["active"] = False
        del test_sessions[user_id]

    if user_id in review_sessions:
        del review_sessions[user_id]

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

    purchases = load_purchases()
    if user_id not in purchases:
        purchases[user_id] = {}
    purchases[user_id][subject] = None
    save_purchases(purchases)
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

    purchases = load_purchases()
    print(f"[REVOKE] До удаления: user_id={user_id}, purchases={purchases.get(user_id, {})}")

    if user_id in purchases and subject in purchases[user_id]:
        del purchases[user_id][subject]
        # Если у пользователя больше нет доступов, удаляем его из словаря
        if not purchases[user_id]:
            del purchases[user_id]
        save_purchases(purchases)

        # Проверяем, что сохранилось
        saved_purchases = load_purchases()
        print(f"[REVOKE] После удаления: user_id={user_id}, purchases={saved_purchases.get(user_id, {})}")

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

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"qr_paid_{subject}_forever")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_menu")]
        ]
    )

    # Отправляем QR код пользователю
    await send_qr_photo(
        chat_id=callback.message.chat.id,
        caption=(
            f"💳 *Покупка доступа к {subj_name}*\n\n"
            f"Стоимость доступа: *300с навсегда*\n\n"
            f"Оплатите по QR-коду и нажмите «Я оплатил»\\.\n"
            f"После проверки доступ откроем вручную\\.\n\n"
            f"По вопросам: @Ameba\\_admin"
        ),
        reply_markup=markup
    )

    # Уведомляем всех админов сразу при показе QR
    for admin_id in ADMIN_IDS:
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
                        text=f"✅ Выдать доступ",
                        callback_data=f"admin_grant_{user_id}_{subject}"
                    )]
                ])
            )
        except Exception:
            pass

    await callback.answer()

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

    purchases = load_purchases()
    if target_user_id not in purchases:
        purchases[target_user_id] = {}
    purchases[target_user_id][subject] = None
    save_purchases(purchases)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Доступ к *{subj_name}* выдан пользователю `{target_user_id}`\\.", parse_mode="MarkdownV2")

    try:
        await bot.send_message(
            target_user_id,
            f"🎉 Вам открыт доступ к *{subj_name}*\\!\n\nТеперь вы можете проходить тесты и экзамены без ограничений\\!",
            parse_mode="MarkdownV2",
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
        await bot.send_document(CODER_CHAT_ID, message.document.file_id, caption=f"💳 Квитанция от {sender} (id:{user_id})")
        await message.answer("✅ Квитанция отправлена администратору.")
    elif message.photo:
        await bot.send_photo(CODER_CHAT_ID, message.photo[-1].file_id, caption=f"💳 Квитанция от {sender} (id:{user_id})")
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

    # Проверяем уникальность вопросов в экзамене (на случай если в базе есть дубликаты)
    seen_ids = set()
    unique_questions = []
    for q in questions:
        if q[0] not in seen_ids:
            seen_ids.add(q[0])
            unique_questions.append(q)
    questions = unique_questions

    # Сохраняем все вопросы экзамена в историю
    save_questions_to_history(user_id, subject, [q[0] for q in questions])

    exam_sessions[user_id] = {
        "subject": subject,
        "questions": questions,
        "current": 0,
        "score": 0,
        "active": True,
        "start_time": datetime.now(),  # Записываем время начала экзамена
        "answers": []  # Список: {"question": tuple, "selected": int, "correct": int, "is_correct": bool}
    }
    await callback.message.edit_text(f"📝 Начинаем экзамен по {subject.capitalize()}!\n⏱ У вас есть 1 час 15 минут.")
    await send_exam_question(callback.message, user_id)
    await callback.answer()

async def send_exam_question(message, user_id):
    session = exam_sessions.get(user_id)
    print(f"[send_exam_question] session={session is not None}, active={session.get('active') if session else None}")
    if not session or not session["active"]:
        return

    # Проверяем, не истекло ли время
    minutes, seconds, is_expired = get_time_remaining(session["start_time"])
    if is_expired:
        await message.answer("⏰ Время экзамена истекло!")
        await finish_exam(message, user_id, time_expired=True)
        return

    if session["current"] >= len(session["questions"]):
        await finish_exam(message, user_id)
        return

    q = session["questions"][session["current"]]
    print(f"[send_exam_question] q_id={q[0]}, q_text={q[2][:30]}...")
    markup = question_to_inline(q, mode="exam")
    print(f"[send_exam_question] markup buttons: {len(markup.inline_keyboard)}")
    session["current_q_id"] = q[0]

    # Форматируем текст вопроса с вариантами ответов и таймером
    time_str = format_time_remaining(minutes, seconds)
    question_text = f"{time_str}\n\n{format_question_text(q, session['current'] + 1, len(session['questions']))}"
    await message.answer(question_text, reply_markup=markup)

async def finish_exam(message, user_id, time_expired=False):
    session = exam_sessions.get(user_id)
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
        review_sessions[user_id] = {
            "subject": session["subject"],
            "answers": answers,
            "current": 0
        }

    # Кнопки после экзамена
    result_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Работа над ошибками", callback_data="review_start")],
            [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_menu")]
        ]
    )

    await message.answer(result_text, parse_mode="Markdown", reply_markup=result_markup)
    del exam_sessions[user_id]

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

    test_sessions[user_id] = {"subject": subject, "question": q, "active": True}
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

@dp.message(F.text)
async def receive_feedback_text(message: Message):
    user_id = message.from_user.id
    if user_id not in feedback_waiting:
        return
    sender = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await bot.send_message(CODER_CHAT_ID, f"🆘 Сообщение от {sender} (id:{user_id}):\n\n{message.text}")
    feedback_waiting.discard(user_id)
    await message.answer("✅ Ваше сообщение отправлено.")

# ---------------- Обработка ответов ЭКЗАМЕН ----------------
@dp.callback_query(lambda c: c.data.startswith("ans_e_"))
async def handle_exam_answer(callback: CallbackQuery):
    print(f"[EXAM] callback: {callback.data}")
    user_id = callback.from_user.id
    session = exam_sessions.get(user_id)
    print(f"[EXAM] session: {session}")

    if not session or not session["active"]:
        await callback.answer("Экзамен не активен.")
        return

    # Проверяем, не истекло ли время
    minutes, seconds, is_expired = get_time_remaining(session["start_time"])
    if is_expired:
        await callback.message.answer("⏰ Время экзамена истекло!")
        await finish_exam(callback.message, user_id, time_expired=True)
        await callback.answer("Время истекло!")
        return

    # ans_e_1_123 -> ["ans", "e", "1", "123"]
    parts = callback.data.split("_")
    selected = int(parts[2])
    question_id = int(parts[3])

    conn = sqlite3.connect("questions.db")
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
    session = review_sessions.get(user_id)

    if not session or not session["answers"]:
        await callback.answer("Нет данных для работы над ошибками.", show_alert=True)
        return

    session["current"] = 0
    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

async def send_review_question(message, user_id, edit=False):
    session = review_sessions.get(user_id)
    if not session:
        return

    answers = session["answers"]
    current = session["current"]
    total = len(answers)

    if current < 0 or current >= total:
        return

    answer_data = answers[current]
    text = format_review_question(answer_data, current, total)

    # Кнопки навигации
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
    session = review_sessions.get(user_id)
    if not session:
        await callback.answer("Сессия не найдена.", show_alert=True)
        return

    if session["current"] < len(session["answers"]) - 1:
        session["current"] += 1

    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

@dp.callback_query(F.data == "review_prev")
async def review_prev(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = review_sessions.get(user_id)
    if not session:
        await callback.answer("Сессия не найдена.", show_alert=True)
        return

    if session["current"] > 0:
        session["current"] -= 1

    await send_review_question(callback.message, user_id, edit=True)
    await callback.answer()

# ---------------- Обработка ответов ТЕСТЫ ----------------
@dp.callback_query(lambda c: c.data.startswith("ans_t_"))
async def handle_test_answer(callback: CallbackQuery):
    print(f"[TEST] callback: {callback.data}")
    user_id = callback.from_user.id
    session = test_sessions.get(user_id)
    print(f"[TEST] session: {session}")

    if not session or not session["active"]:
        await callback.answer("Тест не активен.")
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

    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT correct_option, COALESCE(explanation, '') FROM questions WHERE id=?", (question_id,))
    correct_option, explanation = cursor.fetchone()
    conn.close()

    if selected == correct_option:
        result_msg = "✅ Верно!"
    else:
        result_msg = f"❌ Неверно!\n\nПравильный ответ: *{correct_option}*"

    if explanation.strip():
        result_msg += f"\n\n{explanation}"

    await callback.message.answer(result_msg, parse_mode="Markdown")

    # ---------- УВЕЛИЧИВАЕМ ПРОБНЫЙ СЧЁТЧИК ----------
    # ---------- ПРОБНЫЙ ДОСТУП ----------
    if not has_access(user_id, subject):

        # увеличить счетчик
        trials[user_id][subject] += 1
        save_trials(trials)

        # если достигнут лимит пробных вопросов
        if trials[user_id][subject] >= 5:
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

    # ---------- новый вопрос ----------
    # Получаем последние 100 показанных вопросов для исключения повторов
    recent_ids = set(get_recent_question_ids(user_id, subject, 100))
    new_q = get_questions_excluding(subject, recent_ids, 1)
    if not new_q:
        await callback.message.answer("✔️ Вопросы закончились.")
        session["active"] = False
        return

    # Сохраняем вопрос в историю
    save_question_to_history(user_id, subject, new_q[0][0])

    session["question"] = new_q[0]
    markup = question_to_inline(new_q[0], mode="test")

    # Форматируем текст вопроса с вариантами ответов
    question_text = f"━━━━━━━━━━━━━━━━\n▶️ Следующий вопрос:\n━━━━━━━━━━━━━━━━\n\n{format_question_text(new_q[0])}"
    await callback.message.answer(question_text, reply_markup=markup)

    await callback.answer()
# ---------------- ЗАПУСК ---------------
async def main():
    # Запуск веб-сервера для Mini App
    app = create_app(bot, exam_sessions, test_sessions, review_sessions)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("[WEB] Mini App сервер запущен на http://0.0.0.0:8080")
    print(f"🌍 WebApp URL: {WEBAPP_URL}")
    print("⚡ Убедитесь, что cloudflared tunnel запущен: cloudflared tunnel run ameba")

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
