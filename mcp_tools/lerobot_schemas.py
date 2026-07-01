"""
File purpose:
- Pydantic schemas for LeRobot MCP tool payloads and robot profiles.

Key classes/functions:
- RobotProfile
- LeRobotSessionRequest
- LeRobotRecordControlRequest

Inputs/outputs:
- Input: incoming lerobot.* payload dictionaries
- Output: validated model objects with safe defaults

Dependencies:
- pydantic.BaseModel

Modification guide:
- Safe places to edit: optional fields and defaults
- Risky places to edit: response keys consumed by GUI/tests
- Related files: device_bridges/lerobot_bridge.py, mcp_tools/lerobot_tools.py
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RuntimeMode = Literal["live", "test", "replay", "fault-injection"]
LeRobotDeviceRole = Literal["follower", "leader", "camera"]
DEFAULT_ISAAC_RGBD_RENDER_CAMERAS = "top,front,right"


class IsaacSyntheticPipelineMode(str, Enum):
    """Synthetic pipeline backend selected by section 7."""

    ISAAC_LAB_REPLICATOR = "isaac_lab_replicator"
    REPLICATOR_RENDER_ONLY = "replicator_render_only"
    LEGACY_SIDECAR = "legacy_sidecar"


class IsaacSyntheticFallbackPolicy(str, Enum):
    """Policy for legacy sidecar use when the primary synthetic path is blocked."""

    BLOCK_ON_PRIMARY_FAILURE = "block_on_primary_failure"
    ALLOW_LEGACY_FALLBACK = "allow_legacy_fallback"
    LEGACY_ONLY = "legacy_only"


class IsaacSyntheticSourceIntent(str, Enum):
    """Operator intent for preview/debug/train exposure."""

    PREVIEW_ONLY = "preview_only"
    TRAIN_READY_SUCCESS_ONLY = "train_ready_success_only"
    DEBUG_INCLUDE_FAILED = "debug_include_failed"


class IsaacSyntheticSourceType(str, Enum):
    """Stable source labels used by manifests and training mix logic."""

    REAL_LEROBOT = "real_lerobot"
    ISAAC_RGBD_RENDER = "isaac_rgbd_render"
    REPLICATOR_RENDER_ONLY = "replicator_render_only"
    ISAAC_TELEOP_REPLAY_RENDER = "isaac_teleop_replay_render"
    ISAAC_LAB_MIMIC = "isaac_lab_mimic"
    ISAAC_LAB_RL_TEACHER = "isaac_lab_rl_teacher"
    LEGACY_SIDECAR = "legacy_sidecar"


class IsaacSyntheticRunStatus(str, Enum):
    """Top-level run status returned by Isaac Lab synthetic endpoints."""

    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    BLOCKED = "BLOCKED"
    READY_TO_BUILD = "READY_TO_BUILD"
    BUILDING = "BUILDING"
    READY_FOR_PREVIEW = "READY_FOR_PREVIEW"
    READY_FOR_HDF5 = "READY_FOR_HDF5"
    READY_FOR_TRAINING = "READY_FOR_TRAINING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IsaacSyntheticStage(str, Enum):
    """Validation/build stage names shared by API, CLI, and manifests."""

    REQUEST = "request"
    RUNTIME = "runtime"
    DIGITAL_TWIN = "digital_twin"
    DEPTH = "depth"
    CANONICAL_INDEX = "canonical_index"
    PHYSICS = "physics"
    ARTICULATION = "articulation"
    REPLICATOR = "replicator"
    HDF5 = "hdf5"
    MIMIC = "mimic"
    RL_TEACHER = "rl_teacher"
    TRAINING = "training"
    LEGACY = "legacy"


class IsaacLabSyntheticRequest(BaseModel):
    """Shared payload for Isaac Lab synthetic validation/build endpoints."""

    mode: RuntimeMode = "test"
    runtime_mode: RuntimeMode | None = None
    profile_id: str = ""
    dataset_path: str = ""
    dataset_root: str = ""
    dataset_repo_id: str = ""
    repo_id: str | None = None
    profile_name: str | None = None

    pipeline_mode: IsaacSyntheticPipelineMode = IsaacSyntheticPipelineMode.ISAAC_LAB_REPLICATOR
    fallback_policy: IsaacSyntheticFallbackPolicy = IsaacSyntheticFallbackPolicy.BLOCK_ON_PRIMARY_FAILURE
    source_intent: IsaacSyntheticSourceIntent = IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY

    output_root: str | None = None
    force_rebuild: bool = False
    resume: bool = True
    overwrite_latest: bool = True
    dry_run: bool = False
    job_id: str = ""

    isaac_lab_path: str = ""
    isaac_sim_python: str = ""
    isaac_sim_version: str = ""
    isaac_sim_docs_version: str = ""
    stage_path: str = ""

    cameras: list[str] = Field(default_factory=lambda: ["top", "front", "right"])
    max_source_frames: int = Field(default=150, ge=1, le=5000)
    attempts_per_source_frame: int = Field(default=1, ge=1, le=100)
    seed: int = Field(default=42, ge=0)
    isaac_data_augmentation_preview_count: int = Field(default=20, ge=1, le=200)
    validation_checks: list[str] = Field(default_factory=lambda: ["all"])

    augmentation_profile: str = "conservative"
    rgb_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    depth_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    render_strength: float = Field(default=0.15, ge=0.0, le=1.0)
    camera_pose_strength: float = Field(default=0.05, ge=0.0, le=1.0)

    enable_replicator: bool = True
    enable_hdf5_export: bool = True
    enable_mimic: bool = False
    enable_rl_teacher: bool = False
    enable_legacy_fallback: bool = False

    mimic_trials: int = Field(default=20, ge=1, le=5000)
    mimic_num_envs: int = Field(default=1, ge=1, le=256)
    rl_teacher_steps: int = Field(default=0, ge=0)

    e2e_create_fixture: bool = True
    e2e_episodes: int = Field(default=5, ge=1, le=50)
    e2e_episode_s: int = Field(default=10, ge=1, le=600)
    e2e_fps: int = Field(default=15, ge=1, le=120)
    e2e_train_steps: int = Field(default=2, ge=1, le=1000)

    require_digital_twin_pass: bool = True
    require_physics_pass: bool = True
    require_depth_pass: bool = True
    require_articulation_pass: bool = True

    real_weight: float = Field(default=1.0, ge=0.0, le=2.0)
    isaac_rgbd_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    replicator_render_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    isaac_lab_synthetic_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    legacy_sidecar_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class IsaacLabStepTraceItem(BaseModel):
    """Step trace row rendered by the GUI checklist."""

    stage: IsaacSyntheticStage
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    progress_start: float = 0.0
    progress_end: float = 0.0
    message: str = ""
    artifact: str | None = None
    blocker_code: str | None = None


class IsaacLabSyntheticResponse(BaseModel):
    """Common response envelope for Isaac Lab synthetic endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    ok: bool
    tool: str
    schema_: str = Field(default="atr.lerobot.isaac_lab_synthetic.response.v1", alias="schema")
    status: IsaacSyntheticRunStatus
    dataset_path: str
    output_root: str
    run_id: str
    job_id: str | None = None
    pipeline_mode: IsaacSyntheticPipelineMode
    fallback_policy: IsaacSyntheticFallbackPolicy
    source_intent: IsaacSyntheticSourceIntent
    fallback_used: bool = False
    validation_report: dict[str, Any] = Field(default_factory=dict)
    compatibility: dict[str, Any] = Field(default_factory=dict)
    digital_twin: dict[str, Any] = Field(default_factory=dict)
    canonical_episode_index: dict[str, Any] = Field(default_factory=dict)
    replicator: dict[str, Any] = Field(default_factory=dict)
    hdf5: dict[str, Any] = Field(default_factory=dict)
    mimic: dict[str, Any] = Field(default_factory=dict)
    rl_teacher: dict[str, Any] = Field(default_factory=dict)
    source_labels: dict[str, Any] = Field(default_factory=dict)
    training_exposure: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    step_trace: list[IsaacLabStepTraceItem] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class RobotProfile(BaseModel):
    """Robot profile used to build LeRobot command previews."""

    profile_id: str
    display_name: str
    robot_family: str
    robot_type: str
    teleop_type: str
    robot_port: str = ""
    teleop_port: str = ""
    camera_ports: dict[str, str] = Field(default_factory=dict)
    robot_id: str = ""
    teleop_id: str = ""
    calibration_dir: str = "memory/lerobot/calibration"
    camera_map: dict[str, str] = Field(default_factory=dict)
    fps: int = 30
    observation_schema: str = ""
    observation_pipeline_id: str = ""
    action_schema: str = ""
    safety_limits: dict[str, Any] = Field(default_factory=dict)
    command_templates: dict[str, list[str]] = Field(default_factory=dict)
    supported_workflows: list[str] = Field(default_factory=list)
    test_fixture: str = ""


