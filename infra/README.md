# Infrastructure

Deployment configuration lives next to each app for now:

- `apps/web` → Vercel (zero-config Next.js)
- `apps/api/railway.toml` + `apps/api/Dockerfile` → Railway (API service, worker service)
- `docker-compose.yml` (repo root) → local development stack

This folder is reserved for shared infrastructure-as-code (Railway/Terraform definitions, queue topology, observability config) as the platform grows and the crawler, AI search workers, agent orchestration, and analytics processing are split into their own deployable services.
