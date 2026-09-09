"""LLM may select registered analysis tools, never edit physical inputs."""
import json
from types import SimpleNamespace

import pytest
from agents import analysis_decisions as module


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
    ctx = Context({'option_id': 'run_cae', 'reason': 'Compare against the approved baseline.'})
    decision = await module.decide(ctx, 'simulation', {'model': 'baseline'}, {'run_cae': 'cae.run_static_analysis', 'hold': None})
    assert decision['tool'] == 'cae.run_static_analysis'
    assert decision['source'] == 'llm'
    assert ctx.requests[0][0] == 'analysis_reasoning'


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {'option_id': 'equipment.run', 'reason': 'run'},
    {'option_id': 'run_cae', 'reason': 'run', 'parameters': {'target_strain': 0.9}},
    {'option_id': 'run_cae'},
])
async def test_rejects_unregistered_tool_and_input_mutation(response):
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    with pytest.raises(ValueError):
        await module.decide(Context(response), 'simulation', {}, {'run_cae': 'cae.run_static_analysis'})


@pytest.mark.asyncio
async def test_explicit_virtual_decision_does_not_call_model():
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    ctx = Context({})
    decision = await module.decide(ctx, 'data', {}, {'analyze': 'analysis.process_curve'}, virtual=True)
    assert decision['source'] == 'virtual_test'
    assert decision['tool'] == 'analysis.process_curve'
    assert ctx.requests == []


@pytest.mark.asyncio
async def test_background_model_call_has_lower_priority():
    assert hasattr(module, 'decide'), 'analysis tool decision protocol required'
    ctx = Context({'option_id': 'hold', 'reason': 'Independent evidence missing.'})
    await module.decide(ctx, 'improvement', {}, {'hold': None}, background=True)
    assert ctx.requests[0][2]['priority'] > 10


@pytest.mark.asyncio
async def test_background_loads_only_valid_images_inside_artifact_root(tmp_path):
    from PIL import Image
    root = tmp_path/'runs'; root.mkdir()
    valid, outside, bad = root/'mesh.png', tmp_path/'outside.png', root/'bad.png'
    Image.new('RGB', (4, 4)).save(valid)
    Image.new('RGB', (4, 4)).save(outside)
    bad.write_text('not an image')
    ctx = Context({'option_id':'hold','reason':'Visual and numeric evidence inspected.'})
    ctx.artifact_run_root = str(root)
    await module.decide(ctx,'fem_mesh_assessment', {'image_paths':[str(valid),str(outside),str(bad)]},
                        {'hold':None},background=True)
    images = ctx.requests[0][2]['images']
    assert len(images)==1 and images[0].data==valid.read_bytes()


@pytest.mark.asyncio
async def test_fem_prompt_does_not_send_raw_mesh_or_field_arrays():
    ctx=Context({'option_id':'conclude','reason':'Actual numeric comparison inspected.'})
    evidence={'attempts':[{'comparison':{'work_error_pct':12},'field_summary':{
        'geometry':{'points':[[0,0,0]]*10000}, 'frames':[{'fields':{'U':{
            'units':'mm','values':[[0,0,0]]*10000}}}]}}]}
    await module.decide(ctx,'fem_result',evidence,{'conclude':None},background=True)
    sent=ctx.requests[0][1]['evidence']
    assert len(json.dumps(sent))<5000
    assert sent['attempts'][0]['comparison']['work_error_pct']==12
    assert len(evidence['attempts'][0]['field_summary']['frames'][0]['fields']['U']['values'])==10000
