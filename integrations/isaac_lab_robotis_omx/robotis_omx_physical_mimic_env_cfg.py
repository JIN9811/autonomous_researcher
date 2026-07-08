"""Mimic config for the physical Robotis OMX pick/place Isaac Lab task."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import SimpleNamespace

try:
    from isaaclab.envs import mdp
    from isaaclab.envs.mimic_env_cfg import MimicEnvCfg, SubTaskConfig
    from isaaclab.utils.configclass import configclass
except ImportError:
    mdp = None  # type: ignore[assignment]
    MimicEnvCfg = object  # type: ignore[assignment]

    def configclass(cls):
        return dataclass(cls)

    @dataclass
    class SubTaskConfig:
        object_ref: str
        subtask_term_signal: str | None
        subtask_term_offset_range: tuple[int, int]
        selection_strategy: str
        selection_strategy_kwargs: dict[str, int]
        action_noise: float
        num_interpolation_steps: int
        num_fixed_steps: int
        apply_noise_during_interpolation: bool
        description: str = ""
        next_subtask_description: str = ""

from .mdp import actions as robotis_actions
from .mdp import physical_observations
from .robotis_omx_physical_env_cfg import (
    ROBOTIS_OMX_ARM_JOINT_NAMES,
    ROBOTIS_OMX_EEF_BODY_NAME,
    ROBOTIS_OMX_JOINT_NAMES,
    RobotisOMXPhysicalPickPlaceEnvCfg,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


@configclass
class RobotisOMXPhysicalMimicActionsCfg:
    if mdp is not None:
        joint_position = robotis_actions.ContactLimitedJointPositionActionCfg(
            asset_name="robot",
            joint_names=list(ROBOTIS_OMX_JOINT_NAMES),
            scale=1.0,
            use_default_offset=False,
            preserve_order=True,
            contact_threshold_n=physical_observations.GRASP_CONTACT_THRESHOLD_N,
        )
    else:
        control_mode: str = "joint_position_physical_articulation"
        joint_names: tuple[str, ...] = ROBOTIS_OMX_JOINT_NAMES
        action_dim: int = len(ROBOTIS_OMX_JOINT_NAMES)


@configclass
class RobotisOMXPhysicalPickPlaceMimicEnvCfg(RobotisOMXPhysicalPickPlaceEnvCfg, MimicEnvCfg):
    """Mimic config backed by the physical articulation/contact Robotis OMX env."""

    actions: RobotisOMXPhysicalMimicActionsCfg = field(default_factory=RobotisOMXPhysicalMimicActionsCfg)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.action_contract = {
            "control_mode": "joint_position_physical_articulation",
            "joint_names": list(ROBOTIS_OMX_JOINT_NAMES),
            "arm_joint_names": list(ROBOTIS_OMX_ARM_JOINT_NAMES),
            "action_dim": len(ROBOTIS_OMX_JOINT_NAMES),
            "retarget_mode": "differential_ik",
            "eef_body_name": ROBOTIS_OMX_EEF_BODY_NAME,
            "ik_damping": 0.03,
            "ik_position_gain": 0.8,
            "ik_max_delta_rad": 0.08,
            "gripper_contact_hold": {
                "enabled": True,
                "required_sides": ["left", "right"],
                "threshold_n": physical_observations.GRASP_CONTACT_THRESHOLD_N,
                "overtravel_rad": robotis_actions.DEFAULT_GRIPPER_CONTACT_HOLD_OVERTRAVEL_RAD,
                "release_margin_rad": robotis_actions.DEFAULT_GRIPPER_CONTACT_RELEASE_MARGIN_RAD,
                "gripper_joint": "Gripper",
                "mimic_joint": "Gripper_mimic",
            },
        }
        if not hasattr(self, "datagen_config"):
            self.datagen_config = SimpleNamespace()
        self.datagen_config.name = "robotis_omx_physical_pickplace"
        self.datagen_config.generation_guarantee = _env_bool("ROBOTIS_OMX_MIMIC_GENERATION_GUARANTEE", True)
        self.datagen_config.generation_keep_failed = _env_bool("ROBOTIS_OMX_MIMIC_KEEP_FAILED", False)
        self.datagen_config.generation_num_trials = 20
        self.datagen_config.generation_select_src_per_subtask = False
        self.datagen_config.generation_transform_first_robot_pose = False
        self.datagen_config.generation_interpolate_from_last_target_pose = True
        self.datagen_config.max_num_failures = 50
        self.datagen_config.seed = 42
        self.subtask_configs["omx"] = [
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="cube_lifted",
                subtask_term_offset_range=(0, 0),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 1},
                action_noise=0.0,
                num_interpolation_steps=4,
                num_fixed_steps=1,
                apply_noise_during_interpolation=False,
                description="Approach, grasp, and lift red cube using the successful physical replay contact rule",
                next_subtask_description="Move to the right cylinder top and release",
            ),
            SubTaskConfig(
                object_ref="place_target",
                subtask_term_signal="released_at_target",
                subtask_term_offset_range=(0, 0),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 1},
                action_noise=0.0,
                num_interpolation_steps=5,
                num_fixed_steps=2,
                apply_noise_during_interpolation=False,
                description="Place red cube on the right cylinder top and release gripper",
                next_subtask_description="Retract from the cylinder target",
            ),
            SubTaskConfig(
                object_ref="place_target",
                subtask_term_signal=None,
                subtask_term_offset_range=(0, 0),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 1},
                action_noise=0.0,
                num_interpolation_steps=2,
                num_fixed_steps=3,
                apply_noise_during_interpolation=False,
                description="Retract and hold after successful cylinder placement",
            ),
        ]
