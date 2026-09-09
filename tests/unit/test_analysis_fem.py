"""Study orchestration tests; every external solver/LLM boundary is injected."""
import asyncio
from copy import deepcopy
import hashlib
import importlib
import importlib.util

import pytest


def study():
    assert importlib.util.find_spec('agents.analysis_fem'), 'FEM study module is required'
    return importlib.import_module('agents.analysis_fem').run_fem_study


def evidence(tmp_path, **patch):
    source = tmp_path / 'frozen.stl'
    source.write_bytes(b'frozen geometry')
    return {
        'job_id': 'job-one', 'acquisition_ids': ['only-one'],
        'input_hashes': {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
        'payload': {'specimen_id': 'original', 'stl_path': str(source),
                    'mesh_size_mm': 2.0, 'gauge_length_mm': 20.0,
                    'material': {'yield_strength_mpa': 35.0},
                    'loading': {'target_strain': 0.5}},
        'observation': [[0, 0], [5, 50], [10, 100]],
        'specimen_geometry': {'gauge_length_mm': 20.0},
        **patch,
    }


def solved(end=10, scale=1.0, ok=True):
    return {'ok': ok, 'status': 'complete' if ok else 'partial',
            'reaction_force_displacement_curve': [
                {'displacement_mm': x, 'force_N': x * 10 * scale}
                for x in [0, end / 2, end]],
            'artifacts': {'field_asset_path': '/saved/fields.json'},
            'field_manifest': {'frames': [{'max_stress_MPa': 15.0}]}}


class Boundaries:
    def __init__(self, choices, *, qualities=None, results=None):
        self.choices = iter(choices)
        self.qualities = iter(qualities or [{'validity': 'valid', 'quality': 'good'}] * 6)
        self.results = iter(results or [solved()] * 6)
        self.calls, self.decisions, self.events = [], [], []

    async def choose(self, phase, data, options):
        selected = next(self.choices)
        self.decisions.append((phase, deepcopy(data), deepcopy(options)))
        return {'option_id': selected, 'reason': 'bounded assessment',
                'source': 'llm', 'tool': options.get(selected)}

    async def call(self, name, payload):
        self.calls.append((name, deepcopy(payload)))
        if name == 'cae.prepare_static_analysis':
            return {'ok': True, 'prepared_input': {'inp_path': '/saved/prepared.inp'},
                    'mesh_quality': next(self.qualities), 'paths': {}}
        assert name == 'cae.run_static_analysis'
        return next(self.results)

    async def run(self, data):
        return await study()(data, self.choose, self.call, self.events.append)


@pytest.mark.asyncio
async def test_one_acquisition_can_solve_without_material_promotion(tmp_path):
    data = evidence(tmp_path, run_id='r', loop_key='r:loop-2')
    original = deepcopy(data)
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    result = await io.run(data)
    assert result['status'] == 'completed'
    assert data == original
    attempt = result['attempts'][0]
    assert attempt['endpoint_reached'] is True
    assert attempt['comparison'] == {'end_mm': 10.0, 'peak_error_pct': 0.0,
                                     'work_error_pct': 0.0, 'rmse_N': 0.0}
    assert attempt['field_asset_path'] == '/saved/fields.json'
    assert result['summary']['convergence']['status'] == 'not_assessed'
    for _, payload in io.calls:
        assert payload['material'] == original['payload']['material']
        assert payload['loading'] == original['payload']['loading']
        assert payload['specimen_id'] != 'original'
        assert payload['original_specimen_id'] == 'original'
        assert payload['run_id'] == 'r' and payload['loop_key'] == 'r:loop-2'
        assert payload['computation_limits']['timeout_s'] is None
    assert io.calls[1][1]['prepared_input']['inp_path'] == '/saved/prepared.inp'
    assert io.decisions[-1][1]['attempts'][0]['curve'] == solved()['reaction_force_displacement_curve']
    assert any(event.get('attempts') for event in io.events)


@pytest.mark.asyncio
async def test_failed_final_llm_review_preserves_completed_native_result_without_rerun(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh'])
    async def choose(phase, data, options):
        if phase == 'fem_result':
            raise RuntimeError('empty LLM response')
        return await io.choose(phase, data, options)
    result = await study()(evidence(tmp_path), choose, io.call, io.events.append)
    assert result['status'] == 'completed'
    assert result['attempts'][0]['endpoint_reached'] is True
    assert result['attempts'][0]['field_asset_path'] == '/saved/fields.json'
    assert result['attempts'][0]['curve'] == solved()['reaction_force_displacement_curve']
    assert [name for name, _ in io.calls] == ['cae.prepare_static_analysis', 'cae.run_static_analysis']
    assert result['summary']['review_status'] == 'failed'
    assert result['decisions'][-1]['accepted'] is False
    assert result['decisions'][-1]['error_type'] == 'RuntimeError'
    assert result['summary']['material_promoted'] is False


@pytest.mark.asyncio
async def test_failed_mesh_llm_review_holds_without_native_execution(tmp_path):
    io = Boundaries([])
    async def choose(*args):
        raise ValueError('invalid decision response')
    result = await study()(evidence(tmp_path), choose, io.call, io.events.append)
    assert result['status'] == 'held'
    assert not io.calls
    assert result['summary']['review_status'] == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('quality', [
    {'validity': 'invalid', 'quality': 'good'},
    {'validity': 'valid', 'quality': 'poor'},
    {},
])
async def test_invalid_or_poor_mesh_cannot_solve_even_with_unbounded_choice(tmp_path, quality):
    io = Boundaries(['prepare_mesh', 'solve_mesh'], qualities=[quality])
    result = await io.run(evidence(tmp_path))
    assert [name for name, _ in io.calls] == ['cae.prepare_static_analysis']
    assert 'solve_mesh' not in io.decisions[-1][2]
    assert result['attempts'][0]['endpoint_reached'] is False


@pytest.mark.asyncio
async def test_partial_solver_retains_actual_curve_and_same_interval_metrics(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'], results=[solved(5, 0.8, False)])
    result = await io.run(evidence(tmp_path))
    attempt = result['attempts'][0]
    assert result['status'] == 'partial'
    assert attempt['solver_status'] == 'partial'
    assert attempt['endpoint_reached'] is False
    assert attempt['curve'][-1] == {'displacement_mm': 5.0, 'force_N': 40.0}
    assert attempt['comparison']['end_mm'] == 5.0
    assert attempt['comparison']['peak_error_pct'] == pytest.approx(-20)
    assert attempt['comparison']['work_error_pct'] == pytest.approx(-20)
    assert attempt['comparison']['rmse_N'] == pytest.approx(10 / 3**0.5)
    assert result['summary']['target_displacement_mm'] == 10.0


@pytest.mark.asyncio
async def test_convergence_requires_three_full_target_resolutions(tmp_path):
    io = Boundaries(['prepare_mesh', 'convergence', 'convergence', 'solve_mesh',
                     'convergence', 'solve_mesh', 'conclude'],
                    results=[solved(scale=1), solved(scale=1.01), solved(scale=1.015)])
    result = await io.run(evidence(tmp_path))
    assert result['summary']['convergence']['status'] == 'converged'
    assert [a['mesh_size_mm'] for a in result['attempts']] == [2.0, 1.5, 1.0]
    assert len({p['specimen_id'] for n, p in io.calls if n == 'cae.prepare_static_analysis'}) == 3


@pytest.mark.asyncio
async def test_partial_run_cannot_be_counted_as_converged(tmp_path):
    io = Boundaries(['prepare_mesh', 'convergence', 'convergence', 'solve_mesh',
                     'convergence', 'solve_mesh', 'conclude'],
                    results=[solved(), solved(), solved(5, ok=False)])
    result = await io.run(evidence(tmp_path))
    assert result['summary']['convergence']['status'] == 'insufficient_evidence'


@pytest.mark.asyncio
async def test_input_change_is_detected_after_llm_before_native_call(tmp_path):
    data = evidence(tmp_path)
    io = Boundaries(['prepare_mesh'])
    async def tamper(phase, info, options):
        from pathlib import Path
        Path(data['payload']['stl_path']).write_bytes(b'changed')
        return {'option_id': 'prepare_mesh', 'tool': options['prepare_mesh']}
    result = await study()(data, tamper, io.call, io.events.append)
    assert result['status'] == 'failed'
    assert result['summary']['failure_code'] == 'FEM_INPUT_HASH_MISMATCH'
    assert not io.calls


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh'])
    async def cancel(name, payload):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await study()(evidence(tmp_path), io.choose, cancel, io.events.append)


@pytest.mark.asyncio
async def test_declared_contact_alignment_is_deterministic_not_fit_optimized(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    data = evidence(tmp_path, observation=[[0, 7], [2, 7], [3, 17], [8, 67], [13, 117]],
                    coordinate_convention={'name': 'contact_threshold',
                                           'relative_force_threshold': .01,
                                           'absolute_force_threshold_N': 2})
    result = await io.run(data)
    coordinates = result['summary']['coordinate_convention']
    assert coordinates['displacement_offset_mm'] == 3.0
    assert coordinates['force_offset_N'] == 7.0
    assert result['attempts'][0]['comparison']['peak_error_pct'] == pytest.approx(-100/11)
    assert data['observation'][0] == [0, 7]


@pytest.mark.asyncio
@pytest.mark.parametrize('minimum,p5,fraction,can_solve', [
    (.05, .2, .01, True), (-.01, .2, .01, False),
    (.01, .05, .01, False), (.01, .2, .4, False),
    (float('nan'), .2, .01, False),
])
async def test_native_jacobian_statistics_gate_solver(tmp_path, minimum, p5, fraction, can_solve):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'], qualities=[{
        'validity': {'status': 'valid', 'element_count': 10, 'node_count': 20},
        'quality': {'metric': 'minimum_corner_scaled_jacobian', 'minimum': minimum,
                    'percentile_5': p5, 'below_threshold_fraction': fraction}}])
    result = await io.run(evidence(tmp_path))
    assert bool(result['attempts'][0]['curve']) is can_solve


@pytest.mark.asyncio
async def test_poor_mesh_remeshes_before_any_solve_and_requests_convergence(tmp_path):
    io = Boundaries(['prepare_mesh', 'remesh', 'solve_mesh', 'conclude'],
                    qualities=[{'validity': 'valid', 'quality': 'poor'},
                               {'validity': 'valid', 'quality': 'good'}])
    result = await io.run(evidence(tmp_path))
    assert [name for name, _ in io.calls] == ['cae.prepare_static_analysis',
                                            'cae.prepare_static_analysis', 'cae.run_static_analysis']
    assert result['attempts'][0]['solver_status'] == 'not_run'
    assert result['summary']['convergence']['status'] == 'insufficient_evidence'
    assert io.decisions[2][1]['convergence_required'] is True


@pytest.mark.asyncio
async def test_single_increment_partial_history_is_not_discarded(tmp_path):
    partial = solved(1, ok=False)
    partial['reaction_force_displacement_curve'] = [{'displacement_mm': 1.0, 'force_N': 10.0}]
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'], results=[partial])
    result = await io.run(evidence(tmp_path))
    assert result['attempts'][0]['curve'] == [{'displacement_mm': 1.0, 'force_N': 10.0}]
    assert result['attempts'][0]['comparison']['rmse_N'] is None
    assert result['status'] == 'partial'


@pytest.mark.asyncio
async def test_solver_exception_preserves_preparation_evidence(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh'])
    async def fail(name, params):
        if name == 'cae.run_static_analysis':
            raise RuntimeError('solver boundary unavailable')
        return await io.call(name, params)
    result = await study()(evidence(tmp_path), io.choose, fail, io.events.append)
    assert result['status'] == 'failed'
    assert result['attempts'][0]['mesh_quality']['validity'] == 'valid'
    assert result['summary']['failure_code'] == 'FEM_TOOL_ERROR'
    assert io.events[-1]['status'] == 'failed'


@pytest.mark.asyncio
async def test_finite_job_bound_cannot_be_extended_by_llm(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'convergence'])
    result = await io.run(evidence(tmp_path, policy={'max_fem_jobs': 1}))
    assert len(io.calls) == 2
    assert result['summary']['solve_count'] == 1
    assert 'convergence' not in io.decisions[-1][2]


@pytest.mark.asyncio
async def test_same_geometry_in_distinct_jobs_has_distinct_output_identity(tmp_path):
    first = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    second = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    await first.run(evidence(tmp_path))
    await second.run(evidence(tmp_path, job_id='job-two'))
    assert first.calls[0][1]['specimen_id'] != second.calls[0][1]['specimen_id']


@pytest.mark.asyncio
async def test_declared_solver_target_is_not_replaced_by_short_observation(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    result = await io.run(evidence(tmp_path, observation=[[0, 0], [2, 20]]))
    assert result['summary']['target_displacement_mm'] == 10.0
    assert result['attempts'][0]['comparison']['end_mm'] == 2.0
    assert io.calls[-1][1]['loading']['target_strain'] == .5


@pytest.mark.asyncio
async def test_convergence_scales_surface_resolution_without_changing_shape_controls(tmp_path):
    data = evidence(tmp_path)
    data['payload']['surface_remesh'] = {'method': 'isotropic', 'edge_length_mm': .6,
                                        'iterations': 8, 'max_surface_distance_mm': .05}
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'convergence', 'solve_mesh', 'conclude'])
    await io.run(data)
    requests = [p for name, p in io.calls if name == 'cae.prepare_static_analysis']
    assert requests[0]['surface_remesh']['edge_length_mm'] == .6
    assert requests[1]['surface_remesh']['edge_length_mm'] == pytest.approx(.45)
    assert requests[1]['surface_remesh']['max_surface_distance_mm'] == .05
    assert data['payload']['surface_remesh']['edge_length_mm'] == .6


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', [None, {}, {'option_id': {'arbitrary': 'command'}},
                                  {'option_id': 'prepare_mesh', 'tool': 'hardware.move'}])
