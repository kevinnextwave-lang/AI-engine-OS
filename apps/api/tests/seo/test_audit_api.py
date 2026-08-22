"""SEO audit end-to-end: seeded crawl data -> run_audit -> API, plus RBAC/tenant isolation."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.seo import get_seo_dispatcher
from app.core.security import create_access_token
from app.crawler.intelligence import analyze_page
from app.crawler.parser import process_html
from app.crawler.urls import normalize_crawl_url
from app.models import (
    CrawlJob,
    CrawlStatus,
    CrawlType,
    CrawlUrl,
    CrawlUrlStatus,
    MembershipRole,
    SeoAudit,
    WebsitePage,
)
from app.models.seo import AuditStatus, ObservationStatus
from app.repositories.page_intelligence import PageIntelligenceRepository
from app.seo.engine import run_audit
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

ROOT = "https://www.acme.com/"

HOME = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Acme – Widgets for everyone</title>
<meta name="description" content="Acme makes durable widgets for every household and business.">
<link rel="canonical" href="https://www.acme.com/">
<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
</head><body><h1>Acme</h1><p>Words words words.</p>
<a href="/about">About</a><a href="/products">Products</a><a href="/missing">Missing</a>
</body></html>"""

ABOUT = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Acme – Widgets for everyone</title>
<link rel="canonical" href="https://www.acme.com/about">
</head><body><h2>No h1 here</h2><p>About us.</p><a href="/">Home</a></body></html>"""

PRODUCTS = """<!DOCTYPE html><html><head><title>Products</title>
<meta name="robots" content="noindex"></head><body><h1>Products</h1><a href="/">Home</a>
</body></html>"""

ORPHAN = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Orphan page – Acme</title><meta name="viewport" content="width=device-width"></head>
<body><h1>Orphan</h1></body></html>"""


@pytest.fixture
def dispatched(client: AsyncClient) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_seo_dispatcher] = lambda: calls.append
    return calls


