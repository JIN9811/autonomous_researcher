import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_tools.lerobot_schemas import LeRobotSessionRequest
import utils.lerobot_rollout_profile as rollout
import utils.manipulation_profile as manipulation
from device_bridges.lerobot.bridge import LeRobotBridge


@pytest.mark.parametrize('fps,hz', [(15, 100), (30, 100), (30, 60), (60, 100)])
def test_request_and_bridge_keep_input_and_output_rates_separate(fps, hz):
    request = LeRobotSessionRequest(profile_id='robotis_omx_ai', runtime_mode='live',
        policy_type='smolvla', fps=fps, rollout_linear_enabled=True, rollout_linear_hz=hz)
    assert request.model_dump().get('rollout_linear_hz') == hz
    bridge = object.__new__(LeRobotBridge)
    bridge._selected_profile_id = 'robotis_omx_ai'
    bridge._profile = lambda _: SimpleNamespace(fps=15, robot_type='omx_follower')
    env = bridge._linear_environment('rollout', request, 's1')
    config = json.loads(env['ATR_LINEAR_CONFIG'])
    assert config['input_hz'] == fps
    assert config['output_hz'] == hz
    assert request.fps == fps


def test_off_is_noop_and_does_not_require_native_setup():
    request = LeRobotSessionRequest()
    assert request.model_dump().get('rollout_linear_enabled') is False
    bridge = object.__new__(LeRobotBridge)
    assert bridge._linear_environment('rollout', request, 's1') == {'ATR_LINEAR_ENABLED': '0'}


@pytest.mark.parametrize('workflow', ['record', 'replay', 'train'])
def test_linear_never_changes_other_workflows(workflow):
    bridge = object.__new__(LeRobotBridge)
    assert hasattr(bridge, '_linear_environment')
    with pytest.raises(ValueError, match='rollout'):
        bridge._linear_environment(workflow, LeRobotSessionRequest(rollout_linear_enabled=True), 's1')


def test_saved_standalone_rate_does_not_inherit_agent_enable(tmp_path, monkeypatch):
    monkeypatch.setattr(rollout, 'LEROBOT_ROLLOUT_PROFILE_PATH', tmp_path/'standalone.json')
    profile = rollout.load_lerobot_rollout_profile(fallback={'rollout_linear_enabled': True})
    assert profile.get('rollout_linear_enabled') is False
    rollout.save_lerobot_rollout_profile({'rollout_linear_enabled': True, 'rollout_linear_hz': 60})
    profile = rollout.load_lerobot_rollout_profile()
    assert profile['rollout_linear_enabled'] is True
    assert profile['rollout_linear_hz'] == 60


def test_agent_tasks_round_trip_independent_rates(tmp_path, monkeypatch):
    monkeypatch.setattr(manipulation, 'MANIPULATION_AGENT_PROFILE_PATH', tmp_path/'agent.json')
    manipulation.save_manipulation_agent_profile({'task_profiles': {
        'transfer_to_utm': {'rollout_linear_enabled': True, 'rollout_linear_hz': 100},
        'clear_utm_to_disposal': {'rollout_linear_enabled': False, 'rollout_linear_hz': 60}}})
    profiles = manipulation.load_manipulation_agent_profile()['task_profiles']
    assert profiles['transfer_to_utm'].get('rollout_linear_enabled') is True
    assert profiles['transfer_to_utm']['rollout_linear_hz'] == 100
    assert profiles['clear_utm_to_disposal']['rollout_linear_enabled'] is False
    assert profiles['clear_utm_to_disposal']['rollout_linear_hz'] == 60


def test_package_is_independently_importable_without_lerobot(monkeypatch):
    source = Path(__file__).resolve().parents[2]/'libs/joint_linear_interpolation/src'
    assert source.is_dir(), 'standalone package is missing'
    monkeypatch.syspath_prepend(str(source))
    module = importlib.import_module('joint_linear_interpolation')
    curve = module.LinearInterpolator(1/30)
    curve.retarget({'j': 0.}, {'j': 10.}, 0.)
    assert curve.sample(1/60)['j'] == pytest.approx(5.)
    assert curve.sample(1/30)['j'] == 10.


def test_rtc_rate_resolution_uses_same_normalization_as_runner():
    bridge = object.__new__(LeRobotBridge)
    bridge._profile = lambda _: SimpleNamespace(fps=60, robot_type='omx_follower')
    request = LeRobotSessionRequest(profile_id='robotis_omx_ai', runtime_mode='live',
        policy_type='smolvla', rollout_inference_type=' RTC ',
        rollout_linear_enabled=True, rollout_linear_hz=40)
    with pytest.raises(ValueError, match='Output rate'):
        bridge._linear_environment('rollout', request, 's1')
