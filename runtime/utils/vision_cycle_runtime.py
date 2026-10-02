"""Replace ROS once at cycle admission, not inside observation checkpoints."""
import asyncio

from device_bridges.camera_vision.tools import _reload_vision_cycle
from utils.test_mode_execution_profiles import is_resolved_all_virtual_bridge


async def prepare_cycle_vision_runtime(state, ctx, cycle_index):
    spec = state.current_experiment_spec
    if is_resolved_all_virtual_bridge(spec, mode=state.mode):
        return {"ok": True, "status": "virtual_bridge_selected"}
    required = {"vision.utm_runtime.start", "vision.utm_runtime.stop", "vision.utm_runtime.status"}
    tools = getattr(ctx, "tools", None)
    if not required.issubset(getattr(tools, "list_tools", lambda: [])()):
        return {"ok": True, "status": "runtime_not_configured"}
    if any(getattr(state, key, False) for key in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise RuntimeError("ROS cycle reload rejected: run is stopped")
    key = [state.run_id, "cycle_start", int(cycle_index)]
    cached = state.run_metadata.get("vision_cycle_ros_reload") or {}
    if cached.get("key") == key and cached.get("ok") is True:
        return cached
    payload = {"run_id": state.run_id, "cycle_index": int(cycle_index), "source": "cycle_start_reload"}
    result = await asyncio.to_thread(_reload_vision_cycle, tuple(key),
        lambda: tools.call("vision.utm_runtime.stop", payload),
        lambda: tools.call("vision.utm_runtime.start", payload),
        lambda: tools.call("vision.utm_runtime.status", payload))
    if state.run_id != key[0]:
        raise RuntimeError("Run changed during ROS cycle reload")
    record = {"key": key, **result}
    state.run_metadata["vision_cycle_ros_reload"] = record
    if result.get("ok") is not True:
        raise RuntimeError(result.get("failure_code") or "VISION_ROS_RELOAD_FAILED")
    return record
