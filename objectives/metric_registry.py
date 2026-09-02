"""Allowlisted Analysis metrics available to the objective DSL."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable

from objectives.schemas import MetricDefinition


def _metric(
    metric_id: str,
    label: str,
    source_name: str,
    unit: str,
    dimension: str,
    *,
    description: str = "",
    valid_min: float | None = 0.0,
    fidelity: list[str] | None = None,
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        label=label,
        description=description,
        source_path=f"analysis.metrics.{source_name}",
        unit=unit,
        dimension=dimension,
        valid_min=valid_min,
        uncertainty_path="analysis.uncertainty",
        quality_requirements=["curve_quality.ok"],
        fidelity=fidelity or ["measured", "synthetic"],
        provenance_requirements=["observation_id", "analysis_artifact"],
    )


DEFAULT_METRICS = (
    _metric("peak_force_n", "Peak force", "peak_force_N", "N", "force"),
    _metric("displacement_at_peak_mm", "Displacement at peak", "displacement_at_peak_mm", "mm", "length"),
    _metric("initial_stiffness_n_per_mm", "Initial stiffness", "initial_stiffness_N_per_mm", "N/mm", "stiffness"),
    _metric("compressive_strength_mpa", "Compressive strength", "compressive_strength_MPa", "MPa", "stress"),
    _metric("apparent_modulus_mpa", "Apparent modulus", "apparent_modulus_MPa", "MPa", "stress"),
    _metric("strain_at_peak", "Strain at peak", "strain_at_peak", "1", "dimensionless"),
    _metric("energy_absorption_mj", "Energy absorption", "energy_absorption_mJ", "mJ", "energy"),
    _metric(
        "energy_absorption_50pct_mj",
        "Energy absorption to 50% specimen height",
        "energy_absorption_50pct_mJ",
        "mJ",
        "energy",
    ),
    _metric("energy_density_mj_per_mm3", "Energy density", "energy_density_mJ_per_mm3", "mJ/mm3", "energy_density"),
    _metric(
        "specific_energy_absorption_j_per_g",
        "Specific energy absorption",
        "specific_energy_absorption_J_per_g",
        "J/g",
        "specific_energy",
    ),
)


class MetricRegistry:
    """Immutable lookup for metrics implemented by the current Analysis agent."""

    def __init__(self, metrics: Iterable[MetricDefinition]) -> None:
        materialized = list(metrics)
        indexed = {metric.metric_id: metric for metric in materialized}
        if not indexed:
            raise ValueError("metric registry cannot be empty")
        if len(indexed) != len(materialized):
            raise ValueError("metric ids must be unique")
        self._metrics = dict(sorted(indexed.items()))
        canonical = json.dumps(
            [metric.model_dump(mode="json") for metric in self._metrics.values()],
            sort_keys=True,
            separators=(",", ":"),
        )
        self.version_id = f"metric-registry-{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"

    @classmethod
    def default(cls) -> "MetricRegistry":
        return cls(DEFAULT_METRICS)

    def get(self, metric_id: str) -> MetricDefinition:
        try:
            return self._metrics[metric_id]
        except KeyError as exc:
            raise KeyError(f"unknown metric: {metric_id}") from exc

    def list(self) -> list[MetricDefinition]:
        return list(self._metrics.values())

    def validate_metric_value(self, metric_id: str, value: object) -> float:
        definition = self.get(metric_id)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {metric_id} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"metric {metric_id} must be finite")
        if definition.valid_min is not None and numeric < definition.valid_min:
            raise ValueError(f"metric {metric_id} is below {definition.valid_min}")
        if definition.valid_max is not None and numeric > definition.valid_max:
            raise ValueError(f"metric {metric_id} is above {definition.valid_max}")
        return numeric

    def __contains__(self, metric_id: object) -> bool:
        return isinstance(metric_id, str) and metric_id in self._metrics
