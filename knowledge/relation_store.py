"""Durable queue and append-only records for relation reconciliation."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from knowledge.relation_reconciliation import (
    GraphEditDraft,
    RelationDecision,
    RelationProposal,
    RelationWorkItem,
    stable_relation_id,
    utc_now,
)


class RelationStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.root / "work_queue.json"
        self.proposals_path = self.root / "proposals.jsonl"
        self.decisions_path = self.root / "decisions.jsonl"
        self.graph_edit_decisions_path = self.root / "graph_edit_decisions.jsonl"
        self.drafts_root = self.root / "drafts"
        self.drafts_root.mkdir(parents=True, exist_ok=True)

    def enqueue_node(self, node_id: str, *, graph_revision: str, evidence_hash: str) -> RelationWorkItem:
        clean_node = str(node_id).strip()
        if not clean_node:
            raise ValueError("relation work node_id is required")
        work_id = stable_relation_id(clean_node, graph_revision, evidence_hash, prefix="relation-work")
        with self._locked_json(self.queue_path) as queue:
            for raw in queue:
                if str(raw.get("work_id")) == work_id:
                    return RelationWorkItem(**raw)
            item = RelationWorkItem(
                work_id=work_id,
                node_id=clean_node,
                graph_revision=str(graph_revision),
                evidence_hash=str(evidence_hash),
            )
            queue.append(item.as_dict())
            return item

    def claim_pending(self, *, limit: int = 10) -> list[RelationWorkItem]:
        claimed: list[RelationWorkItem] = []
        with self._locked_json(self.queue_path) as queue:
            for index, raw in enumerate(queue):
                if len(claimed) >= max(1, min(int(limit), 100)):
                    break
                if str(raw.get("status") or "pending") != "pending":
                    continue
                item = RelationWorkItem(**raw)
                updated = replace(item, status="processing", updated_at=utc_now())
                queue[index] = updated.as_dict()
                claimed.append(updated)
        return claimed

    def release_work(self, work_id: str, *, error: str = "") -> RelationWorkItem:
        with self._locked_json(self.queue_path) as queue:
            for index, raw in enumerate(queue):
                if str(raw.get("work_id")) != work_id:
                    continue
                item = RelationWorkItem(**raw)
                updated = replace(
                    item,
                    status="pending",
                    attempts=item.attempts + 1,
                    updated_at=utc_now(),
                    last_error=str(error)[:2000],
                )
                queue[index] = updated.as_dict()
                return updated
        raise KeyError(f"unknown relation work item: {work_id}")

    def append_proposal(self, proposal: RelationProposal) -> RelationProposal:
        if self.get_proposal(proposal.proposal_id) is not None:
            return self.get_proposal(proposal.proposal_id)  # type: ignore[return-value]
        self._append_jsonl(self.proposals_path, proposal.as_dict())
        if proposal.supersedes:
            self._append_jsonl(
                self.decisions_path,
                {
                    "decision_id": stable_relation_id(proposal.supersedes, proposal.proposal_id, prefix="decision"),
                    "proposal_id": proposal.supersedes,
                    "proposal_version": max(1, proposal.version - 1),
                    "decision": "superseded",
                    "decision_source": "re_evaluation",
                    "operator": "system",
                    "rationale": f"Superseded by {proposal.proposal_id}",
                    "accepted_relation": {},
                    "original_relation": {},
                    "validation": {},
                    "promotion_receipt": {},
                    "decided_at": utc_now(),
                },
            )
        self._complete_work(proposal.work_id)
        return proposal

    def append_decision(self, decision: RelationDecision) -> RelationDecision:
        if self.get_proposal(decision.proposal_id) is None:
            raise KeyError(f"unknown relation proposal: {decision.proposal_id}")
        existing = {str(item.get("decision_id")) for item in self._read_jsonl(self.decisions_path)}
        if decision.decision_id not in existing:
            self._append_jsonl(self.decisions_path, decision.as_dict())
        return decision

    def get_proposal(self, proposal_id: str) -> RelationProposal | None:
        for proposal in self.list_proposals():
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def list_proposals(self, *, status: str = "", limit: int = 200) -> list[RelationProposal]:
        decisions: dict[str, str] = {}
        for raw in self._read_jsonl(self.decisions_path):
            decision = str(raw.get("decision") or "")
            if decision:
                decisions[str(raw.get("proposal_id") or "")] = decision
        proposals: list[RelationProposal] = []
        for raw in reversed(self._read_jsonl(self.proposals_path)):
            proposal_id = str(raw.get("proposal_id") or "")
            resolved_status = decisions.get(proposal_id, str(raw.get("status") or "pending"))
            normalized_status = "approved" if resolved_status in {"approved", "revised_approved"} else resolved_status
            payload = {**raw, "status": normalized_status}
            proposal = RelationProposal(**payload)
            if status and proposal.status != status:
                continue
            proposals.append(proposal)
            if len(proposals) >= max(1, min(int(limit), 1000)):
                break
        return proposals

    def list_decisions(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return list(reversed(self._read_jsonl(self.decisions_path)))[: max(1, min(int(limit), 2000))]

    def append_graph_edit_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        decision_id = str(decision.get("decision_id") or "")
        if not decision_id:
            raise ValueError("graph edit decision_id is required")
        existing = {str(item.get("decision_id") or "") for item in self._read_jsonl(self.graph_edit_decisions_path)}
        if decision_id not in existing:
            self._append_jsonl(self.graph_edit_decisions_path, dict(decision))
        return dict(decision)

    def list_graph_edit_decisions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return list(reversed(self._read_jsonl(self.graph_edit_decisions_path)))[: max(1, min(int(limit), 1000))]

    def stats(self) -> dict[str, int]:
        queue = self._read_json(self.queue_path, default=[])
        proposals = self.list_proposals(limit=10000)
        counts = {
            "pending_work": sum(1 for item in queue if str(item.get("status") or "pending") == "pending"),
            "processing_work": sum(1 for item in queue if str(item.get("status") or "") == "processing"),
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "deferred": 0,
            "superseded": 0,
        }
        for proposal in proposals:
            if proposal.status in counts:
                counts[proposal.status] += 1
        return counts

    def save_edit_draft(self, draft: GraphEditDraft) -> GraphEditDraft:
        if not draft.draft_id:
            raise ValueError("graph edit draft_id is required")
        self._write_atomic(self.drafts_root / f"{draft.draft_id}.json", draft.as_dict())
        return draft

    def get_edit_draft(self, draft_id: str) -> GraphEditDraft | None:
        path = self.drafts_root / f"{draft_id}.json"
        if not path.exists():
            return None
        return GraphEditDraft(**self._read_json(path, default={}))

    def _complete_work(self, work_id: str) -> None:
        if not work_id:
            return
        with self._locked_json(self.queue_path) as queue:
            for index, raw in enumerate(queue):
                if str(raw.get("work_id")) != work_id:
                    continue
                item = RelationWorkItem(**raw)
                queue[index] = replace(item, status="completed", updated_at=utc_now()).as_dict()
                return

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    @staticmethod
    def _read_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return payload

    def _write_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    class _LockedJson:
        def __init__(self, store: "RelationStore", path: Path) -> None:
            self.store = store
            self.path = path
            self.lock_path = path.with_suffix(path.suffix + ".lock")
            self.handle = None
            self.payload: list[dict[str, Any]] = []

        def __enter__(self) -> list[dict[str, Any]]:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.lock_path.open("a+")
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
            raw = self.store._read_json(self.path, default=[])
            self.payload = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
            return self.payload

        def __exit__(self, exc_type, exc, traceback) -> None:
            try:
                if exc_type is None:
                    self.store._write_atomic(self.path, self.payload)
            finally:
                if self.handle is not None:
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                    self.handle.close()

    def _locked_json(self, path: Path) -> "RelationStore._LockedJson":
        return self._LockedJson(self, path)
