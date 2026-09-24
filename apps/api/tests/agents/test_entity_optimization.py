"""Milestone 6E — Entity Optimization Agent (fixture data, no live providers)."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.entity_optimization import EntityOptimizationAgent
from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry
from app.models.agents import AgentRun
from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityLink
from app.models.entity_reviews import EntityOptimizationReview
from app.models.project import Project
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, project_with_competitors

pytestmark = pytest.mark.anyio


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(EntityOptimizationAgent())
    return reg


def _page(pid: str, url: str, title: str) -> WebsitePage:
    return WebsitePage(
        project_id=uuid.UUID(pid),
        url=url,
        normalized_url=url,
        http_status=200,
        content_type="text/html",
        title=title,
        word_count=500,
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )


async def _fixture(
    client: AsyncClient, db_session: AsyncSession, *, with_conflicts: bool = True
) -> tuple[dict, str]:
    """Crawled site with: two conflicting Organization declarations (name +
    sameAs differ), one incomplete Product entity, and no people."""
    h, _, pid = await project_with_competitors(client)
    home = _page(pid, "https://www.ledgerly.example/", "Ledgerly")
    about = _page(pid, "https://www.ledgerly.example/about", "About Ledgerly")
    product_page = _page(pid, "https://www.ledgerly.example/product", "Ledgerly product")
    db_session.add_all([home, about, product_page])
    await db_session.flush()
    org_home = Entity(
        project_id=uuid.UUID(pid),
        page_id=home.id,
        entity_type="Organization",
        name="Ledgerly",
        description="Accounting software for small teams.",
        url="https://www.ledgerly.example",
        same_as=["https://www.linkedin.com/company/ledgerly"],
        properties={"logo": "https://www.ledgerly.example/logo.png"},
    )
    org_about = Entity(
        project_id=uuid.UUID(pid),
        page_id=about.id,
        entity_type="Organization",
        name="Ledgerly Inc." if with_conflicts else "Ledgerly",
        description="The modern ledger platform."
        if with_conflicts
        else ("Accounting software for small teams."),
        same_as=[] if with_conflicts else ["https://www.linkedin.com/company/ledgerly"],
        properties={},
    )
    product = Entity(
        project_id=uuid.UUID(pid),
        page_id=product_page.id,
        entity_type="Product",
        name="Ledgerly Books",
        description=None,  # missing on purpose
        url=None,  # missing on purpose
        properties={},  # no brand/publisher → not connected to the organization
    )
    db_session.add_all([org_home, org_about, product])
    await db_session.flush()
    db_session.add(
        EntityLink(
            entity_id=org_home.id,
            project_id=uuid.UUID(pid),
            url="https://www.linkedin.com/company/ledgerly",
            platform="linkedin",
            is_authoritative=True,
        )
    )
    await db_session.flush()
    return h, pid


async def _run(db_session: AsyncSession, pid: str) -> AgentRun:
    project = await db_session.get(Project, uuid.UUID(pid))
    assert project is not None
    orch = AgentOrchestrator(db_session, registry=_registry())
    run = await orch.create_run(
        project, "entity-optimization", objective="review entities", user_id=None
    )
    return await orch.execute(run.id)


async def _reviews(db_session: AsyncSession, pid: str) -> dict[str, EntityOptimizationReview]:
    rows = (
        await db_session.scalars(
            select(EntityOptimizationReview).where(
                EntityOptimizationReview.project_id == uuid.UUID(pid)
            )
        )
    ).all()
    return {r.review_key: r for r in rows}


# --- organization analysis -------------------------------------------------------------


async def test_organization_analysis(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    run = await _run(db_session, pid)
    assert run.status == "awaiting_approval", run.error_message  # approvals pend
    reviews = await _reviews(db_session, pid)
    org = reviews["organization"]
    assert org.entity_type == "organization" and org.status == "draft"
    assert org.entity_id is not None  # anchored to the richest org entity
    aspects = {f["aspect"] for f in org.findings}
    # home org has name/description/url/logo/sameAs but no contact or address
    assert "contact information" in aspects
    assert "location" in aspects
    assert "founding information" in aspects  # low severity, "only if known"
    founding = next(f for f in org.findings if f["aspect"] == "founding information")
    assert "do not guess" in founding["detail"]
    # aspects that ARE present are not flagged
    assert "description" not in aspects and "logo" not in aspects
    # no unsupported claims about engine interpretation
    blob = json.dumps(org.recommendations)
    assert "not guaranteed" in blob
    assert "will rank" not in blob and "will boost" not in blob


async def test_missing_organization_entirely(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    db_session.add(_page(pid, "https://www.ledgerly.example/", "Ledgerly"))
    await db_session.flush()
    await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    org = reviews["organization"]
    assert org.entity_id is None and org.confidence == "high"  # absence directly observed
    assert any(
        r["recommendation"] == "Add appropriate Organization structured data"
        for r in org.recommendations
    )


# --- product analysis ------------------------------------------------------------------


async def test_product_analysis(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    product = reviews["product:ledgerly books"]
    assert product.entity_type == "product"
    aspects = {f["aspect"] for f in product.findings}
    assert {"description", "URL", "relationship to organization"} <= aspects
    assert "features" in aspects and "pricing" in aspects and "audience" in aspects
    recs = {r["recommendation"] for r in product.recommendations}
    assert "Improve product descriptions" in recs
    assert "Connect product entities to organization" in recs
    # name IS present → not flagged
    assert "product name" not in aspects


async def test_product_pages_without_product_entities(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    db_session.add(_page(pid, "https://www.ledgerly.example/pricing", "Pricing"))
    await db_session.flush()
    await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    assert "products" in reviews
    finding = reviews["products"].findings[0]
    assert "no Product" in finding["detail"]
    assert "https://www.ledgerly.example/pricing" in finding["pages"]


# --- consistency -----------------------------------------------------------------------


async def test_consistency(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session, with_conflicts=True)
    await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    consistency = reviews["consistency"]
    aspects = {f["aspect"] for f in consistency.findings}
    assert "conflicting names" in aspects  # "Ledgerly" vs "Ledgerly Inc."
    assert "conflicting descriptions" in aspects
    assert "inconsistent sameAs" in aspects
    names = next(f for f in consistency.findings if f["aspect"] == "conflicting names")
    declared = {c["name"] for c in names["conflicts"]}
    assert declared == {"Ledgerly", "Ledgerly Inc."}
    assert any(
        r["recommendation"] == "Resolve conflicting company information"
        for r in consistency.recommendations
    )


async def test_no_consistency_review_when_consistent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid = await _fixture(client, db_session, with_conflicts=False)
    await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    assert "consistency" not in reviews


# --- structured data & recommendations -------------------------------------------------


async def test_recommendations_and_rerun(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    run = await _run(db_session, pid)
    reviews = await _reviews(db_session, pid)
    # every recommendation carries the interpretation caveat and invents nothing
    for review in reviews.values():
        for rec in review.recommendations:
            assert rec["note"].endswith("is not guaranteed.")
        blob = json.dumps(review.findings) + json.dumps(review.recommendations)
        assert "founded in 20" not in blob  # no invented founding facts
        assert "award" not in blob.lower()  # no invented credentials
    # runs propose approval-gated actions only
    result = run.result or {}
    assert all(a["approval_required"] for a in result["proposed_actions"])
    assert "require human approval" in result["summary"]
    # PATCH approval workflow + status survives re-run
    org_id = reviews["organization"].id
    r = await client.patch(
        f"/api/v1/entity-reviews/{org_id}", json={"status": "approved"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    await _run(db_session, pid)
    again = await _reviews(db_session, pid)
    assert again["organization"].id == org_id  # upsert, no duplicates
    assert again["organization"].status == "approved"
    listing = (await client.get(f"/api/v1/projects/{pid}/entity-reviews", headers=h)).json()
    assert listing["total"] == len(reviews)
    typed = (
        await client.get(
            f"/api/v1/projects/{pid}/entity-reviews",
            params={"entity_type": "product"},
            headers=h,
        )
    ).json()
    assert all(i["entity_type"] == "product" for i in typed["items"])


# --- authorization ---------------------------------------------------------------------


async def test_authorization(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = next(iter((await _reviews(db_session, pid)).values()))

    other = await signup(client, org="Entity Other Org")
    oh = auth_header(other["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/entity-reviews", headers=oh)
    ).status_code == 404
    assert (await client.get(f"/api/v1/entity-reviews/{review.id}", headers=oh)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/entity-reviews/{review.id}", json={"status": "archived"}, headers=oh
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/entity-reviews")).status_code == 401
