import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Competitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A competing brand tracked by a project. Organization-owned through project_id."""

    __tablename__ = "competitors"
    __table_args__ = (
        Index("ix_competitors_hostname", "hostname"),
        Index("ix_competitors_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="competitors")
