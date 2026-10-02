"""Termination helpers for Robotis OMX Isaac Lab configs."""

from __future__ import annotations

from typing import Any

import torch


def _num_envs_and_device(env: Any) -> tuple[int, Any]:
    num_envs = int(getattr(env, "num_envs", 1) or 1)
    device = getattr(env, "device", "cpu")
    return max(1, num_envs), device


def task_success(env: Any) -> torch.Tensor:
    obs_buf = getattr(env, "obs_buf", {})
    if isinstance(obs_buf, dict):
        terms = obs_buf.get("subtask_terms", {})
        if isinstance(terms, dict) and "place" in terms:
            return torch.as_tensor(terms["place"], dtype=torch.bool, device=getattr(env, "device", None)).reshape(-1)
    num_envs, device = _num_envs_and_device(env)
    return torch.zeros(num_envs, dtype=torch.bool, device=device)


def object_grasped(env: Any) -> bool:
    return bool(getattr(env, "object_grasped", False))


def object_lifted(env: Any) -> bool:
    return bool(getattr(env, "object_lifted", False))


def object_placed(env: Any) -> bool:
    return bool(getattr(env, "object_placed", False))
