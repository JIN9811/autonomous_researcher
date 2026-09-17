"""Re-review a rejected, never-executed selection at a paused Guardian boundary."""
from copy import deepcopy
import json
from pathlib import Path


def validate_selection_boundary(state, record):
    from orchestrator.state import Stage
    if state.stage != Stage.GUARDIAN or not state.is_paused:
        raise ValueError("Selection recovery requires paused Guardian")
    if any(getattr(state, k) for k in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise ValueError("Safety controls prohibit selection recovery")
    identity = record.get("identity") or {}
    if any(identity.get(k) != v for k, v in {"run_id":state.run_id,
        "experiment_id":state.experiment_id, "specimen_id":state.current_experiment_spec.get("specimen_id"),
        "sequence_id":f"stacked-loop-{state.loop_count}"}.items()):
        raise ValueError("Selection recovery identity mismatch")
    data = (record.get("workflow_result") or {}).get("data") or {}
    decisions = data.get("equipment_decisions") or []
    selection = decisions[0] if len(decisions) == 1 else {}
    # A pre-model adapter error has no selected command. Combined with the
    # lifecycle proof below, it is as non-actuating as an operator-review choice.
    pre_model_type_error = (selection.get('phase') == 'select'
        and selection.get('llm_used') is False and selection.get('request') is None
        and selection.get('scope_valid') is True and 'evidence' not in selection
        and selection.get('error') == 'TypeError: decision could not be validated')
    if (record.get("lifecycle") != "ESCALATED"
        or data.get("failure_code") != "EQUIPMENT_WORKFLOW_SELECTION_REJECTED"
        or len(decisions) != 1 or decisions[0].get("phase") != "select"
        or ((selection.get("request") or {}).get("tool") != "request_operator" and not pre_model_type_error)
        or not record.get("events")
        or any(e.get("lifecycle") not in {"RESOLVING", "ESCALATED"} for e in record["events"])):
        raise ValueError("Cannot prove Equipment was never executed")
    scope = state.run_metadata.get("utm_verifications") or {}
    first = scope.get("verification_1") or {}
    evidence = first.get("evidence") or {}
    execution = state.run_metadata.get("manipulation_execution") or {}
    for key, value in {"run_id":state.run_id,"loop_id":state.loop_count,
                       "specimen_id":state.current_experiment_spec.get("specimen_id")}.items():
        if scope.get(key) != value or execution.get(key) != value:
            raise ValueError("Transfer scope mismatch")
    if (first.get("confirmed") is not True or execution.get("state") != "done"
        or execution.get("success") is not True or not execution.get("session_id")
        or evidence.get("session_id") != execution["session_id"]
        or evidence.get("rollout_stopped") is not True or evidence.get("rollout_stop_status") != "STOPPED"):
        raise ValueError("Verified stopped transfer required")


def selection_recovery_inputs(controller):
    from agents.equipment.agent import LabEquipmentAgent
    from app.run_recovery import run_directory
    from utils.equipment_runtime_service import EquipmentRuntimeService
    state = controller._state
    if controller._active_safety_sources():
        raise ValueError("Active safety sources prohibit recovery")
    root = run_directory(controller._deps.run_root, state.run_id)
    loop = root / f"runtime/loops/loop-{state.loop_count + 1:06d}"
    attempts = sorted((loop / "equipment_agent").glob("attempt-*/result.json"))
    if not attempts:
        raise ValueError("Current-cycle Equipment archive missing")
    archived_equipment = json.loads(attempts[-1].read_text())
    data = archived_equipment.get("data") or {}
    if archived_equipment.get("status") != "failed" or data.get("failure_code") != "EQUIPMENT_WORKFLOW_SELECTION_REJECTED":
        raise ValueError("Only rejected selection can be reviewed")
    record = EquipmentRuntimeService(LabEquipmentAgent._RUNTIME_ROOT / "workflow_decisions").get(data["equipment_workflow_execution_id"])
    validate_selection_boundary(state, record)
    paths = sorted((root / f"runtime/loops/loop-{state.loop_count + 1:06d}/specimen_agent").glob("attempt-*/result.json"))
    if not paths:
        raise ValueError("Current-cycle specimen archive missing")
    archived = json.loads(paths[-1].read_text())
    specimen = (archived.get("data") or {}).get("specimen_result") or {}
    current = state.run_metadata.get("specimen_result") or {}
    if (archived.get("status") != "completed" or not specimen.get("specimen_id")
        or any(current.get(k) != specimen.get(k) for k in ("specimen_id", "candidate_id"))
        or specimen["specimen_id"] != state.current_experiment_spec.get("specimen_id")):
        raise ValueError("Specimen archive identity mismatch")
    corrected = deepcopy(current)
    for key, value in (("run_id", state.run_id), ("loop_id", state.loop_count)):
        if corrected.get(key) not in (None, value):
            raise ValueError("Conflicting specimen scope")
        corrected[key] = value
    corrected["identity_source"] = str(paths[-1])
    return record, corrected
