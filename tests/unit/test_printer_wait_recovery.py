import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.printer_wait_recovery import resume_printer_wait, validate_boundary


def controller_fixture(one_cycle=True):
    record = {'status':'ready','run_id':'run-a','loop_id':0,'specimen_id':'sp-a','task_id':'6768','stop_after_this_cycle':one_cycle}
    state = SimpleNamespace(run_id='run-a',loop_count=0,stage='specimen',is_paused=True,
        stop_requested=False,safe_stop_requested=False,emergency_stop_requested=False,
        current_experiment_spec={'specimen_id':'sp-a'},run_metadata={'printer_wait_recovery':record,'specimen_result':{}})
    controller = SimpleNamespace(_state=state,_error_resume_lock=asyncio.Lock(),_planning_request_lock=asyncio.Lock(),
        _active_safety_sources=lambda:[],snapshot=lambda:{'is_running':False},_planning_handoff_active=lambda:False,
        _plc_service_start_rejection=AsyncMock(return_value=None),
        _read_specimen_printer_completion_status=AsyncMock(return_value={}),
        _classify_specimen_printer_completion_status=lambda *a,**kw:{'status':'running','task_id':'6768'},
        _expected_specimen_printer_job_names=lambda *a:('job-a',),
        _await_specimen_printer_completion_before_vision=AsyncMock(return_value={'task_id':'6768'}),
        _apply_printer_completion_wait_to_specimen=lambda *a:{'printer_completion_verified':True},
        _write_planning_artifacts=lambda *a,**kw:None,_planning_tail_start_stage=lambda:'vision',
        _record_planning_orchestrator_transition=AsyncMock(),_record_planning_orchestrator_followup=AsyncMock(),
        _planning_cycle_limit=lambda s:10,_run_planning_loop_tail=AsyncMock(return_value={'ok':True,'decision':'continue'}),
        _run_planning_cycle_series=AsyncMock(return_value={'ok':True,'decision':'complete'}),
        _emit_control_event=AsyncMock(),_append_planning_message=AsyncMock())
    controller._set_planning_handoff_task = lambda task:setattr(controller,'task',task)
    return controller


@pytest.mark.asyncio
@pytest.mark.parametrize('one_cycle',[True,False])
async def test_resume_waits_then_uses_existing_tail_without_fabrication(one_cycle):
    c = controller_fixture(one_cycle)
    result = await resume_printer_wait(c)
    assert result['ok'] and result['one_cycle_only'] == one_cycle
    await c.task
    c._await_specimen_printer_completion_before_vision.assert_awaited_once()
    if one_cycle:
        c._run_planning_loop_tail.assert_awaited_once()
        c._run_planning_cycle_series.assert_not_awaited()
        assert c._state.is_paused
    else:
        c._run_planning_cycle_series.assert_awaited_once()
        c._run_planning_loop_tail.assert_not_awaited()
        assert not c._state.is_paused
    assert c._state.run_id == 'run-a'
    assert c._state.run_metadata['printer_wait_recovery']['status'] == 'cycle_finished'


@pytest.mark.asyncio
async def test_wrong_task_or_safety_cannot_resume():
    c = controller_fixture()
    c._classify_specimen_printer_completion_status=lambda *a,**k:{'status':'running','task_id':'other'}
    assert not (await resume_printer_wait(c))['ok']
    c._await_specimen_printer_completion_before_vision.assert_not_awaited()
    c._state.emergency_stop_requested = True
    assert not (await resume_printer_wait(c))['ok']
    assert c._state.emergency_stop_requested


@pytest.mark.asyncio
async def test_double_resume_does_not_create_second_workflow():
    c = controller_fixture()
    release = asyncio.Event()
    async def wait(*a):
        await release.wait()
        return {'task_id':'6768'}
    c._await_specimen_printer_completion_before_vision=wait
    assert (await resume_printer_wait(c))['ok']
    original = c.task
    c._planning_handoff_active=lambda:not c.task.done()
    assert (await resume_printer_wait(c))['status'] == 'already_resuming'
    assert c.task is original
    release.set()
    await c.task


def test_checkpoint_rejects_active_or_unproven_run():
    snapshot={'state':{'run_id':'run-a','stage':'vision'},'is_running':True}
    with pytest.raises(ValueError,match='inactive'):
        validate_boundary(snapshot,{},'run-a')
    snapshot['is_running']=False
    with pytest.raises(ValueError,match='Latest handoff'):
        validate_boundary(snapshot,{},'run-a')
