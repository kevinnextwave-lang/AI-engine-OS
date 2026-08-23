"""Milestone 5F — Competitive AI Alerts."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.engine import CompetitiveAlertEngine
from app.alerts.rules import AlertThresholds, PeriodMeasure, escalate, visibility_drop
from app.models.alerts import AlertSeverity, CompetitiveAlert
from app.models.competitor_candidates import CandidateSource, CandidateStatus, CompetitorCandidate
from app.models.content_gaps import ContentGap
from app.models.intelligence import ResponseCitation, ResponseClaim
from app.models.prompts import AiResponse
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, PV, Seeder, project_with_competitors

pytestmark = pytest.mark.anyio

WINDOW = 7  # detection window in days: current = days 0-7, previous = days 7-14


async def _seed_period(
    s: Seeder,
    *,
    previous: bool,
    n: int = 12,
    brand_every: int = 1,
    brand_position: int = 1,
    brand_strength: str = "strong",
    comp_every: int = 1,
    comp_position: int = 1,
    comp_strength: str = "strong",
    brand_cited_every: int = 0,
    comp_cited_every: int = 0,
) -> list[uuid.UUID]:
    """n responses in one period. *_every: 0 = never, k = every k-th response."""
    base = 8 if previous else 1
    runs = []
    for i in range(n):
        mentioned = brand_every > 0 and i % brand_every == 0
        comps = []
        if comp_every > 0 and i % comp_every == 0:
            comps.append(("QuickBooks", comp_position, "positive", comp_strength))
        run = await s.observation(
            prompt=f"alert prompt {i % 3}",
            provider="openai" if i % 2 == 0 else "google",
            days_ago=base + (i % 6) * 0.9,
            mentioned=mentioned,
            position=brand_position if mentioned else None,
            strength=brand_strength if mentioned else "unknown",
            cited=mentioned and brand_cited_every > 0 and i % brand_cited_every == 0,
            competitors=comps,
            competitor_cited=(
                ["QuickBooks"] if comp_cited_every > 0 and i % comp_cited_every == 0 else []
            ),
        )
        runs.append(run.id)
    return runs


async def _swing(s: Seeder) -> None:
    """Previous: brand dominant, QuickBooks minor. Current: roles reversed."""
    await _seed_period(s, previous=True, comp_every=3, comp_position=2, comp_strength="moderate")
    await _seed_period(
        s,
        previous=False,
        brand_every=6,
        brand_position=3,
        brand_strength="weak",
    )


# --- threshold detection ---------------------------------------------------------------


async def test_threshold_detection(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _swing(s)
    r = await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_responses"] == 12 and body["previous_responses"] == 12
    assert body["alerts_created"] >= 3
    assert body["thresholds"]["brand_drop_points"] == 10.0  # defaults echoed
    items = (await client.get(f"/api/v1/projects/{pid}/competitive-alerts", headers=h)).json()[
        "items"
    ]
    by_type = {a["alert_type"]: a for a in items}
    drop = by_type["visibility_drop"]
    assert drop["severity"] == "critical"  # 100 → 17, far past 2× threshold
    ev = drop["evidence"]
    assert ev["previous_measurement"]["mention_share"] == 100
    assert ev["current_measurement"]["mention_share"] < 30
    assert ev["date_range"]["current"]["end"] > ev["date_range"]["previous"]["start"]
    assert ev["affected_prompts"] and ev["affected_providers"] == ["google", "openai"]
    assert ev["confidence"] == "low"  # 12 responses per period
    assert ev["thresholds"]["brand_drop_points"] == 10.0

    jump = by_type["competitor_visibility_jump"]
    assert jump["competitor_id"] is not None
    assert jump["evidence"]["change_points"] >= 15

    overtake = by_type["competitor_overtakes_brand"]
    assert overtake["evidence"]["margin_points"] > 0
    assert overtake["evidence"]["competitor_current_score"] > 0


async def test_custom_thresholds(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _swing(s)
    # raise thresholds far above the observed change → nothing fires
    r = await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={
            "window_days": WINDOW,
            "thresholds": {
                "brand_drop_points": 95,
                "competitor_jump_points": 95,
                "overtake_margin_points": 99,
                "citation_gap_increase_points": 99,
            },
        },
        headers=h,
    )
    assert r.json()["alerts_created"] == 0
    # a stricter minimum sample also suppresses everything
    r = await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW, "thresholds": {"min_responses": 20}},
        headers=h,
    )
    assert r.json()["alerts_created"] == 0


async def test_citation_gap_increase(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # previous: brand cited half the time, competitor never; current: reversed
    await _seed_period(s, previous=True, brand_cited_every=2, comp_every=1)
    await _seed_period(s, previous=False, brand_cited_every=0, comp_cited_every=2)
    result = await CompetitiveAlertEngine(db_session, now=NOW).detect(
        uuid.UUID(pid), window_days=WINDOW
    )
    assert result.alerts_created >= 1
    rows = (
        await db_session.scalars(
            select(CompetitiveAlert).where(
                CompetitiveAlert.project_id == uuid.UUID(pid),
                CompetitiveAlert.alert_type == "citation_gap_increase",
            )
        )
    ).all()
    assert len(rows) == 1
    ev = rows[0].evidence
    assert ev["previous_gap_points"] < 0 < ev["current_gap_points"]


# --- false-positive prevention ---------------------------------------------------------


async def test_no_alert_on_insignificant_change(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # brand 100% → 92% (12 → 11 of 12): below the 10-point threshold
    await _seed_period(s, previous=True)
    await _seed_period(s, previous=False, brand_every=1)
    # drop exactly one mention in the current period
    obs_run = await s.observation(prompt="alert prompt 0", days_ago=1.5, mentioned=False)
    assert obs_run is not None
    r = await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW},
        headers=h,
    )
    assert r.json()["alerts_created"] == 0


async def test_no_alert_on_tiny_sample(client: AsyncClient, db_session: AsyncSession) -> None:
    """A huge swing on 4 responses per period must not alert (min_responses=10)."""
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_period(s, previous=True, n=4)
    await _seed_period(s, previous=False, n=4, brand_every=0)
    r = await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW},
        headers=h,
    )
    assert r.json()["alerts_created"] == 0
    assert (await client.get(f"/api/v1/projects/{pid}/competitive-alerts", headers=h)).json()[
        "total"
    ] == 0


def test_escalation_and_rule_gates() -> None:
    assert escalate(AlertSeverity.HIGH, 25.0, 10.0) is AlertSeverity.CRITICAL
    assert escalate(AlertSeverity.HIGH, 15.0, 10.0) is AlertSeverity.HIGH
    t = AlertThresholds()
    prev = PeriodMeasure(mention_share=80.0, score=None, citation_share=None, sample_size=12)
    cur = PeriodMeasure(mention_share=75.0, score=None, citation_share=None, sample_size=12)
    assert visibility_drop(prev, cur, {}, t) is None  # 5 points < 10
    cur_big = PeriodMeasure(mention_share=50.0, score=None, citation_share=None, sample_size=12)
    draft = visibility_drop(prev, cur_big, {}, t)
    assert draft is not None and draft.severity is AlertSeverity.CRITICAL  # 30 ≥ 2×10


# --- novelty alerts --------------------------------------------------------------------


async def test_novelty_alerts(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    prev_runs = await _seed_period(s, previous=True)
    cur_runs = await _seed_period(s, previous=False)  # stable visibility: no change alerts

    async def resp_for(run_id: uuid.UUID) -> AiResponse:
        return (
            await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run_id))
        ).one()

    # new citation source: cited twice, only in the current period
    for run_id in cur_runs[:2]:
        db_session.add(
            ResponseCitation(
                ai_response_id=(await resp_for(run_id)).id,
                project_id=s.project_id,
                url="https://newsource.example/accounting-roundup",
                domain="newsource.example",
                citation_type="explicit_url",
                parser_version=PV,
            )
        )
    # old source cited in both periods → no alert for it
    for run_id in (prev_runs[0], cur_runs[3]):
        db_session.add(
            ResponseCitation(
                ai_response_id=(await resp_for(run_id)).id,
                project_id=s.project_id,
                url="https://www.g2.com/products/quickbooks",
                domain="www.g2.com",
                citation_type="explicit_url",
                parser_version=PV,
            )
        )
    # a claim about QuickBooks that existed before, and a genuinely new one
    db_session.add(
        ResponseClaim(
            ai_response_id=(await resp_for(prev_runs[0])).id,
            project_id=s.project_id,
            subject="QuickBooks",
            predicate="offers",
            object="a payroll add-on",
            confidence=0.7,
            context="",
            parser_version=PV,
        )
    )
    for run_id in (cur_runs[0], cur_runs[1]):
        db_session.add(
            ResponseClaim(
                ai_response_id=(await resp_for(run_id)).id,
                project_id=s.project_id,
                subject="QuickBooks",
                predicate="offers" if run_id == cur_runs[0] else "launches",
                object="a payroll add-on" if run_id == cur_runs[0] else "an AI bookkeeping agent",
                confidence=0.7,
                context="",
                parser_version=PV,
            )
        )
    # discovery candidate found this period
    db_session.add(
        CompetitorCandidate(
            project_id=s.project_id,
            name="Wave",
            normalized_name="wave",
            reason="seen in responses",
            evidence={"responses": 4, "prompts": ["alert prompt 0"], "providers": ["openai"]},
            confidence=0.72,
            confidence_label="high",
            source=CandidateSource.AI_RESPONSES.value,
            status=CandidateStatus.NEW.value,
            discovery_version="competitor-discovery/v1",
            discovered_at=NOW - timedelta(days=2),
        )
    )
    # high-opportunity content gap created now (created_at defaults to now())
    db_session.add(
        ContentGap(
            project_id=s.project_id,
            topic="construction accounting",
            normalized_topic="accounting construction",
            gap_type="missing_topic",
            competitor_evidence={"prompt": "best construction accounting", "providers": ["openai"]},
            customer_coverage={},
            opportunity_score=82.0,
            confidence="medium",
            analysis_version="content-gaps/v1",
            window_days=90,
            analyzed_at=NOW,
        )
    )
    await db_session.flush()
    result = await CompetitiveAlertEngine(db_session, now=NOW).detect(
        uuid.UUID(pid), window_days=WINDOW
    )
    rows = (
        await db_session.scalars(
            select(CompetitiveAlert).where(CompetitiveAlert.project_id == uuid.UUID(pid))
        )
    ).all()
    by_type = {r.alert_type: r for r in rows}
    assert set(by_type) == {
        "new_citation_source",
        "new_competitor_claim",
        "new_competitor",
        "content_gap",
    }, result
    source = by_type["new_citation_source"]
    assert "newsource.example" in source.title
    assert source.evidence["current_measurement"]["citations"] == 2
    claim = by_type["new_competitor_claim"]
    assert claim.evidence["current_measurement"]["new_claims"] == 1  # the launches claim only
    assert "AI bookkeeping agent" in claim.evidence["claim_examples"][0]
    assert by_type["new_competitor"].evidence["current_measurement"]["confidence_label"] == "high"
    gap_alert = by_type["content_gap"]
    assert gap_alert.severity == "high" and "construction accounting" in gap_alert.title


# --- deduplication ---------------------------------------------------------------------


async def test_alert_deduplication(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _swing(s)
    engine = CompetitiveAlertEngine(db_session, now=NOW)
    first = await engine.detect(uuid.UUID(pid), window_days=WINDOW)
    assert first.alerts_created >= 3 and first.alerts_updated == 0
    second = await engine.detect(uuid.UUID(pid), window_days=WINDOW)
    assert second.alerts_created == 0 and second.alerts_updated == first.alerts_created
    rows = (
        await db_session.scalars(
            select(CompetitiveAlert).where(CompetitiveAlert.project_id == uuid.UUID(pid))
        )
    ).all()
    assert len(rows) == first.alerts_created

    # dismissed stays dismissed through re-detection
    rows[0].status = "dismissed"
    await db_session.flush()
    await engine.detect(uuid.UUID(pid), window_days=WINDOW)
    await db_session.refresh(rows[0])
    assert rows[0].status == "dismissed"


# --- status changes --------------------------------------------------------------------


async def test_status_changes(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _swing(s)
    await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW},
        headers=h,
    )
    listing = (await client.get(f"/api/v1/projects/{pid}/competitive-alerts", headers=h)).json()
    assert listing["unread"] == listing["total"] >= 3
    alert_id = listing["items"][0]["id"]
    r = await client.patch(
        f"/api/v1/competitive-alerts/{alert_id}", json={"status": "read"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "read"
    r = await client.patch(
        f"/api/v1/competitive-alerts/{alert_id}", json={"status": "dismissed"}, headers=h
    )
    assert r.json()["status"] == "dismissed"
    listing = (
        await client.get(
            f"/api/v1/projects/{pid}/competitive-alerts", params={"status": "new"}, headers=h
        )
    ).json()
    assert all(a["status"] == "new" for a in listing["items"])
    assert listing["unread"] == listing["total"]
    assert (
        await client.patch(
            f"/api/v1/competitive-alerts/{alert_id}", json={"status": "bogus"}, headers=h
        )
    ).status_code == 422


# --- tenant isolation ------------------------------------------------------------------


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _swing(s)
    await client.post(
        f"/api/v1/projects/{pid}/competitive-alerts/detect",
        json={"window_days": WINDOW},
        headers=h,
    )
    alert_id = (await client.get(f"/api/v1/projects/{pid}/competitive-alerts", headers=h)).json()[
        "items"
    ][0]["id"]

    other = await signup(client, org="Other Alert Org")
    oh = auth_header(other["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/competitive-alerts", headers=oh)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/competitive-alerts/detect", json={}, headers=oh)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/competitive-alerts/{alert_id}", headers=oh)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/competitive-alerts/{alert_id}", json={"status": "read"}, headers=oh
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/competitive-alerts")).status_code == 401
