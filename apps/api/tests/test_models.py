"""Milestone 1B — multi-tenant database foundation.

Runs against a real Postgres (see conftest) so constraints, enums and cascades
behave exactly as in production. Each test runs in a rolled-back transaction.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Competitor,
    Domain,
    Membership,
    MembershipRole,
    Organization,
    OrganizationPlan,
    OrganizationStatus,
    Project,
    ProjectStatus,
    User,
)


def _user(email: str | None = None) -> User:
    return User(
        email=email or f"u-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        first_name="Ada",
        last_name="Lovelace",
    )


def _org(slug: str | None = None) -> Organization:
    slug = slug or f"org-{uuid.uuid4().hex[:8]}"
    return Organization(name=slug.title(), slug=slug)


def _project(org: Organization, slug: str = "acme") -> Project:
    return Project(organization=org, name=slug.title(), slug=slug)


async def _expect_integrity_error(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


# 1. organization creation -------------------------------------------------


async def test_organization_creation_defaults(db_session: AsyncSession) -> None:
    org = _org("acme-co")
    db_session.add(org)
    await db_session.flush()
    await db_session.refresh(org)

    assert isinstance(org.id, uuid.UUID)
    assert org.plan == OrganizationPlan.FREE
    assert org.status == OrganizationStatus.ACTIVE
    assert org.deleted_at is None
    assert org.created_at.tzinfo is not None
    assert org.created_at <= datetime.now(UTC)
    assert org.updated_at is not None


async def test_organization_plan_and_status_enums(db_session: AsyncSession) -> None:
    org = _org()
    org.plan = OrganizationPlan.AGENCY
    org.status = OrganizationStatus.SUSPENDED
    db_session.add(org)
    await db_session.flush()
    await db_session.refresh(org)
    assert org.plan is OrganizationPlan.AGENCY
    assert org.status is OrganizationStatus.SUSPENDED


# 2. user membership -------------------------------------------------------


async def test_user_membership_links_user_and_organization(db_session: AsyncSession) -> None:
    user, org = _user(), _org()
    db_session.add_all([user, org])
    await db_session.flush()

    db_session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER))
    await db_session.flush()

    loaded = await db_session.scalar(
        select(User).options(selectinload(User.memberships)).where(User.id == user.id)
    )
    assert loaded is not None
    assert loaded.full_name == "Ada Lovelace"
    assert loaded.email_verified is False
    assert [m.role for m in loaded.memberships] == [MembershipRole.OWNER]
    assert loaded.memberships[0].has_at_least(MembershipRole.ADMIN)

    org_loaded = await db_session.scalar(
        select(Organization)
        .options(selectinload(Organization.memberships))
        .where(Organization.id == org.id)
    )
    assert org_loaded is not None
    assert org_loaded.memberships[0].user_id == user.id


async def test_user_can_belong_to_many_organizations(db_session: AsyncSession) -> None:
    user, a, b = _user(), _org(), _org()
    db_session.add_all([user, a, b])
    await db_session.flush()
    db_session.add_all(
        [
            Membership(organization_id=a.id, user_id=user.id, role=MembershipRole.OWNER),
            Membership(organization_id=b.id, user_id=user.id, role=MembershipRole.VIEWER),
        ]
    )
    await db_session.flush()
    rows = (await db_session.scalars(select(Membership).where(Membership.user_id == user.id))).all()
    assert {m.organization_id for m in rows} == {a.id, b.id}


async def test_membership_requires_existing_user_and_org(db_session: AsyncSession) -> None:
    org = _org()
    db_session.add(org)
    await db_session.flush()
    db_session.add(Membership(organization_id=org.id, user_id=uuid.uuid4()))
    await _expect_integrity_error(db_session)


# 3. project ownership -----------------------------------------------------


async def test_project_belongs_to_organization(db_session: AsyncSession) -> None:
    org = _org()
    project = _project(org, "brand-site")
    project.industry = "SaaS"
    project.country = "US"
    db_session.add(project)
    await db_session.flush()
    await db_session.refresh(project)

    assert project.organization_id == org.id
    assert project.status == ProjectStatus.ACTIVE

    loaded = await db_session.scalar(
        select(Organization)
        .options(selectinload(Organization.projects))
        .where(Organization.id == org.id)
    )
    assert loaded is not None
    assert [p.slug for p in loaded.projects] == ["brand-site"]


async def test_project_requires_organization(db_session: AsyncSession) -> None:
    db_session.add(Project(organization_id=uuid.uuid4(), name="Orphan", slug="orphan"))
    await _expect_integrity_error(db_session)


async def test_deleting_organization_cascades_to_projects(db_session: AsyncSession) -> None:
    org = _org()
    project = _project(org)
    db_session.add(project)
    await db_session.flush()
    project_id = project.id

    await db_session.delete(org)
    await db_session.flush()
    assert await db_session.get(Project, project_id) is None


# 4. domain ownership ------------------------------------------------------


async def test_domain_belongs_to_project_and_traces_to_organization(
    db_session: AsyncSession,
) -> None:
    org = _org()
    project = _project(org)
    domain = Domain(
        project=project, url="https://www.acme.com/", hostname="www.acme.com", is_primary=True
    )
    db_session.add(domain)
    await db_session.flush()
    await db_session.refresh(domain)

    assert domain.verified is False
    assert domain.is_primary is True

    # Server-side traceability: domain -> project -> organization, no client filtering.
    owner_org_id = await db_session.scalar(
        select(Project.organization_id).join(Domain).where(Domain.id == domain.id)
    )
    assert owner_org_id == org.id


async def test_only_one_primary_domain_per_project(db_session: AsyncSession) -> None:
    project = _project(_org())
    db_session.add_all(
        [
            Domain(project=project, url="https://a.com", hostname="a.com", is_primary=True),
            Domain(project=project, url="https://b.com", hostname="b.com", is_primary=False),
        ]
    )
    await db_session.flush()
    db_session.add(Domain(project=project, url="https://c.com", hostname="c.com", is_primary=True))
    await _expect_integrity_error(db_session)


async def test_domain_requires_project(db_session: AsyncSession) -> None:
    db_session.add(Domain(project_id=uuid.uuid4(), url="https://x.com", hostname="x.com"))
    await _expect_integrity_error(db_session)


# 5. competitor ownership --------------------------------------------------


async def test_competitor_belongs_to_project_and_traces_to_organization(
    db_session: AsyncSession,
) -> None:
    org = _org()
    project = _project(org)
    competitor = Competitor(
        project=project, name="Rival", website_url="https://rival.io", hostname="rival.io"
    )
    db_session.add(competitor)
    await db_session.flush()

    loaded = await db_session.scalar(
        select(Project)
        .options(selectinload(Project.competitors), selectinload(Project.domains))
        .where(Project.id == project.id)
    )
    assert loaded is not None
    assert [c.hostname for c in loaded.competitors] == ["rival.io"]

    owner_org_id = await db_session.scalar(
        select(Project.organization_id).join(Competitor).where(Competitor.id == competitor.id)
    )
    assert owner_org_id == org.id


async def test_deleting_project_cascades_to_domains_and_competitors(
    db_session: AsyncSession,
) -> None:
    project = _project(_org())
    domain = Domain(project=project, url="https://a.com", hostname="a.com")
    competitor = Competitor(
        project=project, name="B", website_url="https://b.com", hostname="b.com"
    )
    db_session.add_all([domain, competitor])
    await db_session.flush()
    d_id, c_id = domain.id, competitor.id

    await db_session.delete(project)
    await db_session.flush()
    assert await db_session.get(Domain, d_id) is None
    assert await db_session.get(Competitor, c_id) is None


# 6. uniqueness constraints ------------------------------------------------


async def test_user_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(_user("dup@example.com"))
    await db_session.flush()
    db_session.add(_user("dup@example.com"))
    await _expect_integrity_error(db_session)


async def test_organization_slug_is_unique(db_session: AsyncSession) -> None:
    db_session.add(_org("same-slug"))
    await db_session.flush()
    db_session.add(_org("same-slug"))
    await _expect_integrity_error(db_session)


async def test_membership_is_unique_per_org_and_user(db_session: AsyncSession) -> None:
    user, org = _user(), _org()
    db_session.add_all([user, org])
    await db_session.flush()
    db_session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.ADMIN))
    await db_session.flush()
    db_session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.VIEWER))
    await _expect_integrity_error(db_session)


async def test_project_slug_is_unique_within_organization_only(db_session: AsyncSession) -> None:
    org_a, org_b = _org(), _org()
    db_session.add_all([_project(org_a, "site"), _project(org_b, "site")])
    await db_session.flush()  # same slug in different orgs is fine

    db_session.add(_project(org_a, "site"))
    await _expect_integrity_error(db_session)
