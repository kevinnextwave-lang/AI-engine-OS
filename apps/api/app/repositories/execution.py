import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompts import (
    AiResponse,
    AiUsageRecord,
    BatchStatus,
    PromptRun,
    PromptRunBatch,
    PromptRunStatus,
)


class BatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, batch_id: uuid.UUID) -> PromptRunBatch | None:
        # Counters are bumped by workers via UPDATE; always read the current row.
        return await self._session.get(PromptRunBatch, batch_id, populate_existing=True)

    async def add(self, batch: PromptRunBatch) -> PromptRunBatch:
        self._session.add(batch)
        await self._session.flush()
        return batch

    async def list_for_set(
        self, prompt_set_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[PromptRunBatch], int]:
        base = select(PromptRunBatch).where(PromptRunBatch.prompt_set_id == prompt_set_id)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(PromptRunBatch.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def cancel_queued_runs(self, batch_id: uuid.UUID) -> int:
        """Flip every still-queued run of the batch to cancelled; returns how many."""
        result = await self._session.execute(
            update(PromptRun)
            .where(PromptRun.batch_id == batch_id, PromptRun.status == PromptRunStatus.QUEUED)
            .values(status=PromptRunStatus.CANCELLED, completed_at=datetime.now(UTC))
        )
        count = int(getattr(result, "rowcount", 0) or 0)
        if count:
            await self._session.execute(
                update(PromptRunBatch)
                .where(PromptRunBatch.id == batch_id)
                .values(cancelled_runs=PromptRunBatch.cancelled_runs + count)
            )
        return count

    async def record_outcome(
        self, batch_id: uuid.UUID, status: PromptRunStatus
    ) -> PromptRunBatch | None:
        """Atomically bump the counter for a finished run and finalize the batch
        when every run has finished. Returns the refreshed batch."""
        column = {
            PromptRunStatus.COMPLETED: PromptRunBatch.completed_runs,
            PromptRunStatus.FAILED: PromptRunBatch.failed_runs,
            PromptRunStatus.CANCELLED: PromptRunBatch.cancelled_runs,
        }[status]
        await self._session.execute(
            update(PromptRunBatch)
            .where(PromptRunBatch.id == batch_id)
            .values({column.key: column + 1})
        )
        return await self.finalize_if_done(batch_id)

    async def finalize_if_done(self, batch_id: uuid.UUID) -> PromptRunBatch | None:
        batch = await self._session.get(PromptRunBatch, batch_id, populate_existing=True)
        if batch is None:
            return None
        if batch.finished_runs < batch.total_runs:
            return batch
        if batch.status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED):
            return batch
        if (
            batch.status == BatchStatus.CANCELLING
            or batch.cancelled_runs
            and batch.completed_runs == 0
            and batch.failed_runs == 0
        ):
            batch.status = BatchStatus.CANCELLED
        elif batch.completed_runs == 0 and batch.failed_runs > 0:
            batch.status = BatchStatus.FAILED
        else:
            batch.status = BatchStatus.COMPLETED
        batch.completed_at = datetime.now(UTC)
        await self._session.flush()
        return batch

    async def mark_running(self, batch_id: uuid.UUID) -> None:
        await self._session.execute(
            update(PromptRunBatch)
            .where(PromptRunBatch.id == batch_id, PromptRunBatch.status == BatchStatus.QUEUED)
            .values(status=BatchStatus.RUNNING, started_at=datetime.now(UTC))
        )


class PromptRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: uuid.UUID) -> PromptRun | None:
        return await self._session.get(PromptRun, run_id, populate_existing=True)

    async def claim(self, run_id: uuid.UUID) -> PromptRun | None:
        """Move a queued run to running (first attempt) — returns None if it was
        cancelled or already taken, so a late worker never overwrites a cancel."""
        result = await self._session.execute(
            update(PromptRun)
            .where(PromptRun.id == run_id, PromptRun.status == PromptRunStatus.QUEUED)
            .values(
                status=PromptRunStatus.RUNNING,
                started_at=func.coalesce(PromptRun.started_at, datetime.now(UTC)),
                attempts=PromptRun.attempts + 1,
            )
            .returning(PromptRun.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self._session.get(PromptRun, run_id, populate_existing=True)

    async def requeue(self, run: PromptRun) -> None:
        """Back to queued for a retry; a cancel between attempts is honoured by claim()."""
        run.status = PromptRunStatus.QUEUED
        await self._session.flush()

    async def list_for_batch(
        self,
        batch_id: uuid.UUID,
        *,
        status: PromptRunStatus | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[PromptRun], int]:
        base = select(PromptRun).where(PromptRun.batch_id == batch_id)
        if status is not None:
            base = base.where(PromptRun.status == status)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(PromptRun.created_at).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def responses_for_runs(self, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, AiResponse]:
        if not run_ids:
            return {}
        rows = await self._session.scalars(
            select(AiResponse).where(AiResponse.prompt_run_id.in_(run_ids))
        )
        return {r.prompt_run_id: r for r in rows.all()}

    async def usage_for_batch(self, batch_id: uuid.UUID) -> dict[str, object]:
        row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(AiUsageRecord.input_tokens), 0),
                    func.coalesce(func.sum(AiUsageRecord.output_tokens), 0),
                    func.coalesce(func.sum(AiUsageRecord.estimated_cost), 0),
                )
                .select_from(AiUsageRecord)
                .join(PromptRun, PromptRun.id == AiUsageRecord.prompt_run_id)
                .where(PromptRun.batch_id == batch_id)
            )
        ).one()
        return {
            "input_tokens": int(row[0]),
            "output_tokens": int(row[1]),
            "estimated_cost": str(row[2]),
        }
