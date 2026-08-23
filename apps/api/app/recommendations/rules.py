"""Recommendation rules — pure functions. See docs/recommendations.md.

Priority (critical / high / medium / low) is derived from a **priority
score** that combines the gap's Citation Opportunity Score with confidence,
business relevance, competitor gap and sample size:

    priority_score = opportunity × confidence_factor × (0.7 + 0.3 × business_relevance)

    confidence_factor: high 1.0, medium 0.85, low 0.6   (insufficient ⇒ no recommendation)
    business_relevance: share of the prompts citing the source that are commercial
                        (comparison / recommendation / pricing / alternative, or
                        consideration / decision / purchase funnel stages)

    critical  score ≥ 80 AND confidence = high AND competitor_gap ≥ 0.6 AND relevant responses ≥ 20
    high      score ≥ 65
    medium    score ≥ 40
    low       otherwise

competitor_gap = (competitor − brand) / (competitor + brand) on the source's citations.

Every recommendation carries five explanations: what we observed, why it
matters, what to investigate, what evidence supports it, how confident we are.
"""

from dataclasses import dataclass, field
from typing import Any

from app.models.gaps import GapConfidence, GapType
from app.models.recommendations import RecommendationPriority

CONFIDENCE_FACTOR = {
    GapConfidence.HIGH: 1.0,
    GapConfidence.MEDIUM: 0.85,
    GapConfidence.LOW: 0.6,
}
COMMERCIAL_CATEGORIES = frozenset({"comparison", "recommendation", "pricing", "alternative"})
COMMERCIAL_STAGES = frozenset({"consideration", "decision", "purchase"})
CRITICAL_MIN_SCORE = 80.0
CRITICAL_MIN_GAP = 0.6
CRITICAL_MIN_RESPONSES = 20
HIGH_MIN_SCORE = 65.0
MEDIUM_MIN_SCORE = 40.0

# Gap types that become citation recommendations. Shared/overrepresented sources are not
# opportunities; underrepresented ones only when the source is relevant enough.
RECOMMENDABLE_GAPS = {
    GapType.BRAND_ABSENT,
    GapType.COMPETITOR_ADVANTAGE,
    GapType.EMERGING_SOURCE,
    GapType.SOURCE_UNDERREPRESENTED,
}
UNDERREPRESENTED_MIN_RELEVANCE = 50.0

# "Create original research" requires all three conditions.
RESEARCH_MIN_COMPETITOR_CITATIONS = 3
RESEARCH_MIN_RESPONSES = 2
RESEARCH_MIN_COMMERCIAL_SHARE = 0.5


@dataclass(frozen=True)
class GapFacts:
    """What the recommendation engine knows about one citation gap."""

    domain: str
    display_name: str
    source_type: str
    gap_type: GapType
    opportunity_score: float
    confidence: GapConfidence
    brand_citations: int
    competitor_citations: int
    competitors: dict[str, int]
    relevant_responses: int
    eligible_responses: int
    prompts_citing: int
    total_prompts: int
    source_relevance: float
    commercial_prompts: int  # prompts citing the source that are commercial
    top_pages: list[dict[str, Any]] = field(default_factory=list)
    window_days: int = 90


def business_relevance(commercial_prompts: int, prompts_citing: int) -> float:
    return commercial_prompts / prompts_citing if prompts_citing else 0.0


def competitor_gap(brand: int, competitor: int) -> float:
    return (competitor - brand) / (competitor + brand) if (competitor + brand) else 0.0


def priority_score(facts: GapFacts) -> float:
    factor = CONFIDENCE_FACTOR.get(facts.confidence, 0.0)
    relevance = business_relevance(facts.commercial_prompts, facts.prompts_citing)
    return round(facts.opportunity_score * factor * (0.7 + 0.3 * relevance), 1)


def priority_for(facts: GapFacts) -> tuple[RecommendationPriority, float]:
    score = priority_score(facts)
    gap = competitor_gap(facts.brand_citations, facts.competitor_citations)
    if (
        score >= CRITICAL_MIN_SCORE
        and facts.confidence is GapConfidence.HIGH
        and gap >= CRITICAL_MIN_GAP
        and facts.relevant_responses >= CRITICAL_MIN_RESPONSES
    ):
        return RecommendationPriority.CRITICAL, score
    if score >= HIGH_MIN_SCORE:
        return RecommendationPriority.HIGH, score
    if score >= MEDIUM_MIN_SCORE:
        return RecommendationPriority.MEDIUM, score
    return RecommendationPriority.LOW, score


