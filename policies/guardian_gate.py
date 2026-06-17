"""
File purpose:
- Normalize graph-wide Guardian safety gates, contracts, decisions, and incidents.

Key classes/functions:
- guardian_gate
- gate_blocks_execution

Inputs/outputs:
- Input: OrchestratorState-like object, stage/phase, agent or tool payload
- Output: guardian_gate_result.v1 payload with guardian_contract.v1,
  guardian_decision.v1, incident_record.v1, and corrective_action.v1 records

Dependencies:
- datetime
- hashlib

Modification guide:
- Safe places to edit: reason-code mapping and risk thresholds
- Risky places to edit: decision values consumed by Runtime GUI and GuardianAgent
- Related files: orchestrator/langgraph_runtime.py, agents/guardian_agent.py
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


RISK_VECTOR_KEYS = (
    "hardware",
    "vision",
    "robot",
    "equipment",
    "data",
    "optimization",
    "self_evolution",
    "operator",
)

PHYSICAL_STAGES = {"specimen", "vision", "manipulation", "equipment"}
TERMINAL_FAILURE_STATUSES = {"blocked", "failed", "fail", "error", "critical", "not_enabled"}
WARNING_STATUSES = {"warning", "warn", "degraded"}
ACTION_SHIELDED_TOOLS = {
    "experiment.evaluate",
    "printer.prepare",
    "printer.start",
    "printer.auto_eject",
    "lerobot.rollout.start",
    "lerobot.rollout_start",
    "robot.pick_place",
    "equipment.pyautogui.run",
    "utm.run_protocol",
    "self_evolution.activate",
    "self_evolution.rollback",
    "graph.active_config.activate",
    "knowledge.memory.commit",
}


def guardian_gate(
    *,
    state: Any,
    stage: str,
    phase: str,
    payload: dict[str, Any] | None = None,
    agent: str = "",
    tool: str = "",
    action: str = "",
) -> dict[str, Any]:
    """Build a Guardian gate result for a stage/action without executing side effects."""
    payload = dict(payload or {})
    stage = str(stage or "runtime").strip().lower() or "runtime"
    phase = str(phase or "post").strip().lower() or "post"
    agent = str(agent or payload.get("producer_agent") or payload.get("agent") or f"{stage}_agent")
    now = datetime.now(timezone.utc).isoformat()
    run_id = str(getattr(state, "run_id", payload.get("run_id", "run-unknown")))
    experiment_id = str(getattr(state, "experiment_id", payload.get("experiment_id", "")))
    loop_count = _loop_count(state, payload)
    alarm_payload = _pre_tool_alarm_payload(payload) if phase == "action" and action == "pre_tool_call" else payload
    alarms = _collect_alarm_signals(alarm_payload)
    alarms.extend(_tool_action_alarm_signals(payload=payload, state=state, stage=stage, phase=phase, tool=tool, action=action))
    alarms.extend(_state_alarm_signals(state=state, stage=stage, phase=phase))
    alarms = _filter_expected_non_actuating_print_alarms(alarms, payload=payload, state=state)
    alarms = _dedupe_alarms(alarms)

    risk_vector = _risk_vector_for_alarms(alarms, stage=stage)
    risk_score = max(risk_vector.values()) if risk_vector else 0.0
    decision = _decision_for_risk(risk_score, alarms=alarms, stage=stage, phase=phase)
    reason_code = _primary_reason_code(alarms, decision=decision)
    status = _contract_status(decision, alarms)
    ok_for_next_stage = decision in {"allow", "allow_with_warning", "modify"}
    ok_for_bo = _ok_for_bo(stage=stage, payload=payload, ok_for_next_stage=ok_for_next_stage, alarms=alarms)
    evidence_refs = _extract_refs(payload, ("evidence_refs", "artifact_refs", "artifacts", "runtime_artifacts"))
    provenance_refs = _extract_refs(payload, ("provenance_refs", "source_refs", "lineage_refs"))
    gate_id = _stable_gate_id(run_id, loop_count, stage, phase, agent, tool, action, alarms, now)

    contract = {
        "schema_version": "guardian_contract.v1",
        "run_id": run_id,
        "loop_id": loop_count,
        "stage": stage,
        "phase": phase,
        "agent": agent,
        "tool": tool,
        "action": action,
        "status": status,
        "confidence": _contract_confidence(payload, alarms),
        "artifact_refs": evidence_refs,
        "provenance_refs": provenance_refs or [gate_id],
        "requires_human_approval": decision == "require_human_approval",
        "ok_for_next_stage": ok_for_next_stage,
        "ok_for_bo": ok_for_bo,
        "failure_code": reason_code if decision not in {"allow", "allow_with_warning"} else "",
        "risk_flags": sorted({alarm["reason_code"] for alarm in alarms}),
    }
    modified_payload_patch = _modified_payload_patch(decision=decision, reason_code=reason_code, stage=stage, tool=tool)
    guardian_decision = {
        "schema": "guardian_decision.v1",
        "decision_id": gate_id,
        "decision": decision,
        "reason_code": reason_code,
        "stage": stage,
        "phase": phase,
        "agent": agent,
        "tool": tool,
        "action": action,
        "risk_score": round(risk_score, 4),
        "risk_vector": {key: round(value, 4) for key, value in risk_vector.items()},
        "dominant_risks": [key for key, value in risk_vector.items() if value >= 0.5],
        "requires_human_approval": decision == "require_human_approval",
        "recommended_action": _recommended_action(decision, reason_code),
        "required_evidence": _required_evidence(stage=stage, phase=phase, decision=decision),
        "missing_evidence": _missing_evidence(stage=stage, phase=phase, evidence_refs=evidence_refs, alarms=alarms),
        "fallback_action": _fallback_action(stage, reason_code),
        "taxonomy_action": _taxonomy_action(decision, reason_code),
        "modified_payload_patch": modified_payload_patch,
    }
    corrective_actions = _corrective_actions(
        gate_id=gate_id,
        run_id=run_id,
        loop_count=loop_count,
        stage=stage,
        phase=phase,
        decision=decision,
        alarms=alarms,
        created_at=now,
    )
    incident_records = _incident_records(
        gate_id=gate_id,
        run_id=run_id,
        experiment_id=experiment_id,
        loop_count=loop_count,
        stage=stage,
        phase=phase,
        agent=agent,
        tool=tool,
        action=action,
        decision=decision,
        risk_score=risk_score,
        risk_vector=risk_vector,
        alarms=alarms,
        corrective_actions=corrective_actions,
        evidence_refs=evidence_refs,
        created_at=now,
    )
    return {
        "schema": "guardian_gate_result.v1",
        "gate_id": gate_id,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "loop_id": loop_count,
        "stage": stage,
        "phase": phase,
        "agent": agent,
        "tool": tool,
        "action": action,
        "status": status,
        "decision": decision,
        "reason_code": reason_code,
        "risk_score": round(risk_score, 4),
        "risk_vector": guardian_decision["risk_vector"],
        "guardian_contract": contract,
        "guardian_decision": guardian_decision,
        "modified_payload_patch": modified_payload_patch,
        "alarms": alarms,
        "incident_records": incident_records,
        "corrective_actions": corrective_actions,
        "ok_for_next_stage": ok_for_next_stage,
        "ok_for_bo": ok_for_bo,
        "created_at": now,
    }


def gate_blocks_execution(gate: dict[str, Any]) -> bool:
    """Return True when the gate decision must prevent the next action/stage."""
    return str(gate.get("decision") or "") in {"block", "safe_stop"}


def tool_requires_action_shield(tool: str) -> bool:
    """Return True when a tool has physical, persistent, or runtime-mutating side effects."""
    name = str(tool or "").strip()
    if name in ACTION_SHIELDED_TOOLS:
        return True
    return name.startswith(("lerobot.rollout.", "printer.", "self_evolution.", "graph.active_config."))


def _loop_count(state: Any, payload: dict[str, Any]) -> int:
    try:
        return int(getattr(state, "loop_count", payload.get("loop_id", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _collect_alarm_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alarms: list[dict[str, Any]] = []

    def add(reason: str, severity: str, message: str, path: str) -> None:
        clean_message = str(message or reason).strip()
        if not clean_message:
            return
        alarms.append(
            {
                "reason_code": _map_reason_code(reason or clean_message),
                "severity": _normalize_severity(severity),
                "message": clean_message,
                "source_path": path,
            }
        )

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            status = str(value.get("status") or value.get("handoff_status") or value.get("guardian_status") or "").strip().lower()
            failure = value.get("failure_code") or value.get("error_code") or value.get("incident_code")
            message = str(value.get("message") or value.get("error") or failure or status or "")
            if failure:
                add(str(failure), str(value.get("severity") or "blocking"), message, path)
            elif status in TERMINAL_FAILURE_STATUSES:
                default_severity = "blocking" if _is_top_level_status_path(path) else "warning"
                add(status, str(value.get("severity") or default_severity), message or status, path)
            elif status in WARNING_STATUSES:
                add(status, str(value.get("severity") or "warning"), message or status, path)
            elif value.get("ok") is False:
                add("RESULT_NOT_OK", str(value.get("severity") or "warning"), message or "ok=false", path)

            boolean_blockers = (
                ("requires_operator_input", "MISSING_REQUIRED_INPUT"),
                ("requires_connection_info", "MISSING_REQUIRED_INPUT"),
                ("requires_human_approval", "HUMAN_APPROVAL_REQUIRED"),
                ("requires_approval", "HUMAN_APPROVAL_REQUIRED"),
                ("blocks_workflow", "WORKFLOW_BLOCKED"),
                ("safe_stop_recommended", "OPERATOR_STOP_REQUESTED"),
            )
            is_module_safety_config = path.endswith("module_runtime.safety")
            for key, reason in boolean_blockers:
                if is_module_safety_config and key in {"requires_human_approval", "requires_approval"}:
                    continue
                if value.get(key) is True:
                    severity = "critical" if key == "safe_stop_recommended" else "blocking"
                    if key in {"requires_human_approval", "requires_approval"}:
                        severity = "warning"
                    add(reason, severity, message or key, f"{path}.{key}")

            for key, items in value.items():
                key_lower = str(key).lower()
                if _is_blocking_signal_key(key_lower):
                    if key_lower.endswith("blocking_reason") and status not in TERMINAL_FAILURE_STATUSES:
                        continue
                    severity = "warning" if "agent_performance_records" in path else "blocking"
                    reason_hint = "MISSING_REQUIRED_INPUT" if "missing" in key_lower or "required" in key_lower else None
                    _add_sequence_items(add, items, severity, f"{path}.{key}", reason_hint=reason_hint)
                elif _is_warning_signal_key(key_lower):
                    _add_sequence_items(add, items, "warning", f"{path}.{key}")

            confidence = value.get("confidence")
            if isinstance(confidence, (int, float)) and float(confidence) < 0.5:
                add("VISION_CONFIDENCE_LOW", "warning", f"confidence={confidence}", f"{path}.confidence")

            for key, child in value.items():
                if key in {"raw", "raw_output", "prompt"}:
                    continue
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(payload, "payload")
    return alarms


def _is_blocking_signal_key(key: str) -> bool:
    """Return True for agent-specific keys that should block or pause the workflow."""
    normalized = str(key or "").lower()
    exact = {
        "blocking_reason",
        "block_reason",
        "blocking_reasons",
        "blockers",
        "missing_fields",
        "required_missing",
        "missing_required_fields",
        "required_fields_missing",
        "issues",
        "errors",
    }
    return normalized in exact or normalized.endswith(("_blocking_reason", "_blockers", "_missing_fields", "_errors"))


def _is_warning_signal_key(key: str) -> bool:
    """Return True for agent-specific warning/risk/near-miss list keys."""
    normalized = str(key or "").lower()
    exact = {
        "warning",
        "warnings",
        "risk_flags",
        "failure_tags",
        "quality_flags",
        "near_misses",
        "alerts",
    }
    return normalized in exact or normalized.endswith(("_warning", "_warnings", "_risk_flags", "_failure_tags", "_quality_flags", "_alerts"))


def _add_sequence_items(add: Any, items: Any, severity: str, path: str, *, reason_hint: str | None = None) -> None:
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                reason = reason_hint or item.get("failure_code") or item.get("reason_code") or item.get("code") or item.get("status") or item.get("message")
                message = item.get("message") or item.get("summary") or reason
                if reason:
                    add(str(reason), severity, str(message), path)
            elif str(item or "").strip():
                add(reason_hint or str(item), severity, str(item), path)
    elif isinstance(items, dict):
        reason = reason_hint or items.get("failure_code") or items.get("reason_code") or items.get("code") or items.get("status") or items.get("message")
        message = items.get("message") or items.get("summary") or reason
        if reason:
            add(str(reason), severity, str(message), path)
    elif isinstance(items, str) and items.strip():
        add(reason_hint or items, severity, items, path)


def _pre_tool_alarm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the part of a proposed tool payload that should be scanned as direct alarms."""
    skip_keys = {
        "source_stage_context",
        "previous_stage_context",
        "observation",
        "guardian_gate",
        "guardian_contract",
        "guardian_decision",
        "incident_records",
        "corrective_actions",
        "vision_report",
        "vision_signal",
        "agent_signals",
    }
    return {key: value for key, value in payload.items() if key not in skip_keys}


