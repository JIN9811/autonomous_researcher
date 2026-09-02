"""Unit tests for CAE bridge tool registration and default analysis."""

from __future__ import annotations

from device_bridges.cae_bridge import CAEBridge, CAEBridgeConfig
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
    assert result["analysis_platens"]["bottom"] is False
    assert result["analysis_platens"]["top"] is False
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
    assert result["boundary"] == {
        "bottom": "frictionless_axial_support",
        "top": "frictionless_displacement",
    }
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


def test_cae_test_mode_returns_quasistatic_curve_to_half_planned_height(tmp_path) -> None:
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
            "specimen_id": "cae-quasistatic",
            "specimen_size_mm": [30.0, 30.0, 30.0],
            "material": {
                "elastic_modulus_mpa": 1800.0,
                "poisson_ratio": 0.35,
                "yield_strength_mpa": 35.0,
            },
            "design_parameters": {
                "geometry_type": "gyroid",
                "relative_density": 0.32,
                "wall_thickness_mm": 1.2,
                "cell_size_mm": 10.0,
            },
        },
    )

    curve = result["reaction_force_displacement_curve"]
    energy = result["cae_metrics"]["energy_absorption_50pct_mJ"]
    assert result["ok"] is True
    assert result["analysis_type"] == "quasistatic_compression"
    assert result["loading_control"] == "displacement"
    assert result["solver_mode"] == "deterministic_quasistatic_equivalent"
    assert result["target_strain"] == 0.5
    assert result["target_displacement_mm"] == 15.0
    assert len(curve) == 101
    assert curve[0] == {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0}
    assert curve[-1]["displacement_mm"] == 15.0
    assert result["cae_metrics"]["endpoint_reached"] is True
    assert 6_828.0 <= energy <= 682_841.0
    assert result["cae_metrics"]["peak_reaction_force_N"] > 0.0
    assert result["boundary"] == {
        "bottom": "frictionless_axial_support",
        "top": "frictionless_displacement",
    }
    assert result["analysis_platens"]["bottom"] is False
    assert result["analysis_platens"]["top"] is False


def test_cae_uses_nested_quasistatic_loading_controls(tmp_path) -> None:
    bridge = CAEBridge(
        CAEBridgeConfig(
            enabled=True,
            mode="test",
            artifact_dir=tmp_path,
            default_loading={
                "load_type": "quasistatic_compression",
                "loading_control": "displacement",
                "target_strain": 0.4,
                "initial_increment": 0.005,
                "minimum_increment": 1e-8,
                "maximum_increment": 0.01,
                "max_increments": 900,
            },
        )
    )

    normalized = bridge._normalized_payload({"specimen_size_mm": [30.0, 30.0, 30.0]})

    assert normalized["target_strain"] == 0.4
    assert normalized["increments"] == {
        "initial": 0.005,
        "minimum": 1e-8,
        "maximum": 0.01,
        "max_increments": 900,
        "time_period": 1.0,
    }


def test_cae_live_mode_delegates_displacement_control_to_calculix(tmp_path) -> None:
    class _CalculixStub:
        def __init__(self) -> None:
            self.payload = None

        def health(self):
            return {
                "ok": True,
                "calculix": {"available": True, "path": "/opt/ccx"},
                "gmsh": {"available": True, "path": "/opt/gmsh"},
            }

        def run_job(self, payload):
            self.payload = payload
            return {
                "ok": True,
                "tool": "calculix.run_job",
                "status": "complete",
                "solver_mode": "calculix_quasistatic",
                "target_displacement_mm": 15.0,
                "reaction_force_displacement_curve": [
                    {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
                    {"step_time": 1.0, "displacement_mm": 15.0, "force_N": 12_000.0},
                ],
                "metrics": {
                    "endpoint_reached": True,
                    "peak_reaction_force_N": 12_000.0,
                    "initial_stiffness_N_per_mm": 800.0,
                    "energy_absorption_50pct_mJ": 90_000.0,
                },
                "artifacts": {"inp_path": "/tmp/specimen.inp", "dat_path": "/tmp/specimen.dat"},
                "step_trace": [{"step": "SOLVE", "status": "ok"}],
            }

    backend = _CalculixStub()
    bridge = CAEBridge(
        CAEBridgeConfig(
            enabled=True,
            mode="live",
            require_solver_in_live=True,
            artifact_dir=tmp_path,
        ),
        calculix_bridge=backend,
    )

    result = bridge.run_static_analysis(
        {
            "runtime_mode": "live",
            "runtime_solver_enabled": True,
            "specimen_id": "live-quasistatic",
            "stl_path": "/tmp/specimen.stl",
            "specimen_size_mm": [30.0, 30.0, 30.0],
            "material": {
                "elastic_modulus_mpa": 1800.0,
                "poisson_ratio": 0.35,
                "yield_strength_mpa": 35.0,
                "plastic_curve": [[35.0, 0.0], [42.0, 0.08]],
            },
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "cae.run_static_analysis"
    assert result["solver_mode"] == "calculix_quasistatic"
    assert result["cae_metrics"]["energy_absorption_50pct_mJ"] == 90_000.0
    assert backend.payload["analysis_type"] == "quasistatic_compression"
    assert backend.payload["target_strain"] == 0.5
    assert backend.payload["specimen_size_mm"] == [30.0, 30.0, 30.0]
    assert backend.payload["material"]["plastic_curve"] == [[35.0, 0.0], [42.0, 0.08]]
