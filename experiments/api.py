"""
File purpose:
- Execute candidates through the standard Autonomous Experiment Runtime API.

Key classes/functions:
- ExperimentRuntime
- evaluate_experiment

Inputs/outputs:
- Input: ExperimentEvaluationRequest or MCP-style payload
- Output: ExperimentEvaluationResult as a dictionary

Dependencies:
- experiments.schemas
- optional mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: bridge routing, virtual scoring heuristics
- Risky places to edit: result field names consumed by GUI, logs, and tests
"""

from __future__ import annotations

import hashlib
from typing import Any

from experiments.schemas import ExperimentEvaluationRequest, ExperimentEvaluationResult, request_from_payload


def _evaluation_id(request: ExperimentEvaluationRequest) -> str:
    seed = (
        f"{request.experiment_id}|{request.session_id}|"
        f"{request.candidate.candidate_id}|{request.execution.mode}|{request.execution.bridge}"
    )
    return f"eval-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _virtual_score(request: ExperimentEvaluationRequest) -> tuple[float, dict[str, Any]]:
    """Compute deterministic virtual objective score from candidate/spec fields."""
    params = request.candidate.merged_parameters()
    if "expected_objective_proxy_score" in params:
        score = _as_float(params.get("expected_objective_proxy_score"))
    else:
        density = _as_float(params.get("relative_density"), 0.32)
        wall = _as_float(params.get("wall_thickness_mm"), 1.2)
        cell = max(0.1, _as_float(params.get("cell_size_mm"), 5.0))
        mass = _as_float(params.get("expected_mass_g"), 0.0)
        print_time = _as_float(params.get("expected_print_time_min"), 0.0)
        geometry_bonus = 0.08 if str(params.get("geometry_type", "")).lower() == "gyroid" else 0.0
        density_term = 1.0 - abs(density - 0.32)
        manufacturability = min(1.0, wall / max(1.2, 0.24 * cell))
        cost_penalty = 0.002 * mass + 0.001 * print_time
        score = max(0.0, density_term * 0.55 + manufacturability * 0.35 + geometry_bonus - cost_penalty)
    direction = request.objective.direction
    metric_name = request.objective.metric_name
    if direction == "minimize":
        score = -score
    elif direction == "target" and request.objective.target_value is not None:
        score = -abs(score - float(request.objective.target_value))
    metrics = {
        metric_name: round(score, 6),
        "virtual": True,
        "relative_density": params.get("relative_density"),
        "wall_thickness_mm": params.get("wall_thickness_mm"),
        "cell_size_mm": params.get("cell_size_mm"),
        "geometry_type": params.get("geometry_type"),
    }
    return round(score, 6), metrics


def _select_bridge(request: ExperimentEvaluationRequest) -> str:
    bridge = request.execution.bridge
    if bridge != "auto":
        return bridge
    tool = str(request.execution.requested_tool or "")
    params = request.candidate.merged_parameters()
    if tool.startswith("printer.") or params.get("stl_path") or params.get("handoff_package_path"):
        return "printer"
    return "virtual" if request.execution.mode in {"test", "virtual"} else "analysis"


