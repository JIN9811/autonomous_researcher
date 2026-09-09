"""The validation CLI can be inspected safely without backend or FEM execution."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


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
