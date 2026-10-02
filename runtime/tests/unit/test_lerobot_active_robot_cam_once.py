from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import lerobot_active_robot_cam_once


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Camera:
    use_depth = True

    def __init__(self, clock, frames):
        self.clock, self.frames, self.calls = clock, iter(frames), 0
        self.last = (np.full((12, 16, 3), 100, dtype=np.uint8), np.full((12, 16), 1000, dtype=np.uint16))

    def read_color_depth(self, timeout_ms):
        self.calls += 1
        self.clock.sleep(min(0.1, timeout_ms / 1000))
        value = next(self.frames, self.last)
        if isinstance(value, Exception):
            raise value
        self.last = value
        return value


def test_stable_rgbd_finishes_before_fixed_twenty_second_wait(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock, raising=False)
    camera = Camera(clock, [])
    result = lerobot_active_robot_cam_once._wait_for_camera_ready(camera, timeout_s=20)
    assert result["ok"] is True
    assert result["stable_frames"] >= 8
    assert 0.5 <= result["elapsed_s"] < 3


def test_stable_fast_frames_can_satisfy_minimum_observation_duration(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock)
    camera = Camera(clock, [])

    def read_color_depth(timeout_ms):
        clock.sleep(1 / 60)
        return camera.last

    camera.read_color_depth = read_color_depth
    result = lerobot_active_robot_cam_once._wait_for_camera_ready(camera, timeout_s=2)
    assert result["ok"]
    assert result["stable_frames"] >= 8
    assert 0.5 <= result["elapsed_s"] < 2


@pytest.mark.parametrize("bad", [
    (np.zeros((12, 16, 3), dtype=np.uint8), np.ones((12, 16), dtype=np.uint16)),
    (np.full((12, 16, 3), 100, dtype=np.uint8), np.zeros((12, 16), dtype=np.uint16)),
    (np.full((12, 16, 3), 100, dtype=np.uint8), np.full((12, 16), np.nan)),
    (np.full((12, 16, 3), 100, dtype=np.uint8), np.ones((3, 4), dtype=np.uint16)),
    RuntimeError("no new frame"),
])
def test_invalid_rgbd_never_passes_on_timeout(monkeypatch, bad):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock, raising=False)
    camera = Camera(clock, [bad] * 100)
    with pytest.raises(RuntimeError, match="ACTIVE_ROBOT_CAM_CAMERA_NOT_READY"):
        lerobot_active_robot_cam_once._wait_for_camera_ready(camera, timeout_s=2)
    assert clock.now <= 2.1


def test_exposure_must_stabilize_and_bad_frame_resets_streak(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock, raising=False)
    depth = np.full((12, 16), 1000, dtype=np.uint16)
    frames = [(np.full((12, 16, 3), value, dtype=np.uint8), depth) for value in [30, 180] * 5]
    frames += [RuntimeError("dropped frame")]
    camera = Camera(clock, frames)
    result = lerobot_active_robot_cam_once._wait_for_camera_ready(camera, timeout_s=20)
    assert result["ok"]
    assert camera.calls >= 19


def test_one_shot_realsense_uses_short_bootstrap_without_mutating_input(monkeypatch):
    import sys
    module = SimpleNamespace(RealSenseCameraConfig=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setitem(sys.modules, "lerobot.cameras.realsense.configuration_realsense", module)
    payload = {"serial_number_or_name": "fixture", "warmup_s": 20, "use_depth": True}
    config = lerobot_active_robot_cam_once._realsense_camera_config(payload)
    assert config.warmup_s == 1
    assert config.use_depth is True
    assert payload["warmup_s"] == 20


def robot_fixture(monkeypatch, clock, camera):
    import sys
    calls = []

    class Robot:
        def __init__(self, config):
            self.cameras = {"wrist": camera}
            calls.append(("config", config))

        def connect(self, calibrate):
            calls.append(("connect", calibrate))
            clock.sleep(2)  # Existing SDK initial delay plus short bootstrap.

        def disconnect(self):
            calls.append(("disconnect", None))

    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.config_omx_follower",
                        SimpleNamespace(OmxFollowerConfig=lambda **kwargs: SimpleNamespace(**kwargs)))
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", SimpleNamespace(OmxFollower=Robot))
    monkeypatch.setitem(sys.modules, "lerobot.cameras.realsense.configuration_realsense",
                        SimpleNamespace(RealSenseCameraConfig=lambda **kwargs: SimpleNamespace(**kwargs)))
    return calls, {"robot_port": "fixture-only", "cameras": {"wrist": {
        "type": "intelrealsense", "serial_number_or_name": "fixture", "warmup_s": 20}}}


