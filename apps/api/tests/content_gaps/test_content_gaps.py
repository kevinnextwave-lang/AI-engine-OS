"""Milestone 5E — Competitive Content Gap Engine."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_gaps.engine import ContentGapEngine
from app.content_gaps.topics import (
    MIN_TOPIC_RESPONSES,
    WEIGHTS,
    PageMatch,
    TopicFacts,
    classify,
    match_page,
    page_categories,
    score,
    topic_keywords,
)
from app.models.content_gaps import ContentGap, ContentGapType
from app.models.crawl import WebsitePage
from app.models.intelligence import ResponseCitation
from app.models.prompts import AiResponse, FunnelStage, PromptCategory
from app.models.sources import CitationEntity, SourceDomain
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, PV, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio

CONSTRUCTION = "What are the best accounting platforms for construction companies?"


def _page(
    s: Seeder,
    url: str,
    title: str | None,
    *,
    words: int | None = 800,
    meta: str | None = None,
) -> WebsitePage:
    page = WebsitePage(
        project_id=s.project_id,
        url=url,
        normalized_url=url,
        http_status=200,
        content_type="text/html",
        title=title,
        meta_description=meta,
        word_count=words,
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )
    s.session.add(page)
    return page


async def _seed_topic(
    s: Seeder,
    prompt: str,
    *,
    n: int = 12,
    brand_every: int = 0,  # 0 = never mentioned; k = mentioned every k-th response
    category: PromptCategory = PromptCategory.RECOMMENDATION,
    funnel: FunnelStage = FunnelStage.CONSIDERATION,
) -> list[uuid.UUID]:
    runs = []
    for i in range(n):
        mentioned = brand_every > 0 and i % brand_every == 0
        run = await s.observation(
            prompt=prompt,
            provider="openai" if i % 2 == 0 else "google",
            days_ago=1 + i,
            mentioned=mentioned,
            position=3 if mentioned else None,
            strength="moderate" if mentioned else "unknown",
            competitors=[("QuickBooks", 1, "positive", "strong")],
            category=category,
            funnel_stage=funnel,
        )
        runs.append(run.id)
    return runs


# --- pure helpers ----------------------------------------------------------------------


def test_topic_keywords_and_page_matching() -> None:
    kw = topic_keywords(CONSTRUCTION)
    assert "construction" in kw and "accounting" in kw
    assert "best" not in kw and "platforms" not in kw  # stop/generic words removed
    m = match_page(
        kw,
        "https://www.ledgerly.example/industries/construction-accounting",
        "Construction accounting for contractors",
        None,
        900,
    )
    assert m is not None and "construction" in m.matched_keywords and m.substantial
    assert "use_case" in page_categories(
        "https://www.ledgerly.example/industries/construction", None
    )
    assert match_page(kw, "https://www.ledgerly.example/pricing", "Pricing", None, 500) is None


# --- missing topics --------------------------------------------------------------------


async def test_missing_topic_detected(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12, brand_every=0)
    _page(s, "https://www.ledgerly.example/pricing", "Ledgerly pricing")  # unrelated page
    await db_session.flush()
    r = await client.post(f"/api/v1/projects/{pid}/content-gaps/analyze", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligible_responses"] == 12 and body["gaps_written"] >= 1
    items = (await client.get(f"/api/v1/projects/{pid}/content-gaps", headers=h)).json()["items"]
    gap = next(g for g in items if "construction" in g["topic"])
    assert gap["gap_type"] == "missing_topic"
    ev, cov = gap["competitor_evidence"], gap["customer_coverage"]
    assert ev["top_competitor"] == "QuickBooks" and ev["top_competitor_rate"] == 100.0
    assert ev["brand_mentions"] == 0 and ev["competitor_visibility"] == "high"
    assert cov["pages_matched"] == 0 and cov["coverage"] == "low"
    assert gap["confidence"] == "medium"  # 12 responses
    assert gap["opportunity_score"] > 60


async def test_use_case_gap_for_industry_prompt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The spec's example: construction prompt, competitors visible, no
    construction page anywhere → a use-case-shaped gap for an industry prompt."""
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=10, category=PromptCategory.INDUSTRY)
    await db_session.flush()
    await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    row = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).one()
    assert row.gap_type == ContentGapType.MISSING_USE_CASE.value


