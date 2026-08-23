"""Pure insight rules: facts in, candidate insights out.

Language rules (docs/competitive-insights.md): insights describe **observed
advantages**, **patterns detected** and **potential contributing factors**.
They never claim causation ("ranks higher because…"); every description says
the competitor "is associated with" the pattern, and every evidence payload
carries the same `caution` sentence.

Each analyzer returns None when the evidence does not clear its minimum bar,
so thin data produces no insight rather than a weak one.
"""

from dataclasses import dataclass, field
from typing import Any

from app.models.insights import InsightConfidence, InsightImpact, InsightType

# Below this many eligible responses no insights are produced at all.
MIN_RESPONSES = 10
# Confidence ladder on the eligible-response sample.
HIGH_SAMPLE = 50
MEDIUM_SAMPLE = 20

CAUTION = (
    "Correlation only: this observed pattern may contribute to visibility differences, "
    "but it is not proof of causation."
)

CONTENT_CATEGORIES = ("comparison", "product", "faq", "use_case", "educational")


@dataclass
class EntitySignals:
    """What the response/citation graph shows for one entity (brand or competitor)."""

    name: str
    responses_mentioning: int = 0
    mention_share: float | None = None
    recommendation_share: float | None = None
    average_position: float | None = None
    sentiment_score: float | None = None
    prompt_coverage: int = 0
    # citation footprint
    citing_domains: set[str] = field(default_factory=set)
    citations: int = 0
    domains_by_type: dict[str, set[str]] = field(default_factory=dict)  # review/community/…
    authority_domains: set[str] = field(default_factory=set)
    # content coverage: category → distinct cited page URLs
    cited_pages: dict[str, set[str]] = field(default_factory=dict)
    # evidence footprint
    research_domains: set[str] = field(default_factory=set)
    research_citations: int = 0
    # content specificity
    claims: int = 0
    claims_with_specifics: int = 0
    claim_examples: list[str] = field(default_factory=list)


@dataclass
class BrandProfile:
    """Entity clarity of the customer's own site (from crawled structured data)."""

    pages_crawled: int = 0
    has_organization_schema: bool = False
    organization_names: set[str] = field(default_factory=set)
    has_description: bool = False
    product_schema_count: int = 0
    sameas_links: int = 0
    schema_issues: int = 0


@dataclass
class CompetitorFacts:
    competitor_name: str
    sample_size: int  # eligible responses in the window
    total_prompts: int
    window_days: int
    brand: EntitySignals
    competitor: EntitySignals
    brand_profile: BrandProfile
    visibility_gap: float | None  # 5C competitive score: competitor − brand


@dataclass
class Insight:
    insight_type: InsightType
    title: str
    description: str
    evidence: dict[str, Any]
    confidence: InsightConfidence
    impact: InsightImpact
    strength: float  # 0–100, ordering only


def confidence_for(sample: int, supporting: int) -> InsightConfidence:
    """Sample = eligible responses; supporting = observations backing this insight."""
    if sample >= HIGH_SAMPLE and supporting >= MEDIUM_SAMPLE:
        return InsightConfidence.HIGH
    if sample >= MEDIUM_SAMPLE and supporting >= 5:
        return InsightConfidence.MEDIUM
    return InsightConfidence.LOW


def impact_for(ratio: float) -> InsightImpact:
    if ratio >= 3.0:
        return InsightImpact.HIGH
    if ratio >= 1.5:
        return InsightImpact.MEDIUM
    return InsightImpact.LOW


def _ratio(comp: float, brand: float) -> float:
    return comp / brand if brand else (float(comp) if comp else 0.0)


def _base_evidence(facts: CompetitorFacts) -> dict[str, Any]:
    return {
        "caution": CAUTION,
        "sample_size": facts.sample_size,
        "total_prompts": facts.total_prompts,
        "window_days": facts.window_days,
        "visibility_score_gap": facts.visibility_gap,
    }


def citation_advantage(facts: CompetitorFacts) -> Insight | None:
    b, c = facts.brand, facts.competitor
    b_domains, c_domains = len(b.citing_domains), len(c.citing_domains)
    if c_domains < 5 or c_domains < b_domains + 4 or c_domains < 1.5 * max(b_domains, 1):
        return None
    ratio = _ratio(c_domains, b_domains)
    by_type = {
        t: sorted(c.domains_by_type.get(t, set()))
        for t in ("review", "community", "media", "research")
        if c.domains_by_type.get(t)
    }
    return Insight(
        insight_type=InsightType.CITATION_ADVANTAGE,
        title=f"{c.name} has a substantially larger citation footprint",
        description=(
            f"Observed advantage: across the analyzed prompt set, {c.name} is associated "
            f"with citations from {c_domains} unique domains versus {b_domains} for your "
            "brand. A broader citation footprint is a potential contributing factor to how "
            "often AI answers surface a name; this is a pattern detected in the data, not "
            "proof of cause."
        ),
        evidence={
            **_base_evidence(facts),
            "competitor": {
                "unique_citing_domains": c_domains,
                "citations": c.citations,
                "authoritative_domains": sorted(c.authority_domains),
                "domains_by_type": by_type,
                "top_domains": sorted(c.citing_domains)[:15],
            },
            "brand": {
                "unique_citing_domains": b_domains,
                "citations": b.citations,
                "authoritative_domains": sorted(b.authority_domains),
                "top_domains": sorted(b.citing_domains)[:15],
            },
        },
        confidence=confidence_for(facts.sample_size, c.citations),
        impact=impact_for(ratio),
        strength=min(100.0, 20.0 * ratio),
    )


def content_advantage(facts: CompetitorFacts) -> Insight | None:
    b, c = facts.brand, facts.competitor
    comp_pages = {k: len(v) for k, v in c.cited_pages.items() if v}
    brand_pages = {k: len(v) for k, v in b.cited_pages.items() if v}
    lead_categories = [
        k for k in CONTENT_CATEGORIES if comp_pages.get(k, 0) > brand_pages.get(k, 0)
    ]
    total_comp = sum(comp_pages.values())
    if total_comp < 3 or len(lead_categories) < 2:
        return None
    ratio = _ratio(total_comp, sum(brand_pages.values()))
    examples = {k: sorted(c.cited_pages[k])[:3] for k in lead_categories if c.cited_pages.get(k)}
    return Insight(
        insight_type=InsightType.CONTENT_ADVANTAGE,
        title=f"AI answers cite more distinct {c.name} content types",
        description=(
            f"Pattern detected: responses cite {c.name} pages across "
            f"{len(lead_categories)} content categories where your brand has fewer or no "
            f"cited pages ({', '.join(lead_categories)}). Broader cited content coverage is "
            "a potential contributing factor; only pages that actually appeared in AI "
            "citations are compared, not the sites' full content."
        ),
        evidence={
            **_base_evidence(facts),
            "competitor_cited_pages_by_category": comp_pages,
            "brand_cited_pages_by_category": brand_pages,
            "categories_where_competitor_leads": lead_categories,
            "examples": examples,
        },
        confidence=confidence_for(facts.sample_size, total_comp),
        impact=impact_for(ratio),
        strength=min(100.0, 15.0 * len(lead_categories) + 5.0 * total_comp),
    )


