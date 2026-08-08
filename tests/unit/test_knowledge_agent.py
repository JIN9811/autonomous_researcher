"""Unit tests for KnowledgeAgent memory payload persistence."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agents.knowledge_agent import KnowledgeAgent
from knowledge.evolution_bridge import build_outcomes_for_active_variants
from knowledge.experiment_db import ExperimentDB
from knowledge.schemas import AgentPerformanceRecord, EvolutionOutcomeRecord
from orchestrator.state import Mode, OrchestratorState, Stage


class _RagStub:
    async def retrieve(self, *, query: str, top_k_local: int = 4) -> dict[str, Any]:
        return {"coverage": 1.0, "local_chunks": [], "web_results": []}


class _CtxStub:
    def __init__(self) -> None:
        self.rag = _RagStub()
        self.experiment_db = ExperimentDB()

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> Any:
        return SimpleNamespace(text="analysis memory summary")


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-knowledge",
        experiment_id="exp-knowledge",
        mode=Mode.TEST,
        stage=Stage.KNOWLEDGE,
        active_goal="persist UTM analysis memory",
        latest_analysis={
            "objective_score": 0.73,
            "uncertainty": 0.12,
            "knowledge_payload": {
                "schema": "analysis_knowledge_payload.v1",
                "raw_artifact_refs": [{"kind": "utm_csv", "path": "artifacts/equipment/run/utm.csv"}],
                "metrics": {"peak_force_N": 240.0, "compressive_strength_MPa": 0.6},
                "failure_tags": ["low_point_count"],
            },
        },
    )


@pytest.mark.asyncio
async def test_knowledge_agent_persists_analysis_artifacts_metrics_and_failure_tags() -> None:
    ctx = _CtxStub()

    result = await KnowledgeAgent().run(_state(), ctx)

    assert result.success is True
    assert result.data["knowledge"]["artifact_ref_count"] == 1
    assert result.data["knowledge"]["metric_count"] == 2
    assert result.data["knowledge"]["failure_tags"] == ["low_point_count"]
    assert result.data["knowledge"]["knowledge_context"]["schema"] == "knowledge_context.v1"
    assert result.data["knowledge"]["knowledge_report"]["schema"] == "knowledge_report.v1"
    assert result.data["knowledge"]["evolution_proposal"]["schema"] == "evolution_proposal.v1"
    assert result.data["knowledge"]["agent_performance_count"] >= 1
    assert result.data["knowledge"]["failure_pattern_count"] >= 1
    assert result.data["knowledge"]["evolution_pack_count"] >= 1
    pack = result.data["knowledge"]["self_evolution"]["evidence_packs"][0]
    assert pack["schema_version"] == "evolution_evidence_pack_v1"
    assert pack["target_type"] == "prompt"
    assert pack["constraints"]["require_human_approval"] is True
    assert "knowledge_report" in result.data["knowledge"]["artifact_paths"]
    record = ctx.experiment_db.list_recent(1)[0]
    assert record.artifact_refs[0]["kind"] == "utm_csv"
    assert record.metrics["peak_force_N"] == 240.0
    assert record.failure_tags == ["low_point_count"]


def test_knowledge_builds_outcome_attribution_for_active_variant(tmp_path) -> None:
    evolution_root = tmp_path / "memory" / "evolution"
    (evolution_root / "variants").mkdir(parents=True)
    variant_id = "evo-var-analysis-test"
    (evolution_root / "active_variants.json").write_text(
        json.dumps({"prompt:analysis": {"variant_id": variant_id, "activated_at": "2026-05-30T00:00:00+00:00"}}),
        encoding="utf-8",
    )
    (evolution_root / "variants" / f"{variant_id}.json").write_text(
        json.dumps(
            {
                "variant_id": variant_id,
                "target_type": "prompt",
                "target_id": "analysis",
                "parent_version": "prompt-analysis-parent",
                "source_trace_ids": ["trace-run-before"],
                "metrics": {"trace_metrics": {"warning_count": 2, "error_count": 1}},
            }
        ),
        encoding="utf-8",
    )
    perf = AgentPerformanceRecord(
        record_id="perf-analysis-after",
        run_id="run-after",
        agent_id="analysis",
        stage="analysis",
        status="success",
        score=0.91,
        signals={"warnings": [], "missing_required_fields": [], "artifact_completeness": 1.0, "contract_validity": 1.0},
    )

    outcomes = build_outcomes_for_active_variants(
        run_id="run-after",
        performance_records=[perf],
        evolution_root=evolution_root,
        existing_outcomes=[],
        evidence_refs=[{"kind": "analysis_report", "path": "runs/run-after/analysis/report.json"}],
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert isinstance(outcome, EvolutionOutcomeRecord)
    assert outcome.variant_id == variant_id
    assert outcome.target_type == "prompt"
    assert outcome.target_id == "analysis"
    assert outcome.activated_for_run_id == "run-after"
    assert outcome.comparison_window["before_runs"] == ["run-before"]
    assert outcome.metrics_delta["warning_count_delta"] == -2
    assert outcome.metrics_delta["error_count_delta"] == -1
    assert outcome.metrics_delta["agent_score_after"] == 0.91
    assert outcome.verdict == "promising_keep_observing"
    assert outcome.rollback_recommended is False

    duplicate = build_outcomes_for_active_variants(
        run_id="run-after",
        performance_records=[perf],
        evolution_root=evolution_root,
        existing_outcomes=outcomes,
        evidence_refs=[],
    )
    assert duplicate == []


@pytest.mark.asyncio
async def test_knowledge_agent_ingests_guardian_incidents_as_evolution_evidence() -> None:
    ctx = _CtxStub()
    state = _state()
    state.run_metadata["incident_records"] = [
        {
            "schema": "incident_record.v1",
            "incident_id": "inc-utm-no-motion",
            "stage": "equipment",
            "severity": "critical",
            "risk_class": "utm",
            "component": "utm_motion",
            "reason_code": "UTM_NO_MOTION",
            "failure_code": "UTM_NO_MOTION_AFTER_START",
            "message": "UTM did not move after start command.",
        }
    ]
    state.run_metadata["guardian_gates"] = [
        {
            "schema": "guardian_gate_result.v1",
            "gate_id": "guardian-gate-utm",
            "stage": "equipment",
            "phase": "post",
            "decision": "safe_stop",
            "reason_code": "UTM_NO_MOTION",
            "risk_score": 0.93,
        }
    ]
    state.run_metadata["tool_call_records"] = [
        {
            "schema": "tool_call_record.v1",
            "tool": "utm.run_protocol",
            "status": "failed",
            "failure_code": "UTM_NO_MOTION_AFTER_START",
            "guardian_reason_code": "UTM_NO_MOTION",
        }
    ]

    result = await KnowledgeAgent().run(state, ctx)

    knowledge = result.data["knowledge"]
    evidence = knowledge["guardian_incident_evidence"]
    assert evidence["schema"] == "guardian_incident_evidence.v1"
    assert evidence["incident_count"] == 1
    assert evidence["gate_count"] == 1
    assert "inc-utm-no-motion" in evidence["incident_ids"]
    assert "UTM_NO_MOTION" in knowledge["failure_tags"]
    assert "UTM_NO_MOTION_AFTER_START" in knowledge["failure_tags"]
    assert knowledge["knowledge_report"]["guardian_incident_evidence"]["incident_count"] == 1
    assert knowledge["knowledge_context"]["evidence_quality"]["guardian_incident_count"] == 1


@pytest.mark.asyncio
async def test_knowledge_agent_adds_durable_graph_event_status_when_enabled(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _Service:
        @classmethod
        def from_env(cls, project_root):
            captured["project_root"] = project_root
            return cls()

        def ingest(self, payload):
            captured["payload"] = payload
            return {
                "ok": True,
                "status": "synchronized",
                "event_id": "event:test",
                "outbox": {"pending": 0, "acknowledged": 1, "dead_letter": 0},
                "sync": {"acknowledged": 1, "safety_lag": 0},
            }

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr("agents.knowledge_agent.event_pipeline_enabled", lambda: True)
    monkeypatch.setattr("agents.knowledge_agent.KnowledgeService", _Service)

    result = await KnowledgeAgent().run(_state(), _CtxStub())

    graph_status = result.data["knowledge"]["graph_event_status"]
    assert graph_status["status"] == "synchronized"
    assert result.data["knowledge"]["knowledge_report"]["graph_event_status"] == graph_status
    assert captured["payload"]["event_type"] == "specimen.analyzed"
    assert captured["payload"]["run_id"] == "run-knowledge"
    assert captured["closed"] is True
