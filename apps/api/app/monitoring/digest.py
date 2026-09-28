"""Weekly activity digest email.

One plain-text email per owner/admin of each opted-in organization,
summarizing the last 7 days per project: visibility score movement (from the
same VisibilityEngine the app shows, never recomputed differently),
collections, audits, and crawls. Orgs with nothing to report get no email —
an empty digest trains people to delete the real ones.

Numbers follow the product's honesty rules: a score that lacks sample is
reported as "not enough data", never as 0.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import EmailMessage, EmailSender, get_email_sender
from app.core.logging import get_logger
from app.models.ai_readiness import AiReadinessAudit
from app.models.crawl import CrawlJob, CrawlStatus
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization, OrganizationStatus
from app.models.project import Project, ProjectStatus
from app.models.prompts import BatchStatus, PromptRunBatch
from app.models.seo import AuditStatus, SeoAudit
from app.models.user import User
from app.visibility.engine import VisibilityEngine

log = get_logger("monitoring.digest")

WINDOW_DAYS = 7
_FINISHED_BATCHES = (BatchStatus.COMPLETED, BatchStatus.PARTIAL)
_DIGEST_ROLES = (MembershipRole.OWNER, MembershipRole.ADMIN)


@dataclass
class ProjectSummary:
    name: str
    score: float | None
    previous_score: float | None
    trend: str | None
    sample_size: int
    batches: int
    total_runs: int
    failed_runs: int
    seo_audits: int
    readiness_audits: int
    crawls: int

    @property
    def has_activity(self) -> bool:
        return bool(self.batches or self.seo_audits or self.readiness_audits or self.crawls)


@dataclass
class DigestResult:
    orgs_considered: int = 0
    emails_sent: int = 0
    orgs_skipped_quiet: int = 0
    orgs_failed: int = 0


async def _project_summary(
    session: AsyncSession, project: Project, *, now: datetime
) -> ProjectSummary:
    cutoff = now - timedelta(days=WINDOW_DAYS)
    overview: dict[str, Any] = await VisibilityEngine(session, now=now).overview(project.id, "7d")
    current = overview.get("current") or {}
    previous = overview.get("previous") or {}
    batch_rows = (
        await session.execute(
            select(
                func.count(PromptRunBatch.id),
                func.coalesce(func.sum(PromptRunBatch.total_runs), 0),
                func.coalesce(func.sum(PromptRunBatch.failed_runs), 0),
            ).where(
                PromptRunBatch.project_id == project.id,
                PromptRunBatch.status.in_(_FINISHED_BATCHES),
                PromptRunBatch.created_at >= cutoff,
            )
        )
    ).one()
    seo_count = await session.scalar(
        select(func.count(SeoAudit.id)).where(
            SeoAudit.project_id == project.id,
            SeoAudit.status == AuditStatus.COMPLETED,
            SeoAudit.completed_at >= cutoff,
        )
    )
    readiness_count = await session.scalar(
        select(func.count(AiReadinessAudit.id)).where(
            AiReadinessAudit.project_id == project.id,
            AiReadinessAudit.status == AuditStatus.COMPLETED,
            AiReadinessAudit.completed_at >= cutoff,
        )
    )
    crawl_count = await session.scalar(
        select(func.count(CrawlJob.id)).where(
            CrawlJob.project_id == project.id,
            CrawlJob.status == CrawlStatus.COMPLETED,
            CrawlJob.completed_at >= cutoff,
        )
    )
    return ProjectSummary(
        name=project.name,
        score=current.get("score"),
        previous_score=previous.get("score"),
        trend=overview.get("trend"),
        sample_size=int((current.get("data_quality") or {}).get("sample_size") or 0),
        batches=int(batch_rows[0]),
        total_runs=int(batch_rows[1]),
        failed_runs=int(batch_rows[2]),
        seo_audits=int(seo_count or 0),
        readiness_audits=int(readiness_count or 0),
        crawls=int(crawl_count or 0),
    )


def _fmt_score(s: ProjectSummary) -> str:
    if s.score is None:
        return "Visibility score: not enough data this week"
    line = f"Visibility score: {s.score:g} (n={s.sample_size})"
    if s.previous_score is not None and s.trend in ("up", "down", "flat"):
        arrow = {"up": "up from", "down": "down from", "flat": "unchanged from"}[s.trend]
        line += f", {arrow} {s.previous_score:g} the week before"
    return line


def render_digest(org_name: str, summaries: list[ProjectSummary], *, now: datetime) -> str:
    start = (now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    end = now.date().isoformat()
    lines = [f"AI search visibility for {org_name}, {start} to {end}.", ""]
    for s in summaries:
        lines.append(s.name)
        lines.append(f"  {_fmt_score(s)}")
        if s.batches:
            failed = f", {s.failed_runs} failed" if s.failed_runs else ""
            lines.append(
                f"  Collections: {s.batches} finished ({s.total_runs} prompt runs{failed})"
            )
        else:
            lines.append("  Collections: none this week")
        extras: list[str] = []
        if s.seo_audits:
            extras.append(f"{s.seo_audits} SEO audit{'s' if s.seo_audits != 1 else ''}")
        if s.readiness_audits:
            extras.append(
                f"{s.readiness_audits} AI readiness audit{'s' if s.readiness_audits != 1 else ''}"
            )
        if s.crawls:
            extras.append(f"{s.crawls} crawl{'s' if s.crawls != 1 else ''}")
        if extras:
            lines.append("  Also: " + ", ".join(extras))
        lines.append("")
    lines.append("You get this weekly summary because you manage this organization.")
    lines.append("Turn it off in Settings -> Organization -> Weekly digest.")
    return "\n".join(lines)


async def _recipients(session: AsyncSession, org_id: uuid.UUID) -> list[str]:
    rows = (
        await session.scalars(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == org_id, Membership.role.in_(_DIGEST_ROLES))
            .order_by(User.email)
        )
    ).all()
    return list(rows)


async def build_org_digest(
    session: AsyncSession, org: Organization, *, now: datetime
) -> str | None:
    """The digest body, or None when there is nothing worth sending."""
    projects = (
        await session.scalars(
            select(Project).where(
                Project.organization_id == org.id,
                Project.status == ProjectStatus.ACTIVE,
            )
        )
    ).all()
    if not projects:
        return None
    summaries = [await _project_summary(session, p, now=now) for p in projects]
    if not any(s.has_activity or s.score is not None for s in summaries):
        return None
    return render_digest(org.name, summaries, now=now)


async def send_weekly_digests(
    session: AsyncSession,
    *,
    sender: EmailSender | None = None,
    now: datetime | None = None,
) -> DigestResult:
    now = now or datetime.now(UTC)
    sender = sender or get_email_sender()
    result = DigestResult()
    orgs = (
        await session.scalars(
            select(Organization).where(
                Organization.weekly_digest_enabled.is_(True),
                Organization.status == OrganizationStatus.ACTIVE,
                Organization.deleted_at.is_(None),
            )
        )
    ).all()
    for org in orgs:
        result.orgs_considered += 1
        try:
            body = await build_org_digest(session, org, now=now)
            if body is None:
                result.orgs_skipped_quiet += 1
                continue
            subject = f"{org.name}: your AI visibility week"
            for email in await _recipients(session, org.id):
                await sender.send(EmailMessage(to=email, subject=subject, text=body))
                result.emails_sent += 1
        except Exception as exc:  # noqa: BLE001 - one org must not sink the rest
            result.orgs_failed += 1
            log.warning("digest_org_failed", organization_id=str(org.id), error=str(exc))
    log.info(
        "weekly_digests_sent",
        orgs=result.orgs_considered,
        emails=result.emails_sent,
        quiet=result.orgs_skipped_quiet,
        failed=result.orgs_failed,
    )
    return result
