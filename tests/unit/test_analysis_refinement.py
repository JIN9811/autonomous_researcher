import pytest
from agents import analysis_refinement as module
from agents.analysis_improvement import ImprovementStore


def test_bounded_material_curve_candidates_reach_existing_solver_parameters():
    base = {'material': {'elastic_modulus_mpa': 1800, 'poisson_ratio': 0.35}, 'mesh_size_mm': 1}
    curve = [[50, 0], [55, 0.1], [65, 0.3]]
    policy = {'candidates': [{'material': {'plastic_curve': curve}}],
              'bounds': {'flow_stress_mpa': [20, 90], 'plastic_strain': [0, 0.5]}}
    result = module._candidates(policy, base)
    assert len(result) == 1
    assert result[0]['material']['plastic_curve'] == [[50, 0], [55, 0.1], [65, 0.3]]
    assert result[0]['material']['elastic_modulus_mpa'] == 1800
    assert 'plastic_curve' not in base['material']
    curve[1][0] = 999
    assert result[0]['material']['plastic_curve'][1][0] == 55


@pytest.mark.parametrize('curve', [
    [[50, 0], [100, 0.1]], [[50, 0], [55, 0.6]], [[50, 0.1]],
    [[50, 0], [55, 0]], [[50, 0], [float('nan'), 0.1]],
])
def test_invalid_or_out_of_bounds_material_curve_candidate_is_not_registered(curve):
    policy = {'candidates': [{'material': {'plastic_curve': curve}}],
              'bounds': {'flow_stress_mpa': [20, 90], 'plastic_strain': [0, 0.5]}}
    assert module._candidates(policy, {'material': {}}) == []


@pytest.mark.asyncio
async def test_missing_independent_evidence_never_calls_solver(tmp_path):
    assert hasattr(module, 'refine'), 'bounded refinement engine required'
    calls = []
    async def choose(*args, **kwargs):
        return {'option_id': 'hold', 'reason': 'No independent experiment.'}
    async def solve(payload):
        calls.append(payload)
        return {}
    result = await module.refine(ImprovementStore(tmp_path), {'scope': 's'}, choose, solve)
    assert result['status'] == 'needs_more_data'
    assert calls == []


