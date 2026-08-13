"""Unit tests for the shared BO visualization projection contract."""

from __future__ import annotations

import math

import pytest

from experiments.bo_visualization import (
    build_bo_visualization,
    rebuild_legacy_continuous_objective_trace,
    validate_bo_visualization,
)


def _trace() -> dict[str, object]:
    return {
        "step": 2,
        "acquisition": "expected_improvement",
        "backend_requested": "botorch",
        "backend_active": "botorch",
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "x": 1,
                "surrogate_mean": 0.62,
                "uncertainty": 0.08,
                "acquisition_value": 0.02,
                "parameters": {"relative_density": 0.20, "cell_size_mm": 5.0},
            },
            {
                "candidate_id": "candidate-002",
                "x": 2,
                "surrogate_mean": 0.78,
                "uncertainty": 0.05,
                "acquisition_value": 0.09,
                "parameters": {"relative_density": 0.30, "cell_size_mm": 5.0},
            },
            {
                "candidate_id": "candidate-003",
                "x": 3,
                "surrogate_mean": 0.71,
                "uncertainty": 0.06,
                "acquisition_value": 0.04,
                "parameters": {"relative_density": 0.40, "cell_size_mm": 5.0},
            },
        ],
        "evaluated_points": [
            {
                "candidate_id": "candidate-001",
                "x": 1,
                "score": 0.60,
                "parameters": {"relative_density": 0.20, "cell_size_mm": 5.0},
            },
            {
                "candidate_id": "candidate-002",
                "x": 2,
                "score": 0.76,
                "parameters": {"relative_density": 0.30, "cell_size_mm": 5.0},
            },
        ],
        "selected": {
            "candidate_id": "candidate-002",
            "x": 2,
            "score": 0.76,
            "surrogate_mean": 0.78,
            "uncertainty": 0.05,
            "acquisition_value": 0.09,
            "parameters": {"relative_density": 0.30, "cell_size_mm": 5.0},
        },
    }


def _objective() -> dict[str, object]:
    return {
        "objective_id": "specific-energy-objective",
        "version": 2,
        "objective_hash": "abc123def456789",
        "name": "Specific energy absorption",
        "direction": "maximize",
        "unit": "J/g",
        "expression": {"op": "metric", "metric_id": "specific_energy_absorption"},
        "constraints": [
            {
                "op": "gte",
                "left": {"op": "metric", "metric_id": "relative_density"},
                "right": {"op": "literal", "value": 0.2},
            }
        ],
    }


def test_build_bo_visualization_emits_shared_finite_contract() -> None:
    payload = build_bo_visualization(
        run_id="run-bo-1",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=_trace(),
        selected_parameter="relative_density",
    )

    posterior = payload["posterior"]
    assert payload["schema"] == "bo_visualization.v1"
    assert payload["run_id"] == "run-bo-1"
    assert payload["step"] == 2
    assert payload["objective"]["equation"] == "specific_energy_absorption"
    assert payload["objective"]["constraints"] == ["relative_density >= 0.2"]
    assert payload["view"]["selected_parameter"] == "relative_density"
    assert payload["view"]["fixed_parameters"] == {"cell_size_mm": 5.0}
    assert posterior["x"] == [0.2, 0.3, 0.4]
    assert len(posterior["x"]) == len(posterior["mean"]) == len(posterior["std"])
    assert posterior["lower_95"][0] == pytest.approx(0.62 - 1.96 * 0.08)
    assert posterior["upper_95"][0] == pytest.approx(0.62 + 1.96 * 0.08)
    assert all(math.isfinite(value) for values in posterior.values() for value in values)
    assert payload["current_best"]["candidate_id"] == "candidate-002"
    assert payload["next_point"]["candidate_id"] == "candidate-002"
    assert payload["backend"]["model"] == "SingleTaskGP"
    assert not any("candidate-pool projection" in item for item in payload["warnings"])


