"""Patch ROBOTIS OMX follower runtime units for policy rollout.

LeRobot policies are policy-agnostic at the robot boundary: ACT, Pi0.5,
X-VLA, and SmolVLA all eventually send actions through OmxFollower. Legacy
ROBOTIS OMX recordings use degrees for the full-turn axes and normalized
range units for the other arm joints.
"""

from __future__ import annotations

import os
from typing import Any


_INSTALLED_ATTR = "_atr_omx_runtime_units_patched"
_ORIGINAL_INIT_ATTR = "_atr_original_init_for_runtime_units"
_ORIGINAL_SEND_ATTR = "_atr_original_send_for_shoulder_lift_backstop"
_SHOULDER_LIFT_BACKSTOP_ATTR = "_atr_shoulder_lift_backstop_min"
_SHOULDER_LIFT_KEY = "shoulder_lift.pos"
_FALSE_VALUES = {"0", "false", "no", "off"}


def _legacy_omx_runtime_unit_modes(motor_norm_mode: Any) -> dict[str, Any]:
    return {
        "shoulder_pan": motor_norm_mode.DEGREES,
        "shoulder_lift": motor_norm_mode.RANGE_M100_100,
        "elbow_flex": motor_norm_mode.RANGE_M100_100,
        "wrist_flex": motor_norm_mode.RANGE_M100_100,
        "wrist_roll": motor_norm_mode.DEGREES,
        "gripper": motor_norm_mode.RANGE_0_100,
    }


def apply_omx_follower_runtime_units(robot: Any, motor_norm_mode: Any | None = None) -> bool:
    """Apply the legacy mixed unit map to an OmxFollower instance."""
    if motor_norm_mode is None:
        try:
            from lerobot.motors import MotorNormMode as motor_norm_mode
        except Exception:
            return False
    bus = getattr(robot, "bus", None)
    motors = getattr(bus, "motors", None)
    if not isinstance(motors, dict):
        return False
    changed = False
    for name, mode in _legacy_omx_runtime_unit_modes(motor_norm_mode).items():
        motor = motors.get(name)
        if motor is None:
            continue
        if getattr(motor, "norm_mode", None) is not mode:
            setattr(motor, "norm_mode", mode)
            changed = True
    return changed or bool(motors)


def _read_shoulder_lift_position(robot: Any) -> float | None:
    bus = getattr(robot, "bus", None)
    sync_read = getattr(bus, "sync_read", None)
    if not callable(sync_read):
        return None
    try:
        present = sync_read("Present_Position")
    except Exception:
        return None
    if not isinstance(present, dict):
        return None
    try:
        return float(present["shoulder_lift"])
    except Exception:
        return None


def _limit_shoulder_lift_backstop(robot: Any, action: Any) -> Any:
    if str(os.environ.get("ATR_LEROBOT_SHOULDER_LIFT_BACKSTOP", "1")).strip().lower() in _FALSE_VALUES:
        return action
    if not isinstance(action, dict) or _SHOULDER_LIFT_KEY not in action:
        return action
    backstop = getattr(robot, _SHOULDER_LIFT_BACKSTOP_ATTR, None)
    if backstop is None:
        backstop = _read_shoulder_lift_position(robot)
        if backstop is None:
            return action
        setattr(robot, _SHOULDER_LIFT_BACKSTOP_ATTR, float(backstop))
    try:
        requested = float(action[_SHOULDER_LIFT_KEY])
    except Exception:
        return action
    if requested >= float(backstop):
        return action
    limited = dict(action)
    limited[_SHOULDER_LIFT_KEY] = float(backstop)
    return limited


def install_omx_follower_runtime_units_patch() -> bool:
    """Ensure future OmxFollower instances use the legacy mixed unit map."""
    try:
        from lerobot.motors import MotorNormMode
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
    except Exception as exc:
        print(f"ATR OMX runtime units patch disabled: could not import OmxFollower: {exc}", flush=True)
        return False

    if getattr(OmxFollower, _INSTALLED_ATTR, False):
        return True

    original_init = OmxFollower.__init__
    setattr(OmxFollower, _ORIGINAL_INIT_ATTR, original_init)

    def __init_with_legacy_runtime_units__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        apply_omx_follower_runtime_units(self, MotorNormMode)

    OmxFollower.__init__ = __init_with_legacy_runtime_units__
    original_send_action = getattr(OmxFollower, "send_action", None)
    if callable(original_send_action):
        setattr(OmxFollower, _ORIGINAL_SEND_ATTR, original_send_action)

        def send_action_with_shoulder_lift_backstop(self: Any, action: Any, *args: Any, **kwargs: Any) -> Any:
            return original_send_action(self, _limit_shoulder_lift_backstop(self, action), *args, **kwargs)

        OmxFollower.send_action = send_action_with_shoulder_lift_backstop
    setattr(OmxFollower, _INSTALLED_ATTR, True)
    return True
