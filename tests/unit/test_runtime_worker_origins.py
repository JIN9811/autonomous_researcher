"""Real fresh children, with probes confined to disposable copied sources."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from utils.runtime_paths import load_paths


STORES = dict(run_root="runs", memory_root="memory", artifact_root="artifacts",
              output_root="outputs", source_inbox_root="inbox", user_file_root="files", log_root="logs")


def bound_layout(root):
    runtime = root / "runtime"
    config = runtime / "configs/repository_layout.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(dict(schema="atr.path_layout.v1", repository_root="../..",
        runtime_root="..", system_root="../../system", workspace_root="../../workspace", defaults=STORES)))
    binding = root / "selected.json"
    binding.write_text(json.dumps({"schema": "atr.path_bindings.v1",
                                  "stores": {key: "private/" + value for key, value in STORES.items()}}))
    return load_paths(config, bindings_file=binding), config, binding


PROBE = '''
import json, os, sys
from pathlib import Path
def capture(kind):
    from utils.runtime_paths import current_paths
    from dataclasses import asdict
    root = Path(__file__).parent
    prefixes = {p.name for p in root.iterdir() if p.is_dir() and (p / '__init__.py').exists()}
    origins = {n: str(Path(m.__file__).resolve()) for n, m in tuple(sys.modules.items())
               if (n == '__main__' or n.split('.')[0] in prefixes) and getattr(m, '__file__', None)}
    Path(root.parent / (kind + '.json')).write_text(json.dumps({
        'cwd': str(Path.cwd()), 'origins': origins, 'env': dict(os.environ),
        'sys_path': sys.path, 'executable': sys.executable,
        'finders': [str(type(f)) for f in sys.meta_path],
        'binding': {k: str(v) for k, v in asdict(current_paths()).items()}}))
'''

DRIVER = '''
import hashlib, json, os, sys, threading, time
from pathlib import Path
from urllib.request import urlopen
from utils.runtime_paths import current_paths
from utils.compute_pool import ComputePool, ComputeError
from utils.monitor_process import MonitorProcess
paths = current_paths()
pool = ComputePool(1, paths=paths)
try:
    payload = {'run_id': 'origin', 'specimen_id': 'probe', 'geometry_type': 'gyroid',
               'specimen_size_mm': [10, 10, 10], 'wall_thickness_mm': 1.2,
               'cell_size_mm': 5., 'tpms_resolution': 32}
    result = pool.submit('geometry.generate', payload)[0].result(40)
    artifact = Path(result['stl_path'])
    assert artifact.is_relative_to(paths.run_root)
    cancelled = threading.Event(); cancelled.set()
    try:
        pool.submit('geometry.quality', {}, cancellation=cancelled)[0].result(10)
    except ComputeError:
        pass
    else:
        raise AssertionError('cancelled job applied')
    # A long-lived child retains its startup binding if metadata changes later.
    binding_file = Path(os.environ['ATR_PATH_BINDINGS'])
    original_binding = binding_file.read_text()
    edited_binding = json.loads(original_binding)
    edited_binding['stores']['run_root'] = 'later-unselected-store'
    binding_file.write_text(json.dumps(edited_binding))
    try:
        quality = pool.submit('geometry.quality', {'stl_path': str(artifact)})[0].result(20)
    finally:
        binding_file.write_text(original_binding)
    summary = {'stl_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
               'quality': quality, 'completed': pool.status()['completed'], 'failed': pool.status()['failed']}
finally:
    pool.close()
command = [sys.executable, '-u', '-c', "import sys,time\\nfor i in range(200):\\n sys.stdout.buffer.write(b'\\\\xff\\\\xd8fake\\\\xff\\\\xd9'); sys.stdout.flush(); time.sleep(.02)"]
worker = MonitorProcess('video', {'command': command, 'timeout': 2}, paths=paths)
try:
    binding_file.write_text(json.dumps(edited_binding))
    try:
        worker.control({'operation': 'printer', 'config': {'command': command, 'timeout': 2}})
    finally:
        binding_file.write_text(original_binding)
    for attempt in range(50):
        try:
            with urlopen(worker.url('frame.jpg'), timeout=2) as response:
                assert response.read() == b'\\xff\\xd8fake\\xff\\xd9'
            break
        except ConnectionError:
            time.sleep(.02)
    else:
        raise AssertionError('synthetic monitor frame unavailable')
finally:
    worker.close()
print(json.dumps(summary))
'''


def test_fresh_worker_origins_and_results_from_outer_and_runtime(tmp_path):
    source = Path(__file__).resolve().parents[2]
    runtime = tmp_path / "copied/runtime"
    runtime.mkdir(parents=True)
    for package in source.iterdir():
        if package.is_dir() and (package / "__init__.py").is_file():
            shutil.copytree(package, runtime / package.name, ignore=shutil.ignore_patterns("__pycache__"))
    paths, config, binding = bound_layout(runtime.parent)
    (runtime / "_origin_probe.py").write_text(PROBE)
    (runtime / "origin_driver.py").write_text(DRIVER)
    # Observe real module state after job/app imports; no production probe API.
    compute = runtime / "utils/compute_worker.py"
    compute.write_text(compute.read_text().replace("response = {'ok': True, 'result': result}",
        "from _origin_probe import capture; capture('compute')\n            response = {'ok': True, 'result': result}"))
    monitor = runtime / "utils/monitor_worker.py"
    monitor.write_text(monitor.read_text().replace("listener = socket.socket()",
        "from device_bridges.printer_fleet.monitoring import _video_diagnostic\n"
        "    _video_diagnostic('fixture', 'synthetic diagnostic')\n"
        "    from _origin_probe import capture; capture('monitor')\n    listener = socket.socket()"))
    monitor.write_text(monitor.read_text().replace('reply = app.state.video_control(payload["monitor_control"])',
        'reply = app.state.video_control(payload["monitor_control"])\n'
        '                        from _origin_probe import capture; capture("monitor")'))
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'ATR_LAYOUT_CONFIG', 'ATR_PATH_BINDINGS'}}
    env.update(ATR_LAYOUT_CONFIG=str(config), ATR_PATH_BINDINGS=str(binding),
               UNRELATED_SECRET="must-not-leak", WINDOWS_PYAUTOGUI_RECORDING_DIR="/private-original")
    def source_bytes():
        return {str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in runtime.rglob('*') if p.is_file()}
    unchanged_source = source_bytes()
    summaries = []
    for cwd in (runtime.parent, runtime):
        result = subprocess.run([sys.executable, str(runtime / "origin_driver.py")], cwd=cwd,
                                env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        summaries.append(json.loads(result.stdout.splitlines()[-1]))
        for kind in ("compute", "monitor"):
            observed = json.loads((runtime.parent / f"{kind}.json").read_text())
            assert observed['cwd'] == str(runtime)
            assert observed['origins'] and all(Path(p).is_relative_to(runtime) for p in observed['origins'].values())
            assert not {'PYTHONPATH', 'UNRELATED_SECRET', 'WINDOWS_PYAUTOGUI_RECORDING_DIR'} & observed['env'].keys()
            assert observed['env']['ATR_LAYOUT_CONFIG'] == str(config)
            assert observed['env']['ATR_PATH_BINDINGS'] == str(binding)
            assert observed['binding']['run_root'] == str(paths.run_root)
            assert observed['binding']['memory_root'] == str(paths.memory_root)
            assert observed['executable'].startswith('/deps/bin/')
            assert all('/home/jin' not in p and not p.startswith(str(source)) for p in observed['sys_path'])
            assert not any('editable' in finder.lower() for finder in observed['finders'])
            assert '/tmp/home/.local' not in ':'.join(observed['sys_path'])
    # Artifact bytes and bounded result/cancellation behavior do not depend on launch CWD.
    assert summaries[0] == summaries[1]
    assert summaries[0]['completed'] == 2 and summaries[0]['failed'] == 1
    assert not (runtime / 'runs').exists()
    assert not (runtime / 'device_bridges/runs').exists()
    assert (paths.run_root / 'monitoring/printer_video.log').is_file()
    assert source_bytes() == unchanged_source


@pytest.mark.parametrize('worker_kind', ['compute', 'monitor'])
@pytest.mark.parametrize('failure', ['missing', 'malformed', 'contradictory'])
def test_worker_metadata_fails_before_launch(tmp_path, monkeypatch, worker_kind, failure):
    from utils.compute_pool import ComputePool
    from utils.monitor_process import MonitorProcess
    paths, config, binding = bound_layout(tmp_path)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(config))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(binding))
    if failure == 'missing':
        config.unlink()
    elif failure == 'malformed':
        config.write_text('{malformed')
    else:
        paths = replace(paths, memory_root=tmp_path / 'different')
    def forbidden(*args, **kwargs):
        pytest.fail('Popen reached before metadata validation')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with pytest.raises(ValueError, match='metadata.*ATR_LAYOUT_CONFIG'):
        ComputePool(1, paths=paths) if worker_kind == 'compute' else MonitorProcess('video', {}, paths=paths)


def test_monitor_cache_identity_includes_binding(tmp_path, monkeypatch):
    from utils import monitor_process as mp
    # Real factory decisions; only the external process lifetime is replaced.
    made = []
    class Worker:
        def __init__(self, kind, config, *, paths):
            self.paths, self.config = paths, config
            self.process = type('Process', (), {'poll': lambda self: None})()
            self.closed = False
            made.append(self)
        def close(self): self.closed = True
        def control(self, value): pass
    monkeypatch.setattr(mp, 'MonitorProcess', Worker)
    monkeypatch.setattr(mp, '_workers', {})
    first, _, _ = bound_layout(tmp_path / 'first')
    second = replace(first, memory_root=tmp_path / 'second-memory')
    one = mp.monitor_process('video', {}, paths=first)
    assert mp.monitor_process('video', {}, paths=first) is one
    two = mp.monitor_process('video', {}, paths=second)
    assert two is not one and one.closed
    assert mp.existing_monitor_process('video', paths=first) is None
    assert mp.existing_monitor_process('video', paths=second) is two


def test_canonical_worker_metadata_and_binding_are_fixed_at_construction(tmp_path, monkeypatch):
    from utils.compute_pool import ComputePool
    paths, config, _ = bound_layout(tmp_path)
    paths = load_paths(config)
    monkeypatch.delenv('ATR_LAYOUT_CONFIG', raising=False)
    monkeypatch.delenv('ATR_PATH_BINDINGS', raising=False)
    pool = ComputePool(1, paths=paths)
    try:
        monkeypatch.chdir(tmp_path.parent)
        monkeypatch.setenv('ATR_LAYOUT_CONFIG', '/later/unrelated.json')
        assert pool.paths is paths
        assert pool.workers[0].paths is paths
        assert pool.workers[0].metadata == {'ATR_LAYOUT_CONFIG': str(config)}
        class LaunchObserved(Exception): pass
        observed = []
        def launch(argv, **options):
            observed.append((argv, options))
            raise LaunchObserved()
        monkeypatch.setattr(subprocess, 'Popen', launch)
        with pytest.raises(LaunchObserved):
            pool.submit('geometry.quality', {})[0].result(5)
        assert observed[0][1]['cwd'] == paths.runtime_root
        assert observed[0][1]['env']['ATR_LAYOUT_CONFIG'] == str(config)
    finally:
        pool.close()


def test_worker_artifact_defaults_use_run_binding_and_explicit_outputs_stay_explicit(tmp_path, monkeypatch):
    from utils import runtime_paths
    from mcp_tools.mock_tools import _generate_geometry_stl
    paths, _, _ = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', paths)
    monkeypatch.chdir(paths.runtime_root)
    payload = {'run_id': 'direct', 'specimen_id': 'one', 'geometry_type': 'gyroid',
               'specimen_size_mm': [10, 10, 10], 'wall_thickness_mm': 1.2,
               'cell_size_mm': 5., 'tpms_resolution': 32}
    result = _generate_geometry_stl(payload)
    assert Path(result['stl_path']) == paths.run_root / 'direct/specimens/one/specimen.stl'
    explicit = _generate_geometry_stl({**payload, 'output_dir': 'explicit-output'})
    assert Path(explicit['stl_path']) == Path('explicit-output/specimen.stl')
    assert not (paths.runtime_root / 'runs').exists()


def test_handoff_default_and_explicit_geometry_path(tmp_path, monkeypatch):
    from utils import runtime_paths
    from mcp_tools.mock_tools import _create_specimen_handoff
    paths, _, _ = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', paths)
    monkeypatch.chdir(paths.runtime_root)
    handoff = _create_specimen_handoff({'run_id': 'direct', 'specimen_id': 'one'})
    assert Path(handoff['handoff_package_path']) == paths.run_root / 'direct/specimens/one/handoff_package.json'
    handoff = _create_specimen_handoff({'geometry_result': {'stl_path': 'explicit-output/specimen.stl'}})
    assert Path(handoff['handoff_package_path']) == Path('explicit-output/handoff_package.json')
    assert not (paths.runtime_root / 'runs').exists()


@pytest.mark.parametrize('explicit', [False, True])
def test_video_diagnostic_default_uses_bound_run_store(tmp_path, monkeypatch, explicit):
    import logging
    from utils import runtime_paths
    from device_bridges.printer_fleet.monitoring import _video_diagnostic
    paths, _, _ = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', paths)
    monkeypatch.chdir(paths.runtime_root)
    logger = logging.getLogger('atr.printer_video')
    monkeypatch.setattr(logger, 'handlers', [])
    if explicit:
        monkeypatch.setenv('ATR_VIDEO_LOG_PATH', 'operator.log')
        target = paths.runtime_root / 'operator.log'
    else:
        monkeypatch.delenv('ATR_VIDEO_LOG_PATH', raising=False)
        target = paths.run_root / 'monitoring/printer_video.log'
    try:
        _video_diagnostic('fixture', 'http://user:password@fixture.invalid/path')
        text = target.read_text()
        assert 'fixture [source redacted]' in text and 'password' not in text
    finally:
        for handler in logger.handlers:
            handler.close()
