"""Name / alias normalisation for duplicate detection."""

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SUFFIXES = ("inc", "llc", "ltd", "limited", "corp", "corporation", "co", "gmbh", "plc", "sa")


def normalize_name(value: str) -> str:
    """Lower-case, ASCII-fold, drop punctuation and common company suffixes:
    `QuickBooks, Inc.` → `quickbooks`; `Quick Books` → `quickbooks`."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    tokens = [t for t in _NON_ALNUM.sub(" ", folded.lower()).split() if t]
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return "".join(tokens)
