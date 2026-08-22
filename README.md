# AI Search Growth OS

A SaaS platform that helps businesses understand and improve how their brands appear, are recommended, and are represented across AI search and answer engines.

**Current milestone: 1A — Repository Foundation.** Multi-tenant auth, organizations, the application shell, and the platform skeleton. Product modules (visibility monitoring, citations, GEO audits, agents, …) come in later milestones.

See [`docs/architecture.md`](docs/architecture.md) for the design.

## Layout

```
apps/
  web/             Next.js 16 · TypeScript · Tailwind v4 · shadcn/ui
  api/             FastAPI · SQLAlchemy 2 (async) · Alembic · Celery
packages/
  types/           Shared TS types mirroring the API schemas
  ui/              Shared shadcn/ui primitives + theme
  config/          Shared tsconfig base
workers/           Worker image (code lives in apps/api/app/workers)
infrastructure/    Deployment notes
docs/              Architecture docs
scripts/           bootstrap.sh · dev.sh · check.sh
docker-compose.yml Postgres + Redis (+ optional api/worker containers)
.env.example       Environment template
```

## Quick start

Prerequisites: Python 3.11+, Node 22+, Docker.

```bash
scripts/bootstrap.sh   # env files, venv, npm workspaces, Postgres+Redis, migrations
scripts/dev.sh         # API on http://localhost:8000, web on http://localhost:3000
```

Manual equivalent:

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env        # set JWT_SECRET / JWT_REFRESH_SECRET
cp apps/web/.env.example apps/web/.env.local
docker compose up -d postgres redis

cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload                # docs at /docs, health at /api/v1/health

cd ../..            # repo root
npm install
npm run dev:web
```

Routes: `/` → `/login` · `/signup` · `/app` · `/app/projects` · `/app/settings`.

Crawling requires the worker: `cd apps/api && celery -A app.workers.celery_app:celery_app worker -Q default,crawler --loglevel=INFO`.

## Quality gates

```bash
scripts/check.sh
```

runs: `ruff check`, `ruff format --check`, `mypy app` (strict), `pytest` (against a real Postgres, `TEST_DATABASE_URL`), then `eslint`, `tsc --noEmit` for web and packages, and `next build`. CI (`.github/workflows/ci.yml`) runs the same plus an Alembic upgrade → check → downgrade → upgrade round-trip.

## Database changes

Never edit the database by hand. Change the model, then:

```bash
cd apps/api && alembic revision --autogenerate -m "describe change" && alembic upgrade head
```

Review the generated file (Postgres enum types need explicit drops on downgrade).

## Deployment

- **Web → Vercel.** Root directory `apps/web` (monorepo: Vercel detects npm workspaces). Set `NEXT_PUBLIC_API_URL`.
- **API → Railway.** Root `apps/api` (`railway.toml`). Env: `APP_ENV=production`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `JWT_REFRESH_SECRET`, `CORS_ORIGINS`, `COOKIE_SECURE=true` (+ `COOKIE_SAMESITE=none` if web and API are on different registrable domains).
- **Worker → Railway.** Same codebase, `workers/Dockerfile` or start command `celery -A app.workers.celery_app:celery_app worker`.

Never commit `.env` files. All secrets come from environment variables.