async def seed_crawl(session: AsyncSession, project_id: str) -> CrawlJob:
    """A finished crawl with pages + intelligence rows, inserted directly."""
    pid = uuid.UUID(project_id)
    now = datetime.now(UTC)
    job = CrawlJob(
        project_id=pid,
        root_url=ROOT,
        crawl_type=CrawlType.FULL,
        status=CrawlStatus.COMPLETED,
        max_pages=50,
        max_depth=3,
        started_at=now,
        completed_at=now,
        config={
            "site": {
                "robots_txt": {"checked": True, "present": True, "sitemaps_declared": []},
                "sitemap_urls_found": 0,
            }
        },
    )
    session.add(job)
    await session.flush()
    repo = PageIntelligenceRepository(session)
    specs = [
        ("", 200, HOME, 0),
        ("about", 200, ABOUT, 1),
        ("products", 200, PRODUCTS, 1),
        ("orphan", 200, ORPHAN, 2),
        ("missing", 404, "<html><body>gone</body></html>", 1),
    ]
    for path, status, body, depth in specs:
        url = ROOT + path
        parsed = process_html(body.encode(), normalize_crawl_url(url))
        intel = analyze_page(
            body.encode(), normalize_crawl_url(url), allowed_hosts=frozenset({"www.acme.com"})
        )
        page = WebsitePage(
            project_id=pid,
            url=url,
            normalized_url=url,
            http_status=status,
            content_type="text/html",
            title=parsed.title,
            meta_description=parsed.meta_description,
            canonical_url=parsed.canonical_url,
            language=intel.language.code,
            word_count=intel.content.word_count,
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(page)
        await session.flush()
        await repo.replace_for_page(page, None, intel)
        session.add(
            CrawlUrl(
                crawl_job_id=job.id,
                project_id=pid,
                url=url,
                normalized_url=url,
                depth=depth,
                status=CrawlUrlStatus.CRAWLED,
                http_status=status,
                page_id=page.id,
                crawled_at=now,
            )
        )
    session.add(
        CrawlUrl(
            crawl_job_id=job.id,
            project_id=pid,
            url=ROOT + "old",
            normalized_url=ROOT + "old",
            depth=1,
            status=CrawlUrlStatus.CRAWLED,
            http_status=200,
            final_url=ROOT + "about",
            redirect_chain=[ROOT + "old", ROOT + "older"],
            crawled_at=now,
        )
    )
    await repo.resolve_internal_links(pid)
    await session.flush()
    return job


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="SEO Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, website_url=ROOT))["id"]
    return h, org, pid


async def _run(session: AsyncSession, audit_id: str) -> SeoAudit:
    audit = await session.get(SeoAudit, uuid.UUID(audit_id))
    assert audit is not None
    return await run_audit(session, audit)


# --- engine + API round trip ------------------------------------------------


async def test_audit_produces_expected_observations_and_score(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    job = await seed_crawl(db_session, pid)

    resp = await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)
    assert resp.status_code == 202, resp.text
    audit = resp.json()
    assert audit["status"] == "queued" and audit["crawl_job_id"] == str(job.id)
    assert audit["health_score"] is None  # nothing is scored before observations exist
    assert dispatched == [uuid.UUID(audit["id"])]

    await _run(db_session, audit["id"])  # what the worker does

    got = (await client.get(f"/api/v1/seo-audits/{audit['id']}", headers=h)).json()
    assert got["status"] == "completed", got
    assert got["pages_analyzed"] == 5 and got["observation_count"] > 0
    assert 0 <= got["health_score"] < 100
    assert got["score_breakdown"]["method"] == "technical-seo-health-score/v1"
    assert got["summary"]["html_pages"] == 4 and got["summary"]["indexable_pages"] == 3

    obs = (
        await client.get(
            f"/api/v1/seo-audits/{audit['id']}/observations", params={"limit": 500}, headers=h
        )
    ).json()
    assert obs["total"] == got["observation_count"]
    by_code: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for o in obs["items"]:
        by_code.setdefault(o["code"], []).append(o)

    # duplicate titles (home + about), missing H1 (about), missing description (about)
    assert sorted(by_code["title_duplicate"][0]["evidence"]["urls"]) == [ROOT, ROOT + "about"]
    assert [o["url"] for o in by_code["h1_missing"]] == [ROOT + "about"]
    assert ROOT + "about" in [o["url"] for o in by_code["description_missing"]]
    # noindex (products), 404 (missing), broken link from home, orphan, redirect chain
    assert by_code["noindex_pages"][0]["evidence"]["urls"] == [ROOT + "products"]
    assert by_code["client_error"][0]["evidence"]["http_status"] == 404
    assert by_code["broken_internal_links"][0]["url"] == ROOT
    assert by_code["broken_internal_links"][0]["evidence"]["links"][0]["href"] == "/missing"
    assert by_code["orphan_pages"][0]["evidence"]["urls"] == [ROOT + "orphan"]
    assert by_code["redirect_chain"][0]["evidence"]["chains"][0]["from"] == ROOT + "old"
    # canonical: products/orphan have none; schema detected on home; mobile-html on products
    assert {o["url"] for o in by_code["canonical_missing"]} == {ROOT + "products", ROOT + "orphan"}
    assert by_code["structured_data_detected"][0]["evidence"]["schema_types"] == {"Organization": 1}
    assert by_code["viewport_missing"][0]["evidence"]["urls"] == [ROOT + "products"]
    assert by_code["sitemap_missing"]
    # ordering: most severe first
    ranks = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sev = [ranks[o["severity"]] for o in obs["items"]]
    assert sev == sorted(sev)
    # every observation carries a concrete recommendation and evidence
    assert all(o["recommendation"] and isinstance(o["evidence"], dict) for o in obs["items"])


async def test_observation_filters_and_triage(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    await seed_crawl(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)).json()
    await _run(db_session, audit["id"])
    base = f"/api/v1/seo-audits/{audit['id']}/observations"

    meta = (await client.get(base, params={"category": "metadata"}, headers=h)).json()
    assert meta["total"] > 0 and all(o["category"] == "metadata" for o in meta["items"])
    high = (await client.get(base, params={"severity": "high"}, headers=h)).json()
    assert all(o["severity"] == "high" for o in high["items"])
    paged = (await client.get(base, params={"limit": 2, "offset": 1}, headers=h)).json()
    assert len(paged["items"]) == 2 and paged["offset"] == 1

    target = meta["items"][0]
    patched = await client.patch(
        f"/api/v1/seo-observations/{target['id']}",
        json={"status": "ignored", "note": "Brand decision"},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["status"] == "ignored" and body["status_note"] == "Brand decision"
    assert body["status_changed_by_user_id"] is not None
    ignored = (await client.get(base, params={"status": "ignored"}, headers=h)).json()
    assert [o["id"] for o in ignored["items"]] == [target["id"]]
    total = (await client.get(base, headers=h)).json()["total"]
    open_ = (await client.get(base, params={"status": "open"}, headers=h)).json()
    assert open_["total"] == total - 1


async def test_audit_requires_finished_crawl(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    none = await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)
    assert none.status_code == 422
    job = await seed_crawl(db_session, pid)
    job.status = CrawlStatus.RUNNING
    await db_session.flush()
    running = await client.post(
        f"/api/v1/projects/{pid}/seo-audits", json={"crawl_job_id": str(job.id)}, headers=h
    )
    assert running.status_code == 409
    assert dispatched == []
    listed = (await client.get(f"/api/v1/projects/{pid}/seo-audits", headers=h)).json()
    assert listed["total"] == 0


async def test_dispatch_failure_marks_audit_failed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    await seed_crawl(db_session, pid)

    def boom(_: uuid.UUID) -> None:
        raise ConnectionError("broker down")

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_seo_dispatcher] = lambda: boom
    resp = await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)
    assert resp.status_code == 202
    assert resp.json()["status"] == "failed"
    assert "ConnectionError" in resp.json()["error_message"]


