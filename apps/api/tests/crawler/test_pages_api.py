"""Pages API: listing with pagination/filters, detail, headings, links; tenant isolation."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.intelligence import analyze_page
from app.crawler.urls import normalize_crawl_url
from app.models import WebsitePage
from app.repositories.page_intelligence import PageIntelligenceRepository
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.test_projects_api import create_project

ROOT = "https://www.acme.com"

HOME = """<html lang="en"><head><title>Acme Home</title><meta name="description" content="d">
<meta property="og:title" content="Acme"></head><body><nav><a href="/about">About</a></nav>
<main><h1>Welcome</h1><h2>Products</h2><h2>Products</h2><p>Acme makes things. Lots of things.</p>
<a href="/about">about</a><a href="/gone">gone</a>
<a href="https://other.com/" rel="nofollow">ext</a><a href="http://[bad">invalid</a>
<img src="/hero.png" alt="Hero"></main></body></html>"""


async def seed_pages(session: AsyncSession, project_id: str) -> dict[str, WebsitePage]:
    """Insert crawled pages + intelligence directly (the crawler is tested elsewhere)."""
    now = datetime.now(UTC)
    repo = PageIntelligenceRepository(session)
    pages: dict[str, WebsitePage] = {}
    for path, status, body in [
        ("/", 200, HOME),
        ("/about", 200, "<html lang='fr'><body><h1>À propos</h1><p>Bonjour</p></body></html>"),
        ("/gone", 404, "<html><body>nope</body></html>"),
    ]:
        url = f"{ROOT}{path}"
        page = WebsitePage(
            project_id=uuid.UUID(project_id),
            url=url,
            normalized_url=url,
            http_status=status,
            content_type="text/html",
            title=None,
            language=None,
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(page)
        await session.flush()
        intel = analyze_page(
            body.encode(), normalize_crawl_url(url), allowed_hosts=frozenset({"www.acme.com"})
        )
        page.title = intel.headings[0].text if intel.headings else None
        page.language = intel.language.code
        page.word_count = intel.content.word_count
        await repo.replace_for_page(page, None, intel)
        pages[path] = page
    await repo.resolve_internal_links(uuid.UUID(project_id))
    await session.flush()
    return pages


async def _project(client: AsyncClient) -> tuple[dict[str, str], str]:
    owner = await signup(client, org="Pages Org")
    h = auth_header(owner["access_token"])
    pid = (await create_project(client, h, website_url=ROOT))["id"]
    return h, pid


async def test_list_pages_with_pagination_and_filters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid = await _project(client)
    await seed_pages(db_session, pid)

    first = (
        await client.get(f"/api/v1/projects/{pid}/pages", params={"limit": 2}, headers=h)
    ).json()
    assert (
        first["total"] == 3
        and len(first["items"]) == 2
        and first["limit"] == 2
        and first["offset"] == 0
    )
    second = (
        await client.get(
            f"/api/v1/projects/{pid}/pages", params={"limit": 2, "offset": 2}, headers=h
        )
    ).json()
    assert len(second["items"]) == 1
    assert {p["url"] for p in first["items"]} | {p["url"] for p in second["items"]} == {
        f"{ROOT}/",
        f"{ROOT}/about",
        f"{ROOT}/gone",
    }

    only_404 = (
        await client.get(f"/api/v1/projects/{pid}/pages", params={"http_status": 404}, headers=h)
    ).json()
    assert [p["url"] for p in only_404["items"]] == [f"{ROOT}/gone"]
    french = (
        await client.get(f"/api/v1/projects/{pid}/pages", params={"language": "fr"}, headers=h)
    ).json()
    assert [p["url"] for p in french["items"]] == [f"{ROOT}/about"]
    search = (
        await client.get(f"/api/v1/projects/{pid}/pages", params={"q": "abo"}, headers=h)
    ).json()
    assert search["total"] == 1
    assert (
        await client.get(f"/api/v1/projects/{pid}/pages", params={"limit": 0}, headers=h)
    ).status_code == 422


async def test_page_detail_headings_and_links(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid = await _project(client)
    pages = await seed_pages(db_session, pid)
    home = pages["/"]

    detail = (await client.get(f"/api/v1/pages/{home.id}", headers=h)).json()
    assert detail["url"] == f"{ROOT}/" and detail["pathname"] == "/"
    assert detail["metadata"]["open_graph"] == {"og:title": "Acme"}
    assert (
        detail["metadata"]["language"] == "en"
        and detail["metadata"]["language_source"] == "html_lang"
    )
    assert [hd["text"] for hd in detail["headings"]] == ["Welcome", "Products", "Products"]
    assert detail["content"]["heading_observations"]["duplicate_headings"] == ["products"]
    assert detail["content"]["word_count"] > 0 and detail["content"]["image_count"] == 1
    # nav /about + /about + /gone internal; other.com external; "[bad" invalid (not counted)
    assert detail["link_counts"] == {"total": 5, "internal": 3, "external": 1}
    assert "Acme makes things" in detail["clean_text"] and "About" not in detail["clean_text"]
    assert detail["images"][0]["alt"] == "Hero"

    headings = (await client.get(f"/api/v1/pages/{home.id}/headings", headers=h)).json()
    assert [(x["level"], x["parent_position"]) for x in headings] == [(1, None), (2, 0), (2, 0)]

    links = (await client.get(f"/api/v1/pages/{home.id}/links", headers=h)).json()
    assert links["total"] == 5
    by_href = {x["href"]: x for x in links["items"]}
    assert by_href["/about"]["status"] == "ok" and by_href["/about"]["target_page_id"] == str(
        pages["/about"].id
    )
    assert by_href["/gone"]["status"] == "broken" and by_href["/gone"]["target_http_status"] == 404
    assert (
        by_href["https://other.com/"]["status"] == "unknown"
        and by_href["https://other.com/"]["is_nofollow"]
    )
    assert by_href["http://[bad"]["status"] == "invalid"

    broken = (
        await client.get(f"/api/v1/pages/{home.id}/links", params={"status": "broken"}, headers=h)
    ).json()
    assert [x["href"] for x in broken["items"]] == ["/gone"]
    external = (
        await client.get(
            f"/api/v1/pages/{home.id}/links", params={"type": "external", "limit": 1}, headers=h
        )
    ).json()
    # type=external includes the unparseable href (status=invalid); limit=1 pages it
    assert external["total"] == 2 and external["items"][0]["href"] == "https://other.com/"
    assert len(external["items"]) == 1
    paged = (
        await client.get(
            f"/api/v1/pages/{home.id}/links", params={"limit": 2, "offset": 4}, headers=h
        )
    ).json()
    assert len(paged["items"]) == 1 and paged["offset"] == 4 and paged["total"] == 5


async def test_pages_are_tenant_isolated_and_require_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ha, pid = await _project(client)
    pages = await seed_pages(db_session, pid)
    home = pages["/"]
    other = await signup(client, org="Other")
    hb = auth_header(other["access_token"])
    for path in (
        f"/api/v1/projects/{pid}/pages",
        f"/api/v1/pages/{home.id}",
        f"/api/v1/pages/{home.id}/headings",
        f"/api/v1/pages/{home.id}/links",
    ):
        assert (await client.get(path, headers=hb)).status_code == 404, path
        assert (await client.get(path)).status_code == 401, path
    assert (await client.get(f"/api/v1/pages/{uuid.uuid4()}", headers=ha)).status_code == 404
    assert (await client.get(f"/api/v1/pages/{home.id}", headers=ha)).status_code == 200


async def test_recrawl_replaces_intelligence_rows(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    _, pid = await _project(client)
    pages = await seed_pages(db_session, pid)
    repo = PageIntelligenceRepository(db_session)
    home = pages["/"]
    new = analyze_page(
        b"<html><body><h1>Only one</h1></body></html>", normalize_crawl_url(f"{ROOT}/")
    )
    await repo.replace_for_page(home, None, new)
    assert [x.text for x in await repo.headings_for_page(home.id)] == ["Only one"]
    links, total = await repo.links_for_page(home.id)
    assert links == [] and total == 0
