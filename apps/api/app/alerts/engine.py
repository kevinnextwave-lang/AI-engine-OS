"""Competitive alert detection: measure two adjacent periods, apply the pure
rules, detect novelty (new competitors, sources, claims, content gaps), and
persist with deduplication.

Dedup contract: `(project_id, dedup_key)` is unique. Re-detecting the same
situation updates the existing row's evidence and detected_at; its status is
never reset, so a dismissed alert stays dismissed and a read one stays read.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import ANALYSIS_VERSION
from app.alerts.notifications import NotificationDispatcher
from app.alerts.rules import (
    AlertDraft,
    AlertThresholds,
    PeriodMeasure,
    citation_gap_increase,
    competitor_overtakes_brand,
    competitor_visibility_jump,
    confidence_label,
    fingerprint,
    visibility_drop,
)
from app.competitive.metrics import BRAND, compute_all, entity_view
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.alerts import AlertSeverity, AlertType, CompetitiveAlert
from app.models.competitor import Competitor
from app.models.competitor_candidates import CandidateStatus, CompetitorCandidate
from app.models.content_gaps import ContentGap
from app.models.gaps import GapConfidence, GapStatus
from app.models.intelligence import ResponseCitation, ResponseClaim
from app.models.project import Project
from app.models.prompts import AiResponse, PromptRun, PromptRunStatus
from app.sources.normalize import normalize_hostname
from app.visibility.observations import ResponseObservation, load_observations

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 7


@dataclass
class AlertDetectionResult:
    project_id: uuid.UUID
    window_days: int
    current_responses: int
    previous_responses: int
    alerts_created: int
    alerts_updated: int
    detected_at: datetime
    thresholds: dict[str, Any]
    note: str


class CompetitiveAlertEngine:
    def __init__(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)
        self._dispatcher = dispatcher or NotificationDispatcher()

    async def detect(
        self,
        project_id: uuid.UUID,
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
        thresholds: AlertThresholds | None = None,
    ) -> AlertDetectionResult:
        t = thresholds or AlertThresholds()
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        cur_start = self._now - timedelta(days=window_days)
        prev_start = cur_start - timedelta(days=window_days)
        data = await load_observations(self._session, project_id, start=prev_start, end=self._now)
        previous = [o for o in data.observations if o.completed_at < cur_start]
        current = [o for o in data.observations if o.completed_at >= cur_start]
        date_range = {
            "previous": {"start": prev_start.isoformat(), "end": cur_start.isoformat()},
            "current": {"start": cur_start.isoformat(), "end": self._now.isoformat()},
            "window_days": window_days,
        }

        drafts: list[AlertDraft] = []
        prev_rows = {r.name: r for r in compute_all(previous, data.competitor_names)}
        cur_rows = {r.name: r for r in compute_all(current, data.competitor_names)}
        measures = {
            name: (
                self._measure(prev_rows[name], previous, name),
                self._measure(cur_rows[name], current, name),
            )
            for name in [BRAND, *data.competitor_names]
        }
        brand_prev, brand_cur = measures[BRAND]
        if (d := visibility_drop(brand_prev, brand_cur, date_range, t)) is not None:
            drafts.append(d)
        for name in data.competitor_names:
            comp_prev, comp_cur = measures[name]
            for rule_draft in (
                competitor_visibility_jump(name, comp_prev, comp_cur, date_range, t),
                competitor_overtakes_brand(
                    name, brand_prev, brand_cur, comp_prev, comp_cur, date_range, t
                ),
                citation_gap_increase(
                    name, brand_prev, brand_cur, comp_prev, comp_cur, date_range, t
                ),
            ):
                if rule_draft is not None:
                    drafts.append(rule_draft)

        drafts += await self._new_competitors(project_id, cur_start, t, date_range)
        drafts += await self._new_citation_sources(project_id, cur_start, t, date_range, current)
        drafts += await self._new_competitor_claims(project_id, cur_start, date_range)
        drafts += await self._content_gaps(project_id, cur_start, t, date_range)

        created, updated, new_rows = await self._persist(project_id, drafts)
        await self._session.flush()
        await self._dispatcher.dispatch(new_rows)
        log.info(
            "competitive_alerts_detected",
            project_id=str(project_id),
            current_responses=len(current),
            previous_responses=len(previous),
            created=created,
            updated=updated,
        )
        return AlertDetectionResult(
            project_id=project_id,
            window_days=window_days,
            current_responses=len(current),
            previous_responses=len(previous),
            alerts_created=created,
            alerts_updated=updated,
            detected_at=self._now,
            thresholds=t.model_dump(),
            note=(
                "Alerts require configurable thresholds and minimum samples in both "
                "periods; insignificant changes never alert. Re-detection updates "
                "existing alerts instead of duplicating them."
            ),
        )

    # -- measurements ------------------------------------------------------------------

    @staticmethod
    def _measure(row: Any, obs: list[ResponseObservation], name: str) -> PeriodMeasure:
        prompts = sorted({o.prompt_text for o in obs if entity_view(o, name).mentioned})
        # Raw shares, not the sufficiency-rounded presentation values: rounding to
        # 5-point steps on small samples could push a sub-threshold change over a
        # threshold (or hide a real one).
        n = row.sample_size
        return PeriodMeasure(
            mention_share=round(100.0 * row.mentions / n, 2) if n else None,
            score=row.score,
            citation_share=round(100.0 * row.cited_responses / n, 2) if n else None,
            sample_size=n,
            prompts=prompts[:10],
            providers=sorted({o.provider_key for o in obs}),
        )

    # -- novelty detectors -------------------------------------------------------------

    async def _new_competitors(
        self,
        project_id: uuid.UUID,
        cur_start: datetime,
        t: AlertThresholds,
        date_range: dict[str, Any],
    ) -> list[AlertDraft]:
        rows = (
            await self._session.scalars(
                select(CompetitorCandidate).where(
                    CompetitorCandidate.project_id == project_id,
                    CompetitorCandidate.discovered_at >= cur_start,
                    CompetitorCandidate.status.in_(
                        [CandidateStatus.NEW.value, CandidateStatus.REVIEWING.value]
                    ),
                    CompetitorCandidate.confidence >= t.new_competitor_min_confidence,
                )
            )
        ).all()
        out = []
        for c in rows:
            out.append(
                AlertDraft(
                    alert_type=AlertType.NEW_COMPETITOR,
                    competitor_name=None,
                    subject=c.normalized_name,
                    fingerprint=fingerprint(c.id),
                    title=f"Possible new competitor discovered: {c.name}",
                    description=(
                        f"Discovery surfaced {c.name} "
                        f"({c.confidence_label} confidence, source {c.source}) from the "
                        "analyzed AI responses. It is a candidate awaiting review, not a "
                        "confirmed competitor."
                    ),
                    severity=(
                        AlertSeverity.MEDIUM if c.confidence_label == "high" else AlertSeverity.LOW
                    ),
                    evidence={
                        "previous_measurement": None,
                        "current_measurement": {
                            "candidate_id": str(c.id),
                            "confidence": c.confidence,
                            "confidence_label": c.confidence_label,
                            "source": c.source,
                            "responses": c.evidence.get("responses"),
                        },
                        "date_range": date_range,
                        "affected_prompts": (c.evidence.get("prompts") or [])[:10],
                        "affected_providers": c.evidence.get("providers") or [],
                        "confidence": c.confidence_label,
                        "thresholds": {
                            "new_competitor_min_confidence": t.new_competitor_min_confidence
                        },
                    },
                )
            )
        return out

    async def _new_citation_sources(
        self,
        project_id: uuid.UUID,
        cur_start: datetime,
        t: AlertThresholds,
        date_range: dict[str, Any],
        current: list[ResponseObservation],
    ) -> list[AlertDraft]:
        """Domains cited for this project in the current period but never before."""
        rows = (
            await self._session.execute(
                select(ResponseCitation, PromptRun.completed_at, PromptRun.prompt_id)
                .join(AiResponse, AiResponse.id == ResponseCitation.ai_response_id)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                )
            )
        ).all()
        old_hosts: set[str] = set()
        current_hosts: dict[str, list[Any]] = {}
        for citation, completed_at, prompt_id in rows:
            host = _host_of(citation)
            if host is None or completed_at is None:
                continue
            if completed_at < cur_start:
                old_hosts.add(host)
            else:
                current_hosts.setdefault(host, []).append((citation, prompt_id))
        prompt_texts = {o.prompt_id: o.prompt_text for o in current}
        out = []
        for host, cites in sorted(current_hosts.items()):
            if host in old_hosts or len(cites) < t.new_source_min_citations:
                continue
            prompts = sorted({prompt_texts.get(pid, "") for _, pid in cites} - {""})
            out.append(
                AlertDraft(
                    alert_type=AlertType.NEW_CITATION_SOURCE,
                    competitor_name=None,
                    subject=host,
                    fingerprint="first-seen",
                    title=f"AI answers started citing a new source: {host}",
                    description=(
                        f"{host} was cited {len(cites)} times in this period and had never "
                        "been cited for this project before "
                        f"(threshold: {t.new_source_min_citations} citations)."
                    ),
                    severity=AlertSeverity.LOW,
                    evidence={
                        "previous_measurement": {"citations": 0},
                        "current_measurement": {"citations": len(cites)},
                        "date_range": date_range,
                        "affected_prompts": prompts[:10],
                        "affected_providers": sorted({o.provider_key for o in current}),
                        "confidence": confidence_label(len(current)),
                        "thresholds": {"new_source_min_citations": t.new_source_min_citations},
                        "example_urls": sorted({c.url for c, _ in cites if c.url})[:5],
                    },
                )
            )
        return out

    async def _new_competitor_claims(
        self, project_id: uuid.UUID, cur_start: datetime, date_range: dict[str, Any]
    ) -> list[AlertDraft]:
        """Claims about a configured competitor whose normalized triple was not
        seen before the current period."""
        competitors = (
            await self._session.scalars(
                select(Competitor).where(Competitor.project_id == project_id)
            )
        ).all()
        if not competitors:
            return []
        claims = (
            await self._session.execute(
                select(ResponseClaim, PromptRun.completed_at)
                .join(AiResponse, AiResponse.id == ResponseClaim.ai_response_id)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                )
            )
        ).all()

        def triple(c: ResponseClaim) -> str:
            parts = (c.subject, c.predicate, c.object)
            return "|".join(p.strip().lower() for p in parts)

        old_triples = {triple(c) for c, at in claims if at is not None and at < cur_start}
        out = []
        for competitor in competitors:
            needle = competitor.name.lower()
            new = {}
            for c, at in claims:
                if at is None or at < cur_start or needle not in c.subject.lower():
                    continue
                if triple(c) not in old_triples and triple(c) not in new:
                    new[triple(c)] = c
            if not new:
                continue
            examples = [f"{c.subject} {c.predicate} {c.object}"[:200] for c in new.values()][:5]
            out.append(
                AlertDraft(
                    alert_type=AlertType.NEW_COMPETITOR_CLAIM,
                    competitor_name=competitor.name,
                    subject=competitor.normalized_name,
                    fingerprint=fingerprint(*sorted(new)),
                    title=f"AI answers make {len(new)} new claims about {competitor.name}",
                    description=(
                        f"This period's responses contain {len(new)} claims about "
                        f"{competitor.name} that had not appeared before, e.g. "
                        f"“{examples[0]}”."
                    ),
                    severity=AlertSeverity.LOW if len(new) < 5 else AlertSeverity.MEDIUM,
                    evidence={
                        "previous_measurement": {"known_claims": len(old_triples)},
                        "current_measurement": {"new_claims": len(new)},
                        "date_range": date_range,
                        "affected_prompts": [],
                        "affected_providers": [],
                        "confidence": confidence_label(len(new) * 10),
                        "thresholds": {},
                        "claim_examples": examples,
                    },
                )
            )
        return out

    async def _content_gaps(
        self,
        project_id: uuid.UUID,
        cur_start: datetime,
        t: AlertThresholds,
        date_range: dict[str, Any],
    ) -> list[AlertDraft]:
        rows = (
            await self._session.scalars(
                select(ContentGap).where(
                    ContentGap.project_id == project_id,
                    ContentGap.status == GapStatus.NEW.value,
                    ContentGap.created_at >= cur_start,
                    ContentGap.opportunity_score >= t.content_gap_min_score,
                    ContentGap.confidence != GapConfidence.INSUFFICIENT.value,
                )
            )
        ).all()
        out = []
        for gap in rows:
            ev = gap.competitor_evidence or {}
            out.append(
                AlertDraft(
                    alert_type=AlertType.CONTENT_GAP,
                    competitor_name=None,
                    subject=f"{gap.normalized_topic}:{gap.gap_type}",
                    fingerprint=fingerprint(gap.id),
                    title=f"High-opportunity content gap: {gap.topic}",
                    description=(
                        f"A {gap.gap_type.replace('_', ' ')} gap was detected for "
                        f"“{gap.topic}” (opportunity {gap.opportunity_score:.0f}, "
                        f"threshold {t.content_gap_min_score:.0f})."
                    ),
                    severity=(
                        AlertSeverity.MEDIUM if gap.opportunity_score < 80 else AlertSeverity.HIGH
                    ),
                    evidence={
                        "previous_measurement": None,
                        "current_measurement": {
                            "content_gap_id": str(gap.id),
                            "gap_type": gap.gap_type,
                            "opportunity_score": gap.opportunity_score,
                        },
                        "date_range": date_range,
                        "affected_prompts": [ev.get("prompt")] if ev.get("prompt") else [],
                        "affected_providers": ev.get("providers") or [],
                        "confidence": gap.confidence,
                        "thresholds": {"content_gap_min_score": t.content_gap_min_score},
                    },
                )
            )
        return out

    # -- persistence -------------------------------------------------------------------

    async def _persist(
        self, project_id: uuid.UUID, drafts: list[AlertDraft]
    ) -> tuple[int, int, list[CompetitiveAlert]]:
        if not drafts:
            return 0, 0, []
        competitors = {
            c.name: c.id
            for c in (
                await self._session.scalars(
                    select(Competitor).where(Competitor.project_id == project_id)
                )
            ).all()
        }
        existing = {
            row.dedup_key: row
            for row in (
                await self._session.scalars(
                    select(CompetitiveAlert).where(CompetitiveAlert.project_id == project_id)
                )
            ).all()
        }
        created = updated = 0
        new_rows: list[CompetitiveAlert] = []
        for draft in drafts:
            row = existing.get(draft.dedup_key)
            if row is None:
                row = CompetitiveAlert(
                    project_id=project_id,
                    alert_type=draft.alert_type.value,
                    dedup_key=draft.dedup_key,
                )
                self._session.add(row)
                existing[draft.dedup_key] = row
                new_rows.append(row)
                created += 1
            else:
                updated += 1  # evidence refreshed; status untouched (dismissed stays dismissed)
            row.competitor_id = (
                competitors.get(draft.competitor_name) if draft.competitor_name else None
            )
            row.title = draft.title
            row.description = draft.description
            row.evidence = draft.evidence
            row.severity = draft.severity.value
            row.detected_at = self._now
            row.analysis_version = ANALYSIS_VERSION
        return created, updated, new_rows


def _host_of(citation: ResponseCitation) -> str | None:
    if citation.domain:
        return normalize_hostname(citation.domain)
    if citation.url:
        from urllib.parse import urlsplit

        return normalize_hostname(urlsplit(citation.url).hostname)
    return None
