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


def classify_domain(
    normalized_hostname: str, *, company_hosts: frozenset[str] = frozenset()
) -> DomainType:
    """Hostname-only classification (registry, TLD, project hosts). The full
    signal-based classifier lives in `app.sources.classify`; this is the cheap
    path used when a domain is first seen."""
    from app.sources.classify import classify
    from app.sources.registry import get_registry

    return classify(
        normalized_hostname, registry=get_registry(), company_hosts=company_hosts
    ).domain_type


def host_matches(host: str, candidates: set[str]) -> str | None:
    """The candidate host that `host` equals or is a subdomain of, if any."""
    for c in candidates:
        if host == c or host.endswith("." + c):
            return c
    return None
