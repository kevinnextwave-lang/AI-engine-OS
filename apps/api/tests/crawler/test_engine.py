"""Engine tests: run whole crawls against an in-memory site with a real DB."""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.crawler.runner import RunnerOptions, run_crawl_job
from app.models import (
    CrawlJob,
    CrawlStatus,
    CrawlType,
    CrawlUrl,
    CrawlUrlStatus,
    Domain,
    Organization,
    OrganizationPlan,
    PageVersion,
    Project,
    WebsitePage,
)
from tests.crawler.fakes import FakePage, FakeSite, RecordingSleep, html, make_resolver

ROOT = "https://example.com"


async def make_project(
    session: AsyncSession, *, plan: OrganizationPlan = OrganizationPlan.PRO
) -> Project:
    org = Organization(name="Crawl Co", slug=f"crawl-{uuid.uuid4().hex[:8]}", plan=plan)
    project = Project(organization=org, name="Site", slug="site")
    session.add(project)
    await session.flush()
    session.add(Domain(project_id=project.id, url=ROOT, hostname="example.com", is_primary=True))
    await session.flush()
    return project


async def make_job(session: AsyncSession, project: Project, **kw: object) -> CrawlJob:
    job = CrawlJob(
        project_id=project.id,
        root_url=kw.pop("root_url", ROOT + "/"),
        crawl_type=kw.pop("crawl_type", CrawlType.FULL),
        max_pages=kw.pop("max_pages", 50),
        max_depth=kw.pop("max_depth", 5),
        **kw,
    )
    session.add(job)
    await session.flush()
    return job


def simple_site() -> FakeSite:
    return FakeSite(
        {
            f"{ROOT}/": FakePage(html("Home", ["/about", "/blog", "/blog"], nav=["/contact"])),
            f"{ROOT}/about": FakePage(html("About", ["/", "/team?utm_source=nav", "/team"])),
            f"{ROOT}/team": FakePage(html("Team", ["https://external.com/x", "/deep/1"])),
            f"{ROOT}/contact": FakePage(html("Contact")),
            f"{ROOT}/blog": FakePage(html("Blog", ["/blog/post-1", "/files/brochure.pdf"])),
            f"{ROOT}/blog/post-1": FakePage(html("Post 1", ["/blog"])),
            f"{ROOT}/deep/1": FakePage(html("Deep 1", ["/deep/2"])),
            f"{ROOT}/deep/2": FakePage(html("Deep 2", ["/deep/3"])),
            f"{ROOT}/deep/3": FakePage(html("Deep 3", ["/deep/4"])),
            f"{ROOT}/deep/4": FakePage(html("Deep 4")),
            f"{ROOT}/files/brochure.pdf": FakePage(b"%PDF", content_type="application/pdf"),
        }
    )


def options(site: FakeSite, **overrides: object) -> RunnerOptions:
    settings = get_settings().model_copy(update={"crawl_status_check_interval": 1, **overrides})
    return RunnerOptions(
        transport=site.transport(),
        resolver=make_resolver(),
        settings=settings,
        sleep=RecordingSleep(),
    )


async def urls_for(session: AsyncSession, job: CrawlJob) -> dict[str, CrawlUrl]:
    rows = (await session.scalars(select(CrawlUrl).where(CrawlUrl.crawl_job_id == job.id))).all()
    return {r.normalized_url: r for r in rows}


# --- happy path -------------------------------------------------------------