class ExperimentRuntime:
    """Common runtime facade used by agents, GUI, benchmarks, and tests."""

    def __init__(self, tools: Any | None = None) -> None:
        self.tools = tools

    def evaluate(self, request: ExperimentEvaluationRequest | dict[str, Any]) -> dict[str, Any]:
        """Evaluate one candidate and return the standard result dictionary."""
        normalized = request_from_payload(request) if isinstance(request, dict) else request
        bridge = _select_bridge(normalized)
        if bridge == "printer":
            return self._evaluate_printer(normalized)
        return self._evaluate_virtual(normalized, bridge=bridge)

    def _evaluate_virtual(self, request: ExperimentEvaluationRequest, *, bridge: str) -> dict[str, Any]:
        score, metrics = _virtual_score(request)
        result = ExperimentEvaluationResult(
            ok=True,
            run_id=request.run_id,
            experiment_id=request.experiment_id,
            session_id=request.session_id,
            evaluation_id=_evaluation_id(request),
            objective=request.objective,
            candidate_id=request.candidate.candidate_id,
            mode=request.execution.mode,
            bridge=bridge,
            status="evaluated",
            objective_score=score,
            metrics=metrics,
            artifacts={},
            bridge_result={"ok": True, "status": "virtual_evaluated"},
            step_trace=[
                {"step": "NORMALIZE_REQUEST", "status": "ok"},
                {"step": "EVALUATE_OBJECTIVE", "status": "ok", "detail": request.objective.metric_name},
                {"step": "DONE", "status": "ok"},
            ],
        )
        return result.model_dump(mode="json")

    def _evaluate_printer(self, request: ExperimentEvaluationRequest) -> dict[str, Any]:
        if self.tools is None:
            return self._printer_unavailable(request, "TOOL_REGISTRY_UNAVAILABLE")
        available = set(self.tools.list_tools()) if hasattr(self.tools, "list_tools") else set()
        if "printer.prepare" not in available:
            return self._printer_unavailable(request, "PRINTER_TOOL_UNAVAILABLE")

        params = request.candidate.merged_parameters()
        print_payload = params.get("print") if isinstance(params.get("print"), dict) else {}
        if request.execution.allow_physical and request.execution.mode == "live":
            print_payload = {**print_payload, "start_immediately": bool(print_payload.get("start_immediately", True))}
        experiment_spec = params.get("experiment_spec") if isinstance(params.get("experiment_spec"), dict) else params
        payload = {
            **params,
            "run_id": request.run_id,
            "experiment_id": request.experiment_id,
            "session_id": request.session_id,
            "runtime_mode": request.execution.mode,
            "experiment_spec": experiment_spec,
            "print": print_payload,
        }
        bridge_result = self.tools.call("printer.prepare", payload)
        score, metrics = _virtual_score(request)
        metrics.update(
            {
                "printer_status": bridge_result.get("status"),
                "slicer_ok": bool((bridge_result.get("slicer_result") or {}).get("ok", False))
                if isinstance(bridge_result.get("slicer_result"), dict)
                else None,
                "gcode_ok": bool((bridge_result.get("gcode_validation") or {}).get("ok", False))
                if isinstance(bridge_result.get("gcode_validation"), dict)
                else None,
            }
        )
        ok = bool(bridge_result.get("ok", False))
        status = str(bridge_result.get("status") or ("evaluated" if ok else "failed"))
        result = ExperimentEvaluationResult(
            ok=ok,
            run_id=request.run_id,
            experiment_id=request.experiment_id,
            session_id=request.session_id,
            evaluation_id=_evaluation_id(request),
            objective=request.objective,
            candidate_id=request.candidate.candidate_id,
            mode=request.execution.mode,
            bridge="printer",
            status=status,
            objective_score=score if ok else None,
            metrics=metrics,
            artifacts=bridge_result.get("artifacts") if isinstance(bridge_result.get("artifacts"), dict) else {},
            bridge_result=bridge_result,
            job=bridge_result.get("job") if isinstance(bridge_result.get("job"), dict) else None,
            step_trace=bridge_result.get("step_trace") if isinstance(bridge_result.get("step_trace"), list) else [],
            failure_code=bridge_result.get("failure_code"),
        )
        return result.model_dump(mode="json")

    def _printer_unavailable(self, request: ExperimentEvaluationRequest, failure_code: str) -> dict[str, Any]:
        result = ExperimentEvaluationResult(
            ok=False,
            run_id=request.run_id,
            experiment_id=request.experiment_id,
            session_id=request.session_id,
            evaluation_id=_evaluation_id(request),
            objective=request.objective,
            candidate_id=request.candidate.candidate_id,
            mode=request.execution.mode,
            bridge="printer",
            status="blocked",
            failure_code=failure_code,
            step_trace=[{"step": "RESOLVE_PRINTER_TOOL", "status": "blocked", "detail": failure_code}],
        )
        return result.model_dump(mode="json")


def evaluate_experiment(
    request: ExperimentEvaluationRequest | dict[str, Any],
    *,
    tools: Any | None = None,
) -> dict[str, Any]:
    """Convenience function for one-off evaluation."""
    return ExperimentRuntime(tools=tools).evaluate(request)
