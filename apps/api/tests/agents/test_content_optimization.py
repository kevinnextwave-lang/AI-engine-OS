"""Milestone 6D — GEO Content Optimization Agent (fixture data, no live providers)."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.content_optimization import ContentOptimizationAgent
from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry
from app.models.agents import AgentRun
from app.models.content_reviews import ContentOptimizationReview
from app.models.crawl import CrawlJob, CrawlStatus, CrawlType, PageVersion, WebsitePage
from app.models.page_intelligence import PageHeading
from app.models.project import Project
from app.models.prompts import FunnelStage, PromptCategory
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio

PAGE_TEXT = (
    "We provide powerful solutions for modern businesses. "
    "Our platform is the fastest accounting tool with 95% customer satisfaction. "
    "Construction companies use our software to track project costs across jobs. "
    "Invoices can be created and sent to clients from one dashboard. "
    "Teams reconcile bank transactions and generate reports for accountants. "
) * 3  # comfortably above the minimum analyzable length

PROMPT = "How do construction companies track project costs in accounting software?"


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(ContentOptimizationAgent())
    return reg


async def _fixture(client: AsyncClient, db_session: AsyncSession) -> tuple[dict, str, uuid.UUID]:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await s.prompt(
        PROMPT, category=PromptCategory.PROBLEM_SOLUTION, funnel_stage=FunnelStage.CONSIDERATION
    )
    page = WebsitePage(
        project_id=uuid.UUID(pid),
        url="https://www.ledgerly.example/construction-accounting",
        normalized_url="https://www.ledgerly.example/construction-accounting",
        http_status=200,
        content_type="text/html",
        title="Construction accounting software",
        meta_description=None,  # missing on purpose
        word_count=len(PAGE_TEXT.split()),
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )
    other = WebsitePage(
        project_id=uuid.UUID(pid),
        url="https://www.ledgerly.example/blog/construction-invoicing-guide",
        normalized_url="https://www.ledgerly.example/blog/construction-invoicing-guide",
        http_status=200,
        content_type="text/html",
        title="Construction invoicing guide",
        word_count=900,
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )
    db_session.add_all([page, other])
    crawl = CrawlJob(
        project_id=uuid.UUID(pid),
        root_url="https://www.ledgerly.example/",
        crawl_type=CrawlType.FULL,
        status=CrawlStatus.COMPLETED,
        max_pages=10,
        max_depth=2,
    )
    db_session.add(crawl)
    await db_session.flush()
    db_session.add(
        PageVersion(
            page_id=page.id,
            project_id=uuid.UUID(pid),
            crawl_job_id=crawl.id,
            http_status=200,
            title=page.title,
            word_count=page.word_count,
            extracted_text=PAGE_TEXT,
            crawled_at=NOW,
        )
    )
    db_session.add(
        PageHeading(
            page_id=page.id,
            project_id=uuid.UUID(pid),
            level=1,
            position=0,
            text="Construction accounting software",
        )
    )
    await db_session.flush()
    return h, pid, page.id


async def _run(db_session: AsyncSession, pid: str) -> AgentRun:
    project = await db_session.get(Project, uuid.UUID(pid))
    assert project is not None
    orch = AgentOrchestrator(db_session, registry=_registry())
    run = await orch.create_run(
        project, "content-optimization", objective="review pages", user_id=None
    )
    return await orch.execute(run.id)


async def _review(db_session: AsyncSession, page_id: uuid.UUID) -> ContentOptimizationReview:
    return (
        await db_session.scalars(
            select(ContentOptimizationReview).where(ContentOptimizationReview.page_id == page_id)
        )
    ).one()


# --- content analysis ------------------------------------------------------------------


async def test_content_analysis(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    run = await _run(db_session, pid)
    assert run.status == "awaiting_approval", run.error_message  # review actions pend
    review = await _review(db_session, page_id)
    assert review.status == "draft" and review.agent_run_id == run.id
    assert 0 <= review.score < 100  # deductions were applied
    categories = {f["category"] for f in review.findings}
    assert "specificity" in categories  # "powerful solutions"
    assert "evidence" in categories  # "fastest", "95%"
    assert "structure" in categories  # missing meta, no FAQ despite question prompt
    assert "entity_clarity" in categories  # brand not named, no org entity on page
    # internal linking recommends the real related page
    linking = next(r for r in review.recommendations if r["category"] == "internal_linking")
    assert any("construction-invoicing-guide" in p["url"] for p in linking["pages"])
    # no guaranteed-ranking claims anywhere
    blob = (
        json.dumps(review.findings)
        + json.dumps(review.recommendations)
        + json.dumps(review.proposed_changes)
        + json.dumps(run.result or {}, default=str)
    )
    assert "guarantee any AI ranking" in blob or "cannot guarantee" in blob
    assert "guaranteed ranking" not in blob.lower().replace("cannot guarantee", "")


async def test_structured_recommendations(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    # FAQ change proposed because a question-form prompt targets the page
    faq = next(c for c in review.proposed_changes if c["location"] == "new FAQ section")
    assert PROMPT in faq["proposed_text"]
    # markup only where justified: no FAQPage/Product recommendation without
    # question headings or product entities; nothing recommended "because it exists"
    markup = [r for r in review.recommendations if r["category"] == "entity_markup"]
    if markup:
        text = markup[0]["recommendation"]
        assert "FAQPage" not in text  # page has no question-form headings yet
        assert "Product schema" not in text  # no product entities on this page


# --- evidence handling -----------------------------------------------------------------


async def test_evidence_handling(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    evidence_changes = [
        c for c in review.proposed_changes if "checkable claim" in c["reason"].lower()
    ]
    assert any("fastest" in c["current_text"].lower() for c in evidence_changes)
    assert evidence_changes
    for c in evidence_changes:
        assert "Do not invent evidence" in c["proposed_text"]
        assert "[FILL:" in c["proposed_text"]
        # the proposal adds a sourcing instruction, never a fabricated source
        assert "study shows" not in c["proposed_text"].lower()
    rec = next(r for r in review.recommendations if r["category"] == "evidence")
    assert "Never fabricate" in rec["recommendation"]


# --- proposed changes ------------------------------------------------------------------


async def test_proposed_changes_format(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    assert review.proposed_changes
    for c in review.proposed_changes:
        assert set(c) >= {
            "change_id",
            "location",
            "current_text",
            "proposed_text",
            "reason",
            "evidence",
            "confidence",
            "decision",
        }
        assert c["decision"] == "pending"
        assert c["confidence"] in ("high", "medium", "low")
    vague = next(c for c in review.proposed_changes if "vague" in c["reason"].lower())
    assert "powerful solutions" in vague["current_text"]
    assert "[FILL:" in vague["proposed_text"]  # improvements, never invented facts
    assert "vague" in vague["reason"].lower()


async def test_decisions_and_rerun_carry_over(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    changes = review.proposed_changes
    accept_id, edit_id, reject_id = (
        changes[0]["change_id"],
        changes[1]["change_id"],
        changes[2]["change_id"],
    )
    r = await client.post(
        f"/api/v1/content-reviews/{review.id}/changes/{accept_id}",
        json={"action": "accept"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    accepted = next(c for c in body["proposed_changes"] if c["change_id"] == accept_id)
    assert accepted["decision"] == "accepted"
    assert accepted["decided_text"] == accepted["proposed_text"]
    assert body["status"] == "reviewing"  # first decision moves draft → reviewing

    r = await client.post(
        f"/api/v1/content-reviews/{review.id}/changes/{edit_id}",
        json={"action": "edit", "text": "Our platform automates invoice creation."},
        headers=h,
    )
    edited = next(c for c in r.json()["proposed_changes"] if c["change_id"] == edit_id)
    assert edited["decision"] == "edited"
    assert edited["decided_text"] == "Our platform automates invoice creation."
    # edit without text is refused
    assert (
        await client.post(
            f"/api/v1/content-reviews/{review.id}/changes/{edit_id}",
            json={"action": "edit"},
            headers=h,
        )
    ).status_code == 409
    r = await client.post(
        f"/api/v1/content-reviews/{review.id}/changes/{reject_id}",
        json={"action": "reject"},
        headers=h,
    )
    rejected = next(c for c in r.json()["proposed_changes"] if c["change_id"] == reject_id)
    assert rejected["decision"] == "rejected" and rejected["decided_text"] is None

    # re-running the agent keeps the review row, its status and the decisions
    await _run(db_session, pid)
    await db_session.refresh(review)
    assert review.status == "reviewing"
    by_id = {c["change_id"]: c for c in review.proposed_changes}
    assert by_id[accept_id]["decision"] == "accepted"
    assert by_id[edit_id]["decision"] == "edited"
    assert by_id[edit_id]["decided_text"] == "Our platform automates invoice creation."
    assert by_id[reject_id]["decision"] == "rejected"
    # listing shows pending counts
    listing = (await client.get(f"/api/v1/projects/{pid}/content-reviews", headers=h)).json()
    assert listing["total"] == 1
    assert listing["items"][0]["pending_changes"] == len(review.proposed_changes) - 3


# --- original content preservation -----------------------------------------------------


async def test_original_content_preserved(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    page_before = await db_session.get(WebsitePage, page_id)
    assert page_before is not None
    title_before = page_before.title
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    change_id = review.proposed_changes[0]["change_id"]
    await client.post(
        f"/api/v1/content-reviews/{review.id}/changes/{change_id}",
        json={"action": "accept"},
        headers=h,
    )
    # the page row and its crawled text are untouched by run + accept
    await db_session.refresh(page_before)
    assert page_before.title == title_before
    version = (
        await db_session.scalars(select(PageVersion).where(PageVersion.page_id == page_id))
    ).one()
    assert version.extracted_text == PAGE_TEXT


# --- authorization ---------------------------------------------------------------------


async def test_authorization(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, page_id = await _fixture(client, db_session)
    await _run(db_session, pid)
    review = await _review(db_session, page_id)
    change_id = review.proposed_changes[0]["change_id"]

    other = await signup(client, org="Review Other Org")
    oh = auth_header(other["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/content-reviews", headers=oh)
    ).status_code == 404
    assert (await client.get(f"/api/v1/content-reviews/{review.id}", headers=oh)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/content-reviews/{review.id}", json={"status": "archived"}, headers=oh
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/content-reviews/{review.id}/changes/{change_id}",
            json={"action": "accept"},
            headers=oh,
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/content-reviews")).status_code == 401
    # owner archives
    r = await client.patch(
        f"/api/v1/content-reviews/{review.id}", json={"status": "archived"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "archived"
