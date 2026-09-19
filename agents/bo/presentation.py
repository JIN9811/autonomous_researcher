"""BO-owned report profile and read-only projection for the generic host."""
from __future__ import annotations

from typing import Any


# Read-only report input contract; unlisted state is never copied for this view.
REPORT_METADATA_KEYS = ["bo_agent","next_design_request"]
REPORT_STATE_FIELDS = ["current_experiment_objective"]

REPORT_PROFILE = {
    "title": "Bayesian Optimization / Candidate Selection",
    "summary": "Uses measured evidence and the existing numerical optimizer to propose the next Design constraints.",
    "focus_rows": [
        {"label": "Input", "value": "Analysis observations, objective identity, failure evidence, and local knowledge"},
        {"label": "Numerics", "value": "LHS initialization, BoTorch posterior/acquisition, and exact solver coordinates"},
        {"label": "Handoff", "value": "candidate ranking, evidence audit, artifacts, and next Design request"},
    ],
    "checklist": ["Confirm objective identity", "Inspect measured priors", "Preserve numerical candidate", "Review Design handoff"],
}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def project_objective(metadata: dict, bo_result: dict) -> dict | None:
    """Prefer this run's immutable binding; never borrow the global latest spec."""
    from experiments.bo_visualization import objective_display
    from objectives.metric_registry import MetricRegistry

    state = _dict(metadata.get('_projection_state'))
    status = _dict(metadata.get('_objective_status'))
    binding = _dict(status.get('active_binding'))
    if binding:
        for item in status.get('objective_states', []):
            if not all(item.get(key) == binding.get(key) for key in ('objective_id', 'version', 'objective_hash')):
                continue
            spec = dict(_dict(item.get('spec')))
            spec.update(objective_hash=binding.get('objective_hash'), run_bound=True)
            expression = _dict(spec.get('expression'))
            if expression.get('op') == 'metric':
                try:
                    registry = metadata.get('_objective_registry') or MetricRegistry.default()
                    spec['unit'] = registry.get(expression.get('metric_id', '')).unit
                except (KeyError, ValueError):
                    pass
            display = objective_display(spec)
            return {**display, 'run_id': state.get('run_id', '')}
        return None
    historical = _dict(_dict(bo_result.get('visualization')).get('objective'))
    if historical:
        return {**historical, 'run_id': bo_result.get('run_id') or state.get('run_id', '')}
    current = _dict(state.get('current_experiment_objective'))
    if current.get('expression') or current.get('metric_name'):
        return {**objective_display(current), 'run_id': state.get('run_id', '')}
    return None


def project_bo_report(metadata: dict, agent_payload: dict) -> dict:
    """Project current BO evidence without mutating or recomputing it."""
    bo_result = _dict(metadata.get("bo_agent")) or _dict(agent_payload.get("bo_result"))
    reasoning = _dict(bo_result.get("reasoning"))
    recommendation = _dict(bo_result.get("recommendation"))
    benchmark = _dict(bo_result.get("benchmark"))
    strategies = _dict(benchmark.get("strategies"))
    benchmark_strategy = bo_result.get("benchmark_strategy") or bo_result.get("strategy") or "bo"
    strategy_payload = _dict(strategies.get(benchmark_strategy)) or _dict(strategies.get("bo"))
    surrogate_trace = (
        strategy_payload.get("surrogate_trace")
        if isinstance(strategy_payload.get("surrogate_trace"), list)
        else []
    )
    latest_trace = _dict(surrogate_trace[-1]) if surrogate_trace else {}
    candidate_pool = (
        bo_result.get("candidate_pool")
        if isinstance(bo_result.get("candidate_pool"), list)
        else []
    )
    ranking = (
        bo_result.get("candidate_ranking")
        if isinstance(bo_result.get("candidate_ranking"), list)
        else candidate_pool
    )
    next_design = _dict(bo_result.get("next_design_request")) or _dict(metadata.get("next_design_request"))
    decision_register = []
    if bo_result:
        decision_register = [{
            "decision": "select_next_design_candidate",
            "candidate_id": recommendation.get("candidate_id", ""),
            "source_strategy": recommendation.get("source_strategy", ""),
            "combined_score": recommendation.get("combined_score", ""),
            "rationale": recommendation.get("why_this_candidate") or recommendation.get("reason", ""),
        }]
    role_specific = {}
    if bo_result:
        role_specific = {
            "summary": "BO strategy/tool decisions, measured evidence, numerical acquisition, result review, and the existing Design handoff.",
            "bo_decision": _dict(bo_result.get("decision")),
            "surrogate_panel": {
                "strategy": bo_result.get("strategy", ""),
                "benchmark_strategy": benchmark_strategy,
                "acquisition": bo_result.get("acquisition", ""),
                "budget": bo_result.get("budget", ""),
                "trace_step_count": len(surrogate_trace),
                "latest_selected": _dict(latest_trace.get("selected")),
                "prior_summary": _dict(bo_result.get("prior_summary")),
            },
            "candidate_ranking": ranking[:10],
            "decision_register": decision_register,
            "recommendation": recommendation,
            "handoff_packet": next_design,
            "prior_summary": _dict(bo_result.get("prior_summary")),
            "reasoning_audit": reasoning,
            "failure_model": _dict(bo_result.get("failure_model")),
            "artifacts": _dict(bo_result.get("artifacts")),
            "lhs_visualization": _dict(bo_result.get("lhs_visualization")),
            "visualization": _dict(bo_result.get("visualization")),
        }
    return {
        "objective_display": project_objective(metadata, bo_result),
        "role_specific": role_specific,
        "decisions": decision_register,
        "metrics": {
            "prior_summary": _dict(bo_result.get("prior_summary")),
            "best_so_far_count": len(bo_result.get("best_so_far", [])) if isinstance(bo_result.get("best_so_far"), list) else 0,
            "candidate_count": len(candidate_pool) if candidate_pool else len(ranking),
            "recommended_score": recommendation.get("objective_score"),
        } if bo_result else {},
        "bo_result": bo_result or None,
        "next_design_request": next_design or None,
    }
