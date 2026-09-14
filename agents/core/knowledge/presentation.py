"""Read-only Knowledge report projection for the shared Live host."""

from __future__ import annotations

from copy import deepcopy


REPORT_PROFILE = {
    "title": "Knowledge Memory / Evidence Update",
    "summary": "Writes validated outcomes into session/project knowledge so BO and later reports use observed evidence.",
    "focus_rows": [
        {"label": "Memory", "value": "experiment id, specimen id, final parameters, metrics, and artifacts"},
        {"label": "Quality", "value": "provenance, duplicate detection, uncertainty, and failed-run notes"},
        {"label": "Consumers", "value": "BO candidate selection and final report generation"},
    ],
    "checklist": ["Store observed data", "Link artifacts", "Expose BO-ready row"],
}


def project_knowledge_report(metadata: dict, agent_payload: dict) -> dict:
    """Project the existing Knowledge payload without storing or normalizing it."""
    stored = metadata.get("knowledge") if isinstance(metadata.get("knowledge"), dict) else {}
    fallback = agent_payload.get("knowledge") if isinstance(agent_payload.get("knowledge"), dict) else agent_payload
    payload = deepcopy(stored or fallback if isinstance(fallback, dict) else {})
    knowledge_report = payload.get("knowledge_report") if isinstance(payload.get("knowledge_report"), dict) else {}
    knowledge_context = payload.get("knowledge_context") if isinstance(payload.get("knowledge_context"), dict) else {}
    evolution_proposal = payload.get("evolution_proposal") if isinstance(payload.get("evolution_proposal"), dict) else {}
    role_specific = deepcopy(REPORT_PROFILE)
    role_specific["relation_reconciliation"] = deepcopy(metadata.get("_relation_reconciliation", {
        "examined": 0, "proposed": 0, "auto_approved": 0, "pending": 0,
        "rejected_deferred": 0, "worker_status": "retired", "worker_running": False,
        "review_url": "/knowledge",
    }))
    decisions: list[dict] = []
    metrics: dict = {}
    if knowledge_report:
        memory_intake = knowledge_report.get("memory_intake") if isinstance(knowledge_report.get("memory_intake"), dict) else {}
        improvement_evidence = evolution_proposal
        packs = improvement_evidence.get("evidence_packs") if isinstance(improvement_evidence.get("evidence_packs"), list) else []
        performance = knowledge_report.get("agent_performance_records") if isinstance(knowledge_report.get("agent_performance_records"), list) else []
        role_specific.update({
            "summary": "Research memory board with provenance, failure/success pattern memory, agent performance ledger, and improvement evidence packs.",
            "memory_ledger": {
                "experiment_record_id": memory_intake.get("experiment_record_id", ""),
                "agent_performance_count": memory_intake.get("agent_performance_count", 0),
                "failure_pattern_count": memory_intake.get("failure_pattern_count", 0),
                "success_pattern_count": memory_intake.get("success_pattern_count", 0),
                "evolution_pack_count": memory_intake.get("evolution_pack_count", len(packs)),
                "artifact_paths": payload.get("artifact_paths", {}),
            },
            "retrieval_panel": {
                "coverage": payload.get("retrieval_coverage", 0.0),
                "local_chunks": payload.get("local_chunks", 0),
                "web_results": payload.get("web_results", 0),
                "sources": (knowledge_report.get("data_quality_map") or {}).get("retrieval_sources", {}) if isinstance(knowledge_report.get("data_quality_map"), dict) else {},
            },
            "failure_success_library": {
                "failure_patterns": knowledge_report.get("failure_patterns", []),
                "success_patterns": knowledge_report.get("success_patterns", []),
            },
            "improvement_evidence_board": {
                "status": improvement_evidence.get("status", ""), "top_packs": packs[:5],
                "outcomes": improvement_evidence.get("outcomes", knowledge_report.get("evolution_outcomes", [])),
                "no_evolution_needed_reason": improvement_evidence.get("no_evolution_needed_reason", ""),
            },
            "data_quality_map": knowledge_report.get("data_quality_map", {}),
            "graph_backend_status": knowledge_report.get("graph_backend_status", knowledge_context.get("graph_backend_status", {})),
            "agent_performance_memory": performance,
            "handoff_packet": {"knowledge_context": knowledge_context, "evolution_proposal": evolution_proposal},
        })
        decisions = [{
            "decision": "prepare_improvement_evidence_pack",
            "target_type": pack.get("target_type", ""), "target_id": pack.get("target_id", ""),
            "priority": pack.get("priority", 0.0),
            "rationale": "; ".join(pack.get("why_this_target", [])[:2]),
        } for pack in packs[:8] if isinstance(pack, dict)] or [{
            "decision": "no_evolution_needed",
            "rationale": improvement_evidence.get("no_evolution_needed_reason", "No evidence pack generated."),
        }]
        metrics = knowledge_report.get("evidence_quality", {}) if isinstance(knowledge_report.get("evidence_quality"), dict) else knowledge_context.get("evidence_quality", {}) if isinstance(knowledge_context.get("evidence_quality"), dict) else {}
    return {
        "role_specific": role_specific, "decisions": decisions, "metrics": deepcopy(metrics),
        "knowledge_report": deepcopy(knowledge_report), "knowledge_context": deepcopy(knowledge_context),
        "evolution_proposal": deepcopy(evolution_proposal),
    }
