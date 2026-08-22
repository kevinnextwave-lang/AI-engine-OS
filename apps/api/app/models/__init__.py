"""Import all models here so Alembic and SQLAlchemy see the full metadata."""

from app.db.base import Base
from app.models.ai_readiness import AiReadinessAudit, AiReadinessObservation, ReadinessCategory
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
from app.models.entities import (
    Entity,
    EntityLink,
    EntityObservation,
    EntityScope,
    SchemaIssue,
)
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
    PageStructuredData,
    StructuredDataFormat,
)
from app.models.project import Project, ProjectStatus
from app.models.refresh_token import RefreshToken
from app.models.seo import (
    AuditStatus,
    ObservationCategory,
    ObservationStatus,
    SeoAudit,
    SeoObservation,
    Severity,
)
from app.models.user import User

__all__ = [
    "AiReadinessAudit",
    "AiReadinessObservation",
    "ReadinessCategory",
    "AuditStatus",
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
    "Entity",
    "EntityLink",
    "EntityObservation",
    "EntityScope",
    "SchemaIssue",
    "LinkStatus",
    "LinkType",
    "Membership",
    "MembershipRole",
    "ObservationCategory",
    "ObservationStatus",
    "Organization",
    "OrganizationMember",
    "OrganizationPlan",
    "OrganizationStatus",
    "PageContentMetrics",
    "PageHeading",
    "PageImage",
    "PageLink",
    "PageMetadata",
    "PageStructuredData",
    "Project",
    "ProjectStatus",
    "RefreshToken",
    "SeoAudit",
    "SeoObservation",
    "Severity",
    "StructuredDataFormat",
    "User",
]
