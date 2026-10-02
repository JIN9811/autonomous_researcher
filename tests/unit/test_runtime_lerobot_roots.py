"""LeRobot source, storage and provenance roots remain separate without hardware."""
from copy import deepcopy
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
import json
import os

import pytest
import yaml

from utils.runtime_paths import RuntimePaths
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
from mcp_tools.lerobot_schemas import IsaacLabSyntheticRequest, LeRobotSessionRequest
from mcp_tools.lerobot_tools import register_lerobot_tools
from mcp_tools.tool_registry import ToolRegistry


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


def select_metadata(paths, monkeypatch):
    source_names = {'repository_root', 'runtime_root', 'system_root', 'workspace_root'}
    layout = {'schema': 'atr.path_layout.v1', **{name: str(getattr(paths, name)) for name in source_names},
              'defaults': {f.name: str(getattr(paths, f.name)) for f in fields(paths) if f.name not in source_names}}
    filename = paths.repository_root.parent / 'layout.json'
    filename.write_text(json.dumps(layout))
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(filename))
    monkeypatch.delenv('ATR_PATH_BINDINGS', raising=False)
    return filename


DEFAULTS = {
    'session_memory_path': ('memory_root', 'lerobot_sessions.json', 'memory/lerobot_sessions.json'),
    'device_memory_path': ('memory_root', 'lerobot_device_ports.json', 'memory/lerobot_device_ports.json'),
    'fake_dataset_root': ('artifact_root', 'lerobot/fake_datasets', 'artifacts/lerobot/fake_datasets'),
    'fake_checkpoint_root': ('artifact_root', 'lerobot/fake_checkpoints', 'artifacts/lerobot/fake_checkpoints'),
    'output_root': ('output_root', 'train', 'outputs/train'),
    'policy_root': ('output_root', 'train', 'outputs/train'),
    'session_log_root': ('run_root', 'lerobot_sessions', 'runs/lerobot_sessions'),
    'artifact_run_root': ('run_root', '.', 'runs'),
    'wandb_local_api_key_path': ('memory_root', 'wandb_local_api_key.json', 'memory/wandb_local_api_key.json'),
    'tts_piper_script': ('runtime_root', 'tools/tts/atr_piper_say.py', 'tools/tts/atr_piper_say.py'),
    'tts_piper_model': ('runtime_root', 'models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx', 'models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx'),
    'tts_piper_config': ('runtime_root', 'models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json', 'models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json'),
}


@pytest.mark.parametrize('value', [None, 'custom/data', '/tmp/external-lerobot'])
def test_lerobot_absent_defaults_and_explicit_bases(paths, value):
    config = LeRobotBridgeConfig.from_config({} if value is None else dict.fromkeys(DEFAULTS, value), paths=paths)
    assert config.repo_root == paths.repository_root
    assert config.paths is paths
    for name, (root, suffix, _) in DEFAULTS.items():
        expected = getattr(paths, root) / suffix if value is None else Path(value) if Path(value).is_absolute() else paths.repository_root / value
        assert getattr(config, name) == expected, name
    assert config.tts_piper_python == paths.repository_root / '.venv/bin/python'
    assert config.tts_piper_bin == paths.repository_root / '.venv/bin/piper'
    assert config.dataset_root == Path.home() / '.cache/huggingface/lerobot'
    assert config.pi05_repo_root == Path.home() / 'lerobot_pi05'
    assert not paths.runtime_root.exists() and not paths.memory_root.exists()


def test_lerobot_legacy_and_contradictions(paths):
    legacy = LeRobotBridgeConfig.from_config({}, repo_root=paths.repository_root)
    for name, (_, _, suffix) in DEFAULTS.items():
        assert getattr(legacy, name) == paths.repository_root / suffix
    with pytest.raises(ValueError, match='repo_root'):
        register_lerobot_tools(ToolRegistry(), {}, repo_root=paths.runtime_root, paths=paths)
    assert not paths.memory_root.exists()


