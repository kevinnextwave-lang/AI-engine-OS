"""Deterministic text/heading signal detectors shared by the analyzers.

Each detector returns counts or matched snippets so observations can show
their evidence. These are lexical heuristics, stated as such in the output.
"""

import re
from dataclasses import dataclass

# -- audience / geography / contact ---------------------------------------------

AUDIENCE = re.compile(
    r"\b(?:(?:built|designed|made|created|ideal|perfect|tailored)\s+for|for\s+(?:small|mid-?size|"
    r"large|growing|modern|busy|independent)?\s*(?:businesses|companies|teams|startups|"
    r"enterprises?|agencies|developers|marketers|founders|freelancers|schools|clinics|"
    r"restaurants|retailers|manufacturers|nonprofits|professionals|organizations|"
    r"organisations|brands|shops|stores|hotels|hospitals|dentists|lawyers|accountants|"
    r"families|students|parents|homeowners|patients|engineers|designers|consultants|"
    r"sales\s+teams|hr\s+teams|finance\s+teams|product\s+teams)|who\s+(?:it'?s|is\s+it)\s+for|"
    r"trusted\s+by|used\s+by|customers?\s+(?:include|like)|our\s+(?:customers|clients)\s+are)\b",
    re.I,
)
GEOGRAPHY = re.compile(
    r"\b(?:(?:based|headquartered|located|founded|offices?)\s+in|serving|we\s+serve|available\s+in|"
    r"ship(?:ping|s)?\s+to|operat(?:e|ing)\s+in|worldwide|globally|nationwide|international(?:ly)?|"
    r"across\s+(?:the\s+)?(?:us|usa|uk|eu|europe|north\s+america|asia|australia|canada|africa|"
    r"latin\s+america|\d+\s+countries)|in\s+\d+\s+countries)\b",
    re.I,
)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(r"(?<![\w/(])\(?\+?\d[\d\s().-]{6,20}\d(?![\w/])")
POSTAL_ADDRESS = re.compile(
    r"\b\d{1,5}\s+[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3}\s+(?:street|st\.?|avenue|ave\.?|road|rd\.?|"
    r"boulevard|blvd\.?|lane|ln\.?|drive|dr\.?|way|place|plaza|square|strasse|straße|rue)\b",
    re.I,
)

# -- product aspects ------------------------------------------------------------------

FEATURES_HEADING = re.compile(
    r"\b(features?|capabilities|what(?:'s| is) included|what you get|benefits|how it works|"
    r"key\s+functions|functionality)\b",
    re.I,
)
PRICING = re.compile(
    r"(?:[$€£¥]\s?\d[\d,.]*|\d[\d,.]*\s?(?:usd|eur|gbp|chf|€|\$)|\bper\s+(?:month|year|user|seat)\b|"
    r"/\s?(?:mo|month|yr|year|user|seat)\b|\bfree\s+(?:plan|tier|trial|forever)\b|\bpricing\b|"
    r"\bprice\b|\bstarting\s+at\b|\bquote\b)",
    re.I,
)
USE_CASES = re.compile(
    r"\b(use\s?cases?|how\s+(?:teams|companies|customers|people)\s+use|used\s+to|helps?\s+you|"
    r"so\s+you\s+can|scenarios?|examples?\s+of\s+use|workflows?)\b",
    re.I,
)
INTEGRATIONS = re.compile(
    r"\b(integrat(?:e|es|ed|ion|ions)|works\s+with|connects?\s+(?:to|with)|plugs?\s+into|"
    r"\bapi\b|webhooks?|zapier|slack|salesforce|hubspot|shopify|wordpress|sync(?:s|ing)?\s+with)\b",
    re.I,
)

# -- authority ------------------------------------------------------------------------

BYLINE = re.compile(
    r"(?:^|\n)\s*(?:by|written\s+by|author:?)\s+([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})", re.M
)
AUTHOR_BIO = re.compile(
    r"\b(about\s+the\s+author|author\s+bio|written\s+by|reviewed\s+by|fact[- ]checked\s+by)\b", re.I
)
CREDENTIALS = re.compile(
    r"\b(ph\.?d|m\.?d\.?|mba|cpa|cfa|rn|esq|professor|ceo|cto|cfo|coo|founder|co-founder|"
    r"director|head\s+of|engineer|scientist|researcher|certified|licensed|years?\s+of\s+experience|"
    r"specialist|expert\s+in)\b",
    re.I,
)
DATE_TEXT = re.compile(
    r"\b(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
    r"(?:\d{1,2},?\s+)?(?:19|20)\d{2}\b|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b",
    re.I,
)

