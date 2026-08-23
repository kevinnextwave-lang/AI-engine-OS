"""Research Agent (Milestone 6B): evidence-backed opportunities, no asset changes.

The agent is deliberately deterministic: every number it reports comes from a
tool call over the project's own data, so nothing can be hallucinated. It
follows the three-step research process — identify significant gaps, validate
evidence, prioritize — and keeps three categories strictly apart in every
finding:

    observed        a measured fact ("QuickBooks appeared in 86% of responses")
    inference       what the fact suggests ("stronger AI visibility here")
    recommendation  what to investigate or prepare — never an executed change

Proposed actions are suggestions only. Anything that would touch
customer-facing content is emitted at medium risk, which the orchestrator
forces through human approval.
"""

from dataclasses import dataclass, field
from typing import Any

from app.agents.base import Agent
from app.agents.context import AgentContext, ContextSpec
from app.agents.results import AgentResult, AgentStatus, ProposedAction
from app.competitors.normalize import normalize_name
from app.models.agents import ActionRiskLevel

VERSION = "1.0"
MAX_FINDINGS = 7
MIN_FINDINGS_TARGET = 3

# Prioritization weights (0–100 score).
WEIGHTS = {
    "business_relevance": 25.0,
    "visibility_impact": 25.0,
    "competitor_advantage": 20.0,
    "evidence_strength": 20.0,
    "effort": 10.0,  # inverted: lower effort scores higher
}
EFFORT_SCORE = {"low": 1.0, "medium": 0.6, "high": 0.3}
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "insufficient": 0}

# Content-gap type → suggested action (all suggestions, never automatic).
GAP_ACTION = {
    "missing_comparison": ("create_comparison_page", "Create comparison page", "medium", "high"),
    "missing_topic": ("create_content_brief", "Create content brief", "medium", "medium"),
    "missing_faq": ("create_content_brief", "Create content brief (FAQ)", "medium", "medium"),
    "missing_use_case": (
        "create_content_brief",
        "Create content brief (use case)",
        "medium",
        "medium",
    ),
    "missing_product_detail": (
        "create_content_brief",
        "Create content brief (product detail)",
        "medium",
        "medium",
    ),
    "weak_topic": ("optimize_existing_page", "Optimize existing page", "medium", "low"),
    "missing_evidence": ("add_supporting_evidence", "Add supporting evidence", "medium", "medium"),
}


@dataclass
class Candidate:
    """One scored research finding + its opportunity, built only from tool data."""

    key: str
    title: str
    problem: str
    observed: str
    inference: str
    recommendation: str
    evidence: dict[str, Any]
    confidence: str
    impact: str
    why_now: str
    recommended_action: str
    expected_area_of_impact: str
    action: ProposedAction | None
    components: dict[str, float] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return round(sum(WEIGHTS[k] * v for k, v in self.components.items()), 1)


