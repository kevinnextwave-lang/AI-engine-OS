"""Classify sameAs / profile URLs by platform."""

from urllib.parse import urlsplit

# host suffix -> platform. Order matters only for readability.
_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("linkedin.com", "linkedin"),
    ("wikipedia.org", "wikipedia"),
    ("wikidata.org", "wikidata"),
    ("facebook.com", "facebook"),
    ("instagram.com", "instagram"),
    ("twitter.com", "x"),
    ("x.com", "x"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("tiktok.com", "tiktok"),
    ("threads.net", "threads"),
    ("pinterest.com", "pinterest"),
    ("github.com", "github"),
    ("crunchbase.com", "crunchbase"),
    ("bloomberg.com", "bloomberg"),
    ("trustpilot.com", "trustpilot"),
    ("g2.com", "g2"),
    ("glassdoor.com", "glassdoor"),
    ("medium.com", "medium"),
    ("reddit.com", "reddit"),
    ("mastodon.social", "mastodon"),
    ("bsky.app", "bluesky"),
    ("apps.apple.com", "app_store"),
    ("play.google.com", "google_play"),
    ("google.com", "google"),
    ("yelp.com", "yelp"),
    ("tripadvisor.com", "tripadvisor"),
    ("imdb.com", "imdb"),
    ("orcid.org", "orcid"),
    ("scholar.google.com", "google_scholar"),
    ("dnb.com", "dnb"),
    ("opencorporates.com", "opencorporates"),
)

# Profiles that identify the entity in knowledge graphs / registries rather than
# just host its social presence.
AUTHORITATIVE = frozenset(
    {"wikipedia", "wikidata", "crunchbase", "bloomberg", "orcid", "dnb", "opencorporates", "imdb"}
)


def classify(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for suffix, platform in _PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return platform
    return "other"


def is_authoritative(platform: str) -> bool:
    return platform in AUTHORITATIVE
