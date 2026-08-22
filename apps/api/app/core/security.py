"""Password hashing and JWT primitives.

- Passwords: Argon2id (argon2-cffi defaults, OWASP-recommended).
- Access tokens: short-lived JWTs carrying the user id (sub) and a type claim.
- Refresh tokens: opaque random strings; only a SHA-256 hash is stored server-side.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # argon2id, tuned defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: uuid.UUID, *, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    now = utcnow()
    expire = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "iat", "type"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def generate_refresh_token() -> str:
    """Opaque, high-entropy refresh token handed to the client."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Deterministic hash for storing refresh tokens at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return utcnow() + timedelta(days=get_settings().refresh_token_expire_days)
