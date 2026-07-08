"""Tests for live RealSense depth observation patching during policy rollout."""

from __future__ import annotations

import json
import os
import sys
import threading
import types
from enum import Enum
from functools import cached_property
from types import SimpleNamespace

import numpy as np


def test_live_depth_patch_adds_raw_depth_visual_feature_from_latest_realsense_frame(monkeypatch) -> None:
    class FakeBus:
        motors = {"shoulder_pan": object()}

        def sync_read(self, _key: str) -> dict[str, float]:
            return {"shoulder_pan": 1.0}

    class FakeCamera:
        def __init__(self) -> None:
            self.frame_lock = threading.Lock()
            self.latest_depth_frame = np.array([[0, 1000], [1500, 2500]], dtype=np.uint16)

        def async_read(self) -> np.ndarray:
            return np.zeros((2, 2, 3), dtype=np.uint8)

    class FakeOmxFollower:
        def __init__(self) -> None:
            self.bus = FakeBus()
            self.config = SimpleNamespace(cameras={"top": SimpleNamespace(height=2, width=2, use_depth=True)})
            self.cameras = {"top": FakeCamera()}

        @property
        def _motors_ft(self) -> dict[str, type]:
            return {"shoulder_pan.pos": float}

        @property
        def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
            return {"top": (2, 2, 3)}

        @cached_property
        def observation_features(self) -> dict[str, object]:
            return {**self._motors_ft, **self._cameras_ft}

        def get_observation(self) -> dict[str, object]:
            obs = {f"{key}.pos": value for key, value in self.bus.sync_read("Present_Position").items()}
            obs["top"] = self.cameras["top"].async_read()
            return obs

    module_name = "lerobot.robots.omx_follower.omx_follower"
    fake_module = types.ModuleType(module_name)
    fake_module.OmxFollower = FakeOmxFollower
    monkeypatch.setitem(sys.modules, module_name, fake_module)
    monkeypatch.setenv("ATR_LEROBOT_LIVE_DEPTH_FEATURES", "1")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", "0.001")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_CLIP_MIN_MM", "0")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_CLIP_MAX_MM", "2000")

    from scripts.lerobot_live_depth_observation_patch import install_live_depth_observation_patch

    assert install_live_depth_observation_patch() is True

    robot = FakeOmxFollower()
    assert robot.observation_features["top_depth"] == (2, 2, 3)

    obs = robot.get_observation()
    depth = obs["top_depth"]
    assert isinstance(depth, np.ndarray)
    assert depth.dtype == np.uint8
    assert depth.shape == (2, 2, 3)
    assert depth[0, 0, 0] == 0
    assert 126 <= int(depth[0, 1, 0]) <= 128
    assert depth[1, 1, 0] == 255


def test_live_rollout_wrapper_uses_lerobot_record_console_entrypoint(monkeypatch) -> None:
    called: list[str] = []
    fake_lerobot = types.ModuleType("lerobot")
    fake_scripts = types.ModuleType("lerobot.scripts")
    fake_record = types.ModuleType("lerobot.scripts.lerobot_record")
    fake_record.main = lambda: called.append("record")
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.scripts", fake_scripts)
    monkeypatch.setitem(sys.modules, "lerobot.scripts.lerobot_record", fake_record)
    monkeypatch.delitem(sys.modules, "lerobot.record", raising=False)

    from scripts.lerobot_live_rollout_wrapper import _lerobot_record_main

    main = _lerobot_record_main()
    main()

    assert called == ["record"]


def test_omx_runtime_units_patch_forces_legacy_modes_on_constructed_follower(monkeypatch) -> None:
    class FakeNormMode(str, Enum):
        RANGE_0_100 = "range_0_100"
        RANGE_M100_100 = "range_m100_100"
        DEGREES = "degrees"

    class FakeOmxFollower:
        def __init__(self) -> None:
            self.bus = SimpleNamespace(
                motors={
                    "shoulder_pan": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                    "shoulder_lift": SimpleNamespace(norm_mode=FakeNormMode.DEGREES),
                    "elbow_flex": SimpleNamespace(norm_mode=FakeNormMode.DEGREES),
                    "wrist_flex": SimpleNamespace(norm_mode=FakeNormMode.DEGREES),
                    "wrist_roll": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                    "gripper": SimpleNamespace(norm_mode=FakeNormMode.DEGREES),
                }
            )

    fake_lerobot = types.ModuleType("lerobot")
    fake_motors = types.ModuleType("lerobot.motors")
    fake_motors.MotorNormMode = FakeNormMode
    fake_robots = types.ModuleType("lerobot.robots")
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    fake_omx_module.OmxFollower = FakeOmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.motors", fake_motors)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    from scripts.lerobot_omx_runtime_units_patch import install_omx_follower_runtime_units_patch

    assert install_omx_follower_runtime_units_patch() is True

    robot = FakeOmxFollower()
    modes = {name: motor.norm_mode for name, motor in robot.bus.motors.items()}
    assert modes == {
        "shoulder_pan": FakeNormMode.DEGREES,
        "shoulder_lift": FakeNormMode.RANGE_M100_100,
        "elbow_flex": FakeNormMode.RANGE_M100_100,
        "wrist_flex": FakeNormMode.RANGE_M100_100,
        "wrist_roll": FakeNormMode.DEGREES,
        "gripper": FakeNormMode.RANGE_0_100,
    }


def test_omx_runtime_patch_clamps_shoulder_lift_below_start_position(monkeypatch) -> None:
    class FakeNormMode(str, Enum):
        RANGE_0_100 = "range_0_100"
        RANGE_M100_100 = "range_m100_100"
        DEGREES = "degrees"

    class FakeBus:
        def __init__(self) -> None:
            self.read_count = 0
            self.motors = {
                "shoulder_pan": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                "shoulder_lift": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                "elbow_flex": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                "wrist_flex": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                "wrist_roll": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
                "gripper": SimpleNamespace(norm_mode=FakeNormMode.RANGE_0_100),
            }

        def sync_read(self, key: str) -> dict[str, float]:
            assert key == "Present_Position"
            self.read_count += 1
            return {"shoulder_lift": -63.25}

    class FakeOmxFollower:
        def __init__(self) -> None:
            self.bus = FakeBus()

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            return dict(action)

    fake_lerobot = types.ModuleType("lerobot")
    fake_motors = types.ModuleType("lerobot.motors")
    fake_motors.MotorNormMode = FakeNormMode
    fake_robots = types.ModuleType("lerobot.robots")
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    fake_omx_module.OmxFollower = FakeOmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.motors", fake_motors)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    from scripts.lerobot_omx_runtime_units_patch import install_omx_follower_runtime_units_patch

    assert install_omx_follower_runtime_units_patch() is True

    robot = FakeOmxFollower()
    sent = robot.send_action({"shoulder_pan.pos": 10.0, "shoulder_lift.pos": -90.0})
    assert sent == {"shoulder_pan.pos": 10.0, "shoulder_lift.pos": -63.25}

    sent = robot.send_action({"shoulder_lift.pos": -40.0})
    assert sent == {"shoulder_lift.pos": -40.0}
    assert robot.bus.read_count == 1


def test_omx_runtime_patch_can_disable_shoulder_lift_backstop(monkeypatch) -> None:
    class FakeNormMode(str, Enum):
        RANGE_0_100 = "range_0_100"
        RANGE_M100_100 = "range_m100_100"
        DEGREES = "degrees"

    class FakeBus:
        motors = {
            "shoulder_pan": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
            "shoulder_lift": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
            "elbow_flex": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
            "wrist_flex": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
            "wrist_roll": SimpleNamespace(norm_mode=FakeNormMode.RANGE_M100_100),
            "gripper": SimpleNamespace(norm_mode=FakeNormMode.RANGE_0_100),
        }

        def __init__(self) -> None:
            self.read_count = 0

        def sync_read(self, key: str) -> dict[str, float]:
            self.read_count += 1
            return {"shoulder_lift": -63.25}

    class FakeOmxFollower:
        def __init__(self) -> None:
            self.bus = FakeBus()

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            return dict(action)

    fake_motors = types.ModuleType("lerobot.motors")
    fake_motors.MotorNormMode = FakeNormMode
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    fake_omx_module.OmxFollower = FakeOmxFollower
    monkeypatch.setitem(sys.modules, "lerobot.motors", fake_motors)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)
    monkeypatch.setenv("ATR_LEROBOT_SHOULDER_LIFT_BACKSTOP", "0")

    from scripts.lerobot_omx_runtime_units_patch import install_omx_follower_runtime_units_patch

    assert install_omx_follower_runtime_units_patch() is True

    robot = FakeOmxFollower()
    assert robot.send_action({"shoulder_lift.pos": -90.0}) == {"shoulder_lift.pos": -90.0}
    assert robot.bus.read_count == 0


