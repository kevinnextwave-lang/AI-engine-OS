from fastapi import APIRouter

from app import __version__
from app.api.deps import SettingsDep
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.app_env, version=__version__)
