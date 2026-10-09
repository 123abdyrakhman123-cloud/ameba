import os
import sqlite3


LEGACY_SCHEMA = """
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
);
CREATE TABLE IF NOT EXISTS question_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_user_subject
    ON question_history (user_id, subject);
CREATE TABLE IF NOT EXISTS purchases (
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (user_id, subject)
);
CREATE TABLE IF NOT EXISTS trials (
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, subject)
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS exam_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referee_id INTEGER NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trial_bonus_paid INTEGER NOT NULL DEFAULT 0,
    purchase_bonus_paid INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS points_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    related_user_id INTEGER DEFAULT NULL,
    subject TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS points_reserved (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    points INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_points_log_user ON points_log(user_id);
CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER NOT NULL,
    session_type TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, session_type)
);
"""


WEB_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google')),
    account_key TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_web_sessions_account
    ON web_sessions(provider, account_key, expires_at);
CREATE TABLE IF NOT EXISTS web_google_accounts (
    subject TEXT PRIMARY KEY,
    email TEXT,
    display_name TEXT,
    picture TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS web_google_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_subject TEXT NOT NULL,
    subject TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_web_google_history_subject
    ON web_google_history(google_subject, subject);
CREATE TABLE IF NOT EXISTS web_google_trials (
    google_subject TEXT NOT NULL,
    subject TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (google_subject, subject)
);
CREATE TABLE IF NOT EXISTS web_google_learning_sessions (
    google_subject TEXT NOT NULL,
    session_type TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (google_subject, session_type)
);
CREATE TABLE IF NOT EXISTS web_google_access_grants (
    google_subject TEXT NOT NULL,
    subject TEXT NOT NULL,
    expires_at TEXT,
    granted_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (google_subject, subject)
);
"""


USER_COLUMNS = {
    "referrer_id": "INTEGER DEFAULT NULL",
    "points_balance": "INTEGER NOT NULL DEFAULT 0",
    "trial_bonus_subject": "TEXT DEFAULT NULL",
    "referral_count": "INTEGER NOT NULL DEFAULT 0",
}


def init_web_database(db_path: str) -> None:
    if not db_path:
        raise ValueError("db_path is required")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_SCHEMA)
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        for name, definition in USER_COLUMNS.items():
            if name not in existing_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        conn.executescript(WEB_SCHEMA)
