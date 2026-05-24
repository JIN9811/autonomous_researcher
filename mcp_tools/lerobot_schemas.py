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

from typing import Any, Literal

from pydantic import BaseModel, Field


RuntimeMode = Literal["live", "test", "replay", "fault-injection"]
LeRobotDeviceRole = Literal["follower", "leader", "camera"]


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
    session_id: str = ""
    fault: str = ""
    dry_run: bool = True
    confirm_live_execute: bool = False


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
    train_extra_args: list[str] = Field(default_factory=list)
    fps: int | None = None
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
    camera_enabled: bool = False
    display_data: bool = False
    resume: bool = False
    push_to_hub: bool = False
    episode_index: int = 0
    visualization_tool: Literal["html", "rerun"] = "html"
    visualization_mode: Literal["local", "distant"] = "local"
    visualization_batch_size: int = 32
    visualization_num_workers: int = 4
    visualization_save: bool = False
    visualization_output_dir: str = ""
    visualization_web_port: int = 9090
    visualization_ws_port: int = 9087
    visualization_tolerance_s: float = 1e-4
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
