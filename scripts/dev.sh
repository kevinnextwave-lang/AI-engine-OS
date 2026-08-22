#!/usr/bin/env bash
# Run API and web dev servers together (Ctrl-C stops both).
set -euo pipefail
cd "$(dirname "$0")/.."

(cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

npm run dev --workspace apps/web
