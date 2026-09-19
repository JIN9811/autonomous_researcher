from device_bridges.camera_vision import tools
import pytest


@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    from types import SimpleNamespace
    clock = [0.0]
    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: clock[0],
        time=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))


def test_reload_shared_by_all_checkpoints_once_per_specimen_cycle(monkeypatch):
    monkeypatch.setattr(tools, "_VISION_CYCLE_RELOADS", {})
    state = {"pid": 1, "running": True, "starts": 0}
    def status():
        return {"ok": True, "status": "running" if state["running"] else "stopped",
                "pid": state["pid"] if state["running"] else None}
    def stop():
        state["running"] = False
        return {"ok": True}
    def start():
        state.update(running=True, pid=state["pid"] + 1, starts=state["starts"] + 1)
        return status()
    for _ in range(3):
        result = tools._reload_vision_cycle(("run", "cycle-1-specimen"), stop, start, status)
        assert result["restart_verified"] and result["pid"] == 2
    assert state["starts"] == 1
    tools._reload_vision_cycle(("run", "cycle-2-specimen"), stop, start, status)
    assert state["starts"] == 2


def test_unconfirmed_stop_never_starts_or_claims_ready():
    starts = []
    result = tools._restart_vision_runtime(lambda: {"ok": True},
        lambda: starts.append(True), lambda: {"ok": True, "status": "running", "pid": 1})
    assert not result["ok"] and not starts


def test_same_pid_cannot_confirm_restart():
    samples = iter([{"status": "running", "pid": 1}, {"status": "stopped"},
                    {"status": "running", "pid": 1}])
    result = tools._restart_vision_runtime(lambda: {"ok": True}, lambda: {"ok": True}, lambda: next(samples))
    assert result["failure_code"] == "VISION_ROS_RESTART_UNCONFIRMED"


def test_ros_children_drain_before_start():
    statuses = iter([{"status": "running", "pid": 1},
        {"status": "running", "pid": 2}, {"status": "running", "pid": 2},
        {"status": "stopped"}, {"status": "running", "pid": 3}])
    calls = []
    result = tools._restart_vision_runtime(lambda: {"ok": True},
        lambda: calls.append("start") or {"ok": True}, lambda: next(statuses))
    assert result["restart_verified"] and result["pid"] == 3
    assert calls == ["start"]


def test_failed_reload_can_retry_same_cycle_without_caching_failure_forever(monkeypatch):
    monkeypatch.setattr(tools, "_VISION_CYCLE_RELOADS", {})
    outcomes = iter([{"ok": False, "failure_code": "VISION_ROS_STOP_UNCONFIRMED"},
        {"ok": True, "restart_verified": True, "pid": 4}])
    monkeypatch.setattr(tools, "_restart_vision_runtime", lambda *args: next(outcomes))
    key = ("same-run", "same-specimen")
    assert not tools._reload_vision_cycle(key, None, None, None)["ok"]
    assert tools._reload_vision_cycle(key, None, None, None)["ok"]
    assert tools._reload_vision_cycle(key, None, None, None)["pid"] == 4


def test_capture_checkpoints_never_reload_ros():
    class Manager:
        def stop(self):
            raise AssertionError("Capture must never stop ROS")
    for purpose in ("utm_placement_verification", "utm_clear_verification"):
        assert tools._reload_for_capture({"run_id": "r", "specimen_id": "s", "purpose": purpose}, Manager()) is None


@pytest.mark.asyncio
async def test_cycle_admission_reloads_once_and_next_cycle_reloads_again(monkeypatch):
    from types import SimpleNamespace
    from utils import vision_cycle_runtime as runtime
    monkeypatch.setattr(runtime, "is_resolved_all_virtual_bridge", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(runtime, "_reload_vision_cycle", lambda key, *args: calls.append(key) or {"ok": True, "pid": 4})
    state = SimpleNamespace(run_id="r", mode="live", current_experiment_spec={}, run_metadata={})
    ctx = SimpleNamespace(tools=SimpleNamespace(list_tools=lambda: ["vision.utm_runtime." + s for s in ("start", "stop", "status")]))
    await runtime.prepare_cycle_vision_runtime(state, ctx, 1)
    await runtime.prepare_cycle_vision_runtime(state, ctx, 1)
    await runtime.prepare_cycle_vision_runtime(state, ctx, 2)
    assert calls == [("r", "cycle_start", 1), ("r", "cycle_start", 2)]


@pytest.mark.asyncio
async def test_virtual_cycle_never_touches_ros(monkeypatch):
    from types import SimpleNamespace
    from utils import vision_cycle_runtime as runtime
    monkeypatch.setattr(runtime, "is_resolved_all_virtual_bridge", lambda *a, **k: True)
    result = await runtime.prepare_cycle_vision_runtime(SimpleNamespace(current_experiment_spec={}, mode="test"), None, 1)
    assert result["status"] == "virtual_bridge_selected"
