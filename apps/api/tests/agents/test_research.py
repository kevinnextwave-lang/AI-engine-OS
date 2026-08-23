"""Milestone 6B — Research Agent (fixture data, no live providers)."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry
from app.agents.research import ResearchAgent
from app.api.v1.routes.agents import get_agent_dispatcher, get_registry
from app.models.agents import AgentAction, AgentRun
from app.models.competitor_candidates import CandidateSource, CandidateStatus, CompetitorCandidate
from app.models.content_gaps import ContentGap
from app.models.crawl import CrawlJob, CrawlStatus, CrawlType, WebsitePage
from app.models.entities import Entity
from app.models.gaps import CitationGap
from app.models.intelligence import ResponseClaim
from app.models.project import Project
from app.models.prompts import AiResponse, PromptRun
from app.models.seo import AuditStatus, SeoAudit
from app.models.sources import SourceDomain
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(ResearchAgent())
    return reg


async def _fixture_project(client: AsyncClient, db_session: AsyncSession) -> tuple[dict, str]:
    """A project where QuickBooks clearly dominates, with one citation gap, one
    content gap, a thin Organization entity and one discovery candidate."""
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(24):
        await s.observation(
            prompt=f"research prompt {i % 4}",
            provider="openai" if i % 2 == 0 else "google",
            days_ago=1 + (i % 20),
            mentioned=i % 3 == 0,  # brand 33%
            position=2 if i % 3 == 0 else None,
            strength="moderate" if i % 3 == 0 else "unknown",
            competitors=[("QuickBooks", 1, "positive", "strong")],  # 100%
        )
    domain = SourceDomain(
        hostname="g2.com",
        normalized_hostname="g2.com",
        display_name="G2",
        domain_type="review",
        is_authority=True,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(
        CitationGap(
            project_id=uuid.UUID(pid),
            source_domain_id=domain.id,
            gap_type="brand_absent",
            brand_citations=0,
            competitor_citations=14,
            relevant_response_count=20,
            opportunity_score=82.0,
            confidence="high",
            explanation="seeded",
            competitors={"QuickBooks": 14},
            evidence={},
            analysis_version="citation-gaps/v1",
            analyzed_at=NOW,
        )
    )
    qb_domain = SourceDomain(
        hostname="quickbooks.intuit.com",
        normalized_hostname="quickbooks.intuit.com",
        display_name="QuickBooks",
        domain_type="company",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add(qb_domain)
    await db_session.flush()
    db_session.add(
        CitationGap(
            project_id=uuid.UUID(pid),
            source_domain_id=qb_domain.id,
            gap_type="brand_absent",
            brand_citations=0,
            competitor_citations=30,
            relevant_response_count=20,
            opportunity_score=90.0,
            confidence="high",
            explanation="seeded competitor-owned site",
            competitors={"QuickBooks": 30},
            evidence={},
            analysis_version="citation-gaps/v1",
            analyzed_at=NOW,
        )
    )
    db_session.add(
        ContentGap(
            project_id=uuid.UUID(pid),
            topic="construction accounting",
            normalized_topic="accounting construction",
            gap_type="missing_comparison",
            competitor_evidence={"prompt": "construction accounting comparison"},
            customer_coverage={},
            opportunity_score=76.0,
            confidence="medium",
            analysis_version="content-gaps/v1",
            window_days=90,
            analyzed_at=NOW,
        )
    )
    db_session.add(
        WebsitePage(
            project_id=uuid.UUID(pid),
            url="https://www.ledgerly.example/",
            normalized_url="https://www.ledgerly.example/",
            http_status=200,
            content_type="text/html",
            title="Ledgerly",
            word_count=600,
            first_crawled_at=NOW,
            last_crawled_at=NOW,
        )
    )
    db_session.add(
        Entity(
            project_id=uuid.UUID(pid),
            entity_type="Organization",
            name="Ledgerly",
            description=None,
            same_as=[],
        )
    )
    db_session.add(
        CompetitorCandidate(
            project_id=uuid.UUID(pid),
            name="Wave",
            normalized_name="wave",
            reason="appears alongside the brand",
            evidence={"responses": 6},
            confidence=0.7,
            confidence_label="high",
            source=CandidateSource.AI_RESPONSES.value,
            status=CandidateStatus.NEW.value,
            discovery_version="competitor-discovery/v1",
            discovered_at=NOW,
        )
    )
    crawl = CrawlJob(
        project_id=uuid.UUID(pid),
        root_url="https://www.ledgerly.example/",
        crawl_type=CrawlType.FULL,
        status=CrawlStatus.COMPLETED,
        max_pages=50,
        max_depth=3,
    )
    db_session.add(crawl)
    await db_session.flush()
    db_session.add(
        SeoAudit(
            project_id=uuid.UUID(pid),
            crawl_job_id=crawl.id,
            status=AuditStatus.COMPLETED,
            pages_analyzed=12,
            observation_count=9,
            health_score=42.0,
            summary={"by_severity": {"critical": 3, "warning": 4, "info": 2}},
            completed_at=NOW,
        )
    )
    # the same claim about QuickBooks, repeated in four responses
    resp_ids = (
        await db_session.scalars(
            select(AiResponse.id)
            .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
            .where(PromptRun.project_id == uuid.UUID(pid))
            .limit(4)
        )
    ).all()
    for rid in resp_ids:
        db_session.add(
            ResponseClaim(
                ai_response_id=rid,
                project_id=uuid.UUID(pid),
                subject="QuickBooks",
                predicate="offers",
                object="built-in payroll in every plan",
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
    run = await orch.create_run(project, "research", objective="find opportunities", user_id=None)
    return await orch.execute(run.id)


# --- evidence retrieval ----------------------------------------------------------------


async def test_evidence_retrieval_and_structure(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid = await _fixture_project(client, db_session)
    run = await _run(db_session, pid)
    assert run.status == "awaiting_approval", run.error_message  # content/entity actions pend
    result = run.result or {}
    titles = [f["title"] for f in result["findings"]]
    assert any("QuickBooks" in t for t in titles)
    assert any("g2.com" in t for t in titles)
    assert any("construction accounting" in t for t in titles)
    assert any("brand identity" in t for t in titles)
    assert any("Wave" in t for t in titles)
    assert any("Technical SEO" in t for t in titles)
    assert any("repeat a claim about QuickBooks" in t for t in titles)
    # every finding separates observed / inference / recommendation
    for f in result["findings"]:
        stmts = f["statements"]
        assert set(stmts) == {"observed", "inference", "recommendation"}
        assert stmts["observed"] != stmts["inference"] != stmts["recommendation"]
        assert f["confidence"] in ("high", "medium", "low")
        assert f["evidence"]
    # opportunities carry the required fields
    for o in result["recommendations"]:
        assert set(o) >= {
            "title",
            "why_now",
            "recommended_action",
            "expected_area_of_impact",
            "evidence",
            "confidence",
        }
    # the run's tool trail proves targeted retrieval (tools, not bulk loads)
    used = {t["tool"] for t in result["tool_usage"]}
    assert {
        "get_visibility_metrics",
        "get_competitive_visibility",
        "get_citation_gaps",
        "get_content_gaps",
        "get_entity_data",
        "get_pages",
        "get_seo_audit",
        "get_claims",
    } <= used
    assert "Material competitor lead(s): QuickBooks." in result["summary"]


# --- prioritization --------------------------------------------------------------------


async def test_prioritization(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture_project(client, db_session)
    run = await _run(db_session, pid)
    findings = (run.result or {})["findings"]
    assert 3 <= len(findings) <= 7
    scores = [f["priority_score"] for f in findings]
    assert scores == sorted(scores, reverse=True)
    # the material competitor gap outranks the emerging-competitor note
    order = [f["title"] for f in findings]
    assert order.index(next(t for t in order if "QuickBooks" in t)) < order.index(
        next(t for t in order if "Wave" in t)
    )
    comp = findings[0]["priority_components"]
    assert set(comp) == {
        "business_relevance",
        "visibility_impact",
        "competitor_advantage",
        "evidence_strength",
        "effort",
    }
    # proposed actions are suggestions; customer-facing ones pend for approval
    actions = (
        await db_session.scalars(select(AgentAction).where(AgentAction.agent_run_id == run.id))
    ).all()
    by_type = {a.action_type: a for a in actions}
    assert by_type["create_comparison_page"].status == "pending"
    assert by_type["improve_organization_entity"].status == "pending"
    assert by_type["investigate_citation_opportunity"].status == "approved"  # low-risk note
    assert all(a.executed_at is None for a in actions)  # nothing is ever executed


# --- confidence ------------------------------------------------------------------------


async def test_confidence_reflects_sample(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # a huge competitor lead, but only 6 responses → everything capped at low
    for i in range(6):
        await s.observation(
            prompt="tiny sample",
            days_ago=1 + i,
            mentioned=False,
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
    run = await _run(db_session, pid)
    result = run.result or {}
    assert any("capped at low confidence" in w for w in result["warnings"])
    assert all(f["confidence"] == "low" for f in result["findings"])

    # with the full fixture the competitor finding is medium+ (24 responses)
    h2, pid2 = await _fixture_project(client, db_session)
    run2 = await _run(db_session, pid2)
    comp_finding = next(f for f in (run2.result or {})["findings"] if "QuickBooks" in f["title"])
    assert comp_finding["confidence"] == "medium"
    assert run2.result["confidence"] is not None


# --- hallucination prevention ----------------------------------------------------------


async def test_hallucination_prevention(client: AsyncClient, db_session: AsyncSession) -> None:
    """Every entity the agent names must exist in the fixture; every number must
    match the seeded data. Nothing is invented and no LLM is involved."""
    h, pid = await _fixture_project(client, db_session)
    run = await _run(db_session, pid)
    result = run.result or {}
    blob = json.dumps(result)
    # only seeded names appear
    for name in ("QuickBooks", "Wave", "g2.com", "construction accounting"):
        assert name in blob
    for invented in ("FreshBooks", "Sage", "capterra", "reddit"):
        assert invented not in blob
    # a competitor's own site is never surfaced as a citation opportunity,
    # however large its seeded gap score
    assert "quickbooks.intuit.com" not in blob
    # the numbers are the seeded ones
    comp = next(f for f in result["findings"] if "QuickBooks" in f["title"])
    assert comp["evidence"]["competitor_mention_share"] == 100
    assert comp["evidence"]["brand_mention_share"] == 33
    assert comp["evidence"]["sample_size"] == 24
    cite = next(f for f in result["findings"] if "g2.com" in f["title"])
    assert cite["evidence"]["competitor_citations"] == 14
    assert cite["evidence"]["brand_citations"] == 0
    assert "82" in cite["statements"]["observed"]
    findings_all = result["findings"]
    seo = next((f for f in findings_all if "Technical SEO" in f["title"]), None)
    if seo is not None:  # present when it survives prioritization
        assert seo["evidence"]["health_score"] == 42.0
        assert seo["evidence"]["by_severity"]["critical"] == 3
    claim = next((f for f in findings_all if "repeat a claim" in f["title"]), None)
    if claim is not None:
        assert claim["evidence"]["occurrences"] == 4
        assert "built-in payroll in every plan" in claim["statements"]["observed"]
        assert claim["statements"]["recommendation"].startswith("Verify")
    # observed statements state measurements; inferences never masquerade as facts
    assert "appeared in 100% of eligible AI responses" in comp["statements"]["observed"]
    assert "currently has stronger AI visibility" in comp["statements"]["inference"]
    assert comp["statements"]["recommendation"].startswith("Investigate")


async def test_empty_project_yields_no_invented_findings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    run = await _run(db_session, pid)
    assert run.status == "completed"
    result = run.result or {}
    assert result["findings"] == [] and result["recommendations"] == []
    assert result["confidence"] is None
    assert "No findings met the evidence bar." in result["summary"]


# --- tenant isolation ------------------------------------------------------------------


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid = await _fixture_project(client, db_session)
    # a second project with different data must not leak into this run
    h2, _, pid2 = await project_with_competitors(client, competitors=("Bench", "Kashoo"))
    s2 = Seeder(db_session, uuid.UUID(pid2))
    for i in range(12):
        await s2.observation(
            prompt="other org prompt",
            days_ago=1 + i,
            mentioned=False,
            competitors=[("Bench", 1, "positive", "strong")],
        )
    run = await _run(db_session, pid)
    blob = json.dumps(run.result or {})
    assert "Bench" not in blob and "Kashoo" not in blob and "other org prompt" not in blob

    # the generic endpoint enforces tenancy for the research agent too
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_registry] = _registry
    app.dependency_overrides[get_agent_dispatcher] = lambda: lambda _rid: None
    other = await signup(client, org="Research Other Org")
    oh = auth_header(other["access_token"])
    r = await client.post(
        f"/api/v1/projects/{pid}/agents/research/run", json={"objective": "steal"}, headers=oh
    )
    assert r.status_code == 404
    r = await client.post(
        f"/api/v1/projects/{pid}/agents/research/run", json={"objective": "mine"}, headers=h
    )
    assert r.status_code == 202
