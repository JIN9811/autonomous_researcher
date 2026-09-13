"""Analysis-owned report profile and read-only projection for the generic host."""
from __future__ import annotations

from typing import Any


REPORT_PROFILE = {
    "title": "UTM / FEM / Objective Evaluation",
    "summary": "Processes measurement or simulation output into force/displacement features and objective scores.",
    "focus_rows": [
        {"label": "Data", "value": "UTM curve, CAE contour, boundary conditions, and specimen metadata"},
        {"label": "Metrics", "value": "stiffness, energy absorption, peak force, mass-normalized score"},
        {"label": "Evidence", "value": "plots, contour SVG, tabular summary, and objective JSON"},
    ],
    "checklist": ["Validate boundary conditions", "Attach quantitative metrics", "Prepare BO observation"],
}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def project_analysis_report(metadata: dict, agent_payload: dict) -> dict:
    """Project existing Analysis state without querying or changing its worker."""
    state = _dict(metadata.get("_projection_state"))
    state_analysis = _dict(state.get("latest_analysis"))
    analysis = state_analysis or _dict(metadata.get("analysis_report")) or _dict(agent_payload.get("analysis"))
    bo_observation = _dict(metadata.get("analysis_bo_observation")) or _dict(agent_payload.get("bo_observation")) or _dict(analysis.get("bo_observation"))
    bo_handoff = _dict(metadata.get("analysis_bo_handoff")) or _dict(agent_payload.get("bo_handoff")) or _dict(analysis.get("bo_handoff"))
    experiment_evaluation = _dict(metadata.get("analysis_experiment_evaluation")) or _dict(agent_payload.get("experiment_evaluation"))
    knowledge_payload = _dict(metadata.get("analysis_knowledge_payload")) or _dict(agent_payload.get("knowledge_payload")) or _dict(analysis.get("knowledge_payload"))
    metrics = _dict(metadata.get("analysis_metrics")) or _dict(agent_payload.get("metrics")) or _dict(analysis.get("utm_metrics"))
    decisions = analysis.get("decisions") if isinstance(analysis.get("decisions"), list) else agent_payload.get("decisions") if isinstance(agent_payload.get("decisions"), list) else []
    role_specific: dict[str, Any] = {}
    if analysis:
        role_specific = {
            "summary": "Measured UTM evaluation, optional CAE/FEM evidence, objective quality gates, and BO handoff.",
            "measurement": _dict(analysis.get("utm_metrics")),
            "data_quality": _dict(analysis.get("data_quality_gate")) or _dict(analysis.get("quality_gate")),
            "objective": {
                "score": analysis.get("objective_score"),
                "uncertainty": analysis.get("uncertainty"),
                "uncertainty_status": _dict(analysis.get("uncertainty_status")),
            },
            "cae": _dict(analysis.get("cae_result")),
            "fem": _dict(analysis.get("fem_agentic_loop")) or _dict(analysis.get("fem_job")) or _dict(analysis.get("fem_result")),
            "multifidelity_comparison": _dict(analysis.get("multifidelity_comparison")),
            "trust_score": _dict(analysis.get("trust_score")),
            "artifacts": _dict(analysis.get("analysis_artifacts")),
            "handoff_packet": bo_handoff,
            "bo_observation": bo_observation,
            "knowledge_payload": knowledge_payload,
        }
    return {
        "role_specific": role_specific,
        "decisions": decisions,
        "metrics": metrics,
        "analysis_report": analysis or None,
        "bo_observation": bo_observation or None,
        "bo_handoff": bo_handoff or None,
        "experiment_evaluation": experiment_evaluation or None,
        "knowledge_payload": knowledge_payload or None,
    }
