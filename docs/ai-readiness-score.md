# AI Readiness Score (v1)

`method: ai-readiness-score/v1` — implemented in `apps/api/app/ai_readiness/scoring.py`.

## What it is, and what it is not

The AI Readiness Score is an **internal product metric**. It summarizes deterministic signals about how clearly a website communicates its entities, offerings, authorship and evidence — signals that are useful to readers and to any system that has to understand the site, AI assistants included.

It is **not** an industry standard, it is not derived from any AI system's behaviour, and it does not measure or predict visibility, citations or rankings in ChatGPT, Gemini, Claude, Perplexity or search engines. The analyzer never queries those systems. Treat the observations as the product; the score is a way to compare a site with itself over time.

Every audit stores `score_breakdown` with the category values, the formula used for each, and the raw inputs, so any score can be recomputed by hand.

## Formula

```
score = 100 × Σ_c (weight_c × value_c) / Σ_c weight_c      over applicable categories c
```

| Category | Weight | value_c (0..1) |
|---|---|---|
| entity_clarity | 25 | share of 6 entity signals present: company name, organization description, products/services, target audience, geographic coverage, contact information |
| product_clarity | 20 | mean over product/service pages of 7 aspects: name, description, features, pricing, use cases, target customers, integrations |
| authority | 15 | mean over article pages of 6 aspects: author, author bio, organization, credentials, publication date, modified date |
| evidence | 15 | share of 7 evidence kinds detected anywhere: statistics, research, original data, citations, outbound references, case studies, customer evidence |
| content_structure | 15 | 0.6 × min(1, avg specific-sentence ratio / 0.30) + 0.2 × (1 − thin-page share) + 0.2 × (1 − unstructured-page share) |
| faq | 5 | 0.5 if FAQ-style content exists + 0.5 if FAQPage schema exists |
| factual_consistency | 5 | 1 − (entity value conflicts / entities compared) |
| comparison | 0 | **never scored** — presence of comparison pages is recorded only |

A category is *not applicable* when the site has nothing to assess (no product/service pages, no article pages, no content pages, no comparable entities). Its weight is dropped and the remaining weights are renormalized, so a brochure site without a blog is not penalized for lacking bylines.

### Worked example

A site with entity_clarity 1 of 2 checks (0.5) and FAQ content but no schema (0.5), with every other category inapplicable: score = 100 × (0.5 × 25 + 0.5 × 5) / 30 = **50.0**.

## How signals are detected

All detection is lexical and structural — regular expressions over the cleaned page text and headings, page-kind classification by path and schema type, and the entity layer from Milestone 2D (`apps/api/app/ai_readiness/signals.py`, `context.py`). Each observation's `evidence` carries the matched snippets, URLs or counts so the basis of the signal is visible. The limits of this approach are stated in the observations themselves (e.g. "lexical detection", "recorded as a signal, not a defect"); keyword counts are not presented as optimization.

## Changing the methodology

Change weights, thresholds (`SPECIFICITY_TARGET`, `THIN_PAGE_WORDS`, …) or category formulas only together with a version bump of `method` so historical audits remain interpretable; scores across versions must not be compared.
