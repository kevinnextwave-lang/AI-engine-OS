import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.notification_channels import DeliveryStatus, NotificationChannelType
from app.schemas.common import APIModel


class NotificationChannelCreateRequest(APIModel):
    channel_type: NotificationChannelType = Field(default=NotificationChannelType.WEBHOOK)
    name: str = Field(min_length=2, max_length=200, examples=["Ops webhook"])
    url: str = Field(description="Public HTTP(S) endpoint that receives alert payloads.")
    secret: str | None = Field(
        default=None,
        min_length=8,
        max_length=512,
        description=(
            "Optional HMAC-SHA256 signing secret. Write-only: it is never returned "
            "by the API. When set, deliveries carry X-ASG-Signature over the body."
        ),
    )
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        from app.alerts.delivery import WebhookConfigError, validate_webhook_url

        try:
            return validate_webhook_url(value).normalized
        except WebhookConfigError as exc:
            raise ValueError(str(exc)) from exc


class NotificationChannelUpdateRequest(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    url: str | None = None
    secret: str | None = Field(
        default=None,
        min_length=8,
        max_length=512,
        description="Set a new signing secret; omit to keep the current one.",
    )
    clear_secret: bool = Field(default=False, description="Remove the signing secret.")
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.alerts.delivery import WebhookConfigError, validate_webhook_url

        try:
            return validate_webhook_url(value).normalized
        except WebhookConfigError as exc:
            raise ValueError(str(exc)) from exc


class NotificationChannelView(APIModel):
    """Channel as returned by the API. The secret NEVER appears here."""

    id: uuid.UUID
    project_id: uuid.UUID
    channel_type: NotificationChannelType
    name: str
    url: str
    has_secret: bool
    enabled: bool
    last_delivery_at: datetime | None
    last_delivery_status: DeliveryStatus | None
    last_delivery_error: str | None
    created_at: datetime
    updated_at: datetime


class NotificationChannelListResponse(APIModel):
    items: list[NotificationChannelView]
    total: int


class ChannelTestResponse(APIModel):
    queued: bool
    note: str
