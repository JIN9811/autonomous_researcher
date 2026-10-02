import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.vision_ros_recovery import validate, resume, resume_completed_cycle
from orchestrator.state import Stage


def controller():
    state = NS(stage=Stage.COMPLETE, run_id="r", loop_count=6, current_experiment_spec={"specimen_id": "s"},
        stop_requested=False, safe_stop_requested=False, emergency_stop_requested=False, retry_counters={}, is_paused=False,
        agent_status={"vision_agent": NS(success=False, run_id="r", loop_id=6)},
        run_metadata={"vision_agent_payload": {"failure_code": "VISION_ROS_STOP_UNCONFIRMED",
            "observation": {"raw_capture": {"run_id": "r", "specimen_id": "s", "post_place_interlock": {
                "session_id": "robot-session", "home_after_ungrasping": True, "ready_for_utm_snapshot": True}}}}})
    return NS(_state=state, snapshot=lambda: {"is_running": False}, _planning_request_lock=asyncio.Lock(),
        _planning_handoff_active=lambda: False, _active_safety_sources=lambda: [], _error_resume_lock=asyncio.Lock())


def test_requires_current_post_home_failure_and_no_downstream_execution():
    c = controller()
    assert validate(c)["loop_id"] == 6
    c._state.agent_status["equipment_agent"] = NS(success=True, run_id="r", loop_id=6)
    with pytest.raises(ValueError, match="Downstream"):
        validate(c)
    del c._state.agent_status["equipment_agent"]
    c._state.safe_stop_requested = True
    with pytest.raises(ValueError, match="safety"):
        validate(c)


@pytest.mark.asyncio
async def test_resume_vision_via_normal_series_without_forced_cycle_pause():
    c = controller()
    c._state.run_metadata["vision_ros_retry"] = {**validate(c), "status": "ready"}
    c._plc_service_start_rejection = AsyncMock(return_value=None)
    c._planning_cycle_limit = lambda spec: 20
    c._emit_control_event = AsyncMock()
    async def series(**kwargs):
        assert kwargs == {"first_spec": {"specimen_id": "s"}, "design_constraints": {},
                          "start_cycle": 7, "resume_tail_stage": Stage.VISION}
        c._state.agent_status["vision_agent"].success = True
        return {"ok": True, "decision": "continue"}
    c._run_planning_cycle_series = series
    tasks = []
    c._set_planning_handoff_task = tasks.append
    result = await resume(c)
    assert result["one_cycle_only"] is False
    await tasks[0]
    assert c._state.run_metadata["vision_ros_retry"]["status"] == "finished"
    assert not c._state.is_paused
    assert c._state.loop_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('decision', ['stop', 'pending_operator_input', 'continue'])
async def test_recovery_keeps_normal_series_gates_and_pause_state(decision):
    c = controller()
    c._state.run_metadata['vision_ros_retry'] = {**validate(c), 'status': 'ready'}
    c._plc_service_start_rejection = AsyncMock(return_value=None)
    c._emit_control_event = AsyncMock()
    async def series(**kwargs):
        c._state.agent_status['vision_agent'].success = True
        c._state.is_paused = decision != 'continue'
        return {'ok': True, 'decision': decision}
    c._run_planning_cycle_series = series
    tasks = []
    c._set_planning_handoff_task = tasks.append
    await resume(c)
    await tasks[0]
    assert c._state.is_paused == (decision != 'continue')


def completed_controller():
    c = controller()
    c._state.stage, c._state.loop_count, c._state.is_paused = Stage.DESIGN, 7, True
    c._state.run_metadata.update(vision_ros_retry={'run_id': 'r', 'loop_id': 6,
        'status': 'cycle_finished', 'result': {'ok': True, 'decision': 'continue'}},
        guardian={'decision': 'continue'})
    c._planning_cycle_limit = lambda spec: 20
    c._plc_service_start_rejection = AsyncMock(return_value=None)
    return c


@pytest.mark.asyncio
async def test_legacy_completed_recovery_starts_next_design_not_old_tail():
    c = completed_controller()
    c._run_planning_cycle_series = AsyncMock(return_value={'ok': True, 'decision': 'continue'})
    tasks = []
    c._set_planning_handoff_task = tasks.append
    result = await resume_completed_cycle(c)
    assert result['cycle_index'] == 8 and result['resume_stage'] == 'design'
    await tasks[0]
    c._run_planning_cycle_series.assert_awaited_once_with(first_spec={'specimen_id': 's'},
        design_constraints={}, start_cycle=8, start_with_design=True)
    assert (await resume_completed_cycle(c))['ok'] is False  # no duplicate dispatch


@pytest.mark.asyncio
async def test_completed_image_review_routes_to_next_design_without_repeating_cycle():
    from app.resume_routing import dispatch
    c = completed_controller()
    c._state.experiment_id = 'exp'
    c._state.run_metadata['vision_review_retry'] = c._state.run_metadata.pop('vision_ros_retry')
    calls, tasks = [], []
    async def series(**kwargs):
        calls.append(kwargs)
        return {'ok': True, 'decision': 'continue'}
    c._run_planning_cycle_series = series
    c._set_planning_handoff_task = tasks.append
    result = await dispatch(c)
    assert result['ok'] and result['cycle_index'] == 8
    await tasks[0]
    assert calls == [{'first_spec': {'specimen_id': 's'}, 'design_constraints': {},
                      'start_cycle': 8, 'start_with_design': True}]
    assert not c._state.is_paused
    assert not (await dispatch(c))['ok']


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['safety', 'guardian', 'run', 'cycle', 'budget'])
async def test_legacy_recovery_does_not_bypass_changed_boundary(problem):
    c = completed_controller()
    if problem == 'safety': c._state.safe_stop_requested = True
    if problem == 'guardian': c._state.run_metadata['guardian']['decision'] = 'stop'
    if problem == 'run': c._state.run_id = 'another-run'
    if problem == 'cycle': c._state.loop_count = 8
    if problem == 'budget': c._planning_cycle_limit = lambda spec: 7
    assert (await resume_completed_cycle(c))['ok'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('recover_tail', [False, True])
async def test_real_series_next_design_entry_and_guardian_stop(recover_tail):
    from app.controller import MainController
    c = completed_controller()
    c._state.active_goal = 'SEA'
    c._is_planning_test_cycle = lambda spec: False
    c._store_planning_resume_context = lambda **kw: None
    c._closed_loop_static_design_constraints = lambda value: value
    calls = []
    async def design(**kw):
        calls.append(('design', kw['cycle_index']))
        return {'specimen_id': f"s{kw['cycle_index']}"}
    async def specimen(spec):
        calls.append(('print', spec['specimen_id']))
        return {'pending': False}
    async def tail(spec, **kw):
        calls.append(('tail', kw['cycle_index']))
        if kw['cycle_index'] == 7:
            assert kw['resume_stage'] == Stage.VISION
            return {'ok': True, 'decision': 'continue'}
        return {'ok': True, 'decision': 'stop'}
    c._run_planning_design_stage, c._run_planning_specimen_stage, c._run_planning_loop_tail = design, specimen, tail
    result = await MainController._run_planning_cycle_series(c, first_spec={'specimen_id': 'old7'},
        design_constraints={}, start_cycle=7 if recover_tail else 8, start_with_design=not recover_tail,
        resume_tail_stage=Stage.VISION if recover_tail else None)
    assert calls == ([('tail', 7)] if recover_tail else []) + [('design', 8), ('print', 's8'), ('tail', 8)]
    assert result['decision'] == 'stop'
