"""Pure alert rules: period measurements in, candidate alerts out.

Every rule enforces its threshold (all configurable via `AlertThresholds`) and
a minimum sample in BOTH periods, so insignificant changes and thin data never
alert. Severity escalates with how far past the threshold the change is:
≥ 1× threshold → the rule's base severity, ≥ 2× → one level higher.

Evidence on every alert: previous measurement, current measurement, both date
ranges, affected prompts and providers, sample sizes, the thresholds used and
a confidence label derived from the sample.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.models.alerts import AlertSeverity, AlertType


class AlertThresholds(BaseModel):
    """Configurable detection thresholds. Defaults are deliberately conservative."""

    brand_drop_points: float = Field(default=10.0, ge=1, le=100)
    competitor_jump_points: float = Field(default=15.0, ge=1, le=100)
    overtake_margin_points: float = Field(default=5.0, ge=0, le=100)
    citation_gap_increase_points: float = Field(default=15.0, ge=1, le=100)
    min_responses: int = Field(default=10, ge=1, description="per period, for rate-based alerts")
    new_source_min_citations: int = Field(default=2, ge=1)
    new_competitor_min_confidence: float = Field(default=0.4, ge=0, le=1)
    content_gap_min_score: float = Field(default=60.0, ge=0, le=100)


@dataclass
class PeriodMeasure:
    """One entity's measurements in one period."""

    mention_share: float | None
    score: float | None
    citation_share: float | None
    sample_size: int
    prompts: list[str] = field(default_factory=list)  # prompts where the entity appeared
    providers: list[str] = field(default_factory=list)


@dataclass
class AlertDraft:
    alert_type: AlertType
    competitor_name: str | None
    subject: str  # dedup subject (competitor name, domain, topic…)
    fingerprint: str  # change fingerprint; same situation → same fingerprint
    title: str
    description: str
    severity: AlertSeverity
    evidence: dict[str, Any]

    @property
    def dedup_key(self) -> str:
        return f"{self.alert_type.value}:{self.subject}:{self.fingerprint}"[:400]


_SEVERITY_UP = {
    AlertSeverity.LOW: AlertSeverity.MEDIUM,
    AlertSeverity.MEDIUM: AlertSeverity.HIGH,
    AlertSeverity.HIGH: AlertSeverity.CRITICAL,
    AlertSeverity.CRITICAL: AlertSeverity.CRITICAL,
}


def escalate(base: AlertSeverity, magnitude: float, threshold: float) -> AlertSeverity:
    return _SEVERITY_UP[base] if threshold > 0 and magnitude >= 2 * threshold else base


def confidence_label(*samples: int) -> str:
    smallest = min(samples) if samples else 0
    if smallest >= 50:
        return "high"
    if smallest >= 20:
        return "medium"
    return "low"


def fingerprint(*parts: object) -> str:
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:12]


