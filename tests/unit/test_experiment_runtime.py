"""Unit tests for the Autonomous Experiment Runtime layer."""

from __future__ import annotations

from pathlib import Path

from experiments.api import evaluate_experiment
from experiments.benchmark import run_benchmark
from learning.bo_parameter_space import BOParameterSpace
from learning.botorch_backend import is_available as botorch_available
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
    assert result["job"]["device"] == "printer:fleet"
    selected = result["bridge_result"]["selected_printer"]
    assert selected["provider"] == "prusa_mk4s"
    assert registry.call("experiment.queue.status", {})["devices"]["printer:fleet"]["submitted_count"] == 1


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
    bo_trace = result["strategies"]["bo"]["surrogate_trace"]
    assert len(bo_trace) == 3
    assert bo_trace[0]["candidates"]
    assert bo_trace[0]["selected"]["candidate_id"]
    assert bo_trace[0]["selected"]["acquisition_value"] is not None
    assert bo_trace[0]["x_axis"] == "lhs_design_index"
    assert bo_trace[0]["lhs_visualization"]["schema"] == "lhs_design_visualization.v1"
    assert bo_trace[0]["lhs_visualization"]["step"] == 1
    assert "visualization" not in bo_trace[0]


def test_benchmark_accepts_optional_botorch_backend() -> None:
    result = run_benchmark(
        {
            "budget": 3,
            "strategies": ["bo"],
            "bo_backend": "botorch_optional",
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.4],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [5.0, 8.0],
            },
            "prior_evaluations": [
                {
                    "candidate_id": "prior-1",
                    "parameters": {"geometry_type": "gyroid", "relative_density": 0.24, "wall_thickness_mm": 1.2, "cell_size_mm": 5.0},
                    "score": 0.52,
                },
                {
                    "candidate_id": "prior-2",
                    "parameters": {"geometry_type": "gyroid", "relative_density": 0.36, "wall_thickness_mm": 1.8, "cell_size_mm": 8.0},
                    "score": 0.68,
                },
            ],
            "objective": {"name": "compare botorch optional backend", "metric_name": "score"},
        }
    )

    bo = result["strategies"]["bo"]
    assert result["ok"] is True
    assert result["bo_backend_requested"] == "botorch"
    assert bo["backend_requested"] == "botorch"
    assert bo["backend_active"] in {"lhs", "botorch"}
    assert bo["surrogate_trace"][0]["backend_requested"] == "botorch"


def test_botorch_benchmark_uses_lhs_then_direct_acquisition_optimization() -> None:
    prior_evaluations = [
        {
            "candidate_id": f"prior-{index}",
            "parameters": {
                "geometry_type": "gyroid",
                "relative_density": 0.20 + index * 0.035,
                "wall_thickness_mm": 1.2 + index * 0.1,
                "cell_size_mm": 10.0,
                "orientation_deg": [0, 45, 90][index % 3],
            },
            "score": 0.4 + index * 0.04,
            "uncertainty": 0.03,
        }
        for index in range(8)
    ]
    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.48],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [10.0],
                "orientation_deg": [0, 45, 90],
            },
            "prior_evaluations": prior_evaluations,
        }
    )

    bo = result["strategies"]["bo"]
    trace = bo["surrogate_trace"][0]
    assert result["ok"] is True
    assert len(bo["results"]) == 1
    assert trace["phase"] == "acquisition"
    assert trace["backend_active"] == "botorch"
    assert trace["optimizer"]["function"] == "optimize_acqf_mixed"
    assert trace["visualization"]["posterior"]["x"]
    assert bo["results"][0]["evaluation_deferred"] is True
    assert bo["results"][0]["objective_score"] is None
    assert len(trace["evaluated_points"]) == len(prior_evaluations)


