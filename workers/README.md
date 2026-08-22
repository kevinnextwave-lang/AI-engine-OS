# workers/

Deployment home for background workers. In the modular monolith the worker
**code** lives in `apps/api/app/workers/` (Celery app + tasks) so it shares the
API's models, services and configuration. This directory holds everything needed
to run that code as separate processes:

- `Dockerfile` — same image as the API, different entrypoint.

Queues are already routed by domain (`default`, `crawler`, `ai_search`, `agents`,
`analytics`), so a queue can be moved onto its own worker fleet — or extracted
into its own service — without changing task code.

The full job system (retries, scheduling, result storage) is a later milestone.
