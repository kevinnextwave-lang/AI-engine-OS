import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.membership import Membership
    from app.models.project import Project


class OrganizationPlan(enum.StrEnum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"
    AGENCY = "agency"
    ENTERPRISE = "enterprise"


class OrganizationStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Tenant root. Every organization-owned resource references organizations.id
    (directly, or through its project for project-scoped resources)."""

    __tablename__ = "organizations"
    __table_args__ = (Index("ix_organizations_created_at", "created_at"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[OrganizationPlan] = mapped_column(
        Enum(OrganizationPlan, name="organization_plan", values_callable=_values),
        nullable=False,
        default=OrganizationPlan.FREE,
        server_default=OrganizationPlan.FREE.value,
    )
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, name="organization_status", values_callable=_values),
        nullable=False,
        default=OrganizationStatus.ACTIVE,
        server_default=OrganizationStatus.ACTIVE.value,
    )

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
