"""Recommendation Engine (4E): rules, generation, evidence, transitions, tenancy."""

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.gaps.engine import CitationGapEngine
from app.models import MembershipRole
from app.models.gaps import GapConfidence, GapType
from app.models.intelligence import ResponseCitation
from app.models.prompts import AiResponse, FunnelStage, PromptCategory
from app.models.recommendations import Recommendation, RecommendationPriority
from app.recommendations.engine import RecommendationEngine
from app.recommendations.rules import (
    GapFacts,
    ResearchFacts,
    citation_explanation,
    is_recommendable,
    priority_for,
    research_confidence,
    research_is_warranted,
)
from app.sources.service import SourceIntelligenceService
from tests.conftest import auth_header
from tests.gaps.test_gaps import _seed_market
from tests.test_authz import add_member, signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

# --- rules -------------------------------------------------------------------------------


def facts(**kw) -> GapFacts:  # type: ignore[no-untyped-def]
    base = dict(
        domain="g2.com",
        display_name="g2.com",
        source_type="review",
        gap_type=GapType.COMPETITOR_ADVANTAGE,
        opportunity_score=91.0,
        confidence=GapConfidence.HIGH,
        brand_citations=3,
        competitor_citations=55,
        competitors={"A": 31, "B": 24},
        relevant_responses=34,
        eligible_responses=72,
        prompts_citing=6,
        total_prompts=24,
        source_relevance=70.0,
        commercial_prompts=5,
    )
    base.update(kw)
    return GapFacts(**base)  # type: ignore[arg-type]


def test_priority_combines_score_confidence_relevance_gap_and_sample() -> None:
    p, score = priority_for(facts())
    assert p is RecommendationPriority.CRITICAL and score == round(
        91 * 1.0 * (0.7 + 0.3 * 5 / 6), 1
    )
    # same numbers, medium confidence → not critical
    assert priority_for(facts(confidence=GapConfidence.MEDIUM))[0] is RecommendationPriority.HIGH
    # small competitor gap → not critical even at high score
    assert (
        priority_for(facts(brand_citations=40, competitor_citations=55))[0]
        is RecommendationPriority.HIGH
    )
    # tiny sample → not critical
    assert priority_for(facts(relevant_responses=10))[0] is RecommendationPriority.HIGH
    # no commercial prompts lowers the score
    assert priority_for(facts(commercial_prompts=0))[1] < priority_for(facts())[1]
    assert (
        priority_for(facts(opportunity_score=50, confidence=GapConfidence.LOW))[0]
        is RecommendationPriority.LOW
    )
    assert (
        priority_for(facts(opportunity_score=55, confidence=GapConfidence.HIGH))[0]
        is RecommendationPriority.MEDIUM
    )


def test_recommendability() -> None:
    assert is_recommendable(facts())
    assert not is_recommendable(facts(confidence=GapConfidence.INSUFFICIENT))
    assert not is_recommendable(facts(gap_type=GapType.SHARED_SOURCE))
    assert not is_recommendable(facts(gap_type=GapType.SOURCE_OVERREPRESENTED))
    assert is_recommendable(facts(gap_type=GapType.SOURCE_UNDERREPRESENTED, source_relevance=60))
    # a competitor's own site is never an opportunity
    assert not is_recommendable(
        facts(source_type="company", brand_citations=0, gap_type=GapType.BRAND_ABSENT)
    )
    assert not is_recommendable(
        facts(gap_type=GapType.SOURCE_UNDERREPRESENTED, source_relevance=30)
    )


def test_explanation_answers_the_five_questions() -> None:
    e = citation_explanation(facts())
    assert set(e) == {
        "observed",
        "why_it_matters",
        "investigate",
        "evidence_summary",
        "confidence_statement",
    }
    assert "34 of 72" in e["observed"] and "A (31), B (24)" in e["observed"]
    assert "competitors appear there far more often" in e["why_it_matters"]
    assert "legitimate editorial, review, partnership, research or community" in e["investigate"]
    assert "fake reviews" in e["investigate"]
    assert (
        "6 relevant prompts" in e["evidence_summary"]
        and "55 competitor citations vs 3" in e["evidence_summary"]
    )
    assert (
        e["confidence_statement"].startswith("High")
        and "would not guarantee" in e["confidence_statement"]
    )


