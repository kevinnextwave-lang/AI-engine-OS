import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.models.membership import MembershipRole
from app.schemas.common import APIModel


class OrganizationCreateRequest(APIModel):
    name: str = Field(min_length=2, max_length=200)


class OrganizationResponse(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrganizationWithRoleResponse(OrganizationResponse):
    role: MembershipRole


class MemberResponse(APIModel):
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: MembershipRole
    joined_at: datetime