def is_recommendable(facts: GapFacts) -> bool:
    if facts.confidence is GapConfidence.INSUFFICIENT:
        return False
    if facts.gap_type not in RECOMMENDABLE_GAPS:
        return False
    if (
        facts.source_type == "company"
        and facts.brand_citations == 0
        and facts.competitor_citations > 0
    ):
        return False  # a competitor's own website is not a place the brand can be cited
    if facts.gap_type is GapType.SOURCE_UNDERREPRESENTED:
        return facts.source_relevance >= UNDERREPRESENTED_MIN_RELEVANCE
    return True


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "n/a"


def citation_explanation(facts: GapFacts) -> dict[str, str]:
    comps = sorted(facts.competitors.items(), key=lambda kv: -kv[1])[:3]
    comp_text = ", ".join(f"{n} ({c})" for n, c in comps) or "no configured competitor"
    relevance = business_relevance(facts.commercial_prompts, facts.prompts_citing)
    observed = (
        f"In the last {facts.window_days} days, {facts.display_name} was cited in "
        f"{facts.relevant_responses} of {facts.eligible_responses} relevant AI responses "
        f"({_pct(facts.relevant_responses, facts.eligible_responses)}) across "
        f"{facts.prompts_citing} of {facts.total_prompts} prompts. Competitor-related citations: "
        f"{facts.competitor_citations} ({comp_text}); brand-related citations: "
        f"{facts.brand_citations}."
    )
    why = {
        GapType.BRAND_ABSENT: (
            "AI engines already consult this source for the category and currently find "
            "competitors there but not the brand, so answers drawn from it cannot mention you."
        ),
        GapType.COMPETITOR_ADVANTAGE: (
            "AI engines draw on this source for the category and competitors appear there far "
            "more often than the brand, which shapes which names the answers recommend."
        ),
        GapType.EMERGING_SOURCE: (
            "This source has only recently started being cited and is growing; early presence "
            "on a rising source is cheaper than catching up later."
        ),
        GapType.SOURCE_UNDERREPRESENTED: (
            "This source is relevant and frequently cited, yet neither you nor competitors are "
            "clearly represented on it — open ground in the category."
        ),
    }[facts.gap_type]
    why += (
        f" {_pct(facts.commercial_prompts, facts.prompts_citing)} of the prompts that surface it "
        "are commercial (comparison, recommendation, pricing or alternative questions)."
        if facts.prompts_citing
        else ""
    )
    investigate = (
        f"Check whether {facts.display_name} is genuinely relevant to your market and whether "
        "legitimate editorial, review, partnership, research or community opportunities exist "
        "there. Look at the pages competitors are cited from and whether an equivalent, "
        "policy-compliant presence is available to you. Do not pursue paid placements disguised "
        "as editorial, fake reviews, link schemes or other manipulation."
    )
    evidence = (
        f"{facts.prompts_citing} relevant prompts; {facts.competitor_citations} competitor "
        f"citations vs {facts.brand_citations} brand citations; Source Relevance Score "
        f"{round(facts.source_relevance)}; Citation Opportunity Score "
        f"{round(facts.opportunity_score)}; business relevance {round(100 * relevance)}%."
    )
    confidence = {
        GapConfidence.HIGH: "High: a large sample of responses cites this source consistently.",
        GapConfidence.MEDIUM: "Medium: a moderate sample; the pattern is clear but not yet robust.",
        GapConfidence.LOW: (
            "Low: few responses so far — treat this as a lead to verify, not a fact."
        ),
        GapConfidence.INSUFFICIENT: "Insufficient data.",
    }[facts.confidence]
    confidence += " A citation from this source would not guarantee better AI visibility."
    return {
        "observed": observed,
        "why_it_matters": why,
        "investigate": investigate,
        "evidence_summary": evidence,
        "confidence_statement": confidence,
    }