def test_botorch_sequential_step_continues_from_measured_observation_count() -> None:
    prior_evaluations = [
        {
            "candidate_id": f"prior-{index:03d}",
            "parameters": {
                "geometry_type": "gyroid",
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0][index % 4],
                "relative_density": 0.21 + index * 0.03,
            },
            "score": 0.01 + index * 0.001,
        }
        for index in range(8)
    ]

    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "num_restarts": 2,
            "raw_samples": 16,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
                "relative_density": [0.2, 0.48],
            },
            "prior_evaluations": prior_evaluations,
        }
    )

    trace = result["strategies"]["bo"]["surrogate_trace"][0]
    assert trace["step"] == 8
    assert trace["next_experiment_step"] == 9
    assert trace["selected"]["candidate_id"] == "bo-candidate-009"
    assert trace["visualization"]["step"] == 8
    assert len(trace["candidates"]) == 1
    assert trace["candidates"][0]["parameters"] == trace["selected"]["parameters"]


def test_botorch_decision_candidate_preserves_optimizer_value_not_projection_grid() -> None:
    prior_evaluations = [
        {
            "candidate_id": f"prior-{index:03d}",
            "parameters": {
                "geometry_type": "gyroid",
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0][index % 4],
                "relative_density": 0.21 + index * 0.03,
            },
            "score": 0.01 + index * 0.001,
        }
        for index in range(8)
    ]

    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "num_restarts": 2,
            "raw_samples": 16,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
                "relative_density": [0.2, 0.48],
            },
            "prior_evaluations": prior_evaluations,
        }
    )

    trace = result["strategies"]["bo"]["surrogate_trace"][0]
    selected = trace["selected"]
    assert trace["candidates"] == [selected]
    assert result["strategies"]["bo"]["results"][0]["parameters"] == selected["parameters"]


def test_botorch_sequential_switches_to_gp_at_configured_lhs_target() -> None:
    parameter_space = {
        "geometry_type": ["gyroid"],
        "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
        "relative_density": [0.2, 0.48],
    }
    planned = BOParameterSpace.from_mapping(parameter_space).lhs_points(3, seed=17)
    prior_evaluations = [
        {
            "candidate_id": f"prior-{index:03d}",
            "parameters": parameters,
            "score": 0.4 + index * 0.05,
        }
        for index, parameters in enumerate(planned, start=1)
    ]

    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "seed": 17,
            "initial_design_size": 3,
            "num_restarts": 2,
            "raw_samples": 16,
            "parameter_space": parameter_space,
            "prior_evaluations": prior_evaluations,
        }
    )

    trace = result["strategies"]["bo"]["surrogate_trace"][0]
    assert trace["phase"] == "acquisition"
    assert trace["initial_design"]["target"] == 3
    assert trace["initial_design"]["completed"] == 3
    assert trace["step"] == 3
    assert trace["next_experiment_step"] == 4
    assert trace["visualization"]["step"] == 3
    assert trace["selected"]["candidate_id"] == "bo-candidate-004"


def test_botorch_sequential_initial_design_emits_one_lhs_point() -> None:
    result = run_benchmark(
        {
            "budget": 8,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "seed": 19,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.48],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [10.0],
            },
        }
    )

    bo = result["strategies"]["bo"]
    assert len(bo["results"]) == 1
    assert bo["surrogate_trace"][0]["phase"] == "initial_design"
    assert bo["surrogate_trace"][0]["initial_design"]["target"] == 8


def test_botorch_sequential_initial_design_uses_one_canonical_lhs_plan() -> None:
    parameter_space = {
        "geometry_type": ["gyroid"],
        "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
        "relative_density": [0.2, 0.48],
    }
    space = BOParameterSpace.from_mapping(parameter_space)
    planned = space.lhs_points(8, seed=7)
    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "sequential_only": True,
            "seed": 7,
            "initial_design_size": 8,
            "parameter_space": parameter_space,
            "prior_evaluations": [
                {
                    "candidate_id": "prior-001",
                    "parameters": planned[0],
                    "score": 0.42,
                    "uncertainty": 0.03,
                }
            ],
        }
    )

    bo = result["strategies"]["bo"]
    trace = bo["surrogate_trace"][0]
    assert trace["selected"]["parameters"] == planned[1]
    assert trace["initial_design"]["points"] == [
        {
            "index": index,
            "candidate_id": f"lhs-candidate-{index:03d}",
            "status": "measured" if index == 1 else ("next" if index == 2 else "planned"),
            "parameters": parameters,
        }
        for index, parameters in enumerate(planned, start=1)
    ]
    assert bo["backend_active"] == "lhs"


