# Background worker image: reuses the API codebase with a Celery entrypoint.
# Build from the repo root:  docker build -f workers/Dockerfile -t asg-worker .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install --upgrade pip && pip install .

CMD ["celery", "-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO", "-Q", "default,crawler,ai_search,agents,analytics"]
