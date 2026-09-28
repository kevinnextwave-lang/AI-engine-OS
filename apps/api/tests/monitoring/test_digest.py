"""Weekly digest: recipients, opt-out, quiet-org skip, and honest content."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import EmailMessage, EmailSender
from app.models import MembershipRole
from app.models.organization import Organization
from app.models.prompts import BatchStatus, PromptRunBatch
from app.monitoring.digest import ProjectSummary, _fmt_score, send_weekly_digests
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

pytestmark = pytest.mark.anyio


class RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


async def _org_with_activity(
    client: AsyncClient, db_session: AsyncSession, *, org_name: str = "Digest Co"
) -> tuple[dict[str, str], str, str]:
    """Owner + admin + viewer org with one project and one finished batch."""
    owner = await signup(client, org=org_name)
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    await add_member(
        db_session, org, f"admin-{uuid.uuid4().hex[:6]}@digest.example", MembershipRole.ADMIN
    )
    await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@digest.example", MembershipRole.VIEWER
    )
    pid = (await create_project(client, h, name="Brand", website_url="https://brand.example"))["id"]
    ps = (
        await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": "Core"}, headers=h)
    ).json()
    db_session.add(
        PromptRunBatch(
            project_id=uuid.UUID(pid),
            prompt_set_id=uuid.UUID(ps["id"]),
            status=BatchStatus.COMPLETED,
            total_runs=10,
            completed_runs=10,
            targets=[{"provider_key": "openai", "model_key": "m"}],
        )
    )
    await db_session.flush()
    return h, org, pid


async def test_digest_goes_to_owners_and_admins_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _h, org, _pid = await _org_with_activity(client, db_session)
    sender = RecordingSender()
    result = await send_weekly_digests(db_session, sender=sender, now=datetime.now(UTC))
    ours = [m for m in sender.sent if "Digest Co" in m.subject]
    assert result.emails_sent >= 2
    assert len(ours) == 2  # owner + admin, never the viewer
    recipients = {m.to for m in ours}
    assert any("admin-" in r for r in recipients)
    assert not any("viewer-" in r for r in recipients)
    body = ours[0].text
    assert "Brand" in body
    assert "Collections: 1 finished (10 prompt runs)" in body
    assert "not enough data" in body  # no responses -> no invented score
    assert result.orgs_failed == 0


async def test_digest_respects_org_opt_out(client: AsyncClient, db_session: AsyncSession) -> None:
    _h, org, _pid = await _org_with_activity(client, db_session, org_name="OptOut Co")
    await db_session.execute(
        update(Organization)
        .where(Organization.id == uuid.UUID(org))
        .values(weekly_digest_enabled=False)
    )
    await db_session.flush()
    sender = RecordingSender()
    await send_weekly_digests(db_session, sender=sender)
    assert not any("OptOut Co" in m.subject for m in sender.sent)


async def test_quiet_org_gets_no_email(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="Quiet Co")
    h = auth_header(owner["access_token"])
    await create_project(client, h, name="Idle", website_url="https://idle.example")
    sender = RecordingSender()
    result = await send_weekly_digests(db_session, sender=sender)
    assert not any("Quiet Co" in m.subject for m in sender.sent)
    assert result.orgs_skipped_quiet >= 1


def test_fmt_score_never_invents_numbers() -> None:
    s = ProjectSummary(
        name="X",
        score=None,
        previous_score=None,
        trend=None,
        sample_size=0,
        batches=0,
        total_runs=0,
        failed_runs=0,
        seo_audits=0,
        readiness_audits=0,
        crawls=0,
    )
    assert "not enough data" in _fmt_score(s)
    s.score, s.previous_score, s.trend, s.sample_size = 62.0, 58.0, "up", 120
    line = _fmt_score(s)
    assert "62" in line and "58" in line and "n=120" in line


async def test_org_digest_toggle_route(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="Toggle Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    got = (await client.get(f"/api/v1/organizations/{org}", headers=h)).json()
    assert got["weekly_digest_enabled"] is True
    r = await client.patch(
        f"/api/v1/organizations/{org}", json={"weekly_digest_enabled": False}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["weekly_digest_enabled"] is False
    got = (await client.get(f"/api/v1/organizations/{org}", headers=h)).json()
    assert got["weekly_digest_enabled"] is False
    # Viewers cannot flip org settings.
    from app.core.security import create_access_token

    viewer_id = await add_member(
        db_session, org, f"v-{uuid.uuid4().hex[:6]}@toggle.example", MembershipRole.VIEWER
    )
    vh = auth_header(create_access_token(viewer_id))
    assert (
        await client.patch(
            f"/api/v1/organizations/{org}", json={"weekly_digest_enabled": True}, headers=vh
        )
    ).status_code == 403
