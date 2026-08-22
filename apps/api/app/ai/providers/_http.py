"""Shared HTTP helpers for REST-based adapters."""

from typing import Any

import httpx

from app.ai.base import category_for_status
from app.ai.types import AIError, AIProviderError


def raise_for_error(response: httpx.Response, *, provider: str) -> None:
    """Turn a non-2xx provider response into a normalized AIProviderError.
    Only the provider's error message/code is kept — never headers."""
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
        AIError(category_for_status(response.status_code), message, response.status_code, code)
    )


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
