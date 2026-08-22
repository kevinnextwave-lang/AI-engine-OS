# Prompt Quality Score (v1)

`method: prompt-quality-score/v1` — implemented in `apps/api/app/prompts/quality.py`.

The score (0–100) ranks generated and manual prompts inside a prompt set and sets their default priority. It is deterministic, computed only from the prompt text, the prompt's category and the business profile the set was generated from. It is an internal ranking aid, not a prediction of search volume or AI visibility.

## Formula

```
score = 100 × Σ_k weight_k × component_k / Σ_k weight_k     over applicable components k
```

| Component | Weight | How it is computed (0..1) |
|---|---|---|
| relevance | 0.30 | 0.6 if the prompt mentions the offering/industry, company or a product; + 0.2 per additional profile entity group mentioned (audience, competitor, descriptor/integration, geography), capped at 0.4 |
| uniqueness | 0.20 | 1 − max Jaccard similarity of content tokens against every other prompt in the set (see `normalize.py`; stop words removed, light stemming) |
| commercial_intent | 0.25 | category base (transactional 1.0, pricing 0.95, recommendation/comparison/alternative 0.85, local 0.80, product 0.70, problem_solution 0.50, discovery 0.35, industry 0.30) + 0.1 if a commercial marker appears (best, pricing, cost, alternatives, vs, compare, buy, demo, trial, sign up, recommend), capped at 1 |
| specificity | 0.15 | 0.4 if a named entity (competitor, company or product) is present + 0.3 if a qualifier (audience, feature/use case/integration or geography) is present + 0.3 if the prompt is 6–18 words (0.1 otherwise) |
| geographic_relevance | 0.10 | only when the profile lists a geographic market: 1.0 if the prompt names it, else 0.4. Not applicable (weight dropped) when no market is given |

### Priority

`priority_for(score)`: ≥ 80 → 1, ≥ 65 → 2, ≥ 50 → 3, ≥ 35 → 4, else 5 (1 is highest). Users can override priority on any prompt; a later text edit re-scores and, unless priority was set explicitly in the same request, re-derives it.

### Worked example

Profile: Ledgerly, accounting software, competitors QuickBooks/Xero, audience small businesses, market United Kingdom.

"Ledgerly vs QuickBooks: which is better for small businesses in the United Kingdom?" (comparison): relevance 1.0 (company + competitor + audience + geo), uniqueness ≈ 1.0, commercial 0.95, specificity 1.0, geo 1.0 → ≈ 97.

"What is software?" (discovery): relevance 0 (no offering term), commercial 0.35, specificity 0.1, geo 0.4 → ≈ 18, priority 5.

## Deduplication

`normalized_text` (NFKD, lower-case, punctuation stripped, single spaces) is unique per prompt set at the database level. Near-duplicates are rejected when content-token Jaccard similarity ≥ 0.8 (`is_near_duplicate`). No embeddings are used.

## Changing the methodology

Bump `method` when weights, thresholds or components change so stored `quality_breakdown` values stay interpretable.