# --- weak coverage ---------------------------------------------------------------------


async def test_weak_coverage(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12)
    # a matching but thin page (< 300 words)
    _page(
        s,
        "https://www.ledgerly.example/blog/construction-accounting",
        "Construction accounting basics",
        words=150,
    )
    await db_session.flush()
    await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    row = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).one()
    assert row.gap_type == ContentGapType.WEAK_TOPIC.value
    page = row.customer_coverage["pages"][0]
    assert page["substantial"] is False and page["word_count"] == 150
    assert 0 < row.customer_coverage["coverage_strength"] < 1


async def test_substantial_coverage_produces_no_topic_gap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12)
    _page(
        s,
        "https://www.ledgerly.example/industries/construction-accounting",
        "Construction accounting for contractors",
        words=1200,
    )
    await db_session.flush()
    result = await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    rows = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).all()
    assert result.gaps_written == 0 and rows == []


# --- comparison gaps -------------------------------------------------------------------


async def test_comparison_gap(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    prompt = "Ledgerly vs QuickBooks for small agencies"
    await _seed_topic(s, prompt, n=12, brand_every=4, category=PromptCategory.COMPARISON)
    # topic is covered by a substantial blog post, but no comparison-type page
    _page(
        s,
        "https://www.ledgerly.example/blog/ledgerly-quickbooks-agencies",
        "Ledgerly and QuickBooks for agencies",
        words=900,
    )
    await db_session.flush()
    await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    rows = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).all()
    types = {r.gap_type for r in rows}
    assert ContentGapType.MISSING_COMPARISON.value in types


# --- FAQ gaps --------------------------------------------------------------------------


async def test_faq_gap(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    prompt = "How does invoice reconciliation work in accounting software?"
    await _seed_topic(s, prompt, n=10, category=PromptCategory.PROBLEM_SOLUTION)
    await db_session.flush()
    await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    row = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).one()
    assert row.gap_type == ContentGapType.MISSING_FAQ.value
    assert row.competitor_evidence["prompt"] == prompt


# --- evidence gaps ---------------------------------------------------------------------


