"""Runs every check over an AuditContext and persists the results."""

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import safe_error_message
from app.core.logging import get_logger
from app.models.crawl import CrawlJob
from app.models.seo import AuditStatus, ObservationStatus, SeoAudit, SeoObservation
from app.seo.checks.canonical import check_canonical
from app.seo.checks.headings import check_headings
from app.seo.checks.http import check_http, check_indexability
from app.seo.checks.links import check_internal_links
from app.seo.checks.metadata import check_metadata
from app.seo.checks.structured import check_mobile_html, check_structured_data
from app.seo.context import AuditContext, build_context
from app.seo.findings import Finding
from app.seo.scoring import compute_score

log = get_logger("seo.engine")

CHECKS = (
    check_indexability,
    check_http,
    check_metadata,
    check_headings,
    check_canonical,
    check_internal_links,
    check_structured_data,
    check_mobile_html,
)


def run_checks(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(ctx))
    return findings


async def _previously_ignored(
    session: AsyncSession, audit: SeoAudit
) -> dict[tuple[str, str | None], str | None]:
    """(code, url) -> status_note for observations the user IGNORED on the
    most recent completed audit before this one. Chronology matters: only
    the immediately previous completed audit is consulted."""
    prev_id = (
        await session.execute(
            select(SeoAudit.id)
            .where(
                SeoAudit.project_id == audit.project_id,
                SeoAudit.status == AuditStatus.COMPLETED,
                SeoAudit.id != audit.id,
            )
            .order_by(SeoAudit.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prev_id is None:
        return {}
    rows = (
        await session.execute(
            select(SeoObservation.code, SeoObservation.url, SeoObservation.status_note).where(
                SeoObservation.audit_id == prev_id,
                SeoObservation.status == ObservationStatus.IGNORED,
            )
        )
    ).all()
    return {(code, url): note for code, url, note in rows}


async def run_audit(session: AsyncSession, audit: SeoAudit) -> SeoAudit:
    audit.status = AuditStatus.RUNNING
    audit.started_at = datetime.now(UTC)
    await session.commit()
    try:
        job = await session.get(CrawlJob, audit.crawl_job_id)
        if job is None:
            raise RuntimeError("crawl job no longer exists")
        ctx = await build_context(session, job)
        findings = run_checks(ctx)
        score = compute_score(findings, len(ctx.html_pages))
        # Carry IGNORED forward: when the previous completed audit had the
        # same issue (code + url) marked ignored, the new observation starts
        # ignored too — "don't tell me about this again" survives re-audits.
        # RESOLVED is deliberately NOT carried: a resolved issue that is
        # detected again must come back OPEN, which is exactly what the
        # verification lifecycle surfaces as "still detected".
        ignored = await _previously_ignored(session, audit)
        session.add_all(
            SeoObservation(
                audit_id=audit.id,
                project_id=audit.project_id,
                page_id=f.page_id,
                url=f.url,
                category=f.category,
                code=f.code,
                severity=f.severity,
                title=f.title,
                description=f.description,
                evidence=f.evidence,
                recommendation=f.recommendation,
                status=(
                    ObservationStatus.IGNORED
                    if (f.code, f.url) in ignored
                    else ObservationStatus.OPEN
                ),
                status_note=ignored.get((f.code, f.url)),
            )
            for f in findings
        )
        by_severity = Counter(f.severity.value for f in findings)
        by_category = Counter(f.category.value for f in findings)
        audit.pages_analyzed = len(ctx.pages)
        audit.observation_count = len(findings)
        audit.health_score = score.score
        audit.score_breakdown = score.breakdown
        audit.summary = {
            "by_severity": dict(by_severity),
            "by_category": dict(by_category),
            "html_pages": len(ctx.html_pages),
            "indexable_pages": len(ctx.indexable_pages),
        }
        audit.status = AuditStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - audit row must always be finalized
        log.exception("seo_audit_failed", audit_id=str(audit.id))
        # Clear a possibly-poisoned transaction so the finalizing commit
        # below cannot fail and leave the audit stuck in RUNNING.
        await session.rollback()
        audit.status = AuditStatus.FAILED
        audit.error_message = safe_error_message(exc)
    finally:
        audit.completed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(audit)  # DB-side timestamps
        log.info(
            "seo_audit_completed",
            audit_id=str(audit.id),
            status=audit.status.value,
            observations=audit.observation_count,
            score=audit.health_score,
        )
    return audit
