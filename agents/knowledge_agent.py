"""
File purpose:
- Retrieve guide/web knowledge, write validated experiment memory, and build self-evolution evidence packs.

Key classes/functions:
- KnowledgeAgent

Inputs/outputs:
- Input: active goal, analysis result, current experiment metadata
- Output: knowledge_context.v1, knowledge_report, typed memory artifacts, evolution_evidence_packs

Dependencies:
- knowledge.rag.HybridRAG
- knowledge.retrieval.format_rag_context
- knowledge.schemas
- knowledge.stores.JsonlKnowledgeStore

Modification guide:
- Safe places to edit: memory extraction, evidence-pack ranking, report field additions
- Risky places to edit: MemoryRecord compatibility and AgentResult.data["knowledge"] keys used by GUI/controller
- Related files: knowledge/*, self_evolution/service.py, app/main.py
"""

from __future__ import annotations

from pathlib import Path
import inspect
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from utils.agent_artifact_archive import archive_agent_run
from knowledge.evolution_bridge import build_evidence_packs, build_outcomes_for_active_variants, map_pack_to_evolution_task
from knowledge.graph_backend import graph_backend_from_env
from knowledge.graph_importer import mirror_knowledge_records
from knowledge.pattern_miner import build_agent_performance_records, rank_evolution_targets, update_failure_patterns, update_success_patterns
from knowledge.provenance import build_provenance_ref, stable_id, validate_artifact_refs
from knowledge.retrieval import format_rag_context, retrieve_research_context
from knowledge.schemas import ExperimentKnowledgeRecord, KnowledgeSourceRef, MemoryRecord
from knowledge.service import KnowledgeService, event_pipeline_enabled
from knowledge.stores import JsonlKnowledgeStore
from orchestrator.state import OrchestratorState


