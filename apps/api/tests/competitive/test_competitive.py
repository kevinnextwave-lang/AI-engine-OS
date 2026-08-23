"""Milestone 5C — Competitive AI Visibility."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitive import METHOD
from app.competitive.engine import CompetitiveVisibilityEngine
from app.competitive.metrics import (
    BRAND,
    MATERIAL_ADVANTAGE,
    RANKING_MIN_SAMPLE,
    WEIGHTS,
    advantages,
    compute_all,
    ranking,
)
from app.core.security import create_access_token
from app.models import MembershipRole
from app.visibility.metrics import MIN_SAMPLE
from app.visibility.observations import load_observations
from tests.conftest import auth_header
from tests.test_authz import add_member, signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio


async def _seed_market(db_session: AsyncSession, pid: str, *, n: int = 24, days_offset: float = 0):
    """n responses over 3 prompts and 2 providers. QuickBooks dominates (always
    mentioned first, strongly recommended, often cited); the brand is mentioned in
    half, cited in a quarter; Xero is mentioned in a third with mixed sentiment."""
    s = Seeder(db_session, uuid.UUID(pid))
    prompts = ["best accounting tools", "quickbooks alternatives", "ledgerly vs quickbooks"]
    for i in range(n):
        mentioned = i % 2 == 0
        comps = [("QuickBooks", 1, "positive", "strong")]
        if i % 3 == 0:
            comps.append(("Xero", 3, "mixed", "weak"))
        await s.observation(
            prompt=prompts[i % 3],
            provider="openai" if i % 2 == 0 else "google",
            days_ago=days_offset + 1 + (i % 20) * 0.5,
            mentioned=mentioned,
            position=2 if mentioned else None,
            sentiment="positive",
            strength="moderate" if mentioned else "unknown",
            cited=mentioned and i % 4 == 0,
            competitors=comps,
            competitor_cited=["QuickBooks"] if i % 2 == 1 else [],
        )
    return s


# --- brand vs competitor -------------------------------------------------------------


async def test_brand_vs_competitor_metrics(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    await _seed_market(db_session, pid)
    r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == METHOD and body["weights"] == WEIGHTS
    assert "not an industry-standard" in body["note"]
    dq = body["data_quality"]
    assert dq["sample_size"] == 24 and dq["prompt_count"] == 3 and dq["provider_count"] == 2
    assert dq["confidence"] == "moderate" and dq["date_range"]["start"] < dq["date_range"]["end"]
    by = {e["name"]: e for e in body["entities"]}
    assert set(by) == {BRAND, "QuickBooks", "Xero"}
    brand, qb, xero = by[BRAND], by["QuickBooks"], by["Xero"]
    # mention share
    assert (
        brand["mention_share"] == 50 and qb["mention_share"] == 100 and xero["mention_share"] == 33
    )
    # recommendation share: brand moderate+positive in all its mentions; Xero weak → 0
    assert brand["recommendation_share"] == 50 and qb["recommendation_share"] == 100
    assert xero["recommendation_share"] == 0
    # position
    assert brand["average_position"] == 2.0 and qb["average_position"] == 1.0
    assert xero["average_position"] == 3.0
    # citation share: brand cited when mentioned and i % 4 == 0 → 6 of 24
    assert brand["counts"]["cited_responses"] == 6 and brand["citation_share"] == 25
    assert qb["counts"]["cited_responses"] == 12 and qb["citation_share"] == 50
    assert xero["citation_share"] == 0
    # sentiment
    assert brand["sentiment_score"] == 100.0 and xero["sentiment_score"] == 50.0
    assert xero["sentiment"]["mixed"] == 8
    # prompt coverage
    assert brand["prompt_coverage"] == 3 and xero["prompt_coverage"] == 1  # only prompt 0
    # score ordering and components
    assert qb["score"] > brand["score"] > xero["score"]
    assert set(qb["components"]) == set(WEIGHTS)
    assert qb["score"] == 92  # 92.5 raw, whole points at moderate sufficiency
    # advantages: QuickBooks materially ahead, Xero behind
    adv = {a["competitor"]: a for a in body["advantages"]}
    assert adv["QuickBooks"]["material"] and adv["QuickBooks"]["advantage"] >= MATERIAL_ADVANTAGE
    assert "mention_share" in adv["QuickBooks"]["where_they_win"]
    assert adv["Xero"]["advantage"] < 0 and not adv["Xero"]["material"]
    assert body["ranking"]["available"] and body["ranking"]["order"][0] == "QuickBooks"
    assert body["ranking"]["brand_rank"] == 2
    assert body["material_advantage_threshold"] == MATERIAL_ADVANTAGE


def _score(mention: float, rec: float, pos: float, cite: float, sent: float) -> float:
    w = WEIGHTS
    return (
        w["mention_share"] * mention
        + w["recommendation_share"] * rec
        + w["position_score"] * pos
        + w["citation_share"] * cite
        + w["sentiment_score"] * sent
    ) / sum(w.values())


async def test_score_formula_matches_documented_weights(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    await _seed_market(db_session, pid, n=60)
    data = await load_observations(db_session, uuid.UUID(pid), start=None, end=None)
    rows = {r.name: r for r in compute_all(data.observations, data.competitor_names)}
    brand = rows[BRAND]
    # mention 50, rec 50, position 2 → 85 points, citation 25, sentiment 100
    assert brand.score == round(_score(50, 50, 85, 25, 100), 1)
    # never-mentioned entity: position & sentiment drop out → score 0, not None
    never = compute_all(data.observations, ["Nobody"])[1]
    assert never.score == 0.0 and never.components["position_score"] is None


# --- prompt comparison -----------------------------------------------------------------


async def test_prompt_comparison(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    await _seed_market(db_session, pid)
    r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility/prompts", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["prompts"]) == 3
    p = next(p for p in body["prompts"] if p["text"] == "best accounting tools")
    assert p["responses"] == 8 and p["sufficiency"] == "low"
    ents = {e["name"]: e for e in p["entities"]}
    assert list(ents) == [BRAND, "QuickBooks", "Xero"]
    qb = ents["QuickBooks"]
    assert qb["mentioned"] and qb["recommended"] and qb["position"] == 1.0
    assert qb["sentiment"] == "positive" and qb["recommendation_strength"] == "strong"
    assert qb["citation_count"] == 4 and qb["mentioned_in"] == 8
    brand = ents[BRAND]
    assert brand["mentioned_in"] == 4 and brand["recommended_in"] == 4 and brand["position"] == 2.0
    assert set(brand["latest"]) == {
        "mentioned",
        "recommended",
        "position",
        "sentiment",
        "citation_count",
        "recommendation_strength",
    }
    xero = ents["Xero"]
    assert xero["recommendation_strength"] == "weak" and not xero["recommended"]
    assert p["leader"]["name"] == "QuickBooks"
    # Xero is mentioned in all 8 responses of this prompt, the brand in 4
    assert p["brand_outperformed_by"] == ["QuickBooks", "Xero"]


async def test_prompt_leader_needs_minimum_sample(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(MIN_SAMPLE - 1):
        await s.observation(
            prompt="tiny", days_ago=1 + i, competitors=[("Xero", 1, "positive", "strong")]
        )
    r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility/prompts", headers=h)
    p = r.json()["prompts"][0]
    assert p["leader"]["name"] is None and "fewer than" in p["leader"]["reason"]


# --- provider comparison ---------------------------------------------------------------


async def test_provider_comparison(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # openai: brand leads; anthropic: QuickBooks leads; 20 responses each
    for i in range(20):
        await s.observation(
            provider="openai",
            prompt=f"p{i % 4}",
            days_ago=1 + i * 0.3,
            position=1,
            competitors=[("QuickBooks", 2, "neutral", "weak")],
        )
        await s.observation(
            provider="anthropic",
            prompt=f"p{i % 4}",
            days_ago=1 + i * 0.3,
            mentioned=i % 4 == 0,
            position=3 if i % 4 == 0 else None,
            strength="weak",
            competitors=[("QuickBooks", 1, "positive", "strong")],
            competitor_cited=["QuickBooks"],
        )
    r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility/engines", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    prov = {p["provider"]: p for p in body["providers"]}
    assert set(prov) == {"openai", "anthropic"}
    oa, an = prov["openai"], prov["anthropic"]
    assert oa["data_quality"]["sample_size"] == 20 and an["data_quality"]["sample_size"] == 20
    assert oa["ranking"]["order"][0] == BRAND and an["ranking"]["order"][0] == "QuickBooks"
    assert not oa["advantages"][0]["material"] and an["advantages"][0]["material"]
    spread = {x["provider"]: x for x in body["engine_spread"]}
    assert spread["openai"]["top_competitor_advantage"] < 0
    assert spread["anthropic"]["top_competitor_advantage"] >= MATERIAL_ADVANTAGE
    assert body["overall"]["data_quality"]["provider_count"] == 2
    assert body["overall"]["ranking"]["available"]


# --- historical comparison -------------------------------------------------------------


async def test_historical_comparison(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # previous 30 days: brand never mentioned; current 30 days: brand always first
    for i in range(12):
        await s.observation(
            prompt=f"q{i % 3}",
            days_ago=31 + i,
            mentioned=False,
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
        await s.observation(
            prompt=f"q{i % 3}",
            days_ago=1 + i * 2,
            position=1,
            competitors=[("QuickBooks", 5, "positive", "strong")],
        )
    engine = CompetitiveVisibilityEngine(db_session, now=NOW)
    overview = await engine.overview(uuid.UUID(pid), "30d")
    brand = next(e for e in overview["entities"] if e["is_brand"])
    assert brand["previous_score"] == 0.0 and brand["score"] > 50
    assert brand["trend"] == "up" and brand["change"] == brand["score"]
    qb = next(e for e in overview["entities"] if e["name"] == "QuickBooks")
    assert qb["trend"] == "down"  # dropped from 1st to 5th
    assert overview["previous_data_quality"]["sample_size"] == 12

    trends = await engine.trends(uuid.UUID(pid))
    w30 = trends["windows"]["30d"]
    assert w30["current_sample_size"] == 12 and w30["previous_sample_size"] == 12
    tb = next(e for e in w30["entities"] if e["is_brand"])
    assert tb["trend"] == "up" and tb["previous_mention_share"] == 0
    assert set(trends["series"]) == {BRAND, "QuickBooks", "Xero"}
    assert len(trends["series"][BRAND]) == 13  # 90 days in 7-day buckets
    assert trends["data_quality"]["sample_size"] == 24


# --- insufficient data -----------------------------------------------------------------


async def test_insufficient_data_withholds_scores_and_rankings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["data_quality"]["sample_size"] == 0
    assert body["data_quality"]["confidence"] == "insufficient"
    assert body["data_quality"]["date_range"] == {"start": None, "end": None}
    assert all(e["score"] is None for e in body["entities"])
    assert not body["ranking"]["available"] and body["ranking"]["order"] == []
    assert all(a["advantage"] is None and not a["material"] for a in body["advantages"])
    assert all(a["reason"] == "insufficient data" for a in body["advantages"])

    # a handful of responses: scores exist (coarsely rounded) but no ranking and no
    # "material" advantage, however large the gap
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(MIN_SAMPLE):
        await s.observation(
            prompt="few",
            days_ago=1 + i,
            mentioned=False,
            competitors=[("QuickBooks", 1, "positive", "strong")],
        )
    body = (await client.get(f"/api/v1/projects/{pid}/competitive-visibility", headers=h)).json()
    assert body["data_quality"]["confidence"] == "low"
    qb = next(a for a in body["advantages"] if a["competitor"] == "QuickBooks")
    assert qb["advantage"] is not None and qb["advantage"] >= MATERIAL_ADVANTAGE
    assert not qb["material"] and "sample too small" in qb["reason"]
    assert not body["ranking"]["available"]
    assert str(RANKING_MIN_SAMPLE) in body["ranking"]["reason"]
    scores = {e["name"]: e["score"] for e in body["entities"]}
    assert scores["QuickBooks"] % 5 == 0  # rounded to 5 at low sufficiency

    prompts = (
        await client.get(f"/api/v1/projects/{pid}/competitive-visibility/prompts", headers=h)
    ).json()
    assert prompts["prompts"][0]["leader"]["name"] == "QuickBooks"
    engines = (
        await client.get(f"/api/v1/projects/{pid}/competitive-visibility/engines", headers=h)
    ).json()
    assert not engines["providers"][0]["ranking"]["available"]


def test_ranking_and_advantage_helpers_on_empty() -> None:
    rows = compute_all([], ["A"])
    assert ranking(rows)["available"] is False
    assert advantages(rows)[0]["advantage"] is None


# --- authorization ---------------------------------------------------------------------


async def test_authorization(client: AsyncClient, db_session: AsyncSession) -> None:
    h, org, pid = await project_with_competitors(client)
    paths = ["", "/trends", "/prompts", "/engines"]
    for p in paths:
        assert (
            await client.get(f"/api/v1/projects/{pid}/competitive-visibility{p}")
        ).status_code == 401
    other = await signup(client, org="Other Org")
    oh = auth_header(other["access_token"])
    for p in paths:
        r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility{p}", headers=oh)
        assert r.status_code == 404, p
    viewer_id = await add_member(db_session, org, "viewer-5c@example.com", MembershipRole.VIEWER)
    vh = auth_header(create_access_token(str(viewer_id)))
    for p in paths:
        r = await client.get(f"/api/v1/projects/{pid}/competitive-visibility{p}", headers=vh)
        assert r.status_code == 200, p
    assert (
        await client.get(f"/api/v1/projects/{uuid.uuid4()}/competitive-visibility", headers=h)
    ).status_code == 404
