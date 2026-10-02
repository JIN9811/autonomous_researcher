import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestrator.state import OrchestratorState, Stage
from app.vision_review_recovery import validate_boundary, resume_vision_review


@pytest.fixture
def controller(tmp_path):
    state = OrchestratorState(run_id='review-retry', experiment_id='exp', stage=Stage.COMPLETE,
        current_experiment_spec={'specimen_id': 's1'}, is_paused=True)
    from orchestrator.state import AgentRuntimeStatus
    state.agent_status['vision_agent'] = AgentRuntimeStatus(state='error', success=False,
        run_id=state.run_id, loop_id=0)
    state.run_metadata['specimen_result'] = {'run_id': state.run_id, 'specimen_id': 's1',
        'printer_completion_verified': True, 'printer_completion_wait': {
            'status': 'complete', 'run_id': state.run_id, 'specimen_id': 's1', 'loop_id': 0}}
    path = tmp_path / state.run_id / 'runtime/loops/loop-000001/vision_agent/attempt-000001/result.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'status': 'failed', 'data': {'vision_decision': {
        'failure_code': 'VISION_REVIEW_REQUIRED', 'contract_id': 'active_cam', 'checkpoint': 'image_review',
        'run_id': state.run_id, 'loop_id': 0, 'specimen_id': 's1'}}}))
    tasks = []
    return SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=tmp_path),
        snapshot=lambda: {'is_running': False}, _planning_request_lock=asyncio.Lock(),
        _error_resume_lock=asyncio.Lock(), _planning_handoff_active=lambda: any(not t.done() for t in tasks),
        _active_safety_sources=lambda: [], _plc_service_start_rejection=AsyncMock(return_value=None),
        _run_planning_loop_tail=AsyncMock(return_value={'ok': True, 'decision': 'stop'}),
        _planning_cycle_limit=lambda spec: 20, _set_planning_handoff_task=tasks.append,
        _emit_control_event=AsyncMock(), tasks=tasks)


def test_validate_same_run_pre_manipulation_boundary(controller):
    assert validate_boundary(controller)['specimen_id'] == 's1'


@pytest.mark.parametrize('case', ['safety', 'busy', 'wrong_specimen', 'no_completion', 'downstream', 'wrong_contract'])
def test_unsafe_or_different_boundaries_reject(controller, case):
    if case == 'safety': controller._state.emergency_stop_requested = True
    if case == 'busy': controller.snapshot = lambda: {'is_running': True}
    if case == 'wrong_specimen': controller._state.current_experiment_spec['specimen_id'] = 'other'
    if case == 'no_completion': controller._state.run_metadata['specimen_result']['printer_completion_verified'] = False
    loop = controller._deps.run_root / controller._state.run_id / 'runtime/loops/loop-000001'
    if case == 'downstream': (loop / 'manipulation_agent/attempt-000001').mkdir(parents=True)
    if case == 'wrong_contract':
        source = loop / 'vision_agent/attempt-000001/result.json'
        data = json.loads(source.read_text())
        data['data']['vision_decision']['contract_id'] = 'clearance'
        source.write_text(json.dumps(data))
    with pytest.raises(ValueError): validate_boundary(controller)


@pytest.mark.asyncio
async def test_resume_starts_fresh_vision_not_fabrication_and_does_not_call_stop_success(controller):
    controller._state.run_metadata['vision_review_retry'] = {**validate_boundary(controller), 'status': 'ready'}
    async def failed_series(**kwargs):
        assert kwargs['resume_tail_stage'] == Stage.VISION
        controller._state.is_paused = True
        return {'ok': False, 'decision': 'stop'}
    controller._run_planning_cycle_series = failed_series
    result = await resume_vision_review(controller)
    assert result['status'] == 'resuming_fresh_vision'
    await controller.tasks[0]
    assert controller._state.run_metadata['vision_review_retry']['status'] == 'needs_attention'
    assert controller._state.is_paused


@pytest.mark.asyncio
async def test_plc_latch_and_changed_archive_prevent_resumption(controller):
    controller._state.run_metadata['vision_review_retry'] = {**validate_boundary(controller), 'status': 'ready'}
    controller._plc_service_start_rejection.return_value = {'ok': False, 'status': 'blocked'}
    assert (await resume_vision_review(controller))['ok'] is False
    assert not controller.tasks
    controller._plc_service_start_rejection.return_value = None
    controller._state.run_metadata['vision_review_retry']['source_sha256'] = 'changed'
    assert (await resume_vision_review(controller))['ok'] is False
    assert not controller.tasks


@pytest.mark.asyncio
async def test_successful_review_recovery_keeps_normal_series_running(controller):
    controller._state.run_metadata['vision_review_retry'] = {**validate_boundary(controller), 'status': 'ready'}
    calls = []
    async def series(**kwargs):
        calls.append(kwargs)
        controller._state.agent_status['vision_agent'].success = True
        return {'ok': True, 'decision': 'continue'}
    controller._run_planning_cycle_series = series
    await resume_vision_review(controller)
    await controller.tasks[0]
    assert calls == [{'first_spec': {'specimen_id': 's1'}, 'design_constraints': {},
                      'start_cycle': 1, 'resume_tail_stage': Stage.VISION}]
    assert not controller._state.is_paused


def test_resume_staging_does_not_execute_controller_module(tmp_path):
    from app.safe_hot_reload import stage_resume
    path = tmp_path / 'controller.py'
    path.write_text('raise RuntimeError("no module execution")\nclass MainController:\n'
        '    async def resume(self) -> dict[str, Any]:\n        return {}\n')
    current, candidate = stage_resume(path)
    assert current is not candidate