def citation_title(facts: GapFacts) -> str:
    return f"Investigate {facts.display_name} visibility opportunity"


def citation_description(facts: GapFacts) -> str:
    base = (
        f"Relevant AI responses cite {facts.display_name} frequently when discussing this category."
    )
    if facts.gap_type is GapType.BRAND_ABSENT:
        return base + " Competitors appear there while the project brand does not appear at all."
    if facts.gap_type is GapType.COMPETITOR_ADVANTAGE:
        return base + " Competitors appear substantially more often than the project brand."
    if facts.gap_type is GapType.EMERGING_SOURCE:
        return (
            f"{facts.display_name} has recently started to be cited in relevant AI responses and "
            "is growing, without citing the project brand."
        )
    return base + " Neither the brand nor configured competitors are clearly represented there."


@dataclass(frozen=True)
class ResearchFacts:
    """Evidence for a 'create original research' recommendation."""

    competitor_research_citations: int
    brand_research_citations: int
    research_responses: int
    research_sources: list[dict[str, Any]]  # {domain, citations, competitors}
    commercial_prompts: int
    prompts_citing: int
    competitors: dict[str, int]
    eligible_responses: int
    window_days: int = 90


def research_is_warranted(facts: ResearchFacts) -> tuple[bool, list[str]]:
    """All three conditions must hold; the reasons list explains any refusal."""
    reasons: list[str] = []
    if facts.competitor_research_citations < RESEARCH_MIN_COMPETITOR_CITATIONS:
        reasons.append("competitors are not being cited for research")
    if facts.research_responses < RESEARCH_MIN_RESPONSES:
        reasons.append("research sources appear in too few responses")
    if facts.brand_research_citations > 0:
        reasons.append("the brand is already cited for research (no content gap)")
    share = business_relevance(facts.commercial_prompts, facts.prompts_citing)
    if share < RESEARCH_MIN_COMMERCIAL_SHARE:
        reasons.append("the topic is not commercially relevant enough")
    return (not reasons), reasons


def research_confidence(facts: ResearchFacts) -> GapConfidence:
    if facts.research_responses >= 20 and facts.eligible_responses >= 50:
        return GapConfidence.HIGH
    if facts.research_responses >= 8 and facts.eligible_responses >= 20:
        return GapConfidence.MEDIUM
    return GapConfidence.LOW


def research_explanation(facts: ResearchFacts, confidence: GapConfidence) -> dict[str, str]:
    comps = ", ".join(
        f"{n} ({c})" for n, c in sorted(facts.competitors.items(), key=lambda kv: -kv[1])[:3]
    )
    sources = ", ".join(s["domain"] for s in facts.research_sources[:4])
    return {
        "observed": (
            f"In the last {facts.window_days} days, AI responses cited research-type sources "
            f"({sources}) in {facts.research_responses} responses; "
            f"{facts.competitor_research_citations} of those citations relate to competitors "
            f"({comps}) and {facts.brand_research_citations} to the brand."
        ),
        "why_it_matters": (
            "AI engines use research, reports and studies as evidence when answering commercial "
            "questions in this category; competitors currently supply that evidence and the brand "
            "does not."
        ),
        "investigate": (
            "Consider whether you hold data that could support original, verifiable research "
            "(benchmarks, surveys, usage data) on the topics these prompts ask about, and where "
            "such research would be published and reviewed. Only publish findings you can stand "
            "behind."
        ),
        "evidence_summary": (
            f"{facts.competitor_research_citations} competitor research citations across "
            f"{facts.research_responses} responses; {facts.commercial_prompts} of "
            f"{facts.prompts_citing} citing prompts are commercial; brand research citations: "
            f"{facts.brand_research_citations}."
        ),
        "confidence_statement": {
            GapConfidence.HIGH: "High: research citations are frequent and consistent.",
            GapConfidence.MEDIUM: "Medium: a moderate number of research citations.",
            GapConfidence.LOW: (
                "Low: only a few research citations so far — verify before investing."
            ),
            GapConfidence.INSUFFICIENT: "Insufficient data.",
        }[confidence]
        + " Publishing research does not guarantee it will be cited.",
    }
