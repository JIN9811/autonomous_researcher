"""Distinguish a scoped placement wait from an ordinary workflow step."""
from orchestrator.state import Stage


def vision_poll_pending(state):
    from utils.utm_clear_cycle import current_clear
    clear = current_clear(state)
    return state.stage == Stage.VISION and (placement_poll_pending(state) or
        clear.get("state") in {"starting", "running", "waiting"})


def quiet_vision_poll_event(state, event):
    """Suppress chat only; callers still broadcast/log all runtime evidence."""
    payload = event.get("payload") or {}
    kind = event.get("type") or event.get("event_type")
    if kind not in {"node.started", "node.completed", "orchestrator.followup"}:
        return False
    if str(event.get("level", "")).upper() in {"ERROR", "CRITICAL"}:
        return False
    data = payload.get("result") or {}
    followup = payload.get("orchestrator_followup") or {}
    if (payload.get("requires_response") or data.get("pending_operator_input")
            or data.get("failure_code") or data.get("safe_stop_recommended")
            or followup.get("requires_response") or followup.get("status") == "error"):
        return False
    stage = payload.get("node_id") or event.get("node_id") or followup.get("stage")
    if stage != "vision":
        return False
    return vision_poll_pending(state)


def placement_poll_pending(state):
    if state.stage != Stage.VISION:
        return False
    metadata = state.run_metadata
    scope = {"run_id": state.run_id, "loop_id": state.loop_count,
             "specimen_id": state.current_experiment_spec.get("specimen_id")}
    execution = metadata.get("manipulation_execution") or {}
    verifications = metadata.get("utm_verifications") or {}
    evidence = (verifications.get("verification_1") or {}).get("evidence") or {}
    if not scope["specimen_id"] or not execution.get("session_id"):
        return False
    if any(value.get(key) != expected for value in (execution, verifications, evidence)
           for key, expected in scope.items()):
        return False
    return (execution.get("state") in {"running", "waiting"}
            and evidence.get("session_id") == execution["session_id"]
            and evidence.get("status") == "waiting"
            and evidence.get("detected") is False)
