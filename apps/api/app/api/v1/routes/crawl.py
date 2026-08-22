"""Website crawl endpoints.

Authorization: every route resolves the project (from the path, or from the
crawl job row) and validates the caller's membership in its organization via
`require_project_access`. Crawl jobs are never looked up without the tenant
check; unknown or foreign jobs are 404.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, role_has
from app.models.crawl import CrawlJob, CrawlUrlStatus
from app.models.organization import Organization
from app.repositories.crawl import CrawlJobRepository
from app.schemas.crawl import (
    CrawlJobListResponse,
    CrawlJobResponse,
    CrawlPageSummary,
    CrawlStartRequest,
    CrawlUrlListResponse,
    CrawlUrlResponse,
)
from app.services.crawl import CrawlService, Dispatcher
from app.workers.tasks import dispatch_crawl_job

project_router = APIRouter(prefix="/projects/{project_id}", tags=["crawl"])
router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def get_crawl_dispatcher() -> Dispatcher:
    return dispatch_crawl_job


DispatcherDep = Annotated[Dispatcher, Depends(get_crawl_dispatcher)]


async def get_crawl_job_access(
    session: DBSession,
    user: CurrentUser,
    crawl_id: Annotated[uuid.UUID, Path()],
) -> tuple[CrawlJob, ProjectAccess]:
    """Resolve a crawl job and the caller's access to its project (404 if either fails)."""
    job = await CrawlJobRepository(session).get(crawl_id)
    if job is None:
        raise NotFoundError("Crawl job not found")
    access = await get_project_access(session, user, job.project_id)
    return job, access


CrawlJobAccess = Annotated[tuple[CrawlJob, ProjectAccess], Depends(get_crawl_job_access)]


def _require(access: ProjectAccess, permission: Permission) -> None:
    if not role_has(access.membership.role, permission):
        raise PermissionDeniedError()


def _job_response(job: CrawlJob) -> CrawlJobResponse:
    return CrawlJobResponse.model_validate(job)


# -- project-scoped ----------------------------------------------------------


@project_router.post(
    "/crawl",
    response_model=CrawlJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a crawl",
    description=(
        "Queues an asynchronous crawl of the project's website. Returns 409 if a crawl "
        "is already queued or running. Limits are capped by the organization's plan."
    ),
    responses={**_ERRORS, 409: {"description": "A crawl is already active"}},
)
async def start_crawl(
    body: CrawlStartRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    user: CurrentUser,
    session: DBSession,
    dispatcher: DispatcherDep,
) -> CrawlJobResponse:
    organization: Organization = access.organization
    job = await CrawlService(session, dispatcher).start(
        project=access.project,
        organization=organization,
        requested_by=user.id,
        crawl_type=body.crawl_type,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        url=body.url,
    )
    return _job_response(job)


@project_router.get(
    "/crawl-jobs",
    response_model=CrawlJobListResponse,
    summary="List a project's crawl jobs",
    responses=_ERRORS,
)
async def list_crawl_jobs(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
    dispatcher: DispatcherDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CrawlJobListResponse:
    jobs, total = await CrawlService(session, dispatcher).list_for_project(
        access.project, limit=limit, offset=offset
    )
    return CrawlJobListResponse(items=[_job_response(j) for j in jobs], total=total)


@project_router.post(
    "/crawl-jobs/{crawl_id}/cancel",
    response_model=CrawlJobResponse,
    summary="Cancel a crawl (project-scoped)",
    responses={**_ERRORS, 409: {"description": "Crawl is not active"}},
)
async def cancel_crawl_in_project(
    crawl_id: uuid.UUID,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    session: DBSession,
    dispatcher: DispatcherDep,
) -> CrawlJobResponse:
    service = CrawlService(session, dispatcher)
    job = await service.get_for_project(access.project.id, crawl_id)
    return _job_response(await service.cancel(job))


# -- job-scoped --------------------------------------------------------------


@router.get(
    "/{crawl_id}", response_model=CrawlJobResponse, summary="Get a crawl job", responses=_ERRORS
)
async def get_crawl_job(job_access: CrawlJobAccess) -> CrawlJobResponse:
    job, access = job_access
    _require(access, Permission.DATA_READ)
    return _job_response(job)


@router.post(
    "/{crawl_id}/cancel",
    response_model=CrawlJobResponse,
    summary="Cancel a crawl",
    description="Stops scheduling new fetches; in-flight requests finish gracefully.",
    responses={**_ERRORS, 409: {"description": "Crawl is not active"}},
)
async def cancel_crawl_job(
    job_access: CrawlJobAccess, session: DBSession, dispatcher: DispatcherDep
) -> CrawlJobResponse:
    job, access = job_access
    _require(access, Permission.DATA_MANAGE)
    return _job_response(await CrawlService(session, dispatcher).cancel(job))


@router.get(
    "/{crawl_id}/pages",
    response_model=CrawlUrlListResponse,
    summary="List URLs seen by a crawl",
    description="Every discovered URL with its outcome; crawled URLs include the page record.",
    responses=_ERRORS,
)
async def list_crawl_pages(
    job_access: CrawlJobAccess,
    session: DBSession,
    dispatcher: DispatcherDep,
    status_filter: Annotated[CrawlUrlStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CrawlUrlListResponse:
    job, access = job_access
    _require(access, Permission.DATA_READ)
    rows, total, pages = await CrawlService(session, dispatcher).list_urls(
        job, status=status_filter, limit=limit, offset=offset
    )
    items = []
    for row in rows:
        item = CrawlUrlResponse.model_validate(row)
        page = pages.get(row.page_id) if row.page_id else None
        item.page = CrawlPageSummary.model_validate(page) if page else None
        items.append(item)
    return CrawlUrlListResponse(items=items, total=total, limit=limit, offset=offset)
