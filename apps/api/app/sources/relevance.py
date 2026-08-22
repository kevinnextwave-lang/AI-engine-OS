"""Source Relevance Score — a transparent, initial 0–100 indicator of how much
a cited source matters *in the AI answers we observed*.

This is NOT a universal domain-authority metric. It only reflects what this
product has seen: how often AI engines cite the source, across how many
projects, how steadily over time, what kind of source it is, and (when a
project is given) how much that particular market cites it.

    score = Σ weight_c × component_c        components are 0–100

| component        | weight | derivation                                                   |
|------------------|--------|--------------------------------------------------------------|
| frequency        | 30     | log10(citations + 1) / log10(FREQ_SATURATION + 1), capped    |
| breadth          | 20     | projects observed / BREADTH_SATURATION, capped               |
| consistency      | 15     | weeks with ≥1 citation / weeks since first seen (min 1 week) |
| source_type      | 20     | TYPE_POINTS[domain_type] (unknown = 50, neutral)             |
| project_frequency| 15     | log-scaled project citations; only with a project, else the  |
|                  |        | weight is dropped and the others renormalise                 |

Authority-registry sources get +5 on source_type (capped at 100). Everything is
reported component by component so the number can always be explained.
"""

import math
from dataclasses import dataclass
from typing import Any

from app.models.sources import DomainType

WEIGHTS = {
    "frequency": 30.0,
    "breadth": 20.0,
    "consistency": 15.0,
    "source_type": 20.0,
    "project_frequency": 15.0,
}
FREQ_SATURATION = 1000  # citations at which the frequency component reaches 100
PROJECT_FREQ_SATURATION = 100
BREADTH_SATURATION = 20  # projects at which breadth reaches 100
TYPE_POINTS: dict[str, float] = {
    DomainType.GOVERNMENT.value: 85,
    DomainType.EDUCATION.value: 85,
    DomainType.RESEARCH.value: 85,
    DomainType.MEDIA.value: 75,
    DomainType.REVIEW.value: 75,
    DomainType.DIRECTORY.value: 60,
    DomainType.COMPANY.value: 55,
    DomainType.COMMUNITY.value: 55,
    DomainType.FORUM.value: 55,
    DomainType.BLOG.value: 45,
    DomainType.SOCIAL.value: 40,
    DomainType.OTHER.value: 50,
    DomainType.UNKNOWN.value: 50,
}
AUTHORITY_BONUS = 5.0


@dataclass(frozen=True)
class RelevanceInputs:
    citation_count: int
    projects_observed: int
    weeks_with_citations: int
    weeks_since_first_seen: int
    domain_type: str
    is_authority: bool = False
    project_citation_count: int | None = None  # None when no project scope


def _log_scaled(n: int, saturation: int) -> float:
    if n <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log10(n + 1) / math.log10(saturation + 1))


def source_relevance(inputs: RelevanceInputs) -> dict[str, Any]:
    components: dict[str, float] = {
        "frequency": _log_scaled(inputs.citation_count, FREQ_SATURATION),
        "breadth": min(100.0, 100.0 * inputs.projects_observed / BREADTH_SATURATION),
        "consistency": (
            100.0
            * min(inputs.weeks_with_citations, inputs.weeks_since_first_seen)
            / max(inputs.weeks_since_first_seen, 1)
            if inputs.weeks_with_citations
            else 0.0
        ),
        "source_type": min(
            100.0,
            TYPE_POINTS.get(inputs.domain_type, 50.0)
            + (AUTHORITY_BONUS if inputs.is_authority else 0.0),
        ),
    }
    weights = dict(WEIGHTS)
    if inputs.project_citation_count is None:
        weights.pop("project_frequency")
    else:
        components["project_frequency"] = _log_scaled(
            inputs.project_citation_count, PROJECT_FREQ_SATURATION
        )
    total_weight = sum(weights.values())
    score = sum(weights[k] * components[k] for k in weights) / total_weight
    return {
        "name": "Source Relevance Score",
        "score": round(score, 1),
        "scope": "project" if inputs.project_citation_count is not None else "global",
        "components": {
            k: {"value": round(components[k], 1), "weight": weights[k]} for k in weights
        },
        "note": (
            "Initial transparent indicator of how much this source matters in the AI answers "
            "we observed; not a universal domain authority score."
        ),
    }
