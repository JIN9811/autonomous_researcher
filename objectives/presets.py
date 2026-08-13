"""Read-only built-in objective presets that require explicit operator activation."""

from __future__ import annotations

from objectives.schemas import ObjectiveSpec


def _literal(value: float, unit: str) -> dict[str, object]:
    return {"op": "literal", "value": value, "unit": unit}


def _metric(metric_id: str) -> dict[str, str]:
    return {"op": "metric", "metric_id": metric_id}


def _normalize(metric_id: str, maximum: float, unit: str) -> dict[str, object]:
    return {
        "op": "normalize",
        "value": _metric(metric_id),
        "min": _literal(0.0, unit),
        "max": _literal(maximum, unit),
    }


_PRESET_PAYLOADS: tuple[dict[str, object], ...] = (
    {
        "schema_version": "objective_spec.v1",
        "objective_id": "legacy-utm-composite",
        "version": 1,
        "name": "UTM Compression Composite",
        "description": "Original ATR compression objective for strength, stiffness, and energy absorption.",
        "intent": "Reproduce the established UTM compression score as an optional BO objective.",
        "direction": "maximize",
        "expression": {
            "op": "weighted_sum",
            "terms": [
                {
                    "name": "strength",
                    "weight": 0.45,
                    "expression": _normalize("compressive_strength_mpa", 5.0, "MPa"),
                },
                {
                    "name": "stiffness",
                    "weight": 0.25,
                    "expression": _normalize("apparent_modulus_mpa", 80.0, "MPa"),
                },
                {
                    "name": "energy_absorption",
                    "weight": 0.30,
                    "expression": {
                        "op": "max",
                        "args": [
                            _normalize("specific_energy_absorption_j_per_g", 0.25, "J/g"),
                            _normalize("energy_density_mj_per_mm3", 0.08, "mJ/mm3"),
                        ],
                    },
                },
            ],
        },
        "constraints": [],
        "lifecycle": "draft",
        "created_by": "system:preset",
        "metadata": {
            "preset_id": "legacy-utm-composite",
            "source": "agents.analysis_agent.AnalysisAgent._objective_score",
            "activation": "operator_required",
            "runtime_postprocessing": [
                "curve_quality_warning_factor",
                "cae_score_blend",
            ],
            "note": (
                "This preset encodes the deterministic base expression. Legacy curve-quality and CAE "
                "post-processing remain in the Analysis runtime and are not implicit in the objective AST."
            ),
        },
    },
)


def list_objective_presets(*, registry_version: str = "") -> list[ObjectiveSpec]:
    """Return fresh preset objects without persisting or activating them."""
    return [
        ObjectiveSpec.model_validate({**payload, "metric_registry_version": registry_version})
        for payload in _PRESET_PAYLOADS
    ]


def get_objective_preset(preset_id: str, *, registry_version: str = "") -> ObjectiveSpec:
    """Return one fresh preset by stable catalog id."""
    normalized = preset_id.strip()
    for preset in list_objective_presets(registry_version=registry_version):
        if preset.metadata.get("preset_id") == normalized:
            return preset
    raise KeyError(f"unknown objective preset: {preset_id}")
