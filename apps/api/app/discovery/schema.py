"""Strict schema for the AI-assisted discovery answer. Anything that does not
validate is discarded (and recorded as an error) — free-form AI output never
reaches the database."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sources.normalize import normalize_hostname


class AICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    domain: str | None = Field(default=None, max_length=253)
    reason: str = Field(min_length=3, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    category: str | None = Field(default=None, max_length=100)

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = normalize_hostname(value)
        if normalized is None:
            raise ValueError("not a hostname")
        return normalized


class AICandidateList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[AICandidate] = Field(max_length=25)
