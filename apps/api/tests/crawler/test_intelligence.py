"""Page intelligence analyzer: headings, links, images, metadata, language,
content extraction, classification, duplicates, malformed HTML."""

from datetime import datetime

from app.crawler.intelligence import analyze_page, observations_as_dict
from app.crawler.language import detect_language, normalize_lang_tag, resolve_language
from app.crawler.urls import normalize_crawl_url

PAGE = normalize_crawl_url("https://example.com/blog/post")
HOSTS = frozenset({"example.com"})


def analyze(html: str | bytes, **kw: object):  # type: ignore[no-untyped-def]
    data = html.encode() if isinstance(html, str) else html
    return analyze_page(data, PAGE, allowed_hosts=HOSTS, **kw)  # type: ignore[arg-type]


LONG = "This is an exceptionally long heading that certainly exceeds the seventy character limit"
FULL_PAGE = f"""<!doctype html>
<html lang="en-gb"><head>
<meta charset="utf-8"><title>Post Title</title>
<meta name="description" content="A description">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="index, follow, max-snippet:-1">
<meta name="author" content="Jane Doe">
<meta property="og:title" content="OG Title"><meta property="og:image" content="/og.png">
<meta property="og:locale" content="en_GB">
<meta property="article:published_time" content="2024-03-01T10:00:00Z">
<meta property="article:modified_time" content="2024-04-02T12:30:00+02:00">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:site" content="@acme">
<meta name="generator" content="Static Site 9">
<link rel="canonical" href="https://example.com/blog/post">
</head><body>
<header><a href="/">Home</a><nav><a href="/about">About</a><a href="/blog">Blog</a></nav></header>
<div id="cookie-consent">We use cookies. <a href="/privacy">Privacy</a></div>
<main>
  <h1>Main Heading</h1>
  <p>First paragraph of the article. It has two sentences!</p>
  <h2>Section One</h2>
  <p>Second paragraph with a <a href="/internal-page?utm_source=x">link</a> and an
     <a href="https://partner.example/x" rel="sponsored nofollow">ad</a>.</p>
  <h4>Skipped to four</h4>
  <ul><li>Item one</li><li>Item two</li></ul>
  <table><tr><th>Col</th><td>Cell</td></tr></table>
  <h2>Section One</h2>
  <h3>{LONG}</h3>
  <a href="/internal-page">dup link</a>
  <a href="https://Example.com/internal-page#frag">dup link again</a>
  <a href="https://forum.example.com/t/1" rel="ugc">forum</a>
  <a href="mailto:x@y.z">mail</a><a href="#top">top</a><a href="javascript:void(0)">js</a>
  <img src="/img/hero.jpg" alt="Hero image" width="800" height="600" loading="lazy" title="Hero">
  <img data-src="/img/lazy.png" alt="">
  <img src="data:image/png;base64,xyz" alt="inline">
  <img srcset="/img/a-1x.png 1x, /img/a-2x.png 2x">
  <script>document.write("noise")</script>
  <style>.x{{}}</style>
</main>
<aside>Related: <a href="/rel">rel</a></aside>
<footer>© Example <a href="/terms">Terms</a></footer>
</body></html>"""


# --- headings --------------------------------------------------------------------


def test_heading_extraction_order_hierarchy_and_observations() -> None:
    out = analyze(FULL_PAGE)
    levels = [(h.level, h.text) for h in out.headings]
    assert levels == [
        (1, "Main Heading"),
        (2, "Section One"),
        (4, "Skipped to four"),
        (2, "Section One"),
        (3, LONG),
    ]
    assert [h.parent_position for h in out.headings] == [None, 0, 1, 0, 3]
    obs = observations_as_dict(out.heading_observations)
    assert obs["h1_count"] == 1 and obs["missing_h1"] is False and obs["multiple_h1"] is False
    assert obs["skipped_levels"] == [{"position": 2, "from": 2, "to": 4}]
    assert obs["duplicate_headings"] == ["section one"]
    assert obs["long_heading_positions"] == [4]


def test_missing_and_multiple_h1() -> None:
    assert analyze("<html><body><h2>Only h2</h2></body></html>").heading_observations.missing_h1
    multi = analyze("<html><body><h1>A</h1><h1>B</h1></body></html>").heading_observations
    assert multi.multiple_h1 and multi.h1_count == 2 and not multi.missing_h1


# --- links ---------------------------------------------------------------------------


def test_link_extraction_and_classification() -> None:
    out = analyze(FULL_PAGE)
    by_href = {link.href: link for link in out.links}
    assert "mailto:x@y.z" not in by_href and "#top" not in by_href
    assert "javascript:void(0)" not in by_href

    internal = by_href["/internal-page?utm_source=x"]
    assert internal.link_type == "internal"
    assert internal.normalized_url == "https://example.com/internal-page"
    assert internal.anchor_text == "link" and not internal.is_nofollow

    ad = by_href["https://partner.example/x"]
    assert ad.link_type == "external" and ad.is_sponsored and ad.is_nofollow and not ad.is_ugc

    forum = by_href["https://forum.example.com/t/1"]
    assert forum.is_ugc and forum.link_type == "external"  # subdomains external by default

    nav = by_href["/about"]
    assert nav.in_navigation and nav.link_type == "internal"
    assert by_href["/terms"].in_navigation  # footer counts as navigation chrome

    # Duplicate links are kept as separate facts (position preserved) but share a normalized target.
    dups = [
        link for link in out.links if link.normalized_url == "https://example.com/internal-page"
    ]
    assert len(dups) == 3 and [d.position for d in dups] == sorted(d.position for d in dups)
    assert {d.anchor_text for d in dups} == {"link", "dup link", "dup link again"}


def test_subdomain_links_internal_when_allowed() -> None:
    out = analyze(FULL_PAGE, allow_subdomains=True)
    forum = next(link for link in out.links if "forum.example.com" in link.href)
    assert forum.link_type == "internal"


# --- images -------------------------------------------------------------------------------


def test_image_extraction() -> None:
    out = analyze(FULL_PAGE)
    assert [i.src for i in out.images] == [
        "https://example.com/img/hero.jpg",
        "https://example.com/img/lazy.png",
        "https://example.com/img/a-1x.png",
    ]
    hero = out.images[0]
    assert (hero.alt, hero.title, hero.width, hero.height, hero.loading) == (
        "Hero image",
        "Hero",
        800,
        600,
        "lazy",
    )
    lazy = out.images[1]
    assert lazy.alt == "" and lazy.loading == "lazy" and lazy.width is None
    assert out.images[2].alt is None  # missing alt is distinct from empty alt


# --- metadata --------------------------------------------------------------------------


def test_metadata_extraction() -> None:
    m = analyze(FULL_PAGE).metadata
    assert m.open_graph["og:title"] == "OG Title" and m.open_graph["og:locale"] == "en_GB"
    assert m.twitter == {"twitter:card": "summary_large_image", "twitter:site": "@acme"}
    assert m.robots == "index, follow, max-snippet:-1"
    assert m.viewport == "width=device-width, initial-scale=1"
    assert m.author == "Jane Doe" and m.charset == "utf-8"
    assert m.published_at == datetime.fromisoformat("2024-03-01T10:00:00+00:00")
    assert m.modified_at == datetime.fromisoformat("2024-04-02T12:30:00+02:00")
    assert m.extra["generator"] == "Static Site 9" and "description" in m.extra
    assert m.html_lang == "en-gb"


def test_metadata_dates_from_time_element_and_loose_formats() -> None:
    m = analyze(
        "<html><body><time datetime='2023-12-25' pubdate>xmas</time></body></html>"
    ).metadata
    assert m.published_at == datetime(2023, 12, 25)
    m2 = analyze(
        "<html><head><meta name='date' content='2022-01-05 garbage'></head></html>"
    ).metadata
    assert m2.published_at == datetime(2022, 1, 5)
    m3 = analyze("<html><head><meta name='date' content='yesterday'></head></html>").metadata
    assert m3.published_at is None