def test_research_requires_all_three_conditions() -> None:
    ok = ResearchFacts(
        competitor_research_citations=6,
        brand_research_citations=0,
        research_responses=5,
        research_sources=[{"domain": "statista.com", "citations": 6}],
        commercial_prompts=3,
        prompts_citing=4,
        competitors={"A": 6},
        eligible_responses=60,
    )
    assert research_is_warranted(ok) == (True, [])
    assert research_confidence(ok) is GapConfidence.LOW
    for bad, reason in (
        ({"competitor_research_citations": 2}, "competitors are not being cited for research"),
        ({"brand_research_citations": 1}, "no content gap"),
        ({"commercial_prompts": 1}, "not commercially relevant"),
        ({"research_responses": 1}, "too few responses"),
    ):
        warranted, reasons = research_is_warranted(ResearchFacts(**{**ok.__dict__, **bad}))
        assert not warranted and any(reason in r for r in reasons)


# --- generation over the database ----------------------------------------------------------


async def _prepare(client: AsyncClient, db_session: AsyncSession, responses: int = 60):  # type: ignore[no-untyped-def]
    h, pid, s = await _seed_market(client, db_session, responses=responses)
    await CitationGapEngine(db_session, now=NOW).analyze(s.project_id)
    await db_session.commit()
    return h, pid, s


async def test_generation_from_gaps(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, s = await _prepare(client, db_session)
    r = await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # g2 (competitor advantage), capterra (brand absent), reddit (brand absent, community)
    # → citation recs; the brand's own site (overrepresented) → none; no research evidence.
    assert body["generated"] == 3 and body["research_considered"] is False
    assert "competitors are not being cited for research" in body["research_reasons"]
    items = (await client.get(f"/api/v1/projects/{pid}/recommendations", headers=h)).json()["items"]
    assert [i["title"] for i in items][0] == "Investigate g2.com visibility opportunity"
    g2 = items[0]
    assert g2["recommendation_type"] == "citation" and g2["priority"] in ("critical", "high")
    assert "Competitors appear substantially more often than the project brand" in g2["description"]
    ev = g2["evidence"]
    assert (
        ev["relevant_prompt_count"] == 8
        and ev["competitor_citation_count"] == 40
        and ev["brand_citation_count"] == 3
    )
    assert ev["competitors"] == {"QuickBooks": 20, "Xero": 20} and ev["source_relevance"] > 0
    assert (
        ev["confidence"] == "high" and ev["priority_score"] > 0 and ev["business_relevance"] == 1.0
    )
    assert g2["confidence"] == "high" and g2["citation_gap_id"] and g2["status"] == "new"
    assert set(g2["explanation"]) == {
        "observed",
        "why_it_matters",
        "investigate",
        "evidence_summary",
        "confidence_statement",
    }
    assert g2["allowed_transitions"] == ["approved", "dismissed", "reviewing"]
    assert all(i["recommendation_type"] == "citation" for i in items)
    assert {i["title"] for i in items} == {
        "Investigate g2.com visibility opportunity",
        "Investigate capterra.com visibility opportunity",
        "Investigate reddit.com visibility opportunity",
    }
    summary = (
        await client.get(f"/api/v1/projects/{pid}/recommendations/summary", headers=h)
    ).json()
    assert (
        summary["total"] == 3
        and summary["awaiting_review"] == 3
        and summary["by_type"] == {"citation": 3}
    )
    assert "require human review" in summary["note"]


async def test_research_recommendation_only_with_evidence(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, s = await _prepare(client, db_session, responses=30)
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    # competitors cited from research sources in commercial prompts; brand never
    for i in range(5):
        run = await s.observation(
            prompt=f"research prompt {i % 2}",
            days_ago=2 + i,
            category=PromptCategory.COMPARISON,
            funnel_stage=FunnelStage.DECISION,
        )
        resp = (
            await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
        ).one()
        c = ResponseCitation(
            ai_response_id=resp.id,
            project_id=s.project_id,
            url="https://www.statista.com/report/quickbooks-market-share",
            domain=None,
            citation_type="explicit_url",
            parser_version="response-parser/v1",
        )
        db_session.add(c)
        await db_session.flush()
        c.created_at = NOW - timedelta(days=2 + i)
        await svc.resolve_citation(c, hosts)
    await db_session.commit()
    await CitationGapEngine(db_session, now=NOW).analyze(s.project_id)
    await db_session.commit()
    body = (await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)).json()
    assert body["research_considered"] is True and body["research_reasons"] == []
    research = (
        await client.get(
            f"/api/v1/projects/{pid}/recommendations", params={"type": "content"}, headers=h
        )
    ).json()["items"]
    assert len(research) == 1 and research[0]["title"] == "Create original research"
    ev = research[0]["evidence"]
    assert ev["competitor_research_citations"] == 5 and ev["brand_research_citations"] == 0
    assert ev["conditions"] == {
        "competitors_cited_for_research": True,
        "brand_content_gap": True,
        "commercially_relevant": True,
    }
    assert ev["research_sources"][0]["domain"] == "statista.com"
    assert research[0]["confidence"] == "low" and research[0]["priority"] in ("medium", "low")
    assert (
        "Publishing research does not guarantee"
        in research[0]["explanation"]["confidence_statement"]
    )
    # once the brand is cited for research too, the content gap closes and the rec disappears
    run = await s.observation(
        prompt="research prompt 0", days_ago=1, category=PromptCategory.COMPARISON
    )
    resp = (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).one()
    c = ResponseCitation(
        ai_response_id=resp.id,
        project_id=s.project_id,
        url="https://www.statista.com/report/ledgerly-study",
        domain=None,
        citation_type="explicit_url",
        parser_version="response-parser/v1",
    )
    db_session.add(c)
    await db_session.flush()
    await svc.resolve_citation(c, hosts)
    await db_session.commit()
    body = (await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)).json()
    assert body["research_considered"] is False and any(
        "no content gap" in r for r in body["research_reasons"]
    )
    assert (
        await client.get(
            f"/api/v1/projects/{pid}/recommendations", params={"type": "content"}, headers=h
        )
    ).json()["total"] == 0


async def test_insufficient_gaps_produce_no_recommendation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    run = await s.observation(prompt="p")
    resp = (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).one()
    c = ResponseCitation(
        ai_response_id=resp.id,
        project_id=s.project_id,
        url="https://www.g2.com/products/xero/reviews",
        domain=None,
        citation_type="explicit_url",
        parser_version="response-parser/v1",
    )
    db_session.add(c)
    await db_session.flush()
    await svc.resolve_citation(c, hosts)
    await db_session.commit()
    await client.post(f"/api/v1/projects/{pid}/citation-gaps/analyze", headers=h)
    body = (await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)).json()
    assert body["generated"] == 0 and body["skipped_insufficient"] == 1


