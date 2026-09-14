"""LLM may select registered analysis tools, never edit physical inputs."""
import json
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_validation_distinguishes_warnings_from_blocking_quality_checks():
    from agents.analysis.decisions import decide
    from types import SimpleNamespace
    prompts = []
    class Ctx:
        async def complete(self, task, prompt, **kwargs):
            prompts.append(json.loads(prompt))
            return SimpleNamespace(text='{"option_id":"hold","reason":"An independent inconsistency remains."}')
    result = await decide(Ctx(), 'data_validation', {'quality_gate': {'ok_for_metrics': True,
        'ok_for_bo': True, 'warnings': ['peak_at_curve_boundary']}}, {'accept':'analysis.accept_metrics','hold':None})
    assert 'not by itself' in prompts[0]['instructions']
    assert prompts[0]['evidence']['quality_gate']['warnings'] == ['peak_at_curve_boundary']
    assert result['tool'] is None  # Advice never forces model acceptance.
from agents.analysis import decisions as module


class Context:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def complete(self, route, prompt, **kwargs):
        self.requests.append((route, json.loads(prompt), kwargs))
        return SimpleNamespace(text=json.dumps(self.response))


@pytest.mark.asyncio
async def test_decision_uses_registered_route_and_validated_tool_selection():
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    ctx = Context({'option_id': 'analyze', 'reason': 'Validate the provided measurement.'})
    decision = await module.decide(ctx, 'data_processing', {'point_count': 12}, {'analyze': 'analysis.process_curve', 'hold': None})
    assert decision['tool'] == 'analysis.process_curve'
    assert decision['source'] == 'llm'
    assert ctx.requests[0][0] == 'analysis_reasoning'


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {'option_id': 'equipment.run', 'reason': 'run'},
    {'option_id': 'analyze', 'reason': 'run', 'parameters': {'target_strain': 0.9}},
    {'option_id': 'analyze'},
])
async def test_rejects_unregistered_tool_and_input_mutation(response):
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    with pytest.raises(ValueError):
        await module.decide(Context(response), 'data_processing', {}, {'analyze': 'analysis.process_curve'})


@pytest.mark.asyncio
async def test_explicit_virtual_decision_does_not_call_model():
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    ctx = Context({})
    decision = await module.decide(ctx, 'data', {}, {'analyze': 'analysis.process_curve'}, virtual=True)
    assert decision['source'] == 'virtual_test'
    assert decision['tool'] == 'analysis.process_curve'
    assert ctx.requests == []
