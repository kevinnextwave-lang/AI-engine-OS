"""Source 1 — deterministic candidate extraction from stored AI responses.

Looks at the lists and comparison phrasing of each parsed response and pulls
out *named things that look like products or companies*:

* list items ("1. **Xero** — …", "- FreshBooks: …") whose label is a short
  proper name;
* "alternatives to X", "X vs Y", "competitors such as A, B and C",
  "similar to X" phrasing (direct competitor language).

The brand, configured competitors (names, aliases, products, domains) and a
stop-list of generic words are excluded. Everything else becomes a raw
observation; the discovery service aggregates observations across responses
and only keeps names seen often enough.
"""

import re
from dataclasses import dataclass, field

from app.intelligence.deterministic import parse_structure

# Direct competitor language around a name (case-insensitive, sentence-level).
COMPETITOR_LANGUAGE = re.compile(
    r"\b(alternative|alternatives|competitor|competitors|compet(?:e|ing)s? with"
    r"|similar (?:to|companies|tools|products)"
    r"|instead of|rival|rivals|vs\.?|versus|compared (?:to|with)|comparison)\b",
    re.IGNORECASE,
)
# "alternatives to X", "competitors such as A, B and C", "X vs Y"
_ALT_TO = re.compile(
    r"\b(?:alternatives?|competitors?|similar (?:tools|products|companies))"
    r"\s+(?:to|of|like|such as|include|including)\s+([^.\n]{2,120})",
    re.IGNORECASE,
)
_NAME = r"[A-Z][\w&.+-]{1,40}(?: [A-Z][\w&.+-]{1,40}){0,2}"
_VS = re.compile(rf"\b({_NAME})\s+(?:vs\.?|versus)\s+({_NAME})")
_LABEL = re.compile(
    r"^\s*([A-Z][\w&.+'’-]{1,40}(?:\s+[A-Z0-9][\w&.+'’-]{0,40}){0,3})(?=\s*[:—–\-(|,]|\s*$)"
)
_SPLIT = re.compile(
    r",|\band\b|\bor\b|&|/|;|\binclud(?:e|es|ing)\b|\bsuch as\b|\blike\b", re.IGNORECASE
)
_URL = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)

STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "to",
        "in",
        "on",
        "by",
        "at",
        "best",
        "top",
        "free",
        "cheap",
        "affordable",
        "popular",
        "other",
        "others",
        "more",
        "overview",
        "summary",
        "pros",
        "cons",
        "pricing",
        "features",
        "conclusion",
        "note",
        "tip",
        "tips",
        "why",
        "how",
        "what",
        "when",
        "which",
        "here",
        "there",
        "overall",
        "option",
        "options",
        "tool",
        "tools",
        "software",
        "platform",
        "platforms",
        "solution",
        "solutions",
        "service",
        "services",
        "company",
        "companies",
        "product",
        "products",
        "key",
        "main",
        "final",
        "first",
        "second",
        "third",
        "step",
        "steps",
        "example",
        "examples",
        "sources",
        "source",
        "references",
        "yes",
        "no",
        "none",
        "n/a",
    }
)


@dataclass
class Observation:
    name: str
    competitor_language: bool
    position: int | None = None
    context: str = ""
    domains: set[str] = field(default_factory=set)


def _clean_name(raw: str) -> str | None:
    name = raw.strip().strip("*_`\"'“”‘’()[]").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) < 2 or len(name) > 60:
        return None
    words = name.split()
    if len(words) > 4:
        return None
    if all(w.lower() in STOP_WORDS for w in words):
        return None
    if words[0].lower() in STOP_WORDS and len(words) == 1:
        return None
    if not any(ch.isalpha() for ch in name):
        return None
    # must look like a proper name: starts with an upper-case letter or digit
    if not (name[0].isupper() or name[0].isdigit()):
        return None
    return name


def extract_observations(text: str, excluded: frozenset[str]) -> list[Observation]:
    """`excluded` holds normalised names to drop (brand, known competitors…)."""
    from app.competitors.normalize import is_known_identity, normalize_name

    found: dict[str, Observation] = {}

    def add(raw: str, *, language: bool, position: int | None, context: str) -> None:
        name = _clean_name(raw)
        if name is None:
            return
        key = normalize_name(name)
        if not key or is_known_identity(key, excluded):
            return
        stem = normalize_name(name.split()[0])
        domains = {
            d
            for d in (_host(u) for u in _URL.findall(context))
            if d and (key in d.replace("-", "").replace(".", "") or (len(stem) >= 4 and stem in d))
        }
        existing = found.get(key)
        if existing is not None:
            existing.competitor_language = existing.competitor_language or language
            existing.domains |= domains
            if existing.position is None:
                existing.position = position
            return
        found[key] = Observation(
            name=name,
            competitor_language=language,
            position=position,
            context=context[:300],
            domains=domains,
        )

    structure = parse_structure(text)
    for block in structure.blocks:
        if block.kind == "item":
            m = _LABEL.match(block.text)
            if m:
                language = bool(COMPETITOR_LANGUAGE.search(block.text))
                add(
                    m.group(1),
                    language=language,
                    position=block.index,
                    context=block.raw or block.text,
                )
        if block.kind in ("paragraph", "item", "heading"):
            for m in _ALT_TO.finditer(block.text):
                for part in _SPLIT.split(m.group(1)):
                    add(part, language=True, position=None, context=block.raw or block.text)
            for m in _VS.finditer(block.text):
                for part in (m.group(1), m.group(2)):
                    add(part, language=True, position=None, context=block.raw or block.text)
    return list(found.values())


def _host(url: str) -> str | None:
    from app.sources.normalize import normalize_hostname

    try:
        from urllib.parse import urlsplit

        return normalize_hostname(urlsplit(url).hostname)
    except ValueError:
        return None
