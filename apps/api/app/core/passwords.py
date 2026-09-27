"""Password policy.

Kept separate from hashing so the rules can evolve (breach lists, zxcvbn)
without touching the crypto. Rules are deliberately simple and explainable:
length, some character variety, not containing the user's own email —
plus an optional Have I Been Pwned breach check (k-anonymity: only the
first five hex chars of the SHA-1 ever leave the process).
"""

import hashlib
import re

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("core.passwords")

MIN_LENGTH = 10
MAX_LENGTH = 128

_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT_OR_SYMBOL = re.compile(r"[^A-Za-z]")
_REPEATED = re.compile(r"^(.)\1+$")

_COMMON = {
    "password1!",
    "password123",
    "qwertyuiop",
    "1234567890",
    "abcdefghij",
    "letmein123",
    "iloveyou123",
    "welcome123",
}


def validate_password(password: str, *, email: str | None = None) -> list[str]:
    """Return a list of human-readable problems; empty list means the password is acceptable."""
    problems: list[str] = []

    if len(password) < MIN_LENGTH:
        problems.append(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"Password must be at most {MAX_LENGTH} characters")
    if password.strip() != password:
        problems.append("Password must not start or end with whitespace")
    if not _HAS_LETTER.search(password):
        problems.append("Password must contain at least one letter")
    if not _HAS_DIGIT_OR_SYMBOL.search(password):
        problems.append("Password must contain at least one number or symbol")
    if _REPEATED.match(password):
        problems.append("Password must not be a single repeated character")
    if password.lower() in _COMMON:
        problems.append("Password is too common")

    if email:
        local_part = email.split("@", 1)[0].lower()
        if len(local_part) >= 4 and local_part in password.lower():
            problems.append("Password must not contain your email address")

    return problems


BREACHED_MESSAGE = (
    "This password appears in known data breaches — choose one you haven't used elsewhere."
)

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"


async def is_breached(password: str, *, client: httpx.AsyncClient | None = None) -> bool:
    """Have I Been Pwned range check (k-anonymity). Off unless
    HIBP_PASSWORD_CHECK=true; FAILS OPEN — an unreachable breach API must
    never block signups or resets, it just loses this one defence."""
    settings = get_settings()
    if not settings.hibp_password_check:
        return False
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        if client is not None:
            resp = await client.get(f"{_HIBP_RANGE_URL}{prefix}", timeout=3.0)
        else:
            async with httpx.AsyncClient(timeout=3.0) as own:
                resp = await own.get(f"{_HIBP_RANGE_URL}{prefix}", headers={"Add-Padding": "true"})
        resp.raise_for_status()
        for line in resp.text.splitlines():
            candidate, _, count = line.strip().partition(":")
            if candidate.upper() == suffix:
                return int(count or 0) > 0
        return False
    except Exception as exc:  # noqa: BLE001 - fail open by design
        log.warning("hibp_check_unavailable", error=type(exc).__name__)
        return False
