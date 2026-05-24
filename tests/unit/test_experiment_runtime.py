"""Unit tests for the Autonomous Experiment Runtime layer."""

from __future__ import annotations

from pathlib import Path

from experiments.api import evaluate_experiment
from experiments.benchmark import run_benchmark
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.printer_tools import register_printer_tools
from mcp_tools.tool_registry import ToolRegistry


def test_evaluate_experiment_virtual_returns_standard_result() -> None:
    result = evaluate_experiment(
        {
            "run_id": "run-test",
            "experiment_id": "exp-test",
            "objective": {"name": "maximize printability", "metric_name": "printability_score"},
            "candidate": {
                "candidate_id": "cand-virtual",
                "parameters": {
                    "geometry_type": "gyroid",
                    "relative_density": 0.32,
                    "wall_thickness_mm": 1.2,
                    "cell_size_mm": 5.0,
                },
            },
            "execution": {"mode": "virtual", "bridge": "virtual"},
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "experiment.evaluate"
    assert result["bridge"] == "virtual"
    assert result["candidate_id"] == "cand-virtual"
    assert isinstance(result["objective_score"], float)
    assert result["step_trace"][-1]["step"] == "DONE"


def test_experiment_tool_printer_route_uses_device_queue(tmp_path: Path) -> None:
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                }
            }
        },
        repo_root=tmp_path,
    )
    register_experiment_tools(registry)

    result = registry.call(
        "experiment.evaluate",
        {
            "run_id": "run-test",
            "experiment_id": "exp-test",
            "candidate": {
                "candidate_id": "cand-printer",
                "parameters": {
                    "specimen_id": "specimen-printer",
                    "stl_path": str(stl),
                    "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
                    "material": "PLA",
                    "slicer_profile_hint": "0.2mm_quality",
                },
            },
            "execution": {"mode": "test", "bridge": "printer", "requested_tool": "printer.prepare"},
        },
    )

    assert result["ok"] is True
    assert result["bridge"] == "printer"
    assert result["bridge_result"]["tool"] == "printer.prepare"
    assert result["job"]["device"] == "printer:prusa_mk4s"
    assert registry.call("experiment.queue.status", {})["devices"]["printer:prusa_mk4s"]["submitted_count"] == 1


def test_benchmark_runs_random_grid_bo() -> None:
    result = run_benchmark(
        {
            "budget": 3,
            "strategies": ["random", "grid", "bo"],
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.4],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [5.0, 8.0],
            },
            "objective": {"name": "compare candidate proposal modes", "metric_name": "score"},
        }
    )

    assert result["ok"] is True
    assert set(result["strategies"]) == {"random", "grid", "bo"}
    for strategy in result["strategies"].values():
        assert len(strategy["results"]) == 3
        assert len(strategy["curve"]) == 3
        assert strategy["best_score"] is not None
