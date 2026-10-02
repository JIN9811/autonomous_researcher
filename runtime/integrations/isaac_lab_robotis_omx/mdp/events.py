"""Reset and randomization helpers for Robotis OMX Isaac Lab configs."""

from __future__ import annotations

import math
import os
from typing import Any

from ..domain_randomization import get_profile


def reset_red_cube_a4(env: Any, env_ids: Any, asset_cfg: Any) -> None:
    """Reset the red cube within the A4 workspace using the selected randomization profile."""
    try:
        import torch
        import isaaclab.utils.math as math_utils
    except ImportError:
        return

    cube = env.scene[asset_cfg.name]
    profile = get_profile(selected_domain_randomization_profile(env))
    xy_lo, xy_hi = profile["cube_xy_m"]
    yaw_lo, yaw_hi = profile["cube_yaw_rad"]
    root_state = cube.data.default_root_state[env_ids].clone()
    env_count = int(len(env_ids))
    reset_xyz = _env_float_vector("ROBOTIS_OMX_CUBE_RESET_XYZ", 3)
    reset_yaw = _env_float("ROBOTIS_OMX_CUBE_RESET_YAW")
    if reset_xyz is not None:
        root_state[:, 0] = float(reset_xyz[0])
        root_state[:, 1] = float(reset_xyz[1])
        root_state[:, 2] = float(reset_xyz[2])
        xy_lo, xy_hi = 0.0, 0.0
    root_state[:, 0] += torch.empty(env_count, device=env.device).uniform_(xy_lo, xy_hi)
    root_state[:, 1] += torch.empty(env_count, device=env.device).uniform_(xy_lo, xy_hi)
    if reset_yaw is not None:
        yaw = torch.full((env_count,), float(reset_yaw), device=env.device)
    else:
        yaw = torch.empty(env_count, device=env.device).uniform_(yaw_lo, yaw_hi)
    quat = math_utils.quat_from_euler_xyz(torch.zeros_like(yaw), torch.zeros_like(yaw), yaw)
    root_state[:, 3:7] = quat
    cube.write_root_pose_to_sim(root_state[:, :7], env_ids=env_ids)
    cube.write_root_velocity_to_sim(root_state[:, 7:], env_ids=env_ids)


def selected_domain_randomization_profile(env: Any) -> str:
    return str(getattr(getattr(env, "cfg", None), "domain_randomization_profile", "conservative"))


def _env_float_vector(name: str, count: int) -> list[float] | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        values = [float(item.strip()) for item in raw.split(",")]
    except ValueError:
        return None
    if len(values) != count or any(not math.isfinite(value) for value in values):
        return None
    return values


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None