async def test_evidence_gap(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    prompt = "Construction accounting statistics and benchmarks"
    runs = await _seed_topic(s, prompt, n=12)
    # substantial topic page exists → no missing/weak topic; but responses cite
    # research sources tied to the competitor and never the brand
    _page(
        s,
        "https://www.ledgerly.example/blog/construction-accounting-benchmarks",
        "Construction accounting benchmarks",
        words=800,
    )
    db_session.add(
        SourceDomain(
            hostname="statista.com",
            normalized_hostname="statista.com",
            display_name="Statista",
            domain_type="research",
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    await db_session.flush()
    for run_id in runs[:4]:
        resp = (
            await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run_id))
        ).one()
        c = ResponseCitation(
            ai_response_id=resp.id,
            project_id=s.project_id,
            url="https://www.statista.com/construction-software-market",
            domain="www.statista.com",
            citation_type="explicit_url",
            parser_version=PV,
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(
            CitationEntity(
                citation_id=c.id,
                project_id=s.project_id,
                entity_type="competitor",
                entity_id=None,
                entity_name="QuickBooks",
                relationship="competitor",
                confidence=0.8,
            )
        )
    await db_session.flush()
    await ContentGapEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    rows = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).all()
    assert {r.gap_type for r in rows} == {ContentGapType.MISSING_EVIDENCE.value}
    ev = rows[0].competitor_evidence
    assert ev["competitor_research_domains"] == ["statista.com"]
    assert ev["citations"] == 4


# --- scoring ---------------------------------------------------------------------------


def _facts(**overrides: object) -> TopicFacts:
    base = TopicFacts(
        prompt_id=str(uuid.uuid4()),
        prompt_text=CONSTRUCTION,
        category="recommendation",
        funnel_stage="consideration",
        responses=10,
        brand_mentions=0,
        competitor_mentions={"QuickBooks": 10},
        citations=5,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_scoring_components_and_weights() -> None:
    s = score(_facts())
    # full competitor advantage, saturated frequency, commercial, no coverage, evidence
    assert s["components"] == {
        "competitor_advantage": 1.0,
        "prompt_frequency": 1.0,
        "commercial_relevance": 1.0,
        "coverage_deficit": 1.0,
        "evidence_availability": 1.0,
    }
    assert s["score"] == sum(WEIGHTS.values()) == 100.0
    # informational topic with covered page and no citations scores much lower
    covered = _facts(
        category="industry",
        funnel_stage="awareness",
        citations=0,
        matches=[
            PageMatch("u", "t", 900, ["construction"], set()),
        ],
    )
    s2 = score(covered)
    assert s2["components"]["coverage_deficit"] == 0.0
    assert s2["components"]["commercial_relevance"] == 0.4
    assert s2["score"] < 70


def test_classify_gates() -> None:
    # too few responses → nothing
    assert classify(_facts(responses=MIN_TOPIC_RESPONSES - 1)) == []
    # competitors not visible enough → nothing
    assert classify(_facts(competitor_mentions={"QuickBooks": 3})) == []
    # brand nearly as visible as competitor → nothing
    assert classify(_facts(brand_mentions=9)) == []
    # clear lead + no coverage → missing topic (recommendation prompt has no needed type)
    assert classify(_facts()) == [ContentGapType.MISSING_TOPIC]


# --- lifecycle, API and tenant isolation ----------------------------------------------


async def test_patch_status_survives_reanalysis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12)
    await db_session.flush()
    await client.post(f"/api/v1/projects/{pid}/content-gaps/analyze", headers=h)
    gap = (await client.get(f"/api/v1/projects/{pid}/content-gaps", headers=h)).json()["items"][0]
    r = await client.patch(
        f"/api/v1/content-gaps/{gap['id']}",
        json={"status": "reviewing", "note": "planned for Q4"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "reviewing" and r.json()["note"] == "planned for Q4"
    await client.post(f"/api/v1/projects/{pid}/content-gaps/analyze", headers=h)
    again = (await client.get(f"/api/v1/content-gaps/{gap['id']}", headers=h)).json()
    assert again["status"] == "reviewing" and again["note"] == "planned for Q4"
    # filters
    filtered = (
        await client.get(
            f"/api/v1/projects/{pid}/content-gaps",
            params={"gap_type": "missing_topic", "min_score": 50},
            headers=h,
        )
    ).json()
    assert filtered["total"] == 1


async def test_stale_new_gaps_removed_on_reanalysis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12)
    await db_session.flush()
    engine = ContentGapEngine(db_session, now=NOW)
    first = await engine.analyze(uuid.UUID(pid))
    assert first.gaps_written == 1
    # site gains a substantial matching page → the gap's evidence is gone
    _page(
        s,
        "https://www.ledgerly.example/industries/construction-accounting",
        "Construction accounting for contractors",
        words=1500,
    )
    await db_session.flush()
    second = await engine.analyze(uuid.UUID(pid))
    assert second.gaps_written == 0 and second.gaps_removed == 1
    rows = (
        await db_session.scalars(select(ContentGap).where(ContentGap.project_id == uuid.UUID(pid)))
    ).all()
    assert rows == []


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_topic(s, CONSTRUCTION, n=12)
    await db_session.flush()
    await client.post(f"/api/v1/projects/{pid}/content-gaps/analyze", headers=h)
    gap = (await client.get(f"/api/v1/projects/{pid}/content-gaps", headers=h)).json()["items"][0]

    other = await signup(client, org="Other CG Org")
    oh = auth_header(other["access_token"])
    assert (await client.get(f"/api/v1/projects/{pid}/content-gaps", headers=oh)).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/content-gaps/analyze", headers=oh)
    ).status_code == 404
    assert (await client.get(f"/api/v1/content-gaps/{gap['id']}", headers=oh)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/content-gaps/{gap['id']}", json={"status": "dismissed"}, headers=oh
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/content-gaps")).status_code == 401
