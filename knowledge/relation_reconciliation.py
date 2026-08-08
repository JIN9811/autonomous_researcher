"""Typed contracts for Knowledge Graph relation reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_relation_id(*parts: object, prefix: str) -> str:
    canonical = json.dumps([str(part) for part in parts], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


@dataclass(frozen=True, slots=True)
class RelationWorkItem:
    work_id: str
    node_id: str
    graph_revision: str
    evidence_hash: str
    status: str = "pending"
    attempts: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RelationProposal:
    proposal_id: str
    version: int
    work_id: str
    source_id: str
    source_class: str
    target_id: str
    target_class: str
    relation_type: str
    confidence: float
    evidence_score: float
    rationale: str
    provenance_refs: tuple[str, ...]
    model_snapshot: dict[str, Any]
    ontology_version: str
    graph_revision: str
    graph_context_hash: str
    status: str = "pending"
    supersedes: str = ""
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance_refs", tuple(str(item) for item in self.provenance_refs if str(item)))
        object.__setattr__(self, "model_snapshot", dict(self.model_snapshot))
        object.__setattr__(self, "confidence", max(0.0, min(float(self.confidence), 1.0)))
        object.__setattr__(self, "evidence_score", max(0.0, min(float(self.evidence_score), 1.0)))

    def relationship(self) -> dict[str, Any]:
        relation_id = stable_relation_id(
            self.source_id,
            self.relation_type,
            self.target_id,
            prefix="relation",
        )
        return {
            "relation_id": relation_id,
            "relation_type": self.relation_type,
            "source_id": self.source_id,
            "source_class": self.source_class,
            "target_id": self.target_id,
            "target_class": self.target_class,
            "properties": {
                "proposal_id": self.proposal_id,
                "confidence": self.confidence,
                "evidence_score": self.evidence_score,
                "decision_status": self.status,
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RelationDecision:
    decision_id: str
    proposal_id: str
    proposal_version: int
    decision: str
    decision_source: str
    operator: str
    rationale: str
    accepted_relation: dict[str, Any] = field(default_factory=dict)
    original_relation: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    promotion_receipt: dict[str, Any] = field(default_factory=dict)
    decided_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        allowed = {"approved", "revised_approved", "rejected", "deferred"}
        if self.decision not in allowed:
            raise ValueError(f"unsupported relation decision: {self.decision}")
        object.__setattr__(self, "accepted_relation", dict(self.accepted_relation))
        object.__setattr__(self, "original_relation", dict(self.original_relation))
        object.__setattr__(self, "validation", dict(self.validation))
        object.__setattr__(self, "promotion_receipt", dict(self.promotion_receipt))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphEditDraft:
    draft_id: str
    graph_revision: str
    operator: str
    changes: tuple[dict[str, Any], ...]
    validation: dict[str, Any] = field(default_factory=dict)
    status: str = "draft"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "changes", tuple(dict(item) for item in self.changes))
        object.__setattr__(self, "validation", dict(self.validation))

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changes"] = list(self.changes)
        return payload
