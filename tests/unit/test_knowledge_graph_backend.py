"""Tests for optional Knowledge graph backend and importer."""

from __future__ import annotations

from knowledge.graph_backend import JsonGraphBackend, NullGraphBackend
from knowledge.graph_importer import import_store_to_graph, mirror_knowledge_records, records_to_graph
from knowledge.schemas import AgentPerformanceRecord, EvolutionEvidencePack, ExperimentKnowledgeRecord, FailurePatternRecord, ProvenanceRef, SuccessPatternRecord
from knowledge.stores import JsonlKnowledgeStore


def _records() -> tuple[ExperimentKnowledgeRecord, list[AgentPerformanceRecord], list[FailurePatternRecord], list[SuccessPatternRecord], list[EvolutionEvidencePack]]:
    provenance = ProvenanceRef(
        used=["knowledge_report.json"],
        was_associated_with=["analysis", "knowledge_agent"],
        was_derived_from=["run-graph-1"],
    )
    experiment = ExperimentKnowledgeRecord(
        record_id="exp-graph-1",
        run_id="run-graph-1",
        experiment_id="exp-graph",
        candidate_id="specimen-1",
        summary="Graph backend fixture",
        parameters={"geometry_type": "gyroid"},
        metrics={"objective_score": 0.7},
        artifact_refs={"analysis_artifacts": [{"kind": "analysis_report", "path": "runs/run-graph-1/analysis/report.json"}]},
        provenance=provenance,
    )
    performance = [
        AgentPerformanceRecord(
            record_id="perf-analysis-graph",
            run_id="run-graph-1",
            agent_id="analysis",
            stage="analysis",
            status="warning",
            score=0.6,
            signals={"warnings": ["unit low confidence"]},
            evolution_hint={"needs_evolution": True, "target_type": "prompt", "target_id": "analysis"},
            provenance=provenance,
        )
    ]
    failures = [
        FailurePatternRecord(
            pattern_id="failure-analysis-unit",
            affected_agents=["analysis", "bo"],
            failure_type="ANALYSIS_UNIT_MAPPING_UNCERTAIN",
            recommended_evolution={"target_type": "prompt", "target_id": "analysis"},
            provenance=provenance,
        )
    ]
    successes = [
        SuccessPatternRecord(
            skill_id="success-equipment-export",
            agent_id="equipment",
            scope="utm_export",
            procedure_summary="Exported UTM CSV with visual check.",
            provenance=provenance,
        )
    ]
    packs = [
        EvolutionEvidencePack(
            pack_id="evo-pack-analysis-graph",
            target_type="prompt",
            target_id="analysis",
            priority=0.9,
            objective="Improve analysis unit mapping handoff.",
            why_this_target=["analysis warnings repeated"],
            recommended_changes=["Ask operator when units are ambiguous."],
            provenance=provenance,
        )
    ]
    return experiment, performance, failures, successes, packs


def test_records_to_graph_preserves_runtime_relationships() -> None:
    experiment, performance, failures, successes, packs = _records()
    nodes, edges = records_to_graph([experiment, *performance, *failures, *successes, *packs])

    node_ids = {node["id"] for node in nodes}
    edge_types = {edge["type"] for edge in edges}

    assert "experiment:exp-graph-1" in node_ids
    assert "performance:perf-analysis-graph" in node_ids
    assert "failure:failure-analysis-unit" in node_ids
    assert "evolution_pack:evo-pack-analysis-graph" in node_ids
    assert "agent:analysis" in node_ids
    assert "run:run-graph-1" in node_ids
    assert "OBSERVED_IN" in edge_types
    assert "AFFECTS" in edge_types
    assert "RECOMMENDS" in edge_types
    assert "USED" in edge_types


def test_json_graph_backend_upserts_and_queries_target_context(tmp_path) -> None:
    experiment, performance, failures, successes, packs = _records()
    backend = JsonGraphBackend(tmp_path / "knowledge_graph.json")

    status = mirror_knowledge_records(
        backend,
        experiment_record=experiment,
        performance_records=performance,
        failure_patterns=failures,
        success_patterns=successes,
        evidence_packs=packs,
    )

    assert status["ok"] is True
    assert status["backend"] == "json"
    assert status["nodes_written"] > 0
    assert status["edges_written"] > 0
    health = backend.health()
    assert health["node_count"] > 0
    result = backend.query({"kind": "target_context", "target_type": "prompt", "target_id": "analysis", "limit": 20})
    assert result["ok"] is True
    assert any(node["id"] == "evolution_pack:evo-pack-analysis-graph" for node in result["nodes"])
    assert any(edge["type"] in {"RECOMMENDS", "AFFECTS", "ASSOCIATED_WITH"} for edge in result["edges"])


def test_import_store_to_graph_uses_jsonl_memory(tmp_path) -> None:
    experiment, performance, failures, successes, packs = _records()
    store = JsonlKnowledgeStore(memory_root=tmp_path / "memory" / "knowledge", run_root=tmp_path / "runs")
    store.append_experiment_record(experiment)
    store.append_agent_performance_records(performance)
    store.append_failure_patterns(failures)
    store.append_success_patterns(successes)
    store.append_evolution_evidence_packs(packs)
    backend = JsonGraphBackend(tmp_path / "graph" / "knowledge_graph.json")

    result = import_store_to_graph(store, backend, limit=50)

    assert result["ok"] is True
    assert result["records"] == 5
    assert backend.health()["node_count"] > 0


def test_null_graph_backend_is_fail_open() -> None:
    backend = NullGraphBackend()
    experiment, performance, failures, successes, packs = _records()

    result = mirror_knowledge_records(
        backend,
        experiment_record=experiment,
        performance_records=performance,
        failure_patterns=failures,
        success_patterns=successes,
        evidence_packs=packs,
    )

    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["nodes_written"] == 0
