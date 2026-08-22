"""HTML page processing: metadata, links, text, hashes."""

import hashlib
import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url

MAX_EXTRACTED_TEXT_CHARS = 200_000
_WS = re.compile(r"\s+")
_NAV_ANCESTORS = {"nav", "header", "footer"}
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "ftp:")


@dataclass(frozen=True)
class ExtractedLink:
    url: CrawlURL
    nofollow: bool
    in_navigation: bool


@dataclass
class ProcessedPage:
    title: str | None
    meta_description: str | None
    language: str | None
    canonical_url: str | None
    robots_noindex: bool
    robots_nofollow: bool
    extracted_text: str
    word_count: int
    html_hash: str
    content_hash: str
    links: list[ExtractedLink] = field(default_factory=list)


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


def _is_in_navigation(node) -> bool:  # type: ignore[no-untyped-def]
    parent = node.parent
    while parent is not None:
        if parent.tag in _NAV_ANCESTORS:
            return True
        parent = parent.parent
    return False


def process_html(html: bytes, page_url: CrawlURL) -> ProcessedPage:
    tree = HTMLParser(html)
    html_hash = _sha256(html)

    base_href = page_url.normalized
    base_node = tree.css_first("base[href]")
    base_attr = base_node.attributes.get("href") if base_node is not None else None
    if base_attr:
        try:
            base_href = normalize_crawl_url(base_attr, base=page_url.normalized).normalized
        except CrawlURLError:
            pass

    title_node = tree.css_first("title")
    title = _WS.sub(" ", title_node.text()).strip() if title_node else None
    meta_description = None
    robots_noindex = robots_nofollow = False
    for meta in tree.css("meta"):
        name = (meta.attributes.get("name") or meta.attributes.get("property") or "").lower()
        content = (meta.attributes.get("content") or "").strip()
        if name == "description" and not meta_description:
            meta_description = content or None
        elif name == "robots":
            directives = {d.strip().lower() for d in content.split(",")}
            robots_noindex = robots_noindex or "noindex" in directives or "none" in directives
            robots_nofollow = robots_nofollow or "nofollow" in directives or "none" in directives

    html_node = tree.css_first("html")
    language = (html_node.attributes.get("lang") or "").strip() or None if html_node else None

    canonical_url = None
    canonical_node = tree.css_first('link[rel~="canonical"]')
    canonical_attr = canonical_node.attributes.get("href") if canonical_node is not None else None
    if canonical_attr:
        try:
            canonical_url = normalize_crawl_url(canonical_attr, base=base_href).normalized
        except CrawlURLError:
            canonical_url = None

    links: list[ExtractedLink] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(_SKIP_SCHEMES):
            continue
        try:
            target = normalize_crawl_url(href, base=base_href)
        except CrawlURLError:
            continue
        if target.normalized in seen:
            continue
        seen.add(target.normalized)
        rel = {r.strip().lower() for r in (a.attributes.get("rel") or "").split()}
        links.append(
            ExtractedLink(
                url=target,
                nofollow="nofollow" in rel,
                in_navigation=_is_in_navigation(a),
            )
        )

    # Text: drop non-content elements, then collapse whitespace.
    for node in tree.css("script, style, noscript, template, svg, iframe"):
        node.decompose()
    body = tree.body or tree.root
    raw_text = body.text(separator=" ", strip=True) if body is not None else ""
    text = _WS.sub(" ", raw_text).strip()[:MAX_EXTRACTED_TEXT_CHARS]
    word_count = len(text.split()) if text else 0
    content_hash = _sha256(text.lower())

    return ProcessedPage(
        title=title[:1000] if title else None,
        meta_description=meta_description,
        language=language[:35] if language else None,
        canonical_url=canonical_url,
        robots_noindex=robots_noindex,
        robots_nofollow=robots_nofollow,
        extracted_text=text,
        word_count=word_count,
        html_hash=html_hash,
        content_hash=content_hash,
        links=links,
    )