def test_build_bo_visualization_exposes_two_variable_gyroid_sea_contract() -> None:
    trace = _trace()
    trace.update(
        {
            "phase": "initial_design",
            "initial_design": {"sampler": "latin_hypercube", "target": 8, "completed": 2},
            "selected": {
                "candidate_id": "candidate-003",
                "parameters": {"relative_density": 0.40, "cell_size_mm": 7.5},
            },
            "model": {
                "kernel": "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))",
                "noise_mode": "inferred_homoskedastic",
                "input_normalization": "unit_hypercube",
            },
        }
    )

    payload = build_bo_visualization(
        run_id="run-bo-contract",
        objective=_objective(),
        parameter_space={
            "geometry_type": ["gyroid"],
            "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
            "relative_density": [0.20, 0.48],
            "orientation_deg": [0.0],
        },
        trace=trace,
        selected_parameter="relative_density",
    )

    assert payload["design_space"] == {
        "dimension": 2,
        "variables": ["cell_size_mm", "relative_density"],
        "specimen_length_mm": 30.0,
        "cell_size_rule": "a=L/N",
        "cell_counts": [6, 5, 4, 3],
        "feasible_cell_sizes_mm": [5.0, 6.0, 7.5, 10.0],
        "relative_density_bounds": [0.2, 0.48],
        "input_normalization": "unit_hypercube",
    }
    assert payload["initial_design"] == {
        "sampler": "latin_hypercube",
        "target": 8,
        "completed": 2,
        "points": [
            {
                "index": 1,
                "candidate_id": "candidate-001",
                "status": "measured",
                "parameters": {"relative_density": 0.20, "cell_size_mm": 5.0},
            },
            {
                "index": 2,
                "candidate_id": "candidate-002",
                "status": "measured",
                "parameters": {"relative_density": 0.30, "cell_size_mm": 5.0},
            },
            {
                "index": 3,
                "candidate_id": "candidate-003",
                "status": "next",
                "parameters": {"relative_density": 0.40, "cell_size_mm": 7.5},
            },
        ],
    }
    assert payload["backend"]["kernel"] == "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))"
    assert payload["backend"]["noise_mode"] == "inferred_homoskedastic"
    assert payload["objective"]["name"] == "Specific energy absorption"
    assert payload["objective"]["unit"] == "J/g"
    assert payload["objective"]["direction"] == "maximize"


def test_build_bo_visualization_includes_backend_projection_for_each_numeric_parameter() -> None:
    payload = build_bo_visualization(
        run_id="run-bo-slices",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=_trace(),
        selected_parameter="relative_density",
    )

    assert set(payload["parameter_slices"]) == {"relative_density", "cell_size_mm"}
    assert payload["parameter_slices"]["cell_size_mm"]["posterior"]["x"] == [5.0, 5.0, 5.0]
    assert payload["parameter_slices"]["cell_size_mm"]["next_point"]["x"] == 5.0


def test_build_bo_visualization_exposes_marginal_projection_and_logei_label() -> None:
    trace = _trace()
    trace["projection"] = {"mode": "observed_design_marginal", "anchor_count": 5}
    trace["acquisition_class"] = "LogExpectedImprovement"
    for index, candidate in enumerate(trace["candidates"], start=1):
        candidate["acquisition_value"] = -float(index)
    trace["selected"]["acquisition_value"] = -2.0

    payload = build_bo_visualization(
        run_id="run-bo-marginal",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=trace,
        selected_parameter="relative_density",
    )

    assert payload["view"]["mode"] == "marginal_projection"
    assert payload["view"]["anchor_count"] == 5
    assert payload["view"]["fixed_parameters"] == {}
    assert payload["acquisition"]["name"] == "Expected Improvement"
    assert payload["acquisition"]["raw_name"] == "LogExpectedImprovement"
    assert payload["acquisition"]["value"] == pytest.approx([math.exp(-1.0), math.exp(-2.0), math.exp(-3.0)])
    assert payload["next_point"]["acquisition"] == pytest.approx(math.exp(-2.0))


