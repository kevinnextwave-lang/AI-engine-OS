"""Agent workflow orchestration (Milestone 6F).

Runs a fixed chain of agents in sequence:

    research → content-strategy → content-optimization → entity-optimization

No agent gains extra access inside a workflow: every step is an ordinary agent
run through the same orchestrator, context builder and tool registry. Steps
receive only the previous steps' output *summaries* (`workflow_input`), never
raw data-store access, and no action executes automatically.

Approval gates: whenever a step's run ends `awaiting_approval` (it proposed
content, entity or external changes), the workflow stops in
`awaiting_approval` and only continues after every pending action of that run
is explicitly approved or rejected and the user resumes. `pause` / `resume` /
`cancel` work at any point between steps; a pause or cancel issued while a
step is executing takes effect before the next step starts.

After the final step the orchestrator builds the consolidated action plan:
one prioritized list across all steps with priority, action, reason,
evidence, expected impact area, effort and confidence per item.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator
from app.agents.registry import AgentRegistry, get_agent_registry
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.agents import ActionStatus, AgentAction, AgentRun, AgentRunStatus
from app.models.project import Project
from app.models.workflows import (
    AgentWorkflow,
    AgentWorkflowStep,
    WorkflowStatus,
    WorkflowStepStatus,
)

log = get_logger(__name__)

WORKFLOW_DEFINITIONS: dict[str, list[str]] = {
    "full_optimization": [
        "research",
        "content-strategy",
        "content-optimization",
        "entity-optimization",
    ],
}

# Consolidated-plan metadata per agent.
IMPACT_AREA = {
    "research": "AI visibility",
    "content-strategy": "content coverage",
    "content-optimization": "existing content",
    "entity-optimization": "entity clarity",
}
EFFORT_BY_ACTION = {
    "investigate_citation_opportunity": "low",
    "review_content_brief": "medium",
    "create_content_brief": "medium",
    "create_comparison_page": "high",
    "optimize_existing_page": "medium",
    "add_supporting_evidence": "medium",
    "improve_organization_entity": "low",
    "review_content_optimization": "medium",
    "review_entity_optimization": "low",
}
CANCELLABLE = {
    WorkflowStatus.QUEUED.value,
    WorkflowStatus.RUNNING.value,
    WorkflowStatus.PAUSED.value,
    WorkflowStatus.AWAITING_APPROVAL.value,
}


@dataclass
class WorkflowAdvanceResult:
    workflow_id: uuid.UUID
    status: str
    steps_executed: int


class WorkflowOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: AgentRegistry | None = None,
        definitions: dict[str, list[str]] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or get_agent_registry()
        self._definitions = definitions or WORKFLOW_DEFINITIONS
        self._now = now or datetime.now(UTC)

    # -- lifecycle ---------------------------------------------------------------------

    async def create(
        self,
        project: Project,
        *,
        workflow_type: str,
        objective: str,
        user_id: uuid.UUID | None,
    ) -> AgentWorkflow:
        chain = self._definitions.get(workflow_type)
        if chain is None:
            raise ValidationAppError(f"Unknown workflow type '{workflow_type}'")
        missing = [name for name in chain if self._registry.get(name) is None]
        if missing:
            raise ValidationAppError(f"Workflow agents not registered: {', '.join(missing)}")
        workflow = AgentWorkflow(
            project_id=project.id,
            workflow_type=workflow_type,
            status=WorkflowStatus.QUEUED.value,
            current_step=1,
            objective=objective,
            requested_by_user_id=user_id,
        )
        self._session.add(workflow)
        await self._session.flush()
        for i, agent_name in enumerate(chain, start=1):
            self._session.add(
                AgentWorkflowStep(workflow_id=workflow.id, agent_name=agent_name, sequence=i)
            )
        await self._session.flush()
        return workflow

    async def advance(self, workflow_id: uuid.UUID) -> WorkflowAdvanceResult:
        """Execute steps sequentially until done, held, or stopped. Worker entry."""
        workflow = await self._session.get(AgentWorkflow, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found")
        executed = 0
        while True:
            # a pause/cancel committed elsewhere takes effect before the next step
            await self._session.refresh(workflow)
            if workflow.status == WorkflowStatus.QUEUED.value:
                workflow.status = WorkflowStatus.RUNNING.value
                await self._session.flush()
            if workflow.status != WorkflowStatus.RUNNING.value:
                break
            step = await self._next_pending_step(workflow)
            if step is None:
                await self._finish(workflow)
                break
            held = await self._execute_step(workflow, step)
            executed += 1
            if held:
                break
        return WorkflowAdvanceResult(workflow.id, workflow.status, executed)

    async def _next_pending_step(self, workflow: AgentWorkflow) -> AgentWorkflowStep | None:
        return (
            await self._session.scalars(
                select(AgentWorkflowStep)
                .where(
                    AgentWorkflowStep.workflow_id == workflow.id,
                    AgentWorkflowStep.status == WorkflowStepStatus.PENDING.value,
                )
                .order_by(AgentWorkflowStep.sequence)
                .limit(1)
            )
        ).one_or_none()

    async def _execute_step(self, workflow: AgentWorkflow, step: AgentWorkflowStep) -> bool:
        """Run one step. Returns True when the workflow must hold (approval/failure)."""
        project = await self._session.get(Project, workflow.project_id)
        if project is None:
            workflow.status = WorkflowStatus.FAILED.value
            workflow.error_message = "Project no longer exists"
            return True
        workflow.current_step = step.sequence
        step.status = WorkflowStepStatus.RUNNING.value
        step.input_context = await self._input_for(workflow, step)
        await self._session.flush()

        orchestrator = AgentOrchestrator(self._session, registry=self._registry)
        run = await orchestrator.create_run(
            project,
            step.agent_name,
            objective=workflow.objective or f"Workflow step {step.sequence}",
            user_id=workflow.requested_by_user_id,
        )
        step.agent_run_id = run.id
        await self._session.flush()
        run = await orchestrator.execute(run.id, workflow_input=step.input_context)

        if run.status == AgentRunStatus.FAILED.value:
            step.status = WorkflowStepStatus.FAILED.value
            step.output_summary = {"error": run.error_message}
            workflow.status = WorkflowStatus.FAILED.value
            workflow.error_message = (
                f"Step {step.sequence} ({step.agent_name}) failed: {run.error_message}"
            )
            await self._session.flush()
            return True
        step.status = WorkflowStepStatus.COMPLETED.value
        step.output_summary = self._summarize(run)
        await self._session.flush()
        if run.status == AgentRunStatus.AWAITING_APPROVAL.value:
            workflow.status = WorkflowStatus.AWAITING_APPROVAL.value
            workflow.hold_reason = (
                f"Step {step.sequence} ({step.agent_name}) proposed changes that require "
                "explicit approval. Approve or reject its actions, then resume."
            )
            await self._session.flush()
            return True
        return False

    @staticmethod
    def _summarize(run: AgentRun) -> dict[str, Any]:
        result = run.result or {}
        return {
            "agent_name": run.agent_name,
            "run_id": str(run.id),
            "run_status": run.status,
            "summary": result.get("summary"),
            "finding_titles": [f.get("title") for f in (result.get("findings") or [])][:10],
            "findings": len(result.get("findings") or []),
            "proposed_actions": len(result.get("proposed_actions") or []),
            "confidence": result.get("confidence"),
            "warnings": (result.get("warnings") or [])[:5],
        }

    async def _input_for(self, workflow: AgentWorkflow, step: AgentWorkflowStep) -> dict[str, Any]:
        """What this step receives: the objective plus prior steps' output
        summaries — including which of their proposed actions were approved."""
        prior = (
            await self._session.scalars(
                select(AgentWorkflowStep)
                .where(
                    AgentWorkflowStep.workflow_id == workflow.id,
                    AgentWorkflowStep.sequence < step.sequence,
                    AgentWorkflowStep.status == WorkflowStepStatus.COMPLETED.value,
                )
                .order_by(AgentWorkflowStep.sequence)
            )
        ).all()
        previous_steps = []
        for p in prior:
            entry = dict(p.output_summary or {})
            if p.agent_run_id is not None:
                actions = (
                    await self._session.scalars(
                        select(AgentAction).where(AgentAction.agent_run_id == p.agent_run_id)
                    )
                ).all()
                entry["approved_actions"] = [
                    {"action_type": a.action_type, "description": a.description}
                    for a in actions
                    if a.status == ActionStatus.APPROVED.value
                ][:10]
                entry["rejected_actions"] = sum(
                    1 for a in actions if a.status == ActionStatus.REJECTED.value
                )
            previous_steps.append(entry)
        return {
            "workflow_id": str(workflow.id),
            "workflow_type": workflow.workflow_type,
            "objective": workflow.objective,
            "step": step.sequence,
            "previous_steps": previous_steps,
        }

    # -- controls ----------------------------------------------------------------------

    async def pause(self, workflow: AgentWorkflow) -> AgentWorkflow:
        if workflow.status not in (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value):
            raise ConflictError(f"Workflow is {workflow.status}; only queued/running pause")
        workflow.status = WorkflowStatus.PAUSED.value
        workflow.hold_reason = "Paused by user."
        await self._session.flush()
        return workflow

    async def resume(self, workflow: AgentWorkflow) -> AgentWorkflow:
        """paused → running; awaiting_approval → running only after every pending
        action of the held step has been explicitly approved or rejected."""
        if workflow.status not in (
            WorkflowStatus.PAUSED.value,
            WorkflowStatus.AWAITING_APPROVAL.value,
        ):
            raise ConflictError(
                f"Workflow is {workflow.status}; only paused or awaiting_approval resume"
            )
        if workflow.status == WorkflowStatus.AWAITING_APPROVAL.value:
            pending = await self._pending_actions(workflow)
            if pending:
                raise ConflictError(
                    f"{pending} proposed action(s) still await an explicit decision; "
                    "approve or reject them before resuming"
                )
        if await self._next_pending_step(workflow) is None:
            await self._finish(workflow)
            return workflow
        workflow.status = WorkflowStatus.QUEUED.value
        workflow.hold_reason = None
        await self._session.flush()
        return workflow

    async def cancel(self, workflow: AgentWorkflow) -> AgentWorkflow:
        if workflow.status not in CANCELLABLE:
            raise ConflictError(f"Workflow is {workflow.status}; it cannot be cancelled")
        workflow.status = WorkflowStatus.CANCELLED.value
        workflow.hold_reason = None
        for step in await self._session.scalars(
            select(AgentWorkflowStep).where(
                AgentWorkflowStep.workflow_id == workflow.id,
                AgentWorkflowStep.status.in_(
                    [WorkflowStepStatus.PENDING.value, WorkflowStepStatus.RUNNING.value]
                ),
            )
        ):
            step.status = WorkflowStepStatus.CANCELLED.value
        await self._session.flush()
        return workflow

    async def _pending_actions(self, workflow: AgentWorkflow) -> int:
        run_ids = [
            s.agent_run_id
            for s in (
                await self._session.scalars(
                    select(AgentWorkflowStep).where(
                        AgentWorkflowStep.workflow_id == workflow.id,
                        AgentWorkflowStep.agent_run_id.is_not(None),
                    )
                )
            ).all()
        ]
        if not run_ids:
            return 0
        rows = (
            await self._session.scalars(
                select(AgentAction).where(
                    AgentAction.agent_run_id.in_(run_ids),
                    AgentAction.status == ActionStatus.PENDING.value,
                )
            )
        ).all()
        return len(rows)

    # -- consolidated plan -------------------------------------------------------------

    async def _finish(self, workflow: AgentWorkflow) -> None:
        workflow.action_plan = await self._build_plan(workflow)
        pending = await self._pending_actions(workflow)
        if pending:
            workflow.status = WorkflowStatus.AWAITING_APPROVAL.value
            workflow.hold_reason = (
                f"The consolidated plan is ready; {pending} proposed action(s) still "
                "require an explicit decision."
            )
        else:
            workflow.status = WorkflowStatus.COMPLETED.value
            workflow.hold_reason = None
        await self._session.flush()
        log.info(
            "agent_workflow_finished",
            workflow_id=str(workflow.id),
            status=workflow.status,
            plan_items=len(workflow.action_plan or []),
        )

    async def _build_plan(self, workflow: AgentWorkflow) -> list[dict[str, Any]]:
        """One prioritized list across every step's proposed (non-rejected) actions."""
        steps = (
            await self._session.scalars(
                select(AgentWorkflowStep)
                .where(
                    AgentWorkflowStep.workflow_id == workflow.id,
                    AgentWorkflowStep.agent_run_id.is_not(None),
                )
                .order_by(AgentWorkflowStep.sequence)
            )
        ).all()
        items: list[dict[str, Any]] = []
        for step in steps:
            run = await self._session.get(AgentRun, step.agent_run_id)
            if run is None:
                continue
            confidence = (run.result or {}).get("confidence")
            actions = (
                await self._session.scalars(
                    select(AgentAction)
                    .where(AgentAction.agent_run_id == run.id)
                    .order_by(AgentAction.created_at)
                )
            ).all()
            for action in actions:
                if action.status == ActionStatus.REJECTED.value:
                    continue
                risk_rank = {"high": 0, "medium": 1, "low": 2}.get(action.risk_level, 3)
                items.append(
                    {
                        "action": action.description,
                        "action_type": action.action_type,
                        "reason": (
                            f"Proposed by the {step.agent_name} agent "
                            f"(step {step.sequence}) from observed project data."
                        ),
                        "evidence": action.payload,
                        "expected_impact_area": IMPACT_AREA.get(
                            step.agent_name, "ai search presence"
                        ),
                        "effort": EFFORT_BY_ACTION.get(action.action_type, "medium"),
                        "confidence": confidence,
                        "approval_status": action.status,
                        "agent": step.agent_name,
                        "step": step.sequence,
                        "_rank": (risk_rank, step.sequence),
                    }
                )
        items.sort(key=lambda i: i.pop("_rank"))
        for n, item in enumerate(items, start=1):
            item["priority"] = n
        return items
