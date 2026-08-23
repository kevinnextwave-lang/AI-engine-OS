# Competitive AI Visibility (Milestone 5C)

Compares the customer's brand with each configured competitor over the **same**
eligible AI responses (completed, parsed prompt runs in the window). Everything
is computed on demand from the observations the AI Visibility Score already
uses (`app/visibility/observations.py`), so the two views never disagree about
what a response said. Code: `apps/api/app/competitive/` (`metrics.py` pure,
`engine.py` views), routes `app/api/v1/routes/competitive.py`.

Method id: `competitive-visibility-score/v1`, echoed in every payload with the
weights and a note.

## Per-entity metrics

For the brand (`name = "brand"`) and every configured competitor:

| metric | definition |
|---|---|
| Mention Share | responses mentioning the entity ÷ eligible responses |
| Recommendation Share | responses where the entity is recommended (moderate/strong strength and not negative sentiment) ÷ eligible responses |
| Average Position | mean list position over mentions that have a position |
| Citation Share | responses with at least one citation referencing the entity ÷ eligible responses. A citation references an entity when its host is one of the project's domains / the competitor's domains (`competitors.hostname`, `competitor_domains`), or when source intelligence wrote a `citation_entities` row for it (slug / anchor evidence) |
| Sentiment | counts by sentiment over mentions, plus a 0–100 sentiment score (positive 100, neutral/mixed 50, negative 0) |
| Prompt Coverage | number of distinct prompts in which the entity appears |

`counts` carries the raw numerators (mentions, recommendations, positioned
mentions, cited responses, citations).

## Competitive Visibility Score

This is **our own composite, not an industry-standard score**. It is a weighted
mean of five 0–100 components over the same eligible responses:

| component | weight | source |
|---|---|---|
| mention_share | 30 | Mention Share |
| recommendation_share | 25 | Recommendation Share |
| position_score | 15 | mean position points over positioned mentions: 1st 100, 2nd 85, 3rd 70, 4th 55, 5th 40, 6th+ 25 |
| citation_share | 15 | Citation Share |
| sentiment_score | 15 | sentiment score over mentions |

Position and sentiment are unavailable for an entity that is never mentioned;
those components drop out and the remaining weights renormalise, so an invisible
entity scores 0 (not "unknown"). The score is withheld (`null`) below the
minimum sample of 5 responses and rounded by sufficiency: 5–19 to 5 points,
20–49 to whole points, 50+ to one decimal (the AI Visibility Score rules).

## Competitive advantage

For each competitor: `advantage = competitor score − brand score`, plus the
same difference per component and `where_they_win` (components the competitor
leads by ≥ 5 points). A gap is flagged `material` only when both scores exist,
the sample has at least 20 responses ("moderate" sufficiency) and the gap is
≥ 10 points; otherwise the gap is still reported with a `reason`.

## Rankings and data quality

Every payload includes `data_quality`: `sample_size`, `prompt_count`,
`provider_count` (+ provider keys), `date_range` (first/last response in the
period), `confidence` (insufficient < 5, low < 20, moderate < 50, high) and the
minimum samples. An ordered `ranking` (with `brand_rank`) is produced only at
20+ responses; below that `ranking.available` is false with a reason. Per-prompt
rows name a `leader` only with 5+ responses and report ties instead of picking
one.

## API (DATA_READ; non-members 404)

| path | content |
|---|---|
| `GET /projects/{id}/competitive-visibility?window=7d\|30d\|90d` | entities with metrics, score, previous-period score and trend; advantages; ranking; data quality for both periods |
| `…/trends` | per window (7d/30d/90d) current vs previous score and mention share per entity with advantages; weekly series over 90 days per entity (score, mention/recommendation/citation share, sample, sufficiency) |
| `…/prompts?window=` | for every prompt: brand + each competitor → mentioned, recommended, position (mean), sentiment (dominant), citation count, recommendation strength (strongest), how many of the prompt's responses mention/recommend it, and the latest response's values; leader; competitors that out-mention the brand |
| `…/engines?window=` | the overview block per AI provider plus `engine_spread` (brand score and top-competitor advantage per engine) |

## Limits

Only configured competitors are compared; a competitor accepted from discovery
but never recognised by the parser shows 0 until its mentions are parsed
(parser alias matching is a separate milestone). Citation attribution is
conservative: only own-site hosts and clear slug/anchor matches count.

## Tests

`apps/api/tests/competitive/test_competitive.py`: brand vs competitor metrics
and score formula, prompt comparison and leader gating, provider comparison,
historical comparison (previous period, trends, series), insufficient data
(withheld scores, no ranking, non-material gaps, coarse rounding), helpers on
empty data, and authorization (401 / other tenant 404 / viewer 200 / unknown
project 404).
