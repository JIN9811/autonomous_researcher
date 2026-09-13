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

from collections.abc import Callable

from agents.base_agent import BaseAgent
from agents.module_contract import AgentModule


class AgentRegistry:
    """Registry that supports add/remove of agents with minimal coupling."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._modules: dict[str, AgentModule] = {}
        self._activation: Callable[[], set[str]] | None = None

    def bind_activation(self, provider: Callable[[], set[str]]) -> None:
        """Use the applied graph as the authority; keep no second saved list."""
        self._activation = provider

    def module_for_agent(self, agent_name: str) -> AgentModule | None:
        return next((module for module in self._modules.values()
                     if module.agent_name == agent_name), None)

    def active_names(self) -> list[str]:
        if self._activation is None:
            return self.names()
        active = self._activation()
        return [name for name in self.names()
                if self.module_for_agent(name) is None or name in active]

    def register_module(self, module: AgentModule) -> None:
        """Bind installed code atomically; keep the existing agent invocation path."""
        if module.module_id in self._modules or module.agent_name in self._agents:
            raise ValueError(f"Module or agent already registered: {module.module_id}")
        agent = module.factory()
        if not isinstance(agent, BaseAgent) or agent.name != module.agent_name:
            raise ValueError("Module factory returned a different agent")
        self._agents[module.agent_name] = agent
        self._modules[module.module_id] = module

    def get_module(self, module_id: str) -> AgentModule | None:
        """Return an optional installed module; legacy agents need no descriptor."""
        return self._modules.get(module_id)

    def modules(self) -> tuple[AgentModule, ...]:
        """Return installed modules for the application's API and asset host."""
        return tuple(self._modules.values())

    def register(self, agent: BaseAgent) -> None:
        """Register one agent by its `name` attribute."""
        # Legacy replacement remains allowed, but cannot inherit another
        # implementation's presentation and configuration ownership claims.
        self._modules = {key: module for key, module in self._modules.items()
                         if module.agent_name != agent.name}
        self._agents[agent.name] = agent

    def get_installed(self, name: str) -> BaseAgent:
        """Return installed code without granting active execution admission."""
        if name not in self._agents:
            raise KeyError(f"Agent not found: {name}")
        return self._agents[name]

    def get(self, name: str) -> BaseAgent:
        """Return an active agent by name, raising clearly when unavailable."""
        agent = self.get_installed(name)
        if self.module_for_agent(name) is not None and name not in self.active_names():
            raise KeyError(f"Agent module inactive in applied graph: {name}")
        return agent

    def names(self) -> list[str]:
        """List all registered agent names."""
        return sorted(self._agents.keys())
