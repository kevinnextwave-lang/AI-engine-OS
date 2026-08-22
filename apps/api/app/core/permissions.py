"""Role-based access control.

Roles are ordered (owner > admin > member > viewer) but permissions are the
unit of authorization. Routes ask for a Permission; the matrix decides which
roles hold it. Keep this table the single source of truth.

  Owner   full access
  Admin   manage organization settings, members and projects (not billing/ownership)
  Member  manage projects and data; cannot manage billing, members or the organization
  Viewer  read-only
"""

import enum

from app.models.membership import MembershipRole


class Permission(enum.StrEnum):
    ORG_READ = "org:read"
    ORG_MANAGE = "org:manage"  # rename, settings
    ORG_DELETE = "org:delete"
    ORG_TRANSFER_OWNERSHIP = "org:transfer_ownership"
    BILLING_MANAGE = "billing:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"  # invite, change roles, remove
    PROJECTS_READ = "projects:read"
    PROJECTS_MANAGE = "projects:manage"  # create, update, archive
    PROJECTS_DELETE = "projects:delete"
    DATA_READ = "data:read"  # domains, competitors, future analytics
    DATA_MANAGE = "data:manage"


_ALL = frozenset(Permission)
_READ_ONLY = frozenset(
    {
        Permission.ORG_READ,
        Permission.MEMBERS_READ,
        Permission.PROJECTS_READ,
        Permission.DATA_READ,
    }
)
_MEMBER = _READ_ONLY | {Permission.PROJECTS_MANAGE, Permission.DATA_MANAGE}
_ADMIN = _MEMBER | {Permission.ORG_MANAGE, Permission.MEMBERS_MANAGE, Permission.PROJECTS_DELETE}

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.OWNER: _ALL,
    MembershipRole.ADMIN: frozenset(_ADMIN),
    MembershipRole.MEMBER: frozenset(_MEMBER),
    MembershipRole.VIEWER: _READ_ONLY,
}


def role_has(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