async def test_failed_analysis_is_recorded_not_raised(
    client: AsyncClient,
    dispatched: list[uuid.UUID],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, _, pid = await _setup(client)
    await seed_crawl(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)).json()

    async def broken_context(*_: object, **__: object) -> object:
        raise ValueError("corrupt intelligence row")

    monkeypatch.setattr("app.seo.engine.build_context", broken_context)
    result = await _run(db_session, audit["id"])
    assert result.status == AuditStatus.FAILED
    assert result.error_message == "ValueError: corrupt intelligence row"
    assert result.health_score is None and result.completed_at is not None
    got = (await client.get(f"/api/v1/seo-audits/{audit['id']}", headers=h)).json()
    assert got["status"] == "failed"


# --- authorization -----------------------------------------------------------


async def test_other_tenant_gets_404_everywhere(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    await seed_crawl(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)).json()
    await _run(db_session, audit["id"])
    obs_id = (await client.get(f"/api/v1/seo-audits/{audit['id']}/observations", headers=h)).json()[
        "items"
    ][0]["id"]

    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/seo-audits", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=stranger)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/seo-audits/{audit['id']}", headers=stranger)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/seo-audits/{audit['id']}/observations", headers=stranger)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/seo-observations/{obs_id}", json={"status": "resolved"}, headers=stranger
        )
    ).status_code == 404
    # And nothing changed.
    row = (await client.get(f"/api/v1/seo-audits/{audit['id']}/observations", headers=h)).json()
    assert all(o["status"] == ObservationStatus.OPEN.value for o in row["items"])
    assert (
        await client.get("/api/v1/seo-audits/" + str(uuid.uuid4()), headers=h)
    ).status_code == 404


async def test_viewer_can_read_but_not_start_or_triage(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, org, pid = await _setup(client)
    await seed_crawl(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)).json()
    await _run(db_session, audit["id"])
    obs_id = (await client.get(f"/api/v1/seo-audits/{audit['id']}/observations", headers=h)).json()[
        "items"
    ][0]["id"]

    viewer_id = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer_id))
    assert (await client.get(f"/api/v1/projects/{pid}/seo-audits", headers=v)).status_code == 200
    assert (await client.get(f"/api/v1/seo-audits/{audit['id']}", headers=v)).status_code == 200
    assert (
        await client.get(f"/api/v1/seo-audits/{audit['id']}/observations", headers=v)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=v)
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/seo-observations/{obs_id}", json={"status": "resolved"}, headers=v
        )
    ).status_code == 403

    member_id = await add_member(
        db_session, org, f"member-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.MEMBER
    )
    m = auth_header(create_access_token(member_id))
    assert (
        await client.patch(
            f"/api/v1/seo-observations/{obs_id}", json={"status": "resolved"}, headers=m
        )
    ).status_code == 200
    assert (await client.get("/api/v1/seo-audits/" + audit["id"])).status_code == 401
