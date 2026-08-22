"""Build in-memory AuditContexts without a database."""

import uuid
from typing import Any

from app.models.crawl import CrawlJob, CrawlStatus, CrawlType, CrawlUrlStatus
from app.models.page_intelligence import LinkStatus, LinkType, PageLink
from app.seo.context import AuditContext, PageSnapshot, UrlOutcome
from app.seo.findings import Finding

ROOT = "https://www.acme.com/"


def page(
    url: str,
    *,
    status: int = 200,
    title: str | None = "A fine title for the page",
    description: str | None = "A meta description that is long enough to be useful to readers.",
    canonical: str | None = "self",
    canonical_count: int | None = None,
    robots: str | None = None,
    headings: dict[str, Any] | None = None,
    viewport: str | None = "width=device-width",
    lang: str | None = "en",
    charset: str | None = "utf-8",
    doctype: bool = True,
    title_count: int | None = None,
    depth: int | None = 1,
) -> PageSnapshot:
    canonical_url = url if canonical == "self" else canonical
    return PageSnapshot(
        id=uuid.uuid4(),
        url=url,
        http_status=status,
        title=title,
        meta_description=description,
        canonical_url=canonical_url,
        canonical_count=canonical_count
        if canonical_count is not None
        else int(bool(canonical_url)),
        language=lang,
        html_lang=lang,
        robots_meta=robots,
        viewport=viewport,
        charset=charset,
        has_doctype=doctype,
        title_count=title_count if title_count is not None else int(bool(title)),
        word_count=300,
        heading_observations=headings
        if headings is not None
        else {"h1_count": 1, "missing_h1": False, "multiple_h1": False},
        depth=depth,
        is_duplicate_of_id=None,
    )


def link(
    source: PageSnapshot,
    target: PageSnapshot | None,
    *,
    status: LinkStatus = LinkStatus.OK,
    href: str | None = None,
) -> PageLink:
    return PageLink(
        page_id=source.id,
        project_id=uuid.uuid4(),
        href=href or (target.url if target else "https://www.acme.com/missing"),
        normalized_url=href or (target.url if target else "https://www.acme.com/missing"),
        anchor_text="x",
        link_type=LinkType.INTERNAL,
        status=status,
        target_page_id=target.id if target else None,
        target_http_status=200 if target else 404,
        position=0,
    )


def context(
    pages: list[PageSnapshot],
    *,
    links: list[PageLink] | None = None,
    urls: list[UrlOutcome] | None = None,
    site: dict[str, Any] | None = None,
    root: str = ROOT,
) -> AuditContext:
    links = links or []
    incoming: dict[uuid.UUID, list[PageLink]] = {}
    for p in pages:
        p.outgoing = [ln for ln in links if ln.page_id == p.id]
    for ln in links:
        if ln.target_page_id is not None and ln.status != LinkStatus.INVALID:
            incoming.setdefault(ln.target_page_id, []).append(ln)
    job = CrawlJob(
        project_id=uuid.uuid4(),
        root_url=root,
        crawl_type=CrawlType.FULL,
        status=CrawlStatus.COMPLETED,
        max_pages=10,
        max_depth=3,
    )
    return AuditContext(
        project_id=job.project_id,
        crawl_job=job,
        root_url=root,
        root_host="www.acme.com",
        pages=pages,
        urls=urls
        if urls is not None
        else [
            UrlOutcome(p.url, CrawlUrlStatus.CRAWLED, p.http_status, p.url, [], None, p.depth or 0)
            for p in pages
        ],
        site=site if site is not None else {"robots_txt": {"checked": True, "present": True}},
        incoming=incoming,
    )


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


def by_code(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]
