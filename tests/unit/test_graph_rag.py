from __future__ import annotations

from typing import Any

from knowledge.graph_query_planner import validate_query_plan
from knowledge.graph_rag import GraphRAG
from knowledge.graph_retrieval import GraphRetrievalService


class RecordingBackend:
    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        self.queries.append(query)
        return {
            "ok": True,
            "backend": "test",
            "nodes": [{"id": "runtime:run:run-1", "kind": "Run"}],
            "edges": [],
        }


def test_retrieval_maps_run_context_to_existing_bounded_backend_query() -> None:
    backend = RecordingBackend()
    service = GraphRetrievalService(backend)  # type: ignore[arg-type]
    plan = validate_query_plan({"kind": "run_context", "filters": {"run_id": "run-1"}, "limit": 20})

    result = service.query(plan)

    assert result["ok"]
    assert backend.queries == [
        {
            "kind": "target_context",
            "target_type": "Run",
            "target_id": "run-1",
            "limit": 20,
            "include_properties": True,
        }
    ]


def test_graph_rag_preserves_source_boundaries_and_sync_metadata() -> None:
    graph_result = {
        "ok": True,
        "backend": "neo4j",
        "nodes": [{"id": "runtime:specimen:s-1", "kind": "Specimen"}],
        "edges": [],
    }
    context = GraphRAG.build_context(
        plan=validate_query_plan({"kind": "similar_experiments", "filters": {"q": "gyroid"}}),
        graph_result=graph_result,
        typed_memory=[{"record_id": "memory-1"}],
        vector_context={"coverage": 0.75, "chunks": ["local-1"]},
        orchestrator_state={"run_id": "run-1", "stage": "knowledge"},
        sync_status={"pending": 2, "dead_letter": 0, "safety_lag": 1},
    )

    assert context["schema"] == "graph_rag_context.v1"
    assert context["query_plan"]["kind"] == "similar_experiments"
    assert context["sources"]["graph"]["backend"] == "neo4j"
    assert context["sources"]["typed_memory"][0]["record_id"] == "memory-1"
    assert context["sources"]["current_state"]["run_id"] == "run-1"
    assert context["sync_status"]["safety_lag"] == 1
