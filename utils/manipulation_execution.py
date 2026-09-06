"""Shared display lifecycle for asynchronous, run-scoped manipulation work.

This is observation bookkeeping only, never an authorization or motion gate.
"""
from orchestrator.state import AgentRuntimeStatus, OrchestratorState, Stage


def sync_manipulation_execution_status(state: OrchestratorState, stage: Stage, *, failed: bool = False) -> None:
    metadata = state.run_metadata
    from utils.utm_clear_cycle import current_clear, sync_clear_status
    if current_clear(state):
        sync_clear_status(state, failed=failed)
        return  # Clearance has its own lifecycle; retain the initial VLA transfer.
    if stage == Stage.MANIPULATION and not failed:
        task = metadata.get("robot_task_result") or {}
        response = metadata.get("manipulation_result") or {}
        session_id = task.get("rollout_session_id") or response.get("session_id")
        if not session_id or str(response.get("status", "")).upper() not in {
            "ACTIVE", "POLICY_ACTIVE", "RUNNING", "STARTING", "STOPPING", "STOPPED",
        }:
            metadata.pop("manipulation_execution", None)
            return
        metadata["manipulation_execution"] = {
            "run_id": state.run_id, "loop_id": state.loop_count,
            "specimen_id": task.get("specimen_id") or state.current_experiment_spec.get("specimen_id", ""),
            "session_id": session_id,
            "state": "waiting" if str(response.get("status", "")).upper() in {"STOPPING", "STOPPED"} else "running",
            "success": None,
        }
    elif stage not in {Stage.MANIPULATION, Stage.VISION}:
        return
    execution = metadata.get("manipulation_execution")
    if not isinstance(execution, dict) or (
        execution.get("run_id") != state.run_id or execution.get("loop_id") != state.loop_count
        or execution.get("specimen_id") != state.current_experiment_spec.get("specimen_id")
    ):
        return
    completion = state.latest_observations.get("vision_manipulation_completion", {})
    matching = isinstance(completion, dict) and all(
        completion.get(key) == execution.get(key) for key in ("run_id", "loop_id", "specimen_id", "session_id")
    )
    if failed:
        execution.update(state="error", success=False)
    elif stage == Stage.VISION and matching and execution.get("state") != "error":
        interlock = completion.get("post_place_interlock")
        verified = (
            completion.get("detected") is True and completion.get("ready_to_stop_rollout") is True
            and completion.get("rollout_stopped") is True and completion.get("rollout_stop_status") == "STOPPED"
            and not completion.get("blocking_reason") and isinstance(interlock, dict)
            and interlock.get("ready_for_utm_snapshot") is True
        )
        if verified:
            execution.update(state="done", success=True)
        elif execution.get("state") != "done" and (
            completion.get("rollout_stopped") is True or completion.get("ready_to_stop_rollout") is True
        ):
            execution.update(state="waiting", success=None)
    status = state.agent_status.setdefault("manipulation_agent", AgentRuntimeStatus(mode=state.mode.value))
    status.state, status.success = execution["state"], execution["success"]
    status.last_result = {
        "done": "Transfer verified and rollout stopped",
        "error": "Manipulation execution failed or was blocked",
    }.get(execution["state"], "Transfer execution / Vision verification pending")
