"""Agent framework routes (Milestone 6A).

Project-scoped run/list use `require_project_access`; run- and action-scoped
routes derive the project from the row (non-members 404). Running an agent and
deciding actions are DATA_MANAGE; reads are DATA_READ. Execution happens on
the worker — the POST only creates a queued run and dispatches it.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy import select

from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry, get_agent_registry
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
from app.models.agents import AgentAction, AgentRun, AgentRunStatus
from app.schemas.agents import (
    AgentActionView,
    AgentInfo,
    AgentRunListResponse,
    AgentRunRequest,
    AgentRunView,
)
from app.workers.tasks import dispatch_agent_run

project_router = APIRouter(prefix="/projects/{project_id}", tags=["agents"])
run_router = APIRouter(prefix="/agent-runs/{run_id}", tags=["agents"])
action_router = APIRouter(prefix="/agent-actions/{action_id}", tags=["agents"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
    409: {"description": "Invalid state for this operation"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

AgentDispatcher = Callable[[uuid.UUID], None]


def get_agent_dispatcher() -> AgentDispatcher:
    return dispatch_agent_run


def get_registry() -> AgentRegistry:
    return get_agent_registry()


DispatcherDep = Annotated[AgentDispatcher, Depends(get_agent_dispatcher)]
RegistryDep = Annotated[AgentRegistry, Depends(get_registry)]


@project_router.get(
    "/agents", response_model=list[AgentInfo], summary="Registered agents", responses=_ERRORS
)
async def list_agents(access: ReadAccess, registry: RegistryDep) -> list[AgentInfo]:
    return [AgentInfo(**info) for info in registry.describe()]


@project_router.post(
    "/agents/{agent_name}/run",
    response_model=AgentRunView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an agent run (executed on the worker, never in the request)",
    responses=_ERRORS,
)
async def run_agent(
    agent_name: Annotated[str, Path(max_length=100)],
    body: AgentRunRequest,
    access: ManageAccess,
    session: DBSession,
    registry: RegistryDep,
    dispatch: DispatcherDep,
) -> AgentRunView:
    orchestrator = AgentOrchestrator(session, registry=registry)
    run = await orchestrator.create_run(
        access.project, agent_name, objective=body.objective, user_id=access.membership.user_id
    )
    await session.commit()
    dispatch(run.id)
    return AgentRunView.model_validate(run)


@project_router.get(
    "/agent-runs",
    response_model=AgentRunListResponse,
    summary="Agent run history for a project",
    responses=_ERRORS,
)
async def list_agent_runs(
    access: ReadAccess,
    session: DBSession,
    status_filter: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
    agent_name: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentRunListResponse:
    stmt = select(AgentRun).where(AgentRun.project_id == access.project.id)
    if status_filter is not None:
        stmt = stmt.where(AgentRun.status == status_filter.value)
    if agent_name is not None:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    rows = list((await session.scalars(stmt.order_by(AgentRun.created_at.desc()))).all())
    page = rows[offset : offset + limit]
    return AgentRunListResponse(
        items=[AgentRunView.model_validate(r) for r in page],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_run_access(
    session: DBSession, user: CurrentUser, run_id: Annotated[uuid.UUID, Path()]
) -> tuple[AgentRun, ProjectAccess]:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise NotFoundError("Agent run not found")
    access = await get_project_access(session, user, run.project_id)
    return run, access


RunAccess = Annotated[tuple[AgentRun, ProjectAccess], Depends(get_run_access)]


@run_router.get("", response_model=AgentRunView, summary="Get an agent run", responses=_ERRORS)
async def get_agent_run(run_access: RunAccess) -> AgentRunView:
    run, access = run_access
    _require(access, Permission.DATA_READ)
    return AgentRunView.model_validate(run)


@run_router.get(
    "/actions",
    response_model=list[AgentActionView],
    summary="Actions proposed by a run",
    responses=_ERRORS,
)
async def list_run_actions(run_access: RunAccess, session: DBSession) -> list[AgentActionView]:
    run, access = run_access
    _require(access, Permission.DATA_READ)
    rows = (
        await session.scalars(
            select(AgentAction)
            .where(AgentAction.agent_run_id == run.id)
            .order_by(AgentAction.created_at)
        )
    ).all()
    return [AgentActionView.model_validate(r) for r in rows]


@run_router.post(
    "/cancel", response_model=AgentRunView, summary="Cancel a queued/running run", responses=_ERRORS
)
async def cancel_agent_run(run_access: RunAccess, session: DBSession) -> AgentRunView:
    run, access = run_access
    _require(access, Permission.DATA_MANAGE)
    run = await AgentOrchestrator(session).cancel(run)
    await session.commit()
    await session.refresh(run)
    return AgentRunView.model_validate(run)


async def get_action_access(
    session: DBSession, user: CurrentUser, action_id: Annotated[uuid.UUID, Path()]
) -> tuple[AgentAction, AgentRun, ProjectAccess]:
    row = (
        await session.execute(
            select(AgentAction, AgentRun)
            .join(AgentRun, AgentRun.id == AgentAction.agent_run_id)
            .where(AgentAction.id == action_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Agent action not found")
    action, run = row
    access = await get_project_access(session, user, run.project_id)
    return action, run, access


ActionAccess = Annotated[tuple[AgentAction, AgentRun, ProjectAccess], Depends(get_action_access)]


@action_router.post(
    "/approve",
    response_model=AgentActionView,
    summary="Approve a pending action",
    responses=_ERRORS,
)
async def approve_action(action_access: ActionAccess, session: DBSession) -> AgentActionView:
    action, _, access = action_access
    _require(access, Permission.DATA_MANAGE)
    action = await AgentOrchestrator(session).approve_action(action, access.membership.user_id)
    await session.commit()
    await session.refresh(action)
    return AgentActionView.model_validate(action)


@action_router.post(
    "/reject", response_model=AgentActionView, summary="Reject a pending action", responses=_ERRORS
)
async def reject_action(action_access: ActionAccess, session: DBSession) -> AgentActionView:
    action, _, access = action_access
    _require(access, Permission.DATA_MANAGE)
    action = await AgentOrchestrator(session).reject_action(action, access.membership.user_id)
    await session.commit()
    await session.refresh(action)
    return AgentActionView.model_validate(action)