def _tool_action_alarm_signals(
    *,
    payload: dict[str, Any],
    state: Any,
    stage: str,
    phase: str,
    tool: str,
    action: str,
) -> list[dict[str, Any]]:
    """Return deterministic pre-action alarms for side-effecting runtime tools."""
    name = str(tool or "").strip()
    if not name or not tool_requires_action_shield(name):
        return []
    if str(phase or "").lower() != "action" and not str(action or "").startswith(("pre_tool", "post_tool")):
        return []
    if str(action or "").startswith("post_tool"):
        return []

    alarms: list[dict[str, Any]] = []

    def add(reason: str, severity: str, message: str, source_path: str) -> None:
        alarms.append(_alarm(reason, severity, message, source_path))

    mode = _runtime_mode(payload=payload, state=state)
    if mode != "live":
        if name == "lerobot.rollout.start" and payload.get("rollout_action_clamp") is False:
            add("ROBOT_ACTION_CLAMP_DISABLED", "warning", "rollout_action_clamp=false; bounded rollout should stay enabled", "payload.rollout_action_clamp")
        return alarms

    if _is_non_actuating(payload):
        return alarms

    if name in {"lerobot.rollout.start", "lerobot.rollout_start", "robot.pick_place"}:
        if not _bool_any(payload, ("confirm_live_execute", "operator_confirmed", "human_approved")):
            add(
                "HUMAN_APPROVAL_REQUIRED",
                "warning",
                "live robot rollout requires explicit operator confirmation before execution",
                "payload.confirm_live_execute",
            )
        if name.startswith("lerobot") and payload.get("rollout_action_clamp") is False:
            add("ROBOT_ACTION_CLAMP_DISABLED", "warning", "rollout action clamp is disabled for live robot motion", "payload.rollout_action_clamp")
        if name.startswith("lerobot") and not _has_any(payload, ("policy_path", "policy_repo_id", "policy_checkpoint_path", "checkpoint_path")):
            add("ROBOT_POLICY_UNAPPROVED", "blocking", "live robot rollout requires an approved policy reference", "payload.policy")
        return alarms

    if name in {"equipment.pyautogui.run", "utm.run_protocol"}:
        if not _has_any(payload, ("program_id", "protocol_id", "macro_id")):
            add("MISSING_REQUIRED_INPUT", "blocking", "live equipment macro requires program_id/protocol_id", "payload.program_id")
        if not _bool_any(
            payload,
            (
                "confirm_live_execute",
                "confirm_execute",
                "confirm_physical_setup_safe",
                "confirm_setup_gui_execute",
                "operator_confirmed",
                "human_approved",
            ),
        ):
            add("HUMAN_APPROVAL_REQUIRED", "warning", "live equipment macro requires explicit operator confirmation", "payload.confirm_live_execute")
        return alarms

    if name in {"printer.prepare", "printer.start", "printer.auto_eject", "experiment.evaluate"}:
        if name == "experiment.evaluate":
            execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
            bridge = str(execution.get("bridge") or payload.get("bridge") or "").lower()
            requested_tool = str(execution.get("requested_tool") or payload.get("requested_tool") or "").lower()
            if bridge not in {"printer", "prusa", "auto"} and not requested_tool.startswith("printer."):
                return alarms
            if not bool(execution.get("allow_physical")) and not _bool_any(payload, ("allow_physical", "allow_test_printer_live")):
                add("MISSING_REQUIRED_INPUT", "blocking", "live printer experiment requires execution.allow_physical=true", "payload.execution.allow_physical")
                return alarms
            params = _candidate_parameters(payload)
            print_request = params.get("print") if isinstance(params.get("print"), dict) else {}
            confirmed = _bool_any(params, ("allow_physical", "allow_test_printer_live", "confirm_physical_print", "physical_intent")) or _bool_any(
                print_request,
                ("confirm_physical_print", "physical_intent"),
            )
            starts = bool(print_request.get("start_immediately", not bool(execution.get("dry_run"))))
            if starts and not confirmed:
                add("HUMAN_APPROVAL_REQUIRED", "warning", "live printer start requires explicit physical print confirmation", "payload.candidate.parameters.print")
            return alarms

        print_request = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        starts = bool(print_request.get("start_immediately") or payload.get("start_immediately") or name in {"printer.start", "printer.auto_eject"})
        if not starts:
            return alarms
        if not _bool_any(payload, ("allow_physical", "allow_test_printer_live", "confirm_physical_print", "physical_intent")) and not _bool_any(
            print_request,
            ("confirm_physical_print", "physical_intent"),
        ):
            add("HUMAN_APPROVAL_REQUIRED", "warning", "live printer action requires explicit physical print/ejection confirmation", "payload.print")
        return alarms

    if name in {"self_evolution.activate", "self_evolution.rollback", "graph.active_config.activate", "knowledge.memory.commit"}:
        if not _bool_any(payload, ("human_approved", "operator_confirmed", "approved", "approval_resolved")):
            add("HUMAN_APPROVAL_REQUIRED", "warning", f"{name} requires an explicit operator approval record", "payload.human_approved")
    return alarms


