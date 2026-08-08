from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator
from knowledge.reconciliation_service import KnowledgeReconciliationService, KnowledgeReconciliationWorker
from knowledge.relation_store import RelationStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _GraphBackend:
    def __init__(self) -> None:
        self.nodes = [
            {
                "id": "specimen:1",
                "kind": "Specimen",
                "run_id": "run-1",
                "created_at": "2026-08-09T00:00:00+00:00",
                "properties": {"provenance_refs": ["specimen.stl", "frame.png"]},
            },
            {
                "id": "observation:1",
                "kind": "Observation",
                "run_id": "run-1",
                "created_at": "2026-08-09T00:00:01+00:00",
                "properties": {"provenance_refs": ["specimen.stl", "frame.png"]},
            },
            {
                "id": "observation:2",
                "kind": "Observation",
                "run_id": "run-2",
                "properties": {"provenance_refs": ["other.png"]},
            },
        ]
        self.edges: list[dict] = [
            {"id": "observation-lineage", "source": "observation:1", "target": "observation:2", "type": "DERIVED_FROM"}
        ]

    def query(self, query: dict) -> dict:
        kind = query["kind"]
        if kind == "reconciliation_gaps":
            return {"ok": True, "kind": kind, "nodes": self.nodes, "edges": self.edges, "graph_revision": "rev-1"}
        if kind == "reconciliation_context":
            return {"ok": True, "kind": kind, "nodes": self.nodes, "edges": self.edges, "graph_revision": "rev-1"}
        if kind == "node_lookup":
            ids = set(query.get("node_ids", []))
            return {"ok": True, "kind": kind, "nodes": [node for node in self.nodes if node["id"] in ids], "edges": []}
        raise AssertionError(kind)


class _KnowledgeService:
    def __init__(self) -> None:
        self.registry = OntologyRegistry.load_default(PROJECT_ROOT)
        self.validator = OntologyValidator(self.registry)
        self.repository = SimpleNamespace(backend=_GraphBackend())
        self.ingest_calls: list[dict] = []

    def ingest(self, payload: dict) -> dict:
        self.ingest_calls.append(payload)
        return {"ok": True, "status": "synchronized", "event_id": f"event:{len(self.ingest_calls)}"}


class _AgentContext:
    def __init__(self, response: dict, *, loaded: bool = True) -> None:
        self.response = response
        self.loaded = loaded
        self.complete_calls: list[dict] = []

    async def selected_model_loaded(self, task_type: str) -> bool:
        assert task_type == "knowledge_relation"
        return self.loaded

    async def complete(self, task_type: str, prompt: str, **kwargs):
        self.complete_calls.append({"task_type": task_type, "prompt": prompt, **kwargs})
        return SimpleNamespace(text=json.dumps(self.response), model="gemma4:e4b-it-nvfp4", raw={})


def _response(*, confidence: float, target: str = "observation:1") -> dict:
    return {
        "source_id": "specimen:1",
        "target_id": target,
        "relation_type": "OBSERVED_BY",
        "confidence": confidence,
        "rationale": "The observation shares run-scoped specimen evidence.",
    }


def _service(tmp_path: Path, response: dict, *, loaded: bool = True):
    knowledge = _KnowledgeService()
    context = _AgentContext(response, loaded=loaded)
    service = KnowledgeReconciliationService(
        project_root=PROJECT_ROOT,
        knowledge_service=knowledge,
        agent_context=context,
        store=RelationStore(tmp_path / "reconciliation"),
    )
    return service, knowledge, context


@pytest.mark.asyncio
async def test_medium_confidence_proposal_waits_for_operator(tmp_path) -> None:
    service, knowledge, _ = _service(tmp_path, _response(confidence=0.82))

    result = await service.reconcile_batch(limit=1)

    assert result["proposals"][0]["status"] == "pending"
    assert knowledge.ingest_calls == []


@pytest.mark.asyncio
async def test_high_confidence_proposal_uses_knowledge_ingest(tmp_path) -> None:
    service, knowledge, _ = _service(tmp_path, _response(confidence=0.95))

    result = await service.reconcile_batch(limit=1)

    assert result["proposals"][0]["status"] == "approved"
    assert knowledge.ingest_calls[0]["relationship_intents"][0]["relation_type"] == "OBSERVED_BY"
    assert knowledge.ingest_calls[0]["relationship_intents"][0]["properties"]["decision_status"] == "approved"


@pytest.mark.asyncio
async def test_revision_approval_preserves_original_and_uses_existing_target(tmp_path) -> None:
    service, knowledge, _ = _service(tmp_path, _response(confidence=0.82))
    proposal = (await service.reconcile_batch(limit=1))["proposals"][0]

    decision = service.revise_and_approve(
        proposal["proposal_id"],
        target_id="observation:2",
        relation_type="OBSERVED_BY",
        rationale="Operator selected the second existing observation.",
        operator="jin",
    )

    assert decision["decision"] == "revised_approved"
    assert decision["original_relation"]["target_id"] == "observation:1"
    assert decision["accepted_relation"]["target_id"] == "observation:2"
    assert knowledge.ingest_calls[-1]["relationship_intents"][0]["target_id"] == "observation:2"


@pytest.mark.asyncio
async def test_worker_skips_without_loading_an_unloaded_model(tmp_path) -> None:
    service, knowledge, context = _service(tmp_path, _response(confidence=0.95), loaded=False)
    worker = KnowledgeReconciliationWorker(service)

    result = await worker.run_once()

    assert result["status"] == "model_unloaded"
    assert context.complete_calls == []
    assert knowledge.ingest_calls == []


@pytest.mark.asyncio
async def test_re_evaluation_creates_new_version_without_overwriting_original(tmp_path) -> None:
    service, _, _ = _service(tmp_path, _response(confidence=0.82))
    original = (await service.reconcile_batch(limit=1))["proposals"][0]

    service.re_evaluate(original["proposal_id"])
    replacement = (await service.reconcile_batch(limit=1))["proposals"][0]

    assert replacement["proposal_id"] != original["proposal_id"]
    assert replacement["version"] == 2
    assert replacement["supersedes"] == original["proposal_id"]
    assert service.store.get_proposal(original["proposal_id"]).status == "superseded"