# -- evidence ----------------------------------------------------------------------------

STATISTIC = re.compile(
    r"\b\d[\d,.]*\s?(?:%|percent|x\b|times\b|million|billion|k\b|hours?|days?|minutes?)", re.I
)
RESEARCH = re.compile(
    r"\b(study|studies|research|survey(?:ed)?|report(?:ed)?\s+(?:by|that|found)|according\s+to|"
    r"peer[- ]reviewed|whitepaper|white\s+paper|analysis\s+(?:of|by|shows)|benchmark(?:s|ed)?)\b",
    re.I,
)
ORIGINAL_DATA = re.compile(
    r"\b(our\s+(?:data|research|study|survey|analysis|benchmark|findings)|we\s+(?:analy[sz]ed|"
    r"surveyed|measured|tested|studied|tracked|collected)|internal\s+data|proprietary\s+data|"
    r"based\s+on\s+\d[\d,]*\s+(?:customers|users|companies|respondents|data\s+points|sites|pages))\b",
    re.I,
)
CITATION = re.compile(
    r"\[\d{1,3}\]|\bet\s+al\.|\b(?:source|sources|references?|citations?|bibliography):?\b", re.I
)
CASE_STUDY = re.compile(
    r"\b(case\s+stud(?:y|ies)|success\s+stor(?:y|ies)|customer\s+stor(?:y|ies))\b", re.I
)
CUSTOMER_EVIDENCE = re.compile(
    r"\b(testimonials?|reviews?|rated\s+\d|\d(?:\.\d)?\s*/\s*5|★|stars?\b|trusted\s+by|"
    r"customers?\s+(?:say|love|report)|what\s+(?:our\s+)?(?:customers|clients|users)\s+say|"
    r"g2|capterra|trustpilot|clutch)\b",
    re.I,
)

# -- faq -----------------------------------------------------------------------------------

FAQ_HEADING = re.compile(
    r"\b(faq|faqs|frequently\s+asked|questions?\s*(?:&|and)\s*answers?|q\s*&\s*a)\b", re.I
)
QUESTION_HEADING = re.compile(
    r"^\s*(?:q:\s*)?(?:what|why|how|when|where|who|which|can|do|does|is|are|should|will|could)\b.*\?\s*$",
    re.I,
)

# -- specificity ---------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])\d[\d,.]*(?:%|[kKmMbB])?(?![\w.])")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_PROPER_NOUN = re.compile(
    r"(?<![.!?]\s)(?<!^)\b(?:[A-Z][\w&'-]+(?:\s+(?:of|and|&|de|the)\s+)?){2,}", re.M
)
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([A-Z][\w'-]*)")


@dataclass
class SpecificityFacts:
    sentences: int
    specific_sentences: int
    numbers: int
    dates: int
    named_entities: int
    product_mentions: int
    organization_mentions: int

    @property
    def ratio(self) -> float:
        return self.specific_sentences / self.sentences if self.sentences else 0.0


def specificity(
    text: str, product_names: list[str], organization_names: list[str]
) -> SpecificityFacts:
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if len(s.split()) >= 4]
    numbers = len(NUMBER.findall(text))
    dates = len(DATE_TEXT.findall(text))
    named = len(_PROPER_NOUN.findall(text))
    lowered = text.lower()
    products = sum(lowered.count(n.lower()) for n in product_names if len(n) >= 3)
    orgs = sum(lowered.count(n.lower()) for n in organization_names if len(n) >= 3)
    specific = 0
    for s in sentences:
        if NUMBER.search(s) or DATE_TEXT.search(s):
            specific += 1
            continue
        lowered_s = s.lower()
        if any(n.lower() in lowered_s for n in product_names + organization_names if len(n) >= 3):
            specific += 1
    return SpecificityFacts(
        sentences=len(sentences),
        specific_sentences=specific,
        numbers=numbers,
        dates=dates,
        named_entities=named,
        product_mentions=products,
        organization_mentions=orgs,
    )


def snippets(pattern: re.Pattern[str], text: str, limit: int = 3, width: int = 80) -> list[str]:
    """Short excerpts around the first matches, for evidence."""
    out: list[str] = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - width // 2)
        end = min(len(text), m.end() + width // 2)
        out.append(" ".join(text[start:end].split()))
        if len(out) >= limit:
            break
    return out
