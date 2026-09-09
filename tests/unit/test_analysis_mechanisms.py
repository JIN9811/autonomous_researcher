"""Mechanism evidence must constrain calibration, not be inferred from curve fit."""
from copy import deepcopy
import hashlib

import pytest

from tests.unit.test_analysis_calibration import evidence, SolverFixture


def assessment(data, attempts=None, convergence=None):
    from agents.analysis_mechanisms import assess_mechanisms
    return assess_mechanisms(data, attempts or [], convergence or {'status': 'not_assessed'})


def supported_evidence(data, tmp_path):
    source = tmp_path / 'material-coupon-evidence.json'
    source.write_text('{"scope":"software fixture, not a material measurement"}')
    data['input_hashes'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    data['policy']['mechanism_evidence'] = {
        'material_basis': {'kind': 'printed_material_coupon', 'refs': [str(source)],
                           'acquisition_ids': ['coupon-independent'], 'same_print_process': True,
                           'post_yield_softening_observed': True},
        'deformation_comparison': {'status': 'consistent', 'refs': [str(source)]},
    }
    return data


def test_force_drop_does_not_establish_material_softening(tmp_path):
    data = evidence(tmp_path)
    data['policy'].pop('mechanism_evidence')
    data['observation'] = [[0, 0], [1, 10], [10, 5]]
    report = assessment(data)
    assert report['calibration_admissible'] is False
    assert report['material_mechanism'] == 'unidentified'
    assert 'material_characterization' in report['required_evidence']
    assert report['baseline_action'] == 'preserve'


def test_supported_coupon_and_deformation_allow_research_not_promotion(tmp_path):
    data = supported_evidence(evidence(tmp_path), tmp_path)
    report = assessment(data)
    assert report['calibration_admissible'] is True
    assert report['material_promotable'] is False
    assert report['softening_regularization'] == 'not_implemented'
    assert 'mesh_sensitivity' in report['required_evidence']


@pytest.mark.parametrize('mutation', ['target_acquisition', 'missing_ref', 'geometry_only_ref', 'deformation_mismatch', 'process_mismatch'])
def test_insufficient_or_confounded_provenance_cannot_authorize_material_fit(tmp_path, mutation):
    data = supported_evidence(evidence(tmp_path), tmp_path)
    basis = data['policy']['mechanism_evidence']['material_basis']
    if mutation == 'target_acquisition':
        basis['acquisition_ids'] = data['acquisition_ids']
    elif mutation == 'missing_ref':
        basis['refs'] = ['/missing/material.csv']
    elif mutation == 'geometry_only_ref':
        basis['refs'] = [data['payload']['stl_path']]
    elif mutation == 'process_mismatch':
        basis['same_print_process'] = False
    else:
        data['policy']['mechanism_evidence']['deformation_comparison']['status'] = 'mismatch'
    assert assessment(data)['calibration_admissible'] is False


def test_partial_solver_is_numerical_issue_not_material_identification(tmp_path):
    report = assessment(evidence(tmp_path), [{'solver_status': 'partial', 'endpoint_reached': False,
                         'failure_code': 'NONCONVERGENCE', 'comparison': {'work_error_pct': 0}}])
    assert report['numerical_status'] == 'incomplete'
    assert 'solver_diagnostics' in report['required_evidence']
    assert report['capabilities']['explicit_quasistatic'] == 'not_registered_in_this_workflow'
    assert report['capabilities']['self_contact'] == 'not_registered_in_this_workflow'


@pytest.mark.asyncio
async def test_existing_fem_decision_receives_mechanism_report_without_changing_solver(tmp_path):
    from tests.unit.test_analysis_fem import Boundaries, evidence as fem_evidence
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'conclude'])
    data = fem_evidence(tmp_path)
    original = deepcopy(data)
    result = await io.run(data)
    assert result['status'] == 'completed'
    assert io.decisions[-1][1]['mechanism_assessment']['material_mechanism'] == 'unidentified'
    assert result['mechanism_assessment']['baseline_action'] == 'preserve'
    assert data == original
    assert all(p['material'] == data['payload']['material'] for _, p in io.calls)


@pytest.mark.asyncio
async def test_unsubstantiated_softening_cannot_launch_solver_even_if_llm_says_calibrate(tmp_path):
    from agents.analysis_calibration import calibrate
    data = evidence(tmp_path)
    data['policy'].pop('mechanism_evidence', None)
    io = SolverFixture()
    seen = []
    async def choose(phase, info, options):
        seen.append((phase, info, options))
        return {'option_id': 'calibrate', 'tool': 'cae.prepare_static_analysis', 'reason': 'Fit the peak.'}
    result = await calibrate(data, choose, io.call, lambda event: None)
    assert result['status'] == 'held'
    assert not io.calls
    assert 'calibrate' not in seen[0][2]
    assert result['summary']['failure_code'] == 'FEM_MECHANISM_EVIDENCE_REQUIRED'


@pytest.mark.asyncio
async def test_llm_can_request_deformation_review_without_actuation(tmp_path):
    from tests.unit.test_analysis_fem import Boundaries, evidence as fem_evidence
    io = Boundaries(['prepare_mesh', 'solve_mesh', 'review_deformation'])
    result = await io.run(fem_evidence(tmp_path))
    assert result['status'] == 'completed'
    assert result['summary']['next_evidence_action'] == 'review_deformation'
    assert len(io.calls) == 2