def test_lerobot_shipped_omissions_preserve_flat_config(paths):
    shipped = yaml.safe_load((Path(__file__).resolve().parents[2] / 'configs/lerobot.yaml').read_text())
    omitted = set(DEFAULTS) - {'artifact_run_root', 'wandb_local_api_key_path'}
    assert not omitted.intersection(shipped['lerobot'])
    old = deepcopy(shipped)
    old['lerobot'].update({name: DEFAULTS[name][2] for name in omitted})
    flat = replace(paths, runtime_root=paths.repository_root, memory_root=paths.repository_root / 'memory', artifact_root=paths.repository_root / 'artifacts', output_root=paths.repository_root / 'outputs', run_root=paths.repository_root / 'runs')
    assert LeRobotBridgeConfig.from_config(old, paths=flat) == LeRobotBridgeConfig.from_config(shipped, paths=flat)
    explicit = LeRobotBridgeConfig.from_config(old, paths=paths)
    for name in omitted:
        assert getattr(explicit, name) == paths.repository_root / DEFAULTS[name][2]


def test_lerobot_nested_source_and_direct_store_defaults(paths):
    from utils.isaac_omx_mirror_mapping import default_isaac_omx_mirror_calibration_path
    registry = ToolRegistry()
    bridge = register_lerobot_tools(registry, {}, paths=paths)
    assert registry.resource('lerobot.bridge') is bridge
    request = LeRobotSessionRequest()
    assert bridge._active_robot_cam_capture_pose_path(request) == str(paths.run_root / 'active_robot_cam/latest_follower_capture_pose.json')
    assert bridge._active_robot_cam_home_pose_path(request) == str(paths.run_root / 'active_robot_cam/latest_follower_home_pose.json')
    assert default_isaac_omx_mirror_calibration_path(paths.repository_root, paths=paths) == paths.memory_root / 'isaac_omx_mirror_calibration.json'
    pipeline = bridge._isaac_lab_synthetic_pipeline()
    assert pipeline.repo_root == paths.repository_root
    synthetic = IsaacLabSyntheticRequest(dataset_path=str(paths.artifact_root / 'dataset'))
    command = bridge._isaac_lab_live_e2e_command(synthetic)
    assert command[1] == str(paths.runtime_root / 'scripts/lerobot_isaac_lab_e2e_smoke.py')
    assert command[command.index('--repo-root') + 1] == str(paths.repository_root)
    assert command[command.index('--runtime-root') + 1] == str(paths.runtime_root)
    assert command[command.index('--isaac-lab-path') + 1] == str(Path.home() / 'IsaacLab')
    plan = pipeline._replicator_build_plan({'output_root': str(paths.artifact_root / 'dataset/sidecar')})
    assert str(paths.runtime_root / 'scripts/lerobot_isaac_replicator_synthetic.py') in plan['worker']['command']


def test_lerobot_background_fake_launcher_keeps_source_and_state_separate(paths, monkeypatch):
    from device_bridges.lerobot import bridge as implementation
    captured = []
    metadata = select_metadata(paths, monkeypatch)
    monkeypatch.setattr(implementation.subprocess, 'Popen', lambda command, **kwargs: captured.append((command, kwargs)) or SimpleNamespace(pid=87654321, poll=lambda: None))
    monkeypatch.setattr(implementation.time, 'sleep', lambda _: None)
    bridge = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    monkeypatch.setattr(bridge, '_process_start_ticks', lambda _: 42)
    command = ['/external/python', '-m', 'lerobot.train', '--steps=4']
    result = bridge._start_live_process(session_id='fixture', command=command, background=True)
    argv, kwargs = captured[0]
    assert argv[1:] == [str(paths.runtime_root / 'scripts/lerobot_background_train_runner.py'), '--state-path', str(paths.run_root / 'lerobot_sessions/fixture.state.json'), '--cwd', str(paths.runtime_root), '--', *command]
    assert kwargs['cwd'] == str(paths.runtime_root)
    assert kwargs['text'] is True and kwargs['start_new_session'] is True
    assert kwargs['env']['ATR_LAYOUT_CONFIG'] == str(metadata)
    assert result['session_updates']['log_path'] == str(paths.run_root / 'lerobot_sessions/fixture.log')
    bridge._close_log_handle('fixture')
    assert not paths.runtime_root.exists() and not paths.repository_root.exists()


