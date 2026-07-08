"""Physical task termination helpers for Robotis OMX pick/place."""

from __future__ import annotations

from typing import Any

import torch

from . import physical_observations


def task_success(env: Any) -> torch.Tensor:
    """Return success when the red cube is actually at the place target."""
    placed = physical_observations.place(env).reshape(-1)
    return torch.as_tensor(placed, dtype=torch.bool, device=getattr(env, "device", None))
