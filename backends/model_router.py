"""
File purpose:
- Route task types to model roles and concrete model ids via YAML config.

Key classes/functions:
- ModelRouter

Inputs/outputs:
- Input: task type + model config dictionary
- Output: selected primary/fallback model id

Dependencies:
- dataclasses.dataclass

Modification guide:
- Safe places to edit: fallback strategy and route defaults
- Risky places to edit: config key names shared with models.yaml
- Related files: configs/models.yaml, backends/ollama_client.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ModelSelection:
    """Resolved model choice for one task call."""

    role: str
    primary: str
    fallback: str | None


class ModelRouter:
    """Model selection router driven by YAML configuration."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config
        self._models = config.get("models", {})
        self._task_routes = config.get("task_routes", {})

    def select(self, task_type: str) -> ModelSelection:
        """Resolve model role and model ids for the given task type."""
        role = str(self._task_routes.get(task_type, "e2b"))
        role_cfg = self._models.get(role, {})
        primary = str(role_cfg.get("primary", "qwen2.5:3b"))
        fallback = role_cfg.get("fallback")
        return ModelSelection(role=role, primary=primary, fallback=str(fallback) if fallback else None)
