"""Resolve transient image-read holds only after a matching successful recheck."""

from typing import Any


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