def change_evidence(
    previous: PeriodMeasure,
    current: PeriodMeasure,
    date_range: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    return {
        "previous_measurement": {
            "mention_share": previous.mention_share,
            "score": previous.score,
            "citation_share": previous.citation_share,
            "sample_size": previous.sample_size,
        },
        "current_measurement": {
            "mention_share": current.mention_share,
            "score": current.score,
            "citation_share": current.citation_share,
            "sample_size": current.sample_size,
        },
        "date_range": date_range,
        "affected_prompts": sorted(set(previous.prompts) | set(current.prompts))[:10],
        "affected_providers": sorted(set(previous.providers) | set(current.providers)),
        "confidence": confidence_label(previous.sample_size, current.sample_size),
        "thresholds": thresholds,
    }


def _enough(previous: PeriodMeasure, current: PeriodMeasure, minimum: int) -> bool:
    return previous.sample_size >= minimum and current.sample_size >= minimum


def visibility_drop(
    brand_prev: PeriodMeasure,
    brand_cur: PeriodMeasure,
    date_range: dict[str, Any],
    t: AlertThresholds,
) -> AlertDraft | None:
    if not _enough(brand_prev, brand_cur, t.min_responses):
        return None
    if brand_prev.mention_share is None or brand_cur.mention_share is None:
        return None
    drop = brand_prev.mention_share - brand_cur.mention_share
    if drop < t.brand_drop_points:
        return None
    return AlertDraft(
        alert_type=AlertType.VISIBILITY_DROP,
        competitor_name=None,
        subject="brand",
        fingerprint=fingerprint(round(brand_prev.mention_share), round(brand_cur.mention_share)),
        title=f"Brand visibility fell {drop:.0f} points",
        description=(
            f"The brand was mentioned in {brand_cur.mention_share:.0f}% of eligible AI "
            f"responses this period, down from {brand_prev.mention_share:.0f}% in the "
            f"previous period (threshold: {t.brand_drop_points:.0f} points)."
        ),
        severity=escalate(AlertSeverity.HIGH, drop, t.brand_drop_points),
        evidence={
            **change_evidence(
                brand_prev,
                brand_cur,
                date_range,
                {"brand_drop_points": t.brand_drop_points, "min_responses": t.min_responses},
            ),
            "change_points": round(-drop, 1),
        },
    )


def competitor_visibility_jump(
    name: str,
    prev: PeriodMeasure,
    cur: PeriodMeasure,
    date_range: dict[str, Any],
    t: AlertThresholds,
) -> AlertDraft | None:
    if not _enough(prev, cur, t.min_responses):
        return None
    if prev.mention_share is None or cur.mention_share is None:
        return None
    jump = cur.mention_share - prev.mention_share
    if jump < t.competitor_jump_points:
        return None
    return AlertDraft(
        alert_type=AlertType.COMPETITOR_VISIBILITY_JUMP,
        competitor_name=name,
        subject=name,
        fingerprint=fingerprint(round(prev.mention_share), round(cur.mention_share)),
        title=f"{name} visibility jumped {jump:.0f} points",
        description=(
            f"{name} was mentioned in {cur.mention_share:.0f}% of eligible AI responses "
            f"this period, up from {prev.mention_share:.0f}% in the previous period "
            f"(threshold: {t.competitor_jump_points:.0f} points)."
        ),
        severity=escalate(AlertSeverity.MEDIUM, jump, t.competitor_jump_points),
        evidence={
            **change_evidence(
                prev,
                cur,
                date_range,
                {
                    "competitor_jump_points": t.competitor_jump_points,
                    "min_responses": t.min_responses,
                },
            ),
            "change_points": round(jump, 1),
        },
    )


def competitor_overtakes_brand(
    name: str,
    brand_prev: PeriodMeasure,
    brand_cur: PeriodMeasure,
    comp_prev: PeriodMeasure,
    comp_cur: PeriodMeasure,
    date_range: dict[str, Any],
    t: AlertThresholds,
) -> AlertDraft | None:
    if not _enough(brand_prev, brand_cur, t.min_responses):
        return None
    if (
        brand_prev.score is None
        or brand_cur.score is None
        or comp_prev.score is None
        or comp_cur.score is None
    ):
        return None
    was_behind_or_level = comp_prev.score <= brand_prev.score
    margin = comp_cur.score - brand_cur.score
    if not was_behind_or_level or margin < t.overtake_margin_points:
        return None
    return AlertDraft(
        alert_type=AlertType.COMPETITOR_OVERTAKES_BRAND,
        competitor_name=name,
        subject=name,
        fingerprint=fingerprint(round(comp_cur.score), round(brand_cur.score)),
        title=f"{name} overtook your brand in competitive visibility",
        description=(
            f"{name} now scores {comp_cur.score:.0f} vs your {brand_cur.score:.0f} "
            f"(previous period: {comp_prev.score:.0f} vs {brand_prev.score:.0f}; "
            f"margin threshold {t.overtake_margin_points:.0f} points)."
        ),
        severity=escalate(AlertSeverity.HIGH, margin, t.overtake_margin_points),
        evidence={
            **change_evidence(
                brand_prev,
                brand_cur,
                date_range,
                {
                    "overtake_margin_points": t.overtake_margin_points,
                    "min_responses": t.min_responses,
                },
            ),
            "competitor_previous_score": comp_prev.score,
            "competitor_current_score": comp_cur.score,
            "margin_points": round(margin, 1),
        },
    )


def citation_gap_increase(
    name: str,
    brand_prev: PeriodMeasure,
    brand_cur: PeriodMeasure,
    comp_prev: PeriodMeasure,
    comp_cur: PeriodMeasure,
    date_range: dict[str, Any],
    t: AlertThresholds,
) -> AlertDraft | None:
    if not _enough(brand_prev, brand_cur, t.min_responses):
        return None
    if (
        brand_prev.citation_share is None
        or brand_cur.citation_share is None
        or comp_prev.citation_share is None
        or comp_cur.citation_share is None
    ):
        return None
    prev_gap = comp_prev.citation_share - brand_prev.citation_share
    cur_gap = comp_cur.citation_share - brand_cur.citation_share
    increase = cur_gap - prev_gap
    if increase < t.citation_gap_increase_points or cur_gap <= 0:
        return None
    return AlertDraft(
        alert_type=AlertType.CITATION_GAP_INCREASE,
        competitor_name=name,
        subject=name,
        fingerprint=fingerprint(round(prev_gap), round(cur_gap)),
        title=f"Citation gap to {name} widened by {increase:.0f} points",
        description=(
            f"{name}'s citation share now exceeds the brand's by {cur_gap:.0f} points "
            f"(previously {prev_gap:.0f}; threshold {t.citation_gap_increase_points:.0f})."
        ),
        severity=escalate(AlertSeverity.MEDIUM, increase, t.citation_gap_increase_points),
        evidence={
            **change_evidence(
                brand_prev,
                brand_cur,
                date_range,
                {
                    "citation_gap_increase_points": t.citation_gap_increase_points,
                    "min_responses": t.min_responses,
                },
            ),
            "competitor_previous_citation_share": comp_prev.citation_share,
            "competitor_current_citation_share": comp_cur.citation_share,
            "previous_gap_points": round(prev_gap, 1),
            "current_gap_points": round(cur_gap, 1),
        },
    )
