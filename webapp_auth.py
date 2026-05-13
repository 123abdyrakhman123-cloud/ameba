import hmac
import hashlib
import json
import time
from urllib.parse import parse_qs, unquote


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400 * 30) -> dict | None:
    """
    Validates Telegram WebApp initData.
    Returns user dict if valid, None otherwise.
    max_age: maximum allowed age in seconds (default 24h)
    """
    if not init_data:
        return None

    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        # Each value is a list, take first element
        data = {k: v[0] for k, v in parsed.items()}
    except Exception:
        return None

    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    # Check auth_date
    auth_date_str = data.get("auth_date", "0")
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None

    if time.time() - auth_date > max_age:
        return None

    # Build data_check_string: sorted key=value pairs joined by \n
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
    )

    # Compute secret key
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()

    # Compute hash
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    # Parse user JSON
    user_str = data.get("user")
    if not user_str:
        return None

    try:
        user = json.loads(unquote(user_str))
        return user
    except (json.JSONDecodeError, Exception):
        return None