class KnowledgeAgent(BaseAgent):
    """Handles retrieval, memory persistence, and self-evolution evidence preparation."""

    name = "knowledge_agent"

    @archive_agent_run
    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        query = (
            f"{state.active_goal}. "
            f"Current stage={state.stage.value}. "
            "What constraints, memory, failures, and architecture rules should this loop enforce?"
        )
        retrieval = await ctx.rag.retrieve(query=query, top_k_local=4)
        rag_context = format_rag_context(retrieval)

        timeout_s = 45.0 if state.mode.value == "test" else None
        if state.mode.value == "test" and not getattr(ctx, "force_real_llm_in_test", True):
            memory_summary = _deterministic_memory_summary(state, retrieval)
        else:
            try:
                response = await ctx.complete(
                    "knowledge_query",
                    "Use the context to produce concise constraints, memory implications, failure reminders, and next-step reminders.\n" + rag_context,
                    timeout_s=timeout_s,
                )
                memory_summary = response.text[:500]
            except Exception as exc:
                if state.mode.value == "test":
                    memory_summary = f"Knowledge degraded in test mode: {exc.__class__.__name__}"
                else:
                    raise

        objective = float(state.latest_analysis.get("objective_score", 0.0))
        uncertainty = float(state.latest_analysis.get("uncertainty", 1.0))
        knowledge_payload = state.latest_analysis.get("knowledge_payload") if isinstance(state.latest_analysis.get("knowledge_payload"), dict) else {}
        artifact_refs = _list_of_dicts(knowledge_payload.get("raw_artifact_refs")) or _list_of_dicts(state.latest_analysis.get("artifact_refs"))
        metrics = knowledge_payload.get("metrics") if isinstance(knowledge_payload.get("metrics"), dict) else state.latest_analysis.get("utm_metrics", {})
        metrics = dict(metrics) if isinstance(metrics, dict) else {}
        failure_tags = knowledge_payload.get("failure_tags") if isinstance(knowledge_payload.get("failure_tags"), list) else state.latest_analysis.get("failure_tags", [])
        failure_tags = [str(item) for item in failure_tags if item]
        guardian_incident_evidence = _guardian_incident_evidence_from_state(state)
        guardian_failure_tags = [str(item) for item in guardian_incident_evidence.get("failure_tags", []) if item]
        failure_tags = sorted(dict.fromkeys([*failure_tags, *guardian_failure_tags]))
        objective_evaluation = (
            dict(state.latest_analysis.get("objective_evaluation"))
            if isinstance(state.latest_analysis.get("objective_evaluation"), dict)
            else dict(knowledge_payload.get("objective_evaluation"))
            if isinstance(knowledge_payload.get("objective_evaluation"), dict)
            else {}
        )

        memory_record = MemoryRecord(
            run_id=state.run_id,
            experiment_id=state.experiment_id,
            summary=memory_summary,
            score=objective,
            uncertainty=uncertainty,
            artifact_refs=artifact_refs,
            metrics=metrics,
            failure_tags=failure_tags,
            objective_evaluation=objective_evaluation,
        )
        ctx.experiment_db.add(memory_record)

        project_root = Path(__file__).resolve().parent.parent
        store = JsonlKnowledgeStore.default(project_root)
        now = self.now_iso()
        candidate_id = _candidate_id_from_state(state)
        parameters = _parameters_from_state(state)
        artifact_quality = validate_artifact_refs(artifact_refs, project_root=project_root)
        provenance = build_provenance_ref(
            run_id=state.run_id,
            used=["latest_analysis", "run_metadata", "rag_context"],
            associated_with=["analysis_agent", "knowledge_agent"],
            derived_from=[state.run_id],
            artifact_refs=artifact_refs,
            project_root=project_root,
        )
        source_refs = _source_refs_from_retrieval(retrieval)
        experiment_record = ExperimentKnowledgeRecord(
            record_id=stable_id("experiment-knowledge", state.run_id, state.experiment_id, candidate_id, objective, uncertainty),
            run_id=state.run_id,
            experiment_id=state.experiment_id,
            candidate_id=candidate_id,
            summary=memory_summary,
            parameters=parameters,
            metrics={"objective_score": objective, "uncertainty": uncertainty, **metrics},
            objective_evaluation=objective_evaluation,
            quality={
                "ok_for_bo": bool(state.latest_analysis.get("ok_for_bo", True)) and not failure_tags,
                "ok_for_evolution": bool(artifact_refs or metrics or failure_tags),
                "warnings": failure_tags,
                "artifact_coverage": artifact_quality,
            },
            artifact_refs={"analysis_artifacts": artifact_refs},
            provenance=provenance,
            source_refs=source_refs,
            created_at=now,
        )

        metadata_for_ledger = dict(state.run_metadata)
        metadata_for_ledger["knowledge"] = {
            "knowledge_report": True,
            "evolution_evidence_packs": True,
            "memory_summary": memory_summary,
            "artifact_refs": artifact_refs,
        }
        performance_records = build_agent_performance_records(
            run_id=state.run_id,
            metadata=metadata_for_ledger,
            retry_counters=state.retry_counters,
            current_stage=state.stage.value,
            analysis_payload=state.latest_analysis,
            knowledge_artifacts=artifact_refs,
        )
        failure_patterns = update_failure_patterns(
            run_id=state.run_id,
            performance_records=performance_records,
            failure_tags=failure_tags,
            existing_patterns=store.list_failure_patterns(limit=200),
            evidence_refs=artifact_refs,
        )
        success_patterns = update_success_patterns(
            run_id=state.run_id,
            performance_records=performance_records,
            existing_patterns=store.list_success_patterns(limit=200),
            evidence_refs=artifact_refs,
        )
        ranked_targets = rank_evolution_targets(performance_records, failure_patterns)
        evidence_packs = build_evidence_packs(
            run_id=state.run_id,
            experiment_record=experiment_record,
            performance_records=performance_records,
            failure_patterns=failure_patterns,
            success_patterns=success_patterns,
            ranked_targets=ranked_targets,
            evidence_refs=artifact_refs,
        )
        evolution_prefill = [map_pack_to_evolution_task(pack) for pack in evidence_packs]
        evolution_outcomes = build_outcomes_for_active_variants(
            run_id=state.run_id,
            performance_records=performance_records,
            evolution_root=project_root / "memory" / "evolution",
            existing_outcomes=store.list_evolution_outcomes(limit=500),
            evidence_refs=artifact_refs,
        )
        evolution_outcome_payloads = [record.model_dump(mode="json") for record in evolution_outcomes]
        research_context = retrieve_research_context(query=query, retrieval_result=retrieval)
        graph_backend = graph_backend_from_env(project_root)
        graph_backend_status = mirror_knowledge_records(
            graph_backend,
            experiment_record=experiment_record,
            performance_records=performance_records,
            failure_patterns=failure_patterns,
            success_patterns=success_patterns,
            evidence_packs=evidence_packs,
            evolution_outcomes=evolution_outcomes,
        )
        graph_backend.close()
        graph_event_status = _ingest_graph_event(
            project_root=project_root,
            state=state,
            experiment_record=experiment_record,
            artifact_refs=artifact_refs,
            occurred_at=now,
            activity_counts={
                "collected": 1 + len(performance_records) + len(artifact_refs),
                "updated": len(failure_patterns) + len(success_patterns) + len(evidence_packs) + len(evolution_outcomes),
                "retrieved": len(retrieval.get("local_chunks", [])) + len(retrieval.get("web_results", [])),
                "used": 1,
            },
            activity_consumers=["orchestrator"],
        )
        await _notify_reconciliation_worker(ctx, graph_event_status)
        knowledge_context = {
            "schema": "knowledge_context.v1",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "record_id": experiment_record.record_id,
            "retrieval": {
                "coverage": retrieval.get("coverage", 0.0),
                "local_chunks": len(retrieval.get("local_chunks", [])),
                "web_results": len(retrieval.get("web_results", [])),
            },
            "memory_tiers": {
                "hot": {"warnings": failure_tags, "constraints": memory_summary, "guardian_incidents": guardian_incident_evidence.get("incident_ids", [])},
                "episodic": [experiment_record.record_id],
                "semantic": [item.pattern_id for item in failure_patterns] + [item.skill_id for item in success_patterns],
                "evolution": [item.pack_id for item in evidence_packs],
                "archival": [item.get("path") or item.get("artifact_id") for item in artifact_refs],
            },
            "evidence_quality": {
                "provenance_used_count": len(provenance.used),
                "artifact_link_coverage": artifact_quality.get("coverage", 1.0),
                "agent_report_coverage": _agent_report_coverage(performance_records),
                "evolution_pack_count": len(evidence_packs),
                "evolution_outcome_count": len(evolution_outcomes),
                "graph_backend_enabled": bool(graph_backend_status.get("enabled", False)),
                "graph_event_pipeline_enabled": bool(graph_event_status.get("enabled", False)),
                "graph_pending_event_count": int((graph_event_status.get("outbox") or {}).get("pending", 0)),
                "graph_safety_lag_count": int((graph_event_status.get("sync") or {}).get("safety_lag", 0)),
                "guardian_incident_count": guardian_incident_evidence.get("incident_count", 0),
                "guardian_gate_count": guardian_incident_evidence.get("gate_count", 0),
                "guardian_hardware_alert_count": guardian_incident_evidence.get("hardware_alert_count", 0),
            },
            "guardian_incident_evidence": guardian_incident_evidence,
            "graph_backend_status": graph_backend_status,
            "graph_event_status": graph_event_status,
        }
        evolution_proposal = {
            "schema": "evolution_proposal.v1",
            "run_id": state.run_id,
            "status": "ready" if evidence_packs else "no_evolution_needed",
            "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
            "prefill_tasks": evolution_prefill,
            "outcomes": evolution_outcome_payloads,
            "no_evolution_needed_reason": "No repeated failure, missing-field, retry, or warning pattern crossed the evidence threshold." if not evidence_packs else "",
        }
        knowledge_report = {
            "schema": "knowledge_report.v1",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "summary": memory_summary,
            "memory_intake": {
                "experiment_record_id": experiment_record.record_id,
                "agent_performance_count": len(performance_records),
                "failure_pattern_count": len(failure_patterns),
                "success_pattern_count": len(success_patterns),
                "evolution_pack_count": len(evidence_packs),
                "evolution_outcome_count": len(evolution_outcomes),
            },
            "experiment_memory": experiment_record.model_dump(mode="json"),
            "agent_performance_records": [record.model_dump(mode="json") for record in performance_records],
            "failure_patterns": [record.model_dump(mode="json") for record in failure_patterns],
            "success_patterns": [record.model_dump(mode="json") for record in success_patterns],
            "self_evolution": evolution_proposal,
            "evolution_outcomes": evolution_outcome_payloads,
            "data_quality_map": {
                "artifact_link_coverage": artifact_quality,
                "retrieval_sources": research_context,
                "missing_artifacts": artifact_quality.get("missing", []),
                "guardian_incident_failure_tags": guardian_failure_tags,
            },
            "guardian_incident_evidence": guardian_incident_evidence,
            "evidence_quality": knowledge_context["evidence_quality"],
            "graph_backend_status": graph_backend_status,
            "graph_event_status": graph_event_status,
            "warnings": failure_tags,
        }
        full_evidence_packs = [pack.model_dump(mode="json") for pack in evidence_packs]
        artifact_paths = store.write_run_artifacts(
            state.run_id,
            {
                "knowledge_report": knowledge_report,
                "experiment_knowledge_record": experiment_record.model_dump(mode="json"),
                "agent_performance_records": [record.model_dump(mode="json") for record in performance_records],
                "failure_patterns": [record.model_dump(mode="json") for record in failure_patterns],
                "success_patterns": [record.model_dump(mode="json") for record in success_patterns],
                "evolution_evidence_packs": full_evidence_packs,
                "evolution_outcomes": evolution_outcome_payloads,
            },
        )
        store.append_experiment_record(experiment_record)
        store.append_agent_performance_records(performance_records)
        store.append_failure_patterns(failure_patterns)
        store.append_success_patterns(success_patterns)
        store.append_evolution_evidence_packs(evidence_packs)
        for outcome in evolution_outcomes:
            store.append_evolution_outcome(outcome)

        compact_evidence_packs = [_compact_evidence_pack(pack) for pack in full_evidence_packs]
        compact_evolution_proposal = dict(evolution_proposal)
        compact_evolution_proposal["evidence_packs"] = compact_evidence_packs
        compact_knowledge_report = _compact_knowledge_report(knowledge_report, compact_evolution_proposal)

        return AgentResult(
            success=True,
            summary="Knowledge memory, pattern ledger, and self-evolution evidence update complete",
            data={
                "knowledge": {
                    "retrieval_coverage": retrieval.get("coverage", 0.0),
                    "local_chunks": len(retrieval.get("local_chunks", [])),
                    "web_results": len(retrieval.get("web_results", [])),
                    "memory_summary": memory_summary,
                    "artifact_ref_count": len(memory_record.artifact_refs),
                    "metric_count": len(memory_record.metrics),
                    "failure_tags": memory_record.failure_tags,
                    "knowledge_context": knowledge_context,
                    "knowledge_report": compact_knowledge_report,
                    "evolution_proposal": compact_evolution_proposal,
                    "self_evolution": {"evidence_packs": compact_evidence_packs, "prefill_tasks": evolution_prefill, "outcomes": evolution_outcome_payloads},
                    "artifact_paths": artifact_paths,
                    "agent_performance_count": len(performance_records),
                    "failure_pattern_count": len(failure_patterns),
                    "success_pattern_count": len(success_patterns),
                    "evolution_pack_count": len(evidence_packs),
                    "evolution_outcome_count": len(evolution_outcomes),
                    "graph_backend_status": graph_backend_status,
                    "graph_event_status": graph_event_status,
                    "guardian_incident_evidence": guardian_incident_evidence,
                    "guardian_incident_count": guardian_incident_evidence.get("incident_count", 0),
                },
                "knowledge_context": knowledge_context,
                "evolution_proposal": compact_evolution_proposal,
            },
        )


