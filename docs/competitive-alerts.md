# Competitive AI Alerts (Milestone 5F)

Detects **meaningful** changes in AI search visibility by comparing two
adjacent periods (default 7 days each) of the same observations the 5C engine
uses, plus novelty in discovery, citations, claims and content gaps.
Insignificant changes never alert: every rule has a configurable threshold and
a minimum sample in **both** periods, and raw (unrounded) shares are compared
so presentation rounding can't push a change over a threshold.

Code: `apps/api/app/alerts/` (`rules.py` pure, `engine.py` detection +
persistence, `notifications.py` delivery design), model
`app/models/alerts.py` (`competitive_alerts`), routes
`app/api/v1/routes/alerts.py`. Analysis version `competitive-alerts/v1`.

## Alert types and rules

| type | fires when (defaults) | base severity |
|---|---|---|
| `visibility_drop` | brand mention share falls ≥ **10** points between periods | high |
| `competitor_visibility_jump` | a competitor's mention share rises ≥ **15** points | medium |
| `competitor_overtakes_brand` | competitor was level/behind on the competitive score in the previous period and now leads by ≥ **5** points | high |
| `citation_gap_increase` | (competitor − brand) citation-share gap widens by ≥ **15** points and is positive | medium |
| `new_competitor` | a discovery candidate (5B) first seen this period with confidence ≥ **0.4**, still unreviewed | low/medium |
| `new_citation_source` | a domain cited ≥ **2** times this period that was never cited for the project before | low |
| `new_competitor_claim` | claims about a configured competitor whose normalized subject-predicate-object triple was not seen before this period | low/medium |
| `content_gap` | a new (unreviewed) 5E content gap created this period with opportunity ≥ **60** | medium/high |

Severity escalates one level when the change is ≥ 2× its threshold. Rate-based
rules require ≥ **10** responses per period (`min_responses`).

## Configurable thresholds

`AlertThresholds` (`brand_drop_points`, `competitor_jump_points`,
`overtake_margin_points`, `citation_gap_increase_points`, `min_responses`,
`new_source_min_citations`, `new_competitor_min_confidence`,
`content_gap_min_score`) can be overridden per detection call
(`POST …/detect {"window_days": 7, "thresholds": {...}}`); unset fields keep
their defaults, and the thresholds used are echoed in the result and stored in
each alert's evidence.

## Evidence

Every alert carries: `previous_measurement`, `current_measurement`,
`date_range` (both periods), `affected_prompts` (up to 10),
`affected_providers`, `confidence` (from the smaller period sample: high ≥ 50,
medium ≥ 20, else low), the thresholds used, and rule-specific numbers
(change points, margin, gap points, example URLs / claims).

## Deduplication and status

`(project_id, dedup_key)` is unique, where the key is
`type:subject:fingerprint` (subject = competitor / domain / topic;
fingerprint = a hash of the change). Re-detecting the same situation updates
the existing row's evidence and `detected_at` and never touches `status` —
a **dismissed alert stays dismissed** and a read one stays read. A genuinely
new change (different fingerprint) creates a new alert.

Status: `new` → `read` / `dismissed` (and back) via
`PATCH /competitive-alerts/{id}`. Listings report an `unread` count.

## Notifications (future)

`app/alerts/notifications.py` defines the delivery seam: a
`NotificationChannel` protocol (`send(alert)`) and a `NotificationDispatcher`
the engine hands newly created alerts to. Email, Slack, Teams and generic
webhook channels are documented as future implementations; none are
implemented and no external calls are made — the dispatcher only logs.

## API (non-members 404)

| method | path | permission |
|---|---|---|
| GET | `/projects/{project_id}/competitive-alerts` (filters `status`, `alert_type`, `severity`, `competitor_id`; ordered severity → recency) | DATA_READ |
| POST | `/projects/{project_id}/competitive-alerts/detect` | DATA_MANAGE |
| GET / PATCH | `/competitive-alerts/{alert_id}` (PATCH sets status) | DATA_READ |

## Tests

`apps/api/tests/alerts/test_alerts.py`: threshold detection with full evidence
(drop / jump / overtake), custom thresholds suppressing everything, citation
gap increase, false-positive prevention (sub-threshold change on rounded-share
edge; huge swing on a tiny sample), severity escalation, novelty alerts
(new source vs already-known source, new vs pre-existing claims, discovery
candidate, content gap), deduplication (re-run updates, dismissed stays
dismissed), status changes + filters, tenant isolation.
