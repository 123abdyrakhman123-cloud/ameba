import sqlite3


def create_support_ticket(db_path, provider, account_key, message):
    message = (message or "").strip()
    if not message or len(message) > 5000:
        raise ValueError("Support message must contain 1-5000 characters")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO web_support_tickets(provider, account_key, message) VALUES (?, ?, ?)",
            (provider, account_key, message),
        )
        return cursor.lastrowid


def list_support_tickets(db_path, provider=None, account_key=None):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if provider is None:
            rows = conn.execute(
                "SELECT id, provider, account_key, message, status, created_at "
                "FROM web_support_tickets ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, provider, account_key, message, status, created_at "
                "FROM web_support_tickets WHERE provider=? AND account_key=? ORDER BY updated_at DESC",
                (provider, account_key),
            ).fetchall()
        tickets = []
        for row in rows:
            item = dict(row)
            item["replies"] = [dict(reply) for reply in conn.execute(
                "SELECT author_provider, author_key, message, created_at FROM web_support_replies "
                "WHERE ticket_id=? ORDER BY id", (row["id"],)
            ).fetchall()]
            tickets.append(item)
        return tickets


def add_support_reply(db_path, ticket_id, author_provider, author_key, message):
    message = (message or "").strip()
    if not message or len(message) > 5000:
        raise ValueError("Reply must contain 1-5000 characters")
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute("SELECT 1 FROM web_support_tickets WHERE id=?", (ticket_id,)).fetchone()
        if not exists:
            return False
        conn.execute(
            "INSERT INTO web_support_replies(ticket_id, author_provider, author_key, message) "
            "VALUES (?, ?, ?, ?)",
            (ticket_id, author_provider, author_key, message),
        )
        conn.execute(
            "UPDATE web_support_tickets SET status='answered', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ticket_id,),
        )
        return True


def publish_announcement(db_path, title, body):
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        raise ValueError("Announcement title and body are required")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO web_announcements(title, body) VALUES (?, ?)", (title, body)
        )
        return cursor.lastrowid


def list_announcements(db_path, active_only=True):
    query = "SELECT id, title, body, active, created_at FROM web_announcements"
    if active_only:
        query += " WHERE active=1"
    query += " ORDER BY id DESC"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query).fetchall()]


def set_promo(db_path, text):
    text = (text or "").strip()
    with sqlite3.connect(db_path) as conn:
        if text:
            conn.execute(
                "INSERT INTO web_promo(id, text) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET "
                "text=excluded.text, updated_at=CURRENT_TIMESTAMP",
                (text,),
            )
        else:
            conn.execute("DELETE FROM web_promo WHERE id=1")


def get_promo(db_path):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT text FROM web_promo WHERE id=1").fetchone()
        return row[0] if row else ""
