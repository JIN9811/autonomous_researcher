"""Native fixtures exercise staged receipts and owned-process controls, not FEM physics."""
import json
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import pytest

from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig
from device_bridges.cae_bridge import CAEBridge, CAEBridgeConfig
from mcp_tools.cae_tools import register_cae_tools
from mcp_tools.tool_registry import ToolRegistry


MESH = '*Node\n1,0,0,0\n2,1,0,0\n3,0,1,0\n4,0,0,1\n*Element,type=C3D4,elset=VOLUME\n1,1,2,3,4\n'


def executable(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(f'#!{sys.executable}\nimport sys\nif "-v" in sys.argv or "--version" in sys.argv: raise SystemExit(0)\n' + body)
    path.chmod(0o755)
    return path


def test_explicit_null_removes_solver_deadline_but_unspecified_keeps_default(tmp_path):
    ccx = executable(tmp_path, 'ccx', 'import time\ntime.sleep(0.25)\nprint("finished")\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), timeout_s=0.08, artifact_dir=tmp_path))
    payload = {'runtime_solver_enabled': True, 'inp_text': '*Heading\nprobe\n'}
    assert bridge.solve(payload)['failure_code'] == 'CALCULIX_TIMEOUT'
    result = bridge.solve({**payload, 'computation_limits': {'timeout_s': None}})
    assert result['ok'] is True
    assert result['computation_limits']['timeout_s'] is None
    assert result['stdout_tail'].strip() == 'finished'


def test_cancellation_stops_owned_process_and_retains_partial_files_and_logs(tmp_path):
    ccx = executable(tmp_path, 'ccx', 'import pathlib, time\npathlib.Path(sys.argv[1]+".dat").write_text("partial data")\nprint("started", flush=True)\ntime.sleep(30)\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), artifact_dir=tmp_path))
    cancel = threading.Event()
    events = []
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        result = bridge.solve({'runtime_solver_enabled': True, '_cancel_event': cancel,
                               '_progress_callback': events.append, 'computation_limits': {'timeout_s': None}})
    finally:
        timer.cancel()
    assert time.monotonic() - started < 3
    assert result['status'] == 'cancelled'
    assert result['failure_code'] == 'CALCULIX_CANCELLED'
    assert Path(result['dat_path']).read_text() == 'partial data'
    assert Path(result['stdout_path']).read_text().strip() == 'started'
    assert events and events[-1]['status'] == 'cancelled'
    assert {'elapsed_s', 'cpu_time_s', 'rss_bytes', 'pid'} <= events[0].keys()
    request = Path(result['request_path']).read_text()
    assert '_cancel_event' not in request and '_progress_callback' not in request


def staged_bridge(tmp_path, mesh=MESH, timeout=0.08):
    stl = tmp_path / 'specimen.stl'
    stl.write_text('fixture STL consumed by fixture mesher')
    gmsh = executable(tmp_path, 'gmsh', 'import pathlib, time\ntime.sleep(0.15)\npathlib.Path(sys.argv[sys.argv.index("-o")+1]).write_text(' + repr(mesh) + ')\n')
    ccx = executable(tmp_path, 'ccx', 'print("solve reused deck")\nraise SystemExit(1)\n')
    native = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), gmsh_path=str(gmsh), timeout_s=timeout, artifact_dir=tmp_path / 'native'))
    bridge = CAEBridge(CAEBridgeConfig(mode='live', artifact_dir=tmp_path / 'cae'), calculix_bridge=native)
    payload = {'runtime_mode': 'live', 'runtime_solver_enabled': True, 'stl_path': str(stl),
               'run_id': 'run', 'loop_key': 'loop', 'job_id': 'job', 'attempt_id': 'attempt',
               'specimen_id': 'specimen', 'specimen_size_mm': [1, 1, 1], 'mesh_size_mm': 0.4,
               'loading': {'target_strain': 0.25}, 'material': {'yield_strength_mpa': 35},
               'computation_limits': {'timeout_s': None}}
    return bridge, payload


def test_prepared_mesh_reused_with_normalized_request_and_no_deadline(tmp_path):
    bridge, payload = staged_bridge(tmp_path)
    prepared = bridge.prepare_static_analysis(payload)
    assert prepared['ok'] is True
    assert prepared['mesh_quality']['validity']['status'] == 'valid'
    assert prepared['mesh_quality']['validity']['element_count'] == 1
    assert 'below_threshold_element_ids' not in prepared['mesh_quality']['quality']
    receipt = prepared['prepared_input']
    assert receipt['target_displacement_mm'] == 0.25
    assert prepared['request']['mesh_size_mm'] == 0.4
    mesh_path = Path(receipt['mesh_inp_path'])
    before = mesh_path.stat().st_mtime_ns
    Path(bridge.calculix_bridge.config.gmsh_path).unlink()
    result = bridge.run_static_analysis({**payload, 'prepared_input': receipt})
    assert result['stdout_tail'].strip() == 'solve reused deck'
    assert mesh_path.stat().st_mtime_ns == before
    assert result['prepared']['inp_path'] == receipt['inp_path']