def _runtime_mode(*, payload: dict[str, Any], state: Any) -> str:
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    value = payload.get("runtime_mode") or payload.get("mode") or execution.get("mode")
    if value is None:
        state_mode = getattr(state, "mode", None)
        value = getattr(state_mode, "value", state_mode)
    return str(value or "test").strip().lower()


def _candidate_parameters(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    params = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
    return dict(params) if params else {}


def _is_non_actuating(payload: dict[str, Any]) -> bool:
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    if payload.get("dry_run") is True or execution.get("dry_run") is True:
        return True
    if payload.get("non_actuating") is True:
        return True
    if str(payload.get("test_printer_transport") or "").lower() == "virtual":
        return True
    return False


def _filter_expected_non_actuating_print_alarms(
    alarms: list[dict[str, Any]],
    *,
    payload: dict[str, Any],
    state: Any,
) -> list[dict[str, Any]]:
    """Suppress expected print-disabled markers for dry-run/virtual/test printer checks.

    A disabled start command is a safety violation only when an actual physical
    print was requested. In TEST/virtual/dry-run paths it is evidence that the
    bridge reached the print gate without actuating the printer.
    """
    if not alarms or not _is_expected_non_actuating_print_payload(payload=payload, state=state):
        return alarms
    expected_codes = {"START_PRINT_DISABLED", "AUTO_EJECT_DISABLED", "NOT_ENABLED"}
    filtered: list[dict[str, Any]] = []
    for alarm in alarms:
        reason = str(alarm.get("reason_code") or "").upper()
        message = str(alarm.get("message") or "").upper()
        if reason in expected_codes or any(code in message for code in expected_codes):
            continue
        filtered.append(alarm)
    return filtered


def _is_expected_non_actuating_print_payload(*, payload: dict[str, Any], state: Any) -> bool:
    mode = _runtime_mode(payload=payload, state=state)
    if mode in {"test", "virtual", "dry_run"}:
        return True
    if _is_non_actuating(payload):
        return True
    if _contains_expected_print_status(payload):
        return True
    return False


def _contains_expected_print_status(value: Any) -> bool:
    if isinstance(value, dict):
        status = str(value.get("status") or value.get("printer_prepare_status") or value.get("handoff_status") or "").lower()
        if status in {"simulated_printed", "virtual_finished", "dry_run", "prepared"}:
            return True
        mode = str(value.get("mode") or value.get("runtime_mode") or value.get("printer_mode") or "").lower()
        if mode in {"test", "virtual", "test_printer_live_virtual"}:
            return True
        if value.get("dry_run") is True or value.get("non_actuating") is True:
            return True
        return any(_contains_expected_print_status(child) for key, child in value.items() if key not in {"raw", "raw_output", "prompt"})
    if isinstance(value, list):
        return any(_contains_expected_print_status(child) for child in value)
    return False


def _bool_any(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        if bool(payload.get(key)):
            return True
    return False


def _has_any(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", {}, []):
            return True
    return False


def _state_alarm_signals(*, state: Any, stage: str, phase: str) -> list[dict[str, Any]]:
    alarms: list[dict[str, Any]] = []
    if bool(getattr(state, "safe_stop_requested", False)):
        alarms.append(_alarm("OPERATOR_STOP_REQUESTED", "critical", "safe_stop_requested flag is set", "state.safe_stop_requested"))
    if bool(getattr(state, "stop_requested", False)):
        alarms.append(_alarm("OPERATOR_STOP_REQUESTED", "blocking", "stop_requested flag is set", "state.stop_requested"))
    if phase == "pre":
        metadata = getattr(state, "run_metadata", {}) if isinstance(getattr(state, "run_metadata", {}), dict) else {}
        for alert in metadata.get("hardware_alerts", []) if isinstance(metadata.get("hardware_alerts"), list) else []:
            if not isinstance(alert, dict) or not bool(alert.get("blocks_workflow", False)):
                continue
            alert_stage = str(alert.get("stage") or alert.get("workspace") or "").lower()
            if stage not in PHYSICAL_STAGES and alert_stage not in {stage, "runtime"}:
                continue
            alarms.append(
                _alarm(
                    str(alert.get("failure_code") or "DEVICE_UNHEALTHY"),
                    str(alert.get("severity") or "blocking"),
                    str(alert.get("message") or alert.get("failure_code") or "blocking hardware alert"),
                    "state.run_metadata.hardware_alerts",
                )
            )
    return alarms


def _is_top_level_status_path(path: str) -> bool:
    """Treat only the root stage status as a hard block without extra evidence."""
    return str(path or "payload") == "payload"


def _alarm(reason_code: str, severity: str, message: str, source_path: str) -> dict[str, Any]:
    return {
        "reason_code": _map_reason_code(reason_code),
        "severity": _normalize_severity(severity),
        "message": str(message or reason_code),
        "source_path": source_path,
    }


def _dedupe_alarms(alarms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for alarm in alarms:
        key = (str(alarm.get("reason_code")), str(alarm.get("severity")), str(alarm.get("message"))[:200])
        if key in seen:
            continue
        seen.add(key)
        out.append(alarm)
    return out[:32]


def _map_reason_code(value: str) -> str:
    text = str(value or "").upper()
    if "APPROVAL" in text:
        return "HUMAN_APPROVAL_REQUIRED"
    if "ARTIFACT" in text and "MISSING" in text:
        return "ARTIFACT_MISSING"
    if "PROVENANCE" in text:
        return "PROVENANCE_MISSING"
    if "MISSING" in text or "REQUIRED" in text:
        return "MISSING_REQUIRED_INPUT"
    if "CONTRACT" in text or "SCHEMA" in text or "VALIDATION" in text:
        return "CONTRACT_SCHEMA_INVALID"
    if "WORKFLOW_BLOCKED" in text or "BLOCKS_WORKFLOW" in text:
        return "WORKFLOW_BLOCKED"
    if "HEARTBEAT" in text or "DISCONNECT" in text or "UNREACHABLE" in text:
        return "HEARTBEAT_LOST"
    if text.startswith("VISION") or "CONFIDENCE" in text or "STALE" in text or "OCCLUSION" in text:
        return "VISION_CONFIDENCE_LOW"
    if "ZONE" in text or "OCCUPIED" in text or "HUMAN" in text:
        return "ZONE_OCCUPIED"
    if "LEROBOT" in text or "ROBOT" in text or "POLICY" in text:
        if "CLAMP" in text:
            return "ROBOT_ACTION_CLAMP_DISABLED"
        if "POLICY" in text:
            return "ROBOT_POLICY_UNAPPROVED"
        return "ROBOT_ACTION_OUT_OF_BOUNDS"
    if "UTM_NO_MOTION" in text or "NO_MOTION" in text:
        return "UTM_NO_MOTION"
    if "UTM_EXPORT" in text or "EXPORT_MISSING" in text:
        return "UTM_EXPORT_MISSING"
    if "UTM" in text or "PYAUTOGUI" in text or "MACRO" in text or "WINDOW" in text:
        return "UTM_MACRO_MISMATCH"
    if "PARSE" in text:
        return "DATA_PARSE_FAILED"
    if "DATA" in text or "QUALITY" in text:
        return "DATA_QUALITY_LOW"
    if "FEM" in text or "CAE" in text or "CALCULIX" in text or "DIVERGENCE" in text:
        return "FEM_DIVERGENCE_HIGH"
    if "BO" in text or "CANDIDATE" in text or "UNSAFE" in text:
        return "BO_CANDIDATE_UNSAFE"
    if "EVOLUTION" in text or "VARIANT" in text:
        return "SELF_EVOLUTION_GATE_FAILED"
    if "STOP" in text:
        return "OPERATOR_STOP_REQUESTED"
    if text in {"BLOCKED", "FAILED", "FAIL", "ERROR", "CRITICAL"}:
        return "CONTRACT_SCHEMA_INVALID"
    return text[:64] or "UNKNOWN_GUARDIAN_SIGNAL"


def _normalize_severity(value: str) -> str:
    text = str(value or "").lower()
    if text in {"critical", "safe_stop", "major"}:
        return "critical"
    if text in {"blocking", "block", "blocked", "failed", "fail", "error"}:
        return "blocking"
    if text in {"warning", "warn", "degraded"}:
        return "warning"
    return "near_miss"


def _risk_vector_for_alarms(alarms: list[dict[str, Any]], *, stage: str) -> dict[str, float]:
    vector = {key: 0.0 for key in RISK_VECTOR_KEYS}
    stage_key = {
        "vision": "vision",
        "manipulation": "robot",
        "equipment": "equipment",
        "analysis": "data",
        "bo": "optimization",
        "knowledge": "self_evolution",
        "specimen": "hardware",
        "design": "optimization",
    }.get(stage, "hardware")
    for alarm in alarms:
        reason = str(alarm.get("reason_code") or "")
        severity = str(alarm.get("severity") or "warning")
        score = {"near_miss": 0.25, "warning": 0.45, "blocking": 0.78, "critical": 0.93}.get(severity, 0.35)
        key = stage_key
        if reason.startswith("VISION"):
            key = "vision"
        elif reason.startswith("ROBOT"):
            key = "robot"
        elif reason.startswith("UTM") or "DEVICE" in reason or "HEARTBEAT" in reason:
            key = "equipment"
        elif reason.startswith("DATA") or reason.startswith("FEM"):
            key = "data"
        elif reason.startswith("BO"):
            key = "optimization"
        elif reason.startswith("WORKFLOW"):
            key = stage_key
        elif reason.startswith("SELF_EVOLUTION"):
            key = "self_evolution"
        elif reason.startswith("HUMAN") or reason.startswith("OPERATOR"):
            key = "operator"
        vector[key] = max(vector[key], score)
        if key in {"robot", "equipment"}:
            vector["hardware"] = max(vector["hardware"], min(score, 0.9))
    return vector


def _decision_for_risk(risk_score: float, *, alarms: list[dict[str, Any]], stage: str, phase: str) -> str:
    if not alarms:
        return "allow"
    if any(alarm.get("reason_code") == "OPERATOR_STOP_REQUESTED" or alarm.get("severity") == "critical" for alarm in alarms):
        return "safe_stop"
    if any(alarm.get("reason_code") == "HUMAN_APPROVAL_REQUIRED" for alarm in alarms):
        return "require_human_approval"
    if any(alarm.get("reason_code") == "WORKFLOW_BLOCKED" for alarm in alarms):
        return "block"
    if risk_score >= 0.75:
        return "block"
    if phase == "action" and any(alarm.get("reason_code") == "ROBOT_ACTION_CLAMP_DISABLED" for alarm in alarms):
        return "modify"
    if risk_score >= 0.55 and phase == "action":
        return "require_human_approval"
    return "allow_with_warning"


def _primary_reason_code(alarms: list[dict[str, Any]], *, decision: str) -> str:
    if not alarms:
        return "OK"
    priority = {"critical": 3, "blocking": 2, "warning": 1, "near_miss": 0}
    selected = max(alarms, key=lambda alarm: priority.get(str(alarm.get("severity")), 0))
    return str(selected.get("reason_code") or decision)


def _contract_status(decision: str, alarms: list[dict[str, Any]]) -> str:
    if decision in {"block", "safe_stop"}:
        return "blocked"
    if decision == "require_human_approval":
        return "approval_required"
    if decision == "modify":
        return "modified"
    if alarms:
        return "warning"
    return "ok"


def _contract_confidence(payload: dict[str, Any], alarms: list[dict[str, Any]]) -> float:
    confidence = payload.get("confidence")
    if isinstance(confidence, (int, float)):
        return round(max(0.0, min(1.0, float(confidence))), 4)
    if not alarms:
        return 1.0
    if any(alarm.get("severity") in {"critical", "blocking"} for alarm in alarms):
        return 0.35
    return 0.7


def _ok_for_bo(*, stage: str, payload: dict[str, Any], ok_for_next_stage: bool, alarms: list[dict[str, Any]]) -> bool:
    if not ok_for_next_stage:
        return False
    if stage == "analysis":
        return bool(payload.get("ok_for_bo", payload.get("analysis", {}).get("ok_for_bo", False) if isinstance(payload.get("analysis"), dict) else False))
    return not any(alarm.get("reason_code") in {"DATA_PARSE_FAILED", "DATA_QUALITY_LOW", "FEM_DIVERGENCE_HIGH", "BO_CANDIDATE_UNSAFE"} for alarm in alarms)


def _extract_refs(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    refs: list[Any] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            refs.extend(value)
        elif isinstance(value, dict):
            refs.append(value)
        elif isinstance(value, str) and value:
            refs.append(value)
    return refs[:24]


def _stable_gate_id(run_id: str, loop_count: int, stage: str, phase: str, agent: str, tool: str, action: str, alarms: list[dict[str, Any]], now: str) -> str:
    seed = f"{run_id}:{loop_count}:{stage}:{phase}:{agent}:{tool}:{action}:{now}:{[(a.get('reason_code'), a.get('message')) for a in alarms[:8]]}"
    return "guardian-gate-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:14]


def _recommended_action(decision: str, reason_code: str) -> str:
    if decision == "allow":
        return "continue"
    if decision == "allow_with_warning":
        return "continue_with_warning_and_record_evidence"
    if decision == "modify":
        return "modify_action_with_guardian_patch"
    if decision == "require_human_approval":
        return "pause_for_operator_approval"
    if decision == "safe_stop":
        return "safe_stop_and_verify"
    if reason_code in {"DATA_PARSE_FAILED", "DATA_QUALITY_LOW", "FEM_DIVERGENCE_HIGH"}:
        return "quarantine_artifact_and_block_bo_update"
    if reason_code == "BO_CANDIDATE_UNSAFE":
        return "block_bo_update_and_request_new_candidate"
    if reason_code == "SELF_EVOLUTION_GATE_FAILED":
        return "rollback_or_hold_variant_for_review"
    return "block_and_route_to_guardian_review"


def _taxonomy_action(decision: str, reason_code: str) -> str:
    if reason_code in {"DATA_PARSE_FAILED", "DATA_QUALITY_LOW", "FEM_DIVERGENCE_HIGH"}:
        return "quarantine_artifact"
    if reason_code == "BO_CANDIDATE_UNSAFE":
        return "block_bo_update"
    if reason_code == "SELF_EVOLUTION_GATE_FAILED":
        return "rollback_variant"
    if decision in {"allow", "allow_with_warning", "modify", "require_human_approval", "block", "safe_stop"}:
        return decision
    return decision or "guardian_review"


def _modified_payload_patch(*, decision: str, reason_code: str, stage: str, tool: str) -> dict[str, Any]:
    if decision != "modify":
        return {}
    if reason_code == "ROBOT_ACTION_CLAMP_DISABLED" or str(tool or "").startswith(("lerobot.rollout", "robot.pick_place")):
        return {
            "rollout_action_clamp": True,
            "guardian_modified_payload": True,
            "guardian_modification_reason": reason_code or "ROBOT_ACTION_CLAMP_DISABLED",
        }
    return {"guardian_modified_payload": True, "guardian_modification_reason": reason_code or stage}


def _required_evidence(*, stage: str, phase: str, decision: str) -> list[str]:
    if decision == "allow":
        return []
    if stage == "manipulation":
        return ["vision_signal.fresh", "robot.heartbeat", "policy.approved", "stop_channel.ready"]
    if stage == "equipment":
        return ["bridge.heartbeat", "screen_assertion", "physical_motion_or_data_artifact"]
    if stage == "analysis":
        return ["raw_data_file", "parser_report", "quality_gate"]
    if stage == "bo":
        return ["bounds_check", "prior_evidence", "candidate_risk_assessment"]
    if stage == "knowledge":
        return ["artifact_refs", "provenance_refs"]
    if phase == "action":
        return ["precheck_evidence", "operator_or_guardian_gate"]
    return ["stage_output_contract"]


def _missing_evidence(*, stage: str, phase: str, evidence_refs: list[Any], alarms: list[dict[str, Any]]) -> list[str]:
    missing = [alarm["reason_code"] for alarm in alarms if alarm.get("reason_code") in {"ARTIFACT_MISSING", "PROVENANCE_MISSING", "MISSING_REQUIRED_INPUT"}]
    if stage in {"analysis", "knowledge"} and phase == "post" and alarms and not evidence_refs:
        missing.append("artifact_refs")
    return sorted(set(missing))


def _fallback_action(stage: str, reason_code: str) -> str:
    if stage == "manipulation":
        return "pause_policy_or_retreat_pose"
    if stage == "equipment":
        return "stop_macro_and_recheck_screen"
    if stage == "specimen":
        return "stop_printer_or_hold_for_operator"
    if reason_code.startswith("DATA"):
        return "quarantine_artifact"
    if reason_code.startswith("BO"):
        return "request_new_candidate"
    return "guardian_review"


def _corrective_actions(
    *,
    gate_id: str,
    run_id: str,
    loop_count: int,
    stage: str,
    phase: str,
    decision: str,
    alarms: list[dict[str, Any]],
    created_at: str,
) -> list[dict[str, Any]]:
    if decision == "allow":
        return []
    actions: list[dict[str, Any]] = []
    reason_codes = sorted({str(alarm.get("reason_code") or "") for alarm in alarms if alarm.get("reason_code")})
    for index, reason in enumerate(reason_codes or [decision], start=1):
        actions.append(
            {
                "schema": "corrective_action.v1",
                "action_id": f"{gate_id}-ca-{index}",
                "run_id": run_id,
                "loop_id": loop_count,
                "stage": stage,
                "phase": phase,
                "reason_code": reason,
                "recommended_action": _fallback_action(stage, reason),
                "status": "open",
                "owner": "guardian_agent",
                "created_at": created_at,
            }
        )
    return actions


def _incident_records(
    *,
    gate_id: str,
    run_id: str,
    experiment_id: str,
    loop_count: int,
    stage: str,
    phase: str,
    agent: str,
    tool: str,
    action: str,
    decision: str,
    risk_score: float,
    risk_vector: dict[str, float],
    alarms: list[dict[str, Any]],
    corrective_actions: list[dict[str, Any]],
    evidence_refs: list[Any],
    created_at: str,
) -> list[dict[str, Any]]:
    if decision == "allow":
        return []
    severity = "critical" if decision == "safe_stop" else "major" if decision == "block" else "near_miss"
    risk_class = max(risk_vector, key=lambda key: risk_vector.get(key, 0.0)) if risk_vector else "unknown"
    summary = "; ".join(str(alarm.get("message") or alarm.get("reason_code")) for alarm in alarms[:4]) or decision
    return [
        {
            "schema": "incident_record.v1",
            "incident_id": gate_id,
            "run_id": run_id,
            "experiment_id": experiment_id,
            "loop_id": loop_count,
            "stage": stage,
            "phase": phase,
            "severity": severity,
            "class": risk_class,
            "risk_class": risk_class,
            "event_time": created_at,
            "source": "guardian_gate",
            "component": tool or agent or stage,
            "summary": summary[:500],
            "message": summary[:500],
            "detected_by": ["guardian_gate", agent or f"{stage}_agent"],
            "immediate_cause": alarms[0].get("reason_code") if alarms else decision,
            "root_cause_hypotheses": [alarm.get("reason_code") for alarm in alarms[:6]],
            "evidence_refs": evidence_refs,
            "guardian_decision": decision,
            "corrective_actions": [item.get("recommended_action") for item in corrective_actions],
            "corrective_action_refs": [item.get("action_id") for item in corrective_actions],
            "status": "open",
            "owner": "guardian_agent",
            "tool": tool,
            "action": action,
            "risk_score": round(risk_score, 4),
            "risk_vector": {key: round(value, 4) for key, value in risk_vector.items()},
            "created_at": created_at,
        }
    ]
