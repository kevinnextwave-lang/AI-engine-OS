"""Milestone 5D — Why Competitors Win engine."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.analyzers import (
    CAUTION,
    MIN_RESPONSES,
    BrandProfile,
    CompetitorFacts,
    EntitySignals,
    citation_advantage,
    confidence_for,
    entity_advantage,
)
from app.insights.engine import CompetitiveInsightEngine, categorize_url
from app.models.competitor import Competitor
from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityScope
from app.models.insights import CompetitiveInsight, InsightConfidence
from app.models.intelligence import ResponseCitation, ResponseClaim
from app.models.prompts import AiResponse
from app.models.sources import CitationEntity, SourceDomain
from app.sources.normalize import normalize_hostname
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, PV, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio


async def _competitor_id(db_session: AsyncSession, pid: str, name: str) -> uuid.UUID:
    return (
        await db_session.scalars(
            select(Competitor.id).where(
                Competitor.project_id == uuid.UUID(pid), Competitor.name == name
            )
        )
    ).one()


async def _cite(
    s: Seeder,
    run_id: uuid.UUID,
    url: str,
    *,
    entity: tuple[str, uuid.UUID | None, str] | None,
    domain_type: str = "other",
    authority: bool = False,
) -> None:
    """One citation on a run's response, with an explicit entity attribution and a
    classified source domain — deterministic, no classifier involved."""
    resp = (
        await s.session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run_id))
    ).one()
    citation = ResponseCitation(
        ai_response_id=resp.id,
        project_id=s.project_id,
        url=url,
        domain=None,
        citation_type="explicit_url",
        parser_version=PV,
    )
    s.session.add(citation)
    await s.session.flush()
    host = normalize_hostname(url)
    assert host is not None
    existing = (
        await s.session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == host)
        )
    ).one_or_none()
    if existing is None:
        s.session.add(
            SourceDomain(
                hostname=host,
                normalized_hostname=host,
                display_name=host,
                domain_type=domain_type,
                is_authority=authority,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    if entity is not None:
        etype, eid, ename = entity
        s.session.add(
            CitationEntity(
                citation_id=citation.id,
                project_id=s.project_id,
                entity_type=etype,
                entity_id=eid,
                entity_name=ename,
                relationship="competitor" if etype == "competitor" else "brand",
                confidence=0.8,
            )
        )
    await s.session.flush()


async def _seed_responses(s: Seeder, n: int = 24) -> list[uuid.UUID]:
    runs = []
    for i in range(n):
        run = await s.observation(
            prompt=f"prompt {i % 4}",
            provider="openai" if i % 2 == 0 else "google",
            days_ago=1 + (i % 20),
            mentioned=i % 2 == 0,
            position=2 if i % 2 == 0 else None,
            strength="moderate" if i % 2 == 0 else "unknown",
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
        runs.append(run.id)
    return runs


# --- citation advantage ----------------------------------------------------------------


async def test_citation_advantage(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    runs = await _seed_responses(s)
    qb = ("competitor", qb_id, "QuickBooks")
    hosts = [
        ("https://www.g2.com/products/quickbooks/reviews", "review", True),
        ("https://www.capterra.com/p/quickbooks/", "review", True),
        ("https://www.reddit.com/r/smallbiz/qb", "community", False),
        ("https://www.forbes.com/advisor/quickbooks", "media", True),
        ("https://www.techradar.com/reviews/quickbooks", "media", False),
        ("https://www.pcmag.com/reviews/quickbooks", "review", True),
        ("https://accountingweekly.example/quickbooks", "blog", False),
        ("https://www.trustradius.com/products/quickbooks", "review", False),
    ]
    for i, (url, dtype, auth) in enumerate(hosts):
        for j in range(3):  # 24 competitor citations across 8 domains
            await _cite(
                s, runs[(i * 3 + j) % len(runs)], url, entity=qb, domain_type=dtype, authority=auth
            )
    await _cite(
        s,
        runs[0],
        "https://www.g2.com/products/ledgerly",
        entity=("project", s.project_id, "Ledgerly"),
        domain_type="review",
        authority=True,
    )
    r = await client.post(f"/api/v1/projects/{pid}/competitive-insights/analyze", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligible_responses"] == 24 and body["insights_written"] >= 1
    assert "never causation" in body["note"]
    items = (await client.get(f"/api/v1/projects/{pid}/competitive-insights", headers=h)).json()[
        "items"
    ]
    cite = next(i for i in items if i["insight_type"] == "citation_advantage")
    assert cite["competitor_id"] == str(qb_id)
    assert "larger citation footprint" in cite["title"]
    ev = cite["evidence"]
    assert ev["competitor"]["unique_citing_domains"] == 8
    assert ev["brand"]["unique_citing_domains"] == 1
    assert ev["caution"] == CAUTION
    assert "g2.com" in ev["competitor"]["domains_by_type"]["review"]
    assert "forbes.com" in ev["competitor"]["authoritative_domains"]
    assert cite["impact"] == "high"  # 8x
    # language: observed, never causal
    assert "Observed advantage" in cite["description"]
    assert "because" not in cite["description"].lower()


# --- content advantage -----------------------------------------------------------------


async def test_content_advantage(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    runs = await _seed_responses(s)
    qb = ("competitor", qb_id, "QuickBooks")
    urls = [
        "https://quickbooks.intuit.com/pricing/",
        "https://quickbooks.intuit.com/compare/quickbooks-vs-xero/",
        "https://quickbooks.intuit.com/faq/payroll",
        "https://quickbooks.intuit.com/guide/small-business-accounting",
        "https://quickbooks.intuit.com/customers/agency-story",
    ]
    for i, url in enumerate(urls):
        await _cite(s, runs[i], url, entity=qb, domain_type="company")
    assert categorize_url(urls[1]) == "comparison" and categorize_url(urls[2]) == "faq"
    await CompetitiveInsightEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    rows = (
        await db_session.scalars(
            select(CompetitiveInsight).where(
                CompetitiveInsight.project_id == uuid.UUID(pid),
                CompetitiveInsight.insight_type == "content_advantage",
            )
        )
    ).all()
    assert len(rows) == 1
    ev = rows[0].evidence
    assert ev["competitor_cited_pages_by_category"] == {
        "product": 1,
        "comparison": 1,
        "faq": 1,
        "educational": 1,
        "use_case": 1,
    }
    assert ev["brand_cited_pages_by_category"] == {}
    assert set(ev["categories_where_competitor_leads"]) >= {"comparison", "faq", "product"}
    assert "Pattern detected" in rows[0].description


# --- entity advantage ------------------------------------------------------------------


def _facts(**overrides: object) -> CompetitorFacts:
    base = CompetitorFacts(
        competitor_name="QuickBooks",
        sample_size=30,
        total_prompts=6,
        window_days=90,
        brand=EntitySignals(name="Ledgerly"),
        competitor=EntitySignals(name="QuickBooks"),
        brand_profile=BrandProfile(),
        visibility_gap=None,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


async def test_entity_advantage(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_responses(s)  # QuickBooks always first + strong; brand half, moderate
    # brand site crawled, but: no Organization schema, no Product schema, no sameAs
    db_session.add(
        WebsitePage(
            project_id=s.project_id,
            url="https://www.ledgerly.example/",
            normalized_url="https://www.ledgerly.example/",
            http_status=200,
            content_type="text/html",
            first_crawled_at=NOW,
            last_crawled_at=NOW,
        )
    )
    db_session.add(
        Entity(
            project_id=s.project_id,
            scope=EntityScope.PAGE,
            entity_type="WebSite",
            name="Ledgerly",
        )
    )
    await db_session.flush()
    await CompetitiveInsightEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    row = (
        await db_session.scalars(
            select(CompetitiveInsight).where(
                CompetitiveInsight.project_id == uuid.UUID(pid),
                CompetitiveInsight.insight_type == "entity_advantage",
            )
        )
    ).one()
    ev = row.evidence
    assert ev["competitor_site_analyzed"] is False
    assert ev["brand_has_organization_schema"] is False and ev["brand_sameas_links"] == 0
    assert len(ev["gaps"]) >= 3
    assert "Potential contributing factor" in row.description
    assert row.confidence in ("low", "medium")  # never high: competitor side unobserved
    assert "because" not in row.description.lower()


def test_entity_advantage_needs_visibility_gap_and_crawl() -> None:
    profile = BrandProfile(pages_crawled=1)  # gaps everywhere, but no visibility gap
    assert entity_advantage(_facts(brand_profile=profile, visibility_gap=5.0)) is None
    # gap but no crawl → nothing to compare against
    assert entity_advantage(_facts(visibility_gap=30.0)) is None
    got = entity_advantage(_facts(brand_profile=profile, visibility_gap=30.0))
    assert got is not None and got.confidence is not InsightConfidence.HIGH


# --- evidence advantage ----------------------------------------------------------------


async def test_evidence_advantage(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    runs = await _seed_responses(s)
    qb = ("competitor", qb_id, "QuickBooks")
    await _cite(
        s, runs[0], "https://www.statista.com/accounting-market", entity=qb, domain_type="research"
    )
    await _cite(
        s,
        runs[1],
        "https://www.gartner.com/reports/smb-accounting",
        entity=qb,
        domain_type="research",
        authority=True,
    )
    resp_ids = (
        await db_session.scalars(
            select(AiResponse.id).where(AiResponse.prompt_run_id.in_(runs[:6]))
        )
    ).all()
    for i, rid in enumerate(resp_ids[:6]):
        db_session.add(
            ResponseClaim(
                ai_response_id=rid,
                project_id=s.project_id,
                subject="QuickBooks",
                predicate="serves",
                object=f"{5 + i} million customers",
                confidence=0.7,
                context="QuickBooks serves millions of customers as of 2026.",
                parser_version=PV,
            )
        )
    await db_session.flush()
    await CompetitiveInsightEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    row = (
        await db_session.scalars(
            select(CompetitiveInsight).where(
                CompetitiveInsight.project_id == uuid.UUID(pid),
                CompetitiveInsight.insight_type == "evidence_advantage",
            )
        )
    ).one()
    ev = row.evidence
    assert ev["competitor_research_domains"] == ["gartner.com", "statista.com"]
    assert ev["brand_research_domains"] == []
    assert ev["competitor_specific_claims"] == 6 and ev["brand_specific_claims"] == 0
    assert len(ev["claim_examples"]) == 5
    assert "Pattern detected" in row.description and "cannot be determined" in row.description


# --- confidence ------------------------------------------------------------------------


def test_confidence_ladder() -> None:
    assert confidence_for(60, 30) is InsightConfidence.HIGH
    assert confidence_for(60, 10) is InsightConfidence.MEDIUM
    assert confidence_for(25, 8) is InsightConfidence.MEDIUM
    assert confidence_for(25, 3) is InsightConfidence.LOW
    assert confidence_for(12, 100) is InsightConfidence.LOW


def test_citation_advantage_confidence_scales_with_sample() -> None:
    comp = EntitySignals(
        name="QuickBooks",
        citations=30,
        citing_domains={f"d{i}.example" for i in range(10)},
    )
    small = _facts(sample_size=12, competitor=comp)
    large = _facts(sample_size=80, competitor=comp)
    assert citation_advantage(small).confidence is InsightConfidence.LOW
    assert citation_advantage(large).confidence is InsightConfidence.HIGH


# --- insufficient evidence -------------------------------------------------------------


async def test_insufficient_evidence_produces_no_insights(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    for i in range(MIN_RESPONSES - 1):
        run = await s.observation(
            days_ago=1 + i,
            mentioned=False,
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
        await _cite(
            s,
            run.id,
            f"https://site{i}.example/quickbooks-review",
            entity=("competitor", qb_id, "QuickBooks"),
            domain_type="review",
        )
    r = await client.post(f"/api/v1/projects/{pid}/competitive-insights/analyze", headers=h)
    body = r.json()
    assert body["insights_written"] == 0 and "Fewer than" in body["note"]
    listing = (await client.get(f"/api/v1/projects/{pid}/competitive-insights", headers=h)).json()
    assert listing["total"] == 0 and listing["items"] == [] and listing["note"] == CAUTION


async def test_thin_evidence_produces_no_weak_insights(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Enough responses, but tiny citation/claim gaps → nothing is asserted."""
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    runs = []
    for i in range(12):
        run = await s.observation(
            prompt=f"p{i % 4}",
            days_ago=1 + i,
            mentioned=True,
            position=1,
            competitors=[("QuickBooks", 2, "positive", "moderate")],
        )
        runs.append(run.id)
    await _cite(
        s,
        runs[0],
        "https://www.g2.com/products/quickbooks",
        entity=("competitor", qb_id, "QuickBooks"),
        domain_type="review",
    )
    result = await CompetitiveInsightEngine(db_session, now=NOW).analyze(uuid.UUID(pid))
    assert result.insights_written == 0


