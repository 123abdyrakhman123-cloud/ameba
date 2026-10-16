import random


def _history_insert(conn, provider, account_key, subject, question_id):
    if provider == "telegram":
        conn.execute(
            "INSERT INTO question_history (user_id, subject, question_id) VALUES (?, ?, ?)",
            (int(account_key), subject, question_id),
        )
    elif provider == "google":
        conn.execute(
            "INSERT INTO web_google_history (google_subject, subject, question_id) VALUES (?, ?, ?)",
            (account_key, subject, question_id),
        )
    else:
        raise ValueError("Unsupported question-history provider")


def mark_question_shown(conn, provider, account_key, subject, question_id):
    """Record first exposure during the current cycle and keep all-time history."""
    subject = subject.lower()
    cursor = conn.execute(
        "INSERT OR IGNORE INTO question_cycle_seen(provider, account_key, subject, question_id) "
        "VALUES (?, ?, ?, ?)",
        (provider, str(account_key), subject, question_id),
    )
    if cursor.rowcount:
        _history_insert(conn, provider, str(account_key), subject, question_id)
        return True
    return False


def next_practice_question(conn, provider, account_key, subject):
    """Return an unseen random question, resetting this subject's cycle if needed."""
    subject = subject.lower()
    question = conn.execute(
        "SELECT q.* FROM questions q WHERE LOWER(q.subject)=? "
        "AND NOT EXISTS (SELECT 1 FROM question_cycle_seen s "
        "WHERE s.provider=? AND s.account_key=? AND s.subject=? AND s.question_id=q.id) "
        "ORDER BY RANDOM() LIMIT 1",
        (subject, provider, str(account_key), subject),
    ).fetchone()
    if question is None:
        conn.execute(
            "DELETE FROM question_cycle_seen WHERE provider=? AND account_key=? AND subject=?",
            (provider, str(account_key), subject),
        )
        question = conn.execute(
            "SELECT * FROM questions WHERE LOWER(subject)=? ORDER BY RANDOM() LIMIT 1",
            (subject,),
        ).fetchone()
    if question is not None:
        mark_question_shown(conn, provider, account_key, subject, question[0])
    return question


def select_exam_questions(conn, provider, account_key, subject, limit=50):
    """Select unseen questions first, without marking the exam's set as viewed."""
    subject = subject.lower()
    all_questions = conn.execute(
        "SELECT * FROM questions WHERE LOWER(subject)=? ORDER BY RANDOM()", (subject,)
    ).fetchall()
    if not all_questions:
        return []
    seen_ids = {
        row[0] for row in conn.execute(
            "SELECT question_id FROM question_cycle_seen "
            "WHERE provider=? AND account_key=? AND subject=?",
            (provider, str(account_key), subject),
        )
    }
    unseen = [question for question in all_questions if question[0] not in seen_ids]
    previously_seen = [question for question in all_questions if question[0] in seen_ids]
    count = min(limit, len(all_questions))
    selected = unseen[:count]
    if len(selected) < count:
        selected.extend(previously_seen[:count - len(selected)])
    random.shuffle(selected)
    return selected
