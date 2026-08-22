import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_readiness import AiReadinessAudit, AiReadinessObservation, ReadinessCategory
from app.models.seo import Severity


class AiReadinessAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, audit_id: uuid.UUID) -> AiReadinessAudit | None:
        return await self._session.get(AiReadinessAudit, audit_id)

    async def add(self, audit: AiReadinessAudit) -> AiReadinessAudit:
        self._session.add(audit)
        await self._session.flush()
        return audit

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[AiReadinessAudit], int]:
        base = select(AiReadinessAudit).where(AiReadinessAudit.project_id == project_id)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(AiReadinessAudit.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def observations(
        self,
        audit_id: uuid.UUID,
        *,
        category: ReadinessCategory | None = None,
        severity: Severity | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[AiReadinessObservation], int]:
        base = select(AiReadinessObservation).where(AiReadinessObservation.audit_id == audit_id)
        if category is not None:
            base = base.where(AiReadinessObservation.category == category)
        if severity is not None:
            base = base.where(AiReadinessObservation.severity == severity)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        order = case(
            {s: i for i, s in enumerate(Severity)}, value=AiReadinessObservation.severity, else_=99
        )
        rows = await self._session.scalars(
            base.order_by(order, AiReadinessObservation.category, AiReadinessObservation.code)
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)
