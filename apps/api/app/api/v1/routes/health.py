from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import DBSession, SettingsDep
from app.schemas.common import HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=StatusResponse)
async def health() -> StatusResponse:
    """Versioned liveness probe: GET /api/v1/health -> {"status": "ok"}."""
    return StatusResponse(status="ok")


root_router = APIRouter(tags=["health"], include_in_schema=False)


@root_router.get("/health", response_model=HealthResponse)
async def root_health(settings: SettingsDep) -> HealthResponse:
    """Unversioned LIVENESS probe; never touches dependencies, so a database
    blip doesn't get the process restarted."""
    return HealthResponse(status="ok", environment=settings.app_env, version=__version__)


@root_router.get("/health/ready")
async def readiness(request: Request, response: Response, session: DBSession) -> dict[str, str]:
    """READINESS: is this instance actually able to serve? Checks Postgres
    with a real query and reports Redis state (degraded, not down — the
    limiter has an in-memory fallback). Deploy healthchecks point here so a
    deploy that can't reach its database never goes live."""
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - a failing probe must answer, not crash
        checks["database"] = "error"
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        checks["redis"] = "unconfigured"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"
    ok = checks["database"] == "ok"
    checks["status"] = "ready" if ok else "unavailable"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
