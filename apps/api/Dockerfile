FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# setuptools >= 83 clears PYSEC-2026-3447 in the shipped image.
RUN pip install --upgrade pip "setuptools>=83" && pip install .

EXPOSE 8000
# Run database migrations before serving so a fresh deploy always has its
# schema, regardless of platform start-command configuration. $PORT is set by
# managed hosts (Railway); local runs default to 8000.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
