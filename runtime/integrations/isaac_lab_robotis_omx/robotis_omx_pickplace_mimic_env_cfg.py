"""Mimic config for the Robotis OMX pick/place Isaac Lab task."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

try:
    from isaaclab.envs.mimic_env_cfg import MimicEnvCfg, SubTaskConfig
    from isaaclab.utils.configclass import configclass
except ImportError:
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

from .robotis_omx_pickplace_env_cfg import RobotisOMXPickPlaceEnvCfg


@configclass
class RobotisOMXPickPlaceMimicEnvCfg(RobotisOMXPickPlaceEnvCfg, MimicEnvCfg):
    """Mimic config for Robotis OMX pick/place."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not hasattr(self, "datagen_config"):
            self.datagen_config = SimpleNamespace()
        self.datagen_config.name = "robotis_omx_pickplace"
        self.datagen_config.generation_guarantee = True
        self.datagen_config.generation_keep_failed = False
        self.datagen_config.generation_num_trials = 20
        self.datagen_config.generation_select_src_per_subtask = False
        self.datagen_config.generation_transform_first_robot_pose = False
        self.datagen_config.generation_interpolate_from_last_target_pose = True
        self.datagen_config.max_num_failures = 50
        self.datagen_config.seed = 42
        self.subtask_configs["omx"] = [
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="approach",
                subtask_term_offset_range=(0, 3),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=3,
                num_fixed_steps=0,
                apply_noise_during_interpolation=False,
                description="Move end effector near red cube",
                next_subtask_description="Close gripper on red cube",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="grasp",
                subtask_term_offset_range=(0, 5),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.002,
                num_interpolation_steps=2,
                num_fixed_steps=2,
                apply_noise_during_interpolation=False,
                description="Grasp red cube",
                next_subtask_description="Lift red cube",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="lift",
                subtask_term_offset_range=(0, 5),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=4,
                num_fixed_steps=1,
                apply_noise_during_interpolation=False,
                description="Lift red cube",
                next_subtask_description="Move to place target",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="place",
                subtask_term_offset_range=(0, 8),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=5,
                num_fixed_steps=2,
                apply_noise_during_interpolation=False,
                description="Place red cube at target",
                next_subtask_description="Release gripper",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal=None,
                subtask_term_offset_range=(0, 0),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.0,
                num_interpolation_steps=1,
                num_fixed_steps=3,
                apply_noise_during_interpolation=False,
                description="Release gripper and hold final state",
            ),
        ]
