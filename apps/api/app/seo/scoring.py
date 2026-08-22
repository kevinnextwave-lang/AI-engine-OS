"""Technical SEO Health Score — a preliminary, transparent 0–100 number.

This is NOT an industry-standard metric. It exists so a site can be compared
with itself over time. Methodology: docs/technical-seo-health-score.md.

    score = 100 - sum over categories of min(cap_c, deductions_c)
    deductions_c = sum over findings f in c of weight(severity_f) * spread_f

`spread` scales a finding by how much of the site it touches (affected pages /
html pages, floored at a minimum so one-off issues still register). Categories
have caps so a single problem type cannot zero the score on its own.
"""

from dataclasses import dataclass
from typing import Any

from app.models.seo import ObservationCategory, Severity
from app.seo.findings import Finding

SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 25.0,
    Severity.HIGH: 12.0,
    Severity.MEDIUM: 6.0,
    Severity.LOW: 2.0,
    Severity.INFO: 0.0,
}

CATEGORY_CAP: dict[ObservationCategory, float] = {
    ObservationCategory.INDEXABILITY: 25.0,
    ObservationCategory.HTTP: 20.0,
    ObservationCategory.INTERNAL_LINKS: 15.0,
    ObservationCategory.CANONICALIZATION: 15.0,
    ObservationCategory.METADATA: 15.0,
    ObservationCategory.HEADINGS: 8.0,
    ObservationCategory.MOBILE_HTML: 10.0,
    ObservationCategory.STRUCTURED_DATA: 5.0,
}

MIN_SPREAD = 0.25


@dataclass
class ScoreResult:
    score: float
    breakdown: dict[str, Any]


def _affected(f: Finding) -> int:
    if f.page_id is not None:
        return 1
    ev = f.evidence or {}
    for key in ("count",):
        if isinstance(ev.get(key), int):
            return max(1, int(ev[key]))
    return 1


def compute_score(findings: list[Finding], html_pages: int) -> ScoreResult:
    pages = max(1, html_pages)
    per_category: dict[str, dict[str, Any]] = {}
    for cat in ObservationCategory:
        raw = 0.0
        contributions: list[dict[str, Any]] = []
        for f in findings:
            if f.category != cat:
                continue
            weight = SEVERITY_WEIGHT[f.severity]
            if weight == 0:
                continue
            spread = max(MIN_SPREAD, min(1.0, _affected(f) / pages))
            amount = round(weight * spread, 3)
            raw += amount
            contributions.append(
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "affected_pages": _affected(f),
                    "spread": round(spread, 3),
                    "deduction": amount,
                }
            )
        cap = CATEGORY_CAP[cat]
        applied = min(cap, raw)
        per_category[cat.value] = {
            "raw_deduction": round(raw, 2),
            "cap": cap,
            "applied_deduction": round(applied, 2),
            "contributions": sorted(contributions, key=lambda c: -c["deduction"])[:50],
        }
    total = sum(c["applied_deduction"] for c in per_category.values())
    score = round(max(0.0, 100.0 - total), 1)
    return ScoreResult(
        score=score,
        breakdown={
            "method": "technical-seo-health-score/v1",
            "html_pages": html_pages,
            "severity_weights": {k.value: v for k, v in SEVERITY_WEIGHT.items()},
            "min_spread": MIN_SPREAD,
            "categories": per_category,
            "total_deduction": round(total, 2),
        },
    )