@pytest.mark.parametrize('with_curve', [False, True])
@pytest.mark.asyncio
async def test_validated_candidate_uses_train_then_holdout_and_promotes_next_loop(tmp_path, with_curve):
    assert hasattr(module, 'refine'), 'bounded refinement engine required'
    store = ImprovementStore(tmp_path)
    base = store.pin_model('s', 'loop-1', {'material': {'elastic_modulus_mpa': 1.0}, 'mesh_size_mm': 2.0})
    policy = {'candidates': [{'material': {'elastic_modulus_mpa': 2.0}}],
              'bounds': {'elastic_modulus_mpa': [1.0, 3.0]}, 'max_solver_jobs': 20,
              'convergence_relative_tolerance': 0.02, 'max_wall_time_s': 10,
              'solver_identity': 'fixture-calculix-build-1'}
    if with_curve:
        policy['candidates'][0]['material']['plastic_curve'] = [[50, 0], [40, 0.2]]
        policy['bounds'].update({'flow_stress_mpa': [20, 90], 'plastic_strain': [0, 0.5]})
    for index in (1, 2):
        evidence = {'scope': 's', 'experiment_id': f'e{index}', 'model': base,
                    'acquisition_id': f'e{index}', 'raw_sha256': f'raw-{index}',
                    'observation': [[0, 0], [1, 2]], 'source_kind': 'measured',
                    'paired_identity_verified': True, 'input_hashes': {},
                    'payload': {'specimen_id': f'e{index}', 'material': {'elastic_modulus_mpa': 1.0}, 'mesh_size_mm': 2.0},
                    'policy': policy}
        store.submit(evidence)
    calls = []
    async def choose(phase, evidence, options):
        return {'option_id': next(iter(options)), 'reason': 'Evaluate registered candidate.'}
    async def solve(payload):
        calls.append(payload)
        if with_curve:
            # Exercise the real facade and deck builder, not a material echo mock.
            # Only numerical execution is substituted; no device or native solver runs.
            from device_bridges.cae_bridge import CAEBridge, CAEBridgeConfig
            from utils.calculix_quasistatic import build_compression_deck
            from tests.unit.test_calculix_quasistatic import CUBE_MESH
            normalized = CAEBridge(CAEBridgeConfig())._normalized_payload(payload)
            deck, _ = build_compression_deck(
                CUBE_MESH, material=normalized['material'], target_displacement_mm=1,
                increments=normalized['increments'], boundary_tolerance_mm=1e-6,
            )
            if 'plastic_curve' in payload['material']:
                assert normalized['material']['plastic_curve'] == [[50, 0], [40, 0.2]]
                assert '*PLASTIC\n50,0\n40,0.2\n' in deck
        force = payload['material']['elastic_modulus_mpa']
        return {'ok': True, 'solver_mode': 'calculix_quasistatic',
                'reaction_force_displacement_curve': [{'displacement_mm': 0, 'force_N': 0}, {'displacement_mm': 1, 'force_N': force}]}
    result = await module.refine(store, evidence, choose, solve)
    assert result['status'] == 'promoted'
    assert result['validation']['train_ids'] == ['e1']
    assert result['validation']['holdout_ids'] == ['e2']
    assert store.pin_model('s', 'loop-1', {}) == base
    assert store.pin_model('s', 'loop-3', {})['parameters']['material']['elastic_modulus_mpa'] == 2.0
    if with_curve:
        assert store.pin_model('s', 'loop-3', {})['parameters']['material']['plastic_curve'] == [[50, 0], [40, 0.2]]
    # Errors were evaluated at half the base mesh size, so this is the only
    # mesh allowed to be advertised as the independently validated candidate.
    assert store.pin_model('s', 'loop-3', {})['parameters']['mesh_size_mm'] == 1.0
    assert len(calls) <= 20
    call_count = len(calls)
    repeat = await module.refine(ImprovementStore(tmp_path), evidence, choose, solve)
    assert repeat['status'] == 'needs_more_data'
    assert len(calls) == call_count  # No adaptive reuse of e2's holdout outcome.
    fresh = {**evidence, 'experiment_id': 'e3', 'acquisition_id': 'e3', 'raw_sha256': 'raw-3',
             'payload': {**evidence['payload'], 'specimen_id': 'e3'}}
    reopened = ImprovementStore(tmp_path)
    reopened.submit(fresh)
    next_result = await module.refine(reopened, fresh, choose, solve)
    assert next_result['status'] == 'held'
    assert 'superseded' in next_result['detail']  # Old parent cannot overwrite promotion.
    assert len(calls) - call_count == 6  # Training solves survived store reopen.


@pytest.mark.asyncio
async def test_out_of_bounds_candidate_never_runs(tmp_path):
    assert hasattr(module, 'refine'), 'bounded refinement engine required'
    store = ImprovementStore(tmp_path)
    base = store.pin_model('s', 'l', {'material': {'elastic_modulus_mpa': 1}})
    for eid in ('a', 'b'):
        ev = {'scope': 's', 'experiment_id': eid, 'model': base, 'source_kind': 'measured',
              'acquisition_id': eid, 'raw_sha256': f'raw-{eid}',
              'paired_identity_verified': True, 'observation': [[0, 0], [1, 1]],
              'payload': {'material': {'elastic_modulus_mpa': 1}, 'mesh_size_mm': 2},
              'policy': {'candidates': [{'material': {'elastic_modulus_mpa': 999}}], 'bounds': {'elastic_modulus_mpa': [1, 3]}}}
        store.submit(ev)
    async def choose(*args):
        return {'option_id': 'evaluate_0', 'reason': 'test'}
    async def solve(payload):
        pytest.fail('out-of-bounds candidate must be rejected before solver')
    result = await module.refine(store, ev, choose, solve)
    assert result['status'] == 'needs_more_data'
