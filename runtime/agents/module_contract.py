"""Optional code-owned module bindings for the existing agent registry."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from agents.base_agent import BaseAgent


@dataclass(frozen=True)
class AgentModule:
    """Installed code supplies callables; public metadata never grants execution."""

    module_id: str
    agent_name: str
    version: str
    factory: Callable[[], BaseAgent]
    descriptor_json: str
    project_report: Callable[[dict, dict], dict] | None = None
    frontend_root: Path | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.module_id):
            raise ValueError("Invalid module ID")
        if not self.agent_name or not self.version or not callable(self.factory):
            raise ValueError("Module requires an agent name, version and code factory")
        descriptor = json.loads(self.descriptor_json)
        if not isinstance(descriptor, dict):
            raise ValueError("Module description must be an object")
        if {"id", "kind", "agent_name", "version", "handler", "schema"} & descriptor.keys():
            raise ValueError("Module metadata must not override registered identity")

    def describe(self) -> dict[str, Any]:
        """Return a detached, serializable contract without callables/local paths."""
        return {
            **json.loads(self.descriptor_json),
            "schema": "ax4lab.agent_module.v1",
            "kind": "agent",
            "id": self.module_id,
            "agent_name": self.agent_name,
            "version": self.version,
            "handler": f"agent.{self.agent_name}",
        }