async def test_full_crawl_discovers_internal_html_pages_only(engine_session: AsyncSession) -> None:
    site = simple_site()
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()

    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None and result.status == CrawlStatus.COMPLETED
    # 10 HTML pages exist but /deep/4 is at depth 6 (> max_depth 5).
    assert result.pages_crawled == 9 and result.pages_failed == 0
    assert result.pages_skipped == 1  # the PDF
    assert result.started_at and result.completed_at and result.duration_seconds is not None
    assert result.config["allowed_hosts"] == ["example.com"]

    # External domain never requested; tracking params stripped; duplicates not refetched.
    assert all(r.startswith(ROOT) for r in site.requests)
    assert f"{ROOT}/team?utm_source=nav" not in site.requests
    assert site.requests.count(f"{ROOT}/blog") == 1

    urls = await urls_for(engine_session, job)
    assert urls[f"{ROOT}/"].depth == 0 and urls[f"{ROOT}/"].priority == 0
    assert urls[f"{ROOT}/contact"].priority == 2  # navigation link
    assert urls[f"{ROOT}/about"].priority == 3 and urls[f"{ROOT}/about"].parent_url == f"{ROOT}/"
    assert urls[f"{ROOT}/files/brochure.pdf"].status == CrawlUrlStatus.SKIPPED
    assert "external.com" not in "".join(urls)

    pages = (
        await engine_session.scalars(
            select(WebsitePage).where(WebsitePage.project_id == project.id)
        )
    ).all()
    assert len(pages) == 9 and all(p.normalized_url != f"{ROOT}/deep/4" for p in pages)
    home = next(p for p in pages if p.normalized_url == f"{ROOT}/")
    assert home.title == "Home" and home.meta_description == "About Home" and home.language == "en"
    assert home.word_count and home.content_hash and home.html_hash
    versions = (
        await engine_session.scalars(select(PageVersion).where(PageVersion.page_id == home.id))
    ).all()
    assert (
        len(versions) == 1
        and versions[0].extracted_text
        and "Content of Home" in versions[0].extracted_text
    )
    assert versions[0].html_storage_reference is None  # NullHtmlStorage by default


# --- limits ----------------------------------------------------------------------


async def test_max_depth_is_respected(engine_session: AsyncSession) -> None:
    site = simple_site()
    project = await make_project(engine_session)
    job = await make_job(engine_session, project, max_depth=2)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None
    urls = await urls_for(engine_session, job)
    assert max(u.depth for u in urls.values()) == 2
    assert f"{ROOT}/team" in urls  # depth 2 via / -> /about -> /team
    assert f"{ROOT}/deep/1" not in urls  # would be depth 3
    assert f"{ROOT}/deep/2" not in urls and f"{ROOT}/deep/2" not in site.requests


async def test_max_pages_is_respected(engine_session: AsyncSession) -> None:
    site = simple_site()
    project = await make_project(engine_session)
    job = await make_job(engine_session, project, max_pages=4)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None
    fetched_pages = [r for r in site.requests if not r.endswith(("robots.txt", "sitemap.xml"))]
    assert len(fetched_pages) <= 4
    assert result.pages_crawled <= 4 and result.pages_discovered <= 4


async def test_plan_caps_override_requested_limits(engine_session: AsyncSession) -> None:
    site = simple_site()
    project = await make_project(
        engine_session, plan=OrganizationPlan.FREE
    )  # cap 100 pages, depth 3
    job = await make_job(engine_session, project, max_pages=10_000, max_depth=20)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert (
        result is not None and result.config["max_depth"] == 3 and result.config["max_pages"] == 100
    )


async def test_single_page_crawl(engine_session: AsyncSession) -> None:
    site = simple_site()
    project = await make_project(engine_session)
    job = await make_job(
        engine_session, project, crawl_type=CrawlType.SINGLE_PAGE, max_pages=1, max_depth=0
    )
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None and result.status == CrawlStatus.COMPLETED
    assert result.pages_crawled == 1 and result.pages_discovered == 1
    assert f"{ROOT}/sitemap.xml" not in site.requests


# --- domain restrictions / safety ------------------------------------------------------


