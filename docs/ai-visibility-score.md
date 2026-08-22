# AI Visibility Score — methodology (`ai-visibility-score/v1`)

The **AI Visibility Score** is this product's own composite metric. It is not an
industry standard and is not comparable with scores from other tools. Every
response from the visibility API carries the method identifier, the sample it was
computed from, and a data-sufficiency label so a reader can judge how much to
trust a number.

Code: `apps/api/app/visibility/` (`observations.py` → `metrics.py` → `engine.py`).
Routes: `apps/api/app/api/v1/routes/visibility.py`. Tests: `apps/api/tests/visibility/`.

## 1. Unit of observation

One observation = one **completed prompt run whose response has been parsed**
(`prompt_runs.status = completed` and `ai_responses.parser_version IS NOT NULL`),
joined to its prompt (category, funnel stage) and its parsed rows
(`brand_mentions`, `competitor_mentions`, `citations`). Failed, cancelled,
queued or unparsed runs are never "eligible responses". Observations are
attributed to the period by `prompt_runs.completed_at`.

Per observation the engine derives:

| field | derivation |
|---|---|
| `brand_mentioned` | at least one `brand_mentions` row |
| `brand_position` | the smallest non-null `position` among the brand's mentions |
| `brand_sentiment` | aggregate of mention sentiments: any `mixed`, or both positive and negative → `mixed`; else negative > positive > neutral; all unknown → `unknown` |
| `brand_strength` | the strongest `recommendation_strength` (`strong` > `moderate` > `weak` > `none` > `unknown`) |
| `recommended` | mentioned **and** strength ∈ {moderate, strong} **and** sentiment ≠ negative |
| `brand_cited` | any citation whose domain (or URL host) equals or is a subdomain of one of the project's configured domains (`www.` stripped) |
| competitors | one entry per distinct competitor name, same min-position / strongest-strength / aggregated-sentiment rules |

Nothing is persisted: metrics are recomputed on each request from stored
observations, so a parser reprocess or a methodology change is reflected
immediately and identically across all periods.

## 2. Metrics

All rates are over the eligible responses `N` in the period.

| metric | definition | component sample |
|---|---|---|
| **Mention Rate** | responses mentioning the brand / N | N |
| **Recommendation Rate** | responses with `recommended` / N | N |
| **Average Position** | mean of `brand_position` over mentions that have a position (informational, not a component) | mentions with a position |
| **Position Score** | mean of position points over mentions with a position: 1st = 100, 2nd = 85, 3rd = 70, 4th = 55, 5th = 40, 6th+ = 25. Mentions without a list position are **excluded**, not scored as 0 | mentions with a position |
| **Citation Rate** | responses with `brand_cited` / N | N |
| **Sentiment Score** | mean over mentions with known sentiment: positive = 100, mixed = 50, neutral = 50, negative = 0. `unknown` excluded | mentions with known sentiment |
| **Competitive Score** | brand mention count vs the most-mentioned *configured* competitor: 100 if brand ≥ top competitor, else `brand / top × 100`. **Unavailable** when no competitors are configured or when neither the brand nor any configured competitor is mentioned | N |
| **Competitor Share** (`/competitors`) | per name: mentions, mention rate, recommendation rate, average position, sentiment, share of voice (`mentions / Σ mentions` across brand + configured competitors) | N |

The position point table is an initial heuristic; it will be revisited once
enough real observations exist to calibrate it.

Brands that appear in responses but are not configured as competitors are
ignored by the competitive score and the competitor table. Adding a competitor
never penalises the brand retroactively for brands that were not configured.

## 3. Score

```
score = Σ (weight_c × value_c) / Σ weight_c      over components whose value is available
```

| component | weight |
|---|---|
| mention_rate | 25 |
| recommendation_rate | 25 |
| position_score | 15 |
| citation_rate | 15 |
| sentiment_score | 10 |
| competitive_score | 10 |

Each component is already on a 0–100 scale. An **unavailable** component
(`value: null`) drops out and the remaining weights renormalise; it is never
treated as 0. Each component in the response carries its own `sample` and a
`note` describing its derivation.

## 4. Data sufficiency and rounding

| eligible responses | `sufficiency` | score | rounding |
|---|---|---|---|
| < 5 | `insufficient` | **withheld** (`null`) — rates are `null` too; raw counts (sample size, sentiment counts) remain visible | — |
| 5–19 | `low` | shown | nearest 5 |
| 20–49 | `moderate` | shown | integer |
| ≥ 50 | `high` | shown | one decimal |

A score is never shown with more precision than its sample supports, and an
empty or tiny sample is reported as *unavailable*, never as 0.

Every score payload includes `data_quality`: `sample_size`, `sufficiency`,
`providers` (+ `provider_keys`), `models`, `prompts`, `date_range` (first/last
observation actually used), `parser_versions` seen, and `minimum_sample`.

## 5. Time dimension

Windows: `7d`, `30d`, `90d` (query `?window=`; default `30d`). The *current*
period is `[now − W, now)`; the *previous* period is the same length
immediately before it. `change = current.score − previous.score` (1 decimal);
`trend` is `up`/`down` when |change| ≥ 2 points, `flat` below that, and
`unavailable` with a `reason` when either period's score is withheld.

`/visibility/trends` returns the three window comparisons plus a `series` of
7-day buckets across the last 90 days, each with its own score, rates, sample
size and sufficiency. Buckets below the minimum sample show `null` scores.
`series_by_provider` repeats the same buckets per provider key, and
`series_by_competitor` gives the mention rate per bucket for `brand` and each
configured competitor (for the trend chart's provider/competitor views).

## 6. Breakdowns

* `/visibility/by-engine` — the same metrics per provider and per
  provider/model, each with its own `data_quality`.
* `/visibility/by-prompt` — per prompt (compact row: counts, rates, score,
  sufficiency — per-prompt samples are usually small, so expect `null` scores),
  and full metrics per prompt category and per funnel stage.
* `/visibility/competitors` — the competitive score and the share table.

## 7. API

All routes are read-only and require `DATA_READ` on the project's organization
(viewer and above). Non-members receive 404.

```
GET /api/v1/projects/{project_id}/visibility?window=30d
GET /api/v1/projects/{project_id}/visibility/trends
GET /api/v1/projects/{project_id}/visibility/by-engine?window=30d
GET /api/v1/projects/{project_id}/visibility/by-prompt?window=30d
GET /api/v1/projects/{project_id}/visibility/competitors?window=30d
```

## 8. Known limitations

* Mentions/positions/sentiment come from the response parser; parser quality
  bounds metric quality. `parser_versions` is reported so mixed-version periods
  are visible.
* Position is only meaningful for list-style answers; prose mentions have no
  position and are excluded from the position component.
* Citation matching is by domain only; links to the brand hosted on third-party
  domains (app stores, marketplaces) do not count.
* The score is computed over whatever mix of prompts/providers ran in the
  period. Comparing periods with different prompt sets or providers compares
  different things — the `prompts` and `providers` counts are there to notice.
