import os
import unittest
from unittest.mock import patch

try:
    from webapp_settings import SettingsError, WebSettings
except ModuleNotFoundError:
    SettingsError = RuntimeError
    WebSettings = None


BASE_ENV = {
    "AMEBA_WEB_DB_PATH": "/tmp/ameba-web-test.db",
    "AMEBA_WEB_SESSION_SECRET": "test-session-secret-with-enough-entropy",
    "AMEBA_TELEGRAM_LOGIN_BOT_TOKEN": "123456:test-token",
    "AMEBA_TELEGRAM_LOGIN_BOT_USERNAME": "ameba_test_bot",
    "AMEBA_GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
}


class WebSettingsTests(unittest.TestCase):
    def setUp(self):
        if WebSettings is None:
            self.fail("WebSettings is not implemented")

    def load_settings(self, **overrides):
        env = BASE_ENV | overrides
        with patch.dict(os.environ, env, clear=True):
            return WebSettings.from_env()

    def test_web_settings_require_explicit_isolated_configuration(self):
        required = tuple(BASE_ENV)
        for missing in required:
            with self.subTest(missing=missing):
                env = BASE_ENV.copy()
                env.pop(missing)
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(SettingsError):
                        WebSettings.from_env()

        with self.assertRaises(SettingsError):
            self.load_settings(AMEBA_WEB_ENV="staging", AMEBA_STAGING_GATE_USER="tester")

        with self.assertRaises(SettingsError):
            self.load_settings(AMEBA_WEB_ENV="staging", AMEBA_STAGING_GATE_PASSWORD="secret")

        with self.assertRaises(SettingsError):
            self.load_settings(AMEBA_WEB_DB_PATH="/data/questions.db")

    def test_local_defaults_bind_web_server_to_container_interface(self):
        settings = self.load_settings()

        self.assertEqual(settings.db_path, "/tmp/ameba-web-test.db")
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 8080)
        self.assertEqual(settings.session_ttl_seconds, 2_592_000)
        self.assertEqual(settings.admin_ids, frozenset())
        self.assertEqual(settings.environment, "local")

    def test_malformed_port_is_rejected(self):
        with self.assertRaises(SettingsError):
            self.load_settings(AMEBA_WEB_PORT="not-a-port")

    def test_invalid_telegram_login_bot_username_is_rejected(self):
        with self.assertRaises(SettingsError):
            self.load_settings(AMEBA_TELEGRAM_LOGIN_BOT_USERNAME="not a username")

    def test_staging_requires_both_gate_credentials(self):
        settings = self.load_settings(
            AMEBA_WEB_ENV="staging",
            AMEBA_STAGING_GATE_USER="tester",
            AMEBA_STAGING_GATE_PASSWORD="long-random-password",
        )

        self.assertEqual(settings.staging_gate_user, "tester")
        self.assertEqual(settings.staging_gate_password, "long-random-password")


if __name__ == "__main__":
    unittest.main()