def test_connection_gates_capture_on_stable_frames_and_reports_elapsed(monkeypatch):
    clock = Clock()
    camera = Camera(clock, [])
    calls, payload = robot_fixture(monkeypatch, clock, camera)
    robot, readiness = lerobot_active_robot_cam_once._connect_robot(payload)
    assert readiness["cameras"]["wrist"]["ok"]
    assert 2 < readiness["elapsed_s"] < 5
    assert [c[0] for c in calls] == ["config", "connect"]
    assert calls[0][1].cameras["wrist"].warmup_s == 1
    assert calls[1] == ("connect", False)
    assert robot.cameras["wrist"] is camera


def test_readiness_failure_exits_before_tracker_or_pose_commands(monkeypatch, capsys):
    import sys
    clock = Clock()
    camera = Camera(clock, [RuntimeError("missing RGB-D")]*1000)
    calls, payload = robot_fixture(monkeypatch, clock, camera)
    monkeypatch.setattr(sys, "argv", ["driver", json.dumps(payload)])
    with pytest.raises(SystemExit) as exc:
        lerobot_active_robot_cam_once.main()
    assert exc.value.code == 3
    assert "ACTIVE_ROBOT_CAM_CAMERA_NOT_READY" in capsys.readouterr().out
    assert [c[0] for c in calls] == ["config", "connect", "disconnect"]


def test_unstable_exposure_is_not_accepted_at_deadline(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock)
    depth = np.full((12, 16), 1000, dtype=np.uint16)
    frames = [(np.full((12, 16, 3), v, dtype=np.uint8), depth) for v in [30, 180]*100]
    with pytest.raises(RuntimeError, match="exposure_or_depth_unstable"):
        lerobot_active_robot_cam_once._wait_for_camera_ready(Camera(clock, frames), timeout_s=3)


@pytest.mark.parametrize("metric", ["median", "coverage"])
def test_unstable_depth_is_not_accepted_at_deadline(monkeypatch, metric):
    clock = Clock()
    monkeypatch.setattr(lerobot_active_robot_cam_once, "time", clock)
    color = np.full((12, 16, 3), 100, dtype=np.uint8)
    first = np.full((12, 16), 1000, dtype=np.uint16)
    second = first.copy()
    if metric == "median":
        second[:] = 1500
    else:
        second[:6] = 0
    camera = Camera(clock, [(color, first), (color, second)] * 100)
    with pytest.raises(RuntimeError, match="exposure_or_depth_unstable"):
        lerobot_active_robot_cam_once._wait_for_camera_ready(camera, timeout_s=3)


def test_accepts_resume_timeout_within_tracker_soft_tolerance() -> None:
    wait_result = {
        "ok": False,
        "status": "timeout",
        "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
        "max_error_deg": 2.1001,
        "tolerance_deg": 2.0,
    }

    result = lerobot_active_robot_cam_once._accept_soft_resume_tolerance(wait_result, soft_tolerance_deg=3.0)

    assert result["ok"] is True
    assert result["status"] == "reached_within_soft_tolerance"
    assert result["warning_only"] is True
    assert result["max_error_deg"] == 2.1001
    assert result["soft_tolerance_deg"] == 3.0


def test_rejects_resume_timeout_outside_tracker_soft_tolerance() -> None:
    wait_result = {
        "ok": False,
        "status": "timeout",
        "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
        "max_error_deg": 3.1001,
        "tolerance_deg": 2.0,
    }

    result = lerobot_active_robot_cam_once._accept_soft_resume_tolerance(wait_result, soft_tolerance_deg=3.0)

    assert result == wait_result
