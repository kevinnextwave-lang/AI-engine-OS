"""Centralized crawl URL normalization.

Goals: the same page always maps to the same normalized string, without
collapsing genuinely different pages. We therefore:

- lowercase scheme and host, strip default ports and fragments
- resolve dot-segments, percent-encode consistently
- drop a known list of tracking parameters (never *all* parameters)
- sort the remaining query parameters for stable comparison
- remove a trailing slash except on the root path ("/") and paths that look
  like directories with an extension-less final segment are left alone
  (we keep "/about/" and "/about" distinct? No: we treat them as the same,
  because servers overwhelmingly serve the same document; the canonical tag
  will tell us which the site prefers)
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "ttclid",
        "twclid",
        "mc_cid",
        "mc_eid",
        "yclid",
        "_ga",
        "_gl",
        "igshid",
        "ref_src",
        "spm",
    }
)
TRACKING_PREFIXES: tuple[str, ...] = ("utm_", "hsa_", "pk_", "mtm_", "piwik_", "matomo_")

_SAFE_PATH = "/-._~!$&'()*+,;=:@%"
_SAFE_QUERY = "-._~!$'()*+,;:@/?%"


class CrawlURLError(ValueError):
    pass


@dataclass(frozen=True)
class CrawlURL:
    normalized: str
    scheme: str
    host: str
    port: int | None
    path: str

    @property
    def origin(self) -> str:
        netloc = self.host if self.port is None else f"{self.host}:{self.port}"
        return f"{self.scheme}://{netloc}"


def is_tracking_param(name: str) -> bool:
    lower = name.lower()
    return lower in TRACKING_PARAMS or lower.startswith(TRACKING_PREFIXES)


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    # Decode then re-encode so %7E and ~ compare equal and spaces are encoded.
    decoded = unquote(path)
    # urljoin against a dummy base resolves ./ and ../ segments.
    resolved = urlsplit(urljoin("http://x/", decoded)).path or "/"
    encoded = quote(resolved, safe=_SAFE_PATH)
    if len(encoded) > 1 and encoded.endswith("/"):
        encoded = encoded.rstrip("/") or "/"
    return encoded


def _normalize_query(query: str) -> str:
    if not query:
        return ""
    pairs = [
        (k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not is_tracking_param(k)
    ]
    pairs.sort()
    return urlencode(pairs, safe=_SAFE_QUERY)


def normalize_crawl_url(raw: str, base: str | None = None) -> CrawlURL:
    """Normalize `raw` (optionally relative to `base`). Raises CrawlURLError if unusable."""
    value = (raw or "").strip()
    if not value:
        raise CrawlURLError("empty URL")
    if base:
        value = urljoin(base, value)
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise CrawlURLError(f"unsupported scheme: {scheme or 'none'}")
    if parts.username or parts.password:
        raise CrawlURLError("credentials in URL")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise CrawlURLError("missing host")
    try:
        host = host.encode("idna").decode("ascii")
        port = parts.port
    except (UnicodeError, ValueError) as exc:
        raise CrawlURLError("invalid host or port") from exc
    if port in (None, 80 if scheme == "http" else 443):
        port = None
    path = _normalize_path(parts.path)
    query = _normalize_query(parts.query)
    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit((scheme, netloc, path, query, ""))
    if len(normalized) > 2048:
        raise CrawlURLError("URL too long")
    return CrawlURL(normalized=normalized, scheme=scheme, host=host, port=port, path=path)


def same_site(host: str, root_host: str, *, allow_subdomains: bool) -> bool:
    """True if `host` is the root host or (optionally) a subdomain of it."""
    host, root_host = host.lower(), root_host.lower()
    if host == root_host:
        return True
    # www. and bare apex are treated as the same site in both directions.
    if host.removeprefix("www.") == root_host.removeprefix("www."):
        return True
    if allow_subdomains:
        apex = root_host.removeprefix("www.")
        return host.endswith("." + apex)
    return False
