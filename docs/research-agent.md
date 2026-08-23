# Research Agent (Milestone 6B)

The first agent built on the Agent Framework (6A): it identifies
evidence-backed opportunities from AI visibility, competitor intelligence,
citation gaps, content gaps, entity intelligence and AI responses. It **never
changes customer assets** — every output is a finding, an opportunity or a
suggested action that goes through the framework's approval rules.

Code: `apps/api/app/agents/research.py` (`ResearchAgent`, registered as
`research` in the agent registry). Run it through the generic endpoint:
`POST /api/v1/projects/{project_id}/agents/research/run`.

## Design: deterministic by construction

The agent is deliberately rule-based, not LLM-generated: every number and name
in its output comes from a tool call over the project's own data
(`get_visibility_metrics`, `get_competitive_visibility`, `get_citation_gaps`,
`get_content_gaps`, `get_competitive_insights`, `get_competitor_candidates`,
`get_entity_data`, `get_pages`, `get_ai_responses` — three of these tools were
added to the 6A registry for this milestone). Its declared context is tiny
(20 prompts + 20 competitors); everything else is targeted tool retrieval, and
the run's tool trail is stored as evidence. Nothing can be hallucinated
because nothing is generated.

## Research process

1. **Identify significant gaps** — material competitor visibility leads (5C
   advantages), high-opportunity citation gaps (4C, ≥ 60, excluding
   competitor-owned sites), high-opportunity content gaps (5E, ≥ 60), weak
   Organization entity representation on the crawled site, and unreviewed
   discovery candidates (5B) as emerging competitors.
2. **Validate evidence** — each candidate carries its supporting records
   (gap ids, insight ids, candidate ids, measured shares, citation counts,
   crawl counts) and a confidence derived from the underlying data's
   confidence and the response sample; a sample under 10 responses caps every
   finding at low confidence with an explicit warning.
3. **Prioritize** — score = business relevance 25 + visibility impact 25 +
   competitor advantage 20 + evidence strength 20 + (inverted) effort 10,
   components stored per finding; the top 3–7 survive.

## Output contract

Executive summary; findings (`title`, `problem`, `evidence`, `impact`,
`confidence` + a `statements` object); opportunities (`title`, `why_now`,
`recommended_action`, `expected_area_of_impact`, `evidence`, `confidence`).
Every finding separates three statement categories that are never blurred:

* **observed** — a measurement ("QuickBooks appeared in 86% of eligible
  responses vs 33% for the brand (sample 24).")
* **inference** — what it suggests ("QuickBooks currently has stronger AI
  visibility for this prompt set.")
* **recommendation** — what to investigate or prepare ("Investigate the
  content and citation sources associated with those responses.")

## Proposed actions

Suggestions only, mapped from the finding type: investigate citation
opportunity (low risk, auto-approved as a note), create content brief /
create comparison page / add supporting evidence / optimize existing page /
improve organization entity (medium risk — the orchestrator forces human
approval, so the run ends `awaiting_approval` until a person decides). Nothing
is ever executed; competitor candidates route to the discovery review flow
instead of an action.

## Tests

`apps/api/tests/agents/test_research.py` (fixture data, no live providers):
evidence retrieval and output structure (incl. the tool trail), prioritization
(ordering, 3–7 cap, component weights, pending vs auto-approved actions),
confidence vs sample size, hallucination prevention (only seeded names and
numbers appear; competitor-owned sites are excluded however high their gap
score; empty projects produce zero findings), and tenant isolation (a second
project's data never leaks into a run; the generic endpoint 404s other
tenants).