def _ingest_graph_event(
    *,
    project_root: Path,
    state: OrchestratorState,
    experiment_record: ExperimentKnowledgeRecord,
    artifact_refs: list[dict[str, Any]],
    occurred_at: str,
    activity_counts: dict[str, int] | None = None,
    activity_consumers: list[str] | None = None,
) -> dict[str, Any]:
    if not event_pipeline_enabled():
        return {"ok": True, "enabled": False, "status": "disabled", "outbox": {"pending": 0, "acknowledged": 0, "dead_letter": 0}}
    candidate_id = _candidate_id_from_state(state)
    specimen_id = _specimen_id_from_state(state)
    cycle_id = str(state.run_metadata.get("cycle_id") or state.run_metadata.get("cycle") or "cycle-unknown")
    experiment_entity = f"runtime:experiment:{state.experiment_id}"
    candidate_entity = f"runtime:candidate:{candidate_id}"
    specimen_entity = f"runtime:specimen:{specimen_id}"
    payload = {
        "run_id": state.run_id,
        "cycle_id": cycle_id,
        "source_agent": "knowledge_agent",
        "event_type": "specimen.analyzed",
        "occurred_at": occurred_at,
        "entity_refs": [
            {"entity_id": f"runtime:run:{state.run_id}", "entity_class": "Run", "status": "running"},
            {"entity_id": experiment_entity, "entity_class": "Experiment", "status": "analyzed"},
            {"entity_id": candidate_entity, "entity_class": "Candidate"},
            {"entity_id": specimen_entity, "entity_class": "Specimen", "status": "analyzed"},
        ],
        "relationship_intents": [
            {
                "relation_id": f"relation:{state.experiment_id}:evaluates:{candidate_id}",
                "relation_type": "EVALUATES",
                "source_id": experiment_entity,
                "source_class": "Experiment",
                "target_id": candidate_entity,
                "target_class": "Candidate",
            },
            {
                "relation_id": f"relation:{candidate_id}:generates:{specimen_id}",
                "relation_type": "GENERATES",
                "source_id": candidate_entity,
                "source_class": "Candidate",
                "target_id": specimen_entity,
                "target_class": "Specimen",
            },
        ],
        "artifact_refs": artifact_refs,
        "payload_summary": {
            "experiment_record_id": experiment_record.record_id,
            "objective_score": experiment_record.metrics.get("objective_score", 0.0),
            "uncertainty": experiment_record.metrics.get("uncertainty", 1.0),
            "failure_tags": list(experiment_record.quality.get("warnings", []))[:50],
            "activity": {
                key: max(0, int((activity_counts or {}).get(key, 0)))
                for key in ("collected", "updated", "retrieved", "used")
            },
            "activity_consumers": [str(item) for item in (activity_consumers or []) if str(item).strip()][:12],
        },
        "provenance": experiment_record.provenance.model_dump(mode="json"),
    }
    service: KnowledgeService | None = None
    try:
        service = KnowledgeService.from_env(project_root)
        return {"enabled": True, **service.ingest(payload)}
    except Exception as exc:
        return {
            "ok": True,
            "enabled": True,
            "status": "degraded",
            "error": f"{exc.__class__.__name__}: {exc}",
            "outbox": {"pending": 0, "acknowledged": 0, "dead_letter": 0},
            "sync": {"acknowledged": 0, "safety_lag": 0},
        }
    finally:
        if service is not None:
            service.close()


