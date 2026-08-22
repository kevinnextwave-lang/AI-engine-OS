"""Stage 1 — deterministic extraction from an AI answer (markdown/plain text).

Everything here is regex/structure based and reproducible. Judgements that
need reading comprehension are left "unknown" for Stage 2.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.intelligence import PARSER_VERSION
from app.intelligence.context import KnownBrand, ParseContext
from app.intelligence.schema import (
    Citation,
    CitationType,
    Claim,
    Mention,
    ParsedResponse,
    PositionSignals,
    Recommendation,
    RecommendationStrength,
    Sentiment,
)

# --- structure ------------------------------------------------------------------------

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_ORDERED = re.compile(r"^\s{0,3}(?:\*\*)?(\d{1,3})[.)]\s*(?:\*\*)?\s*(.+)$")
_BULLET = re.compile(r"^\s{0,3}[-*•]\s+(.+)$")
_SOURCE_HEADER = re.compile(
    r"^\s*(?:\*\*)?(sources?|references?|citations?|further reading)(?:\*\*)?\s*:?\s*$", re.I
)
_FOOTNOTE = re.compile(r"^\s*\[?(\d{1,3})\]?[.:)]?\s+(.*)$")

_URL = re.compile(r"(?<![\w(\[])(https?://[^\s<>()\]\"']+[^\s<>()\]\"'.,;:!?])", re.I)
_MD_LINK = re.compile(r"\[([^\]]{1,300})\]\((https?://[^\s)]+)\)")
_DOMAIN = re.compile(
    r"(?<![\w@/.])((?:[a-z0-9-]+\.)+(?:com|org|net|io|co|ai|app|dev|uk|de|fr|eu|ca|au|us|info|biz)"
    r"(?:\.[a-z]{2})?)(?![\w/])",
    re.I,
)

# --- lexical cues -----------------------------------------------------------------------

_STRONG = re.compile(
    r"\b(the best|best choice|top (choice|pick|option|rated)|#\s?1|number one|highly recommend|"
    r"strongly recommend|go-to|leading|industry standard|most popular|clear winner|standout|"
    r"my top recommendation|first choice)\b",
    re.I,
)
_MODERATE = re.compile(
    r"\b(a good (option|choice|fit|pick)|solid (option|choice)|recommended|"
    r"great (option|choice|for)|well[- ]suited|strong (option|choice|contender)|"
    r"popular (option|choice)|reliable|excellent|"
    r"worth (a look|trying)|ideal for|a great fit|good for)\b",
    re.I,
)
_WEAK = re.compile(
    r"\b(one option|another option|an option|also (consider|available|offers)|alternatively|"
    r"worth considering|you (could|might) also|can also|other options include|is available|"
    r"may (also )?work|might be|could be)\b",
    re.I,
)
_NEGATIVE = re.compile(
    r"\b(not recommended|avoid|worse|lacks?|lacking|limited|drawbacks?|downsides?|complaints?|"
    r"poor|expensive|pricey|clunky|outdated|buggy|unreliable|difficult|steep learning curve|"
    r"falls? short|weak(er|est)?|struggles?|no longer|discontinued|frustrating|less (suitable|"
    r"ideal|capable)|not (ideal|suitable|the best|great|good)|can('t| not|not) )\b",
    re.I,
)
_POSITIVE = re.compile(
    r"\b(best|great|excellent|strong|reliable|popular|easy|intuitive|affordable|robust|"
    r"powerful|recommended|ideal|well[- ]suited|leading|top|solid|good|seamless|trusted|"
    r"comprehensive|user[- ]friendly|effective|industry standard|better choice)\b",
    re.I,
)
_CLAIM = re.compile(
    r"\b(is|are|offers?|has|have|supports?|provides?|costs?|integrates? with|lacks?|includes?|"
    r"starts? at|charges?|allows?|lets you|comes with|requires?)\b\s+([^.;:\n!?]{3,200})",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[*\-])|\n+")


@dataclass
class Block:
    kind: str  # heading | item | paragraph | source
    text: str  # markdown stripped
    raw: str = ""  # original line(s), used for link/URL extraction
    index: int | None = None  # 1-based list position for items / source entries
    ordered: bool = False


@dataclass
class Structure:
    blocks: list[Block] = field(default_factory=list)
    list_items: int = 0
    ordered_list: bool = False
    has_source_list: bool = False


def _strip_md(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    return re.sub(r"[*_`]+", "", text).strip()


def parse_structure(text: str) -> Structure:
    s = Structure()
    in_sources = False
    source_index = 0
    item_counter = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if _SOURCE_HEADER.match(line):
            in_sources = True
            s.has_source_list = True
            continue
        heading = _HEADING.match(line)
        if heading:
            in_sources = bool(_SOURCE_HEADER.match(heading.group(1)))
            s.has_source_list = s.has_source_list or in_sources
            s.blocks.append(Block("heading", _strip_md(heading.group(1)), raw=heading.group(1)))
            continue
        if in_sources:
            m = _FOOTNOTE.match(line)
            entry = m.group(2) if m else line.strip()
            bullet = _BULLET.match(entry)
            if bullet:
                entry = bullet.group(1)
            source_index += 1
            s.blocks.append(Block("source", entry, raw=entry, index=source_index))
            continue
        ordered = _ORDERED.match(line)
        if ordered:
            item_counter += 1
            s.ordered_list = True
            s.list_items += 1
            s.blocks.append(
                Block(
                    "item",
                    _strip_md(ordered.group(2)),
                    raw=ordered.group(2),
                    index=item_counter,
                    ordered=True,
                )
            )
            continue
        bullet = _BULLET.match(line)
        if bullet:
            item_counter += 1
            s.list_items += 1
            s.blocks.append(
                Block("item", _strip_md(bullet.group(1)), raw=bullet.group(1), index=item_counter)
            )
            continue
        # Continuation of a list item (indented) keeps the item's position.
        if s.blocks and s.blocks[-1].kind == "item" and raw.startswith((" ", "\t")):
            s.blocks[-1].text += " " + _strip_md(line)
            s.blocks[-1].raw += " " + line.strip()
            continue
        s.blocks.append(Block("paragraph", _strip_md(line), raw=line.strip()))
    return s


# --- citations --------------------------------------------------------------------------


def _domain_of(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.") or None


def extract_citations(text: str, structure: Structure) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str | None, str | None]] = set()

    def add(c: Citation) -> None:
        key = (c.url, c.domain if c.url is None else None)
        if key in seen:
            return
        seen.add(key)
        citations.append(c)

    # Source-list entries first: they carry explicit positions.
    for block in structure.blocks:
        if block.kind != "source":
            continue
        links = _MD_LINK.findall(block.text)
        urls = [u for _, u in links] or _URL.findall(block.text)
        if urls:
            for url in urls:
                anchor = next((a for a, u in links if u == url), None)
                add(
                    Citation(
                        url=url,
                        domain=_domain_of(url),
                        anchor_text=anchor or _strip_md(_MD_LINK.sub("", block.text))[:500] or None,
                        citation_position=block.index,
                        citation_type=CitationType.SOURCE_LIST,
                    )
                )
        else:
            dom = _DOMAIN.search(block.text)
            add(
                Citation(
                    url=None,
                    domain=dom.group(1).lower() if dom else None,
                    anchor_text=block.text[:500],
                    citation_position=block.index,
                    citation_type=CitationType.SOURCE_LIST,
                )
            )

    body = "\n".join(b.raw for b in structure.blocks if b.kind != "source") or text
    for anchor, url in _MD_LINK.findall(body):
        add(
            Citation(
                url=url,
                domain=_domain_of(url),
                anchor_text=anchor.strip(),
                citation_type=CitationType.MARKDOWN_LINK,
            )
        )
    stripped = _MD_LINK.sub(" ", body)
    for url in _URL.findall(stripped):
        add(Citation(url=url, domain=_domain_of(url), citation_type=CitationType.EXPLICIT_URL))
    no_urls = _URL.sub(" ", stripped)
    for dom in _DOMAIN.findall(no_urls):
        add(Citation(url=None, domain=dom.lower(), citation_type=CitationType.DOMAIN_REFERENCE))
    return citations


# --- mentions ---------------------------------------------------------------------------


def _name_pattern(brand: KnownBrand) -> re.Pattern[str]:
    names = sorted({n for n in brand.all_names() if n}, key=len, reverse=True)
    alts = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<![\w-])({alts})(?![\w-])", re.I)


def _judge(text: str) -> tuple[Sentiment, RecommendationStrength]:
    neg = bool(_NEGATIVE.search(text))
    pos = bool(_POSITIVE.search(text))
    if neg and pos:
        sentiment = Sentiment.MIXED
    elif neg:
        sentiment = Sentiment.NEGATIVE
    elif pos:
        sentiment = Sentiment.POSITIVE
    else:
        sentiment = Sentiment.NEUTRAL
    if _STRONG.search(text) and not neg:
        strength = RecommendationStrength.STRONG
    elif _MODERATE.search(text) and not neg:
        strength = RecommendationStrength.MODERATE
    elif _WEAK.search(text) and not neg:
        strength = RecommendationStrength.WEAK
    elif neg and not pos:
        strength = RecommendationStrength.NONE
    else:
        strength = RecommendationStrength.UNKNOWN
    return sentiment, strength


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def extract_mentions(structure: Structure, ctx: ParseContext) -> list[Mention]:
    mentions: list[Mention] = []
    patterns = [(b, _name_pattern(b)) for b in ctx.all_brands]
    for block in structure.blocks:
        if block.kind == "source":
            continue
        for brand, pattern in patterns:
            for sentence in _sentences(block.text):
                m = pattern.search(sentence)
                if not m:
                    continue
                # Headline position in a list item: the brand is the item's subject when it
                # appears in the first ~60 characters; otherwise it is an in-passing mention.
                is_subject = block.kind == "item" and m.start() <= 60
                sentiment, strength = _judge(sentence)
                mentions.append(
                    Mention(
                        brand_name=brand.name,
                        mention_text=m.group(1),
                        context=sentence[:2000],
                        position=block.index if is_subject else None,
                        sentiment=sentiment,
                        recommendation_strength=strength,
                        is_competitor=brand.is_competitor,
                        source="deterministic",
                    )
                )
    return mentions


def extract_claims(structure: Structure, ctx: ParseContext) -> list[Claim]:
    claims: list[Claim] = []
    patterns = [(b, _name_pattern(b)) for b in ctx.all_brands]
    for block in structure.blocks:
        if block.kind == "source":
            continue
        for sentence in _sentences(block.text):
            for brand, pattern in patterns:
                bm = pattern.search(sentence)
                if not bm:
                    continue
                tail = sentence[bm.end() :]
                cm = _CLAIM.search(tail)
                if not cm or cm.start() > 60:
                    continue
                claims.append(
                    Claim(
                        subject=brand.name,
                        predicate=cm.group(1).lower(),
                        object=cm.group(2).strip(" ,"),
                        confidence=0.6,
                        context=sentence[:2000],
                    )
                )
    return claims


# --- entry point --------------------------------------------------------------------------


def aggregate_sentiment(mentions: list[Mention]) -> Sentiment:
    """Sentiment towards the brand across its mentions; unknown when absent."""
    if not mentions:
        return Sentiment.UNKNOWN
    kinds = {m.sentiment for m in mentions} - {Sentiment.UNKNOWN}
    if not kinds:
        return Sentiment.UNKNOWN
    if Sentiment.MIXED in kinds or ({Sentiment.POSITIVE, Sentiment.NEGATIVE} <= kinds):
        return Sentiment.MIXED
    if Sentiment.NEGATIVE in kinds:
        return Sentiment.NEGATIVE
    if Sentiment.POSITIVE in kinds:
        return Sentiment.POSITIVE
    return Sentiment.NEUTRAL


def strongest(mentions: list[Mention]) -> RecommendationStrength:
    order = [
        RecommendationStrength.STRONG,
        RecommendationStrength.MODERATE,
        RecommendationStrength.WEAK,
        RecommendationStrength.NONE,
        RecommendationStrength.UNKNOWN,
    ]
    present = {m.recommendation_strength for m in mentions}
    return next((s for s in order if s in present), RecommendationStrength.UNKNOWN)


def deterministic_parse(text: str, ctx: ParseContext) -> ParsedResponse:
    structure = parse_structure(text)
    all_mentions = extract_mentions(structure, ctx)
    brand_mentions = [m for m in all_mentions if not m.is_competitor]
    competitor_mentions = [m for m in all_mentions if m.is_competitor]

    # Recommendations in answer order: one per known brand, at its first list position.
    recs: dict[str, Recommendation] = {}
    for m in sorted(all_mentions, key=lambda m: (m.position is None, m.position or 0)):
        if m.brand_name in recs:
            continue
        recs[m.brand_name] = Recommendation(
            name=m.brand_name,
            position=m.position,
            strength=strongest([x for x in all_mentions if x.brand_name == m.brand_name]),
        )
    brand_positions = [m.position for m in brand_mentions if m.position is not None]
    first_brand = None
    for block in structure.blocks:
        hits = [
            (m.start(), b.name)
            for b, p in ((b, _name_pattern(b)) for b in ctx.all_brands)
            for m in [p.search(block.text)]
            if m
        ]
        if hits:
            first_brand = min(hits)[1]
            break
    signals = PositionSignals(
        answer_is_list=structure.list_items >= 2,
        list_items=structure.list_items,
        ordered_list=structure.ordered_list,
        brand_position=min(brand_positions) if brand_positions else None,
        first_mentioned_brand=first_brand,
        brand_mentioned=bool(brand_mentions),
        competitors_mentioned=sorted({m.brand_name for m in competitor_mentions}),
    )
    return ParsedResponse(
        parser_version=PARSER_VERSION,
        mentions=brand_mentions,
        competitor_mentions=competitor_mentions,
        claims=extract_claims(structure, ctx),
        citations=extract_citations(text, structure),
        recommendations=list(recs.values()),
        sentiment=aggregate_sentiment(brand_mentions),
        position_signals=signals,
    )
