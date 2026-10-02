"""Action terms for the Robotis OMX Isaac Lab sidecar."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

try:
    import torch
    from isaaclab.envs.mdp.actions.actions_cfg import JointPositionActionCfg
    from isaaclab.envs.mdp.actions.joint_actions import JointPositionAction
    from isaaclab.managers import ActionTerm, ActionTermCfg
    from isaaclab.utils.configclass import configclass
except ImportError:
    torch = None  # type: ignore[assignment]
    ActionTerm = object  # type: ignore[assignment]
    ActionTermCfg = object  # type: ignore[assignment]
    JointPositionAction = object  # type: ignore[assignment]
    JointPositionActionCfg = object  # type: ignore[assignment]

    def configclass(cls):
        return dataclass(cls)


DEFAULT_GRIPPER_CONTACT_HOLD_THRESHOLD_N = 0.2
DEFAULT_GRIPPER_CONTACT_HOLD_OVERTRAVEL_RAD = math.radians(1.0)
DEFAULT_GRIPPER_CONTACT_RELEASE_MARGIN_RAD = math.radians(1.0)
DEFAULT_GRIPPER_MIN_RAD = 0.0


def _finite_or_nan_like(value: Any, reference: Any):
    if torch is None:
        raise RuntimeError("torch is required for Robotis OMX contact-limited actions")
    tensor = torch.as_tensor(value, dtype=reference.dtype, device=reference.device)
    return tensor.reshape(reference.shape)


def _joint_index(joint_names: list[str] | tuple[str, ...], name: str) -> int | None:
    try:
        return list(joint_names).index(name)
    except ValueError:
        return None


def apply_contact_gripper_hold(
    processed_actions: Any,
    *,
    joint_names: list[str] | tuple[str, ...],
    previous_primary_target: Any,
    hold_target: Any,
    left_force_n: Any,
    right_force_n: Any,
    threshold_n: float = DEFAULT_GRIPPER_CONTACT_HOLD_THRESHOLD_N,
    overtravel_rad: float = DEFAULT_GRIPPER_CONTACT_HOLD_OVERTRAVEL_RAD,
    release_margin_rad: float = DEFAULT_GRIPPER_CONTACT_RELEASE_MARGIN_RAD,
    gripper_min_rad: float = DEFAULT_GRIPPER_MIN_RAD,
    gripper_joint_name: str = "Gripper",
    mimic_joint_name: str = "Gripper_mimic",
):
    """Clamp gripper targets after two-sided contact, matching the Sim mirror hold rule."""
    if torch is None:
        raise RuntimeError("torch is required for Robotis OMX contact-limited actions")
    adjusted = processed_actions.clone()
    primary_index = _joint_index(joint_names, gripper_joint_name)
    mimic_index = _joint_index(joint_names, mimic_joint_name)
    num_envs = adjusted.shape[0]
    diagnostics = {
        "enabled": primary_index is not None,
        "contact": [False] * num_envs,
        "clamped": [False] * num_envs,
        "hold_reason": ["missing_gripper_joint"] * num_envs,
    }
    if primary_index is None:
        return adjusted, _finite_or_nan_like(hold_target, adjusted[:, 0]), diagnostics

    primary = adjusted[:, primary_index]
    previous = _finite_or_nan_like(previous_primary_target, primary)
    next_hold = _finite_or_nan_like(hold_target, primary).clone()
    left = _finite_or_nan_like(left_force_n, primary)
    right = _finite_or_nan_like(right_force_n, primary)

    contact = (left >= float(threshold_n)) & (right >= float(threshold_n))
    has_hold = torch.isfinite(next_hold)
    release_opening = has_hold & (primary > next_hold + float(release_margin_rad))
    release_contact_lost = has_hold & ~contact
    released_this_tick = release_opening | release_contact_lost
    next_hold[released_this_tick] = torch.nan

    has_hold = torch.isfinite(next_hold)
    closing_or_unknown = (~torch.isfinite(previous)) | (primary <= previous)
    arm_hold = (~has_hold) & contact & closing_or_unknown & ~released_this_tick
    if torch.any(arm_hold):
        next_hold[arm_hold] = torch.clamp(primary[arm_hold] - float(overtravel_rad), min=float(gripper_min_rad))

    has_hold = torch.isfinite(next_hold)
    clamp = has_hold & (primary < next_hold)
    if torch.any(clamp):
        adjusted[clamp, primary_index] = next_hold[clamp]
        if mimic_index is not None:
            adjusted[clamp, mimic_index] = -next_hold[clamp]

    hold_reason: list[str] = []
    for env_id in range(num_envs):
        if bool(clamp[env_id]):
            hold_reason.append("contact_hold_clamped")
        elif bool(arm_hold[env_id]):
            hold_reason.append("contact_hold_armed")
        elif bool(release_opening[env_id]):
            hold_reason.append("released_opening")
        elif bool(release_contact_lost[env_id]):
            hold_reason.append("released_contact_lost")
        elif bool(has_hold[env_id]):
            hold_reason.append("contact_hold_tracking")
        elif bool(contact[env_id]):
            hold_reason.append("contact_no_closing")
        else:
            hold_reason.append("no_contact")

    diagnostics = {
        "enabled": True,
        "threshold_n": float(threshold_n),
        "overtravel_rad": float(overtravel_rad),
        "release_margin_rad": float(release_margin_rad),
        "contact": [bool(value) for value in contact.detach().cpu().tolist()],
        "clamped": [bool(value) for value in clamp.detach().cpu().tolist()],
        "hold_target": [float(value) for value in next_hold.detach().cpu().tolist()],
        "left_force_n": [float(value) for value in left.detach().cpu().tolist()],
        "right_force_n": [float(value) for value in right.detach().cpu().tolist()],
        "hold_reason": hold_reason,
    }
    return adjusted, next_hold, diagnostics


if torch is not None:

    class RobotisOMXDeltaPoseAction(ActionTerm):
        """Record a 7D end-effector delta-pose plus gripper action without actuating hardware."""

        def __init__(self, cfg: RobotisOMXDeltaPoseActionCfg, env: Any):
            super().__init__(cfg, env)
            width = max(1, int(cfg.action_dim))
            self._raw_actions = torch.zeros(env.num_envs, width, device=self.device)
            self._processed_actions = torch.zeros(env.num_envs, width, device=self.device)

        @property
        def action_dim(self) -> int:
            return self._raw_actions.shape[1]

        @property
        def raw_actions(self) -> torch.Tensor:
            return self._raw_actions

        @property
        def processed_actions(self) -> torch.Tensor:
            return self._processed_actions

        def process_actions(self, actions: torch.Tensor) -> None:
            self._raw_actions[:] = actions
            self._processed_actions[:] = actions

        def apply_actions(self) -> None:
            # This sidecar term preserves the Lab/Mimic action contract without
            # moving real teleop or recording state.
            return None


    class ContactLimitedJointPositionAction(JointPositionAction):
        """Joint position action with the Sim mirror's two-sided gripper contact hold."""

        cfg: "ContactLimitedJointPositionActionCfg"

        def __init__(self, cfg: "ContactLimitedJointPositionActionCfg", env: Any):
            super().__init__(cfg, env)
            self._previous_gripper_primary_target = torch.full((self.num_envs,), torch.nan, device=self.device)
            self._gripper_contact_hold_target = torch.full((self.num_envs,), torch.nan, device=self.device)
            self._last_contact_hold_diagnostics: dict[str, Any] = {}

        def process_actions(self, actions: Any) -> None:
            super().process_actions(actions)
            try:
                from . import physical_observations

                left_force = physical_observations.contact_force(self._env, self.cfg.left_contact_pair)
                right_force = physical_observations.contact_force(self._env, self.cfg.right_contact_pair)
            except Exception:
                left_force = torch.zeros((self.num_envs,), dtype=self.processed_actions.dtype, device=self.device)
                right_force = torch.zeros((self.num_envs,), dtype=self.processed_actions.dtype, device=self.device)

            adjusted, next_hold, diagnostics = apply_contact_gripper_hold(
                self._processed_actions,
                joint_names=list(self._joint_names),
                previous_primary_target=self._previous_gripper_primary_target,
                hold_target=self._gripper_contact_hold_target,
                left_force_n=left_force,
                right_force_n=right_force,
                threshold_n=self.cfg.contact_threshold_n,
                overtravel_rad=self.cfg.hold_overtravel_rad,
                release_margin_rad=self.cfg.release_margin_rad,
                gripper_min_rad=self.cfg.gripper_min_rad,
                gripper_joint_name=self.cfg.gripper_joint_name,
                mimic_joint_name=self.cfg.mimic_joint_name,
            )
            self._processed_actions = adjusted
            self._gripper_contact_hold_target = next_hold
            primary_index = _joint_index(list(self._joint_names), self.cfg.gripper_joint_name)
            if primary_index is not None:
                self._previous_gripper_primary_target = self._processed_actions[:, primary_index].clone()
            self._last_contact_hold_diagnostics = diagnostics
            setattr(self._env, "physical_gripper_contact_hold_state", diagnostics)

        def reset(self, env_ids: Any = None) -> None:
            super().reset(env_ids)
            if env_ids is None:
                self._previous_gripper_primary_target[:] = torch.nan
                self._gripper_contact_hold_target[:] = torch.nan
            else:
                self._previous_gripper_primary_target[env_ids] = torch.nan
                self._gripper_contact_hold_target[env_ids] = torch.nan


