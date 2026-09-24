# Alert Notifications & Scheduled Monitoring

Completes the delivery seam Milestone 5F designed: competitive alerts can now
leave the app through **signed webhooks**, and a **scheduled monitoring** task
re-runs detection daily for projects with fresh data. Email / Slack / Teams
remain design notes in `app/alerts/notifications.py` — no external providers
are integrated.

Code: `app/alerts/delivery.py` (WebhookChannel + orchestration),
`app/models/notification_channels.py` (migration `c09256688932`),
`app/api/v1/routes/notification_channels.py`, `app/monitoring/scheduler.py`,
worker tasks `app.workers.tasks.notifications.*` /
`app.workers.tasks.monitoring.run_scheduled_monitoring`.

## Webhook channels

A project can register any number of channels
(`POST /projects/{id}/notification-channels`, DATA_MANAGE). Each holds a name,
a target URL and an optional signing secret.

- **Payload**: `{"event": "competitive_alert", "alert": {id, project_id,
  alert_type, title, description, severity, status, evidence, detected_at}}`,
  POSTed as JSON with the `AI-Search-Growth-OS/1.0` user agent.
- **Signing**: when the channel has a secret, `X-ASG-Signature:
  sha256=<hex HMAC-SHA256 of the raw body>`. The secret is **write-only** — no
  API response contains it and it is never logged.
- **SSRF policy**: targets pass the same safety layer as the crawler. Create /
  update reject non-HTTP(S) schemes, credentials in URLs, localhost, `.internal`
  style hosts and private-address literals immediately; every delivery then
  resolves DNS, requires all addresses public, and pins the connection to the
  validated address (Host header + SNI preserved). A webhook can never reach
  the internal network or a cloud metadata endpoint.
- **Delivery** happens only in worker tasks, enqueued after commit — never in
  HTTP request handlers. Bounded retries with exponential backoff on 5xx/429;
  other 4xx are treated as permanent. Failures never raise: the outcome lands
  on the channel row (`last_delivery_at/status/error`), which the UI shows.
- `POST /notification-channels/{id}/test` queues a synthetic, never-persisted
  test alert to one channel (202; result appears on the row).

## When alerts are delivered

`POST /projects/{id}/competitive-alerts/detect` enqueues delivery for alerts
persisted **for the first time** in that run; re-detections that only update
existing alerts deliver nothing (no repeat notifications — dedup_key semantics
unchanged).

## Scheduled monitoring

`celery beat` (opt-in process: `celery -A app.workers.celery_app beat`) fires
`run_scheduled_monitoring` daily at `MONITORING_HOUR_UTC`. The task selects
projects with at least one completed AI response in the last
`MONITORING_ACTIVITY_WINDOW_DAYS` days, runs alert detection per project in
its own session (one tenant's failure never blocks the rest) and enqueues
webhook delivery for new alerts. `MONITORING_ENABLED=false` disables it
without redeploys.

## Tests

`tests/alerts/test_notifications.py` (no live network anywhere — fake
transports and resolvers): URL validation rejects file/localhost/metadata/
private/credentialed URLs; signed payload with pinned connect target; 4xx no
retry / 5xx bounded retries; private DNS resolution blocked without any
request; per-channel outcome recording; project scoping (foreign alert ids
never delivered); secret hygiene across every response; channel CRUD, tenant
isolation and role checks; the test endpoint queues to the worker; detect
enqueues delivery exactly once per new alert; scheduled monitoring selects
only recently active projects.
