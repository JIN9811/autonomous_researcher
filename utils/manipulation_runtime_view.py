"""Build the source-backed Manipulation Agent runtime view used by Live GUI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RUNTIME_VIEW_SCHEMA = "manipulation_runtime_view.v1"
COMPLETION_STEP_IDS = (
    "ungrasping_seen",
    "home_after_ungrasping",
    "utm_snapshot_requested",
    "specimen_detected_at_utm",
    "ready_to_stop_rollout",
    "rollout_stop_confirmed",
    "ready_for_equipment",
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _status(value: Any) -> str:
    clean = str(value or "").strip().upper()
    if clean in {"COMPLETED", "COMPLETE", "SUCCESS", "SUCCEEDED"}:
        return "complete"
    if clean in {"FAILED", "ERROR"}:
        return "failed"
    if clean in {"BLOCKED"}:
        return "blocked"
    if clean in {"CANCELLED", "CANCELED"}:
        return "cancelled"
    if clean in {"STOPPING"}:
        return "stopping"
    if clean in {"VERIFYING", "NEEDS_POST_PLACE_VISION", "AWAITING_POST_PLACE_HOME"}:
        return "verifying"
    if clean in {
        "POLICY_ACTIVE",
        "RUNNING",
        "ACTIVE",
        "ACTION_ACTIVE",
        "RECORDING",
        "TELEOP_ACTIVE",
        "STARTING",
    }:
        return "running"
    if clean in {"PREFLIGHT", "READY", "WARN", "WARNING"}:
        return "preflight"
    return "not_started"


def _gate_status(value: Any, *, false_status: str = "waiting") -> str:
    if value is True:
        return "pass"
    if value is False:
        return false_status
    clean = str(value or "").strip().lower()
    if clean in {
        "pass",
        "passed",
        "ready",
        "ok",
        "active",
        "policy_active",
        "action_active",
        "running",
        "leased",
        "available",
        "stopped",
    }:
        return "pass"
    if clean in {"block", "blocked", "failed", "error", "conflict", "unavailable"}:
        return "block"
    if clean in {"waiting", "pending", "starting", "stopping", "unknown"}:
        return clean if clean in {"waiting", "unknown"} else "waiting"
    return "unknown"


def _gate(
    gate_id: str,
    status: str,
    source_type: str,
    source: str,
    *,
    reason: str = "",
    observed_at: str = "",
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "status": status,
        "source_type": source_type,
        "source": source,
        "observed_at": observed_at,
        "reason": reason,
    }


def _metric_counts(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    value = _dict(raw)
    attempts = max(0, int(value.get("attempt_count") or 0))
    completed = max(0, int(value.get("completed_count") or 0))
    success_raw = value.get("success_count") if value.get("success_count") is not None else completed
    pending_raw = value.get("pending_count") if value.get("pending_count") is not None else attempts - completed
    success = max(0, int(success_raw))
    failed = max(0, int(value.get("failed_count") or 0))
    pending = max(0, int(pending_raw))
    rate = value.get("success_rate")
    if rate is None and attempts:
        rate = completed / attempts
    return {
        "attempt_count": attempts,
        "completed_count": completed,
        "success_count": success,
        "failed_count": failed,
        "pending_count": pending,
        "success_rate": float(rate) if rate is not None else None,
    }


def _completion_step(step_id: str, passed: Any, *, source: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    detail = _dict(details)
    return {
        "id": step_id,
        "status": "pass" if passed is True else "failed" if detail.get("failed") else "waiting",
        "source_type": "MEASURED" if step_id in {"ungrasping_seen", "home_after_ungrasping"} else "EVENT",
        "source": source,
        "sequence": detail.get("sequence"),
        "event_id": str(detail.get("event_id") or ""),
        "observed_at": str(detail.get("observed_at") or detail.get("timestamp") or ""),
        "camera_key": str(detail.get("camera_key") or ""),
        "confidence": detail.get("confidence"),
        "evidence_path": str(detail.get("evidence_path") or detail.get("path") or ""),
        "reason": str(detail.get("reason") or ""),
    }


def build_manipulation_runtime_view(
    *,
    session: Mapping[str, Any] | None,
    state: Mapping[str, Any] | None,
    packet: Mapping[str, Any] | None,
    artifacts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a fixed runtime schema without acquiring or controlling hardware."""

    session_data = _dict(session)
    state_data = _dict(state)
    metadata = _dict(state_data.get("run_metadata"))
    manipulation = _dict(metadata.get("manipulation_report"))
    robot_result = _dict(metadata.get("robot_task_result"))
    task = _dict(manipulation.get("task"))
    policy = _dict(manipulation.get("policy_plan"))
    rollout = _dict(manipulation.get("rollout_runtime"))
    policy_runtime = _dict(rollout.get("policy_runtime"))
    stage_machine = _dict(_first(manipulation.get("stage_machine"), robot_result.get("stage_machine"), default={}))
    preflight = _dict(_first(manipulation.get("preflight"), robot_result.get("preflight"), default={}))
    vision = _dict(manipulation.get("vision_context"))
    vision_completion = _dict(vision.get("manipulation_completion"))
    post_place = _dict(_first(robot_result.get("post_place_interlock"), manipulation.get("post_place_interlock"), default={}))
    completion_signal = _dict(
        _first(
            robot_result.get("completion_signal_identity"),
            vision.get("completion_signal_identity"),
            vision_completion,
            default={},
        )
    )
    rollout_stop = _dict(_first(robot_result.get("rollout_stop"), manipulation.get("rollout_stop"), default={}))
    port_lease = _dict(manipulation.get("port_lease"))
    camera_lease = _dict(manipulation.get("active_camera_lease"))
    packet_data = _dict(packet)
    motion = _dict(packet_data.get("motion_state"))
    measured = _dict(motion.get("measured"))
    home_gate = _dict(measured.get("home_gate"))
    task_cycle_raw = _dict(motion.get("task_cycle"))
    artifact_data = _dict(artifacts)

    raw_status = _first(session_data.get("status"), rollout.get("status"), robot_result.get("status"))
    status = _status(raw_status)
    if status == "not_started" and manipulation:
        status = _status(_first(robot_result.get("completion_status"), preflight.get("status")))

    execution = {
        "run_id": str(_first(manipulation.get("run_id"), robot_result.get("run_id"), state_data.get("run_id"))),
        "rollout_session_id": str(
            _first(session_data.get("session_id"), rollout.get("session_id"), manipulation.get("session_id"), robot_result.get("rollout_session_id"))
        ),
        "task_id": str(_first(task.get("task_id"), robot_result.get("task_id"))),
        "task_instruction": str(_first(task.get("canonical_instruction"), session_data.get("task"))),
        "specimen_id": str(_first(task.get("specimen_id"), robot_result.get("specimen_id"))),
        "source_location": str(task.get("source_location") or ""),
        "target_location": str(_first(task.get("target_location"), robot_result.get("location_after"))),
        "policy_type": str(_first(session_data.get("policy_type"), policy.get("policy_type"), policy_runtime.get("policy_type"))),
        "policy_checkpoint_path": str(
            _first(
                session_data.get("policy_checkpoint_path"),
                session_data.get("policy_path"),
                policy.get("policy_ref"),
                policy_runtime.get("policy_ref"),
            )
        ),
        "process_pid": _first(session_data.get("pid"), policy_runtime.get("pid"), rollout.get("pid"), default=None),
        "runtime_status": str(_first(session_data.get("status"), policy_runtime.get("status"), rollout.get("status"), default="not_started")),
        "current_stage": str(_first(stage_machine.get("current_stage"), state_data.get("stage"), default="not_started")),
        "started_at": str(_first(session_data.get("created_at"), rollout.get("started_at"))),
        "elapsed_s": float(_first(packet_data.get("elapsed_s"), rollout.get("duration_s"), default=0.0) or 0.0),
    }

    port_value = _first(port_lease.get("status"), port_lease.get("current_availability"))
    policy_value = _first(policy_runtime.get("status"), rollout.get("status"), session_data.get("status"))
    interlocks = [
        _gate("follower_port_lease", _gate_status(port_value), "MEASURED", "manipulation_report.port_lease", reason=str(port_lease.get("conflict_reason") or "")),
        _gate("camera_lease", _gate_status(camera_lease.get("returned_to_vla")), "MEASURED", "manipulation_report.active_camera_lease.returned_to_vla", reason=str(camera_lease.get("conflict_reason") or "")),
        _gate("policy_process", _gate_status(policy_value), "MEASURED", "rollout_runtime.policy_runtime.status"),
        _gate("measured_home", _gate_status(home_gate.get("passed")), "DERIVED", "joint_telemetry.motion_state.measured.home_gate"),
        _gate(
            "emergency_stop",
            _gate_status(not state_data.get("emergency_stop_requested"), false_status="block")
            if "emergency_stop_requested" in state_data
            else "unknown",
            "EVENT",
            "orchestrator_state.emergency_stop_requested",
        ),
        _gate(
            "safe_stop",
            _gate_status(not state_data.get("safe_stop_requested"), false_status="block")
            if "safe_stop_requested" in state_data
            else "unknown",
            "EVENT",
            "orchestrator_state.safe_stop_requested",
        ),
        _gate("vision_pickup", _gate_status(vision.get("pickup_target_ready")), "MEASURED", "manipulation_report.vision_context.pickup_target_ready"),
        _gate("workspace_clear", _gate_status(preflight.get("workspace_clear")), "MEASURED", "manipulation_report.preflight.workspace_clear"),
    ]

    stop_confirmed = bool(rollout_stop.get("ok")) or str(rollout_stop.get("status") or "").upper() in {"STOPPED", "COMPLETED"}
    ready_for_equipment = str(_first(robot_result.get("handoff_status"), manipulation.get("decision", {}).get("handoff_status") if isinstance(manipulation.get("decision"), Mapping) else "")).lower() == "ready_for_equipment"
    latest_sequence = post_place.get("latest_sequence") or packet_data.get("sequence")
    measured_detail = {"sequence": latest_sequence}
    completion_steps = [
        _completion_step("ungrasping_seen", post_place.get("ungrasping_seen"), source="post_place_interlock.ungrasping_seen", details=measured_detail),
        _completion_step("home_after_ungrasping", post_place.get("home_after_ungrasping"), source="post_place_interlock.home_after_ungrasping", details=measured_detail),
        _completion_step("utm_snapshot_requested", completion_signal.get("requested") or post_place.get("ready_for_utm_snapshot"), source="vision.completion_signal.requested", details=completion_signal),
        _completion_step("specimen_detected_at_utm", completion_signal.get("detected"), source="vision.completion_signal.detected", details=completion_signal),
        _completion_step("ready_to_stop_rollout", completion_signal.get("ready_to_stop_rollout"), source="vision.completion_signal.ready_to_stop_rollout", details=completion_signal),
        _completion_step("rollout_stop_confirmed", stop_confirmed, source="manipulation_report.rollout_stop", details=rollout_stop),
        _completion_step("ready_for_equipment", ready_for_equipment, source="robot_task_result.handoff_status", details=robot_result),
    ]
    first_waiting = next((step["id"] for step in completion_steps if step["status"] != "pass"), "complete")
    terminal_completion = bool(completion_steps) and all(step["status"] == "pass" for step in completion_steps)

    evidence_refs = robot_result.get("evidence_refs") if isinstance(robot_result.get("evidence_refs"), list) else []
    artifact_directory = ""
    for evidence in evidence_refs:
        if isinstance(evidence, Mapping) and evidence.get("type") == "run_dir" and evidence.get("path"):
            artifact_directory = str(evidence["path"])
            break
    terminal_reason = str(
        _first(
            robot_result.get("failure_code"),
            robot_result.get("reason"),
            _dict(manipulation.get("decision")).get("reason"),
        )
    )
    result_status = str(_first(robot_result.get("status"), status, default="not_started")).lower()
    if result_status == "warning" and status == "complete":
        result_status = "complete"
    result = {
        "status": result_status,
        "terminal": status in {"complete", "failed", "blocked", "cancelled"},
        "failure_stage": str(stage_machine.get("blocked_stage") or ""),
        "reason": terminal_reason,
        "failure_code": str(robot_result.get("failure_code") or ""),
        "rollout_stop_status": str(_first(rollout_stop.get("status"), "pass" if stop_confirmed else "waiting")),
        "vision_verification_status": "pass" if completion_signal.get("detected") is True else "waiting",
        "home_return_status": "pass" if post_place.get("home_after_ungrasping") is True else "waiting",
        "next_agent": str(_first(robot_result.get("next_action"), _dict(manipulation.get("decision")).get("recommended_next_agent"))),
        "artifact_directory": artifact_directory,
    }

    task_metrics = _metric_counts(task_cycle_raw)
    task_metrics["state"] = str(task_cycle_raw.get("state") or "not_started")
    task_metrics["current_task_index"] = int(task_cycle_raw.get("current_task_index") or 0)
    task_metrics["milestones"] = _dict(task_cycle_raw.get("milestones"))
    grasp_metrics = _metric_counts(_dict(task_cycle_raw.get("grasp")))
    sample_count = int(_first(artifact_data.get("sample_count"), packet_data.get("sequence"), default=0) or 0)
    duration_s = float(_first(artifact_data.get("duration_s"), packet_data.get("elapsed_s"), rollout.get("duration_s"), default=0.0) or 0.0)
    metrics = {
        "task_cycle": task_metrics,
        "grasp": grasp_metrics,
        "sample_count": sample_count,
        "duration_s": duration_s,
        "effective_action_rate_hz": sample_count / duration_s if sample_count and duration_s > 0 else None,
        "joint_metrics": _dict(_first(artifact_data.get("source_metrics"), artifact_data.get("metrics"), default={})),
        "post_place_verification_latency_s": artifact_data.get("post_place_verification_latency_s"),
        "stop_latency_s": artifact_data.get("stop_latency_s"),
    }

    return {
        "schema": RUNTIME_VIEW_SCHEMA,
        "status": status,
        "session_id": execution["rollout_session_id"],
        "execution": execution,
        "interlocks": interlocks,
        "completion": {
            "steps": completion_steps,
            "current_step": first_waiting,
            "terminal": terminal_completion,
        },
        "result": result,
        "metrics": metrics,
        "freshness": {
            "latest_sequence": packet_data.get("sequence"),
            "packet_timestamp": str(packet_data.get("timestamp") or ""),
            "session_status": str(session_data.get("status") or ""),
        },
        "provenance": {
            "execution": "CONFIGURED",
            "interlocks": "MEASURED|DERIVED|EVENT",
            "completion": "MEASURED|EVENT",
            "result": "EVENT|ARTIFACT",
            "task_cycle": "DERIVED",
            "grasp": "DERIVED",
        },
    }
