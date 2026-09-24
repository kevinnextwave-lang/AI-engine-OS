"""Content Strategy Agent (Milestone 6C): opportunities → content briefs.

The agent does NOT write content. For each verified content opportunity it
determines what should be created, why it matters, which audience it serves,
which of the project's actual AI prompts it targets, which competitors
currently dominate them, and which evidence must be collected. Everything in a
brief is derived from observed project data; evidence requirements state what
real material is needed and explicitly forbid fabrication — no invented
statistics, testimonials, citations, reviews or credentials, and no claims of
guaranteed AI ranking.

Briefs are persisted through the framework's only write tool
(`save_content_brief`: validated, project-scoped, draft-on-insert, review
status preserved on re-save).
"""

from typing import Any

from app.agents.base import Agent
from app.agents.context import AgentContext, ContextSpec
from app.agents.results import AgentResult, AgentStatus, ProposedAction
from app.content_gaps.topics import topic_keywords
from app.models.agents import ActionRiskLevel

VERSION = "1.0"
MAX_BRIEFS = 5
MIN_OPPORTUNITY = 60.0
FABRICATION_RULE = (
    "Use only real, verifiable material. Do not fabricate statistics, customer "
    "testimonials, citations, reviews or credentials, and do not claim guaranteed "
    "AI rankings."
)

# gap_type → (content_type, title template)
GAP_CONTENT_TYPE = {
    "missing_comparison": "comparison_page",
    "missing_faq": "faq_page",
    "missing_use_case": "use_case_page",
    "missing_product_detail": "product_page",
    "missing_topic": "new_article",
    "weak_topic": "existing_page_optimization",
    "missing_evidence": "research_content",
}

INTENT_BY_CATEGORY = {
    "comparison": "Compare specific options side by side before shortlisting one.",
    "alternative": "Find credible alternatives to a tool the user already knows.",
    "recommendation": "Get a trustworthy recommendation for the best option.",
    "pricing": "Understand what the product costs and what is included.",
    "product": "Understand what the product does and whether it fits.",
    "problem_solution": "Solve a concrete task or problem step by step.",
    "industry": "Understand how the category applies to a specific industry.",
    "discovery": "Discover which tools exist for a need.",
}
AUDIENCE_BY_STAGE = {
    "awareness": "people researching the problem space, not yet comparing vendors",
    "consideration": "evaluators shortlisting tools for this use case",
    "decision": "buyers deciding between specific products",
    "purchase": "buyers ready to purchase and validating the choice",
}


