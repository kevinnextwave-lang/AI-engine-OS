import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuthEvent(enum.StrEnum):
    SIGNUP = "signup"
    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    TOKEN_REFRESHED = "token_refreshed"  # noqa: S105
    REFRESH_REUSE_DETECTED = "refresh_reuse_detected"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"


class AuthAuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of authentication events.

    user_id is nullable so failed logins for unknown emails can be recorded
    without leaking whether the account exists. Never store secrets here.
    """

    __tablename__ = "auth_audit_logs"
    __table_args__ = (
        Index("ix_auth_audit_logs_created_at", "created_at"),
        Index("ix_auth_audit_logs_user_event", "user_id", "event"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event: Mapped[AuthEvent] = mapped_column(
        Enum(AuthEvent, name="auth_event", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
