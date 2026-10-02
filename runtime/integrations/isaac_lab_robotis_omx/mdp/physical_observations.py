"""Geometry and contact based observations for the physical Robotis OMX Lab env."""

from __future__ import annotations

from typing import Any

import torch


APPROACH_DISTANCE_M = 0.065
GRASP_CONTACT_THRESHOLD_N = 0.2
LIFT_HEIGHT_M = 0.08
PLACE_TARGET_XY_M = (0.590, 0.078)
PLACE_TARGET_CUBE_CENTER_Z_M = 0.119
PLACE_RADIUS_M = 0.050
PLACE_MIN_HEIGHT_M = 0.095
PLACE_MAX_HEIGHT_M = 0.145
RELEASE_GRIPPER_OPEN_RAD = 0.05
RETRACT_CLEARANCE_M = 0.055


def _num_envs_and_device(env: Any) -> tuple[int, Any]:
    num_envs = int(getattr(env, "num_envs", 1) or 1)
    device = getattr(env, "device", "cpu")
    return max(1, num_envs), device


def _zeros(env: Any, width: int) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    return torch.zeros((num_envs, width), dtype=torch.float32, device=device)


def _sensor_tensor(value: Any) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        return value
    payload = getattr(value, "torch", None)
    if isinstance(payload, torch.Tensor):
        return payload
    return None


def joint_pos(env: Any) -> torch.Tensor:
    try:
        return env.scene["robot"].data.joint_pos
    except Exception:  # noqa: BLE001 - keeps import/unit tests independent of Kit.
        return _zeros(env, 7)


def joint_vel(env: Any) -> torch.Tensor:
    try:
        return env.scene["robot"].data.joint_vel
    except Exception:  # noqa: BLE001
        return _zeros(env, 7)


def gripper_state(env: Any) -> torch.Tensor:
    pos = joint_pos(env)
    if pos.shape[1] == 0:
        return _zeros(env, 1)
    return pos[:, -2:-1] if pos.shape[1] >= 2 else pos[:, -1:]


def cube_pos_w(env: Any) -> torch.Tensor:
    try:
        return env.scene["red_cube"].data.root_pos_w[:, :3]
    except Exception:  # noqa: BLE001
        return _zeros(env, 3)


def eef_pos(env: Any) -> torch.Tensor:
    override = getattr(env, "physical_eef_pos_w", None)
    if isinstance(override, torch.Tensor):
        return override.reshape(_num_envs_and_device(env)[0], 3)
    try:
        target_pos = env.scene["ee_frame"].data.target_pos_w
        if target_pos.ndim == 3:
            return target_pos[:, 0, :3]
        return target_pos[:, :3]
    except Exception:  # noqa: BLE001
        return _zeros(env, 3)


def eef_quat(env: Any) -> torch.Tensor:
    try:
        target_quat = env.scene["ee_frame"].data.target_quat_w
        if target_quat.ndim == 3:
            return target_quat[:, 0, :4]
        return target_quat[:, :4]
    except Exception:  # noqa: BLE001
        num_envs, device = _num_envs_and_device(env)
        quat = torch.zeros((num_envs, 4), dtype=torch.float32, device=device)
        quat[:, 0] = 1.0
        return quat


def eef_pose(env: Any) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    pose = torch.eye(4, dtype=torch.float32, device=device).repeat(num_envs, 1, 1)
    pose[:, :3, 3] = eef_pos(env)
    try:
        import isaaclab.utils.math as math_utils

        pose[:, :3, :3] = math_utils.matrix_from_quat(eef_quat(env))
    except Exception:  # noqa: BLE001
        pass
    return pose


def object_pose(env: Any) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    pose = torch.eye(4, dtype=torch.float32, device=device).repeat(num_envs, 1, 1)
    pose[:, :3, 3] = cube_pos_w(env)
    return pose


def approach(env: Any) -> torch.Tensor:
    distance = torch.linalg.norm(eef_pos(env) - cube_pos_w(env), dim=1)
    return (distance <= APPROACH_DISTANCE_M).reshape(-1, 1)


def grasp(env: Any) -> torch.Tensor:
    left = contact_force(env, "left_finger:red_cube")
    right = contact_force(env, "right_finger:red_cube")
    return ((left >= GRASP_CONTACT_THRESHOLD_N) & (right >= GRASP_CONTACT_THRESHOLD_N)).reshape(-1, 1)


def lift(env: Any) -> torch.Tensor:
    return (cube_pos_w(env)[:, 2] >= LIFT_HEIGHT_M).reshape(-1, 1)


def cube_lifted(env: Any) -> torch.Tensor:
    return lift(env)


def place(env: Any) -> torch.Tensor:
    pos = cube_pos_w(env)
    target_xy = torch.tensor(PLACE_TARGET_XY_M, dtype=pos.dtype, device=pos.device).reshape(1, 2)
    xy_ok = torch.linalg.norm(pos[:, :2] - target_xy, dim=1) <= PLACE_RADIUS_M
    z_ok = (pos[:, 2] >= PLACE_MIN_HEIGHT_M) & (pos[:, 2] <= PLACE_MAX_HEIGHT_M)
    return (xy_ok & z_ok).reshape(-1, 1)


def release(env: Any) -> torch.Tensor:
    gripper = gripper_state(env).reshape(-1)
    return (place(env).reshape(-1) & (gripper >= RELEASE_GRIPPER_OPEN_RAD)).reshape(-1, 1)


def released_at_target(env: Any) -> torch.Tensor:
    return release(env)


def retract(env: Any) -> torch.Tensor:
    clearance = eef_pos(env)[:, 2] - cube_pos_w(env)[:, 2]
    return (release(env).reshape(-1) & (clearance >= RETRACT_CLEARANCE_M)).reshape(-1, 1)


def contact_force(env: Any, pair: str) -> torch.Tensor:
    state = getattr(env, "physical_contact_state", None)
    if isinstance(state, dict) and pair in state:
        value = torch.as_tensor(state[pair], dtype=torch.float32, device=getattr(env, "device", None))
        return value.reshape(_num_envs_and_device(env)[0])
    sensor_name = "left_finger_contact" if pair.startswith("left_") else "right_finger_contact"
    try:
        data = env.scene[sensor_name].data
        force_matrix = _sensor_tensor(getattr(data, "force_matrix_w", None))
        if isinstance(force_matrix, torch.Tensor):
            return torch.linalg.norm(force_matrix.reshape(force_matrix.shape[0], -1, 3), dim=-1).amax(dim=1)
        net_forces = _sensor_tensor(getattr(data, "net_forces_w", None))
        if isinstance(net_forces, torch.Tensor):
            return torch.linalg.norm(net_forces.reshape(net_forces.shape[0], -1, 3), dim=-1).amax(dim=1)
    except Exception:  # noqa: BLE001
        pass
    num_envs, device = _num_envs_and_device(env)
    return torch.zeros(num_envs, dtype=torch.float32, device=device)
