"""Prompt sets and prompts.

Authorization: the collection routes use `require_project_access`; prompt-set
and prompt routes derive the project from the row and check membership
(404 for other tenants). DATA_READ for reads, DATA_MANAGE for writes.
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
from app.models.prompts import FunnelStage, Prompt, PromptCategory, PromptSet, PromptSetStatus
from app.repositories.prompts import PromptRepository, PromptSetRepository
from app.schemas.common import MessageResponse
from app.schemas.prompts import (
    PromptCreateRequest,
    PromptGenerateRequest,
    PromptGenerateResponse,
    PromptListResponse,
    PromptResponse,
    PromptSetCreateRequest,
    PromptSetListResponse,
    PromptSetResponse,
    PromptUpdateRequest,
)
from app.services.prompts import PromptService

project_router = APIRouter(prefix="/projects/{project_id}/prompt-sets", tags=["prompts"])
set_router = APIRouter(prefix="/prompt-sets/{prompt_set_id}", tags=["prompts"])
prompt_router = APIRouter(prefix="/prompts/{prompt_id}", tags=["prompts"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


async def get_prompt_set_access(
    session: DBSession, user: CurrentUser, prompt_set_id: Annotated[uuid.UUID, Path()]
) -> tuple[PromptSet, ProjectAccess]:
    prompt_set = await PromptSetRepository(session).get(prompt_set_id)
    if prompt_set is None:
        raise NotFoundError("Prompt set not found")
    access = await get_project_access(session, user, prompt_set.project_id)
    return prompt_set, access


async def get_prompt_access(
    session: DBSession, user: CurrentUser, prompt_id: Annotated[uuid.UUID, Path()]
) -> tuple[Prompt, ProjectAccess]:
    prompt = await PromptRepository(session).get(prompt_id)
    if prompt is None:
        raise NotFoundError("Prompt not found")
    access = await get_project_access(session, user, prompt.project_id)
    return prompt, access


SetAccess = Annotated[tuple[PromptSet, ProjectAccess], Depends(get_prompt_set_access)]
PromptAccess = Annotated[tuple[Prompt, ProjectAccess], Depends(get_prompt_access)]


def _require(access: ProjectAccess, permission: Permission) -> None:
    if not role_has(access.membership.role, permission):
        raise PermissionDeniedError()


# -- project-scoped ------------------------------------------------------------


@project_router.post(
    "",
    response_model=PromptSetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a prompt set",
    responses=_ERRORS,
)
async def create_prompt_set(
    body: PromptSetCreateRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    session: DBSession,
) -> PromptSetResponse:
    service = PromptService(session)
    return await service.set_response(await service.create_set(access.project, body))


@project_router.get(
    "",
    response_model=PromptSetListResponse,
    summary="List a project's prompt sets",
    responses=_ERRORS,
)
async def list_prompt_sets(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
    status_filter: Annotated[PromptSetStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptSetListResponse:
    items, total = await PromptService(session).list_sets(
        access.project, status=status_filter, limit=limit, offset=offset
    )
    return PromptSetListResponse(items=items, total=total)


# -- prompt-set scoped ---------------------------------------------------------------


@set_router.post(
    "/generate",
    response_model=PromptGenerateResponse,
    summary="Generate prompts for a set",
    description=(
        "Deterministically generates realistic buyer questions from the business profile "
        "(project data plus overrides), de-duplicated against the set, scored and "
        "prioritized. No AI provider is called."
    ),
    responses={**_ERRORS, 409: {"description": "Prompt set is archived"}},
)
async def generate_prompts(
    body: PromptGenerateRequest, set_access: SetAccess, session: DBSession
) -> PromptGenerateResponse:
    prompt_set, access = set_access
    _require(access, Permission.DATA_MANAGE)
    service = PromptService(session)
    created, skipped, profile = await service.generate(
        prompt_set,
        access.project,
        body.profile,
        categories=body.categories,
        max_prompts=body.max_prompts,
        max_per_category=body.max_per_category,
    )
    return PromptGenerateResponse(
        prompt_set_id=prompt_set.id,
        generated=len(created),
        skipped_duplicates=skipped,
        profile=profile.to_dict(),
        items=await service.responses(created),
    )


@set_router.get(
    "/prompts",
    response_model=PromptListResponse,
    summary="List prompts in a set (table-ready)",
    responses=_ERRORS,
)
async def list_prompts(
    set_access: SetAccess,
    session: DBSession,
    category: Annotated[PromptCategory | None, Query()] = None,
    funnel_stage: Annotated[FunnelStage | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptListResponse:
    prompt_set, access = set_access
    _require(access, Permission.DATA_READ)
    items, total = await PromptService(session).list_prompts(
        prompt_set,
        category=category,
        funnel_stage=funnel_stage,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return PromptListResponse(items=items, total=total, limit=limit, offset=offset)


@set_router.post(
    "/prompts",
    response_model=PromptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a prompt manually",
    responses={**_ERRORS, 409: {"description": "Duplicate or near-duplicate prompt"}},
)
async def create_prompt(
    body: PromptCreateRequest, set_access: SetAccess, session: DBSession
) -> PromptResponse:
    prompt_set, access = set_access
    _require(access, Permission.DATA_MANAGE)
    service = PromptService(session)
    prompt = await service.create_prompt(prompt_set, body)
    return (await service.responses([prompt]))[0]


# -- prompt scoped --------------------------------------------------------------------


@prompt_router.patch(
    "",
    response_model=PromptResponse,
    summary="Update a prompt",
    responses={**_ERRORS, 409: {"description": "Duplicate prompt"}},
)
async def update_prompt(
    body: PromptUpdateRequest, prompt_access: PromptAccess, session: DBSession
) -> PromptResponse:
    prompt, access = prompt_access
    _require(access, Permission.DATA_MANAGE)
    service = PromptService(session)
    updated = await service.update_prompt(prompt, body)
    return (await service.responses([updated]))[0]


@prompt_router.delete(
    "", response_model=MessageResponse, summary="Delete a prompt", responses=_ERRORS
)
async def delete_prompt(prompt_access: PromptAccess, session: DBSession) -> MessageResponse:
    prompt, access = prompt_access
    _require(access, Permission.DATA_MANAGE)
    await PromptService(session).delete_prompt(prompt)
    return MessageResponse(message="Prompt deleted")
