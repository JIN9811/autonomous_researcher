"""
File purpose:
- Dynamic registration and lookup for pluggable agent modules.

Key classes/functions:
- AgentRegistry

Inputs/outputs:
- Input: agent instances
- Output: indexed retrieval by agent name

Dependencies:
- agents.base_agent.BaseAgent

Modification guide:
- Safe places to edit: registration and list helpers
- Risky places to edit: error behavior expected by orchestrator
- Related files: app/bootstrap.py, orchestrator/router.py
"""

from __future__ import annotations

from agents.base_agent import BaseAgent


class AgentRegistry:
    """Registry that supports add/remove of agents with minimal coupling."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """Register one agent by its `name` attribute."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        """Return agent by name, raising clear error when missing."""
        if name not in self._agents:
            raise KeyError(f"Agent not found: {name}")
        return self._agents[name]

    def names(self) -> list[str]:
        """List all registered agent names."""
        return sorted(self._agents.keys())
