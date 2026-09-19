from device_bridges.camera_vision import tools


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
