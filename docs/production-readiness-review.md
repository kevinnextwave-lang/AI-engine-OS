# Production-Readiness Review — AI Search Growth OS

Reviewed at commit `f79e77f` (Milestone 1D). Scope: the 25 areas requested, with emphasis on multi-tenant isolation. No code was changed for this review; findings are backed by the existing suite, eight new adversarial probe tests (`apps/api/tests/test_review_probes.py`, not yet committed), dependency audits, and manual inspection.

## Verification run

| Check | Result |
|---|---|
| `pytest` (84 tests, real Postgres) | 84 passed |
| `mypy app` (strict) | clean |
| `ruff check` / `ruff format --check` | clean |
| `alembic check` | models and schema in sync |
| `pip-audit` | no known vulnerabilities |
| `npm audit` (prod and dev) | 0 vulnerabilities |
| `eslint`, `tsc --noEmit`, `next build` | clean |
| Adversarial probes (8) | 6 passed, 2 failed → findings H2, M4; 1 passed-by-design → H1; 1 documents behaviour → M1 |

## Multi-tenant isolation (focus area)

Every path a user from Organization A could take to reach Organization B's data was exercised and held:

- Projects, domains, competitors, organization record, member list: all item routes return **404** for non-members (never 403, so existence is not leaked). Covered by `test_cross_tenant_access_is_blocked`, `test_organization_isolation`, `test_idor_on_project_ids`, `test_org_settings_of_other_tenant_unreachable`.
- Body-supplied `organization_id` on `POST /projects` is validated against membership (404 if not a member, 403 if a viewer) and the legacy `/organizations/{id}/projects` route ignores the body entirely (`test_organization_id_in_body_is_ignored`, `test_viewer_cannot_create_project_via_body_selector`).
- Mixed identifiers (own org id in the path + another tenant's project id, or own competitor id under another tenant's project) are rejected (`test_legacy_org_route_cannot_be_used_to_reach_other_tenant`).
- Soft-deleted organizations disappear from lists and item routes (`test_soft_deleted_org_projects_not_listed`).
- All queries go through the ORM with bound parameters; the only raw SQL is constant DDL/data statements inside migrations. No SQL injection surface found.

The design is sound: `organization_id` is never read from a body for authorization, item routes derive the tenant from the row, and domains/competitors are reached only through a project whose organization membership was verified. **No cross-organization access vulnerability was found.** The isolation gaps that do exist are about *state* (suspended orgs, deleted users), listed below.

---

## Critical issues

None found. Nothing allows cross-tenant reads or writes, credential theft, or injection.

---

## High-priority issues

