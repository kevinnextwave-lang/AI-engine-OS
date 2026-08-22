"""Hostname / URL normalisation and conservative domain classification.

Pure functions. Normalisation is deliberately simple and documented so the
same input always maps to the same source row:

hostname: lowercase, IDNA-encoded, trailing dot and a leading `www.` removed.
url:      scheme lowercased (http → https is NOT assumed), host normalised,
          default port dropped, fragment dropped, tracking parameters removed,
          remaining query parameters sorted, trailing slash removed except for
          the root path. Path case is preserved (paths are case-sensitive).
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.sources import DomainType

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "source",
    "_ga",
    "_gl",
    "yclid",
}
TRACKING_PREFIXES = ("utm_", "hsa_", "pk_", "mtm_")
DEFAULT_PORTS = {"http": "80", "https": "443"}

_HOST_RE = re.compile(r"^[a-z0-9.-]+$")


def normalize_hostname(value: str | None) -> str | None:
    """`WWW.Example.COM.` → `example.com`; None when not a plausible hostname."""
    if not value:
        return None
    host = value.strip().lower().rstrip(".")
    if "://" in host or "/" in host:
        host = (urlsplit(host if "://" in host else f"//{host}").hostname or "").lower()
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    host = host.removeprefix("www.")
    if not host or "." not in host or not _HOST_RE.match(host):
        return None
    return host


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def normalize_url(value: str | None) -> str | None:
    """Canonical form of a cited URL, or None when it has no usable host."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.IGNORECASE) and "://" not in raw:
        return None  # mailto:, tel:, javascript: …
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = normalize_hostname(parts.hostname)
    if host is None:
        return None
    port = parts.port
    netloc = host if port is None or str(port) == DEFAULT_PORTS[scheme] else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def display_name_for(hostname: str) -> str:
    """`docs.example.co.uk` → `example.co.uk`-ish: drop common leading subdomains."""
    parts = hostname.split(".")
    while len(parts) > 2 and parts[0] in ("www", "m", "en", "docs", "blog", "news", "support"):
        parts = parts[1:]
    return ".".join(parts)


# Evidence-based classification. Anything not listed is UNKNOWN on purpose.
_KNOWN: dict[str, DomainType] = {
    # social
    "twitter.com": DomainType.SOCIAL,
    "x.com": DomainType.SOCIAL,
    "linkedin.com": DomainType.SOCIAL,
    "facebook.com": DomainType.SOCIAL,
    "instagram.com": DomainType.SOCIAL,
    "youtube.com": DomainType.SOCIAL,
    "tiktok.com": DomainType.SOCIAL,
    "threads.net": DomainType.SOCIAL,
    # review
    "g2.com": DomainType.REVIEW,
    "capterra.com": DomainType.REVIEW,
    "trustpilot.com": DomainType.REVIEW,
    "trustradius.com": DomainType.REVIEW,
    "getapp.com": DomainType.REVIEW,
    "softwareadvice.com": DomainType.REVIEW,
    "yelp.com": DomainType.REVIEW,
    "gartner.com": DomainType.REVIEW,
    # community / forum
    "reddit.com": DomainType.COMMUNITY,
    "quora.com": DomainType.COMMUNITY,
    "stackoverflow.com": DomainType.FORUM,
    "stackexchange.com": DomainType.FORUM,
    "news.ycombinator.com": DomainType.FORUM,
    "discourse.org": DomainType.FORUM,
    # directory
    "crunchbase.com": DomainType.DIRECTORY,
    "producthunt.com": DomainType.DIRECTORY,
    "clutch.co": DomainType.DIRECTORY,
    "yellowpages.com": DomainType.DIRECTORY,
    # media
    "nytimes.com": DomainType.MEDIA,
    "forbes.com": DomainType.MEDIA,
    "techcrunch.com": DomainType.MEDIA,
    "theverge.com": DomainType.MEDIA,
    "wired.com": DomainType.MEDIA,
    "bbc.co.uk": DomainType.MEDIA,
    "bbc.com": DomainType.MEDIA,
    "reuters.com": DomainType.MEDIA,
    "bloomberg.com": DomainType.MEDIA,
    "wsj.com": DomainType.MEDIA,
    "cnbc.com": DomainType.MEDIA,
    "theguardian.com": DomainType.MEDIA,
    "zdnet.com": DomainType.MEDIA,
    # research
    "arxiv.org": DomainType.RESEARCH,
    "researchgate.net": DomainType.RESEARCH,
    "semanticscholar.org": DomainType.RESEARCH,
    "scholar.google.com": DomainType.RESEARCH,
    "nature.com": DomainType.RESEARCH,
    "sciencedirect.com": DomainType.RESEARCH,
    # blog platforms
    "medium.com": DomainType.BLOG,
    "substack.com": DomainType.BLOG,
    "wordpress.com": DomainType.BLOG,
    "blogspot.com": DomainType.BLOG,
    "dev.to": DomainType.BLOG,
    "hashnode.dev": DomainType.BLOG,
}
_GOV_SUFFIXES = (".gov", ".gov.uk", ".gouv.fr", ".gov.au", ".gc.ca", ".mil")
_EDU_SUFFIXES = (".edu", ".ac.uk", ".edu.au", ".ac.jp", ".ac.nz")


def classify_domain(
    normalized_hostname: str, *, company_hosts: frozenset[str] = frozenset()
) -> DomainType:
    """Only classifies on clear evidence: a project/competitor host (company),
    a government/education TLD, or a well-known platform. Otherwise UNKNOWN."""
    host = normalized_hostname
    if host in company_hosts or any(host.endswith("." + c) for c in company_hosts):
        return DomainType.COMPANY
    for suffix in _GOV_SUFFIXES:
        if host.endswith(suffix):
            return DomainType.GOVERNMENT
    for suffix in _EDU_SUFFIXES:
        if host.endswith(suffix):
            return DomainType.EDUCATION
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _KNOWN:
            return _KNOWN[candidate]
    return DomainType.UNKNOWN


def host_matches(host: str, candidates: set[str]) -> str | None:
    """The candidate host that `host` equals or is a subdomain of, if any."""
    for c in candidates:
        if host == c or host.endswith("." + c):
            return c
    return None
