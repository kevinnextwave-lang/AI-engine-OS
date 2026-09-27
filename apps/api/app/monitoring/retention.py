"""Daily data-retention pruning.

Removes only history and security bookkeeping past its window — never
current state. Specifically NOT pruned: website_pages (current content),
seo observations/audits (the verify lifecycle needs them), ai_responses
(the product's measurements), usage records (billing evidence).

Every window is settings-driven; 0 disables that pruner. The page-version
pruner always keeps each page's newest snapshot regardless of age, so
change detection never loses its baseline.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.account_token import AccountToken
from app.models.auth_audit_log import AuthAuditLog
from app.models.crawl import CrawlUrl, PageVersion
from app.models.refresh_token import RefreshToken

log = get_logger("monitoring.retention")


@dataclass
class PruneResult:
    crawl_urls: int = 0
    page_versions: int = 0
    auth_audit_logs: int = 0
    refresh_tokens: int = 0
    account_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.crawl_urls
            + self.page_versions
            + self.auth_audit_logs
            + self.refresh_tokens
            + self.account_tokens
        )


def _count(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def prune_expired_data(session: AsyncSession, *, now: datetime | None = None) -> PruneResult:
    now = now or datetime.now(UTC)
    settings = get_settings()
    out = PruneResult()

    if settings.retention_crawl_urls_days > 0:
        cutoff = now - timedelta(days=settings.retention_crawl_urls_days)
        out.crawl_urls = _count(
            await session.execute(delete(CrawlUrl).where(CrawlUrl.discovered_at < cutoff))
        )

    if settings.retention_page_versions_days > 0:
        cutoff = now - timedelta(days=settings.retention_page_versions_days)
        # Keep the newest version per page whatever its age: it is the
        # baseline the next crawl's change detection compares against.
        latest_per_page = (
            select(PageVersion.id)
            .distinct(PageVersion.page_id)
            .order_by(PageVersion.page_id, PageVersion.crawled_at.desc())
        )
        out.page_versions = _count(
            await session.execute(
                delete(PageVersion).where(
                    PageVersion.crawled_at < cutoff,
                    PageVersion.id.notin_(latest_per_page),
                )
            )
        )

    if settings.retention_auth_audit_days > 0:
        cutoff = now - timedelta(days=settings.retention_auth_audit_days)
        out.auth_audit_logs = _count(
            await session.execute(delete(AuthAuditLog).where(AuthAuditLog.created_at < cutoff))
        )

    if settings.retention_refresh_tokens_days > 0:
        cutoff = now - timedelta(days=settings.retention_refresh_tokens_days)
        # Only rows that can never authenticate again: long-expired or
        # long-revoked. Live sessions are untouched.
        out.refresh_tokens = _count(
            await session.execute(
                delete(RefreshToken).where(
                    (RefreshToken.expires_at < cutoff)
                    | (RefreshToken.revoked_at.is_not(None) & (RefreshToken.revoked_at < cutoff))
                )
            )
        )

    if settings.retention_account_tokens_days > 0:
        cutoff = now - timedelta(days=settings.retention_account_tokens_days)
        out.account_tokens = _count(
            await session.execute(
                delete(AccountToken).where(
                    (AccountToken.used_at.is_not(None) & (AccountToken.used_at < cutoff))
                    | (AccountToken.expires_at < cutoff)
                )
            )
        )

    await session.commit()
    if out.total:
        log.info(
            "retention_pruned",
            crawl_urls=out.crawl_urls,
            page_versions=out.page_versions,
            auth_audit_logs=out.auth_audit_logs,
            refresh_tokens=out.refresh_tokens,
            account_tokens=out.account_tokens,
        )
    return out