def test_two_variable_surface_exposes_one_dimensional_objective_trace() -> None:
    trace = _trace()
    trace["projection"] = {
        "mode": "candidate_conditioned_slice",
        "anchor_count": 2,
        "parameter": "relative_density",
        "fixed_parameters": {"cell_size_mm": 5.0},
        "surface": {
            "mode": "mixed_2d_gp_surface",
            "x_parameter": "cell_size_mm",
            "x_values": [5.0, 10.0],
            "y_parameter": "relative_density",
            "y_values": [0.2, 0.3, 0.4],
            "shape": [2, 3],
            "mean": [[0.50, 0.70, 0.62], [0.58, 0.82, 0.74]],
            "std": [[0.12, 0.07, 0.10], [0.11, 0.05, 0.08]],
            "lower_95": [[0.2648, 0.5628, 0.424], [0.3644, 0.722, 0.5832]],
            "upper_95": [[0.7352, 0.8372, 0.816], [0.7956, 0.918, 0.8968]],
            "acquisition": [[-4.0, -3.0, -3.8], [-3.7, -2.1, -3.2]],
        },
    }
    trace["evaluated_points"].append(
        {
            "candidate_id": "other-cell",
            "score": 0.99,
            "parameters": {"relative_density": 0.35, "cell_size_mm": 10.0},
        }
    )

    payload = build_bo_visualization(
        run_id="run-bo-conditioned",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=trace,
        selected_parameter="relative_density",
    )

    assert payload["view"]["mode"] == "objective_trace"
    assert payload["view"]["fixed_parameters"] == {}
    assert payload["gp_series"] == []
    assert payload["gp_surface"]["mean"] == [[0.50, 0.70, 0.62], [0.58, 0.82, 0.74]]
    assert payload["objective_trace"]["mode"] == "normalized_search_path"
    assert payload["objective_trace"]["x_label"] == "Normalized BO search coordinate"
    assert payload["objective_trace"]["y_label"] == "Score"
    assert len(payload["objective_trace"]["rows"]) == 6
    assert [row["segment_index"] for row in payload["objective_trace"]["rows"]] == [0, 0, 0, 1, 1, 1]
    assert [row["search_x"] for row in payload["objective_trace"]["rows"]] == pytest.approx(
        [0.02, 0.25, 0.48, 0.52, 0.75, 0.98]
    )
    assert all("parameters" in row for row in payload["objective_trace"]["rows"])
    assert all("mean" in row and "std" in row and "acquisition" in row for row in payload["objective_trace"]["rows"])
    assert len(payload["objective_trace"]["observations"]) == 3
    assert payload["objective_trace"]["observations"][-1]["search_x"] == pytest.approx(0.865)
    assert payload["objective_trace"]["next_point"]["search_x"] == pytest.approx(0.25)
    assert "strata" not in payload["objective_trace"]
    assert payload["objective_trace"]["current_best"] == pytest.approx(0.99)


