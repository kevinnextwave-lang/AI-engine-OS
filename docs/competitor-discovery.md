# AI Competitor Discovery (Milestone 5B)

Discovery finds companies that *may* compete with the project and stores them
as **competitor candidates**. A candidate is never a competitor until a person
accepts it; accepting creates a competitor (source `discovered`) through the
5A `CompetitorService`, with all of its duplicate checks. Rejected names stay
rejected across re-runs.

Code: `apps/api/app/discovery/` (`extract.py`, `schema.py`, `service.py`),
model `app/models/competitor_candidates.py`, routes
`app/api/v1/routes/discovery.py`, migration `e09c3c62daaf`.

## Sources

| source | what it looks at | how it contributes |
|---|---|---|
| `ai_responses` | completed, parsed AI responses in the window (default 90 days) | list items with a proper-name label ("1. **Xero** — …"), "alternatives to X", "competitors such as A, B and C", "X vs Y" phrasing; URLs in the same block whose host matches the name become the candidate's domain evidence |
| `website_intelligence` | `Organization` / `Brand` entities the crawler extracted from the customer's own site | a weak hint that only enriches a name already seen elsewhere (a company page mentioning a partner is not a competitor signal on its own) |
| `ai_assisted` | the first configured AI provider, asked with the project profile (name, website, description, products, services, known competitors) | must return strict JSON validated by `AICandidateList` (`extra="forbid"`, ≤ 25 items, name 2–200 chars, normalised domain or null, reason, confidence 0–1). Anything else is discarded and reported in `ai_error`; the prompt is a plain request for facts, never an instruction to act |

Excluded from every source: the brand, the project's own domains, configured
competitors with their aliases, products and domains — including editions and
sub-products of a known competitor ("QuickBooks Online" when QuickBooks is
configured, `is_known_identity`).

A name seen in a **single response** and by no other source is not written at
all (`MIN_RESPONSES_FOR_CANDIDATE = 2`; counted in
`candidates_skipped_single_mention`).

## Confidence

`confidence` (0–1) is a weighted sum; the components and weights are stored
in `evidence.confidence` so the number is always explainable.

| component | weight | definition |
|---|---|---|
| frequency | 0.30 | responses mentioning the name, log-scaled, 1.0 at ≥ 10 |
| relevance | 0.20 | 0.6 × share of those responses that also mention the brand or a known competitor + 0.4 × share of commercial prompts (comparison / recommendation / pricing / alternative, or consideration / decision / purchase stages) |
| domain_confidence | 0.15 | 1.0 when a matching host appeared in a cited URL, 0.6 when only the AI supplied a domain, else 0 |
| competitor_language | 0.20 | share of observations with direct competitor language (alternative, competitor, vs, similar to, instead of…) |
| cross_provider | 0.15 | AI engines that produced the name ÷ engines seen in the window |

Labels: high ≥ 0.70, medium ≥ 0.40, otherwise low. An AI-only suggestion gets
frequency 0, language 0.5 and half its stated confidence as relevance, so it
cannot exceed "low/medium" until stored answers corroborate it.

## Evidence

`evidence` (JSONB) records: `responses`, `observations`, `prompts` (up to 10
prompt texts the name appeared in), `prompt_count`, `co_occurring_responses`,
`commercial_prompts`, `providers` (engines that produced it), `providers_seen`,
`competitor_language_hits`, `average_position`, `domains_observed`,
`examples` (short context snippets), `ai` (provider, model, reason, stated
confidence, category, domain) when used, `website` hint, `sources`,
`confidence` components/weights and `discovery_version`.

## Re-runs and duplicates

Candidates are unique per project on the normalised name. Re-running discovery
upserts evidence, confidence, reason, source and domain; `status`,
`reviewed_at`, `reviewed_by_user_id` and `competitor_id` are never touched, so
reviews survive. Accepted candidates become known identities and are excluded
from the next run's extraction (their row keeps `status = accepted`).

## API

| method | path | permission | notes |
|---|---|---|---|
| GET | `/projects/{project_id}/competitor-candidates` | DATA_READ | filters `status`, `source`, `min_confidence`, `limit`, `offset`; ordered by confidence desc |
| POST | `/projects/{project_id}/competitor-candidates/discover` | DATA_MANAGE | body `{window_days 7–365, use_ai}`; returns counts, `ai_used`, `ai_error` |
| GET | `/competitor-candidates/{id}` | DATA_READ | project derived from the row; other tenants get 404 |
| POST | `/competitor-candidates/{id}/accept` | DATA_MANAGE | body `{website_url?, name?}`; `website_url` required (422) when the candidate has no domain; 409 when already accepted or when the competitor would duplicate an existing one; returns the created competitor |
| POST | `/competitor-candidates/{id}/reject` | DATA_MANAGE | 409 when already accepted |

## Tests

`apps/api/tests/discovery/test_discovery.py`: extraction from list / "vs" /
"alternatives to" phrasing with domain matching, strict AI schema (extra keys,
bad domains, too many items rejected), confidence components, evidence on
discovered candidates and the single-mention rule, duplicate handling and
status preservation across re-runs, invalid AI JSON discarded without failing
the run, accept / reject lifecycle with conflicts, and tenant isolation. No
live provider is called; the AI path uses a mocked transport.
