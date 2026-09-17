from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from app import equipment_tail_recovery as recovery


def fixture():
    state = SimpleNamespace(run_id='run-1', experiment_id='exp-1', loop_count=1,
        current_experiment_spec={'specimen_id': 'specimen-1'}, run_metadata={},
        stop_requested=False, safe_stop_requested=False, emergency_stop_requested=False)
    record = {'identity': {'run_id':'run-1', 'experiment_id':'exp-1', 'specimen_id':'specimen-1',
        'sequence_id':'stacked-loop-0-review-source'}, 'lifecycle':'ESCALATED',
        'checkpoint': {'next_index':3, 'transitions':[
            {'block_id': block, 'phase':'skill', 'success':True}
            for block in ('prepare_next_specimen','start_test','monitor_contact_and_run')]},
        'workflow_result': {'data': {'failure_code':'EQUIPMENT_WORKFLOW_SCOPE_CHANGED',
            'equipment_skill_flow_execution': {'failure_code':'EQUIPMENT_AGENTIC_RUN_CANCELLED',
                'transitions':[{'block_id':'await_auto_return','outcome':'cancelled'}]}}}}
    return state, record


def test_accepts_only_completed_prefix_and_unstarted_return():
    state, record = fixture()
    assert recovery.boundary(state, record) == 0
    for mutate in (
        lambda s,r: setattr(s, 'run_id', 'other'),
        lambda s,r: setattr(s, 'loop_count', 2),
        lambda s,r: setattr(s, 'emergency_stop_requested', True),
        lambda s,r: s.run_metadata.update(active_safety_sources={'plc':'stop'}),
        lambda s,r: r['checkpoint'].update(next_index=4),
        lambda s,r: r['workflow_result']['data']['equipment_skill_flow_execution']['transitions'][-1].update(outcome='failed'),
        lambda s,r: r['checkpoint']['transitions'].pop(),
    ):
        s,r = deepcopy((state,record))
        mutate(s,r)
        with pytest.raises(ValueError):
            recovery.boundary(s,r)


def test_request_rejects_modified_receipt(tmp_path):
    import hashlib
    directory = tmp_path/'run-1'/'recovery'
    directory.mkdir(parents=True)
    proof = directory/'proof.json'
    proof.write_text('{}')
    request = {'run_id':'run-1','requested_by':'operator','evidence_hashes':{str(proof):recovery.digest(proof)}}
    raw = json.dumps(request)
    (directory/'equipment_tail_request.json').write_text(json.dumps({
        'payload_json':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest()}))
    assert recovery.read_request(tmp_path,'run-1') == request
    proof.write_text('{"modified":true}')
    with pytest.raises(ValueError, match='evidence changed'):
        recovery.read_request(tmp_path,'run-1')


@pytest.mark.asyncio
async def test_dispatches_original_loop_tail_once_without_standalone_device_calls(tmp_path, monkeypatch):
    from orchestrator.state import Stage
    state, _ = fixture()
    state.loop_count = 0
    state.is_paused = False
    state.run_metadata['equipment_tail_recovery'] = {'status':'ready'}
    request = {'run_id':'run-1','loop_id':0,'source_execution_id':'old',
        'experiment_spec':state.current_experiment_spec,'description':{'flow':{}}}
    monkeypatch.setattr(recovery,'read_request',lambda *a:request)
    monkeypatch.setattr(recovery,'validate',lambda *a:None)
    (tmp_path/'run-1'/'recovery').mkdir(parents=True)
    calls=[]
    async def tail(spec, **kwargs):
        calls.append((spec,kwargs))
        return {'ok':True,'decision':'continue'}
    async def emit(*args):
        pass
    controller=SimpleNamespace(_state=state,_deps=SimpleNamespace(run_root=tmp_path),
        _run_planning_loop_tail=tail,_planning_cycle_limit=lambda spec:20,_emit_control_event=emit)
    result=await recovery.continue_tail(controller,state.current_experiment_spec,1)
    assert result['ok']
    assert calls==[(state.current_experiment_spec,{'cycle_index':1,'total_cycles':20,'resume_stage':Stage.EQUIPMENT})]
    assert state.is_paused
    with pytest.raises(FileExistsError):
        await recovery.continue_tail(controller,state.current_experiment_spec,1)
    assert len(calls)==1


@pytest.mark.parametrize('age,error,physical,expected', [(0,'0',True,True),(60,'0',True,False),
    (0,'123',True,False),(0,'0',False,False)])
def test_monitor_resolution_requires_fresh_zero_error_physical_evidence(age,error,physical,expected):
    from datetime import datetime,timezone,timedelta
    now=datetime.now(timezone.utc)
    state,_=fixture()
    state.device_health={'printer':'blocking:BAMBU_DEVICE_ERROR'}
    base={'device_class':'printer','tool':'printer.status','failure_code':'BAMBU_DEVICE_ERROR',
        'device_id':'printer-a','device_identity':'physical-a','resolution_policy':'fresh_matching_device_report',
        'blocks_workflow':True,'created_at':(now-timedelta(seconds=120)).isoformat()}
    state.run_metadata['hardware_alerts']=[base, {**base,'device_class':'utm'}]
    health={'ok':True,'physical_transport':physical,'device_error':error,
        'selected_printer':{'profile_id':'printer-a'},'device_identity':'physical-a',
        'error_fields_observed':True,'observed_job_state':'FINISH',
        'mqtt_snapshot':{'ok':True,'received_at':(now-timedelta(seconds=age)).isoformat()}}
    result=recovery.reconcile_printer_observation(state,health)
    assert bool(result)==expected
    assert state.run_metadata['hardware_alerts'][1]['blocks_workflow']
    assert base['blocks_workflow'] is (not expected)


@pytest.mark.asyncio
async def test_real_equipment_workflow_skips_adopted_prefix_but_keeps_model_review(tmp_path,monkeypatch):
    from tests.unit.test_equipment_workflow_decision import setup_flow, Model
    agent,state,tools,executed,_,flow=setup_flow(tmp_path,monkeypatch)
    state.run_metadata['equipment_tail_recovery']={'status':'running'}
    checkpoint={'next_index':2,'run_context':{},'transitions':[
        {'block_id':name,'phase':'skill','success':True,'outcome':'completed','evidence':{}}
        for name in ('prepare','measure')]}
    request={'source_execution_id':'prior','checkpoint':checkpoint}
    monkeypatch.setattr(recovery,'read_request',lambda *a:deepcopy(request))
    monkeypatch.setattr(recovery,'validate',lambda *a:None)
    model=Model(tools)
    result=await agent.run(state,model)
    assert result.success
    assert executed==['export']
    assert [c[0]['phase'] for c in model.calls]==['select','terminal_review']
    assert model.calls[0][0]['completed_blocks']==['prepare','measure']
