# Citation Gap Engine (Milestone 4C)

Answers *"where are competitors getting cited that we are not?"* for one
project, from the citations already stored by Milestones 3D–4B. No AI call is
made; analysis is a pure read of `citations` + `citation_entities` +
`source_domains`.

Code: `apps/api/app/gaps/` (`scoring.py` pure functions, `engine.py`),
`apps/api/app/models/gaps.py`, routes `apps/api/app/api/v1/routes/gaps.py`,
Celery task `analytics.analyze_citation_gaps`. Migration `dd32486fc9cb`.
Tests: `apps/api/tests/gaps/`.

```
relevant AI responses (completed + parsed, in window)
   → per source domain: relevant responses, prompts, citations
   → brand citations / competitor citations (citation_entities)
   → compare → gap type, Citation Opportunity Score, confidence → citation_gaps
```

## Inputs per source (one project, one window — default 90 days)

| field | meaning |
|---|---|
| eligible_responses | parsed, completed responses of the project in the window |
| relevant_responses | distinct eligible responses that cite the source |
| prompts_citing / total_prompts | distinct prompts whose answers cite the source / prompts with eligible responses |
| citations | citation rows for the source |
| brand_citations | citations with a `brand` relationship |
| competitor_citations | citations with a `competitor` relationship (+ per-competitor counts) |
| first/last cited, first-/second-half split | recency and "emerging" detection |
| source_relevance | Source Relevance Score of the domain (4B, global counts) |

Brand/competitor relationships come from 4A's `citation_entities`. With 4C the
resolver also recognises the brand or a competitor **named in a third-party URL
path or anchor text** (e.g. `g2.com/products/ledgerly`, confidence 0.7), so
review sites and directories can carry brand and competitor counts. A citation
can relate to several entities (comparison pages). Uncertain citations still
get no relationship.

## Gap types

| type | rule (b = brand citations, c = competitor citations, r = relevant responses) |
|---|---|
| `emerging_source` | b = 0, first cited within the last 30 % of the window, second-half citations ≥ max(3, 2 × first half) |
| `brand_absent` | b = 0 and (c ≥ 1 or r ≥ 3) |
| `competitor_advantage` | b > 0, c ≥ 3, c ≥ 2 × b |
| `shared_source` | b > 0 and c > 0 (within 2×) |
| `source_overrepresented` | b ≥ 3, c = 0, brand ≥ 80 % of the source's citations |
| `source_underrepresented` | everything else (cited, but neither brand nor competitor clearly) |

## Citation Opportunity Score (0–100)

    opportunity = Σ weight × component / Σ weight × type multiplier

| component | weight | derivation |
|---|---|---|
| citation_frequency | 25 | share of eligible responses citing the source; 100 at ≥ 30 % |
| competitor_gap | 30 | 50 + 50 × (c − b)/(c + b); b = 0 with competitors → 100; nobody cited → 40 |
| source_relevance | 20 | Source Relevance Score (4B) |
| prompt_relevance | 15 | prompts citing the source / prompts in the window |
| recency | 10 | days since last citation: ≤ 7 → 100, 30 → 60, 90 → 20, then → 0 |

Type multipliers: `source_overrepresented` × 0.3 (not an opportunity),
`shared_source` × 0.7. Priority: ≥ 70 high, ≥ 40 medium, else low. Volume
alone never makes a recommendation: a source the brand already dominates
scores low however often it is cited, a narrow source (one prompt) scores
lower than a broad one, and stale sources decay.

Sample size never inflates the score; it drives **confidence** separately.

## Confidence (data sufficiency)

| confidence | relevant responses citing the source | eligible responses |
|---|---|---|
| high | ≥ 20 | ≥ 50 |
| medium | ≥ 8 | ≥ 20 |
| low | ≥ 3 | ≥ 5 |
| insufficient | ≤ 1 response, or eligible < 5, or below `low` | |

A source whose type is still `unknown` (incomplete source data) is capped at
`medium`. Insufficient gaps are stored (so the user sees what was observed)
but are excluded from `actionable` and `top_opportunities`, and their
explanation ends with "Too little data to act on yet."

## Storage

`citation_gaps`: id, project_id, source_domain_id, source_page_id (NULL —
gaps are domain-level in v1), gap_type, brand_citations,
competitor_citations, relevant_response_count, opportunity_score,
confidence, explanation, status (`new` → reviewing / accepted / dismissed /
in_progress / completed), note, competitors (JSONB name → count), evidence
(JSONB: components, inputs, source relevance, top pages, half-window
split), analysis_version, analyzed_at. Unique per (project, domain, page).
Re-analysis updates metrics in place and keeps status/note; rows still
`new` whose source no longer appears in the window are removed.

## API

```
GET   /api/v1/projects/{project_id}/citation-gaps        filters: source_type, gap_type,
                                                          status, confidence, competitor,
                                                          min_score, max_score; paginated,
                                                          ordered by opportunity desc
GET   /api/v1/projects/{project_id}/citation-gaps/summary counts by type/status/confidence/
                                                          source type/priority, actionable,
                                                          top 5 opportunities, competitors_ahead,
                                                          data sufficiency
POST  /api/v1/projects/{project_id}/citation-gaps/analyze (DATA_MANAGE; ?window_days=)
GET   /api/v1/citation-gaps/{gap_id}
PATCH /api/v1/citation-gaps/{gap_id}                      status / note (DATA_MANAGE)
```

Tenancy: project routes use the project from the path; gap routes derive the
project from the row; non-members get 404. Gaps are per project even when two
tenants cite the same shared source domain.
