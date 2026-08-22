import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import (
    ACTIVE_CRAWL_STATUSES,
    CrawlJob,
    CrawlStatus,
    CrawlUrl,
    CrawlUrlStatus,
    PageVersion,
    WebsitePage,
)


class CrawlJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: uuid.UUID) -> CrawlJob | None:
        return await self._session.get(CrawlJob, job_id)

    async def get_in_project(self, project_id: uuid.UUID, job_id: uuid.UUID) -> CrawlJob | None:
        stmt = select(CrawlJob).where(CrawlJob.id == job_id, CrawlJob.project_id == project_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def active_for_project(self, project_id: uuid.UUID) -> CrawlJob | None:
        stmt = select(CrawlJob).where(
            CrawlJob.project_id == project_id, CrawlJob.status.in_(list(ACTIVE_CRAWL_STATUSES))
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[CrawlJob], int]:
        base = select(CrawlJob).where(CrawlJob.project_id == project_id)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(CrawlJob.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def add(self, job: CrawlJob) -> CrawlJob:
        self._session.add(job)
        await self._session.flush()
        return job

    async def is_cancel_requested(self, job_id: uuid.UUID) -> bool:
        stmt = select(CrawlJob.cancel_requested, CrawlJob.status).where(CrawlJob.id == job_id)
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return True
        cancel_requested, status = row
        return bool(cancel_requested) or status == CrawlStatus.CANCELLED

    async def request_cancel(self, job: CrawlJob) -> None:
        job.cancel_requested = True
        if job.status == CrawlStatus.QUEUED:
            # Not picked up by a worker yet: finalize immediately.
            job.status = CrawlStatus.CANCELLED
            job.completed_at = job.completed_at or datetime.now(UTC)
        await self._session.flush()


class CrawlUrlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, rows: Sequence[CrawlUrl]) -> None:
        self._session.add_all(rows)
        await self._session.flush()

    async def mark(
        self,
        job_id: uuid.UUID,
        normalized_url: str,
        *,
        status: CrawlUrlStatus,
        http_status: int | None = None,
        content_type: str | None = None,
        page_id: uuid.UUID | None = None,
        error_message: str | None = None,
        crawled_at: datetime | None = None,
        response_time_ms: int | None = None,
        final_url: str | None = None,
        redirect_chain: list[str] | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status}
        if final_url is not None:
            values["final_url"] = final_url
        if redirect_chain is not None:
            values["redirect_chain"] = redirect_chain
        if response_time_ms is not None:
            values["response_time_ms"] = response_time_ms
        if http_status is not None:
            values["http_status"] = http_status
        if content_type is not None:
            values["content_type"] = content_type[:120]
        if page_id is not None:
            values["page_id"] = page_id
        if error_message is not None:
            values["error_message"] = error_message[:2000]
        if crawled_at is not None:
            values["crawled_at"] = crawled_at
        await self._session.execute(
            update(CrawlUrl)
            .where(CrawlUrl.crawl_job_id == job_id, CrawlUrl.normalized_url == normalized_url)
            .values(**values)
        )

    async def list_for_job(
        self,
        job_id: uuid.UUID,
        *,
        status: CrawlUrlStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[CrawlUrl], int]:
        base = select(CrawlUrl).where(CrawlUrl.crawl_job_id == job_id)
        if status is not None:
            base = base.where(CrawlUrl.status == status)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(CrawlUrl.discovered_at, CrawlUrl.depth, CrawlUrl.normalized_url)
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)


class WebsitePageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_normalized_url(
        self, project_id: uuid.UUID, normalized_url: str
    ) -> WebsitePage | None:
        stmt = select(WebsitePage).where(
            WebsitePage.project_id == project_id, WebsitePage.normalized_url == normalized_url
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_duplicate(
        self, project_id: uuid.UUID, content_hash: str, *, exclude_page_id: uuid.UUID | None
    ) -> WebsitePage | None:
        stmt = (
            select(WebsitePage)
            .where(
                WebsitePage.project_id == project_id,
                WebsitePage.content_hash == content_hash,
                WebsitePage.is_duplicate_of_id.is_(None),
            )
            .order_by(WebsitePage.first_crawled_at)
        )
        if exclude_page_id is not None:
            stmt = stmt.where(WebsitePage.id != exclude_page_id)
        return (await self._session.execute(stmt)).scalars().first()

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(WebsitePage)
            .where(WebsitePage.project_id == project_id)
        )
        return int(total or 0)

    async def get_many(self, page_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, WebsitePage]:
        if not page_ids:
            return {}
        rows = await self._session.scalars(select(WebsitePage).where(WebsitePage.id.in_(page_ids)))
        return {p.id: p for p in rows.all()}

    async def add(self, page: WebsitePage) -> WebsitePage:
        self._session.add(page)
        await self._session.flush()
        return page

    async def add_version(self, version: PageVersion) -> PageVersion:
        self._session.add(version)
        await self._session.flush()
        return version
