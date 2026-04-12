import sqlite3
import re
import os
import sys

def process(subject_name):
    RAW_FILE = 'raw_questions.txt'
    DB_FILE = 'questions.db'
    OUT_FILE = f'{subject_name}.py'

    # 1. Читаем сырые данные
    with open(RAW_FILE, 'r', encoding='utf-8') as f:
        text = f.read()

    # 2. Парсим вопросы
    blocks = re.findall(r'\[Q\](.*?)(?=\[/\])\[/\]', text, re.DOTALL)
    
    questions = []
    seen = set()
    
    for block in blocks:
        q_match = re.search(r'^(.*?)(?=\[A-\]|\[A\+\])', block, re.DOTALL)
        if not q_match:
            continue
        q_text = q_match.group(1).strip()
        
        # Если вопрос уже был, пропускаем (теперь отключено)
        # if q_text in seen:
        #     continue
        # seen.add(q_text)
        
        # Ищем варианты ответов и объяснение
        options_text = block[q_match.end():]
        
        e_match = re.search(r'\[E\](.*)$', options_text, re.DOTALL)
        expl_text = e_match.group(1).strip() if e_match else ""
        
        opts_section = options_text
        if e_match:
            opts_section = options_text[:e_match.start()]
            
        opts = re.findall(r'\[(A-|A\+)\](.*?)(?=\[[AE]|\n\[|$)', opts_section, re.DOTALL)
        if not opts:
            opts = re.findall(r'\[(A-|A\+)\]\s*(.*)', opts_section)
            
        options_list = []
        correct_idx = -1
        
        for opt_type, opt_val in opts:
            val = opt_val.strip()
            if not val:
                continue
            options_list.append(val)
            if opt_type == 'A+':
                correct_idx = len(options_list)
                
        if correct_idx != -1 and len(options_list) > 0:
            questions.append({
                'question': q_text,
                'options': options_list,
                'correct': correct_idx,
                'explanation': expl_text
            })

    print(f"Найдено уникальных вопросов: {len(questions)}")

    # 3. Удаляем старые вопросы данного предмета
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM questions WHERE subject=?", (subject_name,))
    print(f"Старые вопросы по предмету {subject_name} удалены из базы.")

    # 4. Формируем <subject>.py и записываем в БД
    py_content = f"""import sqlite3

def add_question(subject, question_text, options, correct_option, explanation):
    conn = sqlite3.connect("questions.db")
    cursor = conn.cursor()

    n = len(options)
    columns = [f"option{{i+1}}" for i in range(n)]

    query = f\"\"\"
        INSERT INTO questions (subject, question, {{', '.join(columns)}}, correct_option, explanation)
        VALUES ({{', '.join(['?'] * (n + 4))}})
    \"\"\"

    cursor.execute(query, (subject, question_text, *options, correct_option, explanation))
    conn.commit()
    conn.close()

"""

    inserted = 0
    for q in questions:
        q_text_esc = q['question'].replace('"', '\\"').replace('\n', ' ')
        expl_esc = q['explanation'].replace('"', '\\"').replace('\n', ' ')
        opts_esc = [opt.replace('"', '\\"').replace('\n', ' ') for opt in q['options']]
        
        options_formatted = ", ".join([f'"{opt}"' for opt in opts_esc])
        
        py_content += f"""add_question(
    "{subject_name}",
    "{q_text_esc}",
    [{options_formatted}],
    {q['correct']},
    "{expl_esc}"
)

"""
        n = len(q['options'])
        columns = [f"option{i+1}" for i in range(n)]
        query = f"""
            INSERT INTO questions (subject, question, {', '.join(columns)}, correct_option, explanation)
            VALUES ({', '.join(['?'] * (n + 4))})
        """
        cursor.execute(query, (subject_name, q['question'], *q['options'], q['correct'], q['explanation']))
        inserted += 1

    conn.commit()
    conn.close()
    
    # 5. Сохраняем python файл
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write(py_content)
        
    print(f"Успешно обработано и добавлено в БД: {inserted} вопросов.")
    print(f"Файл {OUT_FILE} сгенерирован.")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        subj = sys.argv[1]
    else:
        subj = input('Введите название предмета (например, psychiatry): ')
    process(subj)
