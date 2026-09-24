# AI Search Growth OS

A SaaS platform that helps businesses understand and improve how their brands appear, are recommended, and are represented across AI search and answer engines.

The platform is feature-complete across its core modules: multi-tenant auth and organizations; safe website crawling with page intelligence; technical SEO, structured-data and AI-readiness audits (GEO); AI visibility measurement across engines with prompt tracking; citation intelligence and citation gaps; competitor discovery, competitive visibility scoring, "why competitors win" insights, competitive content gaps and alerts; and an agent layer (research, content strategy, content optimization, entity optimization) with human approval gates and a multi-agent workflow orchestrator. Every number shown in the product is measured, never invented; agents propose and humans approve.

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

## Quick start (everything in Docker)

```bash
cp apps/api/.env.example apps/api/.env   # set JWT_SECRET / JWT_REFRESH_SECRET
docker compose up --build                # web :3000 · api :8000 · worker · postgres · redis
```

## Quick start (local dev)

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

App sections: `/app` (overview) · `/app/geo` (audits + crawls) · `/app/ai-visibility` · `/app/ai-intelligence` (citations, claims, gaps) · `/app/competitive` (discovery, insights, content gaps, alerts) · `/app/agents` (runs & approvals, workflows, briefs, reviews) · `/app/projects` · `/app/settings`.

Crawls, prompt runs, and agents require the worker: `cd apps/api && celery -A app.workers.celery_app:celery_app worker -Q default,crawler,analytics,ai_search,agents --loglevel=INFO`.

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
