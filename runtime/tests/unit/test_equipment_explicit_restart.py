from copy import deepcopy
from types import SimpleNamespace
import pytest
from agents.equipment import workflow


def fixture():
    identity=dict(run_id='r',experiment_id='e',specimen_id='s',sequence_id='stacked-loop-9')
    source=dict(execution_id='old',identity=identity,lifecycle='ESCALATED',
        workflow_result={'success':False})
    request=dict(run_id='r',loop_id=9,specimen_id='s',requested_by='operator',
                 source_execution_id='old',attempt_id='abc123')
    state=SimpleNamespace(run_id='r',experiment_id='e',loop_count=9,
        current_experiment_spec={'specimen_id':'s'},run_metadata={'equipment_explicit_restart':request})
    return state,source


def test_explicit_retry_has_new_identity_without_mutating_failed_record():
    state,source=fixture(); old=deepcopy(source)
    fn=getattr(workflow,'explicit_restart_suffix',lambda *args:'')
    assert fn(state,SimpleNamespace(get=lambda key:source))=='-restart-abc123'
    assert source==old


@pytest.mark.parametrize('fault',['other_specimen','completed','not_operator','bad_attempt'])
def test_refuses_unproven_explicit_restart(fault):
    state,source=fixture()
    if fault=='other_specimen': source['identity']['specimen_id']='different'
    if fault=='completed': source['lifecycle']='COMPLETED'
    if fault=='not_operator': state.run_metadata['equipment_explicit_restart']['requested_by']='model'
    if fault=='bad_attempt': state.run_metadata['equipment_explicit_restart']['attempt_id']='../'
    fn=getattr(workflow,'explicit_restart_suffix',lambda *args:'')
    with pytest.raises(ValueError): fn(state,SimpleNamespace(get=lambda key:source))


def test_ordinary_and_later_cycles_unchanged():
    state,source=fixture(); state.loop_count=10
    assert workflow.explicit_restart_suffix(state,None)==''
    state.run_metadata.clear()
    assert workflow.explicit_restart_suffix(state,None)==''
