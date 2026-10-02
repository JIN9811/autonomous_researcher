from copy import deepcopy

import pytest

from agents.core.guardian.agent import GuardianAgent
from knowledge.failure_memory import FailureRecord
from orchestrator.state import OrchestratorState
from policies.guardian_gate import _preprint_validation_evidence
from policies.guardian_gate_lifecycle import resolve_image_rechecks
from tests.unit.test_guardian_agent import _valid_spec


def records():
    old={'specimen_id':'s','execution_id':'old','attempt_index':1,'execution_status':'failed',
         'geometry':'pass','mesh':'pass','manufacturability':'fail','wall_status':'unverified','stl_sha256':'a'*64}
    failed={'gate_id':'failed','run_id':'run','experiment_id':'exp','loop_id':7,'stage':'specimen','phase':'post',
        'agent':'specimen_agent','tool':'','action':'','decision':'block','reason_code':'MANUFACTURABILITY_REJECTED',
        'created_at':'2026-09-19T01:00:00+00:00','audit_log':{'preprint_validation':old},
        'alarms':[{'reason_code':'MANUFACTURABILITY_REJECTED','source_path':'payload'}]}
    passed={**deepcopy(failed),'gate_id':'passed','decision':'allow_with_warning','reason_code':'WARN',
        'created_at':'2026-09-19T02:00:00+00:00','ok_for_next_stage':True,'alarms':[],
        'audit_log':{'preprint_validation':{**old,'execution_id':'new','attempt_index':2,'execution_status':'completed',
                                         'manufacturability':'pass','wall_status':'pass','stl_sha256':'b'*64}}}
    return [failed,passed]


def test_recheck_resolves_only_prior_manufacturing_hold_without_deleting_history():
    gates=records();incidents=[{'incident_id':'failed','status':'open'}]
    resolve_image_rechecks(gates,incidents)
    assert gates[0]['decision']=='block'
    assert gates[0]['audit_log']['resolved_by']=='passed' and incidents[0]['status']=='resolved'
    state=OrchestratorState(run_id='run',experiment_id='exp',run_metadata={'guardian_gates':gates,'incident_records':incidents})
    assert GuardianAgent._resolve_graph_gate_pressure(state)['active_gate_count']==0


@pytest.mark.parametrize('field,value',[
    ('run_id','other'),('loop_id',8),('phase','pre'),('decision','block'),('ok_for_next_stage',False),
    ('created_at','2026-09-19T00:00:00+00:00'),
])
def test_other_scope_or_nonpassing_gate_never_resolves(field,value):
    gates=records();gates[1][field]=value;resolve_image_rechecks(gates,[])
    assert 'resolved_by' not in gates[0]['audit_log']


@pytest.mark.parametrize('field,value',[
    ('specimen_id','different'),('execution_id','old'),('attempt_index',1),('execution_status','failed'),
    ('geometry','fail'),('mesh','fail'),('manufacturability','fail'),('wall_status','unverified'),('stl_sha256',''),
])
def test_recheck_needs_fresh_bound_actual_validation(field,value):
    gates=records();gates[1]['audit_log']['preprint_validation'][field]=value
    resolve_image_rechecks(gates,[])
    assert 'resolved_by' not in gates[0]['audit_log']


@pytest.mark.parametrize('alarm',[
    {'reason_code':'COLLISION_RISK','source_path':'payload'},
    {'reason_code':'CONTRACT_SCHEMA_INVALID','source_path':'payload.measurement_contract'},
    {'reason_code':'CONTRACT_SCHEMA_INVALID','source_path':'payload.fabrication_report.quality_gates[9]'},
    {'reason_code':'HUMAN_APPROVAL_REQUIRED','source_path':'payload'},
])
def test_current_other_hazard_is_not_cleared(alarm):
    gates=records();gates[0]['alarms'].append(alarm)
    resolve_image_rechecks(gates,[])
    assert 'resolved_by' not in gates[0]['audit_log']


def test_legacy_unbound_gate_cannot_be_released_by_a_generic_success():
    gates=records();gates[0]['audit_log'].clear();resolve_image_rechecks(gates,[])
    assert 'resolved_by' not in gates[0]['audit_log']


def test_current_manifest_and_fabrication_must_match_before_recording_evidence():
    state=OrchestratorState(run_id='r',experiment_id='e',loop_count=2,current_experiment_spec={'specimen_id':'s'})
    payload={'artifact_execution':{'run_id':'r','loop_index':2,'specimen_id':'s','execution_id':'x',
        'agent':'specimen_agent','attempt_index':2,'status':'completed'},'fabrication_report':{
        'digital_thread':{'run_id':'r','specimen_id':'s'},'quality_gates':[
            {'gate':'geometry','status':'pass'},{'gate':'mesh','status':'pass'},
            {'gate':'manufacturability','status':'pass','evidence':{
                'wall_thickness_verification':{'status':'pass','stl_sha256':'b'*64}}}]}}
    proof=_preprint_validation_evidence(payload,state,'specimen','post')
    assert proof['execution_id']=='x' and proof['wall_status']=='pass'
    payload['artifact_execution']['loop_index']=1
    assert not _preprint_validation_evidence(payload,state,'specimen','post')


def test_historical_pattern_is_advisory_but_current_invalid_design_still_blocks():
    spec=_valid_spec();memory=[FailureRecord(stage='specimen',failure_type='mesh',context={'specimen_id':spec['specimen_id']})]
    result=GuardianAgent()._validate_design_spec(spec,memory)
    assert result['status']=='warning' and not result['reject_reasons']
    assert result['warnings'][0].startswith('Historical failure reference:')
    spec['wall_thickness_mm']=0.01
    assert GuardianAgent()._validate_design_spec(spec,memory)['status']=='fail'
