"""Domain exceptions and consistent HTTP error responses.

Services raise AppError subclasses; the API layer converts them into a stable
JSON envelope: {"error": {"code": "...", "message": "...", "details": ...}}.
Messages are safe to show to clients — never include internals or secrets.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Bad request"

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"
    message = "Validation failed"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication required"


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    message = "Invalid email or password"


class InvalidTokenError(AuthenticationError):
    code = "invalid_token"
    message = "Invalid or expired token"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please try again later."


def _envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        # Two requests raced a check-then-insert (duplicate competitor, second
        # crawl, colliding slug, ...). A 409 tells the client to retry/refresh;
        # a 500 would look like an outage. The exception text (SQL + params)
        # stays in the logs, never in the response.
        log.warning("integrity_conflict", path=request.url.path, error=type(exc.orig).__name__)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(
                "conflict", "The request conflicts with a concurrent change. Please retry."
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope("validation_error", "Validation failed", details),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path, method=request.method)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred"),
        )


def safe_error_message(exc: BaseException, limit: int = 2000) -> str:
    """One-line failure description safe to store on rows the API serves.

    Database driver errors embed the failing SQL statement and its bound
    parameters; only the exception class name may reach API clients.
    """
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, SQLAlchemyError):
        return f"{type(exc).__name__}: database error"
    return f"{type(exc).__name__}: {exc}"[:limit]
