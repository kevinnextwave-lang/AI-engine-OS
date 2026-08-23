"""Entity Optimization Agent (Milestone 6E): how well are the organization,
products, services and people represented across the customer's site?

Deterministic, like the other agents: every finding comes from the project's
own crawled entities, structured data, pages and links. Reviews are written
through the validated `save_entity_review` tool and require human approval —
the agent modifies nothing.

Language rules: recommendations describe what a change makes explicit or
machine-readable; they never promise how any search or AI engine will
interpret it, and they never fabricate credentials, founding facts or contact
details — missing information is always a `[FILL: …]`-style instruction to
supply real data.
"""

from collections import Counter
from typing import Any

from app.agents.base import Agent
from app.agents.context import AgentContext, ContextSpec
from app.agents.results import AgentResult, AgentStatus, ProposedAction
from app.models.agents import ActionRiskLevel

VERSION = "1.0"
ANALYSIS_VERSION = "entity-optimization/v1"

ORG_TYPES = {"organization", "brand", "corporation", "localbusiness"}
PRODUCT_TYPES = {"product", "softwareapplication"}
SERVICE_TYPES = {"service"}
PERSON_TYPES = {"person"}

INTERPRETATION_NOTE = (
    "These changes make the information explicit and machine-readable; how any "
    "particular search or AI engine interprets them is not guaranteed."
)