async def test_malformed_or_unregistered_decision_holds_without_execution(tmp_path, choice):
    io = Boundaries([])
    async def malformed(*args):
        return choice
    result = await study()(evidence(tmp_path), malformed, io.call, io.events.append)
    assert result['status'] == 'held'
    assert not io.calls


@pytest.mark.asyncio
async def test_hash_is_checked_again_between_prepare_and_solve(tmp_path):
    from pathlib import Path
    data = evidence(tmp_path)
    io = Boundaries(['prepare_mesh', 'solve_mesh'])
    async def mutate_after_prepare(phase, info, options):
        if phase == 'fem_mesh_assessment':
            Path(data['payload']['stl_path']).write_bytes(b'changed after prepare')
        return await io.choose(phase, info, options)
    result = await study()(data, mutate_after_prepare, io.call, io.events.append)
    assert result['status'] == 'failed'
    assert len(io.calls) == 1


@pytest.mark.asyncio
async def test_native_cancelled_receipt_retains_partial_history_without_more_llm_calls(tmp_path):
    partial = solved(5, ok=False)
    partial['solve'] = {'status': 'cancelled'}
    io = Boundaries(['prepare_mesh', 'solve_mesh'], results=[partial])
    result = await io.run(evidence(tmp_path))
    assert result['status'] == 'cancelled'
    assert result['attempts'][0]['curve'][-1]['displacement_mm'] == 5
    assert len(io.decisions) == 2


