import asyncio
import json
from types import SimpleNamespace

import pytest

from agents import orchestrator_decision as decision
from orchestrator.state import Mode, OrchestratorState, Stage


def choice(tool='prepare_handoff', arguments=None, refs=None):
    return dict(tool=tool, arguments=arguments if arguments is not None else {'candidate': 'design'},
                reason='Evidence supports next action', evidence_refs=refs or ['context:a'])


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    async def complete(self, task, prompt, **kwargs):
        assert task == 'orchestrator_plan'
        self.prompts.append((json.loads(prompt), kwargs))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response()
        return SimpleNamespace(text=json.dumps(response), model='deterministic:unit')


def state():
    return OrchestratorState(run_id='run-a', experiment_id='exp-a', mode=Mode.TEST, stage=Stage.DESIGN)


def context():
    return {'scope': {'checkpoint': 'pre', 'revision': 1}, 'evidence': {'context:a': {'goal': 'compare'}},
            'handoff_candidates': ['design'], 'owners': ['design_agent'],
            'capabilities': {'design_agent': ['inspect']}, 'settings': {'max_steps': 3, 'timeout_s': 123}}


@pytest.mark.parametrize('payload', [choice('bridge.execute', {}), choice(arguments={'candidate': 'design', 'extra': True}),
    choice(refs=['invented']), choice(arguments=[]), [], {**choice(), 'extra': 1}])
def test_invalid_choices_rejected(payload):
    with pytest.raises(ValueError):
        decision.validate_choice(payload, {'prepare_handoff'}, {'context:a'})


@pytest.mark.asyncio
async def test_inspection_is_fed_back_before_real_handoff_effect():
    effects = []
    async def inspect(args):
        return {'evidence': {'result:b': {'accepted': True}}}
    async def handoff(args):
        effects.append(args)
        return {'handoff_id': 'handoff-1'}
    model = Model(choice('inspect_context', {'evidence_ids': ['context:a']}), choice(refs=['result:b']))
    result = await decision.decide_orchestration(state(), model, context=context(), handlers={'inspect_context': inspect, 'prepare_handoff': handoff})
    assert result['status'] == 'prepared'
    assert result['effect']['handoff_id'] == 'handoff-1'
    assert effects == [{'candidate': 'design'}]
    assert model.prompts[1][0]['evidence']['result:b']['accepted'] is True
    assert model.prompts[0][1]['timeout_s'] == 123
    assert len(result['trace']) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['candidate', 'evidence', 'scope', 'failure', 'budget', 'tool_error'])
async def test_no_success_or_duplicate_effect_for_invalid_or_failed_decisions(kind):
    ctx = context()
    effects = []
    async def handler(args):
        effects.append(args)
        if kind == 'tool_error':
            raise RuntimeError('write failed')
        return {}
    response = choice()
    if kind == 'candidate': response['arguments']['candidate'] = 'equipment'
    if kind == 'evidence': ctx['required_evidence'] = ['missing']
    if kind == 'scope':
        ctx['current_scope'] = lambda: {'checkpoint': 'other', 'revision': 1}
    if kind == 'failure': response = TimeoutError('model timeout')
    if kind == 'budget':
        ctx['settings']['max_steps'] = 1
        response = choice('inspect_context', {'evidence_ids': ['context:a']})
    result = await decision.decide_orchestration(state(), Model(response), context=ctx,
        handlers={'prepare_handoff': handler, 'inspect_context': handler})
    assert result['status'] in {'failed', 'deferred', 'review_required'}
    assert len(effects) == (1 if kind in {'budget', 'tool_error'} else 0)


@pytest.mark.asyncio
async def test_cancellation_propagates():
    with pytest.raises(asyncio.CancelledError):
        await decision.decide_orchestration(state(), Model(asyncio.CancelledError()), context=context(), handlers={})


@pytest.mark.asyncio
@pytest.mark.parametrize('response,pending,want', [
    ({'intent': 'question', 'reason': 'Asks about TEST mode', 'pending_id': None}, None, 'question'),
    ({'intent': 'confirm_pending', 'reason': 'yes', 'pending_id': 'fake'}, 'real', 'unclear'),
    ({'intent': 'confirm_pending', 'reason': 'yes', 'pending_id': None}, None, 'unclear'),
    ({'intent': 'confirm_pending', 'reason': 'yes', 'pending_id': 'real'}, 'real', 'confirm_pending'),
    ({'intent': 'start_run', 'reason': 'go', 'pending_id': None, 'mode': 'live'}, None, 'unclear'),
    (RuntimeError('offline'), None, 'unclear'),
])
async def test_intake_has_no_effect_and_requires_server_pending_id(response, pending, want):
    result = await decision.classify_chat_request(state(), Model(response), message='테스트모드가 뭐야?', pending_id=pending)
    assert result['intent'] == want
    assert set(result) == {'intent', 'reason', 'pending_id'}