async def test_status_transitions_are_human_and_validated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, _ = await _prepare(client, db_session)
    await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)
    rec = (await client.get(f"/api/v1/projects/{pid}/recommendations", headers=h)).json()["items"][
        0
    ]
    rid = rec["id"]
    # start requires approval first
    r = await client.post(f"/api/v1/recommendations/{rid}/start", headers=h)
    assert (
        r.status_code == 409
        and "allowed: approved, dismissed, reviewing" in r.json()["error"]["message"]
    )
    r = await client.post(
        f"/api/v1/recommendations/{rid}/approve", json={"note": "Worth a look"}, headers=h
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "approved"
        and r.json()["note"] == "Worth a look"
    )
    assert r.json()["reviewed_at"] and r.json()["reviewed_by_user_id"]
    assert r.json()["allowed_transitions"] == ["dismissed", "in_progress"]
    assert (
        await client.post(f"/api/v1/recommendations/{rid}/approve", headers=h)
    ).status_code == 409
    r = await client.post(f"/api/v1/recommendations/{rid}/start", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = await client.patch(
        f"/api/v1/recommendations/{rid}", json={"status": "completed"}, headers=h
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "completed"
        and r.json()["allowed_transitions"] == []
    )
    assert (
        await client.post(f"/api/v1/recommendations/{rid}/dismiss", headers=h)
    ).status_code == 409
    # dismiss → reopen via reviewing
    other = (await client.get(f"/api/v1/projects/{pid}/recommendations", headers=h)).json()[
        "items"
    ][1]
    assert (await client.post(f"/api/v1/recommendations/{other['id']}/dismiss", headers=h)).json()[
        "status"
    ] == "dismissed"
    assert (
        await client.patch(
            f"/api/v1/recommendations/{other['id']}", json={"status": "reviewing"}, headers=h
        )
    ).json()["status"] == "reviewing"
    assert (
        await client.patch(
            f"/api/v1/recommendations/{other['id']}", json={"status": "in_progress"}, headers=h
        )
    ).status_code == 409
    # regeneration keeps review state and does not duplicate
    body = (await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)).json()
    assert body["generated"] == 3 and body["removed"] == 0
    items = (await client.get(f"/api/v1/projects/{pid}/recommendations", headers=h)).json()["items"]
    assert len(items) == 3 and {i["status"] for i in items} == {"completed", "reviewing", "new"}
    assert (
        await db_session.scalar(
            select(Recommendation.id).where(Recommendation.id == uuid.UUID(rid))
        )
        is not None
    )


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h_a, pid_a, sa_ = await _prepare(client, db_session, responses=30)
    h_b, pid_b, sb = await _prepare(client, db_session, responses=30)
    for h, pid in ((h_a, pid_a), (h_b, pid_b)):
        assert (
            await client.post(f"/api/v1/projects/{pid}/recommendations/generate", headers=h)
        ).status_code == 200
    a = (await client.get(f"/api/v1/projects/{pid_a}/recommendations", headers=h_a)).json()
    b = (await client.get(f"/api/v1/projects/{pid_b}/recommendations", headers=h_b)).json()
    assert a["total"] == b["total"] == 3 and {i["project_id"] for i in a["items"]} == {pid_a}
    rid = a["items"][0]["id"]
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/recommendations", headers=h_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/recommendations/summary", headers=h_b)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid_a}/recommendations/generate", headers=h_b)
    ).status_code == 404
    for path in ("approve", "dismiss", "start"):
        assert (
            await client.post(f"/api/v1/recommendations/{rid}/{path}", headers=h_b)
        ).status_code == 404
    assert (await client.get(f"/api/v1/recommendations/{rid}", headers=h_b)).status_code == 404
    assert (await client.get(f"/api/v1/recommendations/{rid}")).status_code == 401
    org_a = (await client.get("/api/v1/organizations", headers=h_a)).json()[0]["id"]
    viewer = await add_member(db_session, org_a, "viewer-recs@example.com", MembershipRole.VIEWER)
    await db_session.commit()
    hv = auth_header(create_access_token(str(viewer)))
    assert (await client.get(f"/api/v1/recommendations/{rid}", headers=hv)).status_code == 200
    assert (
        await client.post(f"/api/v1/recommendations/{rid}/approve", headers=hv)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/projects/{pid_a}/recommendations/generate", headers=hv)
    ).status_code == 403
    # A's regeneration never touches B
    await RecommendationEngine(db_session, now=NOW).generate(sa_.project_id)
    await db_session.commit()
    assert (await client.get(f"/api/v1/projects/{pid_b}/recommendations", headers=h_b)).json()[
        "total"
    ] == 3
    stranger = await signup(client, org="Stranger")
    assert (
        await client.get(
            f"/api/v1/recommendations/{rid}", headers=auth_header(stranger["access_token"])
        )
    ).status_code == 404
    assert sb.project_id != sa_.project_id
