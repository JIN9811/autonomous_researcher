"""Tests for objective tools registered in the shared ToolRegistry."""

from __future__ import annotations

from objectives.metric_registry import MetricRegistry
from objectives.service import ObjectiveService
from objectives.store import ObjectiveStore
from objectives.tools import register_objective_tools
from mcp_tools.tool_registry import ToolRegistry


def service(tmp_path) -> ObjectiveService:
    return ObjectiveService(
        store=ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs"),
        registry=MetricRegistry.default(),
    )


def test_objective_tools_register_complete_bounded_surface(tmp_path) -> None:
    registry = ToolRegistry()
    objective_service = service(tmp_path)

    register_objective_tools(registry, objective_service)

    assert {
        "objective.metrics.list",
        "objective.metrics.describe",
        "objective.compose",
        "objective.validate",
        "objective.preview",
        "objective.revise",
        "objective.approve",
        "objective.activate",
        "objective.evaluate",
        "objective.compare",
        "objective.status",
    }.issubset(registry.list_tools())
    assert registry.resource("objective.service") is objective_service


def test_objective_compose_tool_rejects_code_payload(tmp_path) -> None:
    registry = ToolRegistry()
    register_objective_tools(registry, service(tmp_path))

    result = registry.call(
        "objective.compose",
        {
            "spec": {
                "objective_id": "unsafe",
                "version": 1,
                "expression": {
                    "op": "metric",
                    "metric_id": "compressive_strength_mpa",
                    "python": "__import__('os').system('echo unsafe')",
                },
            }
        },
    )

    assert result["ok"] is False
    assert result["failure_code"] == "OBJECTIVE_VALIDATION_FAILED"
    assert "python" in result["errors"][0]


def test_objective_validate_tool_reports_unknown_metric_without_paths(tmp_path) -> None:
    registry = ToolRegistry()
    register_objective_tools(registry, service(tmp_path))
    registry.call(
        "objective.compose",
        {
            "spec": {
                "objective_id": "unknown-metric",
                "version": 1,
                "expression": {"op": "metric", "metric_id": "not_registered"},
            }
        },
    )

    result = registry.call("objective.validate", {"objective_id": "unknown-metric", "version": 1})

    assert result["ok"] is False
    assert "unknown metric" in result["errors"][0]
    assert str(tmp_path) not in str(result)
