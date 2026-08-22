# Technical SEO Health Score (v1)

`method: technical-seo-health-score/v1` — implemented in `apps/api/app/seo/scoring.py`.

## What it is, and what it is not

The score is a **preliminary, internal 0–100 indicator** derived entirely from the observations of one audit. It is computed *after* the observations exist and never influences them. It lets a project compare itself with itself over time (did the number go up after the fixes?). It is **not** an industry-standard metric, does not predict rankings or traffic, and is not comparable with scores from other tools. Treat the observations as the product and the score as a summary of them.

Every audit stores `score_breakdown` with the exact weights, caps and per-finding deductions used, so any score can be re-derived by hand.

## Formula

```
score          = max(0, 100 − Σ_category min(cap_category, raw_category))
raw_category   = Σ_{finding in category} weight(severity) × spread(finding)
spread         = clamp(affected_pages / html_pages, MIN_SPREAD=0.25, 1.0)
```

`html_pages` is the number of crawled pages that returned HTTP 200 with HTML (`summary.html_pages`). `affected_pages` is 1 for page-level findings, or the `count` in a site-wide finding's evidence (e.g. 7 orphan pages), capped at `html_pages`.

### Severity weights

| Severity | Weight |
|---|---|
| critical | 25 |
| high | 12 |
| medium | 6 |
| low | 2 |
| info | 0 (never deducts) |

### Category caps

A single category can never remove more than its cap, so one pervasive problem type cannot zero the score on its own. Caps sum to 113, so a site that is broken everywhere bottoms out at 0.

| Category | Cap |
|---|---|
| indexability | 25 |
| http | 20 |
| internal_links | 15 |
| canonicalization | 15 |
| metadata | 15 |
| mobile_html | 10 |
| headings | 8 |
| structured_data | 5 |

### Why `spread` and `MIN_SPREAD`

A missing title on 1 of 500 pages should not cost as much as on 1 of 4. Scaling by the affected share makes the deduction proportional to how much of the site is touched. The 0.25 floor keeps a one-off high-severity issue visible on large sites (a single 5xx still costs 12 × 0.25 = 3 points).

## Worked example

Site with 10 HTML pages, 10 pages missing a title (each a page-level `high` finding):

- each finding deducts 12 × max(0.25, 1/10) = 3.0 → raw metadata deduction 30.0
- metadata cap is 15 → applied 15.0
- score = 100 − 15 = **85.0**

The audit's `score_breakdown.categories.metadata` reads `{"raw_deduction": 30.0, "cap": 15.0, "applied_deduction": 15.0, "contributions": [...]}` with one contribution per finding.

## How severities are assigned

Severity is set per check in `apps/api/app/seo/checks/*.py`, using context rather than a fixed table — for example a missing title is `high` on an indexable page and `low` on a `noindex` page; `noindex` itself is `info` unless more than 20 % of HTML pages carry it; a 404 is `medium`, other 4xx `low`, 5xx `high`. `critical` is reserved and currently unused by v1 checks. Each observation's `evidence` JSON records the facts (URLs, counts, lengths, status codes) the severity was based on.

## Changing the methodology

Change the weights or caps only together with a version bump of `method` (`…/v2`) so historical audits remain interpretable. Scores across method versions must not be compared.