**H1. Rate limiter is bypassable via `X-Forwarded-For`** — `app/api/deps.py::client_ip`
The limiter keys on the first value of `X-Forwarded-For` whenever the header is present, and the header is trusted from any client. Probe `test_rate_limit_bypass_via_x_forwarded_for` sent 12 failed logins with rotating spoofed addresses and never received a 429. Login brute-force protection is therefore advisory only. Conversely, without uvicorn `--proxy-headers`, a deployment behind Railway's proxy that *did* strip the header would bucket every user under the proxy's IP.
*Fix:* run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy CIDR or "*" when only the platform proxy can reach the app>` so Starlette resolves `request.client.host` from the trusted hop, and make `client_ip()` use `request.client.host` only. Add a per-account limiter key (email) for `/login` so rotating IPs does not help.

**H2. `organizations.status = suspended` is not enforced** — `app/api/deps.py::_org_is_usable`
Only `deleted` is checked. Probe `test_suspended_organization_is_blocked` shows a suspended org can still read and create projects. The `status` column exists precisely for billing/abuse holds, so today it has no effect.
*Fix:* treat `SUSPENDED` as read-only or fully blocked (decide product behaviour) in `_org_is_usable` / a new `require_active_organization`, return 403 with code `organization_suspended`, and filter suspended orgs out of `POST /projects` resolution.

**H3. Database commit happens after the response is sent** — `app/db/session.py::get_db_session`
With FastAPI 0.141 the exit block of a `yield` dependency runs after the response has been streamed. Verified empirically: a dependency that raises on exit still yields HTTP 200. A commit that fails (serialization failure, connection drop, deferred constraint) therefore returns success to the client while the write is lost, and the error only appears in logs.
*Fix:* commit explicitly before returning from the service/route layer (e.g. a `UnitOfWork`/`commit()` helper called at the end of each mutating service method, or a small middleware that commits before the response is built), keep the dependency's rollback-on-exception, and add a test that a failing commit surfaces as 500.

**H4. No account recovery or email verification**
`email_verified` is stored but never set or enforced; there is no password reset. For a production SaaS this means locked-out users have no self-service path, and anyone can sign up with an address they do not own (later tying billing and audit records to it).
*Fix:* add verification + reset tokens (single-use, hashed at rest like refresh tokens, short TTL), an email provider interface behind `services/`, and gate sensitive actions on `email_verified`.

---

## Medium issues

**M1. Access tokens survive `logout-all` and account deactivation for up to 15 min**
JWTs are stateless; `logout-all` only revokes refresh tokens (documented by probe `test_access_token_survives_logout_all`). Acceptable for many products, but a compromised access token or a deactivated employee keeps API access until expiry.
*Fix options:* (a) keep 15-min TTL and document it; (b) add `users.token_version` (bumped on logout-all / password change / deactivation) and embed it in the JWT, checked in `get_current_user` — one indexed integer compare, no Redis; (c) a Redis denylist by `jti`.

**M2. CSRF on the cookie-bearing `/auth/refresh` and `/auth/logout` when `COOKIE_SAMESITE=none`**
With the default `lax` and a POST-only endpoint, browsers will not attach the cookie cross-site, and CORS blocks reading the response. The README tells deployers to switch to `none` when web and API are on different registrable domains, which re-enables cross-site cookie sending; CORS still prevents reading the minted access token, but `/auth/logout` becomes a cross-site logout vector and the refresh rotation can be triggered (invalidating the victim's token family on the next legitimate refresh → forced logout).
*Fix:* require a custom header (e.g. `X-Requested-With: fetch`, which cannot be set cross-origin without a CORS preflight) or an Origin allow-list check on cookie-authenticated endpoints; prefer deploying web and API under one registrable domain so `lax` stays.

**M3. Redis is probed once at startup; an outage degrades to a per-process in-memory limiter permanently**
`main.py` sets `app.state.redis = None` if the ping fails and never retries; `RedisRateLimiter.hit` also fails open on any error. With several API replicas this silently multiplies every limit by the replica count.
*Fix:* keep the client regardless of the startup ping (the client reconnects lazily), fail open only for a bounded window with a warning metric, and expose Redis status in `/health`.

**M4. Soft-deleted users remain in organization member lists** — probe `test_deleted_user_membership_not_listed`
`MembershipRepository.list_for_organization` does not join on `users.deleted_at IS NULL`. Deleted users cannot authenticate, but their rows (email, name) are still shown to the organization and counted toward any future seat logic.
*Fix:* filter on `User.deleted_at.is_(None)` in the repository; on user soft-delete, also revoke memberships (or delete membership rows) in the service.

**M5. Containers run as root; no image healthcheck** — `apps/api/Dockerfile`, `workers/Dockerfile`
Both images install `build-essential` into the runtime layer and run uvicorn/celery as root.
*Fix:* multi-stage build (wheels in a builder stage), `RUN useradd -r app && USER app`, drop build tools from the final image, add `HEALTHCHECK`.

**M6. Migrations run on every replica start** — `railway.toml` `startCommand`
`alembic upgrade head && uvicorn …` executed concurrently by N replicas can race (Alembic does not lock). Works today with one replica.
*Fix:* run migrations as a Railway pre-deploy command / one-off job, and start uvicorn only.

**M7. No browser security headers on the web app**
`next.config.ts` sets no `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors`, `Referrer-Policy`, or `Permissions-Policy`. React escaping and zero `dangerouslySetInnerHTML` usages mean no XSS sink was found, but a CSP is the safety net that keeps a future mistake from exposing the in-memory access token.
*Fix:* add a `headers()` block with a nonce-less CSP (`default-src 'self'; connect-src 'self' $API_URL; img-src 'self' data:; style-src 'self' 'unsafe-inline'`), `frame-ancestors 'none'`, `Referrer-Policy: strict-origin-when-cross-origin`.

**M8. Unbounded growth of `refresh_tokens` and `auth_audit_logs`**
Nothing expires rows. Refresh tokens are created per login/refresh (every 15 min per active user) and kept forever; audit logs likewise.
*Fix:* a Celery beat task (`default` queue) deleting refresh tokens past `expires_at + 30d` and audit rows past a retention window (e.g. 180d); add an index on `refresh_tokens.expires_at`.

**M9. Frontend has no automated tests and CI does not run the Playwright flow**
The e2e script used during development lives outside the repo. Regressions in the auth/refresh flow would only be caught manually.
*Fix:* commit a Playwright smoke suite (`apps/web/e2e/`) and run it in CI against the API service.

---

## Low-priority improvements

**L1. `list_projects` does an N+1 existence check** (`routes/projects.py`): one `get_by_id` per organization to drop soft-deleted orgs. Use the already-loaded `membership.organization` (it is `selectinload`-ed) and filter in Python, or push the `deleted_at IS NULL` predicate into the project query via a join.

**L2. `get_project_access` always `selectinload`s domains**, even for competitor-only routes. Minor; make the load optional or accept the small cost.

**L3. No global rate limit.** Only signup/login/refresh are limited; `rate_limit_default_per_minute` exists in settings but is unused. Apply it as a router-level dependency for authenticated routes (keyed by user id) before opening to the public.

**L4. Organization creation is unlimited** (`POST /organizations`). Combined with free signup this is a cheap way to bloat the database. Rate-limit it and/or cap orgs per user on the free plan.

**L5. Health endpoint is liveness only.** `/health` never touches Postgres or Redis. Add a `/health/ready` that does, for Railway's healthcheck.

**L6. JWT claims lack `iss`/`aud`.** Harmless while there is one issuer and one audience; add them now so a future second service cannot accept tokens meant for this one.

**L7. Logging**: structlog is configured well (JSON in prod, no secrets found in log calls). Request-level context (request id, user id) is not bound via `contextvars`, so correlating a user's requests in logs requires grepping. Add a middleware that binds `request_id` and, after auth, `user_id`.

**L8. Code duplication**: the organization→response mapping is hand-built in both `routes/organizations.py` and `services/organizations.py`; `register = signup` and the `/register` alias can be removed once the web client is confirmed on `/signup` (it is). `ProjectService.create` and `create_project_in_organization` duplicate argument plumbing — a `ProjectCreateInput` dataclass would remove it.

**L9. Dependency pinning**: `pyproject.toml` uses lower bounds only; `requirements.txt` mirrors them. For reproducible deploys generate a lock (`uv lock` / `pip-compile`) and install from it in the Dockerfile. Next 16.3 / React 19.2 are newer than this reviewer's training data; they built and passed e2e, but keep an eye on the `react-hooks/set-state-in-effect` rule changes in future minor versions.

**L10. CI gaps**: no `pip-audit`/`npm audit`, no secret scanning, no Docker build. All cheap to add.

**L11. Test fixtures create the schema from `Base.metadata` rather than by running migrations**; `alembic check` in CI covers drift, but a test that runs `alembic upgrade head` on an empty database and then the suite would catch a migration that is valid-but-wrong (e.g. missing data backfill).

**L12. `.env` handling**: root `.env.example` duplicates keys that live in `apps/api/.env.example`; keep one source and have `scripts/bootstrap.sh` derive the other. The root file's `POSTGRES_PASSWORD=postgres` is fine for docker-compose but worth a comment that it must never be used for a reachable database.

---

## What is in good shape

- Password hashing (Argon2id), uniform login errors, HMAC-keyed refresh tokens with rotation and family revocation, audit trail without secrets.
- Tenant scoping model and the `require_project_access` pattern; 404-over-403 for non-members.
- Consistent error envelope; field-level validation errors; OpenAPI descriptions.
- Migrations are reversible and were exercised up/down with data.
- Type safety end to end (mypy strict, TS strict, shared types package).
- Zero known-vulnerable dependencies.

---

## Recommended fix order

1. **H1** proxy-aware client IP + per-email login limiter — small, high impact.
2. **H3** explicit commit before response — small change in `session.py`/services plus one test.
3. **H2** enforce `suspended` — small.
4. **M4** hide deleted users from member lists; **M3** Redis resilience — small.
5. **M1** `token_version` claim — moderate; **M2** CSRF header check — small.
6. **M5/M6** Dockerfile hardening and migrations as a pre-deploy step — infra-only.
7. **M7** security headers — small.
8. **H4** email verification + password reset — a feature; schedule as its own milestone.
9. **M8, M9, L-items** as hygiene in following iterations.

Items 1–7 are contained, non-architectural changes that I can implement in one pass on your go-ahead.
