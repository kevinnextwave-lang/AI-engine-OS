"""Citation Gap Engine (4C): gap types, opportunity scoring, confidence,
API filtering, status updates, tenant isolation."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gaps.engine import CitationGapEngine
from app.gaps.scoring import (
    SourceStats,
    classify_gap,
    confidence_for,
    explain,
    opportunity,
    priority_for,
)
from app.models import MembershipRole
from app.models.gaps import CitationGap, GapConfidence, GapType
from app.sources.service import SourceIntelligenceService
from tests.conftest import auth_header
from tests.sources.test_sources import _citation
from tests.test_authz import add_member, signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

# --- pure scoring -------------------------------------------------------------------


def stats(**kw) -> SourceStats:  # type: ignore[no-untyped-def]
    base = dict(
        domain="g2.com",
        domain_type="review",
        source_relevance=70.0,
        eligible_responses=100,
        total_prompts=10,
        relevant_responses=30,
        prompts_citing=6,
        citations=40,
        brand_citations=0,
        competitor_citations=0,
        competitors={},
        first_cited_at=NOW - timedelta(days=80),
        last_cited_at=NOW - timedelta(days=1),
        citations_first_half=20,
        citations_second_half=20,
        now=NOW,
    )
    base.update(kw)
    return SourceStats(**base)  # type: ignore[arg-type]


def test_gap_types() -> None:
    assert (
        classify_gap(
            stats(brand_citations=3, competitor_citations=55, competitors={"A": 31, "B": 24})
        )
        is GapType.COMPETITOR_ADVANTAGE
    )
    assert classify_gap(stats(brand_citations=0, competitor_citations=10)) is GapType.BRAND_ABSENT
    assert (
        classify_gap(stats(brand_citations=0, competitor_citations=0, relevant_responses=5))
        is GapType.BRAND_ABSENT
    )
    assert classify_gap(stats(brand_citations=8, competitor_citations=9)) is GapType.SHARED_SOURCE
    assert (
        classify_gap(stats(brand_citations=10, competitor_citations=0, citations=11))
        is GapType.SOURCE_OVERREPRESENTED
    )
    assert (
        classify_gap(
            stats(brand_citations=1, competitor_citations=0, citations=30, relevant_responses=2)
        )
        is GapType.SOURCE_UNDERREPRESENTED
    )
    emerging = stats(
        brand_citations=0,
        competitor_citations=2,
        first_cited_at=NOW - timedelta(days=10),
        citations_first_half=0,
        citations_second_half=6,
    )
    assert classify_gap(emerging) is GapType.EMERGING_SOURCE


def test_opportunity_score_example_from_spec() -> None:
    s = stats(brand_citations=3, competitor_citations=55, competitors={"A": 31, "B": 24})
    gap = classify_gap(s)
    o = opportunity(s, gap)
    assert gap is GapType.COMPETITOR_ADVANTAGE
    assert 0 <= o["score"] <= 100 and o["score"] >= 70 and priority_for(o["score"]) == "high"
    assert set(o["components"]) == {
        "citation_frequency",
        "competitor_gap",
        "source_relevance",
        "prompt_relevance",
        "recency",
    }
    assert o["components"]["competitor_gap"]["value"] == pytest.approx(50 + 50 * 52 / 58, abs=0.1)
    assert o["components"]["citation_frequency"]["value"] == 100.0  # 30 % share saturates
    assert o["components"]["recency"]["value"] == 100.0
    assert sum(c["weight"] for c in o["components"].values()) == 100
    text = explain(s, gap, GapConfidence.HIGH)
    assert (
        "Competitors are frequently cited" in text
        and "A (31)" in text
        and "rarely cited (3)" in text
    )


def test_volume_alone_is_not_an_opportunity() -> None:
    """Same huge volume, but the brand dominates → overrepresented, low score."""
    s = stats(brand_citations=38, competitor_citations=0, citations=40)
    gap = classify_gap(s)
    assert gap is GapType.SOURCE_OVERREPRESENTED
    assert opportunity(s, gap)["score"] < 30
    # shared sources are discounted too
    shared = stats(brand_citations=20, competitor_citations=20)
    assert opportunity(shared, GapType.SHARED_SOURCE)["type_multiplier"] == 0.7


def test_recency_and_prompt_relevance_move_the_score() -> None:
    fresh = opportunity(stats(brand_citations=0, competitor_citations=10), GapType.BRAND_ABSENT)[
        "score"
    ]
    stale = opportunity(
        stats(brand_citations=0, competitor_citations=10, last_cited_at=NOW - timedelta(days=85)),
        GapType.BRAND_ABSENT,
    )["score"]
    narrow = opportunity(
        stats(brand_citations=0, competitor_citations=10, prompts_citing=1), GapType.BRAND_ABSENT
    )["score"]
    assert stale < fresh and narrow < fresh


def test_confidence_never_high_on_tiny_samples() -> None:
    assert confidence_for(stats(relevant_responses=1)) is GapConfidence.INSUFFICIENT
    assert (
        confidence_for(stats(eligible_responses=4, relevant_responses=4))
        is GapConfidence.INSUFFICIENT
    )
    assert confidence_for(stats(eligible_responses=10, relevant_responses=3)) is GapConfidence.LOW
    assert (
        confidence_for(stats(eligible_responses=25, relevant_responses=8)) is GapConfidence.MEDIUM
    )
    assert confidence_for(stats(eligible_responses=60, relevant_responses=25)) is GapConfidence.HIGH
    # incomplete source data (unknown type) caps at medium
    assert (
        confidence_for(stats(eligible_responses=60, relevant_responses=25, domain_type="unknown"))
        is GapConfidence.MEDIUM
    )


# --- engine over the database ------------------------------------------------------------


async def _seed_market(
    client: AsyncClient, db_session: AsyncSession, *, responses: int = 60
) -> tuple[dict[str, str], str, Seeder]:
    """A market where g2.com cites competitors a lot and the brand rarely,
    capterra cites only competitors, the brand's own site is cited, and
    reddit is cited without naming anyone."""
    h, _, pid = await project_with_competitors(client)  # QuickBooks, Xero; domain ledgerly.example
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    plan = []
    for i in range(responses):
        prompt = f"prompt {i % 8}"
        days = 1 + (i % 60)
        if i % 3 == 0:
            plan.append((prompt, days, "https://www.g2.com/products/quickbooks/reviews", None))
        elif i % 3 == 1:
            plan.append((prompt, days, "https://www.g2.com/products/xero/reviews", None))
        else:
            plan.append((prompt, days, "https://www.g2.com/categories/accounting", None))
        if i % 20 == 0:
            plan.append((prompt, days, "https://www.g2.com/products/ledgerly/reviews", None))
        if i % 4 == 0:
            plan.append((prompt, days, "https://www.capterra.com/p/123/QuickBooks/", None))
        if i % 5 == 0:
            plan.append((prompt, days, "https://www.ledgerly.example/pricing", None))
        if i % 6 == 0:
            plan.append((prompt, days, "https://www.reddit.com/r/smallbusiness/comments/abc", None))
    for prompt, days, url, domain in plan:
        c = await _citation(s, url=url, domain=domain, days_ago=days, prompt=prompt)
        await svc.resolve_citation(c, hosts)
    await db_session.commit()
    return h, pid, s


async def test_engine_finds_competitor_advantage_brand_absent_and_shared(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, s = await _seed_market(client, db_session)
    result = await CitationGapEngine(db_session, now=NOW).analyze(s.project_id)
    await db_session.commit()
    assert result.sources_observed == 4 and result.gaps_written == 4
    gaps = {
        g.evidence["inputs"]["domain_type"] + ":" + dom: g
        for g, dom in [
            (g, (await client.get(f"/api/v1/citation-gaps/{g.id}", headers=h)).json()["domain"])
            for g in (
                await db_session.scalars(
                    select(CitationGap).where(CitationGap.project_id == s.project_id)
                )
            ).all()
        ]
    }
    g2 = gaps["review:g2.com"]
    assert g2.gap_type == "competitor_advantage"
    assert g2.brand_citations == 3 and g2.competitor_citations == 40
    assert g2.competitors == {"QuickBooks": 20, "Xero": 20}
    assert g2.confidence == "high" and g2.opportunity_score >= 70
    assert "Competitors are frequently cited from g2.com" in g2.explanation
    cap = gaps["review:capterra.com"]
    assert (
        cap.gap_type == "brand_absent"
        and cap.brand_citations == 0
        and cap.competitors == {"QuickBooks": 15}
    )
    own = gaps["company:ledgerly.example"]
    assert own.gap_type == "source_overrepresented" and own.opportunity_score < 30
    reddit = gaps["community:reddit.com"]
    assert reddit.gap_type == "brand_absent" and reddit.competitors == {}
    # relevant responses per source never exceed the eligible pool
    eligible = g2.evidence["inputs"]["eligible_responses"]
    assert all(g.relevant_response_count <= eligible for g in gaps.values())
    assert g2.evidence["top_pages"][0]["citations"] == 20
    assert g2.evidence["source_relevance"]["name"] == "Source Relevance Score"


async def test_reanalysis_is_idempotent_and_keeps_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, s = await _seed_market(client, db_session, responses=30)
    engine = CitationGapEngine(db_session, now=NOW)
    await engine.analyze(s.project_id)
    await db_session.commit()
    gap = (
        await db_session.scalars(
            select(CitationGap)
            .where(CitationGap.project_id == s.project_id)
            .order_by(CitationGap.opportunity_score.desc())
        )
    ).first()
    assert gap
    r = await client.patch(
        f"/api/v1/citation-gaps/{gap.id}",
        json={"status": "accepted", "note": "owner: Kim"},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "accepted"
        and r.json()["note"] == "owner: Kim"
    )
    before = {
        g.id: g.status
        for g in (
            await db_session.scalars(
                select(CitationGap).where(CitationGap.project_id == s.project_id)
            )
        ).all()
    }
    again = await engine.analyze(s.project_id)
    await db_session.commit()
    assert again.gaps_written == len(before) and again.gaps_removed == 0
    after = {
        g.id: g.status
        for g in (
            await db_session.scalars(
                select(CitationGap).where(CitationGap.project_id == s.project_id)
            )
        ).all()
    }
    assert after == before and after[gap.id] == "accepted"


async def test_insufficient_data_is_labelled(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    c = await _citation(s, url="https://www.g2.com/products/xero/reviews", domain=None)
    await svc.resolve_citation(c, hosts)
    await db_session.commit()
    r = await client.post(f"/api/v1/projects/{pid}/citation-gaps/analyze", headers=h)
    assert r.status_code == 200 and r.json()["eligible_responses"] == 1
    body = (await client.get(f"/api/v1/projects/{pid}/citation-gaps", headers=h)).json()
    assert body["total"] == 1
    gap = body["items"][0]
    assert gap["confidence"] == "insufficient" and "Too little data" in gap["explanation"]
    summary = (await client.get(f"/api/v1/projects/{pid}/citation-gaps/summary", headers=h)).json()
    assert summary["data"]["sufficient"] is False and summary["actionable"] == 0
    assert summary["top_opportunities"] == []
    # empty project: no gaps, explicit note
    hh, _, empty_pid = await project_with_competitors(client)
    assert (
        await client.post(f"/api/v1/projects/{empty_pid}/citation-gaps/analyze", headers=hh)
    ).json()["sources_observed"] == 0
    empty_summary = (
        await client.get(f"/api/v1/projects/{empty_pid}/citation-gaps/summary", headers=hh)
    ).json()
    assert empty_summary["total"] == 0 and "Not enough" in empty_summary["data"]["note"]


async def test_list_filters_and_summary(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, s = await _seed_market(client, db_session)
    await CitationGapEngine(db_session, now=NOW).analyze(s.project_id)
    await db_session.commit()
    base = f"/api/v1/projects/{pid}/citation-gaps"

    async def ids(**params: object) -> list[str]:
        r = await client.get(base, params=params, headers=h)
        assert r.status_code == 200, r.text
        return [i["domain"] for i in r.json()["items"]]

    all_ = await ids()
    assert all_[0] == "g2.com"  # highest opportunity first
    assert await ids(source_type="review") == ["g2.com", "capterra.com"]
    assert await ids(gap_type="brand_absent") == ["capterra.com", "reddit.com"]
    assert await ids(competitor="Xero") == ["g2.com"]
    assert await ids(competitor="QuickBooks") == ["g2.com", "capterra.com"]
    assert await ids(min_score=70) == ["g2.com"]
    assert await ids(max_score=30) == ["ledgerly.example"]
    assert await ids(confidence="high") == ["g2.com"]
    assert await ids(status="new") == all_
    assert await ids(status="completed") == []
    assert (await client.get(base, params={"gap_type": "bogus"}, headers=h)).status_code == 422

    summary = (await client.get(f"{base}/summary", headers=h)).json()
    assert summary["total"] == 4 and summary["by_gap_type"] == {
        "competitor_advantage": 1,
        "brand_absent": 2,
        "source_overrepresented": 1,
    }
    assert summary["by_source_type"] == {"review": 2, "company": 1, "community": 1}
    assert summary["competitors_ahead"] == {
        "QuickBooks": 1
    }  # capterra: QuickBooks cited, brand absent
    assert summary["top_opportunities"][0]["domain"] == "g2.com"
    assert summary["data"]["sufficient"] and summary["analyzed_at"]
    assert summary["by_priority"]["high"] >= 1


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h_a, pid_a, sa_ = await _seed_market(client, db_session, responses=30)
    h_b, pid_b, sb = await _seed_market(client, db_session, responses=30)
    engine = CitationGapEngine(db_session, now=NOW)
    await engine.analyze(sa_.project_id)
    await engine.analyze(sb.project_id)
    await db_session.commit()
    a = (await client.get(f"/api/v1/projects/{pid_a}/citation-gaps", headers=h_a)).json()
    b = (await client.get(f"/api/v1/projects/{pid_b}/citation-gaps", headers=h_b)).json()
    assert a["total"] == b["total"] == 4
    assert {i["project_id"] for i in a["items"]} == {pid_a}
    # same shared source domain, separate gap rows and counts per tenant
    assert a["items"][0]["source_domain_id"] == b["items"][0]["source_domain_id"]
    assert a["items"][0]["id"] != b["items"][0]["id"]
    # cross-tenant access: 404 everywhere, no 403 leak
    gap_a = a["items"][0]["id"]
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/citation-gaps", headers=h_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/citation-gaps/summary", headers=h_b)
    ).status_code == 404
    assert (await client.get(f"/api/v1/citation-gaps/{gap_a}", headers=h_b)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/citation-gaps/{gap_a}", json={"status": "dismissed"}, headers=h_b
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid_a}/citation-gaps/analyze", headers=h_b)
    ).status_code == 404
    assert (await client.get(f"/api/v1/citation-gaps/{gap_a}")).status_code == 401
    # a viewer in A's org may read but not change or analyse
    org_a = (await client.get("/api/v1/organizations", headers=h_a)).json()[0]["id"]
    viewer = await add_member(db_session, org_a, "viewer-gaps@example.com", MembershipRole.VIEWER)
    await db_session.commit()
    from app.core.security import create_access_token

    hv = auth_header(create_access_token(str(viewer)))
    assert (await client.get(f"/api/v1/citation-gaps/{gap_a}", headers=hv)).status_code == 200
    assert (
        await client.patch(
            f"/api/v1/citation-gaps/{gap_a}", json={"status": "dismissed"}, headers=hv
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/projects/{pid_a}/citation-gaps/analyze", headers=hv)
    ).status_code == 403
    # re-analysing A never touches B
    await engine.analyze(sa_.project_id)
    await db_session.commit()
    assert (await client.get(f"/api/v1/projects/{pid_b}/citation-gaps", headers=h_b)).json()[
        "total"
    ] == 4
    stranger = await signup(client, org="Stranger")
    assert (
        await client.get(
            f"/api/v1/citation-gaps/{gap_a}", headers=auth_header(stranger["access_token"])
        )
    ).status_code == 404
