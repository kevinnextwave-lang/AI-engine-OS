"""Shared HTTP helpers for REST-based adapters."""

from typing import Any

import httpx

from app.ai.base import category_for_status
from app.ai.types import AIError, AIProviderError


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After on 429s (seconds form only; providers use it).
    Clamped to a sane ceiling so a hostile/buggy header can't park a run."""
    if response.status_code != 429:
        return None
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None  # HTTP-date form: rare from AI providers; fall back to backoff
    if value <= 0:
        return None
    return min(value, 600.0)


def raise_for_error(response: httpx.Response, *, provider: str) -> None:
    """Turn a non-2xx provider response into a normalized AIProviderError.
    Only the provider's error message/code is kept — plus the Retry-After
    hint on 429s, which the retry scheduler honours."""
    if response.is_success:
        return
    message = f"{provider} returned HTTP {response.status_code}"
    code: str | None = None
    try:
        body: Any = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            message = str(err.get("message") or message)[:500]
            code = str(err.get("type") or err.get("code") or err.get("status") or "") or None
        elif isinstance(err, str):
            message = err[:500]
    except ValueError:
        pass
    raise AIProviderError(
        AIError(
            category_for_status(response.status_code),
            message,
            response.status_code,
            code,
            retry_after_seconds=_retry_after_seconds(response),
        )
    )


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