async def test_subdomains_excluded_by_default_and_allowed_when_configured(
    engine_session: AsyncSession,
) -> None:
    site = FakeSite(
        {
            f"{ROOT}/": FakePage(
                html("Home", ["https://blog.example.com/p", "https://www.example.com/w"])
            ),
            "https://blog.example.com/p": FakePage(html("Blog post")),
            "https://www.example.com/w": FakePage(html("WWW page")),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None
    assert "https://blog.example.com/p" not in site.requests
    assert "https://www.example.com/w" in site.requests  # www <-> apex are the same site

    job2 = await make_job(engine_session, project)
    await engine_session.commit()
    site2 = FakeSite(site.pages)
    await run_crawl_job(engine_session, job2.id, options(site2, crawl_allow_subdomains=True))
    assert "https://blog.example.com/p" in site2.requests


async def test_redirect_to_private_network_is_blocked_and_recorded(
    engine_session: AsyncSession,
) -> None:
    site = FakeSite(
        {
            f"{ROOT}/": FakePage(html("Home", ["/admin", "/ok"])),
            f"{ROOT}/admin": FakePage(status=302, headers={"location": "http://10.0.0.1/secret"}),
            f"{ROOT}/ok": FakePage(html("OK")),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None and result.status == CrawlStatus.PARTIALLY_COMPLETED
    urls = await urls_for(engine_session, job)
    assert urls[f"{ROOT}/admin"].status == CrawlUrlStatus.FAILED
    assert "blocked" in (urls[f"{ROOT}/admin"].error_message or "")
    assert not any("10.0.0.1" in r for r in site.requests)


async def test_root_resolving_to_private_ip_fails_job_without_fetching(
    engine_session: AsyncSession,
) -> None:
    site = simple_site()
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    opts = options(site)
    opts.resolver = make_resolver({"example.com": ["192.168.1.10"]})
    result = await run_crawl_job(engine_session, job.id, opts)
    assert result is not None and result.status == CrawlStatus.FAILED
    assert result.pages_crawled == 0 and site.requests == []


# --- robots / redirects / canonical ---------------------------------------------------------


async def test_robots_disallow_and_sitemap_seeding(engine_session: AsyncSession) -> None:
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    site = FakeSite(
        {
            f"{ROOT}/robots.txt": FakePage(
                f"User-agent: *\nDisallow: /private\nSitemap: {ROOT}/sm.xml\n",
                content_type="text/plain",
            ),
            f"{ROOT}/sm.xml": FakePage(
                f"<urlset {ns}><url><loc>{ROOT}/from-sitemap</loc></url></urlset>",
                content_type="application/xml",
            ),
            f"{ROOT}/": FakePage(html("Home", ["/private/page", "/public"])),
            f"{ROOT}/private/page": FakePage(html("Secret")),
            f"{ROOT}/public": FakePage(html("Public")),
            f"{ROOT}/from-sitemap": FakePage(html("Sitemap page")),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None
    assert f"{ROOT}/private/page" not in site.requests
    urls = await urls_for(engine_session, job)
    assert urls[f"{ROOT}/private/page"].status == CrawlUrlStatus.SKIPPED
    assert "robots" in (urls[f"{ROOT}/private/page"].error_message or "")
    assert (
        urls[f"{ROOT}/from-sitemap"].priority == 1
        and urls[f"{ROOT}/from-sitemap"].status == CrawlUrlStatus.CRAWLED
    )
    # Sitemap page fetched before content links (priority order)
    assert site.requests.index(f"{ROOT}/from-sitemap") < site.requests.index(f"{ROOT}/public")


async def test_redirects_store_final_url_and_canonical_is_queued(
    engine_session: AsyncSession,
) -> None:
    site = FakeSite(
        {
            f"{ROOT}/": FakePage(html("Home", ["/old", "/page?ref=1"])),
            f"{ROOT}/old": FakePage(status=301, headers={"location": "/new"}),
            f"{ROOT}/new": FakePage(html("New")),
            f"{ROOT}/page?ref=1": FakePage(
                html("Page", extra_head=f'<link rel="canonical" href="{ROOT}/page">')
            ),
            f"{ROOT}/page": FakePage(html("Page")),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None
    pages = {p.normalized_url: p for p in (await engine_session.scalars(select(WebsitePage))).all()}
    assert f"{ROOT}/new" in pages and f"{ROOT}/old" not in pages
    assert pages[f"{ROOT}/page?ref=1"].canonical_url == f"{ROOT}/page"
    assert f"{ROOT}/page" in pages  # canonical target was discovered and crawled
    urls = await urls_for(engine_session, job)
    assert (
        urls[f"{ROOT}/old"].status == CrawlUrlStatus.CRAWLED
        and urls[f"{ROOT}/old"].page_id == pages[f"{ROOT}/new"].id
    )


# --- failures, retries, timeouts -------------------------------------------------------------


async def test_transient_failures_retry_and_permanent_failures_are_recorded(
    engine_session: AsyncSession,
) -> None:
    site = FakeSite(
        {
            f"{ROOT}/": FakePage(html("Home", ["/flaky", "/dead", "/slow", "/missing"])),
            f"{ROOT}/flaky": FakePage(html("Flaky"), fail_times=1),
            f"{ROOT}/dead": FakePage(html("Dead"), fail_times=99),
            f"{ROOT}/slow": FakePage(html("Slow"), raise_timeout=True),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site, crawl_max_retries=1))
    assert result is not None and result.status == CrawlStatus.PARTIALLY_COMPLETED
    urls = await urls_for(engine_session, job)
    assert urls[f"{ROOT}/flaky"].status == CrawlUrlStatus.CRAWLED
    assert urls[f"{ROOT}/dead"].status == CrawlUrlStatus.FAILED
    assert (
        urls[f"{ROOT}/slow"].status == CrawlUrlStatus.FAILED
        and urls[f"{ROOT}/slow"].error_message == "timeout"
    )
    assert (
        urls[f"{ROOT}/missing"].status == CrawlUrlStatus.CRAWLED
        and urls[f"{ROOT}/missing"].http_status == 404
    )
    assert result.pages_failed == 2 and result.pages_crawled == 3
    assert site.requests.count(f"{ROOT}/dead") == 2  # 1 retry


# --- duplicates ---------------------------------------------------------------------------------


async def test_duplicate_content_detection_and_page_versions(engine_session: AsyncSession) -> None:
    same = html("Same", body="identical text")
    site = FakeSite(
        {
            f"{ROOT}/": FakePage(html("Home", ["/a", "/b"])),
            f"{ROOT}/a": FakePage(same),
            f"{ROOT}/b": FakePage(same),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    await run_crawl_job(engine_session, job.id, options(site))
    pages = {p.normalized_url: p for p in (await engine_session.scalars(select(WebsitePage))).all()}
    a, b = pages[f"{ROOT}/a"], pages[f"{ROOT}/b"]
    assert a.content_hash == b.content_hash
    assert {a.is_duplicate_of_id, b.is_duplicate_of_id} == {None, a.id} or {
        a.is_duplicate_of_id,
        b.is_duplicate_of_id,
    } == {None, b.id}

    # Second crawl: pages updated in place, new versions appended, unchanged text not duplicated.
    site.pages[f"{ROOT}/a"] = FakePage(html("Same", body="changed text"))
    job2 = await make_job(engine_session, project)
    await engine_session.commit()
    await run_crawl_job(engine_session, job2.id, options(site))
    assert len((await engine_session.scalars(select(WebsitePage))).all()) == 3  # no new page rows
    await engine_session.refresh(a)
    versions = (
        await engine_session.scalars(
            select(PageVersion).where(PageVersion.page_id == a.id).order_by(PageVersion.crawled_at)
        )
    ).all()
    assert (
        len(versions) == 2
        and versions[1].extracted_text
        and "changed text" in versions[1].extracted_text
    )
    b_versions = (
        await engine_session.scalars(select(PageVersion).where(PageVersion.page_id == b.id))
    ).all()
    assert (
        len(b_versions) == 2 and b_versions[1].extracted_text is None
    )  # unchanged => no text copy
    assert a.is_duplicate_of_id is None


# --- cancellation / concurrency / rate limiting -------------------------------------------------


async def test_cancellation_stops_future_fetches(engine_session: AsyncSession) -> None:
    pages = {f"{ROOT}/": FakePage(html("Home", [f"/p{i}" for i in range(30)]))}
    pages.update({f"{ROOT}/p{i}": FakePage(html(f"P{i}")) for i in range(30)})
    site = FakeSite(pages)
    project = await make_project(engine_session)
    job = await make_job(engine_session, project, max_pages=100)
    await engine_session.commit()

    enough = asyncio.Event()
    site.on_request = lambda _url: enough.set() if len(site.requests) >= 6 else None

    async def cancel_after_some() -> None:
        await asyncio.wait_for(enough.wait(), 5)
        from app.db.session import get_session_factory
        from app.repositories.crawl import CrawlJobRepository

        # Cancel through a separate session, like the API would.
        async with get_session_factory()() as other:
            j = await CrawlJobRepository(other).get(job.id)
            assert j is not None
            await CrawlJobRepository(other).request_cancel(j)
            await other.commit()

    result, _ = await asyncio.gather(
        run_crawl_job(engine_session, job.id, options(site)), cancel_after_some()
    )
    assert result is not None and result.status == CrawlStatus.CANCELLED
    page_requests = [r for r in site.requests if not r.endswith(("robots.txt", "sitemap.xml"))]
    assert 1 <= len(page_requests) < 31  # stopped well before the frontier drained
    assert result.pages_crawled == len(page_requests)  # in-flight ones completed gracefully
    assert result.pages_discovered == 31  # discovery already happened; fetches were cut short


async def test_concurrency_is_bounded_and_parallel(engine_session: AsyncSession) -> None:
    pages = {f"{ROOT}/": FakePage(html("Home", [f"/p{i}" for i in range(12)]))}
    pages.update({f"{ROOT}/p{i}": FakePage(html(f"P{i}"), delay=0.03) for i in range(12)})
    site = FakeSite(pages)
    project = await make_project(
        engine_session, plan=OrganizationPlan.PRO
    )  # concurrency 8 -> min(8, setting)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(
        engine_session, job.id, options(site, crawl_concurrency=3, crawl_requests_per_second=1000)
    )
    assert result is not None and result.pages_crawled == 13
    assert 2 <= site.max_in_flight <= 3


async def test_rate_limiting_spaces_requests_to_host(engine_session: AsyncSession) -> None:
    pages = {f"{ROOT}/": FakePage(html("Home", [f"/p{i}" for i in range(5)]))}
    pages.update({f"{ROOT}/p{i}": FakePage(html(f"P{i}")) for i in range(5)})
    site = FakeSite(pages)
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    sleep = RecordingSleep()
    opts = options(site, crawl_requests_per_second=4.0, crawl_concurrency=1)
    opts.sleep = sleep
    await run_crawl_job(engine_session, job.id, opts)
    # The fake sleep returns instantly (clock doesn't advance), so each request after the
    # first must wait one more interval than the previous: 0.25, 0.5, 0.75, ...
    assert len(sleep.calls) >= 5
    assert 0.1 < sleep.calls[0] <= 0.25  # interval minus time spent processing
    assert all(b > a for a, b in zip(sleep.calls, sleep.calls[1:], strict=False))


# --- tenant isolation at the data layer ----------------------------------------------------------


async def test_pages_are_scoped_per_project(engine_session: AsyncSession) -> None:
    site = simple_site()
    p1 = await make_project(engine_session)
    p2 = await make_project(engine_session)
    j1 = await make_job(engine_session, p1, max_pages=3)
    j2 = await make_job(engine_session, p2, max_pages=3)
    await engine_session.commit()
    await run_crawl_job(engine_session, j1.id, options(site))
    await run_crawl_job(engine_session, j2.id, options(FakeSite(site.pages)))
    rows = (await engine_session.scalars(select(WebsitePage))).all()
    assert {r.project_id for r in rows} == {p1.id, p2.id}
    assert (
        len([r for r in rows if r.normalized_url == f"{ROOT}/"]) == 2
    )  # same URL, separate tenants


# --- page intelligence (Milestone 2B) ---------------------------------------------


async def test_crawl_persists_page_intelligence_and_resolves_links(
    engine_session: AsyncSession,
) -> None:
    from app.models import (
        LinkStatus,
        PageContentMetrics,
        PageHeading,
        PageImage,
        PageLink,
        PageMetadata,
    )

    site = FakeSite(
        {
            f"{ROOT}/": FakePage(
                html(
                    "Home",
                    ["/about", "/missing", "https://ext.com/x"],
                    nav=["/contact"],
                    extra_head='<meta property="og:title" content="OG Home">',
                )
                .replace("<h1>Home</h1>", "<h1>Home</h1><h3>Jumped</h3>")
                .replace("</main>", '<img src="/a.png" alt=""><img src="/b.png"></main>')
            ),
            f"{ROOT}/about": FakePage(html("About", ["/"])),
            f"{ROOT}/contact": FakePage(html("Contact")),
        }
    )
    project = await make_project(engine_session)
    job = await make_job(engine_session, project)
    await engine_session.commit()
    result = await run_crawl_job(engine_session, job.id, options(site))
    assert result is not None

    pages = {p.normalized_url: p for p in (await engine_session.scalars(select(WebsitePage))).all()}
    home = pages[f"{ROOT}/"]
    headings = (
        await engine_session.scalars(
            select(PageHeading).where(PageHeading.page_id == home.id).order_by(PageHeading.position)
        )
    ).all()
    assert [(h.level, h.text) for h in headings] == [(1, "Home"), (3, "Jumped")]
    metrics = await engine_session.scalar(
        select(PageContentMetrics).where(PageContentMetrics.page_id == home.id)
    )
    assert metrics is not None
    assert metrics.heading_observations["skipped_levels"] == [{"position": 1, "from": 1, "to": 3}]
    assert metrics.image_count == 2 and metrics.images_missing_alt == 2
    assert metrics.internal_link_count == 3 and metrics.external_link_count == 1
    assert metrics.clean_text and "Content of Home" in metrics.clean_text
    assert home.word_count == metrics.word_count
    meta = await engine_session.scalar(select(PageMetadata).where(PageMetadata.page_id == home.id))
    assert meta is not None and meta.open_graph == {"og:title": "OG Home"}
    assert meta.language == "en" and meta.language_source == "html_lang" and meta.pathname == "/"
    images = (
        await engine_session.scalars(select(PageImage).where(PageImage.page_id == home.id))
    ).all()
    assert {i.src: i.alt for i in images} == {f"{ROOT}/a.png": "", f"{ROOT}/b.png": None}

    links = {
        link.href: link
        for link in (
            await engine_session.scalars(select(PageLink).where(PageLink.page_id == home.id))
        ).all()
    }
    assert (
        links["/about"].status == LinkStatus.OK
        and links["/about"].target_page_id == pages[f"{ROOT}/about"].id
    )
    assert (
        links["/missing"].status == LinkStatus.BROKEN
        and links["/missing"].target_http_status == 404
    )
    assert links["https://ext.com/x"].status == LinkStatus.UNKNOWN  # external: never crawled
    assert links["/contact"].in_navigation

    # Re-crawl replaces rows instead of duplicating them; response time recorded.
    job2 = await make_job(engine_session, project)
    await engine_session.commit()
    await run_crawl_job(engine_session, job2.id, options(FakeSite(site.pages)))
    assert (
        len(
            (
                await engine_session.scalars(
                    select(PageHeading).where(PageHeading.page_id == home.id)
                )
            ).all()
        )
        == 2
    )
    urls = await urls_for(engine_session, job2)
    assert urls[f"{ROOT}/"].response_time_ms is not None and urls[f"{ROOT}/"].response_time_ms >= 0
    versions = (
        await engine_session.scalars(select(PageVersion).where(PageVersion.page_id == home.id))
    ).all()
    assert all(v.response_time_ms is not None for v in versions)