class EntityOptimizationAgent(Agent):
    name = "entity-optimization"
    version = VERSION
    instructions = (
        "Review how the organization, its products, services and people are "
        "represented in the site's structured data and pages. Recommend real, "
        "verifiable information only — never fabricate credentials, founders, "
        "contacts or facts, and never promise how engines will interpret changes. "
        "Never modify anything."
    )
    context_spec = ContextSpec(competitors=5)

    async def run(self, context: AgentContext) -> AgentResult:
        tools = context.tools
        if tools is None:  # pragma: no cover - orchestrator always provides tools
            raise RuntimeError("Entity optimization agent requires a ToolBox")
        warnings: list[str] = []

        entities = await tools.call("get_entity_data", limit=50)
        links = await tools.call("get_entity_links", limit=50)
        pages = await tools.call("get_pages", limit=50)
        project = context.project
        brand = project.get("name") or "the brand"

        if not pages:
            return AgentResult(
                agent_name=self.name,
                agent_version=self.version,
                status=AgentStatus.COMPLETED,
                summary=(
                    "No crawled pages — entity representation cannot be reviewed. "
                    "Run a crawl first."
                ),
                warnings=["No crawled pages available."],
            )

        orgs = [e for e in entities if (e["entity_type"] or "").lower() in ORG_TYPES]
        products = [e for e in entities if (e["entity_type"] or "").lower() in PRODUCT_TYPES]
        services = [e for e in entities if (e["entity_type"] or "").lower() in SERVICE_TYPES]
        people = [e for e in entities if (e["entity_type"] or "").lower() in PERSON_TYPES]

        reviews: list[dict[str, Any]] = [
            self._organization_review(orgs, links, pages, project, brand)
        ]
        for product in products[:5]:
            reviews.append(self._product_review(product, orgs, brand))
        if not products:
            reviews.append(self._missing_products_review(pages, brand))
        for service in services[:3]:
            reviews.append(self._service_review(service, brand))
        person_review = self._people_review(people)
        if person_review is not None:
            reviews.append(person_review)
        consistency = self._consistency_review(orgs, pages, brand)
        if consistency is not None:
            reviews.append(consistency)

        saved: list[dict[str, Any]] = []
        actions: list[ProposedAction] = []
        findings_out: list[dict[str, Any]] = []
        for review in reviews:
            if review is None or not review["findings"]:
                continue
            result = await tools.call("save_entity_review", **review)
            saved.append({**result, "review_key": review["review_key"]})
            findings_out.append(
                {
                    "title": f"Entity review: {review['review_key']}",
                    "review_id": result["id"],
                    "entity_type": review["entity_type"],
                    "findings": len(review["findings"]),
                    "recommendations": len(review["recommendations"]),
                    "confidence": review["confidence"],
                }
            )
            actions.append(
                ProposedAction(
                    action_type="review_entity_optimization",
                    description=(
                        f"Review entity findings for '{review['review_key']}' "
                        "(all modifications require approval)."
                    ),
                    payload={"review_id": result["id"], "review_key": review["review_key"]},
                    risk_level=ActionRiskLevel.MEDIUM,  # would change customer-facing markup
                    approval_required=True,
                )
            )
        return AgentResult(
            agent_name=self.name,
            agent_version=self.version,
            status=AgentStatus.COMPLETED,
            summary=(
                f"Reviewed entity representation across {len(pages)} crawled pages: "
                f"{len(saved)} review(s) with findings. All proposed modifications "
                "require human approval; nothing was changed. " + INTERPRETATION_NOTE
            ),
            findings=findings_out,
            recommendations=[{"title": s["review_key"], "review_id": s["id"]} for s in saved],
            evidence={
                "entities": len(entities),
                "organization_entities": len(orgs),
                "product_entities": len(products),
                "pages": len(pages),
                "interpretation_note": INTERPRETATION_NOTE,
            },
            proposed_actions=actions,
            confidence=0.7 if saved else None,
            warnings=warnings,
        )

    # -- organization ------------------------------------------------------------------

    def _organization_review(
        self,
        orgs: list[dict[str, Any]],
        links: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        project: dict[str, Any],
        brand: str,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        if not orgs:
            findings.append(
                {
                    "aspect": "organization",
                    "severity": "high",
                    "detail": (
                        f"No Organization structured data was found on {len(pages)} crawled pages."
                    ),
                }
            )
            recommendations.append(
                {
                    "recommendation": "Add appropriate Organization structured data",
                    "detail": (
                        f"Declare {brand} once, canonically (name, description, url, "
                        "logo, contact information, sameAs) on the homepage or about "
                        "page. Use only real, current information."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            )
            return {
                "review_key": "organization",
                "entity_id": None,
                "entity_type": "organization",
                "findings": findings,
                "recommendations": recommendations,
                "confidence": "high",  # absence is directly observed
                "analysis_version": ANALYSIS_VERSION,
            }

        primary = max(
            orgs, key=lambda o: len(o.get("properties") or {}) + len(o.get("same_as") or [])
        )
        props = primary.get("properties") or {}
        checks: list[tuple[str, bool, str]] = [
            ("name", bool(primary.get("name")), "the organization name"),
            ("description", bool(primary.get("description")), "a concise description"),
            ("website", bool(primary.get("url")), "the canonical website URL"),
            ("logo", "logo" in props or "image" in props, "a logo"),
            (
                "contact information",
                any(k in props for k in ("contactPoint", "email", "telephone")),
                "contact information (contactPoint, email or telephone)",
            ),
            (
                "social profiles / sameAs",
                bool(primary.get("same_as")) or bool(links),
                "sameAs links to the organization's real profiles",
            ),
            ("location", "address" in props, "a business address"),
        ]
        for aspect, present, needed in checks:
            if not present:
                findings.append(
                    {
                        "aspect": aspect,
                        "severity": "medium",
                        "detail": f"The Organization entity does not declare {needed}.",
                    }
                )
        if "foundingDate" not in props:
            findings.append(
                {
                    "aspect": "founding information",
                    "severity": "low",
                    "detail": (
                        "No founding information is declared. Add it only if the real "
                        "founding date is known — do not guess."
                    ),
                }
            )
        if not project.get("industry"):
            findings.append(
                {
                    "aspect": "industry",
                    "severity": "low",
                    "detail": "The project has no industry set to check the markup against.",
                }
            )
        if not primary.get("description"):
            recommendations.append(
                {
                    "recommendation": "Clarify organization description",
                    "detail": (
                        f"Add a 1–2 sentence description of what {brand} is and who it "
                        "serves — [FILL: use the real positioning, not marketing filler]."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            )
        if not primary.get("same_as") and not links:
            recommendations.append(
                {
                    "recommendation": "Add consistent sameAs relationships",
                    "detail": (
                        "Link the Organization entity to its real external profiles "
                        "(LinkedIn, GitHub, Crunchbase, social accounts) with sameAs; "
                        "use the same set everywhere the entity is declared."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            )
        missing_aspects = [f["aspect"] for f in findings if f["severity"] != "low"]
        if missing_aspects and not recommendations:
            recommendations.append(
                {
                    "recommendation": "Complete the Organization entity",
                    "detail": "Declare the missing aspects with real data: "
                    + ", ".join(missing_aspects)
                    + ".",
                    "note": INTERPRETATION_NOTE,
                }
            )
        return {
            "review_key": "organization",
            "entity_id": primary["id"],
            "entity_type": "organization",
            "findings": findings,
            "recommendations": recommendations,
            "confidence": "high" if len(pages) >= 5 else "medium",
            "analysis_version": ANALYSIS_VERSION,
        }

    # -- products ----------------------------------------------------------------------

    def _product_review(
        self, product: dict[str, Any], orgs: list[dict[str, Any]], brand: str
    ) -> dict[str, Any]:
        props = product.get("properties") or {}
        name = product.get("name") or "unnamed product"
        findings: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        if not product.get("name"):
            findings.append(
                {
                    "aspect": "product name",
                    "severity": "high",
                    "detail": "The product entity has no name.",
                }
            )
        if not product.get("description"):
            findings.append(
                {
                    "aspect": "description",
                    "severity": "medium",
                    "detail": f"{name} has no description.",
                }
            )
            recommendations.append(
                {
                    "recommendation": "Improve product descriptions",
                    "detail": (
                        f"Describe what {name} does in concrete terms — "
                        "[FILL: the real capabilities], not adjectives."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            )
        for aspect, keys, severity in (
            ("features", ("featureList",), "low"),
            ("audience", ("audience",), "low"),
            ("pricing", ("offers", "priceRange"), "low"),
        ):
            if not any(k in props for k in keys):
                findings.append(
                    {
                        "aspect": aspect,
                        "severity": severity,
                        "detail": f"{name} declares no {aspect}.",
                    }
                )
        if not product.get("url"):
            findings.append(
                {"aspect": "URL", "severity": "medium", "detail": f"{name} declares no URL."}
            )
        connected = any(k in props for k in ("brand", "publisher", "manufacturer"))
        if not connected:
            findings.append(
                {
                    "aspect": "relationship to organization",
                    "severity": "medium",
                    "detail": f"{name} is not connected to the {brand} organization entity.",
                }
            )
            recommendations.append(
                {
                    "recommendation": "Connect product entities to organization",
                    "detail": (
                        f"Reference the {brand} Organization entity from {name} "
                        "(brand/publisher/manufacturer) so the product and the company "
                        "are explicitly related."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            )
        return {
            "review_key": f"product:{(product.get('name') or product['id']).lower()[:80]}",
            "entity_id": product["id"],
            "entity_type": "product",
            "findings": findings,
            "recommendations": recommendations,
            "confidence": "high",
            "analysis_version": ANALYSIS_VERSION,
        }

    def _missing_products_review(self, pages: list[dict[str, Any]], brand: str) -> dict[str, Any]:
        product_pages = [
            p
            for p in pages
            if any(k in (p.get("url") or "").lower() for k in ("/product", "/pricing", "/features"))
        ]
        if not product_pages:
            return {
                "review_key": "products",
                "entity_id": None,
                "entity_type": "product",
                "findings": [],
                "recommendations": [],
                "confidence": "low",
                "analysis_version": ANALYSIS_VERSION,
            }
        return {
            "review_key": "products",
            "entity_id": None,
            "entity_type": "product",
            "findings": [
                {
                    "aspect": "product entities",
                    "severity": "medium",
                    "detail": (
                        f"{len(product_pages)} product-like page(s) exist but no Product "
                        "structured data was found."
                    ),
                    "pages": [p["url"] for p in product_pages[:3]],
                }
            ],
            "recommendations": [
                {
                    "recommendation": "Add Product structured data on product pages",
                    "detail": (
                        f"Describe {brand}'s actual product(s) (name, description, URL) "
                        "on the pages that present them."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            ],
            "confidence": "medium",
            "analysis_version": ANALYSIS_VERSION,
        }

    # -- services ----------------------------------------------------------------------

    def _service_review(self, service: dict[str, Any], brand: str) -> dict[str, Any]:
        props = service.get("properties") or {}
        name = service.get("name") or "unnamed service"
        findings = []
        if not service.get("description"):
            findings.append(
                {
                    "aspect": "service definition",
                    "severity": "medium",
                    "detail": f"{name} has no description of what the service is.",
                }
            )
        if "audience" not in props:
            findings.append(
                {
                    "aspect": "target customer",
                    "severity": "low",
                    "detail": f"{name} declares no audience.",
                }
            )
        if "areaServed" not in props:
            findings.append(
                {
                    "aspect": "geographic scope",
                    "severity": "low",
                    "detail": f"{name} declares no areaServed.",
                }
            )
        if "provider" not in props:
            findings.append(
                {
                    "aspect": "related organization",
                    "severity": "medium",
                    "detail": f"{name} is not linked to the {brand} organization (provider).",
                }
            )
        return {
            "review_key": f"service:{(service.get('name') or service['id']).lower()[:80]}",
            "entity_id": service["id"],
            "entity_type": "service",
            "findings": findings,
            "recommendations": (
                [
                    {
                        "recommendation": "Complete the service entity",
                        "detail": (
                            f"Define {name} with a real description, audience, "
                            "geographic scope and provider."
                        ),
                        "note": INTERPRETATION_NOTE,
                    }
                ]
                if findings
                else []
            ),
            "confidence": "high",
            "analysis_version": ANALYSIS_VERSION,
        }

    # -- people ------------------------------------------------------------------------

    def _people_review(self, people: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Only reviews Person entities that exist. Never suggests credentials —
        missing details are instructions to add real information, if any."""
        if not people:
            return None
        findings = []
        for person in people[:5]:
            props = person.get("properties") or {}
            missing = [
                aspect
                for aspect, key in (("role/title", "jobTitle"), ("organization link", "worksFor"))
                if key not in props
            ]
            if missing:
                findings.append(
                    {
                        "aspect": "person",
                        "severity": "low",
                        "detail": (
                            f"{person.get('name') or 'A person entity'} lacks: "
                            + ", ".join(missing)
                            + ". Add only real, current information — never invent "
                            "credentials."
                        ),
                    }
                )
        return {
            "review_key": "people",
            "entity_id": people[0]["id"],
            "entity_type": "person",
            "findings": findings,
            "recommendations": (
                [
                    {
                        "recommendation": "Complete person entities with real information",
                        "detail": (
                            "For authors, leadership and experts already on the site, "
                            "declare their actual role and organization. Do not "
                            "fabricate credentials."
                        ),
                        "note": INTERPRETATION_NOTE,
                    }
                ]
                if findings
                else []
            ),
            "confidence": "medium",
            "analysis_version": ANALYSIS_VERSION,
        }

    # -- consistency -------------------------------------------------------------------

    def _consistency_review(
        self, orgs: list[dict[str, Any]], pages: list[dict[str, Any]], brand: str
    ) -> dict[str, Any] | None:
        if len(orgs) < 2:
            return None
        findings = []
        names = Counter((o.get("name") or "").strip() for o in orgs if o.get("name"))
        if len(names) > 1:
            findings.append(
                {
                    "aspect": "conflicting names",
                    "severity": "high",
                    "detail": (
                        "Pages declare different organization names: "
                        + "; ".join(f"“{n}” ({c}×)" for n, c in names.most_common())
                        + "."
                    ),
                    "conflicts": [
                        {"name": o.get("name"), "page_url": o.get("page_url")}
                        for o in orgs
                        if o.get("name")
                    ][:6],
                }
            )
        descriptions = {(o.get("description") or "").strip() for o in orgs if o.get("description")}
        if len(descriptions) > 1:
            findings.append(
                {
                    "aspect": "conflicting descriptions",
                    "severity": "medium",
                    "detail": (
                        f"{len(descriptions)} different organization descriptions are "
                        "declared across pages."
                    ),
                }
            )
        sameas_sets = {tuple(sorted(o.get("same_as") or [])) for o in orgs}
        if len(sameas_sets) > 1:
            findings.append(
                {
                    "aspect": "inconsistent sameAs",
                    "severity": "medium",
                    "detail": "Different pages declare different sameAs sets.",
                }
            )
        if not findings:
            return None
        return {
            "review_key": "consistency",
            "entity_id": None,
            "entity_type": "consistency",
            "findings": findings,
            "recommendations": [
                {
                    "recommendation": "Resolve conflicting company information",
                    "detail": (
                        f"Pick one canonical declaration of {brand} (name, description, "
                        "sameAs) and reuse it on every page that declares the "
                        "organization — homepage, about, product and contact pages "
                        "and metadata."
                    ),
                    "note": INTERPRETATION_NOTE,
                }
            ],
            "confidence": "high",
            "analysis_version": ANALYSIS_VERSION,
        }
