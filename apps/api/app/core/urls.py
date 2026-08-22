"""Website URL normalization and validation.

Used for project domains and competitors so the same site is always stored
the same way: https scheme when none is given, lowercase punycode hostname,
no default port, no fragment, no trailing slash on a bare host.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


class InvalidURLError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedURL:
    url: str
    hostname: str


def normalize_website_url(raw: str) -> NormalizedURL:
    """Return a canonical URL + hostname, or raise InvalidURLError with a clear message."""
    value = (raw or "").strip()
    if not value:
        raise InvalidURLError("URL is required")
    if any(ch.isspace() for ch in value):
        raise InvalidURLError("URL must not contain whitespace")
    if "://" not in value:
        value = "https://" + value

    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise InvalidURLError("URL must use http or https")
    if parts.username or parts.password:
        raise InvalidURLError("URL must not contain credentials")

    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise InvalidURLError("URL must include a hostname")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidURLError("Hostname is not valid") from exc
    if host in _BLOCKED_HOSTS:
        raise InvalidURLError("Hostname is not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise InvalidURLError("URL must use a domain name, not an IP address")
    if len(host) > 253:
        raise InvalidURLError("Hostname is too long")
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise InvalidURLError("Hostname is not a valid domain name")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1]) or len(labels[-1]) < 2:
        raise InvalidURLError("Hostname must end with a valid top-level domain")

    port = parts.port
    default_port = 443 if parts.scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"

    path = parts.path or ""
    if path == "/":
        path = ""
    url = urlunsplit((parts.scheme, netloc, path, parts.query, ""))
    return NormalizedURL(url=url, hostname=host)