@pytest.mark.asyncio
async def test_agent_preserves_archive_fields_but_never_falls_back_to_test_success():
    from agents.orchestrator_agent import OrchestratorAgent
    result = await OrchestratorAgent().run(state(), Model(RuntimeError('offline')))
    assert result.success is False
    assert result.data['orchestration_decision']['status'] == 'failed'
    assert result.data['decisions'][0]['schema'] == 'decision_register.v1'
    assert result.data['decisions'][0]['selected'] is None
    assert {'plan_text', 'model', 'mission_contract', 'orchestration_plan', 'orchestrator_control_plane',
            'orchestrator_followup', 'decisions', 'metrics'} <= set(result.data)


@pytest.mark.asyncio
async def test_agent_consumes_explicit_dispatch_context_without_changing_mode():
    from agents.orchestrator_agent import OrchestratorAgent
    current = state()
    current.run_metadata['execution_policy'] = 'execute'
    effects = []
    async def prepare(args):
        effects.append(args)
        return {'handoff_id': 'agent-handoff'}
    result = await OrchestratorAgent().run(current, Model(choice()),
        context=context(), handlers={'prepare_handoff': prepare})
    assert result.success is True
    assert result.data['orchestration_decision']['effect']['handoff_id'] == 'agent-handoff'
    assert effects == [{'candidate': 'design'}]
    assert current.mode == Mode.TEST
    assert current.run_metadata['execution_policy'] == 'execute'


@pytest.mark.asyncio
async def test_late_scope_change_after_model_never_calls_handler():
    ctx = context()
    live = {'checkpoint': 'pre', 'revision': 1}
    ctx['current_scope'] = lambda: live
    def late_response():
        live['revision'] = 2
        return choice()
    async def forbidden(args):
        pytest.fail('stale effect')
    result = await decision.decide_orchestration(state(), Model(late_response), context=ctx,
        handlers={'prepare_handoff': forbidden})
    assert result['status'] == 'failed'
    assert 'scope changed' in result['reason']


@pytest.mark.asyncio
async def test_additional_inspection_can_defer_without_handoff():
    async def inspect(args):
        return {'evidence': {'availability:a': {'status': 'unknown'}}}
    async def defer(args):
        return {'waiting_for': args['condition']}
    result = await decision.decide_orchestration(state(), Model(
        choice('inspect_availability', {'owner': 'design_agent', 'capability': 'inspect'}),
        choice('defer', {'condition': 'owner evidence'}, ['availability:a'])), context=context(),
        handlers={'inspect_availability': inspect, 'defer': defer})
    assert result['status'] == 'deferred'
    assert result['effect'] == {'waiting_for': 'owner evidence'}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    choice('inspect_availability', {'owner': 'rogue', 'capability': 'inspect'}),
    choice('inspect_availability', {'owner': 'design_agent', 'capability': 'execute'}),
    choice('request_owner_review', {'owner': 'rogue', 'issues': ['missing']}),
    choice('propose_setup_change', {'block_id': 'a', 'revision': 1, 'changes': {'hidden': True}}),
    choice('propose_setup_change', {'block_id': 'a', 'revision': 2, 'changes': {'research.goal': 'new'}}),
])
async def test_target_validation_precedes_any_effect(payload):
    ctx = context()
    ctx['setup_blocks'] = {'a': {'revision': 1, 'fields': ['research.goal']}}
    async def forbidden(args):
        pytest.fail('invalid target reached handler')
    result = await decision.decide_orchestration(state(), Model(payload), context=ctx,
        handlers={payload['tool']: forbidden})
    assert result['status'] == 'failed'


@pytest.mark.asyncio
async def test_rejected_handler_effect_is_not_prepared():
    async def reject(args):
        return {'status': 'rejected', 'reason': 'owner admission denied'}
    result = await decision.decide_orchestration(state(), Model(choice()), context=context(),
        handlers={'prepare_handoff': reject})
    assert result['status'] == 'failed'


@pytest.mark.asyncio
async def test_explicit_ok_false_handler_effect_never_reports_agent_success():
    from agents.orchestrator_agent import OrchestratorAgent
    async def reject(args):
        return {'ok': False, 'reason': 'owner admission denied'}
    result = await OrchestratorAgent().run(state(), Model(choice()), context=context(),
        handlers={'prepare_handoff': reject})
    assert result.success is False
    assert result.data['orchestration_decision']['status'] == 'failed'
    assert result.data['orchestration_decision']['reason'] == 'owner admission denied'


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout', [-1, True, float('nan')])
async def test_invalid_timeout_cannot_disable_configured_bounds(timeout):
    ctx = context()
    ctx['settings']['timeout_s'] = timeout
    async def forbidden(args):
        pytest.fail('invalid budget reached handler')
    result = await decision.decide_orchestration(state(), Model(choice()), context=ctx,
        handlers={'prepare_handoff': forbidden})
    assert result['status'] == 'failed'
    assert 'budget' in result['reason']
