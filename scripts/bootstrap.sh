#!/usr/bin/env bash
# One-time local setup: env files, Python venv, Node workspaces, database schema.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || cp .env.example .env
[ -f apps/api/.env ] || cp apps/api/.env.example apps/api/.env
[ -f apps/web/.env.local ] || cp apps/web/.env.example apps/web/.env.local

echo "▸ Starting Postgres + Redis"
docker compose up -d postgres redis

echo "▸ Python environment"
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install --quiet --upgrade pip
apps/api/.venv/bin/pip install --quiet -e "apps/api[dev]"

echo "▸ Node workspaces"
npm install

echo "▸ Database migrations"
(cd apps/api && .venv/bin/alembic upgrade head)

cat <<MSG

Done. Next:
  scripts/dev.sh          # API on :8000 and web on :3000
  open http://localhost:3000
MSG
