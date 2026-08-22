"""Plan-aware crawl limits. Business logic asks for a CrawlLimits, never a constant."""

from dataclasses import dataclass

from app.core.config import Settings
from app.models.organization import OrganizationPlan


@dataclass(frozen=True)
class CrawlLimits:
    max_pages_cap: int
    max_depth_cap: int
    concurrency: int
    requests_per_second: float
    allow_subdomains: bool


_PLAN_CAPS: dict[OrganizationPlan, tuple[int, int, int, float]] = {
    # plan: (max_pages_cap, max_depth_cap, concurrency, rps)
    OrganizationPlan.FREE: (100, 3, 2, 1.0),
    OrganizationPlan.STARTER: (500, 5, 3, 2.0),
    OrganizationPlan.GROWTH: (2_000, 8, 5, 3.0),
    OrganizationPlan.PRO: (10_000, 10, 8, 5.0),
    OrganizationPlan.AGENCY: (25_000, 12, 10, 6.0),
    OrganizationPlan.ENTERPRISE: (100_000, 15, 15, 8.0),
}


def limits_for_plan(plan: OrganizationPlan, settings: Settings) -> CrawlLimits:
    pages, depth, conc, rps = _PLAN_CAPS[plan]
    return CrawlLimits(
        max_pages_cap=pages,
        max_depth_cap=depth,
        concurrency=min(conc, settings.crawl_concurrency),
        requests_per_second=min(rps, settings.crawl_requests_per_second),
        allow_subdomains=settings.crawl_allow_subdomains,
    )
