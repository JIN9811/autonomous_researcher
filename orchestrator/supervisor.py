"""
Deterministic supervisor helpers for the Orchestration Agent layer.

These helpers keep the Orchestrator's operational records structured without
making the runtime depend on an LLM call for every stage transition.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from orchestrator.state import Mode, OrchestratorState, Stage


STAGE_AGENT: dict[str, str] = {
    Stage.DESIGN.value: "design_agent",
    Stage.SPECIMEN.value: "specimen_agent",
    Stage.VISION.value: "vision_agent",
    Stage.MANIPULATION.value: "manipulation_agent",
    Stage.EQUIPMENT.value: "equipment_agent",
    Stage.ANALYSIS.value: "analysis_agent",
    Stage.KNOWLEDGE.value: "knowledge_agent",
    Stage.BO.value: "bo_agent",
    Stage.GUARDIAN.value: "guardian_agent",
}


REQUIRED_OUTPUTS: dict[str, list[str]] = {
    Stage.DESIGN.value: ["design_candidate", "experiment_spec", "decisions", "metrics", "evidence_refs"],
    Stage.SPECIMEN.value: ["specimen_fabricated", "fabrication_report", "quality_gates", "evidence_refs"],
    Stage.VISION.value: ["vision_signal", "signal_board", "expires_at", "evidence_refs"],
    Stage.MANIPULATION.value: ["robot_task_result", "completion_status", "risk_flags", "evidence_refs"],
    Stage.EQUIPMENT.value: ["utm_data_ready", "result_file", "cross_checks", "evidence_refs"],
    Stage.ANALYSIS.value: ["bo_observation", "observed_metrics", "simulation_metrics", "data_quality"],
    Stage.KNOWLEDGE.value: ["knowledge_context", "evolution_proposal", "evidence_quality"],
    Stage.BO.value: ["next_design_request", "candidate_ranking", "acquisition", "reasoning"],
    Stage.GUARDIAN.value: ["guardian_decision", "incident_records", "corrective_actions"],
}


BASE_ROUTE: list[str] = [
    Stage.DESIGN.value,
    Stage.SPECIMEN.value,
    Stage.VISION.value,
    Stage.MANIPULATION.value,
    Stage.EQUIPMENT.value,
    Stage.ANALYSIS.value,
    Stage.KNOWLEDGE.value,
    Stage.BO.value,
    Stage.GUARDIAN.value,
]

PARALLELIZABLE_CHECKS: list[str] = [
    "knowledge.retrieve_prior_failures",
    "analysis.lookup_fem_cache",
    "guardian.preflight_devices",
    "bo.constraint_sanity_check",
    "artifacts.lookup_existing_outputs",
    "runtime.compare_previous_loop",
]

SERIAL_PHYSICAL_ACTIONS: list[str] = [
    "printer.start_or_virtual_bridge",
    "vision.verify_print_or_fixture_state",
    "robot.pick_to_utm",
    "equipment.utm_start_test",
    "robot.utm_to_discard",
    "printer.auto_ejection_if_enabled",
]

EXPECTED_ARTIFACTS: list[str] = [
    "design_spec.json",
    "specimen.stl",
    "specimen.gcode",
    "vision_frames_or_signals",
    "robot_task_result.json",
    "utm_raw_file",
    "analysis_bo_handoff.json",
    "bo_trace.json",
    "guardian_events.jsonl",
    "knowledge_memory_record.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage_value(stage: Stage | str | None) -> str:
    if isinstance(stage, Stage):
        return stage.value
    return str(stage or "").strip()


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}"


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, "", {}):
        return []
    return [value]



def _stage_plan_status(state: OrchestratorState, stage: str) -> str:
    if stage == stage_value(state.stage):
        return "active"
    if stage in {Stage.COMPLETE.value, Stage.ERROR.value}:
        return "terminal"
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    if metadata.get(f"{stage}_agent_payload") or metadata.get(f"{stage}_handoff_packet"):
        return "completed"
    return "pending"


def _route_from_current_stage(current_stage: str) -> list[str]:
    if current_stage not in BASE_ROUTE:
        return BASE_ROUTE[:]
    index = BASE_ROUTE.index(current_stage)
    return BASE_ROUTE[index:] + BASE_ROUTE[:index]


def build_mission_contract(
    *,
    state: OrchestratorState,
    operator_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact mission contract from the current runtime state."""
    spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
    objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    safety_budget = metadata.get("safety_budget") if isinstance(metadata.get("safety_budget"), dict) else {}
    contract_seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "goal": state.active_goal,
        "stage": state.stage.value,
    }
    return {
        "schema": "experiment_contract.v1",
        "mission_id": stable_id("mission", contract_seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "mode": state.mode.value,
        "stage": state.stage.value,
        "goal": state.active_goal,
        "operator_intent": (operator_intent or {}).get("intent", "not_provided"),
        "material": spec.get("material") or spec.get("material_name") or "",
        "specimen_id": spec.get("specimen_id", ""),
        "specimen_size_mm": spec.get("specimen_size_mm") or spec.get("size_mm") or [],
        "objective_type": objective.get("objective_type") or spec.get("objective_type") or spec.get("objective") or "",
        "constraints": spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {},
        "safety_budget": {
            "max_loop_count": safety_budget.get("max_loop_count", safety_budget.get("loop_count", 5)),
            "max_print_time_min": safety_budget.get("max_print_time_min", safety_budget.get("print_time", 120)),
            "max_robot_live_rollouts": safety_budget.get("max_robot_live_rollouts", 2),
            "requires_guardian_gate": True,
        },
        "requires_guardian_gate": True,
        "created_at": now_iso(),
    }


def build_orchestration_plan(
    *,
    state: OrchestratorState,
    operator_intent: dict[str, Any] | None = None,
    graph_id: str = "atr_closed_loop",
) -> dict[str, Any]:
    """Compile the current supervisor view into an executable plan object."""
    current_stage = stage_value(state.stage) or Stage.IDLE.value
    route = _route_from_current_stage(current_stage)
    route_steps = []
    for index, stage in enumerate(route, start=1):
        route_steps.append(
            {
                "order": index,
                "stage": stage,
                "agent": STAGE_AGENT.get(stage, stage),
                "status": _stage_plan_status(state, stage),
                "required_outputs": REQUIRED_OUTPUTS.get(stage, []),
                "guardian_pre_gate": f"guardian.pre_{stage}",
                "guardian_post_gate": f"guardian.post_{stage}",
            }
        )
    physical_actions = [
        action for action in SERIAL_PHYSICAL_ACTIONS
        if state.mode.value == Mode.LIVE.value or not action.startswith(("printer.start", "robot.", "equipment."))
    ]
    plan_seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "stage": current_stage,
        "intent": (operator_intent or {}).get("intent"),
        "graph_id": graph_id,
    }
    return {
        "schema": "orchestration_plan.v1",
        "plan_id": stable_id("orch-plan", plan_seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "graph_id": graph_id,
        "current_stage": current_stage,
        "operator_intent": operator_intent or {},
        "route": route_steps,
        "parallelizable_checks": PARALLELIZABLE_CHECKS[:],
        "serial_physical_actions": physical_actions,
        "expected_artifacts": EXPECTED_ARTIFACTS[:],
        "control_planes": {
            "execution": "LangGraph stage execution and handoff packets",
            "safety": "Guardian gates, incidents, approvals, safe-stop authority",
            "memory": "Knowledge records and self-evolution evidence packs",
            "gui": "Live GUI report, backend trace, artifacts, and timeline",
        },
        "next_recommended_stage": route_steps[0]["stage"] if route_steps else current_stage,
        "created_at": now_iso(),
    }


def _metadata_records(metadata: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _runtime_approval_records(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    approvals = metadata.get("runtime_approvals")
    if isinstance(approvals, dict):
        records.extend(dict(item) for item in approvals.values() if isinstance(item, dict))
    records.extend(_metadata_records(metadata, "guardian_approval_queue"))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        key = str(item.get("approval_id") or item.get("gate_key") or item.get("title") or index)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _missing_input_items(state: OrchestratorState) -> list[dict[str, Any]]:
    spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
    objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
    checks = [
        ("operator_goal", "Operator goal", state.active_goal),
        ("specimen_geometry", "Specimen geometry", spec.get("geometry_type") or spec.get("structure_type") or spec.get("specimen_size_mm") or spec.get("size_mm")),
        ("polymer_material", "Polymer / material", spec.get("material") or spec.get("material_family") or spec.get("polymer_grade") or spec.get("polymer")),
        ("objective_type", "Objective type", objective.get("objective_type") or spec.get("objective_type") or spec.get("objective")),
        ("test_protocol", "Test protocol", spec.get("test_protocol") or objective.get("test_protocol")),
    ]
    items: list[dict[str, Any]] = []
    for key, label, value in checks:
        missing = value in (None, "", [], {})
        items.append(
            {
                "key": key,
                "label": label,
                "status": "missing" if missing else "ready",
                "value": "" if missing else value,
                "required": True,
            }
        )
    return items


def _route_state_from_plan(plan: dict[str, Any], state: OrchestratorState) -> dict[str, Any]:
    route = plan.get("route") if isinstance(plan.get("route"), list) else []
    route_steps = [dict(item) for item in route if isinstance(item, dict)]
    completed = [item for item in route_steps if str(item.get("status") or "").lower() in {"complete", "completed", "done", "success"}]
    blocked = [item for item in route_steps if any(token in str(item.get("status") or "").lower() for token in ("block", "fail", "error", "reject"))]
    active = next((item for item in route_steps if any(token in str(item.get("status") or "").lower() for token in ("active", "running", "waiting"))), None)
    if active is None and route_steps:
        active = route_steps[0]
    return {
        "current_stage": plan.get("current_stage") or state.stage.value,
        "next_recommended_stage": plan.get("next_recommended_stage") or (active or {}).get("stage", state.stage.value),
        "route": route_steps,
        "route_count": len(route_steps),
        "completed_count": len(completed),
        "blocked_count": len(blocked),
        "active_stage": (active or {}).get("stage", state.stage.value),
        "progress_ratio": round(len(completed) / max(1, len(route_steps)), 4),
        "parallelizable_check_count": len(plan.get("parallelizable_checks") if isinstance(plan.get("parallelizable_checks"), list) else []),
        "serial_physical_action_count": len(plan.get("serial_physical_actions") if isinstance(plan.get("serial_physical_actions"), list) else []),
    }


def _decision_register_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    decisions = _metadata_records(metadata, "orchestrator_decision_register")
    handoffs = _metadata_records(metadata, "orchestrator_handoff_packets")
    followups = _metadata_records(metadata, "orchestrator_followups")
    blocked = [item for item in decisions if any(token in str(item.get("decision") or item.get("status") or "").lower() for token in ("block", "reject", "fail", "error"))]
    return {
        "decision_count": len(decisions),
        "handoff_count": len(handoffs),
        "followup_count": len(followups),
        "blocked_count": len(blocked),
        "latest_decision": metadata.get("latest_orchestrator_decision") if isinstance(metadata.get("latest_orchestrator_decision"), dict) else (decisions[-1] if decisions else {}),
        "latest_handoff": metadata.get("latest_orchestrator_handoff") if isinstance(metadata.get("latest_orchestrator_handoff"), dict) else (handoffs[-1] if handoffs else {}),
        "items": decisions[-12:],
    }


def _followup_questions_summary(metadata: dict[str, Any], missing_items: list[dict[str, Any]]) -> dict[str, Any]:
    followups = _metadata_records(metadata, "orchestrator_followups")
    operator_queue = _metadata_records(metadata, "operator_followup_queue")
    open_followups = [item for item in followups if item.get("requires_response")]
    synthetic_missing = [
        {
            "schema": "orchestrator_followup_question.v1",
            "source": "missing_input",
            "status": "waiting_operator",
            "question": f"Provide {item['label']}",
            "field": item["key"],
            "priority": "high",
        }
        for item in missing_items
        if item.get("status") == "missing"
    ]
    questions = operator_queue[-10:] + open_followups[-10:] + synthetic_missing
    return {
        "question_count": len(questions),
        "queued_operator_count": len(operator_queue),
        "requires_response_count": len(open_followups) + len(synthetic_missing),
        "status": "waiting_operator" if questions else "clear",
        "items": questions[-12:],
    }


def _approval_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    approvals = _runtime_approval_records(metadata)
    pending = [item for item in approvals if str(item.get("status") or "").lower() in {"pending", "waiting", "waiting_approval", "approval_required"}]
    approved = [item for item in approvals if str(item.get("status") or item.get("decision") or "").lower() in {"approved", "resolved", "allow", "continue"}]
    rejected = [item for item in approvals if any(token in str(item.get("status") or item.get("decision") or "").lower() for token in ("reject", "deny", "block", "safe_stop"))]
    return {
        "approval_count": len(approvals),
        "pending_count": len(pending),
        "approved_count": len(approved),
        "blocked_count": len(rejected),
        "status": "pending" if pending else "clear",
        "items": approvals[-12:],
    }


def _risk_register_summary(state: OrchestratorState, metadata: dict[str, Any], approval: dict[str, Any]) -> dict[str, Any]:
    incidents = _metadata_records(metadata, "incident_records")
    latest_gate = metadata.get("latest_guardian_gate") if isinstance(metadata.get("latest_guardian_gate"), dict) else {}
    latest_decision = metadata.get("latest_guardian_gate_decision") if isinstance(metadata.get("latest_guardian_gate_decision"), dict) else metadata.get("latest_guardian_decision") if isinstance(metadata.get("latest_guardian_decision"), dict) else {}
    risk_items: list[dict[str, Any]] = []
    if latest_gate:
        risk_items.append(
            {
                "source": "guardian_gate",
                "stage": latest_gate.get("stage", state.stage.value),
                "decision": latest_gate.get("decision", latest_decision.get("decision", "")),
                "reason": latest_gate.get("reason_code") or latest_gate.get("reason") or latest_decision.get("reason_code", ""),
                "risk_score": latest_gate.get("risk_score", latest_decision.get("risk_score", 0.0)),
                "status": latest_gate.get("status") or latest_gate.get("decision") or "recorded",
            }
        )
    for incident in incidents[-10:]:
        risk_items.append(
            {
                "source": "incident",
                "stage": incident.get("stage", ""),
                "decision": incident.get("decision", ""),
                "reason": incident.get("reason_code") or incident.get("reason") or incident.get("title", ""),
                "risk_score": incident.get("risk_score", 0.0),
                "status": incident.get("status", "incident"),
            }
        )
    for name, value in (state.device_health or {}).items():
        text = str(value or "")
        if any(token in text.lower() for token in ("warning", "blocked", "failed", "error", "critical")):
            risk_items.append(
                {
                    "source": "device_health",
                    "stage": state.stage.value,
                    "decision": "review",
                    "reason": f"{name}: {text}",
                    "risk_score": 0.45 if "warning" in text.lower() else 0.85,
                    "status": text,
                }
            )
    max_score = 0.0
    for item in risk_items:
        try:
            max_score = max(max_score, float(item.get("risk_score") or 0.0))
        except (TypeError, ValueError):
            continue
    if approval.get("pending_count", 0):
        max_score = max(max_score, 0.35)
    return {
        "risk_count": len(risk_items),
        "incident_count": len(incidents),
        "highest_risk": risk_items[-1]["reason"] if risk_items else "",
        "risk_score": round(max_score, 4),
        "status": "blocked" if any(str(item.get("decision") or "").lower() in {"block", "safe_stop"} for item in risk_items) else "warning" if risk_items else "clear",
        "items": risk_items[-12:],
    }


def _task_queue_from_route(route_state: dict[str, Any]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for item in route_state.get("route", []):
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "")
        status = str(item.get("status") or "pending")
        required_outputs = item.get("required_outputs") if isinstance(item.get("required_outputs"), list) else []
        priority = "high" if status in {"active", "running", "waiting_approval"} else "normal" if status == "pending" else "low"
        tasks.append(
            {
                "order": item.get("order", len(tasks) + 1),
                "task": f"Run {stage or item.get('agent', 'stage')}",
                "stage": stage,
                "agent": item.get("agent", STAGE_AGENT.get(stage, stage)),
                "status": status,
                "priority": priority,
                "required_outputs": required_outputs,
                "required_output_count": len(required_outputs),
                "guardian_pre_gate": item.get("guardian_pre_gate", ""),
                "guardian_post_gate": item.get("guardian_post_gate", ""),
            }
        )
    return {
        "queued_count": sum(1 for item in tasks if item["status"] == "pending"),
        "active_count": sum(1 for item in tasks if item["status"] in {"active", "running", "waiting_approval"}),
        "completed_count": sum(1 for item in tasks if item["status"] in {"complete", "completed", "done", "success"}),
        "blocked_count": sum(1 for item in tasks if any(token in item["status"] for token in ("block", "fail", "error"))),
        "next_agent": (tasks[0]["agent"] if tasks else ""),
        "items": tasks,
    }


def build_orchestrator_control_plane_snapshot(
    *,
    state: OrchestratorState,
    mission_contract: dict[str, Any] | None = None,
    orchestration_plan: dict[str, Any] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Build the ORC Live GUI report contract from current supervisor state."""
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    mission = mission_contract if isinstance(mission_contract, dict) else build_mission_contract(state=state)
    plan = orchestration_plan if isinstance(orchestration_plan, dict) else build_orchestration_plan(state=state)
    missing_items = _missing_input_items(state)
    missing_count = sum(1 for item in missing_items if item["status"] == "missing")
    route_state = _route_state_from_plan(plan, state)
    decision_register = _decision_register_summary(metadata)
    followup_questions = _followup_questions_summary(metadata, missing_items)
    approval = _approval_summary(metadata)
    risk_register = _risk_register_summary(state, metadata, approval)
    task_queue = _task_queue_from_route(route_state)
    next_stage = route_state.get("next_recommended_stage") or state.stage.value
    next_agent = STAGE_AGENT.get(str(next_stage), str(next_stage))
    confidence = 1.0
    if missing_items:
        confidence -= min(0.35, missing_count / max(1, len(missing_items)) * 0.35)
    if approval.get("pending_count", 0):
        confidence -= 0.15
    if risk_register.get("status") in {"warning", "blocked"}:
        confidence -= 0.15 if risk_register.get("status") == "warning" else 0.35
    return {
        "schema": "orchestrator_control_plane.v1",
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "stage": state.stage.value,
        "mission_contract": mission,
        "route_state": route_state,
        "missing_inputs": {
            "missing_count": missing_count,
            "ready_count": len(missing_items) - missing_count,
            "status": "complete" if missing_count == 0 else "missing_required_inputs",
            "items": missing_items,
        },
        "decision_register": decision_register,
        "followup_questions": followup_questions,
        "approval_summary": approval,
        "risk_register": risk_register,
        "task_queue": task_queue,
        "next_action": {
            "next_stage": next_stage,
            "next_agent": next_agent,
            "summary": next_action or f"Continue from {state.stage.value} to {next_stage}.",
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "status": "blocked" if risk_register.get("status") == "blocked" else "waiting_operator" if missing_count or approval.get("pending_count", 0) else "ready",
        },
        "created_at": now_iso(),
    }

def evidence_refs_from_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in refs:
            refs.append(value)

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key).lower()
                if key_text in {"evidence_refs", "artifact_refs", "artifacts"}:
                    for item in as_list(child):
                        if isinstance(item, dict):
                            for ref_key in ("artifact_id", "path", "url", "preview_url", "report_url", "contour_url"):
                                add(item.get(ref_key))
                        else:
                            add(item)
                elif key_text.endswith("_path") or key_text.endswith("_url") or key_text in {"result_file", "stl_path", "gcode_path"}:
                    add(child)
                else:
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for item in value[:20]:
                walk(item, depth + 1)

    walk(payload)
    return refs[:20]



def _artifact_count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_artifact_count(child) for child in value.values())
    if isinstance(value, list):
        return sum(_artifact_count(child) for child in value)
    if isinstance(value, str) and value.strip():
        lowered = value.lower()
        return 1 if any(token in lowered for token in ("artifact://", ".stl", ".gcode", ".json", ".csv", ".png", ".svg")) else 0
    return 0


def build_orchestrator_parallel_check(
    *,
    state: OrchestratorState,
    check_id: str,
    plan_id: str = "",
) -> dict[str, Any]:
    """Run one deterministic read-only supervisor planning check."""
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    evidence_refs: list[str] = []
    status = "ok"
    summary = "check completed"
    details: dict[str, Any] = {}

    if check_id == "knowledge.retrieve_prior_failures":
        failures = metadata.get("failure_patterns") if isinstance(metadata.get("failure_patterns"), list) else []
        incidents = metadata.get("incident_records") if isinstance(metadata.get("incident_records"), list) else []
        knowledge = metadata.get("knowledge_context") if isinstance(metadata.get("knowledge_context"), dict) else {}
        failure_count = len(failures) + len(incidents)
        details = {
            "failure_pattern_count": len(failures),
            "incident_count": len(incidents),
            "knowledge_context_available": bool(knowledge),
        }
        summary = f"{failure_count} prior failure/incident records available for routing context."
        status = "ok" if failure_count or knowledge else "missing"
    elif check_id == "analysis.lookup_fem_cache":
        analysis = metadata.get("analysis") if isinstance(metadata.get("analysis"), dict) else {}
        artifacts = analysis.get("analysis_artifacts") if isinstance(analysis.get("analysis_artifacts"), dict) else {}
        fem_loop = analysis.get("fem_agentic_loop") if isinstance(analysis.get("fem_agentic_loop"), dict) else {}
        cache_refs = [
            str(artifacts.get("fem_cache_manifest") or ""),
            str(artifacts.get("fem_result") or ""),
            str(fem_loop.get("cache_status") or ""),
        ]
        cache_refs = [item for item in cache_refs if item.strip()]
        evidence_refs.extend(cache_refs[:4])
        details = {"cache_refs": cache_refs, "fem_loop_status": fem_loop.get("status", "")}
        summary = "FEM cache/reference lookup completed."
        status = "ok" if cache_refs else "missing"
    elif check_id == "guardian.preflight_devices":
        health = dict(state.device_health or {})
        blocking = {key: value for key, value in health.items() if str(value).lower().startswith(("blocking", "critical", "failed", "error"))}
        warning = {key: value for key, value in health.items() if str(value).lower().startswith("warning")}
        details = {"device_health": health, "blocking": blocking, "warning": warning}
        if blocking:
            status = "blocked"
            summary = f"{len(blocking)} blocking device health item(s) detected."
        elif warning:
            status = "warning"
            summary = f"{len(warning)} warning device health item(s) detected."
        else:
            summary = "No blocking device health state detected."
    elif check_id == "bo.constraint_sanity_check":
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        bo = metadata.get("bo_result") if isinstance(metadata.get("bo_result"), dict) else {}
        recommendation = bo.get("recommendation") if isinstance(bo.get("recommendation"), dict) else {}
        required = ["geometry_type", "specimen_size_mm", "cell_size_mm", "wall_thickness_mm"]
        missing = [field for field in required if not spec.get(field) and not recommendation.get(field)]
        details = {"missing_fields": missing, "has_bo_recommendation": bool(recommendation)}
        status = "ok" if not missing else "warning"
        summary = "BO/design constraint sanity check completed." if not missing else f"Missing optional/required design fields: {', '.join(missing)}"
    elif check_id == "artifacts.lookup_existing_outputs":
        artifact_refs = evidence_refs_from_payload(metadata)
        artifact_total = _artifact_count(metadata)
        evidence_refs.extend(artifact_refs[:10])
        details = {"artifact_ref_count": len(artifact_refs), "artifact_like_value_count": artifact_total}
        status = "ok" if artifact_refs or artifact_total else "missing"
        summary = f"Found {len(artifact_refs)} explicit evidence refs and {artifact_total} artifact-like values."
    elif check_id == "runtime.compare_previous_loop":
        evaluations = state.experiment_evaluations if isinstance(state.experiment_evaluations, list) else []
        previous = evaluations[-1] if evaluations else {}
        details = {
            "evaluation_count": len(evaluations),
            "previous_objective_score": previous.get("objective_score") if isinstance(previous, dict) else None,
            "loop_count": state.loop_count,
        }
        status = "ok" if evaluations or state.loop_count == 0 else "missing"
        summary = "Previous loop comparison context available." if evaluations else "No previous loop evaluation yet."
    else:
        status = "warning"
        details = {"unknown_check_id": check_id}
        summary = "Unknown supervisor check id; recorded without execution."

    seed = {"run_id": state.run_id, "loop_id": state.loop_count, "plan_id": plan_id, "check_id": check_id, "status": status}
    return {
        "schema": "orchestrator_parallel_check.v1",
        "check_id": stable_id("orch-check", seed),
        "name": check_id,
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "plan_id": plan_id,
        "status": status,
        "read_only": True,
        "summary": summary,
        "details": details,
        "evidence_refs": evidence_refs,
        "created_at": now_iso(),
    }


def build_orchestrator_parallel_check_batch(
    *,
    state: OrchestratorState,
    plan: dict[str, Any],
    checks: list[dict[str, Any]],
    stage: Stage | str | None = None,
) -> dict[str, Any]:
    """Package read-only supervisor checks executed for one compiled plan."""
    clean_checks = [item for item in checks if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    for item in clean_checks:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    blocking = status_counts.get("blocked", 0)
    warnings = status_counts.get("warning", 0)
    batch_status = "blocked" if blocking else "warning" if warnings else "ok"
    seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "plan_id": plan.get("plan_id", ""),
        "stage": stage_value(stage) or stage_value(state.stage),
        "count": len(clean_checks),
    }
    return {
        "schema": "orchestrator_parallel_checks.v1",
        "batch_id": stable_id("orch-checks", seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "plan_id": plan.get("plan_id", ""),
        "stage": stage_value(stage) or stage_value(state.stage),
        "status": batch_status,
        "execution_mode": "asyncio.gather/read_only",
        "check_count": len(clean_checks),
        "status_counts": status_counts,
        "checks": clean_checks,
        "created_at": now_iso(),
    }

def normalize_operator_intent(message: str) -> dict[str, Any]:
    """Extract a deterministic operator intent before any LLM fallback."""
    raw = str(message or "")
    compact = re.sub(r"\s+", "", raw.lower())
    intent = "ask_question"
    confidence = 0.45
    triggers: list[str] = []

    def hit(name: str, patterns: tuple[str, ...], new_intent: str, score: float) -> bool:
        nonlocal intent, confidence
        if any(pattern in compact for pattern in patterns):
            intent = new_intent
            confidence = max(confidence, score)
            triggers.append(name)
            return True
        return False

    hit("stop", ("중지", "정지", "멈춰", "stop", "safestop", "safe_stop"), "stop", 0.9)
    hit("pause", ("일시정지", "pause"), "pause", 0.82)
    hit("resume", ("재개", "resume", "계속"), "resume", 0.78)
    hit("status", ("상태", "status", "어디까지", "진행상황"), "request_status", 0.72)
    hit("printer_option", ("가상브릿지", "설치프린터", "실제출력"), "select_option", 0.9)
    if hit("test_mode", ("테스트모드", "testmode"), "start_dry_run", 0.92):
        if any(pattern in compact for pattern in ("실제출력", "설치프린터", "가상브릿지")):
            intent = "start_dry_run"
            triggers.append("test_mode_printer_path")
    hit("live_execute", ("실험수행", "실험진행", "설계수행", "디자인수행", "runexperiment", "startexperiment"), "start_live_run", 0.95)
    if intent == "ask_question" and any(token in compact for token in ("크기", "재료", "pla", "abs", "목표", "조건", "사이즈", "gyroid", "tpms")):
        intent = "set_constraint"
        confidence = 0.62
        triggers.append("constraint_terms")

    return {
        "schema": "operator_intent.v1",
        "intent": intent,
        "confidence": round(confidence, 4),
        "triggers": triggers,
        "requires_design_handoff": intent in {"start_live_run", "start_dry_run"},
        "created_at": now_iso(),
    }


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _status_from_payload(stage: str, payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    candidates = [
        payload.get("status"),
        payload.get("handoff_status"),
        payload.get("completion_status"),
    ]
    nested_keys = {
        Stage.SPECIMEN.value: ("specimen_fabricated", "specimen_result", "fabrication_report"),
        Stage.VISION.value: ("vision_signal", "observation", "vision_report"),
        Stage.MANIPULATION.value: ("robot_task_result", "manipulation_report", "manipulation"),
        Stage.EQUIPMENT.value: ("utm_data_ready", "equipment_result", "equipment_report"),
        Stage.ANALYSIS.value: ("analysis", "handoff_packet"),
        Stage.KNOWLEDGE.value: ("knowledge", "knowledge_context"),
        Stage.BO.value: ("bo_result", "next_design_request"),
        Stage.GUARDIAN.value: ("guardian", "guardian_gate"),
    }.get(stage, ("handoff_packet",))
    for key in nested_keys:
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.extend([nested.get("status"), nested.get("decision"), nested.get("handoff_status")])
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return "ready" if payload else "unknown"


def _confidence_from_payload(stage: str, payload: dict[str, Any]) -> float:
    paths = [
        ("confidence",),
        ("metrics", "confidence"),
        ("vision_signal", "confidence"),
        ("observation", "transfer_readiness", "pose_confidence"),
        ("analysis", "data_quality", "confidence"),
        ("analysis", "uncertainty"),
        ("bo_result", "recommendation", "combined_score"),
    ]
    for path in paths:
        value: Any = payload
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, (int, float)):
            if path[-1] == "uncertainty":
                return max(0.0, min(1.0, 1.0 - float(value)))
            return max(0.0, min(1.0, float(value)))
    return 0.82 if _status_from_payload(stage, payload) in {"ready", "done", "continue", "allow"} else 0.64


def build_orchestrator_followup(
    *,
    state: OrchestratorState,
    stage: Stage | str,
    trigger: str,
    payload: dict[str, Any] | None = None,
    next_stage: Stage | str | None = None,
    guardian_context: dict[str, Any] | None = None,
    requires_response: bool | None = None,
) -> dict[str, Any]:
    """Create an operator-facing Orchestrator follow-up record."""
    data = payload if isinstance(payload, dict) else {}
    stage_text = stage_value(stage)
    next_stage_text = stage_value(next_stage)
    status = _status_from_payload(stage_text, data)
    confidence = _confidence_from_payload(stage_text, data)
    evidence_refs = evidence_refs_from_payload(data)
    concerns: list[str] = []
    recommendation = f"{next_stage_text or 'next stage'} handoff를 준비합니다."
    opinion = f"{stage_text} stage 결과를 확인했고 status={status}로 판단했습니다."
    options: list[dict[str, Any]] = []

    if trigger == "operator_followup":
        operator_followup = _first_dict(data.get("operator_followup"))
        target_agent = str(operator_followup.get("target_agent") or "orchestrator")
        chat_mode = str(operator_followup.get("chat_mode") or "ask")
        message = str(operator_followup.get("message") or "").strip()
        excerpt = message[:120] + ("..." if len(message) > 120 else "")
        opinion = f"Operator follow-up을 {stage_text} stage boundary에서 수신했습니다. target={target_agent}, mode={chat_mode}."
        recommendation = "현재 물리 동작은 중단하지 않고, 이 입력을 다음 agent context와 Guardian/BO 판단 근거에 포함합니다."
        evidence_refs = [*evidence_refs, operator_followup.get("followup_id") or "operator_followup"]
        options = [
            {"id": "continue_with_context", "label": "현재 loop 유지", "risk": "low"},
            {"id": "pause_if_safety_relevant", "label": "안전 관련이면 pause/safe-stop 검토", "risk": "medium"},
        ]
        if excerpt:
            concerns.append(f"operator_note={excerpt}")
    elif stage_text == Stage.DESIGN.value:
        candidate = _first_dict(data.get("design_candidate"), data.get("handoff_packet"))
        design_handoff = _first_dict(_first_dict(data.get("design_report")).get("handoff_to_specimen"))
        missing = as_list(design_handoff.get("missing_required_fields"))
        opinion = f"Design 후보 {candidate.get('specimen_id') or candidate.get('candidate_id') or 'candidate'}를 Specimen handoff 기준으로 점검했습니다."
        if missing:
            concerns.append(f"missing_required_fields={missing}")
            recommendation = "누락값을 operator에게 되묻고 Specimen Agent handoff를 보류합니다."
        else:
            recommendation = "제조 digital thread 생성을 위해 Specimen Making Agent로 넘깁니다."
    elif stage_text == Stage.SPECIMEN.value:
        specimen = _first_dict(data.get("specimen_fabricated"), data.get("handoff_packet"), data.get("specimen_result"))
        fabrication_intent = _first_dict(_first_dict(data.get("fabrication_report")).get("fabrication_intent"))
        physical = bool(fabrication_intent.get("physical_intent"))
        opinion = f"Specimen digital thread를 확인했습니다. fabrication_status={status}, physical_intent={physical}."
        recommendation = "Vision Agent가 bed/basket/fixture 상태를 확인한 뒤 다음 물리 단계로 넘깁니다."
        if specimen.get("requires_operator_input"):
            concerns.append("specimen_operator_input_required")
            recommendation = "프린터 경로 선택 또는 연결정보 입력 전까지 workflow를 보류합니다."
    elif stage_text == Stage.VISION.value:
        observation = _first_dict(data.get("observation"))
        signal = _first_dict(data.get("vision_signal"), observation.get("vision_signal"))
        expires_at = signal.get("expires_at")
        opinion = f"Vision signal confidence={confidence:.2f}로 perception handoff를 평가했습니다."
        recommendation = "signal freshness가 유효하면 Manipulation/Equipment precondition으로 사용합니다."
        if confidence < 0.75:
            concerns.append("vision_confidence_below_preferred_live_threshold")
            recommendation = "추가 촬영 또는 Guardian pre_manipulation gate를 먼저 권장합니다."
        if not expires_at:
            concerns.append("vision_signal_expiry_missing")
    elif stage_text == Stage.MANIPULATION.value:
        robot = _first_dict(data.get("robot_task_result"), data.get("manipulation"))
        opinion = f"Manipulation short-task 결과를 확인했습니다. completion={robot.get('completion_status') or status}."
        recommendation = "Vision verification과 SARM/recovery hint를 확인한 뒤 Equipment Agent로 넘깁니다."
        if str(robot.get("handoff_status") or "").lower() in {"blocked", "warning"}:
            concerns.append(str(robot.get("reason") or "manipulation_handoff_not_clean"))
    elif stage_text == Stage.EQUIPMENT.value:
        equipment = _first_dict(data.get("equipment_result"), data.get("utm_data_ready"), data.get("equipment_handoff"))
        result_file = equipment.get("result_file") or equipment.get("utm_csv_path")
        opinion = f"Lab Equipment 실행과 UTM 데이터 handoff를 점검했습니다. status={status}."
        recommendation = "결과 파일과 screen/physical/data cross-check가 모두 확인되면 Analysis Agent로 넘깁니다."
        if not result_file and status not in {"ready", "done"}:
            concerns.append("utm_result_file_missing_or_not_ready")
            recommendation = "Analysis로 넘기기 전에 Equipment save/export recovery를 먼저 수행합니다."
    elif stage_text == Stage.ANALYSIS.value:
        analysis = _first_dict(data.get("analysis"))
        uncertainty = analysis.get("uncertainty")
        opinion = f"Analysis 결과를 BO observation 후보로 평가했습니다. objective_score={analysis.get('objective_score', 'n/a')}."
        recommendation = "실험 observation과 FEM prediction/residual을 분리해 BO Agent로 넘깁니다."
        if isinstance(uncertainty, (int, float)) and float(uncertainty) > 0.35:
            concerns.append("analysis_uncertainty_high")
    elif stage_text == Stage.KNOWLEDGE.value:
        knowledge = _first_dict(data.get("knowledge"))
        opinion = f"Knowledge memory와 self-evolution evidence pack 갱신 상태를 확인했습니다."
        recommendation = "성공/실패/incident 근거를 다음 BO 및 loop reflection에 반영합니다."
        if not knowledge.get("retrieval_coverage"):
            concerns.append("knowledge_retrieval_coverage_not_reported")
    elif stage_text == Stage.BO.value:
        bo = _first_dict(data.get("bo_result"))
        rec = _first_dict(bo.get("recommendation"))
        opinion = f"BO 후보 {rec.get('candidate_id') or 'next candidate'}의 acquisition/uncertainty trade-off를 확인했습니다."
        recommendation = "Guardian 제약 검토 후 다음 Design cycle 후보로 채택합니다."
        if rec.get("risk") in {"high", "blocked"}:
            concerns.append("bo_candidate_risk_high")
            options = [
                {"id": "accept_with_guardian", "label": "Guardian gate 후 진행", "risk": "medium"},
                {"id": "use_second_best", "label": "second-best 후보 사용", "risk": "lower"},
            ]
    elif stage_text == Stage.GUARDIAN.value:
        guardian = _first_dict(data.get("guardian"), data.get("guardian_gate"), guardian_context)
        decision = str(guardian.get("decision") or status or "continue")
        opinion = f"Guardian decision={decision}를 workflow 관점에서 해석했습니다."
        recommendation = "block/safe_stop이면 recovery 또는 operator approval로 라우팅하고, continue면 다음 loop로 넘깁니다."
        if decision in {"stop", "block", "safe_stop", "require_human_approval"}:
            concerns.append(f"guardian_{decision}")
            requires_response = decision == "require_human_approval"

    if guardian_context and str(guardian_context.get("decision") or "") in {"block", "safe_stop", "require_human_approval"}:
        concerns.append(f"guardian_gate={guardian_context.get('decision')}")
        requires_response = bool(requires_response or guardian_context.get("decision") == "require_human_approval")

    followup_seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "stage": stage_text,
        "trigger": trigger,
        "status": status,
        "next_stage": next_stage_text,
        "evidence_refs": evidence_refs[:5],
    }
    followup = {
        "schema": "orchestrator_followup.v1",
        "followup_id": stable_id("ofup", followup_seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "stage": stage_text,
        "trigger": trigger,
        "opinion": opinion,
        "confidence": round(confidence, 4),
        "evidence_refs": evidence_refs,
        "concerns": concerns,
        "recommendation": recommendation,
        "options": options,
        "question_to_operator": "승인 또는 대안 선택이 필요합니다." if requires_response else None,
        "requires_response": bool(requires_response),
        "next_agent": STAGE_AGENT.get(next_stage_text, next_stage_text),
        "status": "warning" if concerns else "ok",
        "created_at": now_iso(),
    }
    if trigger == "operator_followup" and isinstance(data.get("operator_followup"), dict):
        followup["operator_followup"] = {
            key: data["operator_followup"].get(key)
            for key in ("followup_id", "message", "target_agent", "chat_mode", "stage_at_submit", "consumed_stage", "created_at", "consumed_at")
            if key in data["operator_followup"]
        }
    return followup


def build_decision_record(
    *,
    state: OrchestratorState,
    stage: Stage | str,
    decision: str,
    selected: Any = None,
    alternatives: list[Any] | None = None,
    reason: str = "",
    authority: str = "orchestrator",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    stage_text = stage_value(stage)
    seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "stage": stage_text,
        "decision": decision,
        "selected": selected,
    }
    return {
        "schema": "decision_register.v1",
        "decision_id": stable_id("dec", seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "stage": stage_text,
        "decision": decision,
        "selected": selected,
        "alternatives": alternatives or [],
        "reason": reason or "Orchestrator supervisor decision recorded from runtime state.",
        "authority": authority,
        "evidence_refs": evidence_refs or [],
        "created_at": now_iso(),
    }


def build_orchestrator_handoff_packet(
    *,
    state: OrchestratorState,
    from_stage: Stage | str,
    to_stage: Stage | str,
    result_payload: dict[str, Any] | None = None,
    selected_transition: dict[str, Any] | None = None,
    guardian_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from_text = stage_value(from_stage)
    to_text = stage_value(to_stage)
    payload = result_payload if isinstance(result_payload, dict) else {}
    source_packet = _first_dict(payload.get("handoff_packet"), payload.get("design_candidate"), payload.get("vision_signal"), payload.get("utm_data_ready"))
    evidence_refs = evidence_refs_from_payload(payload)
    packet_seed = {
        "run_id": state.run_id,
        "loop_id": state.loop_count,
        "from_stage": from_text,
        "to_stage": to_text,
        "source_schema": source_packet.get("schema"),
    }
    return {
        "schema": "handoff_packet.v1",
        "packet_id": stable_id("orch-handoff", packet_seed),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "producer_agent": "orchestrator_agent",
        "consumer_agent": STAGE_AGENT.get(to_text, to_text),
        "from_stage": from_text,
        "to_stage": to_text,
        "task": f"{from_text}_to_{to_text}",
        "objective": state.active_goal,
        "inputs": {
            "source_packet_schema": source_packet.get("schema", ""),
            "source_packet_id": source_packet.get("packet_id") or source_packet.get("signal_id") or source_packet.get("specimen_id") or "",
            "current_specimen_id": state.current_experiment_spec.get("specimen_id") if isinstance(state.current_experiment_spec, dict) else "",
            "selected_transition": selected_transition or {},
        },
        "required_outputs": REQUIRED_OUTPUTS.get(to_text, []),
        "guardian_preconditions": [
            "guardian.pre_gate.allow_or_warning",
            "required_evidence_refs.present",
            "stage_input_schema.valid",
        ],
        "guardian_status": str((guardian_context or {}).get("decision") or "not_checked"),
        "decisions": [],
        "warnings": [],
        "evidence_refs": evidence_refs,
        "next_action": f"Run {STAGE_AGENT.get(to_text, to_text)}" if to_text not in {Stage.COMPLETE.value, Stage.ERROR.value} else to_text,
        "created_at": now_iso(),
    }


def build_loop_reflection(
    *,
    state: OrchestratorState,
    guardian_payload: dict[str, Any] | None = None,
    next_stage: Stage | str | None = None,
) -> dict[str, Any]:
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    followups = [item for item in metadata.get("orchestrator_followups", []) if isinstance(item, dict)]
    decisions = [item for item in metadata.get("orchestrator_decision_register", []) if isinstance(item, dict)]
    incidents = [item for item in metadata.get("incident_records", []) if isinstance(item, dict)]
    guardian = guardian_payload if isinstance(guardian_payload, dict) else metadata.get("guardian", {}) if isinstance(metadata.get("guardian"), dict) else {}
    decision = str(guardian.get("decision") or "continue")
    concerns = []
    for followup in followups[-8:]:
        concerns.extend(str(item) for item in as_list(followup.get("concerns")) if str(item).strip())
    what_worked = [
        "stage handoffs recorded" if metadata.get("handoff_packets") or metadata.get("orchestrator_handoff_packets") else "stage execution completed",
        "guardian reviewed loop" if guardian else "guardian context pending",
    ]
    if not incidents:
        what_worked.append("no incident records in current loop metadata")
    return {
        "schema": "loop_reflection.v1",
        "reflection_id": stable_id(
            "loop-reflection",
            {"run_id": state.run_id, "loop_id": state.loop_count, "decision": decision, "next_stage": stage_value(next_stage)},
        ),
        "run_id": state.run_id,
        "experiment_id": state.experiment_id,
        "loop_id": state.loop_count,
        "guardian_decision": decision,
        "what_worked": what_worked,
        "what_failed_or_nearly_failed": sorted(set(concerns))[:10],
        "operator_visible_summary": (
            f"Loop {state.loop_count} finished with Guardian decision={decision}. "
            f"{len(decisions)} supervisor decisions and {len(followups)} follow-ups are recorded."
        ),
        "next_loop_recommendation": (
            "다음 Design cycle로 진행합니다." if stage_value(next_stage) == Stage.DESIGN.value else
            "작업을 완료 상태로 정리합니다." if stage_value(next_stage) == Stage.COMPLETE.value else
            f"{stage_value(next_stage) or 'next stage'} 상태를 확인합니다."
        ),
        "knowledge_updates": [
            "store_orchestrator_followups",
            "store_decision_register",
            "store_incident_context" if incidents else "store_no_incident_context",
        ],
        "self_evolution_candidates": [
            {"target_id": "orchestrator_agent", "reason": "follow-up concerns accumulated", "concern_count": len(concerns)}
        ] if len(concerns) >= 3 else [],
        "created_at": now_iso(),
    }
