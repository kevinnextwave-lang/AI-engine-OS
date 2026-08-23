"""Pure competitive metrics. One `EntityMetrics` per entity (the brand and each
configured competitor) over the same set of eligible responses.

    Competitive Visibility Score (0–100, our own definition — not an industry standard)
        = Σ weight_c × component_c / Σ weight_c   over available components

    mention_share         30   responses mentioning the entity / eligible responses
    recommendation_share  25   responses recommending it (moderate/strong, not negative) / eligible
    position_score        15   mean position points over positioned mentions (1st=100 … 6+=25)
    citation_share        15   responses with ≥1 citation referencing the entity / eligible
    sentiment_score       15   positive=100, mixed/neutral=50, negative=0 over mentions

Position and sentiment are unavailable for an entity that is never mentioned;
they drop out and the remaining weights renormalise, so an invisible entity
scores 0 rather than "unknown". The score is withheld below MIN_SAMPLE
responses and rounded coarsely for small samples (same rules as the AI
Visibility Score). Rankings are only produced at "moderate" sufficiency
(≥ 20 responses) or better.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.competitive import METHOD
from app.visibility.metrics import (
    MIN_SAMPLE,
    SENTIMENT_POINTS,
    position_points,
    round_for,
    sufficiency_for,
)
from app.visibility.observations import ResponseObservation

WEIGHTS: dict[str, float] = {
    "mention_share": 30.0,
    "recommendation_share": 25.0,
    "position_score": 15.0,
    "citation_share": 15.0,
    "sentiment_score": 15.0,
}
RANKING_MIN_SAMPLE = 20  # "moderate" sufficiency — no leader boards on tiny datasets
MATERIAL_ADVANTAGE = 10.0  # score points; below this a gap is reported but not flagged
COMPONENT_WIN_MARGIN = 5.0  # a component counts as "where they win" only above this gap
BRAND = "brand"


@dataclass(frozen=True)
class EntityView:
    """What one response says about one entity."""

    mentioned: bool
    recommended: bool
    position: int | None
    sentiment: str
    strength: str
    citations: int


def entity_view(o: ResponseObservation, name: str) -> EntityView:
    if name == BRAND:
        return EntityView(
            mentioned=o.brand_mentioned,
            recommended=o.recommended,
            position=o.brand_position,
            sentiment=o.brand_sentiment if o.brand_mentioned else "unknown",
            strength=o.brand_strength if o.brand_mentioned else "unknown",
            citations=o.brand_citations,
        )
    hit = next((c for c in o.competitors if c.name == name), None)
    if hit is None:
        return EntityView(
            False, False, None, "unknown", "unknown", o.competitor_citations.get(name, 0)
        )
    return EntityView(
        mentioned=True,
        recommended=hit.strength in ("moderate", "strong") and hit.sentiment != "negative",
        position=hit.position,
        sentiment=hit.sentiment,
        strength=hit.strength,
        citations=o.competitor_citations.get(name, 0),
    )


@dataclass
class EntityMetrics:
    name: str
    is_brand: bool
    sample_size: int
    mentions: int
    recommendations: int
    positioned_mentions: int
    cited_responses: int
    citations: int
    prompts_appearing: int
    mention_share: float | None
    recommendation_share: float | None
    average_position: float | None
    citation_share: float | None
    sentiment_score: float | None
    sentiment: dict[str, int]
    score: float | None
    components: dict[str, float | None]
    sufficiency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_brand": self.is_brand,
            "score": self.score,
            "mention_share": self.mention_share,
            "recommendation_share": self.recommendation_share,
            "average_position": self.average_position,
            "citation_share": self.citation_share,
            "sentiment_score": self.sentiment_score,
            "sentiment": self.sentiment,
            "prompt_coverage": self.prompts_appearing,
            "counts": {
                "mentions": self.mentions,
                "recommendations": self.recommendations,
                "positioned_mentions": self.positioned_mentions,
                "cited_responses": self.cited_responses,
                "citations": self.citations,
            },
            "components": self.components,
            "sufficiency": self.sufficiency,
        }


def _pct(n: int, total: int) -> float | None:
    return None if total == 0 else 100.0 * n / total


def compute_entity(obs: list[ResponseObservation], name: str) -> EntityMetrics:
    total = len(obs)
    views = [(o, entity_view(o, name)) for o in obs]
    mentioned = [(o, v) for o, v in views if v.mentioned]
    positions = [v.position for _, v in mentioned if v.position is not None]
    sentiments = [v.sentiment for _, v in mentioned]
    scored = [s for s in sentiments if s in SENTIMENT_POINTS]
    recommendations = sum(1 for _, v in views if v.recommended)
    cited = sum(1 for _, v in views if v.citations > 0)
    citations = sum(v.citations for _, v in views)

    raw: dict[str, float | None] = {
        "mention_share": _pct(len(mentioned), total),
        "recommendation_share": _pct(recommendations, total),
        "position_score": (
            sum(position_points(p) for p in positions) / len(positions) if positions else None
        ),
        "citation_share": _pct(cited, total),
        "sentiment_score": (
            sum(SENTIMENT_POINTS[s] for s in scored) / len(scored) if scored else None
        ),
    }
    available = {k: v for k, v in raw.items() if v is not None}
    score = (
        sum(WEIGHTS[k] * v for k, v in available.items()) / sum(WEIGHTS[k] for k in available)
        if available and total >= MIN_SAMPLE
        else None
    )
    return EntityMetrics(
        name=name,
        is_brand=name == BRAND,
        sample_size=total,
        mentions=len(mentioned),
        recommendations=recommendations,
        positioned_mentions=len(positions),
        cited_responses=cited,
        citations=citations,
        prompts_appearing=len({o.prompt_id for o, _ in mentioned}),
        mention_share=round_for(total, raw["mention_share"]),
        recommendation_share=round_for(total, raw["recommendation_share"]),
        average_position=round(sum(positions) / len(positions), 2) if positions else None,
        citation_share=round_for(total, raw["citation_share"]),
        sentiment_score=round(raw["sentiment_score"], 1)
        if raw["sentiment_score"] is not None
        else None,
        sentiment={
            k: Counter(sentiments).get(k, 0)
            for k in ("positive", "neutral", "negative", "mixed", "unknown")
        },
        score=round_for(total, score),
        components={k: round_for(total, v) for k, v in raw.items()},
        sufficiency=sufficiency_for(total),
    )


def compute_all(obs: list[ResponseObservation], competitor_names: list[str]) -> list[EntityMetrics]:
    return [compute_entity(obs, BRAND)] + [compute_entity(obs, n) for n in competitor_names]


def advantages(rows: list[EntityMetrics]) -> list[dict[str, Any]]:
    """competitor score − brand score, per competitor and per component.
    `material` only when both scores exist, the sample is at least "moderate" and the
    gap is ≥ MATERIAL_ADVANTAGE points; smaller or under-sampled gaps are reported
    with a reason instead of being flagged."""
    brand = next(r for r in rows if r.is_brand)
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.is_brand:
            continue
        if brand.score is None or r.score is None:
            gap: float | None = None
            material = False
            reason: str | None = "insufficient data"
        else:
            gap = round(r.score - brand.score, 1)
            if r.sample_size < RANKING_MIN_SAMPLE:
                material, reason = False, "sample too small to call the gap material"
            elif gap >= MATERIAL_ADVANTAGE:
                material, reason = True, None
            else:
                material, reason = False, "gap below the material threshold"
        comps = {k: _diff(r.components[k], brand.components[k]) for k in WEIGHTS}
        leading = sorted(
            ((k, v) for k, v in comps.items() if v is not None and v >= COMPONENT_WIN_MARGIN),
            key=lambda kv: -kv[1],
        )
        out.append(
            {
                "competitor": r.name,
                "competitor_score": r.score,
                "brand_score": brand.score,
                "advantage": gap,
                "material": material,
                "reason": reason,
                "components": comps,
                "where_they_win": [k for k, _ in leading],
            }
        )
    out.sort(key=lambda a: -(a["advantage"] if a["advantage"] is not None else -1e9))
    return out


def _diff(a: float | None, b: float | None) -> float | None:
    return round(a - b, 1) if a is not None and b is not None else None


def ranking(rows: list[EntityMetrics]) -> dict[str, Any]:
    """Entities ordered by score; only when the sample is at least "moderate"."""
    sample = rows[0].sample_size if rows else 0
    if sample < RANKING_MIN_SAMPLE:
        return {
            "available": False,
            "reason": (
                f"ranking requires at least {RANKING_MIN_SAMPLE} eligible responses (have {sample})"
            ),
            "order": [],
            "brand_rank": None,
        }
    scored = [r for r in rows if r.score is not None]
    order = sorted(scored, key=lambda r: (-(r.score or 0.0), r.name))
    names = [r.name for r in order]
    return {
        "available": True,
        "reason": None,
        "order": names,
        "brand_rank": names.index(BRAND) + 1 if BRAND in names else None,
    }


def data_quality(obs: list[ResponseObservation], competitors: int) -> dict[str, Any]:
    total = len(obs)
    return {
        "sample_size": total,
        "prompt_count": len({o.prompt_id for o in obs}),
        "provider_count": len({o.provider_key for o in obs}),
        "providers": sorted({o.provider_key for o in obs}),
        "date_range": {
            "start": min((o.completed_at for o in obs), default=None),
            "end": max((o.completed_at for o in obs), default=None),
        },
        "confidence": sufficiency_for(total),
        "competitors_configured": competitors,
        "minimum_sample": MIN_SAMPLE,
        "ranking_minimum_sample": RANKING_MIN_SAMPLE,
    }


def method_block() -> dict[str, Any]:
    return {
        "method": METHOD,
        "weights": WEIGHTS,
        "note": (
            "Competitive Visibility Score is this product's own weighted composite of mention, "
            "recommendation, position, citation and sentiment over the same eligible responses; "
            "it is not an industry-standard metric and is withheld on small samples."
        ),
    }


def serialize_date_range(dq: dict[str, Any]) -> dict[str, Any]:
    dr = dq["date_range"]
    return {
        **dq,
        "date_range": {
            "start": dr["start"].isoformat() if isinstance(dr["start"], datetime) else None,
            "end": dr["end"].isoformat() if isinstance(dr["end"], datetime) else None,
        },
    }