@configclass
class RobotisOMXDeltaPoseActionCfg(ActionTermCfg):
    """Configuration for the Robotis OMX 7D delta-pose action contract."""

    if torch is not None:
        class_type: type = RobotisOMXDeltaPoseAction
    else:
        class_type: Any = None
        asset_name: str = "red_cube"
        debug_vis: bool = False
        clip: dict[str, tuple] | None = None

    action_dim: int = 7


@configclass
class ContactLimitedJointPositionActionCfg(JointPositionActionCfg):
    """Joint position action config with two-sided gripper contact hold enabled."""

    if torch is not None:
        class_type: type = ContactLimitedJointPositionAction
    else:
        class_type: Any = None
        asset_name: str = "robot"
        debug_vis: bool = False
        clip: dict[str, tuple] | None = None
        joint_names: list[str] | tuple[str, ...] = ()
        scale: float | dict[str, float] = 1.0
        offset: float | dict[str, float] = 0.0
        preserve_order: bool = False
        use_default_offset: bool = False

    gripper_joint_name: str = "Gripper"
    mimic_joint_name: str = "Gripper_mimic"
    left_contact_pair: str = "left_finger:red_cube"
    right_contact_pair: str = "right_finger:red_cube"
    contact_threshold_n: float = DEFAULT_GRIPPER_CONTACT_HOLD_THRESHOLD_N
    hold_overtravel_rad: float = DEFAULT_GRIPPER_CONTACT_HOLD_OVERTRAVEL_RAD
    release_margin_rad: float = DEFAULT_GRIPPER_CONTACT_RELEASE_MARGIN_RAD
    gripper_min_rad: float = DEFAULT_GRIPPER_MIN_RAD