class ResearchAgent(Agent):
    name = "research"
    version = VERSION
    instructions = (
        "Identify evidence-backed AI-visibility opportunities from the project's own "
        "data. Report observed facts, inferences and recommendations as separate "
        "statements. Never propose changing customer assets directly."
    )
    # Targeted context only; everything else through tools at run time.
    context_spec = ContextSpec(prompts=20, competitors=20)

    async def run(self, context: AgentContext) -> AgentResult:
        tools = context.tools
        if tools is None:  # pragma: no cover - the orchestrator always provides tools
            raise RuntimeError("Research agent requires a ToolBox")
        warnings: list[str] = []

        visibility = await tools.call("get_visibility_metrics")
        competitive = await tools.call("get_competitive_visibility")
        citation_gaps = await tools.call("get_citation_gaps", limit=10)
        content_gaps = await tools.call("get_content_gaps", limit=10)
        insights = await tools.call("get_competitive_insights", limit=10)
        candidates_raw = await tools.call("get_competitor_candidates", limit=5)
        entities = await tools.call("get_entity_data", limit=50)
        pages = await tools.call("get_pages", limit=50)
        responses = await tools.call("get_ai_responses", limit=10)

        sample = competitive.get("data_quality", {}).get("sample_size") or 0
        if sample < 10:
            warnings.append(
                f"Only {sample} eligible AI responses in the window — findings are "
                "capped at low confidence."
            )

        candidates: list[Candidate] = []
        candidates += self._competitor_gaps(competitive, insights, sample)
        competitor_hosts = {
            (c.get("domain") or "").lower().removeprefix("www.")
            for c in context.competitors
            if c.get("domain")
        }
        competitor_names = {normalize_name(c["name"]) for c in context.competitors if c.get("name")}
        candidates += self._citation_gaps(citation_gaps, sample, competitor_hosts, competitor_names)
        candidates += self._content_gaps(content_gaps, sample)
        candidates += self._entity_representation(entities, pages, competitive)
        candidates += self._emerging_competitors(candidates_raw)
        if sample < 10:
            for c in candidates:
                if CONFIDENCE_RANK[c.confidence] > CONFIDENCE_RANK["low"]:
                    c.confidence = "low"

        # prioritize; keep the strongest 3–7 (fewer only if the data offers fewer)
        candidates.sort(key=lambda c: (-c.score, c.title))
        top = candidates[:MAX_FINDINGS]
        if len(top) < MIN_FINDINGS_TARGET and len(candidates) >= len(top):
            warnings.append(
                f"Only {len(top)} findings met the evidence bar (target ≥ {MIN_FINDINGS_TARGET})."
            )

        findings = [
            {
                "title": c.title,
                "problem": c.problem,
                "evidence": c.evidence,
                "impact": c.impact,
                "confidence": c.confidence,
                "statements": {
                    "observed": c.observed,
                    "inference": c.inference,
                    "recommendation": c.recommendation,
                },
                "priority_score": c.score,
                "priority_components": c.components,
            }
            for c in top
        ]
        opportunities = [
            {
                "title": c.title,
                "why_now": c.why_now,
                "recommended_action": c.recommended_action,
                "expected_area_of_impact": c.expected_area_of_impact,
                "evidence": c.evidence,
                "confidence": c.confidence,
            }
            for c in top
        ]
        summary = self._executive_summary(visibility, competitive, top)
        return AgentResult(
            agent_name=self.name,
            agent_version=self.version,
            status=AgentStatus.COMPLETED,
            summary=summary,
            findings=findings,
            recommendations=opportunities,
            evidence={
                "visibility": visibility,
                "sample_size": sample,
                "responses_reviewed": len(responses),
                "priority_weights": WEIGHTS,
                "statement_categories": ["observed", "inference", "recommendation"],
            },
            proposed_actions=[c.action for c in top if c.action is not None],
            confidence=_overall_confidence(top),
            warnings=warnings,
        )

    # -- step 1 + 2: gaps with validated evidence --------------------------------------

    def _competitor_gaps(
        self, competitive: dict[str, Any], insights: list[dict[str, Any]], sample: int
    ) -> list[Candidate]:
        out: list[Candidate] = []
        entities = {e["name"]: e for e in competitive.get("entities", [])}
        brand = next((e for e in entities.values() if e["is_brand"]), None)
        for adv in competitive.get("advantages", []):
            if not adv.get("material"):
                continue
            name = adv["competitor"]
            comp = entities.get(name, {})
            related = [i for i in insights if name in (i.get("title") or "")]
            confidence = "high" if sample >= 50 else "medium" if sample >= 20 else "low"
            share = comp.get("mention_share")
            brand_share = brand.get("mention_share") if brand else None
            out.append(
                Candidate(
                    key=f"competitor:{name}",
                    title=f"{name} holds a material AI-visibility lead",
                    problem=(
                        f"{name} outperforms the brand across the analyzed prompt set "
                        f"(+{adv['advantage']} score points)."
                    ),
                    observed=(
                        f"{name} appeared in {_pct(share)} of eligible AI responses vs "
                        f"{_pct(brand_share)} for the brand (sample {sample})."
                    ),
                    inference=(f"{name} currently has stronger AI visibility for this prompt set."),
                    recommendation=(
                        f"Investigate the content and citation sources associated with "
                        f"the responses that feature {name}, starting with: "
                        + (", ".join(adv.get("where_they_win", [])) or "overall visibility")
                        + "."
                    ),
                    evidence={
                        "advantage_points": adv["advantage"],
                        "where_they_win": adv.get("where_they_win", []),
                        "competitor_mention_share": share,
                        "brand_mention_share": brand_share,
                        "supporting_insights": [
                            {"id": i["id"], "type": i["insight_type"], "title": i["title"]}
                            for i in related[:3]
                        ],
                        "sample_size": sample,
                    },
                    confidence=confidence,
                    impact="high",
                    why_now=(
                        f"The gap is material now (+{adv['advantage']} points) and "
                        "measured on current responses."
                    ),
                    recommended_action="Investigate citation opportunity",
                    expected_area_of_impact="competitive AI visibility",
                    action=ProposedAction(
                        action_type="investigate_citation_opportunity",
                        description=(
                            f"Investigate the sources and content behind {name}'s "
                            "visibility lead (suggestion only)."
                        ),
                        payload={"competitor": name, "advantage": adv["advantage"]},
                        risk_level=ActionRiskLevel.LOW,
                        approval_required=False,
                    ),
                    components={
                        "business_relevance": 1.0,
                        "visibility_impact": min(1.0, (adv["advantage"] or 0) / 30.0),
                        "competitor_advantage": 1.0,
                        "evidence_strength": min(1.0, 0.5 + 0.25 * len(related)),
                        "effort": EFFORT_SCORE["low"],
                    },
                )
            )
        return out

    def _citation_gaps(
        self,
        gaps: list[dict[str, Any]],
        sample: int,
        competitor_hosts: set[str],
        competitor_names: set[str],
    ) -> list[Candidate]:
        out = []
        for gap in gaps:
            if gap["opportunity_score"] < 60 or gap["confidence"] == "insufficient":
                continue
            host = (gap["domain"] or "").lower()
            if _is_competitor_site(host, competitor_hosts, competitor_names):
                continue  # a competitor's own site is not a place the brand can be cited
            domain = gap["domain"]
            out.append(
                Candidate(
                    key=f"citation:{domain}",
                    title=f"Citation gap on {domain}",
                    problem=(
                        f"AI answers cite {domain} for the category while the brand is "
                        "under-represented there."
                    ),
                    observed=(
                        f"{domain}: {gap['competitor_citations']} competitor-related "
                        f"citations vs {gap['brand_citations']} brand-related "
                        f"({gap['gap_type']}, opportunity {gap['opportunity_score']:.0f})."
                    ),
                    inference=(
                        f"Answers drawn from {domain} currently surface competitors "
                        "rather than the brand."
                    ),
                    recommendation=(
                        f"Investigate legitimate presence options on {domain} before "
                        "any outreach; do not pursue manipulative placements."
                    ),
                    evidence={
                        "citation_gap_id": gap["id"],
                        "domain": domain,
                        "gap_type": gap["gap_type"],
                        "opportunity_score": gap["opportunity_score"],
                        "brand_citations": gap["brand_citations"],
                        "competitor_citations": gap["competitor_citations"],
                    },
                    confidence=gap["confidence"],
                    impact="high" if gap["opportunity_score"] >= 75 else "medium",
                    why_now=(
                        f"The source is being cited in current responses "
                        f"(opportunity {gap['opportunity_score']:.0f})."
                    ),
                    recommended_action="Investigate citation opportunity",
                    expected_area_of_impact="citation footprint",
                    action=ProposedAction(
                        action_type="investigate_citation_opportunity",
                        description=f"Investigate citation opportunity on {domain} (suggestion).",
                        payload={"domain": domain, "citation_gap_id": gap["id"]},
                        risk_level=ActionRiskLevel.LOW,
                        approval_required=False,
                    ),
                    components={
                        "business_relevance": 0.8,
                        "visibility_impact": min(1.0, gap["opportunity_score"] / 100.0),
                        "competitor_advantage": min(
                            1.0,
                            gap["competitor_citations"]
                            / max(1, gap["brand_citations"] + gap["competitor_citations"]),
                        ),
                        "evidence_strength": min(
                            1.0, CONFIDENCE_RANK.get(gap["confidence"], 0) / 3
                        ),
                        "effort": EFFORT_SCORE["medium"],
                    },
                )
            )
        return out

    def _content_gaps(self, gaps: list[dict[str, Any]], sample: int) -> list[Candidate]:
        out = []
        for gap in gaps:
            if gap["opportunity_score"] < 60 or gap["confidence"] == "insufficient":
                continue
            action_type, action_label, risk, effort = GAP_ACTION.get(
                gap["gap_type"],
                ("create_content_brief", "Create content brief", "medium", "medium"),
            )
            out.append(
                Candidate(
                    key=f"content:{gap['topic']}:{gap['gap_type']}",
                    title=f"Content gap: {gap['topic']}",
                    problem=(
                        f"Competitors appear in AI answers about “{gap['topic']}” while "
                        f"site coverage is weak or missing ({gap['gap_type']})."
                    ),
                    observed=(
                        f"Content gap “{gap['topic']}” ({gap['gap_type']}) with "
                        f"opportunity {gap['opportunity_score']:.0f} and "
                        f"{gap['confidence']} confidence."
                    ),
                    inference=(
                        "The prompt set asks about this topic and competitors are the "
                        "names answers currently surface."
                    ),
                    recommendation=(
                        f"{action_label} for “{gap['topic']}” and review it before "
                        "publishing anything."
                    ),
                    evidence={
                        "content_gap_id": gap["id"],
                        "topic": gap["topic"],
                        "gap_type": gap["gap_type"],
                        "opportunity_score": gap["opportunity_score"],
                    },
                    confidence=gap["confidence"],
                    impact="high" if gap["opportunity_score"] >= 80 else "medium",
                    why_now=(
                        "The prompts driving this gap are being asked now "
                        f"(opportunity {gap['opportunity_score']:.0f})."
                    ),
                    recommended_action=action_label,
                    expected_area_of_impact="content coverage",
                    action=ProposedAction(
                        action_type=action_type,
                        description=f"{action_label} for “{gap['topic']}” (suggestion only).",
                        payload={"content_gap_id": gap["id"], "topic": gap["topic"]},
                        # touches customer-facing content → never auto-approved
                        risk_level=ActionRiskLevel.MEDIUM,
                        approval_required=True,
                    ),
                    components={
                        "business_relevance": 1.0 if risk == "medium" else 0.8,
                        "visibility_impact": min(1.0, gap["opportunity_score"] / 100.0),
                        "competitor_advantage": 0.7,
                        "evidence_strength": min(
                            1.0, CONFIDENCE_RANK.get(gap["confidence"], 0) / 3
                        ),
                        "effort": EFFORT_SCORE[effort],
                    },
                )
            )
        return out

    def _entity_representation(
        self,
        entities: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        competitive: dict[str, Any],
    ) -> list[Candidate]:
        if not pages:
            return []  # nothing crawled — no evidence either way
        org_types = {"organization", "brand", "corporation", "localbusiness"}
        orgs = [e for e in entities if (e.get("entity_type") or "").lower() in org_types]
        has_sameas = any(e.get("same_as") for e in orgs)
        missing = []
        if not orgs:
            missing.append("no Organization schema")
        elif not has_sameas:
            missing.append("no sameAs links on the Organization entity")
        if orgs and not any(e.get("description") for e in orgs):
            missing.append("no Organization description")
        if not missing:
            return []
        observed = (
            f"Crawled {len(pages)} pages; found {len(orgs)} Organization-type entities; "
            + "; ".join(missing)
            + "."
        )
        return [
            Candidate(
                key="entity:organization",
                title="Weak machine-readable brand identity",
                problem="The site's structured data under-describes the organization.",
                observed=observed,
                inference=(
                    "AI engines have less machine-readable identity to associate the "
                    "brand with than the markup could provide."
                ),
                recommendation=(
                    "Improve the Organization entity (schema, description, sameAs) and "
                    "re-crawl to verify."
                ),
                evidence={
                    "pages_crawled": len(pages),
                    "organization_entities": len(orgs),
                    "issues": missing,
                },
                confidence="medium",
                impact="medium",
                why_now="Fixable on owned pages without external dependencies.",
                recommended_action="Improve organization entity",
                expected_area_of_impact="entity clarity",
                action=ProposedAction(
                    action_type="improve_organization_entity",
                    description="Improve Organization structured data (suggestion only).",
                    payload={"issues": missing},
                    # customer-facing markup change → approval required
                    risk_level=ActionRiskLevel.MEDIUM,
                    approval_required=True,
                ),
                components={
                    "business_relevance": 0.7,
                    "visibility_impact": 0.5,
                    "competitor_advantage": 0.5,
                    "evidence_strength": 0.9,  # directly observed on the crawl
                    "effort": EFFORT_SCORE["low"],
                },
            )
        ]

    def _emerging_competitors(self, candidates: list[dict[str, Any]]) -> list[Candidate]:
        out = []
        for c in candidates:
            if c.get("status") != "new" or c.get("confidence_label") not in ("high", "medium"):
                continue
            out.append(
                Candidate(
                    key=f"emerging:{c['name']}",
                    title=f"Emerging competitor candidate: {c['name']}",
                    problem=(
                        f"{c['name']} keeps appearing in AI responses but is not a "
                        "configured competitor."
                    ),
                    observed=(
                        f"Discovery surfaced {c['name']} with confidence "
                        f"{c['confidence']:.2f} ({c['confidence_label']}) from "
                        f"{c.get('responses') or 'several'} responses."
                    ),
                    inference=(f"{c['name']} may be competing for the same AI answers."),
                    recommendation=(
                        f"Review the candidate and accept or reject {c['name']} in "
                        "competitor discovery."
                    ),
                    evidence={
                        "candidate_id": c["id"],
                        "name": c["name"],
                        "confidence": c["confidence"],
                        "responses": c.get("responses"),
                    },
                    confidence=c["confidence_label"],
                    impact="medium",
                    why_now="The candidate is unreviewed and present in current answers.",
                    recommended_action="Review competitor candidate",
                    expected_area_of_impact="competitive coverage",
                    action=None,  # review happens in the discovery workflow, not via actions
                    components={
                        "business_relevance": 0.6,
                        "visibility_impact": 0.4,
                        "competitor_advantage": 0.6,
                        "evidence_strength": min(1.0, float(c["confidence"])),
                        "effort": EFFORT_SCORE["low"],
                    },
                )
            )
        return out

    # -- output ------------------------------------------------------------------------

    @staticmethod
    def _executive_summary(
        visibility: dict[str, Any], competitive: dict[str, Any], top: list[Candidate]
    ) -> str:
        parts = []
        score = visibility.get("score")
        sample = competitive.get("data_quality", {}).get("sample_size")
        if score is not None:
            parts.append(f"AI Visibility Score {score} over {sample} eligible responses.")
        else:
            parts.append(f"Insufficient responses for a visibility score (sample {sample}).")
        material = [a for a in competitive.get("advantages", []) if a.get("material")]
        if material:
            names = ", ".join(a["competitor"] for a in material[:3])
            parts.append(f"Material competitor lead(s): {names}.")
        if top:
            parts.append(
                f"Top opportunity: {top[0].title} (priority {top[0].score:.0f}, "
                f"{top[0].confidence} confidence)."
            )
            parts.append(f"{len(top)} prioritized findings in total; all are suggestions.")
        else:
            parts.append("No findings met the evidence bar.")
        return " ".join(parts)


def _is_competitor_site(host: str, competitor_hosts: set[str], competitor_names: set[str]) -> bool:
    """True when the cited host is a configured competitor's own site: an exact /
    subdomain match on its domain, or a DNS label equal to its normalized name
    (quickbooks.intuit.com → label "quickbooks")."""
    if not host:
        return False
    if any(host == c or host.endswith("." + c) for c in competitor_hosts if c):
        return True
    labels = set(host.split("."))
    return any(name and name in labels for name in competitor_names)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}%"


def _overall_confidence(top: list[Candidate]) -> float | None:
    if not top:
        return None
    return round(sum(CONFIDENCE_RANK[c.confidence] for c in top) / (3 * len(top)), 2)
