"""Use the installed OMX methods; replace only physical serial/camera I/O."""
import contextlib
import json
import time

import pytest


def test_existing_omx_connect_observe_clamp_send_disconnect_without_worker(monkeypatch, tmp_path):
    omx = pytest.importorskip('lerobot.robots.omx_follower.omx_follower')
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from scripts import lerobot_linear_interpolation as runtime

    class Serial:
        def __init__(self, *, port, motors, calibration):
            self.motors = motors
            self.calibration = calibration
            self.is_connected = False
            self.is_calibrated = True
            self.values = dict.fromkeys(motors, 0.)
            self.goals = []
            self.disconnected_with = None
        def connect(self):
            self.is_connected = True
        def disconnect(self, disable_torque):
            self.is_connected = False
            self.disconnected_with = disable_torque
        def torque_disabled(self):
            return contextlib.nullcontext()
        def configure_motors(self):
            pass
        def write(self, *args):
            pass
        def sync_read(self, register):
            assert register == 'Present_Position'
            return dict(self.values)
        def sync_write(self, register, values):
            assert register == 'Goal_Position'
            self.goals.append(dict(values))
            self.values.update(values)

    class Camera:
        is_connected = False
        image = object()
        def connect(self):
            self.is_connected = True
        def disconnect(self):
            self.is_connected = False
        def async_read(self):
            return self.image

    def no_worker(*args, **kwargs):
        raise AssertionError('linear path must not create an IPC/motor worker')

    monkeypatch.setattr(omx, 'DynamixelMotorsBus', Serial)
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', no_worker)
    monkeypatch.setenv('ATR_LINEAR_ENABLED', '1')
    monkeypatch.setenv('ATR_LINEAR_CONFIG', json.dumps({
        'input_hz': 30, 'output_hz': 100, 'session_id': 'driver-test'}))
    monkeypatch.delenv('ATR_LEROBOT_OMX_ACTION_LOG_DIR', raising=False)
    # Undo class installation at fixture teardown, including the marker.
    for name in ('connect', 'disconnect'):
        monkeypatch.setattr(omx.OmxFollower, name, getattr(omx.OmxFollower, name))
    monkeypatch.setattr(omx.OmxFollower, '_atr_linear_installed', False, raising=False)
    assert runtime.install_linear_if_enabled()
    robot = omx.OmxFollower(OmxFollowerConfig(
        port='/dev/DO_NOT_OPEN', id='test', calibration_dir=tmp_path,
        max_relative_target=5., disable_torque_on_disconnect=False))
    camera = Camera()
    robot.cameras = {'top': camera}
    original_bus = robot.bus
    robot.connect()
    try:
        assert robot.bus is original_bus
        assert robot.get_observation()['top'] is camera.image
        assert robot.send_action({'shoulder_pan.pos': 20.}) == {'shoulder_pan.pos': 5.}
        deadline = time.monotonic() + 1
        while (not original_bus.goals or original_bus.goals[-1]['shoulder_pan'] != 5.) and time.monotonic() < deadline:
            time.sleep(.005)
        assert len(original_bus.goals) >= 3
        assert 0 < original_bus.goals[0]['shoulder_pan'] < 5.
        assert original_bus.goals[-1]['shoulder_pan'] == 5.
        assert robot.get_observation()['shoulder_pan.pos'] == 5.
    finally:
        robot.disconnect()
    assert not camera.is_connected
    assert original_bus.disconnected_with is False
