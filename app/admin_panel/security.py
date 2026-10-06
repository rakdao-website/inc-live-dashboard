"""Password hashing and signed session tokens (standard library only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

from app.config import settings

logger = logging.getLogger("admin.security")

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_KEYLEN = 32
MIN_PASSWORD_LENGTH = 12

_ephemeral_secret: str | None = None


class AdminSecretMissing(RuntimeError):
    """Raised when production starts without ADMIN_SESSION_SECRET."""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_KEYLEN
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _b64(salt), _b64(digest)
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=_SCRYPT_KEYLEN,
        )
        return hmac.compare_digest(digest, _unb64(digest_b64))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Password must mix upper case, lower case and a digit."
    return None


def get_session_secret() -> bytes:
    global _ephemeral_secret
    if settings.admin_session_secret:
        if len(settings.admin_session_secret) < 32:
            raise AdminSecretMissing("ADMIN_SESSION_SECRET must be at least 32 characters.")
        return settings.admin_session_secret.encode("utf-8")
    if settings.environment.lower() in {"production", "prod", "staging"}:
        raise AdminSecretMissing("ADMIN_SESSION_SECRET is required when ENVIRONMENT is production.")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        logger.warning(
            "ADMIN_SESSION_SECRET is not set; using a random per-process secret. "
            "Admin sessions will end on every restart."
        )
    return _ephemeral_secret.encode("utf-8")


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def sign_token(session_id: str, expires_at: int) -> str:
    body = _b64(json.dumps({"sid": session_id, "exp": expires_at}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(get_session_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_token(token: str | None) -> str | None:
    """Return the session id if the signature is valid and not expired."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    expected = _b64(hmac.new(get_session_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
        if int(payload["exp"]) < int(time.time()):
            return None
        return str(payload["sid"])
    except (ValueError, KeyError, TypeError):
        return None


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# Verified against when the username does not exist, so a missing user and a
# wrong password take the same time.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
