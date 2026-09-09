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


@pytest.mark.asyncio
async def test_mesh_decision_deduplicates_receipt_but_keeps_quality_and_identity():
    ctx = Context({'option_id': 'solve_mesh', 'reason': 'Prepared mesh is numerically admissible.'})
    quality = {'validity': {'status': 'valid', 'element_count': 159772},
               'quality': {'minimum': .001, 'percentile_5': .24, 'below_threshold_fraction': .01}}
    prepared = {'ok': True, 'mesh_quality': quality, 'target_displacement_mm': 15,
                'request': {'long_diagnostic': 'x' * 12000},
                'manifest': {'long_diagnostic': 'x' * 12000},
                'artifacts': {'inp_path': '/artifacts/' + 'x' * 6000},
                'prepared_input': {'schema': 'cae_prepared_input.v1', 'request_sha256': 'a' * 64,
                                   'mesh_sha256': 'b' * 64, 'target_displacement_mm': 15,
                                   'request': {'long_diagnostic': 'x' * 12000}, 'mesh_quality': quality}}
    await module.decide(ctx, 'fem_mesh_assessment', {'prepared': prepared,
                        'summary': {'target_displacement_mm': 15}}, {'solve_mesh': 'cae.run_static_analysis'}, background=True)
    sent = ctx.requests[0][1]
    assert len(json.dumps(sent)) < 8000
    assert sent['evidence']['prepared']['mesh_quality'] == quality
    assert sent['evidence']['prepared']['prepared_input']['mesh_sha256'] == 'b' * 64
    assert sent['evidence']['prepared']['target_displacement_mm'] == 15
    assert len(prepared['request']['long_diagnostic']) == 12000


@pytest.mark.asyncio
async def test_long_calibration_history_keeps_best_and_recent_errors_in_local_context():
    ctx = Context({'option_id': 'hold', 'reason': 'More numerical evidence is required.'})
    records = [{'parameters': {'peak_flow_mpa': i + 1}, 'comparison': {'objective': i + 1},
                'material': {'plastic_curve': [[50, j / 100] for j in range(100)]}}
               for i in range(32)]
    evidence = {'calibration': {'records': records, 'best_parameters': {'peak_flow_mpa': 1},
                               'best_comparison': {'objective': 1}}}
    await module.decide(ctx, 'fem_calibration_review', evidence, {'hold': None}, background=True)
    sent = ctx.requests[0][1]['evidence']['calibration']
    assert len(json.dumps(ctx.requests[0][1])) < 8000
    assert sent['best_parameters'] == {'peak_flow_mpa': 1}
    assert sent['records'][-1]['comparison']['objective'] == 32
    assert sent['records_total'] == 32
    assert len(records) == 32


@pytest.mark.parametrize('curve, expected', [
    ([[0, 0], [1, 2]], 2),
    ({'count': 2113, 'sampled_preview': [[0, 0], [1, 2]]}, 2113),
    (None, None),
])
def test_comparison_curve_projection_preserves_known_count(curve, expected):
    result = module.fem_decision_evidence({'comparison_curve': curve})
    assert result['comparison_curve'] == {'source': 'experiment_curve', 'count': expected}