@pytest.mark.asyncio
async def test_solver_plot_paths_are_offered_as_images_for_result_assessment(tmp_path):
    output = solved()
    output['artifacts']['contour_png_path'] = '/saved/contour.png'
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'], results=[output])
    await io.run(evidence(tmp_path))
    assert '/saved/contour.png' in io.decisions[-1][1]['image_paths']


@pytest.mark.asyncio
async def test_nonfinite_native_quality_evidence_can_be_persisted_as_json(tmp_path):
    import json
    io = Boundaries(['prepare_mesh', 'hold'], qualities=[{
        'validity': {'status': 'valid'},
        'quality': {'minimum': float('nan'), 'percentile_5': .2, 'below_threshold_fraction': 0}}])
    result = await io.run(evidence(tmp_path))
    json.dumps(result, allow_nan=False)
    json.dumps(io.events, allow_nan=False)
    assert result['attempts'][0]['mesh_quality']['quality']['minimum'] is None


@pytest.mark.asyncio
async def test_failed_solver_without_history_reports_failed_not_held(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'],
                    results=[{'ok': False, 'status': 'failed', 'failure_code': 'NO_DAT'}])
    result = await io.run(evidence(tmp_path))
    assert result['status'] == 'failed'
    assert result['attempts'][0]['failure_code'] == 'NO_DAT'


