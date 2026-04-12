import sqlite3

def deduplicate_db():
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()
    
    # Оставляем только те вопросы, у которых минимальный rowid (первое добавление),
    # а остальные дубликаты (с тем же subject и текстом вопроса) удаляем.
    cursor.execute('''
        DELETE FROM questions 
        WHERE rowid NOT IN (
            SELECT MIN(rowid) 
            FROM questions 
            GROUP BY subject, question
        );
    ''')
    
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"Очистка завершена. Удалено дубликатов: {deleted_count}")

if __name__ == '__main__':
    deduplicate_db()
