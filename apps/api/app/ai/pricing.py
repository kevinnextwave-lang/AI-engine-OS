"""Cost estimation from configurable per-model pricing (ai_models.pricing)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


@dataclass(frozen=True)
class CostEstimate:
    amount: Decimal
    currency: str
    pricing_version: str | None


def estimate_cost(
    pricing: dict[str, Any] | None, input_tokens: int | None, output_tokens: int | None
) -> CostEstimate:
    """Cost in the model's currency from per-million-token rates. Missing or
    zero pricing yields 0 (unknown models are never silently priced)."""
    pricing = pricing or {}
    rate_in = Decimal(str(pricing.get("input_per_million", 0) or 0))
    rate_out = Decimal(str(pricing.get("output_per_million", 0) or 0))
    amount = (
        rate_in * Decimal(input_tokens or 0) + rate_out * Decimal(output_tokens or 0)
    ) / Decimal(1_000_000)
    return CostEstimate(
        amount=amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        currency=str(pricing.get("currency") or "USD"),
        pricing_version=pricing.get("version"),
    )
