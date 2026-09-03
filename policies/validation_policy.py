"""
File purpose:
- Validate core stage output schemas and state consistency.

Key classes/functions:
- validate_agent_output

Inputs/outputs:
- Input: stage and output payload
- Output: bool validity and optional message

Dependencies:
- none

Modification guide:
- Safe places to edit: stage-specific required keys
- Risky places to edit: strictness may break stage transitions
- Related files: orchestrator/run_loop.py, tests/integration/test_loop.py
"""

from __future__ import annotations


_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "design": ("experiment_spec",),
    "vision": ("observation",),
    "equipment": ("equipment_result", "protocol_note"),
    "analysis": ("analysis",),
    "guardian": ("guardian",),
}


def validate_agent_output(stage: str, payload: dict[str, object]) -> tuple[bool, str]:
    """Validate required payload keys for selected stages."""
    required = _REQUIRED_KEYS.get(stage, ())
    missing = [key for key in required if key not in payload]
    if missing:
        return False, f"Missing required keys for stage={stage}: {missing}"
    if stage == "specimen" and isinstance(payload.get("printer_preflight"), dict):
        preflight = payload["printer_preflight"]
        valid_preflight = bool(
            preflight.get("schema") == "printer_preflight.v1"
            and preflight.get("status") == "execution_ready_pending_approval"
            and preflight.get("actuation_performed") is False
            and preflight.get("upload_performed") is False
            and preflight.get("start_command_published") is False
        )
        if not valid_preflight:
            return False, "Invalid printer_preflight no-actuation contract."
        fabricated = payload.get("specimen_fabricated")
        if not (
            isinstance(fabricated, dict)
            and fabricated.get("schema") == "specimen_fabricated.v1"
            and fabricated.get("status") == "preflight_ready"
            and fabricated.get("physical_location") == "not_actuated"
        ):
            return False, "Invalid specimen preflight handoff contract."
    if stage == "equipment":
        result = payload.get("equipment_result")
        if not isinstance(result, dict):
            return False, "Invalid equipment_result payload."
        if result.get("ok") is False:
            failure_code = result.get("failure_code") or result.get("status") or "unknown"
            return False, f"Equipment stage failed: {failure_code}"
        preflight = payload.get("equipment_preflight")
        valid_no_actuation_preflight = bool(
            isinstance(preflight, dict)
            and preflight.get("schema") == "equipment_preflight.v1"
            and preflight.get("status") == "execution_ready_pending_approval"
            and preflight.get("actuation_performed") is False
            and preflight.get("resolved_program_id") == "run_utm_compression_cycle"
            and result.get("status") == "execution_ready_pending_approval"
            and result.get("actuation_performed") is False
        )
        handoff = payload.get("equipment_handoff")
        if isinstance(handoff, dict) and handoff.get("status") != "ready_for_analysis" and not valid_no_actuation_preflight:
            failure_code = handoff.get("failure_code") or handoff.get("status") or "unknown"
            return False, f"Equipment handoff blocked: {failure_code}"
        packet = payload.get("utm_data_ready")
        if isinstance(packet, dict) and packet.get("status") != "ready" and not valid_no_actuation_preflight:
            failure_code = packet.get("failure_code") or packet.get("status") or "unknown"
            return False, f"UTM data handoff blocked: {failure_code}"
        report = payload.get("equipment_report")
        if isinstance(report, dict):
            cross_checks = report.get("cross_checks") if isinstance(report.get("cross_checks"), dict) else {}
            required_checks = ("screen_started", "physical_motion_started", "save_completed", "data_file_created", "data_parse_probe_ok")
            failed_checks = [name for name in required_checks if cross_checks.get(name) is False]
            if failed_checks:
                return False, f"Equipment verification checks failed: {failed_checks}"
    if stage == "analysis":
        result = payload.get("analysis")
        if not isinstance(result, dict):
            return False, "Invalid analysis payload."
        if result.get("ok") is False:
            failure_code = result.get("failure_code") or "unknown"
            return False, f"Analysis stage failed: {failure_code}"
    return True, "ok"
