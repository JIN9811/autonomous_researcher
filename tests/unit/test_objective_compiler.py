"""Unit tests for unit-safe objective DSL compilation."""

from __future__ import annotations

import pytest

from objectives.compiler import ObjectiveCompileError, compile_objective, validate_objective
from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec


def metric(metric_id: str) -> dict[str, object]:
    return {"op": "metric", "metric_id": metric_id}


def literal(value: float, unit: str = "1") -> dict[str, object]:
    return {"op": "literal", "value": value, "unit": unit}


def objective(expression: dict[str, object], constraints: list[dict[str, object]] | None = None) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="compiler-test",
        version=1,
        direction="maximize",
        expression=expression,
        constraints=constraints or [],
    )


@pytest.fixture
def registry() -> MetricRegistry:
    return MetricRegistry.default()


def test_compiler_rejects_incompatible_addition(registry: MetricRegistry) -> None:
    spec = objective(
        {
            "op": "add",
            "args": [metric("compressive_strength_mpa"), metric("displacement_at_peak_mm")],
        }
    )

    result = validate_objective(spec, registry)

    assert result.valid is False
    assert "incompatible units" in result.errors[0]


def test_compiler_requires_epsilon_for_division(registry: MetricRegistry) -> None:
    spec = objective(
        {
            "op": "divide",
            "numerator": metric("peak_force_n"),
            "denominator": metric("displacement_at_peak_mm"),
        }
    )

    result = validate_objective(spec, registry)

    assert result.valid is False
    assert "epsilon" in result.errors[0]


def test_compiler_rejects_non_dimensionless_log(registry: MetricRegistry) -> None:
    result = validate_objective(objective({"op": "log1p", "arg": metric("peak_force_n")}), registry)

    assert result.valid is False
    assert "dimensionless" in result.errors[0]


def test_compiler_limits_ast_depth_and_nodes(registry: MetricRegistry) -> None:
    expression: dict[str, object] = metric("strain_at_peak")
    for _ in range(17):
        expression = {"op": "abs", "arg": expression}

    result = validate_objective(objective(expression), registry)

    assert result.valid is False
    assert "depth" in result.errors[0]


def test_compiler_accepts_nonlinear_penalty_and_hard_constraint(registry: MetricRegistry) -> None:
    spec = objective(
        {
            "op": "subtract",
            "args": [
                {"op": "normalize", "value": metric("compressive_strength_mpa"), "min": literal(0, "MPa"), "max": literal(8, "MPa")},
                {
                    "op": "hinge_penalty",
                    "value": metric("displacement_at_peak_mm"),
                    "threshold": literal(3, "mm"),
                    "scale": literal(2, "mm"),
                    "side": "above",
                },
            ],
        },
        constraints=[
            {
                "op": "greater_equal",
                "args": [metric("specific_energy_absorption_j_per_g"), literal(0.1, "J/g")],
            }
        ],
    )

    compiled = compile_objective(spec, registry)

    assert compiled.validation.valid is True
    assert compiled.validation.result_dimension == "dimensionless"
    assert compiled.validation.metric_ids == [
        "compressive_strength_mpa",
        "displacement_at_peak_mm",
        "specific_energy_absorption_j_per_g",
    ]


def test_compile_raises_structured_error(registry: MetricRegistry) -> None:
    with pytest.raises(ObjectiveCompileError) as exc_info:
        compile_objective(objective(metric("missing_metric")), registry)

    assert exc_info.value.validation.valid is False
    assert "expression.metric_id" in exc_info.value.validation.errors[0]
