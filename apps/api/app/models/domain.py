import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Domain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A website owned by a project. Organization-owned through project_id."""

    __tablename__ = "domains"
    __table_args__ = (
        Index("ix_domains_hostname", "hostname"),
        Index("ix_domains_created_at", "created_at"),
        # At most one primary domain per project (partial unique index).
        Index(
            "uq_domains_project_primary",
            "project_id",
            unique=True,
            postgresql_where="is_primary",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    project: Mapped["Project"] = relationship(back_populates="domains")
