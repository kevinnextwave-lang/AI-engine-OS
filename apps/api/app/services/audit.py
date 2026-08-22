"""Authentication audit trail: writes a DB row and a structured log line per event."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.auth_audit_log import AuthAuditLog, AuthEvent

log = get_logger("audit.auth")


class AuthAuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        event: AuthEvent,
        *,
        user_id: uuid.UUID | None = None,
        email: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuthAuditLog(
                user_id=user_id,
                event=event,
                email=email,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:512] or None,
                details=details,
            )
        )
        await self._session.flush()
        log.info(
            "auth_event",
            auth_event=event.value,
            user_id=str(user_id) if user_id else None,
            ip=ip_address,
            details=details,
        )
