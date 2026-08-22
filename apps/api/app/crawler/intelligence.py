"""Page intelligence: structured facts about one crawled HTML page.

Pure function over (html, url, site policy) → PageIntelligence. No I/O.
Observations (missing H1, skipped levels, ...) are recorded as facts; the
scoring layer decides what they mean.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser, Node

from app.crawler.language import LanguageResult, resolve_language
from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url, same_site

MAX_CLEAN_TEXT_CHARS = 200_000
MAX_HEADINGS = 500
MAX_LINKS = 2_000
MAX_IMAGES = 1_000
MAX_STRUCTURED_BLOCKS = 50
MAX_STRUCTURED_PAYLOAD_BYTES = 64_000
LONG_HEADING_CHARS = 70
WORDS_PER_MINUTE = 238  # adult silent reading average

_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"[.!?…]+(?:\s|$)")
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:")
_BOILERPLATE_TAGS = "script, style, noscript, template, svg, iframe, canvas, object, embed"
_STRUCTURAL_BOILERPLATE = "nav, header, footer, aside, form"
_COOKIE_HINT = re.compile(r"cookie|consent|gdpr|privacy-banner|cc-banner|onetrust|cmp-", re.I)
_PUBLISHED_KEYS = (
    "article:published_time",
    "datepublished",
    "date",
    "dc.date",
    "dc.date.issued",
    "pubdate",
    "publish-date",
    "og:published_time",
)
_MODIFIED_KEYS = (
    "article:modified_time",
    "datemodified",
    "last-modified",
    "dc.date.modified",
    "og:updated_time",
    "revised",
)


@dataclass
class HeadingFact:
    level: int
    position: int
    text: str
    parent_position: int | None


@dataclass
class LinkFact:
    href: str
    normalized_url: str | None
    anchor_text: str
    link_type: str  # internal | external
    is_nofollow: bool
    is_sponsored: bool
    is_ugc: bool
    position: int
    in_navigation: bool


@dataclass
class ImageFact:
    src: str
    alt: str | None
    title: str | None
    width: int | None
    height: int | None
    loading: str | None
    position: int


@dataclass
class MetadataFacts:
    open_graph: dict[str, str]
    twitter: dict[str, str]
    robots: str | None
    viewport: str | None
    author: str | None
    published_at: datetime | None
    modified_at: datetime | None
    charset: str | None
    html_lang: str | None
    metadata_lang: str | None
    extra: dict[str, str]  # other name/property metas (dynamic, bounded)


@dataclass
class StructuredDataFact:
    format: str  # json_ld | microdata | rdfa
    schema_types: list[str]
    payload: dict[str, Any] | list[Any] | None
    is_valid: bool
    error: str | None
    position: int


@dataclass
class ValidityFacts:
    has_doctype: bool
    title_count: int
    canonical_count: int
    canonical_url: str | None


@dataclass
class ContentMetrics:
    word_count: int
    character_count: int
    paragraph_count: int
    sentence_count: int
    reading_time_seconds: int
    text_to_html_ratio: float
    html_bytes: int


@dataclass
class HeadingObservations:
    h1_count: int
    missing_h1: bool
    multiple_h1: bool
    skipped_levels: list[dict[str, int]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    long_headings: list[int] = field(default_factory=list)  # positions


@dataclass
class PageIntelligence:
    pathname: str
    headings: list[HeadingFact]
    links: list[LinkFact]
    images: list[ImageFact]
    metadata: MetadataFacts
    content: ContentMetrics
    heading_observations: HeadingObservations
    language: LanguageResult
    clean_text: str
    structured_data: list[StructuredDataFact] = field(default_factory=list)
    validity: ValidityFacts = field(default_factory=lambda: ValidityFacts(False, 0, 0, None))


# --- helpers ------------------------------------------------------------------


def _iter_tags(root: Node | None, tags: frozenset[str]) -> list[Node]:
    """Nodes with one of `tags` in document order (css() with a list groups by selector)."""
    if root is None:
        return []
    return [node for node in root.traverse(include_text=False) if node.tag in tags]


_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "li",
        "td",
        "th",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "dd",
        "dt",
        "figcaption",
    }
)


def _text(node: Node) -> str:
    return _WS.sub(" ", node.text(separator=" ", strip=True) if node else "").strip()


def _int_attr(node: Node, name: str) -> int | None:
    raw = (node.attributes.get(name) or "").strip().rstrip("px")
    return int(raw) if raw.isdigit() else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        try:
            return datetime.fromisoformat(match.group(1))
        except ValueError:
            return None
    return None


def _is_boilerplate(node: Node) -> bool:
    """Structural chrome or cookie/consent widgets, by tag or id/class hints."""
    ident = f"{node.attributes.get('id') or ''} {node.attributes.get('class') or ''}"
    role = (node.attributes.get("role") or "").lower()
    if _COOKIE_HINT.search(ident):
        return True
    return role in {"navigation", "banner", "contentinfo", "complementary", "dialog", "alertdialog"}


# --- extractors ---------------------------------------------------------------


def _extract_headings(tree: HTMLParser) -> tuple[list[HeadingFact], HeadingObservations]:
    facts: list[HeadingFact] = []
    stack: list[tuple[int, int]] = []  # (level, position)
    for node in _iter_tags(tree.root, _HEADING_TAGS):
        if len(facts) >= MAX_HEADINGS:
            break
        level = int(node.tag[1])
        text = _text(node)[:1000]
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        position = len(facts)
        facts.append(HeadingFact(level=level, position=position, text=text, parent_position=parent))
        stack.append((level, position))

    h1s = [h for h in facts if h.level == 1]
    obs = HeadingObservations(h1_count=len(h1s), missing_h1=not h1s, multiple_h1=len(h1s) > 1)
    previous_level = 0
    for h in facts:
        if previous_level and h.level > previous_level + 1:
            obs.skipped_levels.append(
                {"position": h.position, "from": previous_level, "to": h.level}
            )
        previous_level = h.level
        if len(h.text) > LONG_HEADING_CHARS:
            obs.long_headings.append(h.position)
    seen: dict[str, int] = {}
    for h in facts:
        key = h.text.lower()
        if key:
            seen[key] = seen.get(key, 0) + 1
    obs.duplicates = sorted(t for t, n in seen.items() if n > 1)
    return facts, obs


def _extract_links(
    tree: HTMLParser,
    base: str,
    page: CrawlURL,
    allowed_hosts: frozenset[str],
    allow_subdomains: bool,
) -> list[LinkFact]:
    facts: list[LinkFact] = []
    for node in tree.css("a[href]"):
        if len(facts) >= MAX_LINKS:
            break
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(_SKIP_SCHEMES):
            continue
        normalized: str | None
        link_type = "external"
        try:
            target = normalize_crawl_url(href, base=base)
            normalized = target.normalized
            hosts = allowed_hosts or frozenset({page.host})
            if any(same_site(target.host, h, allow_subdomains=allow_subdomains) for h in hosts):
                link_type = "internal"
        except CrawlURLError:
            normalized = None
        rel = {r.strip().lower() for r in (node.attributes.get("rel") or "").split()}
        anchor = (
            _text(node)[:500]
            or (node.attributes.get("title") or node.attributes.get("aria-label") or "").strip()[
                :500
            ]
        )
        in_nav = False
        parent = node.parent
        while parent is not None:
            if parent.tag in {"nav", "header", "footer"}:
                in_nav = True
                break
            parent = parent.parent
        facts.append(
            LinkFact(
                href=href[:2048],
                normalized_url=normalized,
                anchor_text=anchor,
                link_type=link_type,
                is_nofollow="nofollow" in rel,
                is_sponsored="sponsored" in rel,
                is_ugc="ugc" in rel,
                position=len(facts),
                in_navigation=in_nav,
            )
        )
    return facts


def _extract_images(tree: HTMLParser, base: str) -> list[ImageFact]:
    facts: list[ImageFact] = []
    for node in tree.css("img"):
        if len(facts) >= MAX_IMAGES:
            break
        raw_src = (
            node.attributes.get("src")
            or node.attributes.get("data-src")
            or node.attributes.get("data-lazy-src")
            or ""
        ).strip()
        srcset = node.attributes.get("srcset") or ""
        if not raw_src and srcset:
            raw_src = srcset.split(",")[0].strip().split(" ")[0]
        if not raw_src or raw_src.startswith("data:"):
            continue
        try:
            src = normalize_crawl_url(raw_src, base=base).normalized
        except CrawlURLError:
            src = raw_src[:2048]
        # selectolax returns None for attributes with empty values, so check presence.
        alt = (node.attributes.get("alt") or "") if "alt" in node.attributes else None
        facts.append(
            ImageFact(
                src=src[:2048],
                alt=alt.strip()[:1000] if alt is not None else None,
                title=(node.attributes.get("title") or "").strip()[:500] or None,
                width=_int_attr(node, "width"),
                height=_int_attr(node, "height"),
                loading=(node.attributes.get("loading") or "").strip().lower()
                or (
                    "lazy"
                    if node.attributes.get("data-src") or node.attributes.get("data-lazy-src")
                    else None
                ),
                position=len(facts),
            )
        )
    return facts


def _extract_metadata(tree: HTMLParser) -> MetadataFacts:
    og: dict[str, str] = {}
    tw: dict[str, str] = {}
    extra: dict[str, str] = {}
    robots = viewport = author = charset = None
    published = modified = None
    metadata_lang = None
    for meta in tree.css("meta"):
        charset_attr = meta.attributes.get("charset")
        if charset_attr:
            charset = charset_attr.strip().lower()
            continue
        key = (
            (
                meta.attributes.get("property")
                or meta.attributes.get("name")
                or meta.attributes.get("http-equiv")
                or ""
            )
            .strip()
            .lower()
        )
        content = (meta.attributes.get("content") or "").strip()
        if not key or not content:
            continue
        if key.startswith("og:") or key.startswith("article:"):
            og.setdefault(key, content[:2000])
        elif key.startswith("twitter:"):
            tw.setdefault(key, content[:2000])
        elif key == "robots":
            robots = content[:500]
        elif key == "viewport":
            viewport = content[:200]
        elif key in ("author", "dc.creator", "article:author"):
            author = author or content[:200]
        elif key in ("content-language", "dc.language", "language"):
            metadata_lang = metadata_lang or content
        elif key == "content-type" and "charset=" in content.lower():
            charset = charset or content.lower().split("charset=")[-1].strip()
        elif len(extra) < 50:
            extra.setdefault(key[:100], content[:500])
        if key in _PUBLISHED_KEYS:
            published = published or _parse_date(content)
        elif key in _MODIFIED_KEYS:
            modified = modified or _parse_date(content)
    if not metadata_lang and og.get("og:locale"):
        metadata_lang = og["og:locale"]
    if not published:
        time_node = tree.css_first(
            "time[datetime][pubdate], time[datetime][itemprop='datePublished']"
        )
        if time_node is not None:
            published = _parse_date(time_node.attributes.get("datetime"))
    html_node = tree.css_first("html")
    html_lang = (html_node.attributes.get("lang") or "").strip() or None if html_node else None
    return MetadataFacts(
        open_graph=og,
        twitter=tw,
        robots=robots,
        viewport=viewport,
        author=author,
        published_at=published,
        modified_at=modified,
        charset=charset,
        html_lang=html_lang,
        metadata_lang=metadata_lang,
        extra=extra,
    )


def _schema_types_from_jsonld(data: Any) -> list[str]:
    types: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(x for x in t if isinstance(x, str))
            for key in ("@graph", "mainEntity", "itemListElement", "hasPart"):
                if key in node:
                    walk(node[key], depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(data)
    return list(dict.fromkeys(types))


def _short_type(value: str) -> str:
    value = value.strip()
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1] or value


def _extract_structured_data(tree: HTMLParser) -> list[StructuredDataFact]:
    facts: list[StructuredDataFact] = []
    for node in tree.css('script[type="application/ld+json"]'):
        if len(facts) >= MAX_STRUCTURED_BLOCKS:
            break
        raw = (node.text() or "").strip()
        position = len(facts)
        if not raw:
            facts.append(StructuredDataFact("json_ld", [], None, False, "empty block", position))
            continue
        if len(raw.encode("utf-8")) > MAX_STRUCTURED_PAYLOAD_BYTES:
            facts.append(
                StructuredDataFact("json_ld", [], None, False, "block too large", position)
            )
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            facts.append(
                StructuredDataFact("json_ld", [], None, False, f"invalid JSON: {exc.msg}", position)
            )
            continue
        facts.append(
            StructuredDataFact(
                "json_ld", _schema_types_from_jsonld(data), data, True, None, position
            )
        )
    microdata_types: list[str] = []
    for node in tree.css("[itemscope][itemtype]"):
        for t in (node.attributes.get("itemtype") or "").split():
            microdata_types.append(_short_type(t))
    if microdata_types and len(facts) < MAX_STRUCTURED_BLOCKS:
        facts.append(
            StructuredDataFact(
                "microdata", list(dict.fromkeys(microdata_types)), None, True, None, len(facts)
            )
        )
    rdfa_types: list[str] = []
    for node in tree.css("[typeof]"):
        for t in (node.attributes.get("typeof") or "").split():
            rdfa_types.append(_short_type(t))
    if rdfa_types and len(facts) < MAX_STRUCTURED_BLOCKS:
        facts.append(
            StructuredDataFact(
                "rdfa", list(dict.fromkeys(rdfa_types)), None, True, None, len(facts)
            )
        )
    return facts


def _extract_validity(tree: HTMLParser, html: bytes, base: str) -> ValidityFacts:
    head = html[:2048].lstrip().lower()
    has_doctype = head.startswith(b"<!doctype")
    title_count = len(tree.css("head title") or tree.css("title"))
    canonicals = tree.css('link[rel~="canonical"]')
    canonical_url: str | None = None
    for node in canonicals:
        href = node.attributes.get("href")
        if href:
            try:
                canonical_url = normalize_crawl_url(href, base=base).normalized
                break
            except CrawlURLError:
                continue
    return ValidityFacts(
        has_doctype=has_doctype,
        title_count=title_count,
        canonical_count=len(canonicals),
        canonical_url=canonical_url,
    )


def _clean_text(tree: HTMLParser) -> tuple[str, int]:
    """Main-content text with boilerplate removed. Returns (text, paragraph_count)."""
    for node in tree.css(_BOILERPLATE_TAGS):
        node.decompose()
    for node in tree.css(_STRUCTURAL_BOILERPLATE):
        node.decompose()
    for node in tree.css("[id], [class], [role]"):
        if _is_boilerplate(node):
            node.decompose()
    root = tree.css_first("main") or tree.css_first("article") or tree.body or tree.root
    if root is None:
        return "", 0
    paragraph_count = len([p for p in root.css("p") if _text(p)])
    # Keep block boundaries as newlines so lists/tables remain readable.
    for br in root.css("br"):
        br.replace_with("\n")
    blocks = _iter_tags(root, _BLOCK_TAGS)
    if blocks:
        lines = [_text(b) for b in blocks]
        text = "\n".join(line for line in lines if line)
    else:
        text = _text(root)
    return text[:MAX_CLEAN_TEXT_CHARS], paragraph_count


def _content_metrics(text: str, paragraph_count: int, html_bytes: int) -> ContentMetrics:
    words = text.split()
    word_count = len(words)
    sentence_count = len([m for m in _SENTENCE_END.finditer(text)]) if text else 0
    if text and sentence_count == 0:
        sentence_count = 1
    ratio = round(len(text.encode("utf-8")) / html_bytes, 4) if html_bytes else 0.0
    return ContentMetrics(
        word_count=word_count,
        character_count=len(text),
        paragraph_count=paragraph_count,
        sentence_count=sentence_count,
        reading_time_seconds=round(word_count / WORDS_PER_MINUTE * 60),
        text_to_html_ratio=min(ratio, 1.0),
        html_bytes=html_bytes,
    )


# --- entry point ----------------------------------------------------------------


def analyze_page(
    html: bytes,
    page_url: CrawlURL,
    *,
    allowed_hosts: frozenset[str] = frozenset(),
    allow_subdomains: bool = False,
) -> PageIntelligence:
    tree = HTMLParser(html)
    base = page_url.normalized
    base_node = tree.css_first("base[href]")
    base_attr = base_node.attributes.get("href") if base_node is not None else None
    if base_attr:
        try:
            base = normalize_crawl_url(base_attr, base=page_url.normalized).normalized
        except CrawlURLError:
            pass

    headings, observations = _extract_headings(tree)
    links = _extract_links(tree, base, page_url, allowed_hosts, allow_subdomains)
    images = _extract_images(tree, base)
    metadata = _extract_metadata(tree)
    structured = _extract_structured_data(tree)
    validity = _extract_validity(tree, html, base)
    # Cleaning mutates the tree, so it runs last.
    clean_text, paragraph_count = _clean_text(tree)
    content = _content_metrics(clean_text, paragraph_count, len(html))
    language = resolve_language(
        html_lang=metadata.html_lang, metadata_lang=metadata.metadata_lang, text=clean_text
    )
    return PageIntelligence(
        pathname=urlsplit(page_url.normalized).path or "/",
        headings=headings,
        links=links,
        images=images,
        metadata=metadata,
        content=content,
        heading_observations=observations,
        language=language,
        clean_text=clean_text,
        structured_data=structured,
        validity=validity,
    )


def observations_as_dict(obs: HeadingObservations) -> dict[str, Any]:
    return {
        "h1_count": obs.h1_count,
        "missing_h1": obs.missing_h1,
        "multiple_h1": obs.multiple_h1,
        "skipped_levels": obs.skipped_levels,
        "duplicate_headings": obs.duplicates,
        "long_heading_positions": obs.long_headings,
    }
