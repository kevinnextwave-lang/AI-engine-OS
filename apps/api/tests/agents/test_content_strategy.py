"""Milestone 6C — Content Strategy Agent (fixture data, no live providers)."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.content_strategy import ContentStrategyAgent
from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry
from app.models.agents import AgentRun
from app.models.competitor import Competitor
from app.models.content_briefs import ContentBrief
from app.models.content_gaps import ContentGap
from app.models.crawl import WebsitePage
from app.models.gaps import CitationGap
from app.models.intelligence import ResponseClaim
from app.models.project import Project
from app.models.prompts import AiResponse, Prompt, PromptRun
from app.models.sources import SourceDomain
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio

COMPARISON_PROMPT = "Ledgerly vs QuickBooks for construction companies"
FAQ_PROMPT = "How does construction job costing work in accounting software?"


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(ContentStrategyAgent())
    return reg


async def _fixture(client: AsyncClient, db_session: AsyncSession) -> tuple[dict, str]:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    from app.models.prompts import FunnelStage, PromptCategory

    comparison_prompt = await s.prompt(
        COMPARISON_PROMPT, category=PromptCategory.COMPARISON, funnel_stage=FunnelStage.DECISION
    )
    await s.prompt(
        FAQ_PROMPT,
        category=PromptCategory.PROBLEM_SOLUTION,
        funnel_stage=FunnelStage.CONSIDERATION,
    )
    for i in range(12):
        await s.observation(
            prompt=COMPARISON_PROMPT,
            days_ago=1 + i,
            mentioned=i % 4 == 0,
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
    db_session.add(
        ContentGap(
            project_id=uuid.UUID(pid),
            prompt_id=comparison_prompt.id,
            topic="construction accounting comparison",
            normalized_topic="accounting comparison construction",
            gap_type="missing_comparison",
            competitor_evidence={
                "prompt": COMPARISON_PROMPT,
                "prompt_id": str(comparison_prompt.id),
                "top_competitor": "QuickBooks",
                "top_competitor_rate": 100.0,
                "brand_mention_rate": 25.0,
                "providers": ["openai"],
                "research_domains": [],
            },
            customer_coverage={},
            opportunity_score=84.0,
            confidence="high",
            analysis_version="content-gaps/v1",
            window_days=90,
            analyzed_at=NOW,
        )
    )
    db_session.add(
        ContentGap(
            project_id=uuid.UUID(pid),
            topic="construction job costing",
            normalized_topic="construction costing job",
            gap_type="missing_faq",
            competitor_evidence={
                "prompt": FAQ_PROMPT,
                "top_competitor": "QuickBooks",
                "top_competitor_rate": 80.0,
                "brand_mention_rate": 10.0,
                "providers": ["openai"],
            },
            customer_coverage={},
            opportunity_score=71.0,
            confidence="medium",
            analysis_version="content-gaps/v1",
            window_days=90,
            analyzed_at=NOW,
        )
    )
    # a low-opportunity gap that must NOT become a brief
    db_session.add(
        ContentGap(
            project_id=uuid.UUID(pid),
            topic="misc bookkeeping",
            normalized_topic="bookkeeping misc",
            gap_type="missing_topic",
            competitor_evidence={},
            customer_coverage={},
            opportunity_score=35.0,
            confidence="low",
            analysis_version="content-gaps/v1",
            window_days=90,
            analyzed_at=NOW,
        )
    )
    g2 = SourceDomain(
        hostname="g2.com",
        normalized_hostname="g2.com",
        display_name="G2",
        domain_type="review",
        is_authority=True,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    qb_site = SourceDomain(
        hostname="quickbooks.intuit.com",
        normalized_hostname="quickbooks.intuit.com",
        display_name="QuickBooks",
        domain_type="company",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add_all([g2, qb_site])
    await db_session.flush()
    for dom, score in ((g2, 80.0), (qb_site, 90.0)):
        db_session.add(
            CitationGap(
                project_id=uuid.UUID(pid),
                source_domain_id=dom.id,
                gap_type="brand_absent",
                brand_citations=0,
                competitor_citations=12,
                relevant_response_count=15,
                opportunity_score=score,
                confidence="high",
                explanation="seeded",
                competitors={"QuickBooks": 12},
                evidence={},
                analysis_version="citation-gaps/v1",
                analyzed_at=NOW,
            )
        )
    db_session.add(
        WebsitePage(
            project_id=uuid.UUID(pid),
            url="https://www.ledgerly.example/industries/construction",
            normalized_url="https://www.ledgerly.example/industries/construction",
            http_status=200,
            content_type="text/html",
            title="Construction accounting with Ledgerly",
            word_count=700,
            first_crawled_at=NOW,
            last_crawled_at=NOW,
        )
    )
    # a claim AI answers make about QuickBooks on the topic
    rid = (
        await db_session.scalars(
            select(AiResponse.id)
            .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
            .where(PromptRun.project_id == uuid.UUID(pid))
            .limit(1)
        )
    ).one()
    db_session.add(
        ResponseClaim(
            ai_response_id=rid,
            project_id=uuid.UUID(pid),
            subject="QuickBooks",
            predicate="offers",
            object="construction job costing reports",
            confidence=0.7,
            context="",
            parser_version="response-parser/v1",
        )
    )
    await db_session.flush()
    return h, pid


async def _run(db_session: AsyncSession, pid: str) -> AgentRun:
    project = await db_session.get(Project, uuid.UUID(pid))
    assert project is not None
    orch = AgentOrchestrator(db_session, registry=_registry())
    run = await orch.create_run(
        project, "content-strategy", objective="prepare briefs", user_id=None
    )
    return await orch.execute(run.id)


async def _briefs(db_session: AsyncSession, pid: str) -> list[ContentBrief]:
    return list(
        (
            await db_session.scalars(
                select(ContentBrief).where(ContentBrief.project_id == uuid.UUID(pid))
            )
        ).all()
    )


# --- brief generation ------------------------------------------------------------------


async def test_brief_generation(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    run = await _run(db_session, pid)
    assert run.status == "awaiting_approval", run.error_message  # review actions pend
    briefs = await _briefs(db_session, pid)
    assert len(briefs) == 2  # the 35-score gap produced no brief
    by_type = {b.content_type: b for b in briefs}
    comparison, faq = by_type["comparison_page"], by_type["faq_page"]
    assert comparison.title == "Ledgerly vs QuickBooks: Construction accounting comparison"
    assert comparison.status == "draft" and comparison.agent_run_id == run.id
    assert "opportunity 84" in comparison.objective
    assert "guaranteed" in comparison.objective  # explicit "no ... guaranteed" disclaimer
    assert comparison.search_intent.startswith("Compare specific options")
    assert "buyers deciding between specific products" in comparison.audience
    structure = comparison.outline["structure"]
    assert structure[0].startswith("H1:") and any(x.startswith("H2:") for x in structure)
    assert any(x.startswith("FAQ") for x in structure)
    assert any(x.startswith("Sources") for x in structure)
    assert faq.title == "Construction job costing: frequently asked questions"
    # API surface
    listing = (await client.get(f"/api/v1/projects/{pid}/content-briefs", headers=h)).json()
    assert listing["total"] == 2
    got = (await client.get(f"/api/v1/content-briefs/{comparison.id}", headers=h)).json()
    assert got["content_type"] == "comparison_page" and got["status"] == "draft"


async def test_rerun_updates_briefs_and_keeps_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    briefs = await _briefs(db_session, pid)
    brief = briefs[0]
    r = await client.patch(
        f"/api/v1/content-briefs/{brief.id}", json={"status": "approved"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    await _run(db_session, pid)  # regenerate
    again = await _briefs(db_session, pid)
    assert len(again) == 2  # upsert, no duplicates
    await db_session.refresh(brief)
    assert brief.status == "approved"  # review status survives re-save


# --- evidence requirements -------------------------------------------------------------


async def test_evidence_requirements(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    comparison = next(
        b for b in await _briefs(db_session, pid) if b.content_type == "comparison_page"
    )
    ev = comparison.evidence_requirements
    assert set(ev) >= {"data", "research", "citations", "examples", "customer_evidence", "rule"}
    assert ev["data"]["required"] is True  # comparisons need real numbers
    assert ev["citations"]["required"] is True
    assert "Do not fabricate" in ev["rule"]
    assert "g2.com" in ev["citations"]["candidate_sources"]
    # never invented: candidate sources come only from observed citation gaps
    assert set(ev["citations"]["candidate_sources"]) <= {"g2.com"}
    # information requirements address the observed competitor claim, with a caveat
    info = " ".join(comparison.information_requirements)
    assert "construction job costing reports" in info and "verify" in info.lower()


# --- competitor integration ------------------------------------------------------------


async def test_competitor_integration(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    comparison = next(
        b for b in await _briefs(db_session, pid) if b.content_type == "comparison_page"
    )
    qb_id = (
        await db_session.scalars(
            select(Competitor.id).where(
                Competitor.project_id == uuid.UUID(pid), Competitor.name == "QuickBooks"
            )
        )
    ).one()
    assert comparison.competitor_ids == [str(qb_id)]
    assert "QuickBooks" in comparison.differentiation
    assert any("QuickBooks" in e for e in comparison.entity_requirements)
    # competitor-owned sites are never citation opportunities
    assert all(c["domain"] != "quickbooks.intuit.com" for c in comparison.citation_opportunities)


# --- prompt mapping --------------------------------------------------------------------


async def test_prompt_mapping(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    briefs = {b.content_type: b for b in await _briefs(db_session, pid)}
    project_prompts = {
        str(p)
        for p in (
            await db_session.scalars(select(Prompt.id).where(Prompt.project_id == uuid.UUID(pid)))
        ).all()
    }
    comparison = briefs["comparison_page"]
    assert comparison.target_prompt_ids  # actual prompts from the project
    assert set(comparison.target_prompt_ids) <= project_prompts
    # the gap's own prompt is targeted first
    texts = {
        p.text: str(p.id)
        for p in (
            await db_session.scalars(select(Prompt).where(Prompt.project_id == uuid.UUID(pid)))
        ).all()
    }
    assert comparison.target_prompt_ids[0] == texts[COMPARISON_PROMPT]
    # internal links point at the real matching page
    assert briefs["faq_page"].internal_link_recommendations == [] or all(
        "ledgerly.example" in rec["url"] for rec in briefs["faq_page"].internal_link_recommendations
    )
    assert any("construction" in link["url"] for link in comparison.internal_link_recommendations)


# --- hallucination prevention ----------------------------------------------------------


async def test_hallucination_prevention(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    run = await _run(db_session, pid)
    blob = json.dumps((run.result or {}), default=str) + json.dumps(
        [
            {
                "t": b.title,
                "o": b.objective,
                "i": b.information_requirements,
                "e": b.evidence_requirements,
                "c": b.citation_opportunities,
                "links": b.internal_link_recommendations,
            }
            for b in await _briefs(db_session, pid)
        ],
        default=str,
    )
    # nothing invented: no unseeded competitors, domains or numbers-with-claims
    for invented in ("FreshBooks", "capterra", "forrester", "According to a survey"):
        assert invented.lower() not in blob.lower()
    # "testimonials" may appear only inside the anti-fabrication rule itself
    rule_free = blob.lower().replace(
        "do not fabricate statistics, customer testimonials, citations, reviews or "
        "credentials, and do not claim guaranteed ai rankings.",
        "",
    )
    assert "testimonial" not in rule_free
    # no ranking guarantees anywhere
    assert "guaranteed AI" not in blob or "not claim guaranteed" in blob
    assert "No ranking or citation outcome is guaranteed." in blob
    # prompts referenced verbatim exist in the project
    assert COMPARISON_PROMPT in blob
    # empty project → zero briefs, zero findings
    _, _, pid2 = await project_with_competitors(client)
    run2 = await _run(db_session, pid2)
    assert run2.status == "completed"
    assert (run2.result or {})["findings"] == []
    assert await _briefs(db_session, pid2) == []
    assert any("No content gap met" in w for w in (run2.result or {})["warnings"])


# --- authorization ---------------------------------------------------------------------


async def test_authorization(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture(client, db_session)
    await _run(db_session, pid)
    brief = (await _briefs(db_session, pid))[0]

    other = await signup(client, org="Brief Other Org")
    oh = auth_header(other["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/content-briefs", headers=oh)
    ).status_code == 404
    assert (await client.get(f"/api/v1/content-briefs/{brief.id}", headers=oh)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/content-briefs/{brief.id}", json={"status": "archived"}, headers=oh
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/content-briefs")).status_code == 401
    # owner can archive
    r = await client.patch(
        f"/api/v1/content-briefs/{brief.id}", json={"status": "archived"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "archived"
