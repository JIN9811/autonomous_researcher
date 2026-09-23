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
