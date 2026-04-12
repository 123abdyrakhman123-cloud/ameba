import sqlite3

conn = sqlite3.connect("questions.db")
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

conn.commit()
conn.close()

print("Таблицы созданы успешно!")
