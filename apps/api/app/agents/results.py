"""Agent result types: what every agent must return from `run()`."""

import enum
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.agents import ActionRiskLevel


class AgentStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0


@dataclass
class ProposedAction:
    """An action the agent wants taken. The framework decides nothing here:
    anything that would change external or customer-facing state must set
    `approval_required=True` (the orchestrator forces it for medium/high risk)."""

    action_type: str
    description: str
    payload: dict[str, Any] = field(default_factory=dict)
    risk_level: ActionRiskLevel = ActionRiskLevel.LOW
    approval_required: bool = True


@dataclass
class AgentResult:
    agent_name: str
    agent_version: str
    status: AgentStatus
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    proposed_actions: list[ProposedAction] = field(default_factory=list)
    confidence: float | None = None  # 0–1
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    execution_time_ms: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "status": self.status.value,
            "summary": self.summary,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "evidence": self.evidence,
            "proposed_actions": [
                {**asdict(a), "risk_level": a.risk_level.value} for a in self.proposed_actions
            ],
            "confidence": self.confidence,
            "token_usage": {
                "input_tokens": self.token_usage.input_tokens,
                "output_tokens": self.token_usage.output_tokens,
                "total_tokens": self.token_usage.total_tokens,
            },
            "execution_time_ms": self.execution_time_ms,
            "warnings": self.warnings,
        }