@pytest.mark.parametrize('mutation', ['mesh', 'deck', 'request', 'source'])
def test_prepared_receipt_rejects_changed_mesh_deck_request_or_source(tmp_path, mutation):
    bridge, payload = staged_bridge(tmp_path)
    prepared = bridge.prepare_static_analysis(payload)
    receipt = prepared['prepared_input']
    if mutation in {'mesh', 'deck', 'source'}:
        path = Path(receipt['mesh_inp_path'] if mutation == 'mesh' else receipt['inp_path'] if mutation == 'deck' else payload['stl_path'])
        path.write_text(path.read_text() + '\nchanged\n')
    else:
        payload['mesh_size_mm'] = 0.2
    result = bridge.run_static_analysis({**payload, 'prepared_input': receipt})
    assert result['ok'] is False
    assert result['failure_code'] == 'CALCULIX_PREPARED_INPUT_MISMATCH'
    assert 'solve' not in result


def test_invalid_mesh_is_reported_before_deck_or_solve(tmp_path):
    bridge, payload = staged_bridge(tmp_path, MESH.replace('1,1,2,3,4', '1,1,3,2,4'))
    result = bridge.prepare_static_analysis(payload)
    assert result['ok'] is False
    assert result['mesh_quality']['validity']['status'] == 'invalid'
    assert result['failure_code'] == 'CALCULIX_FIELD_MESH_INVALID'
    assert not list((tmp_path / 'native').rglob('specimen.inp'))


def test_prepare_tool_is_registered_and_does_not_start_native_in_test_mode(tmp_path):
    registry = ToolRegistry()
    register_cae_tools(registry, {'devices': {'cae': {'mode': 'test', 'artifact_dir': str(tmp_path)}}})
    assert 'cae.prepare_static_analysis' in registry.list_tools()
    result = registry.call('cae.prepare_static_analysis', {})
    assert result['status'] == 'blocked'
    assert result['failure_code'] == 'CAE_NATIVE_PREPARATION_REQUIRES_LIVE_MODE'


def test_explicit_surface_profile_conditions_current_specimen_and_records_geometry_checks(tmp_path):
    trimesh = pytest.importorskip('trimesh')
    pytest.importorskip('pymeshlab')
    pytest.importorskip('pyvista')
    bridge, payload = staged_bridge(tmp_path)
    trimesh.creation.box().export(payload['stl_path'])
    payload['surface_remesh'] = {'method': 'isotropic', 'edge_length_mm': 0.25,
                                 'iterations': 2, 'max_surface_distance_mm': 0.05}
    result = bridge.prepare_static_analysis(payload)
    assert result['ok'] is True
    conditioning = result['surface_remesh']
    assert conditioning['accepted'] is True
    assert conditioning['source'] == payload['stl_path']
    assert conditioning['watertight'] is True
    assert abs(conditioning['volume_error_pct']) < 1
    assert conditioning['bidirectional_vertex_surface_max_mm'] < 0.1
    assert Path(conditioning['surface_path']).is_file()
    assert conditioning['surface_path'] in Path(result['geo_path']).read_text()
    assert result['prepared_input']['surface_remesh'] == conditioning


@pytest.mark.parametrize('profile', [{'method': 'invented'}, {'method': 'isotropic', 'iterations': 10000}, {'method': 'isotropic', 'edge_length_mm': float('nan')}])
def test_invalid_surface_profile_cannot_silently_fall_back_to_raw_surface(tmp_path, profile):
    bridge, payload = staged_bridge(tmp_path)
    result = bridge.prepare_static_analysis({**payload, 'surface_remesh': profile})
    assert result['ok'] is False
    assert result['failure_code'] == 'CAE_SURFACE_REMESH_PROFILE_INVALID'


def test_pre_cancelled_surface_preparation_does_not_start_mesher(tmp_path):
    bridge, payload = staged_bridge(tmp_path)
    cancel = threading.Event()
    cancel.set()
    result = bridge.prepare_static_analysis({**payload, '_cancel_event': cancel,
        'surface_remesh': {'method': 'isotropic', 'edge_length_mm': 0.6}})
    assert result['status'] == 'cancelled'
    assert result['failure_code'] == 'CAE_SURFACE_REMESH_CANCELLED'
    assert not list((tmp_path / 'native').rglob('*.geo'))


def test_prepared_input_cannot_silently_run_equivalent_mode(tmp_path):
    bridge, payload = staged_bridge(tmp_path)
    receipt = bridge.prepare_static_analysis(payload)['prepared_input']
    result = bridge.run_static_analysis({**payload, 'runtime_mode': 'test', 'prepared_input': receipt})
    assert result['status'] == 'blocked'
    assert result['failure_code'] == 'CAE_NATIVE_PREPARATION_REQUIRES_LIVE_MODE'