def coverage_advantage(facts: CompetitorFacts) -> Insight | None:
    b, c = facts.brand, facts.competitor
    if facts.total_prompts < 3:
        return None
    if c.prompt_coverage < b.prompt_coverage + 2 or c.prompt_coverage < 1.4 * max(
        b.prompt_coverage, 1
    ):
        return None
    ratio = _ratio(c.prompt_coverage, b.prompt_coverage)
    return Insight(
        insight_type=InsightType.COVERAGE_ADVANTAGE,
        title=f"{c.name} appears across more of the prompt set",
        description=(
            f"Observed advantage: {c.name} appears in {c.prompt_coverage} of "
            f"{facts.total_prompts} analyzed prompts versus {b.prompt_coverage} for your "
            "brand. Broader prompt coverage is a potential contributing factor to overall "
            "visibility; it may also simply reflect the competitor's wider product surface."
        ),
        evidence={
            **_base_evidence(facts),
            "competitor_prompt_coverage": c.prompt_coverage,
            "brand_prompt_coverage": b.prompt_coverage,
            "competitor_mention_share": c.mention_share,
            "brand_mention_share": b.mention_share,
        },
        confidence=confidence_for(facts.sample_size, c.responses_mentioning),
        impact=impact_for(ratio),
        strength=min(100.0, 25.0 * ratio),
    )


def positioning_advantage(facts: CompetitorFacts) -> Insight | None:
    b, c = facts.brand, facts.competitor
    if c.recommendation_share is None or b.recommendation_share is None:
        return None
    rec_gap = c.recommendation_share - b.recommendation_share
    pos_gap = (
        b.average_position - c.average_position
        if b.average_position is not None and c.average_position is not None
        else None
    )
    better_position = pos_gap is not None and pos_gap >= 0.5
    if rec_gap < 15 and not better_position:
        return None
    parts = []
    if rec_gap >= 15:
        parts.append(
            f"is positively recommended in {c.recommendation_share:.0f}% of responses "
            f"versus {b.recommendation_share:.0f}% for your brand"
        )
    if better_position:
        parts.append(
            f"is listed on average at position {c.average_position:.1f} versus "
            f"{b.average_position:.1f}"
        )
    ratio = _ratio(c.recommendation_share or 0.0, b.recommendation_share or 0.0)
    return Insight(
        insight_type=InsightType.POSITIONING_ADVANTAGE,
        title=f"{c.name} is recommended more strongly and earlier",
        description=(
            f"Observed advantage: {c.name} " + " and ".join(parts) + ". Stronger, earlier "
            "placement in answers is a pattern detected in the responses themselves; the "
            "underlying reasons are not directly observable from this data."
        ),
        evidence={
            **_base_evidence(facts),
            "competitor_recommendation_share": c.recommendation_share,
            "brand_recommendation_share": b.recommendation_share,
            "competitor_average_position": c.average_position,
            "brand_average_position": b.average_position,
            "competitor_sentiment_score": c.sentiment_score,
            "brand_sentiment_score": b.sentiment_score,
        },
        confidence=confidence_for(facts.sample_size, c.responses_mentioning),
        impact=impact_for(max(ratio, 1.5 if better_position and rec_gap >= 15 else ratio)),
        strength=min(100.0, rec_gap + (20.0 if better_position else 0.0)),
    )


def evidence_advantage(facts: CompetitorFacts) -> Insight | None:
    b, c = facts.brand, facts.competitor
    research_lead = len(c.research_domains) >= 2 and len(c.research_domains) > len(
        b.research_domains
    )
    specifics_lead = c.claims_with_specifics >= 5 and c.claims_with_specifics >= 2 * max(
        b.claims_with_specifics, 1
    )
    if not research_lead and not specifics_lead:
        return None
    parts = []
    if research_lead:
        parts.append(
            f"is cited by {len(c.research_domains)} research/report sources versus "
            f"{len(b.research_domains)} for your brand"
        )
    if specifics_lead:
        parts.append(
            f"is the subject of {c.claims_with_specifics} specific, checkable claims "
            f"(numbers, dates, named capabilities) versus {b.claims_with_specifics} for "
            "your brand"
        )
    ratio = max(
        _ratio(len(c.research_domains), len(b.research_domains)),
        _ratio(c.claims_with_specifics, b.claims_with_specifics),
    )
    return Insight(
        insight_type=InsightType.EVIDENCE_ADVANTAGE,
        title=f"AI answers attach more verifiable evidence to {c.name}",
        description=(
            f"Pattern detected: {c.name} " + " and ".join(parts) + ". Answers that can "
            "point at research, statistics and concrete claims are a potential "
            "contributing factor to favourable treatment; whether the evidence causes the "
            "visibility cannot be determined from this data."
        ),
        evidence={
            **_base_evidence(facts),
            "competitor_research_domains": sorted(c.research_domains),
            "brand_research_domains": sorted(b.research_domains),
            "competitor_research_citations": c.research_citations,
            "brand_research_citations": b.research_citations,
            "competitor_specific_claims": c.claims_with_specifics,
            "brand_specific_claims": b.claims_with_specifics,
            "competitor_total_claims": c.claims,
            "brand_total_claims": b.claims,
            "claim_examples": c.claim_examples[:5],
        },
        confidence=confidence_for(
            facts.sample_size, c.research_citations + c.claims_with_specifics
        ),
        impact=impact_for(ratio),
        strength=min(100.0, 10.0 * (len(c.research_domains) + c.claims_with_specifics)),
    )