async def _notify_reconciliation_worker(ctx: AgentContext, graph_event_status: dict[str, Any]) -> None:
    """Wake the app-owned worker after a durable Knowledge event without coupling failures."""
    if not graph_event_status.get("enabled") or not graph_event_status.get("ok", False):
        return
    callback = getattr(ctx, "on_knowledge_ingest", None)
    if callback is None:
        return
    try:
        result = callback(graph_event_status=graph_event_status)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return



def _guardian_incident_evidence_from_state(state: OrchestratorState) -> dict[str, Any]:
    """Return Guardian incident/gate evidence for Knowledge and Self-Evolution intake."""
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    incidents = _list_of_dicts(metadata.get("incident_records"))[-50:]
    gates = _list_of_dicts(metadata.get("guardian_gates"))[-80:]
    hardware_alerts = _list_of_dicts(metadata.get("hardware_alerts"))[-50:]
    tool_records = _list_of_dicts(metadata.get("tool_call_records"))[-80:]

    tags: list[str] = []
    incident_ids: list[str] = []
    for incident in incidents:
        incident_id = str(incident.get("incident_id") or incident.get("id") or "")
        if incident_id:
            incident_ids.append(incident_id)
        for key in ("reason_code", "failure_code", "severity", "component", "risk_class"):
            value = str(incident.get(key) or "").strip()
            if value:
                tags.append(value)
    for gate in gates:
        decision = str(gate.get("decision") or "").strip()
        reason = str(gate.get("reason_code") or "").strip()
        if decision in {"block", "safe_stop", "require_human_approval", "allow_with_warning"} and reason:
            tags.append(reason)
    for alert in hardware_alerts:
        for key in ("failure_code", "reason_code", "severity", "component"):
            value = str(alert.get(key) or "").strip()
            if value:
                tags.append(value)
    for record in tool_records:
        status = str(record.get("status") or "").strip()
        if status in {"failed", "blocked", "approval_required"}:
            for key in ("failure_code", "guardian_reason_code", "tool"):
                value = str(record.get(key) or "").strip()
                if value:
                    tags.append(value)

    gate_decisions = [
        {
            "gate_id": gate.get("gate_id", ""),
            "stage": gate.get("stage", ""),
            "phase": gate.get("phase", ""),
            "decision": gate.get("decision", ""),
            "reason_code": gate.get("reason_code", ""),
            "risk_score": gate.get("risk_score", 0.0),
        }
        for gate in gates[-20:]
        if isinstance(gate, dict)
    ]
    return {
        "schema": "guardian_incident_evidence.v1",
        "run_id": state.run_id,
        "incident_count": len(incidents),
        "gate_count": len(gates),
        "hardware_alert_count": len(hardware_alerts),
        "tool_call_record_count": len(tool_records),
        "incident_ids": incident_ids[-20:],
        "failure_tags": sorted(dict.fromkeys(tags))[:80],
        "incident_records": incidents[-20:],
        "gate_decisions": gate_decisions,
        "hardware_alerts": hardware_alerts[-20:],
        "blocked_tool_records": [item for item in tool_records if str(item.get("status") or "") in {"failed", "blocked", "approval_required"}][-20:],
    }

