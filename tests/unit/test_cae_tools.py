"""Unit tests for CAE bridge tool registration and default analysis."""

from __future__ import annotations

from mcp_tools.cae_tools import register_cae_tools
from mcp_tools.tool_registry import ToolRegistry


def test_cae_tool_defaults_bottom_fixed_top_cyclic(tmp_path) -> None:
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {
            "devices": {
                "cae": {
                    "enabled": True,
                    "mode": "test",
                    "artifact_dir": "artifacts/cae",
                    "default_loading": {"load_max_n": 300.0, "cycles": 5},
                }
            }
        },
        repo_root=tmp_path,
    )

    result = tools.call(
        "cae.run_static_analysis",
        {"runtime_mode": "test", "specimen_id": "cae-test", "specimen_size_mm": [20, 20, 20]},
    )

    assert result["ok"] is True
    assert result["tool"] == "cae.run_static_analysis"
    assert result["boundary_condition"] == "bottom_fixed_support"
    assert result["loading_mode"] == "top_cyclic_loading"
    assert result["analysis_platens"]["bottom"] is True
    assert result["analysis_platens"]["top"] is True
    assert result["cae_metrics"]["max_von_mises_MPa"] > 0
    assert result["cae_metrics"]["structural_score"] > 0
    assert result["artifacts"]["contour_svg_path"].endswith("_cae.contour.svg")
    assert result["artifacts"]["report_path"].endswith("_cae.report.json")


def test_cae_tool_normalizes_boundary_condition_labels(tmp_path) -> None:
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {"devices": {"cae": {"enabled": True, "mode": "test", "artifact_dir": "artifacts/cae"}}},
        repo_root=tmp_path,
    )

    result = tools.call(
        "cae.run_static_analysis",
        {
            "runtime_mode": "test",
            "specimen_id": "cae-boundary-test",
            "boundary_condition": "bottom_fixed_support",
            "loading_mode": "top_cyclic_loading",
            "specimen_size_mm": [20, 20, 20],
        },
    )

    assert result["ok"] is True
    assert result["boundary"] == {"bottom": "fixed_support", "top": "cyclic_loading"}
    assert result["boundary_condition"] == "bottom_fixed_support"
    assert result["loading_mode"] == "top_cyclic_loading"


def test_cae_live_requires_solver_when_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "")
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {"devices": {"cae": {"enabled": True, "mode": "live", "require_solver_in_live": True}}},
        repo_root=tmp_path,
    )

    result = tools.call("cae.run_static_analysis", {"runtime_mode": "live"})

    assert result["ok"] is False
    assert result["failure_code"] == "CAE_SOLVER_REQUIRED"
    assert result["boundary_condition"] == "bottom_fixed_support"
