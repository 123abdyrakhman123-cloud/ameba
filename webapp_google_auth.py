from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str | None
    display_name: str | None
    picture: str | None


def validate_google_id_token(token: str, client_id: str) -> GoogleIdentity | None:
    if not token or not client_id:
        return None
    try:
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(token, None, client_id)
        subject = claims.get("sub")
        issuer = claims.get("iss")
        audience = claims.get("aud")
        if not isinstance(subject, str) or not subject.strip():
            return None
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            return None
        if audience != client_id:
            return None
        return GoogleIdentity(
            subject=subject,
            email=claims.get("email"),
            display_name=claims.get("name"),
            picture=claims.get("picture"),
        )
    except Exception:
        return None
