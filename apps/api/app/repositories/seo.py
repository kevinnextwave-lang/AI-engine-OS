import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.seo import (
    ObservationCategory,
    ObservationStatus,
    SeoAudit,
    SeoObservation,
    Severity,
)


class SeoAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, audit_id: uuid.UUID) -> SeoAudit | None:
        return await self._session.get(SeoAudit, audit_id)

    async def add(self, audit: SeoAudit) -> SeoAudit:
        self._session.add(audit)
        await self._session.flush()
        return audit

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[SeoAudit], int]:
        base = select(SeoAudit).where(SeoAudit.project_id == project_id)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(SeoAudit.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)


class SeoObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, observation_id: uuid.UUID) -> SeoObservation | None:
        return await self._session.get(SeoObservation, observation_id)

    async def list_for_audit(
        self,
        audit_id: uuid.UUID,
        *,
        category: ObservationCategory | None = None,
        severity: Severity | None = None,
        status: ObservationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SeoObservation], int]:
        base = select(SeoObservation).where(SeoObservation.audit_id == audit_id)
        if category is not None:
            base = base.where(SeoObservation.category == category)
        if severity is not None:
            base = base.where(SeoObservation.severity == severity)
        if status is not None:
            base = base.where(SeoObservation.status == status)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        # Most severe first, then stable by code/url for deterministic paging.
        order = case(
            {s: i for i, s in enumerate(Severity)}, value=SeoObservation.severity, else_=99
        )
        rows = await self._session.scalars(
            base.order_by(order, SeoObservation.code, SeoObservation.url, SeoObservation.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)
