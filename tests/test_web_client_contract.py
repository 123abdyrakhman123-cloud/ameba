import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BrowserClientContractTests(unittest.TestCase):
    def test_login_offers_both_providers_and_purchase_guidance(self):
        client = (ROOT / "web_static/app.js").read_text()
        self.assertIn("Telegram Login Widget", client)
        self.assertIn("google.accounts.id.renderButton", client)
        self.assertIn("Если вы уже покупали доступ в боте, войдите через Telegram", client)
        self.assertIn("Google создаёт отдельный веб-аккаунт", client)
        self.assertIn("/api/session/telegram", client)
        self.assertIn("/api/session/google", client)
        self.assertIn("/api/session/demo", client)
        self.assertIn("WEB_CONFIG.demo_login_enabled", client)

    def test_demo_session_is_visibly_marked_in_the_account_ui(self):
        client = (ROOT / "web_static/app.js").read_text()
        self.assertIn("WEB_SESSION.is_demo", client)
        self.assertIn('class="demo-marker"', client)
        self.assertIn("Демо", client)

    def test_client_uses_cookie_sessions_and_browser_history_not_mini_app_auth(self):
        client = (ROOT / "web_static/app.js").read_text()
        self.assertIn("/api/session", client)
        self.assertIn("credentials: 'same-origin'", client)
        self.assertIn("history.pushState", client)
        self.assertIn("popstate", client)
        self.assertNotRegex(client, re.compile(r"Telegram\.WebApp|initData|headers\s*:\s*\{[^}]*Authorization", re.S))
        self.assertNotIn("tg.", client)

    def test_html_allows_zoom_and_loads_no_telegram_mini_app_script(self):
        html = (ROOT / "web_static/index.html").read_text()
        self.assertIn("width=device-width, initial-scale=1.0", html)
        self.assertNotRegex(html, re.compile(r"maximum-scale\s*=\s*1|user-scalable\s*=\s*no", re.I))
        self.assertNotIn("telegram-web-app.js", html)

    def test_legacy_telegram_client_bundle_remains_untouched(self):
        old_html = (ROOT / "static/index.html").read_text()
        old_client = (ROOT / "static/app.js").read_text()
        self.assertIn("telegram-web-app.js", old_html)
        self.assertIn("Telegram.WebApp", old_client)


if __name__ == "__main__":
    unittest.main()