def test_omx_action_logger_writes_observation_requested_and_sent_events(tmp_path, monkeypatch) -> None:
    class FakeBus:
        motors = {
            "shoulder_pan": SimpleNamespace(id=11),
            "shoulder_lift": SimpleNamespace(id=12),
            "elbow_flex": SimpleNamespace(id=13),
            "wrist_flex": SimpleNamespace(id=14),
            "wrist_roll": SimpleNamespace(id=15),
            "gripper": SimpleNamespace(id=16),
        }

        def _unnormalize(self, ids_values: dict[int, float]) -> dict[int, int]:
            return {id_: int(value * 10) for id_, value in ids_values.items()}

    class FakeOmxFollower:
        def __init__(self) -> None:
            self.bus = FakeBus()

        def get_observation(self) -> dict[str, float]:
            return {
                "shoulder_pan.pos": 1.0,
                "shoulder_lift.pos": 2.0,
                "elbow_flex.pos": 3.0,
                "wrist_flex.pos": 4.0,
                "wrist_roll.pos": 5.0,
                "gripper.pos": 6.0,
            }

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            return dict(action)

    module_name = "lerobot.robots.omx_follower.omx_follower"
    fake_module = types.ModuleType(module_name)
    fake_module.OmxFollower = FakeOmxFollower
    monkeypatch.setitem(sys.modules, module_name, fake_module)
    monkeypatch.setenv("ATR_LEROBOT_OMX_ACTION_LOG", "1")
    monkeypatch.setenv("ATR_LEROBOT_OMX_ACTION_LOG_DIR", str(tmp_path / "motor_log"))
    monkeypatch.setenv("ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID", "lr-rollout-test")

    from scripts.lerobot_omx_action_logger import install_omx_follower_action_logger

    assert install_omx_follower_action_logger() is True

    robot = FakeOmxFollower()
    robot.get_observation()
    robot.send_action(
        {
            "shoulder_pan.pos": 10.0,
            "shoulder_lift.pos": 20.0,
            "elbow_flex.pos": 30.0,
            "wrist_flex.pos": 40.0,
            "wrist_roll.pos": 50.0,
            "gripper.pos": 60.0,
        }
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "motor_log" / "motor_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["observation", "action"]
    assert rows[0]["motors"]["shoulder_pan"]["id"] == 11
    assert rows[0]["positions"]["shoulder_pan.pos"] == 1.0
    assert rows[1]["requested_action"]["shoulder_pan.pos"] == 10.0
    assert rows[1]["sent_action"]["gripper.pos"] == 60.0
    assert rows[1]["latest_observation"]["wrist_roll.pos"] == 5.0
    assert rows[0]["raw_positions"]["shoulder_pan.pos"] == 10
    assert rows[1]["raw_requested_action"]["shoulder_pan.pos"] == 100
    assert rows[1]["raw_sent_action"]["gripper.pos"] == 600
    assert rows[1]["raw_latest_observation"]["wrist_roll.pos"] == 50
    assert (tmp_path / "motor_log" / "motor_events.csv").is_file()


def test_live_rollout_wrapper_installs_omx_action_logger(monkeypatch) -> None:
    calls: list[str] = []
    fake_lerobot = types.ModuleType("lerobot")
    fake_scripts = types.ModuleType("lerobot.scripts")
    fake_record = types.ModuleType("lerobot.scripts.lerobot_record")
    fake_record.main = lambda: calls.append("record")
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.scripts", fake_scripts)
    monkeypatch.setitem(sys.modules, "lerobot.scripts.lerobot_record", fake_record)
    monkeypatch.delitem(sys.modules, "lerobot.record", raising=False)

    import scripts.lerobot_live_rollout_wrapper as wrapper

    monkeypatch.setattr(wrapper, "install_omx_follower_runtime_units_patch", lambda: calls.append("units"))
    monkeypatch.setattr(wrapper, "install_live_depth_observation_patch", lambda: calls.append("depth"))
    monkeypatch.setattr(wrapper, "install_omx_follower_action_logger", lambda: calls.append("action_log"))

    wrapper.main()

    assert calls == ["units", "depth", "action_log", "record"]


def test_live_rollout_wrapper_defaults_omx_action_log_env(monkeypatch) -> None:
    import scripts.lerobot_live_rollout_wrapper as wrapper

    monkeypatch.delenv("ATR_LEROBOT_OMX_ACTION_LOG", raising=False)
    monkeypatch.delenv("ATR_LEROBOT_OMX_ACTION_LOG_DIR", raising=False)
    monkeypatch.delenv("ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lerobot_live_rollout_wrapper.py",
            "--dataset.repo_id=jin/eval_20260707_1-20260707T023521Z",
        ],
    )

    wrapper._ensure_omx_action_log_env_defaults()

    assert os.environ["ATR_LEROBOT_OMX_ACTION_LOG"] == "1"
    assert os.environ["ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID"].startswith("eval_20260707_1-20260707T023521Z-pid")
    assert os.environ["ATR_LEROBOT_OMX_ACTION_LOG_DIR"].endswith(
        f"runs/lerobot_action_logs/{os.environ['ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID']}"
    )
    assert os.environ["ATR_LEROBOT_OMX_ACTION_LOG_MOTORS"] == "shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper"
