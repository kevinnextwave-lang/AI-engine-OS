"""Agent orchestrator: run lifecycle, approval workflow, execution history.

    Agent Request → Orchestrator → Agent → Tools → Knowledge
                  → Structured Result → Approval → (future) Action

The orchestrator owns the `agent_runs` / `agent_actions` rows. Agents return
`AgentResult`s; they never touch persistence, approvals or external systems.
Approval rules are enforced HERE and cannot be bypassed by an agent:

* any proposed action with medium/high risk is forced to `approval_required`;
* `approval_required` actions start `pending`; only `approve_action` /
  `reject_action` (with the acting user recorded) move them on;
* a run with pending actions is `awaiting_approval`; once every action is
  resolved it becomes `completed`;
* execution of approved actions is NOT implemented in 6A — `executed_at` /
  `execution_result` stay empty.
"""

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BudgetExceededError
from app.agents.context import build_context
from app.agents.registry import AgentRegistry, get_agent_registry
from app.agents.results import AgentResult, AgentStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.agents import (
    ActionRiskLevel,
    ActionStatus,
    AgentAction,
    AgentRun,
    AgentRunStatus,
)
from app.models.project import Project

log = get_logger(__name__)

CANCELLABLE = {AgentRunStatus.QUEUED.value, AgentRunStatus.RUNNING.value}


class AgentOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: AgentRegistry | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or get_agent_registry()
        self._now = now or datetime.now(UTC)

    # -- lifecycle ---------------------------------------------------------------------

    async def create_run(
        self,
        project: Project,
        agent_name: str,
        *,
        objective: str,
        user_id: uuid.UUID | None,
    ) -> AgentRun:
        agent = self._registry.get(agent_name)
        if agent is None:
            raise NotFoundError(f"Unknown agent '{agent_name}'")
        run = AgentRun(
            project_id=project.id,
            agent_name=agent.name,
            agent_version=agent.version,
            status=AgentRunStatus.QUEUED.value,
            objective=objective,
            requested_by_user_id=user_id,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def execute(self, run_id: uuid.UUID) -> AgentRun:
        """Run one queued agent run to completion. Called from the worker."""
        run = await self._session.get(AgentRun, run_id)
        if run is None:
            raise NotFoundError("Agent run not found")
        if run.status == AgentRunStatus.CANCELLED.value:
            return run  # cancelled while queued: never execute
        if run.status != AgentRunStatus.QUEUED.value:
            return run
        agent = self._registry.get(run.agent_name)
        if agent is None:
            return await self._fail(run, f"Agent '{run.agent_name}' is no longer registered")
        project = await self._session.get(Project, run.project_id)
        if project is None:
            return await self._fail(run, "Project no longer exists")

        run.status = AgentRunStatus.RUNNING.value
        run.started_at = self._now
        await self._session.flush()
        started = time.monotonic()
        try:
            context = await build_context(
                self._session,
                project,
                objective=run.objective,
                user_id=run.requested_by_user_id,
                spec=agent.context_spec,
            )
            result = await agent.run(context)
        except BudgetExceededError as exc:
            return await self._fail(run, f"Budget exceeded: {exc}", started)
        except Exception as exc:  # noqa: BLE001 - one run must never kill the worker
            log.error("agent_run_failed", run_id=str(run.id), error=str(exc))
            return await self._fail(run, str(exc)[:2000], started)
        # a cancellation issued while the agent was running wins over its result
        await self._session.refresh(run, attribute_names=["status"])
        if run.status == AgentRunStatus.CANCELLED.value:
            return run
        tool_usage = [
            {"tool": c.tool, "params": c.params, "items": c.items}
            for c in (context.tools.usage if context.tools else [])
        ]
        return await self._record_result(
            run, result, started, context_summary=context.summary(), tool_usage=tool_usage
        )

    async def _fail(self, run: AgentRun, message: str, started: float | None = None) -> AgentRun:
        run.status = AgentRunStatus.FAILED.value
        run.error_message = message
        run.completed_at = self._now
        if started is not None:
            run.execution_time_ms = int((time.monotonic() - started) * 1000)
        await self._session.flush()
        return run

    async def _record_result(
        self,
        run: AgentRun,
        result: AgentResult,
        started: float,
        *,
        context_summary: dict[str, int],
        tool_usage: list[dict[str, object]],
    ) -> AgentRun:
        elapsed_ms = result.execution_time_ms or int((time.monotonic() - started) * 1000)
        pending = 0
        for proposed in result.proposed_actions:
            # Approval rules are the orchestrator's, not the agent's: anything
            # beyond low risk requires approval no matter what the agent set.
            approval_required = (
                proposed.approval_required or proposed.risk_level is not ActionRiskLevel.LOW
            )
            status = ActionStatus.PENDING if approval_required else ActionStatus.APPROVED
            if status is ActionStatus.PENDING:
                pending += 1
            self._session.add(
                AgentAction(
                    agent_run_id=run.id,
                    action_type=proposed.action_type,
                    description=proposed.description,
                    payload=proposed.payload,
                    risk_level=proposed.risk_level.value,
                    approval_required=approval_required,
                    status=status.value,
                )
            )
        if result.status is AgentStatus.FAILED:
            run.status = AgentRunStatus.FAILED.value
            run.error_message = result.summary[:2000]
        else:
            run.status = (
                AgentRunStatus.AWAITING_APPROVAL.value
                if pending
                else AgentRunStatus.COMPLETED.value
            )
        run.completed_at = self._now
        run.execution_time_ms = elapsed_ms
        run.input_tokens = result.token_usage.input_tokens
        run.output_tokens = result.token_usage.output_tokens
        run.estimated_cost = _cost_of(result)
        run.result = {
            **result.to_dict(),
            "execution_time_ms": elapsed_ms,
            "context_summary": context_summary,
            "tool_usage": tool_usage,
        }
        await self._session.flush()
        log.info(
            "agent_run_recorded",
            run_id=str(run.id),
            agent=run.agent_name,
            status=run.status,
            actions=len(result.proposed_actions),
            pending=pending,
        )
        return run

    async def cancel(self, run: AgentRun) -> AgentRun:
        if run.status not in CANCELLABLE:
            raise ConflictError(f"Run is {run.status}; only queued or running runs cancel")
        run.status = AgentRunStatus.CANCELLED.value
        run.completed_at = self._now
        for action in await self._pending_actions(run.id):
            action.status = ActionStatus.CANCELLED.value
        await self._session.flush()
        return run

    # -- approvals ---------------------------------------------------------------------

    async def approve_action(self, action: AgentAction, user_id: uuid.UUID) -> AgentAction:
        self._require_pending(action)
        action.status = ActionStatus.APPROVED.value
        action.approved_by = user_id
        action.approved_at = self._now
        await self._settle_run(action.agent_run_id)
        return action

    async def reject_action(self, action: AgentAction, user_id: uuid.UUID) -> AgentAction:
        self._require_pending(action)
        action.status = ActionStatus.REJECTED.value
        action.approved_by = user_id
        action.approved_at = self._now
        await self._settle_run(action.agent_run_id)
        return action

    @staticmethod
    def _require_pending(action: AgentAction) -> None:
        if action.status != ActionStatus.PENDING.value:
            raise ConflictError(f"Action is {action.status}; only pending actions can be decided")

    async def _pending_actions(self, run_id: uuid.UUID) -> list[AgentAction]:
        return list(
            (
                await self._session.scalars(
                    select(AgentAction).where(
                        AgentAction.agent_run_id == run_id,
                        AgentAction.status == ActionStatus.PENDING.value,
                    )
                )
            ).all()
        )

    async def _settle_run(self, run_id: uuid.UUID) -> None:
        """awaiting_approval → completed once no pending actions remain."""
        await self._session.flush()
        run = await self._session.get(AgentRun, run_id)
        if run is None or run.status != AgentRunStatus.AWAITING_APPROVAL.value:
            return
        if not await self._pending_actions(run_id):
            run.status = AgentRunStatus.COMPLETED.value
        await self._session.flush()


def _cost_of(result: AgentResult) -> Decimal | None:
    raw = result.evidence.get("estimated_cost")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except ArithmeticError:
        return None
