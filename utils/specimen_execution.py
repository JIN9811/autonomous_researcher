"""SPC lifecycle projection and run-scoped printer prerequisite verification.

No function here actuates a device. Vision uses the prerequisite check before
accepting physical ejection evidence; the display uses the same check.
"""
from typing import Any

from orchestrator.state import AgentRuntimeStatus, OrchestratorState, Stage


def current_printer_execution_verified(state: OrchestratorState, specimen: dict[str, Any]) -> bool:
    """Physical image checks cannot substitute for this cycle's printer execution.

    This verifies the printer-job prerequisite, not that an ejection physically
    succeeded. Virtual fixtures retain their separate simulated semantics.
    """
    path = str(specimen.get("printer_path") or "")
    physical = path in {"installed_printer", "physical_print", "actual_print", "bambulab_x2d", "live", "bambu", "prusalink"}
    if not physical:
        intent = (specimen.get("fabrication_report") or {}).get("fabrication_intent") or {}
        physical = intent.get("physical_intent") is True
    if not physical:
        return True
    receipt = specimen.get("printer_completion_wait") or {}
    specimen_id = state.current_experiment_spec.get("specimen_id")
    return bool(
        specimen_id
        and receipt.get("status") == "complete"
        and receipt.get("run_id") == state.run_id
        and receipt.get("loop_id") == state.loop_count
        and receipt.get("specimen_id") == specimen_id
        and receipt.get("completion_scope") == "printer_job_only"
    )


def sync_specimen_execution_status(
    state: OrchestratorState, stage: Stage, data: dict[str, Any] | None = None, *, failed: bool = False,
) -> None:
    data = data or {}
    metadata = state.run_metadata
    if stage == Stage.SPECIMEN and not failed:
        # Only a new SPC result starts an execution. Never reuse old Vision flags.
        specimen = data.get("specimen_result") or {}
        report = specimen.get("fabrication_report") or {}
        outcome = report.get("fabrication_outcome") or {}
        if (outcome.get("requires_after_print_confirmation") is not True
                or outcome.get("status") == "preflight_complete"):
            metadata.pop("specimen_execution", None)
            return
        metadata["specimen_execution"] = {
            "run_id": state.run_id, "loop_id": state.loop_count,
            "specimen_id": specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id", ""),
            "state": "running", "success": None,
        }
    elif stage not in {Stage.SPECIMEN, Stage.VISION}:
        return

    execution = metadata.get("specimen_execution")
    if not isinstance(execution, dict) or (
        execution.get("run_id") != state.run_id or execution.get("loop_id") != state.loop_count
        or execution.get("specimen_id") != state.current_experiment_spec.get("specimen_id")
    ):
        return
    if failed:
        execution.update(state="error", success=False)
    elif stage == Stage.VISION:
        # Later UTM observation owns placement verification, not fabrication.
        if data.get("transition_decision") in {"vision_utm_monitoring", "vision_equipment_handoff"}:
            return
        signal = data.get("vision_signal") or {}
        matching = (
            signal.get("run_id") == execution["run_id"]
            and signal.get("specimen_id") == execution["specimen_id"]
            and signal.get("loop_id") in (execution["loop_id"], f"loop-{execution['loop_id']}")
        )
        if not matching or execution.get("state") == "error":
            return
        observation = data.get("observation") or {}
        confirmation = observation.get("spc_autoejection_confirmation")
        active_check = observation.get("active_cam_ejection_check")
        if not isinstance(confirmation, dict) and not isinstance(active_check, dict):
            return
        # If both forms are present, neither may contradict confirmation.
        checks = []
        if isinstance(confirmation, dict):
            checks.append(confirmation.get("confirmed") is True and confirmation.get("status") == "confirmed")
        if isinstance(active_check, dict):
            checks.append(active_check.get("spc_autoejection_confirmed") is True and active_check.get("status") == "confirmed")
        verified = all(checks) and current_printer_execution_verified(state, metadata.get("specimen_result") or {})
        execution.update(state="done" if verified else "running", success=True if verified else None)

    status = state.agent_status.setdefault("specimen_agent", AgentRuntimeStatus(mode=state.mode.value))
    status.state, status.success = execution["state"], execution["success"]
    status.last_result = {
        "done": "Specimen ejection verified by ActiveCam",
        "error": "Specimen execution failed or was blocked",
    }.get(execution["state"], "Printer execution / ActiveCam verification pending")
