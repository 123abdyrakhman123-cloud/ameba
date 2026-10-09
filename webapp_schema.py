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
    display_name TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS web_support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google')),
    account_key TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_web_support_owner ON web_support_tickets(provider, account_key, created_at);
CREATE TABLE IF NOT EXISTS web_support_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    author_provider TEXT NOT NULL CHECK (author_provider IN ('telegram', 'google', 'system')),
    author_key TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_web_support_replies_ticket ON web_support_replies(ticket_id, created_at);
CREATE TABLE IF NOT EXISTS web_announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS web_promo (
    id INTEGER PRIMARY KEY CHECK (id=1),
    text TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS web_referral_codes (
    provider TEXT NOT NULL,
    account_key TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(provider, account_key)
);
CREATE TABLE IF NOT EXISTS web_referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_provider TEXT NOT NULL,
    referrer_key TEXT NOT NULL,
    referee_provider TEXT NOT NULL,
    referee_key TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(referee_provider, referee_key)
);
CREATE TABLE IF NOT EXISTS web_points_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    account_key TEXT NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    related_provider TEXT,
    related_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_web_points_owner ON web_points_log(provider, account_key, created_at);
CREATE TABLE IF NOT EXISTS web_exam_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google')),
    account_key TEXT NOT NULL,
    exam_session_key TEXT NOT NULL,
    subject TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    elapsed_seconds INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    answered INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    max_score INTEGER NOT NULL DEFAULT 0,
    time_expired INTEGER NOT NULL DEFAULT 0,
    UNIQUE(provider, account_key, exam_session_key)
);
CREATE INDEX IF NOT EXISTS idx_web_exam_owner_time
    ON web_exam_results(provider, account_key, completed_at DESC);
CREATE TABLE IF NOT EXISTS web_exam_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL REFERENCES web_exam_results(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL,
    question_order INTEGER NOT NULL,
    selected_option INTEGER,
    correct_option INTEGER,
    is_correct INTEGER NOT NULL DEFAULT 0,
    explanation TEXT NOT NULL DEFAULT '',
    UNIQUE(result_id, question_order)
);
CREATE INDEX IF NOT EXISTS idx_web_exam_answers_result
    ON web_exam_answers(result_id, question_order);
CREATE TABLE IF NOT EXISTS web_activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google')),
    account_key TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    event_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE(provider, account_key, event_key)
);
CREATE INDEX IF NOT EXISTS idx_web_activity_owner_time
    ON web_activity_events(provider, account_key, occurred_at);
CREATE TABLE IF NOT EXISTS web_leaderboard_profiles (
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'google')),
    account_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    display_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(provider, account_key)
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
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(web_sessions)")}
        if "display_name" not in session_columns:
            conn.execute("ALTER TABLE web_sessions ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