def test_bootstrap_supplies_lerobot_binding(paths, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    guide = paths.system_root / 'project/Project_guide.txt'
    guide.parent.mkdir(parents=True)
    guide.write_text('Synthetic software-only fixture.')
    monkeypatch.setattr(bootstrap, '_load_configs', lambda paths: {'system': {'system': {}}, 'models': {}, 'devices': {'devices': {}}, 'lerobot': {}})
    monkeypatch.setattr(bootstrap, '_build_backend', lambda *a, **kw: MockLLMBackend())
    actual = bootstrap.register_lerobot_tools
    seen = []
    def capture(*args, **kwargs):
        bridge = actual(*args, **kwargs)
        seen.append(bridge.config)
        return bridge
    monkeypatch.setattr(bootstrap, 'register_lerobot_tools', capture)
    bootstrap.load_runtime(paths=paths)
    assert seen[0].paths is paths
    assert seen[0].session_memory_path == paths.memory_root / 'lerobot_sessions.json'


def test_app_lazy_lerobot_uses_frozen_binding(paths, monkeypatch):
    from app import main
    config = paths.runtime_root / 'configs/lerobot.yaml'
    config.parent.mkdir(parents=True)
    config.write_text('lerobot: {}\n')
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    monkeypatch.setattr(main, '_LEROBOT_BRIDGE', None)
    monkeypatch.setattr(main, '_registered_lerobot_bridge', lambda: None)
    monkeypatch.setattr(main, 'load_all_configs', lambda location: {'lerobot': {}} if location == paths.runtime_root / 'configs' else pytest.fail(str(location)))
    bridge = main._lerobot_bridge()
    assert bridge.config.paths is paths
    assert bridge.config.artifact_run_root == paths.run_root
    assert bridge.config.session_memory_path == paths.memory_root / 'lerobot_sessions.json'


@pytest.mark.asyncio
async def test_app_reads_bound_profile_stores(paths, monkeypatch):
    from app import main
    from utils.lerobot_rollout_profile import save_lerobot_rollout_profile
    from utils.manipulation_profile import save_manipulation_agent_profile
    from utils.printer_profile import save_prusa_print_profile
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    save_lerobot_rollout_profile({'profile_id': 'bound-rollout'}, paths=paths)
    save_manipulation_agent_profile({'profile_id': 'bound-manipulation'}, paths=paths)
    save_prusa_print_profile({'material': 'PETG'}, path=paths.memory_root / 'prusa_print_profile.json')
    rollout = await main.get_lerobot_rollout_config()
    manipulation = await main.get_lerobot_manipulation_agent_config()
    assert rollout['profile']['profile_id'] == 'bound-rollout'
    assert rollout['profile_path'] == str(paths.memory_root / 'lerobot_rollout_profile.json')
    assert manipulation['profile']['profile_id'] == 'bound-manipulation'
    manager = SimpleNamespace(fleet_selection=lambda: (SimpleNamespace(provider='prusa'), 'fixture'))
    assert main._selected_print_profile(manager)['material'] == 'PETG'


def test_controller_reads_bound_printer_profile(paths, monkeypatch):
    from app.controller import MainController
    from utils.printer_profile import save_prusa_print_profile
    save_prusa_print_profile({'material': 'PETG', 'bed_leveling_enabled': False}, path=paths.memory_root / 'prusa_print_profile.json')
    assert MainController._validated_printer_defaults(paths=paths)['material'] == 'PETG'
    assert MainController._print_start_calibration_flags(paths=paths)['bed_leveling'] is False


def test_e2e_helper_keeps_legacy_and_bound_config_sources(paths, monkeypatch):
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke
    from utils import config_loader
    seen = []
    monkeypatch.setattr(config_loader, 'load_all_configs', lambda source: seen.append(source) or {'lerobot': {}})
    legacy = smoke._bridge(paths.repository_root)
    bound = smoke._bridge(paths.repository_root, paths=paths)
    assert seen == [paths.repository_root / 'configs', paths.runtime_root / 'configs']
    assert legacy.config.session_memory_path == paths.repository_root / 'memory/lerobot_sessions.json'
    assert bound.config.session_memory_path == paths.memory_root / 'lerobot_sessions.json'
    assert bound.config.paths is paths


def test_named_profiles_are_independently_bound(paths):
    from utils.lerobot_rollout_profile import save_lerobot_rollout_profile, load_lerobot_rollout_profile
    from utils.manipulation_profile import save_manipulation_agent_profile, load_manipulation_agent_profile
    other = replace(paths, memory_root=paths.memory_root / 'other')
    for binding, profile in ((paths, 'one'), (other, 'two')):
        save_lerobot_rollout_profile({'profile_id': profile}, paths=binding)
        save_manipulation_agent_profile({'profile_id': profile}, paths=binding)
    for binding, profile in ((paths, 'one'), (other, 'two')):
        assert load_lerobot_rollout_profile(paths=binding)['profile_id'] == profile
        assert load_manipulation_agent_profile(paths=binding)['profile_id'] == profile
        assert (binding.memory_root / 'lerobot_rollout_profile.json').is_file()
        assert (binding.memory_root / 'manipulation_agent_bridge.json').is_file()
    assert not paths.runtime_root.exists() and not paths.repository_root.exists()


def test_source_launcher_rejects_nonreproducible_binding(paths, monkeypatch):
    from device_bridges.lerobot import bridge as implementation
    monkeypatch.setattr(implementation.subprocess, 'Popen', lambda *a, **kw: pytest.fail('mismatched metadata reached process launch'))
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(paths.repository_root / 'missing-layout.json'))
    bridge = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    result = bridge._start_live_process(session_id='fixture', command=['/external/python', '-m', 'lerobot.train'])
    assert result['ok'] is False
    assert 'runtime metadata' in result['message']


