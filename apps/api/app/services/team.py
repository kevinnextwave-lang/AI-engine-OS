"""Team management: invitations, member removal, role changes.

Rules that keep an organization coherent:
- Invites never carry OWNER; ownership is granted only by an existing
  owner changing a member's role afterwards.
- Only the invited email's account can accept (the token is a capability,
  but forwarding it must not move the seat to a stranger).
- The last owner can never be removed or demoted — transfer first.
- Touching an OWNER (remove or role change, either direction) requires
  being an owner yourself.
"""

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email import EmailMessage, EmailSender, get_email_sender
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.core.logging import get_logger
from app.core.security import hash_token, utcnow
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.user import User
from app.repositories.organizations import MembershipRepository
from app.repositories.users import UserRepository

log = get_logger("services.team")

INVITE_TTL_DAYS = 7

_INVALID_INVITE = "This invitation is invalid, has expired, or was already used."


class TeamService:
    def __init__(self, session: AsyncSession, sender: EmailSender | None = None) -> None:
        self._session = session
        self._memberships = MembershipRepository(session)
        self._users = UserRepository(session)
        self._settings = get_settings()
        self._sender = sender or get_email_sender(self._settings)

    # -- invitations -------------------------------------------------------

    async def create_invite(
        self, org: Organization, *, email: str, role: MembershipRole, invited_by: User
    ) -> OrganizationInvite:
        email = email.lower().strip()
        if role == MembershipRole.OWNER:
            raise ValidationAppError(
                "Invitations cannot grant ownership. Invite as admin, then transfer."
            )
        existing_user = await self._users.get_by_email(email)
        if existing_user is not None:
            if await self._memberships.get(org.id, existing_user.id) is not None:
                raise ConflictError("That person is already a member of this organization")
        # One pending invite per (org, email): a re-invite replaces the old
        # link (the previous email's token stops working).
        pending = (
            await self._session.scalars(
                select(OrganizationInvite).where(
                    OrganizationInvite.organization_id == org.id,
                    OrganizationInvite.email == email,
                    OrganizationInvite.accepted_at.is_(None),
                    OrganizationInvite.revoked_at.is_(None),
                )
            )
        ).all()
        for old in pending:
            old.revoked_at = utcnow()
        raw = secrets.token_urlsafe(48)
        invite = OrganizationInvite(
            organization_id=org.id,
            email=email,
            role=role,
            token_hash=hash_token(raw),
            invited_by_user_id=invited_by.id,
            expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
        )
        self._session.add(invite)
        await self._session.flush()

        inviter = invited_by.full_name or invited_by.email
        link = f"{self._settings.web_base_url.rstrip('/')}/accept-invite?token={raw}"
        message = EmailMessage(
            to=email,
            subject=f"{inviter} invited you to {org.name}",
            text=(
                f"{inviter} invited you to join the organization “{org.name}” on "
                f"AI Search Growth OS as {role.value}.\n\n"
                f"Accept here (link valid for {INVITE_TTL_DAYS} days, single use):\n{link}\n\n"
                "You'll need an account with THIS email address — sign up first if you "
                "don't have one, then open the link again.\n\n"
                "If you weren't expecting this, you can ignore this email."
            ),
        )
        try:
            await self._sender.send(message)
        except Exception:  # noqa: BLE001 - the invite row exists; delivery is logged
            log.exception("invite_email_failed", invite_id=str(invite.id))
        return invite

    async def list_pending(self, org_id: uuid.UUID) -> list[OrganizationInvite]:
        now = utcnow()
        rows = (
            await self._session.scalars(
                select(OrganizationInvite)
                .where(
                    OrganizationInvite.organization_id == org_id,
                    OrganizationInvite.accepted_at.is_(None),
                    OrganizationInvite.revoked_at.is_(None),
                )
                .order_by(OrganizationInvite.created_at.desc())
            )
        ).all()
        return [r for r in rows if r.expires_at > now]

    async def revoke_invite(self, org_id: uuid.UUID, invite_id: uuid.UUID) -> None:
        invite = await self._session.get(OrganizationInvite, invite_id)
        if invite is None or invite.organization_id != org_id or not invite.is_pending:
            raise NotFoundError("Invitation not found")
        invite.revoked_at = utcnow()

    async def accept_invite(self, user: User, *, token: str) -> Membership:
        invite = (
            await self._session.scalars(
                select(OrganizationInvite).where(OrganizationInvite.token_hash == hash_token(token))
            )
        ).first()
        if invite is None or not invite.is_pending or invite.expires_at <= utcnow():
            raise ValidationAppError(_INVALID_INVITE)
        if user.email.lower() != invite.email:
            raise ValidationAppError(
                f"This invitation was sent to {invite.email}. Sign in with that "
                "account (or ask for a new invite to your address)."
            )
        org = await self._session.get(Organization, invite.organization_id)
        if org is None or org.deleted_at is not None:
            raise ValidationAppError(_INVALID_INVITE)
        invite.accepted_at = utcnow()
        existing = await self._memberships.get(invite.organization_id, user.id)
        if existing is not None:
            return existing  # already in — accepting again is a no-op
        membership = Membership(
            organization_id=invite.organization_id, user_id=user.id, role=invite.role
        )
        self._session.add(membership)
        await self._session.flush()
        log.info(
            "invite_accepted",
            organization_id=str(invite.organization_id),
            user_id=str(user.id),
            role=invite.role.value,
        )
        return membership

    # -- members -------------------------------------------------------------

    async def _owner_count(self, org_id: uuid.UUID) -> int:
        members = await self._memberships.list_for_organization(org_id)
        return sum(1 for m in members if m.role == MembershipRole.OWNER)

    async def remove_member(self, actor: Membership, target_user_id: uuid.UUID) -> None:
        target = await self._memberships.get(actor.organization_id, target_user_id)
        if target is None:
            raise NotFoundError("Member not found")
        if target.role == MembershipRole.OWNER:
            if actor.role != MembershipRole.OWNER:
                raise PermissionDeniedError()
            if await self._owner_count(actor.organization_id) <= 1:
                raise ValidationAppError(
                    "The last owner cannot leave. Transfer ownership first "
                    "(or delete the organization)."
                )
        await self._session.delete(target)
        await self._session.flush()
        log.info(
            "member_removed",
            organization_id=str(actor.organization_id),
            user_id=str(target_user_id),
            by=str(actor.user_id),
        )

    async def change_role(
        self, actor: Membership, target_user_id: uuid.UUID, new_role: MembershipRole
    ) -> Membership:
        target = await self._memberships.get(actor.organization_id, target_user_id)
        if target is None:
            raise NotFoundError("Member not found")
        touches_ownership = target.role == MembershipRole.OWNER or new_role == MembershipRole.OWNER
        if touches_ownership and actor.role != MembershipRole.OWNER:
            raise PermissionDeniedError()
        if (
            target.role == MembershipRole.OWNER
            and new_role != MembershipRole.OWNER
            and await self._owner_count(actor.organization_id) <= 1
        ):
            raise ValidationAppError(
                "The last owner cannot be demoted. Make someone else an owner first."
            )
        target.role = new_role
        await self._session.flush()
        return target
