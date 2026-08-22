"""In-memory snapshot of everything the checks need. Built once per audit from
crawl + page-intelligence rows; checks are pure functions over it."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.urls import CrawlURLError, normalize_crawl_url
from app.models.crawl import CrawlJob, CrawlUrl, CrawlUrlStatus, WebsitePage
from app.models.page_intelligence import (
    LinkStatus,
    LinkType,
    PageContentMetrics,
    PageLink,
    PageMetadata,
    PageStructuredData,
)


@dataclass
class PageSnapshot:
    id: uuid.UUID
    url: str
    http_status: int
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    canonical_count: int
    language: str | None
    html_lang: str | None
    robots_meta: str | None
    viewport: str | None
    charset: str | None
    has_doctype: bool
    title_count: int
    word_count: int
    heading_observations: dict[str, Any]
    depth: int | None
    is_duplicate_of_id: uuid.UUID | None
    structured: list[PageStructuredData] = field(default_factory=list)
    outgoing: list[PageLink] = field(default_factory=list)

    @property
    def is_html_ok(self) -> bool:
        return self.http_status == 200

    @property
    def noindex(self) -> bool:
        directives = {d.strip().lower() for d in (self.robots_meta or "").split(",")}
        return "noindex" in directives or "none" in directives

    @property
    def indexable(self) -> bool:
        """200, not noindex, and not canonicalized elsewhere."""
        return (
            self.is_html_ok
            and not self.noindex
            and (self.canonical_url is None or self.canonical_url == self.url)
        )


@dataclass
class UrlOutcome:
    url: str
    status: CrawlUrlStatus
    http_status: int | None
    final_url: str | None
    redirect_chain: list[str]
    error_message: str | None
    depth: int


@dataclass
class AuditContext:
    project_id: uuid.UUID
    crawl_job: CrawlJob
    root_url: str
    root_host: str
    pages: list[PageSnapshot]
    urls: list[UrlOutcome]
    site: dict[str, Any]
    incoming: dict[uuid.UUID, list[PageLink]]  # target page -> links pointing at it
    by_id: dict[uuid.UUID, PageSnapshot] = field(default_factory=dict)
    by_url: dict[str, PageSnapshot] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_id = {p.id: p for p in self.pages}
        self.by_url = {p.url: p for p in self.pages}

    @property
    def html_pages(self) -> list[PageSnapshot]:
        return [p for p in self.pages if p.is_html_ok]

    @property
    def indexable_pages(self) -> list[PageSnapshot]:
        return [p for p in self.pages if p.indexable]


async def build_context(session: AsyncSession, job: CrawlJob) -> AuditContext:
    project_id = job.project_id
    pages = list(
        (
            await session.scalars(select(WebsitePage).where(WebsitePage.project_id == project_id))
        ).all()
    )
    page_ids = [p.id for p in pages]
    meta = {
        m.page_id: m
        for m in (
            await session.scalars(select(PageMetadata).where(PageMetadata.project_id == project_id))
        ).all()
    }
    metrics = {
        m.page_id: m
        for m in (
            await session.scalars(
                select(PageContentMetrics).where(PageContentMetrics.project_id == project_id)
            )
        ).all()
    }
    structured: dict[uuid.UUID, list[PageStructuredData]] = defaultdict(list)
    for sd in (
        await session.scalars(
            select(PageStructuredData).where(PageStructuredData.project_id == project_id)
        )
    ).all():
        structured[sd.page_id].append(sd)
    links = list(
        (await session.scalars(select(PageLink).where(PageLink.project_id == project_id))).all()
    )
    outgoing: dict[uuid.UUID, list[PageLink]] = defaultdict(list)
    incoming: dict[uuid.UUID, list[PageLink]] = defaultdict(list)
    for link in links:
        outgoing[link.page_id].append(link)
        if (
            link.link_type == LinkType.INTERNAL
            and link.target_page_id is not None
            and link.status != LinkStatus.INVALID
            and link.target_page_id != link.page_id
        ):
            incoming[link.target_page_id].append(link)

    crawl_urls = list(
        (await session.scalars(select(CrawlUrl).where(CrawlUrl.crawl_job_id == job.id))).all()
    )
    depth_by_page: dict[uuid.UUID, int] = {}
    for cu in crawl_urls:
        if cu.page_id is not None:
            depth_by_page[cu.page_id] = min(depth_by_page.get(cu.page_id, cu.depth), cu.depth)

    snapshots: list[PageSnapshot] = []
    for p in pages:
        m = meta.get(p.id)
        c = metrics.get(p.id)
        snapshots.append(
            PageSnapshot(
                id=p.id,
                url=p.normalized_url,
                http_status=p.http_status,
                title=p.title,
                meta_description=p.meta_description,
                canonical_url=(m.canonical_url if m else None) or p.canonical_url,
                canonical_count=m.canonical_count if m else (1 if p.canonical_url else 0),
                language=p.language,
                html_lang=m.html_lang if m else None,
                robots_meta=m.robots if m else None,
                viewport=m.viewport if m else None,
                charset=m.charset if m else None,
                has_doctype=m.has_doctype if m else False,
                title_count=m.title_count if m else (1 if p.title else 0),
                word_count=c.word_count if c else (p.word_count or 0),
                heading_observations=c.heading_observations if c else {},
                depth=depth_by_page.get(p.id),
                is_duplicate_of_id=p.is_duplicate_of_id,
                structured=structured.get(p.id, []),
                outgoing=outgoing.get(p.id, []),
            )
        )
    _ = page_ids
    try:
        root = normalize_crawl_url(job.root_url)
        root_host = root.host
    except CrawlURLError:
        root_host = ""
    return AuditContext(
        project_id=project_id,
        crawl_job=job,
        root_url=job.root_url,
        root_host=root_host,
        pages=snapshots,
        urls=[
            UrlOutcome(
                url=cu.normalized_url,
                status=cu.status,
                http_status=cu.http_status,
                final_url=cu.final_url,
                redirect_chain=list(cu.redirect_chain or []),
                error_message=cu.error_message,
                depth=cu.depth,
            )
            for cu in crawl_urls
        ],
        site=(job.config or {}).get("site", {}),
        incoming=dict(incoming),
    )
