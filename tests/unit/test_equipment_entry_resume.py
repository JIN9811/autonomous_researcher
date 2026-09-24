import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import resume_routing
from orchestrator.state import OrchestratorState, Stage


def fixture():
    state = OrchestratorState(run_id='run', experiment_id='exp', loop_count=0,
        stage=Stage.GUARDIAN, is_paused=True, current_experiment_spec={'specimen_id': 'spec'})
    state.run_metadata['guardian_recovery_wait'] = dict(status='waiting', run_id='run', loop_id=0,
        specimen_id='spec', action='recover')
    state.run_metadata['equipment_agent_payload'] = dict(equipment_workflow_execution_id='old',
        failure_code='EQUIPMENT_WORKFLOW_REVIEW_REQUIRED')
    exception = dict(failure_code='UI_LOCATOR_NOT_FOUND', message='Required screen target not found: entry_height_150_mm',
        segment_id='segment', skill_id='utm_prepare_next_specimen', version='1.0.6')
    record = dict(execution_id='old', identity=dict(run_id='run', experiment_id='exp', specimen_id='spec',
        sequence_id='stacked-loop-0'), lifecycle='ESCALATED', workflow_result=dict(success=False, data=dict(
        equipment_workflow_execution_id='old', equipment_workflow_recovery={'attempts':0},
        equipment_skill_exception=exception,
        equipment_skill_execution=dict(state='EXCEPTION', completed_segments=[], attempt=0),
        equipment_skill_flow_execution=dict(state='BLOCKED', run_id='run', transitions=[dict(
            block_id='prepare_next_specimen', phase='skill', success=False, outcome='failed',
            skill_id='utm_prepare_next_specimen', skill_version='1.0.6')]))))
    program = dict(program_id='segment', sequence=[dict(action='screenshot'),
        dict(action='wait_until_image', target='entry_height_150_mm', required=True),
        dict(action='click', target='move_jigs_next_specimen')])
    return state, record, program


def test_stopped_entry_retry_matches_only_same_unfinished_cycle():
    from app import equipment_entry_resume as recovery
    state, _, _ = fixture()
    state.stage = Stage.COMPLETE
    state.loop_count = 1
    state.is_paused = False
    state.run_metadata['guardian_recovery_wait']['status'] = 'stopped'
    state.run_metadata['_planning_resume_context'] = {'cycle_index': 1, 'total_cycles': 3,
        'current_spec': {'specimen_id': 'spec'}}
    matches = getattr(recovery, 'stopped_matches', lambda state: False)
    assert matches(state)
    state.loop_count = 2
    assert not matches(state)
    state.loop_count = 1
    state.run_metadata['_planning_resume_context']['current_spec']['specimen_id'] = 'other'
    assert not matches(state)


def test_readonly_recheck_stops_before_first_device_action():
    from app import equipment_entry_resume as recovery
    _, _, program = fixture()
    prefix = getattr(recovery, 'readonly_prefix', lambda program: [])(program)
    assert [step['action'] for step in prefix] == ['screenshot', 'wait_until_image']
    assert prefix[-1]['target'] == 'entry_height_150_mm'


def stopped_fixture(tmp_path, monkeypatch):
    from app import equipment_entry_resume as recovery
    state, record, program = fixture()
    state.stage, state.loop_count, state.is_paused = Stage.COMPLETE, 1, False
    state.run_metadata['guardian_recovery_wait']['status'] = 'stopped'
    state.run_metadata['_planning_resume_context'] = {'cycle_index': 1, 'total_cycles': 3,
        'current_spec': {'specimen_id': 'spec'}, 'design_constraints': {'material': 'PLA'}}
    state.run_metadata['hardware_alerts'] = [dict(schema='hardware_alert.v1', alert_id='capture',
        run_id='run', loop_id=0, device_class='equipment', tool='equipment.pyautogui.screenshot',
        failure_code='PYAUTOGUI_SCREENSHOT_FAILED', lifecycle='active', severity='blocking',
        blocks_workflow=True, requires_ack=True, message='failed')]
    state.device_health['equipment'] = 'blocking:PYAUTOGUI_SCREENSHOT_FAILED'
    state.run_metadata['guardian_gates'] = [dict(gate_id='entry', run_id='run', loop_id=0,
        stage='equipment', phase='action', decision='block', reason_code='UI_LOCATOR_NOT_FOUND',
        alarms=[dict(reason_code='UI_LOCATOR_NOT_FOUND', severity='blocking',
                     message='Required screen target not found: entry_height_150_mm', source_path='payload')])]
    state.run_metadata['incident_records'] = [dict(incident_id='entry', status='open')]
    tasks = []
    c = SimpleNamespace(_state=state, _run_task=None, _deps=SimpleNamespace(run_root=tmp_path),
        _planning_handoff_active=lambda: bool(tasks and not tasks[-1].done()),
        _planning_request_lock=asyncio.Lock(), _error_resume_lock=asyncio.Lock(),
        _active_safety_sources=lambda:{}, _plc_service_start_rejection=AsyncMock(return_value=None),
        _emit_control_event=AsyncMock(), _set_planning_handoff_task=tasks.append,
        _run_planning_cycle_series=AsyncMock(return_value={'ok': True}),
        snapshot=lambda: {'state':state.model_dump(mode='json'), 'is_running':False})
    monkeypatch.setattr(recovery, 'stopped_inputs', lambda controller: (deepcopy(record), deepcopy(program)), raising=False)
    proof = dict(ok=True, status='completed', step_trace=[dict(step='SEQ_2_WAIT_UNTIL_IMAGE',
        status='ok', detail='entry_height_150_mm via image')],
        output_artifacts=[{'local_path':'/readonly/screen.png', 'sha256':'capture-hash'}])
    monkeypatch.setattr(recovery, 'recheck_entry', AsyncMock(return_value=proof), raising=False)
    return c, tasks, record, program


