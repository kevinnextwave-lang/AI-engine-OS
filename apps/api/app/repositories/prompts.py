import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompts import (
    FunnelStage,
    Prompt,
    PromptCategory,
    PromptRun,
    PromptRunStatus,
    PromptSet,
    PromptSetStatus,
)


class PromptSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, prompt_set_id: uuid.UUID) -> PromptSet | None:
        return await self._session.get(PromptSet, prompt_set_id)

    async def add(self, prompt_set: PromptSet) -> PromptSet:
        self._session.add(prompt_set)
        await self._session.flush()
        return prompt_set

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: PromptSetStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PromptSet], int]:
        base = select(PromptSet).where(PromptSet.project_id == project_id)
        if status is not None:
            base = base.where(PromptSet.status == status)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(PromptSet.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def prompt_counts(
        self, prompt_set_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """prompt_set_id -> (total, active)."""
        if not prompt_set_ids:
            return {}
        rows = await self._session.execute(
            select(
                Prompt.prompt_set_id,
                func.count(),
                func.count().filter(Prompt.is_active.is_(True)),
            )
            .where(Prompt.prompt_set_id.in_(prompt_set_ids))
            .group_by(Prompt.prompt_set_id)
        )
        return {sid: (int(total), int(active)) for sid, total, active in rows.all()}


class PromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, prompt_id: uuid.UUID) -> Prompt | None:
        return await self._session.get(Prompt, prompt_id)

    async def add_all(self, prompts: list[Prompt]) -> None:
        self._session.add_all(prompts)
        await self._session.flush()

    async def delete(self, prompt: Prompt) -> None:
        await self._session.delete(prompt)
        await self._session.flush()

    async def texts_for_set(self, prompt_set_id: uuid.UUID) -> list[str]:
        rows = await self._session.scalars(
            select(Prompt.text).where(Prompt.prompt_set_id == prompt_set_id)
        )
        return list(rows.all())

    async def normalized_exists(self, prompt_set_id: uuid.UUID, normalized_text: str) -> bool:
        row = await self._session.scalar(
            select(Prompt.id).where(
                Prompt.prompt_set_id == prompt_set_id, Prompt.normalized_text == normalized_text
            )
        )
        return row is not None

    async def list_for_set(
        self,
        prompt_set_id: uuid.UUID,
        *,
        category: PromptCategory | None = None,
        funnel_stage: FunnelStage | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Prompt], int]:
        base = select(Prompt).where(Prompt.prompt_set_id == prompt_set_id)
        if category is not None:
            base = base.where(Prompt.category == category)
        if funnel_stage is not None:
            base = base.where(Prompt.funnel_stage == funnel_stage)
        if is_active is not None:
            base = base.where(Prompt.is_active.is_(is_active))
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(
                Prompt.priority, Prompt.quality_score.desc().nulls_last(), Prompt.created_at
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def latest_runs(self, prompt_ids: list[uuid.UUID]) -> dict[uuid.UUID, PromptRun]:
        """Most recent run per prompt (any status)."""
        if not prompt_ids:
            return {}
        rows = await self._session.scalars(
            select(PromptRun)
            .where(PromptRun.prompt_id.in_(prompt_ids))
            .order_by(PromptRun.prompt_id, PromptRun.created_at.desc())
        )
        out: dict[uuid.UUID, PromptRun] = {}
        for run in rows.all():
            out.setdefault(run.prompt_id, run)
        return out

    async def latest_completed_runs(
        self, prompt_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, PromptRun]:
        if not prompt_ids:
            return {}
        rows = await self._session.scalars(
            select(PromptRun)
            .where(
                PromptRun.prompt_id.in_(prompt_ids), PromptRun.status == PromptRunStatus.COMPLETED
            )
            .order_by(PromptRun.prompt_id, PromptRun.completed_at.desc())
        )
        out: dict[uuid.UUID, PromptRun] = {}
        for run in rows.all():
            out.setdefault(run.prompt_id, run)
        return out
