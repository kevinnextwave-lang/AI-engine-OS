"""Probabilistic source-domain classification.

Every signal is a small function that returns *evidence* — (domain type,
weight in (0, 1], signal name, detail). Evidence is combined per type with a
noisy-OR (`1 - Π(1 - w)`), normalised into a probability distribution, and the
top type is accepted only when its combined score clears the configured
threshold. Otherwise the domain stays `unknown` and the candidates are still
reported, so "we don't know" is explicit rather than a forced guess.

Signals (in the order the spec lists them):
  1. hostname          – project/competitor host ⇒ company; subdomain prefixes
  2. TLD               – government / education suffixes
  3. known patterns    – hostname prefixes, URL path patterns from the registry
  4. page title        – keywords in cited page titles
  5. page metadata     – og:type / generator hints when a page was fetched
  6. URL structure     – path patterns over the cited URLs
  7. source registry   – curated known-domain lists (strongest signal)
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.models.sources import DomainType
from app.sources.registry import SourceRegistry

# Evidence weights: how much one observation of a signal says on its own.
W_REGISTRY = 0.9
W_COMPANY = 0.95
W_TLD = 0.9
W_HOST_PATTERN = 0.45
W_PATH_PATTERN = 0.25
W_TITLE = 0.2
W_METADATA = 0.25
# Weak signals saturate: at most this many observations of one signal count.
MAX_OBSERVATIONS = 4


@dataclass(frozen=True)
class Evidence:
    domain_type: DomainType
    weight: float
    signal: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.domain_type.value,
            "weight": round(self.weight, 3),
            "signal": self.signal,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PageSignals:
    url: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Classification:
    domain_type: DomainType
    confidence: float  # combined score of the chosen type (0 for unknown)
    probabilities: dict[str, float]  # every candidate type → share
    evidence: list[Evidence]
    authority: bool
    threshold: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.domain_type.value,
            "confidence": round(self.confidence, 3),
            "probabilities": {k: round(v, 3) for k, v in self.probabilities.items()},
            "authority": self.authority,
            "threshold": self.threshold,
            "evidence": [e.as_dict() for e in self.evidence],
        }


# -- signals ---------------------------------------------------------------------


def signal_company(host: str, company_hosts: frozenset[str]) -> list[Evidence]:
    for c in company_hosts:
        if host == c or host.endswith("." + c):
            return [
                Evidence(DomainType.COMPANY, W_COMPANY, "hostname", f"project/competitor host {c}")
            ]
    return []


def signal_tld(host: str, reg: SourceRegistry) -> list[Evidence]:
    gov = reg.suffix_match(host, reg.government_suffixes)
    if gov:
        return [Evidence(DomainType.GOVERNMENT, W_TLD, "tld", gov)]
    edu = reg.suffix_match(host, reg.education_suffixes)
    if edu:
        return [Evidence(DomainType.EDUCATION, W_TLD, "tld", edu)]
    return []


def signal_registry(host: str, reg: SourceRegistry) -> list[Evidence]:
    return [
        Evidence(dtype, W_REGISTRY, "registry", f"{entry} in {key}")
        for dtype, entry, key in reg.category_matches(host)
    ]


def signal_hostname_patterns(host: str, reg: SourceRegistry) -> list[Evidence]:
    out = []
    for type_key, prefixes in reg.hostname_patterns.items():
        for prefix in prefixes:
            if host.startswith(prefix):
                out.append(
                    Evidence(DomainType(type_key), W_HOST_PATTERN, "hostname_pattern", prefix)
                )
                break
    return out


def _paths(pages: Iterable[PageSignals]) -> list[str]:
    out = []
    for p in pages:
        if p.url:
            try:
                out.append(urlsplit(p.url).path.lower() or "/")
            except ValueError:
                continue
    return out


def signal_url_structure(pages: Iterable[PageSignals], reg: SourceRegistry) -> list[Evidence]:
    out: list[Evidence] = []
    counts: dict[tuple[str, str], int] = {}
    for path in _paths(pages):
        for type_key, patterns in reg.path_patterns.items():
            for pat in patterns:
                if pat in path:
                    counts[(type_key, pat)] = counts.get((type_key, pat), 0) + 1
                    break
    for (type_key, pat), n in counts.items():
        for _ in range(min(n, MAX_OBSERVATIONS)):
            out.append(Evidence(DomainType(type_key), W_PATH_PATTERN, "url_structure", pat))
    return out


def signal_titles(pages: Iterable[PageSignals], reg: SourceRegistry) -> list[Evidence]:
    out: list[Evidence] = []
    counts: dict[tuple[str, str], int] = {}
    for p in pages:
        title = (p.title or "").lower()
        if not title:
            continue
        for type_key, words in reg.title_keywords.items():
            for w in words:
                if w in title:
                    counts[(type_key, w)] = counts.get((type_key, w), 0) + 1
                    break
    for (type_key, w), n in counts.items():
        for _ in range(min(n, MAX_OBSERVATIONS)):
            out.append(Evidence(DomainType(type_key), W_TITLE, "page_title", w))
    return out


_OG_TYPE = {
    "article": DomainType.MEDIA,
    "profile": DomainType.SOCIAL,
    "product": DomainType.COMPANY,
}
_GENERATORS = {
    "wordpress": DomainType.BLOG,
    "ghost": DomainType.BLOG,
    "discourse": DomainType.FORUM,
}


def signal_metadata(pages: Iterable[PageSignals]) -> list[Evidence]:
    out: list[Evidence] = []
    for p in pages:
        meta = {str(k).lower(): str(v).lower() for k, v in (p.metadata or {}).items()}
        og = meta.get("og:type", "")
        if og in _OG_TYPE:
            out.append(Evidence(_OG_TYPE[og], W_METADATA, "page_metadata", f"og:type={og}"))
        gen = meta.get("generator", "")
        for name, dtype in _GENERATORS.items():
            if name in gen:
                out.append(Evidence(dtype, W_METADATA, "page_metadata", f"generator={name}"))
    return out[: MAX_OBSERVATIONS * 2]


# -- combination --------------------------------------------------------------------


def combine(evidence: list[Evidence]) -> dict[DomainType, float]:
    """Noisy-OR per type: independent weak signals add up, one strong signal dominates."""
    scores: dict[DomainType, float] = {}
    for e in evidence:
        scores[e.domain_type] = 1 - (1 - scores.get(e.domain_type, 0.0)) * (1 - e.weight)
    return scores


def classify(
    host: str,
    *,
    registry: SourceRegistry,
    pages: Iterable[PageSignals] = (),
    company_hosts: frozenset[str] = frozenset(),
    threshold: float = 0.5,
) -> Classification:
    pages = list(pages)
    evidence = [
        *signal_company(host, company_hosts),
        *signal_tld(host, registry),
        *signal_hostname_patterns(host, registry),
        *signal_titles(pages, registry),
        *signal_metadata(pages),
        *signal_url_structure(pages, registry),
        *signal_registry(host, registry),
    ]
    scores = combine(evidence)
    total = sum(scores.values())
    probabilities = {t.value: s / total for t, s in scores.items()} if total else {}
    authority = registry.is_authority(host)
    if not scores:
        return Classification(DomainType.UNKNOWN, 0.0, {}, evidence, authority, threshold)
    best, best_score = max(scores.items(), key=lambda kv: kv[1])
    # A tie between strong candidates is not a decision.
    runner_up = max((s for t, s in scores.items() if t != best), default=0.0)
    if best_score < threshold or (runner_up and best_score - runner_up < 0.05):
        return Classification(
            DomainType.UNKNOWN, 0.0, probabilities, evidence, authority, threshold
        )
    return Classification(best, best_score, probabilities, evidence, authority, threshold)
