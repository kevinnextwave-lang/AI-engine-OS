"""Retention pruning: old history goes, current state and baselines stay."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models import CrawlJob, CrawlStatus, CrawlType, Organization, Project
from app.models.account_token import AccountToken, AccountTokenPurpose
from app.models.crawl import CrawlUrl, CrawlUrlStatus, PageVersion, WebsitePage
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.monitoring.retention import prune_expired_data

NOW = datetime.now(UTC)


async def _project(session: AsyncSession) -> Project:
    org = Organization(name="Retain Co", slug=f"ret-{uuid.uuid4().hex[:8]}")
    project = Project(organization=org, name="Site", slug=f"site-{uuid.uuid4().hex[:6]}")
    session.add(project)
    await session.flush()
    return project


async def test_prune_page_versions_keeps_newest_per_page(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    job = CrawlJob(
        project_id=project.id,
        root_url="https://ret.example/",
        crawl_type=CrawlType.FULL,
        max_pages=10,
        max_depth=2,
        status=CrawlStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.flush()
    page = WebsitePage(
        project_id=project.id,
        url="https://ret.example/a",
        normalized_url="https://ret.example/a",
        http_status=200,
        content_type="text/html",
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )
    db_session.add(page)
    await db_session.flush()

    def version(days_ago: int) -> PageVersion:
        return PageVersion(
            page_id=page.id,
            project_id=project.id,
            crawl_job_id=job.id,
            http_status=200,
            crawled_at=NOW - timedelta(days=days_ago),
        )

    ancient_a = version(400)
    ancient_b = version(300)  # newest for this page — must survive despite age
    db_session.add_all([ancient_a, ancient_b])
    # A second page whose only (ancient) version must also survive.
    page2 = WebsitePage(
        project_id=project.id,
        url="https://ret.example/b",
        normalized_url="https://ret.example/b",
        http_status=200,
        content_type="text/html",
        first_crawled_at=NOW,
        last_crawled_at=NOW,
    )
    db_session.add(page2)
    await db_session.flush()
    only = PageVersion(
        page_id=page2.id,
        project_id=project.id,
        crawl_job_id=job.id,
        http_status=200,
        crawled_at=NOW - timedelta(days=500),
    )
    db_session.add(only)
    # Old crawl_urls go; fresh ones stay.
    old_url = CrawlUrl(
        crawl_job_id=job.id,
        project_id=project.id,
        url="https://ret.example/old",
        normalized_url="https://ret.example/old",
        status=CrawlUrlStatus.CRAWLED,
        discovered_at=NOW - timedelta(days=120),
    )
    new_url = CrawlUrl(
        crawl_job_id=job.id,
        project_id=project.id,
        url="https://ret.example/new",
        normalized_url="https://ret.example/new",
        status=CrawlUrlStatus.CRAWLED,
        discovered_at=NOW - timedelta(days=5),
    )
    db_session.add_all([old_url, new_url])
    await db_session.flush()

    result = await prune_expired_data(db_session, now=NOW)

    assert result.page_versions == 1  # only ancient_a
    remaining = {v.id for v in (await db_session.scalars(select(PageVersion))).all()}
    assert ancient_b.id in remaining and only.id in remaining and ancient_a.id not in remaining
    assert result.crawl_urls >= 1
    urls = {u.normalized_url for u in (await db_session.scalars(select(CrawlUrl))).all()}
    assert "https://ret.example/new" in urls and "https://ret.example/old" not in urls


async def test_prune_tokens_only_dead_ones(db_session: AsyncSession) -> None:
    user = User(email=f"ret-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    live = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(f"live-{uuid.uuid4().hex}"),
        expires_at=NOW + timedelta(days=10),
    )
    long_dead = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(f"dead-{uuid.uuid4().hex}"),
        expires_at=NOW - timedelta(days=90),
    )
    recently_revoked = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(f"rev-{uuid.uuid4().hex}"),
        expires_at=NOW + timedelta(days=10),
        revoked_at=NOW - timedelta(days=2),
    )
    used_old = AccountToken(
        user_id=user.id,
        purpose=AccountTokenPurpose.PASSWORD_RESET.value,
        token_hash=hash_token(f"acct-{uuid.uuid4().hex}"),
        expires_at=NOW - timedelta(days=40),
        used_at=NOW - timedelta(days=40),
    )
    fresh_unused = AccountToken(
        user_id=user.id,
        purpose=AccountTokenPurpose.EMAIL_VERIFY.value,
        token_hash=hash_token(f"acct2-{uuid.uuid4().hex}"),
        expires_at=NOW + timedelta(days=2),
    )
    db_session.add_all([live, long_dead, recently_revoked, used_old, fresh_unused])
    await db_session.flush()

    result = await prune_expired_data(db_session, now=NOW)

    assert result.refresh_tokens == 1 and result.account_tokens == 1
    kept_refresh = {r.id for r in (await db_session.scalars(select(RefreshToken))).all()}
    assert live.id in kept_refresh and recently_revoked.id in kept_refresh
    assert long_dead.id not in kept_refresh
    kept_acct = {a.id for a in (await db_session.scalars(select(AccountToken))).all()}
    assert fresh_unused.id in kept_acct and used_old.id not in kept_acct
