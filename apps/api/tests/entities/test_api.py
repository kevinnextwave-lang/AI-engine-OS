"""Entity analysis over seeded pages -> API responses; RBAC and tenant isolation."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.entities import get_entity_dispatcher
from app.core.security import create_access_token
from app.crawler.intelligence import analyze_page
from app.crawler.urls import normalize_crawl_url
from app.entities.engine import run_entity_analysis
from app.models import MembershipRole, WebsitePage
from app.repositories.page_intelligence import PageIntelligenceRepository
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

ROOT = "https://www.acme.com/"

HOME = """<html><head><title>Acme</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"Organization","@id":"https://www.acme.com/#org","name":"Acme Inc.",
  "url":"https://www.acme.com/","foundingDate":"2018","telephone":"+33 1 23 45 67 89",
  "logo":"https://www.acme.com/logo.png",
  "sameAs":["https://www.linkedin.com/company/acme","https://www.wikidata.org/wiki/Q1",
            "https://x.com/acme"]},
 {"@type":"WebSite","name":"Acme","url":"https://www.acme.com/",
  "publisher":{"@id":"https://www.acme.com/#org"}}
]}</script></head><body><h1>Acme</h1>
<p>Contact: hello@acme.com or +33 1 23 45 67 89</p></body></html>"""

ABOUT = """<html><head><title>About</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",
 "name":"ACME, Inc.","url":"https://www.acme.com/","foundingDate":"2019",
 "sameAs":["https://www.linkedin.com/company/acme"],
 "founder":{"@type":"Person","name":"Jane Doe"}}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",
 "name":"Acme Inc."}</script>
</head><body><h1>About us</h1><p>Founded by Jane. Email press@acme.com</p></body></html>"""

BLOG = """<html><head><title>Post</title>
<script type="application/ld+json">{"@type":"BlogPosting","headline":"Hello",
 "author":{"name":"Jane Doe"}}</script>
