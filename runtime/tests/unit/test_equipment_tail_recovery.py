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


def test_selected_memory_tail_receipt_blocks_unstarted_retry(tmp_path):
    from dataclasses import replace
    from utils.runtime_paths import current_paths
    state, _ = fixture()
    state.run_metadata['equipment_tail_recovery'] = {'status': 'returned', 'result': {'decision': 'stop'}}
    request = {'run_id': state.run_id, 'loop_id': 0, 'source_execution_id': 'source'}
    paths = replace(current_paths(), memory_root=tmp_path / 'selected-memory')
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(agent_context=SimpleNamespace(paths=paths)))
    assert recovery.unstarted_tail(controller, request)
    path = paths.memory_root / 'equipment_runtime/workflow_decisions/executions/selected/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'identity': {'run_id': state.run_id, 'sequence_id': 'stacked-loop-0-tail-source'}}))
    original = path.read_bytes()
    assert not recovery.unstarted_tail(controller, request)
    assert path.read_bytes() == original


def test_preparation_reads_selected_record_before_rejecting_identity(tmp_path):
    from dataclasses import replace
    from utils.runtime_paths import current_paths
    from orchestrator.state import OrchestratorState, Stage
    paths = replace(current_paths(), memory_root=tmp_path / 'selected-memory', run_root=tmp_path / 'selected-runs')
    path = paths.memory_root / 'equipment_runtime/workflow_decisions/executions/source/state.json'
    path.parent.mkdir(parents=True)
    _, record = fixture()
    path.write_text(json.dumps(record))
    state = OrchestratorState(run_id='different-run', experiment_id='exp-1', stage=Stage.ERROR)
    with pytest.raises(ValueError, match='identity/cycle mismatch'):
        recovery.prepare_request({'state': state.model_dump(mode='json'), 'is_running': False},
            paths.run_root, 'source', ctx=SimpleNamespace(paths=paths))


@pytest.mark.parametrize('mutation', [None, 'deployment', 'evidence'])
def test_tail_ready_resume_authenticates_real_selected_request(tmp_path, monkeypatch, mutation):
    from dataclasses import replace
    import hashlib
    import shutil
    from utils.runtime_paths import current_paths
    from tests.unit.test_equipment_workflow_decision import setup_flow
    from agents.equipment.workflow import _describe
    from app.run_recovery import prepare_error_resume
    from orchestrator.state import Stage
    agent, state, _, executed, _, flow = setup_flow(tmp_path, monkeypatch)
    paths = replace(current_paths(), memory_root=tmp_path / 'selected-memory', run_root=tmp_path / 'selected-runs')
    shutil.copytree(tmp_path / 'skills', paths.memory_root / 'equipment_skills')
    state.current_experiment_spec.pop('equipment_skill_registry_root')
    state.current_experiment_spec['specimen_id'] = 'specimen-selected-tail'
    state.stage = Stage.ERROR
    state.run_metadata['equipment_tail_recovery'] = {'status': 'ready'}
    ctx = SimpleNamespace(paths=paths)
    _, source = fixture()
    source['identity'].update(run_id=state.run_id, experiment_id=state.experiment_id,
        specimen_id=state.current_experiment_spec['specimen_id'])
    source_path = paths.memory_root / 'equipment_runtime/workflow_decisions/executions/source/state.json'
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(source))
    request = {'run_id': state.run_id, 'requested_by': 'operator', 'loop_id': 0,
        'source_execution_id': 'source', 'source_path': str(source_path),
        'evidence_hashes': {str(source_path): recovery.digest(source_path)},
        'description': _describe(agent, state, flow, ctx=ctx),
        'experiment_spec': deepcopy(state.current_experiment_spec)}
    raw = json.dumps(request)
    request_path = paths.run_root / state.run_id / 'recovery/equipment_tail_request.json'
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps({'payload_json': raw, 'sha256': hashlib.sha256(raw.encode()).hexdigest()}))
    original = request_path.read_bytes()
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=paths.run_root, agent_context=ctx),
        snapshot=lambda: {'state': state.model_dump(mode='json'), 'is_running': False})
    if mutation == 'deployment':
        path = paths.memory_root / 'equipment_skills/prepare/1.0.0/manifest.json'
        data = json.loads(path.read_text())
        data['deployment']['deployment_sha256'] = 'changed'
        path.write_text(json.dumps(data))
    elif mutation == 'evidence':
        source_path.write_text(source_path.read_text() + ' ')
    if mutation:
        with pytest.raises(ValueError, match='deployed programs changed' if mutation == 'deployment' else 'evidence changed'):
            prepare_error_resume(controller)
    else:
        assert prepare_error_resume(controller) == 'source'
    assert request_path.read_bytes() == original and executed == []


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
    request={'source_execution_id':'prior','checkpoint':checkpoint, 'run_id':state.run_id,
        'requested_by':'operator','evidence_hashes':{}}
    from dataclasses import replace
    from utils.runtime_paths import current_paths
    import hashlib
    paths=replace(current_paths(),run_root=tmp_path/'selected-runs', memory_root=tmp_path/'selected-memory')
    directory=paths.run_root/state.run_id/'recovery'
    directory.mkdir(parents=True)
    raw=json.dumps(request)
    (directory/'equipment_tail_request.json').write_text(json.dumps({
        'payload_json':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest()}))
    monkeypatch.setattr(recovery,'validate',lambda *a,**kw:None)
    model=Model(tools)
    model.paths=paths
    result=await agent.run(state,model)
    assert result.success
    assert executed==['export']
    assert [c[0]['phase'] for c in model.calls]==['select','terminal_review']
    assert model.calls[0][0]['completed_blocks']==['prepare','measure']
