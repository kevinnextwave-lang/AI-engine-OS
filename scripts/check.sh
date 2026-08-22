#!/usr/bin/env bash
# Every quality gate CI runs, locally.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▸ API: ruff / mypy / pytest"
(cd apps/api && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest -q)

echo "▸ Web + packages: lint / typecheck / build"
npm run lint
npm run typecheck
npm run build
