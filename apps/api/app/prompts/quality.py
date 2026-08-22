"""Deterministic prompt quality score (0–100). Methodology: docs/prompt-quality-score.md.

    score = Σ weight_k × component_k / Σ weight_k   over applicable components

Components (each 0..1): relevance, uniqueness, commercial_intent, specificity,
geographic_relevance (only when the profile names a geographic market).
"""

import re
from dataclasses import dataclass
from typing import Any

from app.models.prompts import PromptCategory
from app.prompts.normalize import normalize_text, similarity
from app.prompts.profile import BusinessProfile

WEIGHTS = {
    "relevance": 0.30,
    "uniqueness": 0.20,
    "commercial_intent": 0.25,
    "specificity": 0.15,
    "geographic_relevance": 0.10,
}

COMMERCIAL_BASE: dict[PromptCategory, float] = {
    PromptCategory.TRANSACTIONAL: 1.0,
    PromptCategory.PRICING: 0.95,
    PromptCategory.RECOMMENDATION: 0.85,
    PromptCategory.COMPARISON: 0.85,
    PromptCategory.ALTERNATIVE: 0.85,
    PromptCategory.LOCAL: 0.80,
    PromptCategory.PRODUCT: 0.70,
    PromptCategory.PROBLEM_SOLUTION: 0.50,
    PromptCategory.DISCOVERY: 0.35,
    PromptCategory.INDUSTRY: 0.30,
}
_COMMERCIAL_MARKERS = re.compile(
    r"\b(best|top|pricing|price|cost|alternatives?|vs\.?|versus|compare|buy|demo|trial|"
    r"sign up|recommend)\b",
    re.I,
)
IDEAL_WORDS = (6, 18)
METHOD = "prompt-quality-score/v1"


@dataclass
class QualityResult:
    score: float
    priority: int
    breakdown: dict[str, Any]


def _contains_any(norm: str, terms: list[str]) -> bool:
    return any(t and normalize_text(t) in norm for t in terms)


def score_prompt(
    text: str,
    category: PromptCategory,
    profile: BusinessProfile,
    others: list[str],
) -> QualityResult:
    norm = normalize_text(text)
    terms = profile.terms()

    # relevance: must mention the offering/industry; bonus for any other profile entity
    offering_hit = (
        _contains_any(norm, terms["offering"])
        or _contains_any(norm, terms["company"])
        or _contains_any(norm, terms["product"])
    )
    entity_groups = ("audience", "competitor", "descriptor", "geo")
    entity_hits = sum(1 for g in entity_groups if _contains_any(norm, terms[g]))
    relevance = (0.6 if offering_hit else 0.0) + min(0.4, 0.2 * entity_hits)

    # uniqueness vs the rest of the set
    max_sim = max((similarity(text, o) for o in others if normalize_text(o) != norm), default=0.0)
    uniqueness = max(0.0, 1.0 - max_sim)

    # commercial intent
    commercial = min(
        1.0, COMMERCIAL_BASE[category] + (0.1 if _COMMERCIAL_MARKERS.search(text) else 0.0)
    )

    # specificity: named entities + qualifiers + sensible length
    named = (
        _contains_any(norm, terms["competitor"])
        or _contains_any(norm, terms["company"])
        or _contains_any(norm, terms["product"])
    )
    qualified = (
        _contains_any(norm, terms["audience"])
        or _contains_any(norm, terms["descriptor"])
        or _contains_any(norm, terms["geo"])
    )
    words = len(norm.split())
    length_ok = IDEAL_WORDS[0] <= words <= IDEAL_WORDS[1]
    specificity = (
        (0.4 if named else 0.0) + (0.3 if qualified else 0.0) + (0.3 if length_ok else 0.1)
    )

    components: dict[str, float | None] = {
        "relevance": round(relevance, 3),
        "uniqueness": round(uniqueness, 3),
        "commercial_intent": round(commercial, 3),
        "specificity": round(min(1.0, specificity), 3),
        "geographic_relevance": None,
    }
    if terms["geo"]:
        components["geographic_relevance"] = 1.0 if _contains_any(norm, terms["geo"]) else 0.4

    weight_sum = sum(WEIGHTS[k] for k, v in components.items() if v is not None)
    total = sum(WEIGHTS[k] * v for k, v in components.items() if v is not None) / weight_sum
    score = round(100 * total, 1)
    return QualityResult(
        score=score,
        priority=priority_for(score),
        breakdown={
            "method": METHOD,
            "components": components,
            "weights": WEIGHTS,
            "signals": {
                "offering_mentioned": offering_hit,
                "entity_groups_mentioned": entity_hits,
                "max_similarity": round(max_sim, 3),
                "named_entity": named,
                "qualifier": qualified,
                "word_count": words,
            },
        },
    )


def priority_for(score: float) -> int:
    """1 = highest priority … 5 = lowest."""
    if score >= 80:
        return 1
    if score >= 65:
        return 2
    if score >= 50:
        return 3
    if score >= 35:
        return 4
    return 5
