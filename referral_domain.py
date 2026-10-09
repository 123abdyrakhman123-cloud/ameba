import hashlib
import sqlite3


LEVELS = (
    (0, "🟢 Новичок", 30, 100),
    (10, "🔵 Продвинутый", 40, 200),
    (20, "🟣 Мессия", 50, 300),
)


def referral_level(referral_count):
    current = LEVELS[0]
    for level in LEVELS:
        if referral_count >= level[0]:
            current = level
    return current[1], current[2], current[3]


def make_referral_code(provider, account_key):
    if provider == "telegram":
        return f"ref_{int(account_key)}"
    if provider == "google":
        digest = hashlib.sha256(account_key.encode("utf-8")).hexdigest()[:20]
        return f"web_{digest}"
    raise ValueError("Unsupported referral provider")


def get_or_create_referral_code(db_path, provider, account_key):
    code = make_referral_code(provider, account_key)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO web_referral_codes(provider, account_key, code) VALUES (?, ?, ?)",
            (provider, account_key, code),
        )
    return code


def claim_referral(db_path, referee_provider, referee_key, code):
    if referee_provider not in {"telegram", "google"} or not referee_key or not code:
        return False
    with sqlite3.connect(db_path) as conn:
        referrer = conn.execute(
            "SELECT provider, account_key FROM web_referral_codes WHERE code=?", (code,)
        ).fetchone()
        if not referrer and code.startswith("ref_"):
            try:
                referrer = ("telegram", str(int(code[4:])))
            except ValueError:
                return False
        if not referrer:
            return False
        referrer_provider, referrer_key = referrer
        if referrer_provider != referee_provider:
            return False
        if referrer_provider == referee_provider and referrer_key == referee_key:
            return False
        if referrer_provider == referee_provider == "telegram":
            referrer_id, referee_id = int(referrer_key), int(referee_key)
            referee = conn.execute(
                "SELECT referrer_id FROM users WHERE user_id=?", (referee_id,)
            ).fetchone()
            if not referee or referee[0] is not None:
                return False
            if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone():
                return False
            cursor = conn.execute(
                "INSERT OR IGNORE INTO referrals(referrer_id, referee_id) VALUES (?, ?)",
                (referrer_id, referee_id),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, referee_id))
            conn.execute(
                "UPDATE users SET points_balance=points_balance+10 WHERE user_id=?", (referrer_id,)
            )
            conn.execute(
                "INSERT INTO points_log(user_id, delta, reason, related_user_id) VALUES (?, 10, 'referral_join', ?)",
                (referrer_id, referee_id),
            )
            return True

        cursor = conn.execute(
            "INSERT OR IGNORE INTO web_referrals(referrer_provider, referrer_key, referee_provider, referee_key, code) "
            "VALUES (?, ?, ?, ?, ?)",
            (referrer_provider, referrer_key, referee_provider, referee_key, code),
        )
        if cursor.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO web_points_log(provider, account_key, delta, reason, related_provider, related_key) "
            "VALUES (?, ?, 10, 'referral_join', ?, ?)",
            (referrer_provider, referrer_key, referee_provider, referee_key),
        )
        return True