@pytest.mark.asyncio
async def test_evidence_request_stops_calibration_search_and_export(tmp_path):
    from agents.analysis_calibration import calibrate, freeze_candidate
    data = supported_evidence(evidence(tmp_path), tmp_path)
    io = SolverFixture()
    # Use an actually offered action: a material-supported candidate can still
    # request solver diagnostics when it does not reach its requested endpoint.
    io.partial = True
    async def request_diagnostics(phase, info, options):
        if phase == 'fem_result':
            return {'option_id': 'review_solver_diagnostics', 'reason': 'Partial solve needs numerical diagnosis.'}
        return await io.choose(phase, info, options)
    result = await calibrate(data, request_diagnostics, io.call, lambda event: None)
    assert len(io.calls) == 2
    assert result['status'] == 'held'
    assert result['summary']['next_evidence_action'] == 'review_solver_diagnostics'
    with pytest.raises(ValueError):
        freeze_candidate(result, data)


def test_runtime_singular_acquisition_id_cannot_be_reused_as_coupon(tmp_path):
    data = supported_evidence(evidence(tmp_path), tmp_path)
    data.pop('acquisition_ids')
    data['acquisition_id'] = 'coupon-independent'
    assert assessment(data)['calibration_admissible'] is False


@pytest.mark.asyncio
async def test_partial_candidate_stops_search_even_when_llm_concludes(tmp_path):
    from agents.analysis_calibration import calibrate
    io = SolverFixture(partial=True)
    result = await calibrate(evidence(tmp_path), io.choose, io.call, lambda event: None)
    assert len(io.calls) == 2
    assert result['mechanism_assessment']['numerical_status'] == 'incomplete'
    assert result['mechanism_assessment']['calibration_admissible'] is False
    assert result['summary']['next_evidence_action'] == 'review_solver_diagnostics'


def test_runtime_freezes_declared_mechanism_refs_with_existing_job_inputs(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.analysis_runtime import service_for
    from mcp_tools.tool_registry import ToolRegistry
    from tests.unit.test_analysis_runtime import state
    s = state()
    data = supported_evidence(evidence(tmp_path), tmp_path)
    s.current_experiment_spec['analysis_improvement'] = data['policy']
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    service = service_for(ctx)
    monkeypatch.setattr(service, 'resume', lambda *a, **k: False)
    service.submit(s, {'source': {}, 'specimen_geometry': {'gauge_length_mm': 20}},
                   [{'displacement_mm': 0, 'force_N': 0}, {'displacement_mm': 10, 'force_N': 100}],
                   data['payload'], job_kind='fem')
    stored = service.store(s.run_id).jobs()[0]['evidence']
    ref = stored['policy']['mechanism_evidence']['material_basis']['refs'][0]
    assert ref in stored['input_hashes']
    assert ref != data['policy']['mechanism_evidence']['material_basis']['refs'][0]
    assert 'inputs' in ref


def test_freezer_preserves_sources_and_missing_refs_cannot_pass(tmp_path):
    from agents.analysis_mechanisms import freeze_mechanism_references
    data = supported_evidence(evidence(tmp_path), tmp_path)
    original = deepcopy(data['policy'])
    source = data['policy']['mechanism_evidence']['material_basis']['refs'][0]
    hashes = freeze_mechanism_references(data, tmp_path / 'frozen-inputs')
    assert hashes[source] == data['input_hashes'][source]
    assert original['mechanism_evidence']['material_basis']['refs'] == [source]
    assert assessment(data)['calibration_admissible'] is True
    data['policy']['mechanism_evidence']['material_basis']['refs'] = ['/missing/ref.json']
    freeze_mechanism_references(data, tmp_path / 'frozen-inputs')
    assert assessment(data)['calibration_admissible'] is False


def test_cli_config_transfers_mechanism_evidence_without_mutating_configuration(tmp_path):
    from scripts.validation.run_analysis_fem_cycle import configure_calibration
    data = supported_evidence(evidence(tmp_path), tmp_path)
    config = {**data['policy']['calibration'], 'mechanism_evidence': data['policy']['mechanism_evidence']}
    original = deepcopy(config)
    data['policy'].pop('mechanism_evidence')
    configure_calibration(data, {}, config)
    assert data['policy']['mechanism_evidence'] == original['mechanism_evidence']
    assert assessment(data)['calibration_admissible'] is True
    assert config == original


def test_freezer_cannot_turn_geometry_copy_into_material_evidence(tmp_path):
    from agents.analysis_mechanisms import freeze_mechanism_references
    data = supported_evidence(evidence(tmp_path), tmp_path)
    data['policy']['mechanism_evidence']['material_basis']['refs'] = [data['payload']['stl_path']]
    freeze_mechanism_references(data, tmp_path / 'copied-inputs')
    assert assessment(data)['calibration_admissible'] is False


def test_measurement_copy_with_new_name_is_not_independent_material_data(tmp_path):
    data = supported_evidence(evidence(tmp_path), tmp_path)
    ref = data['policy']['mechanism_evidence']['material_basis']['refs'][0]
    data['raw_sha256'] = data['input_hashes'][ref]
    assert assessment(data)['calibration_admissible'] is False
