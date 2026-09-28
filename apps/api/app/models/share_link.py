"""Public share links: tokenized read-only access to a project's report.

The raw token appears exactly once, in the create response; only its keyed
hash (HMAC-SHA256, same scheme as refresh/account tokens) is stored, so a
database leak alone cannot reconstruct working share URLs. Revocation is a
timestamp — the row stays for auditability ("who created what, when, and
when it was cut off").
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProjectShareLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_share_links"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Optional human label ("Client X monthly report").
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
