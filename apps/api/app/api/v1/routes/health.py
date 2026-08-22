from fastapi import APIRouter

from app import __version__
from app.api.deps import SettingsDep
from app.schemas.common import HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=StatusResponse)
async def health() -> StatusResponse:
    """Versioned liveness probe: GET /api/v1/health -> {"status": "ok"}."""
    return StatusResponse(status="ok")


root_router = APIRouter(tags=["health"], include_in_schema=False)


@root_router.get("/health", response_model=HealthResponse)
async def root_health(settings: SettingsDep) -> HealthResponse:
    """Unversioned probe used by Railway / load balancers; includes build metadata."""
    return HealthResponse(status="ok", environment=settings.app_env, version=__version__)
