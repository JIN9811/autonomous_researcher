"""Resolve transient image-read holds only after a matching successful recheck."""

from typing import Any


def resolve_image_rechecks(gates: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> None:
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
        codes = {
            alarm.get("reason_code") for alarm in failed.get("alarms", []) if isinstance(alarm, dict)
            # A failed execution archive repeats its status as a schema alarm;
            # it is not a separate equipment or measurement-contract hazard.
            and not (alarm.get("reason_code") == "CONTRACT_SCHEMA_INVALID"
                     and alarm.get("source_path") == "payload.artifact_execution")
        }
        if not codes.intersection({"ROS_IMAGE_FRAME_UNAVAILABLE", "ROS_IMAGE_TIMEOUT"}) or not codes <= wrappers:
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
            if not failed.get("created_at") or str(passed.get("created_at", "")) <= str(failed["created_at"]):
                continue
            failed["audit_log"].update(lifecycle="resolved", resolved_by=passed["gate_id"], resolved_at=passed["created_at"])
            for incident in incidents:
                if isinstance(incident, dict) and incident.get("incident_id") == failed["gate_id"]:
                    incident.update(status="resolved", resolved_by=passed["gate_id"], resolved_at=passed["created_at"])
            break
