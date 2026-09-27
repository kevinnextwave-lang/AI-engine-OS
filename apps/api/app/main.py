"""FastAPI application factory."""

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app import __version__
from app.api.v1.router import api_router
from app.api.v1.routes.health import root_router as health_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.observability import init_sentry
from app.db.session import dispose_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis: Redis | None = None
    try:
        redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await redis.ping()
        log.info("redis_connected")
    except Exception as exc:  # noqa: BLE001
        log.warning("redis_unavailable_using_memory_rate_limiter", error=type(exc).__name__)
        redis = None
    app.state.redis = redis
    try:
        yield
    finally:
        if redis is not None:
            await redis.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    init_sentry(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Request ID + one access log line per request.

        The ID is bound into structlog's contextvars, so every log event a
        request produces carries request_id — and it's echoed back as
        X-Request-ID for support ("send us the request id"). uvicorn's own
        access log stays silenced; this line replaces it with structure.
        """
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        with structlog.contextvars.bound_contextvars(request_id=rid):
            response = await call_next(request)
            if not request.url.path.startswith("/health"):
                log.info(
                    "http_request",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
        response.headers["X-Request-ID"] = rid
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        # A JSON API needs few headers, but these close real holes: MIME
        # sniffing, framing, and referrer leakage. HSTS only when the deploy
        # is actually HTTPS (cookie_secure is required true in production).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if settings.is_production and settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
