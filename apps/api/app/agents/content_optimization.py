"""GEO Content Optimization Agent (Milestone 6D): review pages, propose changes.

Analyzes existing crawled pages for answerability, entity clarity, factual
specificity, evidence quality, structure, entity markup and internal linking,
and PROPOSES improvements. It never rewrites a page: proposals are stored on
`content_optimization_reviews` for humans to accept, edit or reject; the
original page rows are read-only to this agent.

Anti-fabrication: proposed replacement text never contains invented facts —
wherever a real detail is needed the proposal carries an explicit
`[FILL: …]` placeholder telling the editor what verifiable material to add,
and evidence recommendations say what to collect, never supply it. The agent
makes no claim of guaranteed AI ranking improvement.
"""

import re
from typing import Any

from app.agents.base import Agent
from app.agents.context import AgentContext, ContextSpec
from app.agents.results import AgentResult, AgentStatus, ProposedAction
from app.content_gaps.topics import topic_keywords
from app.models.agents import ActionRiskLevel

VERSION = "1.0"
ANALYSIS_VERSION = "content-optimization/v1"
MAX_REVIEWS = 5
MIN_TEXT_CHARS = 200  # below this the page cannot be meaningfully analyzed

VAGUE_TERMS = (
    "powerful",
    "best-in-class",
    "world-class",
    "cutting-edge",
    "state-of-the-art",
    "next-generation",
    "revolutionary",
    "seamless",
    "robust",
    "innovative",
    "industry-leading",
    "leading",
    "game-changing",
)
UNSUPPORTED_MARKERS = ("fastest", "cheapest", "#1", "number one", "most popular", "guarantee")
_SENTENCE = re.compile(r"[^.!?\n]{20,300}[.!?]")

DISCLAIMER = (
    "These are proposals for human review; applying them cannot guarantee any AI "
    "ranking or citation outcome."
)


