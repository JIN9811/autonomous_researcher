"""LLM may select registered analysis tools, never edit physical inputs."""
import json
from types import SimpleNamespace

import pytest
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
