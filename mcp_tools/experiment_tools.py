"""
File purpose:
- Register Autonomous Experiment Runtime tools.

Key classes/functions:
- register_experiment_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: experiment.evaluate, experiment.benchmark, experiment.queue.status

Dependencies:
- experiments.api
- experiments.benchmark

Modification guide:
- Safe places to edit: tool names under experiment.*
- Risky places to edit: payload/result contract used by agents and GUI
"""

from __future__ import annotations

from typing import Any

from experiments.api import ExperimentRuntime
from experiments.benchmark import run_benchmark
from mcp_tools.tool_registry import ToolRegistry


def register_experiment_tools(registry: ToolRegistry, devices_config: dict[str, Any] | None = None) -> None:
    """Register common experiment API tools without replacing existing device tools."""
    runtime = ExperimentRuntime(tools=registry)

    def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
        return runtime.evaluate(dict(payload or {}))

    def benchmark(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        return run_benchmark(normalized, evaluator=runtime.evaluate)

    def queue_status(payload: dict[str, Any]) -> dict[str, Any]:
        return registry.queue_status()

    registry.register("experiment.evaluate", evaluate)
    registry.register("experiment.benchmark", benchmark)
    registry.register("experiment.queue.status", queue_status)
