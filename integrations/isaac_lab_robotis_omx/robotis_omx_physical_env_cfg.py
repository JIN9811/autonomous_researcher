"""Physical Robotis OMX pick/place env config for Isaac Lab."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .domain_randomization import event_ranges


REPO_ROOT = Path(__file__).resolve().parents[2]
ROBOTIS_OMX_USD_PATH = str((REPO_ROOT / "sim" / "robotis_omx" / "omx" / "omx.usda").resolve())
ROBOTIS_OMX_STAGE_PATH = str((REPO_ROOT / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda").resolve())
ROBOTIS_OMX_JOINT_NAMES = ("Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic")
ROBOTIS_OMX_ARM_JOINT_NAMES = ("Joint1", "Joint2", "Joint3", "Joint4", "Joint5")
ROBOTIS_OMX_GRIPPER_JOINT_NAMES = ("Gripper", "Gripper_mimic")
ROBOTIS_OMX_EEF_BODY_NAME = "link5"
ROBOTIS_OMX_EEF_PRIM_PATH = "{ENV_REGEX_NS}/Robot/Geometry/link0/link1/link2/link3/link4/link5"
ROBOTIS_OMX_LEFT_FINGER_PRIM_PATH = "{ENV_REGEX_NS}/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6"
ROBOTIS_OMX_RIGHT_FINGER_PRIM_PATH = "{ENV_REGEX_NS}/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7"
ROBOTIS_OMX_CONTACT_REPORTER_PRIM_PATHS = (
    "Geometry/link0/link1/link2/link3/link4/link5/link6",
    "Geometry/link0/link1/link2/link3/link4/link5/link7",
)
ROBOTIS_OMX_SPAWN_FUNC = (
    "integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg:spawn_robotis_omx_usd_with_contact_reporters"
)
ROBOTIS_OMX_CAMERA_NAMES = ("top", "front", "right")
ROBOTIS_OMX_DEPTH_SCALE_M_PER_UNIT = 0.001
ROBOTIS_OMX_DEFAULT_CAMERA_WIDTH = 640
ROBOTIS_OMX_DEFAULT_CAMERA_HEIGHT = 480
ROBOTIS_OMX_STAGE_ROBOT_PRIM_PATH = "/World/Robot"
ROBOTIS_OMX_STAGE_RED_CUBE_PRIM_PATH = "/World/Workspace/RedSpecimenBlock"
ROBOTIS_OMX_STAGE_STATIC_PRIM_NAMES = (
    "TableTop",
    "TableTopFrontLeft",
    "TableTopFrontRight",
    "RobotBasePocketFloor",
    "A4Sheet",
    "A4CornerMarker_1",
    "A4CornerMarker_2",
    "A4CornerMarker_3",
    "A4CornerMarker_4",
    "A4CenterMarker",
    "RightDiskAluminumTop",
    "RightDiskBlackBase",
    "RightDiskCenterYellowMarker",
)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, min(maximum, value))


def _camera_mode_enabled() -> bool:
    value = os.environ.get("ROBOTIS_OMX_CAMERA_MODE", "rgbd").strip().lower()
    return value not in {"0", "false", "none", "off", "disabled"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "none", "off", "disabled", "no"}


try:
    import isaaclab.sim as sim_utils
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
    from isaaclab.envs import ManagerBasedRLEnvCfg
    from isaaclab.envs.common import ViewerCfg
    from isaaclab.envs import mdp
    from isaaclab.managers import EventTermCfg as EventTerm
    from isaaclab.managers import ObservationGroupCfg as ObsGroup
    from isaaclab.managers import ObservationTermCfg as ObsTerm
    from isaaclab.managers import SceneEntityCfg
    from isaaclab.managers import TerminationTermCfg as DoneTerm
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.sensors import CameraCfg, ContactSensorCfg, FrameTransformerCfg
    from isaaclab.sensors.frame_transformer.frame_transformer_cfg import OffsetCfg
    from isaaclab.sim.schemas import schemas as sim_schemas
    from isaaclab.sim.spawners.from_files.from_files import _spawn_from_usd_file
    from isaaclab.sim.utils import clone
    from isaaclab.utils.configclass import configclass
except ImportError:
    sim_utils = None  # type: ignore[assignment]
    ImplicitActuatorCfg = None  # type: ignore[assignment]
    ArticulationCfg = None  # type: ignore[assignment]
    AssetBaseCfg = None  # type: ignore[assignment]
    RigidObjectCfg = None  # type: ignore[assignment]
    ManagerBasedRLEnvCfg = object  # type: ignore[assignment]
    ViewerCfg = None  # type: ignore[assignment]
    mdp = None  # type: ignore[assignment]
    EventTerm = None  # type: ignore[assignment]
    ObsGroup = object  # type: ignore[assignment]
    ObsTerm = None  # type: ignore[assignment]
    SceneEntityCfg = None  # type: ignore[assignment]
    DoneTerm = None  # type: ignore[assignment]
    InteractiveSceneCfg = object  # type: ignore[assignment]
    CameraCfg = None  # type: ignore[assignment]
    ContactSensorCfg = None  # type: ignore[assignment]
    FrameTransformerCfg = None  # type: ignore[assignment]
    OffsetCfg = None  # type: ignore[assignment]
    sim_schemas = None  # type: ignore[assignment]
    _spawn_from_usd_file = None  # type: ignore[assignment]
    clone = None  # type: ignore[assignment]

    def configclass(cls):
        return dataclass(cls)


from .mdp import actions as robotis_actions
from .mdp import events as robotis_events
from .mdp import physical_observations, physical_terminations


if clone is not None and _spawn_from_usd_file is not None and sim_schemas is not None:

    @clone
    def spawn_robotis_omx_usd_with_contact_reporters(
        prim_path: str,
        cfg,
        translation: tuple[float, float, float] | None = None,
        orientation: tuple[float, float, float, float] | None = None,
        **kwargs,
    ):
        prim = _spawn_from_usd_file(prim_path, cfg.usd_path, cfg, translation, orientation, **kwargs)
        for relative_path in ROBOTIS_OMX_CONTACT_REPORTER_PRIM_PATHS:
            sim_schemas.activate_contact_sensors(f"{prim_path}/{relative_path}")
        return prim

else:

    def spawn_robotis_omx_usd_with_contact_reporters(*args, **kwargs):
        raise RuntimeError("Isaac Lab is required to spawn Robotis OMX contact reporters.")


if AssetBaseCfg is not None and sim_utils is not None:

    def _stage_cuboid_asset(
        prim_path: str,
        *,
        size: tuple[float, float, float],
        pos: tuple[float, float, float],
        diffuse_color: tuple[float, float, float],
        static_friction: float,
        dynamic_friction: float,
        contact_offset: float = 0.003,
    ):
        return AssetBaseCfg(
            prim_path=prim_path,
            spawn=sim_utils.CuboidCfg(
                size=size,
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=contact_offset, rest_offset=0.0),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=static_friction,
                    dynamic_friction=dynamic_friction,
                    restitution=0.0,
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=diffuse_color),
            ),
            init_state=AssetBaseCfg.InitialStateCfg(pos=pos),
        )

    def _stage_marker_cylinder_asset(
        prim_path: str,
        *,
        radius: float,
        height: float,
        pos: tuple[float, float, float],
        diffuse_color: tuple[float, float, float],
    ):
        return AssetBaseCfg(
            prim_path=prim_path,
            spawn=sim_utils.CylinderCfg(
                radius=radius,
                height=height,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=diffuse_color),
            ),
            init_state=AssetBaseCfg.InitialStateCfg(pos=pos),
        )

    def _stage_collision_cylinder_asset(
        prim_path: str,
        *,
        radius: float,
        height: float,
        pos: tuple[float, float, float],
        diffuse_color: tuple[float, float, float],
        static_friction: float,
        dynamic_friction: float,
        contact_offset: float = 0.003,
    ):
        return AssetBaseCfg(
            prim_path=prim_path,
            spawn=sim_utils.CylinderCfg(
                radius=radius,
                height=height,
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=contact_offset, rest_offset=0.0),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=static_friction,
                    dynamic_friction=dynamic_friction,
                    restitution=0.0,
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=diffuse_color),
            ),
            init_state=AssetBaseCfg.InitialStateCfg(pos=pos),
        )


@configclass
class RobotisOMXPhysicalSceneCfg(InteractiveSceneCfg):
    num_envs: int = 1
    env_spacing: float = 2.0

    if ArticulationCfg is not None and sim_utils is not None and ImplicitActuatorCfg is not None:
        robot = ArticulationCfg(
            prim_path="{ENV_REGEX_NS}/Robot",
            spawn=sim_utils.UsdFileCfg(
                func=ROBOTIS_OMX_SPAWN_FUNC,
                usd_path=ROBOTIS_OMX_USD_PATH,
                activate_contact_sensors=True,
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    disable_gravity=False,
                    max_depenetration_velocity=0.2,
                    max_linear_velocity=1000.0,
                    max_angular_velocity=1000.0,
                    solver_position_iteration_count=64,
                    solver_velocity_iteration_count=4,
                    enable_gyroscopic_forces=True,
                ),
                articulation_props=sim_utils.ArticulationRootPropertiesCfg(
                    enabled_self_collisions=False,
                    solver_position_iteration_count=64,
                    solver_velocity_iteration_count=4,
                ),
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.003, rest_offset=0.0),
                semantic_tags=[("class", "robotis_omx")],
            ),
            init_state=ArticulationCfg.InitialStateCfg(
                pos=(0.315, 0.06, -0.02),
                rot=(0.0, 0.0, 0.7071068, 0.7071068),
                joint_pos={
                    "Joint1": 0.0,
                    "Joint2": 0.0,
                    "Joint3": 0.0,
                    "Joint4": 0.0,
                    "Joint5": 0.0,
                    "Gripper": 0.0,
                    "Gripper_mimic": 0.0,
                },
            ),
            actuators={
                "omx_arm": ImplicitActuatorCfg(
                    joint_names_expr=list(ROBOTIS_OMX_ARM_JOINT_NAMES),
                    effort_limit=1.5,
                    velocity_limit=8.0,
                    stiffness=450.0,
                    damping=60.0,
                    friction=0.1,
                    armature=0.1,
                ),
                "omx_gripper": ImplicitActuatorCfg(
                    joint_names_expr=list(ROBOTIS_OMX_GRIPPER_JOINT_NAMES),
                    effort_limit=4.0,
                    velocity_limit=10.0,
                    stiffness=180.0,
                    damping=18.0,
                    friction=0.1,
                    armature=0.1,
                ),
            },
        )

    if RigidObjectCfg is not None and sim_utils is not None:
        red_cube = RigidObjectCfg(
            prim_path="{ENV_REGEX_NS}/red_cube",
            init_state=RigidObjectCfg.InitialStateCfg(pos=[0.40, 0.30, 0.0152], rot=[0.0, 0.0, 0.0, 1.0]),
            spawn=sim_utils.CuboidCfg(
                size=(0.03, 0.03, 0.03),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    solver_position_iteration_count=32,
                    solver_velocity_iteration_count=4,
                    max_depenetration_velocity=0.2,
                    max_angular_velocity=1000.0,
                    max_linear_velocity=1000.0,
                    disable_gravity=False,
                    enable_gyroscopic_forces=True,
                ),
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.003, rest_offset=0.0),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.03),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=1.0,
                    dynamic_friction=0.8,
                    restitution=0.0,
                    compliant_contact_stiffness=100000.0,
                    compliant_contact_damping=1000.0,
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.86, 0.05, 0.04)),
                semantic_tags=[("class", "red_cube")],
            ),
        )

    if AssetBaseCfg is not None and sim_utils is not None:
        table_top = _stage_cuboid_asset(
            "{ENV_REGEX_NS}/Table/TableTop",
            size=(0.7, 0.33, 0.03),
            pos=(0.35, 0.285, -0.015),
            diffuse_color=(0.42, 0.095, 0.04),
            static_friction=0.45,
            dynamic_friction=0.35,
        )
        table_top_front_left = _stage_cuboid_asset(
            "{ENV_REGEX_NS}/Table/TableTopFrontLeft",
            size=(0.24, 0.12, 0.03),
            pos=(0.12, 0.06, -0.015),
            diffuse_color=(0.42, 0.095, 0.04),
            static_friction=0.45,
            dynamic_friction=0.35,
        )
        table_top_front_right = _stage_cuboid_asset(
            "{ENV_REGEX_NS}/Table/TableTopFrontRight",
            size=(0.31, 0.12, 0.03),
            pos=(0.545, 0.06, -0.015),
            diffuse_color=(0.42, 0.095, 0.04),
            static_friction=0.45,
            dynamic_friction=0.35,
        )
        robot_base_pocket_floor = _stage_cuboid_asset(
            "{ENV_REGEX_NS}/Table/RobotBasePocketFloor",
            size=(0.15, 0.12, 0.004),
            pos=(0.315, 0.06, -0.022),
            diffuse_color=(0.2, 0.045, 0.022),
            static_friction=0.45,
            dynamic_friction=0.35,
        )
        a4_sheet = _stage_cuboid_asset(
            "{ENV_REGEX_NS}/Workspace/A4Sheet",
            size=(0.297, 0.21, 0.00012),
            pos=(0.315, 0.265, 0.00006),
            diffuse_color=(0.93, 0.93, 0.9),
            static_friction=1.1,
            dynamic_friction=0.9,
            contact_offset=0.001,
        )
        a4_corner_marker_1 = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/A4CornerMarker_1",
            radius=0.004,
            height=0.00003,
            pos=(0.1665, 0.16, 0.00014),
            diffuse_color=(0.02, 0.42, 0.9),
        )
        a4_corner_marker_2 = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/A4CornerMarker_2",
            radius=0.004,
            height=0.00003,
            pos=(0.4635, 0.16, 0.00014),
            diffuse_color=(0.02, 0.42, 0.9),
        )
        a4_corner_marker_3 = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/A4CornerMarker_3",
            radius=0.004,
            height=0.00003,
            pos=(0.1665, 0.37, 0.00014),
            diffuse_color=(0.02, 0.42, 0.9),
        )
        a4_corner_marker_4 = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/A4CornerMarker_4",
            radius=0.004,
            height=0.00003,
            pos=(0.4635, 0.37, 0.00014),
            diffuse_color=(0.02, 0.42, 0.9),
        )
        a4_center_marker = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/A4CenterMarker",
            radius=0.004,
            height=0.00003,
            pos=(0.315, 0.265, 0.00014),
            diffuse_color=(0.02, 0.42, 0.9),
        )
        right_disk_aluminum_top = _stage_collision_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/RightDiskAluminumTop",
            radius=0.050,
            height=0.104,
            pos=(0.590, 0.078, 0.052),
            diffuse_color=(0.72, 0.69, 0.62),
            static_friction=0.8,
            dynamic_friction=0.55,
        )
        right_disk_black_base = _stage_collision_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/RightDiskBlackBase",
            radius=0.052,
            height=0.024,
            pos=(0.590, 0.078, 0.012),
            diffuse_color=(0.02, 0.018, 0.016),
            static_friction=0.8,
            dynamic_friction=0.55,
        )
        right_disk_center_yellow_marker = _stage_marker_cylinder_asset(
            "{ENV_REGEX_NS}/Workspace/RightDiskCenterYellowMarker",
            radius=0.0045,
            height=0.00003,
            pos=(0.590, 0.078, 0.1043),
            diffuse_color=(1.0, 0.88, 0.02),
        )
        dome_light = AssetBaseCfg(
            prim_path="/World/Lights/SoftLabDome",
            spawn=sim_utils.DomeLightCfg(intensity=450.0, color=(1.0, 1.0, 1.0)),
        )
        overhead_light = AssetBaseCfg(
            prim_path="/World/Lights/OverheadLight",
            spawn=sim_utils.DistantLightCfg(intensity=1200.0, angle=0.35),
        )

    if FrameTransformerCfg is not None and OffsetCfg is not None:
        ee_frame = FrameTransformerCfg(
            prim_path="{ENV_REGEX_NS}/Robot/Geometry/link0",
            debug_vis=False,
            target_frames=[
                FrameTransformerCfg.FrameCfg(
                    prim_path=ROBOTIS_OMX_EEF_PRIM_PATH,
                    name="end_effector",
                    offset=OffsetCfg(pos=(0.0295, 0.0, 0.0)),
                ),
            ],
        )

    if ContactSensorCfg is not None:
        left_finger_contact = ContactSensorCfg(
            prim_path=ROBOTIS_OMX_LEFT_FINGER_PRIM_PATH,
            filter_prim_paths_expr=["{ENV_REGEX_NS}/red_cube"],
            history_length=3,
            max_contact_data_count_per_prim=128,
            track_contact_points=True,
            debug_vis=False,
        )
        right_finger_contact = ContactSensorCfg(
            prim_path=ROBOTIS_OMX_RIGHT_FINGER_PRIM_PATH,
            filter_prim_paths_expr=["{ENV_REGEX_NS}/red_cube"],
            history_length=3,
            max_contact_data_count_per_prim=128,
            track_contact_points=True,
            debug_vis=False,
        )

    if CameraCfg is not None and sim_utils is not None:
        top_cam = CameraCfg(
            prim_path="{ENV_REGEX_NS}/CameraTop",
            data_types=["rgb", "depth"],
            width=640,
            height=480,
            update_period=1.0 / 15.0,
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=18.0,
                horizontal_aperture=20.955,
                clipping_range=(0.05, 2.0),
            ),
            offset=CameraCfg.OffsetCfg(
                pos=(0.315, 0.205, 0.72),
                rot=(0.0415586345, -0.0, -0.0, 0.9991360903),
                convention="opengl",
            ),
        )
        front_cam = CameraCfg(
            prim_path="{ENV_REGEX_NS}/CameraFront",
            data_types=["rgb", "depth"],
            width=640,
            height=480,
            update_period=1.0 / 15.0,
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=14.0,
                horizontal_aperture=20.955,
                clipping_range=(0.05, 2.0),
            ),
            offset=CameraCfg.OffsetCfg(
                pos=(0.36, 0.96, 0.52),
                rot=(0.0, 0.4535829127, 0.8912140727, -0.0),
                convention="opengl",
            ),
        )
        right_cam = CameraCfg(
            prim_path="{ENV_REGEX_NS}/CameraRight",
            data_types=["rgb", "depth"],
            width=640,
            height=480,
            update_period=1.0 / 15.0,
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=10.0,
                horizontal_aperture=20.955,
                clipping_range=(0.05, 2.0),
            ),
            offset=CameraCfg.OffsetCfg(
                pos=(0.86, 0.58, 0.52),
                rot=(0.1927962303, 0.372826755, 0.8062312603, 0.4169183969),
                convention="opengl",
            ),
        )


@configclass
class RobotisOMXPhysicalObservationsCfg:
    if ObsTerm is not None:

        @configclass
        class PolicyCfg(ObsGroup):
            joint_pos = ObsTerm(func=physical_observations.joint_pos)
            joint_vel = ObsTerm(func=physical_observations.joint_vel)
            gripper_state = ObsTerm(func=physical_observations.gripper_state)
            eef_pos = ObsTerm(func=physical_observations.eef_pos)
            eef_quat = ObsTerm(func=physical_observations.eef_quat)
            eef_pose = ObsTerm(func=physical_observations.eef_pose)
            object_pose = ObsTerm(func=physical_observations.object_pose)
            top_rgb = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("top_cam"), "data_type": "rgb", "normalize": False})
            top_depth = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("top_cam"), "data_type": "depth", "normalize": False})
            front_rgb = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("front_cam"), "data_type": "rgb", "normalize": False})
            front_depth = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("front_cam"), "data_type": "depth", "normalize": False})
            right_rgb = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("right_cam"), "data_type": "rgb", "normalize": False})
            right_depth = ObsTerm(func=mdp.image, params={"sensor_cfg": SceneEntityCfg("right_cam"), "data_type": "depth", "normalize": False})

            def __post_init__(self) -> None:
                self.enable_corruption = False
                self.concatenate_terms = False

        @configclass
        class SubtaskTermsCfg(ObsGroup):
            approach = ObsTerm(func=physical_observations.approach)
            grasp = ObsTerm(func=physical_observations.grasp)
            lift = ObsTerm(func=physical_observations.lift)
            cube_lifted = ObsTerm(func=physical_observations.cube_lifted)
            place = ObsTerm(func=physical_observations.place)
            release = ObsTerm(func=physical_observations.release)
            released_at_target = ObsTerm(func=physical_observations.released_at_target)
            retract = ObsTerm(func=physical_observations.retract)

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
            "top_rgb",
            "top_depth",
            "front_rgb",
            "front_depth",
            "right_rgb",
            "right_depth",
        )


@configclass
class RobotisOMXPhysicalActionsCfg:
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
class RobotisOMXPhysicalEventsCfg:
    pass


if EventTerm is not None and SceneEntityCfg is not None and mdp is not None:
    RobotisOMXPhysicalEventsCfg.reset_base_scene = EventTerm(func=mdp.reset_scene_to_default, mode="reset")
    RobotisOMXPhysicalEventsCfg.reset_cube_pose = EventTerm(
        func=robotis_events.reset_red_cube_a4,
        mode="reset",
        params={"asset_cfg": SceneEntityCfg("red_cube")},
    )
    RobotisOMXPhysicalEventsCfg.cube_material = EventTerm(
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
    RobotisOMXPhysicalEventsCfg.cube_mass = EventTerm(
        func=mdp.randomize_rigid_body_mass,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "mass_distribution_params": (0.9, 1.1),
            "operation": "scale",
            "distribution": "uniform",
        },
    )


@configclass
class RobotisOMXPhysicalTerminationsCfg:
    pass


if DoneTerm is not None:
    RobotisOMXPhysicalTerminationsCfg.success = DoneTerm(func=physical_terminations.task_success)


@configclass
class RobotisOMXPhysicalRewardsCfg:
    pass


@configclass
class RobotisOMXPhysicalPickPlaceEnvCfg(ManagerBasedRLEnvCfg):
    decimation: int = 1
    episode_length_s: float = 10.0
    if ViewerCfg is not None:
        viewer: ViewerCfg = field(
            default_factory=lambda: ViewerCfg(
                eye=(0.9, -1.2, 0.8),
                lookat=(0.315, 0.22, 0.02),
                origin_type="world",
                env_index=0,
            )
        )
    scene: RobotisOMXPhysicalSceneCfg = field(default_factory=RobotisOMXPhysicalSceneCfg)
    observations: RobotisOMXPhysicalObservationsCfg = field(default_factory=RobotisOMXPhysicalObservationsCfg)
    actions: RobotisOMXPhysicalActionsCfg = field(default_factory=RobotisOMXPhysicalActionsCfg)
    rewards: RobotisOMXPhysicalRewardsCfg = field(default_factory=RobotisOMXPhysicalRewardsCfg)
    events: RobotisOMXPhysicalEventsCfg = field(default_factory=RobotisOMXPhysicalEventsCfg)
    terminations: RobotisOMXPhysicalTerminationsCfg = field(default_factory=RobotisOMXPhysicalTerminationsCfg)
    domain_randomization_profile: str = "conservative"
    action_contract: dict = field(default_factory=dict)
    contact_contract: dict = field(default_factory=dict)
    rgbd_contract: dict = field(default_factory=dict)
    scene_contract: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.domain_randomization_profile = os.environ.get(
            "ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE",
            self.domain_randomization_profile,
        )
        if hasattr(self, "sim") and hasattr(self.sim, "use_fabric"):
            self.sim.use_fabric = _env_bool("ROBOTIS_OMX_USE_FABRIC", bool(self.sim.use_fabric))
        ranges = event_ranges(self.domain_randomization_profile)
        if hasattr(self.events, "cube_material"):
            self.events.cube_material.params["static_friction_range"] = ranges["cube_static_friction_range"]
            self.events.cube_material.params["dynamic_friction_range"] = ranges["cube_dynamic_friction_range"]
        if hasattr(self.events, "cube_mass"):
            self.events.cube_mass.params["mass_distribution_params"] = ranges["cube_mass_scale_range"]
        if not hasattr(self, "subtask_configs"):
            self.subtask_configs = {}
        if not hasattr(self, "datagen_config"):
            self.datagen_config = SimpleNamespace()
        camera_width = _env_int(
            "ROBOTIS_OMX_CAMERA_WIDTH",
            ROBOTIS_OMX_DEFAULT_CAMERA_WIDTH,
            minimum=64,
            maximum=1920,
        )
        camera_height = _env_int(
            "ROBOTIS_OMX_CAMERA_HEIGHT",
            ROBOTIS_OMX_DEFAULT_CAMERA_HEIGHT,
            minimum=64,
            maximum=1080,
        )
        cameras_enabled = _camera_mode_enabled()
        camera_attrs = ("top_cam", "front_cam", "right_cam")
        if cameras_enabled:
            for camera_attr in camera_attrs:
                camera_cfg = getattr(self.scene, camera_attr, None)
                if camera_cfg is not None:
                    camera_cfg.width = camera_width
                    camera_cfg.height = camera_height
        else:
            for camera_attr in camera_attrs:
                if hasattr(self.scene, camera_attr):
                    setattr(self.scene, camera_attr, None)
            policy_obs = getattr(self.observations, "policy", None)
            for obs_attr in (
                "top_rgb",
                "top_depth",
                "front_rgb",
                "front_depth",
                "right_rgb",
                "right_depth",
            ):
                if policy_obs is not None and hasattr(policy_obs, obs_attr):
                    setattr(policy_obs, obs_attr, None)
        self.action_contract = {
            "control_mode": "joint_position_physical_articulation",
            "joint_names": list(ROBOTIS_OMX_JOINT_NAMES),
            "unit": "radians",
            "source": "lerobot_omx_joint_targets_or_generated_joint_targets",
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
        self.contact_contract = {
            "required_pairs": ["left_finger:red_cube", "right_finger:red_cube"],
            "threshold_n": physical_observations.GRASP_CONTACT_THRESHOLD_N,
            "sensors": ["left_finger_contact", "right_finger_contact"],
            "contact_reporter_prims": list(ROBOTIS_OMX_CONTACT_REPORTER_PRIM_PATHS),
        }
        self.rgbd_contract = {
            "cameras": list(ROBOTIS_OMX_CAMERA_NAMES),
            "enabled": cameras_enabled,
            "fps": 15,
            "width": camera_width,
            "height": camera_height,
            "rgb_encoding": "png",
            "depth_encoding": "png16",
            "depth_scale_m_per_unit": ROBOTIS_OMX_DEPTH_SCALE_M_PER_UNIT,
        }
        self.scene_contract = {
            "layout_basis": "omx_table_layout_usda_static_props",
            "source_stage_path": ROBOTIS_OMX_STAGE_PATH,
            "robot_stage_prim": ROBOTIS_OMX_STAGE_ROBOT_PRIM_PATH,
            "red_cube_stage_prim": ROBOTIS_OMX_STAGE_RED_CUBE_PRIM_PATH,
            "static_prim_names": list(ROBOTIS_OMX_STAGE_STATIC_PRIM_NAMES),
            "managed_robot_prim": "{ENV_REGEX_NS}/Robot",
            "managed_red_cube_prim": "{ENV_REGEX_NS}/red_cube",
        }
