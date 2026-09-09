"""Calibration must improve real predictions, not replay measured forces."""
from copy import deepcopy
import importlib
import importlib.util
import math

import pytest


def module():
    assert importlib.util.find_spec('agents.analysis_calibration'), 'feature-informed calibration is required'
    return importlib.import_module('agents.analysis_calibration')


def test_features_have_hand_checked_units_and_no_fitted_shift():
    # Area = 1 + 1.5 + 1 = 3.5 N mm. Peak occurs at x=1, not endpoint.
    result = module().response_features([[0, 0], [1, 2], [2, 1], [3, 1]], 3)
    assert result['peak_force_N'] == 2
    assert result['peak_displacement_mm'] == 1
    assert result['work_J'] == pytest.approx(.0035)
    assert result['early_secant_N_per_mm'] == pytest.approx(2)
    assert result['late_secant_N_per_mm'] == pytest.approx(0)


@pytest.mark.parametrize('curve', [
    [[0, 0], [2, 2]], [[.1, 0], [3, 3]], [[0, 0], [3, float('nan')]],
    [[0, 0], [0, 1], [3, 2]],
])
def test_partial_or_invalid_predictions_cannot_be_scored(curve):
    with pytest.raises(ValueError):
        module().compare_response([[0, 0], [3, 3]], curve, 3)


def test_equal_energy_does_not_hide_wrong_peak_and_shape():
    result = module().compare_response([[0, 0], [1, 2], [2, 0]],
                                       [[0, 0], [1, 0], [2, 4]], 2)
    assert result['errors']['work_pct'] == pytest.approx(0)
    assert result['errors']['peak_force_pct'] == pytest.approx(100)
    assert result['objective'] > 0
    assert result['errors']['normalized_rmse_pct'] > 0


def test_exact_prediction_scores_zero():
    curve = [[0, 0], [1, 4], [2, 2], [3, 2.5]]
    assert module().compare_response(curve, curve, 3)['objective'] == pytest.approx(0)


def test_interpretable_law_is_not_specimen_engineering_curve():
    base = {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'yield_strength_mpa': 35}
    parameters = {'peak_flow_mpa': 50., 'residual_flow_mpa': 25., 'decay_plastic_strain': .1}
    material = module().material_from_parameters(parameters, base)
    assert material['elastic_modulus_mpa'] == 1800
    assert material['plastic_curve'][0] == [50., 0.]
    stress = next(row[0] for row in material['plastic_curve'] if row[1] == .1)
    assert stress == pytest.approx(25 + 25 / math.e)
    assert material['plastic_curve'][-1][0] >= 25
    assert 'plastic_curve' not in base
    constant = module().material_from_parameters({**parameters, 'residual_flow_mpa': 50}, base)
    assert all(row[0] == 50 for row in constant['plastic_curve'])


@pytest.mark.parametrize('patch', [
    {'residual_flow_mpa': 60}, {'decay_plastic_strain': 0},
    {'peak_flow_mpa': float('inf')}, {'posthoc_force_scale': 1.2},
])
def test_material_law_rejects_invalid_or_unregistered_parameters(patch):
    with pytest.raises(ValueError):
        module().material_from_parameters({'peak_flow_mpa': 50, 'residual_flow_mpa': 25,
                                          'decay_plastic_strain': .1, **patch}, {})


