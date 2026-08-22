# AI Search Graph v1 (Milestone 4D)

The AI Search Graph is the connected view of everything the product observes:

```
Project ─has_prompt→ Prompt ─produces→ AI Response ─mentions→ Brand / Competitor
   │                                        ├─makes→ Claim
   └─tracks→ Brand / Competitor             └─cites→ Citation ─belongs_to→ Source Page ─belongs_to→ Source Domain
```

**v1 is relational.** There is no graph database and no new table: the nodes
are existing rows and the edges are existing foreign keys and link tables.

| graph concept | relational entity | edge realised by |
|---|---|---|
| project | `projects` | — |
| prompt | `prompts` | `prompts.project_id` (has_prompt) |
| model | `ai_models` / `prompt_runs.provider_key, model_key` | `prompt_runs` (produces) |
| response | `ai_responses` | `ai_responses.prompt_run_id` (produces) |
| brand / competitor | `projects` (brand), `competitors` | `brand_mentions`, `competitor_mentions` (mentions); `competitors.project_id` (tracks) |
| claim | `claims` | `claims.ai_response_id` (makes) |
| citation | `citations` | `citations.ai_response_id` (cites) |
| source page / domain | `source_pages`, `source_domains` | `citations.source_page_id / source_domain_id`, `source_pages.source_domain_id` (belongs_to) |
| associated_with | `citation_entities` | citation ↔ brand/competitor with confidence |
| competes_with | derived | responses mentioning both brand and competitor |

Code: `apps/api/app/graph/queries.py` (`GraphQueryService`), routes
`apps/api/app/api/v1/routes/graph.py`, schemas `apps/api/app/schemas/graph.py`.
Tests: `apps/api/tests/graph/`.

## Queries

All queries are scoped to one project and a window on
`prompt_runs.completed_at` (`start`/`end`, default last 90 days) and only
consider completed, parsed responses. All are top-N / paginated (`limit` ≤ 200,
default 50, `offset`).

| question | call |
|---|---|
| Q1 Which sources are most frequently cited? | `GET …/graph/sources?view=top` |
| Q2 Which sources are frequently associated with competitors? | `…/sources?view=competitor` (competitor citations > 0, ordered by competitor citations; `competitor_share`) |
| Q3 Which sources cite competitors but rarely the brand? | `…/sources?view=gap` (competitor ≥ 3 and ≥ 3× brand; `brand_ratio`) |
| Q4 Which prompts produce the most competitor citations? | `…/graph/prompts` (per prompt: responses, brand/competitor mentions, brand/competitor citations, competitors, top sources) |
| Q5 Which sources are becoming more important? | `…/sources?view=rising` (citations in the window vs the preceding window of equal length; `growth = (current − previous)/max(previous, 1)`, needs ≥ 3 current citations) |
| Q6 Which claims are repeatedly associated with competitors? | `…/graph/claims?associated_with=competitor` (claims grouped by normalised subject/predicate/object, `min_occurrences` default 2; association by subject = brand or configured competitor name) |

`…/graph/competitors` returns the brand and every competitor (mentioned or
configured) with mentions, responses, citations, co-mentions with the brand,
top sources, plus the `competes_with` edges.

`…/graph/overview` returns a **bounded subgraph**: project, brand, competitor
nodes, the top-N prompts (`top_prompts`), top-N source domains (`top_sources`),
top-N claims (`top_claims`), with `has_prompt`, `tracks`, `mentions`, `cites`
(prompt → competitor via citations and prompt → source), `associated_with`
(brand/competitor → source), `competes_with`, and `claims` edges — only
between nodes that are in the subgraph. Responses and pages are counted in
`statistics` but not returned as nodes. `statistics.truncated` says whether
limits cut anything. Node ids are `<type>:<uuid-or-key>`.

## Performance

Every endpoint filters by window first (indexed `prompt_runs.project_id`,
`completed_at`), aggregates in SQL and returns at most `limit` rows; the
overview assembles at most `top_prompts + top_sources + top_claims +
competitors + 2` nodes. The "rising" view ranks in Python over a bounded
candidate set (≤ 400 sources). Nothing loads all responses or citations.

## Future architecture: moving to a graph store

The relational model is the source of truth; a graph store would be a
*projection* of it, rebuilt from the same tables.

1. **PostgreSQL graph extensions (Apache AGE / pgRouting).** Keep the tables;
   add an AGE graph whose vertices mirror the node ids used here
   (`project:<id>`, `source_domain:<id>`, …) and whose edges are created from
   the link tables by a materialising job (`citation_entities` →
   `associated_with`, `citations` → `cites`, `brand_mentions` → `mentions`, …).
   `GraphQueryService` methods become Cypher queries (`MATCH
   (c:competitor)-[:associated_with]->(s:source_domain) … RETURN s, count(*)`);
   tenancy stays enforced by a `project_id` property on every vertex and edge
   plus the existing access checks. Lowest risk: same database, same
   transactions, same backups.
2. **Neo4j (or another property-graph store).** Same projection, exported
   incrementally: a Celery task streams new/changed rows (by `updated_at`)
   into the graph with MERGE on the stable node ids, and the graph API reads
   from Neo4j while writes stay in PostgreSQL (CQRS). Multi-tenancy via one
   database per organisation or a `project_id` property guarded in every
   query. Needed when traversals get deep (multi-hop influence, path queries)
   or the dataset outgrows SQL aggregation.
3. **Other (e.g. a vector-enabled graph, or Dgraph/TigerGraph).** Identical
   contract: the `GraphNode`/`GraphEdge` schema in `schemas/graph.py` and the
   six questions in `queries.py` are the interface; only the implementation of
   `GraphQueryService` changes. Because node ids, edge types and window
   semantics are already fixed here, clients do not change.

What to keep stable now so the migration stays cheap: the node id scheme, the
edge type vocabulary (`has_prompt`, `tracks`, `produces`, `mentions`, `cites`,
`claims`, `associated_with`, `competes_with`, `belongs_to`), `project_id` on
every tenant-scoped row, and the rule that confidence/weights live on edges.
