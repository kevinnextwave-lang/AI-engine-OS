from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, DBSession, SettingsDep, client_ip, rate_limit
from app.core.config import Settings
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserResponse
from app.schemas.common import MessageResponse
from app.services.auth import AuthResult, AuthService, ClientInfo

router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request) -> ClientInfo:
    return ClientInfo(user_agent=request.headers.get("user-agent"), ip_address=client_ip(request))


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path=f"{settings.api_v1_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        domain=settings.cookie_domain,
        path=f"{settings.api_v1_prefix}/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _to_response(result: AuthResult, response: Response, settings: Settings) -> TokenResponse:
    _set_refresh_cookie(response, result.refresh_token, settings)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserResponse.model_validate(result.user),
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth:signup", per_minute=10))],
)
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth:signup", per_minute=10))],
    include_in_schema=False,  # legacy alias for /signup
)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    session: DBSession,
    settings: SettingsDep,
) -> TokenResponse:
    """Validate email + password, create user, organization and owner membership, start session."""
    result = await AuthService(session).signup(
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        organization_name=body.organization_name,
        client=_client(request),
    )
    return _to_response(result, response, settings)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth:login", per_minute=10))],
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: DBSession,
    settings: SettingsDep,
) -> TokenResponse:
    result = await AuthService(session).login(
        email=body.email, password=body.password, client=_client(request)
    )
    return _to_response(result, response, settings)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth:refresh", per_minute=30))],
)
async def refresh(
    request: Request, response: Response, session: DBSession, settings: SettingsDep
) -> TokenResponse:
    token = request.cookies.get(settings.refresh_cookie_name, "")
    try:
        result = await AuthService(session).refresh(refresh_token=token, client=_client(request))
    except Exception:
        _clear_refresh_cookie(response, settings)
        raise
    return _to_response(result, response, settings)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, response: Response, session: DBSession, settings: SettingsDep
) -> MessageResponse:
    token = request.cookies.get(settings.refresh_cookie_name)
    await AuthService(session).logout(refresh_token=token, client=_client(request))
    _clear_refresh_cookie(response, settings)
    return MessageResponse(message="Logged out")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    user: CurrentUser,
    request: Request,
    response: Response,
    session: DBSession,
    settings: SettingsDep,
) -> MessageResponse:
    await AuthService(session).logout_everywhere(user_id=user.id, client=_client(request))
    _clear_refresh_cookie(response, settings)
    return MessageResponse(message="Logged out of all sessions")


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
