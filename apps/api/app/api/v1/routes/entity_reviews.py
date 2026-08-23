"""Entity optimization reviews (Milestone 6E).

Written by the entity-optimization agent; humans review here. All proposed
modifications require approval (review status + the run's approval actions);
nothing in these routes changes the site or its structured data.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.entity_reviews import EntityOptimizationReview, ReviewStatus
from app.schemas.entity_reviews import (
    EntityReviewListResponse,
    EntityReviewUpdateRequest,
    EntityReviewView,
)

project_router = APIRouter(prefix="/projects/{project_id}/entity-reviews", tags=["entity-reviews"])
review_router = APIRouter(prefix="/entity-reviews/{review_id}", tags=["entity-reviews"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]


@project_router.get(
    "",
    response_model=EntityReviewListResponse,
    summary="Entity optimization reviews for a project",
    responses=_ERRORS,
)
async def list_entity_reviews(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[ReviewStatus | None, Query()] = None,
    entity_type: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EntityReviewListResponse:
    stmt = select(EntityOptimizationReview).where(
        EntityOptimizationReview.project_id == access.project.id
    )
    if status is not None:
        stmt = stmt.where(EntityOptimizationReview.status == status.value)
    if entity_type is not None:
        stmt = stmt.where(EntityOptimizationReview.entity_type == entity_type)
    rows = list((await session.scalars(stmt.order_by(EntityOptimizationReview.review_key))).all())
    page = rows[offset : offset + limit]
    return EntityReviewListResponse(
        items=[EntityReviewView.model_validate(r) for r in page],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_entity_review_access(
    session: DBSession, user: CurrentUser, review_id: Annotated[uuid.UUID, Path()]
) -> tuple[EntityOptimizationReview, ProjectAccess]:
    review = await session.get(EntityOptimizationReview, review_id)
    if review is None:
        raise NotFoundError("Entity review not found")
    access = await get_project_access(session, user, review.project_id)
    return review, access


EntityReviewAccess = Annotated[
    tuple[EntityOptimizationReview, ProjectAccess], Depends(get_entity_review_access)
]


@review_router.get(
    "", response_model=EntityReviewView, summary="Get an entity review", responses=_ERRORS
)
async def get_entity_review(review_access: EntityReviewAccess) -> EntityReviewView:
    review, access = review_access
    _require(access, Permission.DATA_READ)
    return EntityReviewView.model_validate(review)


@review_router.patch(
    "",
    response_model=EntityReviewView,
    summary="Update a review's status (approval workflow)",
    responses=_ERRORS,
)
async def update_entity_review(
    review_access: EntityReviewAccess, body: EntityReviewUpdateRequest, session: DBSession
) -> EntityReviewView:
    review, access = review_access
    _require(access, Permission.DATA_MANAGE)
    review.status = body.status.value
    await session.commit()
    await session.refresh(review)
    return EntityReviewView.model_validate(review)