<script type="application/ld+json">{"@context":"https://schema.org", "@type":"Article",</script>
</head><body><article itemscope itemtype="https://schema.org/Article">
<h1 itemprop="headline">Hello</h1>
<span itemprop="author" itemscope itemtype="https://schema.org/Person">
<span itemprop="name">Jane Doe</span></span>
</article></body></html>"""


@pytest.fixture
def dispatched(client: AsyncClient) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_entity_dispatcher] = lambda: calls.append
    return calls


async def seed(session: AsyncSession, project_id: str) -> dict[str, WebsitePage]:
    pid = uuid.UUID(project_id)
    now = datetime.now(UTC)
    repo = PageIntelligenceRepository(session)
    pages: dict[str, WebsitePage] = {}
    for path, body in (("", HOME), ("about", ABOUT), ("blog/hello", BLOG)):
        url = ROOT + path
        intel = analyze_page(
            body.encode(), normalize_crawl_url(url), allowed_hosts=frozenset({"www.acme.com"})
        )
        page = WebsitePage(
            project_id=pid,
            url=url,
            normalized_url=url,
            http_status=200,
            content_type="text/html",
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(page)
        await session.flush()
        await repo.replace_for_page(page, None, intel)
        pages[path or "/"] = page
    await session.flush()
    return pages


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="Entities Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, website_url=ROOT))["id"]
    return h, org, pid


async def test_entities_schema_and_consistency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    pages = await seed(db_session, pid)
    result = await run_entity_analysis(db_session, uuid.UUID(pid))
    assert result.organization_entity_id is not None

    # -- entities --------------------------------------------------------------
    body = (await client.get(f"/api/v1/projects/{pid}/entities", headers=h)).json()
    assert body["analyzed_at"] is not None
    types = {(e["entity_type"], e["name"]) for e in body["items"] if e["scope"] == "page"}
    assert ("Organization", "Acme Inc.") in types and ("WebSite", "Acme") in types
    assert ("Person", "Jane Doe") in types and ("Article", "Hello") in types  # microdata
    assert ("BlogPosting", "Hello") in types  # JSON-LD without @context still extracted
    org = body["organization"]
    assert org["scope"] == "project" and org["page_id"] is None
    assert org["name"] == "Acme Inc." and org["url"] == "https://www.acme.com/"
    assert org["properties"]["foundingDate"] == "2018"  # homepage wins, conflict recorded
    assert org["properties"]["_conflicts"]["foundingDate"][1]["value"] == "2019"
    assert org["properties"]["_signals"]["homepage_schema"] is True
    assert org["properties"]["_signals"]["about_page"] == ROOT + "about"
    assert set(org["properties"]["_signals"]["text_emails"]) == {"hello@acme.com", "press@acme.com"}
    assert org["properties"]["_signals"]["text_phones"] == ["+33 1 23 45 67 89"]
    assert org["properties"]["_confidence"] == "high"
    platforms = {ln["platform"]: ln["is_authoritative"] for ln in org["links"]}
    assert platforms == {"linkedin": False, "wikidata": True, "x": False}

    filtered = (
        await client.get(
            f"/api/v1/projects/{pid}/entities",
            params={"type": "Organization", "scope": "page"},
            headers=h,
        )
    ).json()
    assert {e["scope"] for e in filtered["items"]} == {"page"}
    assert filtered["total"] == 3  # home, about ×2
    only_project = (
        await client.get(f"/api/v1/projects/{pid}/entities", params={"scope": "project"}, headers=h)
    ).json()
    assert only_project["total"] == 1 and only_project["items"][0]["id"] == org["id"]

    # -- project schema ------------------------------------------------------
    schema = (await client.get(f"/api/v1/projects/{pid}/schema", headers=h)).json()
    s = schema["summary"]
    assert s["pages_crawled"] == 3 and s["pages_with_structured_data"] == 3
    assert s["formats"] == {"json_ld": 5, "microdata": 1}
    assert s["blocks_invalid"] == 1
    assert s["schema_types"]["Organization"] == 2 and s["schema_types"]["Article"] == 1
    assert "FAQPage" in s["known_types_absent"] and "Organization" in s["known_types_present"]
    assert s["issues_by_code"]["invalid_json"] == 1
    assert s["issues_by_code"]["missing_context"] == 1 and s["issues_by_code"]["missing_type"] == 1
    assert "rich-result" in schema["note"]
    invalid = next(i for i in schema["issues"] if i["code"] == "invalid_json")
    assert invalid["page_url"] == ROOT + "blog/hello" and invalid["severity"] == "high"

    # -- page schema ---------------------------------------------------------
    blog_id = pages["blog/hello"].id
    page_schema = (await client.get(f"/api/v1/pages/{blog_id}/schema", headers=h)).json()
    assert page_schema["url"] == ROOT + "blog/hello"
    assert [(b["format"], b["is_valid"]) for b in page_schema["blocks"]] == [
        ("json_ld", True),
        ("json_ld", False),
        ("microdata", True),
    ]
    first = page_schema["blocks"][0]
    assert {i["code"] for i in first["issues"]} == {"missing_context", "missing_type"}
    assert [e["entity_type"] for e in first["entities"]] == ["BlogPosting"]
    assert (
        page_schema["blocks"][1]["entities"] == [] and page_schema["blocks"][1]["payload"] is None
    )
    assert sorted(e["entity_type"] for e in page_schema["blocks"][2]["entities"]) == [
        "Article",
        "Person",
    ]

    # -- consistency ---------------------------------------------------------
    cons = (await client.get(f"/api/v1/projects/{pid}/entity-consistency", headers=h)).json()
    by_code = {}
    for o in cons["items"]:
        by_code.setdefault(o["code"], []).append(o)
    conflict = by_code["entity_value_conflict"]
    assert [c["evidence"]["property"] for c in conflict] == ["foundingDate"]
    assert conflict[0]["title"] == "Potential factual inconsistency"
    assert {v["value"] for v in conflict[0]["evidence"]["values"]} == {"2018", "2019"}
    assert by_code["same_as_inconsistent"][0]["severity"] == "info"
    dup = by_code["duplicate_entity"][0]
    assert dup["evidence"]["page_url"] == ROOT + "about" and dup["evidence"]["count"] == 2
    assert cons["entities_compared"] > 0 and "no value is assumed" in cons["note"]


async def test_rerun_is_idempotent_and_empty_project_is_fine(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    empty = await run_entity_analysis(db_session, uuid.UUID(pid))
    assert empty.entities == 0 and empty.organization_entity_id is None
    body = (await client.get(f"/api/v1/projects/{pid}/entities", headers=h)).json()
    assert body["total"] == 0 and body["organization"] is None and body["analyzed_at"] is None
    await seed(db_session, pid)
    first = await run_entity_analysis(db_session, uuid.UUID(pid))
    second = await run_entity_analysis(db_session, uuid.UUID(pid))
    assert (first.entities, first.observations) == (second.entities, second.observations)
    body = (
        await client.get(f"/api/v1/projects/{pid}/entities", params={"limit": 500}, headers=h)
    ).json()
    assert body["total"] == second.entities  # page entities + the project organization


async def test_start_analysis_dispatches(client: AsyncClient, dispatched: list[uuid.UUID]) -> None:
    h, _, pid = await _setup(client)
    resp = await client.post(f"/api/v1/projects/{pid}/entity-analysis", headers=h)
    assert resp.status_code == 202 and resp.json()["queued"] is True
    assert dispatched == [uuid.UUID(pid)]


async def test_authorization(
    client: AsyncClient, db_session: AsyncSession, dispatched: list[uuid.UUID]
) -> None:
    h, org, pid = await _setup(client)
    pages = await seed(db_session, pid)
    await run_entity_analysis(db_session, uuid.UUID(pid))
    page_id = pages["/"].id

    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    for path in (
        f"/api/v1/projects/{pid}/entities",
        f"/api/v1/projects/{pid}/schema",
        f"/api/v1/projects/{pid}/entity-consistency",
        f"/api/v1/pages/{page_id}/schema",
    ):
        assert (await client.get(path, headers=stranger)).status_code == 404, path
        assert (await client.get(path)).status_code == 401, path
    assert (
        await client.post(f"/api/v1/projects/{pid}/entity-analysis", headers=stranger)
    ).status_code == 404

    viewer = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer))
    assert (await client.get(f"/api/v1/projects/{pid}/entities", headers=v)).status_code == 200
    assert (await client.get(f"/api/v1/pages/{page_id}/schema", headers=v)).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/entity-analysis", headers=v)
    ).status_code == 403
    assert dispatched == []
