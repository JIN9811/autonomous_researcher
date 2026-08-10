"""Unit tests for the shared BO visualization projection contract."""

from __future__ import annotations

import math

import pytest

from experiments.bo_visualization import build_bo_visualization, validate_bo_visualization


def _trace() -> dict[str, object]:
    return {
        "step": 2,
        "acquisition": "expected_improvement",
        "backend_requested": "botorch_optional",
        "backend_active": "botorch_optional",
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
    assert payload["backend"]["model"] == "pool_projection"


def test_build_bo_visualization_selects_largest_numeric_range_deterministically() -> None:
    payload = build_bo_visualization(
        run_id="run-bo-2",
        objective=_objective(),
        parameter_space={
            "geometry_type": ["gyroid"],
            "relative_density": [0.2, 0.4],
            "wall_thickness_mm": [0.8, 2.8],
        },
        trace=_trace(),
    )

    assert payload["view"]["selected_parameter"] == "wall_thickness_mm"


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
