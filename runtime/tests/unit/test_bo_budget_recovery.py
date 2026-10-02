import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from orchestrator.state import OrchestratorState, Stage


def state_fixture():
    state = OrchestratorState(run_id='run', experiment_id='exp', loop_count=7,
        stage=Stage.GUARDIAN, is_paused=True, current_experiment_spec={'specimen_id': 's8'})
    m = state.run_metadata
    m['planning_cycle_contract'] = {'schema': 'planning_cycle_contract.v1', 'total_cycles': 15}
    m['_planning_resume_context'] = {'cycle_index': 8, 'total_cycles': 15,
        'current_spec': {'specimen_id': 's8'}, 'design_constraints': {}}
    m['guardian_recovery_wait'] = {'status': 'waiting', 'run_id': 'run', 'loop_id': 7, 'specimen_id': 's8'}
    m['bo_settings'] = {'budget': 8}
    m['bo_agent'] = {'run_id': 'run', 'experiment_id': 'exp', 'failure_code': 'BO_OWNER_REVIEW',
        'decision': {'status': 'returned', 'optimizer_result': None,
            'reason': '8 finite observations and experiment budget is 8',
            'diagnostics': {'finite_observation_count': 8}}}
    m['guardian_gates'] = [{'gate_id': 'old', 'run_id': 'run', 'loop_id': 7, 'stage': 'bo',
        'phase': 'post', 'decision': 'block', 'reason_code': 'AGENT_RESULT_FAILED',
        'alarms': [{'reason_code': 'BO_CANDIDATE_UNSAFE', 'message': 'BO_OWNER_REVIEW',
            'source_path': 'payload.bo_result'}]}]
    for name in ('equipment_agent', 'analysis_agent', 'knowledge_agent'):
        from orchestrator.state import AgentRuntimeStatus
        state.agent_status[name] = AgentRuntimeStatus(state='done', success=True, run_id='run', loop_id=7)
    return state


def test_budget_recovery_keeps_cycle_and_evidence_and_only_resolves_budget_gate():
    from app.bo_budget_recovery import prepare_state
    state = state_fixture()
    original = deepcopy(state.model_dump())
    restored = prepare_state(state)
    assert state.model_dump() == original
    assert restored.stage == Stage.BO and restored.is_paused
    assert restored.loop_count == 7 and restored.current_experiment_spec == {'specimen_id': 's8'}
    assert restored.run_metadata['bo_settings']['budget'] == 15
    gate = restored.run_metadata['guardian_gates'][0]
    assert gate['decision'] == 'block' and gate['audit_log']['lifecycle'] == 'resolved'
    assert restored.agent_status == state.agent_status


def test_saved_bo_checkpoint_restores_transcript_and_rejects_corruption(tmp_path):
    from app.bo_budget_recovery import save, restore
    from app.run_recovery import restore_checkpoint
    transcript = tmp_path / 'session/live_planning_transcript.jsonl'
    transcript.parent.mkdir()
    transcript.write_text(json.dumps({'role': 'user', 'content': 'existing run'}) + '\n')
    state = state_fixture()
    path = save({'state': state.model_dump(mode='json')},
        {'planning_session_id': 'session', 'transcript_path': str(transcript)}, tmp_path)
    controller = SimpleNamespace(_state=OrchestratorState(run_id='startup', experiment_id='startup', stage=Stage.IDLE),
        _deps=SimpleNamespace(run_root=tmp_path, logging_config={}),
        snapshot=lambda: {'is_running': False}, _active_safety_sources=lambda: [])
    assert restore_checkpoint(controller, 'run')['status'] == 'bo_resume_ready'
    assert controller._state.run_id == 'run' and controller._state.loop_count == 7
    assert controller._planning_messages == [{'role': 'user', 'content': 'existing run'}]
    assert controller._planning_message_total == 1
    with pytest.raises(ValueError): restore(controller, 'run')
    controller._state = OrchestratorState(run_id='startup', experiment_id='startup', stage=Stage.IDLE)
    envelope = json.loads(path.read_text())
    envelope['payload'] += ' '
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='integrity'): restore(controller, 'run')


@pytest.mark.parametrize('fault', ['safety', 'other_gate', 'other_loop', 'already_optimized', 'completed_budget', 'wrong_specimen'])
def test_budget_recovery_rejects_unrelated_or_changed_boundary(fault):
    from app.bo_budget_recovery import prepare_state
    state = state_fixture()
    if fault == 'safety': state.safe_stop_requested = True
    elif fault == 'other_gate': state.run_metadata['guardian_gates'].append({'decision': 'block', 'stage': 'equipment'})
    elif fault == 'other_loop': state.loop_count = 8
    elif fault == 'already_optimized': state.run_metadata['bo_agent']['decision']['optimizer_result'] = {'ok': True}
    elif fault == 'completed_budget': state.run_metadata['planning_cycle_contract']['total_cycles'] = 8
    elif fault == 'wrong_specimen': state.current_experiment_spec = {'specimen_id': 's9'}
    with pytest.raises(ValueError): prepare_state(state)


@pytest.mark.asyncio
async def test_budget_resume_dispatches_bo_only_once():
    from app.bo_budget_recovery import prepare_state, resume
    state = prepare_state(state_fixture())
    tasks = []
    tail = AsyncMock(return_value={'ok': True})
    controller = SimpleNamespace(_state=state, _error_resume_lock=asyncio.Lock(),
        _planning_handoff_active=lambda: bool(tasks and not tasks[0].done()),
        _active_safety_sources=lambda: [], _plc_service_start_rejection=AsyncMock(return_value=None),
        _set_planning_handoff_task=tasks.append, _run_planning_cycle_series=tail,
        _emit_control_event=AsyncMock())
    result = await resume(controller)
    assert result['resume_stage'] == 'bo' and result['cycle_index'] == 8
    assert (await resume(controller))['status'] == 'already_running'
    await tasks[0]
    assert tail.await_args.kwargs['resume_tail_stage'] == Stage.BO
    assert tail.await_args.kwargs['start_cycle'] == 8
    assert len(tasks) == 1