class ContentOptimizationAgent(Agent):
    name = "content-optimization"
    version = VERSION
    instructions = (
        "Review existing pages for clarity, specificity, entity clarity, "
        "answerability, evidence quality, structure and citation readiness. Propose "
        "improvements with explicit [FILL: …] placeholders wherever a real fact is "
        "needed — never invent facts, evidence or credentials, and never claim "
        "guaranteed AI ranking improvements. Never modify the page itself."
    )
    context_spec = ContextSpec(prompts=50, competitors=10)

    async def run(self, context: AgentContext) -> AgentResult:
        tools = context.tools
        if tools is None:  # pragma: no cover - orchestrator always provides tools
            raise RuntimeError("Content optimization agent requires a ToolBox")
        warnings: list[str] = []

        pages = await tools.call("get_pages", limit=50)
        content_gaps = await tools.call("get_content_gaps", limit=20)
        citation_gaps = await tools.call("get_citation_gaps", limit=10)
        insights = await tools.call("get_competitive_insights", limit=10)
        brand = context.project.get("name") or "the brand"

        selected = self._select_pages(pages, content_gaps, context.prompts)
        if not selected:
            warnings.append("No crawled pages available to review.")

        findings_out: list[dict[str, Any]] = []
        actions: list[ProposedAction] = []
        reviews: list[dict[str, Any]] = []
        for page_meta in selected[:MAX_REVIEWS]:
            page = await tools.call("get_page_content", page_id=page_meta["id"])
            text = page.get("extracted_text") or ""
            if len(text) < MIN_TEXT_CHARS:
                warnings.append(
                    f"{page['url']}: too little extracted text to review "
                    f"({len(text)} chars) — skipped."
                )
                continue
            review = self._review_page(
                page,
                brand=brand,
                prompts=context.prompts,
                pages=pages,
                citation_gaps=citation_gaps,
                insights=insights,
            )
            result = await tools.call("save_content_review", **review)
            reviews.append({**result, "url": page["url"], "score": review["score"]})
            findings_out.append(
                {
                    "title": f"Content review: {page['url']}",
                    "review_id": result["id"],
                    "score": review["score"],
                    "proposed_changes": result["changes"],
                    "confidence": review["confidence"],
                    "statements": {
                        "observed": (
                            f"{page['url']}: score {review['score']:.0f}/100 from "
                            f"{len(review['findings'])} findings over "
                            f"{page.get('word_count') or 'unknown'} words."
                        ),
                        "inference": (
                            "The page under-serves AI answerability in the flagged areas."
                        ),
                        "recommendation": (
                            "Review the proposed changes; accept, edit or reject each — "
                            "nothing is applied automatically."
                        ),
                    },
                }
            )
            actions.append(
                ProposedAction(
                    action_type="review_content_optimization",
                    description=(
                        f"Review proposed content changes for {page['url']} (suggestion only)."
                    ),
                    payload={"review_id": result["id"], "page_id": page["id"]},
                    risk_level=ActionRiskLevel.MEDIUM,  # would change customer-facing content
                    approval_required=True,
                )
            )

        return AgentResult(
            agent_name=self.name,
            agent_version=self.version,
            status=AgentStatus.COMPLETED,
            summary=(
                f"Reviewed {len(reviews)} page(s); every change is a proposal for human "
                "review and the original pages are untouched. " + DISCLAIMER
            ),
            findings=findings_out,
            recommendations=[
                {
                    "title": f"Review {r['url']}",
                    "review_id": r["id"],
                    "recommended_action": "Accept, edit or reject the proposed changes",
                }
                for r in reviews
            ],
            evidence={"reviews": reviews, "disclaimer": DISCLAIMER},
            proposed_actions=actions,
            confidence=0.7 if reviews else None,
            warnings=warnings,
        )

    # -- page selection ----------------------------------------------------------------

    @staticmethod
    def _select_pages(
        pages: list[dict[str, Any]],
        content_gaps: list[dict[str, Any]],
        prompts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Pages tied to weak/covered topics first, then prompt-related, then rest."""
        gap_keywords = {
            k
            for g in content_gaps
            if g["gap_type"] == "weak_topic"
            for k in topic_keywords(g["topic"])
        }
        prompt_keywords = {k for p in prompts for k in topic_keywords(p.get("text") or "")}

        def rank(page: dict[str, Any]) -> tuple[int, int]:
            hay = f"{page.get('url', '')} {page.get('title') or ''}".lower()
            gap_hits = sum(1 for k in gap_keywords if k in hay)
            prompt_hits = sum(1 for k in prompt_keywords if k in hay)
            return (gap_hits, prompt_hits)

        return sorted(pages, key=lambda p: rank(p), reverse=True)

    # -- the seven analyzers -----------------------------------------------------------

    def _review_page(
        self,
        page: dict[str, Any],
        *,
        brand: str,
        prompts: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        citation_gaps: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> dict[str, Any]:
        text: str = page.get("extracted_text") or ""
        lower = text.lower()
        findings: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        changes: list[dict[str, Any]] = []
        deductions = 0.0

        related_prompts = self._related_prompts(page, prompts)

        # 1. Answerability — can the page answer its related prompts directly?
        unanswered = []
        for p in related_prompts[:5]:
            kws = topic_keywords(p["text"])
            coverage = sum(1 for k in set(kws) if k in lower) / max(1, len(set(kws)))
            if coverage < 0.6:
                unanswered.append(p["text"])
        if unanswered:
            deductions += 15
            findings.append(
                {
                    "category": "answerability",
                    "severity": "high",
                    "detail": (
                        f"The page does not directly address {len(unanswered)} related prompt(s)."
                    ),
                    "evidence": {"prompts": unanswered[:3]},
                }
            )
            changes.append(
                {
                    "location": "body: new answer section",
                    "current_text": "",
                    "proposed_text": (
                        f"Add a section that directly answers: “{unanswered[0]}”. Open "
                        "with a one-paragraph answer, then support it with "
                        "[FILL: the specific, verifiable details from your product/data]."
                    ),
                    "reason": "Related AI prompts are not directly answered on the page.",
                    "evidence": {"unanswered_prompts": unanswered[:3]},
                    "confidence": "medium",
                }
            )
        # 2. Entity clarity — who / what / for whom / where
        entity_missing = []
        if brand.lower() not in lower[:1500]:
            entity_missing.append("who the company is (brand not named early)")
        if not any(w in lower for w in ("for ", "designed for", "built for", "serves")):
            entity_missing.append("who it serves")
        entities = page.get("entities") or []
        if not any(
            (e.get("entity_type") or "").lower() in ("organization", "brand") for e in entities
        ):
            entity_missing.append("machine-readable organization identity on this page")
        if entity_missing:
            deductions += 10
            findings.append(
                {
                    "category": "entity_clarity",
                    "severity": "medium",
                    "detail": "Unclear: " + "; ".join(entity_missing) + ".",
                    "evidence": {"page_entities": [e.get("entity_type") for e in entities]},
                }
            )
            changes.append(
                {
                    "location": "intro paragraph",
                    "current_text": text[:160].strip(),
                    "proposed_text": (
                        f"{brand} is [FILL: one-sentence description of what {brand} is] "
                        "for [FILL: the specific audience it serves]. " + text[:160].strip()
                    ),
                    "reason": (
                        "State who the company is and who it serves in the first "
                        "paragraph so both readers and AI engines can attribute the page."
                    ),
                    "evidence": {"missing": entity_missing},
                    "confidence": "medium",
                }
            )
        # 3. Specificity — vague claims
        vague_sentences = []
        seen_sentences: set[str] = set()
        for m in _SENTENCE.finditer(text):
            sentence = m.group(0).strip()
            if sentence in seen_sentences:
                continue  # repeated boilerplate: propose each fix once
            hits = [t for t in VAGUE_TERMS if t in sentence.lower()]
            if hits:
                seen_sentences.add(sentence)
                vague_sentences.append((sentence, hits))
        for sentence, hits in vague_sentences[:3]:
            deductions += 5
            changes.append(
                {
                    "location": "body",
                    "current_text": sentence,
                    "proposed_text": (
                        "Replace with a specific, verifiable statement, e.g.: "
                        f"“{brand} [FILL: names the exact capabilities — what it "
                        "automates or provides] for [FILL: the specific audience].” "
                        "Keep only claims you can back up."
                    ),
                    "reason": (
                        f"Vague marketing language ({', '.join(hits)}) — AI answers "
                        "favour specifics."
                    ),
                    "evidence": {"vague_terms": hits},
                    "confidence": "high",
                }
            )
        if vague_sentences:
            findings.append(
                {
                    "category": "specificity",
                    "severity": "medium",
                    "detail": f"{len(vague_sentences)} sentence(s) rely on vague claims.",
                    "evidence": {
                        "examples": [s for s, _ in vague_sentences[:3]],
                        "terms": sorted({t for _, hits in vague_sentences for t in hits}),
                    },
                }
            )
        # 4. Evidence — claims that need support
        unsupported = []
        for m in _SENTENCE.finditer(text):
            sentence = m.group(0).strip()
            low = sentence.lower()
            if any(t in low for t in UNSUPPORTED_MARKERS) or re.search(r"\b\d{2,}%", sentence):
                unsupported.append(sentence)
        for sentence in unsupported[:3]:
            deductions += 5
            changes.append(
                {
                    "location": "body",
                    "current_text": sentence,
                    "proposed_text": (
                        sentence + " [FILL: add the verifiable source for this claim — a real "
                        "study, dataset or documentation link. If no source exists, "
                        "soften or remove the claim. Do not invent evidence.]"
                    ),
                    "reason": "A checkable claim without a source; cite it or drop it.",
                    "evidence": {"claim": sentence[:200]},
                    "confidence": "high",
                }
            )
        if unsupported:
            findings.append(
                {
                    "category": "evidence",
                    "severity": "high",
                    "detail": f"{len(unsupported)} claim(s) lack sources.",
                    "evidence": {"examples": [s[:150] for s in unsupported[:3]]},
                }
            )
            recommendations.append(
                {
                    "category": "evidence",
                    "recommendation": (
                        "Collect real supporting material (data, research, examples, "
                        "customer evidence with permission) for the flagged claims. "
                        "Never fabricate sources, statistics or testimonials."
                    ),
                }
            )
        # 5. Structure — headings, FAQs, lists, concise answers
        headings = page.get("headings") or []
        h1s = [h for h in headings if h["level"] == 1]
        structure_issues = []
        if not headings:
            structure_issues.append("no headings recorded")
        elif not h1s:
            structure_issues.append("no H1")
        elif len(h1s) > 1:
            structure_issues.append(f"{len(h1s)} H1s")
        has_question_heading = any("?" in (h.get("text") or "") for h in headings)
        if related_prompts and not has_question_heading:
            structure_issues.append("no question-form headings/FAQ despite question prompts")
        if (page.get("word_count") or 0) > 600 and "\n-" not in text and "•" not in text:
            structure_issues.append("long page without lists")
        if not page.get("meta_description"):
            structure_issues.append("missing meta description")
        if structure_issues:
            deductions += 4 * len(structure_issues)
            findings.append(
                {
                    "category": "structure",
                    "severity": "medium",
                    "detail": "; ".join(structure_issues) + ".",
                    "evidence": {"headings": len(headings), "h1_count": len(h1s)},
                }
            )
            if "no question-form headings/FAQ despite question prompts" in structure_issues:
                changes.append(
                    {
                        "location": "new FAQ section",
                        "current_text": "",
                        "proposed_text": (
                            "Add an FAQ section whose questions mirror the prompts this "
                            "page targets, each with a concise 2–3 sentence answer "
                            "first and detail after: "
                            + "; ".join(f"“{p['text']}”" for p in related_prompts[:3])
                        ),
                        "reason": (
                            "Question-form headings with concise answers improve answerability."
                        ),
                        "evidence": {"related_prompts": [p["text"] for p in related_prompts[:3]]},
                        "confidence": "medium",
                    }
                )
        # 6. Entity markup — only when justified by the page itself
        schema_types = {t.lower() for t in (page.get("schema_types") or [])}
        markup_recs = []
        if has_question_heading and "faqpage" not in schema_types:
            markup_recs.append("FAQPage schema — the page already has question-form content")
        page_is_root = page.get("url", "").rstrip("/").count("/") <= 2
        if page_is_root and "organization" not in schema_types:
            markup_recs.append("Organization schema on this top-level page")
        product_entities = [
            e
            for e in (page.get("entities") or [])
            if (e.get("entity_type") or "").lower() in ("product", "softwareapplication")
        ]
        if product_entities and "product" not in schema_types:
            markup_recs.append("Product schema for the product(s) already described here")
        if markup_recs:
            deductions += 5
            findings.append(
                {
                    "category": "entity_markup",
                    "severity": "low",
                    "detail": "Justified structured data is missing.",
                    "evidence": {"present": sorted(schema_types), "recommended": markup_recs},
                }
            )
            recommendations.append(
                {
                    "category": "entity_markup",
                    "recommendation": (
                        "Add only the schema the page's actual content justifies: "
                        + "; ".join(markup_recs)
                        + "."
                    ),
                }
            )
        # 7. Internal linking — real related pages
        related_pages = self._related_pages(page, pages)
        if related_pages:
            recommendations.append(
                {
                    "category": "internal_linking",
                    "recommendation": "Link to related pages where relevant.",
                    "pages": related_pages[:3],
                }
            )
        # citation readiness — sources already observed in the AI Search Graph
        candidate_sources = [g["domain"] for g in citation_gaps if g["opportunity_score"] >= 50][:5]
        if candidate_sources:
            recommendations.append(
                {
                    "category": "citation_readiness",
                    "recommendation": (
                        "Make the page's key facts attributable (clear statements, "
                        "cited sources) — sources already observed citing this "
                        "category: " + ", ".join(candidate_sources) + "."
                    ),
                }
            )

        score = max(0.0, round(100.0 - deductions, 1))
        confidence = "high" if len(text) >= 2000 and headings else "medium"
        return {
            "page_id": page["id"],
            "score": score,
            "findings": findings,
            "recommendations": recommendations,
            "proposed_changes": changes,
            "confidence": confidence,
            "analysis_version": ANALYSIS_VERSION,
        }

    @staticmethod
    def _related_prompts(
        page: dict[str, Any], prompts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        text_head = (page.get("extracted_text") or "")[:1000]
        hay = f"{page.get('url', '')} {page.get('title') or ''} {text_head}".lower()
        out = []
        for p in prompts:
            kws = set(topic_keywords(p.get("text") or ""))
            if not kws:
                continue
            if sum(1 for k in kws if k in hay) >= max(1, (len(kws) + 1) // 2):
                out.append(p)
        return out

    @staticmethod
    def _related_pages(page: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kws = set(topic_keywords(f"{page.get('title') or ''} {page.get('url', '')}"))
        out = []
        for other in pages:
            if other["id"] == page["id"]:
                continue
            hay = f"{other.get('url', '')} {other.get('title') or ''}".lower()
            hits = [k for k in kws if k in hay]
            if hits:
                out.append({"url": other["url"], "title": other.get("title"), "shared": hits[:5]})
        out.sort(key=lambda p: -len(p["shared"]))
        return out
