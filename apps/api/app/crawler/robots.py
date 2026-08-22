"""robots.txt handling with a per-origin cache."""

from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

from app.core.logging import get_logger
from app.crawler.fetcher import Fetcher
from app.crawler.urls import CrawlURL, normalize_crawl_url

log = get_logger("crawler.robots")

_MAX_ROBOTS_BYTES = 512 * 1024


@dataclass
class RobotsRules:
    parser: RobotFileParser | None  # None => no robots.txt, allow all
    crawl_delay: float | None
    sitemaps: list[str]
    fetch_error: str | None = None  # set when robots.txt could not be retrieved

    def allows(self, user_agent: str, url: str) -> bool:
        if self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)


class RobotsCache:
    def __init__(self, fetcher: Fetcher, user_agent: str) -> None:
        self._fetcher = fetcher
        self._ua = user_agent
        self._cache: dict[str, RobotsRules] = {}

    def product_token(self) -> str:
        return self._ua.split("/")[0]

    async def rules_for(self, url: CrawlURL) -> RobotsRules:
        origin = url.origin
        cached = self._cache.get(origin)
        if cached is not None:
            return cached
        robots_url = normalize_crawl_url(f"{origin}/robots.txt")
        result = await self._fetcher.fetch(robots_url, allow_non_html=True)
        rules = RobotsRules(parser=None, crawl_delay=None, sitemaps=[])
        if result.ok and result.body is not None and result.status_code == 200:
            text = result.body[:_MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            delay = parser.crawl_delay(self.product_token())
            rules = RobotsRules(
                parser=parser,
                crawl_delay=float(delay) if delay else None,
                sitemaps=list(parser.site_maps() or []),
            )
        elif result.status_code is not None and 400 <= result.status_code < 500:
            rules = RobotsRules(parser=None, crawl_delay=None, sitemaps=[])  # 4xx => allow all
        elif result.error or (result.status_code or 0) >= 500:
            # Unreachable / server error: be conservative and disallow everything
            # except the homepage, as Google does for persistent 5xx.
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
            rules = RobotsRules(
                parser=parser,
                crawl_delay=None,
                sitemaps=[],
                fetch_error=result.error or f"http {result.status_code}",
            )
            log.warning("robots_unavailable", origin=origin, error=rules.fetch_error)
        self._cache[origin] = rules
        return rules

    def allows(self, rules: RobotsRules, url: str) -> bool:
        return rules.allows(self.product_token(), url)
