"""Integration tests for Knowledge memory and self-evolution API contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from knowledge.schemas import (
    AgentPerformanceRecord,
    EvolutionEvidencePack,
    FailurePatternRecord,
    ProvenanceRef,
    SuccessPatternRecord,
)
from knowledge.stores import JsonlKnowledgeStore


def _store(tmp_path: Path, monkeypatch) -> JsonlKnowledgeStore:
    memory_root = tmp_path / "memory" / "knowledge"
    run_root = tmp_path / "runs"
    monkeypatch.setattr(app_main, "KNOWLEDGE_MEMORY_ROOT", memory_root)
    monkeypatch.setattr(app_main, "resolve_path", lambda value: run_root if value == "runs" else Path(value))
    return JsonlKnowledgeStore(memory_root=memory_root, run_root=run_root)


def test_knowledge_memory_apis_filter_and_return_typed_records(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    provenance = ProvenanceRef(
        used=["knowledge_report.json"],
        was_associated_with=["analysis", "knowledge_agent"],
        was_derived_from=["run-knowledge-api"],
    )
    store.append_agent_performance_records(
        [
            AgentPerformanceRecord(
                record_id="perf-analysis-1",
                run_id="run-knowledge-api",
                agent_id="analysis",
                stage="analysis",
                status="warning",
                score=0.62,
                signals={"missing_required_fields": ["bo_observation"], "warnings": ["unit confidence low"]},
                evolution_hint={"needs_evolution": True, "target_type": "prompt", "target_id": "analysis"},
                provenance=provenance,
            ),
            AgentPerformanceRecord(
                record_id="perf-design-1",
                run_id="run-knowledge-api",
                agent_id="design",
                stage="design",
                status="success",
                score=0.94,
                signals={},
                provenance=provenance,
            ),
        ]
    )
    store.append_failure_patterns(
        [
            FailurePatternRecord(
                pattern_id="analysis-unit-confidence-low",
                affected_agents=["analysis", "bo"],
                failure_type="ANALYSIS_UNIT_MAPPING_UNCERTAIN",
                recurrence_count=2,
                first_seen_run_id="run-knowledge-api",
                last_seen_run_id="run-knowledge-api",
                root_cause_hypothesis="UTM export unit evidence is ambiguous.",
                do_not_repeat=["Do not send BO observation when unit confidence is below threshold."],
                recommended_evolution={"target_type": "prompt", "target_id": "analysis"},
                provenance=provenance,
            )
        ]
    )
    store.append_success_patterns(
        [
            SuccessPatternRecord(
                skill_id="equipment-utm-export-v1",
                agent_id="equipment",
                scope="utm_export",
                procedure_summary="Visual-control macro exported a verified UTM CSV.",
                success_metrics={"runs_successful": 3},
                provenance=provenance,
            )
        ]
    )
    store.append_evolution_evidence_packs(
        [
            EvolutionEvidencePack(
                pack_id="evo-pack-analysis-1",
                target_type="prompt",
                target_id="analysis",
                priority=0.91,
                objective="Reduce ambiguous UTM unit handoffs before BO.",
                why_this_target=["analysis has repeated low-confidence unit warnings"],
                supporting_records={"agent_performance_records": ["perf-analysis-1"], "failure_patterns": ["analysis-unit-confidence-low"]},
                recommended_changes=["Emit a blocking operator question when units cannot be verified."],
                constraints={"require_human_approval": True, "no_live_hardware_execution": True},
                eval_metrics={"primary": "bo_handoff_validity_rate"},
                provenance=provenance,
            )
        ]
    )
    store.write_run_artifacts(
        "run-knowledge-api",
        {
            "knowledge_report": {
                "schema": "knowledge_report.v1",
                "summary": "Knowledge API integration fixture",
                "self_evolution": {"evidence_packs": ["evo-pack-analysis-1"]},
            }
        },
    )

    client = TestClient(app)

    perf = client.get("/api/knowledge/agent-performance?agent_id=analysis").json()
    assert perf["ok"] is True
    assert [item["record_id"] for item in perf["records"]] == ["perf-analysis-1"]
    assert perf["records"][0]["signals"]["missing_required_fields"] == ["bo_observation"]

    failures = client.get("/api/knowledge/failure-patterns?agent_id=bo").json()
    assert failures["ok"] is True
    assert failures["records"][0]["failure_type"] == "ANALYSIS_UNIT_MAPPING_UNCERTAIN"

    successes = client.get("/api/knowledge/success-patterns?agent_id=equipment").json()
    assert successes["ok"] is True
    assert successes["records"][0]["skill_id"] == "equipment-utm-export-v1"

    packs = client.get("/api/knowledge/evolution-packs?target_type=prompt&target_id=analysis").json()
    assert packs["ok"] is True
    assert packs["packs"][0]["pack_id"] == "evo-pack-analysis-1"
    assert packs["packs"][0]["constraints"]["require_human_approval"] is True

    run_context = client.get("/api/knowledge/run-context?agent_id=bo&run_id=run-knowledge-api").json()
    assert run_context["ok"] is True
    assert run_context["knowledge_report"]["schema"] == "knowledge_report.v1"

    bo_context = client.get("/api/knowledge/bo-context?objective_id=utm-strength").json()
    assert bo_context["ok"] is True
    assert bo_context["failure_patterns"][0]["pattern_id"] == "analysis-unit-confidence-low"
    assert bo_context["success_patterns"][0]["skill_id"] == "equipment-utm-export-v1"

    safety = client.get("/api/knowledge/safety-context?stage=analysis").json()
    assert safety["ok"] is True
    assert safety["risk_patterns"][0]["failure_type"] == "ANALYSIS_UNIT_MAPPING_UNCERTAIN"


def test_knowledge_evolution_outcome_api_appends_reviewed_attribution(tmp_path: Path, monkeypatch) -> None:
    _store(tmp_path, monkeypatch)
    client = TestClient(app)

    payload = {
        "schema_version": "evolution_outcome_v1",
        "outcome_id": "outcome-analysis-1",
        "variant_id": "variant-analysis-1",
        "target_type": "prompt",
        "target_id": "analysis",
        "parent_version": "prompt-analysis-parent",
        "activated_for_run_id": "run-after",
        "comparison_window": {"before_runs": ["run-before"], "after_runs": ["run-after"]},
        "metrics_delta": {"bo_handoff_validity_rate": 0.2, "warning_count": -1},
        "verdict": "promising_keep_observing",
        "rollback_recommended": False,
        "provenance": {
            "was_generated_by": "self_evolution_service",
            "used": ["evolution_evidence_packs.json"],
            "was_associated_with": ["analysis", "knowledge_agent"],
            "was_derived_from": ["run-before", "run-after"],
            "artifact_fingerprints": {},
        },
    }

    posted = client.post("/api/knowledge/evolution-outcomes", json=payload).json()
    assert posted["ok"] is True
    assert posted["record"]["outcome_id"] == "outcome-analysis-1"

    listed = client.get("/api/knowledge/evolution-outcomes?target_id=analysis").json()
    assert listed["ok"] is True
    assert [item["outcome_id"] for item in listed["records"]] == ["outcome-analysis-1"]


def test_knowledge_agent_report_exposes_memory_and_evolution_boards(monkeypatch) -> None:
    knowledge_payload = {
        "retrieval_coverage": 0.87,
        "local_chunks": 3,
        "web_results": 1,
        "artifact_paths": {"knowledge_report": "/tmp/run/knowledge/knowledge_report.json"},
        "knowledge_context": {
            "schema": "knowledge_context.v1",
            "evidence_quality": {"artifact_link_coverage": 1.0, "evolution_pack_count": 1},
        },
        "evolution_proposal": {
            "schema": "evolution_proposal.v1",
            "status": "ready",
            "evidence_packs": [],
        },
        "knowledge_report": {
            "schema": "knowledge_report.v1",
            "memory_intake": {
                "experiment_record_id": "experiment-memory-1",
                "agent_performance_count": 2,
                "failure_pattern_count": 1,
                "success_pattern_count": 1,
                "evolution_pack_count": 1,
            },
            "agent_performance_records": [
                {"record_id": "perf-analysis-1", "agent_id": "analysis", "score": 0.62}
            ],
            "failure_patterns": [
                {"pattern_id": "analysis-unit-confidence-low", "failure_type": "ANALYSIS_UNIT_MAPPING_UNCERTAIN"}
            ],
            "success_patterns": [
                {"skill_id": "equipment-utm-export-v1", "agent_id": "equipment"}
            ],
            "self_evolution": {
                "schema": "evolution_proposal.v1",
                "status": "ready",
                "evidence_packs": [
                    {
                        "pack_id": "evo-pack-analysis-1",
                        "target_type": "prompt",
                        "target_id": "analysis",
                        "priority": 0.91,
                        "why_this_target": ["analysis has repeated low-confidence unit warnings"],
                    }
                ],
                "prefill_tasks": [
                    {"target_type": "prompt", "target_id": "analysis", "constraints": {"knowledge_evidence_pack_id": "evo-pack-analysis-1"}}
                ],
                "outcomes": [
                    {"outcome_id": "outcome-analysis-1", "variant_id": "variant-analysis-1", "target_type": "prompt", "target_id": "analysis", "verdict": "promising_keep_observing"}
                ],
            },
            "evolution_outcomes": [
                {"outcome_id": "outcome-analysis-1", "variant_id": "variant-analysis-1", "target_type": "prompt", "target_id": "analysis", "verdict": "promising_keep_observing"}
            ],
            "data_quality_map": {"retrieval_sources": {"run_context": []}, "missing_artifacts": []},
            "evidence_quality": {"artifact_link_coverage": 1.0, "agent_report_coverage": 1.0},
        },
    }
    fake_controller = SimpleNamespace(
        snapshot=lambda: {"is_running": False, "state": {"run_id": "run-report", "stage": "knowledge", "run_metadata": {"knowledge": knowledge_payload}}},
        planning_snapshot=lambda: {"state": {"run_id": "run-report", "stage": "knowledge", "run_metadata": {"knowledge": knowledge_payload}}, "messages": []},
        recent_events=lambda: [
            {
                "run_id": "run-report",
                "event_type": "knowledge.memory_written",
                "level": "INFO",
                "message": "Knowledge memory written",
                "payload": {"agent_id": "knowledge", "stage": "knowledge"},
            }
        ],
    )
    monkeypatch.setattr(app_main, "controller", fake_controller)

    report = TestClient(app).get("/api/agents/knowledge/report?run_id=run-report").json()["report"]

    assert report["agent_id"] == "knowledge"
    assert report["role_specific"]["memory_ledger"]["experiment_record_id"] == "experiment-memory-1"
    assert report["role_specific"]["retrieval_panel"]["coverage"] == 0.87
    assert report["role_specific"]["failure_success_library"]["failure_patterns"][0]["pattern_id"] == "analysis-unit-confidence-low"
    assert report["role_specific"]["self_evolution_board"]["top_packs"][0]["pack_id"] == "evo-pack-analysis-1"
    assert report["role_specific"]["self_evolution_board"]["outcomes"][0]["outcome_id"] == "outcome-analysis-1"
    assert report["role_specific"]["handoff_packet"]["knowledge_context"]["schema"] == "knowledge_context.v1"
    assert report["decisions"][0]["decision"] == "prepare_self_evolution_evidence_pack"
    assert report["metrics"]["agent_report_coverage"] == 1.0



def test_knowledge_graph_api_imports_and_queries_json_backend(tmp_path: Path, monkeypatch) -> None:
    memory_root = tmp_path / "memory" / "knowledge"
    run_root = tmp_path / "runs"
    monkeypatch.setattr(app_main, "KNOWLEDGE_MEMORY_ROOT", memory_root)

    def _resolve(value: str) -> Path:
        if value == "runs":
            return run_root
        if value == ".":
            return tmp_path
        return Path(value)

    monkeypatch.setattr(app_main, "resolve_path", _resolve)
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_BACKEND", "json")

    store = JsonlKnowledgeStore(memory_root=memory_root, run_root=run_root)
    provenance = ProvenanceRef(
        used=["knowledge_report.json"],
        was_associated_with=["analysis", "knowledge_agent"],
        was_derived_from=["run-graph-api"],
    )
    store.append_agent_performance_records(
        [
            AgentPerformanceRecord(
                record_id="perf-analysis-graph-api",
                run_id="run-graph-api",
                agent_id="analysis",
                stage="analysis",
                status="warning",
                score=0.6,
                signals={"warnings": ["unit confidence low"]},
                evolution_hint={"needs_evolution": True, "target_type": "prompt", "target_id": "analysis"},
                provenance=provenance,
            )
        ]
    )
    store.append_failure_patterns(
        [
            FailurePatternRecord(
                pattern_id="failure-analysis-graph-api",
                affected_agents=["analysis", "bo"],
                failure_type="ANALYSIS_UNIT_MAPPING_UNCERTAIN",
                recurrence_count=2,
                recommended_evolution={"target_type": "prompt", "target_id": "analysis"},
                provenance=provenance,
            )
        ]
    )
    store.append_evolution_evidence_packs(
        [
            EvolutionEvidencePack(
                pack_id="evo-pack-analysis-graph-api",
                target_type="prompt",
                target_id="analysis",
                priority=0.88,
                objective="Improve analysis unit confidence handling.",
                why_this_target=["analysis warning repeated"],
                recommended_changes=["Block BO handoff until units are verified."],
                provenance=provenance,
            )
        ]
    )

    client = TestClient(app)
    before = client.get("/api/knowledge/graph/health").json()
    assert before["ok"] is True
    assert before["backend"] == "json"

    imported = client.post("/api/knowledge/graph/import", json={"limit": 20}).json()
    assert imported["ok"] is True
    assert imported["backend"] == "json"
    assert imported["records"] == 3
    assert imported["nodes_written"] > 0

    queried = client.get("/api/knowledge/graph/query?kind=target_context&target_type=prompt&target_id=analysis&limit=20").json()
    assert queried["ok"] is True
    assert any(node["id"] == "evolution_pack:evo-pack-analysis-graph-api" for node in queried["nodes"])
    assert any(edge["type"] in {"AFFECTS", "RECOMMENDS", "ASSOCIATED_WITH"} for edge in queried["edges"])
