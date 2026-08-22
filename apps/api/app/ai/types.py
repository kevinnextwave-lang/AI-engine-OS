"""Normalized request / response / error types shared by every provider."""

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any


class AIErrorCategory(enum.StrEnum):
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INVALID_REQUEST = "invalid_request"
    CONTENT_FILTER = "content_filter"
    UNKNOWN_ERROR = "unknown_error"


RETRYABLE = frozenset(
    {AIErrorCategory.RATE_LIMIT, AIErrorCategory.TIMEOUT, AIErrorCategory.PROVIDER_ERROR}
)


@dataclass(frozen=True)
class AIError:
    category: AIErrorCategory
    message: str
    status_code: int | None = None
    provider_code: str | None = None

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


class AIProviderError(Exception):
    """Raised by adapters; carries the normalized error."""

    def __init__(self, error: AIError) -> None:
        super().__init__(f"{error.category.value}: {error.message}")
        self.error = error


class FinishReason(enum.StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_USE = "tool_use"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_system_prompt: bool = True
    supports_temperature: bool = True
    min_temperature: float = 0.0
    max_temperature: float = 2.0
    max_output_tokens: int | None = None
    supports_json_mode: bool = False


@dataclass
class AIRequest:
    model: str
    prompt: str
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class AIResponse:
    provider: str
    model: str
    request_id: uuid.UUID
    response_text: str = ""
    finish_reason: FinishReason = FinishReason.UNKNOWN
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int = 0
    provider_request_id: str | None = None
    # Small, provider-neutral metadata (e.g. model version, stop sequence).
    # Never the full provider payload.
    raw_response: dict[str, Any] = field(default_factory=dict)
    error: AIError | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None
