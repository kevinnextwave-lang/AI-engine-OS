"""Single-use account action tokens (password reset, email verification).

Same storage discipline as refresh tokens: only the HMAC-SHA256 hash of the
token is stored, so a database leak alone cannot forge a reset link. Tokens
are single-use (used_at) and expire (expires_at); issuing a new token for
the same purpose invalidates nothing by itself — validation checks used_at
and expiry, and completed flows mark the token used.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AccountTokenPurpose(enum.StrEnum):
    PASSWORD_RESET = "password_reset"  # noqa: S105 - purpose label, not a secret
    EMAIL_VERIFY = "email_verify"


class AccountToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_usable(self) -> bool:
        return self.used_at is None
