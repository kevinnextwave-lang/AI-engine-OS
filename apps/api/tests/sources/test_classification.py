"""Source classification (4B): registry, signals, probabilistic combination,
unknown-stays-unknown, relevance score, source profile API."""

import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sources import DomainType, SourceDomain, SourcePage
from app.sources.classify import Evidence, PageSignals, classify, combine
from app.sources.registry import SourceRegistry, get_registry
from app.sources.relevance import RelevanceInputs, source_relevance
from app.sources.service import SourceIntelligenceService
from tests.conftest import auth_header
from tests.sources.test_sources import _citation
from tests.test_authz import signup
from tests.visibility.seed import Seeder, project_with_competitors

REG = get_registry()


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("g2.com", DomainType.REVIEW),
        ("www.g2.com", DomainType.REVIEW),
        ("capterra.com", DomainType.REVIEW),
        ("reddit.com", DomainType.COMMUNITY),
        ("old.reddit.com", DomainType.COMMUNITY),
        ("stackoverflow.com", DomainType.FORUM),
        ("forbes.com", DomainType.MEDIA),
        ("techcrunch.com", DomainType.MEDIA),
        ("linkedin.com", DomainType.SOCIAL),
        ("crunchbase.com", DomainType.DIRECTORY),
        ("arxiv.org", DomainType.RESEARCH),
        ("medium.com", DomainType.BLOG),
        ("nasa.gov", DomainType.GOVERNMENT),
        ("data.gov.uk", DomainType.GOVERNMENT),
        ("mit.edu", DomainType.EDUCATION),
        ("ox.ac.uk", DomainType.EDUCATION),
    ],
)
def test_common_categories(host: str, expected: DomainType) -> None:
    c = classify(host.removeprefix("www."), registry=REG)
    assert c.domain_type is expected
    assert c.confidence >= 0.9
    assert c.probabilities[expected.value] == 1.0
    assert any(e.signal in ("registry", "tld") for e in c.evidence)


def test_company_hosts_win() -> None:
    c = classify("ledgerly.example", registry=REG, company_hosts=frozenset({"ledgerly.example"}))
    assert c.domain_type is DomainType.COMPANY and c.confidence >= 0.95
    c = classify(
        "app.ledgerly.example", registry=REG, company_hosts=frozenset({"ledgerly.example"})
    )
    assert c.domain_type is DomainType.COMPANY


@pytest.mark.parametrize(
    "host", ["some-random-site.io", "acme-widgets.com", "xn--mnchen-3ya.de", "example.org"]
)
def test_unknown_domains_stay_unknown(host: str) -> None:
    c = classify(host, registry=REG)
    assert c.domain_type is DomainType.UNKNOWN
    assert c.confidence == 0.0 and c.evidence == [] and c.probabilities == {}


def test_weak_signals_alone_do_not_force_a_category() -> None:
    """One path hint (0.25) is below the threshold → unknown, but the candidate is reported."""
    c = classify(
        "acme-widgets.com",
        registry=REG,
        pages=[PageSignals(url="https://acme-widgets.com/blog/hello")],
    )
    assert c.domain_type is DomainType.UNKNOWN
    assert c.probabilities == {"blog": 1.0}
    assert [e.signal for e in c.evidence] == ["url_structure"]


def test_weak_signals_accumulate_probabilistically() -> None:
    """Several consistent weak signals (subdomain + paths + titles) cross the threshold."""
    pages = [
        PageSignals(
            url="https://blog.acme-widgets.com/blog/post-1", title="How to pick widgets — Acme blog"
        ),
        PageSignals(url="https://blog.acme-widgets.com/blog/post-2", title="Widget tutorial"),
        PageSignals(
            url="https://blog.acme-widgets.com/posts/3", metadata={"generator": "WordPress 6.5"}
        ),
    ]
    c = classify("blog.acme-widgets.com", registry=REG, pages=pages)
    assert c.domain_type is DomainType.BLOG
    assert 0.5 <= c.confidence < 0.95  # probabilistic, not certain
    signals = {e.signal for e in c.evidence}
    assert {"hostname_pattern", "url_structure", "page_title", "page_metadata"} <= signals
    assert c.probabilities["blog"] > 0.9


