import hashlib
import hmac
import unittest
from urllib.parse import urlencode

from webapp_auth import TelegramIdentity, validate_telegram_login


BOT_TOKEN = "123456:secret"


def signed_payload(**overrides):
    data = {
        "id": "123456789",
        "first_name": "Ruslan",
        "username": "ruslan11",
        "photo_url": "https://example.test/photo.jpg",
        "auth_date": "1700000000",
    } | overrides
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


class TelegramLoginTests(unittest.TestCase):
    def test_valid_payload_returns_verified_identity(self):
        identity = validate_telegram_login(signed_payload(), BOT_TOKEN, now=1700000100)
        self.assertEqual(
            identity,
            TelegramIdentity(123456789, "Ruslan", "ruslan11", "https://example.test/photo.jpg"),
        )

    def test_login_rejects_invalid_hash_and_stale_auth_date(self):
        payload = signed_payload()
        payload["username"] = "tampered"
        self.assertIsNone(validate_telegram_login(payload, BOT_TOKEN, now=1700000100))
        self.assertIsNone(validate_telegram_login(signed_payload(), BOT_TOKEN, now=1700000400))

    def test_rejects_missing_hash_malformed_id_and_future_timestamp(self):
        payload = signed_payload()
        del payload["hash"]
        self.assertIsNone(validate_telegram_login(payload, BOT_TOKEN, now=1700000100))
        self.assertIsNone(validate_telegram_login(signed_payload(id="0"), BOT_TOKEN, now=1700000100))
        self.assertIsNone(validate_telegram_login(signed_payload(auth_date="1700000101"), BOT_TOKEN, now=1700000100))


if __name__ == "__main__":
    unittest.main()
