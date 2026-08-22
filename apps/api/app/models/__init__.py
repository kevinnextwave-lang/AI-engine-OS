"""Import all models here so Alembic and SQLAlchemy see the full metadata."""

from app.db.base import Base
from app.models.auth_audit_log import AuthAuditLog, AuthEvent
from app.models.competitor import Competitor
from app.models.crawl import (
    CrawlJob,
    CrawlStatus,
    CrawlType,
    CrawlUrl,
    CrawlUrlStatus,
    PageVersion,
    WebsitePage,
)
from app.models.domain import Domain
from app.models.membership import Membership, MembershipRole, OrganizationMember
from app.models.organization import Organization, OrganizationPlan, OrganizationStatus
from app.models.page_intelligence import (
    LinkStatus,
    LinkType,
    PageContentMetrics,
    PageHeading,
    PageImage,
    PageLink,
    PageMetadata,
)
from app.models.project import Project, ProjectStatus
from app.models.refresh_token import RefreshToken
from app.models.user import User

__all__ = [
    "AuthAuditLog",
    "AuthEvent",
    "Base",
    "Competitor",
    "CrawlJob",
    "CrawlStatus",
    "CrawlType",
    "CrawlUrl",
    "CrawlUrlStatus",
    "PageVersion",
    "WebsitePage",
    "Domain",
    "LinkStatus",
    "LinkType",
    "Membership",
    "MembershipRole",
    "Organization",
    "OrganizationMember",
    "OrganizationPlan",
    "OrganizationStatus",
    "PageContentMetrics",
    "PageHeading",
    "PageImage",
    "PageLink",
    "PageMetadata",
    "Project",
    "ProjectStatus",
    "RefreshToken",
    "User",
]
