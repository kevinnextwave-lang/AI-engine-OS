# Architecture

AI Search Growth OS is a multi-tenant SaaS built as a **modular monolith**: one FastAPI backend, one Next.js frontend, one Postgres database, Redis for background jobs and rate limiting. Modules are separated by package boundaries and queue names so the heavy parts (crawler, AI search workers, agent orchestration, analytics) can be extracted into services later without a rewrite.

## Repository layout

```
apps/web            Next.js 16 app (TypeScript, Tailwind v4, shadcn/ui)
apps/api            FastAPI app (Python 3.11, SQLAlchemy 2 async, Alembic, Celery)
packages/types      Shared TS types mirroring the API's Pydantic schemas
packages/ui         Shared shadcn/ui primitives + Tailwind theme
packages/config     Shared tsconfig base
workers/            Worker image/deployment; code lives in apps/api/app/workers
infrastructure/     Deployment notes, future IaC
docs/               This folder
scripts/            bootstrap.sh, dev.sh, check.sh
```

npm workspaces link `apps/web` to the `packages/*`. Python is a single package under `apps/api`.

## Backend layering (`apps/api/app`)

```
api/v1/routes  →  services  →  repositories  →  models
     ↑                ↑
  api/deps.py      core/*  (config, security, logging, errors, rate limiting)
```

- **Routes** are thin: parse input, call one service, shape the response.
- **Services** own business logic and transaction boundaries.
- **Repositories** own queries. Soft-deleted rows are filtered here.
- **Models** use UUID primary keys, timezone-aware UTC `created_at`/`updated_at`, and `deleted_at` for soft deletion on major entities.
- **`db/session.py`** exposes `get_db_session`, a per-request dependency that commits on success and rolls back on error.

## Data model (Milestone 1B)

```
users ──< organization_members >── organizations ──< projects ──< domains
                                                              └──< competitors
```

- `users`: email (unique), password_hash, first_name, last_name, is_active, email_verified, last_login_at, soft-delete.
- `organizations`: name, slug (unique), plan (`free|starter|growth|pro|agency|enterprise`), status (`active|suspended|deleted`).
- `organization_members`: organization_id + user_id (unique together), role (`owner|admin|member|viewer`).
- `projects`: organization_id, name, slug (unique per organization), description, industry, country, status (`active|paused|archived`).
- `domains`: project_id, url, hostname, is_primary (at most one per project via partial unique index), verified.
- `competitors`: project_id, name, website_url, hostname.

All tables have UUID primary keys and timezone-aware UTC `created_at`/`updated_at`; `organization_id`, `project_id`, `user_id`, `hostname`, and `created_at` are indexed. Foreign keys cascade on delete.

## Tenancy

`Organization` is the tenant root; `organization_members` links users to organizations with a role (`owner > admin > member > viewer`). Organization-owned tables carry `organization_id` directly (`projects`) or reach it through one join (`domains`/`competitors` → `projects`). Ownership is always resolved server-side, never by client-side filtering.

The API never trusts a client-supplied organization id. `organization_id` is read from the **URL path** and `get_current_membership` checks that the authenticated user belongs to it. Non-members get `404`, so the existence of other tenants is not leaked. `require_role(MembershipRole.X)` enforces the role hierarchy.

## Authentication

- Endpoints: `POST /api/v1/auth/signup` (validates email + password policy, creates user, organization and owner membership, starts a session), `login`, `refresh`, `logout`, `logout-all`, `GET /api/v1/auth/me`.
- Password policy in `core/passwords.py`: 10–128 chars, at least one letter and one non-letter, not a repeated character, not a common password, must not contain the user's email local part.
- Argon2id password hashing.
- Access tokens: 15-minute JWTs (`JWT_SECRET`), returned in the JSON body and kept **in memory** by the SPA.
- Refresh tokens: opaque 48-byte random strings in an `httpOnly` cookie scoped to `/api/v1/auth`. Stored as HMAC-SHA256(`JWT_REFRESH_SECRET`, token). Each refresh **rotates** the token; presenting a rotated token revokes its whole family (theft detection). Logout revokes the family; logout-all revokes every token for the user.
- Rate limiting on auth endpoints: Redis fixed window, in-memory fallback if Redis is down.
- Errors are always `{"error": {"code", "message", "details?"}}`. Invalid login returns the same body for unknown email and wrong password.
- Every auth event (signup, login success/failure, refresh, refresh reuse, logout, logout-all) is written to `auth_audit_logs` with IP and user agent, and emitted as a structured log line. Secrets never appear in either.

## Authorization

Dependencies in `api/deps.py`:

| Dependency | Resolves | Raises |
|---|---|---|
| `get_current_user` | user from Bearer JWT | 401 |
| `get_current_membership` / `get_current_organization` | caller's membership in the path `organization_id` | 404 if not a member |
| `require_role(min)` | membership with at least that role | 403 |
| `require_permission(perm)` | membership whose role holds the permission | 403 |
| `require_project_access(perm)` | project from path `project_id` **and** caller's membership in the project's organization | 404 if not a member, 403 if role lacks perm |

`organization_id` is never read from a request body; it comes from the path or is derived from the requested resource.

Permission matrix (`core/permissions.py`): **Owner** everything, including billing and ownership transfer. **Admin** manages the organization, members and projects (including delete), not billing/ownership. **Member** manages projects and data, cannot delete projects or manage members/organization/billing. **Viewer** read-only.

## Frontend

- `/login`, `/signup` — public, under the `(auth)` route group.
- `/app`, `/app/projects`, `/app/settings` — under the `(app)` group whose layout is an auth guard (silent refresh on mount, redirect to `/login` otherwise) and mounts the `AppShell`.
- `AppShell` = persistent sidebar (≥ md), sheet drawer (mobile), top bar with `OrganizationSwitcher` and `UserMenu`. The selected organization lives in `OrganizationProvider` and is remembered per browser.
- `lib/api.ts` is the only place that talks HTTP; it retries once after a transparent refresh on `401`.

## Background jobs

Celery app in `apps/api/app/workers/celery_app.py` with Redis as broker/backend. Tasks are routed by module name to the `crawler`, `ai_search`, `agents`, and `analytics` queues. Only a `ping` task exists today; the job system proper is a later milestone.

## Environments

Configuration is read exclusively through `app/core/config.py` (pydantic-settings). Production refuses to start with development secrets. See the root `.env.example` for the variable list.

## Deployment

- `apps/web` → Vercel.
- `apps/api` → Railway (`railway.toml` runs migrations, then uvicorn). Worker = same image, Celery entrypoint (`workers/Dockerfile`). Postgres and Redis as Railway plugins.
