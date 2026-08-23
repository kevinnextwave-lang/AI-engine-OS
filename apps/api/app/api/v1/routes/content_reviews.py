"""Content optimization reviews (Milestone 6D).

The GEO Content Optimization Agent writes reviews; humans decide each proposed
change here (accept / edit / reject). THE ORIGINAL PAGE IS NEVER MODIFIED by
any of these routes — accepted changes are only marked for a later
integration. Project-scoped list uses `require_project_access`; review routes
derive the project from the row (non-members 404).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import Permission
from app.models.content_reviews import ContentOptimizationReview, ReviewStatus
from app.models.crawl import WebsitePage
from app.schemas.content_reviews import (
    ChangeDecisionRequest,
    ReviewListItem,
    ReviewListResponse,
    ReviewUpdateRequest,
    ReviewView,
)

project_router = APIRouter(
    prefix="/projects/{project_id}/content-reviews", tags=["content-reviews"]
)
review_router = APIRouter(prefix="/content-reviews/{review_id}", tags=["content-reviews"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
    409: {"description": "Invalid state for this operation"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]


@project_router.get(
    "",
    response_model=ReviewListResponse,
    summary="Content optimization reviews for a project",
    responses=_ERRORS,
)
async def list_reviews(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[ReviewStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewListResponse:
    stmt = (
        select(ContentOptimizationReview, WebsitePage.url)
        .join(WebsitePage, WebsitePage.id == ContentOptimizationReview.page_id)
        .where(ContentOptimizationReview.project_id == access.project.id)
    )
    if status is not None:
        stmt = stmt.where(ContentOptimizationReview.status == status.value)
    rows = (await session.execute(stmt.order_by(ContentOptimizationReview.score))).all()
    page = rows[offset : offset + limit]
    return ReviewListResponse(
        items=[
            ReviewListItem(
                id=r.id,
                page_id=r.page_id,
                page_url=url,
                score=r.score,
                confidence=r.confidence,
                status=ReviewStatus(r.status),
                findings_count=len(r.findings or []),
                changes_count=len(r.proposed_changes or []),
                pending_changes=sum(
                    1 for c in (r.proposed_changes or []) if c.get("decision") == "pending"
                ),
                analyzed_at=r.analyzed_at,
            )
            for r, url in page
        ],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_review_access(
    session: DBSession, user: CurrentUser, review_id: Annotated[uuid.UUID, Path()]
) -> tuple[ContentOptimizationReview, ProjectAccess]:
    review = await session.get(ContentOptimizationReview, review_id)
    if review is None:
        raise NotFoundError("Content review not found")
    access = await get_project_access(session, user, review.project_id)
    return review, access


ReviewAccess = Annotated[
    tuple[ContentOptimizationReview, ProjectAccess], Depends(get_review_access)
]


@review_router.get("", response_model=ReviewView, summary="Get a review", responses=_ERRORS)
async def get_review(review_access: ReviewAccess) -> ReviewView:
    review, access = review_access
    _require(access, Permission.DATA_READ)
    return ReviewView.model_validate(review)


@review_router.patch(
    "", response_model=ReviewView, summary="Update a review's status", responses=_ERRORS
)
async def update_review(
    review_access: ReviewAccess, body: ReviewUpdateRequest, session: DBSession
) -> ReviewView:
    review, access = review_access
    _require(access, Permission.DATA_MANAGE)
    review.status = body.status.value
    await session.commit()
    await session.refresh(review)
    return ReviewView.model_validate(review)


@review_router.post(
    "/changes/{change_id}",
    response_model=ReviewView,
    summary="Decide one proposed change: accept, edit (with text) or reject",
    responses=_ERRORS,
)
async def decide_change(
    review_access: ReviewAccess,
    change_id: Annotated[str, Path(max_length=32)],
    body: ChangeDecisionRequest,
    session: DBSession,
) -> ReviewView:
    """Records the human decision on the review row only — the original page is
    never touched; accepted/edited changes can later be sent to an integration."""
    review, access = review_access
    _require(access, Permission.DATA_MANAGE)
    changes = list(review.proposed_changes or [])
    target = next((c for c in changes if c.get("change_id") == change_id), None)
    if target is None:
        raise NotFoundError("Proposed change not found on this review")
    if body.action == "edit" and not (body.text and body.text.strip()):
        raise ConflictError("Editing a change requires the edited text")
    target["decision"] = {"accept": "accepted", "edit": "edited", "reject": "rejected"}[body.action]
    if body.action == "edit" and body.text is not None:
        target["decided_text"] = body.text.strip()
    elif body.action == "accept":
        target["decided_text"] = target["proposed_text"]
    else:
        target["decided_text"] = None
    review.proposed_changes = changes
    flag_modified(review, "proposed_changes")
    if review.status == ReviewStatus.DRAFT.value:
        review.status = ReviewStatus.REVIEWING.value
    await session.commit()
    await session.refresh(review)
    return ReviewView.model_validate(review)
