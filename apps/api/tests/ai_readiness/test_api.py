"""Readiness audit end-to-end on seeded pages + entity layer; RBAC and tenant isolation."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_readiness.engine import run_readiness_audit
from app.api.v1.routes.ai_readiness import get_readiness_dispatcher
from app.core.security import create_access_token
from app.crawler.intelligence import analyze_page
from app.crawler.parser import process_html
from app.crawler.urls import normalize_crawl_url
from app.entities.engine import run_entity_analysis
from app.models import AiReadinessAudit, MembershipRole, WebsitePage
from app.repositories.page_intelligence import PageIntelligenceRepository
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

ROOT = "https://www.acme.com/"
FILLER = (
    "<p>"
    + "Acme helps agencies report faster with less manual work every single week. " * 15
    + "</p>"
)

HOME = f"""<html><head><title>Acme – Reporting widgets for agencies</title>
<meta name="description"
 content="Acme builds reporting widgets for marketing agencies in Europe and beyond.">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Organization",
 "name":"Acme","url":"https://www.acme.com/","description":"Acme makes reporting widgets.",
 "telephone":"+33 1 23 45 67 89","address":{{"@type":"PostalAddress","addressLocality":"Paris"}},
 "sameAs":["https://www.linkedin.com/company/acme"]}}</script></head>
<body><main><h1>Acme</h1><h2>Our products</h2>
<p>Acme is built for marketing agencies. We are based in Paris and serve clients worldwide.
Rated 4.8/5 on G2. Contact hello@acme.com.</p>{FILLER}</main></body></html>"""

PRODUCT = f"""<html><head><title>Widget – Acme</title>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product",
 "name":"Widget","description":"Automated client reporting.",
 "offers":{{"@type":"Offer","price":"29","priceCurrency":"USD"}}}}</script>
</head><body><main><h1>Widget</h1><h2>Features</h2>
<p>Plans start at $29 per month. Widget integrates
with Slack and HubSpot.</p><h2>What is Widget?</h2><p>A tool.</p><h2>How does pricing work?</h2>
<p>Monthly.</p><h2>Can I cancel?</h2><p>Yes.</p>{FILLER}</main></body></html>"""

ARTICLE = f"""<html><head><title>Agency reporting benchmark 2024 – Acme</title>
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2024-03-01T00:00:00Z">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article",
 "headline":"Benchmark",
 "author":{{"@type":"Person","name":"Jane Doe","jobTitle":"Head of Data"}},
 "publisher":{{"@type":"Organization","name":"Acme"}},"datePublished":"2024-03-01"}}</script>
