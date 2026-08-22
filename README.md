# AI Search Growth OS

A SaaS platform that helps businesses understand and improve how their brands appear, are recommended, and are represented across AI search and answer engines.

**Current milestone: 1 — Project Foundation.** Multi-tenant auth, organizations, and the platform skeleton. Product modules (visibility monitoring, citations, GEO audits, agents, …) are built on top of this in later milestones.

## Layout

```
apps/
  api/   FastAPI modular monolith (Python 3.11, SQLAlchemy 2 async, Alembic, Celery)
  web/   Next.js 16 app (TypeScript, Tailwind v4, shadcn/ui)
infra/   Deployment notes and future IaC
docker-compose.yml   Postgres + Redis + API + worker for local development
```

### Backend structure (`apps/api/app`)

| Layer | Path | Responsibility |
|---|---|---|
| HTTP | `api/v1/routes/*` | Thin handlers: validate, call a service, shape the response |
| Dependencies | `api/deps.py` | DB session, current user, **tenant scoping**, rate limiting |
| Services | `services/*` | Business logic and transactions |
| Repositories | `repositories/*` | Query/data-access code |
| Models | `models/*` | SQLAlchemy models (UUID PKs, timestamps, soft delete) |
| Core | `core/*` | Settings, security primitives, logging, errors, rate limiter |
| Workers | `workers/*` | Celery app and tasks; routes by queue (`crawler`, `ai_search`, `agents`, `analytics`) so workers can later be split into separate deployments |

### Tenancy and authorization

- Every org-owned resource carries `organization_id`.
- `organization_id` is taken **only from the URL path** and validated against the caller's membership (`get_current_membership`). Unauthorized orgs return `404`, so existence is never leaked.
- Roles: `owner > admin > member > viewer` via `require_role(...)`.

### Authentication

- Argon2id password hashing.
- Short-lived JWT access tokens (15 min) returned in the JSON body; the SPA keeps them in memory.
- Opaque refresh tokens (30 days) in an `httpOnly` cookie scoped to `/api/v1/auth`. Only a SHA-256 hash is stored. Refresh **rotates** the token; reuse of a rotated token revokes the entire token family.
- Rate limiting on auth endpoints (Redis fixed window; in-memory fallback when Redis is unavailable).
- Consistent error envelope: `{"error": {"code", "message", "details?"}}`.

## Local development

Prerequisites: Python 3.11+, Node 22+, Docker (or local Postgres 16 + Redis 7).

```bash
# 1. Infrastructure
cp .env.example .env
docker compose up -d postgres redis

# 2. API
cd apps/api
cp .env.example .env            # set JWT_SECRET_KEY
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload    # http://localhost:8000/docs

# 3. Worker (optional for Milestone 1)
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO

# 4. Web
cd apps/web
cp .env.example .env.local
npm install
npm run dev                      # http://localhost:3000
```

Or run the whole stack: `docker compose up --build`.

### Quality gates

```bash
# API
cd apps/api && ruff check . && ruff format --check . && mypy app && pytest
# Web
cd apps/web && npm run lint && npm run typecheck && npm run build
```

Tests run against a real Postgres database (`TEST_DATABASE_URL`, default `ai_search_growth_os_test`). CI (`.github/workflows/ci.yml`) runs all of the above plus an Alembic upgrade → check → downgrade → upgrade round-trip.

### Database changes

Never edit the database by hand. Change the model, then:

```bash
cd apps/api && alembic revision --autogenerate -m "describe change" && alembic upgrade head
```

Review the generated file before committing (Postgres enum types in particular need explicit drops on downgrade).

## Deployment

- **Web → Vercel.** Root directory `apps/web`. Set `NEXT_PUBLIC_API_URL` to the API's public URL.
- **API + worker + Postgres + Redis → Railway.** Root directory `apps/api` (see `railway.toml`). Run the API service with the default start command (runs migrations then uvicorn) and a second service from the same image with `celery -A app.workers.celery_app:celery_app worker`. Required env: `APP_ENV=production`, `DATABASE_URL` (asyncpg URL), `REDIS_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`, `COOKIE_SECURE=true`, and `COOKIE_SAMESITE=none` if the web and API are on different registrable domains.

Never commit `.env` files. All secrets come from environment variables.
