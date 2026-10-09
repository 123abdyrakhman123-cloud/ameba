import sys
import types
import unittest
from unittest.mock import patch

from webapp_google_auth import GoogleIdentity, validate_google_id_token


class GoogleLoginTests(unittest.TestCase):
    def setUp(self):
        self.verifier = unittest.mock.Mock(return_value={
            "sub": "google-subject-1",
            "email": "ruslan@example.test",
            "name": "Ruslan",
            "picture": "https://example.test/picture.jpg",
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "exp": 2000000000,
        })
        google = types.ModuleType("google")
        auth = types.ModuleType("google.auth")
        oauth2 = types.ModuleType("google.oauth2")
        id_token = types.ModuleType("google.oauth2.id_token")
        id_token.verify_oauth2_token = self.verifier
        google.auth = auth
        google.oauth2 = oauth2
        oauth2.id_token = id_token
        self.modules = patch.dict(sys.modules, {
            "google": google,
            "google.auth": auth,
            "google.oauth2": oauth2,
            "google.oauth2.id_token": id_token,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_valid_token_uses_stable_subject_and_profile_claims(self):
        identity = validate_google_id_token("signed-token", "client-id")
        self.assertEqual(identity, GoogleIdentity(
            "google-subject-1", "ruslan@example.test", "Ruslan", "https://example.test/picture.jpg"
        ))
        self.verifier.assert_called_once_with("signed-token", None, "client-id")

    def test_google_login_rejects_invalid_token_or_csrf(self):
        self.verifier.side_effect = ValueError("bad signature")
        self.assertIsNone(validate_google_id_token("bad-token", "client-id"))

    def test_rejects_missing_subject_wrong_issuer_or_audience(self):
        self.verifier.return_value = {"aud": "client-id", "iss": "https://accounts.google.com"}
        self.assertIsNone(validate_google_id_token("token", "client-id"))
        self.verifier.return_value = {"sub": "s", "aud": "client-id", "iss": "attacker.test"}
        self.assertIsNone(validate_google_id_token("token", "client-id"))
        self.verifier.return_value = {"sub": "s", "aud": "other", "iss": "https://accounts.google.com"}
        self.assertIsNone(validate_google_id_token("token", "client-id"))

    def test_email_changes_do_not_change_google_identity_key(self):
        self.verifier.return_value = {
            "sub": "stable-subject", "email": "old@example.test",
            "aud": "client-id", "iss": "https://accounts.google.com",
        }
        first = validate_google_id_token("token-1", "client-id")
        self.verifier.return_value["email"] = "new@example.test"
        second = validate_google_id_token("token-2", "client-id")
        self.assertEqual(first.subject, second.subject)
        self.assertNotEqual(first.email, second.email)


if __name__ == "__main__":
    unittest.main()
