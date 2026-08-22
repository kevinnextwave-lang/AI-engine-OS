"""Pure metric computation. Every component is 0–100 or None (unavailable).

    AI Visibility Score = Σ weight_c × component_c / Σ weight_c   over available components

Weights: mention 25, recommendation 25, position 15, citation 15, sentiment 10,
competitive 10. Unavailable components drop out and weights renormalize. The
score is withheld below MIN_SAMPLE and rounded coarsely for small samples.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.visibility import METHOD
from app.visibility.observations import ObservationSet, ResponseObservation

WEIGHTS: dict[str, float] = {
    "mention_rate": 25.0,
    "recommendation_rate": 25.0,
    "position_score": 15.0,
    "citation_rate": 15.0,
    "sentiment_score": 10.0,
    "competitive_score": 10.0,
}
POSITION_POINTS = {1: 100.0, 2: 85.0, 3: 70.0, 4: 55.0, 5: 40.0}
POSITION_POINTS_DEFAULT = 25.0  # 6th or later
SENTIMENT_POINTS = {"positive": 100.0, "mixed": 50.0, "neutral": 50.0, "negative": 0.0}

MIN_SAMPLE = 5  # below this no score is produced
SUFFICIENCY = ((50, "high"), (20, "moderate"), (MIN_SAMPLE, "low"))


def position_points(position: int) -> float:
    return POSITION_POINTS.get(position, POSITION_POINTS_DEFAULT)


def sufficiency_for(sample: int) -> str:
    for threshold, label in SUFFICIENCY:
        if sample >= threshold:
            return label
    return "insufficient"


def round_for(sample: int, value: float | None) -> float | None:
    """Coarser rounding for smaller samples so precision never outruns the data."""
    if value is None:
        return None
    label = sufficiency_for(sample)
    if label == "insufficient":
        return None
    if label == "low":
        return float(round(value / 5) * 5)
    if label == "moderate":
        return float(round(value))
    return round(value, 1)


@dataclass
class Component:
    key: str
    value: float | None  # 0..100, None = unavailable
    weight: float
    sample: int
    note: str


@dataclass
class VisibilityMetrics:
    sample_size: int
    score: float | None
    components: list[Component]
    mention_rate: float | None
    recommendation_rate: float | None
    average_position: float | None
    citation_rate: float | None
    sentiment: dict[str, int]
    sufficiency: str
    providers: list[str]
    models: list[str]
    prompts: int
    date_range: dict[str, datetime | None]
    parser_versions: list[str]
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "score": self.score,
            "mention_rate": self.mention_rate,
            "recommendation_rate": self.recommendation_rate,
            "average_position": self.average_position,
            "citation_rate": self.citation_rate,
            "sentiment": self.sentiment,
            "components": [
                {
                    "key": c.key,
                    "value": c.value,
                    "weight": c.weight,
                    "sample": c.sample,
                    "note": c.note,
                }
                for c in self.components
            ],
            "data_quality": {
                "sample_size": self.sample_size,
                "sufficiency": self.sufficiency,
                "providers": len(self.providers),
                "provider_keys": self.providers,
                "models": len(self.models),
                "prompts": self.prompts,
                "date_range": {
                    "start": self.date_range["start"].isoformat()
                    if self.date_range["start"]
                    else None,
                    "end": self.date_range["end"].isoformat() if self.date_range["end"] else None,
                },
                "parser_versions": self.parser_versions,
                "minimum_sample": MIN_SAMPLE,
            },
            **self.extras,
        }


def _pct(n: int, total: int) -> float | None:
    return None if total == 0 else 100.0 * n / total


def compute(obs: list[ResponseObservation], competitor_names: list[str]) -> VisibilityMetrics:
    total = len(obs)
    mentioned = [o for o in obs if o.brand_mentioned]
    positioned = [o.brand_position for o in mentioned if o.brand_position is not None]
    sentiments = Counter(o.brand_sentiment for o in mentioned)
    scored_sentiments = [
        o.brand_sentiment for o in mentioned if o.brand_sentiment in SENTIMENT_POINTS
    ]

    mention_rate = _pct(len(mentioned), total)
    recommendation_rate = _pct(sum(1 for o in obs if o.recommended), total)
    citation_rate = _pct(sum(1 for o in obs if o.brand_cited), total)
    position_score = (
        sum(position_points(p) for p in positioned) / len(positioned) if positioned else None
    )
    average_position = sum(positioned) / len(positioned) if positioned else None
    sentiment_score = (
        sum(SENTIMENT_POINTS[s] for s in scored_sentiments) / len(scored_sentiments)
        if scored_sentiments
        else None
    )
    competitive_score, competitive_note = _competitive(obs, competitor_names)

    components = [
        Component(
            "mention_rate",
            mention_rate,
            WEIGHTS["mention_rate"],
            total,
            "responses mentioning the brand / eligible responses",
        ),
        Component(
            "recommendation_rate",
            recommendation_rate,
            WEIGHTS["recommendation_rate"],
            total,
            "responses recommending the brand (moderate/strong, not negative) / eligible responses",
        ),
        Component(
            "position_score",
            position_score,
            WEIGHTS["position_score"],
            len(positioned),
            "mean of position points over mentions with a list position "
            "(1st=100 … 6+=25); unknown positions excluded",
        ),
        Component(
            "citation_rate",
            citation_rate,
            WEIGHTS["citation_rate"],
            total,
            "responses citing one of the project's domains / eligible responses",
        ),
        Component(
            "sentiment_score",
            sentiment_score,
            WEIGHTS["sentiment_score"],
            len(scored_sentiments),
            "positive=100, mixed/neutral=50, negative=0 over brand mentions; unknown excluded",
        ),
        Component(
            "competitive_score",
            competitive_score,
            WEIGHTS["competitive_score"],
            total,
            competitive_note,
        ),
    ]
    available = [c for c in components if c.value is not None]
    raw_score = (
        sum(c.value * c.weight for c in available if c.value is not None)
        / sum(c.weight for c in available)
        if available and total >= MIN_SAMPLE
        else None
    )
    return VisibilityMetrics(
        sample_size=total,
        score=round_for(total, raw_score),
        components=[
            Component(
                c.key,
                round_for(total, c.value) if c.value is not None else None,
                c.weight,
                c.sample,
                c.note,
            )
            for c in components
        ],
        mention_rate=round_for(total, mention_rate),
        recommendation_rate=round_for(total, recommendation_rate),
        average_position=round(average_position, 2) if average_position is not None else None,
        citation_rate=round_for(total, citation_rate),
        sentiment={
            k: sentiments.get(k, 0) for k in ("positive", "neutral", "negative", "mixed", "unknown")
        },
        sufficiency=sufficiency_for(total),
        providers=sorted({o.provider_key for o in obs}),
        models=sorted({f"{o.provider_key}/{o.model_key}" for o in obs}),
        prompts=len({o.prompt_id for o in obs}),
        date_range={
            "start": min((o.completed_at for o in obs), default=None),
            "end": max((o.completed_at for o in obs), default=None),
        },
        parser_versions=sorted({o.parser_version for o in obs if o.parser_version}),
    )


def _competitive(
    obs: list[ResponseObservation], competitor_names: list[str]
) -> tuple[float | None, str]:
    """100 when the brand is mentioned at least as often as the best configured
    competitor; otherwise brand rate / top competitor rate × 100. Unavailable when
    no competitors are configured or nobody (brand or competitor) is mentioned."""
    note = "brand mention rate relative to the most-mentioned configured competitor (100 = leading)"
    if not competitor_names or not obs:
        return (
            None,
            note + "; unavailable: no competitors configured" if not competitor_names else note,
        )
    brand = sum(1 for o in obs if o.brand_mentioned)
    per_competitor = Counter()  # type: Counter[str]
    for o in obs:
        for c in o.competitors:
            if c.name in competitor_names:
                per_competitor[c.name] += 1
    top = max(per_competitor.values(), default=0)
    if brand == 0 and top == 0:
        return None, note + "; unavailable: neither brand nor competitors mentioned"
    if brand >= top:
        return 100.0, note
    return 100.0 * brand / top, note


def competitor_table(data: ObservationSet) -> list[dict[str, Any]]:
    obs = data.observations
    total = len(obs)
    rows: list[dict[str, Any]] = []

    def row(
        name: str,
        is_brand: bool,
        mentioned: list[ResponseObservation],
        positions: list[int],
        recommended: int,
        sentiments: list[str],
    ) -> dict[str, Any]:
        scored = [s for s in sentiments if s in SENTIMENT_POINTS]
        return {
            "name": name,
            "is_brand": is_brand,
            "mentions": len(mentioned),
            "mention_rate": round_for(total, _pct(len(mentioned), total)),
            "recommendation_rate": round_for(total, _pct(recommended, total)),
            "average_position": round(sum(positions) / len(positions), 2) if positions else None,
            "positioned_mentions": len(positions),
            "sentiment_score": round(sum(SENTIMENT_POINTS[s] for s in scored) / len(scored), 1)
            if scored
            else None,
            "sentiment": dict(Counter(sentiments)),
        }

    brand_mentioned = [o for o in obs if o.brand_mentioned]
    rows.append(
        row(
            "brand",
            True,
            brand_mentioned,
            [o.brand_position for o in brand_mentioned if o.brand_position is not None],
            sum(1 for o in obs if o.recommended),
            [o.brand_sentiment for o in brand_mentioned],
        )
    )
    for name in data.competitor_names:
        hits = [(o, c) for o in obs for c in o.competitors if c.name == name]
        rows.append(
            row(
                name,
                False,
                [o for o, _ in hits],
                [c.position for _, c in hits if c.position is not None],
                sum(
                    1
                    for _, c in hits
                    if c.strength in ("moderate", "strong") and c.sentiment != "negative"
                ),
                [c.sentiment for _, c in hits],
            )
        )
    total_mentions = sum(r["mentions"] for r in rows)
    for r in rows:
        r["share_of_voice"] = (
            round(100.0 * r["mentions"] / total_mentions, 1) if total_mentions else None
        )
    return rows
