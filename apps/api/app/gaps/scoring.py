"""Citation Opportunity Score and gap classification — pure functions.

See docs/citation-gaps.md. Everything here takes a `SourceStats` (what we
observed about one source in one project's relevant AI responses over the
analysis window) and returns fully explained results.

    opportunity = Σ weight_c × component_c / Σ weight_c       (0–100)

| component           | weight | derivation                                                     |
|---------------------|--------|----------------------------------------------------------------|
| citation_frequency  | 25     | share of relevant responses that cite the source, 100 at ≥ 30 %|
| competitor_gap      | 30     | (competitor − brand) / (competitor + brand), scaled 0–100;     |
|                     |        | brand_absent with competitors cited ⇒ 100; nobody cited ⇒ 40   |
| source_relevance    | 20     | Source Relevance Score of the domain (4B)                      |
| prompt_relevance    | 15     | share of the project's prompts whose answers cite the source   |
| recency             | 10     | days since last citation: ≤7 → 100, 30 → 60, 90 → 20, older → 0|

Gap-type modifiers (the score is what it would take to act, so): a
`source_overrepresented` source is not an opportunity (score × 0.3), a
`shared_source` is a modest one (× 0.7). Sample size never inflates the score;
it only drives `confidence`, which is reported separately.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.models.gaps import GapConfidence, GapType

WEIGHTS = {
    "citation_frequency": 25.0,
    "competitor_gap": 30.0,
    "source_relevance": 20.0,
    "prompt_relevance": 15.0,
    "recency": 10.0,
}
FREQUENCY_SATURATION = 0.30  # share of relevant responses at which frequency = 100
TYPE_MULTIPLIER = {
    GapType.SOURCE_OVERREPRESENTED: 0.3,
    GapType.SHARED_SOURCE: 0.7,
}

# Data sufficiency thresholds: (relevant responses citing the source, eligible responses)
CONFIDENCE_LEVELS = (
    (GapConfidence.HIGH, 20, 50),
    (GapConfidence.MEDIUM, 8, 20),
    (GapConfidence.LOW, 3, 5),
)


@dataclass
class SourceStats:
    domain: str
    domain_type: str
    source_relevance: float  # 0–100 (4B)
    eligible_responses: int  # parsed, completed responses in the window
    total_prompts: int  # distinct prompts with eligible responses in the window
    relevant_responses: int  # distinct responses citing this source
    prompts_citing: int  # distinct prompts whose responses cite this source
    citations: int  # citation rows for this source
    brand_citations: int
    competitor_citations: int
    competitors: dict[str, int] = field(default_factory=dict)  # name → citations
    first_cited_at: datetime | None = None
    last_cited_at: datetime | None = None
    citations_first_half: int = 0  # split of the window, for "emerging"
    citations_second_half: int = 0
    now: datetime | None = None
    window_days: int = 90


def _recency(stats: SourceStats) -> float:
    if stats.last_cited_at is None or stats.now is None:
        return 0.0
    days = max(0.0, (stats.now - stats.last_cited_at).total_seconds() / 86400)
    if days <= 7:
        return 100.0
    if days <= 30:
        return 100.0 - (days - 7) * (40.0 / 23.0)  # 100 → 60
    if days <= 90:
        return 60.0 - (days - 30) * (40.0 / 60.0)  # 60 → 20
    return max(0.0, 20.0 - (days - 90) * (20.0 / 90.0))


def _competitor_gap(stats: SourceStats) -> float:
    b, c = stats.brand_citations, stats.competitor_citations
    if b == 0 and c > 0:
        return 100.0
    if b == 0 and c == 0:
        return 40.0  # nobody is cited from it: open ground, not a proven competitor edge
    return max(0.0, 50.0 + 50.0 * (c - b) / (c + b))


def classify_gap(stats: SourceStats) -> GapType:
    b, c, r = stats.brand_citations, stats.competitor_citations, stats.relevant_responses
    recent_start = (
        stats.first_cited_at is not None
        and stats.now is not None
        and (stats.now - stats.first_cited_at).days <= stats.window_days * 0.3
    )
    rising = stats.citations_second_half >= max(3, 2 * stats.citations_first_half)
    if b == 0 and recent_start and rising:
        return GapType.EMERGING_SOURCE
    if b == 0 and (c >= 1 or r >= 3):
        return GapType.BRAND_ABSENT
    if b > 0 and c >= 3 and c >= 2 * b:
        return GapType.COMPETITOR_ADVANTAGE
    if b > 0 and c > 0:
        return GapType.SHARED_SOURCE
    if b >= 3 and c == 0 and b >= 0.8 * stats.citations:
        return GapType.SOURCE_OVERREPRESENTED
    return GapType.SOURCE_UNDERREPRESENTED


def confidence_for(stats: SourceStats) -> GapConfidence:
    """Sample-size driven. A single response, a tiny eligible pool, or a source
    we know nothing about (unknown type) can never be high confidence."""
    if stats.relevant_responses <= 1 or stats.eligible_responses < 5:
        return GapConfidence.INSUFFICIENT
    level = GapConfidence.INSUFFICIENT
    for candidate, min_relevant, min_eligible in CONFIDENCE_LEVELS:
        if stats.relevant_responses >= min_relevant and stats.eligible_responses >= min_eligible:
            level = candidate
            break
    if level is GapConfidence.HIGH and stats.domain_type == "unknown":
        return GapConfidence.MEDIUM  # source data incomplete
    return level


def opportunity(stats: SourceStats, gap_type: GapType) -> dict[str, Any]:
    share = stats.relevant_responses / stats.eligible_responses if stats.eligible_responses else 0
    components = {
        "citation_frequency": min(100.0, 100.0 * share / FREQUENCY_SATURATION),
        "competitor_gap": _competitor_gap(stats),
        "source_relevance": max(0.0, min(100.0, stats.source_relevance)),
        "prompt_relevance": (
            min(100.0, 100.0 * stats.prompts_citing / stats.total_prompts)
            if stats.total_prompts
            else 0.0
        ),
        "recency": _recency(stats),
    }
    raw = sum(WEIGHTS[k] * v for k, v in components.items()) / sum(WEIGHTS.values())
    multiplier = TYPE_MULTIPLIER.get(gap_type, 1.0)
    score = round(raw * multiplier, 1)
    return {
        "score": score,
        "raw_score": round(raw, 1),
        "type_multiplier": multiplier,
        "components": {
            k: {"value": round(v, 1), "weight": WEIGHTS[k]} for k, v in components.items()
        },
        "inputs": {
            "eligible_responses": stats.eligible_responses,
            "relevant_responses": stats.relevant_responses,
            "citation_share": round(share, 3),
            "total_prompts": stats.total_prompts,
            "prompts_citing": stats.prompts_citing,
            "citations": stats.citations,
            "brand_citations": stats.brand_citations,
            "competitor_citations": stats.competitor_citations,
            "source_relevance": stats.source_relevance,
            "domain_type": stats.domain_type,
            "first_cited_at": stats.first_cited_at.isoformat() if stats.first_cited_at else None,
            "last_cited_at": stats.last_cited_at.isoformat() if stats.last_cited_at else None,
        },
    }


def priority_for(score: float) -> Literal["high", "medium", "low"]:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def explain(stats: SourceStats, gap_type: GapType, confidence: GapConfidence) -> str:
    top = sorted(stats.competitors.items(), key=lambda kv: -kv[1])[:3]
    comp = ", ".join(f"{n} ({c})" for n, c in top) or "no configured competitor"
    base = {
        GapType.BRAND_ABSENT: (
            f"{stats.domain} is cited in {stats.relevant_responses} relevant AI responses "
            f"but never for the brand; competitors cited from it: {comp}."
        ),
        GapType.COMPETITOR_ADVANTAGE: (
            f"Competitors are frequently cited from {stats.domain} "
            f"({stats.competitor_citations} citations: {comp}) while the brand is rarely cited "
            f"({stats.brand_citations})."
        ),
        GapType.SHARED_SOURCE: (
            f"{stats.domain} cites both the brand ({stats.brand_citations}) and competitors "
            f"({stats.competitor_citations}: {comp}); parity rather than a gap."
        ),
        GapType.SOURCE_OVERREPRESENTED: (
            f"{stats.domain} cites the brand ({stats.brand_citations}) and no competitor; "
            "the brand already dominates this source."
        ),
        GapType.SOURCE_UNDERREPRESENTED: (
            f"{stats.domain} appears in {stats.relevant_responses} relevant AI responses without "
            "citing the brand or a configured competitor; coverage there is open ground."
        ),
        GapType.EMERGING_SOURCE: (
            f"{stats.domain} started appearing recently and is being cited more and more "
            f"({stats.citations_first_half} → {stats.citations_second_half} citations) "
            "without citing the brand."
        ),
    }[gap_type]
    sample = (
        f" Based on {stats.relevant_responses} of {stats.eligible_responses} eligible responses "
        f"across {stats.prompts_citing} prompt{'s' if stats.prompts_citing != 1 else ''}"
        f" ({confidence.value} confidence)."
    )
    if confidence is GapConfidence.INSUFFICIENT:
        sample += " Too little data to act on yet."
    return base + sample