class LeRobotBaseRequest(BaseModel):
    """Base payload for LeRobot tools."""

    mode: RuntimeMode = "test"
    runtime_mode: RuntimeMode | None = None
    profile_id: str = ""
    observation_pipeline_id: str = ""
    session_id: str = ""
    fault: str = ""
    dry_run: bool = True
    confirm_live_execute: bool = False
    isaac_mirror_enabled: bool = False
    isaac_mirror_endpoint: str = "http://127.0.0.1:8766/joints"
    isaac_mirror_sample_hz: float = 15.0
    isaac_mirror_timeout_s: float = 0.5
    isaac_mirror_max_samples: int | None = None
    isaac_mirror_record_path: str = ""
    isaac_mirror_attached_to_session_id: str = ""
    isaac_mirror_receiver_launch_mode: str = "isaac_extension"
    isaac_mirror_receiver_isaac_sim_executable: str = ""
    isaac_mirror_receiver_python: str = ""
    isaac_mirror_receiver_scene: str = ""
    isaac_mirror_receiver_start_timeout_s: float | None = None
    isaac_mirror_receiver_force_restart: bool = False
    isaac_mirror_receiver_play_timeline_on_startup: bool = False
    isaac_viewport_frame_on_start: bool = True
    isaac_rgbd_render_enabled: bool = True
    isaac_rgbd_render_target_fps: float = 15.0
    isaac_rgbd_render_cameras: str = DEFAULT_ISAAC_RGBD_RENDER_CAMERAS
    isaac_rgbd_post_render_auto_on_record_success: bool = True
    isaac_rgbd_post_render_inline: bool = False
    isaac_rgbd_post_render_poll_timeout_s: float = 10.0
    record_attempt_overwrite: bool = True
    active_robot_cam_enabled: bool = False
    active_robot_cam_record_start_enabled: bool = True
    active_robot_cam_camera_priority: str = "d405,d455f"
    active_robot_cam_primary_camera_key: str = "wrist"
    active_robot_cam_fallback_camera_key: str = "top"
    active_robot_cam_capture_pose_path: str = ""
    active_robot_cam_home_pose_path: str = ""
    active_robot_cam_resume_mode: str = "auto"
    active_robot_cam_d455f_fallback_enabled: bool = True
    active_robot_cam_trigger_on_first_action: bool = True


