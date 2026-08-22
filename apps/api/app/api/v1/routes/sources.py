"""Source profiles (Citation Intelligence, 4B).

Source domains are shared reference data, so any authenticated user may read a
profile; everything that would reveal *who* cited the source (pages, brands,
competitors, per-project counts) is computed only over projects the caller is a
member of. Cross-tenant information is limited to two plain counts.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError
from app.models.intelligence import ResponseCitation
from app.models.membership import Membership
from app.models.project import Project
from app.models.sources import CitationEntity, SourceDomain, SourcePage
from app.schemas.sources import (
    CitedEntityView,
    CitedPageView,
    SourceClassificationView,
    SourceDomainProfile,
    SourceRelevanceView,
)
from app.sources.relevance import RelevanceInputs, source_relevance

router = APIRouter(prefix="/source-domains", tags=["sources"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    404: {"description": "Source domain not found"},
}


def _accessible_projects(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return (
        select(Project.id)
        .join(Membership, Membership.organization_id == Project.organization_id)
        .where(Membership.user_id == user_id)
    )


@router.get(
    "/{domain_id}",
    response_model=SourceDomainProfile,
    summary="Profile of a cited source domain",
    responses=_ERRORS,
)
async def get_source_domain(
    domain_id: uuid.UUID,
    session: DBSession,
    user: CurrentUser,
    project_id: Annotated[
        uuid.UUID | None,
        Query(description="Scope the relevance score to one of your projects"),
    ] = None,
) -> SourceDomainProfile:
    domain = await session.get(SourceDomain, domain_id)
    if domain is None:
        raise NotFoundError("Source domain not found")
    mine = _accessible_projects(user.id)
    if project_id is not None and project_id not in {
        pid for (pid,) in (await session.execute(mine)).all()
    }:
        raise NotFoundError("Project not found")

    cites = select(ResponseCitation).where(ResponseCitation.source_domain_id == domain.id)
    my_cites = cites.where(ResponseCitation.project_id.in_(mine)).subquery()
    all_cites = cites.subquery()

    citation_count = await session.scalar(select(func.count()).select_from(my_cites)) or 0
    global_count = await session.scalar(select(func.count()).select_from(all_cites)) or 0
    projects_observed = (
        await session.scalar(select(func.count(distinct(my_cites.c.project_id)))) or 0
    )
    global_projects = (
        await session.scalar(select(func.count(distinct(all_cites.c.project_id)))) or 0
    )
    weeks_with = (
        await session.scalar(
            select(func.count(distinct(func.date_trunc("week", all_cites.c.created_at))))
        )
        or 0
    )
    project_count = (
        await session.scalar(
            select(func.count()).select_from(my_cites).where(my_cites.c.project_id == project_id)
        )
        if project_id is not None
        else None
    )

    pages = (
        await session.execute(
            select(
                SourcePage.id,
                SourcePage.url,
                SourcePage.title,
                SourcePage.last_seen_at,
                func.count(my_cites.c.id).label("n"),
            )
            .join(my_cites, my_cites.c.source_page_id == SourcePage.id)
            .group_by(SourcePage.id)
            .order_by(func.count(my_cites.c.id).desc(), SourcePage.last_seen_at.desc())
            .limit(25)
        )
    ).all()
    pages_cited = await session.scalar(select(func.count(distinct(my_cites.c.source_page_id)))) or 0

    async def entities(relationship: str) -> list[CitedEntityView]:
        rows = (
            await session.execute(
                select(CitationEntity.entity_name, func.count())
                .join(my_cites, my_cites.c.id == CitationEntity.citation_id)
                .where(CitationEntity.relationship == relationship)
                .group_by(CitationEntity.entity_name)
                .order_by(func.count().desc())
            )
        ).all()
        return [CitedEntityView(name=name, citations=int(n)) for name, n in rows]

    weeks_since = max(1, (datetime.now(UTC) - domain.first_seen_at).days // 7 + 1)
    relevance = source_relevance(
        RelevanceInputs(
            citation_count=int(global_count),
            projects_observed=int(global_projects),
            weeks_with_citations=int(weeks_with),
            weeks_since_first_seen=weeks_since,
            domain_type=domain.domain_type,
            is_authority=domain.is_authority,
            project_citation_count=int(project_count) if project_count is not None else None,
        )
    )
    cls = domain.classification or {}
    return SourceDomainProfile(
        id=domain.id,
        domain=domain.normalized_hostname,
        display_name=domain.display_name,
        type=domain.domain_type,
        classification=SourceClassificationView(
            type=domain.domain_type,
            confidence=domain.classification_confidence,
            probabilities=cls.get("probabilities", {}),
            authority=domain.is_authority,
            threshold=float(cls.get("threshold", 0.5)),
            evidence=cls.get("evidence", []),
            classified_at=domain.classified_at,
        ),
        citation_count=int(citation_count),
        global_citation_count=int(global_count),
        projects_observed=int(projects_observed),
        global_projects_observed=int(global_projects),
        pages_cited=int(pages_cited),
        pages=[
            CitedPageView(id=pid, url=url, title=title, citation_count=int(n), last_seen_at=seen)
            for pid, url, title, seen, n in pages
        ],
        brands_cited=await entities("brand"),
        competitors_cited=await entities("competitor"),
        first_seen_at=domain.first_seen_at,
        last_seen_at=domain.last_seen_at,
        relevance=SourceRelevanceView(**relevance),
    )