# --- re-analysis and stale removal -----------------------------------------------------


async def test_reanalysis_upserts_and_removes_stale(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    runs = await _seed_responses(s)
    for i in range(8):
        await _cite(
            s,
            runs[i],
            f"https://reviews{i}.example/quickbooks",
            entity=("competitor", qb_id, "QuickBooks"),
            domain_type="review",
        )
    engine = CompetitiveInsightEngine(db_session, now=NOW)
    first = await engine.analyze(uuid.UUID(pid))
    assert first.insights_written >= 1
    ids_before = {
        (r.insight_type, r.id)
        for r in (
            await db_session.scalars(
                select(CompetitiveInsight).where(CompetitiveInsight.project_id == uuid.UUID(pid))
            )
        ).all()
    }
    second = await engine.analyze(uuid.UUID(pid))  # same data → same rows, updated in place
    ids_after = {
        (r.insight_type, r.id)
        for r in (
            await db_session.scalars(
                select(CompetitiveInsight).where(CompetitiveInsight.project_id == uuid.UUID(pid))
            )
        ).all()
    }
    assert ids_before == ids_after and second.insights_removed == 0
    # narrow window with no data → evidence gone → stale rows removed
    shrunk = await CompetitiveInsightEngine(db_session, now=NOW + timedelta(days=400)).analyze(
        uuid.UUID(pid), window_days=7
    )
    assert shrunk.insights_written == 0 and shrunk.insights_removed == len(ids_before)


# --- API shape and authorization -------------------------------------------------------


async def test_competitor_scoped_listing_and_authz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    qb_id = await _competitor_id(db_session, pid, "QuickBooks")
    xero_id = await _competitor_id(db_session, pid, "Xero")
    runs = await _seed_responses(s)
    for i in range(8):
        await _cite(
            s,
            runs[i],
            f"https://reviews{i}.example/quickbooks",
            entity=("competitor", qb_id, "QuickBooks"),
            domain_type="review",
        )
    assert (
        await client.post(f"/api/v1/projects/{pid}/competitive-insights/analyze", headers=h)
    ).status_code == 200
    qb_items = (await client.get(f"/api/v1/competitors/{qb_id}/insights", headers=h)).json()
    assert qb_items["total"] >= 1
    assert all(i["competitor_id"] == str(qb_id) for i in qb_items["items"])
    xero_items = (await client.get(f"/api/v1/competitors/{xero_id}/insights", headers=h)).json()
    assert xero_items["total"] == 0
    # filters on the project listing
    filtered = (
        await client.get(
            f"/api/v1/projects/{pid}/competitive-insights",
            params={"insight_type": "citation_advantage", "competitor_id": str(qb_id)},
            headers=h,
        )
    ).json()
    assert filtered["total"] >= 1
    assert all(i["insight_type"] == "citation_advantage" for i in filtered["items"])

    other = await signup(client, org="Other Insight Org")
    oh = auth_header(other["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/competitive-insights", headers=oh)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/competitive-insights/analyze", headers=oh)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/competitors/{qb_id}/insights", headers=oh)
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/competitive-insights")).status_code == 401
