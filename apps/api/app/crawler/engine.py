"""Crawl engine: frontier -> fetcher -> processor -> persistence.

One engine instance runs one crawl job inside a worker process. All I/O is
async; concurrency is bounded by `CrawlSettings.concurrency` workers plus the
per-host rate limiter. Cancellation is cooperative: the engine re-reads the
job row every `status_check_interval` URLs and stops scheduling new fetches;
in-flight fetches finish (or time out) and their results are still recorded.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.crawler.fetcher import Fetcher, FetchResult
from app.crawler.frontier import Frontier, FrontierItem, Priority
from app.crawler.intelligence import analyze_page
from app.crawler.parser import ProcessedPage, process_html
from app.crawler.ratelimit import HostRateLimiter
from app.crawler.robots import RobotsCache
from app.crawler.sitemaps import discover_sitemap_urls
from app.crawler.storage import HtmlStorage, NullHtmlStorage
from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url, same_site
from app.models.crawl import (
    CrawlJob,
    CrawlStatus,
    CrawlType,
    CrawlUrl,
    CrawlUrlStatus,
    PageVersion,
    WebsitePage,
)
from app.repositories.crawl import CrawlJobRepository, CrawlUrlRepository, WebsitePageRepository
from app.repositories.page_intelligence import PageIntelligenceRepository

log = get_logger("crawler.engine")

_SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".avif",
    ".mp4", ".mp3", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4a", ".wav", ".ogg",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".dmg", ".exe", ".msi", ".apk", ".bin",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
)  # fmt: skip


@dataclass(frozen=True)
class CrawlSettings:
    max_pages: int
    max_depth: int
    concurrency: int
    allowed_hosts: frozenset[str]
    allow_subdomains: bool
    status_check_interval: int = 10
    follow_sitemaps: bool = True
    respect_robots: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "concurrency": self.concurrency,
            "allowed_hosts": sorted(self.allowed_hosts),
            "allow_subdomains": self.allow_subdomains,
            "follow_sitemaps": self.follow_sitemaps,
            "respect_robots": self.respect_robots,
        }


@dataclass
class CrawlStats:
    discovered: int = 0
    crawled: int = 0
    failed: int = 0
    skipped: int = 0
    pending_rows: list[CrawlUrl] = field(default_factory=list)


class CrawlEngine:
    def __init__(
        self,
        *,
        session: AsyncSession,
        job: CrawlJob,
        settings: CrawlSettings,
        fetcher: Fetcher,
        limiter: HostRateLimiter,
        user_agent: str,
        storage: HtmlStorage | None = None,
    ) -> None:
        self._session = session
        self._job = job
        self._settings = settings
        self._fetcher = fetcher
        self._limiter = limiter
        self._robots = RobotsCache(fetcher, user_agent)
        self._storage = storage or NullHtmlStorage()
        self._frontier = Frontier()
        self._stats = CrawlStats()
        self._jobs = CrawlJobRepository(session)
        self._urls = CrawlUrlRepository(session)
        self._pages = WebsitePageRepository(session)
        self._intel = PageIntelligenceRepository(session)
        self._root = normalize_crawl_url(job.root_url)
        self._stop = asyncio.Event()
        self._scheduled = 0
        self._db_lock = asyncio.Lock()
        self._since_check = 0
        self._skipped_urls: set[str] = set()
        self._site_facts: dict[str, Any] = {}

    # -- public ------------------------------------------------------------

    async def run(self) -> CrawlJob:
        job = self._job
        job.status = CrawlStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.config = self._settings.to_dict()
        await self._session.commit()
        log.info(
            "crawl_started",
            crawl_job_id=str(job.id),
            project_id=str(job.project_id),
            root_url=job.root_url,
            max_pages=self._settings.max_pages,
            max_depth=self._settings.max_depth,
        )
        try:
            await self._seed()
            await self._flush_discovered()
            await self._crawl_loop()
            await self._finalize_links()
            if await self._jobs.is_cancel_requested(job.id):
                job.status = CrawlStatus.CANCELLED
            elif self._stats.crawled == 0 and self._stats.failed > 0:
                job.status = CrawlStatus.FAILED
                job.error_message = "No page could be fetched"
            elif (
                self._stats.failed > 0
                or self._stats.crawled < self._frontier.seen_count - self._stats.skipped
            ):
                job.status = CrawlStatus.PARTIALLY_COMPLETED
            else:
                job.status = CrawlStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001 - job must always be finalized
            log.exception("crawl_failed", crawl_job_id=str(job.id))
            job.status = CrawlStatus.FAILED
            job.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        finally:
            job.completed_at = datetime.now(UTC)
            if self._site_facts:
                job.config = {**(job.config or {}), "site": self._site_facts}
            self._sync_counts()
            await self._session.commit()
            log.info(
                "crawl_completed",
                crawl_job_id=str(job.id),
                status=job.status.value,
                discovered=self._stats.discovered,
                crawled=self._stats.crawled,
                failed=self._stats.failed,
                skipped=self._stats.skipped,
                duration_seconds=job.duration_seconds,
            )
        return job

    # -- seeding -------------------------------------------------------------

    async def _seed(self) -> None:
        self._discover(self._root, depth=0, priority=Priority.HOMEPAGE, parent=None, source="seed")
        if self._job.crawl_type == CrawlType.SINGLE_PAGE or not self._settings.follow_sitemaps:
            return
        rules = await self._robots.rules_for(self._root) if self._settings.respect_robots else None
        candidates = rules.sitemaps if rules else []
        self._site_facts = {
            "robots_txt": {
                "checked": rules is not None,
                "present": bool(rules and rules.parser is not None and not rules.fetch_error),
                "error": rules.fetch_error if rules else None,
                "crawl_delay": rules.crawl_delay if rules else None,
                "sitemaps_declared": list(rules.sitemaps) if rules else [],
            },
            "sitemap_urls_found": 0,
        }
        try:
            sitemap_urls = await discover_sitemap_urls(self._fetcher, self._root, candidates)
            self._site_facts["sitemap_urls_found"] = len(sitemap_urls)
            for raw in sitemap_urls:
                try:
                    url = normalize_crawl_url(raw)
                except CrawlURLError:
                    continue
                self._discover(
                    url, depth=1, priority=Priority.SITEMAP, parent=None, source="sitemap"
                )
        except Exception as exc:  # noqa: BLE001 - sitemaps are best-effort
            log.warning("sitemap_discovery_failed", crawl_job_id=str(self._job.id), error=str(exc))

    # -- frontier ------------------------------------------------------------

    def _is_allowed_host(self, url: CrawlURL) -> bool:
        return any(
            same_site(url.host, host, allow_subdomains=self._settings.allow_subdomains)
            for host in self._settings.allowed_hosts
        )

    def _discover(
        self, url: CrawlURL, *, depth: int, priority: int, parent: str | None, source: str
    ) -> None:
        if self._frontier.has_seen(url.normalized):
            return
        if self._frontier.seen_count >= self._settings.max_pages:
            return
        if not self._is_allowed_host(url):
            return  # external domains are never queued (and not recorded as noise)
        if depth > self._settings.max_depth:
            return
        item = FrontierItem(
            url=url.normalized, depth=depth, priority=priority, parent_url=parent, source=source
        )
        if not self._frontier.push(item):
            return
        self._stats.discovered += 1
        status = (
            CrawlUrlStatus.SKIPPED
            if url.path.lower().endswith(_SKIP_EXTENSIONS)
            else CrawlUrlStatus.QUEUED
        )
        row = CrawlUrl(
            crawl_job_id=self._job.id,
            project_id=self._job.project_id,
            url=url.normalized,
            normalized_url=url.normalized,
            parent_url=parent,
            depth=depth,
            priority=priority,
            status=status,
            error_message="skipped by extension" if status == CrawlUrlStatus.SKIPPED else None,
        )
        self._stats.pending_rows.append(row)
        if status == CrawlUrlStatus.SKIPPED:
            self._stats.skipped += 1
            # Pop it from the heap lazily: mark so the worker skips it.
            self._skipped_urls.add(url.normalized)
        log.debug("url_discovered", crawl_job_id=str(self._job.id), url=url.normalized, depth=depth)

    async def _flush_discovered(self) -> None:
        if not self._stats.pending_rows:
            return
        rows, self._stats.pending_rows = self._stats.pending_rows, []
        async with self._db_lock:
            await self._urls.add_many(rows)
            self._sync_counts()
            await self._session.commit()

    # -- crawl loop ------------------------------------------------------------

    async def _crawl_loop(self) -> None:
        workers = [asyncio.create_task(self._worker(i)) for i in range(self._settings.concurrency)]
        await asyncio.gather(*workers)
        await self._flush_discovered()

    async def _should_stop(self) -> bool:
        if self._stop.is_set():
            return True
        self._since_check += 1
        if self._since_check >= self._settings.status_check_interval:
            self._since_check = 0
            async with self._db_lock:
                if await self._jobs.is_cancel_requested(self._job.id):
                    self._stop.set()
                    log.info("crawl_cancel_observed", crawl_job_id=str(self._job.id))
                    return True
        return False

    async def _worker(self, index: int) -> None:
        while True:
            if await self._should_stop():
                return
            if self._stats.crawled + self._stats.failed >= self._settings.max_pages:
                self._stop.set()
                return
            item = self._frontier.pop()
            if item is None:
                # Queue drained for now; other workers may still discover links.
                if self._scheduled == 0:
                    return
                await asyncio.sleep(0.05)
                if len(self._frontier) == 0 and self._scheduled == 0:
                    return
                continue
            if item.url in self._skipped_urls:
                continue
            self._scheduled += 1
            try:
                await self._process_item(item)
            finally:
                self._scheduled -= 1
            await self._flush_discovered()

    async def _process_item(self, item: FrontierItem) -> None:
        url = normalize_crawl_url(item.url)
        job_id = self._job.id

        if self._settings.respect_robots:
            rules = await self._robots.rules_for(url)
            if rules.fetch_error and rules.fetch_error.startswith("blocked"):
                # The host itself is unsafe (SSRF policy); this is a failure, not a robots skip.
                await self._record_failure(item, rules.fetch_error)
                return
            if rules.crawl_delay:
                self._limiter.set_delay(url.host, rules.crawl_delay)
            if not self._robots.allows(rules, url.normalized):
                await self._record_skip(item, "disallowed by robots.txt")
                return

        await self._limiter.acquire(url.host)
        try:
            async with self._db_lock:
                await self._urls.mark(job_id, item.url, status=CrawlUrlStatus.CRAWLING)
            result = await self._fetcher.fetch(url)
        finally:
            self._limiter.release(url.host)

        if result.skipped_reason:
            await self._record_skip(item, result.skipped_reason, result)
            return
        if result.error or result.status_code is None:
            await self._record_failure(item, result.error or "no response", result)
            return
        if result.body is None or not result.is_html:
            await self._record_skip(item, "no HTML body", result)
            return

        try:
            processed = process_html(result.body, normalize_crawl_url(result.final_url))
        except Exception as exc:  # noqa: BLE001 - parser errors become page failures
            await self._record_failure(item, f"processing error: {type(exc).__name__}", result)
            return

        await self._persist_page(item, result, processed)
        self._stats.crawled += 1
        log.info(
            "page_processed",
            crawl_job_id=str(job_id),
            url=item.url,
            http_status=result.status_code,
            word_count=processed.word_count,
            links=len(processed.links),
        )
        if result.status_code >= 400:
            return
        if not processed.robots_nofollow and item.depth < self._settings.max_depth:
            self._discover_links(item, processed, result)

    def _discover_links(
        self, item: FrontierItem, processed: ProcessedPage, result: FetchResult
    ) -> None:
        for link in processed.links:
            if link.nofollow:
                continue
            priority = Priority.NAVIGATION if link.in_navigation else Priority.CONTENT
            self._discover(
                link.url,
                depth=item.depth + 1,
                priority=priority,
                parent=result.final_url,
                source="link",
            )
        if processed.canonical_url and processed.canonical_url != result.final_url:
            try:
                canonical = normalize_crawl_url(processed.canonical_url)
            except CrawlURLError:
                return
            self._discover(
                canonical,
                depth=item.depth,
                priority=Priority.CONTENT,
                parent=result.final_url,
                source="link",
            )

    async def _finalize_links(self) -> None:
        async with self._db_lock:
            updated = await self._intel.resolve_internal_links(self._job.project_id)
            await self._session.commit()
        log.info("links_resolved", crawl_job_id=str(self._job.id), updated=updated)

    # -- persistence ----------------------------------------------------------

    async def _record_skip(
        self, item: FrontierItem, reason: str, result: FetchResult | None = None
    ) -> None:
        self._stats.skipped += 1
        log.info("url_skipped", crawl_job_id=str(self._job.id), url=item.url, reason=reason)
        async with self._db_lock:
            await self._urls.mark(
                self._job.id,
                item.url,
                status=CrawlUrlStatus.SKIPPED,
                http_status=result.status_code if result else None,
                content_type=result.content_type if result else None,
                error_message=reason,
                crawled_at=datetime.now(UTC),
            )

    async def _record_failure(
        self, item: FrontierItem, reason: str, result: FetchResult | None = None
    ) -> None:
        self._stats.failed += 1
        log.warning("fetch_failed", crawl_job_id=str(self._job.id), url=item.url, error=reason)
        async with self._db_lock:
            await self._urls.mark(
                self._job.id,
                item.url,
                status=CrawlUrlStatus.FAILED,
                http_status=result.status_code if result else None,
                error_message=reason,
                crawled_at=datetime.now(UTC),
                final_url=result.final_url if result else None,
                redirect_chain=list(result.redirect_chain) if result else None,
            )

    async def _persist_page(
        self, item: FrontierItem, result: FetchResult, processed: ProcessedPage
    ) -> WebsitePage:
        now = datetime.now(UTC)
        project_id = self._job.project_id
        mime = result.mime_type or "text/html"
        async with self._db_lock:
            page = await self._pages.get_by_normalized_url(project_id, result.final_url)
            is_new = page is None
            if page is None:
                page = WebsitePage(
                    project_id=project_id,
                    url=result.final_url,
                    normalized_url=result.final_url,
                    http_status=result.status_code or 0,
                    content_type=mime,
                    first_crawled_at=now,
                    last_crawled_at=now,
                )
                await self._pages.add(page)
            changed = page.content_hash != processed.content_hash
            page.url = result.final_url
            page.canonical_url = processed.canonical_url
            page.http_status = result.status_code or 0
            page.content_type = mime
            page.title = processed.title
            page.meta_description = processed.meta_description
            page.language = processed.language
            page.word_count = processed.word_count
            page.html_hash = processed.html_hash
            page.content_hash = processed.content_hash
            page.last_crawled_at = now
            duplicate = await self._pages.find_duplicate(
                project_id, processed.content_hash, exclude_page_id=page.id
            )
            page.is_duplicate_of_id = duplicate.id if duplicate else None

            intel = analyze_page(
                result.body or b"",
                normalize_crawl_url(result.final_url),
                allowed_hosts=self._settings.allowed_hosts,
                allow_subdomains=self._settings.allow_subdomains,
            )
            page.word_count = intel.content.word_count
            page.language = intel.language.code or processed.language
            version = PageVersion(
                page_id=page.id,
                project_id=project_id,
                crawl_job_id=self._job.id,
                http_status=result.status_code or 0,
                html_hash=processed.html_hash,
                content_hash=processed.content_hash,
                title=processed.title,
                meta_description=processed.meta_description,
                word_count=intel.content.word_count,
                extracted_text=intel.clean_text if changed or is_new else None,
                response_time_ms=result.elapsed_ms,
                crawled_at=now,
            )
            await self._pages.add_version(version)
            await self._intel.replace_for_page(page, version.id, intel)
            if result.body is not None:
                version.html_storage_reference = await self._storage.store(
                    project_id, page.id, version.id, result.body
                )
            await self._urls.mark(
                self._job.id,
                item.url,
                status=CrawlUrlStatus.CRAWLED,
                http_status=result.status_code,
                content_type=result.content_type,
                page_id=page.id,
                crawled_at=now,
                response_time_ms=result.elapsed_ms,
                final_url=result.final_url,
                redirect_chain=list(result.redirect_chain),
            )
            self._sync_counts()
            await self._session.commit()
        return page

    def _sync_counts(self) -> None:
        self._job.pages_discovered = self._stats.discovered
        self._job.pages_crawled = self._stats.crawled
        self._job.pages_failed = self._stats.failed
        self._job.pages_skipped = self._stats.skipped
