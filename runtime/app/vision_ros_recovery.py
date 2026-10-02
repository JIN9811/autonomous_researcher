"""Resume failed ROS observation without replaying completed work, then continue the series."""
import asyncio
from copy import deepcopy

from orchestrator.state import Stage


def validate(controller):
    state = controller._state
    if controller.snapshot().get("is_running") or controller._planning_request_lock.locked() or controller._planning_handoff_active():
        raise ValueError("Vision recovery requires an inactive workflow")
    if state.stage not in {Stage.COMPLETE, Stage.ERROR}:
        raise ValueError("Vision recovery requires a terminal boundary")
    if controller._active_safety_sources() or any(getattr(state, k) for k in
            ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise ValueError("Resolve safety controls before Vision recovery")
    data = state.run_metadata.get("vision_agent_payload") or {}
    capture = (data.get("observation") or {}).get("raw_capture") or {}
    interlock = capture.get("post_place_interlock") or {}
    owner = state.agent_status.get("vision_agent")
    if (data.get("failure_code") not in {"VISION_ROS_STOP_UNCONFIRMED", "VISION_ROS_RESTART_UNCONFIRMED"}
            or not owner or owner.success is not False or owner.run_id != state.run_id or owner.loop_id != state.loop_count
            or capture.get("specimen_id") != state.current_experiment_spec.get("specimen_id")
            or capture.get("run_id") != state.run_id
            or not interlock.get("session_id") or interlock.get("ready_for_utm_snapshot") is not True
            or interlock.get("home_after_ungrasping") is not True):
        raise ValueError("No same-cycle post-home ROS failure to resume")
    for name in ("equipment_agent", "analysis_agent", "bo_agent"):
        downstream = state.agent_status.get(name)
        if downstream and downstream.run_id == state.run_id and downstream.loop_id == state.loop_count:
            raise ValueError("Downstream execution exists; refusing to repeat it")
    return {"run_id": state.run_id, "loop_id": state.loop_count,
            "specimen_id": state.current_experiment_spec["specimen_id"], "session_id": interlock["session_id"]}


async def resume(controller):
    async with controller._error_resume_lock:
        state = controller._state
        record = state.run_metadata.get("vision_ros_retry") or {}
        if record.get("status") == "running" and controller._planning_handoff_active():
            return {"ok": True, "status": "already_resuming"}
        try:
            boundary = validate(controller)
            if record.get("status") != "ready" or any(record.get(k) != v for k, v in boundary.items()):
                raise ValueError("Prepared Vision ROS recovery no longer matches")
        except ValueError as exc:
            return {"ok": False, "status": "blocked", "message": str(exc)}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        spec = deepcopy(state.current_experiment_spec)
        record["status"] = "running"
        state.is_paused = False
        state.retry_counters.pop("vision", None)

        async def continue_cycle():
            try:
                context = state.run_metadata.get("_planning_resume_context") or {}
                result = await controller._run_planning_cycle_series(first_spec=spec,
                    design_constraints=deepcopy(context.get("design_constraints") or {}),
                    start_cycle=boundary["loop_id"] + 1, resume_tail_stage=Stage.VISION)
                failed = any(owner.success is False and owner.run_id == state.run_id and owner.loop_id == state.loop_count
                             for owner in state.agent_status.values())
                record.update(status="finished" if result.get("ok") and not failed else "needs_attention", result=result)
            except Exception as exc:
                record.update(status="needs_attention", error=f"{type(exc).__name__}: {exc}")
                state.stage = Stage.ERROR
                state.is_paused = True
            finally:
                await controller._emit_control_event("vision_ros_retry.finished", "Recovered workflow returned through the normal cycle series", dict(record))
        controller._set_planning_handoff_task(asyncio.create_task(continue_cycle()))
        return {"ok": True, "status": "resuming", "resume_stage": "vision", "one_cycle_only": False, **boundary}


async def resume_completed_cycle(controller, *, recovery_key="vision_ros_retry"):
    """Compatibility for the old one-cycle recovery already stopped at next Design."""
    async with controller._error_resume_lock:
        state = controller._state
        record = state.run_metadata.get(recovery_key) or {}
        result = record.get("result") or {}
        if controller._planning_handoff_active():
            return {"ok": True, "status": "already_resuming"}
        if (record.get("status") != "cycle_finished" or record.get("run_id") != state.run_id
                or state.stage != Stage.DESIGN or not state.is_paused
                or state.loop_count != int(record.get("loop_id", -2)) + 1
                or result.get("ok") is not True or result.get("decision") != "continue"
                or (state.run_metadata.get("guardian") or {}).get("decision") != "continue"
                or controller.snapshot().get("is_running") or controller._planning_request_lock.locked()
                or controller._active_safety_sources() or any(getattr(state, k) for k in
                    ("stop_requested", "safe_stop_requested", "emergency_stop_requested"))):
            return {"ok": False, "status": "blocked", "message": "Completed ROS cycle boundary no longer matches"}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        spec = deepcopy(state.current_experiment_spec)
        cycle = state.loop_count + 1
        if cycle > controller._planning_cycle_limit(spec):
            return {"ok": False, "status": "complete", "message": "No cycles remain"}
        context = state.run_metadata.get("_planning_resume_context") or {}
        constraints = deepcopy(context.get("design_constraints") or {})
        record["status"] = "continuing"
        state.is_paused = False

        async def continue_series():
            try:
                outcome = await controller._run_planning_cycle_series(first_spec=spec,
                    design_constraints=constraints, start_cycle=cycle, start_with_design=True)
                record.update(status="finished" if outcome.get("ok") else "needs_attention", result=outcome)
            except Exception as exc:
                record.update(status="needs_attention", error=f"{type(exc).__name__}: {exc}")
                state.stage, state.is_paused = Stage.ERROR, True
        controller._set_planning_handoff_task(asyncio.create_task(continue_series()))
        return {"ok": True, "status": "resuming", "resume_stage": "design", "cycle_index": cycle, "run_id": state.run_id}