@pytest.mark.asyncio
async def test_terminal_resume_rechecks_then_continues_same_eqp_without_print_or_transfer(tmp_path, monkeypatch):
    c, tasks, record, _ = stopped_fixture(tmp_path, monkeypatch)
    original = deepcopy(record)
    result = await resume_routing.dispatch(c)
    assert result['ok'] and result['cycle_index'] == 1
    assert c._state.loop_count == 0 and c._state.stage == Stage.EQUIPMENT
    assert (await resume_routing.dispatch(c))['status'] == 'already_running'
    await tasks[0]
    c._run_planning_cycle_series.assert_awaited_once_with(first_spec={'specimen_id':'spec'},
        design_constraints={'material':'PLA'}, start_cycle=1, resume_tail_stage=Stage.EQUIPMENT)
    assert record == original
    assert c._state.run_metadata['hardware_alerts'][0]['lifecycle'] == 'resolved'
    assert c._state.run_metadata['guardian_gates'][0]['decision'] == 'block'
    assert c._state.run_metadata['guardian_gates'][0]['audit_log']['resolved_by']
    assert c._state.device_health['equipment'] == 'ready'
    assert list((tmp_path/'run/recovery').glob('equipment_entry_before_*.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['safety','plc','failed_capture','unknown_alert','other_run_alert',
    'unknown_gate','changed_boundary','source_changed'])
async def test_terminal_recovery_never_releases_unproven_or_changed_boundary(tmp_path, monkeypatch, fault):
    from app import equipment_entry_resume as recovery
    c, tasks, record, _ = stopped_fixture(tmp_path, monkeypatch)
    if fault == 'safety': c._state.emergency_stop_requested = True
    if fault == 'plc': c._plc_service_start_rejection.return_value = {'ok':False, 'status':'blocked'}
    if fault == 'failed_capture': recovery.recheck_entry.return_value = {'ok':False}
    if fault == 'unknown_alert': c._state.run_metadata['hardware_alerts'][0]['failure_code'] = 'MOTOR_FAULT'
    if fault == 'other_run_alert': c._state.run_metadata['hardware_alerts'][0]['run_id'] = 'other'
    if fault == 'unknown_gate': c._state.run_metadata['guardian_gates'][0]['reason_code'] = 'COLLISION'
    if fault == 'changed_boundary':
        async def changed(*args):
            c._state.loop_count = 2
            return {'ok':True}
        recovery.recheck_entry.side_effect = changed
    if fault == 'source_changed':
        async def changed(*args):
            record['execution_id'] = 'different'
            return {'ok':True}
        recovery.recheck_entry.side_effect = changed
    before = deepcopy(c._state.run_metadata)
    result = await resume_routing.dispatch(c)
    assert not result['ok'] and not tasks
    assert c._state.run_metadata == before


@pytest.mark.asyncio
async def test_unrelated_monitor_refresh_does_not_invalidate_eqp_recheck(tmp_path, monkeypatch):
    from app import equipment_entry_resume as recovery
    c, tasks, _, _ = stopped_fixture(tmp_path, monkeypatch)
    proof = recovery.recheck_entry.return_value
    async def monitor_refresh(*args):
        c._state.run_metadata['printer_monitor'] = {'updated_at': 'newer'}
        return proof
    recovery.recheck_entry.side_effect = monitor_refresh
    result = await resume_routing.dispatch(c)
    assert result['ok']
    await tasks[0]


def test_proven_read_only_first_block_failure_is_retryable_without_changing_evidence():
    from app.equipment_entry_resume import validate_record
    state, record, program = fixture()
    before = deepcopy(record)
    validate_record(state, record, program)
    assert record == before


@pytest.mark.parametrize('fault', ['other_run', 'other_cycle', 'later_block', 'completed_segment',
    'unknown_effect', 'earlier_click', 'wrong_target', 'recovered', 'started_test', 'not_failed'])
