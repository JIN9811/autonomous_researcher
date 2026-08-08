from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import app.main as app_main
from app.main import app
from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator
from knowledge.reconciliation_service import KnowledgeReconciliationService
from knowledge.relation_reconciliation import RelationProposal
from knowledge.relation_store import RelationStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Backend:
    def __init__(self) -> None:
        self.revision = "rev-1"
        self.nodes = [
            {"id": "specimen:1", "kind": "Specimen", "run_id": "run-1", "properties": {"provenance_refs": ["specimen.stl"]}},
            {"id": "observation:1", "kind": "Observation", "run_id": "run-1", "properties": {"provenance_refs": ["frame.png"]}},
            {"id": "observation:2", "kind": "Observation", "run_id": "run-1", "properties": {"provenance_refs": ["frame-2.png"]}},
        ]
        self.edges: list[dict] = []

    def query(self, query: dict) -> dict:
        kind = query["kind"]
        if kind in {"reconciliation_gaps", "reconciliation_context"}:
            return {"ok": True, "kind": kind, "nodes": self.nodes, "edges": self.edges, "graph_revision": self.revision}
        if kind == "node_lookup":
            requested = set(query.get("node_ids", []))
            return {"ok": True, "kind": kind, "nodes": [node for node in self.nodes if node["id"] in requested], "edges": []}
        raise AssertionError(kind)


class _Knowledge:
    def __init__(self) -> None:
        self.registry = OntologyRegistry.load_default(PROJECT_ROOT)
        self.validator = OntologyValidator(self.registry)
        self.repository = SimpleNamespace(backend=_Backend())
        self.ingest_calls: list[dict] = []

    def ingest(self, payload: dict) -> dict:
        self.ingest_calls.append(payload)
        return {"ok": True, "status": "synchronized", "event_id": f"event:{len(self.ingest_calls)}"}

    def close(self) -> None:
        return None


class _Context:
    async def selected_model_loaded(self, task_type: str) -> bool:
        return False


class _Worker:
    def __init__(self, service: KnowledgeReconciliationService) -> None:
        self.service = service

    def start(self):
        return self.status()

    def wake(self):
        return self.status()

    def status(self):
        return {"status": "idle", "running": False, "started": True, "store": self.service.store.stats()}

    async def shutdown(self):
        return None


@pytest.fixture
def relation_api(tmp_path: Path, monkeypatch):
    knowledge = _Knowledge()
    service = KnowledgeReconciliationService(
        project_root=PROJECT_ROOT,
        knowledge_service=knowledge,
        agent_context=_Context(),
        store=RelationStore(tmp_path / "reconciliation"),
    )
    proposal = RelationProposal(
        proposal_id="proposal:1",
        version=1,
        work_id="work:1",
        source_id="specimen:1",
        source_class="Specimen",
        target_id="observation:1",
        target_class="Observation",
        relation_type="OBSERVED_BY",
        confidence=0.82,
        evidence_score=0.85,
        rationale="Shared run evidence.",
        provenance_refs=("specimen.stl", "frame.png"),
        model_snapshot={"model": "gemma4:e4b-it-nvfp4"},
        ontology_version=knowledge.registry.version_id,
        graph_revision="rev-1",
        graph_context_hash="context-1",
    )
    service.store.append_proposal(proposal)
    worker = _Worker(service)
    monkeypatch.setattr(app_main, "_KNOWLEDGE_RECONCILIATION_SERVICE", service)
    monkeypatch.setattr(app_main, "_KNOWLEDGE_RECONCILIATION_WORKER", worker)
    monkeypatch.setattr(app_main, "_KNOWLEDGE_RECONCILIATION_KNOWLEDGE_SERVICE", knowledge)
    monkeypatch.setattr(app_main, "_knowledge_reconciliation_worker", lambda: worker)
    with TestClient(app) as client:
        yield client, service, knowledge


def test_relation_status_and_pending_proposal_listing(relation_api) -> None:
    client, _, _ = relation_api

    status = client.get("/api/knowledge/relations/status").json()
    proposals = client.get("/api/knowledge/relations/proposals?status=pending").json()

    assert status["ok"] is True
    assert status["graph_revision"] == "rev-1"
    assert status["relations"]["pending"] == 1
    assert proposals["proposals"][0]["proposal_id"] == "proposal:1"


def test_revised_approval_rejects_new_target_node(relation_api) -> None:
    client, _, _ = relation_api

    response = client.post(
        "/api/knowledge/relations/proposal:1/revise-approve",
        json={
            "proposal_version": 1,
            "graph_context_hash": "context-1",
            "target_id": "invented:node",
            "relation_type": "OBSERVED_BY",
            "rationale": "manual correction",
            "operator": "jin",
        },
    )

    assert response.status_code == 409


def test_approval_requires_current_proposal_version(relation_api) -> None:
    client, _, _ = relation_api

    response = client.post(
        "/api/knowledge/relations/proposal:1/approve",
        json={"proposal_version": 9, "graph_context_hash": "context-1", "operator": "jin", "rationale": "approve"},
    )

    assert response.status_code == 409


def test_graph_edit_apply_requires_matching_revision(relation_api) -> None:
    client, _, _ = relation_api

    response = client.post(
        "/api/knowledge/graph/edit/apply",
        json={"graph_revision": "stale", "operator": "jin", "changes": []},
    )

    assert response.status_code == 409


def test_graph_edit_validates_and_applies_existing_nodes_only(relation_api) -> None:
    client, service, knowledge = relation_api
    payload = {
        "graph_revision": "rev-1",
        "operator": "jin",
        "changes": [
            {"operation": "update_node_metadata", "node_id": "specimen:1", "metadata": {"note": "reviewed", "tags": ["validated"]}},
            {"operation": "add_relation", "source_id": "specimen:1", "target_id": "observation:2", "relation_type": "OBSERVED_BY"},
        ],
    }

    validated = client.post("/api/knowledge/graph/edit/validate", json=payload)
    applied = client.post("/api/knowledge/graph/edit/apply", json=payload)

    assert validated.status_code == 200
    assert validated.json()["validation"]["ok"] is True
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert knowledge.ingest_calls[-1]["relationship_intents"][0]["target_id"] == "observation:2"
    assert knowledge.ingest_calls[-1]["entity_refs"][0]["note"] == "reviewed"
    assert service.store.list_graph_edit_decisions()[0]["status"] == "applied"
