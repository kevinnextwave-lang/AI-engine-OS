"""Milestone 6F — Agent workflow orchestration."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.agents.context import AgentContext
from app.agents.registry import AgentRegistry
from app.agents.results import AgentResult, AgentStatus, ProposedAction
from app.agents.workflow import WorkflowOrchestrator
from app.api.v1.routes.agents import get_registry
from app.api.v1.routes.workflows import get_workflow_dispatcher
from app.core.errors import ConflictError, ValidationAppError
from app.models.agents import ActionRiskLevel, AgentAction
from app.models.project import Project
from app.models.user import User
from app.models.workflows import AgentWorkflow
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import project_with_competitors

pytestmark = pytest.mark.anyio


class StepAgent(Agent):
    """Configurable chain agent: records what it received, optionally proposes
    an approval-gated action or fails."""

    version = "1.0"

    def __init__(self, name: str, *, propose: bool = False, fail: bool = False) -> None:
        self.name = name
        self.propose = propose
        self.fail = fail
        self.received: list[dict | None] = []

    async def run(self, context: AgentContext) -> AgentResult:
        self.received.append(context.workflow_input)
        if self.fail:
            raise RuntimeError(f"{self.name} exploded")
        result = AgentResult(
            agent_name=self.name,
            agent_version=self.version,
            status=AgentStatus.COMPLETED,
            summary=f"{self.name} finished",
            findings=[{"title": f"{self.name} finding"}],
            confidence=0.9,
        )
        if self.propose:
            result.proposed_actions = [
                ProposedAction(
                    action_type=f"{self.name}_change",
                    description=f"{self.name} proposes a content change",
                    payload={"agent": self.name},
                    risk_level=ActionRiskLevel.MEDIUM,
                    approval_required=True,
                )
            ]
        return result


def _chain(*agents: Agent) -> tuple[AgentRegistry, dict[str, list[str]]]:
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    return reg, {"test_chain": [a.name for a in agents]}


async def _project(client: AsyncClient, db_session: AsyncSession) -> tuple[dict, str, Project]:
    h, _, pid = await project_with_competitors(client)
    project = await db_session.get(Project, uuid.UUID(pid))
    assert project is not None
    return h, pid, project


async def _create(
    db_session: AsyncSession,
    project: Project,
    reg: AgentRegistry,
    defs: dict[str, list[str]],
) -> tuple[WorkflowOrchestrator, AgentWorkflow]:
    orch = WorkflowOrchestrator(db_session, registry=reg, definitions=defs)
    wf = await orch.create(
        project, workflow_type="test_chain", objective="chain things", user_id=None
    )
    return orch, wf


async def _steps(db_session: AsyncSession, wf: AgentWorkflow) -> list:
    from app.models.workflows import AgentWorkflowStep

    return list(
        (
            await db_session.scalars(
                select(AgentWorkflowStep)
                .where(AgentWorkflowStep.workflow_id == wf.id)
                .order_by(AgentWorkflowStep.sequence)
            )
        ).all()
    )


# --- sequential execution & context passing --------------------------------------------


async def test_sequential_execution_and_context_passing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b, c = StepAgent("step-a"), StepAgent("step-b"), StepAgent("step-c")
    reg, defs = _chain(a, b, c)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    steps = await _steps(db_session, wf)
    assert [s.agent_name for s in steps] == ["step-a", "step-b", "step-c"]
    result = await orch.advance(wf.id)
    assert result.status == "completed" and result.steps_executed == 3
    await db_session.refresh(wf)
    steps = await _steps(db_session, wf)
    assert [s.status for s in steps] == ["completed"] * 3
    assert wf.current_step == 3
    # each agent ran exactly once, in order, with the prior steps' summaries
    assert a.received[0]["previous_steps"] == []
    assert [p["agent_name"] for p in b.received[0]["previous_steps"]] == ["step-a"]
    assert [p["agent_name"] for p in c.received[0]["previous_steps"]] == ["step-a", "step-b"]
    assert b.received[0]["previous_steps"][0]["finding_titles"] == ["step-a finding"]
    assert b.received[0]["objective"] == "chain things"
    # the stored step rows mirror what was passed and produced
    assert steps[1].input_context["previous_steps"][0]["summary"] == "step-a finished"
    assert steps[2].output_summary["findings"] == 1
    assert steps[0].agent_run_id is not None
    # no approvals were needed → completed with an (empty) plan
    assert wf.action_plan == [] and wf.hold_reason is None


# --- failures --------------------------------------------------------------------------


async def test_step_failure_fails_workflow(client: AsyncClient, db_session: AsyncSession) -> None:
    a, boom, c = StepAgent("step-a"), StepAgent("step-boom", fail=True), StepAgent("step-c")
    reg, defs = _chain(a, boom, c)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    result = await orch.advance(wf.id)
    assert result.status == "failed"
    await db_session.refresh(wf)
    assert wf.status == "failed" and "step-boom" in (wf.error_message or "")
    steps = await _steps(db_session, wf)
    statuses = {s.agent_name: s.status for s in steps}
    assert statuses == {"step-a": "completed", "step-boom": "failed", "step-c": "pending"}
    assert steps[1].output_summary["error"]
    assert c.received == []  # later steps never ran


# --- approval gates --------------------------------------------------------------------


async def test_approval_gate_and_resume(client: AsyncClient, db_session: AsyncSession) -> None:
    a = StepAgent("step-a", propose=True)  # proposes a content change → gate
    b = StepAgent("step-b")
    reg, defs = _chain(a, b)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    result = await orch.advance(wf.id)
    assert result.status == "awaiting_approval" and result.steps_executed == 1
    await db_session.refresh(wf)
    assert "require" in (wf.hold_reason or "") and b.received == []

    # resume is refused while the proposed action is undecided
    with pytest.raises(ConflictError, match="approve or reject"):
        await orch.resume(wf)

    steps = await _steps(db_session, wf)
    action = (
        await db_session.scalars(
            select(AgentAction).where(AgentAction.agent_run_id == steps[0].agent_run_id)
        )
    ).one()
    from app.agents.orchestrator import AgentOrchestrator

    user_id = (await db_session.scalars(select(User.id).limit(1))).one()
    await AgentOrchestrator(db_session).approve_action(action, user_id)
    wf = await orch.resume(wf)
    assert wf.status == "queued"  # re-dispatched
    result = await orch.advance(wf.id)
    assert result.status == "completed"
    # step 2 saw step 1's APPROVED action in its input context
    assert b.received[0]["previous_steps"][0]["approved_actions"] == [
        {"action_type": "step-a_change", "description": "step-a proposes a content change"}
    ]
    await db_session.refresh(wf)
    # consolidated plan includes the approved item with all required fields
    assert len(wf.action_plan) == 1
    item = wf.action_plan[0]
    assert set(item) >= {
        "priority",
        "action",
        "reason",
        "evidence",
        "expected_impact_area",
        "effort",
        "confidence",
        "approval_status",
    }
    assert item["priority"] == 1 and item["approval_status"] == "approved"


async def test_rejected_actions_leave_plan_and_complete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = StepAgent("step-a", propose=True)
    reg, defs = _chain(a)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    await orch.advance(wf.id)
    steps = await _steps(db_session, wf)
    action = (
        await db_session.scalars(
            select(AgentAction).where(AgentAction.agent_run_id == steps[0].agent_run_id)
        )
    ).one()
    from app.agents.orchestrator import AgentOrchestrator

    user_id = (await db_session.scalars(select(User.id).limit(1))).one()
    await AgentOrchestrator(db_session).reject_action(action, user_id)
    wf = await orch.resume(wf)  # no pending steps left → finishes directly
    assert wf.status == "completed"
    assert wf.action_plan == []  # rejected actions never reach the plan


# --- pause / resume --------------------------------------------------------------------


async def test_pause_between_steps_and_resume(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    paused_after_first: list[bool] = []

    class PausingAgent(StepAgent):
        """Simulates a user pausing while step 1 executes."""

        def __init__(self, name: str, orch_ref: list) -> None:
            super().__init__(name)
            self.orch_ref = orch_ref

        async def run(self, context: AgentContext) -> AgentResult:
            result = await super().run(context)
            orch, wf = self.orch_ref[0]
            await orch.pause(wf)
            paused_after_first.append(True)
            return result

    ref: list = []
    a = PausingAgent("step-a", ref)
    b = StepAgent("step-b")
    reg, defs = _chain(a, b)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    ref.append((orch, wf))
    result = await orch.advance(wf.id)
    # the pause took effect after step 1 completed, before step 2 started
    assert result.status == "paused" and result.steps_executed == 1
    assert b.received == []
    await db_session.refresh(wf)
    steps = await _steps(db_session, wf)
    assert steps[0].status == "completed" and steps[1].status == "pending"

    wf = await orch.resume(wf)
    assert wf.status == "queued"
    result = await orch.advance(wf.id)
    assert result.status == "completed"
    assert len(b.received) == 1

    with pytest.raises(ConflictError):  # completed workflows do not pause
        await orch.pause(wf)


# --- cancellation ----------------------------------------------------------------------


async def test_workflow_cancellation(client: AsyncClient, db_session: AsyncSession) -> None:
    a, b = StepAgent("step-a"), StepAgent("step-b")
    reg, defs = _chain(a, b)
    _, _, project = await _project(client, db_session)
    orch, wf = await _create(db_session, project, reg, defs)
    await orch.cancel(wf)
    assert wf.status == "cancelled"
    assert all(s.status == "cancelled" for s in await _steps(db_session, wf))
    result = await orch.advance(wf.id)  # the worker refuses to run it
    assert result.status == "cancelled" and result.steps_executed == 0
    assert a.received == []
    with pytest.raises(ConflictError):
        await orch.cancel(wf)


async def test_unknown_workflow_type(client: AsyncClient, db_session: AsyncSession) -> None:
    reg, defs = _chain(StepAgent("step-a"))
    _, _, project = await _project(client, db_session)
    orch = WorkflowOrchestrator(db_session, registry=reg, definitions=defs)
    with pytest.raises(ValidationAppError, match="Unknown workflow type"):
        await orch.create(project, workflow_type="nope", objective="x", user_id=None)
    with pytest.raises(ValidationAppError, match="not registered"):
        await WorkflowOrchestrator(
            db_session, registry=reg, definitions={"bad": ["ghost-agent"]}
        ).create(project, workflow_type="bad", objective="x", user_id=None)


# --- the real 4-agent chain over the API -----------------------------------------------


async def test_full_optimization_chain_via_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, project = await _project(client, db_session)
    app = client._transport.app  # type: ignore[attr-defined]
    from app.agents.registry import get_agent_registry

    calls: list[uuid.UUID] = []
    app.dependency_overrides[get_registry] = get_agent_registry
    app.dependency_overrides[get_workflow_dispatcher] = lambda: calls.append
    r = await client.post(
        f"/api/v1/projects/{pid}/agent-workflows",
        json={"workflow_type": "full_optimization", "objective": "improve AI visibility"},
        headers=h,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    wf_id = uuid.UUID(body["id"])
    assert body["status"] == "queued" and calls == [wf_id]
    assert [s["agent_name"] for s in body["steps"]] == [
        "research",
        "content-strategy",
        "content-optimization",
        "entity-optimization",
    ]
    # execute like the worker would (empty project: agents complete without holds)
    result = await WorkflowOrchestrator(db_session).advance(wf_id)
    assert result.status in ("completed", "awaiting_approval")
    got = (await client.get(f"/api/v1/agent-workflows/{wf_id}", headers=h)).json()
    assert got["status"] == result.status
    assert all(s["status"] == "completed" for s in got["steps"])
    assert got["action_plan"] is not None
    listing = (await client.get(f"/api/v1/projects/{pid}/agent-workflows", headers=h)).json()
    assert listing["total"] == 1 and listing["items"][0]["steps_completed"] == 4
    # invalid type via API → 422
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/agent-workflows",
            json={"workflow_type": "nope", "objective": "x"},
            headers=h,
        )
    ).status_code == 422


# --- tenant isolation ------------------------------------------------------------------


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, project = await _project(client, db_session)
    app = client._transport.app  # type: ignore[attr-defined]
    from app.agents.registry import get_agent_registry

    app.dependency_overrides[get_registry] = get_agent_registry
    app.dependency_overrides[get_workflow_dispatcher] = lambda: lambda _id: None
    wf_id = (
        await client.post(
            f"/api/v1/projects/{pid}/agent-workflows",
            json={"objective": "authz check"},
            headers=h,
        )
    ).json()["id"]

    other = await signup(client, org="Workflow Other Org")
    oh = auth_header(other["access_token"])
    for method, path in (
        ("post", f"/api/v1/projects/{pid}/agent-workflows"),
        ("get", f"/api/v1/projects/{pid}/agent-workflows"),
        ("get", f"/api/v1/agent-workflows/{wf_id}"),
        ("post", f"/api/v1/agent-workflows/{wf_id}/pause"),
        ("post", f"/api/v1/agent-workflows/{wf_id}/resume"),
        ("post", f"/api/v1/agent-workflows/{wf_id}/cancel"),
    ):
        kwargs = (
            {"json": {"objective": "steal"}}
            if path.endswith("agent-workflows") and method == "post"
            else {}
        )
        resp = await getattr(client, method)(path, headers=oh, **kwargs)
        assert resp.status_code == 404, path
    assert (await client.get(f"/api/v1/projects/{pid}/agent-workflows")).status_code == 401