class ContentStrategyAgent(Agent):
    name = "content-strategy"
    version = VERSION
    instructions = (
        "Turn verified AI-search opportunities into content briefs: what to create, "
        "why, for whom, targeting which real prompts, against which competitors, with "
        "which real evidence. Never draft the content itself. " + FABRICATION_RULE
    )
    context_spec = ContextSpec(prompts=50, competitors=20)

    async def run(self, context: AgentContext) -> AgentResult:
        tools = context.tools
        if tools is None:  # pragma: no cover - orchestrator always provides tools
            raise RuntimeError("Content strategy agent requires a ToolBox")
        warnings: list[str] = []

        content_gaps = await tools.call("get_content_gaps", limit=20)
        citation_gaps = await tools.call("get_citation_gaps", limit=20)
        insights = await tools.call("get_competitive_insights", limit=10)
        pages = await tools.call("get_pages", limit=50)
        entities = await tools.call("get_entity_data", limit=50)
        claims = await tools.call("get_claims", limit=50)

        prompts = context.prompts  # actual project prompts from the declared context
        competitors = {c["name"]: c for c in context.competitors if c.get("name")}
        brand = context.project.get("name") or "the brand"

        eligible = [
            g
            for g in content_gaps
            if g["opportunity_score"] >= MIN_OPPORTUNITY
            and g["confidence"] != "insufficient"
            and g["status"] in ("new", "reviewing", "accepted", "in_progress")
        ][:MAX_BRIEFS]
        if not eligible:
            warnings.append(
                "No content gap met the opportunity bar "
                f"(≥ {MIN_OPPORTUNITY:.0f}); no briefs were generated."
            )

        findings: list[dict[str, Any]] = []
        saved: list[dict[str, Any]] = []
        actions: list[ProposedAction] = []
        for gap in eligible:
            brief = self._brief_for(
                gap,
                prompts=prompts,
                competitors=competitors,
                citation_gaps=citation_gaps,
                insights=insights,
                pages=pages,
                entities=entities,
                claims=claims,
                brand=brand,
            )
            result = await tools.call("save_content_brief", **brief)
            saved.append({**result, "title": brief["title"], "source_key": brief["source_key"]})
            findings.append(
                {
                    "title": brief["title"],
                    "content_type": brief["content_type"],
                    "brief_id": result["id"],
                    "target_prompts": len(brief["target_prompt_ids"]),
                    "competitors": len(brief["competitor_ids"]),
                    "confidence": brief["confidence"],
                    "statements": {
                        "observed": (
                            f"Content gap “{gap['topic']}” ({gap['gap_type']}) with "
                            f"opportunity {gap['opportunity_score']:.0f}; top competitor "
                            f"{gap.get('top_competitor') or 'n/a'} at "
                            f"{gap.get('top_competitor_rate') or 'n/a'}% vs brand "
                            f"{gap.get('brand_mention_rate') or 0}%."
                        ),
                        "inference": (
                            "The prompt set asks about this topic and competitors are "
                            "the names AI answers currently surface."
                        ),
                        "recommendation": (
                            f"Prepare the '{brief['content_type']}' brief and review it "
                            "before any content work starts."
                        ),
                    },
                }
            )
            actions.append(
                ProposedAction(
                    action_type="review_content_brief",
                    description=f"Review the draft brief “{brief['title']}” (suggestion only).",
                    payload={"brief_id": result["id"], "source_key": brief["source_key"]},
                    risk_level=ActionRiskLevel.MEDIUM,  # leads to customer-facing content
                    approval_required=True,
                )
            )

        summary = (
            f"Prepared {len(saved)} content brief(s) from {len(eligible)} eligible "
            f"content gaps (of {len(content_gaps)} retrieved). Briefs are drafts for "
            "human review; no content was generated and no assets were changed."
        )
        return AgentResult(
            agent_name=self.name,
            agent_version=self.version,
            status=AgentStatus.COMPLETED,
            summary=summary,
            findings=findings,
            recommendations=[
                {
                    "title": s["title"],
                    "brief_id": s["id"],
                    "recommended_action": "Review the draft content brief",
                }
                for s in saved
            ],
            evidence={
                "briefs": saved,
                "eligible_gaps": [g["id"] for g in eligible],
                "fabrication_rule": FABRICATION_RULE,
            },
            proposed_actions=actions,
            confidence=0.7 if saved else None,
            warnings=warnings,
        )

    # -- brief construction (all inputs are observed project data) ---------------------

    def _brief_for(
        self,
        gap: dict[str, Any],
        *,
        prompts: list[dict[str, Any]],
        competitors: dict[str, dict[str, Any]],
        citation_gaps: list[dict[str, Any]],
        insights: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        brand: str,
    ) -> dict[str, Any]:
        topic: str = gap["topic"]
        content_type = GAP_CONTENT_TYPE.get(gap["gap_type"], "new_article")
        keywords = [k for k in topic_keywords(topic) if len(k) >= 3]
        matched_prompts = self._match_prompts(prompts, keywords, gap.get("prompt_id"))
        # ordered: the gap's own prompt first, so intent derives deterministically
        categories = [p["category"] for p in matched_prompts]
        stages = {p["funnel_stage"] for p in matched_prompts}
        top_competitor = gap.get("top_competitor")
        competitor_rows = [competitors[top_competitor]] if top_competitor in competitors else []
        # claims about the dominating competitor that overlap the topic → facts to address
        related_claims = [
            f"{c['subject']} {c['predicate']} {c['object']}"
            for c in claims
            if top_competitor
            and top_competitor.lower() in (c.get("subject") or "").lower()
            and any(k in (c.get("object") or "").lower() for k in keywords)
        ][:3]
        matched_pages = self._match_pages(pages, keywords)
        org_entities = [
            e for e in entities if (e.get("entity_type") or "").lower() in ("organization", "brand")
        ]
        product_entities = [
            e
            for e in entities
            if (e.get("entity_type") or "").lower() in ("product", "softwareapplication")
        ]
        citation_ops = [
            {
                "domain": g["domain"],
                "gap_type": g["gap_type"],
                "opportunity_score": g["opportunity_score"],
            }
            for g in citation_gaps
            if g["opportunity_score"] >= 50 and not self._competitor_owned(g["domain"], competitors)
        ][:5]
        insight_titles = [
            i["title"]
            for i in insights
            if top_competitor and top_competitor in (i.get("title") or "")
        ][:3]

        info_requirements = [f"Directly answer: “{p['text']}”" for p in matched_prompts[:5]] + [
            f"Cover the topic facets: {', '.join(keywords[:6])}"
        ]
        if related_claims:
            info_requirements.append(
                "Address competitor claims AI answers repeat: "
                + "; ".join(related_claims)
                + " (verify before responding to them)"
            )

        evidence_requirements = {
            "data": {
                "required": content_type in ("research_content", "comparison_page"),
                "notes": (
                    "Real, checkable numbers (pricing, limits, benchmarks) with their sources."
                ),
            },
            "research": {
                "required": content_type == "research_content",
                "observed_research_sources": gap.get("research_domains") or [],
                "notes": "Cite existing research or publish original, verifiable findings.",
            },
            "citations": {
                "required": True,
                "candidate_sources": [c["domain"] for c in citation_ops],
                "notes": "Cite real sources only; every claim must be attributable.",
            },
            "examples": {
                "required": content_type in ("use_case_page", "faq_page", "documentation"),
                "notes": "Concrete, reproducible examples from the actual product.",
            },
            "customer_evidence": {
                "required": content_type in ("case_study", "use_case_page"),
                "notes": "Only real customer stories with permission — never invented.",
            },
            "rule": FABRICATION_RULE,
        }
        entity_requirements = (
            [f"{brand} as an Organization (name, description, sameAs)"]
            + [f"Product entity: {e['name']}" for e in product_entities[:3] if e.get("name")]
            + ([f"Competitor referenced accurately: {top_competitor}"] if top_competitor else [])
            + ([] if org_entities else ["Add Organization schema — none was found on the site"])
        )

        h2s = [f"H2: {p['text']}" for p in matched_prompts[:3]] or [f"H2: {topic}"]
        outline = {
            "structure": [
                f"H1: {self._title(topic, content_type, top_competitor, brand)}",
                *h2s,
                "H3: Evidence and sources for the claims above",
                f"H2: How {brand} approaches {topic}",
                "FAQ: the questions the target prompts actually ask",
                "Sources: every cited source, linked",
            ],
            "notes": "Structure follows the prompts this content targets; adjust on review.",
        }
        differentiation = (
            (
                f"Competitor answers currently lean on {top_competitor}"
                + (f" ({'; '.join(insight_titles)})" if insight_titles else "")
                + ". "
            )
            if top_competitor
            else ""
        ) + (
            "Add what those answers lack: verifiable specifics for "
            f"“{topic}” from {brand}'s own data, with sources — not generic copy."
        )

        intent = next(
            (INTENT_BY_CATEGORY[c] for c in categories if c in INTENT_BY_CATEGORY),
            "Get a well-evidenced answer to the underlying question.",
        )
        audience = (
            ", ".join(sorted(AUDIENCE_BY_STAGE[s] for s in stages if s in AUDIENCE_BY_STAGE))
            or "evaluators researching this category"
        )

        return {
            "source_key": f"content_gap:{gap['id']}",
            "title": self._title(topic, content_type, top_competitor, brand),
            "content_type": content_type,
            "objective": (
                f"Close the “{topic}” gap ({gap['gap_type']}, opportunity "
                f"{gap['opportunity_score']:.0f}): give AI engines substantive, "
                "evidence-backed brand content for the prompts below. No ranking or "
                "citation outcome is guaranteed."
            ),
            "search_intent": intent,
            "audience": audience,
            "differentiation": differentiation,
            "target_prompt_ids": [p["id"] for p in matched_prompts[:10]],
            "competitor_ids": [c["id"] for c in competitor_rows],
            "outline": outline,
            "information_requirements": info_requirements[:12],
            "evidence_requirements": evidence_requirements,
            "citation_opportunities": citation_ops,
            "entity_requirements": entity_requirements[:10],
            "internal_link_recommendations": matched_pages[:5],
            "confidence": gap["confidence"] if gap["confidence"] != "insufficient" else "low",
        }

    @staticmethod
    def _title(topic: str, content_type: str, competitor: str | None, brand: str) -> str:
        t = topic.strip().capitalize()
        if content_type == "comparison_page" and competitor:
            return f"{brand} vs {competitor}: {t}"[:300]
        if content_type == "alternative_page" and competitor:
            return f"{competitor} alternatives: {t}"[:300]
        if content_type == "faq_page":
            return f"{t}: frequently asked questions"[:300]
        if content_type == "use_case_page":
            return f"{t} with {brand}"[:300]
        if content_type == "product_page":
            return f"{t}: what {brand} offers"[:300]
        if content_type == "research_content":
            return f"{t}: data and benchmarks"[:300]
        if content_type == "existing_page_optimization":
            return f"Strengthen existing coverage: {t}"[:300]
        return t[:300]

    @staticmethod
    def _match_prompts(
        prompts: list[dict[str, Any]], keywords: list[str], gap_prompt_id: str | None
    ) -> list[dict[str, Any]]:
        """Actual project prompts only: the gap's own prompt first, then prompts
        sharing at least half of the topic keywords."""
        matched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for p in prompts:
            if gap_prompt_id and p["id"] == gap_prompt_id:
                matched.append(p)
                seen.add(p["id"])
        needed = max(1, (len(set(keywords)) + 1) // 2) if keywords else 1
        for p in prompts:
            if p["id"] in seen:
                continue
            text = (p.get("text") or "").lower()
            if sum(1 for k in set(keywords) if k in text) >= needed:
                matched.append(p)
                seen.add(p["id"])
        return matched

    @staticmethod
    def _match_pages(pages: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
        out = []
        for page in pages:
            hay = f"{page.get('url', '')} {page.get('title') or ''}".lower()
            hits = [k for k in set(keywords) if k in hay]
            if hits:
                out.append(
                    {
                        "page_id": page["id"],
                        "url": page["url"],
                        "title": page.get("title"),
                        "matched_keywords": sorted(hits),
                    }
                )
        out.sort(key=lambda p: -len(p["matched_keywords"]))
        return out

    @staticmethod
    def _competitor_owned(host: str, competitors: dict[str, dict[str, Any]]) -> bool:
        host = (host or "").lower()
        labels = set(host.split("."))
        for c in competitors.values():
            domain = (c.get("domain") or "").lower().removeprefix("www.")
            if domain and (host == domain or host.endswith("." + domain)):
                return True
            name = "".join(ch for ch in (c.get("name") or "").lower() if ch.isalnum())
            if name and name in labels:
                return True
        return False
