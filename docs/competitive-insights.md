# Why Competitors Win (Milestone 5D)

The Competitive Advantage Analysis engine looks for **evidence-backed patterns**
that may explain why a competitor appears more often or more favourably in AI
responses. It never claims causation: every insight is an *observed advantage*,
a *pattern detected* or a *potential contributing factor*, and every evidence
payload carries the same caution sentence. "Competitor X ranks higher because
of Y" is exactly the sentence this engine is built not to produce.

Code: `apps/api/app/insights/` (`analyzers.py` pure rules, `engine.py` fact
gathering + persistence), model `app/models/insights.py`
(`competitive_insights`), routes `app/api/v1/routes/insights.py`. Analysis
version `competitive-insights/v1`.

## What is compared

All comparisons come from data the platform has actually observed: parsed AI
responses in the window (default 90 days), their citations with
`citation_entities` attribution, source-domain classifications (4B), response
claims, the 5C competitive metrics and the brand's own crawled structured data.
**Competitor websites are not crawled**; anything that would require them is
either derived from citations that appeared in responses or framed as a
brand-side gap.

| insight type | signal | minimum bar |
|---|---|---|
| `citation_advantage` | unique citing domains, citation counts, authoritative / review / community / media breakdown | competitor ≥ 5 domains, ≥ brand + 4 and ≥ 1.5× |
| `content_advantage` | cited competitor pages by category (comparison, product, FAQ, use case, educational) vs cited brand pages — only pages that appeared in citations | ≥ 3 cited pages and leads in ≥ 2 categories |
| `coverage_advantage` | prompt coverage (distinct prompts where the entity appears) | ≥ brand + 2 prompts and ≥ 1.4×, ≥ 3 prompts total |
| `positioning_advantage` | recommendation share and average list position (5C) | rec share ≥ brand + 15 points, or average position better by ≥ 0.5 |
| `evidence_advantage` | research-type citing domains and specific, checkable claims (numbers/dates in claim object or context) | ≥ 2 research domains above brand, or ≥ 5 specific claims and ≥ 2× brand |
| `entity_advantage` | brand-side only: competitor's 5C score ≥ brand + 10 while the crawled brand site is missing ≥ 2 of Organization schema, description, Product schema, sameAs, consistent names | site crawled; capped at medium confidence; evidence says `competitor_site_analyzed: false` |

Reputation signals are analyzed only through the response/citation graph
(review/community domains, sentiment on mentions); raw domain authority alone
never produces an insight.

## Confidence and impact

`confidence` (high / medium / low) comes from the eligible-response sample and
the number of observations backing the specific insight: high needs ≥ 50
responses and ≥ 20 supporting observations, medium ≥ 20 and ≥ 5, otherwise
low. `impact` (high / medium / low) reflects the magnitude of the gap
(roughly ≥ 3× high, ≥ 1.5× medium). `strength` (0–100) is only an ordering
key within an impact band.

**Insufficient evidence produces nothing**: below 10 eligible responses no
insights are generated at all, and each analyzer returns nothing when its
minimum bar is not met — thin data yields no insight rather than a weak one.

## Persistence

`competitive_insights` is unique on (project, competitor, insight type):
re-analysis updates rows in place and deletes insights whose evidence no longer
exists. `analyzed_at`, `window_days` and `analysis_version` record how each row
was produced.

## API

| method | path | permission |
|---|---|---|
| GET | `/projects/{project_id}/competitive-insights` (filters `insight_type`, `impact`, `confidence`, `competitor_id`; ordered impact → strength) | DATA_READ |
| POST | `/projects/{project_id}/competitive-insights/analyze` (`{window_days}`) | DATA_MANAGE |
| GET | `/competitors/{competitor_id}/insights` (project derived from the row; other tenants 404) | DATA_READ |

## Tests

`apps/api/tests/insights/test_insights.py`: citation advantage (domains,
types, authority, language), content advantage (cited-page categories),
entity advantage (brand-side gaps, gated on visibility gap + crawl, never
high confidence), evidence advantage (research domains + specific claims),
the confidence ladder, insufficient evidence (too few responses → nothing;
thin gaps → nothing), re-analysis upsert/stale removal, competitor-scoped
listing, filters and tenant isolation.
