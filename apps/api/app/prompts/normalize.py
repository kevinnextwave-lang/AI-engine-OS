"""Text normalization and near-duplicate detection (no embeddings)."""

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")
# Function words removed for similarity only (not for the stored normalized_text).
STOPWORDS = frozenset(
    "a an the of for to in on at with and or is are be which what who how does do can i my "
    "our your we you it its this that there any some per each every".split()
)
_PLURAL = re.compile(r"(?<=[a-z])(ies|es|s)$")


def normalize_text(text: str) -> str:
    """Canonical form for exact-duplicate detection: NFKD, lowercase, no punctuation,
    single spaces. Stored in prompts.normalized_text (unique per set)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = _PUNCT.sub(" ", t.lower())
    return _WS.sub(" ", t).strip()


def _stem(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    return _PLURAL.sub("", word)


def content_tokens(text: str) -> frozenset[str]:
    """Stemmed, stop-word-free token set used for near-duplicate similarity."""
    return frozenset(_stem(w) for w in normalize_text(text).split() if w not in STOPWORDS)


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of content tokens (0..1)."""
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 1.0 if normalize_text(a) == normalize_text(b) else 0.0
    return len(ta & tb) / len(ta | tb)


NEAR_DUPLICATE_THRESHOLD = 0.8


def is_near_duplicate(a: str, b: str, threshold: float = NEAR_DUPLICATE_THRESHOLD) -> bool:
    return normalize_text(a) == normalize_text(b) or similarity(a, b) >= threshold
