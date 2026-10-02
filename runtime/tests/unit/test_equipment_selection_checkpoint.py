import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app import equipment_selection_checkpoint as recovery
from orchestrator.state import OrchestratorState, Stage


@pytest.fixture
def saved(tmp_path, monkeypatch):
    run = tmp_path / 'run-a'
    run.mkdir()
    transcript = run / 'live_planning_transcript.jsonl'
    transcript.write_text('{"role":"system","content":"paused"}\n')
    state = OrchestratorState(run_id='run-a', experiment_id='exp-a', stage=Stage.GUARDIAN,
        is_paused=True, current_experiment_spec={'specimen_id':'s'})
    state.run_metadata['guardian_recovery_wait'] = {'status':'waiting','run_id':'run-a','loop_id':0}
    record = {'execution_id':'selection-a'}
    specimen = {'specimen_id':'s','run_id':'run-a','loop_id':0,'printer_completion_verified':True}
    monkeypatch.setattr(recovery, 'selection_recovery_inputs', lambda c:(deepcopy(record),deepcopy(specimen)))
    snapshot = {'state':state.model_dump(mode='json'),'is_running':True}
    planning = {'planning_session_id':'run-a','transcript_path':str(transcript)}
    recovery.save_checkpoint(snapshot, planning, tmp_path, 'run-a')
    return tmp_path, state, record, transcript


@pytest.mark.parametrize('fault', ['none','digest','transcript','execution','claim'])
def test_checkpoint_integrity_and_single_use(saved, fault):
    root, state, record, transcript = saved
    if fault == 'digest':
        path = root / 'run-a/recovery/equipment_selection.json'
        content = json.loads(path.read_text()); content['sha256'] = 'bad'
        path.write_text(json.dumps(content))
    elif fault == 'transcript': transcript.write_text('changed')
    elif fault == 'execution': record['execution_id'] = 'different'
    elif fault == 'claim': (root / 'run-a/recovery/equipment_selection.claim').touch()
    if fault == 'none': assert recovery.load_checkpoint(root, 'run-a')['run_id'] == 'run-a'
    else:
        with pytest.raises(ValueError): recovery.load_checkpoint(root, 'run-a')


def make_controller(saved):
    root,state,record,transcript=saved
    state.run_metadata['equipment_selection_resume'] = {'status':'ready','run_id':'run-a',
        'loop_id':0,'specimen_id':'s','source_execution_id':'selection-a'}
    c=SimpleNamespace(_state=state,_deps=SimpleNamespace(run_root=root),
        _error_resume_lock=asyncio.Lock(),_planning_request_lock=asyncio.Lock(),
        snapshot=lambda:{'is_running':False},_planning_handoff_active=lambda:False,
        _plc_service_start_rejection=AsyncMock(return_value=None),
        _planning_cycle_limit=lambda s:20,
        _run_planning_loop_tail=AsyncMock(return_value={'ok':True,'decision':'continue'}),
        _run_planning_cycle_series=AsyncMock(),_emit_control_event=AsyncMock())
    c._set_planning_handoff_task=lambda task:setattr(c,'task',task)
    return c


@pytest.mark.asyncio
async def test_resumes_only_eqp_tail_and_preserves_single_cycle(saved):
    c=make_controller(saved)
    assert (await recovery.resume_selection(c))['ok']
    c._planning_handoff_active=lambda:not c.task.done()
    assert (await recovery.resume_selection(c))['status']=='already_resuming'
    await c.task
    c._run_planning_loop_tail.assert_awaited_once_with(c._state.current_experiment_spec,
        cycle_index=1,total_cycles=20,resume_stage=Stage.EQUIPMENT)
    c._run_planning_cycle_series.assert_not_called()
    assert c._state.is_paused
    assert c._state.run_metadata['equipment_selection_resume']['status']=='cycle_finished'
    assert c._state.run_metadata['specimen_result']['printer_completion_verified']
    c._state.run_metadata['equipment_selection_resume']['status']='ready'
    assert not (await recovery.resume_selection(c))['ok']
    c._run_planning_loop_tail.assert_awaited_once()


@pytest.mark.asyncio
async def test_plc_rejection_is_preserved(saved):
    c=make_controller(saved)
    c._plc_service_start_rejection.return_value={'ok':False,'status':'plc_blocked'}
    assert (await recovery.resume_selection(c))['status']=='plc_blocked'
    c._run_planning_loop_tail.assert_not_called()
    assert c._state.is_paused
    assert not (saved[0]/'run-a/recovery/equipment_selection.claim').exists()


@pytest.mark.asyncio
async def test_boundary_changed_cannot_resume(saved):
    c=make_controller(saved)
    c._state.loop_count=1
    assert not (await recovery.resume_selection(c))['ok']
    c._run_planning_loop_tail.assert_not_called()


def test_restore_is_nonactuating_and_preserves_transfer(saved, monkeypatch):
    import app.controller  # Import before patching factories captured by that module.
    import logging_system.logger_factory
    import orchestrator.experimental_setup
    monkeypatch.setattr(logging_system.logger_factory,'build_logger_bundle',lambda **kw:object())
    monkeypatch.setattr(orchestrator.experimental_setup,'SetupStore',lambda *a:object())
    c=make_controller(saved)
    c._state=OrchestratorState(run_id='fresh',experiment_id='fresh',stage=Stage.IDLE)
    c._deps.logging_config={}
    c._active_safety_sources=lambda:{}
    assert recovery.restore_checkpoint(c,'run-a')['actuation_performed'] is False
    assert c._state.stage==Stage.GUARDIAN and c._state.is_paused
    assert c._state.run_metadata['equipment_selection_resume']['status']=='ready'
    assert c._state.run_metadata['specimen_result']['printer_completion_verified']
    c._run_planning_loop_tail.assert_not_called()
    with pytest.raises(ValueError, match='fresh inactive'):
        recovery.restore_checkpoint(c,'run-a')
