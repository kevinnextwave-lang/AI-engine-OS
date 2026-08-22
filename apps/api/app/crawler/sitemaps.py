"""Sitemap discovery (sitemap.xml, sitemap indexes) with hard bounds."""

import xml.etree.ElementTree as ET  # noqa: S405 - parsed with size limits, entities disabled below

from app.core.logging import get_logger
from app.crawler.fetcher import Fetcher
from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url

log = get_logger("crawler.sitemaps")

MAX_SITEMAPS = 20
MAX_SITEMAP_URLS = 5000
_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _safe_parse(data: bytes) -> ET.Element | None:
    parser = ET.XMLParser()  # noqa: S314 - DOCTYPE/ENTITY refused below
    # Defuse entity expansion: refuse documents that declare a DOCTYPE at all.
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        return None
    try:
        return ET.fromstring(data, parser=parser)  # noqa: S314 - DOCTYPE/ENTITY refused above
    except ET.ParseError:
        return None


async def discover_sitemap_urls(
    fetcher: Fetcher, root: CrawlURL, candidates: list[str], *, limit: int = MAX_SITEMAP_URLS
) -> list[str]:
    """Return page URLs listed in the site's sitemaps (bounded), same order as found."""
    queue = [*candidates] or []
    queue.append(f"{root.origin}/sitemap.xml")
    seen: set[str] = set()
    found: list[str] = []
    fetched = 0
    while queue and fetched < MAX_SITEMAPS and len(found) < limit:
        raw = queue.pop(0)
        try:
            sm = normalize_crawl_url(raw)
        except CrawlURLError:
            continue
        if sm.normalized in seen or sm.host != root.host:
            continue
        seen.add(sm.normalized)
        fetched += 1
        result = await fetcher.fetch(sm, allow_non_html=True)
        if not result.ok or result.body is None or result.status_code != 200:
            continue
        tree = _safe_parse(result.body)
        if tree is None:
            continue
        if tree.tag == f"{_NS}sitemapindex":
            for loc in tree.iter(f"{_NS}loc"):
                if loc.text:
                    queue.append(loc.text.strip())
        elif tree.tag == f"{_NS}urlset":
            for loc in tree.iter(f"{_NS}loc"):
                if loc.text:
                    found.append(loc.text.strip())
                    if len(found) >= limit:
                        break
    log.info("sitemaps_discovered", origin=root.origin, sitemaps=fetched, urls=len(found))
    return found
