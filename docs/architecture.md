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

## Tenancy

`Organization` is the tenant root; `Membership` links users to organizations with a role (`owner > admin > member > viewer`). Every organization-owned table carries `organization_id`.

The API never trusts a client-supplied organization id. `organization_id` is read from the **URL path** and `get_current_membership` checks that the authenticated user belongs to it. Non-members get `404`, so the existence of other tenants is not leaked. `require_role(MembershipRole.X)` enforces the role hierarchy.

## Authentication

- Argon2id password hashing.
- Access tokens: 15-minute JWTs (`JWT_SECRET`), returned in the JSON body and kept **in memory** by the SPA.
- Refresh tokens: opaque 48-byte random strings in an `httpOnly` cookie scoped to `/api/v1/auth`. Stored as HMAC-SHA256(`JWT_REFRESH_SECRET`, token). Each refresh **rotates** the token; presenting a rotated token revokes its whole family (theft detection). Logout revokes the family; logout-all revokes every token for the user.
- Rate limiting on auth endpoints: Redis fixed window, in-memory fallback if Redis is down.
- Errors are always `{"error": {"code", "message", "details?"}}`.

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
