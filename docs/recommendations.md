# Citation Opportunity Recommendations (Milestone 4E)

The first Recommendation Engine turns Citation Intelligence — citation gaps
(4C) plus the underlying citations — into **evidence-based opportunities that a
person reviews**. The engine never executes anything: it writes rows to
`recommendations`; humans approve, dismiss, start and complete them. There are
no automated external actions anywhere in this milestone.

Code: `apps/api/app/recommendations/` (`rules.py` pure functions, `engine.py`,
`service.py` transitions), `apps/api/app/models/recommendations.py`, routes
`apps/api/app/api/v1/routes/recommendations.py`. Migration `1f489b701689`.
Tests: `apps/api/tests/recommendations/`.

## Table `recommendations`

id, project_id, recommendation_type (`citation`, `content`, `entity`,
`technical`, `authority`, `reputation`), title, description, explanation
(JSONB, the five answers below), evidence (JSONB), priority (`critical` /
`high` / `medium` / `low`), opportunity_score, confidence, status (`new`,
`reviewing`, `approved`, `dismissed`, `in_progress`, `completed`), note,
source_key (stable identity, unique per project — regeneration updates in
place and keeps the review status), citation_gap_id, generator_version,
generated_at, reviewed_at, reviewed_by_user_id, created_at, updated_at.

v1 generates `citation` and `content` recommendations. The other types are
defined for later analyzers (entities, technical SEO, readiness, sentiment).

## Generation (`POST /projects/{id}/recommendations/generate`, DATA_MANAGE)

Run the citation-gap analysis first. For every gap:

* skipped when confidence is `insufficient`, when the gap type is
  `shared_source` or `source_overrepresented`, when it is
  `source_underrepresented` with a Source Relevance Score below 50, or when the
  source is a competitor's own website (company type, only competitor
  citations);
* otherwise a **citation** recommendation — *"Investigate {source} visibility
  opportunity"* — with evidence: relevant prompt count, total prompts,
  competitor citation count (+ per competitor), brand citation count, relevant
  and eligible responses, Source Relevance Score, source type, gap type,
  confidence, competitor gap, business relevance, priority score, top pages,
  window.

**"Create original research"** (`content`) is generated only when all three
conditions hold, and the response lists the reasons when it is not:

1. competitors are cited for research — ≥ 3 competitor-related citations to
   research-type sources (domain type `research`, or a path containing
   `/research`, `/report`, `/study`, `/whitepaper`, `/survey`, `/paper`) across ≥ 2 responses;
2. the customer has a content gap — zero brand-related research citations;
3. the topic is commercially relevant — ≥ 50 % of the prompts surfacing those
   sources are commercial (categories comparison / recommendation / pricing /
   alternative, or funnel stages consideration / decision / purchase).

Recommendations still `new` whose basis disappeared are removed on
regeneration; reviewed ones are kept.

## Priority

    priority_score = opportunity × confidence_factor × (0.7 + 0.3 × business_relevance)

| input | use |
|---|---|
| opportunity score | the gap's Citation Opportunity Score (4C) |
| confidence | factor 1.0 high, 0.85 medium, 0.6 low; insufficient ⇒ no recommendation |
| business relevance | share of prompts citing the source that are commercial |
| competitor gap | (competitor − brand) / (competitor + brand); required ≥ 0.6 for critical |
| sample size | relevant responses ≥ 20 required for critical |

`critical` = score ≥ 80 and high confidence and competitor gap ≥ 0.6 and ≥ 20
responses; `high` ≥ 65; `medium` ≥ 40; else `low`. The priority score is
stored in the evidence so the decision can be traced.

## Explanations

Every recommendation answers, in `explanation`:

1. `observed` — what we observed (counts, shares, competitors);
2. `why_it_matters` — why it matters for this gap type and how commercial the prompts are;
3. `investigate` — what the customer could investigate (legitimate editorial, review, partnership, research or community routes; explicitly *not* paid placements disguised as editorial, fake reviews, link schemes or manipulation);
4. `evidence_summary` — the numbers behind it;
5. `confidence_statement` — how confident we are, always ending with the reminder that a citation does not guarantee better AI visibility.

## Human approval

```
GET   /projects/{id}/recommendations           filters: status, priority, type, min_score; paginated
GET   /projects/{id}/recommendations/summary
POST  /projects/{id}/recommendations/generate
GET   /recommendations/{id}
POST  /recommendations/{id}/approve            new | reviewing → approved
POST  /recommendations/{id}/dismiss            new | reviewing | approved | in_progress → dismissed
POST  /recommendations/{id}/start              approved → in_progress
PATCH /recommendations/{id}                    reviewing (from new, or reopen from dismissed),
                                               completed (from in_progress), or a note
```

Allowed transitions are returned on every recommendation
(`allowed_transitions`); an invalid transition is a 409 naming the allowed
targets. Every change records who reviewed it and when. DATA_READ to read,
DATA_MANAGE to generate or change status; non-members get 404.
