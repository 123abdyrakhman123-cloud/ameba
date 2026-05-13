"""
Парсит txt-файлы с вопросами и импортирует в questions.db
Формат файла:
[Q] Текст вопроса
[A-] Вариант 1
[A+] Вариант 2 (правильный)
[A-] Вариант 3
[E] Объяснение
[/]
"""
import sqlite3
import os
import sys

DB_PATH = "/data/questions.db"
if not os.path.exists(DB_PATH):
    DB_PATH = "questions.db"  # локальный запуск


def parse_file(filepath):
    """Парсит файл и возвращает список вопросов."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    questions = []
    # Разбиваем на блоки по [/]
    blocks = content.split("[/]")

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = [l.strip() for l in block.splitlines() if l.strip()]

        question_text = None
        options = []
        correct_idx = None
        explanation_lines = []
        in_explanation = False

        for line in lines:
            if line.startswith("[Q]"):
                question_text = line[3:].strip()
                in_explanation = False
            elif line.startswith("[A+]"):
                options.append(line[4:].strip())
                correct_idx = len(options)  # 1-based
                in_explanation = False
            elif line.startswith("[A-]"):
                options.append(line[4:].strip())
                in_explanation = False
            elif line.startswith("[E]"):
                explanation_lines.append(line[3:].strip())
                in_explanation = True
            elif in_explanation:
                explanation_lines.append(line)
            elif question_text and not options:
                # Многострочный вопрос
                question_text += " " + line

        if not question_text or not options or correct_idx is None:
            continue

        # Нормализуем до 5 вариантов
        while len(options) < 5:
            options.append(None)
        options = options[:5]

        explanation = " ".join(explanation_lines).strip() or None

        questions.append({
            "question": question_text,
            "option1": options[0],
            "option2": options[1],
            "option3": options[2],
            "option4": options[3],
            "option5": options[4],
            "correct_option": correct_idx,
            "explanation": explanation,
        })

    return questions


def import_to_db(subject, questions):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0
    for q in questions:
        cursor.execute("""
            INSERT INTO questions (subject, question, option1, option2, option3, option4, option5, correct_option, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            subject,
            q["question"],
            q["option1"],
            q["option2"],
            q["option3"],
            q["option4"],
            q["option5"],
            q["correct_option"],
            q["explanation"],
        ))
        inserted += 1
    conn.commit()
    conn.close()
    return inserted


FILES = [
    ("/Users/ruslan/Downloads/Инфекционные болезни.txt", "infections"),
    ("/Users/ruslan/Downloads/ЛОР .txt", "lor"),
    ("/Users/ruslan/Downloads/Офтальма.txt", "ophthalmology"),
    ("/Users/ruslan/Downloads/Терапия 4 курс (1).txt", "therapy4"),
]

if __name__ == "__main__":
    for filepath, subject in FILES:
        if not os.path.exists(filepath):
            print(f"[SKIP] Файл не найден: {filepath}")
            continue
        questions = parse_file(filepath)
        count = import_to_db(subject, questions)
        print(f"[OK] {subject}: импортировано {count} вопросов из {filepath}")

    # Проверка
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject ORDER BY subject")
    rows = cursor.fetchall()
    conn.close()
    print("\n=== Статистика по предметам ===")
    total = 0
    for subject, count in rows:
        print(f"  {subject}: {count}")
        total += count
    print(f"  ИТОГО: {total}")
