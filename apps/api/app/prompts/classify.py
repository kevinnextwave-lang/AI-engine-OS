"""Rule-based categorization of a prompt's category, intent and funnel stage.
Used for manual prompts and to double-check generated ones."""

import re
from dataclasses import dataclass

from app.models.prompts import FunnelStage, PromptCategory, PromptIntent

_RULES: tuple[tuple[PromptCategory, re.Pattern[str]], ...] = (
    (
        PromptCategory.PRICING,
        re.compile(
            r"\b(pric(e|es|ing)|cost|how much|cheap|affordable|free plan|budget|"
            r"subscription fee)\b",
            re.I,
        ),
    ),
    (
        PromptCategory.ALTERNATIVE,
        re.compile(
            r"\b(alternatives?|instead of|replace(ment)?|switch(ing)? from|similar to)\b", re.I
        ),
    ),
    (
        PromptCategory.COMPARISON,
        re.compile(
            r"\b(vs\.?|versus|compared? (to|with)|comparison|compare|difference(s)? between|"
            r"better than|which is better)\b",
            re.I,
        ),
    ),
    (
        PromptCategory.LOCAL,
        re.compile(
            r"\b(near me|nearby|in (the )?[A-Z][\w-]+(?: [A-Z][\w-]+)?|local|closest|"
            r"in my (area|city|country))\b"
        ),
    ),
    (
        PromptCategory.RECOMMENDATION,
        re.compile(
            r"\b(best|top|recommend(ed|ation)?|which .* (should|is (the )?(best|easiest|most))|"
            r"most (popular|reliable|trusted))\b",
            re.I,
        ),
    ),
    (
        PromptCategory.PRODUCT,
        re.compile(
            r"\b(support(s)?|integrat(e|es|ion|ions)|feature(s)?|does .* (have|offer|include)|"
            r"work(s)? with|capabilit)",
            re.I,
        ),
    ),
    (
        PromptCategory.TRANSACTIONAL,
        re.compile(
            r"\b(buy|purchase|sign up|order|book|subscribe|get started|free trial|demo|quote)\b",
            re.I,
        ),
    ),
    (
        PromptCategory.PROBLEM_SOLUTION,
        re.compile(
            r"\b(how (do|can|to)|fix|solve|reduce|avoid|prevent|struggling|problem|issue|"
            r"improve|automate)\b",
            re.I,
        ),
    ),
    (
        PromptCategory.INDUSTRY,
        re.compile(
            r"\b(trends?|industry|market|regulation|compliance|statistics|future of|state of)\b",
            re.I,
        ),
    ),
    (
        PromptCategory.DISCOVERY,
        re.compile(
            r"\b(what (is|are)|who (is|are|offers|provides)|explain|overview|types of|"
            r"examples of)\b",
            re.I,
        ),
    ),
)

_CATEGORY_DEFAULTS: dict[PromptCategory, tuple[PromptIntent, FunnelStage]] = {
    PromptCategory.DISCOVERY: (PromptIntent.INFORMATIONAL, FunnelStage.AWARENESS),
    PromptCategory.INDUSTRY: (PromptIntent.INFORMATIONAL, FunnelStage.AWARENESS),
    PromptCategory.PROBLEM_SOLUTION: (PromptIntent.INFORMATIONAL, FunnelStage.AWARENESS),
    PromptCategory.RECOMMENDATION: (PromptIntent.COMMERCIAL, FunnelStage.CONSIDERATION),
    PromptCategory.COMPARISON: (PromptIntent.COMMERCIAL, FunnelStage.CONSIDERATION),
    PromptCategory.ALTERNATIVE: (PromptIntent.COMMERCIAL, FunnelStage.CONSIDERATION),
    PromptCategory.PRODUCT: (PromptIntent.COMMERCIAL, FunnelStage.CONSIDERATION),
    PromptCategory.LOCAL: (PromptIntent.COMMERCIAL, FunnelStage.DECISION),
    PromptCategory.PRICING: (PromptIntent.TRANSACTIONAL, FunnelStage.DECISION),
    PromptCategory.TRANSACTIONAL: (PromptIntent.TRANSACTIONAL, FunnelStage.PURCHASE),
}

_RETENTION = re.compile(
    r"\b(cancel|renew|upgrade|downgrade|migrate|export|support ticket|refund|churn|how to use|"
    r"tutorial|set ?up)\b",
    re.I,
)
_NAVIGATIONAL = re.compile(
    r"\b(login|log in|sign in|website|official site|contact|customer service|phone number)\b", re.I
)


@dataclass(frozen=True)
class Classification:
    category: PromptCategory
    intent: PromptIntent
    funnel_stage: FunnelStage


def classify(text: str) -> Classification:
    category = PromptCategory.DISCOVERY
    for cat, pattern in _RULES:
        if pattern.search(text):
            category = cat
            break
    intent, stage = _CATEGORY_DEFAULTS[category]
    if _RETENTION.search(text):
        stage = FunnelStage.RETENTION
    if _NAVIGATIONAL.search(text):
        intent = PromptIntent.NAVIGATIONAL
    return Classification(category, intent, stage)
