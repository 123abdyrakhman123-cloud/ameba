import sqlite3
import tempfile
import unittest
from pathlib import Path

from referral_domain import claim_referral, get_or_create_referral_code, referral_level
from webapp_schema import init_web_database


class ReferralDomainTests(unittest.TestCase):
    def test_referral_levels_match_existing_bot_thresholds(self):
        self.assertEqual(referral_level(0), ("🟢 Новичок", 30, 100))
        self.assertEqual(referral_level(10), ("🔵 Продвинутый", 40, 200))
        self.assertEqual(referral_level(20), ("🟣 Мессия", 50, 300))

    def test_telegram_referral_state_uses_legacy_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "referrals.db"
            init_web_database(str(db))
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO users(user_id, full_name) VALUES (10, 'Referrer')")
                conn.execute("INSERT INTO users(user_id, full_name) VALUES (20, 'Referee')")
            code = get_or_create_referral_code(str(db), "telegram", "10")
            self.assertTrue(claim_referral(str(db), "telegram", "20", code))
            self.assertFalse(claim_referral(str(db), "telegram", "20", code))
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT referrer_id FROM users WHERE user_id=20").fetchone()[0], 10)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=10 AND referee_id=20").fetchone()[0], 1)

    def test_google_referrals_never_write_legacy_referral_or_points_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "google-referrals.db"
            init_web_database(str(db))
            code = get_or_create_referral_code(str(db), "google", "google-referrer")
            self.assertTrue(claim_referral(str(db), "google", "google-referee", code))
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_referrals").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_points_log").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_referrals_do_not_cross_provider_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "provider-boundary.db"
            init_web_database(str(db))
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO users(user_id, full_name) VALUES (10, 'Telegram')")
            google_code = get_or_create_referral_code(str(db), "google", "google-referrer")
            self.assertFalse(claim_referral(str(db), "telegram", "10", google_code))
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_referrals").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM web_points_log").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
