"""
ATR Self-Evolution data models.

Self-evolution is a meta-runtime. It evaluates prompts, graph/module configs,
report templates, and policies from run traces without directly touching live
hardware-control code.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TargetType = Literal["prompt", "tool", "graph", "report", "policy", "code_patch"]
TaskStatus = Literal["draft", "running", "evaluated", "failed", "complete"]
VariantStatus = Literal[
    "draft",
    "generated",
    "evaluated",
    "gate_passed",
    "approved",
    "active_next_run",
    "active",
    "rejected",
    "rolled_back",
]


class EvolutionTrace(BaseModel):
    trace_id: str
    run_id: str
    graph_id: str | None = None
    graph_version: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    human_feedback: list[dict[str, Any]] = Field(default_factory=list)


class EvolutionTaskCreate(BaseModel):
    target_type: TargetType
    target_id: str = Field(..., min_length=1)
    source_run_ids: list[str] = Field(default_factory=list)
    objective: str = Field(..., min_length=1)
    constraints: dict[str, Any] = Field(default_factory=dict)


class EvolutionTask(BaseModel):
    task_id: str
    target_type: TargetType
    target_id: str
    source_run_ids: list[str] = Field(default_factory=list)
    objective: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = "draft"
    created_at: str
    updated_at: str
    trace_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    gate_id: str
    passed: bool
    score: float | None = None
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class EvolutionVariant(BaseModel):
    variant_id: str
    task_id: str
    parent_version: str | None = None
    target_type: TargetType
    target_id: str
    body: dict[str, Any] = Field(default_factory=dict)
    diff: str | None = None
    score: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    gate_results: list[GateResult] = Field(default_factory=list)
    status: VariantStatus = "draft"
    created_at: str
    updated_at: str
    source_trace_ids: list[str] = Field(default_factory=list)
    activation: dict[str, Any] = Field(default_factory=dict)


class EvolutionActivationRequest(BaseModel):
    operator: str = "operator"
    note: str = ""
    activate_runtime: bool = True


class EvolutionRollbackRequest(BaseModel):
    operator: str = "operator"
    note: str = ""
