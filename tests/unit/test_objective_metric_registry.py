"""Unit tests for the objective metric registry and typed contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec


def test_registry_exposes_analysis_metrics_with_units() -> None:
    registry = MetricRegistry.default()

    strength = registry.get("compressive_strength_mpa")

    assert strength.unit == "MPa"
    assert strength.source_path == "analysis.metrics.compressive_strength_MPa"
    assert strength.quality_requirements == ["curve_quality.ok"]
    assert registry.get("specific_energy_absorption_j_per_g").unit == "J/g"
    energy_50pct = registry.get("energy_absorption_50pct_mj")
    assert energy_50pct.unit == "mJ"
    assert energy_50pct.source_path == "analysis.metrics.energy_absorption_50pct_mJ"
    energy_density_50pct = registry.get("energy_density_50pct_mj_per_m3")
    assert energy_density_50pct.unit == "MJ/m3"
    assert energy_density_50pct.dimension == "energy_density"
    assert energy_density_50pct.source_path == "analysis.metrics.energy_density_50pct_MJ_per_m3"
    assert registry.version_id.startswith("metric-registry-")


def test_registry_rejects_unknown_and_non_finite_metric_values() -> None:
    registry = MetricRegistry.default()

    with pytest.raises(KeyError, match="unknown metric"):
        registry.get("not_registered")
    with pytest.raises(ValueError, match="finite"):
        registry.validate_metric_value("compressive_strength_mpa", float("nan"))


def test_registry_accepts_single_pass_metric_iterables() -> None:
    source = MetricRegistry.default().list()

    registry = MetricRegistry(metric for metric in source)

    assert [item.metric_id for item in registry.list()] == sorted(item.metric_id for item in source)


def test_objective_spec_rejects_unknown_root_operator() -> None:
    with pytest.raises(ValidationError, match="unsupported objective operator"):
        ObjectiveSpec(
            objective_id="x",
            version=1,
            direction="maximize",
            expression={"op": "unknown"},
        )


def test_objective_spec_accepts_registered_metric_expression() -> None:
    spec = ObjectiveSpec(
        objective_id="strength-objective",
        version=1,
        name="Maximize compressive strength",
        direction="maximize",
        expression={"op": "metric", "metric_id": "compressive_strength_mpa"},
    )

    assert spec.schema_version == "objective_spec.v1"
    assert spec.expression["metric_id"] == "compressive_strength_mpa"