def test_conflicting_evidence_is_not_decided() -> None:
    """Equal strong evidence for two types → unknown with both candidates shown."""
    reg = SourceRegistry.from_dict(
        {"known_review_domains": ["both.example"], "known_media_domains": ["both.example"]}
    )
    c = classify("both.example", registry=reg)
    assert c.domain_type is DomainType.UNKNOWN
    assert set(c.probabilities) == {"review", "media"}


def test_noisy_or_combination() -> None:
    scores = combine(
        [
            Evidence(DomainType.BLOG, 0.25, "url_structure", "/blog"),
            Evidence(DomainType.BLOG, 0.25, "url_structure", "/blog"),
            Evidence(DomainType.MEDIA, 0.9, "registry", "x"),
        ]
    )
    assert scores[DomainType.BLOG] == pytest.approx(1 - 0.75 * 0.75)
    assert scores[DomainType.MEDIA] == pytest.approx(0.9)


def test_registry_override_extends_lists(tmp_path: Path) -> None:
    extra = tmp_path / "registry.json"
    extra.write_text(
        json.dumps(
            {
                "known_review_domains": ["my-niche-reviews.example"],
                "hostname_patterns": {"review": ["ratings."]},
            }
        )
    )
    reg = SourceRegistry.load(str(extra))
    assert "g2.com" in reg.lists["known_review_domains"]  # bundled kept
    assert classify("my-niche-reviews.example", registry=reg).domain_type is DomainType.REVIEW
    assert "ratings." in reg.hostname_patterns["review"]
    assert reg.is_authority("en.wikipedia.org") and not reg.is_authority("g2.com")


def test_relevance_score_is_transparent_and_bounded() -> None:
    low = source_relevance(RelevanceInputs(1, 1, 1, 1, "unknown"))
    high = source_relevance(RelevanceInputs(5000, 40, 52, 52, "research", is_authority=True))
    assert low["name"] == high["name"] == "Source Relevance Score"
    assert 0 <= low["score"] < high["score"] <= 100
    assert (
        high["components"]["frequency"]["value"] == 100
        and high["components"]["source_type"]["value"] == 90
    )
    assert set(low["components"]) == {"frequency", "breadth", "consistency", "source_type"}
    assert low["scope"] == "global"
    scoped = source_relevance(RelevanceInputs(10, 2, 2, 4, "review", project_citation_count=10))
    assert scoped["scope"] == "project" and "project_frequency" in scoped["components"]
    assert scoped["components"]["consistency"]["value"] == 50.0
    assert "not a universal domain authority" in low["note"]


# --- service + API ------------------------------------------------------------------


async def test_classification_is_stored_and_upgraded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    # unknown host: stays unknown, evidence stored
    await svc.resolve_citation(
        await _citation(s, url="https://acme-widgets.com/x", domain=None), hosts
    )
    d = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "acme-widgets.com")
        )
    ).one()
    assert d.domain_type == "unknown" and d.classification_confidence is None and d.classified_at
    # three cited blog pages with titles → full pass upgrades it to blog with a real confidence
    for i in range(3):
        await svc.resolve_citation(
            await _citation(
                s, url=f"https://acme-widgets.com/blog/post-{i}", domain=None, prompt=f"p{i}"
            ),
            hosts,
        )
    pages = (
        await db_session.scalars(select(SourcePage).where(SourcePage.source_domain_id == d.id))
    ).all()
    for p in pages:
        p.title = "How to choose widgets — blog"
    await db_session.flush()
    result = await svc.classify_domain_record(d)
    assert result.domain_type is DomainType.BLOG and d.domain_type == "blog"
    assert (
        d.classification_confidence == pytest.approx(result.confidence)
        and 0.5 <= result.confidence < 1
    )
    assert d.classification and d.classification["probabilities"]["blog"] > 0.9
    # reclassify over everything keeps known types
    assert await svc.reclassify() >= 1
    await db_session.refresh(d)
    assert d.domain_type == "blog"