def entity_advantage(facts: CompetitorFacts) -> Insight | None:
    """Brand-side pattern only: the competitor is materially more visible while the
    brand's own structured data has clear gaps. Competitor sites are not crawled, so
    this is framed strictly as a potential contributing factor and never exceeds
    medium confidence."""
    b_profile = facts.brand_profile
    if facts.visibility_gap is None or facts.visibility_gap < 10:
        return None
    if b_profile.pages_crawled == 0:
        return None
    gaps: list[str] = []
    if not b_profile.has_organization_schema:
        gaps.append("no Organization schema was found on your site")
    if b_profile.has_organization_schema and not b_profile.has_description:
        gaps.append("your Organization schema has no description")
    if b_profile.product_schema_count == 0:
        gaps.append("no Product schema was found on your site")
    if b_profile.sameas_links == 0:
        gaps.append("no sameAs links connect your site to external profiles")
    if len(b_profile.organization_names) > 1:
        gaps.append(
            "your pages declare inconsistent organization names ("
            + ", ".join(sorted(b_profile.organization_names))
            + ")"
        )
    if len(gaps) < 2:
        return None
    confidence = confidence_for(facts.sample_size, facts.sample_size)
    if confidence is InsightConfidence.HIGH:
        confidence = InsightConfidence.MEDIUM
    return Insight(
        insight_type=InsightType.ENTITY_ADVANTAGE,
        title=f"Entity clarity gaps on your site while {facts.competitor_name} leads",
        description=(
            f"Potential contributing factor: {facts.competitor_name} shows a materially "
            f"higher competitive visibility score (+{facts.visibility_gap:.0f} points) "
            f"while your own site's machine-readable identity has gaps: {'; '.join(gaps)}. "
            "Competitor sites were not crawled, so this compares your site against what AI "
            "engines would need, not against the competitor's markup; it is not proof of "
            "cause."
        ),
        evidence={
            **_base_evidence(facts),
            "brand_pages_crawled": b_profile.pages_crawled,
            "brand_has_organization_schema": b_profile.has_organization_schema,
            "brand_has_description": b_profile.has_description,
            "brand_product_schema_count": b_profile.product_schema_count,
            "brand_sameas_links": b_profile.sameas_links,
            "brand_organization_names": sorted(b_profile.organization_names),
            "brand_schema_issues": b_profile.schema_issues,
            "gaps": gaps,
            "competitor_site_analyzed": False,
        },
        confidence=confidence,
        impact=InsightImpact.MEDIUM if len(gaps) >= 3 else InsightImpact.LOW,
        strength=min(100.0, 15.0 * len(gaps) + facts.visibility_gap),
    )


ANALYZERS = (
    citation_advantage,
    content_advantage,
    coverage_advantage,
    positioning_advantage,
    evidence_advantage,
    entity_advantage,
)


def analyze_competitor(facts: CompetitorFacts) -> list[Insight]:
    if facts.sample_size < MIN_RESPONSES:
        return []
    return [i for i in (a(facts) for a in ANALYZERS) if i is not None]
