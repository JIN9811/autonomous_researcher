import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import specimen_resume, resume_routing
from orchestrator.state import AgentRuntimeStatus, OrchestratorState, Stage


def fixture(tmp_path):
    state = OrchestratorState(run_id='retry-run', experiment_id='exp', loop_count=7,
        stage=Stage.ERROR, is_paused=True, current_experiment_spec={'specimen_id':'s8','candidate_id':'c8'})
    state.agent_status['specimen_agent'] = AgentRuntimeStatus(success=False, run_id='retry-run', loop_id=7)
    state.run_metadata['_planning_resume_context'] = {'cycle_index':8,'total_cycles':20,
        'current_spec':deepcopy(state.current_experiment_spec),'design_constraints':{'cell_size_bounds_mm':[5,10]}}
    folder = tmp_path/'retry-run/runtime/loops/loop-000008/specimen_agent/attempt-000001'
    folder.mkdir(parents=True)
    manifest = dict(run_id='retry-run',loop_index=7,specimen_id='s8',agent='specimen_agent',
                    status='failed',archive_status='complete',pending_tools=0,execution_id='exec1')
    (folder/'manifest.json').write_text(json.dumps(manifest))
    (folder/'result.json').write_text(json.dumps({'status':'failed'}))
    (folder/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in [
        {'event':'tool_started','payload':{'tool':'geometry.check_manufacturability'}},
        {'event':'tool_result','payload':{'tool':'geometry.check_manufacturability','data':{'ok':False}}},
        {'event':'agent_finished','payload':{'status':'failed'}}]))
    tasks=[]
    c=SimpleNamespace(_state=state,_deps=SimpleNamespace(run_root=tmp_path),_run_task=None,
        _planning_request_lock=asyncio.Lock(),_error_resume_lock=asyncio.Lock(),
        _planning_handoff_active=lambda:bool(tasks and not tasks[-1].done()),
        snapshot=lambda:{'is_running':False},_active_safety_sources=lambda:{},
        _plc_service_start_rejection=AsyncMock(return_value=None),
        _run_planning_specimen_stage=AsyncMock(return_value={'pending':False}),
        _run_planning_cycle_series=AsyncMock(return_value={'ok':True}),
        _emit_control_event=AsyncMock(),_set_planning_handoff_task=tasks.append)
    return c,folder,tasks


@pytest.mark.asyncio
async def test_resume_same_spec_once_then_normal_series_without_reset(tmp_path):
    c,folder,tasks=fixture(tmp_path)
    before=deepcopy(c._state.current_experiment_spec)
    first=await resume_routing.dispatch(c)
    second=await resume_routing.dispatch(c)
    assert first['cycle_index']==8 and second['status']=='already_running'
    await tasks[0]
    c._run_planning_specimen_stage.assert_awaited_once_with(before)
    c._run_planning_cycle_series.assert_awaited_once_with(first_spec=before,
        design_constraints={'cell_size_bounds_mm':[5,10]},start_cycle=8)
    assert c._state.loop_count==7 and c._state.run_id=='retry-run'
    assert json.loads((folder/'result.json').read_text())['status']=='failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('defect',['printer','unknown_tool','incomplete','wrong_spec','context','downstream','no_archive','missing_terminal'])
async def test_unproven_or_started_print_is_never_redispatched(tmp_path,defect):
    c,folder,tasks=fixture(tmp_path)
    if defect in {'printer','unknown_tool'}:
        events=(folder/'events.jsonl').read_text().replace('geometry.check_manufacturability',
            'printer.prepare' if defect=='printer' else 'custom.operation')
        (folder/'events.jsonl').write_text(events)
    if defect in {'incomplete','wrong_spec'}:
        p=folder/'manifest.json';m=json.loads(p.read_text())
        m['pending_tools' if defect=='incomplete' else 'specimen_id']=1 if defect=='incomplete' else 'other'
        p.write_text(json.dumps(m))
    if defect=='context': c._state.run_metadata['_planning_resume_context']['cycle_index']=9
    if defect=='downstream': (folder.parent.parent/'manipulation_agent/attempt-000001').mkdir(parents=True)
    if defect=='no_archive': (folder/'events.jsonl').unlink()
    if defect=='missing_terminal':
        path=folder/'events.jsonl'
        path.write_text('\n'.join(line for line in path.read_text().splitlines() if 'tool_result' not in line))
    result=await resume_routing.dispatch(c)
    assert not result['ok'] and c._state.is_paused and not tasks
    c._run_planning_specimen_stage.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['flag','source','plc'])
