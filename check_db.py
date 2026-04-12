import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('questions.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT subject, COUNT(*) as total, COUNT(DISTINCT question) as unique_q
    FROM questions 
    GROUP BY subject
''')

print("Database check:")
for row in cursor.fetchall():
    subj, total, unique_q = row
    duplicates = total - unique_q
    if duplicates > 0:
        print(f"DUPLICATES FOUND in {subj}: Total={total}, Unique={unique_q}")
    else:
        print(f"OK {subj}: {total} unique.")

conn.close()
