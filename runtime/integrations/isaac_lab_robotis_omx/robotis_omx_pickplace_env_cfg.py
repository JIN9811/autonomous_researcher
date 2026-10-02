"""Minimal Robotis OMX pick/place env config entry points for Isaac Lab."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import SimpleNamespace

from .domain_randomization import event_ranges

try:
    import isaaclab.sim as sim_utils
    from isaaclab.assets import RigidObjectCfg
    from isaaclab.envs import ManagerBasedRLEnvCfg
    from isaaclab.envs import mdp
    from isaaclab.managers import EventTermCfg as EventTerm
    from isaaclab.managers import ObservationGroupCfg as ObsGroup
    from isaaclab.managers import ObservationTermCfg as ObsTerm
    from isaaclab.managers import SceneEntityCfg
    from isaaclab.managers import TerminationTermCfg as DoneTerm
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.utils.configclass import configclass
except ImportError:
    sim_utils = None  # type: ignore[assignment]
    RigidObjectCfg = None  # type: ignore[assignment]
    ManagerBasedRLEnvCfg = object  # type: ignore[assignment]
    mdp = None  # type: ignore[assignment]
    EventTerm = None  # type: ignore[assignment]
    ObsGroup = object  # type: ignore[assignment]
    ObsTerm = None  # type: ignore[assignment]
    SceneEntityCfg = None  # type: ignore[assignment]
    DoneTerm = None  # type: ignore[assignment]
    InteractiveSceneCfg = object  # type: ignore[assignment]

    def configclass(cls):
        return dataclass(cls)


if ObsTerm is not None:
    from .mdp import actions as robotis_actions
    from .mdp import observations as robotis_observations
else:
    robotis_actions = None  # type: ignore[assignment]
    robotis_observations = None  # type: ignore[assignment]


@configclass
class RobotisOMXSceneCfg(InteractiveSceneCfg):
    num_envs: int = 1
    env_spacing: float = 2.0

    if RigidObjectCfg is not None and sim_utils is not None:
        red_cube = RigidObjectCfg(
            prim_path="{ENV_REGEX_NS}/red_cube",
            init_state=RigidObjectCfg.InitialStateCfg(pos=[0.4, 0.0, 0.025], rot=[0.0, 0.0, 0.0, 1.0]),
            spawn=sim_utils.CuboidCfg(
                size=(0.05, 0.05, 0.05),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    solver_position_iteration_count=16,
                    solver_velocity_iteration_count=1,
                    max_angular_velocity=1000.0,
                    max_linear_velocity=1000.0,
                    max_depenetration_velocity=5.0,
                    disable_gravity=False,
                ),
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.005, rest_offset=0.0),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.05),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=0.8,
                    dynamic_friction=0.6,
                    restitution=0.0,
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(1.0, 0.0, 0.0)),
            ),
        )


@configclass
class RobotisOMXObservationsCfg:
    if ObsTerm is not None:
        @configclass
        class PolicyCfg(ObsGroup):
            joint_pos = ObsTerm(func=robotis_observations.joint_pos)
            joint_vel = ObsTerm(func=robotis_observations.joint_vel)
            gripper_state = ObsTerm(func=robotis_observations.gripper_state)
            eef_pos = ObsTerm(func=robotis_observations.eef_pos)
            eef_quat = ObsTerm(func=robotis_observations.eef_quat)
            eef_pose = ObsTerm(func=robotis_observations.eef_pose)
            object_pose = ObsTerm(func=robotis_observations.object_pose)

            def __post_init__(self) -> None:
                self.enable_corruption = False
                self.concatenate_terms = False

        @configclass
        class SubtaskTermsCfg(ObsGroup):
            approach = ObsTerm(func=robotis_observations.approach)
            grasp = ObsTerm(func=robotis_observations.grasp)
            lift = ObsTerm(func=robotis_observations.lift)
            place = ObsTerm(func=robotis_observations.place)

            def __post_init__(self) -> None:
                self.enable_corruption = False
                self.concatenate_terms = False

        policy: PolicyCfg = field(default_factory=PolicyCfg)
        subtask_terms: SubtaskTermsCfg = field(default_factory=SubtaskTermsCfg)
    else:
        policy: tuple[str, ...] = (
            "joint_pos",
            "joint_vel",
            "gripper_state",
            "eef_pos",
            "eef_quat",
            "eef_pose",
            "object_pose",
        )


@configclass
class RobotisOMXActionsCfg:
    if robotis_actions is not None:
        omx_action = robotis_actions.RobotisOMXDeltaPoseActionCfg(asset_name="red_cube", action_dim=7)
    else:
        control_mode: str = "eef_delta_pose_plus_gripper"
        action_dim: int = 7


@configclass
class RobotisOMXEventsCfg:
    pass


if EventTerm is not None and SceneEntityCfg is not None and mdp is not None:
    from .mdp import events as robotis_events

    RobotisOMXEventsCfg.reset_base_scene = EventTerm(func=mdp.reset_scene_to_default, mode="reset")
    RobotisOMXEventsCfg.reset_cube_pose = EventTerm(
        func=robotis_events.reset_red_cube_a4,
        mode="reset",
        params={"asset_cfg": SceneEntityCfg("red_cube")},
    )
    RobotisOMXEventsCfg.cube_material = EventTerm(
        func=mdp.randomize_rigid_body_material,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "static_friction_range": (0.8, 1.1),
            "dynamic_friction_range": (0.6, 0.9),
            "restitution_range": (0.0, 0.02),
            "num_buckets": 16,
        },
    )
    RobotisOMXEventsCfg.cube_mass = EventTerm(
        func=mdp.randomize_rigid_body_mass,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "mass_distribution_params": (0.9, 1.1),
            "operation": "scale",
            "distribution": "uniform",
        },
    )
    RobotisOMXEventsCfg.cube_collider_offsets = EventTerm(
        func=mdp.randomize_rigid_body_collider_offsets,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "rest_offset_distribution_params": (0.0, 0.001),
            "contact_offset_distribution_params": (0.003, 0.006),
            "distribution": "uniform",
        },
    )


@configclass
class RobotisOMXTerminationsCfg:
    pass


if DoneTerm is not None:
    from .mdp import terminations as robotis_terminations

    RobotisOMXTerminationsCfg.success = DoneTerm(func=robotis_terminations.task_success)


@configclass
class RobotisOMXRewardsCfg:
    pass


@configclass
class RobotisOMXPickPlaceEnvCfg(ManagerBasedRLEnvCfg):
    decimation: int = 1
    episode_length_s: float = 10.0
    scene: RobotisOMXSceneCfg = field(default_factory=RobotisOMXSceneCfg)
    observations: RobotisOMXObservationsCfg = field(default_factory=RobotisOMXObservationsCfg)
    actions: RobotisOMXActionsCfg = field(default_factory=RobotisOMXActionsCfg)
    rewards: RobotisOMXRewardsCfg = field(default_factory=RobotisOMXRewardsCfg)
    events: RobotisOMXEventsCfg = field(default_factory=RobotisOMXEventsCfg)
    terminations: RobotisOMXTerminationsCfg = field(default_factory=RobotisOMXTerminationsCfg)
    domain_randomization_profile: str = "conservative"

    def __post_init__(self) -> None:
        self.domain_randomization_profile = os.environ.get(
            "ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE",
            self.domain_randomization_profile,
        )
        ranges = event_ranges(self.domain_randomization_profile)
        if hasattr(self.events, "cube_material"):
            self.events.cube_material.params["static_friction_range"] = ranges["cube_static_friction_range"]
            self.events.cube_material.params["dynamic_friction_range"] = ranges["cube_dynamic_friction_range"]
        if hasattr(self.events, "cube_mass"):
            self.events.cube_mass.params["mass_distribution_params"] = ranges["cube_mass_scale_range"]
        if hasattr(self.events, "cube_collider_offsets"):
            self.events.cube_collider_offsets.params["rest_offset_distribution_params"] = ranges["cube_rest_offset_range"]
            self.events.cube_collider_offsets.params["contact_offset_distribution_params"] = ranges["cube_contact_offset_range"]
        if not hasattr(self, "subtask_configs"):
            self.subtask_configs = {}
        if not hasattr(self, "datagen_config"):
            self.datagen_config = SimpleNamespace()