async def test_source_profile_api_scoped_to_caller(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h_a, _, pid_a = await project_with_competitors(client)
    h_b, _, pid_b = await project_with_competitors(client, competitors=("Xero",))
    sa_, sb = Seeder(db_session, uuid.UUID(pid_a)), Seeder(db_session, uuid.UUID(pid_b))
    svc = SourceIntelligenceService(db_session)
    ha, hb = await svc.project_hosts(sa_.project_id), await svc.project_hosts(sb.project_id)
    assert ha and hb
    for i in range(3):
        await svc.resolve_citation(
            await _citation(
                sa_, url="https://www.g2.com/products/ledgerly/reviews", domain=None, prompt=f"a{i}"
            ),
            ha,
        )
    await svc.resolve_citation(
        await _citation(
            sa_, url="https://www.g2.com/products/xero/reviews", domain=None, prompt="ax"
        ),
        ha,
    )
    await svc.resolve_citation(
        await _citation(
            sb, url="https://www.g2.com/products/xero/reviews", domain=None, prompt="b"
        ),
        hb,
    )
    # A: competitor citation via xero.com; B: none
    await svc.resolve_citation(
        await _citation(sa_, url="https://xero.com/pricing", domain=None, prompt="ac"), ha
    )
    await db_session.commit()
    g2 = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "g2.com")
        )
    ).one()

    assert (await client.get(f"/api/v1/source-domains/{g2.id}")).status_code == 401
    assert (
        await client.get(f"/api/v1/source-domains/{uuid.uuid4()}", headers=h_a)
    ).status_code == 404

    a = (await client.get(f"/api/v1/source-domains/{g2.id}", headers=h_a)).json()
    assert a["domain"] == "g2.com" and a["type"] == "review"
    assert a["classification"]["confidence"] >= 0.9 and a["classification"]["evidence"]
    assert a["citation_count"] == 4 and a["global_citation_count"] == 5
    assert a["projects_observed"] == 1 and a["global_projects_observed"] == 2
    assert a["pages_cited"] == 2 and [p["citation_count"] for p in a["pages"]] == [3, 1]
    # slug evidence: /products/ledgerly → brand, /products/xero → competitor (A configured Xero)
    assert a["brands_cited"] == [{"name": "Ledgerly", "citations": 3}]
    assert a["competitors_cited"] == [{"name": "Xero", "citations": 1}]
    assert a["relevance"]["name"] == "Source Relevance Score" and 0 < a["relevance"]["score"] <= 100
    assert a["relevance"]["scope"] == "global"
    assert a["first_seen_at"] and a["last_seen_at"]

    b = (await client.get(f"/api/v1/source-domains/{g2.id}", headers=h_b)).json()
    assert b["citation_count"] == 1 and b["projects_observed"] == 1 and b["pages_cited"] == 1
    assert b["global_citation_count"] == 5  # counts only; no tenant detail

    # project scope: only own projects; other tenant's project → 404
    scoped = (
        await client.get(
            f"/api/v1/source-domains/{g2.id}", params={"project_id": pid_a}, headers=h_a
        )
    ).json()
    assert (
        scoped["relevance"]["scope"] == "project"
        and "project_frequency" in scoped["relevance"]["components"]
    )
    assert (
        await client.get(
            f"/api/v1/source-domains/{g2.id}", params={"project_id": pid_a}, headers=h_b
        )
    ).status_code == 404

    xero = (
        await db_session.scalars(
            select(SourceDomain).where(SourceDomain.normalized_hostname == "xero.com")
        )
    ).one()
    x_a = (await client.get(f"/api/v1/source-domains/{xero.id}", headers=h_a)).json()
    assert x_a["type"] == "company" and x_a["competitors_cited"] == [
        {"name": "Xero", "citations": 1}
    ]
    stranger = await signup(client, org="Stranger")
    x_s = (
        await client.get(
            f"/api/v1/source-domains/{xero.id}", headers=auth_header(stranger["access_token"])
        )
    ).json()
    assert x_s["citation_count"] == 0 and x_s["competitors_cited"] == [] and x_s["pages"] == []
    assert x_s["global_citation_count"] == 1
