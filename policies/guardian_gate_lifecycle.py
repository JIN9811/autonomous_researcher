"""Resolve historical holds only after a matching, evidenced successful recheck."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any


def new_agent_attempt(state: Any, attempt_id: str, *, stage: str | None = None) -> dict[str, Any]:
    """Freeze logical input identity before execution; session IDs are not work."""
    spec = state.current_experiment_spec or {}
    stage = stage or state.stage.value
    metadata = state.run_metadata
    inputs = {"spec": spec, "objective": state.current_experiment_objective, "goal": state.active_goal}
    task = str(spec.get("task_id") or spec.get("purpose") or stage)
    if stage == "bo":
        from agents.bo.agent import BOAgent
        settings = metadata.get("bo_settings") or {}
        contract = metadata.get("orchestrator_design_contract") or {}
        if contract.get("parameter_space") and contract.get("manufacturing_constraints"):
            settings = {**settings, "parameter_space": contract["parameter_space"]}
        # BO consumes spec/settings constraints, not the last evaluated
        # candidate cached in current_experiment_objective.constraints.
        inputs["objective"] = BOAgent._objective_from_state(state, settings)
        try:
            normalized, _ = BOAgent.normalize_settings(settings)
            normalized["parameter_space"] = BOAgent._fixed_surface_space_for_state(normalized["parameter_space"], state)
            # Numeric JSON representations (0 versus 0.0) are the same domain.
            normalized["parameter_space"] = {
                key: [float(item) if type(item) in {int, float} else item for item in values]
                for key, values in normalized["parameter_space"].items()
            }
            cycle = metadata.get("planning_cycle_contract") or {}
            if cycle.get("schema") == "planning_cycle_contract.v1" and type(cycle.get("total_cycles")) is int and cycle["total_cycles"] > 0:
                normalized["budget"] = cycle["total_cycles"]
        except (TypeError, ValueError):
            # Still let the owner emit its normal invalid-request failure gate.
            normalized = settings
        inputs["request"] = {"settings": normalized, "design_contract": contract,
                             "analysis": state.latest_analysis, "evaluations": state.experiment_evaluations}
    if stage in {"manipulation", "vision"}:
        from utils.utm_clear_cycle import current_clear
        clearance = bool(current_clear(state))
        if stage == "manipulation":
            from agents.manipulation.agent import ManipulationAgent
            task = "clear_utm_to_disposal" if clearance else ManipulationAgent()._task_id(state, spec)
            equipment = metadata.get("equipment_result") or {}
            inputs["equipment_completed"] = equipment.get("status") in {"complete", "completed", "done", "success"}
            inputs["direct_bridge"] = metadata.get("source") == "lerobot_gui_manipulation_bridge"
        else:
            from agents.vision.agent import VisionAgent
            task = ("utm_clearance" if clearance else "utm_placement" if VisionAgent._post_manipulation_handoff_requested(state)
                    else VisionAgent()._resolve_task(state, {}))
    inputs["task_id"] = task
    work_id = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
    return {"schema": "guardian_agent_attempt.v1", "work_id": work_id,
            "attempt_id": attempt_id, "specimen_id": spec.get("specimen_id", ""),
            "candidate_id": spec.get("candidate_id", ""), "task_id": task}


def complete_agent_attempt(gate: dict[str, Any], payload: dict[str, Any]) -> None:
    """Called only after output validation, true AgentResult.success and completion.

    Defense in depth: a permissive post gate cannot turn a progress/waiting or
    approval result into proof of finished work. This does not grant approvals.
    """
    audit = gate.get("audit_log") or {}
    attempt = audit.get("agent_attempt")
    if (not isinstance(attempt, dict) or gate.get("phase") != "post"
            or gate.get("decision") not in {"allow", "allow_with_warning"}
            or gate.get("ok_for_next_stage") is not True):
        return
    guardian = payload.get("guardian")
    if isinstance(guardian, dict) and guardian.get("action") in {"recover", "retry", "safe_stop"}:
        return
    history = {"guardian_gate", "guardian_contract", "guardian_decision", "incident_records", "corrective_actions",
               "audit_log", "history", "attempts", "events", "decisions", "stage_machine", "trace"}
    if gate.get("stage") == "bo":
        history.update({"benchmark", "candidate_pool", "candidate_ranking", "visualization", "visualization_steps",
                        "lhs_visualization", "lhs_visualization_steps", "prior_summary"})

    def incomplete(value: Any, depth: int = 0) -> bool:
        if depth > 16:
            return True  # Uninspected nested evidence cannot attest completion.
        if isinstance(value, list):
            return any(incomplete(item, depth + 1) for item in value)
        if not isinstance(value, dict):
            return False
        for field in ("status", "handoff_status", "completion_status"):
            status = str(value.get(field) or "").lower()
            # An accepted owner decision is terminal evidence; an accepted
            # execution request is merely queued and remains nonterminal.
            if field == "status" and status == "accepted" and str(value.get("schema", "")).endswith("_decision.v1"):
                continue
            if (status in {"failed", "error", "blocked", "running", "waiting", "progress", "in_progress", "pending", "retrying",
                           "idle", "skipped", "queued", "starting", "accepted", "reported_complete", "preflight_complete"}
                    or status.startswith(("needs_", "awaiting_"))
                    or any(token in status for token in ("waiting", "pending", "monitoring"))):
                return True
        if (value.get("ok") is False or any(value.get(key) is True for key in (
                "pending_operator_input", "requires_operator_input", "requires_human_approval", "requires_approval"))):
            return True
        return any(incomplete(item, depth + 1) for key, item in value.items() if key not in history)

    if incomplete(payload):
        return
    audit["agent_completion"] = {**deepcopy(attempt), "validated": True, "success": True, "status": "completed"}


def resolve_completed_retries(
    gates: list[dict[str, Any]], incidents: list[dict[str, Any]],
    corrective_actions: list[dict[str, Any]],
) -> None:
    """Retire software failures using runtime-attested same-work completion.

    A post allow alone is insufficient. The common runtime completion hook must
    attest validated, successful, terminal work. Legacy records without bound
    attempt evidence remain active; no status/owner/timestamp heuristic backfill.
    """
    scope = ("run_id", "experiment_id", "loop_id", "stage", "agent", "tool", "action")
    software_codes = {"AGENT_RESULT_FAILED", "VALUEERROR", "TYPEERROR", "KEYERROR",
                      "INDEXERROR", "RUNTIMEERROR", "CONTRACT_SCHEMA_INVALID"}
    for index, failed in enumerate(gates):
        if not isinstance(failed, dict) or failed.get("decision") != "block" or failed.get("phase") not in {"post", "exception"}:
            continue
        audit = failed.get("audit_log")
        old = audit.get("agent_attempt") if isinstance(audit, dict) else None
        if (not isinstance(old, dict) or old.get("schema") != "guardian_agent_attempt.v1"
                or not old.get("work_id") or not old.get("attempt_id")
                or any(not failed.get(key) for key in ("gate_id", "run_id", "experiment_id", "stage", "agent"))
                or failed.get("loop_id") is None or failed.get("tool") or failed.get("action")
                or audit.get("lifecycle") == "resolved"):
            continue
        alarms = failed.get("alarms")
        bo_invalid = (failed.get("stage") == "bo" and bool(old.get("candidate_id"))
                      and isinstance(alarms, list) and any(
                          isinstance(alarm, dict) and alarm.get("reason_code") == "BO_CANDIDATE_UNSAFE"
                          and alarm.get("message") == "BO_DECISION_INVALID"
                          and alarm.get("source_path") == "payload.bo_result" for alarm in alarms))

        def software_alarm(alarm: Any) -> bool:
            if not isinstance(alarm, dict):
                return False
            code, path = alarm.get("reason_code"), alarm.get("source_path")
            if bo_invalid and path == "payload.bo_result" and code == "BO_CANDIDATE_UNSAFE":
                return alarm.get("message") == "BO_DECISION_INVALID"
            if bo_invalid and path == "payload.bo_result.next_design_request" and code == "CONTRACT_SCHEMA_INVALID":
                return alarm.get("message") == "blocked"
            return code in software_codes and (path in {"payload", "payload.artifact_execution"}
                or (code == "CONTRACT_SCHEMA_INVALID" and str(path).startswith("payload.blocking_reasons[")))

        if (failed.get("reason_code") not in software_codes or not isinstance(alarms, list) or not alarms
                or not all(software_alarm(alarm) for alarm in alarms)):
            continue
        for passed in gates[index + 1:]:
            if (not isinstance(passed, dict) or passed.get("phase") != "post"
                    or passed.get("decision") not in {"allow", "allow_with_warning"}
                    or passed.get("ok_for_next_stage") is not True
                    or not passed.get("gate_id") or passed["gate_id"] == failed["gate_id"]
                    or any(passed.get(key) != failed.get(key) for key in scope)):
                continue
            new_audit = passed.get("audit_log") or {}
            new = new_audit.get("agent_completion")
            attempt = new_audit.get("agent_attempt")
            if (not isinstance(new, dict) or not isinstance(attempt, dict)
                    or new.get("schema") != "guardian_agent_attempt.v1"
                    or new.get("status") != "completed" or new.get("validated") is not True
                    or new.get("success") is not True or not new.get("attempt_id")
                    or new["attempt_id"] == old["attempt_id"]
                    or any(new.get(key) != old.get(key) for key in ("work_id", "specimen_id", "candidate_id", "task_id"))
                    or any(new.get(key) != attempt.get(key) for key in ("schema", "work_id", "attempt_id", "specimen_id", "candidate_id", "task_id"))):
                continue
            try:
                newer = datetime.fromisoformat(passed["created_at"]) > datetime.fromisoformat(failed["created_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if not newer:
                continue
            resolution = {"resolved_by": passed["gate_id"], "resolved_at": passed["created_at"],
                          "resolution": "validated_same_work_retry_completed", "resolution_evidence": deepcopy(new)}
            audit.update(lifecycle="resolved", **resolution)
            action_ids = {item.get("action_id") for item in failed.get("corrective_actions", []) if isinstance(item, dict)}

            def matching_record(record: dict[str, Any]) -> bool:
                return all(key not in record or record[key] == failed.get(key)
                           for key in ("run_id", "experiment_id", "loop_id", "stage", "phase", "agent"))

            for incident in [*incidents, *failed.get("incident_records", [])]:
                if isinstance(incident, dict) and incident.get("incident_id") == failed["gate_id"] and matching_record(incident):
                    action_ids.update(incident.get("corrective_action_refs") or [])
                    incident.update(status="resolved", **deepcopy(resolution))
            for action in [*corrective_actions, *failed.get("corrective_actions", [])]:
                if isinstance(action, dict) and action.get("action_id") in action_ids and matching_record(action):
                    action.update(status="resolved", **deepcopy(resolution))
            break


def resolve_image_rechecks(gates: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> None:
    # Retain the existing caller surface; new checks remain independently scoped.
    resolve_preprint_rechecks(gates, incidents)
    scope_fields = ("run_id", "experiment_id", "loop_id", "stage", "phase", "tool", "action")
    wrappers = {"ROS_IMAGE_FRAME_UNAVAILABLE", "ROS_IMAGE_TIMEOUT", "MISSING_REQUIRED_INPUT",
                "SYSTEM_SAFE_STOP_RECOMMENDED", "VISION_REVIEW_REQUIRED"}
    for index, failed in enumerate(gates):
        if not isinstance(failed, dict) or failed.get("decision") not in {"block", "safe_stop"}:
            continue
        if failed.get("stage") != "vision" or failed.get("phase") != "post":
            continue
        # Incomplete UI projections are not proof that two checks are equivalent.
        check_scope = (failed.get("audit_log") or {}).get("check_scope")
        if not check_scope or any(failed.get(key) in (None, "") for key in ("gate_id", "run_id", "experiment_id")) or failed.get("loop_id") is None:
            continue
        def legacy_camera_alarm(alarm):
            return (alarm.get("reason_code") == "UTM_MACRO_MISMATCH" and
                (alarm.get("message"), alarm.get("source_path")) in {
                    ("UTM Vision runtime is not running; ROS frame capture was skipped.", "payload.observation.utm_clear_verification"),
                    ("UTM_CLEAR_PENDING_TIMEOUT", "payload")})

        legacy = check_scope == "utm_clearance" and any(
            legacy_camera_alarm(alarm) for alarm in failed.get("alarms", []) if isinstance(alarm, dict))
        codes = {
            alarm.get("reason_code") for alarm in failed.get("alarms", []) if isinstance(alarm, dict)
            # A failed execution archive repeats its status as a schema alarm;
            # it is not a separate equipment or measurement-contract hazard.
            and not (alarm.get("reason_code") == "CONTRACT_SCHEMA_INVALID"
                     and alarm.get("source_path") == "payload.artifact_execution")
            and not (legacy and legacy_camera_alarm(alarm))
        }
        if (not legacy and not codes.intersection({"ROS_IMAGE_FRAME_UNAVAILABLE", "ROS_IMAGE_TIMEOUT"})) or not codes <= wrappers:
            continue
        for passed in gates[index + 1:]:
            if not isinstance(passed, dict) or passed.get("decision") != "allow" or passed.get("ok_for_next_stage") is not True:
                continue
            if not passed.get("gate_id") or passed.get("gate_id") == failed["gate_id"]:
                continue
            if any(passed.get(key) != failed.get(key) for key in scope_fields):
                continue
            if (passed.get("audit_log") or {}).get("check_scope") != check_scope:
                continue
            if legacy:
                new_audit = passed.get("audit_log") or {}
                proof = new_audit.get("clearance_completion") or {}
                old = failed["audit_log"].get("agent_attempt") or {}
                new = new_audit.get("agent_attempt") or {}
                if (proof.get("verified") is not True or not proof.get("session_id")
                        or any(not old.get(k) or old[k] != new.get(k) for k in ("work_id", "specimen_id", "task_id"))
                        or proof.get("specimen_id") != old["specimen_id"]
                        or any(proof.get(k) != failed.get(k) for k in ("run_id", "loop_id"))):
                    continue
            if not failed.get("created_at") or str(passed.get("created_at", "")) <= str(failed["created_at"]):
                continue
            failed["audit_log"].update(lifecycle="resolved", resolved_by=passed["gate_id"], resolved_at=passed["created_at"])
            for incident in incidents:
                if isinstance(incident, dict) and incident.get("incident_id") == failed["gate_id"]:
                    incident.update(status="resolved", resolved_by=passed["gate_id"], resolved_at=passed["created_at"])
            break


def resolve_preprint_rechecks(gates, incidents):
    """Resolve manufacturing holds only with a newer same-specimen passing SPC attempt."""
    scope = ('run_id', 'experiment_id', 'loop_id', 'stage', 'phase', 'agent', 'tool', 'action')
    for index, failed in enumerate(gates):
        if (not isinstance(failed, dict) or failed.get('stage') != 'specimen' or failed.get('phase') != 'post'
                or failed.get('decision') != 'block' or failed.get('reason_code') != 'MANUFACTURABILITY_REJECTED'):
            continue
        audit = failed.get('audit_log') or {}
        old = audit.get('preprint_validation') or {}
        if (not all(failed.get(k) for k in ('gate_id','run_id','experiment_id','created_at'))
                or failed.get('loop_id') is None or not old.get('specimen_id') or not old.get('execution_id')
                or old.get('execution_status') != 'failed' or old.get('manufacturability') != 'fail'
                or old.get('wall_status') not in {'fail','unverified'}
                or not isinstance(old.get('attempt_index'), int)):
            continue
        # A nested contract/hardware failure is not a manufacturing-summary wrapper.
        allowed = True
        for alarm in failed.get('alarms', []):
            code, path = alarm.get('reason_code'), alarm.get('source_path', '')
            if code == 'MANUFACTURABILITY_REJECTED' and path == 'payload':
                continue
            if (code in {'CONTRACT_SCHEMA_INVALID','RESULT_NOT_OK','WARN'}
                    and (path in {'payload.fabrication_report.fabrication_outcome', 'payload.specimen_result',
                                  'payload.specimen_result.manufacturability', 'payload.artifact_execution'}
                         or path in {f'payload.fabrication_report.quality_gates[{i}]' for i in range(4)}
                         or (code == 'WARN' and path == 'payload.fabrication_report.quality_gates[4]'))):
                continue
            allowed = False
        if not allowed:
            continue
        for passed in gates[index + 1:]:
            if not isinstance(passed, dict) or any(passed.get(k) != failed.get(k) for k in scope):
                continue
            new = (passed.get('audit_log') or {}).get('preprint_validation') or {}
            if (passed.get('decision') not in {'allow','allow_with_warning'} or passed.get('ok_for_next_stage') is not True
                    or not passed.get('gate_id') or str(passed.get('created_at','')) <= str(failed['created_at'])
                    or new.get('specimen_id') != old['specimen_id'] or not new.get('execution_id')
                    or new['execution_id'] == old['execution_id'] or new.get('execution_status') != 'completed'
                    or not isinstance(new.get('attempt_index'), int) or new['attempt_index'] <= old['attempt_index']
                    or any(new.get(k) != 'pass' for k in ('geometry','mesh','manufacturability','wall_status'))
                    or not isinstance(new.get('stl_sha256'), str) or len(new['stl_sha256']) != 64
                    or any(char not in '0123456789abcdef' for char in new['stl_sha256'])):
                continue
            audit.update(lifecycle='resolved', resolved_by=passed['gate_id'], resolved_at=passed['created_at'],
                         resolution='same_specimen_preprint_revalidated', resolved_execution_id=new['execution_id'])
            for incident in incidents:
                if isinstance(incident, dict) and incident.get('incident_id') == failed['gate_id']:
                    incident.update(status='resolved', resolved_by=passed['gate_id'], resolved_at=passed['created_at'])
            break
