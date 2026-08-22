"""Prompt execution: run a set, inspect batches/runs, cancel.

Tenancy: prompt-set and batch routes derive the project from the row and
check membership (404 otherwise). DATA_MANAGE to run/cancel, DATA_READ to read.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.ai.registry import ProviderRegistry
from app.api.deps import CurrentUser, DBSession, ProjectAccess, get_project_access
from app.api.v1.routes.prompts import SetAccess, _require
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.prompts import PromptRunBatch, PromptRunStatus
from app.repositories.execution import BatchRepository, PromptRunRepository
from app.schemas.execution import (
    AiResponseView,
    BatchListResponse,
    BatchResponse,
    PromptRunListResponse,
    PromptRunResponse,
    RunPromptSetRequest,
)
from app.services.execution import ExecutionService, RunDispatcher
from app.workers.tasks import dispatch_prompt_run

set_router = APIRouter(prefix="/prompt-sets/{prompt_set_id}", tags=["execution"])
batch_router = APIRouter(prefix="/prompt-run-batches/{batch_id}", tags=["execution"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}

_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _registry  # noqa: PLW0603 - process-wide adapter cache
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def get_run_dispatcher() -> RunDispatcher:
    return dispatch_prompt_run


RegistryDep = Annotated[ProviderRegistry, Depends(get_provider_registry)]
DispatcherDep = Annotated[RunDispatcher, Depends(get_run_dispatcher)]


async def get_batch_access(
    session: DBSession, user: CurrentUser, batch_id: Annotated[uuid.UUID, Path()]
) -> tuple[PromptRunBatch, ProjectAccess]:
    batch = await BatchRepository(session).get(batch_id)
    if batch is None:
        raise NotFoundError("Batch not found")
    access = await get_project_access(session, user, batch.project_id)
    return batch, access


BatchAccess = Annotated[tuple[PromptRunBatch, ProjectAccess], Depends(get_batch_access)]


async def _batch_response(session: DBSession, batch: PromptRunBatch) -> BatchResponse:
    item = BatchResponse.model_validate(batch)
    item.usage = await PromptRunRepository(session).usage_for_batch(batch.id)
    return item


@set_router.post(
    "/run",
    response_model=BatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a prompt set against AI providers",
    description=(
        "Creates a batch with one run per active prompt × selected provider/model and "
        "queues them on the ai_search worker queue. Returns immediately; poll the batch."
    ),
    responses={
        **_ERRORS,
        409: {"description": "Prompt set is archived"},
        422: {"description": "Invalid targets or no active prompts"},
    },
)
async def run_prompt_set(
    body: RunPromptSetRequest,
    set_access: SetAccess,
    user: CurrentUser,
    session: DBSession,
    registry: RegistryDep,
    dispatcher: DispatcherDep,
) -> BatchResponse:
    prompt_set, access = set_access
    _require(access, Permission.DATA_MANAGE)
    batch = await ExecutionService(session, registry, dispatcher).run_prompt_set(
        prompt_set,
        providers=body.providers,
        models=body.models,
        priority=body.priority,
        requested_by=user.id,
        prompt_ids=body.prompt_ids,
    )
    return await _batch_response(session, batch)


@set_router.get(
    "/batches",
    response_model=BatchListResponse,
    summary="List a prompt set's batches",
    responses=_ERRORS,
)
async def list_batches(
    set_access: SetAccess,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BatchListResponse:
    prompt_set, access = set_access
    _require(access, Permission.DATA_READ)
    batches, total = await BatchRepository(session).list_for_set(
        prompt_set.id, limit=limit, offset=offset
    )
    return BatchListResponse(items=[BatchResponse.model_validate(b) for b in batches], total=total)


@batch_router.get("", response_model=BatchResponse, summary="Get a batch", responses=_ERRORS)
async def get_batch(batch_access: BatchAccess, session: DBSession) -> BatchResponse:
    batch, access = batch_access
    _require(access, Permission.DATA_READ)
    return await _batch_response(session, batch)


@batch_router.get(
    "/runs",
    response_model=PromptRunListResponse,
    summary="List a batch's runs with responses",
    responses=_ERRORS,
)
async def list_runs(
    batch_access: BatchAccess,
    session: DBSession,
    status_filter: Annotated[PromptRunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromptRunListResponse:
    batch, access = batch_access
    _require(access, Permission.DATA_READ)
    repo = PromptRunRepository(session)
    runs, total = await repo.list_for_batch(
        batch.id, status=status_filter, limit=limit, offset=offset
    )
    responses = await repo.responses_for_runs([r.id for r in runs])
    items = []
    for run in runs:
        item = PromptRunResponse.model_validate(run)
        resp = responses.get(run.id)
        item.response = AiResponseView.model_validate(resp) if resp else None
        items.append(item)
    return PromptRunListResponse(items=items, total=total, limit=limit, offset=offset)


@batch_router.post(
    "/cancel",
    response_model=BatchResponse,
    summary="Cancel a batch",
    description=(
        "Queued runs are cancelled immediately. Runs already inside a provider call finish "
        "and are recorded; the batch ends as `cancelled` once they report back."
    ),
    responses={**_ERRORS, 409: {"description": "Batch already finished"}},
)
async def cancel_batch(
    batch_access: BatchAccess, session: DBSession, registry: RegistryDep, dispatcher: DispatcherDep
) -> BatchResponse:
    batch, access = batch_access
    _require(access, Permission.DATA_MANAGE)
    updated = await ExecutionService(session, registry, dispatcher).cancel(batch)
    return await _batch_response(session, updated)
