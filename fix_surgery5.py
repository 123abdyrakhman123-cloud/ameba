import sqlite3
import subprocess

def fix_database():
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()
    
    # Очищаем все вопросы по предмету surgery5
    cursor.execute("DELETE FROM questions WHERE subject='surgery5'")
    
    # Также очистим 'surgery' на всякий случай, если там вдруг появятся случайные дубли
    cursor.execute("DELETE FROM questions WHERE subject='surgery'")
    
    conn.commit()
    print("Старые дубликаты хирургии удалены из базы.")
    conn.close()
    
    # Запускаем скрипт surgery5.py, чтобы добавить вопросы заново
    print("Заполняем базу заново (запускаем surgery5.py)...")
    subprocess.run(['python', 'surgery5.py'], check=True)
    
    # Проверяем итоговое количество
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM questions WHERE subject='surgery5'")
    count = cursor.fetchone()[0]
    conn.close()
    
    print(f"Готово! Теперь в базе {count} уникальных вопросов для предмета surgery5.")

if __name__ == '__main__':
    fix_database()
