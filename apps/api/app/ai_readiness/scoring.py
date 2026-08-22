"""AI Readiness Score — an internal, transparent 0–100 product metric.

It is NOT an industry standard and does not predict AI visibility. It is the
weighted average of per-category coverage values (0..1), each computed from
the detected signals recorded in the breakdown. Categories that do not apply
to a site (no product pages, no articles, no comparable entities) are
excluded and their weight is redistributed. `comparison` is informational and
never scored. Methodology: docs/ai-readiness-score.md.
"""

from dataclasses import dataclass
from typing import Any

from app.models.ai_readiness import ReadinessCategory as C

WEIGHTS: dict[str, float] = {
    C.ENTITY_CLARITY.value: 25.0,
    C.PRODUCT_CLARITY.value: 20.0,
    C.AUTHORITY.value: 15.0,
    C.EVIDENCE.value: 15.0,
    C.CONTENT_STRUCTURE.value: 15.0,
    C.FAQ.value: 5.0,
    C.FACTUAL_CONSISTENCY.value: 5.0,
}
METHOD = "ai-readiness-score/v1"


@dataclass
class ScoreResult:
    score: float
    breakdown: dict[str, Any]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def category_value(category: str, inp: dict[str, Any]) -> tuple[float, str]:
    """Coverage in 0..1 and a one-line explanation of how it was derived."""
    if category == C.ENTITY_CLARITY.value:
        checks = inp["checks"]
        return _mean([1.0 if v else 0.0 for v in checks.values()]), (
            f"{sum(checks.values())} of {len(checks)} entity signals present"
        )
    if category in (C.PRODUCT_CLARITY.value, C.AUTHORITY.value):
        cov = inp["coverage"]
        return _mean(list(cov.values())), f"mean aspect coverage over {inp['pages']} page(s)"
    if category == C.EVIDENCE.value:
        checks = inp["checks"]
        return _mean([1.0 if v else 0.0 for v in checks.values()]), (
            f"{sum(checks.values())} of {len(checks)} evidence kinds detected"
        )
    if category == C.FAQ.value:
        checks = inp["checks"]
        value = (0.5 if checks["faq_content"] else 0.0) + (0.5 if checks["faq_schema"] else 0.0)
        return value, "0.5 for FAQ content, 0.5 for FAQPage schema"
    if category == C.CONTENT_STRUCTURE.value:
        spec = min(1.0, inp["avg_specific_ratio"] / inp["specificity_target"])
        value = 0.6 * spec + 0.2 * (1 - inp["thin_share"]) + 0.2 * (1 - inp["unstructured_share"])
        return value, (
            f"0.6 × specificity ({inp['avg_specific_ratio']:.2f}/{inp['specificity_target']}) + "
            "0.2 × (1 − thin share) + 0.2 × (1 − unstructured share)"
        )
    if category == C.FACTUAL_CONSISTENCY.value:
        compared = max(1, inp["entities_compared"])
        value = max(0.0, 1.0 - inp["conflicts"] / compared)
        return value, f"1 − conflicts/entities compared ({inp['conflicts']}/{compared})"
    return 0.0, "not scored"


def compute_score(inputs: dict[str, Any]) -> ScoreResult:
    categories: dict[str, Any] = {}
    weighted = 0.0
    applicable_weight = 0.0
    for category, weight in WEIGHTS.items():
        inp = inputs.get(category, {"applicable": False})
        if not inp.get("applicable"):
            categories[category] = {
                "applicable": False,
                "weight": weight,
                "value": None,
                "inputs": inp,
            }
            continue
        value, how = category_value(category, inp)
        value = max(0.0, min(1.0, value))
        categories[category] = {
            "applicable": True,
            "weight": weight,
            "value": round(value, 3),
            "how": how,
            "inputs": _json_safe(inp),
        }
        weighted += value * weight
        applicable_weight += weight
    comparison = inputs.get(C.COMPARISON.value, {})
    categories[C.COMPARISON.value] = {
        "applicable": False,
        "weight": 0.0,
        "value": None,
        "how": "informational only; presence of comparison pages is recorded, not scored",
        "inputs": comparison,
    }
    score = round(100.0 * weighted / applicable_weight, 1) if applicable_weight else 0.0
    return ScoreResult(
        score=score,
        breakdown={
            "method": METHOD,
            "weights": WEIGHTS,
            "applicable_weight": applicable_weight,
            "categories": categories,
            "note": (
                "Internal product metric built only from the signals listed here. Not an "
                "industry standard; does not measure or predict AI visibility or rankings."
            ),
        },
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return round(value, 3)
    return value
