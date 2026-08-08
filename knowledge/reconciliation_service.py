"""LLM-assisted, ontology-bounded Knowledge Graph relation reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backends.llm_lease import LLMLeaseBusy, RECONCILIATION_PRIORITY
from knowledge.relation_reconciliation import (
    GraphEditDraft,
    GraphGapDetector,
    RelationCandidate,
    RelationCandidateGenerator,
    RelationDecision,
    RelationProposal,
    stable_relation_id,
)
from knowledge.relation_store import RelationStore


class GraphRevisionConflict(RuntimeError):
    """Raised when an optimistic graph/proposal revision no longer matches."""


class KnowledgeReconciliationService:
    AUTO_CONFIDENCE = 0.90
    AUTO_EVIDENCE_SCORE = 0.80
    EDITABLE_METADATA = frozenset({"label", "alias", "note", "tags"})
    RELATION_LIFECYCLE = frozenset({"deprecated", "revoked"})

    def __init__(
        self,
        *,
        project_root: Path,
        knowledge_service: Any,
        agent_context: Any,
        store: RelationStore | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.knowledge_service = knowledge_service
        self.agent_context = agent_context
        self.store = store or RelationStore(self.project_root / "memory" / "knowledge" / "reconciliation")
        self.detector = GraphGapDetector()
        self.generator = RelationCandidateGenerator()

    @property
    def backend(self) -> Any:
        return self.knowledge_service.repository.backend

    def scan_gaps(self, *, limit: int = 10) -> dict[str, Any]:
        snapshot = self.backend.query(
            {"kind": "reconciliation_gaps", "limit": 500, "include_properties": True}
        )
        if not snapshot.get("ok", False):
            return {"ok": False, "status": "graph_unavailable", "gaps": [], "queued": 0}
        graph_revision = str(snapshot.get("graph_revision") or self._snapshot_hash(snapshot))
        gaps = self.detector.detect(snapshot, limit=limit)
        queued = [
            self.store.enqueue_node(
                gap.node_id,
                graph_revision=graph_revision,
                evidence_hash=gap.evidence_hash,
            )
            for gap in gaps
        ]
        return {
            "ok": True,
            "status": "queued" if queued else "no_gaps",
            "graph_revision": graph_revision,
            "gaps": [self._gap_dict(gap) for gap in gaps],
            "queued": len(queued),
        }

    async def reconcile_batch(self, *, limit: int = 10, background: bool = False) -> dict[str, Any]:
        loaded_check = getattr(self.agent_context, "selected_model_loaded", None)
        if loaded_check is not None and not await loaded_check("knowledge_relation"):
            return {"ok": True, "status": "model_unloaded", "proposals": [], "processed": 0}
        scan = self.scan_gaps(limit=max(limit, 10))
        if not scan.get("ok", False):
            return {**scan, "proposals": [], "processed": 0}
        work_items = self.store.claim_pending(limit=limit)
        proposals: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for work in work_items:
            try:
                proposal = await self._propose(work, background=background)
                if proposal is None:
                    self.store.release_work(work.work_id, error="no ontology-compatible candidates")
                    continue
                self.store.append_proposal(proposal)
                if self._eligible_for_automatic_promotion(proposal):
                    self.approve(proposal.proposal_id, operator="knowledge_agent:auto", rationale="Automatic relation policy passed.")
                resolved = self.store.get_proposal(proposal.proposal_id) or proposal
                proposals.append(resolved.as_dict())
            except LLMLeaseBusy as exc:
                self.store.release_work(work.work_id, error=str(exc))
                errors.append({"work_id": work.work_id, "error": "llm_busy"})
                break
            except Exception as exc:
                self.store.release_work(work.work_id, error=f"{type(exc).__name__}: {exc}")
                errors.append({"work_id": work.work_id, "error": f"{type(exc).__name__}: {exc}"})
        status = "completed"
        if errors and not proposals:
            status = "degraded"
        elif errors:
            status = "partial"
        return {
            "ok": not errors,
            "status": status,
            "processed": len(proposals),
            "proposals": proposals,
            "errors": errors,
            "store": self.store.stats(),
        }

    async def _propose(self, work: Any, *, background: bool) -> RelationProposal | None:
        context = self.backend.query(
            {
                "kind": "reconciliation_context",
                "node_id": work.node_id,
                "limit": 100,
                "include_properties": True,
            }
        )
        nodes = [dict(item) for item in context.get("nodes", []) if isinstance(item, dict)]
        edges = [dict(item) for item in context.get("edges", []) if isinstance(item, dict)]
        source = next((node for node in nodes if str(node.get("id") or "") == work.node_id), None)
        if source is None:
            raise ValueError(f"relation source no longer exists: {work.node_id}")
        candidates = self.generator.rank(
            source,
            nodes,
            edges,
            self.knowledge_service.registry,
            limit=8,
        )
        if not candidates:
            return None
        prompt = self._proposal_prompt(source, candidates, work.graph_revision)
        response = await self.agent_context.complete(
            "knowledge_relation",
            prompt,
            timeout_s=90.0,
            priority=RECONCILIATION_PRIORITY,
            owner=f"knowledge-reconciliation:{work.work_id}",
            lease_wait=not background,
        )
        payload = self._parse_json_object(str(response.text or ""))
        selected = self._selected_candidate(payload, candidates, source_id=work.node_id)
        confidence = max(0.0, min(float(payload.get("confidence", 0.0)), 1.0))
        rationale = str(payload.get("rationale") or "").strip()[:2000]
        if not rationale:
            raise ValueError("relation proposal rationale is required")
        context_hash = self._snapshot_hash(context)
        previous = next(
            (
                item
                for item in self.store.list_proposals(limit=1000)
                if item.source_id == selected.source_id
                and item.relation_type == selected.relation_type
                and item.target_id == selected.target_id
            ),
            None,
        )
        version = previous.version + 1 if previous is not None else 1
        supersedes = previous.proposal_id if previous is not None else ""
        proposal_id = stable_relation_id(
            work.work_id,
            selected.relation_type,
            selected.target_id,
            context_hash,
            version,
            prefix="relation-proposal",
        )
        return RelationProposal(
            proposal_id=proposal_id,
            version=version,
            work_id=work.work_id,
            source_id=selected.source_id,
            source_class=selected.source_class,
            target_id=selected.target_id,
            target_class=selected.target_class,
            relation_type=selected.relation_type,
            confidence=confidence,
            evidence_score=selected.score,
            rationale=rationale,
            provenance_refs=selected.provenance_refs,
            model_snapshot={
                "model": str(getattr(response, "model", "")),
                "backend": str(getattr(self.agent_context, "active_backend", "")),
                "task_type": "knowledge_relation",
            },
            ontology_version=self.knowledge_service.registry.version_id,
            graph_revision=str(context.get("graph_revision") or work.graph_revision),
            graph_context_hash=context_hash,
            supersedes=supersedes,
        )

    def approve(self, proposal_id: str, *, operator: str, rationale: str = "") -> dict[str, Any]:
        proposal = self._require_proposal(proposal_id)
        relation = proposal.relationship()
        relation["properties"]["decision_status"] = "approved"
        validation = self._validate_existing_relation(relation)
        receipt = self._promote(proposal, relation, decision="approved", operator=operator, rationale=rationale)
        decision = RelationDecision(
            decision_id=stable_relation_id(proposal_id, "approved", operator, prefix="decision"),
            proposal_id=proposal_id,
            proposal_version=proposal.version,
            decision="approved",
            decision_source="automatic" if operator == "knowledge_agent:auto" else "operator",
            operator=operator,
            rationale=rationale or proposal.rationale,
            accepted_relation=relation,
            original_relation=proposal.relationship(),
            validation=validation,
            promotion_receipt=receipt,
        )
        return self.store.append_decision(decision).as_dict()

    def revise_and_approve(
        self,
        proposal_id: str,
        *,
        target_id: str,
        relation_type: str,
        rationale: str,
        operator: str,
    ) -> dict[str, Any]:
        proposal = self._require_proposal(proposal_id)
        target = self._lookup_nodes([target_id]).get(target_id)
        if target is None:
            raise ValueError(f"relation target does not exist: {target_id}")
        relation = {
            "relation_id": stable_relation_id(proposal.source_id, relation_type, target_id, prefix="relation"),
            "relation_type": str(relation_type),
            "source_id": proposal.source_id,
            "source_class": proposal.source_class,
            "target_id": str(target_id),
            "target_class": str(target.get("kind") or "KnowledgeNode"),
            "properties": {
                "proposal_id": proposal.proposal_id,
                "confidence": proposal.confidence,
                "evidence_score": proposal.evidence_score,
                "decision_status": "revised_approved",
            },
        }
        validation = self._validate_existing_relation(relation)
        receipt = self._promote(proposal, relation, decision="revised_approved", operator=operator, rationale=rationale)
        decision = RelationDecision(
            decision_id=stable_relation_id(proposal_id, "revised_approved", target_id, relation_type, operator, prefix="decision"),
            proposal_id=proposal_id,
            proposal_version=proposal.version,
            decision="revised_approved",
            decision_source="operator",
            operator=operator,
            rationale=str(rationale)[:2000],
            accepted_relation=relation,
            original_relation=proposal.relationship(),
            validation=validation,
            promotion_receipt=receipt,
        )
        return self.store.append_decision(decision).as_dict()

    def reject(self, proposal_id: str, *, operator: str, rationale: str) -> dict[str, Any]:
        return self._record_nonpromotion(proposal_id, "rejected", operator, rationale)

    def defer(self, proposal_id: str, *, operator: str, rationale: str) -> dict[str, Any]:
        return self._record_nonpromotion(proposal_id, "deferred", operator, rationale)

    def re_evaluate(self, proposal_id: str) -> dict[str, Any]:
        proposal = self._require_proposal(proposal_id)
        self.store.enqueue_node(
            proposal.source_id,
            graph_revision=f"{proposal.graph_revision}:reevaluate:{proposal.version + 1}",
            evidence_hash=proposal.graph_context_hash,
        )
        return {"ok": True, "status": "queued", "proposal_id": proposal_id, "next_version": proposal.version + 1}

    def assert_proposal_current(self, proposal_id: str, *, version: int, graph_context_hash: str) -> RelationProposal:
        proposal = self._require_proposal(proposal_id)
        if proposal.version != int(version):
            raise GraphRevisionConflict(
                f"proposal version changed: expected={version} current={proposal.version}"
            )
        if proposal.graph_context_hash != str(graph_context_hash):
            raise GraphRevisionConflict("proposal graph context changed; re-evaluation is required")
        if proposal.status not in {"pending", "deferred"}:
            raise GraphRevisionConflict(f"proposal is already resolved: {proposal.status}")
        return proposal

    def validate_graph_edit(
        self,
        *,
        graph_revision: str,
        changes: list[dict[str, Any]],
        operator: str,
        draft_id: str = "",
    ) -> dict[str, Any]:
        snapshot = self.backend.query(
            {"kind": "reconciliation_gaps", "limit": 500, "include_properties": True}
        )
        current_revision = str(snapshot.get("graph_revision") or self._snapshot_hash(snapshot))
        if str(graph_revision) != current_revision:
            raise GraphRevisionConflict(
                f"graph revision changed: expected={graph_revision} current={current_revision}"
            )
        if not isinstance(changes, list) or len(changes) > 100:
            raise ValueError("graph edit changes must be a list with at most 100 entries")
        nodes = {
            str(node.get("id") or ""): dict(node)
            for node in snapshot.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }
        edges = {
            str(edge.get("id") or ""): dict(edge)
            for edge in snapshot.get("edges", [])
            if isinstance(edge, dict) and edge.get("id")
        }
        normalized: list[dict[str, Any]] = []
        staged_relations = {
            (str(edge.get("source") or ""), str(edge.get("type") or ""), str(edge.get("target") or ""))
            for edge in edges.values()
        }
        for raw in changes:
            if not isinstance(raw, dict):
                raise ValueError("each graph edit change must be an object")
            operation = str(raw.get("operation") or "")
            if operation == "move_node":
                node_id = self._require_existing_node(raw.get("node_id"), nodes)
                normalized.append({"operation": operation, "node_id": node_id, "x": float(raw.get("x", 0)), "y": float(raw.get("y", 0))})
                continue
            if operation == "update_node_metadata":
                node_id = self._require_existing_node(raw.get("node_id"), nodes)
                metadata = raw.get("metadata")
                if not isinstance(metadata, dict) or not metadata:
                    raise ValueError("metadata edit requires a non-empty metadata object")
                unknown = sorted(set(metadata) - self.EDITABLE_METADATA)
                if unknown:
                    raise ValueError(f"metadata fields are not editable: {', '.join(unknown)}")
                clean_metadata = self._normalize_edit_metadata(metadata)
                normalized.append({"operation": operation, "node_id": node_id, "metadata": clean_metadata})
                continue
            if operation == "add_relation":
                relation = self._normalized_edit_relation(raw, nodes)
                key = (relation["source_id"], relation["relation_type"], relation["target_id"])
                if key in staged_relations:
                    raise ValueError("duplicate relationship is forbidden")
                staged_relations.add(key)
                normalized.append({"operation": operation, **relation})
                continue
            if operation == "revise_relation":
                edge_id = str(raw.get("edge_id") or "")
                original = edges.get(edge_id)
                if original is None:
                    raise ValueError(f"relationship does not exist: {edge_id}")
                relation = self._normalized_edit_relation(
                    {
                        "source_id": original.get("source"),
                        "target_id": raw.get("target_id") or original.get("target"),
                        "relation_type": raw.get("relation_type") or original.get("type"),
                    },
                    nodes,
                )
                key = (relation["source_id"], relation["relation_type"], relation["target_id"])
                if key in staged_relations and key != (
                    str(original.get("source") or ""),
                    str(original.get("type") or ""),
                    str(original.get("target") or ""),
                ):
                    raise ValueError("duplicate revised relationship is forbidden")
                normalized.append({"operation": operation, "edge_id": edge_id, "original": original, **relation})
                continue
            if operation == "set_relation_status":
                edge_id = str(raw.get("edge_id") or "")
                edge = edges.get(edge_id)
                status = str(raw.get("status") or "")
                if edge is None:
                    raise ValueError(f"relationship does not exist: {edge_id}")
                if status not in self.RELATION_LIFECYCLE:
                    raise ValueError("relationship status must be deprecated or revoked")
                relation = self._normalized_edit_relation(
                    {"source_id": edge.get("source"), "target_id": edge.get("target"), "relation_type": edge.get("type")},
                    nodes,
                )
                normalized.append({"operation": operation, "edge_id": edge_id, "status": status, **relation})
                continue
            raise ValueError(f"unsupported graph edit operation: {operation}")
        resolved_draft_id = draft_id or stable_relation_id(
            graph_revision,
            operator,
            json.dumps(normalized, ensure_ascii=True, sort_keys=True, default=str),
            prefix="graph-edit-draft",
        )
        validation = {
            "ok": True,
            "graph_revision": current_revision,
            "change_count": len(normalized),
            "semantic_change_count": sum(1 for item in normalized if item["operation"] != "move_node"),
        }
        draft = GraphEditDraft(
            draft_id=resolved_draft_id,
            graph_revision=current_revision,
            operator=str(operator or "local-operator"),
            changes=tuple(normalized),
            validation=validation,
        )
        self.store.save_edit_draft(draft)
        return {"ok": True, "draft": draft.as_dict(), "validation": validation}

    def apply_graph_edit(
        self,
        *,
        graph_revision: str,
        changes: list[dict[str, Any]],
        operator: str,
        draft_id: str = "",
    ) -> dict[str, Any]:
        validated = self.validate_graph_edit(
            graph_revision=graph_revision,
            changes=changes,
            operator=operator,
            draft_id=draft_id,
        )
        draft = GraphEditDraft(**validated["draft"])
        snapshot = self.backend.query(
            {"kind": "reconciliation_gaps", "limit": 500, "include_properties": True}
        )
        nodes = {
            str(node.get("id") or ""): dict(node)
            for node in snapshot.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }
        entity_refs: list[dict[str, Any]] = []
        relationship_intents: list[dict[str, Any]] = []
        for change in draft.changes:
            operation = str(change["operation"])
            if operation == "update_node_metadata":
                node = nodes[change["node_id"]]
                entity_refs.append(
                    {
                        "entity_id": change["node_id"],
                        "entity_class": str(node.get("kind") or "KnowledgeNode"),
                        **dict(change["metadata"]),
                    }
                )
            elif operation == "add_relation":
                relationship_intents.append(self._edit_intent(change, status="active", operator=operator))
            elif operation == "revise_relation":
                original = dict(change["original"])
                relationship_intents.append(
                    self._edit_intent(
                        {
                            "relation_id": change["edge_id"],
                            "source_id": original["source"],
                            "source_class": str(nodes[original["source"]].get("kind") or "KnowledgeNode"),
                            "target_id": original["target"],
                            "target_class": str(nodes[original["target"]].get("kind") or "KnowledgeNode"),
                            "relation_type": original["type"],
                        },
                        status="deprecated",
                        operator=operator,
                    )
                )
                relationship_intents.append(self._edit_intent(change, status="active", operator=operator))
            elif operation == "set_relation_status":
                relationship_intents.append(self._edit_intent(change, status=change["status"], operator=operator))
        receipt: dict[str, Any] = {"ok": True, "status": "layout_only"}
        if entity_refs or relationship_intents:
            now = datetime.now(timezone.utc).isoformat()
            receipt = self.knowledge_service.ingest(
                {
                    "run_id": "knowledge-graph-edit",
                    "cycle_id": draft.draft_id,
                    "source_agent": "knowledge_agent",
                    "event_type": "agent.completed",
                    "occurred_at": now,
                    "entity_refs": entity_refs,
                    "relationship_intents": relationship_intents,
                    "artifact_refs": [],
                    "payload_summary": {
                        "operation": "knowledge_graph_edit",
                        "draft_id": draft.draft_id,
                        "operator": operator,
                        "change_count": len(draft.changes),
                    },
                    "provenance": {
                        "draft_id": draft.draft_id,
                        "graph_revision": draft.graph_revision,
                        "operator": operator,
                    },
                }
            )
            if not receipt.get("ok", False):
                raise RuntimeError(f"knowledge graph edit ingest failed: {receipt}")
        applied = replace(draft, status="applied", updated_at=datetime.now(timezone.utc).isoformat())
        self.store.save_edit_draft(applied)
        decision = {
            "schema": "knowledge_graph_edit_decision.v1",
            "decision_id": stable_relation_id(draft.draft_id, "applied", prefix="graph-edit-decision"),
            "draft_id": draft.draft_id,
            "graph_revision": draft.graph_revision,
            "operator": operator,
            "status": "applied",
            "changes": list(draft.changes),
            "validation": validated["validation"],
            "promotion_receipt": receipt,
            "decided_at": applied.updated_at,
        }
        self.store.append_graph_edit_decision(decision)
        return {"ok": True, "status": "applied", "draft": applied.as_dict(), "decision": decision, "receipt": receipt}

    def _record_nonpromotion(self, proposal_id: str, decision_name: str, operator: str, rationale: str) -> dict[str, Any]:
        proposal = self._require_proposal(proposal_id)
        decision = RelationDecision(
            decision_id=stable_relation_id(proposal_id, decision_name, operator, prefix="decision"),
            proposal_id=proposal_id,
            proposal_version=proposal.version,
            decision=decision_name,
            decision_source="operator",
            operator=operator,
            rationale=str(rationale)[:2000],
            original_relation=proposal.relationship(),
        )
        return self.store.append_decision(decision).as_dict()

    def _eligible_for_automatic_promotion(self, proposal: RelationProposal) -> bool:
        if proposal.confidence < self.AUTO_CONFIDENCE or proposal.evidence_score < self.AUTO_EVIDENCE_SCORE:
            return False
        if not proposal.provenance_refs or proposal.source_id == proposal.target_id:
            return False
        try:
            self._validate_existing_relation(proposal.relationship())
        except ValueError:
            return False
        return True

    def _validate_existing_relation(self, relation: dict[str, Any]) -> dict[str, Any]:
        node_ids = [str(relation["source_id"]), str(relation["target_id"])]
        nodes = self._lookup_nodes(node_ids)
        missing = [node_id for node_id in node_ids if node_id not in nodes]
        if missing:
            raise ValueError(f"relation references missing nodes: {', '.join(missing)}")
        if relation["source_id"] == relation["target_id"]:
            raise ValueError("self-referential relationships are forbidden")
        report = self.knowledge_service.validator.validate_relationship(relation)
        if not report.ok:
            raise ValueError("; ".join(report.errors))
        context = self.backend.query(
            {"kind": "reconciliation_context", "node_id": relation["source_id"], "limit": 500, "include_properties": False}
        )
        duplicate = any(
            str(edge.get("source") or "") == relation["source_id"]
            and str(edge.get("target") or "") == relation["target_id"]
            and str(edge.get("type") or "") == relation["relation_type"]
            for edge in context.get("edges", [])
            if isinstance(edge, dict)
        )
        if duplicate:
            raise ValueError("duplicate relationship is forbidden")
        return {"ok": True, "ontology": True, "existing_nodes": True, "duplicate": False}

    def _promote(
        self,
        proposal: RelationProposal,
        relation: dict[str, Any],
        *,
        decision: str,
        operator: str,
        rationale: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        run_id = self._node_run_id(proposal.source_id) or "knowledge-reconciliation"
        event = {
            "run_id": run_id,
            "cycle_id": f"relation:{proposal.proposal_id}",
            "source_agent": "knowledge_agent",
            "event_type": "agent.completed",
            "occurred_at": now,
            "entity_refs": [],
            "relationship_intents": [relation],
            "artifact_refs": [
                {"kind": "relation_provenance", "path": ref}
                for ref in proposal.provenance_refs
            ],
            "payload_summary": {
                "operation": "knowledge_relation_reconciliation",
                "proposal_id": proposal.proposal_id,
                "decision": decision,
                "operator": operator,
                "rationale": str(rationale or proposal.rationale)[:2000],
            },
            "provenance": {
                "proposal_id": proposal.proposal_id,
                "model_snapshot": proposal.model_snapshot,
                "graph_revision": proposal.graph_revision,
                "refs": list(proposal.provenance_refs),
            },
        }
        receipt = self.knowledge_service.ingest(event)
        if not receipt.get("ok", False):
            raise RuntimeError(f"knowledge relation promotion failed: {receipt}")
        return dict(receipt)

    def _lookup_nodes(self, node_ids: list[str]) -> dict[str, dict[str, Any]]:
        result = self.backend.query(
            {"kind": "node_lookup", "node_ids": node_ids, "limit": len(node_ids), "include_properties": True}
        )
        return {
            str(node.get("id") or ""): dict(node)
            for node in result.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }

    @staticmethod
    def _require_existing_node(raw_node_id: Any, nodes: dict[str, dict[str, Any]]) -> str:
        node_id = str(raw_node_id or "")
        if node_id not in nodes:
            raise ValueError(f"graph edit cannot create or reference a new node: {node_id}")
        return node_id

    @classmethod
    def _normalize_edit_metadata(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in metadata.items():
            if key == "tags":
                if not isinstance(value, list):
                    raise ValueError("metadata tags must be a list")
                normalized[key] = [str(item)[:120] for item in value if str(item).strip()][:50]
            elif isinstance(value, (str, int, float, bool)) or value is None:
                normalized[key] = str(value)[:2000] if isinstance(value, str) else value
            else:
                raise ValueError(f"metadata field {key} must be scalar")
        return normalized

    def _normalized_edit_relation(
        self,
        raw: dict[str, Any],
        nodes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = self._require_existing_node(raw.get("source_id"), nodes)
        target_id = self._require_existing_node(raw.get("target_id"), nodes)
        if source_id == target_id:
            raise ValueError("self-referential relationships are forbidden")
        relation_type = str(raw.get("relation_type") or "")
        relation = {
            "relation_id": str(raw.get("relation_id") or stable_relation_id(source_id, relation_type, target_id, prefix="relation")),
            "source_id": source_id,
            "source_class": str(nodes[source_id].get("kind") or "KnowledgeNode"),
            "target_id": target_id,
            "target_class": str(nodes[target_id].get("kind") or "KnowledgeNode"),
            "relation_type": relation_type,
        }
        report = self.knowledge_service.validator.validate_relationship(relation)
        if not report.ok:
            raise ValueError("; ".join(report.errors))
        return relation

    @staticmethod
    def _edit_intent(change: dict[str, Any], *, status: str, operator: str) -> dict[str, Any]:
        return {
            "relation_id": str(change.get("relation_id") or stable_relation_id(change["source_id"], change["relation_type"], change["target_id"], prefix="relation")),
            "relation_type": change["relation_type"],
            "source_id": change["source_id"],
            "source_class": change["source_class"],
            "target_id": change["target_id"],
            "target_class": change["target_class"],
            "properties": {
                "lifecycle_status": status,
                "edited_by": operator,
                "edit_mode": True,
            },
        }

    def _node_run_id(self, node_id: str) -> str:
        node = self._lookup_nodes([node_id]).get(node_id, {})
        return str(node.get("run_id") or "")

    def _require_proposal(self, proposal_id: str) -> RelationProposal:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown relation proposal: {proposal_id}")
        return proposal

    @staticmethod
    def _proposal_prompt(source: dict[str, Any], candidates: list[RelationCandidate], graph_revision: str) -> str:
        payload = {
            "instruction": "Select exactly one supplied candidate. Do not create nodes or relation types. Return JSON only.",
            "source": source,
            "graph_revision": graph_revision,
            "candidates": [
                {
                    "source_id": item.source_id,
                    "target_id": item.target_id,
                    "relation_type": item.relation_type,
                    "target_class": item.target_class,
                    "evidence_score": item.score,
                    "score_factors": item.score_factors,
                    "provenance_refs": list(item.provenance_refs),
                }
                for item in candidates
            ],
            "response_schema": {
                "source_id": "existing source ID",
                "target_id": "one supplied target ID",
                "relation_type": "one supplied relation type",
                "confidence": "0..1",
                "rationale": "evidence-based explanation",
            },
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        payload = json.loads(clean)
        if not isinstance(payload, dict):
            raise ValueError("relation proposal must be a JSON object")
        return payload

    @staticmethod
    def _selected_candidate(payload: dict[str, Any], candidates: list[RelationCandidate], *, source_id: str) -> RelationCandidate:
        if str(payload.get("source_id") or "") != source_id:
            raise ValueError("LLM selected an unknown relation source")
        target_id = str(payload.get("target_id") or "")
        relation_type = str(payload.get("relation_type") or "")
        selected = next(
            (item for item in candidates if item.target_id == target_id and item.relation_type == relation_type),
            None,
        )
        if selected is None:
            raise ValueError("LLM selected a relationship outside the supplied candidates")
        return selected

    @staticmethod
    def _snapshot_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _gap_dict(gap: Any) -> dict[str, Any]:
        return {
            "node_id": gap.node_id,
            "node_class": gap.node_class,
            "gap_type": gap.gap_type,
            "component_size": gap.component_size,
            "degree": gap.degree,
            "evidence_hash": gap.evidence_hash,
        }


class KnowledgeReconciliationWorker:
    """App-owned background worker that never prewarms or waits for an LLM."""

    def __init__(self, service: KnowledgeReconciliationService, *, interval_s: float = 60.0) -> None:
        self.service = service
        self.interval_s = max(5.0, float(interval_s))
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._status: dict[str, Any] = {"status": "idle", "running": False, "last_result": {}}

    def start(self) -> dict[str, Any]:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="knowledge-reconciliation-worker")
        return self.status()

    def wake(self) -> dict[str, Any]:
        self._wake.set()
        return self.status()

    async def run_once(self) -> dict[str, Any]:
        loaded_check = getattr(self.service.agent_context, "selected_model_loaded", None)
        if loaded_check is not None and not await loaded_check("knowledge_relation"):
            result = {"ok": True, "status": "model_unloaded", "processed": 0, "proposals": []}
        else:
            result = await self.service.reconcile_batch(limit=10, background=True)
        self._status = {"status": result.get("status", "unknown"), "running": False, "last_result": result}
        return result

    async def shutdown(self) -> None:
        self._stopping.set()
        self._wake.set()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._status["running"] = False

    def status(self) -> dict[str, Any]:
        return {
            **self._status,
            "started": self._task is not None and not self._task.done(),
            "store": self.service.store.stats(),
        }

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._stopping.is_set():
                break
            self._status["running"] = True
            try:
                await self.run_once()
            except Exception as exc:
                self._status = {
                    "status": "degraded",
                    "running": False,
                    "last_result": {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                }
