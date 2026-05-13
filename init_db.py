"""
Инициализация БД на постоянном volume /data/questions.db
Запускается при каждом старте контейнера.
"""
import sqlite3
import os
import shutil

DATA_DIR = "/data"
DB_PATH = os.path.join(DATA_DIR, "questions.db")
LOCAL_DB = "questions.db"  # вопросы из образа

# Создаём директорию если нет
os.makedirs(DATA_DIR, exist_ok=True)

# Если на volume ещё нет базы — копируем из образа (там уже есть вопросы)
if not os.path.exists(DB_PATH):
    print(f"[init_db] Копируем {LOCAL_DB} → {DB_PATH}")
    shutil.copy2(LOCAL_DB, DB_PATH)

# Создаём таблицы если не существуют (безопасно)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    question TEXT,
    option1 TEXT,
    option2 TEXT,
    option3 TEXT,
    option4 TEXT,
    option5 TEXT,
    correct_option INTEGER,
    explanation TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS question_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_history_user_subject
ON question_history (user_id, subject)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS purchases (
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (user_id, subject)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS trials (
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, subject)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS exam_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# ───────────────────────────────────────────
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ───────────────────────────────────────────

# Расширяем таблицу users новыми колонками (безопасно — IF NOT EXISTS аналог через try)
for col_sql in [
    "ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN points_balance INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN trial_bonus_subject TEXT DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN referral_count INTEGER NOT NULL DEFAULT 0",
]:
    try:
        cursor.execute(col_sql)
    except Exception:
        pass  # колонка уже существует

# Таблица реферальных связей
cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,       -- кто пригласил
    referee_id  INTEGER NOT NULL UNIQUE, -- кого пригласили
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trial_bonus_paid INTEGER NOT NULL DEFAULT 0,  -- выплачен ли бонус за 5 вопросов
    purchase_bonus_paid INTEGER NOT NULL DEFAULT 0 -- выплачен ли бонус за покупку
)
""")

# Лог всех начислений и списаний баллов
cursor.execute("""
CREATE TABLE IF NOT EXISTS points_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    delta       INTEGER NOT NULL,          -- положительное = начисление, отрицательное = списание
    reason      TEXT NOT NULL,             -- 'referral_trial', 'referral_purchase', 'own_trial', 'own_purchase', 'spend'
    related_user_id INTEGER DEFAULT NULL,  -- связанный пользователь (реферал или реферер)
    subject     TEXT DEFAULT NULL,         -- предмет если применимо
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Таблица зарезервированных (замороженных) баллов при ожидании подтверждения оплаты
cursor.execute("""
CREATE TABLE IF NOT EXISTS points_reserved (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    subject     TEXT NOT NULL,
    points      INTEGER NOT NULL,          -- сколько баллов зарезервировано
    status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'confirmed', 'cancelled'
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_points_log_user ON points_log(user_id)")

# Таблица сессий (экзамен, тест, review)
cursor.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    user_id     INTEGER NOT NULL,
    session_type TEXT NOT NULL,   -- 'exam', 'test', 'review'
    data        TEXT NOT NULL,    -- JSON
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, session_type)
)
""")

conn.commit()
conn.close()
print(f"[init_db] БД готова: {DB_PATH}")
