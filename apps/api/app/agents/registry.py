"""Agent registry: the fixed set of runnable agents.

The framework ships EMPTY — individual agents register in later milestones
(or tests register stubs). Names are unique; an unknown name is a 404 at the
API layer, never a dynamic import.
"""

from app.agents.base import Agent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if not agent.name or agent.name == "abstract":
            raise ValueError("Agent must define a name")
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' is already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return sorted(self._agents)

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": a.name, "version": a.version} for a in (self._agents[n] for n in self.names())
        ]


_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    global _registry  # noqa: PLW0603 - process-wide registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