class LeRobotSessionRequest(LeRobotBaseRequest):
    """Payload for LeRobot session start/status/stop tools."""

    task_instruction: str = "pick and place specimen"
    dataset_path: str = ""
    dataset_root: str = ""
    dataset_repo_id: str = ""
    policy_path: str = ""
    policy_repo_id: str = ""
    policy_checkpoint_path: str = ""
    policy_pretrained_path: str = ""
    policy_type: str = "act"
    output_dir: str = ""
    job_name: str = ""
    device: str = "cuda"
    seed: int | None = None
    batch_size: int = 8
    steps: int = 100000
    num_workers: int = 4
    eval_freq: int = 20000
    log_freq: int = 200
    save_freq: int = 20000
    save_checkpoint: bool = True
    eval_batch_size: int | None = None
    optimizer_type: str = ""
    optimizer_lr: float | None = None
    optimizer_weight_decay: float | None = None
    optimizer_grad_clip_norm: float | None = None
    scheduler_type: str = ""
    scheduler_warmup_steps: int | None = None
    scheduler_decay_steps: int | None = None
    scheduler_peak_lr: float | None = None
    scheduler_decay_lr: float | None = None
    policy_n_obs_steps: int | None = None
    policy_chunk_size: int | None = None
    policy_n_action_steps: int | None = None
    policy_use_amp: bool = False
    wandb_enable: bool = False
    wandb_project: str = ""
    wandb_mode: str = "disabled"
    wandb_base_url: str = ""
    wandb_local_port: int = 8081
    train_extra_args: list[str] = Field(default_factory=list)
    dataset_mix_real_original_weight: float = 1.0
    dataset_mix_isaac_rgbd_weight: float = 0.5
    dataset_mix_isaac_augmentation_weight: float = 0.5
    dataset_mix_isaac_lab_synthetic_weight: float = 0.5
    dataset_mix_real_original_max_samples: int | None = None
    dataset_mix_isaac_rgbd_max_samples: int | None = None
    dataset_mix_isaac_augmentation_max_samples: int | None = None
    dataset_mix_isaac_lab_synthetic_max_samples: int | None = None
    dataset_mix_seed: int = 0
    fidelity_weighting_enabled: bool = True
    fidelity_real_original_weight: float = 1.0
    fidelity_isaac_rgbd_weight: float = 0.5
    fidelity_isaac_augmentation_weight: float = 0.3
    fidelity_isaac_lab_synthetic_weight: float = 0.2
    fps: int | None = None
    camera_fps: int | None = None
    teleop_time_s: float | None = None
    warmup_s: float = 2.0
    episode_s: float = 5.0
    reset_s: float = 2.0
    num_episodes: int = 1
    continuous_rollout: bool = False
    rollout_action_clamp: bool = True
    rollout_max_relative_target: int = 5
    rollout_temporal_ensemble: bool = True
    rollout_temporal_ensemble_coeff: float = 0.01
    rollout_inference_type: str = ""
    task_id: str = ""
    skill_id: str = ""
    policy_backend: str = "lerobot_cli"
    max_duration_s: float | None = None
    rollout_rtc_execution_horizon: int | None = None
    rollout_rtc_max_guidance_weight: float | None = None
    rollout_action_queue_size_to_get_new_actions: int | None = None
    camera_enabled: bool = False
    display_data: bool = False
    resume: bool = False
    push_to_hub: bool = False
    tts_engine: str = ""
    tts_rate: int | None = None
    tts_voice: str = ""
    episode_index: int = 0
    episode_indices: str = ""
    visualization_tool: Literal["html", "rerun"] = "rerun"
    visualization_mode: Literal["local", "distant"] = "distant"
    visualization_batch_size: int = 32
    visualization_num_workers: int = 4
    visualization_save: bool = False
    visualization_output_dir: str = ""
    visualization_web_port: int = 9092
    visualization_ws_port: int = 9089
    visualization_tolerance_s: float = 1e-4
    isaac_data_augmentation_output_dir: str = ""
    isaac_data_augmentation_variants: int = 8
    isaac_data_augmentation_max_frames: int = 200
    isaac_data_augmentation_seed: int | None = 0
    isaac_data_augmentation_cameras: str = DEFAULT_ISAAC_RGBD_RENDER_CAMERAS
    isaac_data_augmentation_profile: Literal["conservative", "sim2real", "stress"] = "conservative"
    isaac_data_augmentation_image_enabled: bool = True
    isaac_data_augmentation_photometric_enabled: bool = True
    isaac_data_augmentation_sensor_noise_enabled: bool = True
    isaac_data_augmentation_depth_noise_enabled: bool = True
    isaac_data_augmentation_render_domain_enabled: bool = True
    isaac_data_augmentation_camera_pose_enabled: bool = True
    isaac_data_augmentation_rgb_strength: float = 1.0
    isaac_data_augmentation_depth_strength: float = 1.0
    isaac_data_augmentation_render_domain_strength: float = 1.0
    isaac_data_augmentation_camera_pose_strength: float = 1.0
    isaac_data_augmentation_preview_count: int = 20
    observation: dict[str, Any] = Field(default_factory=dict)


class LeRobotRecordControlRequest(LeRobotBaseRequest):
    """Payload for recording controls."""

    action: Literal["stop", "retry", "next", "finish"] = "stop"


class LeRobotDevicePortRequest(LeRobotBaseRequest):
    """Payload for LeRobot leader/follower/camera port discovery and persistence."""

    device_role: LeRobotDeviceRole = "follower"
    port: str = ""
    camera_key: str = "top"
    camera_index: int | None = None
    camera_backend: str = "opencv"
    camera_use_depth: bool = False
    camera_fps: int | None = None
    camera_width: int = 640
    camera_height: int = 480
