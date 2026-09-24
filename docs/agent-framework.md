# Agent Framework (Milestone 6A)

Reusable architecture for specialized AI agents. The framework ships with **no
individual agents**; agents register in later milestones. Flow:

    Agent Request → Orchestrator → Agent → Tools → Knowledge/Intelligence
                  → Structured Result → Approval → (future) Action

Code: `apps/api/app/agents/` — `base.py` (Agent, ModelPreferences, AgentLLM),
`context.py` (AgentContext + targeted retrieval), `tools.py` (controlled tool
registry), `prompting.py` (trust separation), `registry.py`,
`orchestrator.py`; models `app/models/agents.py` (`agent_runs`,
`agent_actions`), routes `app/api/v1/routes/agents.py`, worker task
`app.workers.tasks.agents.run_agent`.

## Agent interface

```python
class MyAgent(Agent):
    name = "my_agent"
    version = "1.0"
    instructions = "…trusted agent instructions…"
    context_spec = ContextSpec(prompts=20, competitors=10)
    model_preferences = ModelPreferences(
        preferred=ModelChoice("openai", "gpt-4o-mini"),
        fallback=ModelChoice("anthropic", "claude-3-5-haiku-latest"),
        max_cost=Decimal("0.50"),
        max_tokens=4000,
    )

    async def run(self, context: AgentContext) -> AgentResult: ...
```

`AgentContext` carries organization/project/user ids, the objective, and only
the categories the agent's `ContextSpec` requested (observations,
recommendations, prompts, competitors, citations, pages — each capped at 50
rows) plus a project-bound `ToolBox`. **The whole database is never passed**;
anything beyond the declared context is fetched through tools at run time.

`AgentResult` carries agent name/version, status (queued / running / completed
/ failed / awaiting_approval / cancelled), summary, findings, recommendations,
evidence, proposed actions, confidence, token usage, execution time and
warnings; the orchestrator serializes it onto the run row.

## Persistence

`agent_runs`: status, objective, timing, `input_tokens` / `output_tokens` /
`estimated_cost`, `error_message`, serialized result (including tool usage and
context summary). `agent_actions`: action_type, description, payload, risk
level (low/medium/high), `approval_required`, status (pending / approved /
rejected / cancelled / executed), approver + timestamps, `execution_result`.

## Human approval — not bypassable

Agents only *propose* actions. The **orchestrator** applies the approval
rules: any action of medium/high risk is forced to `approval_required`
regardless of what the agent set; approval-required actions start `pending`
and can only move through `POST /agent-actions/{id}/approve|reject`, which
records the acting user. A run with pending actions is `awaiting_approval` and
becomes `completed` when every action is decided. Executing approved actions
is a later milestone — nothing in 6A changes external or customer-facing
state.

## Tool system

`ToolBox` is the only path from an agent to project data: fixed, parameterized
queries bound to one project. Tools: get_project, get_pages, get_page,
get_competitors, get_prompts, get_ai_responses, get_citations,
get_citation_gaps, get_content_gaps, get_entity_data, get_visibility_metrics,
get_recommendations. Each tool validates its arguments against a pydantic
schema (exposed via `available()`), enforces row caps (≤ 50) and text caps,
verifies row ownership (`get_page` on another project's page is an error, not
data), and logs every call — the run's evidence trail records tool usage.
**No agent ever gets a session, raw SQL, or an unscoped query; an LLM never
constructs SQL.**

## Prompt architecture and injection protection

`prompting.py` keeps five layers separate: framework system rules and agent
instructions (trusted, system prompt); project context (platform facts);
tool results / data (untrusted, fenced); the user request. Crawled website
content and AI-generated text are **always untrusted data**: they are rendered
only inside `<<<BEGIN_UNTRUSTED_DATA … END_UNTRUSTED_DATA>>>` fences in the
user message, never in the system prompt, and `sanitize()` neutralizes fence
markers inside the payload so content like "Ignore previous instructions" or a
forged END marker cannot escape its block. The standing system rule tells the
model that fenced content is data, never instructions.

## Model selection and cost

`ModelPreferences` is provider-neutral (provider key + model name resolved via
the existing `ProviderRegistry`): preferred model, fallback model, max output
tokens and a per-run cost ceiling. `AgentLLM` is the single LLM path: it falls
back on provider errors, accumulates token usage, prices calls from the model
catalog and raises `BudgetExceededError` the moment the ceiling is crossed —
the orchestrator fails the run with the budget message.

## Execution

`POST /projects/{id}/agents/{name}/run` (DATA_MANAGE) creates a **queued** run,
commits, and dispatches `app.workers.tasks.agents.run_agent` to the `agents`
Celery queue — agents never execute inside API requests. Cancellation
(`POST /agent-runs/{id}/cancel`) works on queued/running runs; the worker
refuses to execute a cancelled run and a cancellation issued mid-run wins over
the agent's result. Reads: `GET /projects/{id}/agent-runs`,
`GET /agent-runs/{id}`, `GET /agent-runs/{id}/actions` (row-derived access;
other tenants 404).

## Tests

`apps/api/tests/agents/test_agents.py`: registration (duplicates, unknown
agent 404), tool validation/caps/logging and project scoping, targeted
context retrieval, prompt-injection isolation (system prompt free of
untrusted content, fencing, marker neutralization), approval workflow
(forced approval on high risk, approve/reject, 409 on re-decide, run
settling), agent failures and budget failures, cancellation, LLM cost
tracking with fallback and ceilings, run cost/token persistence, and
authorization/tenant isolation across every endpoint.
