"""Deterministic prompt generation: realistic buyer questions built from the
business profile along the decision journey (awareness → retention).

Templates are grouped by category; each yields (text, category, intent,
funnel_stage). Slot values rotate so the output is diverse, and candidates
are de-duplicated with normalized/near-duplicate checks before scoring.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import cycle

from app.models.prompts import FunnelStage, PromptCategory, PromptIntent
from app.prompts.normalize import is_near_duplicate, normalize_text
from app.prompts.profile import BusinessProfile

C, N, F = PromptCategory, PromptIntent, FunnelStage


@dataclass(frozen=True)
class Template:
    # slots: {offering} {offerings} {audience} {competitor} {company} {descriptor} {task}
    #        {integration} {geo} {product}
    text: str
    category: PromptCategory
    intent: PromptIntent
    stage: FunnelStage


TEMPLATES: tuple[Template, ...] = (
    # discovery / awareness
    Template(
        "What should I know about {offerings} before choosing one?",
        C.DISCOVERY,
        N.INFORMATIONAL,
        F.AWARENESS,
    ),
    Template(
        "What should {audience} look for in {offerings}?", C.DISCOVERY, N.INFORMATIONAL, F.AWARENESS
    ),
    Template(
        "What types of {offerings} exist for {audience}?", C.DISCOVERY, N.INFORMATIONAL, F.AWARENESS
    ),
    Template(
        "Who are the leading providers of {offerings}?", C.DISCOVERY, N.INFORMATIONAL, F.AWARENESS
    ),
    # recommendation / consideration
    Template(
        "What are the best {offerings} for {audience}?",
        C.RECOMMENDATION,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "Which {offering} is easiest for {audience} to get started with?",
        C.RECOMMENDATION,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "Which {offerings} do experts recommend for {audience}?",
        C.RECOMMENDATION,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "What is the most reliable option among {offerings} for {descriptor}?",
        C.RECOMMENDATION,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    # comparison
    Template(
        "How does {company} compare to {competitor}?", C.COMPARISON, N.COMMERCIAL, F.CONSIDERATION
    ),
    Template(
        "{company} vs {competitor}: which is better for {audience}?",
        C.COMPARISON,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "What are the differences between {competitor} and {company} for {descriptor}?",
        C.COMPARISON,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    # alternative
    Template(
        "What are the best alternatives to {competitor}?",
        C.ALTERNATIVE,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "Which {offering} can replace {competitor} for {audience}?",
        C.ALTERNATIVE,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    Template(
        "Is there a simpler alternative to {competitor} for {descriptor}?",
        C.ALTERNATIVE,
        N.COMMERCIAL,
        F.CONSIDERATION,
    ),
    # product / capabilities
    Template("What {offerings} support {descriptor}?", C.PRODUCT, N.COMMERCIAL, F.CONSIDERATION),
    Template(
        "Which {offerings} integrate with {integration}?", C.PRODUCT, N.COMMERCIAL, F.CONSIDERATION
    ),
    Template("Does {company} offer {descriptor}?", C.PRODUCT, N.COMMERCIAL, F.DECISION),
    Template("Does {product} work with {integration}?", C.PRODUCT, N.COMMERCIAL, F.DECISION),
    # pricing / decision
    Template(
        "How much do {offerings} cost for {audience}?", C.PRICING, N.TRANSACTIONAL, F.DECISION
    ),
    Template(
        "What does {company} pricing look like compared to {competitor}?",
        C.PRICING,
        N.TRANSACTIONAL,
        F.DECISION,
    ),
    Template(
        "Are there affordable {offerings} for {audience}?", C.PRICING, N.TRANSACTIONAL, F.DECISION
    ),
    Template("Does {company} have a free plan or trial?", C.PRICING, N.TRANSACTIONAL, F.DECISION),
    # problem / solution
    Template(
        "How can {audience} automate {task}?",
        C.PROBLEM_SOLUTION,
        N.INFORMATIONAL,
        F.AWARENESS,
    ),
    Template(
        "How do I choose between {offerings} that handle {descriptor}?",
        C.PROBLEM_SOLUTION,
        N.INFORMATIONAL,
        F.CONSIDERATION,
    ),
    Template(
        "What is the fastest way for {audience} to set up {offerings}?",
        C.PROBLEM_SOLUTION,
        N.INFORMATIONAL,
        F.RETENTION,
    ),
    # industry
    Template(
        "What are the current trends in {offerings} for {audience}?",
        C.INDUSTRY,
        N.INFORMATIONAL,
        F.AWARENESS,
    ),
    Template(
        "How is the market for {offerings} changing for {audience} this year?",
        C.INDUSTRY,
        N.INFORMATIONAL,
        F.AWARENESS,
    ),
    # local
    Template(
        "What are the best {offerings} available in {geo}?", C.LOCAL, N.COMMERCIAL, F.DECISION
    ),
    Template(
        "Which {offering} providers serve {audience} in {geo}?", C.LOCAL, N.COMMERCIAL, F.DECISION
    ),
    Template("Is {company} available in {geo}?", C.LOCAL, N.NAVIGATIONAL, F.DECISION),
    # transactional / purchase
    Template("How do I sign up for {company}?", C.TRANSACTIONAL, N.TRANSACTIONAL, F.PURCHASE),
    Template(
        "Where can I get a demo of {offerings} for {audience}?",
        C.TRANSACTIONAL,
        N.TRANSACTIONAL,
        F.PURCHASE,
    ),
    Template(
        "How do I migrate from {competitor} to {company}?",
        C.TRANSACTIONAL,
        N.TRANSACTIONAL,
        F.RETENTION,
    ),
)

SLOT_NAMES = (
    "offering",
    "offerings",
    "audience",
    "competitor",
    "company",
    "descriptor",
    "task",
    "integration",
    "geo",
    "product",
)


@dataclass
class Candidate:
    text: str
    category: PromptCategory
    intent: PromptIntent
    funnel_stage: FunnelStage
    template: str


def _slot_values(profile: BusinessProfile) -> dict[str, list[str]]:
    return {
        "offering": profile.offerings_singular,
        "offerings": profile.offerings,
        "audience": profile.target_audience,
        "competitor": profile.competitors,
        "company": [profile.company_name],
        "descriptor": profile.descriptors,
        "task": profile.tasks,
        "integration": profile.integrations,
        "geo": profile.geo_phrases,
        "product": profile.brand_products,
    }


def _slots_in(template: str) -> list[str]:
    return [s for s in SLOT_NAMES if "{" + s + "}" in template]


def _fill(template: Template, values: dict[str, list[str]], limit: int) -> Iterable[Candidate]:
    slots = _slots_in(template.text)
    if any(not values.get(s) for s in slots):
        return []
    # Rotate every slot independently so combinations stay varied without
    # exploding into a cartesian product.
    cycles = {s: cycle(values[s]) for s in slots}
    longest = max(len(values[s]) for s in slots) if slots else 1
    out: list[Candidate] = []
    for _ in range(min(limit, longest)):
        filled = template.text.format(**{s: next(cycles[s]) for s in slots})
        out.append(
            Candidate(
                _tidy(filled), template.category, template.intent, template.stage, template.text
            )
        )
    return out


def _tidy(text: str) -> str:
    text = " ".join(text.split())
    return text[0].upper() + text[1:] if text else text


def generate_candidates(
    profile: BusinessProfile,
    *,
    max_total: int = 60,
    max_per_category: int = 8,
    per_template: int = 3,
    categories: Iterable[PromptCategory] | None = None,
    existing_texts: Iterable[str] = (),
) -> list[Candidate]:
    """Deterministic, diverse, de-duplicated candidates for the profile."""
    values = _slot_values(profile)
    wanted = set(categories) if categories else set(PromptCategory)
    per_category: dict[PromptCategory, int] = {c: 0 for c in PromptCategory}
    kept: list[Candidate] = []
    seen_norm: set[str] = {normalize_text(t) for t in existing_texts}
    seen_texts: list[str] = list(existing_texts)

    # Round-robin over templates so early categories don't starve later ones.
    rounds = [t for t in TEMPLATES if t.category in wanted]
    pending = {t.text: list(_fill(t, values, per_template)) for t in rounds}
    progressed = True
    while progressed and len(kept) < max_total:
        progressed = False
        for t in rounds:
            queue = pending[t.text]
            if not queue or per_category[t.category] >= max_per_category or len(kept) >= max_total:
                continue
            cand = queue.pop(0)
            progressed = True
            norm = normalize_text(cand.text)
            if norm in seen_norm or any(is_near_duplicate(cand.text, s) for s in seen_texts):
                continue
            seen_norm.add(norm)
            seen_texts.append(cand.text)
            per_category[cand.category] += 1
            kept.append(cand)
    return kept
