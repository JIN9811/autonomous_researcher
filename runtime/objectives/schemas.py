"""Typed contracts for the bounded objective compiler runtime."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ObjectiveDirection = Literal["maximize", "minimize"]
ObjectiveLifecycle = Literal["draft", "validated", "approved", "active", "retired"]
DecisionAction = Literal["compose", "validate", "preview", "revise", "approve", "activate", "retire"]

ALLOWED_OPERATORS = frozenset(
    {
        "literal",
        "metric",
        "reference",
        "add",
        "subtract",
        "multiply",
        "divide",
        "weighted_sum",
        "ratio",
        "abs",
        "square",
        "power",
        "sqrt",
        "log1p",
        "min",
        "max",
        "clip",
        "target_deviation",
        "hinge_penalty",
        "piecewise_penalty",
        "normalize",
        "aggregate",
        "less_than",
        "less_equal",
        "greater_than",
        "greater_equal",
        "equal",
        "and",
        "or",
        "not",
    }
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetricDefinition(BaseModel):
    """One implemented metric that objective expressions may reference."""

    metric_id: str
    label: str
    description: str = ""
    source_path: str
    unit: str
    dimension: str
    value_type: Literal["number"] = "number"
    valid_min: float | None = None
    valid_max: float | None = None
    uncertainty_path: str | None = None
    quality_requirements: list[str] = Field(default_factory=list)
    allowed_modes: list[Literal["test", "live", "virtual", "replay"]] = Field(
        default_factory=lambda: ["test", "live", "virtual", "replay"]
    )
    fidelity: list[Literal["measured", "simulation", "synthetic"]] = Field(default_factory=lambda: ["measured"])
    provenance_requirements: list[str] = Field(default_factory=lambda: ["observation_id"])


class ObjectiveSpec(BaseModel):
    """Versioned declarative objective supplied by an untrusted composer."""

    schema_version: Literal["objective_spec.v1"] = "objective_spec.v1"
    objective_id: str
    version: int = Field(ge=1)
    name: str = ""
    description: str = ""
    intent: str = ""
    direction: ObjectiveDirection = "maximize"
    expression: dict[str, Any]
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    metric_registry_version: str = ""
    lifecycle: ObjectiveLifecycle = "draft"
    created_by: str = "llm"
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective_id")
    @classmethod
    def validate_objective_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in normalized):
            raise ValueError("objective_id must contain only letters, numbers, '-' or '_'")
        return normalized

    @field_validator("expression")
    @classmethod
    def validate_root_operator(cls, value: dict[str, Any]) -> dict[str, Any]:
        operator = value.get("op")
        if operator not in ALLOWED_OPERATORS:
            raise ValueError(f"unsupported objective operator: {operator!r}")
        return value


class ObjectiveValidation(BaseModel):
    schema_version: Literal["objective_validation.v1"] = "objective_validation.v1"
    valid: bool
    objective_id: str = ""
    version: int = 0
    objective_hash: str = ""
    registry_version: str = ""
    result_dimension: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    node_count: int = 0
    max_depth: int = 0


class ObjectivePreview(BaseModel):
    schema_version: Literal["objective_preview.v1"] = "objective_preview.v1"
    objective_id: str
    version: int
    objective_hash: str
    usable_rows: int = 0
    missing_rows: int = 0
    rejected_rows: int = 0
    total_rows: int = 0
    feasible_ratio: float | None = None
    score_distribution: dict[str, float | None] = Field(default_factory=dict)
    contribution_summary: dict[str, float] = Field(default_factory=dict)
    sensitivity: dict[str, float] = Field(default_factory=dict)
    uncertainty_stability: dict[str, float | None] = Field(default_factory=dict)
    fidelity_groups: dict[str, int] = Field(default_factory=dict)
    observation_refs: list[str] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)


class ObjectiveEvaluation(BaseModel):
    schema_version: Literal["objective_evaluation.v1"] = "objective_evaluation.v1"
    evaluation_id: str
    objective_id: str
    objective_version: int
    objective_hash: str
    observation_id: str
    score: float
    feasible: bool = True
    raw_value: float
    term_contributions: dict[str, float] = Field(default_factory=dict)
    constraint_results: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    provenance_refs: list[str] = Field(default_factory=list)
    fidelity: str = "measured"
    created_at: str = Field(default_factory=now_iso)

    @field_validator("score", "raw_value")
    @classmethod
    def finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("objective evaluation values must be finite")
        return value


class ObjectiveDecision(BaseModel):
    schema_version: Literal["objective_decision.v1"] = "objective_decision.v1"
    decision_id: str
    action: DecisionAction
    objective_id: str
    version: int
    objective_hash: str
    operator: str = ""
    run_id: str = ""
    reason: str = ""
    created_at: str = Field(default_factory=now_iso)


class ObjectiveBinding(BaseModel):
    schema_version: Literal["objective_binding.v1"] = "objective_binding.v1"
    run_id: str
    objective_id: str
    version: int
    objective_hash: str
    activated_by: str
    activated_at: str = Field(default_factory=now_iso)