def test_legacy_segmented_trace_is_refit_as_one_continuous_botorch_path() -> None:
    observations = [
        {
            "candidate_id": f"lhs-{index:03d}",
            "parameters": {"cell_size_mm": cell_size, "relative_density": density},
            "score": score,
        }
        for index, (cell_size, density, score) in enumerate(
            (
                (5.0, 0.22, 0.38),
                (6.0, 0.31, 0.76),
                (7.5, 0.44, 0.51),
                (10.0, 0.27, 0.64),
                (5.0, 0.39, 0.83),
                (6.0, 0.46, 0.56),
                (7.5, 0.25, 0.69),
                (10.0, 0.35, 0.72),
            ),
            start=1,
        )
    ]
    legacy = build_bo_visualization(
        run_id="run-bo-legacy",
        objective=_objective(),
        parameter_space={"cell_size_mm": [5.0, 6.0, 7.5, 10.0], "relative_density": [0.2, 0.48]},
        trace={
            **_trace(),
            "step": 8,
            "evaluated_points": observations,
            "model": {
                "class": "SingleTaskGP",
                "training_count": len(observations),
                "kernel": "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))",
                "noise_mode": "inferred_homoskedastic",
                "input_normalization": "unit_hypercube",
            },
            "projection": {
                "mode": "candidate_conditioned_slice",
                "surface": {
                    "mode": "mixed_2d_gp_surface",
                    "x_parameter": "cell_size_mm",
                    "x_values": [5.0, 6.0, 7.5, 10.0],
                    "y_parameter": "relative_density",
                    "y_values": [0.2, 0.3, 0.4, 0.48],
                    "shape": [4, 4],
                    "mean": [[0.4 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
                    "std": [[0.08 - col * 0.01 for col in range(4)] for _row in range(4)],
                    "lower_95": [[0.2 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
                    "upper_95": [[0.6 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
                    "acquisition": [[-4.0 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
                },
            },
        },
        selected_parameter="relative_density",
    )
    assert legacy["objective_trace"].get("path_mode") != "continuous_2d_gp_path"

    rebuilt = rebuild_legacy_continuous_objective_trace(
        legacy,
        parameter_space={"cell_size_mm": [5.0, 6.0, 7.5, 10.0], "relative_density": [0.2, 0.48]},
        random_seed=19,
        num_restarts=2,
        raw_samples=16,
        fit_max_iter=15,
    )

    trace = rebuilt["objective_trace"]
    assert trace["path_mode"] == "continuous_2d_gp_path"
    assert len(trace["rows"]) == 384
    assert trace["rows"][0]["search_x"] == pytest.approx(0.0)
    assert trace["rows"][-1]["search_x"] == pytest.approx(1.0)
    assert all("segment_index" not in row and "normalized_vector" in row for row in trace["rows"])
    assert max(row["acquisition"] for row in trace["rows"]) > 0.0
    assert len(trace["observations"]) == len(observations)
    assert trace["next_point"]["parameters"] == legacy["next_point"]["parameters"]


def test_two_dimensional_gp_surface_preserves_all_lhs_training_observations() -> None:
    trace = _trace()
    trace["model"] = {
        "class": "SingleTaskGP",
        "training_count": 8,
        "kernel": "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))",
        "noise_mode": "known_observation_variance",
        "input_normalization": "unit_hypercube",
    }
    trace["evaluated_points"] = [
        {
            "candidate_id": f"lhs-{index:03d}",
            "score": 0.4 + index * 0.05,
            "parameters": {
                "cell_size_mm": (5.0, 6.0, 7.5, 10.0)[(index - 1) % 4],
                "relative_density": 0.21 + index * 0.03,
            },
        }
        for index in range(1, 9)
    ]
    trace["evaluated_points"].append(
        {
            "candidate_id": "acquisition-009",
            "score": 0.91,
            "parameters": {"cell_size_mm": 5.0, "relative_density": 0.205},
        }
    )
    trace["projection"] = {
        "mode": "candidate_conditioned_slice",
        "parameter": "relative_density",
        "fixed_parameters": {"cell_size_mm": 5.0},
        "surface": {
            "mode": "mixed_2d_gp_surface",
            "x_parameter": "cell_size_mm",
            "x_values": [5.0, 6.0, 7.5, 10.0],
            "y_parameter": "relative_density",
            "y_values": [0.2, 0.3, 0.4, 0.48],
            "shape": [4, 4],
            "mean": [[0.4 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
            "std": [[0.08 - col * 0.01 for col in range(4)] for _row in range(4)],
            "lower_95": [[0.2 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
            "upper_95": [[0.6 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
            "acquisition": [[-4.0 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
        },
    }

    payload = build_bo_visualization(
        run_id="run-bo-surface",
        objective=_objective(),
        parameter_space={
            "geometry_type": ["gyroid"],
            "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
            "relative_density": [0.20, 0.48],
        },
        trace=trace,
        selected_parameter="relative_density",
    )

    assert payload["view"]["mode"] == "objective_trace"
    assert payload["gp_surface"]["shape"] == [4, 4]
    assert payload["gp_surface"]["x_parameter"] == "cell_size_mm"
    assert payload["gp_surface"]["y_parameter"] == "relative_density"
    assert len(payload["training_observations"]) == 8
    assert {item["candidate_id"] for item in payload["training_observations"]} == {
        f"lhs-{index:03d}" for index in range(1, 9)
    }
    assert payload["backend"]["training_count"] == 8
    assert payload["backend"]["model"] == "SingleTaskGP"
    assert payload["gp_series"] == []
    assert payload["next_point"]["parameters"] == {
        "cell_size_mm": 5.0,
        "relative_density": 0.30,
    }


def test_conditioned_projection_is_not_used_when_two_variable_surface_exists() -> None:
    trace = _trace()
    trace["projection"] = {
        "mode": "candidate_conditioned_slice",
        "anchor_count": 2,
        "parameter": "relative_density",
        "fixed_parameters": {"cell_size_mm": 5.0},
        "x": [0.20, 0.25, 0.30, 0.35, 0.40],
        "mean": [0.50, 0.63, 0.75, 0.70, 0.61],
        "std": [0.12, 0.09, 0.05, 0.07, 0.11],
        "lower_95": [0.2648, 0.4536, 0.652, 0.5628, 0.3944],
        "upper_95": [0.7352, 0.8064, 0.848, 0.8372, 0.8256],
        "acquisition": [0.01, 0.05, 0.12, 0.08, 0.02],
        "surface": {
            "mode": "mixed_2d_gp_surface",
            "x_parameter": "cell_size_mm",
            "x_values": [5.0, 10.0],
            "y_parameter": "relative_density",
            "y_values": [0.20, 0.30, 0.40],
            "shape": [2, 3],
            "mean": [[0.50, 0.75, 0.61], [0.56, 0.80, 0.69]],
            "std": [[0.12, 0.05, 0.11], [0.10, 0.04, 0.08]],
            "lower_95": [[0.2648, 0.652, 0.3944], [0.364, 0.7216, 0.5332]],
            "upper_95": [[0.7352, 0.848, 0.8256], [0.756, 0.8784, 0.8468]],
            "acquisition": [[0.01, 0.12, 0.02], [0.02, 0.15, 0.04]],
        },
    }

    payload = build_bo_visualization(
        run_id="run-bo-projection",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4], "cell_size_mm": [5.0, 10.0]},
        trace=trace,
        selected_parameter="relative_density",
    )

    assert payload["view"]["mode"] == "objective_trace"
    assert payload["view"]["fixed_parameters"] == {}
    assert payload["view"]["anchor_count"] == 0
    assert payload["gp_series"] == []
    assert payload["gp_surface"]["mean"] == trace["projection"]["surface"]["mean"]
    assert payload["posterior"]["mean"] != trace["projection"]["mean"]


def test_build_bo_visualization_selects_first_continuous_range_instead_of_largest_raw_unit_range() -> None:
    payload = build_bo_visualization(
        run_id="run-bo-2",
        objective=_objective(),
        parameter_space={
            "geometry_type": ["gyroid"],
            "orientation_deg": [0, 15, 30, 45, 60, 90],
            "relative_density": [0.2, 0.4],
            "wall_thickness_mm": [0.8, 2.8],
        },
        trace=_trace(),
    )

    assert payload["view"]["selected_parameter"] == "relative_density"


def test_validate_bo_visualization_rejects_non_finite_or_mismatched_arrays() -> None:
    payload = build_bo_visualization(
        run_id="run-bo-3",
        objective=_objective(),
        parameter_space={"relative_density": [0.2, 0.4]},
        trace=_trace(),
        selected_parameter="relative_density",
    )
    payload["posterior"]["std"] = [float("nan")]

    with pytest.raises(ValueError, match="posterior arrays"):
        validate_bo_visualization(payload)


def test_build_bo_visualization_rejects_space_without_numeric_parameter() -> None:
    with pytest.raises(ValueError, match="numeric parameter"):
        build_bo_visualization(
            run_id="run-bo-4",
            objective=_objective(),
            parameter_space={"geometry_type": ["gyroid", "diamond"]},
            trace=_trace(),
        )