</head><body><main><h1>Agency reporting benchmark 2024</h1><p>By Jane Doe</p>
<p>We surveyed 1,200 agencies in 2024. 63% spend more than 10 hours per week on reports, according
to our data. Sources: [1] <a href="https://www.example.org/study">Example study</a>.</p>
{FILLER}</main></body></html>"""

GENERIC = (
    "<p>" + "We believe good work comes from caring about the craft and the people. " * 45 + "</p>"
)
PLAIN = (
    "<html><head><title>Thoughts</title></head><body><main><h1>Thoughts</h1>"
    f"{GENERIC}</main></body></html>"
)


@pytest.fixture
def dispatched(client: AsyncClient) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_readiness_dispatcher] = lambda: calls.append
    return calls


async def seed(session: AsyncSession, project_id: str) -> None:
    pid = uuid.UUID(project_id)
    now = datetime.now(UTC)
    repo = PageIntelligenceRepository(session)
    for path, body in (
        ("", HOME),
        ("products/widget", PRODUCT),
        ("blog/benchmark", ARTICLE),
        ("blog/thoughts", PLAIN),
    ):
        url = ROOT + path
        parsed = process_html(body.encode(), normalize_crawl_url(url))
        intel = analyze_page(
            body.encode(), normalize_crawl_url(url), allowed_hosts=frozenset({"www.acme.com"})
        )
        page = WebsitePage(
            project_id=pid,
            url=url,
            normalized_url=url,
            http_status=200,
            content_type="text/html",
            title=parsed.title,
            meta_description=parsed.meta_description,
            word_count=intel.content.word_count,
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(page)
        await session.flush()
        await repo.replace_for_page(page, None, intel)
    await repo.resolve_internal_links(pid)
    await session.flush()
    await run_entity_analysis(session, pid)


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="Readiness Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, website_url=ROOT, name="Acme"))["id"]
    return h, org, pid


async def _run(session: AsyncSession, audit_id: str) -> AiReadinessAudit:
    audit = await session.get(AiReadinessAudit, uuid.UUID(audit_id))
    assert audit is not None
    return await run_readiness_audit(session, audit)


async def test_audit_round_trip(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    await seed(db_session, pid)
    resp = await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)
    assert resp.status_code == 202, resp.text
    audit = resp.json()
    assert audit["status"] == "queued" and audit["readiness_score"] is None
    assert dispatched == [uuid.UUID(audit["id"])]

    await _run(db_session, audit["id"])

    got = (await client.get(f"/api/v1/ai-readiness-audits/{audit['id']}", headers=h)).json()
    assert got["status"] == "completed", got
    assert got["pages_analyzed"] == 4 and got["observations_total"] == got["observation_count"] > 0
    assert 0 < got["readiness_score"] <= 100
    bd = got["score_breakdown"]
    assert bd["method"] == "ai-readiness-score/v1" and "Not an industry standard" in bd["note"]
    assert "industry standard" in got["note"]
    cats = bd["categories"]
    assert cats["comparison"]["weight"] == 0.0
    assert cats["entity_clarity"]["applicable"] and cats["entity_clarity"]["value"] == 1.0
    assert cats["product_clarity"]["inputs"]["pages"] == 1
    assert cats["authority"]["inputs"]["pages"] == 2  # benchmark + thoughts (blog path)
    assert got["summary"]["page_kinds"]["product"] == 1 and got["summary"]["organization_entity"]

    by_code = {o["code"]: o for o in got["observations"]}
    assert "entity_clarity_complete" in by_code
    assert by_code["faq_content_without_schema"]["evidence"]["urls"] == [ROOT + "products/widget"]
    assert by_code["article_author_missing"]["evidence"]["urls"] == [ROOT + "blog/thoughts"]
    assert (
        by_code["content_specificity_low"]["evidence"]["pages"][0]["url"] == ROOT + "blog/thoughts"
    )
    assert by_code["evidence_summary"]["evidence"]["pages_per_kind"]["statistics"] >= 1
    assert by_code["evidence_summary"]["evidence"]["pages_per_kind"]["references"] == 1
    assert by_code["comparison_pages_absent"]["severity"] == "info"
    assert by_code["entity_facts_consistent"]["category"] == "factual_consistency"
    assert all(o["recommendation"] for o in got["observations"])
    sev = [
        {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[o["severity"]]
        for o in got["observations"]
    ]
    assert sev == sorted(sev)

    only = (
        await client.get(
            f"/api/v1/ai-readiness-audits/{audit['id']}", params={"category": "faq"}, headers=h
        )
    ).json()
    assert {o["category"] for o in only["observations"]} == {"faq"}
    listed = (await client.get(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)).json()
    assert listed["total"] == 1 and listed["items"][0]["readiness_score"] == got["readiness_score"]


async def test_requires_crawled_pages_and_records_dispatch_failure(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_readiness_dispatcher] = lambda: lambda _: None
    assert (
        await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)
    ).status_code == 422
    await seed(db_session, pid)

    def boom(_: uuid.UUID) -> None:
        raise ConnectionError("broker down")

    app.dependency_overrides[get_readiness_dispatcher] = lambda: boom
    resp = await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)
    assert resp.status_code == 202 and resp.json()["status"] == "failed"


async def test_analysis_failure_is_recorded(
    client: AsyncClient,
    dispatched: list[uuid.UUID],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, _, pid = await _setup(client)
    await seed(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)).json()

    async def broken(*_: object, **__: object) -> object:
        raise ValueError("bad input")

    monkeypatch.setattr("app.ai_readiness.engine.build_context", broken)
    result = await _run(db_session, audit["id"])
    assert result.status.value == "failed" and result.error_message == "ValueError: bad input"


async def test_authorization(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, org, pid = await _setup(client)
    await seed(db_session, pid)
    audit = (await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=h)).json()
    await _run(db_session, audit["id"])

    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=stranger)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/ai-readiness-audits/{audit['id']}", headers=stranger)
    ).status_code == 404
    assert (await client.get(f"/api/v1/ai-readiness-audits/{audit['id']}")).status_code == 401
    assert (
        await client.get(f"/api/v1/ai-readiness-audits/{uuid.uuid4()}", headers=h)
    ).status_code == 404

    viewer = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer))
    assert (
        await client.get(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=v)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/ai-readiness-audits/{audit['id']}", headers=v)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/ai-readiness-audits", headers=v)
    ).status_code == 403
    assert len(dispatched) == 1
