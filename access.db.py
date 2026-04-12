# create_db.py
import sqlite3

conn = sqlite3.connect("access.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS access (
    user_id INTEGER PRIMARY KEY,
    end_date TEXT
)
""")

conn.commit()
conn.close()
print("База access.db создана ✅")