@pytest.mark.asyncio
async def test_prepared_receipt_with_changed_target_cannot_be_solved(tmp_path):
    io = Boundaries(['prepare_mesh', 'solve_mesh'])
    async def mismatched(name, params):
        prepared = await io.call(name, params)
        prepared['prepared_input']['target_displacement_mm'] = 5
        return prepared
    result = await study()(evidence(tmp_path), io.choose, mismatched, io.events.append)
    assert len(io.calls) == 1
    assert result['attempts'][0]['quality_gate'] == 'prepared_target_mismatch'


@pytest.mark.asyncio
async def test_contact_alignment_uses_full_curve_not_clipped_observation(tmp_path):
    raw = [[0, 7], [2, 7], [3, 17], [8, 67], [13, 117]]
    data = evidence(tmp_path, observation=raw[:-1] + [[10, 87]],
                    experiment_curve=[{'displacement_mm': x, 'force_N': y} for x, y in raw],
                    coordinate_convention={'name': 'contact_threshold'})
    original = deepcopy(data)
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    result = await io.run(data)
    assert result['attempts'][0]['comparison']['end_mm'] == 10.0
    assert result['experiment_curve'] == [{'displacement_mm': 0.0, 'force_N': 10.0},
                                          {'displacement_mm': 5.0, 'force_N': 60.0},
                                          {'displacement_mm': 10.0, 'force_N': 110.0}]
    assert result['coordinate_convention']['displacement_offset_mm'] == 3
    assert result['convergence']['status'] == 'not_assessed'
    assert data == original
    assert io.events[-1]['experiment_curve'] == result['experiment_curve']


@pytest.mark.asyncio
@pytest.mark.parametrize('initial_quality', ['good', 'poor'])
async def test_virtual_first_option_policy_can_reach_a_valid_solve(tmp_path, initial_quality):
    io = Boundaries([], qualities=[{'validity': 'valid', 'quality': initial_quality},
                                   {'validity': 'valid', 'quality': 'good'}])
    async def first_option(phase, info, options):
        selected = next(iter(options))
        return {'option_id': selected, 'tool': options[selected], 'source': 'virtual'}
    result = await study()(evidence(tmp_path), first_option, io.call, io.events.append)
    assert result['status'] == 'completed'
    assert result['attempts'][-1]['endpoint_reached'] is True
    assert len(result['attempts']) == (1 if initial_quality == 'good' else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize('native_status', ['complete', 'completed'])
async def test_successful_native_statuses_normalize_to_store_terminal_status(tmp_path, native_status):
    native = solved()
    native['status'] = native_status
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'], results=[native])
    result = await io.run(evidence(tmp_path))
    assert result['status'] == 'completed'
    assert result['attempts'][0]['solver_status'] == 'complete'
    assert result['attempts'][0]['endpoint_reached'] is True
