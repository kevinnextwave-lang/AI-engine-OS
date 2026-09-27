FROM python:3.11-slim

# The shipped image is production by default, so the startup safety checks in
# get_settings() (strong secrets, secure cookies, explicit CORS) always run on
# a real deploy even when the platform forgets to set APP_ENV. Local
# docker-compose overrides this with APP_ENV=development explicitly.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# setuptools >= 83 clears PYSEC-2026-3447 in the shipped image.
# The compiler toolchain is only needed while pip builds any sdists; purge it
# from the final filesystem so a compromised container has no build tools.
RUN pip install --upgrade pip "setuptools>=83" && pip install . \
    && apt-get purge -y build-essential && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user; nothing in the image needs root at runtime.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# Run database migrations before serving so a fresh deploy always has its
# schema, regardless of platform start-command configuration. $PORT is set by
# managed hosts (Railway); local runs default to 8000.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
