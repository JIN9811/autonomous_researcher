"""Typed contracts for Knowledge Graph relation reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from knowledge.ontology.registry import OntologyRegistry


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_relation_id(*parts: object, prefix: str) -> str:
    canonical = json.dumps([str(part) for part in parts], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


@dataclass(frozen=True, slots=True)
class GraphGap:
    node_id: str
    node_class: str
    gap_type: str
    component_size: int
    degree: int
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    source_id: str
    source_class: str
    target_id: str
    target_class: str
    relation_type: str
    allowed_target_classes: tuple[str, ...]
    score: float
    score_factors: dict[str, float]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_target_classes", tuple(self.allowed_target_classes))
        object.__setattr__(self, "score_factors", dict(self.score_factors))
        object.__setattr__(self, "provenance_refs", tuple(self.provenance_refs))


class GraphGapDetector:
    """Find structurally isolated nodes without inferring semantic relationships."""

    def detect(self, snapshot: dict[str, Any], *, limit: int = 10) -> list[GraphGap]:
        nodes = [dict(item) for item in snapshot.get("nodes", []) if isinstance(item, dict) and item.get("id")]
        edges = [dict(item) for item in snapshot.get("edges", []) if isinstance(item, dict)]
        node_by_id = {str(node["id"]): node for node in nodes}
        adjacency = {node_id: set() for node_id in node_by_id}
        for edge in edges:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source in adjacency and target in adjacency and source != target:
                adjacency[source].add(target)
                adjacency[target].add(source)

        components: list[set[str]] = []
        unseen = set(node_by_id)
        while unseen:
            seed = min(unseen)
            component: set[str] = set()
            stack = [seed]
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                unseen.discard(current)
                stack.extend(sorted(adjacency[current] - component, reverse=True))
            components.append(component)

        connected = [component for component in components if len(component) > 1]
        main_component = max(
            connected,
            key=lambda component: (
                any(str(node_by_id[node_id].get("kind")) == "Run" for node_id in component),
                len(component),
                sorted(component)[0],
            ),
            default=set(),
        )
        gaps: list[GraphGap] = []
        for component in components:
            for node_id in sorted(component):
                degree = len(adjacency[node_id])
                if degree == 0:
                    gap_type = "isolated"
                elif component != main_component:
                    gap_type = "disconnected_component"
                else:
                    continue
                node = node_by_id[node_id]
                evidence_hash = stable_relation_id(
                    node_id,
                    node.get("kind", "KnowledgeNode"),
                    _provenance_refs(node),
                    prefix="evidence",
                )
                gaps.append(
                    GraphGap(
                        node_id=node_id,
                        node_class=str(node.get("kind") or "KnowledgeNode"),
                        gap_type=gap_type,
                        component_size=len(component),
                        degree=degree,
                        evidence_hash=evidence_hash,
                    )
                )
        priority = {"isolated": 0, "disconnected_component": 1}
        gaps.sort(key=lambda item: (priority[item.gap_type], item.node_id))
        return gaps[: max(1, min(int(limit), 500))]


class RelationCandidateGenerator:
    """Rank only ontology-compatible relationships between existing nodes."""

    def rank(
        self,
        source: dict[str, Any],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        registry: OntologyRegistry,
        *,
        limit: int = 8,
    ) -> list[RelationCandidate]:
        source_id = str(source.get("id") or "")
        source_class = str(source.get("kind") or "KnowledgeNode")
        if not source_id:
            return []
        existing = {
            (str(edge.get("source") or ""), str(edge.get("type") or ""), str(edge.get("target") or ""))
            for edge in edges
        }
        source_neighbors = _neighbors(source_id, edges)
        source_provenance = set(_provenance_refs(source))
        candidates: list[RelationCandidate] = []
        for rule in registry.relations_from(source_class):
            for target in nodes:
                target_id = str(target.get("id") or "")
                target_class = str(target.get("kind") or "KnowledgeNode")
                if not target_id or target_id == source_id or target_class not in rule.target_classes:
                    continue
                if (source_id, rule.relation_type, target_id) in existing:
                    continue
                target_provenance = set(_provenance_refs(target))
                shared = source_provenance & target_provenance
                factors = {
                    "ontology_compatibility": 0.35,
                    "same_run": 0.25 if _same_nonempty(source, target, "run_id") else 0.0,
                    "same_cycle": 0.10 if _same_nonempty(source, target, "cycle_id") else 0.0,
                    "shared_provenance": min(0.20, 0.10 * len(shared)),
                    "temporal_proximity": 0.05 * _temporal_proximity(source, target),
                    "neighbor_overlap": 0.05 * _neighbor_overlap(source_neighbors, _neighbors(target_id, edges)),
                }
                score = round(sum(factors.values()), 6)
                candidates.append(
                    RelationCandidate(
                        source_id=source_id,
                        source_class=source_class,
                        target_id=target_id,
                        target_class=target_class,
                        relation_type=rule.relation_type,
                        allowed_target_classes=rule.target_classes,
                        score=score,
                        score_factors=factors,
                        provenance_refs=tuple(sorted(source_provenance | target_provenance)),
                    )
                )
        candidates.sort(key=lambda item: (-item.score, item.relation_type, item.target_id))
        return candidates[: max(1, min(int(limit), 100))]


def _provenance_refs(node: dict[str, Any]) -> tuple[str, ...]:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    raw = node.get("provenance_refs", properties.get("provenance_refs", ()))
    if isinstance(raw, dict):
        raw = [*raw.get("used", []), *raw.get("was_derived_from", []), *raw.get("was_associated_with", [])]
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw] if raw else []
    return tuple(sorted({str(item) for item in raw if str(item)}))


def _same_nonempty(left: dict[str, Any], right: dict[str, Any], key: str) -> bool:
    left_value = str(left.get(key) or "")
    return bool(left_value and left_value == str(right.get(key) or ""))


def _neighbors(node_id: str, edges: list[dict[str, Any]]) -> set[str]:
    related: set[str] = set()
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source == node_id and target:
            related.add(target)
        elif target == node_id and source:
            related.add(source)
    return related


def _neighbor_overlap(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _temporal_proximity(left: dict[str, Any], right: dict[str, Any]) -> float:
    try:
        left_time = datetime.fromisoformat(str(left.get("created_at") or "").replace("Z", "+00:00"))
        right_time = datetime.fromisoformat(str(right.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    delta = abs((left_time - right_time).total_seconds())
    return max(0.0, 1.0 - min(delta / 86400.0, 1.0))


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
