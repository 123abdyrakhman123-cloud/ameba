import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebAdminClientContractTests(unittest.TestCase):
    def test_web_admin_uses_cookie_session_not_static_password_or_mini_app_auth(self):
        client = (ROOT / "web_static/admin.js").read_text()
        html = (ROOT / "web_static/admin.html").read_text()
        self.assertIn("credentials: 'same-origin'", client)
        self.assertIn("/api/admin/check", client)
        self.assertNotIn("admin_token", client)
        self.assertNotIn("password", client.lower())
        self.assertNotIn("Telegram.WebApp", client + html)
        self.assertNotIn("Authorization", client)


if __name__ == "__main__":
    unittest.main()