# --- language ------------------------------------------------------------------------------


def test_language_precedence_html_lang_then_metadata_then_detection() -> None:
    assert analyze(FULL_PAGE).language.code == "en-GB"
    assert analyze(FULL_PAGE).language.source == "html_lang"

    meta_only = (
        "<html><head><meta property='og:locale' content='de_DE'></head><body>x</body></html>"
    )
    lang = analyze(meta_only).language
    assert (lang.code, lang.source) == ("de-DE", "metadata")

    german = " ".join(["Das ist ein Text und der Text ist nicht mit einem Fehler auf dem Weg"] * 8)
    detected = analyze(f"<html><body><main><p>{german}</p></main></body></html>").language
    assert (detected.code, detected.source) == ("de", "detected") and detected.confidence

    # Too short / ambiguous => abstain rather than guess.
    assert analyze("<html><body><p>hello world</p></body></html>").language.code is None
    assert detect_language("lorem ipsum dolor sit amet " * 20).code is None


def test_lang_tag_normalization() -> None:
    assert normalize_lang_tag("EN-us") == "en-US"
    assert normalize_lang_tag("pt_BR") == "pt-BR"
    assert normalize_lang_tag("en-Latn-US") == "en-Latn"
    assert normalize_lang_tag("not a tag") is None and normalize_lang_tag("") is None
    assert resolve_language(html_lang="x y", metadata_lang="fr", text="").code == "fr"


# --- content extraction / metrics -----------------------------------------------------------


def test_content_extraction_removes_boilerplate_and_keeps_structure() -> None:
    out = analyze(FULL_PAGE)
    text = out.clean_text
    assert "Main Heading" in text and "First paragraph" in text
    assert "Item one" in text and "Item two" in text and "Cell" in text  # lists/tables kept
    for noise in ("We use cookies", "Home", "About", "Related", "© Example", "noise", ".x{}"):
        assert noise not in text, noise
    assert out.pathname == "/blog/post"


def test_content_metrics() -> None:
    c = analyze(FULL_PAGE).content
    assert c.paragraph_count == 2
    assert c.sentence_count >= 3
    assert c.word_count == len(analyze(FULL_PAGE).clean_text.split())
    assert c.character_count == len(analyze(FULL_PAGE).clean_text)
    assert c.reading_time_seconds == round(c.word_count / 238 * 60)
    assert 0 < c.text_to_html_ratio < 1 and c.html_bytes == len(FULL_PAGE.encode())


def test_page_without_main_falls_back_to_body() -> None:
    out = analyze(
        "<html><body><div><p>Body only text.</p></div><footer>foot</footer></body></html>"
    )
    assert out.clean_text == "Body only text." and "foot" not in out.clean_text


# --- malformed HTML --------------------------------------------------------------------------


def test_malformed_html_is_handled() -> None:
    broken = (
        "<html><head><title>Broken</title><meta name=description content='d'>"  # no </head>"
        "<body><h1>Unclosed heading<p>para one<p>para two<a href='/x'>x<a href='/y'>y"
        "<img src=/i.png alt=pic><ul><li>one<li>two</body>"
    )
    out = analyze(broken)
    assert out.headings and out.headings[0].level == 1
    assert {link.href for link in out.links} >= {"/x", "/y"}
    assert out.images[0].src == "https://example.com/i.png" and out.images[0].alt == "pic"
    assert "para one" in out.clean_text and "two" in out.clean_text
    assert out.content.word_count > 0


def test_empty_and_binary_garbage_do_not_crash() -> None:
    for payload in (b"", b"\x00\xff\xfe garbage \x01", b"<html>", b"<<<>>>"):
        out = analyze(payload)
        assert out.headings == [] and out.links == [] and out.images == []
        assert out.content.word_count >= 0 and out.language.code is None


def test_limits_are_enforced() -> None:
    html = (
        "<html><body>" + "".join(f"<a href='/p{i}'>l</a>" for i in range(2500)) + "</body></html>"
    )
    assert len(analyze(html).links) == 2000
