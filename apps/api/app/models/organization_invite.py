"""Email invitations into an organization.

Same storage discipline as every other emailed token: only the HMAC-SHA256
hash is stored. Single-use (accepted_at), expiring, and role-carrying —
never OWNER; ownership is granted only by an existing owner changing a
member's role afterwards.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.membership import MembershipRole


class OrganizationInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_invites"
    __table_args__ = (Index("ix_organization_invites_org_email", "organization_id", "email"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole, name="membership_role", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=MembershipRole.MEMBER,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None and self.revoked_at is None
