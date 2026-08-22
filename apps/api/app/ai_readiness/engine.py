"""Runs the readiness analyzers for an audit row and persists the results."""

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_readiness.analyzers import run_analyzers
from app.ai_readiness.context import build_context
from app.ai_readiness.scoring import compute_score
from app.core.logging import get_logger
from app.models.ai_readiness import AiReadinessAudit, AiReadinessObservation
from app.models.project import Project
from app.models.seo import AuditStatus
from app.repositories.projects import DomainRepository

log = get_logger("ai_readiness.engine")


async def run_readiness_audit(session: AsyncSession, audit: AiReadinessAudit) -> AiReadinessAudit:
    audit.status = AuditStatus.RUNNING
    audit.started_at = datetime.now(UTC)
    await session.commit()
    try:
        project = await session.get(Project, audit.project_id)
        if project is None:
            raise RuntimeError("project no longer exists")
        domains = await DomainRepository(session).list_for_project(project.id)
        primary = next((d for d in domains if d.is_primary), domains[0] if domains else None)
        root_host = (primary.hostname if primary else "").lower().removeprefix("www.")
        ctx = await build_context(session, project, root_host)
        findings, inputs = run_analyzers(ctx)
        score = compute_score(inputs)
        session.add_all(
            AiReadinessObservation(
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
            )
            for f in findings
        )
        kinds = Counter(k for p in ctx.pages for k in p.kinds)
        audit.pages_analyzed = len(ctx.pages)
        audit.observation_count = len(findings)
        audit.readiness_score = score.score
        audit.score_breakdown = score.breakdown
        audit.summary = {
            "by_severity": dict(Counter(f.severity.value for f in findings)),
            "by_category": dict(Counter(f.category.value for f in findings)),
            "page_kinds": dict(kinds),
            "organization_entity": bool(ctx.organization),
            "entities_compared": ctx.entities_compared,
        }
        audit.status = AuditStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - audit row must always be finalized
        log.exception("ai_readiness_audit_failed", audit_id=str(audit.id))
        audit.status = AuditStatus.FAILED
        audit.error_message = f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        audit.completed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(audit)
        log.info(
            "ai_readiness_audit_completed",
            audit_id=str(audit.id),
            status=audit.status.value,
            observations=audit.observation_count,
            score=audit.readiness_score,
        )
    return audit
