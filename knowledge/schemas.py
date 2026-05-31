"""
File purpose:
- Typed schema definitions for Knowledge Agent memory and evolution evidence.

Key classes/functions:
- MemoryRecord
- ExperimentKnowledgeRecord
- AgentPerformanceRecord
- FailurePatternRecord
- SuccessPatternRecord
- EvolutionEvidencePack
- EvolutionOutcomeRecord

Inputs/outputs:
- Input: runtime reports, metrics, artifacts, provenance refs
- Output: validated memory/evidence records used by RAG, BO, Guardian, and Self-Evolution

Dependencies:
- pydantic.BaseModel

Modification guide:
- Safe places to edit: additive optional fields and new record types
- Risky places to edit: MemoryRecord required fields used in DB serialization
- Related files: knowledge/experiment_db.py, agents/knowledge_agent.py, knowledge/stores.py
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """Represents one stored experiment memory snapshot."""

    run_id: str = Field(..., description="Run identifier")
    experiment_id: str = Field(..., description="Experiment identifier")
    summary: str = Field(..., description="Compact memory summary")
    score: float = Field(..., description="Objective score")
    uncertainty: float = Field(..., description="Uncertainty estimate")
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list, description="Raw artifact references used by analysis")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Key observed metrics for downstream retrieval")
    failure_tags: list[str] = Field(default_factory=list, description="Quality or failure tags from the loop")


KnowledgeSourceType = Literal[
    "project_guideline",
    "official_doc",
    "scientific_paper",
    "run_artifact",
    "experiment_memory",
    "failure_memory",
    "success_pattern",
    "evolution_variant",
    "operator_feedback",
    "graph_backend",
]


class ProvenanceRef(BaseModel):
    """PROV-like lineage for a knowledge record."""

    was_generated_by: str = "knowledge_agent"
    used: list[str] = Field(default_factory=list)
    was_associated_with: list[str] = Field(default_factory=list)
    was_derived_from: list[str] = Field(default_factory=list)
    artifact_fingerprints: dict[str, str] = Field(default_factory=dict)


class KnowledgeSourceRef(BaseModel):
    """One retrieval/source reference with trust and recency evidence."""

    source_type: KnowledgeSourceType
    source_ref: str
    trust_level: str = "unreviewed"
    recency: str = "unknown"
    retrieval_score: float = 0.0
    used_for: list[str] = Field(default_factory=list)


class ExperimentKnowledgeRecord(BaseModel):
    """Run/experiment-level verified memory with provenance."""

    schema_version: str = "experiment_knowledge_v1"
    record_id: str
    run_id: str
    experiment_id: str
    candidate_id: str = ""
    summary: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    source_refs: list[KnowledgeSourceRef] = Field(default_factory=list)
    created_at: str = ""


class AgentPerformanceRecord(BaseModel):
    """Agent-level performance ledger entry used by self-evolution ranking."""

    schema_version: str = "agent_performance_v1"
    record_id: str
    run_id: str
    agent_id: str
    stage: str
    status: str = "unknown"
    score: float = 0.0
    signals: dict[str, Any] = Field(default_factory=dict)
    evolution_hint: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    created_at: str = ""


class FailurePatternRecord(BaseModel):
    """Repeated or current failure pattern with do-not-repeat guidance."""

    schema_version: str = "failure_pattern_v1"
    pattern_id: str
    affected_agents: list[str] = Field(default_factory=list)
    failure_type: str
    recurrence_count: int = 1
    first_seen_run_id: str = ""
    last_seen_run_id: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    root_cause_hypothesis: str = ""
    do_not_repeat: list[str] = Field(default_factory=list)
    recommended_evolution: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    created_at: str = ""
    updated_at: str = ""


class SuccessPatternRecord(BaseModel):
    """Reusable successful procedure/skill candidate."""

    schema_version: str = "success_pattern_v1"
    skill_id: str
    agent_id: str
    scope: str
    preconditions: list[str] = Field(default_factory=list)
    procedure_summary: str = ""
    success_metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    operator_review_required: bool = True
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    created_at: str = ""
    updated_at: str = ""


class EvolutionEvidencePack(BaseModel):
    """Knowledge-to-SelfEvolution contract for one proposed target."""

    schema_version: str = "evolution_evidence_pack_v1"
    pack_id: str
    created_by: str = "knowledge_agent"
    target_type: str
    target_id: str
    priority: float = 0.0
    objective: str
    why_this_target: list[str] = Field(default_factory=list)
    supporting_records: dict[str, Any] = Field(default_factory=dict)
    recommended_changes: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    eval_metrics: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    created_at: str = ""


class EvolutionOutcomeRecord(BaseModel):
    """Before/after attribution after an evolved variant is activated."""

    schema_version: str = "evolution_outcome_v1"
    outcome_id: str
    variant_id: str
    target_type: str
    target_id: str
    parent_version: str = ""
    activated_for_run_id: str = ""
    comparison_window: dict[str, Any] = Field(default_factory=dict)
    metrics_delta: dict[str, Any] = Field(default_factory=dict)
    verdict: str = "observe"
    rollback_recommended: bool = False
    provenance: ProvenanceRef = Field(default_factory=ProvenanceRef)
    created_at: str = ""
