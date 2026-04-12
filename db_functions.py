# db_functions.py
import sqlite3
import random


# Получить случайный вопрос по предмету
def get_questions(subject):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM questions WHERE subject=?", (subject,))
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        return None

    question = random.choice(questions)
    return question

# Добавление нового вопроса
def add_question(subject, question_text, options, correct_option, explanation):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()

    # Гарантируем, что будет ровно 5 вариантов:
    # если меньше 5 — дополняем None, если больше — обрезаем
    options = (options + [None] * 5)[:5]

    cursor.execute("""
        INSERT INTO questions (subject, question, option1, option2, option3, option4, option5,
                               correct_option, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (subject, question_text, *options, correct_option, explanation))

    conn.commit()
    conn.close()
