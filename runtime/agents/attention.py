"""Owner-issued presentation requests. Never authorize or execute device actions."""
import inspect


CHECKPOINTS = {
    "design": {"handoff": "report"},
    "specimen": {"print_started": "printer_video"},
    "vision": {"active_cam": "active_cam", "placement_home": "verification_1", "replay_complete": "verification_2"},
    "manipulation": {"inference_started": "report"},
    "equipment": {"handoff": "report"},
    "analysis": {"handoff": "report"},
    "knowledge": {"handoff": "report"},
    "bo": {"handoff": "report"},
}


async def request_attention(state, ctx, agent_id, checkpoint):
    action = CHECKPOINTS.get(agent_id, {}).get(checkpoint)
    callback = getattr(ctx, "emit_execution_event", None)
    if not action or not callable(callback):
        return False
    if str(getattr(state.mode, "value", state.mode)) == "replay" or any(
        getattr(state, flag, False) for flag in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")
    ):
        return False
    spec = state.current_experiment_spec or {}
    key = f"{state.run_id}:{state.loop_count}:{spec.get('specimen_id', '')}:{agent_id}:{checkpoint}"
    sent = state.run_metadata.setdefault("agent_attention_sent", [])
    if key in sent:
        return False
    sent.append(key)
    del sent[:-128]
    try:
        result = callback({"type": "agent.attention_requested", "payload": {
            "schema": "agent_attention.v1", "run_id": state.run_id,
            "loop_index": state.loop_count, "invocation_id": key,
            "attention_id": key, "module_id": agent_id, "agent_id": agent_id,
            "checkpoint": checkpoint, "view_action": action, "status": "attention",
            "presentation_only": True,
        }})
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Presentation failure cannot fail an experiment or replay an effect.
        if key in sent:
            sent.remove(key)
        return False
    return True
