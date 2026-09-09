"""The validation CLI can be inspected safely without backend or FEM execution."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/validation/run_analysis_fem_cycle.py'


def load_runner():
    spec = importlib.util.spec_from_file_location('fem_validation_runner', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_help_requires_no_models_or_devices(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--help'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert '--execute' in result.stdout
    assert '--output-dir' in result.stdout
    assert not list(tmp_path.iterdir())


def test_cli_requires_explicit_execute_before_any_work(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--output-dir', str(tmp_path / 'out')],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert '--execute' in result.stderr
    assert not (tmp_path / 'out').exists()


def test_frozen_evidence_preserves_sources_and_declares_reference_profile(tmp_path):
    runner = load_runner()
    stl = tmp_path / 'original.stl'
    stl.write_text('fixture surface')
    csv = tmp_path / 'original.csv'
    csv.write_text('time_s,force_N,displacement_mm\n0,1,0\n1,2,1\n2,4,2\n')
    analysis = tmp_path / 'analysis.json'
    analysis.write_text(json.dumps({'data': {'analysis': {
        'source': {'path': str(csv)}, 'specimen_geometry': {
            'specimen_size_mm': [30, 30, 30], 'gauge_length_mm': 30, 'cross_section_area_mm2': 900}}}}))
    archive = tmp_path / 'request.json'
    archive.write_text(json.dumps({'source_analysis_result': str(analysis), 'request': {
        'stl_path': str(stl), 'specimen_id': 'original', 'specimen_size_mm': [30, 30, 30],
        'material': {'yield_strength_mpa': 999}, 'loading': {'target_strain': .5}}}))
    out = tmp_path / 'isolated'
    out.mkdir()
    evidence, metadata = runner.prepare_evidence(archive, out, max_fem_jobs=1, max_mesh_actions=3)
    assert Path(evidence['payload']['stl_path']).parent == out / 'inputs'
    assert Path(evidence['payload']['stl_path']).read_bytes() == stl.read_bytes()
    assert evidence['payload']['material'] == {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'yield_strength_mpa': 35}
    assert evidence['payload']['computation_limits']['timeout_s'] is None
    assert evidence['payload']['computation_limits']['threads'] == 4
    assert evidence['payload']['computation_limits']['equation_solver_threads'] == 1
    assert evidence['payload']['surface_remesh']['edge_length_mm'] == .6
    assert evidence['payload']['boundary_tolerance_mm'] == .15
    assert evidence['experiment_curve'][-1]['force_N'] == 4
    assert metadata['source_hashes_before'][str(stl)] == runner.sha256(stl)
    assert metadata['source_hashes_before'][str(csv)] == runner.sha256(csv)
    assert stl.read_text() == 'fixture surface'

    sparse_out = tmp_path / 'sparse'
    sparse_out.mkdir()
    sparse, receipt = runner.prepare_evidence(archive, sparse_out, max_fem_jobs=1,
        max_mesh_actions=3, mesh_size_mm=.8, surface_distance_mm=.03)
    assert sparse['payload']['mesh_size_mm'] == .8
    assert sparse['payload']['surface_remesh']['edge_length_mm'] == .8
    assert sparse['payload']['surface_remesh']['max_surface_distance_mm'] == .03
    assert sparse['payload']['loading'] == evidence['payload']['loading']
    assert sparse['payload']['material'] == evidence['payload']['material']
    assert sparse['payload']['boundary_tolerance_mm'] == .15
    assert sparse['experiment_curve'] == evidence['experiment_curve']
    assert receipt['mesh_size_mm'] == .8


def test_native_start_is_announced_once_with_pid_phase_and_utc(tmp_path, capsys):
    runner = load_runner()
    journal = runner.Journal(tmp_path)
    event = {'phase': 'solve', 'pid': 12345, 'status': 'running', 'elapsed_s': 0.1}
    journal.emit(event)
    journal.emit({**event, 'elapsed_s': 0.2})
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    notice = json.loads(lines[0])
    assert notice['kind'] == 'START_NATIVE'
    assert notice['pid'] == 12345
    assert notice['phase'] == 'solve'
    assert notice['at'].endswith('+00:00')
    assert len((tmp_path / 'progress.jsonl').read_text().splitlines()) == 2


def test_material_hypothesis_changes_only_material_and_retains_provenance():
    runner = load_runner()
    evidence = {'payload': {'material': {'yield_strength_mpa': 35},
                           'loading': {'target_strain': .5}, 'stl_path': 'frozen.stl'},
                'policy': {}, 'experiment_curve': [{'displacement_mm': 0, 'force_N': 0}]}
    metadata = {}
    configuration = {'label': 'postyield hypothesis', 'basis': 'explicit numerical sensitivity study',
        'material': {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35,
                     'plastic_curve': [[55, 0], [30, .15], [30, 1]]}}
    runner.configure_material_hypothesis(evidence, metadata, configuration)
    assert evidence['payload']['material']['plastic_curve'] == [[55, 0], [30, .15], [30, 1]]
    assert evidence['payload']['loading'] == {'target_strain': .5}
    assert evidence['payload']['stl_path'] == 'frozen.stl'
    assert evidence['policy'] == {}
    assert metadata['material_promoted'] is False
    assert metadata['independent_validation'] == 'not_performed'
    assert metadata['material_hypothesis']['basis'] == configuration['basis']
    configuration['material']['plastic_curve'][0][0] = 999
    assert evidence['payload']['material']['plastic_curve'][0][0] == 55


@pytest.mark.parametrize('extra', [{'loading': {'target_strain': .1}}, {'stl_path': 'other.stl'}])
def test_material_hypothesis_rejects_nonmaterial_overrides(extra):
    runner = load_runner()
    with pytest.raises(ValueError):
        runner.configure_material_hypothesis({'payload': {}}, {}, {
            'label': 'test', 'basis': 'test', 'material': {'elastic_modulus_mpa': 1800}, **extra})


@pytest.mark.parametrize('material', [
    {'elastic_modulus_mpa': float('nan'), 'poisson_ratio': .35, 'yield_strength_mpa': 35},
    {'elastic_modulus_mpa': 1800, 'poisson_ratio': .5, 'yield_strength_mpa': 35},
    {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'plastic_curve': [[55, .1], [30, .2]]},
    {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'plastic_curve': []},
    {'elastic_modulus_mpa': 1800, 'poisson_ratio': .4999, 'yield_strength_mpa': 35},
    {'elastic_modulus_mpa': 1e-10, 'poisson_ratio': .35, 'yield_strength_mpa': 35},
    {'elastic_modulus_mpa': True, 'poisson_ratio': .35, 'yield_strength_mpa': 35},
])
def test_material_hypothesis_rejects_invalid_laws(material):
    runner = load_runner()
    with pytest.raises(ValueError):
        runner.configure_material_hypothesis({'payload': {}}, {}, {
            'label': 'test', 'basis': 'test', 'material': material})


def test_material_hypothesis_cannot_be_shadowed_by_archive_material_aliases():
    from device_bridges.cae_bridge import CAEBridge, CAEBridgeConfig
    runner = load_runner()
    evidence = {'payload': {'material': {}, 'elastic_modulus_mpa': 999,
                           'poisson_ratio': .2, 'yield_strength_mpa': 35}}
    runner.configure_material_hypothesis(evidence, {}, {'label': 'test', 'basis': 'research',
        'material': {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'yield_strength_mpa': 55}})
    bridge = CAEBridge(CAEBridgeConfig(mode='test'))
    normalized = bridge._normalized_payload(evidence['payload'])
    assert normalized['material']['elastic_modulus_mpa'] == 1800
    assert normalized['material']['poisson_ratio'] == .35
    assert normalized['material']['yield_strength_mpa'] == 55
