"""Password policy.

Kept separate from hashing so the rules can evolve (breach lists, zxcvbn)
without touching the crypto. Rules are deliberately simple and explainable:
length, some character variety, not containing the user's own email.
"""

import re

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