def test_standalone_wrappers_bind_only_default_private_paths(paths, monkeypatch):
    from utils import runtime_paths
    from scripts import lerobot_isaac_mirror_runtime_wrapper as mirror
    from scripts import lerobot_live_rollout_wrapper as rollout
    from scripts import lerobot_omx_action_logger as logger
    monkeypatch.setattr(runtime_paths, '_current', paths)
    for key in ('ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH', 'ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH', 'ATR_ACTIVE_ROBOT_CAM_RESULT_DIR', 'ATR_LEROBOT_OMX_ACTION_LOG_DIR'):
        monkeypatch.delenv(key, raising=False)
    tracker = mirror.ActiveRobotCamTracker(None, None)
    assert tracker.capture_pose_path == paths.run_root / 'active_robot_cam/latest_follower_capture_pose.json'
    assert tracker.home_pose_path == paths.run_root / 'active_robot_cam/latest_follower_home_pose.json'
    assert tracker.result_dir == paths.run_root / 'active_robot_cam'
    monkeypatch.setenv('ATR_ACTIVE_ROBOT_CAM_RESULT_DIR', 'explicit-relative')
    assert mirror.ActiveRobotCamTracker(None, None).result_dir == Path('explicit-relative')
    monkeypatch.setenv('ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID', 'fixture')
    rollout._ensure_omx_action_log_env_defaults()
    assert os.environ['ATR_LEROBOT_OMX_ACTION_LOG_DIR'] == str(paths.run_root / 'lerobot_action_logs/fixture')
    monkeypatch.delenv('ATR_LEROBOT_OMX_ACTION_LOG_DIR')
    log = logger._logger_from_env()
    assert log.log_dir == paths.run_root / 'lerobot_action_logs/fixture'


