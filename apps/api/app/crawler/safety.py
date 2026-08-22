"""SSRF protection for the crawler.

Every URL the crawler is about to fetch — including every redirect hop —
passes through `UrlSafetyPolicy.check()`, which validates the scheme, rejects
hostnames that are obviously internal, resolves DNS, and refuses any address
in a private, loopback, link-local, multicast, reserved, or cloud-metadata
range. The resolved addresses are returned so the fetcher can pin them and
avoid DNS rebinding between check and connect.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.crawler.urls import CrawlURL

Resolver = Callable[[str], Awaitable[list[str]]]

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan", ".corp")

# Cloud metadata and other well-known sensitive addresses, beyond the RFC ranges.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "169.254.169.254/32",  # AWS/GCP/Azure metadata (also covered by link-local)
        "100.100.100.200/32",  # Alibaba metadata
        "fd00:ec2::254/128",  # AWS IMDS IPv6
        "0.0.0.0/8",
        "100.64.0.0/10",  # CGNAT
        "192.0.0.0/24",
        "198.18.0.0/15",  # benchmarking
        "240.0.0.0/4",
        "::/128",
        "64:ff9b::/96",  # NAT64
    )
]


class UnsafeURLError(ValueError):
    pass


@dataclass(frozen=True)
class SafetyVerdict:
    host: str
    addresses: tuple[str, ...]


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    ):
        return False
    return all(ip not in net for net in _BLOCKED_NETWORKS)


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


class UrlSafetyPolicy:
    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolve = resolver or system_resolver

    def check_host_syntax(self, host: str) -> None:
        if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeURLError(f"host {host!r} is not allowed")
        if "." not in host and ":" not in host:
            raise UnsafeURLError(f"host {host!r} is not a public domain name")
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return
        if not is_public_address(str(literal)):
            raise UnsafeURLError(f"address {host!r} is not public")

    async def check(self, url: CrawlURL) -> SafetyVerdict:
        """Raise UnsafeURLError unless the URL points at a public HTTP(S) endpoint."""
        if url.scheme not in ("http", "https"):
            raise UnsafeURLError(f"scheme {url.scheme!r} is not allowed")
        self.check_host_syntax(url.host)
        try:
            addresses = await self._resolve(url.host)
        except (OSError, ValueError) as exc:
            raise UnsafeURLError(f"could not resolve {url.host!r}") from exc
        if not addresses:
            raise UnsafeURLError(f"{url.host!r} did not resolve")
        for address in addresses:
            if not is_public_address(address):
                raise UnsafeURLError(f"{url.host!r} resolves to non-public address {address}")
        return SafetyVerdict(host=url.host, addresses=tuple(addresses))
