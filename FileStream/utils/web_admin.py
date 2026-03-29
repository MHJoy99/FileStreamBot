import base64
import hashlib
import hmac
import secrets
import time

from FileStream.config import Telegram, Server


COOKIE_NAME = "filestream_admin_session"


def _sign_payload(payload: str) -> str:
    return hmac.new(
        Telegram.WEB_SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _decode_session_value(value: str | None) -> tuple[str, int, str] | None:
    if not value:
        return None
    try:
        decoded = base64.urlsafe_b64decode(value.encode("utf-8")).decode("utf-8")
        username, expires_at, signature = decoded.rsplit(":", 2)
        return username, int(expires_at), signature
    except Exception:
        return None


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 260000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = str(password_hash).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(expected, digest)
    except Exception:
        return False


def build_session_value(username: str) -> str:
    expires_at = int(time.time()) + Telegram.WEB_SESSION_TTL
    payload = f"{username}:{expires_at}"
    signature = _sign_payload(payload)
    raw_value = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw_value).decode("utf-8")


def validate_session_value(value: str | None) -> bool:
    decoded = _decode_session_value(value)
    if not decoded:
        return False
    username, expires_at, signature = decoded
    payload = f"{username}:{expires_at}"
    expected_signature = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False
    if int(expires_at) < int(time.time()):
        return False

    return True


def is_admin_authenticated(request) -> bool:
    return validate_session_value(request.cookies.get(COOKIE_NAME))


def get_admin_username(request) -> str:
    decoded = _decode_session_value(request.cookies.get(COOKIE_NAME))
    if not decoded:
        return ""
    username, expires_at, signature = decoded
    payload = f"{username}:{expires_at}"
    expected_signature = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return ""
    if int(expires_at) < int(time.time()):
        return ""
    return username


def attach_admin_session(response, username: str):
    response.set_cookie(
        COOKIE_NAME,
        build_session_value(username),
        httponly=True,
        secure=Server.HAS_SSL,
        samesite="Lax",
        max_age=Telegram.WEB_SESSION_TTL,
        path="/",
    )


def clear_admin_session(response):
    response.del_cookie(COOKIE_NAME, path="/")
