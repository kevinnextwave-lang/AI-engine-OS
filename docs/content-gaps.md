# Competitive Content Gap Engine (Milestone 5E)

Finds **topics where competitors appear in AI responses while the customer's
website has weak or missing coverage**. Everything is observed: competitor
visibility comes from parsed responses (mentions per prompt), customer coverage
from the crawled site's pages (title, meta description, URL, word count), and
evidence from citations with `citation_entities` attribution. Content is never
recommended blindly — every gap requires a real competitor lead, a minimum
sample, and records exactly what was and wasn't found.

Code: `apps/api/app/content_gaps/` (`topics.py` pure extraction/classification/
scoring, `engine.py` gathering + persistence), model
`app/models/content_gaps.py` (`content_gaps`), routes
`app/api/v1/routes/content_gaps.py`. Analysis version `content-gaps/v1`.

## Topics and coverage

A topic is derived from each prompt in the analyzed set: stop words and generic
category words ("best", "software", "platforms"…) are removed, leaving content
keywords (e.g. "What are the best accounting platforms for construction
companies?" → `accounting construction companies`). A crawled page covers the
topic when at least half of its keywords appear in the page URL, title or meta
description. Coverage strength: a substantial matched page (≥ 300 words) counts
1.0, a thin one 0.4, capped at 1.0. Matched pages are also categorized
(comparison / faq / use_case / product / educational) from URL and title.

## Gap types

Gaps are only produced when the topic has ≥ 5 responses, the most-visible
competitor appears in ≥ 40% of them, and its rate exceeds the brand's by ≥ 20
points.

| type | when |
|---|---|
| `missing_topic` | no matching page at all, and the prompt calls for no specific page type |
| `weak_topic` | matching pages exist but coverage strength < 1 (thin or too few) |
| `missing_comparison` | comparison/alternative prompt and no comparison-type page (either none at all, or the topic is covered but not with a comparison page) |
| `missing_use_case` | industry / "for &lt;segment&gt;" prompt and no use-case/industry page |
| `missing_faq` | how/can/does-style or problem-solution prompt and no FAQ/help page ("what/which are the best…" prompts are recommendation questions, not FAQ) |
| `missing_product_detail` | pricing/product/integration prompt and no product-detail page |
| `missing_evidence` | responses on the topic cite research-type sources tied to competitors while the brand is never cited on the topic |

## Opportunity Score (0–100)

    30 · competitor_advantage   (top competitor − brand mention rate on the topic)
    25 · prompt_frequency       (responses on the topic, saturating at 10)
    20 · commercial_relevance   (1.0 commercial category/stage, 0.4 informational)
    15 · coverage_deficit       (1 − coverage strength)
    10 · evidence_availability  (citations observed on the topic)

Components and weights are stored in `competitor_evidence.scoring`. Confidence:
high ≥ 20 responses on the topic, medium ≥ 10, low ≥ 5.

## Persistence

`content_gaps` is unique on (project, normalized topic, gap type). Re-analysis
upserts evidence and score; `status` and `note` survive; rows still `new`
whose evidence disappeared (e.g. the site gained a substantial matching page)
are removed. `competitor_evidence` records the prompt, responses, providers,
per-competitor mentions, rates, citations and research domains;
`customer_coverage` records matched pages with word counts, categories and the
coverage band.

## API (non-members 404)

| method | path | permission |
|---|---|---|
| GET | `/projects/{project_id}/content-gaps` (filters `gap_type`, `status`, `min_score`; ordered by score) | DATA_READ |
| POST | `/projects/{project_id}/content-gaps/analyze` (`{window_days}`) | DATA_MANAGE |
| GET | `/content-gaps/{gap_id}` | DATA_READ |
| PATCH | `/content-gaps/{gap_id}` (`status`, `note`) | DATA_MANAGE |

## Limits

Competitor websites are not crawled; their side of "coverage" is what AI
responses showed (mentions, citations, research sources), not their sites'
actual content. Topic/page matching is keyword-based and conservative — a page
can cover a topic under vocabulary the matcher doesn't connect; gaps are leads
to review, not verdicts.

## Tests

`apps/api/tests/content_gaps/test_content_gaps.py`: keyword extraction and
page matching, missing topic (incl. the construction example as a use-case
gap), weak coverage, substantial coverage producing nothing, comparison gaps,
FAQ gaps, evidence gaps, scoring components/weights and classification gates,
PATCH lifecycle surviving re-analysis, stale-row removal, and tenant
isolation.