async def test_safety_is_not_cleared_by_resume(tmp_path,kind):
    c,_,tasks=fixture(tmp_path)
    if kind=='flag': c._state.emergency_stop_requested=True
    if kind=='source': c._active_safety_sources=lambda:{'plc':'active'}
    if kind=='plc': c._plc_service_start_rejection.return_value={'ok':False,'status':'blocked'}
    assert not (await resume_routing.dispatch(c))['ok']
    assert c._state.is_paused and not tasks


@pytest.mark.asyncio
async def test_failed_retry_stays_same_cycle_and_does_not_enter_tail(tmp_path):
    c,_,tasks=fixture(tmp_path)
    c._run_planning_specimen_stage.side_effect=RuntimeError('mesh still rejected')
    assert (await resume_routing.dispatch(c))['ok']
    await tasks[0]
    assert c._state.stage==Stage.ERROR and c._state.is_paused and c._state.loop_count==7
    c._run_planning_cycle_series.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_pause_ignores_old_recovery_and_does_not_spawn(tmp_path):
    c,_,tasks=fixture(tmp_path)
    c._state.stage=Stage.MANIPULATION
    c._state.run_metadata['vision_ros_retry']={'status':'ready','run_id':'old','loop_id':1}
    gate=asyncio.Event();task=asyncio.create_task(gate.wait());c._run_task=task
    try:
        assert (await resume_routing.dispatch(c))['status']=='resumed'
        assert not c._state.is_paused and not tasks
    finally:
        gate.set();await task


@pytest.mark.asyncio
@pytest.mark.parametrize('key,module,function',resume_routing.ROUTES)
async def test_prepared_routes_are_run_and_cycle_scoped(tmp_path,monkeypatch,key,module,function):
    import importlib
    c,_,tasks=fixture(tmp_path)
    c._state.agent_status.clear();c._state.stage=Stage.COMPLETE
    marker={'status':'ready','run_id':'retry-run','loop_id':7,'cycle':7,'specimen_id':'s8'}
    c._state.run_metadata[key]=marker
    handler=AsyncMock(return_value={'ok':True,'route':key})
    monkeypatch.setattr(importlib.import_module(module),function,handler)
    assert (await resume_routing.dispatch(c))['route']==key
    marker['run_id']='old'
    assert not (await resume_routing.dispatch(c))['ok']
    marker.update(run_id='retry-run',loop_id=6,cycle=6)
    assert not (await resume_routing.dispatch(c))['ok']
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_inactive_pause_does_not_claim_execution_resumed(tmp_path):
    c,_,tasks=fixture(tmp_path);c._state.stage=Stage.ANALYSIS
    result=await resume_routing.dispatch(c)
    assert not result['ok'] and c._state.is_paused and not tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['stop','cycle','task_finished'])
async def test_paused_execution_is_rechecked_after_plc_await(tmp_path,change):
    c,_,tasks=fixture(tmp_path)
    gate=asyncio.Event(); task=asyncio.create_task(gate.wait()); c._run_task=task
    async def check():
        if change=='stop': c._state.safe_stop_requested=True
        if change=='cycle': c._state.loop_count+=1
        if change=='task_finished':
            gate.set(); await task
    c._plc_service_start_rejection.side_effect=check
    try:
        assert not (await resume_routing.dispatch(c))['ok']
        assert c._state.is_paused and not tasks
    finally:
        gate.set(); await task
