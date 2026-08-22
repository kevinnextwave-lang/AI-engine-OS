.PHONY: api web worker migrate test lint typecheck

api:
	cd apps/api && uvicorn app.main:app --reload --port 8000

worker:
	cd apps/api && celery -A app.workers.celery_app:celery_app worker --loglevel=INFO

migrate:
	cd apps/api && alembic upgrade head

migration:
	cd apps/api && alembic revision --autogenerate -m "$(m)"

test:
	cd apps/api && pytest

lint:
	cd apps/api && ruff check . && ruff format --check .
	npm run lint

typecheck:
	cd apps/api && mypy app
	npm run typecheck

web:
	npm run dev:web