def test_validate_cli_uses_bound_source_and_private_roots(paths, monkeypatch):
    from utils import runtime_paths
    from scripts import lerobot_isaac_lab_validate as validate
    monkeypatch.setattr(runtime_paths, '_current', paths)
    monkeypatch.setattr(validate, 'load_all_configs', lambda source: {'lerobot': {}} if source == paths.runtime_root / 'configs' else pytest.fail(str(source)))
    assert validate._bridge().config.session_memory_path == paths.memory_root / 'lerobot_sessions.json'


@pytest.mark.parametrize('script', ['lerobot_isaac_lab_e2e_smoke', 'lerobot_synthetic_e2e_smoke'])
def test_smoke_cli_absent_root_binds_but_explicit_repository_stays_legacy(paths, monkeypatch, script):
    import importlib
    from utils import runtime_paths
    smoke = importlib.import_module('scripts.' + script)
    monkeypatch.setattr(runtime_paths, '_current', paths)
    seen = []
    def bridge(root, **kwargs):
        seen.append((root, kwargs.get('paths')))
        return SimpleNamespace(isaac_lab_run_e2e=lambda payload: {'ok': True})
    monkeypatch.setattr(smoke, '_bridge', bridge)
    if script == 'lerobot_synthetic_e2e_smoke':
        monkeypatch.setattr(smoke, 'run_e2e_smoke', lambda **kwargs: {'ok': True})
        argv = ['--dataset', '/tmp/fixture', '--stage', '/external/scene.usda', '--isaac-lab-path', '/external/IsaacLab']
    else:
        argv = ['--dataset-path', '/tmp/fixture']
    assert smoke.main(argv) == 0
    assert seen[-1] == (paths.repository_root, paths)
    assert smoke.main([*argv, '--repo-root', str(paths.repository_root)]) == 0
    assert seen[-1] == (paths.repository_root, None)
    assert not paths.runtime_root.exists() and not paths.repository_root.exists()


def test_e2e_direct_script_bootstraps_source_before_loading_binding(monkeypatch):
    import builtins
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke
    source = str(smoke._repo_root())
    monkeypatch.setattr(smoke.sys, 'path', [entry for entry in smoke.sys.path if entry != source])
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == 'utils.runtime_paths':
            assert source in smoke.sys.path
            raise RuntimeError('binding import reached')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    with pytest.raises(RuntimeError, match='binding import reached'):
        smoke.main(['--dataset-path', '/tmp/fixture'])


def test_bound_camera_capture_is_servable_and_does_not_change_image(paths):
    from mcp_tools.lerobot_schemas import RobotProfile
    bound = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    legacy = register_lerobot_tools(ToolRegistry(), {}, repo_root=paths.repository_root)
    profile = RobotProfile(profile_id='fixture', display_name='Fixture', robot_family='omx', robot_type='omx_follower', teleop_type='omx_leader')
    actual = bound._fake_camera_capture(profile, 'top', 'fake')
    expected = legacy._fake_camera_capture(profile, 'top', 'fake')
    assert Path(actual['path']).is_relative_to(paths.artifact_root / 'lerobot/camera_tests')
    assert Path(actual['path']).read_bytes() == Path(expected['path']).read_bytes()
    assert bound._is_under_allowed_roots(Path(actual['path']))


def test_preconstructed_lerobot_config_cannot_contradict_binding(paths):
    config = LeRobotBridgeConfig(repo_root=paths.runtime_root, paths=paths)
    with pytest.raises(ValueError, match='repo_root'):
        LeRobotBridge(config)


def test_monitor_fake_launch_and_process_ownership_remain_scoped(paths, monkeypatch):
    from device_bridges.lerobot import bridge as implementation
    select_metadata(paths, monkeypatch)
    bridge = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    source = paths.runtime_root / 'scripts/training_stability_monitor.py'
    source.parent.mkdir(parents=True)
    source.touch()
    launches = []
    monkeypatch.setattr(implementation.subprocess, 'Popen', lambda cmd, **kw: launches.append((cmd, kw)) or SimpleNamespace(pid=87654))
    monkeypatch.setattr(bridge, '_process_start_ticks', lambda _: 42)
    result = bridge._start_training_monitor({'session_id': 'fixture', 'log_path': '/external/train.log'}, LeRobotSessionRequest())
    assert result['status'] == 'running'
    assert launches[0][0][1:] == [str(source), '--interval-seconds', '30', '--output-dir', str(paths.run_root / 'training_watch'), '--train-log', '/external/train.log']
    assert launches[0][1]['cwd'] == str(paths.runtime_root)
    original_read = Path.read_bytes
    monkeypatch.setattr(implementation.os, 'listdir', lambda path: ['87654', '87655'])
    monkeypatch.setattr(Path, 'read_bytes', lambda path: b'python\x00-m\x00lerobot.train\x00' if str(path).startswith('/proc/8765') else original_read(path))
    monkeypatch.setattr(implementation.os, 'readlink', lambda path: str(paths.repository_root if str(path).startswith('/proc/87654/') else paths.runtime_root))
    assert bridge._project_lerobot_pids('train') == [87654]


@pytest.mark.parametrize('external_cwd', ['', '/external/IsaacLab'])
def test_isaac_fake_launch_preserves_nonpath_args_and_external_cwd(paths, monkeypatch, external_cwd):
    import sys
    from device_bridges.lerobot import bridge as implementation
    select_metadata(paths, monkeypatch)
    monkeypatch.setenv('PYTHONPATH', '/external/dependency')
    bridge = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    script = paths.runtime_root / 'scripts/fixture.py'
    script.parent.mkdir(parents=True)
    script.touch()
    command = [sys.executable, str(script), '--trials', '3', '--seed', '42', '--headless']
    captured = []
    monkeypatch.setattr(implementation.subprocess, 'Popen', lambda cmd, **kw: captured.append((cmd, kw)) or SimpleNamespace(pid=87654, poll=lambda: None))
    output = paths.artifact_root / 'dataset/sidecar'
    request = IsaacLabSyntheticRequest(dataset_path=str(paths.artifact_root / 'dataset'), isaac_lab_path=external_cwd)
    result = bridge._record_isaac_lab_running_job('mimic', request, {'output_root': str(output), 'mimic': {'runner': {'command': command}}})
    assert result['ok'], result
    assert captured[0][0] == command
    assert captured[0][1]['cwd'] == (external_cwd or str(paths.runtime_root))
    assert captured[0][1]['env']['PYTHONPATH'] == str(paths.runtime_root) + os.pathsep + '/external/dependency'
    assert result['job']['cwd'] == captured[0][1]['cwd']
    assert Path(result['job']['log_path']).is_relative_to(output)


def test_bound_e2e_command_keeps_all_existing_nonpath_arguments(paths):
    bound = register_lerobot_tools(ToolRegistry(), {}, paths=paths)
    legacy = register_lerobot_tools(ToolRegistry(), {}, repo_root=paths.repository_root)
    request = IsaacLabSyntheticRequest(dataset_path='/external/dataset', isaac_lab_path='/external/lab', isaac_sim_python='/external/sim/python.sh', mimic_trials=3, mimic_num_envs=2, e2e_episodes=5, e2e_episode_s=10)
    before = legacy._isaac_lab_live_e2e_command(request)
    after = bound._isaac_lab_live_e2e_command(request)
    after[1] = before[1]
    offset = after.index('--runtime-root')
    del after[offset:offset + 2]
    assert after == before
