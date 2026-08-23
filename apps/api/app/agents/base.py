"""Agent base class, model selection and the budgeted LLM helper."""

from dataclasses import dataclass
from decimal import Decimal

from app.agents.context import AgentContext, ContextSpec
from app.agents.results import AgentResult, TokenUsage
from app.ai.catalog import default_pricing
from app.ai.pricing import estimate_cost
from app.ai.registry import ProviderRegistry
from app.ai.types import AIProviderError, AIRequest, AIResponse
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ModelChoice:
    provider: str  # provider key in the registry ("openai", "anthropic", …)
    model: str


@dataclass(frozen=True)
class ModelPreferences:
    """Provider-neutral model selection. The framework resolves these against
    the configured provider registry; nothing here is tied to one vendor."""

    preferred: ModelChoice
    fallback: ModelChoice | None = None
    max_cost: Decimal = Decimal("1.00")  # per run, in USD
    max_tokens: int = 4000  # max output tokens per call


class BudgetExceededError(Exception):
    """The run hit its configured cost ceiling; the orchestrator fails the run."""


class AgentLLM:
    """The only path from an agent to a model: applies the agent's preferences,
    falls back on provider errors, accumulates token usage and cost, and stops
    the run when the cost ceiling is reached."""

    def __init__(self, registry: ProviderRegistry, preferences: ModelPreferences) -> None:
        self._registry = registry
        self._prefs = preferences
        self.usage = TokenUsage()
        self.cost = Decimal("0")
        self.calls = 0
        self.models_used: list[str] = []

    async def generate(self, *, system_prompt: str, prompt: str) -> AIResponse:
        if self.cost >= self._prefs.max_cost:
            raise BudgetExceededError(
                f"Cost ceiling {self._prefs.max_cost} reached before the call"
            )
        choices = [self._prefs.preferred] + ([self._prefs.fallback] if self._prefs.fallback else [])
        last_error: AIProviderError | None = None
        for choice in choices:
            provider = self._registry.get_optional(choice.provider)
            if provider is None:
                continue
            request = AIRequest(
                model=choice.model,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=self._prefs.max_tokens,
            )
            try:
                response = await provider.generate(request)
            except AIProviderError as exc:
                last_error = exc
                log.warning(
                    "agent_llm_fallback",
                    provider=choice.provider,
                    model=choice.model,
                    error=exc.error.category.value,
                )
                continue
            self.calls += 1
            self.usage.add(response.input_tokens, response.output_tokens)
            self.models_used.append(f"{choice.provider}/{choice.model}")
            self.cost += estimate_cost(
                default_pricing(choice.model), response.input_tokens, response.output_tokens
            ).amount
            if self.cost > self._prefs.max_cost:
                raise BudgetExceededError(
                    f"Cost ceiling {self._prefs.max_cost} exceeded (spent {self.cost})"
                )
            return response
        if last_error is not None:
            raise last_error
        raise RuntimeError("No configured AI provider matches the agent's model preferences")


class Agent:
    """Base class for specialized agents (none ship in 6A).

    Subclasses set `name`, `version`, optionally `context_spec`, `instructions`
    and `model_preferences`, and implement `run`."""

    name: str = "abstract"
    version: str = "0.0"
    instructions: str = ""
    context_spec: ContextSpec = ContextSpec()
    model_preferences: ModelPreferences = ModelPreferences(
        preferred=ModelChoice("openai", "gpt-4o-mini"),
        fallback=ModelChoice("anthropic", "claude-3-5-haiku"),
    )

    async def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError
