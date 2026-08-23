# Content Strategy Agent (Milestone 6C)

Converts verified AI-search opportunities into **content briefs** — what should
be created, why it matters, which audience it serves, which of the project's
actual AI prompts it targets, which competitors currently dominate them, and
which evidence must be collected. It never generates the content itself.

Code: `apps/api/app/agents/content_strategy.py` (registered as
`content-strategy`), model `app/models/content_briefs.py` (`content_briefs`,
migration `5401563bd6e4`), routes `app/api/v1/routes/content_briefs.py`.
Run it via the generic agent endpoint:
`POST /api/v1/projects/{project_id}/agents/content-strategy/run`.

## How briefs are built (deterministic, observed data only)

Inputs come through the controlled tool registry: content gaps (with selected
evidence fields), citation gaps, competitive insights, pages, entities, claims,
plus prompts and competitors from the declared context. Each content gap with
opportunity ≥ 60 (and not archived/dismissed) becomes one brief, at most 5 per
run:

| gap type | content type | 
|---|---|
| missing_comparison | comparison_page |
| missing_faq | faq_page |
| missing_use_case | use_case_page |
| missing_product_detail | product_page |
| missing_topic | new_article |
| weak_topic | existing_page_optimization |
| missing_evidence | research_content |

(The `content_briefs.content_type` column supports the full set including
alternative_page, case_study, glossary and documentation for later agents and
manual briefs.)

Each brief carries: a human title; search intent (from the targeted prompt's
category); audience (from funnel stages); **target prompts that actually exist
in the project** (the gap's own prompt first, then keyword-matched ones);
competitor ids resolved from configured competitors; information requirements
(directly answer the targeted prompts; address competitor claims AI answers
repeat — with an instruction to verify them first); evidence requirements per
type (data / research / citations / examples / customer evidence, each with
`required` and notes, candidate citation sources taken only from observed
citation gaps with competitor-owned sites excluded, and the standing rule
"do not fabricate…"); entity requirements (Organization/product entities,
flagged when missing from the crawl); a recommended structure
(H1/H2s/H3/FAQ/Sources built from the targeted prompts); differentiation
(grounded in 5D insights about the dominating competitor); internal link
recommendations (real matching pages); and a confidence taken from the gap.

## Anti-fabrication guarantees

The agent never invents statistics, testimonials, citations, reviews or
credentials — structurally, because every value comes from a tool call — and
every brief's objective states that no ranking or citation outcome is
guaranteed. Evidence requirements describe what real material must be
*collected*, never supply it.

## Persistence and lifecycle

Briefs are written through `save_content_brief`, the framework's only write
tool: schema-validated, project-scoped, prompt/competitor ids verified to
belong to the project, insert as `draft`, and re-saves update content but never
the review status. Unique per (project, source_key = `content_gap:<id>`), so
re-runs upsert. Status flow: draft → reviewing → approved → in_progress →
completed → archived via `PATCH /content-briefs/{id}` (DATA_MANAGE). Each run
also proposes a medium-risk `review_content_brief` action per brief, so the
run ends `awaiting_approval` until a person acknowledges them.

## API

`GET /projects/{id}/content-briefs` (filters `status`, `content_type`),
`GET /content-briefs/{id}`, `PATCH /content-briefs/{id}` (status, light
edits). Non-members 404.

## Tests

`apps/api/tests/agents/test_content_strategy.py`: brief generation (types,
titles, structure, API surface; low-opportunity gaps produce nothing),
re-run upsert with review status surviving, evidence requirements (only
observed citation sources; fabrication rule present; competitor claims
flagged with a verify instruction), competitor integration (ids,
differentiation, entity requirements, competitor-owned sites excluded),
prompt mapping (all targeted prompts exist in the project; the gap's prompt
first; internal links are real pages), hallucination prevention (no invented
names/sources; empty project → zero briefs), and authorization.
