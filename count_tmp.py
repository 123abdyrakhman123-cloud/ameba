import sqlite3

def count_questions():
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM questions WHERE subject='surgery'")
    surgery_db = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM questions WHERE subject='surgery5'")
    surgery5_db = cursor.fetchone()[0]
    print(f"Surgery DB count: {surgery_db}")
    print(f"Surgery5 DB count: {surgery5_db}")

count_questions()
