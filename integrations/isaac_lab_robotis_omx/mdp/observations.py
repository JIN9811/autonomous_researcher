"""Observation helpers for Robotis OMX Isaac Lab configs."""

from __future__ import annotations

from typing import Any

import torch


def _num_envs_and_device(env: Any) -> tuple[int, Any]:
    num_envs = int(getattr(env, "num_envs", 1) or 1)
    device = getattr(env, "device", "cpu")
    return max(1, num_envs), device


def _zeros(env: Any, width: int) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    return torch.zeros((num_envs, width), dtype=torch.float32, device=device)


def policy_observation_keys() -> tuple[str, ...]:
    return ("joint_pos", "joint_vel", "gripper_state", "eef_pos", "eef_quat", "eef_pose", "object_pose")


def get_policy_obs(obs_buf: dict[str, Any], key: str) -> Any:
    return obs_buf["policy"][key]


def joint_pos(env: Any) -> torch.Tensor:
    try:
        return env.scene["robot"].data.joint_pos
    except Exception:  # noqa: BLE001 - smoke fallback for incomplete scene wiring.
        return _zeros(env, 6)


def joint_vel(env: Any) -> torch.Tensor:
    try:
        return env.scene["robot"].data.joint_vel
    except Exception:  # noqa: BLE001
        return _zeros(env, 6)


def gripper_state(env: Any) -> torch.Tensor:
    return _zeros(env, 1)


def eef_pos(env: Any) -> torch.Tensor:
    return _zeros(env, 3)


def eef_quat(env: Any) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    quat = torch.zeros((num_envs, 4), dtype=torch.float32, device=device)
    quat[:, 0] = 1.0
    return quat


def eef_pose(env: Any) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    return torch.eye(4, dtype=torch.float32, device=device).repeat(num_envs, 1, 1)


def object_pose(env: Any) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    pose = torch.eye(4, dtype=torch.float32, device=device).repeat(num_envs, 1, 1)
    try:
        pose[:, :3, 3] = env.scene["red_cube"].data.root_pos_w[:, :3]
    except Exception:  # noqa: BLE001
        pass
    return pose


def approach(env: Any) -> torch.Tensor:
    return _step_signal(env, minimum_step=20)


def grasp(env: Any) -> torch.Tensor:
    return _step_signal(env, minimum_step=50)


def lift(env: Any) -> torch.Tensor:
    return _step_signal(env, minimum_step=90)


def place(env: Any) -> torch.Tensor:
    return _step_signal(env, minimum_step=130)


def _step_signal(env: Any, *, minimum_step: int) -> torch.Tensor:
    num_envs, device = _num_envs_and_device(env)
    steps = getattr(env, "episode_length_buf", None)
    if isinstance(steps, torch.Tensor):
        return (steps.to(device=device) >= int(minimum_step)).reshape(num_envs, 1)
    return torch.ones((num_envs, 1), dtype=torch.bool, device=device)
