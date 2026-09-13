"""Equipment report projection preserving the existing host keys and precedence."""
from __future__ import annotations

import json
from typing import Any


REPORT_PROFILE = {
    "title": "Lab Equipment / UTM Visual Control",
    "summary": "Shows Windows/UTM control trace, screen-state assertions, Vision physical cross-checks, data artifact ledger, and Analysis handoff gate evidence.",
    "focus_rows": [
        {"label": "Control trace", "value": "registered UTM program, macro version, locator backend, bridge provider, and tool result sequence"},
        {"label": "Visual assertion", "value": "before/running/complete screen checks and state-transition evidence"},
        {"label": "Physical check", "value": "Vision-backed fixture, crosshead motion, alignment, and safe-access confirmation"},
        {"label": "Data ledger", "value": "Windows export path, Linux pulled CSV path, checksum, row count, columns, and parse probe"},
        {"label": "Handoff gate", "value": "ready_for_analysis only when screen, physical, save, file, and parse gates all pass"},
    ],
    "checklist": [
        "Confirm bridge/profile readiness",
        "Verify screen assertions",
        "Verify Vision physical checks",
        "Confirm CSV artifact pull",
        "Gate Analysis handoff",
    ],
}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def project_equipment_report(metadata: dict, agent_payload: dict) -> dict:
    """Project only existing Equipment data; no runtime query or persistence occurs."""
    equipment_report = _dict(metadata.get("equipment_report"))
    if not equipment_report:
        equipment_report = _dict(agent_payload.get("equipment_report"))
    equipment_result = (
        metadata["equipment_result"]
        if isinstance(metadata.get("equipment_result"), dict)
        else _dict(agent_payload.get("equipment_result"))
    )
    utm_packet = (
        metadata["utm_data_ready"]
        if isinstance(metadata.get("utm_data_ready"), dict)
        else _dict(agent_payload.get("utm_data_ready"))
    )
    equipment_handoff = (
        metadata["equipment_handoff"]
        if isinstance(metadata.get("equipment_handoff"), dict)
        else _dict(agent_payload.get("equipment_handoff"))
    )
    role_specific: dict[str, Any] = {}
    report_decisions: list = []
    report_metrics: dict = {}

    if equipment_report:
        role_specific["summary"] = (
            "Windows bridge control trace, UTM screen assertions, Vision physical cross-checks, "
            "exported data ledger, and Analysis handoff gate evidence."
        )
        bridge = _dict(equipment_report.get("bridge"))
        control_plan = _dict(equipment_report.get("control_plan"))
        vision_cross_checks = _dict(equipment_report.get("vision_cross_checks"))
        screen_checks = _list(equipment_report.get("screen_checks"))
        physical_checks = _dict(equipment_report.get("physical_checks"))
        data_acquisition = _dict(equipment_report.get("data_acquisition"))
        cross_checks = _dict(equipment_report.get("cross_checks"))
        decision = _dict(equipment_report.get("decision"))
        artifact_records = _list(equipment_report.get("artifact_records"))
        artifact_refs = _list(equipment_report.get("artifact_refs"))
        screen_evidence_refs = _list(equipment_report.get("screen_evidence_refs"))
        data_evidence_refs = _list(equipment_report.get("data_evidence_refs"))
        failure_retry_table = _list(equipment_report.get("failure_retry_table"))
        recovery = _dict(equipment_report.get("recovery"))
        live_evidence_audit = _dict(equipment_report.get("live_evidence_audit"))
        save_export_audit = _dict(live_evidence_audit.get("save_export"))
        hardware_alert = (
            equipment_report["hardware_alert"]
            if isinstance(equipment_report.get("hardware_alert"), dict)
            else metadata["hardware_alert"]
            if isinstance(metadata.get("hardware_alert"), dict)
            else _dict(agent_payload.get("hardware_alert"))
        )
        hardware_alerts = (
            metadata["hardware_alerts"]
            if isinstance(metadata.get("hardware_alerts"), list)
            else _list(agent_payload.get("hardware_alerts"))
        )
        hardware_alerts = [dict(item) for item in hardware_alerts if isinstance(item, dict)]
        if hardware_alert and not any(
            item.get("alert_id") == hardware_alert.get("alert_id") for item in hardware_alerts
        ):
            hardware_alerts.insert(0, hardware_alert)
        incident_records = (
            metadata["incident_records"]
            if isinstance(metadata.get("incident_records"), list)
            else _list(agent_payload.get("incident_records"))
        )
        incident_records = [dict(item) for item in incident_records if isinstance(item, dict)]
        incident_records.extend(
            dict(item) for item in _list(equipment_report.get("incident_records")) if isinstance(item, dict)
        )
        hardware_incident = _dict(hardware_alert.get("incident_record"))
        if hardware_incident:
            incident_records.append(dict(hardware_incident))
        seen_incident_ids: set[str] = set()
        unique_incidents: list[dict[str, Any]] = []
        for incident in incident_records:
            incident_id = str(
                incident.get("incident_id")
                or incident.get("id")
                or json.dumps(incident, sort_keys=True, default=str)
            )
            if incident_id not in seen_incident_ids:
                seen_incident_ids.add(incident_id)
                unique_incidents.append(incident)
        incident_records = unique_incidents
        guardian_decision = _dict(hardware_alert.get("guardian_decision"))
        guardian_contract = _dict(hardware_alert.get("guardian_contract"))
        screen_passed = sum(
            1 for item in screen_checks if isinstance(item, dict) and item.get("ok")
        )

        role_specific.update({
            "bridge": bridge,
            "preconditions": equipment_report.get("preconditions", {}),
            "control_plan": control_plan,
            "vision_requests": equipment_report.get("vision_requests", []),
            "vision_cross_checks": vision_cross_checks,
            "screen_checks": screen_checks,
            "physical_checks": physical_checks,
            "data_acquisition": data_acquisition,
            "cross_checks": cross_checks,
            "decision": decision,
            "control_trace": {
                "bridge_provider": bridge.get("provider", ""),
                "connection_status": bridge.get("connection_status", ""),
                "program_id": control_plan.get("program_id", equipment_result.get("program_id", "")),
                "macro_version": control_plan.get("macro_version", ""),
                "locator_backend": control_plan.get("locator_backend", ""),
                "tool_result_count": len(_list(agent_payload.get("tool_results"))),
            },
            "visual_assertion": {
                "screen_checks_passed": screen_passed,
                "screen_checks_total": len(screen_checks),
                "screen_started": bool(cross_checks.get("screen_started")),
                "checkpoints": [item.get("checkpoint") for item in screen_checks if isinstance(item, dict)],
            },
            "physical_verification": {
                "all_required_ok": bool(vision_cross_checks.get("all_required_ok")),
                "vision_motion_confirmed": bool(physical_checks.get("vision_motion_confirmed")),
                "specimen_alignment_ok": bool(physical_checks.get("specimen_alignment_ok")),
                "fixture_safe_to_access": bool(physical_checks.get("fixture_safe_to_access")),
                "evidence_frame_ids": physical_checks.get("evidence_frame_ids", []),
            },
            "data_ledger": {
                "status": data_acquisition.get("status", ""),
                "save_method": data_acquisition.get("save_method", ""),
                "save_attempted_by_agent": data_acquisition.get(
                    "save_attempted_by_agent", save_export_audit.get("save_attempted_by_agent", "")
                ),
                "save_confirmation_screen_ok": data_acquisition.get(
                    "save_confirmation_screen_ok", save_export_audit.get("save_confirmation_screen_ok", "")
                ),
                "save_export_responsibility_ok": bool(
                    cross_checks.get("save_export_responsibility_ok", save_export_audit.get("ok", False))
                ),
                "recognized_save_method": save_export_audit.get("recognized_save_method", ""),
                "windows_path": data_acquisition.get("windows_path") or save_export_audit.get("windows_path", ""),
                "linux_path": data_acquisition.get("linux_path")
                or save_export_audit.get("linux_path")
                or equipment_result.get("result_file")
                or equipment_result.get("utm_csv_path")
                or "",
                "sha256": data_acquisition.get("sha256", ""),
                "size_bytes": data_acquisition.get("size_bytes", 0),
                "row_count_probe": data_acquisition.get("row_count_probe", 0),
                "columns_probe": data_acquisition.get("columns_probe", []),
                "parse_ready": bool(cross_checks.get("data_parse_probe_ok")),
            },
            "artifact_ledger": {
                "artifact_records": artifact_records,
                "artifact_refs": artifact_refs,
                "screen_evidence_refs": screen_evidence_refs,
                "data_evidence_refs": data_evidence_refs,
                "screen_evidence_count": len(screen_evidence_refs),
                "data_evidence_count": len(data_evidence_refs),
            },
            "failure_recovery": {
                "recovery": recovery,
                "failure_retry_table": failure_retry_table,
                "operator_intervention_required": bool(recovery.get("operator_intervention_required")),
                "retry_count": recovery.get("retry_count", 0),
                "fallback_macros": recovery.get("fallback_macros", []),
            },
        })
        blocked_commands = (
            list(decision.get("blocking_reasons", []))
            if isinstance(decision.get("blocking_reasons"), list)
            else []
        )
        role_specific["safety_gate"] = {
            "guardian_status": (utm_packet or {}).get("guardian_status", "")
            or (
                "block"
                if hardware_alerts or decision.get("failure_code")
                else "allow"
                if (decision.get("handoff_status") or equipment_handoff.get("status"))
                == "ready_for_analysis"
                else "not_checked"
            ),
            "hardware_alert_count": len(hardware_alerts),
            "active_hardware_alert": hardware_alert,
            "incident_records": incident_records,
            "incident_count": len(incident_records),
            "requires_human_approval": bool(
                hardware_alert.get("requires_ack")
                or guardian_decision.get("requires_human_approval")
                or guardian_contract.get("requires_human_approval")
            ),
            "blocks_workflow": bool(
                hardware_alert.get("blocks_workflow")
                or guardian_contract.get("ok_for_next_stage") is False
                or (decision.get("handoff_status") or equipment_handoff.get("status")) == "blocked"
            ),
            "guardian_route_hint": hardware_alert.get(
                "guardian_route_hint", guardian_decision.get("recommended_action", "")
            ),
            "guardian_decision": guardian_decision.get("decision", ""),
            "risk_score": hardware_alert.get("risk_score", guardian_decision.get("risk_score", "")),
            "risk_flags": guardian_contract.get("risk_flags", hardware_alert.get("risk_flags", [])),
            "blocked_commands": blocked_commands,
            "emergency_stop_evidence": {
                "safe_stop_recommended": guardian_decision.get("decision") == "safe_stop"
                or hardware_alert.get("guardian_route_hint") == "stop",
                "route_hint": hardware_alert.get("guardian_route_hint", ""),
                "corrective_action": _dict(hardware_alert.get("incident_record")).get(
                    "corrective_action", ""
                ),
            },
        }
        role_specific["live_evidence_audit"] = live_evidence_audit
        role_specific["handoff_gate"] = {
            "handoff_status": decision.get("handoff_status") or equipment_handoff.get("status"),
            "equipment_status": decision.get("equipment_status") or equipment_result.get("status"),
            "failure_code": decision.get("failure_code") or equipment_result.get("failure_code"),
            "guardian_status": (utm_packet or {}).get("guardian_status", ""),
            "required_gates": cross_checks,
            "save_export_responsibility_ok": bool(
                cross_checks.get("save_export_responsibility_ok", save_export_audit.get("ok", False))
            ),
            "live_evidence_audit": live_evidence_audit,
        }
        role_specific["handoff_packet"] = utm_packet or equipment_handoff
        role_specific["equipment_result"] = {
            "status": equipment_result.get("status", ""),
            "program_id": equipment_result.get("program_id", ""),
            "failure_code": equipment_result.get("failure_code"),
            "result_file": equipment_result.get("result_file") or equipment_result.get("utm_csv_path"),
        }
        report_decisions = (
            [equipment_report.get("decision", {})]
            if isinstance(equipment_report.get("decision"), dict)
            else _list(agent_payload.get("decisions"))
        )
        report_metrics = (
            metadata["equipment_metrics"]
            if isinstance(metadata.get("equipment_metrics"), dict)
            else _dict(agent_payload.get("metrics"))
        )

    return {
        "role_specific": role_specific,
        "decisions": report_decisions,
        "metrics": report_metrics,
        "equipment_report": equipment_report,
        "equipment_result": equipment_result,
        "utm_data_ready": utm_packet,
        "equipment_handoff": equipment_handoff,
    }
