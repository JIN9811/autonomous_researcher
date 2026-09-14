import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Stage


@pytest.mark.asyncio
async def test_opening_live_gui_cannot_change_active_planning_run_scope(monkeypatch):
    from orchestrator.state import Mode
    controller = load_runtime()
    controller._state.mode = Mode.TEST
    controller._state.active_goal = "Keep approved experiment"
    controller._planning_messages = [{"content": "Keep this conversation"}]
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    controller._set_planning_handoff_task(task)
    monkeypatch.setattr(controller, "planning_snapshot", lambda: {})
    try:
        controller.prepare_live_gui(goal="New goal", reset=True)
        assert controller._state.mode == Mode.TEST
        assert controller._state.active_goal == "Keep approved experiment"
        assert controller._planning_messages == [{"content": "Keep this conversation"}]
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_error_resume_uses_equipment_boundary_once_without_new_run(monkeypatch):
    from app import run_recovery
    controller = load_runtime()
    controller._state.stage = Stage.ERROR
    run_id = controller._state.run_id
    controller._state.retry_counters = {"equipment": 3, "vision": 2}
    monkeypatch.setattr(run_recovery, "prepare_error_resume", lambda c: "equipment-" + "a" * 32, raising=False)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def tail(spec, **kwargs):
        calls.append(kwargs)
        entered.set()
        await release.wait()
        return {"ok": True, "decision": "complete"}
    monkeypatch.setattr(controller, "_run_planning_loop_tail", tail)
    first = await controller.resume()
    await asyncio.wait_for(entered.wait(), 1)
    second = await controller.resume()
    assert first["ok"] and second["ok"]
    assert len(calls) == 1
    assert calls[0]["resume_stage"] == Stage.EQUIPMENT
    assert controller._state.run_id == run_id
    assert controller._state.retry_counters == {"vision": 2}
    release.set()
    await controller._planning_handoff_task


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["emergency_stop_requested", "safe_stop_requested", "stop_requested"])
async def test_error_resume_never_clears_stop_flags(monkeypatch, flag):
    from app import run_recovery
    controller = load_runtime()
    controller._state.stage = Stage.ERROR
    setattr(controller._state, flag, True)
    def forbidden(_):
        pytest.fail("Recovery preparation must not run with a stop flag")
    monkeypatch.setattr(run_recovery, "prepare_error_resume", forbidden, raising=False)
    result = await controller.resume()
    assert result["ok"] is False
    assert getattr(controller._state, flag)
    assert controller._planning_handoff_task is None


@pytest.mark.asyncio
async def test_ordinary_pause_resume_does_not_enter_error_recovery(monkeypatch):
    from app import run_recovery
    controller = load_runtime()
    controller._state.stage = Stage.ANALYSIS
    controller._state.is_paused = True
    def forbidden(_):
        pytest.fail("Normal resume must preserve the existing path")
    monkeypatch.setattr(run_recovery, "prepare_error_resume", forbidden, raising=False)
    result = await controller.resume()
    assert result["ok"] and not controller._state.is_paused
    assert controller._state.stage == Stage.ANALYSIS


@pytest.mark.asyncio
async def test_error_resume_checks_external_plc_latch_before_preparation(monkeypatch):
    from app import run_recovery
    controller = load_runtime()
    controller._state.stage = Stage.ERROR
    controller.set_plc_safety_status_provider(lambda: {
        "active_estop_sources": ["plc_pb2"], "safety_state": "estop_latched"})
    def forbidden(_):
        pytest.fail("PLC latch must block before recovery preparation")
    monkeypatch.setattr(run_recovery, "prepare_error_resume", forbidden)
    result = await controller.resume()
    assert not result["ok"]
    assert result["failure_code"] == "PLC_SERVICE_SAFETY_LATCH_ACTIVE"
    assert controller._planning_handoff_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("first_ok", [True, False])
async def test_recovery_series_skips_completed_stages_only_in_first_cycle(monkeypatch, first_ok):
    controller = load_runtime()
    calls = []
    monkeypatch.setattr(controller, "_planning_cycle_limit", lambda spec: 2)
    def no_reset():
        pytest.fail("Recovery must not reset workflow safety controls")
    monkeypatch.setattr(controller, "_reset_planning_workflow_controls", no_reset)
    async def design(**kwargs):
        calls.append(("design", kwargs["cycle_index"]))
        return {}
    async def specimen(spec):
        calls.append(("specimen", 2))
        return {"ok": True}
    async def tail(spec, **kwargs):
        calls.append(("tail", kwargs["cycle_index"], kwargs.get("resume_stage")))
        return {"ok": first_ok, "decision": "continue"}
    monkeypatch.setattr(controller, "_run_planning_design_stage", design)
    monkeypatch.setattr(controller, "_run_planning_specimen_stage", specimen)
    monkeypatch.setattr(controller, "_run_planning_loop_tail", tail)
    await controller._run_planning_cycle_series(first_spec={}, design_constraints={},
        start_cycle=1, resume_tail_stage=Stage.EQUIPMENT)
    expected = [("tail", 1, Stage.EQUIPMENT)]
    if first_ok:
        expected += [("design", 2), ("specimen", 2), ("tail", 2, None)]
    assert calls == expected


@pytest.mark.asyncio
async def test_requested_next_design_limit_stops_before_specimen(monkeypatch):
    controller = load_runtime()
    controller._state.run_metadata["recovery_design_limit"] = {
        "run_id": controller._state.run_id, "cycle_index": 2, "requested_by": "operator"}
    monkeypatch.setattr(controller, "_planning_cycle_limit", lambda spec: 20)
    calls = []
    async def design(**kwargs):
        calls.append("design")
        return {"specimen_id": "next-specimen", "stl_path": "next.stl"}
    async def specimen(spec):
        pytest.fail("No fabrication is permitted after the requested design limit")
    async def tail(spec, **kwargs):
        calls.append("tail")
        return {"ok": True, "decision": "continue"}
    monkeypatch.setattr(controller, "_run_planning_design_stage", design)
    monkeypatch.setattr(controller, "_run_planning_specimen_stage", specimen)
    monkeypatch.setattr(controller, "_run_planning_loop_tail", tail)
    result = await controller._run_planning_cycle_series(first_spec={}, design_constraints={},
        start_cycle=1, resume_tail_stage=Stage.EQUIPMENT)
    assert calls == ["tail", "design"]
    assert result["decision"] == "paused_after_design"
    assert controller._state.is_paused is True
    assert controller._state.stage == Stage.DESIGN


@pytest.mark.asyncio
async def test_proven_clearance_recovery_resumes_vision_without_equipment_recheck(monkeypatch):
    controller = load_runtime()
    controller._state.run_metadata["recovery_resume_stage"] = "vision"
    monkeypatch.setattr(controller, "_planning_cycle_limit", lambda spec: 1)
    seen = []
    async def tail(spec, **kwargs):
        seen.append(kwargs["resume_stage"])
        return {"ok": True, "decision": "stop"}
    monkeypatch.setattr(controller, "_run_planning_loop_tail", tail)
    await controller._run_planning_cycle_series(first_spec={}, design_constraints={},
        start_cycle=1, resume_tail_stage=Stage.EQUIPMENT)
    assert seen == [Stage.VISION]
