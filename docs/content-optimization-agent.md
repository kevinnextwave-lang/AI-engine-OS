# GEO Content Optimization Agent (Milestone 6D)

Analyzes existing crawled pages and **proposes** improvements for clarity,
factual specificity, entity clarity, answerability, evidence quality,
structure and citation readiness. It never rewrites a page and never claims a
guaranteed AI ranking improvement — every proposal is stored for a human to
accept, edit or reject.

Code: `apps/api/app/agents/content_optimization.py` (registered as
`content-optimization`, run via the generic agent endpoint), model
`app/models/content_reviews.py` (`content_optimization_reviews`, migration
`1ba15eba6ca2`), routes `app/api/v1/routes/content_reviews.py`.

## Inputs

Through the controlled tool registry: page metadata (`get_pages`), the new
`get_page_content` tool (latest crawled extracted text — treated as untrusted —
plus headings, structured-data types and page-scoped entities), content gaps,
citation gaps, competitive insights, and the project's prompts/competitors from
the declared context. Pages tied to weak-topic gaps and prompt keywords are
reviewed first (up to 5 per run); pages with too little extracted text are
skipped with a warning.

## The seven analyses

1. **Answerability** — related prompts whose keywords the page doesn't cover
   get a proposed answer section (with `[FILL: …]` placeholders).
2. **Entity clarity** — who the company is / what it offers / who it serves /
   machine-readable identity; a proposed intro rewrite states them.
3. **Specificity** — vague marketing sentences ("powerful solutions",
   "best-in-class", …) each get a replacement template that keeps only
   verifiable claims; repeated boilerplate is proposed once.
4. **Evidence** — checkable claims without sources ("fastest", "95%", "#1")
   get an explicit sourcing instruction: cite a real source or soften/remove
   the claim; **evidence is never invented**.
5. **Structure** — H1s, question-form headings/FAQ vs question prompts,
   lists on long pages, meta description.
6. **Entity markup** — schema recommended **only where the page's content
   justifies it** (FAQPage only with question-form content, Product only with
   product entities, Organization only on top-level pages) — never merely
   because a type exists.
7. **Internal linking** — real related pages by shared keywords.

Score = 100 − transparent deductions per finding; confidence from how much
content was available to analyze.

## Proposed change format and human review

Every change: `location`, `current_text`, `proposed_text`, `reason`,
`evidence`, `confidence`, plus a stable `change_id` (hash of
location+current_text), `decision` and `decided_text`. Proposed text never
contains invented facts — real details appear as `[FILL: …]` instructions to
the editor.

Decisions via `POST /content-reviews/{id}/changes/{change_id}` with
`{action: accept | edit | reject, text?}` (edit requires the edited text;
accept copies the proposed text into `decided_text`). The first decision moves
the review draft → reviewing. **The original page is never modified** by the
agent or any review route; accepted/edited changes can later be sent to an
integration. Reviews are unique per (project, page); re-runs replace the
analysis but keep the review's status and carry decisions over for unchanged
changes (same location + current text).

## API

`GET /projects/{id}/content-reviews` (status filter, pending-change counts,
lowest score first), `GET /content-reviews/{id}`,
`PATCH /content-reviews/{id}` (status), and the change-decision endpoint
above. Non-members 404. Each run also proposes a medium-risk
`review_content_optimization` action per page, so runs end
`awaiting_approval`.

## Tests

`apps/api/tests/agents/test_content_optimization.py`: content analysis
(categories, internal links, no ranking guarantees), structured
recommendations (FAQ proposal from real prompts; markup only where
justified), evidence handling (sourcing instructions, never fabricated
sources), proposed-change format and `[FILL]` placeholders, decisions
(accept/edit/reject, edit requires text, draft → reviewing) with re-run
carry-over, original content preservation (page row and crawled text
byte-identical after run + accept), and authorization.
