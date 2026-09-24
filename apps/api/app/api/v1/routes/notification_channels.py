"""Notification channel management (webhook delivery for competitive alerts).

Project-scoped list/create use `require_project_access`; channel-scoped
routes derive the project from the row (non-members 404). DATA_MANAGE for
every write and for the test trigger; DATA_READ to list. The signing secret
is write-only — no response ever contains it.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy import func, select

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.models.notification_channels import NotificationChannelConfig
from app.schemas.notification_channels import (
    ChannelTestResponse,
    NotificationChannelCreateRequest,
    NotificationChannelListResponse,
    NotificationChannelUpdateRequest,
    NotificationChannelView,
)

log = get_logger(__name__)

project_router = APIRouter(
    prefix="/projects/{project_id}/notification-channels", tags=["notifications"]
)
channel_router = APIRouter(prefix="/notification-channels/{channel_id}", tags=["notifications"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}

TestDispatcher = Callable[[uuid.UUID], None]


def get_test_dispatcher() -> TestDispatcher:
    from app.workers.tasks import dispatch_channel_test

    return dispatch_channel_test


def _view(channel: NotificationChannelConfig) -> NotificationChannelView:
    return NotificationChannelView(
        id=channel.id,
        project_id=channel.project_id,
        channel_type=channel.channel_type,
        name=channel.name,
        url=str(channel.config.get("url", "")),
        has_secret=channel.secret is not None,
        enabled=channel.enabled,
        last_delivery_at=channel.last_delivery_at,
        last_delivery_status=channel.last_delivery_status,
        last_delivery_error=channel.last_delivery_error,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]


@project_router.get(
    "", response_model=NotificationChannelListResponse, summary="List channels", responses=_ERRORS
)
async def list_channels(access: ReadAccess, session: DBSession) -> NotificationChannelListResponse:
    rows = list(
        (
            await session.scalars(
                select(NotificationChannelConfig)
                .where(NotificationChannelConfig.project_id == access.project.id)
                .order_by(NotificationChannelConfig.created_at)
            )
        ).all()
    )
    total = (
        await session.scalar(
            select(func.count())
            .select_from(NotificationChannelConfig)
            .where(NotificationChannelConfig.project_id == access.project.id)
        )
    ) or 0
    return NotificationChannelListResponse(items=[_view(r) for r in rows], total=total)


@project_router.post(
    "",
    response_model=NotificationChannelView,
    status_code=status.HTTP_201_CREATED,
    summary="Add a webhook channel",
    description=(
        "Registers a public HTTP(S) endpoint for alert delivery. Internal hosts, "
        "private addresses and non-HTTP schemes are rejected; the same SSRF policy "
        "is re-checked with DNS resolution at every delivery."
    ),
    responses=_ERRORS,
)
async def create_channel(
    body: NotificationChannelCreateRequest,
    access: ManageAccess,
    user: CurrentUser,
    session: DBSession,
) -> NotificationChannelView:
    channel = NotificationChannelConfig(
        project_id=access.project.id,
        channel_type=body.channel_type,
        name=body.name,
        config={"url": body.url},
        secret=body.secret,
        enabled=body.enabled,
        created_by_user_id=user.id,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return _view(channel)


async def get_channel_access(
    session: DBSession, user: CurrentUser, channel_id: Annotated[uuid.UUID, Path()]
) -> tuple[NotificationChannelConfig, ProjectAccess]:
    channel = await session.get(NotificationChannelConfig, channel_id)
    if channel is None:
        raise NotFoundError("Notification channel not found")
    access = await get_project_access(session, user, channel.project_id)
    return channel, access


ChannelAccess = Annotated[
    tuple[NotificationChannelConfig, ProjectAccess], Depends(get_channel_access)
]


@channel_router.get(
    "", response_model=NotificationChannelView, summary="Get a channel", responses=_ERRORS
)
async def get_channel(channel_access: ChannelAccess) -> NotificationChannelView:
    channel, access = channel_access
    _require(access, Permission.DATA_READ)
    return _view(channel)


@channel_router.patch(
    "", response_model=NotificationChannelView, summary="Update a channel", responses=_ERRORS
)
async def update_channel(
    channel_access: ChannelAccess, body: NotificationChannelUpdateRequest, session: DBSession
) -> NotificationChannelView:
    channel, access = channel_access
    _require(access, Permission.DATA_MANAGE)
    if body.name is not None:
        channel.name = body.name
    if body.url is not None:
        channel.config = {**channel.config, "url": body.url}
    if body.clear_secret:
        channel.secret = None
    elif body.secret is not None:
        channel.secret = body.secret
    if body.enabled is not None:
        channel.enabled = body.enabled
    await session.commit()
    await session.refresh(channel)
    return _view(channel)


@channel_router.delete(
    "", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a channel", responses=_ERRORS
)
async def delete_channel(channel_access: ChannelAccess, session: DBSession) -> None:
    channel, access = channel_access
    _require(access, Permission.DATA_MANAGE)
    await session.delete(channel)
    await session.commit()


@channel_router.post(
    "/test",
    response_model=ChannelTestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a test delivery",
    description=(
        "Queues a synthetic test alert to this channel. Delivery happens in the "
        "worker (never in this request); the outcome appears on the channel's "
        "last-delivery fields."
    ),
    responses=_ERRORS,
)
async def test_channel(
    channel_access: ChannelAccess,
    dispatcher: Annotated[TestDispatcher, Depends(get_test_dispatcher)],
) -> ChannelTestResponse:
    channel, access = channel_access
    _require(access, Permission.DATA_MANAGE)
    try:
        dispatcher(channel.id)
    except Exception:  # noqa: BLE001 - broker outage: report instead of claiming "queued"
        log.exception("channel_test_dispatch_failed", channel_id=str(channel.id))
        return ChannelTestResponse(
            queued=False,
            note="Could not queue the test delivery (worker broker unavailable). Try again.",
        )
    return ChannelTestResponse(
        queued=True,
        note="Test delivery queued; check the channel's last delivery status shortly.",
    )