def test_botorch_twenty_cycle_contract_uses_eight_lhs_then_twelve_acquisition_steps() -> None:
    def evaluator(request: dict[str, object]) -> dict[str, object]:
        candidate = request["candidate"]
        assert isinstance(candidate, dict)
        parameters = candidate["parameters"]
        assert isinstance(parameters, dict)
        cell_size = float(parameters["cell_size_mm"])
        density = float(parameters["relative_density"])
        score = 0.8 - ((cell_size - 7.5) / 5.0) ** 2 - ((density - 0.34) / 0.2) ** 2
        return {"ok": True, "objective_score": score, "uncertainty": 0.02}

    result = run_benchmark(
        {
            "budget": 20,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "initial_design_size": 8,
            "seed": 19,
            "num_restarts": 2,
            "raw_samples": 16,
            "optimizer_timeout_s": 5.0,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
                "relative_density": [0.2, 0.48],
                "orientation_deg": [0.0],
                "anisotropy_ratio": [1.0],
            },
            "objective": {
                "objective_id": "sea",
                "direction": "maximize",
                "metric_name": "specific_energy_absorption_J_per_g",
            },
        },
        evaluator=evaluator,
    )

    trace = result["strategies"]["bo"]["surrogate_trace"]
    assert result["ok"] is True
    assert len(trace) == 20
    assert [item["phase"] for item in trace] == ["initial_design"] * 8 + ["acquisition"] * 12
    assert [item["backend_active"] for item in trace] == ["lhs"] * 8 + ["botorch"] * 12
    assert all(item["acquisition_class"] == "LogExpectedImprovement" for item in trace[8:])
    assert all(item["lhs_visualization"]["schema"] == "lhs_design_visualization.v1" for item in trace[:8])
    assert all("visualization" not in item for item in trace[:8])
    assert all(item["visualization"]["schema"] == "bo_visualization.v1" for item in trace[8:])
    assert all("lhs_visualization" not in item for item in trace[8:])


def test_botorch_benchmark_does_not_invent_observation_noise_for_lhs_scores() -> None:
    def evaluator(request: dict[str, object]) -> dict[str, object]:
        candidate = request["candidate"]
        assert isinstance(candidate, dict)
        parameters = candidate["parameters"]
        assert isinstance(parameters, dict)
        cell_size = float(parameters["cell_size_mm"])
        density = float(parameters["relative_density"])
        score = 1.0 - ((cell_size - 6.0) / 7.0) ** 2 - ((density - 0.34) / 0.18) ** 2
        return {"ok": True, "objective_score": score}

    result = run_benchmark(
        {
            "budget": 9,
            "strategies": ["bo"],
            "bo_backend": "botorch",
            "initial_design_size": 8,
            "seed": 19,
            "num_restarts": 2,
            "raw_samples": 16,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
                "relative_density": [0.2, 0.48],
            },
        },
        evaluator=evaluator,
    )

    acquisition_step = result["strategies"]["bo"]["surrogate_trace"][8]
    assert acquisition_step["model"]["noise_mode"] == "inferred_homoskedastic"
    assert all("uncertainty" not in item for item in acquisition_step["evaluated_points"])
    surface = acquisition_step["projection"]["surface"]
    assert any(max(row) - min(row) > 0.01 for row in surface["mean"])


def test_benchmark_does_not_invent_proxy_score_for_missing_prior() -> None:
    from experiments.benchmark import run_benchmark

    result = run_benchmark(
        {
            "budget": 1,
            "strategies": ["bo"],
            "parameter_space": {"relative_density": [0.2, 0.4]},
            "prior_evaluations": [
                {
                    "candidate_id": "missing-score",
                    "parameters": {"relative_density": 0.3},
                    "fidelity": "measured",
                }
            ],
        }
    )

    trace = result["strategies"]["bo"]["surrogate_trace"][0]
    assert all(item.get("candidate_id") != "missing-score" for item in trace["evaluated_points"])
