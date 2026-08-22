import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.core.passwords import MAX_LENGTH, MIN_LENGTH, validate_password
from app.schemas.common import APIModel


def _normalize_email(value: str) -> str:
    return value.lower().strip()


class SignupRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    organization_name: str = Field(min_length=2, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalize_email(value)

    @model_validator(mode="after")
    def _password_policy(self) -> "SignupRequest":
        problems = validate_password(self.password, email=self.email)
        if problems:
            raise ValueError("; ".join(problems))
        return self


# Backwards-compatible alias used by the original /register route.
RegisterRequest = SignupRequest


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalize_email(value)


class UserResponse(APIModel):
    id: uuid.UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    full_name: str | None
    is_active: bool
    email_verified: bool
    created_at: datetime


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserResponse
