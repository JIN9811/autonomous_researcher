"""Unit tests for deterministic objective evaluation."""

from __future__ import annotations

import math

import pytest

from objectives.compiler import compile_objective
from objectives.evaluator import evaluate_objective
from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec


METRICS = {
    "compressive_strength_mpa": 5.0,
    "displacement_at_peak_mm": 4.0,
    "specific_energy_absorption_j_per_g": 0.2,
    "strain_at_peak": 0.15,
}


def compiled_objective():
    spec = ObjectiveSpec(
        objective_id="evaluation-test",
        version=2,
        direction="maximize",
        expression={
            "op": "weighted_sum",
            "terms": [
                {
                    "name": "strength",
                    "weight": 0.7,
                    "expression": {
                        "op": "normalize",
                        "value": {"op": "metric", "metric_id": "compressive_strength_mpa"},
                        "min": {"op": "literal", "value": 0.0, "unit": "MPa"},
                        "max": {"op": "literal", "value": 10.0, "unit": "MPa"},
                    },
                },
                {
                    "name": "energy",
                    "weight": 0.3,
                    "expression": {
                        "op": "normalize",
                        "value": {"op": "metric", "metric_id": "specific_energy_absorption_j_per_g"},
                        "min": {"op": "literal", "value": 0.0, "unit": "J/g"},
                        "max": {"op": "literal", "value": 0.4, "unit": "J/g"},
                    },
                },
            ],
        },
        constraints=[
            {
                "op": "less_equal",
                "args": [
                    {"op": "metric", "metric_id": "displacement_at_peak_mm"},
                    {"op": "literal", "value": 5.0, "unit": "mm"},
                ],
            }
        ],
    )
    return compile_objective(spec, MetricRegistry.default())


def test_evaluator_is_reproducible_and_reports_contributions() -> None:
    compiled = compiled_objective()

    first = evaluate_objective(compiled, METRICS, "obs-1", uncertainty={"compressive_strength_mpa": 0.1})
    second = evaluate_objective(compiled, METRICS, "obs-1", uncertainty={"compressive_strength_mpa": 0.1})

    assert first.model_dump() == second.model_dump()
    assert first.score == pytest.approx(0.5)
    assert first.feasible is True
    assert first.term_contributions == {"strength": pytest.approx(0.35), "energy": pytest.approx(0.15)}
    assert first.uncertainty is not None and first.uncertainty > 0
    assert math.isfinite(first.score)


def test_evaluator_marks_hard_constraint_infeasible() -> None:
    evaluation = evaluate_objective(
        compiled_objective(),
        {**METRICS, "displacement_at_peak_mm": 7.0},
        "obs-2",
    )

    assert evaluation.feasible is False
    assert evaluation.constraint_results[0]["passed"] is False


def test_evaluator_rejects_effective_zero_denominator() -> None:
    spec = ObjectiveSpec(
        objective_id="ratio-test",
        version=1,
        expression={
            "op": "ratio",
            "numerator": {"op": "metric", "metric_id": "strain_at_peak"},
            "denominator": {"op": "literal", "value": 0.0},
            "epsilon": 1e-6,
        },
    )

    with pytest.raises(ValueError, match="denominator"):
        evaluate_objective(compile_objective(spec, MetricRegistry.default()), METRICS, "obs-zero")


def test_evaluator_rejects_non_finite_metric_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        evaluate_objective(
            compiled_objective(),
            {**METRICS, "compressive_strength_mpa": float("inf")},
            "obs-inf",
        )
