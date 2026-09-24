# Agent Workflows (Milestone 6F)

The orchestration layer lets multiple agents collaborate **without giving any
agent extra access**. The initial workflow (`full_optimization`) runs:

    research → content-strategy → content-optimization → entity-optimization

Code: `apps/api/app/agents/workflow.py` (`WorkflowOrchestrator`,
`WORKFLOW_DEFINITIONS`), models `app/models/workflows.py` (`agent_workflows`,
`agent_workflow_steps`, migration `6c69eb8fd272`), routes
`app/api/v1/routes/workflows.py`, worker task
`app.workers.tasks.agents.run_agent_workflow`.

## Isolation model

Each step is an ordinary agent run through the same 6A orchestrator, context
builder and controlled tool registry — a workflow grants nothing beyond that.
Context passing is **summaries only**: a step's `input_context` (stored on the
step row and handed to the agent as `context.workflow_input`) carries the
objective plus prior steps' output summaries — finding titles, counts,
warnings, and the prior runs' **approved** actions (rejected ones appear only
as a count). No step ever receives another step's session, tools or raw data.
No action executes automatically at any point.

## Execution and approval gates

`POST /projects/{id}/agent-workflows` queues the workflow and dispatches the
Celery `agents` worker; execution never happens in API requests. The worker
advances step by step, re-reading the workflow status before each step so a
pause or cancel issued mid-run takes effect before the next step starts.

Whenever a step's run ends `awaiting_approval` — it proposed content changes,
entity changes or external actions — the **workflow stops in
`awaiting_approval`**. `POST …/resume` is refused (409) while any of that
run's proposed actions is still pending: the user must explicitly approve or
reject each via the 6A action endpoints first. Resuming re-queues the workflow
and the next step receives the approved actions in its input context.

A failing step marks the step and the workflow `failed` (later steps stay
pending, never run). `pause` works on queued/running; `cancel` works on
queued/running/paused/awaiting_approval and cancels the remaining steps.

## Consolidated action plan

After the final step the orchestrator builds one prioritized plan across every
step's non-rejected proposed actions. Each item: `priority` (rank),
`action` (+ action_type), `reason`, `evidence` (the action payload),
`expected_impact_area` (per agent: AI visibility / content coverage / existing
content / entity clarity), `effort` (per action type), `confidence` (the
producing run's confidence) and `approval_status`. If pending actions remain
at the end, the workflow finishes in `awaiting_approval` with the plan
attached; once everything is decided (and resumed) it completes.

## API

`POST /projects/{id}/agent-workflows` (`{workflow_type, objective}`, 202),
`GET /projects/{id}/agent-workflows` (status filter, step progress),
`GET /agent-workflows/{id}` (steps, input/output context, plan),
`POST /agent-workflows/{id}/pause|resume|cancel`. DATA_MANAGE for writes,
DATA_READ for reads, non-members 404.

## Tests

`apps/api/tests/agents/test_workflows.py`: sequential execution with context
passing (each agent runs once, in order, with prior summaries; stored step
rows mirror it), step failure fails the workflow and blocks later steps,
approval gate + refused resume until actions are decided + approved actions
flowing into the next step's context + the consolidated plan's fields,
rejected actions excluded from the plan, pause taking effect between steps
with resume continuing exactly where it left off, cancellation (worker refuses
cancelled workflows; steps cancelled), unknown workflow types / unregistered
agents, the real 4-agent chain through the API, and tenant isolation across
every endpoint.
