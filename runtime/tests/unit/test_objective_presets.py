"""Regression tests for optional built-in objective presets."""

from __future__ import annotations

import pytest

from objectives.compiler import compile_objective
from objectives.evaluator import evaluate_objective
from objectives.metric_registry import MetricRegistry
from objectives.presets import get_objective_preset, list_objective_presets


def test_legacy_utm_composite_preset_matches_original_cycle_formula() -> None:
    registry = MetricRegistry.default()
    preset = get_objective_preset("legacy-utm-composite", registry_version=registry.version_id)
    compiled = compile_objective(preset, registry)

    evaluation = evaluate_objective(
        compiled,
        {
            "compressive_strength_mpa": 2.5,
            "apparent_modulus_mpa": 40.0,
            "specific_energy_absorption_j_per_g": 0.125,
            "energy_density_mj_per_mm3": 0.04,
        },
        "preset-midpoint",
    )

    assert evaluation.score == pytest.approx(0.5)
    assert evaluation.term_contributions == pytest.approx(
        {"strength": 0.225, "stiffness": 0.125, "energy_absorption": 0.15}
    )
    assert preset.lifecycle == "draft"
    assert preset.metadata["activation"] == "operator_required"
    assert preset.metadata["runtime_postprocessing"] == [
        "curve_quality_warning_factor",
        "cae_score_blend",
    ]


def test_preset_catalog_returns_independent_copies() -> None:
    first = list_objective_presets(registry_version="registry-a")
    first[0].metadata["mutated"] = True
    second = list_objective_presets(registry_version="registry-b")

    assert first[0].objective_id == "legacy-utm-composite"
    assert second[0].metadata.get("mutated") is None
    assert second[0].metric_registry_version == "registry-b"


def test_legacy_utm_composite_preset_saturates_each_term_at_one() -> None:
    registry = MetricRegistry.default()
    compiled = compile_objective(
        get_objective_preset("legacy-utm-composite", registry_version=registry.version_id),
        registry,
    )

    evaluation = evaluate_objective(
        compiled,
        {
            "compressive_strength_mpa": 10.0,
            "apparent_modulus_mpa": 160.0,
            "specific_energy_absorption_j_per_g": 0.5,
            "energy_density_mj_per_mm3": 0.16,
        },
        "preset-saturation",
    )

    assert evaluation.score == pytest.approx(1.0)