def test_prepared_input_still_requires_explicit_runtime_solver_gate(tmp_path):
    bridge, payload = staged_bridge(tmp_path)
    receipt = bridge.prepare_static_analysis(payload)['prepared_input']
    result = bridge.run_static_analysis({**payload, 'runtime_solver_enabled': False, 'prepared_input': receipt})
    assert result['status'] == 'blocked'
    assert result['failure_code'] == 'CALCULIX_RUNTIME_SOLVER_DISABLED'


def test_cancellation_kills_descendants_and_preserves_solver_increment(tmp_path):
    child_code = 'import time; time.sleep(30)'
    ccx = executable(tmp_path, 'ccx', 'import subprocess, pathlib, time\n'
        f'child = subprocess.Popen([sys.executable, "-c", {child_code!r}])\n'
        'pathlib.Path("child.pid").write_text(str(child.pid))\n'
        'pathlib.Path(sys.argv[1]+".sta").write_text("STEP INC ATT\\n1 7 1 0.1\\n")\n'
        'time.sleep(30)\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), artifact_dir=tmp_path))
    cancel = threading.Event()
    events = []
    def progress(event):
        events.append(event)
        if event.get('solver_increment') == 7:
            cancel.set()
    result = bridge.solve({'runtime_solver_enabled': True, '_cancel_event': cancel,
                           '_progress_callback': progress, 'computation_limits': {'timeout_s': 2}})
    assert result['status'] == 'cancelled'
    child_pid = int((Path(result['inp_path']).parent / 'child.pid').read_text())
    child_stat = Path(f'/proc/{child_pid}/stat')
    try:
        state = child_stat.read_text().rsplit(')', 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        state = 'gone'
    assert state in {'gone', 'Z', 'X', 'x'}
    assert events[-1]['solver_increment'] == 7


def test_large_native_stdout_is_on_disk_with_bounded_response_tail(tmp_path):
    ccx = executable(tmp_path, 'ccx', 'print("x" * 2000000)\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), artifact_dir=tmp_path))
    result = bridge.solve({'runtime_solver_enabled': True})
    assert result['ok'] is True
    assert len(result['stdout_tail']) == 2000
    assert Path(result['stdout_path']).stat().st_size == 2000001


def test_cancelled_solve_retains_actual_converged_partial_curve(tmp_path):
    bridge, payload = staged_bridge(tmp_path)
    receipt = bridge.prepare_static_analysis(payload)['prepared_input']
    partial = 'total force (fx,fy,fz) for set TOP and time 0.1\n\n0 0 -4\n\ndisplacements (vx,vy,vz) for set TOP and time 0.1\n\n4 0 0 -0.1\n'
    ccx = executable(tmp_path, 'ccx_partial', 'import pathlib, time\n'
        f'pathlib.Path(sys.argv[1]+".dat").write_text({partial!r})\n'
        'pathlib.Path(sys.argv[1]+".sta").write_text("1 1 1 0.1\\n")\ntime.sleep(30)\n')
    bridge.calculix_bridge.config.executable_path = str(ccx)
    cancel = threading.Event()
    def progress(event):
        if event.get('solver_increment') == 1:
            cancel.set()
    result = bridge.run_static_analysis({**payload, 'prepared_input': receipt,
        '_cancel_event': cancel, '_progress_callback': progress, 'computation_limits': {'timeout_s': 2}})
    assert result['status'] == 'partial'
    assert result['solve']['status'] == 'cancelled'
    assert result['reaction_force_displacement_curve'][-1] == {
        'step_time': 0.1, 'displacement_mm': 0.1, 'force_N': 4.0}
    assert result['metrics']['endpoint_reached'] is False
    assert Path(result['artifacts']['curve_json_path']).is_file()


def test_version_probe_also_has_bounded_stdout_memory(tmp_path):
    ccx = executable(tmp_path, 'ccx', 'print("version first line")\nprint("x" * 4000000)\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path))
    tracemalloc.start()
    try:
        version = bridge._version(str(ccx))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert version == 'version first line'
    assert peak < 1000000


@pytest.mark.parametrize('control', [{'_cancel_event': {}}, {'_progress_callback': 'http callback'}])
def test_serialized_native_controls_are_rejected_before_process_start(tmp_path, control):
    marker = tmp_path / 'started'
    ccx = executable(tmp_path, 'ccx', f'import pathlib\npathlib.Path({str(marker)!r}).touch()\n')
    bridge = CalculiXBridge(CalculiXBridgeConfig(executable_path=str(ccx), artifact_dir=tmp_path))
    with pytest.raises(ValueError, match='in-process'):
        bridge.solve({'runtime_solver_enabled': True, **control})
    assert not marker.exists()
