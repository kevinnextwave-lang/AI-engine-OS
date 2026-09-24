"""Agent workflow routes (Milestone 6F).

Creating a workflow queues it and dispatches the worker — execution never
happens inside API requests. Pause/resume/cancel act between steps; resume
from awaiting_approval requires every pending proposed action to have been
explicitly approved or rejected first.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.registry import AgentRegistry
from app.agents.workflow import WorkflowOrchestrator
from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.agents import get_registry
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.models.workflows import AgentWorkflow, WorkflowStatus, WorkflowStepStatus
from app.schemas.workflows import (
    WorkflowCreateRequest,
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowView,
)
from app.workers.tasks import dispatch_agent_workflow

log = get_logger(__name__)

project_router = APIRouter(prefix="/projects/{project_id}/agent-workflows", tags=["workflows"])
workflow_router = APIRouter(prefix="/agent-workflows/{workflow_id}", tags=["workflows"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
    409: {"description": "Invalid state for this operation"},
    422: {"description": "Unknown workflow type"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

WorkflowDispatcher = Callable[[uuid.UUID], None]


def get_workflow_dispatcher() -> WorkflowDispatcher:
    return dispatch_agent_workflow


DispatcherDep = Annotated[WorkflowDispatcher, Depends(get_workflow_dispatcher)]
RegistryDep = Annotated[AgentRegistry, Depends(get_registry)]


async def _loaded(session: DBSession, workflow_id: uuid.UUID) -> AgentWorkflow | None:
    return (
        await session.scalars(
            select(AgentWorkflow)
            .options(selectinload(AgentWorkflow.steps))
            .where(AgentWorkflow.id == workflow_id)
        )
    ).one_or_none()


@project_router.post(
    "",
    response_model=WorkflowView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an agent workflow (executed on the worker)",
    responses=_ERRORS,
)
async def create_workflow(
    body: WorkflowCreateRequest,
    access: ManageAccess,
    session: DBSession,
    registry: RegistryDep,
    dispatch: DispatcherDep,
) -> WorkflowView:
    orchestrator = WorkflowOrchestrator(session, registry=registry)
    workflow = await orchestrator.create(
        access.project,
        workflow_type=body.workflow_type,
        objective=body.objective,
        user_id=access.membership.user_id,
    )
    await session.commit()
    try:
        dispatch(workflow.id)
    except Exception:  # noqa: BLE001 - broker outage must not strand the workflow as "queued"
        log.exception("workflow_dispatch_failed", workflow_id=str(workflow.id))
        workflow.status = WorkflowStatus.FAILED.value
        await session.commit()
    loaded = await _loaded(session, workflow.id)
    return WorkflowView.model_validate(loaded)


@project_router.get(
    "",
    response_model=WorkflowListResponse,
    summary="Workflows for a project",
    responses=_ERRORS,
)
async def list_workflows(
    access: ReadAccess,
    session: DBSession,
    status_filter: Annotated[WorkflowStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowListResponse:
    stmt = (
        select(AgentWorkflow)
        .options(selectinload(AgentWorkflow.steps))
        .where(AgentWorkflow.project_id == access.project.id)
    )
    if status_filter is not None:
        stmt = stmt.where(AgentWorkflow.status == status_filter.value)
    rows = list((await session.scalars(stmt.order_by(AgentWorkflow.created_at.desc()))).all())
    page = rows[offset : offset + limit]
    return WorkflowListResponse(
        items=[
            WorkflowListItem(
                id=w.id,
                workflow_type=w.workflow_type,
                status=WorkflowStatus(w.status),
                current_step=w.current_step,
                objective=w.objective,
                steps_total=len(w.steps),
                steps_completed=sum(
                    1 for s in w.steps if s.status == WorkflowStepStatus.COMPLETED.value
                ),
                created_at=w.created_at,
            )
            for w in page
        ],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_workflow_access(
    session: DBSession, user: CurrentUser, workflow_id: Annotated[uuid.UUID, Path()]
) -> tuple[AgentWorkflow, ProjectAccess]:
    workflow = await _loaded(session, workflow_id)
    if workflow is None:
        raise NotFoundError("Workflow not found")
    access = await get_project_access(session, user, workflow.project_id)
    return workflow, access


WorkflowAccess = Annotated[tuple[AgentWorkflow, ProjectAccess], Depends(get_workflow_access)]


@workflow_router.get("", response_model=WorkflowView, summary="Get a workflow", responses=_ERRORS)
async def get_workflow(workflow_access: WorkflowAccess) -> WorkflowView:
    workflow, access = workflow_access
    _require(access, Permission.DATA_READ)
    return WorkflowView.model_validate(workflow)


@workflow_router.post(
    "/pause", response_model=WorkflowView, summary="Pause a workflow", responses=_ERRORS
)
async def pause_workflow(workflow_access: WorkflowAccess, session: DBSession) -> WorkflowView:
    workflow, access = workflow_access
    _require(access, Permission.DATA_MANAGE)
    await WorkflowOrchestrator(session).pause(workflow)
    await session.commit()
    return WorkflowView.model_validate(await _loaded(session, workflow.id))


@workflow_router.post(
    "/resume",
    response_model=WorkflowView,
    summary="Resume a paused or approval-held workflow",
    responses=_ERRORS,
)
async def resume_workflow(
    workflow_access: WorkflowAccess, session: DBSession, dispatch: DispatcherDep
) -> WorkflowView:
    workflow, access = workflow_access
    _require(access, Permission.DATA_MANAGE)
    workflow = await WorkflowOrchestrator(session).resume(workflow)
    await session.commit()
    if workflow.status == WorkflowStatus.QUEUED.value:
        try:
            dispatch(workflow.id)
        except Exception:  # noqa: BLE001 - broker outage must not strand the workflow as "queued"
            log.exception("workflow_dispatch_failed", workflow_id=str(workflow.id))
            workflow.status = WorkflowStatus.FAILED.value
            await session.commit()
    return WorkflowView.model_validate(await _loaded(session, workflow.id))


@workflow_router.post(
    "/cancel", response_model=WorkflowView, summary="Cancel a workflow", responses=_ERRORS
)
async def cancel_workflow(workflow_access: WorkflowAccess, session: DBSession) -> WorkflowView:
    workflow, access = workflow_access
    _require(access, Permission.DATA_MANAGE)
    await WorkflowOrchestrator(session).cancel(workflow)
    await session.commit()
    return WorkflowView.model_validate(await _loaded(session, workflow.id))
