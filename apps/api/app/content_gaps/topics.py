"""Pure topic extraction, page matching, gap classification and scoring.

A *topic* is derived from one prompt: its content keywords (stop words and
generic category words removed) plus a display label. Customer coverage is
measured by matching those keywords against the crawled site's page titles,
meta descriptions and URLs — never guessed.

    Opportunity Score (0–100) =
        30 · competitor_advantage   (competitor − brand mention rate on the topic)
      + 25 · prompt_frequency       (responses on the topic, saturating at 10)
      + 20 · commercial_relevance   (commercial category/funnel stage)
      + 15 · coverage_deficit       (1 − coverage strength of matching pages)
      + 10 · evidence_availability  (citations observed on the topic → investigable)

Confidence: high ≥ 20 responses on the topic, medium ≥ 10, low ≥ 5; below 5
no gap is produced at all ("do not recommend content blindly").
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.content_gaps import ContentGapType, GapConfidence

MIN_TOPIC_RESPONSES = 5
CONFIDENCE_LADDER = ((20, GapConfidence.HIGH), (10, GapConfidence.MEDIUM), (5, GapConfidence.LOW))
FREQUENCY_SATURATION = 10
# The competitor must actually be visible on the topic, and the brand behind.
MIN_COMPETITOR_RATE = 40.0  # % of topic responses mentioning any competitor
MIN_RATE_GAP = 20.0  # competitor rate must exceed brand rate by this much
WEIGHTS = {
    "competitor_advantage": 30.0,
    "prompt_frequency": 25.0,
    "commercial_relevance": 20.0,
    "coverage_deficit": 15.0,
    "evidence_availability": 10.0,
}
COMMERCIAL_CATEGORIES = frozenset({"comparison", "recommendation", "pricing", "alternative"})
COMMERCIAL_STAGES = frozenset({"consideration", "decision", "purchase"})
SUBSTANTIAL_WORDS = 300  # a matched page below this counts as thin

STOP_WORDS = frozenset(
    """a an and are be best can cheap cheapest do does for from how i in is it my of on or
    should that the there to top what when which who why with you your""".split()
)
GENERIC_WORDS = frozenset(
    """tool tools software solution solutions platform platforms app apps service services
    company companies product products option options alternatives alternative vs versus
    compare comparison price prices pricing cost costs review reviews""".split()
)

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]+")

# Page-category signals in a URL path or title.
PAGE_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("comparison", re.compile(r"\bvs\b|versus|compare|comparison|alternatives?")),
    ("faq", re.compile(r"faq|frequently.asked|help|support|docs|questions?\b")),
    (
        "use_case",
        re.compile(r"use.?cases?|customers?|case.stud|success|stories|industries|industry"),
    ),
    ("product", re.compile(r"products?\b|pricing|features?|plans\b|integrations?")),
    ("educational", re.compile(r"guide|how.to|learn|tutorial|academy|blog|resources")),
)

# "how / can / does…" prompts read like FAQ material; "what/which are the best…"
# are recommendation questions and are NOT treated as FAQ prompts.
QUESTION_START = re.compile(r"^(how|can|does|do|is|are|should|why|when)\b", re.I)

# gap type a prompt calls for, by prompt nature
NEEDED_BY_CATEGORY = {
    "comparison": ContentGapType.MISSING_COMPARISON,
    "alternative": ContentGapType.MISSING_COMPARISON,
    "pricing": ContentGapType.MISSING_PRODUCT_DETAIL,
    "product": ContentGapType.MISSING_PRODUCT_DETAIL,
    "industry": ContentGapType.MISSING_USE_CASE,
}
NEEDED_PAGE_CATEGORY = {
    ContentGapType.MISSING_COMPARISON: "comparison",
    ContentGapType.MISSING_FAQ: "faq",
    ContentGapType.MISSING_USE_CASE: "use_case",
    ContentGapType.MISSING_PRODUCT_DETAIL: "product",
}


def topic_keywords(prompt_text: str) -> list[str]:
    words = _WORD.findall(prompt_text.lower())
    return [w for w in words if w not in STOP_WORDS and w not in GENERIC_WORDS and len(w) >= 3]


def topic_label(prompt_text: str) -> str:
    """Human topic label: the prompt without filler, title-cased lightly."""
    kept = topic_keywords(prompt_text)
    return " ".join(kept)[:300] if kept else prompt_text[:300]


def normalize_topic(label: str) -> str:
    return " ".join(sorted(set(_WORD.findall(label.lower()))))[:300]


def page_categories(url: str, title: str | None) -> set[str]:
    hay = f"{url} {title or ''}".lower()
    return {name for name, pattern in PAGE_CATEGORY_PATTERNS if pattern.search(hay)}


@dataclass
class PageMatch:
    url: str
    title: str | None
    word_count: int | None
    matched_keywords: list[str]
    categories: set[str]

    @property
    def substantial(self) -> bool:
        return (self.word_count or 0) >= SUBSTANTIAL_WORDS


def match_page(
    keywords: list[str], url: str, title: str | None, meta: str | None, word_count: int | None
) -> PageMatch | None:
    """A page matches a topic when at least half of the topic's keywords (min 2,
    or all of them for single-keyword topics) appear in its URL, title or meta."""
    if not keywords:
        return None
    hay = f"{url} {title or ''} {meta or ''}".lower()
    hits = [k for k in set(keywords) if k in hay]
    needed = max(1, (len(set(keywords)) + 1) // 2) if len(set(keywords)) > 1 else 1
    if len(hits) < needed:
        return None
    return PageMatch(
        url=url,
        title=title,
        word_count=word_count,
        matched_keywords=sorted(hits),
        categories=page_categories(url, title),
    )


def coverage_strength(matches: list[PageMatch]) -> float:
    """0 = nothing, 1 = clearly covered. A substantial page counts 1.0, a thin one 0.4."""
    return min(1.0, sum(1.0 if m.substantial else 0.4 for m in matches))


@dataclass
class TopicFacts:
    """Everything observed about one topic (one prompt) in the window."""

    prompt_id: str
    prompt_text: str
    category: str
    funnel_stage: str
    responses: int
    brand_mentions: int
    competitor_mentions: dict[str, int]  # name → responses mentioning it
    providers: list[str] = field(default_factory=list)
    research_domains: list[str] = field(default_factory=list)  # research sources cited on topic
    competitor_research_domains: list[str] = field(default_factory=list)
    brand_cited: int = 0  # responses citing the brand's site on this topic
    citations: int = 0
    matches: list[PageMatch] = field(default_factory=list)

    @property
    def brand_rate(self) -> float:
        return 100.0 * self.brand_mentions / self.responses if self.responses else 0.0

    @property
    def top_competitor(self) -> tuple[str, int] | None:
        if not self.competitor_mentions:
            return None
        return max(self.competitor_mentions.items(), key=lambda kv: (kv[1], kv[0]))

    @property
    def competitor_rate(self) -> float:
        top = self.top_competitor
        return 100.0 * top[1] / self.responses if top and self.responses else 0.0


def confidence_for(responses: int) -> GapConfidence:
    for threshold, label in CONFIDENCE_LADDER:
        if responses >= threshold:
            return label
    return GapConfidence.INSUFFICIENT


def needed_gap_type(category: str, prompt_text: str) -> ContentGapType | None:
    """The structural page type this prompt calls for, if any."""
    by_category = NEEDED_BY_CATEGORY.get(category)
    if by_category is not None:
        return by_category
    if category in ("problem_solution", "faq") or QUESTION_START.match(prompt_text.strip()):
        return ContentGapType.MISSING_FAQ
    if re.search(r"\bfor\s+[a-z]+", prompt_text.lower()) and category in ("discovery", "industry"):
        return ContentGapType.MISSING_USE_CASE
    return None


def classify(facts: TopicFacts) -> list[ContentGapType]:
    """Gap types for one topic. Empty when competitors are not clearly ahead or the
    sample is too small — content is never recommended blindly."""
    if facts.responses < MIN_TOPIC_RESPONSES:
        return []
    if facts.competitor_rate < MIN_COMPETITOR_RATE:
        return []
    if facts.competitor_rate - facts.brand_rate < MIN_RATE_GAP:
        return []
    out: list[ContentGapType] = []
    coverage = coverage_strength(facts.matches)
    needed = needed_gap_type(facts.category, facts.prompt_text)
    if coverage == 0.0:
        out.append(needed or ContentGapType.MISSING_TOPIC)
    elif coverage < 1.0:
        out.append(ContentGapType.WEAK_TOPIC)
    elif needed is not None and NEEDED_PAGE_CATEGORY[needed] not in {
        c for m in facts.matches for c in m.categories
    }:
        # topic covered in general, but not with the page type the prompt calls for
        out.append(needed)
    if (
        facts.competitor_research_domains
        and facts.brand_cited == 0
        and ContentGapType.MISSING_TOPIC not in out
    ):
        out.append(ContentGapType.MISSING_EVIDENCE)
    return out


def score(facts: TopicFacts) -> dict[str, Any]:
    coverage = coverage_strength(facts.matches)
    components = {
        "competitor_advantage": max(0.0, facts.competitor_rate - facts.brand_rate) / 100.0,
        "prompt_frequency": min(1.0, facts.responses / FREQUENCY_SATURATION),
        "commercial_relevance": (
            1.0
            if facts.category in COMMERCIAL_CATEGORIES or facts.funnel_stage in COMMERCIAL_STAGES
            else 0.4
        ),
        "coverage_deficit": 1.0 - coverage,
        "evidence_availability": 1.0 if facts.citations else 0.3,
    }
    total = round(sum(WEIGHTS[k] * v for k, v in components.items()), 1)
    return {
        "score": total,
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": WEIGHTS,
        "coverage_strength": round(coverage, 2),
    }
