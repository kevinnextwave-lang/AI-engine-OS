"""Citation Intelligence (4A): normalisation, dedup, relationships, aggregation,
tenant isolation, backfill."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import ResponseCitation
from app.models.sources import (
    CitationEntity,
    DomainType,
    ProjectSource,
    SourceDomain,
    SourcePage,
)
from app.sources.normalize import (
    classify_domain,
    display_name_for,
    normalize_hostname,
    normalize_url,
)
from app.sources.service import SourceIntelligenceService
from tests.visibility.seed import Seeder, project_with_competitors

# --- normalisation (pure) -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.com", "example.com"),
        ("WWW.Example.COM.", "example.com"),
        ("https://www.example.com/path", "example.com"),
        ("docs.example.co.uk", "docs.example.co.uk"),
        ("münchen.de", "xn--mnchen-3ya.de"),
        ("", None),
        (None, None),
        ("localhost", None),
        ("not a host", None),
    ],
)
def test_normalize_hostname(raw: str | None, expected: str | None) -> None:
    assert normalize_hostname(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Example.com/Pricing/", "https://example.com/Pricing"),
        ("HTTP://example.com:80/a//b/?b=2&a=1#frag", "http://example.com/a/b?a=1&b=2"),
        (
            "https://example.com/?utm_source=x&utm_medium=y&id=7&fbclid=zz",
            "https://example.com/?id=7",
        ),
        ("example.com/docs", "https://example.com/docs"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        ("ftp://example.com/x", None),
        ("mailto:a@b.com", None),
        ("", None),
    ],
)
def test_normalize_url(raw: str, expected: str | None) -> None:
    assert normalize_url(raw) == expected


def test_display_name_and_classification() -> None:
    assert display_name_for("docs.example.com") == "example.com"
    assert display_name_for("example.co.uk") == "example.co.uk"
    assert classify_domain("reddit.com") is DomainType.COMMUNITY
    assert classify_domain("old.reddit.com") is DomainType.COMMUNITY
    assert classify_domain("g2.com") is DomainType.REVIEW
    assert classify_domain("nasa.gov") is DomainType.GOVERNMENT
    assert classify_domain("ox.ac.uk") is DomainType.EDUCATION
    assert (
        classify_domain("ledgerly.example", company_hosts=frozenset({"ledgerly.example"}))
        is DomainType.COMPANY
    )
    assert (
        classify_domain("app.ledgerly.example", company_hosts=frozenset({"ledgerly.example"}))
        is DomainType.COMPANY
    )
    # no evidence → unknown, never a guess
    assert classify_domain("some-random-site.io") is DomainType.UNKNOWN


# --- service over the database -----------------------------------------------------


async def _citation(
    s: Seeder,
    *,
    url: str | None,
    domain: str | None,
    days_ago: float = 1,
    prompt: str = "best accounting tools",
) -> ResponseCitation:
    run = await s.observation(prompt=prompt, days_ago=days_ago)
    from app.models.prompts import AiResponse

    resp = (
        await s.session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).one()
    c = ResponseCitation(
        ai_response_id=resp.id,
        project_id=s.project_id,
        url=url,
        domain=domain,
        citation_type="explicit_url" if url else "domain_reference",
        parser_version="response-parser/v1",
    )
    s.session.add(c)
    await s.session.flush()
    # created_at is the observation time
    c.created_at = datetime.now(UTC) - timedelta(days=days_ago)
    await s.session.flush()
    return c


async def test_duplicate_sources_collapse_to_one_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    variants = [
        ("https://www.G2.com/products/ledgerly/reviews/", "www.g2.com"),
        ("https://g2.com/products/ledgerly/reviews?utm_source=chatgpt", "g2.com"),
        ("http://G2.COM:80/products/ledgerly/reviews", None),
    ]
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    for url, domain in variants:
        assert await svc.resolve_citation(await _citation(s, url=url, domain=domain), hosts)
    domains = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "g2.com")
        )
    ).all()
    assert len(domains) == 1 and domains[0].domain_type == "review"
    pages = (
        await db_session.scalars(
            select(SourcePage)
            .where(SourcePage.source_domain_id == domains[0].id)
            .order_by(SourcePage.normalized_url)
        )
    ).all()
    # the two https variants collapse; http is a distinct page (scheme is never assumed)
    assert [p.normalized_url for p in pages] == [
        "http://g2.com/products/ledgerly/reviews",
        "https://g2.com/products/ledgerly/reviews",
    ]
    cites = (
        await db_session.scalars(
            select(ResponseCitation).where(ResponseCitation.project_id == s.project_id)
        )
    ).all()
    assert {c.source_domain_id for c in cites} == {domains[0].id}
    assert sum(1 for c in cites if c.source_page_id == pages[1].id) == 2


async def test_http_and_https_are_distinct_pages_same_domain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    for url in ("https://example.org/a", "http://example.org/a"):
        await svc.resolve_citation(await _citation(s, url=url, domain=None), hosts)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(SourceDomain)
            .where(SourceDomain.normalized_hostname == "example.org")
        )
        == 1
    )
    assert await db_session.scalar(select(func.count()).select_from(SourcePage)) == 2


async def test_first_and_last_seen_span_all_observations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    for days in (10, 1, 5):
        await svc.resolve_citation(
            await _citation(s, url="https://forbes.com/x", domain=None, days_ago=days), hosts
        )
    d = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "forbes.com")
        )
    ).one()
    assert (d.last_seen_at - d.first_seen_at).days == 9
    assert d.domain_type == "media"


async def test_citation_relationships_brand_competitor_or_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(
        client
    )  # domain ledgerly.example; competitors QuickBooks, Xero
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    brand = await _citation(s, url="https://www.ledgerly.example/pricing", domain=None)
    brand_sub = await _citation(s, url="https://docs.ledgerly.example/api", domain=None)
    comp = await _citation(s, url=None, domain="www.xero.com")
    neutral = await _citation(
        s, url="https://www.reddit.com/r/smallbusiness/comments/1", domain="reddit.com"
    )
    for c in (brand, brand_sub, comp, neutral):
        await svc.resolve_citation(c, hosts)
    ents = {e.citation_id: e for e in (await db_session.scalars(select(CitationEntity))).all()}
    assert ents[brand.id].relationship == "brand" and ents[brand.id].entity_type == "project"
    assert ents[brand.id].entity_id == s.project_id and ents[brand.id].confidence == 0.95
    assert ents[brand_sub.id].relationship == "brand" and ents[brand_sub.id].confidence == 0.8
    assert ents[comp.id].relationship == "competitor" and ents[comp.id].entity_name == "Xero"
    assert ents[comp.id].entity_type == "competitor" and ents[comp.id].entity_id is not None
    assert neutral.id not in ents  # uncertain → no relationship forced
    # resolving again does not duplicate relationship rows
    await svc.resolve_citation(brand, hosts)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CitationEntity)
            .where(CitationEntity.citation_id == brand.id)
        )
        == 1
    )
    # the brand's own domain is classified as company
    d = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "ledgerly.example")
        )
    ).one()
    assert d.domain_type == "company"


async def test_project_source_aggregation(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    cites = [
        ("https://www.g2.com/products/ledgerly", None, 3),
        ("https://www.g2.com/products/ledgerly", None, 1),
        ("https://www.g2.com/products/xero", None, 2),
        ("https://ledgerly.example/pricing", None, 1),
        (None, "quickbooks.com", 1),
        (None, None, 1),  # unresolvable, never counted
    ]
    for url, domain, days in cites:
        await svc.resolve_citation(await _citation(s, url=url, domain=domain, days_ago=days), hosts)
    n = await svc.aggregate_project_sources(s.project_id)
    rows = (
        await db_session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == s.project_id)
        )
    ).all()
    assert n == len(rows) == 3 + 3  # 3 domains + 3 distinct pages
    by_domain = {}
    for r in rows:
        d = await db_session.get(SourceDomain, r.source_domain_id)
        assert d is not None
        by_domain.setdefault(d.normalized_hostname, []).append(r)
    g2_domain = next(r for r in by_domain["g2.com"] if r.source_page_id is None)
    assert g2_domain.citation_count == 3 and g2_domain.brand_citation_count == 0
    assert (g2_domain.last_cited_at - g2_domain.first_cited_at).days == 2
    g2_pages = sorted(
        (r.citation_count for r in by_domain["g2.com"] if r.source_page_id), reverse=True
    )
    assert g2_pages == [2, 1]
    brand_row = next(r for r in by_domain["ledgerly.example"] if r.source_page_id is None)
    assert brand_row.citation_count == 1 and brand_row.brand_citation_count == 1
    qb = next(r for r in by_domain["quickbooks.com"] if r.source_page_id is None)
    assert qb.competitor_citation_count == 1 and qb.brand_citation_count == 0
    # idempotent rebuild
    assert await svc.aggregate_project_sources(s.project_id) == 6
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectSource)
            .where(ProjectSource.project_id == s.project_id)
        )
        == 6
    )


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    """Two tenants citing the same page share the source rows but never each
    other's project-level data; a competitor configured by tenant A is not a
    competitor for tenant B."""
    _, _, pid_a = await project_with_competitors(client)
    _, _, pid_b = await project_with_competitors(client, competitors=())
    sa_, sb = Seeder(db_session, uuid.UUID(pid_a)), Seeder(db_session, uuid.UUID(pid_b))
    svc = SourceIntelligenceService(db_session)
    ha, hb = await svc.project_hosts(sa_.project_id), await svc.project_hosts(sb.project_id)
    assert ha and hb
    url = "https://www.xero.com/blog/best-tools"
    ca = await _citation(sa_, url=url, domain=None)
    cb = await _citation(sb, url=url, domain=None)
    await svc.resolve_citation(ca, ha)
    await svc.resolve_citation(cb, hb)
    assert ca.source_page_id == cb.source_page_id and ca.source_domain_id == cb.source_domain_id
    ents = (await db_session.scalars(select(CitationEntity))).all()
    assert [e.project_id for e in ents] == [sa_.project_id]  # only A has Xero as competitor
    await svc.aggregate_project_sources(sa_.project_id)
    await svc.aggregate_project_sources(sb.project_id)
    a_rows = (
        await db_session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == sa_.project_id)
        )
    ).all()
    b_rows = (
        await db_session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == sb.project_id)
        )
    ).all()
    assert len(a_rows) == len(b_rows) == 2
    assert all(r.competitor_citation_count == 1 for r in a_rows)
    assert all(r.competitor_citation_count == 0 for r in b_rows)
    # rebuilding A never touches B
    await svc.aggregate_project_sources(sa_.project_id)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectSource)
            .where(ProjectSource.project_id == sb.project_id)
        )
        == 2
    )


async def test_historical_backfill(client: AsyncClient, db_session: AsyncSession) -> None:
    """Citations stored before 4A have no source links; the backfill fills them
    without re-running any prompt."""
    _, _, pid_a = await project_with_competitors(client)
    _, _, pid_b = await project_with_competitors(client, competitors=("Xero",))
    sa_, sb = Seeder(db_session, uuid.UUID(pid_a)), Seeder(db_session, uuid.UUID(pid_b))
    for i in range(7):
        await _citation(
            sa_, url=f"https://www.g2.com/products/p{i % 3}", domain=None, prompt=f"a{i}"
        )
    await _citation(sa_, url="https://ledgerly.example/", domain=None, prompt="brand")
    await _citation(sa_, url=None, domain=None, prompt="nothing")
    await _citation(sb, url=None, domain="xero.com", prompt="b")
    await db_session.commit()
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ResponseCitation)
            .where(ResponseCitation.source_domain_id.is_not(None))
        )
        == 0
    )

    stats = await SourceIntelligenceService(db_session).backfill(batch_size=4)
    assert stats.resolved == 9 and stats.skipped == 1
    assert stats.domains_created == 3 and stats.pages_created == 4
    assert stats.relationships == 2  # ledgerly (brand, A) + xero (competitor, B)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ResponseCitation)
            .where(ResponseCitation.source_domain_id.is_(None))
        )
        == 1
    )
    a_rows = (
        await db_session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == sa_.project_id)
        )
    ).all()
    assert sum(r.citation_count for r in a_rows if r.source_page_id is None) == 8
    b_rows = (
        await db_session.scalars(
            select(ProjectSource).where(ProjectSource.project_id == sb.project_id)
        )
    ).all()
    assert len(b_rows) == 1 and b_rows[0].competitor_citation_count == 1
    # second run is a no-op without force
    again = await SourceIntelligenceService(db_session).backfill()
    assert again.resolved == 0
    # force re-resolves but creates nothing new
    forced = await SourceIntelligenceService(db_session).backfill(
        project_id=sa_.project_id, force=True
    )
    assert forced.resolved == 8 and forced.domains_created == 0 and forced.pages_created == 0
    assert await db_session.scalar(select(func.count()).select_from(CitationEntity)) == 2


async def test_parse_pipeline_links_new_citations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Citations produced by the parser are resolved immediately, so new data
    never needs a backfill."""
    from tests.intelligence import fixtures as fx
    from tests.intelligence.test_service_api import _run_batch, _setup

    h, _, pid, set_id, reg = await _setup(client, fx.LIST_RECOMMENDATIONS)
    _, run_id = await _run_batch(client, db_session, h, set_id, reg)
    cites = (
        await db_session.scalars(
            select(ResponseCitation).where(ResponseCitation.project_id == uuid.UUID(pid))
        )
    ).all()
    assert cites and all(c.source_domain_id is not None for c in cites)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectSource)
            .where(ProjectSource.project_id == uuid.UUID(pid))
        )
        >= 1
    )
    # reprocessing replaces citations and keeps aggregates consistent (no orphans)
    r = await client.post(f"/api/v1/prompt-runs/{run_id}/reprocess", headers=h)
    assert r.status_code == 200
    cites2 = (
        await db_session.scalars(
            select(ResponseCitation).where(ResponseCitation.project_id == uuid.UUID(pid))
        )
    ).all()
    assert len(cites2) == len(cites) and all(c.source_page_id or c.source_domain_id for c in cites2)
    total = await db_session.scalar(
        select(func.sum(ProjectSource.citation_count)).where(
            ProjectSource.project_id == uuid.UUID(pid), ProjectSource.source_page_id.is_(None)
        )
    )
    assert total == len([c for c in cites2 if c.source_domain_id])
