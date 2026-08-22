"""Primary-language resolution.

Order of trust:
1. `<html lang>` (declared by the site)
2. metadata (`og:locale`, `content-language`, `dc.language`)
3. a conservative stop-word detector as a fallback — it only answers when
   the evidence is clear, otherwise returns None rather than guessing.

The detector is intentionally small (no external model). It distinguishes
the major Latin-script languages by function words; for anything else it
abstains. Callers must treat `source` as the confidence signal.
"""

import re
from dataclasses import dataclass

_WORD = re.compile(r"[a-zA-ZÀ-ÿ']+")

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and of to in is that for with as on are this by from it was be at or an".split()
    ),
    "de": frozenset(
        "der die und das ist nicht mit sich ein eine auf für von den dem des im zu auch".split()
    ),
    "fr": frozenset(
        "le la les et des est une un du dans pour que qui sur avec pas au ce plus".split()
    ),
    "es": frozenset(
        "el la los las y de que en un una es por con para del se no al como más".split()
    ),
    "it": frozenset(
        "il la di che e un una per non con del della sono le gli si da come anche".split()
    ),
    "pt": frozenset("o a os as de que e um uma para com não do da em no na se por mais".split()),
    "nl": frozenset(
        "de het een en van is dat op te zijn voor met niet ook aan bij als maar".split()
    ),
    "sv": frozenset("och att det i en som är av för på med till den inte har var om".split()),
    "da": frozenset("og at det i en som er af for på med til den ikke har var om".split()),
    "pl": frozenset("i w nie na z się że do jest to jak o co tak za od po".split()),
}
_MIN_WORDS = 40
_MIN_HITS = 8
_MIN_MARGIN = 1.6  # best score must beat runner-up by this factor


@dataclass(frozen=True)
class LanguageResult:
    code: str | None
    source: str | None  # "html_lang" | "metadata" | "detected" | None
    confidence: float | None


def normalize_lang_tag(value: str | None) -> str | None:
    if not value:
        return None
    tag = value.strip().replace("_", "-")
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", tag):
        return None
    parts = tag.split("-")
    parts[0] = parts[0].lower()
    if len(parts) > 1:
        parts[1] = parts[1].upper() if len(parts[1]) == 2 else parts[1].title()
    return "-".join(parts[:2])


def detect_language(text: str) -> LanguageResult:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < _MIN_WORDS:
        return LanguageResult(None, None, None)
    sample = words[:5000]
    scores = {code: sum(1 for w in sample if w in stop) for code, stop in _STOPWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, second = ranked[0], ranked[1]
    if best[1] < _MIN_HITS or best[1] < second[1] * _MIN_MARGIN:
        return LanguageResult(None, None, None)
    confidence = round(best[1] / max(1, len(sample)), 4)
    return LanguageResult(best[0], "detected", confidence)


def resolve_language(
    *, html_lang: str | None, metadata_lang: str | None, text: str
) -> LanguageResult:
    declared = normalize_lang_tag(html_lang)
    if declared:
        return LanguageResult(declared, "html_lang", 1.0)
    meta = normalize_lang_tag(metadata_lang)
    if meta:
        return LanguageResult(meta, "metadata", 0.9)
    return detect_language(text)