def test_unknown_or_actuated_failure_cannot_restart_equipment(fault):
    from app.equipment_entry_resume import validate_record
    state, record, program = fixture()
    data = record['workflow_result']['data']
    if fault == 'other_run': record['identity']['run_id'] = 'other'
    if fault == 'other_cycle': record['identity']['sequence_id'] = 'stacked-loop-01'
    if fault == 'later_block': data['equipment_skill_flow_execution']['transitions'][0]['block_id'] = 'start_test'
    if fault == 'completed_segment': data['equipment_skill_execution']['completed_segments'] = ['first']
    if fault == 'unknown_effect': record['lifecycle'] = 'EFFECT_UNKNOWN'
    if fault == 'earlier_click': program['sequence'].insert(0, dict(action='click'))
    if fault == 'wrong_target': program['sequence'][1]['target'] = 'other'
    if fault == 'recovered': data['equipment_workflow_recovery']['attempts'] = 1
    if fault == 'started_test': data['equipment_skill_flow_execution']['transitions'].append(dict(block_id='start_test'))
    if fault == 'not_failed': record['workflow_result']['success'] = True
    with pytest.raises(ValueError): validate_record(state, record, program)


@pytest.mark.asyncio
async def test_resume_redirects_existing_task_once_preserving_cycle_and_gates(monkeypatch):
    from app import equipment_entry_resume as recovery
    state, record, program = fixture()
    state.run_metadata['guardian_gates'] = [{'gate_id':'failed', 'decision':'block'}]
    pending = asyncio.Event()
    task = asyncio.create_task(pending.wait())
    c = SimpleNamespace(_state=state, _run_task=None, _planning_handoff_active=lambda:not task.done(),
        _error_resume_lock=asyncio.Lock(), _active_safety_sources=lambda:{},
        _plc_service_start_rejection=AsyncMock(return_value=None), _emit_control_event=AsyncMock())
    monkeypatch.setattr(recovery, 'inputs', lambda controller: (deepcopy(record), deepcopy(program)))
    try:
        result = await resume_routing.dispatch(c)
        repeat = await resume_routing.dispatch(c)
        assert result['resume_stage'] == 'equipment'
        assert repeat['status'] == 'already_running'
        assert state.stage == Stage.EQUIPMENT and not state.is_paused
        assert state.run_id == 'run' and state.loop_count == 0 and not task.done()
        assert state.run_metadata['guardian_gates'] == [{'gate_id':'failed', 'decision':'block'}]
        assert state.run_metadata['equipment_explicit_restart']['source_execution_id'] == 'old'
    finally:
        pending.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['unsafe', 'source_changed', 'ended', 'plc', 'unproven'])
async def test_resume_does_not_unpause_invalid_equipment_hold(monkeypatch, fault):
    from app import equipment_entry_resume as recovery
    state, record, program = fixture()
    active = True
    async def plc():
        nonlocal active
        if fault == 'unsafe': state.safe_stop_requested = True
        if fault == 'source_changed': record['execution_id'] = 'changed'
        if fault == 'ended': active = False
        if fault == 'plc': return {'ok':False, 'status':'blocked'}
    if fault == 'unproven': program['sequence'].insert(0, dict(action='click'))
    c = SimpleNamespace(_state=state, _run_task=None, _planning_handoff_active=lambda:active,
        _error_resume_lock=asyncio.Lock(), _active_safety_sources=lambda:{},
        _plc_service_start_rejection=plc, _emit_control_event=AsyncMock())
    monkeypatch.setattr(recovery, 'inputs', lambda controller: (deepcopy(record), deepcopy(program)))
    result = await resume_routing.dispatch(c)
    assert not result['ok'] and state.is_paused and state.stage == Stage.GUARDIAN
    assert 'equipment_explicit_restart' not in state.run_metadata


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [False, True])
async def test_hotfix_only_publishes_resume_code_at_unchanged_hold(monkeypatch, changed):
    import subprocess
    from app import equipment_entry_resume as recovery, safe_hot_reload
    state, record, program = fixture()
    c = SimpleNamespace(_state=state, _run_task=None, _planning_handoff_active=lambda:True,
        _active_safety_sources=lambda:{}, _emit_control_event=AsyncMock())
    monkeypatch.setattr(recovery, 'inputs', lambda controller: (deepcopy(record), deepcopy(program)))
    published = []
    monkeypatch.setattr(safe_hot_reload, 'reload_sources', lambda sources: published.extend(sources) or list(sources))
    def checked(*args, **kwargs):
        if changed: state.loop_count = 1
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', checked)
    if changed:
        with pytest.raises(ValueError): await recovery.hot_reload(c)
        assert not published
    else:
        result = await recovery.hot_reload(c)
        assert result['actuation_performed'] is False and result['workflow_resumed'] is False
        assert published == ['app.resume_routing']
    assert state.is_paused and state.stage == Stage.GUARDIAN
    assert 'equipment_explicit_restart' not in state.run_metadata