def evidence(tmp_path):
    from tests.unit.test_analysis_fem import evidence as fem_evidence
    data = fem_evidence(tmp_path, source_kind='measured', paired_identity_verified=True,
        policy={'max_fem_jobs': 1, 'max_mesh_actions': 1,
        'mesh_size_factors': [1], 'calibration': {
            'initial': {'peak_flow_mpa': 30., 'residual_flow_mpa': 20., 'decay_plastic_strain': .1},
            'bounds': {'peak_flow_mpa': [20, 60]}, 'max_evaluations': 5, 'step_fraction': .25,
        }})
    # Characterization declarations are explicit software fixtures, not a claim
    # that the retained physical acquisition has independent coupon evidence.
    import hashlib
    source = tmp_path / 'characterization-fixture.json'
    source.write_text('{"scope":"software fixture, no physical material evidence"}')
    data['input_hashes'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    data['policy']['mechanism_evidence'] = {
        'material_basis': {'kind': 'printed_material_coupon', 'refs': [str(source)],
                           'acquisition_ids': ['coupon-fixture'], 'same_print_process': True,
                           'post_yield_softening_observed': True},
        'deformation_comparison': {'status': 'consistent', 'refs': [str(source)]},
    }
    return data


class SolverFixture:
    """Only replace external FEM; response depends on actual requested material."""
    def __init__(self, *, partial=False):
        self.calls = []
        self.partial = partial

    async def choose(self, phase, info, options):
        return {'option_id': next(iter(options)), 'reason': 'Numerical candidate study, not promotion.'}

    async def call(self, name, payload):
        self.calls.append((name, deepcopy(payload)))
        if name == 'cae.prepare_static_analysis':
            return {'ok': True, 'prepared_input': {'inp_path': '/prepared'},
                    'mesh_quality': {'validity': 'valid', 'quality': 'good'}}
        end = 5 if self.partial else 10
        force = payload['material']['plastic_curve'][0][0]
        return {'ok': not self.partial, 'status': 'partial' if self.partial else 'complete',
                'solver_mode': 'calculix_quasistatic',
                'reaction_force_displacement_curve': [
                    {'displacement_mm': 0, 'force_N': 0},
                    {'displacement_mm': end, 'force_N': force * 2.5}]}


@pytest.mark.asyncio
async def test_single_acquisition_can_calibrate_through_existing_fem_without_promotion(tmp_path):
    from agents.analysis_fem import run_fem_study
    data = evidence(tmp_path)
    original = deepcopy(data)
    io = SolverFixture()
    result = await run_fem_study(data, io.choose, io.call, lambda event: None)
    assert result['calibration']['status'] == 'calibrated'
    assert result['calibration']['best_parameters']['peak_flow_mpa'] == pytest.approx(40)
    assert result['calibration']['best_comparison']['objective'] == pytest.approx(0)
    assert result['calibration']['independent_validation'] == 'not_performed'
    assert result['summary']['material_promoted'] is False
    assert data == original
    solves = [p for n, p in io.calls if n == 'cae.run_static_analysis']
    assert len(solves) <= 5
    assert len({p['specimen_id'] for p in solves}) == len(solves)
    assert all(p['computation_limits']['timeout_s'] is None for p in solves)
    assert all(p['loading'] == data['payload']['loading'] for p in solves)
    assert all('reference_calibration' not in p for p in solves)


@pytest.mark.asyncio
@pytest.mark.parametrize('patch', [{'source_kind': 'synthetic'}, {'paired_identity_verified': False}])
async def test_calibration_requires_paired_measured_identity(tmp_path, patch):
    data = {**evidence(tmp_path), **patch}
    io = SolverFixture()
    result = await module().calibrate(data, io.choose, io.call, lambda event: None)
    assert result['status'] == 'failed'
    assert not io.calls


@pytest.mark.asyncio
async def test_proxy_curve_cannot_become_a_fitted_fe_candidate(tmp_path):
    io = SolverFixture()
    async def proxy(name, payload):
        result = await io.call(name, payload)
        if name == 'cae.run_static_analysis':
            result['solver_mode'] = 'deterministic_quasistatic_equivalent'
        return result
    result = await module().calibrate(evidence(tmp_path), io.choose, proxy, lambda event: None)
    assert result['calibration']['best_parameters'] is None


@pytest.mark.asyncio
async def test_candidate_progress_retains_prior_attempts_and_no_early_job_completion(tmp_path):
    io, events = SolverFixture(), []
    result = await module().calibrate(evidence(tmp_path), io.choose, io.call, events.append)
    progress = [event for event in events if event.get('attempts')]
    lengths = [len(event['attempts']) for event in progress]
    assert lengths == sorted(lengths)
    assert not any(event.get('status') == 'completed' for event in events[:-1])
    assert result['calibration']['best_parameters'] is not None


@pytest.mark.asyncio
async def test_frozen_candidate_is_forward_usable_without_measured_curve(tmp_path):
    io = SolverFixture()
    data = evidence(tmp_path)
    result = await module().calibrate(data, io.choose, io.call, lambda event: None)
    frozen = module().freeze_candidate(result, data)
    assert frozen['material']['plastic_curve'][0][0] == pytest.approx(40)
    assert frozen['independent_validation'] == 'not_performed'
    assert frozen['status'] == 'candidate_not_promoted'
    assert 'observation' not in frozen and 'experiment_curve' not in frozen
    assert frozen['source_input_hashes'] == data['input_hashes']
    assert frozen['material'] is not result['calibration']['best_material']
    result['calibration']['retention_status'] = 'held'
    result['status'] = 'held'
    with pytest.raises(ValueError, match='retained'):
        module().freeze_candidate(result, data)


@pytest.mark.asyncio
async def test_partial_candidate_never_becomes_calibrated(tmp_path):
    io = SolverFixture(partial=True)
    result = await module().calibrate(evidence(tmp_path), io.choose, io.call, lambda event: None)
    assert result['calibration']['status'] == 'no_eligible_candidate'
    assert result['calibration']['best_parameters'] is None


@pytest.mark.asyncio
async def test_unbounded_search_or_input_mutation_never_reaches_solver(tmp_path):
    data = evidence(tmp_path)
    data['policy']['calibration']['bounds']['posthoc_force_scale'] = [.1, 2]
    io = SolverFixture()
    result = await module().calibrate(data, io.choose, io.call, lambda event: None)
    assert result['status'] == 'failed'
    assert io.calls == []


@pytest.mark.asyncio
async def test_llm_hold_stops_calibration_without_solver_calls(tmp_path):
    io = SolverFixture()
    async def hold(*args):
        return {'option_id': 'hold', 'reason': 'Evidence insufficient for this hypothesis.'}
    result = await module().calibrate(evidence(tmp_path), hold, io.call, lambda event: None)
    assert result['status'] == 'held'
    assert io.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('phase_to_hold', ['fem_result', 'fem_calibration_review'])
async def test_llm_hold_is_respected_after_successful_native_solve(tmp_path, phase_to_hold):
    io = SolverFixture()
    async def choose(phase, info, options):
        if phase == phase_to_hold:
            return {'option_id': 'hold', 'reason': 'Candidate requires review before more work.'}
        return await io.choose(phase, info, options)
    result = await module().calibrate(evidence(tmp_path), choose, io.call, lambda event: None)
    assert result['status'] == 'held'
    assert result['calibration']['retention_status'] == 'held'
    assert result['attempts'][0]['endpoint_reached'] is True
    if phase_to_hold == 'fem_result':
        assert len([p for n, p in io.calls if n == 'cae.run_static_analysis']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('curve', [[[0, 0], [10, 0]], [[0, -100], [9, -100], [10, 1]]])
async def test_invalid_measured_response_rejected_before_expensive_work(tmp_path, curve):
    io = SolverFixture()
    data = {**evidence(tmp_path), 'observation': curve}
    result = await module().calibrate(data, io.choose, io.call, lambda event: None)
    assert result['status'] == 'failed'
    assert not io.calls


def test_runner_calibration_configuration_is_explicit_and_preserves_inputs(tmp_path):
    from scripts.validation.run_analysis_fem_cycle import configure_calibration
    data = evidence(tmp_path)
    config = deepcopy(data['policy']['calibration'])
    del data['policy']['calibration']
    before = deepcopy(data)
    metadata = {'calibration_applied': False}
    configure_calibration(data, metadata, config)
    assert data['policy']['calibration'] == config
    assert data['payload'] == before['payload']
    assert data['input_hashes'] == before['input_hashes']
    assert metadata['material_promoted'] is False
    assert metadata['independent_validation'] == 'not_performed'
    data['policy']['calibration']['initial']['peak_flow_mpa'] = 999
    assert config['initial']['peak_flow_mpa'] == 30


@pytest.mark.asyncio
async def test_validation_context_resolves_registered_managed_url_without_loading(tmp_path, monkeypatch):
    import utils.config_loader
    monkeypatch.setenv('AUTONOMOUS_BACKEND', 'vllm')
    from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime
    from scripts.validation.run_analysis_fem_cycle import build_context, Journal
    configuration = {'system': {'system': {'inference_backend': 'vllm'}, 'vllm': {
        'base_url': 'http://unused-localhost/v1', 'nemoclaw_k8s': {'enabled': True,
        'node_host': 'registered-node', 'models': {'registered-model': {'deployment': 'existing', 'node_port': 31001}}}}},
        'models': {'backend': {'fallback': 'openai'}}, 'devices': {}}
    monkeypatch.setattr(utils.config_loader, 'load_all_configs', lambda path: configuration)
    async def forbid_load(*args, **kwargs):
        pytest.fail('Validation URL resolution must not change model lifecycle')
    monkeypatch.setattr(NemoClawVLLMRuntime, 'ensure_model', forbid_load)
    ctx, _ = build_context(tmp_path, tmp_path, Journal(tmp_path))
    url = await ctx.primary_backends['vllm']._base_url_for_model('registered-model')
    assert url == 'http://registered-node:31001/v1'


def test_backend_pinning_removes_cross_backend_fallback_without_global_mutation():
    from types import SimpleNamespace
    from agents.base_agent import AgentContext
    from backends.model_router import ModelRouter
    from scripts.validation.run_analysis_fem_cycle import pin_validation_backend
    local = ModelRouter({'models': {'e4b': {'primary': 'small', 'fallback': 'large'}}})
    cloud = ModelRouter({'models': {'e4b': {'primary': 'api-model'}}})
    a, b = object(), object()
    ctx = AgentContext(model_router=local, primary_backend=a, fallback_backend=b,
        tools=SimpleNamespace(), rag=SimpleNamespace(), experiment_db=SimpleNamespace(), failure_memory=SimpleNamespace(),
        model_routers={'vllm': local, 'openai': cloud}, primary_backends={'vllm': a, 'openai': b},
        backend_fallbacks={'vllm': 'openai'}, active_backend='vllm')
    pinned = pin_validation_backend(ctx, 'vllm', model='large')
    assert pinned.primary_backend is a and pinned.fallback_backend is a
    assert pinned.backend_fallbacks == {}
    assert pinned.model_router.select('analysis_reasoning').primary == 'large'
    assert pinned.model_router.select('analysis_reasoning').fallback is None
    assert ctx.backend_fallbacks == {'vllm': 'openai'}
    assert ctx.model_router.select('analysis_reasoning').primary == 'small'
    with pytest.raises(ValueError, match='registered'):
        pin_validation_backend(ctx, 'vllm', model='invented-model')
