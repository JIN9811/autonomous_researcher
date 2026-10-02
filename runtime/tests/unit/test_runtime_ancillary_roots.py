"""Ancillary writers and process boundaries preserve independent root authority."""
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys

import pytest

from utils.runtime_paths import RuntimePaths


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


@pytest.mark.asyncio
async def test_actual_analysis_run_writes_only_bound_artifacts_with_same_measurements(paths, monkeypatch):
    from agents.analysis.agent import AnalysisAgent
    from tests.unit.test_analysis_agent import _CtxStub, _state
    monkeypatch.setattr('agents.analysis.agent.resolve_path', lambda value: paths.repository_root / value)
    outputs = []
    for selected in (paths, replace(paths, run_root=paths.run_root.with_name('other-runs'))):
        ctx = _CtxStub(force_real_llm_in_test=True)
        ctx.paths = selected
        result = await AnalysisAgent().run(_state(), ctx)
        assert result.success
        artifacts = result.data['analysis']['analysis_artifacts']
        assert all(Path(path).is_relative_to(selected.run_root / 'run-analysis/analysis/specimen-analysis') for path in artifacts.values())
        outputs.append(Path(artifacts['canonical_curve']).read_bytes())
        assert result.data['metrics']['peak_force_N'] == 520.0
    assert outputs[0] == outputs[1]
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_design_preview_outputs_and_urls_share_binding(paths, monkeypatch):
    from agents.design.agent import DesignAgent
    monkeypatch.setattr('agents.design.agent.resolve_path', lambda value: paths.repository_root / value)
    agent = DesignAgent()
    candidate = {'candidate_id': 'a/b', 'geometry_type': 'gyroid', 'cell_size_mm': 6}
    ctx = SimpleNamespace(paths=paths, tools=SimpleNamespace(call=lambda *args: None))
    steps = agent._candidate_preview_steps(state=SimpleNamespace(run_id='run test'), ctx=ctx,
                                            pool=[candidate], constraints={'material': 'PLA'})
    name, payload = next(steps)
    assert name == 'geometry.generate_metamaterial_stl'
    output = paths.run_root / 'run-test/design_candidates/a-b'
    assert payload['output_dir'] == str(output) and payload['cell_size_mm'] == 6
    output.mkdir(parents=True)
    stl = output / 'sample.stl'
    stl.write_bytes(b'synthetic-stl')
    with pytest.raises(StopIteration):
        steps.send({'ok': True, 'stl_path': str(stl), 'preview_image_path': str(paths.repository_root / 'foreign.png')})
    assert candidate['stl_url'] == '/api/runs/run-test/artifact-file/design_candidates/a-b/sample.stl'
    assert candidate['preview_image_url'] == ''


def test_doctor_separates_git_venv_and_environment_from_runtime_resources(paths, monkeypatch):
    from scripts import doctor
    calls = []
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/usr/bin/git')
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(doctor.subprocess, 'run', run)
    check = doctor.Doctor(paths=paths)
    check.check_secrets_policy()
    assert [cmd[-1] for cmd, _ in calls] == ['.env', 'memory/api_keys.json', 'memory/bambu_connection.json', 'memory/prusa_connection.json']
    assert all(kw['cwd'] == paths.repository_root and kw['check'] is False for _, kw in calls)
    config = paths.runtime_root / 'configs/fixture.yaml'
    config.parent.mkdir(parents=True)
    config.write_text('safe: true\n')
    assert check.load_yaml('configs/fixture.yaml') == {'safe': True}
    interpreter = paths.repository_root / '.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    check.check_python()
    assert any(x['name'] == 'virtualenv' and x['level'] == 'ok' for x in check.results)
    (paths.repository_root / '.env').touch()
    (paths.repository_root / '.env.example').write_text('SAFE=1\n')
    check.check_env()
    assert any(x['name'] == 'environment' and x['level'] == 'ok' for x in check.results)
    assert any(x['name'] == '.env.example' and x['level'] == 'ok' for x in check.results)
    assert check.resolve_repo_path('operator/tool') == paths.repository_root / 'operator/tool'


def test_benchmark_child_has_explicit_runtime_cwd_without_changing_protocol(paths, monkeypatch, tmp_path):
    from scripts import benchmark_compute_workers as benchmark
    class Captured(Exception):
        pass
    calls = []
    def popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise Captured()
    monkeypatch.setattr(benchmark.subprocess, 'Popen', popen)
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace())
    # Only a loopback listener is opened, no child or geometry workload executes.
    with pytest.raises(Captured):
        benchmark.measure(3, tmp_path / 'output', paths=paths)
    cmd, kw = calls[0]
    assert cmd[:6] == [sys.executable, '-m', 'scripts.benchmark_compute_workers', '--serve', '3', '--root']
    assert cmd[6:8] == [str(tmp_path / 'output'), '--fd']
    assert kw['pass_fds'] == [int(cmd[-1])]
    assert kw['cwd'] == paths.runtime_root
    assert 'env' not in kw


@pytest.mark.parametrize('explicit', [False, True])
def test_piper_paths_and_synthesis_argv_preserved_without_audio(paths, tmp_path, monkeypatch, explicit):
    from tools.tts import atr_piper_say as piper
    model = paths.runtime_root / 'models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx'
    config = model.with_suffix('.onnx.json')
    executable = paths.repository_root / '.venv/bin/piper'
    argv = ['piper', 'hello', '--player', 'fixture-player']
    if explicit:
        monkeypatch.chdir(tmp_path)
        model, config, executable = Path('voice.onnx'), Path('voice.json'), Path('piper-bin')
        argv += ['--model', str(model), '--config', str(config), '--piper-bin', str(executable)]
    for path in (model, config, executable):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if '--output-file' in cmd:
            Path(cmd[cmd.index('--output-file') + 1]).write_bytes(b'fake-wave')
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(piper.subprocess, 'run', run)
    monkeypatch.setattr(piper.shutil, 'which', lambda value: value)
    assert piper.main(paths=paths) == 0
    cmd, kw = calls[0]
    wav = cmd[cmd.index('--output-file') + 1]
    assert cmd == [str(executable), '--model', str(model), '--config', str(config), '--output-file', wav,
                   '--length-scale', '1.123', '--sentence-silence', '0.05', '--volume', '1.0']
    assert kw == {'input': 'hello\n', 'text': True, 'capture_output': True, 'check': False}
    assert calls[1] == (['fixture-player', wav], {'check': False})
    assert not Path(wav).exists()