def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _candidate_id_from_state(state: OrchestratorState) -> str:
    for source in (state.latest_analysis, state.current_experiment_spec, state.run_metadata):
        if not isinstance(source, dict):
            continue
        for key in ("candidate_id", "specimen_id", "design_id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return state.experiment_id


def _specimen_id_from_state(state: OrchestratorState) -> str:
    for source in (state.latest_analysis, state.current_experiment_spec, state.run_metadata):
        if not isinstance(source, dict):
            continue
        value = source.get("specimen_id")
        if isinstance(value, str) and value:
            return value
    return _candidate_id_from_state(state)


def _parameters_from_state(state: OrchestratorState) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for source in (state.current_experiment_spec, state.current_experiment_objective):
        if isinstance(source, dict):
            params.update(source)
    design = state.run_metadata.get("design_report") if isinstance(state.run_metadata.get("design_report"), dict) else {}
    if isinstance(design.get("selected_candidate"), dict):
        params.update(design["selected_candidate"])
    return params


def _source_refs_from_retrieval(retrieval: dict[str, Any]) -> list[KnowledgeSourceRef]:
    refs: list[KnowledgeSourceRef] = []
    coverage = float(retrieval.get("coverage") or 0.0)
    for chunk in retrieval.get("local_chunks", []) or []:
        if isinstance(chunk, dict):
            refs.append(
                KnowledgeSourceRef(
                    source_type="project_guideline",
                    source_ref=str(chunk.get("source") or chunk.get("chunk_id") or "local_chunk"),
                    trust_level="project_local_index",
                    recency="indexed",
                    retrieval_score=float(chunk.get("score") or coverage),
                    used_for=["run_context", "knowledge_report"],
                )
            )
    for item in retrieval.get("web_results", []) or []:
        if isinstance(item, dict):
            refs.append(
                KnowledgeSourceRef(
                    source_type="official_doc" if item.get("url") else "scientific_paper",
                    source_ref=str(item.get("url") or item.get("title") or "web_result"),
                    trust_level="external_retrieval",
                    recency="retrieved",
                    retrieval_score=float(item.get("score") or 0.0),
                    used_for=["research_context"],
                )
            )
    return refs[:12]


def _agent_report_coverage(records: list[Any]) -> float:
    if not records:
        return 0.0
    observed = sum(1 for record in records if getattr(record, "status", "") in {"success", "warning", "failed"})
    return round(observed / len(records), 4)


def _deterministic_memory_summary(state: OrchestratorState, retrieval: dict[str, Any]) -> str:
    """Fast test-mode summary when tests explicitly disable real LLM calls."""
    score = state.latest_analysis.get("objective_score", "n/a")
    uncertainty = state.latest_analysis.get("uncertainty", "n/a")
    coverage = retrieval.get("coverage", 0.0)
    return (
        f"Deterministic Knowledge summary for {state.experiment_id}: "
        f"objective_score={score}, uncertainty={uncertainty}, retrieval_coverage={coverage}. "
        "Preserve provenance, quality flags, and self-evolution evidence before BO/Guardian handoff."
    )[:500]


def _compact_evidence_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """Return a GUI/controller-safe evidence pack without large artifact fan-out."""
    compact = dict(pack)
    supporting = dict(compact.get("supporting_records") or {}) if isinstance(compact.get("supporting_records"), dict) else {}
    artifact_refs = supporting.get("artifact_refs") if isinstance(supporting.get("artifact_refs"), list) else []
    supporting["artifact_ref_count"] = len(artifact_refs)
    supporting["artifact_refs"] = artifact_refs[:3]
    compact["supporting_records"] = supporting
    return compact


def _compact_record_artifacts(record: Any) -> Any:
    """Cap artifact-bearing lists inside a report record."""
    if not isinstance(record, dict):
        return record
    compact = dict(record)
    for key in ("artifact_refs", "evidence_refs"):
        refs = compact.get(key)
        if isinstance(refs, list):
            compact[f"{key}_count"] = len(refs)
            compact[key] = refs[:3]
    provenance = compact.get("provenance") if isinstance(compact.get("provenance"), dict) else {}
    if provenance:
        used = provenance.get("used") if isinstance(provenance.get("used"), list) else []
        provenance = dict(provenance)
        provenance["used_count"] = len(used)
        provenance["used"] = used[:5]
        fingerprints = provenance.get("artifact_fingerprints") if isinstance(provenance.get("artifact_fingerprints"), dict) else {}
        provenance["artifact_fingerprint_count"] = len(fingerprints)
        provenance["artifact_fingerprints"] = dict(list(fingerprints.items())[:3])
        compact["provenance"] = provenance
    return compact


def _compact_knowledge_report(report: dict[str, Any], compact_evolution_proposal: dict[str, Any]) -> dict[str, Any]:
    """Return report payload suitable for Live GUI while full JSON remains in run artifacts."""
    compact = dict(report)
    compact["self_evolution"] = compact_evolution_proposal
    compact["agent_performance_records"] = [_compact_record_artifacts(item) for item in list(compact.get("agent_performance_records", []))[:12]]
    compact["failure_patterns"] = [_compact_record_artifacts(item) for item in list(compact.get("failure_patterns", []))[:12]]
    compact["success_patterns"] = [_compact_record_artifacts(item) for item in list(compact.get("success_patterns", []))[:12]]
    experiment_memory = dict(compact.get("experiment_memory") or {}) if isinstance(compact.get("experiment_memory"), dict) else {}
    artifact_refs = experiment_memory.get("artifact_refs") if isinstance(experiment_memory.get("artifact_refs"), dict) else {}
    analysis_artifacts = artifact_refs.get("analysis_artifacts") if isinstance(artifact_refs.get("analysis_artifacts"), list) else []
    artifact_refs["analysis_artifacts_count"] = len(analysis_artifacts)
    artifact_refs["analysis_artifacts"] = analysis_artifacts[:5]
    experiment_memory["artifact_refs"] = artifact_refs
    compact["experiment_memory"] = experiment_memory
    return compact
