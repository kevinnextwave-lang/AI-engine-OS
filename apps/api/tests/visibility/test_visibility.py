"""AI Visibility Score: metrics, sufficiency, trends, breakdowns, tenancy."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import MembershipRole
from app.models.prompts import FunnelStage, PromptCategory
from app.visibility import METHOD
from app.visibility.engine import VisibilityEngine, compare
from app.visibility.metrics import (
    MIN_SAMPLE,
    POSITION_POINTS,
    WEIGHTS,
    compute,
    position_points,
    round_for,
    sufficiency_for,
)
from app.visibility.observations import load_observations
from tests.conftest import auth_header
from tests.test_authz import add_member, signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

# --- pure metric helpers -----------------------------------------------------


def test_position_points_heuristic() -> None:
    assert [position_points(p) for p in range(1, 8)] == [100, 85, 70, 55, 40, 25, 25]
    assert POSITION_POINTS[1] == 100


def test_sufficiency_and_rounding_never_overstate_precision() -> None:
    assert (
        sufficiency_for(0) == "insufficient" and sufficiency_for(MIN_SAMPLE - 1) == "insufficient"
    )
    assert sufficiency_for(5) == "low" and sufficiency_for(20) == "moderate"
    assert sufficiency_for(50) == "high"
    assert round_for(3, 63.7) is None  # withheld, never a silent zero
    assert round_for(8, 63.7) == 65.0  # nearest 5
    assert round_for(25, 63.7) == 64.0  # integer
    assert round_for(80, 63.74) == 63.7  # one decimal


def test_weights_match_methodology() -> None:
    assert WEIGHTS == {
        "mention_rate": 25,
        "recommendation_rate": 25,
        "position_score": 15,
        "citation_rate": 15,
        "sentiment_score": 10,
        "competitive_score": 10,
    }


# --- metrics over seeded observations ----------------------------------------


async def _metrics(session: AsyncSession, pid: str):  # type: ignore[no-untyped-def]
    data = await load_observations(session, uuid.UUID(pid), start=None, end=None)
    return compute(data.observations, data.competitor_names), data


async def test_mention_and_recommendation_rates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # 20 responses: 12 mention, of which 8 strong/positive, 2 weak, 2 strong-but-negative
    for i in range(8):
        await s.observation(prompt=f"p{i}", strength="strong")
    for i in range(2):
        await s.observation(prompt=f"w{i}", strength="weak")
    for i in range(2):
        await s.observation(prompt=f"n{i}", strength="strong", sentiment="negative")
    for i in range(8):
        await s.observation(prompt=f"x{i}", mentioned=False)

    m, _ = await _metrics(db_session, pid)
    assert m.sample_size == 20 and m.sufficiency == "moderate"
    assert m.mention_rate == 60.0  # 12/20
    assert m.recommendation_rate == 40.0  # 8/20 (weak and negative excluded)
    assert m.prompts == 20 and m.providers == ["openai"]
    assert m.parser_versions == ["response-parser/v1"]


async def test_average_position_and_position_score_skip_unknown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i, pos in enumerate([1, 3, None, None, 6]):
        await s.observation(prompt=f"p{i}", position=pos)
    m, _ = await _metrics(db_session, pid)
    assert m.average_position == 3.33  # mean of 1, 3, 6
    comp = {c.key: c for c in m.components}
    assert comp["position_score"].sample == 3  # unknown positions excluded
    # (100 + 70 + 25) / 3 = 65, low sample → nearest 5
    assert comp["position_score"].value == 65.0


async def test_position_unavailable_when_no_positions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(6):
        await s.observation(prompt=f"p{i}", position=None)
    m, _ = await _metrics(db_session, pid)
    comp = {c.key: c for c in m.components}
    assert m.average_position is None and comp["position_score"].value is None
    # the score still exists, renormalized over the available components
    assert m.score is not None


async def test_citation_rate_counts_only_project_domains(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(5):
        await s.observation(prompt=f"c{i}", cited=True)
    for i in range(5):
        await s.observation(prompt=f"u{i}", cited=False)
    # a citation to somebody else's domain must not count
    run = await s.observation(prompt="other", cited=False)
    from sqlalchemy import select

    from app.models.intelligence import ResponseCitation
    from app.models.prompts import AiResponse

    resp = (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).one()
    db_session.add(
        ResponseCitation(
            ai_response_id=resp.id,
            project_id=uuid.UUID(pid),
            url="https://www.xero.com/blog",
            domain="www.xero.com",
            parser_version="response-parser/v1",
        )
    )
    await db_session.flush()
    m, data = await _metrics(db_session, pid)
    assert data.brand_domains == ["ledgerly.example"]
    assert m.sample_size == 11 and m.citation_rate == 45.0  # 5/11 = 45.45 → nearest 5


async def test_sentiment_aggregate(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i, sent in enumerate(["positive", "positive", "neutral", "negative", "unknown"]):
        await s.observation(prompt=f"p{i}", sentiment=sent)
    m, _ = await _metrics(db_session, pid)
    assert m.sentiment == {"positive": 2, "neutral": 1, "negative": 1, "mixed": 0, "unknown": 1}
    comp = {c.key: c for c in m.components}
    assert comp["sentiment_score"].sample == 4  # unknown excluded
    # (100+100+50+0)/4 = 62.5 → low sample → 60 or 65 (banker's rounding of 12.5 → 12 → 60)
    assert comp["sentiment_score"].value in (60.0, 65.0)


async def test_competitor_comparison(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # brand mentioned 3/6; QuickBooks 6/6; Xero 1/6; unconfigured "FreshBooks" 6/6
    for i in range(6):
        await s.observation(
            prompt=f"p{i}",
            mentioned=i < 3,
            position=2 if i < 3 else None,
            competitors=[
                ("QuickBooks", 1, "positive", "strong"),
                ("FreshBooks", 3, "positive", "strong"),
            ]
            + ([("Xero", 4, "neutral", "weak")] if i == 0 else []),
        )
    m, data = await _metrics(db_session, pid)
    comp = {c.key: c for c in m.components}
    assert comp["competitive_score"].value == 50.0  # 3/6 vs 6/6 → 50
    from app.visibility.metrics import competitor_table

    rows = {r["name"]: r for r in competitor_table(data)}
    assert set(rows) == {"brand", "QuickBooks", "Xero"}  # FreshBooks is not configured
    assert rows["brand"]["mentions"] == 3 and rows["QuickBooks"]["mentions"] == 6
    assert rows["Xero"]["mentions"] == 1 and rows["Xero"]["share_of_voice"] == 10.0
    assert (
        rows["QuickBooks"]["average_position"] == 1.0 and rows["brand"]["average_position"] == 2.0
    )


async def test_competitive_score_not_penalized_without_configured_competitors(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, pid = await project_with_competitors(client, competitors=())
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(6):
        await s.observation(
            prompt=f"p{i}",
            position=1,
            cited=True,
            competitors=[("FreshBooks", 1, "positive", "strong")],
        )
    m, _ = await _metrics(db_session, pid)
    comp = {c.key: c for c in m.components}
    assert comp["competitive_score"].value is None
    assert "no competitors configured" in comp["competitive_score"].note
    # all other components are 100 → score is 100, unaffected by the missing component
    assert m.score == 100.0


async def test_insufficient_data_withholds_score_but_reports_counts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for i in range(MIN_SAMPLE - 1):
        await s.observation(prompt=f"p{i}")
    await s.observation(prompt="unparsed", parsed=False)  # never counted
    await db_session.commit()

    body = (await client.get(f"/api/v1/projects/{pid}/visibility", headers=h)).json()
    cur = body["current"]
    assert cur["score"] is None and cur["mention_rate"] is None
    assert cur["data_quality"]["sample_size"] == MIN_SAMPLE - 1
    assert cur["data_quality"]["sufficiency"] == "insufficient"
    assert cur["data_quality"]["minimum_sample"] == MIN_SAMPLE
    assert cur["sentiment"]["positive"] == MIN_SAMPLE - 1  # raw counts are still visible
    assert all(c["value"] is None for c in cur["components"])
    assert body["trend"] == "unavailable" and body["change"] is None and body["reason"]


async def test_empty_project_is_unavailable_not_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    body = (await client.get(f"/api/v1/projects/{pid}/visibility", headers=h)).json()
    assert body["current"]["score"] is None
    assert body["current"]["data_quality"] == {
        "sample_size": 0,
        "sufficiency": "insufficient",
        "providers": 0,
        "provider_keys": [],
        "models": 0,
        "prompts": 0,
        "date_range": {"start": None, "end": None},
        "parser_versions": [],
        "minimum_sample": MIN_SAMPLE,
    }


# --- time dimension -----------------------------------------------------------


def test_compare_trend_labels() -> None:
    from app.visibility.metrics import VisibilityMetrics

    def m(score: float | None) -> VisibilityMetrics:
        return VisibilityMetrics(
            sample_size=10,
            score=score,
            components=[],
            mention_rate=None,
            recommendation_rate=None,
            average_position=None,
            citation_rate=None,
            sentiment={},
            sufficiency="low",
            providers=[],
            models=[],
            prompts=0,
            date_range={"start": None, "end": None},
            parser_versions=[],
        )

    assert compare(m(70), m(60)) == {"change": 10.0, "trend": "up", "reason": None}
    assert compare(m(60), m(70))["trend"] == "down"
    assert compare(m(61), m(60))["trend"] == "flat"
    assert compare(m(None), m(60))["trend"] == "unavailable"
    assert compare(m(60), m(None))["reason"] == "insufficient data in the previous period"


async def test_historical_trends(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # last 7 days: 6 responses all mentioned; 8–14 days ago: 6 responses none mentioned
    for i in range(6):
        await s.observation(prompt=f"now{i}", days_ago=1 + i * 0.5, position=1, cited=True)
    for i in range(6):
        await s.observation(prompt=f"old{i}", days_ago=8 + i * 0.5, mentioned=False)
    # 40 days ago: 2 responses (insufficient on its own)
    for i in range(2):
        await s.observation(prompt=f"far{i}", days_ago=40)
    await db_session.commit()

    engine = VisibilityEngine(db_session, now=NOW)
    week = await engine.overview(uuid.UUID(pid), "7d")
    assert week["current"]["data_quality"]["sample_size"] == 6
    assert week["previous"]["data_quality"]["sample_size"] == 6
    assert week["current"]["score"] == 100.0 and week["previous"]["score"] == 0.0
    assert week["trend"] == "up" and week["change"] == 100.0

    month = await engine.overview(uuid.UUID(pid), "30d")
    assert month["current"]["data_quality"]["sample_size"] == 12
    assert month["previous"]["data_quality"]["sample_size"] == 2
    assert month["previous"]["score"] is None and month["trend"] == "unavailable"

    trends = await engine.trends(uuid.UUID(pid))
    assert set(trends["windows"]) == {"7d", "30d", "90d"}
    assert trends["windows"]["7d"]["trend"] == "up"
    assert trends["windows"]["90d"]["current_sample_size"] == 14
    assert trends["windows"]["90d"]["previous_sample_size"] == 0
    assert trends["windows"]["90d"]["trend"] == "unavailable"
    series = trends["series"]
    assert len(series) == 13  # 90 days in 7-day buckets (last one partial)
    assert sum(p["sample_size"] for p in series) == 14
    assert series[-1]["sample_size"] == 6 and series[-1]["score"] == 100.0
    assert series[-2]["sample_size"] == 6 and series[-2]["score"] == 0.0

    # API mirrors the engine (with the real clock the seeded data is still "recent")
    r = await client.get(f"/api/v1/projects/{pid}/visibility/trends", headers=h)
    assert r.status_code == 200 and r.json()["method"] == METHOD
    r = await client.get(f"/api/v1/projects/{pid}/visibility", params={"window": "1d"}, headers=h)
    assert r.status_code == 422


# --- breakdowns ---------------------------------------------------------------


async def test_breakdown_by_engine_and_prompt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    for _i in range(6):
        await s.observation(
            prompt="best accounting tools",
            provider="openai",
            model="gpt-4o-mini",
            mentioned=True,
            category=PromptCategory.RECOMMENDATION,
            funnel_stage=FunnelStage.DECISION,
        )
    for _i in range(6):
        await s.observation(
            prompt="ledgerly pricing",
            provider="google",
            model="gemini-2.0-flash",
            mentioned=False,
            category=PromptCategory.PRICING,
            funnel_stage=FunnelStage.PURCHASE,
        )
    await db_session.commit()

    eng = (await client.get(f"/api/v1/projects/{pid}/visibility/by-engine", headers=h)).json()
    assert eng["overall"]["data_quality"]["sample_size"] == 12
    assert eng["overall"]["data_quality"]["providers"] == 2
    by_provider = {p["provider"]: p for p in eng["providers"]}
    assert by_provider["openai"]["mention_rate"] == 100.0
    assert by_provider["google"]["mention_rate"] == 0.0
    assert {(m["provider"], m["model"]) for m in eng["models"]} == {
        ("openai", "gpt-4o-mini"),
        ("google", "gemini-2.0-flash"),
    }

    bp = (await client.get(f"/api/v1/projects/{pid}/visibility/by-prompt", headers=h)).json()
    prompts = {p["text"]: p for p in bp["prompts"]}
    assert prompts["best accounting tools"]["mentions"] == 6
    assert prompts["best accounting tools"]["sufficiency"] == "low"
    assert prompts["ledgerly pricing"]["mention_rate"] == 0.0
    assert {c["category"]: c["mention_rate"] for c in bp["categories"]} == {
        "recommendation": 100.0,
        "pricing": 0.0,
    }
    assert {f["funnel_stage"] for f in bp["funnel_stages"]} == {"decision", "purchase"}

    comp = (await client.get(f"/api/v1/projects/{pid}/visibility/competitors", headers=h)).json()
    assert comp["competitors_configured"] == 2
    assert [r["name"] for r in comp["rows"]] == ["brand", "QuickBooks", "Xero"]
    assert comp["rows"][0]["is_brand"] and comp["rows"][0]["mentions"] == 6
    assert comp["competitive_score"] == 100.0  # nobody else mentioned → brand leads


# --- multi-tenant authorization ------------------------------------------------


@pytest.mark.parametrize("path", ["", "/trends", "/by-engine", "/by-prompt", "/competitors"])
async def test_visibility_requires_membership(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    h, org, pid = await project_with_competitors(client)
    # a user from another org sees 404, not 403
    other = await signup(client, org="Other Org")
    r = await client.get(
        f"/api/v1/projects/{pid}/visibility{path}", headers=auth_header(other["access_token"])
    )
    assert r.status_code == 404
    # unauthenticated
    assert (await client.get(f"/api/v1/projects/{pid}/visibility{path}")).status_code == 401
    # viewer in the same org may read
    viewer_id = await add_member(db_session, org, "viewer-vis@example.com", MembershipRole.VIEWER)
    await db_session.commit()
    r = await client.get(
        f"/api/v1/projects/{pid}/visibility{path}",
        headers=auth_header(create_access_token(str(viewer_id))),
    )
    assert r.status_code == 200
    assert (
        await client.get(f"/api/v1/projects/{pid}/visibility{path}", headers=h)
    ).status_code == 200


async def test_observations_never_cross_projects(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid_a = await project_with_competitors(client)
    owner_b = await signup(client, org="B Org")
    from tests.test_projects_api import create_project

    pid_b = (
        await create_project(
            client,
            auth_header(owner_b["access_token"]),
            name="Brand B",
            website_url="https://b.example",
        )
    )["id"]
    sb = Seeder(db_session, uuid.UUID(pid_b))
    for i in range(8):
        await sb.observation(prompt=f"b{i}")
    await db_session.commit()
    body = (await client.get(f"/api/v1/projects/{pid_a}/visibility", headers=h)).json()
    assert body["current"]["data_quality"]["sample_size"] == 0
