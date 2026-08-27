"""
File purpose:
- Deterministic LeRobot / ROBOTIS bridge for test-mode sessions and gated live-mode command previews.

Key classes/functions:
- LeRobotBridgeConfig
- LeRobotBridge

Inputs/outputs:
- Input: lerobot.* MCP payloads and configs/lerobot.yaml
- Output: structured tool responses with command previews, session state, and step traces

Dependencies:
- pathlib
- mcp_tools.lerobot_schemas

Modification guide:
- Safe places to edit: fake state traces, response decorations, config fields
- Risky places to edit: live gate behavior and command argument validation
- Related files: mcp_tools/lerobot_tools.py, app/main.py, agents/manipulation_agent.py
"""

from __future__ import annotations

import copy
import glob
import inspect
import json
import os
import re
import select
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, IO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

from mcp_tools.lerobot_schemas import (
    IsaacLabSyntheticRequest,
    LeRobotBaseRequest,
    LeRobotDevicePortRequest,
    LeRobotRecordControlRequest,
    LeRobotSessionRequest,
    RobotProfile,
)
from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
from utils.isaac_omx_mirror_mapping import (
    ISAAC_OMX_ARTICULATION_ROOT,
    ISAAC_OMX_JOINT_MAP,
    ISAAC_OMX_SCENE_RELATIVE_PATH,
    ISAAC_OMX_TEST_JOINT_STATE_DEG,
    action_to_joint_state,
    default_isaac_omx_mirror_calibration_path,
    load_isaac_omx_mirror_calibration,
    positions_to_joint_state,
)
from utils.lerobot_joint_telemetry import (
    TELEMETRY_SCHEMA,
    JointTelemetryFileObserver,
    PostPlaceInterlock,
)


EventCallback = Callable[[dict[str, Any]], None]


UNSAFE_ARGUMENT_RE = re.compile(r"[;&|`]|[$][(]")
GENERATED_PATH_SUFFIX_RE = re.compile(r"-(?:\d{8}T\d{6}(?:\d{6})?Z)(?:-\d{2})?$")
POLICY_OUTPUT_FILE_NAMES = {"model.safetensors", "pytorch_model.bin", "policy.ckpt", "policy.pt", "policy.pth"}
POLICY_OUTPUT_FILE_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
MANUAL_STOP_ROLLOUT_EPISODE_S = 86400.0
LEROBOT_REALSENSE_BACKENDS = {"realsense", "intelrealsense", "intel_realsense", "realsense_sdk"}
LEROBOT_REALSENSE_TYPE = "intelrealsense"
LEROBOT_DEFAULT_REALSENSE_FPS = 15


def _command_script_path(command: list[str]) -> Path:
    if len(command) > 2 and command[1] == "-p":
        return Path(command[2]).expanduser()
    return Path(command[1]).expanduser() if len(command) > 1 else Path("")
LEROBOT_DEFAULT_REALSENSE_WARMUP_S = 20
LEROBOT_DEFAULT_CAMERA_WIDTH = 640
LEROBOT_DEFAULT_CAMERA_HEIGHT = 480
LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT = 0.001
LEROBOT_D405_DEPTH_SCALE_M_PER_UNIT = 0.0001
LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM = 0.0
LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM = 2000.0
LEROBOT_DEFAULT_CAMERA_DEPTH_CLIP_MM = {"wrist": {"min_mm": 50.0, "max_mm": 150.0}}
LEROBOT_REALSENSE_MODEL_NAMES = {
    "405": "Intel(R) RealSense(TM) Depth Camera 405",
    "455": "Intel(R) RealSense(TM) Depth Camera 455",
    "455f": "Intel(R) RealSense(TM) Depth Camera 455f",
}
LEROBOT_REALSENSE_DEFAULT_IDENTIFIERS = {
    "top": "341522300873",
    "wrist": "352122273019",
}
LEROBOT_REALSENSE_CAMERA_MODEL_HINTS = {
    "top": ("d455f", "d455", "455f", "455"),
    "wrist": ("d405", "405"),
}
LEROBOT_DEFAULT_TASK_INSTRUCTION = "Pick up the cube and place it"
LEROBOT_DEFAULT_RECORD_NUM_EPISODES = 60
LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID = "raw_depth_adapter"
LEROBOT_DEFAULT_TRAIN_POLICY_TYPE = "smolvla"
LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS = "top,front,right"
ISAAC_RGBD_POST_RENDER_EXECUTION_MODE = "headless_preplay_replay"
ISAAC_RGBD_POST_RENDER_PREPLAY_POLICY = "stop_specimen_play_settle_per_episode"
LEROBOT_OBSERVATION_PIPELINES: dict[str, dict[str, Any]] = {
    "legacy_lerobot": {
        "pipeline_id": "legacy_lerobot",
        "label": "Legacy LeRobot",
        "description": "LeRobot standard RGB/depth visual features only; raw 16-bit sidecar disabled.",
        "raw_depth_sidecar": False,
        "requires_raw_depth": False,
    },
    "rgbd_sidecar": {
        "pipeline_id": "rgbd_sidecar",
        "label": "RGB-D Sidecar",
        "description": "LeRobot standard RGB-D features plus ATR 16-bit raw-depth sidecar metadata.",
        "raw_depth_sidecar": True,
        "requires_raw_depth": False,
    },
    "raw_depth_adapter": {
        "pipeline_id": "raw_depth_adapter",
        "label": "Raw Depth Adapter",
        "description": "Adapter-ready RGB-D pipeline requiring ATR raw-depth sidecar and transform metadata.",
        "raw_depth_sidecar": True,
        "requires_raw_depth": True,
    },
}
def _normalize_observation_pipeline_id(value: Any, default: str = LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID) -> str:
    """Normalize operator-facing RGB-D pipeline aliases into stable IDs."""
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "legacy": "legacy_lerobot",
        "lerobot": "legacy_lerobot",
        "rgbd": "rgbd_sidecar",
        "rgb_d": "rgbd_sidecar",
        "sidecar": "rgbd_sidecar",
        "raw": "raw_depth_adapter",
        "raw_depth": "raw_depth_adapter",
        "adapter": "raw_depth_adapter",
    }
    clean = aliases.get(clean, clean)
    if clean in LEROBOT_OBSERVATION_PIPELINES:
        return clean
    fallback = str(default or LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID)
    return fallback if fallback in LEROBOT_OBSERVATION_PIPELINES else LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID


class _SubprocessFollowerJointPositionReader:
    """Keep one Dynamixel bus process open and read OMX follower positions on demand."""

    def __init__(self, bridge: "LeRobotBridge", port: str, motor_ids: list[int], *, timeout_s: float = 3.0) -> None:
        self._bridge = bridge
        self._port = str(port or "").strip()
        self._motor_ids = [int(item) for item in motor_ids]
        self._timeout_s = timeout_s
        self._process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "_SubprocessFollowerJointPositionReader":
        if not self._port:
            raise ValueError("follower port is empty")
        command = [
            self._bridge.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self._bridge.config.conda_env_name,
            "python",
            "-u",
            "-c",
            self._script(),
            self._port,
            json.dumps(self._motor_ids),
        ]
        self._process = subprocess.Popen(
            command,
            cwd=str(self._bridge.config.repo_root),
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        ready = self._read_message(timeout_s=max(self._timeout_s, 8.0))
        if not ready.get("ok"):
            raise RuntimeError(str(ready.get("message") or ready.get("error") or "Dynamixel reader did not become ready"))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        process = self._process
        if process is None:
            return
        try:
            if process.stdin and process.poll() is None:
                process.stdin.write(json.dumps({"command": "close"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        finally:
            self._process = None

    def read(self) -> dict[int, float]:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError("Dynamixel reader stdin is unavailable")
        process.stdin.write(json.dumps({"command": "read"}) + "\n")
        process.stdin.flush()
        message = self._read_message(timeout_s=self._timeout_s)
        if not message.get("ok"):
            raise RuntimeError(str(message.get("message") or message.get("error") or "Dynamixel read failed"))
        positions = message.get("positions")
        if not isinstance(positions, dict):
            raise RuntimeError("Dynamixel reader returned no positions")
        requested = set(self._motor_ids)
        return {
            _safe_int(key, -1, minimum=0): _safe_float(value, 0.0)
            for key, value in positions.items()
            if _safe_int(key, -1, minimum=0) in requested
        }

    def _require_process(self) -> subprocess.Popen[str]:
        process = self._process
        if process is None or process.poll() is not None:
            output_tail = ""
            if process and process.stdout:
                try:
                    output_tail = process.stdout.read()[-500:]
                except Exception:
                    output_tail = ""
            raise RuntimeError(f"Dynamixel reader process is not running. {output_tail}".strip())
        return process

    def _read_message(self, *, timeout_s: float) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("Dynamixel reader stdout is unavailable")
        deadline = time.monotonic() + timeout_s
        last_line = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                remainder = ""
                try:
                    remainder = process.stdout.read()
                except Exception:
                    remainder = ""
                raise RuntimeError((last_line + "\n" + remainder).strip() or f"Dynamixel reader exited with {process.returncode}")
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([process.stdout], [], [], min(remaining, 0.1))
            if not readable:
                continue
            line = process.stdout.readline()
            if not line:
                continue
            last_line = line.strip()
            if not last_line.startswith("{"):
                continue
            try:
                parsed = json.loads(last_line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise TimeoutError(f"Dynamixel reader timed out after {timeout_s:g}s; last_line={last_line}")

    @staticmethod
    def _script() -> str:
        return r"""
import importlib
import json
import sys
from pathlib import Path

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.dynamixel import DynamixelMotorsBus

port = sys.argv[1]
requested_ids = {int(item) for item in json.loads(sys.argv[2])}
motors = {
    "shoulder_pan": Motor(11, "xl430-w250", MotorNormMode.DEGREES),
    "shoulder_lift": Motor(12, "xl430-w250", MotorNormMode.RANGE_M100_100),
    "elbow_flex": Motor(13, "xl430-w250", MotorNormMode.RANGE_M100_100),
    "wrist_flex": Motor(14, "xl330-m288", MotorNormMode.RANGE_M100_100),
    "wrist_roll": Motor(15, "xl330-m288", MotorNormMode.DEGREES),
    "gripper": Motor(16, "xl330-m288", MotorNormMode.RANGE_0_100),
}
limits = {
    11: (-270.0, 360.0, "degrees"),
    12: (-120.0, 90.0, "range_m100_100"),
    13: (-120.0, 90.0, "range_m100_100"),
    14: (-100.0, 100.0, "range_m100_100"),
    15: (-270.0, 270.0, "degrees"),
    16: (0.0, 100.0, "range_0_100"),
}
calibration = {}
try:
    module = importlib.import_module("lerobot.robots.omx_follower.omx_follower")
    calib_path = Path(module.__file__).parent / "calibration" / "omx_follower_arm.json"
    if calib_path.exists():
        raw_calib = json.loads(calib_path.read_text(encoding="utf-8"))
        calibration = {name: MotorCalibration(**value) for name, value in raw_calib.items()}
except Exception:
    calibration = {}

bus = DynamixelMotorsBus(port, motors, calibration=calibration)
full_turn_deg_per_norm = 1.8

def read_positions():
    raw = bus.sync_read("Present_Position", normalize=False, num_retry=1)
    normalized = {}
    if calibration:
        try:
            normalized = bus.sync_read("Present_Position", normalize=True, num_retry=1)
        except Exception:
            normalized = {}
    values = {}
    for name, motor in motors.items():
        if motor.id not in requested_ids:
            continue
        lower, upper, norm_mode = limits[motor.id]
        raw_value = float(raw.get(name, 0.0))
        if name in normalized:
            norm_value = float(normalized[name])
            if norm_mode == "range_m100_100":
                value = norm_value * full_turn_deg_per_norm
            else:
                value = norm_value
        else:
            if norm_mode == "range_m100_100":
                value = ((raw_value / 4095.0) * 360.0) - 180.0
            else:
                value = lower + (raw_value / 4095.0) * (upper - lower)
        values[str(motor.id)] = value
    return values

try:
    bus.connect(handshake=False)
    bus.set_baudrate(bus.default_baudrate)
    print(json.dumps({"ok": True, "event": "ready"}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except Exception as exc:
            print(json.dumps({"ok": False, "message": f"invalid request: {exc}"}), flush=True)
            continue
        command = str(request.get("command") or "").lower()
        if command == "close":
            break
        if command != "read":
            print(json.dumps({"ok": False, "message": f"unsupported command: {command}"}), flush=True)
            continue
        try:
            print(json.dumps({"ok": True, "positions": read_positions()}, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "message": f"{exc.__class__.__name__}: {exc}"}), flush=True)
finally:
    try:
        bus.port_handler.closePort()
    except Exception:
        pass
""".strip()


@dataclass(slots=True)
class LeRobotBridgeConfig:
    """Parsed LeRobot bridge configuration."""

    default_profile_id: str = "robotis_omx_ai"
    default_mode: str = "test"
    session_memory_path: Path = Path("memory/lerobot_sessions.json")
    device_memory_path: Path = Path("memory/lerobot_device_ports.json")
    fake_dataset_root: Path = Path("artifacts/lerobot/fake_datasets")
    fake_checkpoint_root: Path = Path("artifacts/lerobot/fake_checkpoints")
    dataset_root: Path = Path("~/.cache/huggingface/lerobot")
    output_root: Path = Path("outputs/train")
    policy_root: Path = Path("outputs/train")
    session_log_root: Path = Path("runs/lerobot_sessions")
    conda_env_name: str = "lerobot"
    conda_executable: str = "conda"
    pi05_conda_env_name: str = "lerobot-pi05-torch211"
    xvla_conda_env_name: str = "lerobot-pi05-torch211"
    smolvla_conda_env_name: str = "lerobot-pi05-torch211"
    pi05_repo_root: Path = Path("~/lerobot_pi05")
    pi05_hf_home: Path = Path("~/.cache/huggingface_pi05")
    train_video_backend: str = "torchcodec"
    train_video_backend_fallback: str = "pyav"
    pi05_video_backend: str = "torchcodec"
    hf_token_path: Path = Path("~/.cache/huggingface/token")
    pi05_base_policy: str = "lerobot/pi05_base"
    xvla_base_policy: str = "lerobot/xvla-base"
    smolvla_base_policy: str = "lerobot/smolvla_base"
    wandb_local_port: int = 8081
    wandb_local_base_url: str = "http://127.0.0.1:8081"
    realsense_depth_align_to_color: bool = True
    realsense_depth_scale_m_per_unit: float = LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT
    realsense_depth_clip_min_mm: float = LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM
    realsense_depth_clip_max_mm: float = LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM
    realsense_camera_depth_clip_mm: dict[str, dict[str, float]] = field(
        default_factory=lambda: copy.deepcopy(LEROBOT_DEFAULT_CAMERA_DEPTH_CLIP_MM)
    )
    default_observation_pipeline_id: str = LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID
    tts_engine: str = "piper"
    tts_rate: int = -35
    tts_voice: str = "en_US-lessac-medium"
    tts_piper_python: Path = Path(".venv/bin/python")
    tts_piper_script: Path = Path("tools/tts/atr_piper_say.py")
    tts_piper_bin: Path = Path(".venv/bin/piper")
    tts_piper_model: Path = Path("models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx")
    tts_piper_config: Path = Path("models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json")
    policy_presets: list[dict[str, str]] = field(default_factory=list)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    repo_root: Path = Path(".")

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None, *, repo_root: Path | None = None) -> "LeRobotBridgeConfig":
        """Create bridge config from configs/lerobot.yaml-shaped data."""
        raw = dict(config or {})
        root = raw.get("lerobot", raw)
        repo = Path(repo_root or ".").resolve()
        session_memory = _resolve_path(repo, str(root.get("session_memory_path", "memory/lerobot_sessions.json")))
        device_memory = _resolve_path(repo, str(root.get("device_memory_path", "memory/lerobot_device_ports.json")))
        fake_dataset_root = _resolve_path(repo, str(root.get("fake_dataset_root", "artifacts/lerobot/fake_datasets")))
        fake_checkpoint_root = _resolve_path(repo, str(root.get("fake_checkpoint_root", "artifacts/lerobot/fake_checkpoints")))
        dataset_root = _resolve_path(repo, str(root.get("dataset_root", "~/.cache/huggingface/lerobot")))
        output_root = _resolve_path(repo, str(root.get("output_root", "outputs/train")))
        policy_root = _resolve_path(repo, str(root.get("policy_root", "outputs/train")))
        session_log_root = _resolve_path(repo, str(root.get("session_log_root", "runs/lerobot_sessions")))
        pi05_repo_root = _resolve_path(repo, str(root.get("pi05_repo_root", "~/lerobot_pi05")))
        pi05_hf_home = _resolve_path(repo, str(root.get("pi05_hf_home", "~/.cache/huggingface_pi05")))
        hf_token_path = _resolve_path(repo, str(root.get("hf_token_path", "~/.cache/huggingface/token")))
        tts_piper_python = _resolve_path(repo, str(root.get("tts_piper_python", ".venv/bin/python")))
        tts_piper_script = _resolve_path(repo, str(root.get("tts_piper_script", "tools/tts/atr_piper_say.py")))
        tts_piper_bin = _resolve_path(repo, str(root.get("tts_piper_bin", ".venv/bin/piper")))
        tts_piper_model = _resolve_path(repo, str(root.get("tts_piper_model", "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx")))
        tts_piper_config = _resolve_path(repo, str(root.get("tts_piper_config", "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json")))
        profiles = _resolve_profiles(dict(root.get("profiles", {})))
        policy_presets = [dict(item) for item in root.get("policy_presets", []) if isinstance(item, dict)]
        return cls(
            default_profile_id=str(root.get("default_profile_id", "robotis_omx_ai")),
            default_mode=str(root.get("default_mode", "test")),
            session_memory_path=session_memory,
            device_memory_path=device_memory,
            fake_dataset_root=fake_dataset_root,
            fake_checkpoint_root=fake_checkpoint_root,
            dataset_root=dataset_root,
            output_root=output_root,
            policy_root=policy_root,
            session_log_root=session_log_root,
            conda_env_name=str(root.get("conda_env_name", "lerobot")),
            conda_executable=_resolve_conda_executable(str(root.get("conda_executable", "conda"))),
            pi05_conda_env_name=str(root.get("pi05_conda_env_name", "lerobot-pi05-torch211")),
            xvla_conda_env_name=str(root.get("xvla_conda_env_name", root.get("pi05_conda_env_name", "lerobot-pi05-torch211"))),
            smolvla_conda_env_name=str(root.get("smolvla_conda_env_name", root.get("pi05_conda_env_name", "lerobot-pi05-torch211"))),
            pi05_repo_root=pi05_repo_root,
            pi05_hf_home=pi05_hf_home,
            train_video_backend=str(root.get("train_video_backend", "torchcodec")),
            train_video_backend_fallback=str(root.get("train_video_backend_fallback", "pyav")),
            pi05_video_backend=str(root.get("pi05_video_backend", root.get("train_video_backend", "torchcodec"))),
            hf_token_path=hf_token_path,
            pi05_base_policy=str(root.get("pi05_base_policy", "lerobot/pi05_base")),
            xvla_base_policy=str(root.get("xvla_base_policy", "lerobot/xvla-base")),
            smolvla_base_policy=str(root.get("smolvla_base_policy", "lerobot/smolvla_base")),
            wandb_local_port=_safe_int(root.get("wandb_local_port", 8081), 8081, minimum=1, maximum=65535),
            wandb_local_base_url=str(root.get("wandb_local_base_url", "http://127.0.0.1:8081")),
            realsense_depth_align_to_color=bool(root.get("realsense_depth_align_to_color", True)),
            realsense_depth_scale_m_per_unit=_safe_float(
                root.get("realsense_depth_scale_m_per_unit", LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT),
                LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT,
                minimum=0.000001,
            ),
            realsense_depth_clip_min_mm=_safe_float(
                root.get("realsense_depth_clip_min_mm", LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM),
                LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM,
            ),
            realsense_depth_clip_max_mm=_safe_float(
                root.get("realsense_depth_clip_max_mm", LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM),
                LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM,
                minimum=1.0,
            ),
            realsense_camera_depth_clip_mm=_normalize_camera_depth_clip_map(
                root.get("realsense_camera_depth_clip_mm", LEROBOT_DEFAULT_CAMERA_DEPTH_CLIP_MM)
            ),
            default_observation_pipeline_id=_normalize_observation_pipeline_id(
                root.get("default_observation_pipeline_id", LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID)
            ),
            tts_engine=str(root.get("tts_engine", "piper")),
            tts_rate=_safe_int(root.get("tts_rate", -35), -35, minimum=-100, maximum=100),
            tts_voice=str(root.get("tts_voice", "en_US-lessac-medium")),
            tts_piper_python=tts_piper_python,
            tts_piper_script=tts_piper_script,
            tts_piper_bin=tts_piper_bin,
            tts_piper_model=tts_piper_model,
            tts_piper_config=tts_piper_config,
            policy_presets=policy_presets,
            profiles=profiles,
            repo_root=repo,
        )


class LeRobotBridge:
    """Deterministic LeRobot bridge with live-mode gates disabled by default."""

    def __init__(self, config: LeRobotBridgeConfig) -> None:
        self.config = config
        self._sessions: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._monitor_processes: dict[str, subprocess.Popen[str]] = {}
        self._receiver_processes: dict[str, subprocess.Popen[str]] = {}
        self._log_handles: dict[str, IO[str]] = {}
        self._receiver_log_handles: dict[str, IO[str]] = {}
        self._receiver_commands: dict[str, list[str]] = {}
        self._mirror_stop_events: dict[str, threading.Event] = {}
        self._mirror_threads: dict[str, threading.Thread] = {}
        self._isaac_rgbd_render_jobs: dict[str, dict[str, Any]] = {}
        self._isaac_rgbd_render_threads: dict[str, threading.Thread] = {}
        self._isaac_rgbd_render_lock = threading.Lock()
        self._isaac_augmentation_jobs: dict[str, dict[str, Any]] = {}
        self._isaac_augmentation_threads: dict[str, threading.Thread] = {}
        self._isaac_augmentation_lock = threading.Lock()
        self._isaac_augmentation_latest_job_id = ""
        self._isaac_lab_mimic_jobs: dict[str, dict[str, Any]] = {}
        self._isaac_lab_mimic_processes: dict[str, subprocess.Popen[str]] = {}
        self._isaac_lab_mimic_threads: dict[str, threading.Thread] = {}
        self._isaac_lab_mimic_lock = threading.Lock()
        self._isaac_lab_mimic_latest_job_id = ""
        self._isaac_lab_rl_teacher_jobs: dict[str, dict[str, Any]] = {}
        self._isaac_lab_rl_teacher_processes: dict[str, subprocess.Popen[str]] = {}
        self._isaac_lab_rl_teacher_threads: dict[str, threading.Thread] = {}
        self._isaac_lab_rl_teacher_lock = threading.Lock()
        self._isaac_lab_rl_teacher_latest_job_id = ""
        self._isaac_lab_runner_jobs: dict[str, dict[str, dict[str, Any]]] = {
            "annotate": {},
            "mimic": {},
            "il_train": {},
            "il_eval": {},
            "rl_teacher": {},
            "live_e2e": {},
        }
        self._isaac_lab_runner_processes: dict[str, dict[str, subprocess.Popen[str]]] = {
            "annotate": {},
            "mimic": {},
            "il_train": {},
            "il_eval": {},
            "rl_teacher": {},
            "live_e2e": {},
        }
        self._isaac_lab_runner_locks: dict[str, threading.Lock] = {
            "annotate": threading.Lock(),
            "mimic": threading.Lock(),
            "il_train": threading.Lock(),
            "il_eval": threading.Lock(),
            "rl_teacher": threading.Lock(),
            "live_e2e": threading.Lock(),
        }
        self._isaac_lab_runner_latest_job_id: dict[str, str] = {
            "annotate": "",
            "mimic": "",
            "il_train": "",
            "il_eval": "",
            "rl_teacher": "",
            "live_e2e": "",
        }
        self._counter = 0
        self._selected_profile_id = config.default_profile_id
        self._selected_observation_pipeline_id = _normalize_observation_pipeline_id(config.default_observation_pipeline_id)
        self._module_available_cache: dict[tuple[str, str], bool] = {}
        self._joint_telemetry_observer = JointTelemetryFileObserver(
            max_initial_samples=0,
            max_batch_samples=0,
            max_initial_bytes=16 * 1024 * 1024,
            max_batch_bytes=4 * 1024 * 1024,
        )
        self._post_place_interlocks: dict[str, PostPlaceInterlock] = {}
        self._latest_joint_telemetry_packets: dict[str, dict[str, Any]] = {}
        self._joint_telemetry_gate_lock = threading.Lock()
        self._realsense_sysfs_root = Path("/sys/bus/usb/devices")

    def shutdown(self) -> dict[str, Any]:
        """Stop tracked and stale LeRobot live subprocesses before the GUI server exits."""
        mirror_trace = self._stop_all_mirror_loops()
        step_trace = self.cleanup_all_lerobot_processes()
        for session_id in list(self._monitor_processes):
            self._stop_training_monitor({"session_id": session_id})
        for session_id in list(self._log_handles):
            self._close_log_handle(session_id)
        for endpoint in list(self._receiver_processes):
            self._stop_receiver_process(endpoint)
        step_trace = mirror_trace + step_trace
        return {"ok": True, "tool": "lerobot.shutdown", "step_trace": step_trace, "events": step_trace}

    def cleanup_all_lerobot_processes(self, *, exclude_workflows: set[str] | None = None) -> list[dict[str, Any]]:
        """Stop any live LeRobot workflow process group tied to this checkout."""
        excluded = exclude_workflows or set()
        step_trace: list[dict[str, Any]] = []
        for workflow in ("teleoperate", "record", "train", "rollout", "visualize"):
            if workflow in excluded:
                continue
            step_trace.extend(self._cleanup_lerobot_processes(workflow))
        return step_trace

    def config_status(self) -> dict[str, Any]:
        """Return GUI-friendly configuration and current session summary."""
        profiles = [self._public_profile(profile) for profile in self._profiles()]
        return {
            "ok": True,
            "tool": "lerobot.config",
            "default_profile_id": self.config.default_profile_id,
            "selected_profile_id": self._selected_profile_id,
            "default_observation_pipeline_id": self.config.default_observation_pipeline_id,
            "selected_observation_pipeline_id": self._selected_observation_pipeline_id,
            "observation_pipelines": self._observation_pipeline_options(),
            "profiles": profiles,
            "sessions": self.sessions_recent(),
            "live_gate_summary": self._live_gate_summary(self._profile(self._selected_profile_id)),
            "paths": self._path_status(),
            "workflow_defaults": self._workflow_defaults_status(),
            "policy_presets": self._policy_presets(),
            "tts": self._tts_config_public(),
            "wandb": {
                "local_base_url": self.config.wandb_local_base_url,
                "local_port": self.config.wandb_local_port,
            },
            "environment": self._environment_status(),
            "device_memory": self._device_memory_public(),
        }

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Select a profile for GUI convenience without launching hardware."""
        profile_id = str(payload.get("profile_id") or self._selected_profile_id or self.config.default_profile_id)
        profile = self._profile(profile_id)
        if profile is None:
            return self._error("lerobot.config", "test", profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        self._selected_profile_id = profile.profile_id
        self._selected_observation_pipeline_id = self._request_observation_pipeline_id(payload, profile)
        return self.config_status()

    def profiles_list(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """List available robot profiles."""
        mode = self._mode(payload or {})
        return {
            "ok": True,
            "tool": "lerobot.profiles.list",
            "mode": mode,
            "selected_profile_id": self._selected_profile_id,
            "profiles": [self._public_profile(profile) for profile in self._profiles()],
            "step_trace": [{"step": "LIST_PROFILES", "status": "ok", "detail": f"{len(self.config.profiles)} profiles"}],
        }

    def profiles_validate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate one robot profile."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.profiles.validate", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        missing = [
            key
            for key in ("profile_id", "robot_type", "teleop_type", "robot_id", "teleop_id")
            if not str(getattr(profile, key, "")).strip()
        ]
        ok = not missing
        return {
            "ok": ok,
            "tool": "lerobot.profiles.validate",
            "mode": mode,
            "profile_id": profile.profile_id,
            "profile": self._public_profile(profile),
            "status": "valid" if ok else "invalid",
            "missing_fields": missing,
            "live_gate_summary": self._live_gate_summary(profile),
            "step_trace": [
                {
                    "step": "VALIDATE_PROFILE",
                    "status": "ok" if ok else "blocked",
                    "detail": "profile valid" if ok else f"missing={','.join(missing)}",
                }
            ],
        }

    def mirror_joint_mapping(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the physical OMX follower to Isaac Sim joint mapping."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.mirror.joint_mapping", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        joint_map = [dict(item) for item in ISAAC_OMX_JOINT_MAP]
        scene_path = self.config.repo_root / ISAAC_OMX_SCENE_RELATIVE_PATH
        calibration = self._isaac_mirror_calibration()
        step_trace = [
            {"step": "MIRROR_MAPPING", "status": "ok", "detail": f"{len(joint_map)} follower joints -> Isaac articulation"},
            {
                "step": "MIRROR_CALIBRATION",
                "status": "ok" if calibration.get("loaded") else "idle",
                "detail": str(calibration.get("path") or ""),
            },
        ]
        return {
            "ok": True,
            "tool": "lerobot.mirror.joint_mapping",
            "mode": mode,
            "profile_id": profile.profile_id,
            "scene_path": str(scene_path),
            "articulation_root": ISAAC_OMX_ARTICULATION_ROOT,
            "joint_map": joint_map,
            "calibration": calibration,
            "events": step_trace,
            "step_trace": step_trace,
            "error": None,
        }

    def mirror_joint_state_probe(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read the follower arm state for Isaac mirror mode without commanding motion."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.mirror.state_probe", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        joint_map = [dict(item) for item in ISAAC_OMX_JOINT_MAP]
        motor_ids = [int(item["motor_id"]) for item in joint_map]
        follower_port = self._device_port(profile, "follower", allow_fake=mode != "live")
        if mode == "test":
            positions = dict(ISAAC_OMX_TEST_JOINT_STATE_DEG)
            probe_source = "deterministic_test_state"
            read_step = {"step": "READ_TEST_STATE", "status": "ok", "detail": "fake follower joint positions"}
        else:
            follower_port = self._runtime_device_port(follower_port, "follower", live=True)
            if not follower_port:
                return self._error(
                    "lerobot.mirror.state_probe",
                    mode,
                    profile.profile_id,
                    "LEROBOT_MIRROR_FOLLOWER_PORT_REQUIRED",
                    "Saved follower port is required before live mirror probing.",
                )
            if follower_port.startswith("/dev/") and not Path(follower_port).exists():
                return self._error(
                    "lerobot.mirror.state_probe",
                    mode,
                    profile.profile_id,
                    "LEROBOT_MIRROR_FOLLOWER_PORT_UNAVAILABLE",
                    f"Follower port is not available: {follower_port}",
                )
            try:
                positions = self._read_follower_joint_positions(follower_port, motor_ids)
            except Exception as exc:
                return self._error(
                    "lerobot.mirror.state_probe",
                    mode,
                    profile.profile_id,
                    "LEROBOT_MIRROR_JOINT_READ_FAILED",
                    f"Follower joint read failed: {exc}",
                )
            probe_source = "live_dynamixel_present_position"
            read_step = {"step": "READ_LIVE_STATE", "status": "ok", "detail": f"follower={follower_port}"}
        return self._isaac_mirror_probe_from_positions(
            mode=mode,
            profile_id=profile.profile_id,
            follower_port=follower_port,
            probe_source=probe_source,
            read_step=read_step,
            joint_map=joint_map,
            positions=positions,
        )

    def _isaac_mirror_probe_from_positions(
        self,
        *,
        mode: str,
        profile_id: str,
        follower_port: str,
        probe_source: str,
        read_step: dict[str, str],
        joint_map: list[dict[str, Any]],
        positions: dict[int, float],
    ) -> dict[str, Any]:
        calibration = self._isaac_mirror_calibration()
        normalized_positions = {
            int(item["motor_id"]): _safe_float(
                positions.get(int(item["motor_id"])),
                ISAAC_OMX_TEST_JOINT_STATE_DEG.get(int(item["motor_id"]), 0.0),
            )
            for item in joint_map
        }
        joint_state = positions_to_joint_state(
            normalized_positions,
            calibration=calibration,
            values_are_isaac_targets=True,
            joint_map=joint_map,
        )
        step_trace = [
            {"step": "MIRROR_MAPPING", "status": "ok", "detail": f"{len(joint_map)} joints"},
            {
                "step": "MIRROR_CALIBRATION",
                "status": "ok" if calibration.get("loaded") else "idle",
                "detail": str(calibration.get("path") or ""),
            },
            read_step,
            {"step": "STATE_READY", "status": "ok", "detail": f"{len(joint_state)} joint values"},
        ]
        return {
            "ok": True,
            "tool": "lerobot.mirror.state_probe",
            "mode": mode,
            "profile_id": profile_id,
            "scene_path": str(self.config.repo_root / ISAAC_OMX_SCENE_RELATIVE_PATH),
            "articulation_root": ISAAC_OMX_ARTICULATION_ROOT,
            "follower_port": follower_port,
            "probe_source": probe_source,
            "joint_state": joint_state,
            "joint_map": joint_map,
            "calibration": calibration,
            "events": step_trace,
            "step_trace": step_trace,
            "error": None,
        }

    def _isaac_mirror_calibration(self) -> dict[str, Any]:
        return load_isaac_omx_mirror_calibration(default_isaac_omx_mirror_calibration_path(self.config.repo_root))

    def mirror_receiver_health(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check the Isaac mirror receiver before live teleop/record synchronization."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        endpoint = self._isaac_mirror_endpoint(request)
        timeout_s = self._isaac_mirror_timeout_s(request)
        health = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=timeout_s)
        ok = bool(health.get("ok"))
        step_trace = [
            {
                "step": "ISAAC_MIRROR_RECEIVER_HEALTH",
                "status": "ok" if ok else "failed",
                "detail": str(health.get("health_url") or self._isaac_mirror_health_url(endpoint)),
            }
        ]
        return {
            "ok": ok,
            "tool": "lerobot.mirror.receiver_health",
            "mode": mode,
            "profile_id": profile_id,
            "mirror_endpoint": endpoint,
            "health_url": health.get("health_url", self._isaac_mirror_health_url(endpoint)),
            "receiver_health": health,
            "status": "READY" if ok else "UNAVAILABLE",
            "apply_mode": health.get("apply_mode", ""),
            "sample_count": health.get("sample_count", 0),
            "message": "" if ok else str(health.get("message") or health.get("error") or "Isaac mirror receiver is unavailable."),
            "events": step_trace,
            "step_trace": step_trace,
            "error": None if ok else str(health.get("message") or health.get("error") or "Isaac mirror receiver is unavailable."),
        }

    def mirror_receiver_verify(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Post one mirror sample and confirm the Isaac receiver reports it as latest state."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        endpoint = self._isaac_mirror_endpoint(request)
        timeout_s = self._isaac_mirror_timeout_s(request)
        health = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=timeout_s)
        if not health.get("ok"):
            return self._error(
                "lerobot.mirror.receiver_verify",
                mode,
                profile_id,
                "LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE",
                f"Isaac mirror receiver is unavailable at {health.get('health_url', self._isaac_mirror_health_url(endpoint))}: "
                f"{health.get('message') or health.get('error') or 'health check failed'}",
            )
        verify_payload = {**raw_payload, "isaac_mirror_endpoint": endpoint, "isaac_mirror_timeout_s": timeout_s, "isaac_mirror_max_samples": 1}
        loop = self.mirror_loop_start(verify_payload)
        if not loop.get("ok"):
            result = self._error(
                "lerobot.mirror.receiver_verify",
                mode,
                profile_id,
                str(loop.get("failure_code") or "LEROBOT_ISAAC_MIRROR_LOOP_FAILED"),
                str(loop.get("message") or loop.get("error") or "Mirror loop failed during receiver verification."),
            )
            result["isaac_mirror"] = loop
            result["receiver_health_before"] = health
            return result
        state = self._fetch_isaac_mirror_receiver_state(endpoint, timeout_s=timeout_s)
        if not state.get("ok"):
            result = self._error(
                "lerobot.mirror.receiver_verify",
                mode,
                profile_id,
                "LEROBOT_ISAAC_MIRROR_STATE_UNAVAILABLE",
                f"Isaac mirror receiver state is unavailable at {state.get('state_url', self._isaac_mirror_state_url(endpoint))}: "
                f"{state.get('message') or state.get('error') or 'state check failed'}",
            )
            result["isaac_mirror"] = loop
            result["receiver_health_before"] = health
            result["receiver_state_after"] = state
            return result
        summary = dict(state.get("last_payload_summary") or {})
        loop_session_id = str(loop.get("session_id") or "")
        loop_sample_count = int(loop.get("sample_count") or 0)
        summary_session_id = str(summary.get("session_id") or "")
        summary_sample_index = int(summary.get("sample_index") or 0)
        before_count = int(health.get("sample_count") or 0)
        after_count = int(state.get("sample_count") or 0)
        if summary_session_id != loop_session_id or summary_sample_index != loop_sample_count or after_count <= before_count:
            message = (
                "Isaac mirror receiver did not report the posted sample as latest state: "
                f"expected session={loop_session_id} sample={loop_sample_count}, "
                f"got session={summary_session_id or '-'} sample={summary_sample_index}, "
                f"receiver_count {before_count}->{after_count}."
            )
            result = self._error(
                "lerobot.mirror.receiver_verify",
                mode,
                profile_id,
                "LEROBOT_ISAAC_MIRROR_VERIFY_STALE_STATE",
                message,
            )
            result["isaac_mirror"] = loop
            result["receiver_health_before"] = health
            result["receiver_state_after"] = state
            return result
        step_trace = [
            {"step": "ISAAC_MIRROR_RECEIVER_HEALTH", "status": "ok", "detail": str(health.get("health_url") or self._isaac_mirror_health_url(endpoint))},
            {"step": "MIRROR_SAMPLE_POSTED", "status": "ok", "detail": f"session={loop_session_id} sample={loop_sample_count}"},
            {"step": "RECEIVER_STATE_CONFIRMED", "status": "ok", "detail": f"receiver_count {before_count}->{after_count}"},
        ]
        return {
            "ok": True,
            "tool": "lerobot.mirror.receiver_verify",
            "mode": mode,
            "profile_id": profile_id,
            "status": "VERIFIED",
            "mirror_endpoint": endpoint,
            "health_url": health.get("health_url", self._isaac_mirror_health_url(endpoint)),
            "state_url": state.get("state_url", self._isaac_mirror_state_url(endpoint)),
            "isaac_mirror": loop,
            "receiver_health_before": health,
            "receiver_state_after": state,
            "verification": {
                "session_id": loop_session_id,
                "sample_index": loop_sample_count,
                "receiver_sample_count_before": before_count,
                "receiver_sample_count_after": after_count,
                "last_payload_summary": summary,
            },
            "events": step_trace,
            "step_trace": step_trace,
            "error": None,
        }

    def mirror_receiver_process_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start the Isaac mirror receiver process for the configured endpoint."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        endpoint = self._isaac_mirror_endpoint(request)
        process_key = self._isaac_mirror_process_key(endpoint)
        command_info = self._isaac_mirror_receiver_command(raw_payload, endpoint)
        host, port = self._isaac_mirror_host_port(endpoint)
        if not command_info.get("ok"):
            return self._error(
                "lerobot.mirror.receiver_process.start",
                mode,
                profile_id,
                str(command_info.get("failure_code") or "LEROBOT_ISAAC_MIRROR_RECEIVER_COMMAND_INVALID"),
                str(command_info.get("message") or "Isaac mirror receiver command is invalid."),
            )
        command = [str(item) for item in command_info["command"]]
        existing = self._receiver_processes.get(process_key)
        force_restart = _safe_bool(raw_payload.get("isaac_mirror_receiver_force_restart"), False)
        stopped_for_restart: dict[str, Any] = {}
        if force_restart:
            stopped_for_restart = self._stop_receiver_process(process_key)
            unmanaged_stop = self._stop_unmanaged_receiver_processes(endpoint)
            if unmanaged_stop:
                stopped_for_restart["unmanaged"] = unmanaged_stop
        elif existing and existing.poll() is None:
            if self._receiver_commands.get(process_key) == command:
                return self.mirror_receiver_process_status(raw_payload)
            self._stop_receiver_process(process_key)
        else:
            self._stop_receiver_process(process_key)

        log_dir = self.config.repo_root / "runs" / "isaac_mirror_receiver"
        log_dir.mkdir(parents=True, exist_ok=True)
        launch_mode = str(command_info.get("launch_mode") or "python_script")
        log_path = log_dir / f"receiver_{launch_mode}_{host.replace('.', '_')}_{port}.log"
        log_handle = log_path.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.config.repo_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except Exception as exc:
            log_handle.close()
            return self._error("lerobot.mirror.receiver_process.start", mode, profile_id, "LEROBOT_ISAAC_MIRROR_RECEIVER_START_FAILED", f"{exc.__class__.__name__}: {exc}")
        self._receiver_processes[process_key] = process
        self._receiver_log_handles[process_key] = log_handle
        self._receiver_commands[process_key] = command
        default_timeout_s = 180.0 if launch_mode == "isaac_extension" else 5.0
        timeout_s = _safe_float(raw_payload.get("isaac_mirror_receiver_start_timeout_s"), default_timeout_s, minimum=0.1, maximum=300.0)
        health = self._wait_for_isaac_mirror_receiver(endpoint, timeout_s=timeout_s, request_timeout_s=self._isaac_mirror_timeout_s(request), process=process)
        if not health.get("ok"):
            failure_code = str(health.get("failure_code") or "LEROBOT_ISAAC_MIRROR_RECEIVER_HEALTH_TIMEOUT")
            message = (
                str(health.get("message"))
                if health.get("message")
                else f"Receiver process started but health did not become ready within {timeout_s:g}s."
            )
            if failure_code == "LEROBOT_ISAAC_MIRROR_RECEIVER_EXITED":
                self._stop_receiver_process(process_key)
            return {
                "ok": False,
                "tool": "lerobot.mirror.receiver_process.start",
                "mode": mode,
                "profile_id": profile_id,
                "status": "failed" if failure_code == "LEROBOT_ISAAC_MIRROR_RECEIVER_EXITED" else "STARTING",
                "failure_code": failure_code,
                "message": message,
                "pid": process.pid,
                "launch_mode": launch_mode,
                "command_preview": command,
                "log_path": str(log_path),
                "health": health,
                "step_trace": [{"step": "RECEIVER_PROCESS_STARTED", "status": "active", "detail": f"pid={process.pid}"}],
                "events": [{"step": "RECEIVER_PROCESS_STARTED", "status": "active", "detail": f"pid={process.pid}"}],
                "error": message,
            }
        step_trace = [
            {"step": "RECEIVER_PROCESS_STARTED", "status": "ok", "detail": f"pid={process.pid}"},
            {"step": "RECEIVER_HEALTH_READY", "status": "ok", "detail": str(health.get("health_url") or self._isaac_mirror_health_url(endpoint))},
        ]
        return {
            "ok": True,
            "tool": "lerobot.mirror.receiver_process.start",
            "mode": mode,
            "profile_id": profile_id,
            "status": "RUNNING",
            "pid": process.pid,
            "launch_mode": launch_mode,
            "mirror_endpoint": endpoint,
            "command_preview": command,
            "log_path": str(log_path),
            "health": health,
            "force_restart": force_restart,
            "stopped_for_restart": stopped_for_restart,
            "events": step_trace,
            "step_trace": step_trace,
            "error": None,
        }

    def mirror_receiver_process_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return managed Isaac mirror receiver process and HTTP health status."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        endpoint = self._isaac_mirror_endpoint(request)
        process_key = self._isaac_mirror_process_key(endpoint)
        process = self._receiver_processes.get(process_key)
        returncode = process.poll() if process else None
        running = bool(process and returncode is None)
        health = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=self._isaac_mirror_timeout_s(request)) if running else {"ok": False, "message": "managed receiver process is not running"}
        status = "RUNNING" if running else "STOPPED" if process else "IDLE"
        return {
            "ok": bool(running and health.get("ok")),
            "tool": "lerobot.mirror.receiver_process.status",
            "mode": mode,
            "profile_id": profile_id,
            "status": status,
            "pid": process.pid if process else None,
            "returncode": returncode,
            "mirror_endpoint": endpoint,
            "health": health,
            "log_path": str(self._receiver_log_handles.get(process_key).name) if self._receiver_log_handles.get(process_key) else "",
            "events": [{"step": "RECEIVER_PROCESS_STATUS", "status": "ok" if running else "idle", "detail": status}],
            "step_trace": [{"step": "RECEIVER_PROCESS_STATUS", "status": "ok" if running else "idle", "detail": status}],
            "error": None if running else "managed receiver process is not running",
        }

    def mirror_receiver_process_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop the managed Isaac mirror receiver process for the configured endpoint."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        endpoint = self._isaac_mirror_endpoint(request)
        process_key = self._isaac_mirror_process_key(endpoint)
        stopped = self._stop_receiver_process(process_key)
        step_trace = [{"step": "RECEIVER_PROCESS_STOP", "status": "ok", "detail": stopped.get("detail", "stopped")}]
        return {
            "ok": True,
            "tool": "lerobot.mirror.receiver_process.stop",
            "mode": mode,
            "profile_id": profile_id,
            "status": "STOPPED",
            "mirror_endpoint": endpoint,
            "pid": stopped.get("pid"),
            "returncode": stopped.get("returncode"),
            "events": step_trace,
            "step_trace": step_trace,
            "error": None,
        }

    def mirror_loop_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Continuously mirror the physical follower state into an Isaac Sim endpoint."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.mirror.loop_start", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        endpoint = self._isaac_mirror_endpoint(request)
        if not endpoint:
            return self._error(
                "lerobot.mirror.loop_start",
                mode,
                profile.profile_id,
                "LEROBOT_ISAAC_MIRROR_ENDPOINT_REQUIRED",
                "Isaac mirror endpoint is required.",
            )
        sample_hz = self._isaac_mirror_sample_hz(request)
        max_samples = request.isaac_mirror_max_samples
        if mode == "test" and (max_samples is None or max_samples <= 0):
            max_samples = 1
        attached_to = str(request.isaac_mirror_attached_to_session_id or raw_payload.get("attached_to_session_id") or "").strip()
        session_id = request.session_id or self._new_session_id("isaac_mirror")
        record_path = self._isaac_mirror_record_path(request, session_id)
        step_trace = [
            {"step": "MIRROR_LOOP_READY", "status": "ok", "detail": f"endpoint={endpoint}"},
            {"step": "MIRROR_LOOP_SAMPLING", "status": "active", "detail": f"{sample_hz:g} Hz"},
        ]
        session = {
            "session_id": session_id,
            "tool": "lerobot.mirror.loop_start",
            "workflow": "isaac_mirror",
            "mode": mode,
            "profile_id": profile.profile_id,
            "status": "MIRROR_ACTIVE",
            "command_preview": ["POST", endpoint],
            "step_trace": step_trace,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_repo_id": "",
            "dataset_root": "",
            "dataset_path": "",
            "output_dir": "",
            "job_name": "",
            "checkpoint_path": "",
            "log_path": str(record_path),
            "pid": None,
            "returncode": None,
            "mirror_endpoint": endpoint,
            "mirror_sample_hz": sample_hz,
            "mirror_timeout_s": self._isaac_mirror_timeout_s(request),
            "mirror_record_path": str(record_path),
            "attached_to_session_id": attached_to,
            "sample_count": 0,
            "sync_summary": {
                "target_sample_hz": sample_hz,
                "sample_period_s": round(1.0 / sample_hz, 6),
                "sample_count": 0,
                "effective_sample_hz": 0.0,
                "mean_post_latency_ms": 0.0,
                "max_post_latency_ms": 0.0,
                "mean_loop_lag_ms": 0.0,
                "max_loop_lag_ms": 0.0,
                "post_ok_count": 0,
                "post_fail_count": 0,
                "last_receiver_sample_count": None,
            },
        }
        self._sessions[session_id] = session
        stop_event = threading.Event()
        self._mirror_stop_events[session_id] = stop_event
        if mode == "test" or (max_samples is not None and max_samples > 0):
            self._run_isaac_mirror_loop(session, request, stop_event, max_samples=max_samples)
        else:
            thread = threading.Thread(
                target=self._run_isaac_mirror_loop,
                args=(session, request, stop_event),
                kwargs={"max_samples": max_samples},
                name=f"isaac-mirror-{session_id}",
                daemon=True,
            )
            self._mirror_threads[session_id] = thread
            thread.start()
        self._emit_trace(raw_payload, "lerobot.mirror.loop_start", list(session.get("step_trace", [])), profile.profile_id, mode, session_id)
        return self._session_response(
            "lerobot.mirror.loop_start",
            mode,
            session,
            list(session.get("step_trace", [])),
            mirror_record_path=str(record_path),
            sample_count=session.get("sample_count", 0),
            attached_to_session_id=attached_to,
        )

    def mirror_loop_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop an Isaac mirror loop by session id or attached LeRobot session id."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        attached_to = str(request.isaac_mirror_attached_to_session_id or raw_payload.get("attached_to_session_id") or "").strip()
        session = self._resolve_mirror_session(request.session_id, attached_to, prefer_active=True)
        profile_id = str(session.get("profile_id") if session else request.profile_id or self._selected_profile_id)
        if session is None:
            step_trace = [{"step": "MIRROR_LOOP_STOP", "status": "ok", "detail": "no active mirror session; idempotent stop"}]
            return {
                "ok": True,
                "tool": "lerobot.mirror.loop_stop",
                "mode": mode,
                "profile_id": profile_id,
                "session_id": request.session_id,
                "workflow": "isaac_mirror",
                "status": "STOPPED",
                "attached_to_session_id": attached_to,
                "idempotent": True,
                "events": step_trace,
                "step_trace": step_trace,
                "error": None,
            }
        session_id = str(session.get("session_id", ""))
        stop_event = self._mirror_stop_events.get(session_id)
        if stop_event:
            stop_event.set()
        thread = self._mirror_threads.get(session_id)
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        status = str(session.get("status") or "").upper()
        if status not in {"COMPLETED", "FAILED"}:
            session["status"] = "STOPPED"
            session["returncode"] = 0
        step_trace = [
            {"step": "MIRROR_LOOP_STOPPING", "status": "ok", "detail": f"session={session_id}"},
            {"step": str(session.get("status") or "STOPPED"), "status": "ok", "detail": "mirror loop stopped"},
        ]
        session.setdefault("step_trace", []).extend(step_trace)
        self._mirror_stop_events.pop(session_id, None)
        self._mirror_threads.pop(session_id, None)
        self._emit_trace(raw_payload, "lerobot.mirror.loop_stop", step_trace, profile_id, mode, session_id)
        return self._session_response(
            "lerobot.mirror.loop_stop",
            mode,
            session,
            step_trace,
            mirror_record_path=session.get("mirror_record_path", ""),
            sample_count=session.get("sample_count", 0),
            attached_to_session_id=str(session.get("attached_to_session_id") or attached_to),
        )

    def mirror_loop_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return Isaac mirror loop status."""
        raw_payload = dict(payload or {})
        request = LeRobotBaseRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        attached_to = str(request.isaac_mirror_attached_to_session_id or raw_payload.get("attached_to_session_id") or "").strip()
        session = self._resolve_mirror_session(request.session_id, attached_to)
        if session is None:
            step_trace = [{"step": "MIRROR_LOOP_STATUS", "status": "idle", "detail": "no mirror session"}]
            return {
                "ok": True,
                "tool": "lerobot.mirror.loop_status",
                "mode": mode,
                "profile_id": request.profile_id or self._selected_profile_id,
                "session_id": request.session_id,
                "workflow": "isaac_mirror",
                "status": "IDLE",
                "sample_count": 0,
                "attached_to_session_id": attached_to,
                "events": step_trace,
                "step_trace": step_trace,
                "error": None,
            }
        return self._session_response(
            "lerobot.mirror.loop_status",
            mode,
            session,
            list(session.get("step_trace", [])),
            mirror_record_path=session.get("mirror_record_path", ""),
            sample_count=session.get("sample_count", 0),
            attached_to_session_id=str(session.get("attached_to_session_id") or attached_to),
        )

    def find_ports(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return fake ports in test mode and block unsafe live discovery by default."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.find_ports", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        command_preview = self._command_preview(profile, "find_ports", [])
        ports = [
            {"role": "follower", "legacy_role": "robot", "port": self._device_port(profile, "follower"), "detected": True},
            {"role": "leader", "legacy_role": "teleop", "port": self._device_port(profile, "leader"), "detected": True},
        ]
        for camera_key in self._profile_camera_keys(profile):
            ports.append({"role": "camera", "port": self._device_port(profile, "camera", camera_key=camera_key), "camera_key": camera_key, "detected": True})
        detail = "deterministic fake ports"
        serial_ports = [item["port"] for item in ports if item.get("role") in {"follower", "leader"}]
        camera_ports = [str(item["port"]) for item in ports if item.get("role") == "camera"]
        if mode == "live":
            scanned = self._scan_serial_ports()
            scanned_cameras = self._scan_camera_ports()
            scanned_realsense = self._scan_realsense_camera_ids()
            ports = [
                {"role": "candidate", "port": port, "port_type": "serial", "detected": True}
                for port in scanned
            ]
            ports.extend({"role": "camera_candidate", "port": port, "port_type": "camera", "detected": True} for port in scanned_cameras)
            ports.extend(
                {"role": "camera_candidate", "port": port, "port_type": "realsense_camera", "backend": LEROBOT_REALSENSE_TYPE, "detected": True}
                for port in scanned_realsense
            )
            serial_ports = scanned
            camera_ports = sorted(dict.fromkeys([*scanned_cameras, *scanned_realsense]))
            detail = f"{len(scanned)} serial, {len(scanned_cameras)} v4l camera, {len(scanned_realsense)} RealSense candidate ports"
        step_trace = [
            {"step": "PRECHECK", "status": "ok", "detail": f"profile={profile.profile_id}"},
            {"step": "DISCOVERING", "status": "ok", "detail": detail},
            {"step": "DONE", "status": "ok", "detail": "ports ready"},
        ]
        self._emit_trace(payload, "lerobot.find_ports", step_trace, profile.profile_id, mode)
        return {
            "ok": True,
            "tool": "lerobot.find_ports",
            "mode": mode,
            "profile_id": profile.profile_id,
            "status": "DONE",
            "ports": ports,
            "serial_ports": serial_ports,
            "camera_ports": camera_ports,
            "saved_devices": self._saved_devices(profile.profile_id),
            "instructions": [
                "For follower/leader, keep the MotorBus boards connected and run Detect & Save; live detection verifies Dynamixel IDs before saving.",
                "ROBOTIS OMX-AI leader uses IDs 1-6 and follower uses IDs 11-16. Removed serial ports are not auto-saved.",
                "For cameras, scan or save top and wrist camera device/index separately, then run each capture test.",
            ],
            "command_preview": command_preview,
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def ports_baseline(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist a pre-plug baseline for leader/follower/camera port identification."""
        request = LeRobotDevicePortRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.ports.baseline", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        serial_ports = [] if mode == "test" else self._scan_serial_ports()
        camera_ports = [] if mode == "test" else self._scan_camera_candidates(request)
        baseline = {
            "device_role": request.device_role,
            "serial_ports": serial_ports,
            "camera_ports": camera_ports,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if mode != "test" and request.device_role in {"follower", "leader"}:
            baseline["serial_identity_map"] = self._serial_identity_map(serial_ports)
        memory = self._load_device_memory()
        profile_memory = self._profile_device_memory(memory, profile.profile_id)
        baseline_key = self._device_memory_key(request.device_role, request.camera_key)
        profile_memory.setdefault("baselines", {})[baseline_key] = baseline
        self._save_device_memory(memory)
        step_trace = [
            {"step": "BASELINE", "status": "ok", "detail": f"{request.device_role} serial={len(serial_ports)} camera={len(camera_ports)}"},
            {"step": "WAIT_DEVICE_CHANGE", "status": "operator", "detail": "Optional snapshot saved. For live follower/leader, reconnect all boards and run ID detect/save."},
        ]
        return {
            "ok": True,
            "tool": "lerobot.ports.baseline",
            "mode": mode,
            "profile_id": profile.profile_id,
            "device_role": request.device_role,
            "camera_key": request.camera_key,
            "baseline": baseline,
            "saved_devices": self._saved_devices(profile.profile_id),
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def ports_detect(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Detect a device and persist it after role validation where available."""
        request = LeRobotDevicePortRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.ports.detect", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        memory = self._load_device_memory()
        profile_memory = self._profile_device_memory(memory, profile.profile_id)
        baseline_key = self._device_memory_key(request.device_role, request.camera_key)
        baseline = dict(profile_memory.get("baselines", {}).get(baseline_key, {}))
        camera_backend = self._normalize_camera_backend(request.camera_backend)
        is_realsense_camera = request.device_role == "camera" and camera_backend == LEROBOT_REALSENSE_TYPE
        if mode == "test":
            candidates = [
                self._default_realsense_identifier(request.camera_key)
                if is_realsense_camera
                else self._fake_camera_port(profile, request.camera_key)
                if request.device_role == "camera"
                else self._fake_port(profile, request.device_role)
            ]
            change_type = "test"
        else:
            now = self._scan_camera_candidates(request) if request.device_role == "camera" else self._scan_serial_ports()
            before = baseline.get("camera_ports" if request.device_role == "camera" else "serial_ports", [])
            added = sorted(set(now) - set(before))
            removed = sorted(set(before) - set(now))
            if mode == "live" and is_realsense_camera:
                # RealSense role selection is identity-based, not reconnect-delta based.
                # Keep an already-present configured camera eligible when another camera appears.
                candidates = list(now)
                change_type = "added" if added else "unchanged" if now else "removed"
            else:
                candidates = added or removed or list(now)
                change_type = "added" if added else "removed" if removed else "unchanged"
        chosen = request.port or ""
        role_verification: dict[str, Any] = {}
        role_verifications: list[dict[str, Any]] = []
        save_source = f"detect_delta:{change_type}"
        if not chosen and candidates and is_realsense_camera:
            preferred = self._preferred_realsense_identifier(request.camera_key)
            if preferred not in candidates:
                return self._error(
                    "lerobot.ports.detect",
                    mode,
                    profile.profile_id,
                    "LEROBOT_REALSENSE_ROLE_CAMERA_NOT_FOUND",
                    f"Expected RealSense camera for {request.camera_key} was not found. "
                    f"expected={preferred}; candidates={', '.join(map(str, candidates)) or 'none'}",
                )
            chosen = preferred
        live_robot_port = mode == "live" and request.device_role in {"follower", "leader"}
        if live_robot_port and not chosen and change_type == "removed":
            result = self._error(
                "lerobot.ports.detect",
                mode,
                profile.profile_id,
                "LEROBOT_PORT_REMOVED_UNVERIFIED",
                f"{request.device_role} port disappeared from the baseline. Reconnect it and run detect/save so the bridge can verify Dynamixel IDs.",
            )
            result.update(
                {
                    "device_role": request.device_role,
                    "camera_key": request.camera_key,
                    "candidates": candidates,
                    "change_type": change_type,
                    "saved_devices": self._saved_devices(profile.profile_id),
                }
            )
            return result
        if live_robot_port:
            validation_candidates = [chosen] if chosen else candidates
            selected, role_verification, role_verifications = self._select_serial_candidate_with_role_verification(
                validation_candidates,
                request.device_role,
            )
            if selected:
                chosen = selected
                save_source = f"id_detect:{role_verification.get('status') or 'verified'}"
            elif validation_candidates:
                result = self._error(
                    "lerobot.ports.detect",
                    mode,
                    profile.profile_id,
                    "LEROBOT_PORT_ROLE_NOT_VERIFIED",
                    f"No current serial port exposes Dynamixel IDs matching {request.device_role}.",
                )
                result.update(
                    {
                        "device_role": request.device_role,
                        "camera_key": request.camera_key,
                        "candidates": candidates,
                        "change_type": change_type,
                        "role_verifications": role_verifications,
                        "saved_devices": self._saved_devices(profile.profile_id),
                    }
                )
                return result
        if not chosen:
            chosen = candidates[0] if candidates else ""
        if not chosen:
            return self._error("lerobot.ports.detect", mode, profile.profile_id, "LEROBOT_PORT_NOT_FOUND", f"No candidate found for {request.device_role}.")
        raw_chosen = chosen
        if mode == "live" and request.device_role in {"follower", "leader"}:
            chosen = self._baseline_serial_identity_port(baseline, chosen)
        chosen = self._normalize_realsense_selected_identifier(request, chosen, mode=mode)
        camera_metadata: dict[str, Any] | None = None
        if mode == "live" and is_realsense_camera:
            entry = self._realsense_entry_for_identifier(chosen, self._scan_live_realsense_camera_entries())
            if entry:
                camera_metadata = self._realsense_usb_link_metadata(entry)
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            chosen,
            camera_key=request.camera_key,
            source=save_source,
            memory=memory,
            prefer_identity_link=mode == "live",
            raw_port=raw_chosen,
            camera_backend=request.camera_backend,
            camera_use_depth=request.camera_use_depth,
            camera_fps=request.camera_fps,
            camera_width=request.camera_width,
            camera_height=request.camera_height,
            camera_metadata=camera_metadata,
        )
        step_trace = [
            {"step": "COMPARE_BASELINE", "status": "ok", "detail": f"candidates={len(candidates)}"},
            {"step": "SAVE_DEVICE_PORT", "status": "ok", "detail": f"{request.device_role}={saved.get('port', chosen)}"},
        ]
        return {
            "ok": True,
            "tool": "lerobot.ports.detect",
            "mode": mode,
            "profile_id": profile.profile_id,
            "device_role": request.device_role,
            "camera_key": request.camera_key,
            "candidates": candidates,
            "change_type": change_type,
            "selected_port": saved.get("port", chosen),
            "raw_selected_port": raw_chosen,
            "role_verification": role_verification,
            "role_verifications": role_verifications,
            "saved_device": saved,
            "saved_devices": self._saved_devices(profile.profile_id),
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def ports_save(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist an explicitly selected leader/follower/camera port."""
        request = LeRobotDevicePortRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.ports.save", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        port = request.port or (f"/dev/video{request.camera_index}" if request.device_role == "camera" and request.camera_index is not None else "")
        camera_backend = self._normalize_camera_backend(request.camera_backend)
        is_realsense_camera = request.device_role == "camera" and camera_backend == LEROBOT_REALSENSE_TYPE
        if not port and is_realsense_camera:
            port = self._preferred_realsense_identifier(request.camera_key)
        if not port:
            return self._error("lerobot.ports.save", mode, profile.profile_id, "LEROBOT_PORT_REQUIRED", "A port or camera index is required.")
        raw_port = port
        port = self._normalize_realsense_selected_identifier(request, port, mode=mode)
        realsense_entries: list[dict[str, Any]] = []
        if mode == "live" and is_realsense_camera:
            realsense_entries = self._scan_live_realsense_camera_entries()
            if not self._realsense_identifier_available(port, realsense_entries):
                visible = self._realsense_visible_summary(realsense_entries)
                return self._error(
                    "lerobot.ports.save",
                    mode,
                    profile.profile_id,
                    "LEROBOT_REALSENSE_CAMERA_UNAVAILABLE",
                    f"Selected RealSense camera for {request.camera_key} is not available: {port}; visible RealSense devices: {visible}.",
                )
        camera_metadata: dict[str, Any] | None = None
        if mode == "live" and is_realsense_camera:
            entry = self._realsense_entry_for_identifier(port, realsense_entries)
            if entry:
                camera_metadata = self._realsense_usb_link_metadata(entry)
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            port,
            camera_key=request.camera_key,
            source="manual",
            prefer_identity_link=mode == "live",
            camera_backend=request.camera_backend,
            camera_use_depth=request.camera_use_depth,
            camera_fps=request.camera_fps,
            camera_width=request.camera_width,
            camera_height=request.camera_height,
            camera_metadata=camera_metadata,
        )
        step_trace = [{"step": "SAVE_DEVICE_PORT", "status": "ok", "detail": f"{request.device_role}={saved.get('port', port)}"}]
        return {
            "ok": True,
            "tool": "lerobot.ports.save",
            "mode": mode,
            "profile_id": profile.profile_id,
            "device_role": request.device_role,
            "camera_key": request.camera_key,
            "raw_selected_port": raw_port,
            "saved_device": saved,
            "saved_devices": self._saved_devices(profile.profile_id),
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def ports_delete(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Remove a saved LeRobot device entry; default cameras are protected."""
        request = LeRobotDevicePortRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.ports.delete", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        if request.device_role == "camera":
            camera_key = request.camera_key or "top"
            if camera_key in self._default_camera_keys(profile):
                return self._blocked(
                    "lerobot.ports.delete",
                    mode,
                    profile.profile_id,
                    "LEROBOT_DEFAULT_CAMERA_DELETE_BLOCKED",
                    f"Default camera cannot be deleted from GUI: {camera_key}",
                    "ports_delete",
                )
        data = self._load_device_memory()
        profile_memory = self._profile_device_memory(data, profile.profile_id)
        devices = profile_memory.setdefault("devices", {})
        removed: dict[str, Any] = {}
        if request.device_role == "camera":
            camera_key = request.camera_key or "top"
            cameras = devices.setdefault("cameras", {})
            if isinstance(cameras, dict):
                removed = dict(cameras.pop(camera_key, {}) or {})
            if camera_key == "top":
                devices.pop("camera", None)
            profile_memory.setdefault("baselines", {}).pop(self._device_memory_key("camera", camera_key), None)
        else:
            removed = dict(devices.pop(request.device_role, {}) or {})
            profile_memory.setdefault("baselines", {}).pop(self._device_memory_key(request.device_role), None)
        self._save_device_memory(data)
        step_trace = [
            {
                "step": "DELETE_DEVICE_PORT",
                "status": "ok",
                "detail": f"{request.device_role}:{request.camera_key if request.device_role == 'camera' else ''}",
            }
        ]
        return {
            "ok": True,
            "tool": "lerobot.ports.delete",
            "mode": mode,
            "profile_id": profile.profile_id,
            "device_role": request.device_role,
            "camera_key": request.camera_key,
            "removed_device": removed,
            "saved_devices": self._saved_devices(profile.profile_id),
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def camera_test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a camera capture smoke test without robot motion."""
        raw_payload = dict(payload or {})
        request = LeRobotDevicePortRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.camera.test", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        camera_key = request.camera_key or self._default_camera_key(profile)
        camera_port = request.port or self._device_port(profile, "camera", camera_key=camera_key)
        if mode == "live" and not request.confirm_live_execute:
            return self._blocked("lerobot.camera.test", mode, profile.profile_id, "LEROBOT_LIVE_CONFIRMATION_REQUIRED", "Live camera test requires confirm_live_execute=true.", "camera_test")
        if not camera_port:
            return self._error("lerobot.camera.test", mode, profile.profile_id, "LEROBOT_CAMERA_PORT_REQUIRED", "Save a camera port before testing capture.")
        runtime_camera_port = self._runtime_device_port(camera_port, "camera", live=mode == "live")
        saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
        request_camera = self._request_camera_metadata(request) if self._camera_request_has_explicit_metadata(raw_payload) else {}
        camera_device = {**saved_camera, **{key: value for key, value in request_camera.items() if value not in ("", None)}}
        capture = (
            self._fake_camera_capture(profile, camera_key, runtime_camera_port)
            if mode != "live"
            else self._live_camera_capture(profile, camera_key, runtime_camera_port, camera_device=camera_device)
        )
        if not capture.get("ok"):
            return self._error("lerobot.camera.test", mode, profile.profile_id, str(capture.get("failure_code")), str(capture.get("message")))
        capture = self._camera_release_contract(
            {
                **capture,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
                "release_status": "released",
            }
        )
        step_trace = [
            {"step": "RESOLVE_CAMERA_PORT", "status": "ok", "detail": f"{camera_port} -> {runtime_camera_port}"},
            {"step": "OPEN_CAMERA", "status": "ok", "detail": runtime_camera_port},
            {"step": "CAPTURE_FRAME", "status": "ok", "detail": str(capture.get("path", ""))},
            {
                "step": "RELEASE_CAMERA_PORT",
                "status": "ok" if capture.get("camera_returned_to_vla") else "warning",
                "detail": str(capture.get("release_status") or "released"),
            },
        ]
        return {
            "ok": True,
            "tool": "lerobot.camera.test",
            "mode": mode,
            "profile_id": profile.profile_id,
            "device_role": "camera",
            "camera_key": camera_key,
            "camera_port": runtime_camera_port,
            "camera_identity_port": camera_port,
            "port_released": bool(capture.get("port_released")),
            "camera_returned_to_vla": bool(capture.get("camera_returned_to_vla")),
            "camera_owner_after": str(capture.get("camera_owner_after") or ""),
            "release_status": str(capture.get("release_status") or ""),
            "capture": capture,
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    def active_robot_cam_capture(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the LeRobot ActiveCam routine: move follower, capture, and return pose/camera lease."""
        raw_payload = dict(payload or {})
        request = LeRobotSessionRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.active_robot_cam.capture", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        camera_key = str(raw_payload.get("camera_key") or request.active_robot_cam_primary_camera_key or "wrist").strip() or "wrist"
        if mode != "live":
            capture = self._camera_release_contract(
                {
                    **self._fake_camera_capture(profile, camera_key, self._fake_camera_port(profile, camera_key)),
                    "port_released": True,
                    "camera_returned_to_vla": True,
                    "camera_owner_after": "vla_runtime",
                    "release_status": "simulated",
                }
            )
            return self._active_robot_cam_capture_response(
                request=request,
                profile=profile,
                camera_key=camera_key,
                camera_identity_port=self._fake_camera_port(profile, camera_key),
                camera_port=self._fake_camera_port(profile, camera_key),
                capture=capture,
                driver_result={
                    "ok": True,
                    "status": "simulated",
                    "robot_pose_included": True,
                    "capture_pose": {"status": "simulated"},
                    "resume_pose": {"status": "simulated"},
                },
                command=[],
                env_overrides={},
            )
        if not request.confirm_live_execute:
            return self._blocked(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                "LEROBOT_LIVE_CONFIRMATION_REQUIRED",
                "Live ActiveCam capture requires confirm_live_execute=true.",
                "active_robot_cam_capture",
            )
        blocked = self._live_block_if_needed(
            tool="lerobot.active_robot_cam.capture",
            mode=mode,
            profile=profile,
            workflow="rollout",
            allow_key="allow_policy_rollout",
        )
        if blocked:
            return blocked
        port_blocked = self._live_port_block_if_needed(tool="lerobot.active_robot_cam.capture", mode=mode, profile=profile, workflow="rollout")
        if port_blocked:
            return port_blocked
        camera_identity_port = self._device_port(profile, "camera", camera_key=camera_key, allow_fake=False)
        if not camera_identity_port:
            return self._blocked(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                "LEROBOT_ACTIVE_CAM_PORT_REQUIRED",
                f"Save the ActiveCam camera port before live capture: {camera_key}.",
                "active_robot_cam_capture",
            )
        saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
        backend = self._normalize_camera_backend(saved_camera.get("backend", "opencv"))
        if backend == LEROBOT_REALSENSE_TYPE:
            realsense_entries = self._scan_live_realsense_camera_entries()
            identifier = str(saved_camera.get("serial_number_or_name") or camera_identity_port).strip()
            if not self._realsense_identifier_available(identifier, realsense_entries):
                visible = self._realsense_visible_summary(realsense_entries)
                return self._blocked(
                    "lerobot.active_robot_cam.capture",
                    mode,
                    profile.profile_id,
                    "LEROBOT_REALSENSE_CAMERA_UNAVAILABLE",
                    f"Saved ActiveCam camera is not available: {camera_key}={identifier}; visible RealSense devices: {visible}.",
                    "active_robot_cam_capture",
                )
        elif not self._camera_port_available(camera_identity_port):
            return self._blocked(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                "LEROBOT_CAMERA_PORT_UNAVAILABLE",
                f"Saved ActiveCam camera is not available: {camera_key}={camera_identity_port}.",
                "active_robot_cam_capture",
            )
        active_request = request.model_copy(
            update={
                "active_robot_cam_enabled": True,
                "active_robot_cam_primary_camera_key": camera_key,
                "camera_enabled": True,
            }
        )
        env_overrides = self._active_robot_cam_env_overrides(active_request)
        env_overrides.update(self._live_depth_env_overrides(active_request))
        env_overrides["ATR_LEROBOT_OBSERVATION_PIPELINE_ID"] = self._request_observation_pipeline_id(active_request, profile)
        env_overrides["ATR_LEROBOT_SPECIMEN_CAMERA_KEY"] = camera_key
        env_overrides["ATR_ACTIVE_ROBOT_CAM_PRIMARY_CAMERA_KEY"] = camera_key
        driver_payload = self._active_robot_cam_driver_payload(profile, active_request, camera_key=camera_key)
        script_path = self.config.repo_root / "scripts" / "lerobot_active_robot_cam_once.py"
        command = [
            self.config.conda_executable,
            "run",
            "-n",
            self.config.conda_env_name,
            "python",
            str(script_path),
            json.dumps(driver_payload, ensure_ascii=True),
        ]
        run_env = {**os.environ, **env_overrides, "PYTHONUNBUFFERED": "1"}
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                env=run_env,
                text=True,
                capture_output=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return self._error(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                "LEROBOT_ACTIVE_CAM_TIMEOUT",
                "ActiveCam pose/capture routine timed out.",
            )
        driver_result = self._json_object_from_stdout(completed.stdout)
        if not driver_result:
            return self._error(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                "LEROBOT_ACTIVE_CAM_OUTPUT_INVALID",
                f"ActiveCam runner did not return JSON; returncode={completed.returncode}; stderr={completed.stderr[-1000:]}",
            )
        detection_failure_code = self._active_robot_cam_specimen_detection_failure_code(driver_result)
        specimen_not_detected = bool(detection_failure_code)
        if (completed.returncode != 0 or not bool(driver_result.get("ok"))) and not specimen_not_detected:
            error_response = self._error(
                "lerobot.active_robot_cam.capture",
                mode,
                profile.profile_id,
                str(driver_result.get("failure_code") or "LEROBOT_ACTIVE_CAM_FAILED"),
                str(driver_result.get("message") or driver_result.get("status") or "ActiveCam capture failed."),
            )
            error_response["active_robot_cam_result"] = driver_result
            error_response["command_preview"] = command
            return error_response
        # The isolated child has exited, so the OS has closed every camera handle it owned.
        # Reopening RGB-D here only to prove release races with the next rollout owner.
        release_verification = {
            "ok": True,
            "status": "process_exit_verified",
            "method": "child_process_exit",
            "returncode": completed.returncode,
        }
        capture = self._camera_release_contract(
            {
                **dict(driver_result.get("capture") or {}),
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
                "release_status": "process_exit_verified",
            }
        )
        response = self._active_robot_cam_capture_response(
            request=active_request,
            profile=profile,
            camera_key=camera_key,
            camera_identity_port=camera_identity_port,
            camera_port=self._runtime_device_port(camera_identity_port, "camera", live=True),
            capture=capture,
            driver_result=driver_result,
            command=command,
            env_overrides=env_overrides,
            release_verification=release_verification,
        )
        if specimen_not_detected:
            response.update(
                {
                    "status": "not_detected",
                    "specimen_detected": False,
                    "placement_status": "outside" if detection_failure_code == "SPECIMEN_OUTSIDE_A4" else "not_detected",
                    "detection_failure_code": detection_failure_code,
                    "message": detection_failure_code,
                }
            )
        return response

    def _active_robot_cam_driver_payload(self, profile: RobotProfile, request: LeRobotSessionRequest, *, camera_key: str) -> dict[str, Any]:
        follower_port = self._device_port(profile, "follower", allow_fake=False)
        calibration_dir = self._profile_calibration_dir(profile)
        camera_identity_port = self._device_port(profile, "camera", camera_key=camera_key, allow_fake=False)
        runtime_camera_port = self._runtime_device_port(camera_identity_port, "camera", live=True)
        saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
        camera_config = self._camera_config_for_command(
            runtime_camera_port,
            saved_camera,
            camera_key=camera_key,
            request_fps=request.camera_fps or request.fps or profile.fps,
            include_color_format=True,
            include_depth_metadata=True,
        )
        return {
            "profile_id": profile.profile_id,
            "robot_type": profile.robot_type,
            "robot_id": profile.robot_id,
            "robot_port": self._runtime_device_port(follower_port, "follower", live=True),
            "calibration_dir": calibration_dir,
            "camera_key": camera_key,
            "cameras": {camera_key: camera_config},
            "reason": "spc_autoejection_verification",
        }

    def _active_robot_cam_capture_response(
        self,
        *,
        request: LeRobotSessionRequest,
        profile: RobotProfile,
        camera_key: str,
        camera_identity_port: str,
        camera_port: str,
        capture: dict[str, Any],
        driver_result: dict[str, Any],
        command: list[str],
        env_overrides: dict[str, str],
        release_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = request.runtime_mode or request.mode
        port_released = bool(capture.get("port_released", True))
        camera_returned = bool(capture.get("camera_returned_to_vla", port_released))
        step_trace = [
            {"step": "RESOLVE_ACTIVE_CAM", "status": "ok", "detail": f"{camera_key}={camera_identity_port}"},
            {"step": "MOVE_TO_CAPTURE_POSE", "status": "ok", "detail": str((driver_result.get("capture_pose") or {}).get("status") or "applied")},
            {"step": "CAPTURE_FRAME", "status": "ok", "detail": str(capture.get("path") or "")},
            {"step": "RETURN_ROBOT_POSE", "status": "ok", "detail": str((driver_result.get("resume_pose") or {}).get("status") or "applied")},
            {"step": "RELEASE_CAMERA_PORT", "status": "ok" if camera_returned else "warning", "detail": str(capture.get("release_status") or "released")},
        ]
        return {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": mode,
            "runtime_mode": mode,
            "profile_id": profile.profile_id,
            "workflow": "active_robot_cam_capture",
            "status": str(driver_result.get("status") or "applied"),
            "camera_key": camera_key,
            "camera_port": camera_port,
            "camera_identity_port": camera_identity_port,
            "robot_pose_included": bool(driver_result.get("robot_pose_included", True)),
            "capture_pose": dict(driver_result.get("capture_pose") or driver_result.get("capture_wait") or {}),
            "resume_pose": dict(driver_result.get("resume_pose") or {}),
            "port_released": port_released,
            "camera_returned_to_vla": camera_returned,
            "camera_owner_after": str(capture.get("camera_owner_after") or ("vla_runtime" if camera_returned else "unknown")),
            "release_status": str(capture.get("release_status") or ""),
            "release_verification": dict(release_verification or {}),
            "capture": capture,
            "active_robot_cam_result": driver_result,
            "command_preview": command,
            "env_overrides": env_overrides,
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

    @staticmethod
    def _active_robot_cam_specimen_detection_failure_code(driver_result: dict[str, Any]) -> str:
        """Return a placement-negative detector code when a valid evidence frame exists."""
        capture = driver_result.get("capture") if isinstance(driver_result.get("capture"), dict) else {}
        if not bool(capture.get("ok") and capture.get("path")):
            return ""

        detected_codes: set[str] = set()
        pending: list[Any] = [driver_result]
        while pending:
            current = pending.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if key in {"failure_code", "message", "status"}:
                        marker = str(value).strip().lower()
                        if "specimen_outside_a4" in marker:
                            detected_codes.add("SPECIMEN_OUTSIDE_A4")
                        elif "specimen_not_detected" in marker:
                            detected_codes.add("SPECIMEN_NOT_DETECTED")
                    if isinstance(value, (dict, list)):
                        pending.append(value)
            elif isinstance(current, list):
                pending.extend(current)
        if "SPECIMEN_OUTSIDE_A4" in detected_codes:
            return "SPECIMEN_OUTSIDE_A4"
        if "SPECIMEN_NOT_DETECTED" in detected_codes:
            return "SPECIMEN_NOT_DETECTED"
        return ""

    @classmethod
    def _active_robot_cam_specimen_not_detected(cls, driver_result: dict[str, Any]) -> bool:
        """Recognize a valid placement-negative observation without treating it as a bridge failure."""
        return bool(cls._active_robot_cam_specimen_detection_failure_code(driver_result))

    @staticmethod
    def _json_object_from_stdout(stdout: str) -> dict[str, Any] | None:
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _camera_release_contract(capture: dict[str, Any]) -> dict[str, Any]:
        """Normalize one-shot camera capture results so downstream VLA can reclaim the camera."""
        normalized = dict(capture or {})
        released = bool(normalized.get("port_released", False))
        owner_after = str(normalized.get("camera_owner_after") or ("vla_runtime" if released else "unknown"))
        returned_to_vla = bool(normalized.get("camera_returned_to_vla", released and owner_after == "vla_runtime"))
        normalized["port_released"] = released
        normalized["camera_owner_after"] = owner_after
        normalized["camera_returned_to_vla"] = returned_to_vla
        normalized["release_status"] = str(normalized.get("release_status") or ("released" if returned_to_vla else "release_unverified"))
        return normalized

    @staticmethod
    def _camera_request_has_explicit_metadata(payload: dict[str, Any]) -> bool:
        """Return true only when the caller intentionally overrides saved camera metadata."""
        return any(
            key in payload and payload.get(key) not in ("", None)
            for key in ("camera_backend", "camera_use_depth", "camera_fps", "camera_width", "camera_height")
        )

    def teleoperate_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start a deterministic fake teleoperation session."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        connect_detail = "leader/follower ports accepted" if mode == "live" else "fake leader/follower connected"
        active_detail = "LeRobot teleoperation process starting" if mode == "live" else "synthetic teleoperation session active"
        result = self._start_session(
            tool="lerobot.teleoperate.start",
            workflow="teleoperate",
            request=request,
            status="TELEOP_ACTIVE",
            trace=[
                ("PRECHECK", "ok", "profile and ports valid"),
                ("CONNECTING", "ok", connect_detail),
                ("TELEOP_ACTIVE", "active", active_detail),
            ],
            allow_key="allow_teleoperation",
            extra_args=[
                f"--fps={request.fps or profile.fps if (profile := self._profile(request.profile_id)) else ''}",
                f"--teleop_time_s={request.teleop_time_s}" if request.teleop_time_s is not None else "",
                f"--display_data={_bool_arg(request.display_data)}",
            ],
            event_payload=payload or {},
        )
        return self._attach_isaac_mirror_loop_if_requested(result, payload or {}, workflow="teleoperate")

    def teleoperate_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop a teleoperation session idempotently."""
        stopped = self._stop_session("lerobot.teleoperate.stop", payload or {}, "teleoperate")
        if self._uses_in_process_isaac_mirror(stopped):
            stopped["isaac_mirror_stop"] = self._in_process_isaac_mirror_stop_summary(stopped)
        else:
            stopped["isaac_mirror_stop"] = self.mirror_loop_stop(
                {
                    **dict(payload or {}),
                    "isaac_mirror_attached_to_session_id": stopped.get("session_id", ""),
                }
            )
        return stopped

    def teleoperate_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return teleoperation session status."""
        return self._session_status("lerobot.teleoperate.status", payload or {}, "teleoperate")

    def record_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start a LeRobot recording session."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        request, effective_resume, ready_detail = self._record_start_request(request)
        active_detail = "LeRobot recording process starting" if mode == "live" else "synthetic recording session active"
        result = self._start_session(
            tool="lerobot.record.start",
            workflow="record",
            request=request,
            status="RECORDING",
            trace=[
                ("READY", "ok", ready_detail),
                ("WARMUP", "ok", f"warmup_s={request.warmup_s}"),
                ("RECORDING", "active", active_detail),
            ],
            allow_key="allow_recording",
            extra_args=[
                f"--dataset.repo_id={request.dataset_repo_id or 'local/fake_lerobot_dataset'}",
                f"--dataset.root={self._dataset_path_for(request)}",
                f"--dataset.single_task={request.task_instruction or 'Pick up the cylinder'}",
                f"--dataset.fps={request.fps or ''}",
                f"--dataset.episode_time_s={request.episode_s}",
                f"--dataset.reset_time_s={request.reset_s}",
                f"--dataset.num_episodes={request.num_episodes}",
                f"--dataset.push_to_hub={_bool_arg(request.push_to_hub)}",
                f"--display_data={_bool_arg(request.display_data)}",
                f"--resume={_bool_arg(effective_resume)}",
            ],
            event_payload=payload or {},
        )
        return self._attach_isaac_mirror_loop_if_requested(result, payload or {}, workflow="record")

    def record_control(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply a deterministic recording control action."""
        request = LeRobotRecordControlRequest.model_validate(payload or {})
        if request.action == "stop":
            stopped = self._stop_session("lerobot.record.control", payload or {}, "record", stopped_status="STOPPED")
            if self._uses_in_process_isaac_mirror(stopped):
                stopped["isaac_mirror_stop"] = self._in_process_isaac_mirror_stop_summary(stopped)
            else:
                stopped["isaac_mirror_stop"] = self.mirror_loop_stop(
                    {
                        **dict(payload or {}),
                        "isaac_mirror_attached_to_session_id": stopped.get("session_id", ""),
                    }
                )
            self._refresh_record_isaac_mirror_metadata(stopped.get("session_id", ""), stopped["isaac_mirror_stop"])
            session = self._resolve_session(str(stopped.get("session_id") or ""), "record", prefer_active=False)
            if session is not None and self._record_session_has_isaac_rgbd_post_render_candidates(session):
                self._start_isaac_rgbd_post_render_after_record(session)
                if isinstance(session.get("isaac_rgbd_post_render"), dict):
                    stopped["isaac_rgbd_post_render"] = dict(session["isaac_rgbd_post_render"])
                    stopped["isaac_rgbd_post_render_auto_started"] = bool(session.get("isaac_rgbd_post_render_auto_started"))
                    stopped["step_trace"] = list(session.get("step_trace", stopped.get("step_trace", [])))
                    stopped["events"] = list(stopped["step_trace"])
            extra_cleanup = self.cleanup_all_lerobot_processes(exclude_workflows={"record"})
            if extra_cleanup:
                step_trace = list(stopped.get("step_trace", [])) + extra_cleanup
                stopped["step_trace"] = step_trace
                stopped["events"] = step_trace
            stopped["action"] = "stop"
            return stopped
        mode = request.runtime_mode or request.mode
        session = self._resolve_session(request.session_id, "record", prefer_active=True)
        profile_id = str(session.get("profile_id") if session else request.profile_id or self._selected_profile_id)
        if session is None:
            return self._error("lerobot.record.control", mode, profile_id, "LEROBOT_SESSION_NOT_FOUND", "Recording session not found.")
        if mode == "live":
            self._refresh_process_status(session)
            if session.get("returncode") is not None:
                return self._error(
                    "lerobot.record.control",
                    mode,
                    profile_id,
                    "LEROBOT_RECORD_NOT_ACTIVE",
                    f"Recording process is not active; current status={session.get('status')}, returncode={session.get('returncode')}.",
                )
            phase = self._record_log_phase(session)
            if request.action in {"next", "retry"} and phase == "saving":
                return self._error(
                    "lerobot.record.control",
                    mode,
                    profile_id,
                    "LEROBOT_RECORD_CONTROL_WAIT_FOR_NEXT_PHASE",
                    "LeRobot is saving/encoding the previous episode. Wait until the next 'Recording episode' or 'Reset the environment' message before sending another right/left-arrow control.",
                )
            control = self._send_lerobot_record_control_key(request.action)
            if not control.get("ok"):
                return self._error("lerobot.record.control", mode, profile_id, str(control.get("failure_code")), str(control.get("message")))
            action_status = "FINISHING" if request.action == "finish" else "RECORDING"
            session["status"] = action_status
            step_trace = [
                {"step": "SEND_LEROBOT_RECORD_CONTROL", "status": "ok", "detail": str(control.get("detail", request.action))},
                {"step": request.action.upper(), "status": "active", "detail": action_status},
            ]
            session.setdefault("step_trace", []).extend(step_trace)
            self._emit_trace(payload, "lerobot.record.control", step_trace, profile_id, mode, session["session_id"])
            return self._session_response("lerobot.record.control", mode, session, step_trace, action=request.action, control=control)
        action_status = {
            "stop": "STOPPED",
            "retry": "READY",
            "next": "EPISODE_COMPLETE",
            "finish": "DATASET_COMPLETE",
        }[request.action]
        session["status"] = action_status
        step_trace = [
            {"step": request.action.upper(), "status": "ok", "detail": action_status},
        ]
        session.setdefault("step_trace", []).extend(step_trace)
        self._emit_trace(payload, "lerobot.record.control", step_trace, profile_id, mode, session["session_id"])
        return self._session_response("lerobot.record.control", mode, session, step_trace, action=request.action)

    def record_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return recording session status."""
        return self._session_status("lerobot.record.status", payload or {}, "record")

    def train_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start LeRobot policy training in test or gated live mode."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.train.start", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        if mode == "live":
            active_session = self._latest_active_session("train")
            if active_session is not None:
                return self._session_response(
                    "lerobot.train.start",
                    mode,
                    active_session,
                    list(active_session.get("step_trace", [])),
                    idempotent=True,
                    message="Training is already active; returning the existing train session instead of starting a duplicate process.",
                )
        try:
            request, runtime_detail = self._train_request_with_policy_runtime(request)
            request, dataset_detail = self._train_request_with_local_dataset(request)
            raw_depth_normalization = self._normalize_train_raw_depth_sidecar(request)
            if raw_depth_normalization.get("changed"):
                dataset_detail = f"{dataset_detail}; raw depth indices normalized"
            pipeline_block = self._dataset_pipeline_block_if_needed("lerobot.train.start", mode, profile, request, "train")
            if pipeline_block:
                return pipeline_block
            request, dataset_version_detail = self._train_request_with_pi05_dataset_version(request)
            metadata_detail = self._ensure_train_dataset_jsonl_metadata_compat(request)
            pipeline_block = self._dataset_pipeline_block_if_needed("lerobot.train.start", mode, profile, request, "train")
            if pipeline_block:
                return pipeline_block
            augmentation_qa = self._train_isaac_augmentation_qa_preflight(request)
            if augmentation_qa.get("blocked"):
                return self._blocked(
                    "lerobot.train.start",
                    mode,
                    profile.profile_id,
                    "LEROBOT_ISAAC_AUGMENTATION_QA_BLOCKED",
                    str(augmentation_qa.get("message") or "Isaac augmentation QA blocked training."),
                    "train",
                )
            request, train_detail = self._train_request_with_output_dir(profile, request)
            request, resume_detail = self._train_request_with_resume_config(profile, request)
            train_args = self._train_args(profile, request)
        except ValueError as exc:
            return self._error("lerobot.train.start", mode, profile.profile_id, "LEROBOT_TRAIN_CONFIG_INVALID", str(exc))
        status = "COMPLETED" if mode != "live" else "TRAINING"
        trace = [
            ("PRECHECK", "ok", f"{train_detail}; {runtime_detail}; {resume_detail}"),
            ("LOAD_DATASET", "ok", f"{dataset_detail}; {dataset_version_detail}; {metadata_detail}"),
            *list(augmentation_qa.get("trace", [])),
            ("TRAINING", "ok" if mode != "live" else "active", f"steps={request.steps} batch_size={request.batch_size}"),
            ("CHECKPOINT", "ok" if mode != "live" else "pending", self._train_checkpoint_path(profile, request)),
        ]
        if mode != "live":
            trace.append(("COMPLETED", "ok", "fake training complete"))
        return self._start_session(
            tool="lerobot.train.start",
            workflow="train",
            request=request,
            status=status,
            trace=trace,
            allow_key="allow_training",
            extra_args=train_args,
            event_payload=payload or {},
        )

    def train_cancel(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Cancel training idempotently."""
        return self._stop_session("lerobot.train.cancel", payload or {}, "train", stopped_status="CANCELLED")

    def train_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return training status."""
        return self._session_status("lerobot.train.status", payload or {}, "train")

    def rollout_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start LeRobot policy inference/rollout."""
        raw_payload = dict(payload or {})
        request = LeRobotSessionRequest.model_validate(raw_payload)
        unsafe = self._unsafe_arguments([request.policy_checkpoint_path, request.policy_path, request.policy_repo_id])
        if unsafe:
            return self._error("lerobot.rollout.start", request.runtime_mode or request.mode, request.profile_id, "LEROBOT_UNSAFE_ARGUMENT", f"Unsafe command argument rejected: {unsafe}")
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.rollout.start", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        active_guard = self._rollout_active_guard(request, mode)
        if active_guard:
            return active_guard
        blocked = self._live_block_if_needed(
            tool="lerobot.rollout.start",
            mode=mode,
            profile=profile,
            workflow="rollout",
            allow_key="allow_policy_rollout",
        )
        if blocked:
            return blocked
        try:
            request = self._rollout_request_with_local_policy(request)
            request = self._rollout_request_with_eval_dataset(request)
            request = self._rollout_request_with_manual_stop(request)
            request, _, dataset_detail = self._record_start_request(request)
        except ValueError as exc:
            return self._error("lerobot.rollout.start", request.runtime_mode or request.mode, request.profile_id, "LEROBOT_POLICY_CONFIG_INVALID", str(exc))
        policy_ref = self._policy_ref(request)
        if not policy_ref and (request.runtime_mode or request.mode) == "live":
            return self._error("lerobot.rollout.start", "live", request.profile_id, "LEROBOT_POLICY_PATH_REQUIRED", "Live rollout requires policy_path, policy_checkpoint_path, or policy_repo_id.")
        policy_type = self._canonical_policy_type(request.policy_type or "act")
        is_pi05 = self._is_pi05_policy(policy_type)
        policy_args = [f"--policy.path={policy_ref or str(self.config.fake_checkpoint_root / 'policy.ckpt')}"]
        device_override = str(raw_payload.get("device") or "").strip()
        if device_override:
            if is_pi05:
                policy_args.append(f"--device={device_override}")
                policy_args.append(f"--policy.device={device_override}")
            else:
                policy_args.append(f"--policy.device={device_override}")
        inference_type = str(request.rollout_inference_type or "").strip().lower()
        if is_pi05 and not inference_type:
            inference_type = "rtc"
        if is_pi05:
            rtc_enabled = inference_type != "sync"
            policy_args.append(f"--rtc.enabled={_bool_arg(rtc_enabled)}")
            if rtc_enabled and request.rollout_rtc_execution_horizon is not None:
                policy_args.append(f"--rtc.execution_horizon={int(request.rollout_rtc_execution_horizon)}")
            if rtc_enabled and request.rollout_rtc_max_guidance_weight is not None:
                policy_args.append(f"--rtc.max_guidance_weight={float(request.rollout_rtc_max_guidance_weight)}")
            if rtc_enabled and request.rollout_action_queue_size_to_get_new_actions is not None:
                queue_size = max(1, int(request.rollout_action_queue_size_to_get_new_actions))
                policy_args.append(f"--action_queue_size_to_get_new_actions={queue_size}")
        elif inference_type:
            policy_args.append(f"--inference.type={inference_type}")
            if inference_type == "rtc":
                if request.rollout_rtc_execution_horizon is not None:
                    policy_args.append(f"--inference.rtc.execution_horizon={int(request.rollout_rtc_execution_horizon)}")
                if request.rollout_rtc_max_guidance_weight is not None:
                    policy_args.append(f"--inference.rtc.max_guidance_weight={float(request.rollout_rtc_max_guidance_weight)}")
        if "policy_use_amp" in raw_payload:
            policy_args.append(f"--policy.use_amp={_bool_arg(request.policy_use_amp)}")
        if request.rollout_temporal_ensemble and not is_pi05 and not self._is_vla_policy(policy_type):
            coeff = float(request.rollout_temporal_ensemble_coeff or 0.01)
            policy_args.append(f"--policy.temporal_ensemble_coeff={coeff}")
            policy_args.append("--policy.n_action_steps=1")
        if request.rollout_action_clamp:
            max_relative_target = max(1, int(round(float(request.rollout_max_relative_target or 5))))
            policy_args.append(f"--robot.max_relative_target={max_relative_target}")
        task_instruction = self._rollout_task_instruction(request, is_pi05=is_pi05)
        if is_pi05:
            duration_source = request.max_duration_s if request.max_duration_s and request.max_duration_s > 0 else request.episode_s
            duration = max(1, int(round(float(duration_source or 1))))
            rollout_extra_args = policy_args + [
                f"--fps={request.fps or profile.fps or 30}",
                f"--task={task_instruction}",
                f"--duration={duration}",
            ]
        else:
            rollout_extra_args = policy_args + [
                f"--dataset.repo_id={request.dataset_repo_id or 'local/eval_lerobot_policy'}",
                f"--dataset.root={self._dataset_path_for(request)}",
                f"--dataset.single_task={task_instruction}",
                f"--dataset.fps={request.fps or ''}",
                f"--dataset.episode_time_s={request.episode_s}",
                f"--dataset.num_episodes={request.num_episodes}",
                f"--dataset.push_to_hub={_bool_arg(request.push_to_hub)}",
                f"--display_data={_bool_arg(request.display_data)}",
            ]
        return self._start_session(
            tool="lerobot.rollout.start",
            workflow="rollout",
            request=request,
            status="POLICY_ACTIVE",
            trace=[
                ("PRECHECK", "ok", "policy request accepted"),
                ("LOAD_POLICY", "ok", policy_ref or "fake policy"),
                ("PREPARE_ROLLOUT_DATASET", "ok", dataset_detail),
                ("POLICY_ACTIVE", "active", "policy rollout active"),
            ],
            allow_key="allow_policy_rollout",
            extra_args=rollout_extra_args,
            event_payload=payload or {},
        )

    def _rollout_active_guard(self, request: LeRobotSessionRequest, mode: str) -> dict[str, Any] | None:
        """Prevent duplicate live rollout/inference processes from sharing robot IO."""
        if mode != "live":
            return None
        active = self._latest_active_session("rollout")
        if active is None:
            return None
        active_session_id = str(active.get("session_id") or "")
        if request.session_id and request.session_id == active_session_id:
            step_trace = [
                {
                    "step": "ROLLOUT_ACTIVE_GUARD",
                    "status": "ok",
                    "detail": f"rollout session already active: {active_session_id}",
                }
            ]
            return self._session_response(
                "lerobot.rollout.start",
                mode,
                active,
                step_trace,
                idempotent=True,
                message="Rollout is already active; returning the existing session instead of starting another process.",
            )
        step_trace = [
            {
                "step": "ROLLOUT_ACTIVE_GUARD",
                "status": "blocked",
                "detail": f"active_session_id={active_session_id} profile={active.get('profile_id', '')}",
            }
        ]
        return self._session_response(
            "lerobot.rollout.start",
            mode,
            active,
            step_trace,
            ok=False,
            failure_code="LEROBOT_ROLLOUT_ALREADY_ACTIVE",
            guard_status="blocked",
            blocked_by_session_id=active_session_id,
            message="Another LeRobot rollout is already active. Stop the active rollout before starting a new inference session.",
            error="Another LeRobot rollout is already active. Stop the active rollout before starting a new inference session.",
        )

    def rollout_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop all rollout/inference sessions and stale rollout subprocesses idempotently."""
        return self._stop_all_workflow_sessions("lerobot.rollout.stop", payload or {}, "rollout")

    def rollout_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return rollout status."""
        return self._session_status("lerobot.rollout.status", payload or {}, "rollout")

    def visualize_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start LeRobot's dataset visualizer."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.visualize.start", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        try:
            viz_args, viz_info = self._visualization_args(request)
        except ValueError as exc:
            return self._error("lerobot.visualize.start", mode, profile.profile_id, "LEROBOT_VISUALIZATION_CONFIG_INVALID", str(exc))
        unsafe = self._unsafe_arguments(viz_args)
        if unsafe:
            return self._error("lerobot.visualize.start", mode, profile.profile_id, "LEROBOT_UNSAFE_ARGUMENT", f"Unsafe command argument rejected: {unsafe}")

        session_id = request.session_id or self._new_session_id("visualize")
        command_preview = self._visualization_command(request, viz_info, viz_args)
        step_trace = [
            {"step": "PRECHECK", "status": "ok", "detail": "LeRobot visualization config accepted"},
            {"step": "LOAD_DATASET", "status": "ok", "detail": str(viz_info.get("dataset_path", ""))},
            {"step": "START_VISUALIZER", "status": "active", "detail": f"tool={viz_info.get('tool')} episode={viz_info.get('episode_index')} episodes={viz_info.get('episode_indices')}"},
        ]
        session = {
            "session_id": session_id,
            "tool": "lerobot.visualize.start",
            "workflow": "visualize",
            "mode": mode,
            "profile_id": profile.profile_id,
            "status": "VISUALIZING",
            "command_preview": command_preview,
            "step_trace": step_trace,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_path": str(viz_info.get("dataset_path", "")),
            "checkpoint_path": "",
            "log_path": "",
            "pid": None,
            "returncode": None,
            "visualization": viz_info,
        }
        live_start = self._start_live_process(session_id=session_id, command=command_preview)
        if live_start.get("session_updates"):
            session.update(dict(live_start["session_updates"]))
        if not live_start["ok"]:
            session["status"] = "FAILED"
            failure_trace = {
                "step": str(live_start.get("failure_code", "PROCESS_START_FAILED")),
                "status": "failed",
                "detail": str(live_start.get("message", "LeRobot visualization process failed during startup.")),
            }
            step_trace.append(failure_trace)
            session["step_trace"] = step_trace
            self._sessions[session_id] = session
            return self._session_response(
                "lerobot.visualize.start",
                mode,
                session,
                step_trace,
                ok=False,
                failure_code=str(live_start.get("failure_code", "LEROBOT_PROCESS_START_FAILED")),
                message=str(live_start.get("message", "")),
                error=str(live_start.get("message", "")),
                visualization=viz_info,
            )
        if live_start.get("completed_during_startup"):
            session["status"] = "COMPLETED"
            step_trace.append({"step": "PROCESS_COMPLETED", "status": "ok", "detail": f"returncode={session.get('returncode')}"})
        else:
            step_trace.append({"step": "PROCESS_STARTED", "status": "active", "detail": f"pid={session.get('pid')}"})
        self._sessions[session_id] = session
        self._emit_trace(payload or request.model_dump(), "lerobot.visualize.start", step_trace, profile.profile_id, mode, session_id)
        return self._session_response("lerobot.visualize.start", mode, session, step_trace, visualization=viz_info)

    def visualize_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop LeRobot dataset visualization idempotently."""
        return self._stop_session("lerobot.visualize.stop", payload or {}, "visualize")

    def visualize_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return LeRobot dataset visualization status."""
        return self._session_status("lerobot.visualize.status", payload or {}, "visualize", prefer_active=True)

    def wandb_local_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start a local W&B Server instance for LeRobot training dashboards."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        url = self._wandb_local_url(request)
        port = self._wandb_local_port(request)
        command = self._wandb_local_command("start", port)
        step_trace = [{"step": "WANDB_LOCAL_COMMAND", "status": "ok", "detail": " ".join(command)}]
        session_id = request.session_id or self._new_session_id("wandb-local")
        session = {
            "session_id": session_id,
            "workflow": "wandb_local",
            "profile_id": request.profile_id or self._selected_profile_id,
            "observation_pipeline_id": self._selected_observation_pipeline_id,
            "mode": mode,
            "status": "WANDB_LOCAL_READY" if mode == "test" else "STARTING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "command_preview": command,
            "url": url,
            "port": port,
            "step_trace": step_trace,
            "events": step_trace,
        }
        env_overrides = {"WANDB_BASE_URL": url, "DOCKER_DEFAULT_PLATFORM": "linux/amd64"}

        def fail_start(failure_code: str, message: str) -> dict[str, Any]:
            session["status"] = "FAILED"
            session.setdefault("step_trace", []).append({"step": failure_code, "status": "failed", "detail": message})
            self._sessions[session_id] = session
            return self._session_response(
                "lerobot.wandb_local.start",
                mode,
                session,
                session["step_trace"],
                ok=False,
                failure_code=failure_code,
                message=message,
                error=message,
                url=url,
                port=port,
            )

        def start_process(step_name: str) -> dict[str, Any]:
            live_start = self._start_live_process(session_id=session_id, command=command, env_overrides=env_overrides)
            if live_start.get("session_updates"):
                session.update(dict(live_start["session_updates"]))
            if not live_start["ok"]:
                message = str(live_start.get("message", "Local W&B server failed during startup."))
                return {
                    "ok": False,
                    "response": fail_start(str(live_start.get("failure_code", "WANDB_LOCAL_PROCESS_START_FAILED")), message),
                }
            session.setdefault("step_trace", []).append({"step": step_name, "status": "active", "detail": f"pid={session.get('pid')}"})
            return {"ok": True}

        def stop_failed_process_for_retry() -> None:
            process = self._processes.get(session_id)
            if process and process.poll() is None:
                self._terminate_live_process(process, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._terminate_live_process(process, signal.SIGKILL)
                    process.wait(timeout=5)
            if process:
                session["returncode"] = process.returncode
                self._processes.pop(session_id, None)
            self._close_log_handle(session_id)

        if mode != "test":
            if self._wandb_local_port_ready(url):
                session["status"] = "WANDB_LOCAL_RUNNING"
                session.setdefault("step_trace", []).append({"step": "PORT_READY", "status": "ok", "detail": url})
                self._sessions[session_id] = session
                return self._session_response("lerobot.wandb_local.start", mode, session, session["step_trace"], url=url, port=port, idempotent=True)
            started = start_process("PROCESS_STARTED")
            if not started["ok"]:
                return dict(started["response"])
            ready, failure = self._wait_for_wandb_local_ready(url, session, timeout_s=45.0)
            if ready:
                session["status"] = "WANDB_LOCAL_RUNNING"
                session.setdefault("step_trace", []).append({"step": "PORT_READY", "status": "ok", "detail": url})
            elif failure:
                failure_code, message = failure
                if failure_code == "WANDB_LOCAL_PLATFORM_EMULATION_REQUIRED":
                    install = self._install_wandb_local_amd64_binfmt()
                    install_detail = str(install.get("output") or install.get("error") or " ".join(map(str, install.get("command", []))))
                    if not bool(install.get("ok")):
                        session.setdefault("step_trace", []).append(
                            {"step": "WANDB_LOCAL_AMD64_BINFMT", "status": "failed", "detail": install_detail}
                        )
                        return fail_start(failure_code, message)
                    session.setdefault("step_trace", []).append({"step": "WANDB_LOCAL_AMD64_BINFMT", "status": "ok", "detail": install_detail})
                    stop_failed_process_for_retry()
                    restarted = start_process("PROCESS_RESTARTED")
                    if not restarted["ok"]:
                        return dict(restarted["response"])
                    ready, failure = self._wait_for_wandb_local_ready(url, session, timeout_s=45.0)
                    if ready:
                        session["status"] = "WANDB_LOCAL_RUNNING"
                        session.setdefault("step_trace", []).append({"step": "PORT_READY", "status": "ok", "detail": url})
                    elif failure:
                        failure_code, message = failure
                        return fail_start(failure_code, message)
                    else:
                        session["status"] = "STARTING"
                        session.setdefault("step_trace", []).append({"step": "PORT_WAITING", "status": "active", "detail": url})
                else:
                    return fail_start(failure_code, message)
            else:
                session["status"] = "STARTING"
                session.setdefault("step_trace", []).append({"step": "PORT_WAITING", "status": "active", "detail": url})
        self._sessions[session_id] = session
        return self._session_response("lerobot.wandb_local.start", mode, session, session["step_trace"], url=url, port=port)

    def wandb_local_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop the tracked local W&B Server process and ask W&B to stop its local container."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        result = self._stop_all_workflow_sessions("lerobot.wandb_local.stop", payload or {}, "wandb_local")
        stop_command = self._wandb_local_command("stop", self._wandb_local_port(request))
        result["stop_command_preview"] = stop_command
        if mode != "test":
            try:
                completed = subprocess.run(stop_command, cwd=str(self.config.repo_root), text=True, capture_output=True, timeout=60)
                result["stop_returncode"] = completed.returncode
                result["stop_output"] = (completed.stdout or completed.stderr or "").strip()[-2000:]
            except (OSError, subprocess.TimeoutExpired) as exc:
                result["ok"] = False
                result["status"] = "FAILED"
                result["error"] = str(exc)
        result["url"] = self._wandb_local_url(request)
        return result

    def wandb_local_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return local W&B Server status tracked by this bridge."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        result = self._session_status("lerobot.wandb_local.status", payload or {}, "wandb_local")
        url = self._wandb_local_url(request)
        result["url"] = url
        result["port"] = self._wandb_local_port(request)
        failure = self._wandb_local_failure_from_log(str(result.get("log_tail") or ""))
        if failure:
            failure_code, message = failure
            result.update({"ok": False, "status": "FAILED", "failure_code": failure_code, "message": message, "error": message})
        elif self._wandb_local_port_ready(url):
            result.update({"ok": True, "status": "WANDB_LOCAL_RUNNING"})
        elif str(result.get("status") or "").upper() in {"COMPLETED", "IDLE"}:
            message = f"Local W&B server is not listening at {url}."
            result.update({"ok": False, "status": "FAILED", "failure_code": "WANDB_LOCAL_NOT_LISTENING", "message": message, "error": message})
        return result

    def dataset_inspect(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return LeRobot dataset metadata from the selected local dataset path."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.dataset.inspect", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        dataset_path = request.dataset_path or self._dataset_path_for(request)
        dataset_dir = _resolve_path(self.config.repo_root, dataset_path)
        info_path = dataset_dir / "meta" / "info.json"
        info: dict[str, Any] = {}
        if info_path.is_file():
            try:
                loaded = json.loads(info_path.read_text(encoding="utf-8"))
                info = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                info = {}
        features = info.get("features") if isinstance(info.get("features"), dict) else {}
        feature_names = sorted(str(key) for key in features)
        depth_features = sorted(key for key in feature_names if key.startswith("observation.images.") and "depth" in key)
        pipeline_metadata = self._read_dataset_pipeline_metadata(dataset_dir)
        metadata_profile_id = str(pipeline_metadata.get("profile_id") or "").strip()
        restored_profile = self._profile(metadata_profile_id) if metadata_profile_id else None
        effective_profile = restored_profile or profile
        metadata_files = [
            rel
            for rel in (
                "meta/info.json",
                "meta/atr_pipeline.json",
                "meta/tasks.parquet",
                "meta/tasks.jsonl",
                "meta/episodes.jsonl",
                "meta/episodes_stats.jsonl",
                "meta/stats.json",
            )
            if (dataset_dir / rel).is_file()
        ]
        requested_pipeline_id = self._request_observation_pipeline_id(request, effective_profile)
        dataset_payload = {
            "path": dataset_path,
            "root": request.dataset_root or str(self.config.dataset_root),
            "robot_profile_id": effective_profile.profile_id,
            "robot_type": str(info.get("robot_type") or effective_profile.robot_type),
            "teleop_type": effective_profile.teleop_type,
            "observation_pipeline_id": pipeline_metadata["observation_pipeline_id"],
            "requested_observation_pipeline_id": requested_pipeline_id,
            "observation_pipeline_source": pipeline_metadata["source"],
            "profile_restored_from_metadata": bool(restored_profile is not None),
            "pipeline_metadata_path": str(pipeline_metadata.get("path") or ""),
            "episode_count": _safe_int(info.get("total_episodes"), request.num_episodes, minimum=0),
            "frame_count": _safe_int(info.get("total_frames"), 0, minimum=0),
            "fps": _safe_int(info.get("fps"), request.fps or effective_profile.fps, minimum=0),
            "codebase_version": str(info.get("codebase_version") or ""),
            "tasks": [request.task_instruction],
            "camera_keys": sorted(effective_profile.camera_map.values()),
            "metadata_files": metadata_files,
            "features": feature_names,
            "depth_features": depth_features,
            "has_depth_features": bool(depth_features),
        }
        health = self._dataset_health_summary(
            dataset_dir,
            dataset=dataset_payload,
            requested_pipeline_id=requested_pipeline_id,
            request=request,
        )
        return {
            "ok": True,
            "tool": "lerobot.dataset.inspect",
            "mode": mode,
            "profile_id": effective_profile.profile_id,
            "status": "ready",
            "dataset": dataset_payload,
            "dataset_health": health,
            "step_trace": [{"step": "INSPECT_DATASET", "status": "ok", "detail": dataset_path}],
            "error": None,
        }

    def _dataset_health_summary(
        self,
        dataset_path: Path,
        *,
        dataset: dict[str, Any],
        requested_pipeline_id: str,
        request: LeRobotSessionRequest | None = None,
    ) -> dict[str, Any]:
        raw_depth = self._dataset_raw_depth_health(dataset_path)
        isaac_rgbd = self._dataset_isaac_rgbd_health(dataset_path)
        isaac_augmentation = self._read_latest_isaac_augmentation_summary(dataset_path)
        active_robot_cam = self._dataset_active_robot_cam_health(dataset_path)
        issues: list[dict[str, Any]] = []
        if requested_pipeline_id == "raw_depth_adapter":
            if not raw_depth.get("available"):
                issues.append(
                    {
                        "severity": "blocking",
                        "code": "LEROBOT_RAW_DEPTH_SIDECAR_MISSING",
                        "message": f"Raw-depth adapter requires {raw_depth.get('manifest_path')}.",
                    }
                )
            elif _safe_int(raw_depth.get("total_frame_count"), 0, minimum=0) <= 0:
                issues.append(
                    {
                        "severity": "blocking",
                        "code": "LEROBOT_RAW_DEPTH_FRAMES_MISSING",
                        "message": "Raw-depth adapter is selected but no raw depth PNG frames were found.",
                    }
                )
        if _safe_int(isaac_rgbd.get("manifest_count"), 0, minimum=0) <= 0:
            issues.append(
                {
                    "severity": "warning",
                    "code": "LEROBOT_ISAAC_RGBD_SIDECAR_MISSING",
                    "message": "Isaac RGB-D sidecar is missing; synthetic render coverage is unavailable.",
                }
            )
        else:
            coverage = isaac_rgbd.get("coverage") if isinstance(isaac_rgbd.get("coverage"), dict) else {}
            if _safe_bool(coverage.get("incomplete"), False):
                missing_count = _safe_int(coverage.get("missing_episode_count"), 0, minimum=0)
                missing_indices = coverage.get("missing_episode_indices") if isinstance(coverage.get("missing_episode_indices"), list) else []
                missing_label = ", ".join(str(index) for index in missing_indices[:8])
                if len(missing_indices) > 8:
                    missing_label = f"{missing_label}, +{len(missing_indices) - 8} more"
                issues.append(
                    {
                        "severity": "warning",
                        "code": "LEROBOT_ISAAC_RGBD_COVERAGE_INCOMPLETE",
                        "message": (
                            "Isaac RGB-D render coverage is incomplete: "
                            f"{missing_count} episode(s) have no rendered RGB-D output"
                            f"{f': {missing_label}' if missing_label else ''}."
                        ),
                    }
                )
            contact_audit = isaac_rgbd.get("contact_audit") if isinstance(isaac_rgbd.get("contact_audit"), dict) else {}
            severe_episodes = contact_audit.get("severe_episodes") if isinstance(contact_audit.get("severe_episodes"), list) else []
            if severe_episodes:
                episode_labels = ", ".join(str(item.get("episode_index")) for item in severe_episodes[:8] if isinstance(item, dict))
                if len(severe_episodes) > 8:
                    episode_labels = f"{episode_labels}, +{len(severe_episodes) - 8} more"
                issues.append(
                    {
                        "severity": "warning",
                        "code": "LEROBOT_ISAAC_RGBD_CONTACT_WARNINGS",
                        "message": (
                            "Isaac RGB-D contact audit found "
                            f"{len(severe_episodes)} episode(s) where the gripper closed without reliable object contact/lift"
                            f"{f': {episode_labels}' if episode_labels else ''}."
                        ),
                    }
                )
        if not isaac_augmentation.get("available"):
            issues.append(
                {
                    "severity": "warning",
                    "code": "LEROBOT_ISAAC_AUGMENTATION_MISSING",
                    "message": "Isaac augmentation sidecar is missing; training will use non-augmented data only.",
                }
            )
        else:
            variant_count = _safe_int(isaac_augmentation.get("variant_count"), 0, minimum=0)
            valid_variant_count = _safe_int(isaac_augmentation.get("valid_variant_count"), variant_count, minimum=0)
            failed_variant_count = _safe_int(isaac_augmentation.get("failed_variant_count"), max(0, variant_count - valid_variant_count), minimum=0)
            if variant_count > 0 and valid_variant_count <= 0:
                issues.append(
                    {
                        "severity": "blocking",
                        "code": "LEROBOT_ISAAC_AUGMENTATION_NO_VALID_VARIANTS",
                        "message": "Isaac augmentation manifest exists but QA left 0 valid variants.",
                    }
                )
            elif failed_variant_count > 0:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "LEROBOT_ISAAC_AUGMENTATION_FAILED_VARIANTS",
                        "message": f"Isaac augmentation QA rejected {failed_variant_count} variants.",
                    }
                )
        blocking_count = sum(1 for issue in issues if issue.get("severity") == "blocking")
        warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
        severity = "blocking" if blocking_count else "warning" if warning_count else "ok"
        original_frames = _safe_int(dataset.get("frame_count"), 0, minimum=0)
        rendered_count = _safe_int(isaac_rgbd.get("rendered_count"), 0, minimum=0)
        valid_variant_count = _safe_int(isaac_augmentation.get("valid_variant_count"), 0, minimum=0)
        training_exclusions = self._write_contact_training_exclusion_manifest(dataset_path, isaac_rgbd.get("contact_audit"))
        dataset_mix = self._dataset_mix_summary_for_counts(
            request or LeRobotSessionRequest(),
            real_available=original_frames,
            isaac_rgbd_available=rendered_count,
            isaac_augmentation_available=valid_variant_count,
        )
        return {
            "schema": "atr.lerobot.dataset_health.v1",
            "severity": severity,
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "issues": issues,
            "metrics": {
                "episodes": _safe_int(dataset.get("episode_count"), 0, minimum=0),
                "original_frames": original_frames,
                "raw_depth_total_frames": _safe_int(raw_depth.get("total_frame_count"), 0, minimum=0),
                "isaac_rgbd_rendered_frames": rendered_count,
                "augmentation_valid_variants": valid_variant_count,
                "active_robot_cam_attempt_count": _safe_int(active_robot_cam.get("attempt_count"), 0, minimum=0),
                "excluded_flagged_episode_count": _safe_int(training_exclusions.get("episode_count"), 0, minimum=0),
                "train_effective_frame_count": dataset_mix["effective_counts"]["total"],
            },
            "dataset_mix": dataset_mix,
            "sidecars": {
                "raw_depth": raw_depth,
                "isaac_rgbd": isaac_rgbd,
                "isaac_augmentation": isaac_augmentation,
                "active_robot_cam": active_robot_cam,
                "training_exclusions": training_exclusions,
            },
        }

    def _dataset_raw_depth_health(self, dataset_path: Path) -> dict[str, Any]:
        manifest_path = self._dataset_raw_depth_manifest_path(dataset_path)
        camera_keys: list[str] = []
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    camera_keys = [str(item).strip() for item in loaded.get("camera_keys", []) if str(item).strip()]
            except (OSError, json.JSONDecodeError):
                camera_keys = []
        root = manifest_path.parent
        if not camera_keys and root.is_dir():
            camera_keys = sorted(path.name for path in root.iterdir() if path.is_dir())
        camera_counts = {camera_key: self._raw_depth_camera_frame_count(root / camera_key) for camera_key in camera_keys}
        return {
            "available": manifest_path.is_file(),
            "manifest_path": str(manifest_path),
            "camera_keys": camera_keys,
            "camera_counts": camera_counts,
            "total_frame_count": sum(camera_counts.values()),
        }

    @staticmethod
    def _raw_depth_camera_frame_count(camera_dir: Path) -> int:
        if not camera_dir.is_dir():
            return 0
        flat_count = len(sorted(camera_dir.glob("frame_*.png")))
        episode_count = sum(len(sorted(path.glob("frame_*.png"))) for path in camera_dir.glob("episode_*") if path.is_dir())
        return flat_count + episode_count

    def _dataset_isaac_rgbd_health(self, dataset_path: Path) -> dict[str, Any]:
        manifest_paths = sorted((dataset_path / "sidecar" / "isaac_rgbd").glob("**/manifest.jsonl"))
        row_count = 0
        rendered_count = 0
        failed_count = 0
        skipped_count = 0
        cameras: set[str] = set()
        rendered_episode_indices: set[int] = set()
        contact_audit = self._dataset_isaac_rgbd_contact_audit(manifest_paths)
        for manifest_path in manifest_paths:
            for row in self._read_jsonl_file(manifest_path):
                row_count += 1
                status = str(row.get("status") or "").lower()
                if isinstance(row.get("cameras"), list):
                    cameras.update(str(item) for item in row["cameras"] if str(item).strip())
                has_files = bool(row.get("files")) if isinstance(row.get("files"), list) else False
                if "fail" in status or "error" in status:
                    failed_count += 1
                elif "skip" in status:
                    skipped_count += 1
                elif has_files or status in {"rendered", "metadata_only", "ok", "complete", "completed"}:
                    rendered_count += 1
                    episode_index = _safe_int(row.get("episode_index"), -1)
                    if episode_index >= 0:
                        rendered_episode_indices.add(episode_index)
        coverage = self._dataset_isaac_rgbd_coverage(dataset_path, rendered_episode_indices)
        return {
            "available": bool(manifest_paths),
            "root": str(dataset_path / "sidecar" / "isaac_rgbd"),
            "manifest_count": len(manifest_paths),
            "row_count": row_count,
            "rendered_count": rendered_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "cameras": sorted(cameras),
            "coverage": coverage,
            "contact_audit": contact_audit,
        }

    def _dataset_isaac_rgbd_coverage(self, dataset_path: Path, rendered_episode_indices: set[int]) -> dict[str, Any]:
        expected_episode_indices = self._dataset_expected_episode_indices(dataset_path)
        missing_episode_indices = [index for index in expected_episode_indices if index not in rendered_episode_indices]
        extra_episode_indices = sorted(index for index in rendered_episode_indices if index not in set(expected_episode_indices))
        return {
            "schema": "atr.lerobot.isaac_rgbd_coverage.v1",
            "expected_episode_indices": expected_episode_indices[:200],
            "expected_episode_count": len(expected_episode_indices),
            "rendered_episode_indices": sorted(rendered_episode_indices)[:200],
            "rendered_episode_count": len(rendered_episode_indices),
            "missing_episode_indices": missing_episode_indices[:200],
            "missing_episode_count": len(missing_episode_indices),
            "extra_episode_indices": extra_episode_indices[:200],
            "extra_episode_count": len(extra_episode_indices),
            "incomplete": bool(expected_episode_indices and missing_episode_indices),
        }

    def _dataset_expected_episode_indices(self, dataset_path: Path) -> list[int]:
        episodes_path = dataset_path / "meta" / "episodes.jsonl"
        indices = sorted(
            {
                _safe_int(row.get("episode_index"), -1)
                for row in self._read_jsonl_file(episodes_path)
                if _safe_int(row.get("episode_index"), -1) >= 0
            }
        )
        if indices:
            return indices
        info_path = dataset_path / "meta" / "info.json"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            info = {}
        total_episodes = _safe_int(info.get("total_episodes") if isinstance(info, dict) else 0, 0, minimum=0)
        return list(range(total_episodes))

    def _dataset_isaac_rgbd_contact_audit(self, manifest_paths: list[Path]) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        severe_episodes: list[dict[str, Any]] = []
        transient_episodes: list[dict[str, Any]] = []
        unique_frame_count = 0
        for manifest_path in manifest_paths:
            rows_by_frame: dict[int, dict[str, Any]] = {}
            for row in self._read_jsonl_file(manifest_path):
                frame_index = _safe_int(row.get("frame_index"), -1)
                if frame_index >= 0:
                    rows_by_frame[frame_index] = row
            if not rows_by_frame:
                continue
            unique_frame_count += len(rows_by_frame)
            episode_index = _safe_int(next(iter(rows_by_frame.values())).get("episode_index"), 0, minimum=0)
            summary = self._isaac_rgbd_contact_episode_summary(episode_index, rows_by_frame, manifest_path, status_counts)
            if summary["severe"]:
                severe_episodes.append(summary)
            elif summary["near_closed_without_contact_ranges"]:
                transient_episodes.append(summary)
        severe_episodes.sort(key=lambda item: (-_safe_int(item.get("bad_frame_count"), 0), _safe_int(item.get("episode_index"), 0)))
        transient_episodes.sort(key=lambda item: (-_safe_int(item.get("bad_frame_count"), 0), _safe_int(item.get("episode_index"), 0)))
        return {
            "schema": "atr.lerobot.isaac_rgbd_contact_audit.v1",
            "available": bool(manifest_paths),
            "unique_frame_count": unique_frame_count,
            "status_counts": status_counts,
            "severe_episode_count": len(severe_episodes),
            "transient_episode_count": len(transient_episodes),
            "severe_episodes": severe_episodes[:50],
            "transient_episodes": transient_episodes[:50],
            "thresholds": {
                "closed_frame_min_for_severe": 20,
                "lifted_frame_max_for_severe": 4,
                "contact_frame_min_for_severe": 10,
                "closed_not_near_frame_min_for_severe": 50,
                "force_spike_n": 30.0,
                "penetration_spike_m": 0.01,
            },
        }

    def _isaac_rgbd_contact_episode_summary(
        self,
        episode_index: int,
        rows_by_frame: dict[int, dict[str, Any]],
        manifest_path: Path,
        status_counts: dict[str, int],
    ) -> dict[str, Any]:
        closed_frames: list[int] = []
        lifted_frames: list[int] = []
        any_contact_frames: list[int] = []
        both_contact_frames: list[int] = []
        closed_not_near_frames: list[int] = []
        near_no_contact_frames: list[int] = []
        force_spike_frames: list[int] = []
        penetration_spike_frames: list[int] = []
        object_positions: list[tuple[float, float, float]] = []
        for frame_index, row in sorted(rows_by_frame.items()):
            grasp = row.get("grasp_diagnostics") if isinstance(row.get("grasp_diagnostics"), dict) else {}
            contact = row.get("gripper_contact") if isinstance(row.get("gripper_contact"), dict) else {}
            grasp_status = str(grasp.get("status") or "unknown")
            status_counts[grasp_status] = status_counts.get(grasp_status, 0) + 1
            gripper_closed = bool(grasp.get("gripper_closed"))
            near_object = bool(grasp.get("near_object"))
            has_contact = bool(grasp.get("contact")) or bool(contact.get("contact"))
            if gripper_closed:
                closed_frames.append(frame_index)
            if bool(grasp.get("object_lifted")):
                lifted_frames.append(frame_index)
            if has_contact:
                any_contact_frames.append(frame_index)
            if bool(contact.get("both_sides_contact")):
                both_contact_frames.append(frame_index)
            if grasp_status == "closed_not_near_object":
                closed_not_near_frames.append(frame_index)
            if grasp_status == "near_closed_without_contact" or (gripper_closed and near_object and not has_contact):
                near_no_contact_frames.append(frame_index)
            if _safe_float(contact.get("force_n", grasp.get("contact_force_n")), 0.0) >= 30.0:
                force_spike_frames.append(frame_index)
            if _safe_float(contact.get("penetration_m", grasp.get("contact_penetration_m")), 0.0) >= 0.01:
                penetration_spike_frames.append(frame_index)
            position = grasp.get("object_position")
            if isinstance(position, list) and len(position) >= 3:
                object_positions.append(
                    (
                        _safe_float(position[0], 0.0),
                        _safe_float(position[1], 0.0),
                        _safe_float(position[2], 0.0),
                    )
                )
        severe = (
            (len(closed_frames) >= 20 and len(lifted_frames) < 5)
            or (len(closed_frames) >= 20 and len(any_contact_frames) < 10)
            or len(closed_not_near_frames) >= 50
        )
        return {
            "episode_index": episode_index,
            "manifest_path": str(manifest_path),
            "severe": severe,
            "frame_count": len(rows_by_frame),
            "bad_frame_count": len(closed_not_near_frames) + len(near_no_contact_frames),
            "closed_frame_count": len(closed_frames),
            "lifted_frame_count": len(lifted_frames),
            "any_contact_frame_count": len(any_contact_frames),
            "both_sides_contact_frame_count": len(both_contact_frames),
            "closed_not_near_ranges": self._frame_range_strings(closed_not_near_frames),
            "near_closed_without_contact_ranges": self._frame_range_strings(near_no_contact_frames),
            "force_spike_ranges": self._frame_range_strings(force_spike_frames),
            "penetration_spike_ranges": self._frame_range_strings(penetration_spike_frames),
            "object_position_range_m": self._object_position_range(object_positions),
        }

    @staticmethod
    def _frame_range_strings(frame_indices: list[int]) -> list[str]:
        values = sorted(set(frame_indices))
        if not values:
            return []
        ranges: list[str] = []
        start = end = values[0]
        for value in values[1:]:
            if value == end + 1:
                end = value
                continue
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = value
        ranges.append(f"{start}-{end}" if start != end else str(start))
        return ranges

    @staticmethod
    def _object_position_range(positions: list[tuple[float, float, float]]) -> dict[str, list[float]]:
        if not positions:
            return {}
        xs = [item[0] for item in positions]
        ys = [item[1] for item in positions]
        zs = [item[2] for item in positions]
        return {
            "x": [round(min(xs), 4), round(max(xs), 4)],
            "y": [round(min(ys), 4), round(max(ys), 4)],
            "z": [round(min(zs), 4), round(max(zs), 4)],
        }

    @staticmethod
    def _contact_training_exclusion_manifest_path(dataset_path: Path) -> Path:
        return dataset_path / "sidecar" / "train_exclusions" / "contact_audit.json"

    def _write_contact_training_exclusion_manifest(self, dataset_path: Path, contact_audit: Any) -> dict[str, Any]:
        manifest_path = self._contact_training_exclusion_manifest_path(dataset_path)
        audit = contact_audit if isinstance(contact_audit, dict) else {}
        if not _safe_bool(audit.get("available"), False):
            existing = self._read_contact_training_exclusion_manifest(dataset_path)
            if existing.get("available"):
                return existing
            return {
                "schema": "atr.lerobot.training_exclusions.contact_audit.v1",
                "available": False,
                "manifest_path": str(manifest_path),
                "created_at": "",
                "policy": "exclude_severe_contact_episodes",
                "source": "isaac_rgbd_contact_audit",
                "episode_indices": [],
                "episode_count": 0,
                "severe_episodes": [],
                "original_data_preserved": True,
            }
        severe_episodes = [item for item in audit.get("severe_episodes", []) if isinstance(item, dict)]
        episode_indices = sorted(
            {
                _safe_int(item.get("episode_index"), -1)
                for item in severe_episodes
                if _safe_int(item.get("episode_index"), -1) >= 0
            }
        )
        payload = {
            "schema": "atr.lerobot.training_exclusions.contact_audit.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_path": str(dataset_path),
            "manifest_path": str(manifest_path),
            "policy": "exclude_severe_contact_episodes",
            "source": "isaac_rgbd_contact_audit",
            "episode_indices": episode_indices,
            "episode_count": len(episode_indices),
            "severe_episodes": severe_episodes,
            "original_data_preserved": True,
        }
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            tmp_path.replace(manifest_path)
        except OSError as exc:
            payload["write_error"] = str(exc)
        return self._read_contact_training_exclusion_manifest(dataset_path, default=payload)

    def _read_contact_training_exclusion_manifest(self, dataset_path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest_path = self._contact_training_exclusion_manifest_path(dataset_path)
        loaded: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    loaded = raw
            except (OSError, json.JSONDecodeError):
                loaded = {}
        if not loaded and default is not None:
            loaded = dict(default)
        indices = sorted(
            {
                _safe_int(item, -1)
                for item in loaded.get("episode_indices", [])
                if _safe_int(item, -1) >= 0
            }
        )
        severe_episodes = loaded.get("severe_episodes") if isinstance(loaded.get("severe_episodes"), list) else []
        return {
            "schema": str(loaded.get("schema") or "atr.lerobot.training_exclusions.contact_audit.v1"),
            "available": manifest_path.is_file() or bool(loaded),
            "manifest_path": str(manifest_path),
            "created_at": str(loaded.get("created_at") or ""),
            "policy": str(loaded.get("policy") or "exclude_severe_contact_episodes"),
            "source": str(loaded.get("source") or "isaac_rgbd_contact_audit"),
            "episode_indices": indices,
            "episode_count": len(indices),
            "severe_episodes": severe_episodes,
            "original_data_preserved": bool(loaded.get("original_data_preserved", True)),
            **({"write_error": str(loaded.get("write_error"))} if loaded.get("write_error") else {}),
        }

    def _contact_training_excluded_episode_indices(self, dataset_path: Path, request: LeRobotSessionRequest | None = None) -> list[int]:
        if request is not None and not _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True):
            return []
        manifest = self._read_contact_training_exclusion_manifest(dataset_path)
        return [int(item) for item in manifest.get("episode_indices", [])]

    def _ensure_contact_training_exclusion_manifest(self, dataset_path: Path, *, enabled: bool = True) -> dict[str, Any]:
        if not enabled:
            return self._read_contact_training_exclusion_manifest(dataset_path)
        existing = self._read_contact_training_exclusion_manifest(dataset_path)
        if existing.get("available"):
            return existing
        isaac_rgbd = self._dataset_isaac_rgbd_health(dataset_path)
        return self._write_contact_training_exclusion_manifest(dataset_path, isaac_rgbd.get("contact_audit"))

    def _ensure_contact_training_exclusion_manifest_for_request(self, request: Any) -> dict[str, Any]:
        enabled = _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True)
        raw_dataset_path = str(getattr(request, "dataset_path", "") or "").strip()
        dataset_path = Path(raw_dataset_path).expanduser() if raw_dataset_path else Path(self._dataset_path_for(request)).expanduser()
        return self._ensure_contact_training_exclusion_manifest(dataset_path.resolve(), enabled=enabled)

    @staticmethod
    def _dataset_active_robot_cam_health(dataset_path: Path) -> dict[str, Any]:
        candidate_roots = [
            dataset_path / "sidecar" / "active_robot_cam",
            dataset_path / "sidecar" / "isaac_mirror",
            dataset_path / "sidecar" / "latest_frame",
        ]
        result_paths: list[Path] = []
        for root in candidate_roots:
            if root.is_dir():
                result_paths.extend(sorted(root.glob("**/*specimen_pose*.json")))
                result_paths.extend(sorted(root.glob("**/*active_robot_cam*.json")))
        unique_paths = sorted({str(path) for path in result_paths})
        return {
            "available": bool(unique_paths),
            "attempt_count": len(unique_paths),
            "result_paths": unique_paths[:20],
        }

    def policies_list(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """List configured, local, and likely cached policy choices."""
        mode = self._mode(payload or {})
        policies = self._discover_local_policies()
        policies.extend(self._policy_presets())
        unique: dict[str, dict[str, Any]] = {}
        for item in policies:
            key = item.get("value") or item.get("path") or item.get("repo_id") or item.get("label")
            if key:
                unique[str(key)] = item
        return {
            "ok": True,
            "tool": "lerobot.policies.list",
            "mode": mode,
            "policies": list(unique.values()),
            "policy_root": str(self.config.policy_root),
            "output_root": str(self.config.output_root),
            "step_trace": [{"step": "LIST_POLICIES", "status": "ok", "detail": str(len(unique))}],
        }

    def browse_paths(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Browse local roots for GUI path selection without native browser file APIs."""
        raw = dict(payload or {})
        kind = str(raw.get("kind") or "any")
        include_files = bool(raw.get("include_files", True))
        base = self._browse_base(kind, str(raw.get("path") or ""))
        if not self._is_under_allowed_roots(base) and base.exists():
            return self._error("lerobot.files.browse", "test", self._selected_profile_id, "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS", f"Path is outside allowed roots: {base}")
        entries: list[dict[str, Any]] = []
        if base.exists() and base.is_dir():
            for path in sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:200]:
                if path.name.startswith("."):
                    continue
                if path.is_file() and not include_files:
                    continue
                if kind == "policy" and path.is_file() and not self._is_policy_output_file(path):
                    continue
                entries.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "kind": "dir" if path.is_dir() else "file",
                        "size_bytes": path.stat().st_size if path.is_file() else None,
                    }
                )
        return {
            "ok": True,
            "tool": "lerobot.files.browse",
            "kind": kind,
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else "",
            "entries": entries,
            "allowed_roots": [str(path) for path in self._allowed_roots()],
            "step_trace": [{"step": "BROWSE", "status": "ok", "detail": str(base)}],
        }

    def pick_path(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open a native OS picker for local folder/file selection."""
        raw = dict(payload or {})
        kind = str(raw.get("kind") or "any")
        select = str(raw.get("select") or "directory")
        initial = self._browse_base(kind, str(raw.get("path") or ""))
        if initial.is_file():
            initial = initial.parent
        if not initial.exists():
            default_initial = self._browse_base(kind, "")
            initial = default_initial if default_initial.exists() else Path.home()
        picker = shutil.which("zenity") or shutil.which("kdialog") or shutil.which("yad")
        if not picker:
            return self._error("lerobot.files.pick", "test", self._selected_profile_id, "LEROBOT_NATIVE_PICKER_UNAVAILABLE", "No native picker found. Install zenity, kdialog, or yad.")

        title = f"Select LeRobot {kind} {'file' if select == 'file' else 'folder'}"
        if Path(picker).name == "kdialog":
            command = [picker, "--getopenfilename" if select == "file" else "--getexistingdirectory", str(initial), "--title", title]
            if kind == "policy" and select == "file":
                command.append("*.safetensors *.ckpt *.pt *.pth *.bin|LeRobot policy outputs")
        else:
            command = [picker, "--file-selection", "--title", title, "--filename", str(initial) + os.sep]
            if select != "file":
                command.append("--directory")
            elif kind == "policy":
                command.append("--file-filter=LeRobot policy outputs | *.safetensors *.ckpt *.pt *.pth *.bin")

        try:
            result = subprocess.run(command, cwd=str(self.config.repo_root), text=True, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            return self._error("lerobot.files.pick", "test", self._selected_profile_id, "LEROBOT_NATIVE_PICKER_TIMEOUT", "Native path picker timed out.")
        except Exception as exc:
            return self._error("lerobot.files.pick", "test", self._selected_profile_id, "LEROBOT_NATIVE_PICKER_FAILED", f"{exc.__class__.__name__}: {exc}")

        selected = (result.stdout or "").strip().splitlines()[0].strip() if result.stdout else ""
        if result.returncode != 0 or not selected:
            return {
                "ok": False,
                "tool": "lerobot.files.pick",
                "kind": kind,
                "select": select,
                "status": "cancelled",
                "failure_code": "LEROBOT_PICKER_CANCELLED",
                "message": "Native path picker was cancelled.",
                "selected_path": "",
                "step_trace": [{"step": "PICK_PATH", "status": "cancelled", "detail": str(initial)}],
                "error": None,
            }
        selected_path = Path(selected).expanduser().resolve()
        if kind == "policy" and selected_path.is_file() and not self._is_policy_output_file(selected_path):
            return self._error(
                "lerobot.files.pick",
                "test",
                self._selected_profile_id,
                "LEROBOT_POLICY_FILE_UNSUPPORTED",
                f"Selected file is not a supported LeRobot policy output: {selected_path}",
            )
        return {
            "ok": True,
            "tool": "lerobot.files.pick",
            "kind": kind,
            "select": select,
            "status": "selected",
            "selected_path": str(selected_path),
            "path": str(selected_path),
            "step_trace": [{"step": "PICK_PATH", "status": "ok", "detail": str(selected_path)}],
            "error": None,
        }

    def visualize_dataset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return local LeRobot dataset metadata and media candidates for GUI visualization."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        if not dataset_path.is_absolute():
            dataset_path = self.config.dataset_root / dataset_path
        dataset_path = dataset_path.resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error("lerobot.dataset.visualize", request.runtime_mode or request.mode, request.profile_id, "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS", f"Dataset path is outside allowed roots: {dataset_path}")
        metadata = self._read_dataset_metadata(dataset_path)
        episode_indices = self._visualization_episode_indices(request, dataset_path)
        media_by_episode = {
            str(episode_index): self._dataset_media(dataset_path, episode_index=episode_index)
            for episode_index in episode_indices
        }
        media: list[dict[str, Any]] = []
        seen: set[str] = set()
        for episode_media in media_by_episode.values():
            for item in episode_media:
                path_key = str(item.get("path") or item.get("serve_url") or "")
                if path_key in seen:
                    continue
                seen.add(path_key)
                media.append(item)
        return {
            "ok": True,
            "tool": "lerobot.dataset.visualize",
            "mode": request.runtime_mode or request.mode,
            "profile_id": request.profile_id or self._selected_profile_id,
            "dataset_path": str(dataset_path),
            "episode_index": episode_indices[0],
            "episode_indices": episode_indices,
            "metadata": metadata,
            "media": media,
            "media_by_episode": media_by_episode,
            "summary": {
                "video_count": len([item for item in media if item.get("media_type") == "video"]),
                "image_count": len([item for item in media if item.get("media_type") == "image"]),
                "data_files": len([item for item in media if item.get("media_type") == "data"]),
                "source_counts": self._dataset_media_source_counts(media),
            },
            "step_trace": [{"step": "VISUALIZE_DATASET", "status": "ok", "detail": str(dataset_path)}],
            "error": None,
        }

    def augment_isaac_dataset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build Isaac Sim augmentation sidecars for a selected LeRobot dataset."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.augment.isaac",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        raw_output = str(getattr(request, "isaac_data_augmentation_output_dir", "") or "").strip()
        output_dir = (
            _resolve_path(self.config.repo_root, raw_output).resolve()
            if raw_output
            else dataset_path / "sidecar" / "isaac_augmentation" / "latest"
        )
        if not self._is_under_allowed_roots(output_dir):
            return self._error(
                "lerobot.augment.isaac",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Augmentation output dir is outside allowed roots: {output_dir}",
            )
        cameras = [
            item.strip()
            for item in str(
                getattr(request, "isaac_data_augmentation_cameras", LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS)
                or LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS
            ).split(",")
            if item.strip()
        ] or [item.strip() for item in LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS.split(",") if item.strip()]
        variants = _safe_int(getattr(request, "isaac_data_augmentation_variants", 8), 8, minimum=1, maximum=256)
        max_frames = _safe_int(getattr(request, "isaac_data_augmentation_max_frames", 200), 200, minimum=1, maximum=100_000)
        seed = getattr(request, "isaac_data_augmentation_seed", 0)
        seed_value = int(seed if seed is not None else 0)
        augmentation_profile = str(getattr(request, "isaac_data_augmentation_profile", "conservative") or "conservative")
        image_enabled = bool(getattr(request, "isaac_data_augmentation_image_enabled", True))
        photometric_enabled = bool(getattr(request, "isaac_data_augmentation_photometric_enabled", True))
        sensor_noise_enabled = bool(getattr(request, "isaac_data_augmentation_sensor_noise_enabled", True))
        depth_noise_enabled = bool(getattr(request, "isaac_data_augmentation_depth_noise_enabled", True))
        render_domain_enabled = bool(getattr(request, "isaac_data_augmentation_render_domain_enabled", True))
        camera_pose_enabled = bool(getattr(request, "isaac_data_augmentation_camera_pose_enabled", True))
        exclude_flagged_episodes = _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True)
        self._ensure_contact_training_exclusion_manifest(dataset_path, enabled=exclude_flagged_episodes)
        rgb_strength = _safe_float(getattr(request, "isaac_data_augmentation_rgb_strength", 1.0), 1.0, minimum=0.0, maximum=2.0)
        depth_strength = _safe_float(getattr(request, "isaac_data_augmentation_depth_strength", 1.0), 1.0, minimum=0.0, maximum=2.0)
        render_domain_strength = _safe_float(getattr(request, "isaac_data_augmentation_render_domain_strength", 1.0), 1.0, minimum=0.0, maximum=2.0)
        camera_pose_strength = _safe_float(getattr(request, "isaac_data_augmentation_camera_pose_strength", 1.0), 1.0, minimum=0.0, maximum=2.0)
        command_preview = [
            sys.executable,
            "scripts/lerobot_isaac_data_augmentation.py",
            f"--dataset-path={dataset_path}",
            f"--output-dir={output_dir}",
            f"--variants-per-frame={variants}",
            f"--max-source-frames={max_frames}",
            f"--seed={seed_value}",
            f"--cameras={','.join(cameras)}",
            f"--augmentation-profile={augmentation_profile}",
            f"--image-augmentation-enabled={1 if image_enabled else 0}",
            f"--photometric-enabled={1 if photometric_enabled else 0}",
            f"--sensor-noise-enabled={1 if sensor_noise_enabled else 0}",
            f"--depth-noise-enabled={1 if depth_noise_enabled else 0}",
            f"--render-domain-enabled={1 if render_domain_enabled else 0}",
            f"--camera-pose-enabled={1 if camera_pose_enabled else 0}",
            f"--rgb-strength={rgb_strength:g}",
            f"--depth-strength={depth_strength:g}",
            f"--render-domain-strength={render_domain_strength:g}",
            f"--camera-pose-strength={camera_pose_strength:g}",
            f"--exclude-flagged-episodes={1 if exclude_flagged_episodes else 0}",
        ]
        build_kwargs = {
            "dataset_path": dataset_path,
            "output_dir": output_dir,
            "variants_per_frame": variants,
            "max_source_frames": max_frames,
            "seed": seed_value,
            "cameras": cameras,
            "augmentation_profile": augmentation_profile,
            "image_augmentation_enabled": image_enabled,
            "photometric_enabled": photometric_enabled,
            "sensor_noise_enabled": sensor_noise_enabled,
            "depth_noise_enabled": depth_noise_enabled,
            "render_domain_enabled": render_domain_enabled,
            "camera_pose_enabled": camera_pose_enabled,
            "rgb_strength": rgb_strength,
            "depth_strength": depth_strength,
            "render_domain_strength": render_domain_strength,
            "camera_pose_strength": camera_pose_strength,
            "exclude_flagged_episodes": exclude_flagged_episodes,
        }
        if bool(getattr(request, "isaac_data_augmentation_async", False)):
            return self._start_isaac_augmentation_job(
                mode=mode,
                profile_id=profile_id,
                dataset_path=dataset_path,
                output_dir=output_dir,
                command_preview=command_preview,
                build_kwargs=build_kwargs,
            )
        progress_events: list[dict[str, Any]] = []
        try:
            summary = self._build_isaac_augmentation_sidecar(
                build_kwargs,
                progress_callback=lambda event: progress_events.append(dict(event)),
            )
        except Exception as exc:
            return self._error(
                "lerobot.augment.isaac",
                mode,
                profile_id,
                "LEROBOT_ISAAC_AUGMENTATION_FAILED",
                f"{exc.__class__.__name__}: {exc}",
            )
        return self._isaac_augmentation_completed_response(
            mode=mode,
            profile_id=profile_id,
            dataset_path=dataset_path,
            output_dir=output_dir,
            command_preview=command_preview,
            summary=summary,
            progress_events=progress_events,
        )

    @staticmethod
    def _build_isaac_augmentation_sidecar(
        build_kwargs: dict[str, Any],
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        from scripts.lerobot_isaac_data_augmentation import build_augmentation_sidecar

        return build_augmentation_sidecar(**build_kwargs, progress_callback=progress_callback)

    def _isaac_augmentation_completed_response(
        self,
        *,
        mode: str,
        profile_id: str,
        dataset_path: Path,
        output_dir: Path,
        command_preview: list[str],
        summary: dict[str, Any],
        progress_events: list[dict[str, Any]],
        job_id: str = "",
    ) -> dict[str, Any]:
        status = "completed" if summary.get("ok") else "failed"
        augmentation_progress = dict(summary.get("progress") or (progress_events[-1] if progress_events else {}))
        step_trace = [
            {"step": "RESOLVE_DATASET", "status": "ok", "detail": str(dataset_path)},
            {"step": "BUILD_ISAAC_AUGMENTATION", "status": "ok" if summary.get("ok") else "failed", "detail": str(summary.get("manifest_path") or "")},
        ]
        self._write_latest_isaac_augmentation_metadata(dataset_path, summary)
        return {
            "ok": bool(summary.get("ok")),
            "tool": "lerobot.augment.isaac",
            "mode": mode,
            "profile_id": profile_id,
            "status": status,
            "job_id": job_id,
            "dataset_path": str(dataset_path),
            "output_dir": str(output_dir),
            "summary": summary,
            "augmentation_progress": augmentation_progress,
            "command_preview": command_preview,
            "step_trace": step_trace,
            "events": step_trace,
            "error": None if summary.get("ok") else summary.get("message"),
        }

    @staticmethod
    def _new_isaac_augmentation_job_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"isaac_aug_{stamp}_{uuid.uuid4().hex[:8]}"

    def _isaac_augmentation_job_snapshot(self, job_id: str = "") -> dict[str, Any] | None:
        with self._isaac_augmentation_lock:
            resolved = job_id or self._isaac_augmentation_latest_job_id
            if not resolved:
                return None
            job = self._isaac_augmentation_jobs.get(resolved)
            return copy.deepcopy(job) if job else None

    def _store_isaac_augmentation_job(self, job: dict[str, Any]) -> None:
        with self._isaac_augmentation_lock:
            job_id = str(job.get("job_id") or "")
            if not job_id:
                return
            self._isaac_augmentation_jobs[job_id] = copy.deepcopy(job)
            self._isaac_augmentation_latest_job_id = job_id

    def _update_isaac_augmentation_job(self, job_id: str, **updates: Any) -> None:
        with self._isaac_augmentation_lock:
            job = self._isaac_augmentation_jobs.setdefault(job_id, {"job_id": job_id})
            job.update(copy.deepcopy(updates))
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _start_isaac_augmentation_job(
        self,
        *,
        mode: str,
        profile_id: str,
        dataset_path: Path,
        output_dir: Path,
        command_preview: list[str],
        build_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = self._new_isaac_augmentation_job_id()
        now = datetime.now(timezone.utc).isoformat()
        progress = {
            "stage": "queued",
            "done": 0,
            "total": 1,
            "percent": 0.0,
            "message": "Isaac augmentation job queued",
        }
        step_trace = [
            {"step": "RESOLVE_DATASET", "status": "ok", "detail": str(dataset_path)},
            {"step": "QUEUE_ISAAC_AUGMENTATION", "status": "active", "detail": job_id},
        ]
        job = {
            "ok": True,
            "tool": "lerobot.augment.isaac",
            "mode": mode,
            "profile_id": profile_id,
            "status": "RUNNING",
            "job_id": job_id,
            "dataset_path": str(dataset_path),
            "output_dir": str(output_dir),
            "summary": {},
            "augmentation_progress": progress,
            "command_preview": list(command_preview),
            "step_trace": step_trace,
            "events": step_trace,
            "started_at": now,
            "updated_at": now,
            "completed_at": "",
            "error": None,
        }
        self._store_isaac_augmentation_job(job)
        worker = threading.Thread(
            target=self._run_isaac_augmentation_job,
            args=(job_id,),
            kwargs={
                "mode": mode,
                "profile_id": profile_id,
                "dataset_path": dataset_path,
                "output_dir": output_dir,
                "command_preview": list(command_preview),
                "build_kwargs": copy.deepcopy(build_kwargs),
            },
            name=f"atr-isaac-augmentation-{job_id[-8:]}",
            daemon=True,
        )
        with self._isaac_augmentation_lock:
            self._isaac_augmentation_threads[job_id] = worker
        worker.start()
        snapshot = self._isaac_augmentation_job_snapshot(job_id)
        return snapshot or job

    def _run_isaac_augmentation_job(
        self,
        job_id: str,
        *,
        mode: str,
        profile_id: str,
        dataset_path: Path,
        output_dir: Path,
        command_preview: list[str],
        build_kwargs: dict[str, Any],
    ) -> None:
        progress_events: list[dict[str, Any]] = []

        def progress_callback(event: dict[str, Any]) -> None:
            progress = dict(event)
            progress_events.append(progress)
            self._update_isaac_augmentation_job(job_id, status="RUNNING", augmentation_progress=progress)

        try:
            summary = self._build_isaac_augmentation_sidecar(build_kwargs, progress_callback=progress_callback)
            completed = self._isaac_augmentation_completed_response(
                mode=mode,
                profile_id=profile_id,
                dataset_path=dataset_path,
                output_dir=output_dir,
                command_preview=command_preview,
                summary=summary,
                progress_events=progress_events,
                job_id=job_id,
            )
            completed["status"] = "COMPLETED" if completed.get("ok") else "FAILED"
            completed["completed_at"] = datetime.now(timezone.utc).isoformat()
            updates = dict(completed)
            updates.pop("job_id", None)
            self._update_isaac_augmentation_job(job_id, **updates)
        except Exception as exc:
            progress = {
                "stage": "failed",
                "done": 1,
                "total": 1,
                "percent": 100.0,
                "message": f"{exc.__class__.__name__}: {exc}",
            }
            self._update_isaac_augmentation_job(
                job_id,
                ok=False,
                status="FAILED",
                augmentation_progress=progress,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=f"{exc.__class__.__name__}: {exc}",
            )

    def augment_isaac_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the current Isaac augmentation job status."""
        raw_payload = dict(payload or {})
        request = LeRobotSessionRequest.model_validate(raw_payload)
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        job_id = str(raw_payload.get("job_id") or request.isaac_data_augmentation_job_id or "").strip()
        job = self._isaac_augmentation_job_snapshot(job_id)
        if job is None:
            return self._error(
                "lerobot.augment.status",
                mode,
                profile_id,
                "LEROBOT_ISAAC_AUGMENTATION_JOB_NOT_FOUND",
                f"Isaac augmentation job not found: {job_id or 'latest'}",
            )
        job["tool"] = "lerobot.augment.status"
        return job

    def augment_isaac_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return deterministic preview rows for the latest Isaac augmentation sidecar."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.augment.preview",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        summary = self._read_latest_isaac_augmentation_summary(dataset_path)
        manifest_path = Path(str(summary.get("manifest_path") or self._dataset_isaac_augmentation_summary_path(dataset_path).parent / "manifest.jsonl")).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = (dataset_path / manifest_path).resolve()
        else:
            manifest_path = manifest_path.resolve()
        if not manifest_path.is_file():
            return self._error(
                "lerobot.augment.preview",
                mode,
                profile_id,
                "LEROBOT_ISAAC_AUGMENTATION_MANIFEST_MISSING",
                f"Isaac augmentation manifest not found: {manifest_path}",
            )
        if not self._is_under_allowed_roots(manifest_path):
            return self._error(
                "lerobot.augment.preview",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Isaac augmentation manifest is outside allowed roots: {manifest_path}",
            )
        preview_limit = _safe_int(getattr(request, "isaac_data_augmentation_preview_count", 20), 20, minimum=1, maximum=200)
        preview_dir = manifest_path.parent / "previews"
        manifest_rows = self._read_jsonl_file(manifest_path)
        preview_rows: list[dict[str, Any]] = []
        for row in manifest_rows:
            if len(preview_rows) >= preview_limit:
                break
            if not isinstance(row, dict):
                continue
            source_files = self._augmentation_source_files(row, dataset_path=dataset_path)
            image_outputs = row.get("image_outputs") if isinstance(row.get("image_outputs"), dict) else {}
            cameras = [str(item) for item in row.get("cameras", []) if str(item or "").strip()]
            variant_id = str(row.get("variant_id") or f"variant_{len(preview_rows):06d}")
            for camera in cameras:
                if len(preview_rows) >= preview_limit:
                    break
                source_camera = source_files.get(camera, {})
                augmented_camera = image_outputs.get(camera) if isinstance(image_outputs.get(camera), dict) else {}
                source_rgb_path = self._allowed_file_or_none(source_camera.get("rgb"))
                source_depth_path = self._allowed_file_or_none(source_camera.get("depth"))
                augmented_rgb_path = self._allowed_file_or_none(augmented_camera.get("rgb_path"))
                augmented_depth_path = self._allowed_file_or_none(augmented_camera.get("depth_path"))
                row_preview_dir = preview_dir / variant_id / camera
                source_depth_preview = (
                    self._write_depth_preview_png(source_depth_path, row_preview_dir / "source_depth_preview.png")
                    if source_depth_path is not None
                    else None
                )
                augmented_depth_preview = (
                    self._write_depth_preview_png(augmented_depth_path, row_preview_dir / "augmented_depth_preview.png")
                    if augmented_depth_path is not None
                    else None
                )
                source = row.get("source") if isinstance(row.get("source"), dict) else {}
                preview_rows.append(
                    {
                        "variant_id": variant_id,
                        "episode_index": _safe_int(source.get("episode_index"), _safe_int(row.get("episode_index"), 0, minimum=0), minimum=0),
                        "frame_index": _safe_int(source.get("frame_index"), _safe_int(row.get("frame_index"), 0, minimum=0), minimum=0),
                        "camera": camera,
                        "source_rgb": self._media_file_ref(source_rgb_path),
                        "source_depth_preview": self._media_file_ref(source_depth_preview),
                        "isaac_rgb": self._media_file_ref(source_rgb_path),
                        "isaac_depth_preview": self._media_file_ref(source_depth_preview),
                        "augmented_rgb": self._media_file_ref(augmented_rgb_path),
                        "augmented_depth_preview": self._media_file_ref(augmented_depth_preview),
                        "source_pose": row.get("source_pose") if isinstance(row.get("source_pose"), dict) else {},
                        "augmentation_parameters": {
                            "image": row.get("image_augmentations") if isinstance(row.get("image_augmentations"), dict) else {},
                            "depth": row.get("depth_augmentations") if isinstance(row.get("depth_augmentations"), dict) else {},
                            "render_domain": row.get("render_domain_augmentations") if isinstance(row.get("render_domain_augmentations"), dict) else {},
                            "camera_pose": (row.get("render_request") or {}).get("camera_specs", {}) if isinstance(row.get("render_request"), dict) else {},
                        },
                        "qa": {
                            "ok": bool(row.get("qa_ok")),
                            "failure_code": str(row.get("qa_failure_code") or ""),
                            "depth_valid_ratio": row.get("depth_valid_ratio"),
                            "rgb_exists": bool(row.get("rgb_exists")),
                            "depth_exists": bool(row.get("depth_exists")),
                        },
                    }
                )
        return {
            "ok": True,
            "tool": "lerobot.augment.preview",
            "mode": mode,
            "profile_id": profile_id,
            "dataset_path": str(dataset_path),
            "manifest_path": str(manifest_path),
            "preview_dir": str(preview_dir),
            "requested_count": preview_limit,
            "preview_count": len(preview_rows),
            "rows": preview_rows,
            "summary": summary,
            "step_trace": [{"step": "BUILD_ISAAC_AUGMENTATION_PREVIEW", "status": "ok", "detail": str(preview_dir)}],
            "error": None,
        }

    def isaac_lab_validate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run non-actuating Isaac Lab synthetic validation checks."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().validate(request)

    def isaac_lab_prepare(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run digital-twin preflight and write validation artifacts."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().prepare(request)

    def isaac_lab_build_synthetic(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build canonical indexes and training import manifests for synthetic workflow."""
        request = self._isaac_lab_synthetic_request(payload)
        self._ensure_contact_training_exclusion_manifest_for_request(request)
        return self._isaac_lab_synthetic_pipeline().build_synthetic(request)

    def isaac_lab_run_replicator_worker(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the Replicator worker from the latest build plan, then refresh synthetic summaries."""
        request = self._isaac_lab_synthetic_request(payload)
        self._ensure_contact_training_exclusion_manifest_for_request(request)
        pipeline = self._isaac_lab_synthetic_pipeline()
        build = pipeline.build_synthetic(request)
        output_root = Path(str(build.get("output_root") or "")).expanduser().resolve()
        build_plan_path = output_root / "replicator" / "build_plan.json"
        try:
            build_plan = json.loads(build_plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                **build,
                "ok": False,
                "tool": "lerobot.isaac_lab.run_replicator_worker",
                "status": "BLOCKED",
                "worker": {
                    "status": "blocked",
                    "blocker": "REPLICATOR_BUILD_PLAN_MISSING",
                    "build_plan_path": str(build_plan_path),
                },
                "error": {
                    "code": "REPLICATOR_BUILD_PLAN_MISSING",
                    "message": "Replicator build plan is missing or invalid.",
                },
            }
        command = [str(item) for item in list((build_plan.get("worker") or {}).get("command") or [])]
        if not command or command[0] == "<isaac-sim-python>":
            return {
                **build,
                "ok": False,
                "tool": "lerobot.isaac_lab.run_replicator_worker",
                "status": "BLOCKED",
                "worker": {
                    "status": "blocked",
                    "blocker": "REPLICATOR_RUNTIME_MISSING",
                    "build_plan_path": str(build_plan_path),
                    "command": command,
                },
                "error": {
                    "code": "REPLICATOR_RUNTIME_MISSING",
                    "message": "Replicator worker requires isaac_sim_python in the build plan.",
                },
            }
        active_live_sessions = self._active_live_control_sessions(mode=str((payload or {}).get("mode") or ""))
        allow_during_live = bool((payload or {}).get("allow_replicator_during_live_control"))
        if active_live_sessions and not allow_during_live:
            return {
                **build,
                "ok": False,
                "tool": "lerobot.isaac_lab.run_replicator_worker",
                "status": "BLOCKED",
                "worker": {
                    "status": "blocked",
                    "blocker": "REPLICATOR_LIVE_SESSION_ACTIVE",
                    "build_plan_path": str(build_plan_path),
                    "command": command,
                    "active_sessions": active_live_sessions,
                },
                "error": {
                    "code": "REPLICATOR_LIVE_SESSION_ACTIVE",
                    "message": "Replicator worker is blocked while live teleoperation, recording, or rollout is active.",
                    "active_sessions": active_live_sessions,
                },
            }
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                text=True,
                capture_output=True,
                timeout=900,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                **build,
                "ok": False,
                "tool": "lerobot.isaac_lab.run_replicator_worker",
                "status": "BLOCKED",
                "worker": {
                    "status": "blocked",
                    "blocker": "REPLICATOR_WORKER_FAILED",
                    "build_plan_path": str(build_plan_path),
                    "command": command,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                "error": {
                    "code": "REPLICATOR_WORKER_FAILED",
                    "message": f"Replicator worker could not be launched: {exc}",
                },
            }
        refreshed = pipeline.build_synthetic(request)
        worker = {
            "status": "completed" if completed.returncode == 0 else "blocked",
            "returncode": completed.returncode,
            "command": command,
            "build_plan_path": str(build_plan_path),
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
        }
        status = refreshed.get("status", "BLOCKED") if completed.returncode == 0 else "BLOCKED"
        return {
            **refreshed,
            "ok": bool(completed.returncode == 0 and refreshed.get("ok")),
            "tool": "lerobot.isaac_lab.run_replicator_worker",
            "status": status,
            "worker": worker,
            "step_trace": list(refreshed.get("step_trace") or [])
            + [
                {
                    "stage": "replicator_worker",
                    "status": "ok" if completed.returncode == 0 else "blocked",
                    "message": f"returncode={completed.returncode}",
                }
            ],
        }

    def _active_live_control_sessions(self, *, mode: str = "") -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for session in self._sessions.values():
            workflow = str(session.get("workflow") or "").lower()
            if workflow not in {"teleoperate", "record", "rollout"}:
                continue
            if not self._session_is_active(session):
                continue
            active.append(
                {
                    "session_id": str(session.get("session_id") or ""),
                    "workflow": workflow,
                    "status": str(session.get("status") or ""),
                }
            )
        if str(mode or "").lower() == "live":
            known = {(item["workflow"], item.get("session_id", "")) for item in active}
            for workflow in ("teleoperate", "record", "rollout"):
                for pid in self._project_lerobot_pids(workflow):
                    key = (workflow, "")
                    if key in known:
                        continue
                    active.append(
                        {
                            "session_id": "",
                            "workflow": workflow,
                            "status": "PROCESS_ACTIVE",
                            "pid": int(pid),
                        }
                    )
                    known.add(key)
        return active

    def isaac_lab_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return preview card metadata for the latest synthetic run."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().preview(request)

    def isaac_lab_export_hdf5(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Write HDF5 export hook summaries for the latest synthetic run."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().export_hdf5(request)

    def isaac_lab_annotate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run or summarize the Isaac Lab Mimic annotation command."""
        request = self._isaac_lab_synthetic_request(payload)
        result = self._isaac_lab_synthetic_pipeline().annotate_source(request)
        annotation = ((result.get("hdf5") or {}).get("annotation") if isinstance(result.get("hdf5"), dict) else {})
        if isinstance(annotation, dict) and str(annotation.get("status") or "") == "completed":
            return self._record_isaac_lab_immediate_job("annotate", result)
        return self._record_or_launch_isaac_lab_runner("annotate", request, result)

    def isaac_lab_train_il(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run or summarize the Isaac Lab robomimic IL training command."""
        request = self._isaac_lab_synthetic_request(payload)
        result = self._isaac_lab_synthetic_pipeline().train_il(request)
        return self._record_or_launch_isaac_lab_runner("il_train", request, result)

    def isaac_lab_eval_il(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run or summarize the Isaac Lab robomimic IL evaluation command."""
        request = self._isaac_lab_synthetic_request(payload)
        result = self._isaac_lab_synthetic_pipeline().eval_il(request)
        return self._record_or_launch_isaac_lab_runner("il_eval", request, result)

    def isaac_lab_run_e2e(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the Isaac Lab domain-randomized Mimic sidecar sequence."""
        data = dict(payload or {})
        data["enable_mimic"] = True
        request = self._isaac_lab_synthetic_request(data)
        if self._isaac_lab_live_runner_requested(request):
            return self._run_live_isaac_lab_domain_mimic_pipeline(request)
        return self._isaac_lab_synthetic_pipeline().run_e2e(request)

    @staticmethod
    def _isaac_lab_annotation_completed(result: dict[str, Any]) -> bool:
        hdf5_summary = result.get("hdf5") if isinstance(result.get("hdf5"), dict) else {}
        annotation = hdf5_summary.get("annotation") if isinstance(hdf5_summary.get("annotation"), dict) else {}
        if str(annotation.get("status") or "").lower() == "completed":
            return True
        job = result.get("job") if isinstance(result.get("job"), dict) else {}
        return str(job.get("status") or result.get("status") or "").upper() == "COMPLETED"

    @staticmethod
    def _write_isaac_lab_e2e_summary(output_root: Path, summary: dict[str, Any]) -> None:
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "summary_e2e.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _run_live_isaac_lab_domain_mimic_pipeline(self, request: IsaacLabSyntheticRequest) -> dict[str, Any]:
        pipeline = self._isaac_lab_synthetic_pipeline()
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        output_root = Path(request.output_root).expanduser().resolve() if request.output_root else self._dataset_isaac_lab_synthetic_root(dataset_path)
        self._ensure_contact_training_exclusion_manifest_for_request(request)
        build = pipeline.build_synthetic(request)
        export = pipeline.export_hdf5(request) if build.get("ok") else {}
        annotation = pipeline.annotate_source(request) if export.get("ok") else {}
        annotation_ready = bool(annotation.get("ok")) and (
            request.mimic_generation_backend == "official"
            or self._isaac_lab_annotation_completed(annotation)
        )
        if not (build.get("ok") and export.get("ok") and annotation_ready):
            summary = {
                "schema": "atr.lerobot.isaac_lab.e2e.summary.v1",
                "ok": False,
                "status": "blocked",
                "build": {"ok": bool(build.get("ok")), "status": build.get("status")},
                "export": {"ok": bool(export.get("ok")), "status": export.get("status")},
                "annotation": {"ok": bool(annotation.get("ok")), "status": annotation.get("status")},
                "mimic": {},
                "training_import_refresh": {},
                "train": {},
                "eval": {},
            }
            self._write_isaac_lab_e2e_summary(output_root, summary)
            blocked = {
                "ok": False,
                "tool": "lerobot.isaac_lab.run_e2e",
                "status": "BLOCKED",
                "dataset_path": str(dataset_path),
                "output_root": str(output_root),
                "validation_report": build.get("validation_report") if isinstance(build.get("validation_report"), dict) else {},
                "hdf5": export.get("hdf5") if isinstance(export.get("hdf5"), dict) else {},
                "mimic": {},
                "training_exposure": {"e2e": summary, "train": {}, "eval": {}},
                "step_trace": [
                    {"stage": "build", "status": build.get("status", "missing")},
                    {"stage": "export", "status": export.get("status", "missing")},
                    {"stage": "annotation", "status": annotation.get("status", "missing")},
                ],
                "error": {
                    "code": "ISAAC_LAB_E2E_PREP_BLOCKED",
                    "message": "Domain-randomized Mimic pipeline could not launch because build/export/annotation is not complete.",
                },
            }
            return self._record_isaac_lab_immediate_job("mimic", blocked)
        mimic = pipeline.run_mimic(request)
        launched = self._record_or_launch_isaac_lab_runner("mimic", request, mimic)
        status = str(launched.get("status") or "").upper()
        summary = {
            "schema": "atr.lerobot.isaac_lab.e2e.summary.v1",
            "ok": bool(launched.get("ok")),
            "status": "MIMIC_RUNNING" if status == "RUNNING" else "READY_FOR_VLA_TRAINING_IMPORT" if status == "COMPLETED" else "blocked",
            "build": {"ok": bool(build.get("ok")), "status": build.get("status")},
            "export": {"ok": bool(export.get("ok")), "status": export.get("status")},
            "annotation": {"ok": bool(annotation.get("ok")), "status": annotation.get("status")},
            "mimic": {
                "ok": bool(launched.get("ok")),
                "status": launched.get("status"),
                "job_id": launched.get("job_id", ""),
            },
            "training_import_refresh": {},
            "train": {},
            "eval": {},
        }
        self._write_isaac_lab_e2e_summary(output_root, summary)
        training_exposure = dict(launched.get("training_exposure") if isinstance(launched.get("training_exposure"), dict) else {})
        training_exposure["e2e"] = summary
        training_exposure.setdefault("train", {})
        training_exposure.setdefault("eval", {})
        launched["tool"] = "lerobot.isaac_lab.run_e2e"
        launched["training_exposure"] = training_exposure
        launched["step_trace"] = list(launched.get("step_trace") or []) + [
            {"stage": "domain_randomization", "status": str(request.domain_randomization_profile or "standard")},
            {"stage": "mimic_runner", "status": status.lower(), "message": str(launched.get("job_id") or "")},
        ]
        return launched

    def isaac_lab_run_live_e2e_check(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Launch the real Isaac Lab Mimic + IL 10s x 3 validation runner."""
        request = self._isaac_lab_live_e2e_request(self._isaac_lab_synthetic_request(payload))
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.isaac_lab.run_live_e2e_check",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        active_live_sessions = self._active_live_control_sessions(mode=str(mode or ""))
        if active_live_sessions:
            return self._isaac_lab_live_e2e_blocked_response(
                request,
                dataset_path,
                "ISAAC_LAB_LIVE_E2E_ACTIVE_SESSION",
                "Isaac Lab live E2E check is blocked while live teleoperation, recording, or rollout is active.",
                {"active_sessions": active_live_sessions},
            )
        command = self._isaac_lab_live_e2e_command(request)
        runtime_path = Path(command[0]).expanduser()
        script_path = _command_script_path(command)
        if not runtime_path.is_file():
            return self._isaac_lab_live_e2e_blocked_response(
                request,
                dataset_path,
                "ISAAC_LAB_LIVE_E2E_PYTHON_MISSING",
                f"LeRobot Python runtime is missing: {runtime_path}",
                {"command": command},
            )
        if not script_path.is_file():
            return self._isaac_lab_live_e2e_blocked_response(
                request,
                dataset_path,
                "ISAAC_LAB_LIVE_E2E_SCRIPT_MISSING",
                f"Live E2E runner script is missing: {script_path}",
                {"command": command},
            )
        job_id = self._new_isaac_lab_job_id("live_e2e")
        now = datetime.now(timezone.utc).isoformat()
        output_root = self._isaac_lab_live_e2e_output_root(request, dataset_path)
        log_path = output_root / "live_e2e" / "logs" / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        repo_root_text = str(self.config.repo_root.resolve())
        existing_pythonpath = str(env.get("PYTHONPATH") or "")
        env["PYTHONPATH"] = repo_root_text if not existing_pythonpath else repo_root_text + os.pathsep + existing_pythonpath
        if request.isaac_lab_visualize_generation:
            env["ROBOTIS_OMX_USE_FABRIC"] = "0"
        try:
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.config.repo_root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
        except OSError as exc:
            return self._isaac_lab_live_e2e_blocked_response(
                request,
                dataset_path,
                "ISAAC_LAB_LIVE_E2E_LAUNCH_FAILED",
                f"Live E2E runner could not be launched: {exc}",
                {"command": command, "log_path": str(log_path)},
            )
        job = {
            "job_id": job_id,
            "kind": "live_e2e",
            "status": "RUNNING",
            "progress": {"percent": 5.0, "stage": "running", "message": "live 10s x 3 check started"},
            "summary": {
                "tool": "lerobot.isaac_lab.run_live_e2e_check",
                "dataset_path": str(dataset_path),
                "output_root": str(output_root),
                "visualize_generation": bool(request.isaac_lab_visualize_generation),
                "episodes": request.e2e_episodes,
                "episode_s": request.e2e_episode_s,
                "mimic_trials": request.mimic_trials,
                "mimic_num_envs": request.mimic_num_envs,
            },
            "command_preview": {"operation": "live_e2e_check", "visual": bool(request.isaac_lab_visualize_generation)},
            "command": command,
            "cwd": str(self.config.repo_root),
            "pid": int(process.pid),
            "log_path": str(log_path),
            "output_root": str(output_root),
            "artifact_checks": self._isaac_lab_live_e2e_artifact_checks(output_root),
            "error": None,
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "stop_requested": False,
        }
        self._store_isaac_lab_runner_process("live_e2e", job_id, process)
        self._store_isaac_lab_job("live_e2e", job)
        return self._isaac_lab_job_response("lerobot.isaac_lab.live_e2e.start", job)

    def isaac_lab_live_e2e_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the latest or requested live Isaac Lab E2E job state."""
        return self._isaac_lab_live_e2e_job_response("lerobot.isaac_lab.live_e2e.status", payload or {})

    def isaac_lab_live_e2e_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop the latest or requested live Isaac Lab E2E job."""
        stopped = self._isaac_lab_job_stop("live_e2e", payload or {})
        job = stopped.get("job") if isinstance(stopped.get("job"), dict) else {}
        if job:
            stopped["job"] = self._decorate_isaac_lab_live_e2e_job(dict(job))
            stopped["summary"] = copy.deepcopy(stopped["job"].get("summary") or {})
        stopped["tool"] = "lerobot.isaac_lab.live_e2e.stop"
        return stopped

    def isaac_lab_run_mimic_smoke(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate and write the non-actuating Isaac Lab Mimic smoke launch artifact."""
        data = dict(payload or {})
        data["enable_mimic"] = True
        request = self._isaac_lab_synthetic_request(data)
        result = self._isaac_lab_synthetic_pipeline().run_mimic_smoke(request)
        return self._record_isaac_lab_immediate_job("mimic", result)

    def isaac_lab_run_mimic(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the Isaac Lab Mimic generation branch or deterministic dry-run runner."""
        data = dict(payload or {})
        data["enable_mimic"] = True
        request = self._isaac_lab_synthetic_request(data)
        result = self._isaac_lab_synthetic_pipeline().run_mimic(request)
        return self._record_or_launch_isaac_lab_runner("mimic", request, result)

    def isaac_lab_generate_mimic(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Alias for the E2E GUI's named Mimic generation step."""
        return self.isaac_lab_run_mimic(payload)

    def isaac_lab_render_mimic_rgbd(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the Isaac Lab Mimic RGB-D sidecar without using the recording RGB-D renderer."""
        data = dict(payload or {})
        data["enable_mimic"] = True
        data["mimic_enable_cameras"] = True
        data["isaac_lab_visualize_generation"] = True
        request = self._isaac_lab_synthetic_request(data)
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        output_root = Path(request.output_root).expanduser().resolve() if request.output_root else self._dataset_isaac_lab_synthetic_root(dataset_path).resolve()
        generated_hdf5 = output_root / "mimic" / "generated_dataset.hdf5"
        mimic_summary = self._read_json_dict(output_root / "mimic" / "summary.json")
        if not generated_hdf5.is_file():
            blocked = {
                "ok": False,
                "tool": "lerobot.isaac_lab.mimic_rgbd.render_missing",
                "status": "BLOCKED",
                "dataset_path": str(dataset_path),
                "output_root": str(output_root),
                "mimic": mimic_summary,
                "training_exposure": {},
                "error": {
                    "code": "ISAAC_LAB_MIMIC_RGBD_SOURCE_MISSING",
                    "message": "Mimic RGB-D rendering requires the generated Mimic HDF5 dataset.",
                    "input_file": str(generated_hdf5),
                },
            }
            return self._record_isaac_lab_immediate_job("mimic", blocked)

        pipeline = self._isaac_lab_synthetic_pipeline()
        runner = dict(mimic_summary.get("runner") if isinstance(mimic_summary.get("runner"), dict) else {})
        post_run = dict(runner.get("post_run") if isinstance(runner.get("post_run"), dict) else {})
        command = [str(item) for item in list(post_run.get("command") or []) if str(item)]
        if str(post_run.get("stage") or "") != "rgbd_render_after_generation":
            command = pipeline._joint_replay_rgbd_render_command(  # noqa: SLF001 - Section 7 intentionally reuses the Lab RGB-D render command.
                request,
                output_root=output_root,
                hook_summary=mimic_summary,
            )
            post_run = {
                "enabled": True,
                "stage": "rgbd_render_after_generation",
                "trigger": "manual_render_missing",
                "fps": 0,
                "max_demos": 0,
                "command": command,
                "script_path": str(_command_script_path(command)) if command else "",
                "script_exists": _command_script_path(command).is_file() if command else False,
                "input_file": str(output_root / "mimic" / "generated_dataset.hdf5"),
                "output_file": str(output_root / "mimic_rgbd" / "generated_dataset_rgbd.hdf5"),
                "success_manifest_path": str(output_root / "mimic_rgbd" / "successes.jsonl"),
                "failure_manifest_path": str(output_root / "mimic_rgbd" / "failures.jsonl"),
                "render_manifest_path": str(output_root / "mimic_rgbd" / "manifest.jsonl"),
                "render_root": str(output_root / "mimic_rgbd" / "renders"),
            }
        elif len(command) < 2:
            post_run = pipeline._runner_post_run_summary(  # noqa: SLF001 - section 7 uses the pipeline's Lab RGB-D command contract.
                request,
                kind="mimic",
                output_root=output_root,
                hook_summary=mimic_summary,
            )
            command = [str(item) for item in list(post_run.get("command") or []) if str(item)]
        if len(command) < 2:
            blocked = {
                "ok": False,
                "tool": "lerobot.isaac_lab.mimic_rgbd.render_missing",
                "status": "BLOCKED",
                "dataset_path": str(dataset_path),
                "output_root": str(output_root),
                "mimic": {**mimic_summary, "runner": {**runner, "post_run": post_run}},
                "training_exposure": {},
                "error": {
                    "code": "ISAAC_LAB_MIMIC_RGBD_RENDER_COMMAND_MISSING",
                    "message": "Mimic RGB-D render command is missing from the Mimic summary.",
                },
            }
            return self._record_isaac_lab_immediate_job("mimic", blocked)

        job_id = self._new_isaac_lab_job_id("mimic")
        now = datetime.now(timezone.utc).isoformat()
        log_path = output_root / "mimic_rgbd" / "logs" / f"{job_id}.log"
        runner.update(
            {
                "post_run": {
                    **post_run,
                    "enabled": True,
                    "status": "pending",
                    "started_at": "",
                    "command": command,
                    "log_path": str(log_path),
                }
            }
        )
        result = {
            "ok": True,
            "tool": "lerobot.isaac_lab.mimic_rgbd.render_missing",
            "status": "READY_FOR_TRAINING",
            "dataset_path": str(dataset_path),
            "output_root": str(output_root),
            "hdf5": self._read_json_dict(output_root / "hdf5" / "export_summary.json"),
            "mimic": {**mimic_summary, "runner": runner},
            "training_exposure": self._read_json_dict(output_root / "training_import" / "summary.json"),
        }
        summary = self._isaac_lab_result_summary("mimic", result)
        job = {
            "job_id": job_id,
            "kind": "mimic",
            "status": "COMPLETED",
            "progress": {"percent": 90.0, "stage": "lab_rgbd_render_pending"},
            "summary": summary,
            "command_preview": {},
            "command": [],
            "primary_command": [],
            "post_run": copy.deepcopy(runner["post_run"]),
            "cwd": str(self.config.repo_root),
            "pid": None,
            "log_path": str(log_path),
            "runtime_smoke": {},
            "job_manifest_path": "",
            "error": None,
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "completed_at": now,
            "stop_requested": False,
        }
        running, process = self._start_isaac_lab_post_run_process("mimic", job)
        if process is not None:
            self._store_isaac_lab_runner_process("mimic", job_id, process)
        self._store_isaac_lab_job("mimic", running)
        return self._isaac_lab_job_response("lerobot.isaac_lab.mimic_rgbd.render_missing", running)

    def isaac_lab_mimic_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the latest or requested Isaac Lab Mimic job state."""
        return self._isaac_lab_job_status("mimic", payload or {})

    def isaac_lab_mimic_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Mark a running Isaac Lab Mimic job as stopped without touching teleop state."""
        return self._isaac_lab_job_stop("mimic", payload or {})

    def isaac_lab_run_rl_teacher_smoke(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate and write the non-actuating Isaac Lab RL teacher smoke launch artifact."""
        data = dict(payload or {})
        data["enable_rl_teacher"] = True
        request = self._isaac_lab_synthetic_request(data)
        result = self._isaac_lab_synthetic_pipeline().run_rl_teacher_smoke(request)
        return self._record_isaac_lab_immediate_job("rl_teacher", result)

    def isaac_lab_run_rl_teacher(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the Isaac Lab RL teacher branch or deterministic dry-run runner."""
        data = dict(payload or {})
        data["enable_rl_teacher"] = True
        request = self._isaac_lab_synthetic_request(data)
        result = self._isaac_lab_synthetic_pipeline().run_rl_teacher(request)
        return self._record_or_launch_isaac_lab_runner("rl_teacher", request, result)

    def isaac_lab_rl_teacher_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the latest or requested Isaac Lab RL teacher job state."""
        return self._isaac_lab_job_status("rl_teacher", payload or {})

    def isaac_lab_rl_teacher_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Mark a running Isaac Lab RL teacher job as stopped without touching teleop state."""
        return self._isaac_lab_job_stop("rl_teacher", payload or {})

    def isaac_lab_run_e2e_smoke(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the non-actuating 5x10 synthetic workflow smoke through the same bridge methods as the GUI."""
        from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset, run_e2e_smoke

        request = self._isaac_lab_synthetic_request(payload)
        dataset_path = Path(request.dataset_path).expanduser()
        if not str(request.dataset_path or "").strip():
            dataset_path = self.config.repo_root / "artifacts" / "lerobot" / "synthetic_e2e_gui" / "five-by-ten"
        dataset_path = dataset_path.resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return {
                "ok": False,
                "tool": "lerobot.isaac_lab.e2e_smoke",
                "schema": "atr.lerobot.synthetic_e2e.smoke_report.v1",
                "status": "BLOCKED",
                "error": {
                    "code": "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                    "message": f"Dataset path is outside allowed roots: {dataset_path}",
                },
                "dataset_path": str(dataset_path),
                "step_trace": [{"stage": "resolve_dataset", "status": "blocked", "message": "Dataset path is outside allowed roots."}],
            }
        isaac_lab_path = Path(request.isaac_lab_path).expanduser().resolve() if request.isaac_lab_path else (self.config.repo_root / "IsaacLab").resolve()
        stage_path = Path(request.stage_path).expanduser().resolve() if request.stage_path else (self.config.repo_root / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda").resolve()
        fixture = {}
        if request.e2e_create_fixture:
            fixture = build_fixture_recording_dataset(
                dataset_path,
                episodes=request.e2e_episodes,
                episode_s=request.e2e_episode_s,
                fps=request.e2e_fps,
            )
        report = run_e2e_smoke(
            bridge=self,
            dataset_path=dataset_path,
            isaac_lab_path=isaac_lab_path,
            stage_path=stage_path,
            train_steps=request.e2e_train_steps,
            enable_replicator=request.enable_replicator,
        )
        status = "COMPLETED" if report.get("ok") else "BLOCKED"
        report.update(
            {
                "tool": "lerobot.isaac_lab.e2e_smoke",
                "status": status,
                "fixture_created": bool(request.e2e_create_fixture),
                "created_fixture": fixture,
                "step_trace": [
                    {"stage": "recording_fixture", "status": "ok" if (report.get("recording_fixture") or {}).get("frame_count") else "warning", "message": "5x10 fixture recording ready"},
                    {"stage": "synthetic_build", "status": str((report.get("synthetic") or {}).get("status") or "")},
                    {"stage": "hdf5_export", "status": str((report.get("hdf5") or {}).get("status") or "")},
                    {"stage": "train_smoke", "status": str((report.get("train") or {}).get("status") or "")},
                ],
            }
        )
        return report

    def isaac_lab_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return latest synthetic pipeline status without launching external runtimes."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().status(request)

    def isaac_lab_check_outputs(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check latest Isaac Lab synthetic artifacts without launching external runtimes."""
        request = self._isaac_lab_synthetic_request(payload)
        return self._isaac_lab_synthetic_pipeline().check_outputs(request)

    def _record_or_launch_isaac_lab_runner(
        self,
        kind: str,
        request: IsaacLabSyntheticRequest,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if not result.get("ok"):
            return self._record_isaac_lab_immediate_job(kind, result)
        if not self._isaac_lab_live_runner_requested(request):
            return self._record_isaac_lab_immediate_job(kind, result)
        active_live_sessions = self._active_live_control_sessions(mode=str(request.mode or ""))
        if active_live_sessions:
            return self._record_isaac_lab_blocked_runner(
                kind,
                result,
                code="ISAAC_LAB_RUNNER_LIVE_SESSION_ACTIVE",
                message="Isaac Lab runner is blocked while live teleoperation, recording, or rollout is active.",
                details={"active_sessions": active_live_sessions},
            )
        return self._record_isaac_lab_running_job(kind, request, result)

    @staticmethod
    def _isaac_lab_live_runner_requested(request: IsaacLabSyntheticRequest) -> bool:
        return str(request.mode or "").lower() == "live" and not bool(request.dry_run)

    def _isaac_lab_live_e2e_request(self, request: IsaacLabSyntheticRequest) -> IsaacLabSyntheticRequest:
        visual_enabled = bool(request.isaac_lab_visualize_generation)
        camera_enabled = bool(request.mimic_enable_cameras)
        return request.model_copy(
            update={
                "mode": "live",
                "runtime_mode": "live",
                "dry_run": False,
                "e2e_create_fixture": False,
                "e2e_episodes": 3,
                "e2e_episode_s": 10,
                "e2e_fps": 15,
                "mimic_trials": 3,
                "mimic_enable_cameras": camera_enabled,
                "mimic_camera_width": 320,
                "mimic_camera_height": 240,
                "mimic_annotation_mode": "preannotated_passthrough",
                "isaac_lab_policy_task_name": (
                    "ATR-Robotis-OMX-PickPlace-Physical-v0"
                    if camera_enabled
                    else "ATR-Robotis-OMX-PickPlace-Physical-State-v0"
                ),
                "enable_mimic": True,
                "enable_hdf5_export": True,
                "enable_replicator": False,
            }
        )

    def _isaac_lab_live_e2e_command(self, request: IsaacLabSyntheticRequest) -> list[str]:
        request = self._isaac_lab_live_e2e_request(request)
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        script = self.config.repo_root / "scripts" / "lerobot_isaac_lab_e2e_smoke.py"
        env_python = Path.home() / "miniconda3" / "envs" / self.config.conda_env_name / "bin" / "python"
        python_executable = str(env_python if env_python.is_file() else Path(sys.executable or "python"))
        command = [
            python_executable,
            str(script),
            "--mode",
            "live",
            "--dataset-path",
            str(dataset_path),
            "--isaac-lab-path",
            str(Path(request.isaac_lab_path or "/home/jin/IsaacLab").expanduser()),
            "--isaac-sim-python",
            str(Path(request.isaac_sim_python or "/home/jin/IsaacSim/python.sh").expanduser()),
            "--trials",
            str(request.mimic_trials),
            "--num-envs",
            str(request.mimic_num_envs),
            "--domain-randomization-profile",
            str(request.domain_randomization_profile or "conservative"),
            "--repo-root",
            str(self.config.repo_root),
            "--no-create-fixture",
            "--episodes",
            str(request.e2e_episodes),
            "--episode-s",
            str(request.e2e_episode_s),
            "--fps",
            str(request.e2e_fps),
            "--mimic-camera-width",
            str(request.mimic_camera_width),
            "--mimic-camera-height",
            str(request.mimic_camera_height),
            "--stage-timeout-s",
            str(float(request.e2e_stage_timeout_s)),
        ]
        if request.isaac_lab_visualize_generation:
            command.append("--visualize-generation")
        command.append("--mimic-enable-cameras" if request.mimic_enable_cameras else "--no-mimic-enable-cameras")
        return command

    @staticmethod
    def _isaac_lab_live_e2e_output_root(request: IsaacLabSyntheticRequest, dataset_path: Path) -> Path:
        if request.output_root:
            return Path(request.output_root).expanduser().resolve()
        return dataset_path / "sidecar" / "isaac_lab_synthetic" / "latest"

    @staticmethod
    def _isaac_lab_live_e2e_artifact_checks(output_root: Path) -> list[dict[str, Any]]:
        specs = [
            ("hdf5_source", output_root / "hdf5" / "exported_successful_real_episodes.hdf5", "file"),
            ("hdf5_annotated", output_root / "hdf5" / "source_real_success_annotated.hdf5", "file"),
            ("mimic_generated_dataset", output_root / "mimic" / "generated_dataset.hdf5", "file"),
            ("mimic_successes", output_root / "mimic" / "successes.jsonl", "file"),
            ("il_robomimic", output_root / "il" / "robomimic", "dir"),
        ]
        checks: list[dict[str, Any]] = []
        for name, path, kind in specs:
            exists = path.is_dir() if kind == "dir" else path.is_file()
            checks.append(
                {
                    "name": name,
                    "path": str(path),
                    "kind": kind,
                    "status": "present" if exists else "missing",
                    "exists": exists,
                }
            )
        return checks

    @classmethod
    def _isaac_lab_live_e2e_artifact_error(cls, job: dict[str, Any]) -> str:
        output_root = Path(str(job.get("output_root") or (job.get("summary") or {}).get("output_root") or "")).expanduser()
        if not str(output_root):
            return "LIVE_E2E_OUTPUT_ROOT_MISSING"
        missing = [check["name"] for check in cls._isaac_lab_live_e2e_artifact_checks(output_root) if check.get("status") != "present"]
        return "LIVE_E2E_ARTIFACTS_MISSING:" + ",".join(missing) if missing else ""

    def _decorate_isaac_lab_live_e2e_job(self, job: dict[str, Any]) -> dict[str, Any]:
        output_root = Path(str(job.get("output_root") or (job.get("summary") or {}).get("output_root") or "")).expanduser()
        if str(output_root):
            job["artifact_checks"] = self._isaac_lab_live_e2e_artifact_checks(output_root)
            summary = dict(job.get("summary") or {})
            summary["artifact_checks"] = copy.deepcopy(job["artifact_checks"])
            job["summary"] = summary
        return job

    def _isaac_lab_live_e2e_job_response(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(payload.get("job_id") or "").strip()
        self._refresh_isaac_lab_runner_process("live_e2e", job_id)
        job = self._isaac_lab_job_snapshot("live_e2e", job_id)
        if not job:
            job = self._read_isaac_lab_job_manifest("live_e2e", payload)
        if not job:
            return self._isaac_lab_job_not_found_response(tool, job_id)
        job = self._decorate_isaac_lab_live_e2e_job(job)
        self._store_isaac_lab_job("live_e2e", job)
        return self._isaac_lab_job_response(tool, job)

    def _isaac_lab_live_e2e_blocked_response(
        self,
        request: IsaacLabSyntheticRequest,
        dataset_path: Path,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        output_root = self._isaac_lab_live_e2e_output_root(request, dataset_path)
        job = {
            "job_id": self._new_isaac_lab_job_id("live_e2e"),
            "kind": "live_e2e",
            "status": "BLOCKED",
            "progress": {"percent": 100.0, "stage": "blocked", "message": message},
            "summary": {
                "tool": "lerobot.isaac_lab.run_live_e2e_check",
                "dataset_path": str(dataset_path),
                "output_root": str(output_root),
                "artifact_checks": self._isaac_lab_live_e2e_artifact_checks(output_root),
            },
            "command": list((details or {}).get("command") or []),
            "output_root": str(output_root),
            "artifact_checks": self._isaac_lab_live_e2e_artifact_checks(output_root),
            "error": {"code": code, "message": message, **copy.deepcopy(details or {})},
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
            "stop_requested": False,
        }
        self._store_isaac_lab_job("live_e2e", job)
        return self._isaac_lab_job_response("lerobot.isaac_lab.live_e2e.start", job)

    @staticmethod
    def _isaac_lab_summary_key(kind: str) -> str:
        return {
            "annotate": "hdf5",
            "mimic": "mimic",
            "il_train": "training_exposure",
            "il_eval": "training_exposure",
            "rl_teacher": "rl_teacher",
            "live_e2e": "live_e2e",
        }.get(kind, kind)

    @staticmethod
    def _isaac_lab_hook_dir(kind: str) -> str:
        return {
            "annotate": "hdf5",
            "mimic": "mimic",
            "il_train": "il/robomimic",
            "il_eval": "il/eval",
            "rl_teacher": "rl_teacher",
            "live_e2e": "live_e2e",
        }.get(kind, kind)

    @staticmethod
    def _isaac_lab_hook_summary(kind: str, result: dict[str, Any]) -> dict[str, Any]:
        if kind == "annotate":
            hdf5_summary = result.get("hdf5") if isinstance(result.get("hdf5"), dict) else {}
            annotation = hdf5_summary.get("annotation") if isinstance(hdf5_summary.get("annotation"), dict) else {}
            return copy.deepcopy(annotation)
        if kind == "il_train":
            exposure = result.get("training_exposure") if isinstance(result.get("training_exposure"), dict) else {}
            return copy.deepcopy(exposure.get("il_train") if isinstance(exposure.get("il_train"), dict) else {})
        if kind == "il_eval":
            exposure = result.get("training_exposure") if isinstance(result.get("training_exposure"), dict) else {}
            return copy.deepcopy(exposure.get("il_eval") if isinstance(exposure.get("il_eval"), dict) else {})
        summary_key = LeRobotBridge._isaac_lab_summary_key(kind)
        return copy.deepcopy(result.get(summary_key) if isinstance(result.get(summary_key), dict) else {})

    @staticmethod
    def _with_isaac_lab_hook_summary(kind: str, result: dict[str, Any], hook_summary: dict[str, Any]) -> dict[str, Any]:
        decorated = copy.deepcopy(result)
        if kind == "annotate":
            hdf5_summary = dict(decorated.get("hdf5") if isinstance(decorated.get("hdf5"), dict) else {})
            hdf5_summary["annotation"] = hook_summary
            decorated["hdf5"] = hdf5_summary
            return decorated
        if kind in {"il_train", "il_eval"}:
            exposure = dict(decorated.get("training_exposure") if isinstance(decorated.get("training_exposure"), dict) else {})
            exposure["il_train" if kind == "il_train" else "il_eval"] = hook_summary
            decorated["training_exposure"] = exposure
            return decorated
        summary_key = LeRobotBridge._isaac_lab_summary_key(kind)
        decorated[summary_key] = hook_summary
        return decorated

    def _isaac_lab_result_summary(self, kind: str, result: dict[str, Any]) -> dict[str, Any]:
        summary_key = self._isaac_lab_summary_key(kind)
        return {
            "tool": result.get("tool", ""),
            "dataset_path": result.get("dataset_path", ""),
            "output_root": result.get("output_root", ""),
            "hdf5": copy.deepcopy(result.get("hdf5") or {}),
            summary_key: copy.deepcopy(result.get(summary_key) or {}),
            "runner": self._isaac_lab_hook_summary(kind, result),
            "validation_report": {
                "status": (result.get("validation_report") or {}).get("status"),
                "blockers": copy.deepcopy((result.get("validation_report") or {}).get("blockers") or []),
            },
        }

    def _record_isaac_lab_blocked_runner(
        self,
        kind: str,
        result: dict[str, Any],
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary_key = self._isaac_lab_summary_key(kind)
        hook_summary = self._isaac_lab_hook_summary(kind, result)
        runner = dict(hook_summary.get("runner") or {})
        runner.update(
            {
                "status": "blocked",
                "blocker": code,
                "message": message,
                **copy.deepcopy(details or {}),
            }
        )
        hook_summary["runner"] = runner
        decorated = self._with_isaac_lab_hook_summary(kind, result, hook_summary)
        decorated["ok"] = False
        decorated["status"] = "BLOCKED"
        decorated["error"] = {
            "code": code,
            "message": message,
            **copy.deepcopy(details or {}),
        }
        decorated["step_trace"] = list(decorated.get("step_trace") or []) + [
            {
                "stage": f"{summary_key}_runner",
                "status": "blocked",
                "message": message,
            }
        ]
        return self._record_isaac_lab_immediate_job(kind, decorated)

    def _record_isaac_lab_running_job(
        self,
        kind: str,
        request: IsaacLabSyntheticRequest,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        summary_key = self._isaac_lab_summary_key(kind)
        hook_summary = self._isaac_lab_hook_summary(kind, result)
        runner = dict(hook_summary.get("runner") or {})
        if not runner and hook_summary.get("command"):
            runner = dict(hook_summary)
        command = [str(item) for item in list(runner.get("command") or []) if str(item)]
        if len(command) < 2:
            return self._record_isaac_lab_blocked_runner(
                kind,
                result,
                code="ISAAC_LAB_RUNNER_COMMAND_MISSING",
                message="Isaac Lab runner command is missing from the synthetic summary.",
            )
        runtime_path = Path(command[0]).expanduser()
        script_path = _command_script_path(command)
        if not runtime_path.is_file():
            return self._record_isaac_lab_blocked_runner(
                kind,
                result,
                code="ISAAC_LAB_RUNNER_RUNTIME_MISSING",
                message=f"Isaac Sim Python runtime is missing: {runtime_path}",
                details={"command": command},
            )
        if not script_path.is_file():
            return self._record_isaac_lab_blocked_runner(
                kind,
                result,
                code="ISAAC_LAB_RUNNER_SCRIPT_MISSING",
                message=f"Isaac Lab runner script is missing: {script_path}",
                details={"command": command},
            )
        job_id = self._new_isaac_lab_job_id(kind)
        now = datetime.now(timezone.utc).isoformat()
        output_root = Path(str(result.get("output_root") or "")).expanduser().resolve()
        log_path = output_root / self._isaac_lab_hook_dir(kind) / "logs" / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cwd = Path(request.isaac_lab_path).expanduser().resolve() if request.isaac_lab_path else self.config.repo_root
        env = os.environ.copy()
        repo_root_text = str(self.config.repo_root.resolve())
        existing_pythonpath = str(env.get("PYTHONPATH") or "")
        env["PYTHONPATH"] = (
            repo_root_text
            if not existing_pythonpath
            else repo_root_text + os.pathsep + existing_pythonpath
        )
        if request.isaac_lab_visualize_generation:
            env["ROBOTIS_OMX_USE_FABRIC"] = "0"
        try:
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
        except OSError as exc:
            return self._record_isaac_lab_blocked_runner(
                kind,
                result,
                code="ISAAC_LAB_RUNNER_LAUNCH_FAILED",
                message=f"Isaac Lab runner could not be launched: {exc}",
                details={"command": command, "log_path": str(log_path)},
            )
        runner.update(
            {
                "status": "running",
                "pid": int(process.pid),
                "command": command,
                "cwd": str(cwd),
                "pythonpath_prefix": repo_root_text,
                "log_path": str(log_path),
                "started_at": now,
            }
        )
        hook_summary["runner"] = runner
        decorated = self._with_isaac_lab_hook_summary(kind, result, hook_summary)
        summary = self._isaac_lab_result_summary(kind, decorated)
        progress = {"percent": 5.0, "stage": "running"}
        job_manifest_path = self._isaac_lab_job_manifest_path(kind, result.get("output_root"))
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": "RUNNING",
            "progress": progress,
            "summary": summary,
            "command_preview": copy.deepcopy(runner.get("command_preview") or {}),
            "command": command,
            "primary_command": command,
            "post_run": copy.deepcopy(runner.get("post_run") or {}),
            "cwd": str(cwd),
            "pid": int(process.pid),
            "log_path": str(log_path),
            "runtime_smoke": copy.deepcopy(runner.get("runtime_smoke") or {}),
            "job_manifest_path": str(job_manifest_path) if job_manifest_path else "",
            "request_payload": request.model_dump(mode="json"),
            "error": None,
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "stop_requested": False,
        }
        self._store_isaac_lab_runner_process(kind, job_id, process)
        self._store_isaac_lab_job(kind, job)
        decorated["ok"] = True
        decorated["status"] = "RUNNING"
        decorated["job_id"] = job_id
        decorated["job"] = copy.deepcopy(job)
        decorated["progress"] = progress
        return decorated

    def _store_isaac_lab_runner_process(self, kind: str, job_id: str, process: subprocess.Popen[str]) -> None:
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            self._isaac_lab_runner_processes.setdefault(kind, {})[job_id] = process
        if kind == "mimic":
            with self._isaac_lab_mimic_lock:
                self._isaac_lab_mimic_processes[job_id] = process
            return
        if kind == "rl_teacher":
            with self._isaac_lab_rl_teacher_lock:
                self._isaac_lab_rl_teacher_processes[job_id] = process
            return

    def _store_isaac_lab_job(self, kind: str, job: dict[str, Any]) -> None:
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            self._isaac_lab_runner_jobs.setdefault(kind, {})[str(job["job_id"])] = job
            self._isaac_lab_runner_latest_job_id[kind] = str(job["job_id"])
        if kind == "mimic":
            with self._isaac_lab_mimic_lock:
                self._isaac_lab_mimic_jobs[str(job["job_id"])] = job
                self._isaac_lab_mimic_latest_job_id = str(job["job_id"])
            self._write_isaac_lab_job_manifest(job)
            return
        if kind == "rl_teacher":
            with self._isaac_lab_rl_teacher_lock:
                self._isaac_lab_rl_teacher_jobs[str(job["job_id"])] = job
                self._isaac_lab_rl_teacher_latest_job_id = str(job["job_id"])
        self._write_isaac_lab_job_manifest(job)

    def _record_isaac_lab_immediate_job(self, kind: str, result: dict[str, Any]) -> dict[str, Any]:
        job_id = self._new_isaac_lab_job_id(kind)
        status = self._isaac_lab_job_status_from_result(result)
        now = datetime.now(timezone.utc).isoformat()
        job_manifest_path = self._isaac_lab_job_manifest_path(kind, result.get("output_root"))
        hook_summary = self._isaac_lab_hook_summary(kind, result)
        smoke_summary = hook_summary.get("smoke") if isinstance(hook_summary.get("smoke"), dict) else {}
        summary = self._isaac_lab_result_summary(kind, result)
        progress = {"percent": 100.0, "stage": status.lower()}
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": status,
            "progress": progress,
            "summary": summary,
            "command_preview": copy.deepcopy(smoke_summary.get("command_preview") or {}),
            "runtime_smoke": copy.deepcopy(smoke_summary.get("runtime_smoke") or {}),
            "job_manifest_path": str(job_manifest_path) if job_manifest_path else "",
            "error": copy.deepcopy(result.get("error")) if status == "FAILED" else None,
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "completed_at": now,
            "stop_requested": False,
        }
        self._store_isaac_lab_job(kind, job)
        decorated = dict(result)
        decorated["job_id"] = job_id
        decorated["job"] = copy.deepcopy(job)
        decorated.setdefault("progress", progress)
        return decorated

    def _isaac_lab_job_manifest_path(self, kind: str, output_root_value: Any) -> Path | None:
        output_root_text = str(output_root_value or "").strip()
        if not output_root_text:
            return None
        try:
            output_root = Path(output_root_text).expanduser().resolve()
        except OSError:
            return None
        if not self._is_under_allowed_roots(output_root):
            return None
        hook_dir = self._isaac_lab_hook_dir(kind)
        return output_root / hook_dir / "job.json"

    def _write_isaac_lab_job_manifest(self, job: dict[str, Any]) -> None:
        summary = job.get("summary") if isinstance(job.get("summary"), dict) else {}
        manifest_path = self._isaac_lab_job_manifest_path(str(job.get("kind") or ""), summary.get("output_root"))
        if manifest_path is None:
            return
        job["job_manifest_path"] = str(manifest_path)
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp.{os.getpid()}")
            tmp_path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(manifest_path)
        except OSError:
            return

    def _read_isaac_lab_job_manifest(self, kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            request = self._isaac_lab_synthetic_request(payload)
        except Exception:
            return None
        try:
            dataset_path = Path(request.dataset_path).expanduser().resolve()
            output_root = Path(request.output_root).expanduser().resolve() if request.output_root else self._dataset_isaac_lab_synthetic_root(dataset_path).resolve()
        except OSError:
            return None
        manifest_path = self._isaac_lab_job_manifest_path(kind, output_root)
        if manifest_path is None or not manifest_path.is_file():
            return None
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(job, dict) or str(job.get("kind") or "") != kind:
            return None
        requested_job_id = str(payload.get("job_id") or "").strip()
        if requested_job_id and str(job.get("job_id") or "") != requested_job_id:
            return None
        job["job_manifest_path"] = str(manifest_path)
        self._store_isaac_lab_job(kind, copy.deepcopy(job))
        return job

    @staticmethod
    def _new_isaac_lab_job_id(kind: str) -> str:
        prefix = {
            "annotate": "isaac_lab_annotate",
            "mimic": "isaac_lab_mimic",
            "il_train": "isaac_lab_il_train",
            "il_eval": "isaac_lab_il_eval",
            "rl_teacher": "isaac_lab_rl_teacher",
        }.get(kind, f"isaac_lab_{kind}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _isaac_lab_job_status_from_result(result: dict[str, Any]) -> str:
        if result.get("ok"):
            return "COMPLETED"
        status = str(result.get("status") or "").upper()
        if status == "BLOCKED":
            return "BLOCKED"
        return "FAILED"

    def _isaac_lab_job_snapshot(self, kind: str, job_id: str = "") -> dict[str, Any] | None:
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            resolved = job_id or self._isaac_lab_runner_latest_job_id.get(kind, "")
            job = self._isaac_lab_runner_jobs.setdefault(kind, {}).get(resolved)
            if job:
                return copy.deepcopy(job)
        if kind == "mimic":
            with self._isaac_lab_mimic_lock:
                resolved = job_id or self._isaac_lab_mimic_latest_job_id
                job = self._isaac_lab_mimic_jobs.get(resolved)
                return copy.deepcopy(job) if job else None
        with self._isaac_lab_rl_teacher_lock:
            resolved = job_id or self._isaac_lab_rl_teacher_latest_job_id
            job = self._isaac_lab_rl_teacher_jobs.get(resolved)
            return copy.deepcopy(job) if job else None

    def _refresh_isaac_lab_runner_process(self, kind: str, job_id: str = "") -> None:
        refreshed: dict[str, Any] | None = None
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            resolved = job_id or self._isaac_lab_runner_latest_job_id.get(kind, "")
            job = self._isaac_lab_runner_jobs.setdefault(kind, {}).get(resolved)
            process = self._isaac_lab_runner_processes.setdefault(kind, {}).get(resolved)
            if not job or not process or str(job.get("status") or "").upper() != "RUNNING":
                return
            returncode = process.poll()
            if returncode is None:
                active_failure = self._isaac_lab_active_runner_failure(kind, job)
                if active_failure:
                    self._terminate_live_process(process, signal.SIGTERM)
                    self._isaac_lab_runner_processes.setdefault(kind, {}).pop(resolved, None)
                    refreshed = self._fail_isaac_lab_runner_job(job, **active_failure)
                    self._isaac_lab_runner_jobs.setdefault(kind, {})[resolved] = refreshed
                else:
                    return
            else:
                self._isaac_lab_runner_processes.setdefault(kind, {}).pop(resolved, None)
                refreshed = self._complete_isaac_lab_runner_job(job, int(returncode))
                if self._isaac_lab_post_run_was_running(job):
                    post_run = dict(refreshed.get("post_run") or {})
                    post_run["status"] = "completed" if refreshed.get("status") == "COMPLETED" else "failed"
                    post_run["returncode"] = int(returncode)
                    post_run["completed_at"] = refreshed.get("completed_at")
                    refreshed["post_run"] = post_run
                    if (
                        kind == "mimic"
                        and refreshed.get("status") == "COMPLETED"
                        and int(returncode) == 0
                        and str(post_run.get("stage") or "") in {"replay_validate_after_generation", "rgbd_render_after_generation"}
                    ):
                        refreshed = self._refresh_isaac_lab_training_import_after_post_run(refreshed)
                elif refreshed.get("status") == "COMPLETED" and self._isaac_lab_post_run_enabled(refreshed):
                    refreshed, post_process = self._start_isaac_lab_post_run_process(kind, refreshed)
                    if post_process is not None:
                        self._isaac_lab_runner_processes.setdefault(kind, {})[resolved] = post_process
                self._isaac_lab_runner_jobs.setdefault(kind, {})[resolved] = refreshed
        if refreshed is None:
            return
        if kind == "mimic":
            with self._isaac_lab_mimic_lock:
                self._isaac_lab_mimic_processes.pop(resolved, None)
                self._isaac_lab_mimic_jobs[resolved] = refreshed
        elif kind == "rl_teacher":
            with self._isaac_lab_rl_teacher_lock:
                self._isaac_lab_rl_teacher_processes.pop(resolved, None)
                self._isaac_lab_rl_teacher_jobs[resolved] = refreshed
        if refreshed is not None:
            self._write_isaac_lab_job_manifest(refreshed)

    @staticmethod
    def _isaac_lab_post_run_was_running(job: dict[str, Any]) -> bool:
        post_run = job.get("post_run") if isinstance(job.get("post_run"), dict) else {}
        return str(post_run.get("status") or "").lower() == "running"

    def _refresh_isaac_lab_training_import_after_post_run(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = dict(job.get("request_payload") if isinstance(job.get("request_payload"), dict) else {})
        summary = job.get("summary") if isinstance(job.get("summary"), dict) else {}
        dataset_path = str(payload.get("dataset_path") or summary.get("dataset_path") or "").strip()
        output_root = str(payload.get("output_root") or summary.get("output_root") or "").strip()
        post_run = dict(job.get("post_run") if isinstance(job.get("post_run"), dict) else {})
        if not dataset_path or not output_root:
            post_run["training_import_refresh"] = {
                "ok": False,
                "status": "BLOCKED",
                "error": {
                    "code": "ISAAC_LAB_POST_RUN_REFRESH_CONTEXT_MISSING",
                    "message": "Cannot refresh Isaac Lab training import after post-run without dataset_path and output_root.",
                },
            }
            job["post_run"] = post_run
            return job
        refresh_payload = {
            **payload,
            "dataset_path": dataset_path,
            "output_root": output_root,
            "enable_mimic": True,
            "force_rebuild": False,
            "overwrite_latest": False,
            "resume": True,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
        try:
            request = self._isaac_lab_synthetic_request(refresh_payload)
            refreshed = self._isaac_lab_synthetic_pipeline().build_synthetic(request)
        except Exception as exc:  # noqa: BLE001 - status response should preserve refresh failures.
            refreshed = {
                "ok": False,
                "status": "BLOCKED",
                "error": {
                    "code": "ISAAC_LAB_POST_RUN_REFRESH_FAILED",
                    "message": f"Training import refresh after Isaac Lab post-run failed: {exc}",
                },
            }
        post_run["training_import_refresh"] = copy.deepcopy(refreshed)
        job["post_run"] = post_run
        summary = dict(summary)
        if isinstance(refreshed, dict):
            if isinstance(refreshed.get("training_exposure"), dict):
                summary["training_exposure"] = copy.deepcopy(refreshed["training_exposure"])
            if isinstance(refreshed.get("mimic"), dict):
                summary["mimic"] = copy.deepcopy(refreshed["mimic"])
                summary["runner"] = copy.deepcopy(refreshed["mimic"])
            if isinstance(refreshed.get("validation_report"), dict):
                summary["validation_report"] = {
                    "status": refreshed["validation_report"].get("status"),
                    "blockers": copy.deepcopy(refreshed["validation_report"].get("blockers") or []),
                }
        job["summary"] = summary
        if not bool(refreshed.get("ok")):
            job["status"] = "BLOCKED"
            job["progress"] = {"percent": 100.0, "stage": "training_import_refresh_blocked"}
            job["error"] = copy.deepcopy(refreshed.get("error")) or {
                "code": "ISAAC_LAB_POST_RUN_REFRESH_BLOCKED",
                "message": "Isaac Lab post-run completed, but training import refresh did not pass.",
            }
        return job

    @staticmethod
    def _isaac_lab_post_run_enabled(job: dict[str, Any]) -> bool:
        post_run = job.get("post_run") if isinstance(job.get("post_run"), dict) else {}
        command = [str(item) for item in list(post_run.get("command") or []) if str(item)]
        return bool(post_run.get("enabled") and len(command) >= 2 and not post_run.get("started_at"))

    def _start_isaac_lab_post_run_process(
        self,
        kind: str,
        job: dict[str, Any],
    ) -> tuple[dict[str, Any], subprocess.Popen[str] | None]:
        post_run = dict(job.get("post_run") if isinstance(job.get("post_run"), dict) else {})
        command = [str(item) for item in list(post_run.get("command") or []) if str(item)]
        now = datetime.now(timezone.utc).isoformat()
        if len(command) < 2:
            failed = copy.deepcopy(job)
            failed["status"] = "FAILED"
            failed["progress"] = {"percent": 100.0, "stage": "failed"}
            failed["updated_at"] = now
            failed["completed_at"] = now
            failed["error"] = {
                "code": "ISAAC_LAB_POST_RUN_COMMAND_MISSING",
                "message": "Isaac Lab post-run preview command is missing.",
            }
            post_run["status"] = "failed"
            post_run["completed_at"] = now
            failed["post_run"] = post_run
            return failed, None
        runtime_path = Path(command[0]).expanduser()
        script_path = _command_script_path(command)
        if not runtime_path.is_file() or not script_path.is_file():
            failed = copy.deepcopy(job)
            failed["status"] = "FAILED"
            failed["progress"] = {"percent": 100.0, "stage": "failed"}
            failed["updated_at"] = now
            failed["completed_at"] = now
            failed["error"] = {
                "code": "ISAAC_LAB_POST_RUN_COMMAND_INVALID",
                "message": "Isaac Lab post-run preview runtime or script is missing.",
                "runtime": str(runtime_path),
                "script": str(script_path),
            }
            post_run["status"] = "failed"
            post_run["completed_at"] = now
            failed["post_run"] = post_run
            return failed, None

        cwd = str(job.get("cwd") or self.config.repo_root)
        log_path = Path(str(job.get("log_path") or "")).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        repo_root_text = str(self.config.repo_root.resolve())
        existing_pythonpath = str(env.get("PYTHONPATH") or "")
        env["PYTHONPATH"] = (
            repo_root_text
            if not existing_pythonpath
            else repo_root_text + os.pathsep + existing_pythonpath
        )
        env["ROBOTIS_OMX_USE_FABRIC"] = "0"
        try:
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
        except OSError as exc:
            failed = copy.deepcopy(job)
            failed["status"] = "FAILED"
            failed["progress"] = {"percent": 100.0, "stage": "failed"}
            failed["updated_at"] = now
            failed["completed_at"] = now
            failed["error"] = {
                "code": "ISAAC_LAB_POST_RUN_LAUNCH_FAILED",
                "message": f"Isaac Lab post-run preview could not be launched: {exc}",
                "command": command,
            }
            post_run["status"] = "failed"
            post_run["completed_at"] = now
            failed["post_run"] = post_run
            return failed, None

        running = copy.deepcopy(job)
        running["status"] = "RUNNING"
        stage = str(post_run.get("stage") or "")
        if stage == "rgbd_render_after_generation":
            progress_stage = "rgbd_render_running"
        elif stage == "replay_validate_after_generation":
            progress_stage = "replay_validation_running"
        else:
            progress_stage = "preview_running"
        running["progress"] = {"percent": 95.0, "stage": progress_stage}
        running["primary_command"] = list(job.get("primary_command") or job.get("command") or [])
        running["command"] = command
        running["pid"] = int(process.pid)
        running["updated_at"] = now
        running["completed_at"] = None
        running["error"] = None
        post_run.update(
            {
                "enabled": True,
                "status": "running",
                "pid": int(process.pid),
                "started_at": now,
                "command": command,
                "log_path": str(log_path),
            }
        )
        running["post_run"] = post_run
        return running, process

    @staticmethod
    def _isaac_lab_job_log_text(job: dict[str, Any], *, max_chars: int = 200000) -> str:
        log_path = Path(str(job.get("log_path") or "")).expanduser()
        if not log_path.is_file():
            return ""
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
        except OSError:
            return ""

    @classmethod
    def _isaac_lab_active_runner_failure(cls, kind: str, job: dict[str, Any]) -> dict[str, str] | None:
        if kind != "mimic":
            return None
        text = cls._isaac_lab_job_log_text(job)
        attempts = [int(match.group(1)) for match in re.finditer(r"0/(\d+)\s+\(0\.0%\)\s+successful demos generated by mimic", text)]
        if not attempts:
            return None
        max_attempts = max(attempts)
        if max_attempts < 9:
            return None
        return {
            "code": "ISAAC_LAB_MIMIC_ZERO_SUCCESS_ATTEMPTS",
            "message": (
                "Isaac Lab Mimic generated zero successful demos after "
                f"{max_attempts} attempts; stopping the runner instead of waiting indefinitely."
            ),
            "log_tail": text[-2000:],
        }

    @staticmethod
    def _fail_isaac_lab_runner_job(job: dict[str, Any], *, code: str, message: str, log_tail: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        failed = copy.deepcopy(job)
        failed["status"] = "FAILED"
        failed["returncode"] = None
        failed["progress"] = {"percent": 100.0, "stage": "failed"}
        failed["updated_at"] = now
        failed["completed_at"] = now
        failed["error"] = {"code": code, "message": message, "log_tail": log_tail[-2000:]}
        return failed

    def _normalize_isaac_lab_runner_status(self, kind: str, job: dict[str, Any]) -> dict[str, Any]:
        status = str(job.get("status") or "").upper()
        if status != "RUNNING":
            error = job.get("error") if isinstance(job.get("error"), dict) else {}
            if status == "FAILED" and str(error.get("code") or "") == "ISAAC_LAB_RUNNER_PROCESS_EXITED":
                recovered = self._recover_completed_isaac_lab_post_run_job(kind, job)
                if recovered is not None:
                    return recovered
            return job
        active_failure = self._isaac_lab_active_runner_failure(kind, job)
        if active_failure:
            normalized = self._fail_isaac_lab_runner_job(job, **active_failure)
        elif self._isaac_lab_tracked_runner_process_alive(kind, job):
            return job
        elif not self._isaac_lab_runner_pid_alive(job):
            recovered = self._recover_completed_isaac_lab_post_run_job(kind, job)
            if recovered is not None:
                return recovered
            normalized = self._fail_isaac_lab_runner_job(
                job,
                code="ISAAC_LAB_RUNNER_PROCESS_EXITED",
                message="Isaac Lab runner process is no longer alive while the manifest still says RUNNING.",
                log_tail=self._isaac_lab_job_log_text(job, max_chars=2000),
            )
        else:
            return job
        resolved = str(normalized.get("job_id") or "")
        if resolved:
            lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
            with lock:
                self._isaac_lab_runner_jobs.setdefault(kind, {})[resolved] = copy.deepcopy(normalized)
            if kind == "mimic":
                with self._isaac_lab_mimic_lock:
                    self._isaac_lab_mimic_jobs[resolved] = copy.deepcopy(normalized)
            elif kind == "rl_teacher":
                with self._isaac_lab_rl_teacher_lock:
                    self._isaac_lab_rl_teacher_jobs[resolved] = copy.deepcopy(normalized)
        self._write_isaac_lab_job_manifest(normalized)
        return normalized

    def _recover_completed_isaac_lab_post_run_job(self, kind: str, job: dict[str, Any]) -> dict[str, Any] | None:
        if kind != "mimic":
            return None
        post_run = dict(job.get("post_run") if isinstance(job.get("post_run"), dict) else {})
        if str(post_run.get("stage") or "") != "replay_validate_after_generation":
            return None
        summary_path_text = str(post_run.get("summary_file") or "").strip()
        if not summary_path_text:
            command = [str(item) for item in list(post_run.get("command") or [])]
            summary_path_text = self._command_option_value(command, "--summary-file")
        if not summary_path_text:
            return None
        replay_summary = self._read_json_dict(Path(summary_path_text).expanduser())
        if not replay_summary:
            return None
        if not bool(replay_summary.get("ok")):
            return None
        if str(replay_summary.get("status") or "").lower() not in {"completed", "passed", "ok"}:
            return None

        now = datetime.now(timezone.utc).isoformat()
        recovered = copy.deepcopy(job)
        recovered["status"] = "COMPLETED"
        recovered["returncode"] = 0
        recovered["progress"] = {"percent": 100.0, "stage": "completed"}
        recovered["updated_at"] = now
        recovered["completed_at"] = now
        recovered["error"] = None
        post_run.update(
            {
                "status": "completed",
                "returncode": 0,
                "completed_at": now,
                "replay_validation_summary": copy.deepcopy(replay_summary),
            }
        )
        recovered["post_run"] = post_run
        recovered = self._refresh_isaac_lab_training_import_after_post_run(recovered)

        resolved = str(recovered.get("job_id") or "")
        if resolved:
            lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
            with lock:
                self._isaac_lab_runner_jobs.setdefault(kind, {})[resolved] = copy.deepcopy(recovered)
            with self._isaac_lab_mimic_lock:
                self._isaac_lab_mimic_jobs[resolved] = copy.deepcopy(recovered)
        self._write_isaac_lab_job_manifest(recovered)
        return recovered

    @staticmethod
    def _jsonl_line_count(path: Path) -> int:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    @staticmethod
    def _command_option_value(command: list[Any], option: str) -> str:
        items = [str(item) for item in command]
        if option not in items:
            return ""
        index = items.index(option)
        if index + 1 >= len(items):
            return ""
        return items[index + 1]

    def _decorate_isaac_lab_mimic_rgbd_progress(self, job: dict[str, Any]) -> dict[str, Any]:
        if str(job.get("status") or "").upper() != "RUNNING":
            return job
        post_run = job.get("post_run") if isinstance(job.get("post_run"), dict) else {}
        if str(post_run.get("stage") or "") != "rgbd_render_after_generation":
            return job
        render_root_text = str(post_run.get("render_root") or "").strip()
        if not render_root_text:
            render_root_text = self._command_option_value(list(post_run.get("command") or job.get("command") or []), "--rgbd-output-dir")
        if not render_root_text:
            return job
        render_root = Path(render_root_text).expanduser()
        output_root = render_root.parent.parent if render_root.name == "renders" and render_root.parent.name == "mimic_rgbd" else Path()
        expected_demos = 0
        if str(output_root):
            replay_successes = output_root / "mimic" / "replay_successes.jsonl"
            mimic_successes = output_root / "mimic" / "successes.jsonl"
            expected_demos = max(self._jsonl_line_count(replay_successes), self._jsonl_line_count(mimic_successes))
        staging_parent = render_root.parent / ".render_staging"
        staging_demo_dirs: list[Path] = []
        if staging_parent.is_dir():
            for staging_render_root in sorted(staging_parent.glob("*/renders")):
                if staging_render_root.is_dir():
                    staging_demo_dirs.extend(sorted(path for path in staging_render_root.glob("demo_*") if path.is_dir()))
        demo_dirs = staging_demo_dirs
        if not demo_dirs and render_root.is_dir():
            demo_dirs = sorted(path for path in render_root.glob("demo_*") if path.is_dir())
        if expected_demos <= 0:
            expected_demos = max(1, len(demo_dirs))
        manifest_counts = [self._jsonl_line_count(path / "manifest.jsonl") for path in demo_dirs]
        rendered_files = 0
        for path in demo_dirs:
            try:
                rendered_files += sum(1 for child in path.rglob("*") if child.is_file())
            except OSError:
                continue
        per_demo_units = max(manifest_counts) if manifest_counts else 0
        rendered_units = sum(min(count, per_demo_units) for count in manifest_counts) if per_demo_units > 0 else 0
        total_units = expected_demos * per_demo_units if per_demo_units > 0 else expected_demos
        if total_units > 0 and rendered_units > 0:
            percent = min(99.0, max(5.0, (rendered_units / total_units) * 100.0))
        else:
            percent = 5.0
        decorated = copy.deepcopy(job)
        decorated["progress"] = {
            "percent": round(percent, 2),
            "stage": "rgbd_render_running",
            "done": rendered_units,
            "total": total_units,
            "message": f"demos={len(demo_dirs)}/{expected_demos} · files={rendered_files}",
            "rendered_demos": len(demo_dirs),
            "expected_demos": expected_demos,
            "render_manifest_lines": rendered_units,
        }
        return decorated

    def _isaac_lab_tracked_runner_process_alive(self, kind: str, job: dict[str, Any]) -> bool:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return False
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            process = self._isaac_lab_runner_processes.setdefault(kind, {}).get(job_id)
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            return False

    @staticmethod
    def _isaac_lab_runner_pid_alive(job: dict[str, Any]) -> bool:
        try:
            pid = int(job.get("pid") or 0)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _complete_isaac_lab_runner_job(job: dict[str, Any], returncode: int) -> dict[str, Any]:
        log_tail = ""
        log_scan = ""
        log_path = Path(str(job.get("log_path") or "")).expanduser()
        if log_path.is_file():
            try:
                log_text = log_path.read_text(encoding="utf-8", errors="replace")
                log_scan = log_text[-200000:]
                log_tail = log_text[-8000:]
            except OSError:
                log_tail = ""
                log_scan = ""
        failure_markers = (
            "Traceback (most recent call last):",
            "NotImplementedError:",
            "KeyError:",
            "TypeError:",
            "AttributeError:",
            "ValueError:",
            "RuntimeError:",
            "There was an error running python",
        )
        log_failed = any(marker in log_scan for marker in failure_markers)
        artifact_error = ""
        if returncode == 0 and not log_failed:
            if str(job.get("kind") or "") == "live_e2e":
                artifact_error = LeRobotBridge._isaac_lab_live_e2e_artifact_error(job)
            else:
                artifact_error = LeRobotBridge._isaac_lab_runner_hdf5_output_error(job)
        status = "COMPLETED" if returncode == 0 and not log_failed and not artifact_error else "FAILED"
        now = datetime.now(timezone.utc).isoformat()
        job["status"] = status
        job["returncode"] = returncode
        job["progress"] = {"percent": 100.0, "stage": status.lower()}
        if str(job.get("kind") or "") == "live_e2e":
            output_root = Path(str(job.get("output_root") or (job.get("summary") or {}).get("output_root") or "")).expanduser()
            job["artifact_checks"] = LeRobotBridge._isaac_lab_live_e2e_artifact_checks(output_root)
            summary = dict(job.get("summary") or {})
            summary["artifact_checks"] = copy.deepcopy(job["artifact_checks"])
            job["summary"] = summary
        job["updated_at"] = now
        job["completed_at"] = now
        job["error"] = None
        if status == "FAILED":
            job["error"] = {
                "code": "ISAAC_LAB_RUNNER_FAILED",
                "message": (
                    f"Isaac Lab runner exited with returncode={returncode}; "
                    f"log_failed={log_failed}; artifact_error={artifact_error or 'none'}."
                ),
                "log_tail": log_tail[-2000:],
            }
        return copy.deepcopy(job)

    @staticmethod
    def _isaac_lab_runner_hdf5_output_error(job: dict[str, Any]) -> str:
        kind = str(job.get("kind") or "")
        if kind not in {"annotate", "mimic"}:
            return ""
        command = [str(item) for item in list(job.get("command") or [])]
        output_flag = "--output_file" if "--output_file" in command else "--output-file" if "--output-file" in command else ""
        if not output_flag:
            return ""
        index = command.index(output_flag)
        if index + 1 >= len(command):
            return "HDF5_OUTPUT_ARGUMENT_MISSING"
        output_path = Path(command[index + 1]).expanduser()
        if not output_path.is_file():
            return f"HDF5_OUTPUT_MISSING:{output_path}"
        try:
            import h5py

            with h5py.File(output_path, "r") as handle:
                data = handle.get("data")
                if data is None:
                    return f"HDF5_DATA_GROUP_MISSING:{output_path}"
                if len(data.keys()) <= 0:
                    return f"HDF5_DATA_EMPTY:{output_path}"
        except Exception as exc:  # noqa: BLE001 - job status must preserve HDF5 open failures.
            return f"HDF5_OUTPUT_INVALID:{exc.__class__.__name__}:{exc}"
        return ""

    def _isaac_lab_job_status(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(payload.get("job_id") or "").strip()
        self._refresh_isaac_lab_runner_process(kind, job_id)
        job = self._isaac_lab_job_snapshot(kind, job_id)
        if not job:
            job = self._read_isaac_lab_job_manifest(kind, payload)
        tool = f"lerobot.isaac_lab.{kind}.status"
        if not job:
            return self._isaac_lab_job_not_found_response(tool, job_id)
        job = self._normalize_isaac_lab_runner_status(kind, job)
        if kind == "mimic":
            job = self._decorate_isaac_lab_mimic_rgbd_progress(job)
        return self._isaac_lab_job_response(tool, job)

    def _isaac_lab_job_stop(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(payload.get("job_id") or "").strip()
        tool = f"lerobot.isaac_lab.{kind}.stop"
        terminal = {"BLOCKED", "COMPLETED", "FAILED", "STOPPED"}
        self._refresh_isaac_lab_runner_process(kind, job_id)
        if not self._isaac_lab_job_snapshot(kind, job_id):
            self._read_isaac_lab_job_manifest(kind, payload)
        lock = self._isaac_lab_runner_locks.setdefault(kind, threading.Lock())
        with lock:
            resolved = job_id or self._isaac_lab_runner_latest_job_id.get(kind, "")
            job = self._isaac_lab_runner_jobs.setdefault(kind, {}).get(resolved)
            if not job:
                return self._isaac_lab_job_not_found_response(tool, resolved)
            if str(job.get("status") or "").upper() not in terminal:
                process = self._isaac_lab_runner_processes.setdefault(kind, {}).pop(resolved, None)
                if process is not None:
                    self._terminate_live_process(process, signal.SIGTERM)
                job["status"] = "STOPPED"
                job["progress"] = {"percent": 100.0, "stage": "stopped"}
                job["stop_requested"] = True
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
            elif str(job.get("status") or "").upper() == "STOPPED":
                job["progress"] = {"percent": 100.0, "stage": "stopped"}
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            public_job = copy.deepcopy(job)
        if kind == "mimic":
            with self._isaac_lab_mimic_lock:
                self._isaac_lab_mimic_processes.pop(resolved, None)
                self._isaac_lab_mimic_jobs[resolved] = public_job
        elif kind == "rl_teacher":
            with self._isaac_lab_rl_teacher_lock:
                self._isaac_lab_rl_teacher_processes.pop(resolved, None)
                self._isaac_lab_rl_teacher_jobs[resolved] = public_job
        self._write_isaac_lab_job_manifest(public_job)
        return self._isaac_lab_job_response(tool, public_job)

    @staticmethod
    def _isaac_lab_job_response(tool: str, job: dict[str, Any]) -> dict[str, Any]:
        status = str(job.get("status") or "FAILED").upper()
        return {
            "ok": status != "FAILED",
            "tool": tool,
            "status": status,
            "job_id": str(job.get("job_id") or ""),
            "progress": copy.deepcopy(job.get("progress") or {}),
            "summary": copy.deepcopy(job.get("summary") or {}),
            "error": copy.deepcopy(job.get("error")) if status == "FAILED" else None,
            "stop_requested": bool(job.get("stop_requested")),
            "job": copy.deepcopy(job),
        }

    @staticmethod
    def _isaac_lab_job_not_found_response(tool: str, job_id: str = "") -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool,
            "status": "FAILED",
            "job_id": job_id,
            "progress": {},
            "summary": {},
            "error": {
                "code": "ISAAC_LAB_JOB_NOT_FOUND",
                "message": "Isaac Lab job was not found in the current bridge process.",
            },
            "stop_requested": False,
            "job": {},
        }

    def isaac_rgbd_render_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render missing Isaac RGB-D sidecar frames after recording has completed."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.isaac_rgbd.render.start",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        job_id = self._isaac_rgbd_post_render_job_id(dataset_path, request.session_id)
        with self._isaac_rgbd_render_lock:
            existing = self._isaac_rgbd_render_jobs.get(job_id)
            if existing and str(existing.get("status") or "").upper() in {"RUNNING", "STOPPING"}:
                return self._isaac_rgbd_post_render_response(
                    "lerobot.isaac_rgbd.render.start",
                    mode,
                    profile_id,
                    dataset_path,
                    dict(existing),
                    idempotent=True,
                )
        episode_indices = self._isaac_rgbd_post_render_episode_filter(
            getattr(request, "isaac_rgbd_post_render_episode_indices", "")
        )
        candidates = self._isaac_rgbd_post_render_candidates(
            dataset_path,
            request.session_id,
            episode_indices=episode_indices,
        )
        overwrite = bool(getattr(request, "isaac_rgbd_post_render_overwrite", False))
        overwrite_summary = self._stage_isaac_rgbd_overwrite_candidates(dataset_path, candidates, job_id) if overwrite else {}
        job = self._new_isaac_rgbd_post_render_job(job_id, dataset_path, request.session_id, candidates)
        if episode_indices is not None:
            job["episode_indices"] = sorted(episode_indices)
        if overwrite:
            job["overwrite"] = True
            job["overwrite_summary"] = overwrite_summary
        with self._isaac_rgbd_render_lock:
            self._isaac_rgbd_render_jobs[job_id] = job
        if bool(getattr(request, "isaac_rgbd_post_render_inline", False)):
            self._run_isaac_rgbd_post_render_job(
                job_id,
                candidates,
                post_timeout_s=0.5,
                poll_timeout_s=_safe_float(getattr(request, "isaac_rgbd_post_render_poll_timeout_s", 10.0), 10.0, minimum=0.1, maximum=120.0),
            )
        else:
            worker = threading.Thread(
                target=self._run_isaac_rgbd_post_render_job,
                args=(job_id, candidates),
                kwargs={
                    "post_timeout_s": 0.5,
                    "poll_timeout_s": _safe_float(
                        getattr(request, "isaac_rgbd_post_render_poll_timeout_s", 10.0),
                        10.0,
                        minimum=0.1,
                        maximum=120.0,
                    ),
                },
                name=f"atr-isaac-rgbd-post-render-{job_id[:12]}",
                daemon=True,
            )
            with self._isaac_rgbd_render_lock:
                self._isaac_rgbd_render_threads[job_id] = worker
            worker.start()
        with self._isaac_rgbd_render_lock:
            public_job = dict(self._isaac_rgbd_render_jobs.get(job_id, job))
        return self._isaac_rgbd_post_render_response("lerobot.isaac_rgbd.render.start", mode, profile_id, dataset_path, public_job)

    def isaac_rgbd_render_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the current or discovered Isaac RGB-D post-record render status."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = Path(self._dataset_path_for(request)).expanduser().resolve()
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.isaac_rgbd.render.status",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        job_id = self._isaac_rgbd_post_render_job_id(dataset_path, request.session_id)
        with self._isaac_rgbd_render_lock:
            job = dict(self._isaac_rgbd_render_jobs.get(job_id, {}))
        if not job:
            episode_indices = self._isaac_rgbd_post_render_episode_filter(
                getattr(request, "isaac_rgbd_post_render_episode_indices", "")
            )
            candidates = self._isaac_rgbd_post_render_candidates(
                dataset_path,
                request.session_id,
                episode_indices=episode_indices,
            )
            job = self._new_isaac_rgbd_post_render_job(job_id, dataset_path, request.session_id, candidates)
            if episode_indices is not None:
                job["episode_indices"] = sorted(episode_indices)
            done_index = self._isaac_rgbd_render_done_index(candidates)
            done = skipped = 0
            for candidate in candidates:
                if self._isaac_rgbd_render_candidate_done(candidate, done_index=done_index):
                    done += 1
                    skipped += 1
            job.update(
                {
                    "status": "COMPLETED" if done == len(candidates) else "IDLE",
                    "done": done,
                    "skipped": skipped,
                    "pending": max(0, len(candidates) - done),
                    "percent": self._percent(done, len(candidates)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        return self._isaac_rgbd_post_render_response("lerobot.isaac_rgbd.render.status", mode, profile_id, dataset_path, job)

    def _isaac_rgbd_post_render_dataset_path_for_stop_request(self, request: LeRobotSessionRequest) -> Path:
        if request.dataset_path or request.dataset_repo_id:
            return Path(self._dataset_path_for(request)).expanduser().resolve()
        requested_session = str(request.session_id or "")
        with self._isaac_rgbd_render_lock:
            jobs = list(self._isaac_rgbd_render_jobs.values())
        for active_only in (True, False):
            for job in reversed(jobs):
                if requested_session and str(job.get("session_id") or "") != requested_session:
                    continue
                status = str(job.get("status") or "").upper()
                if active_only and status not in {"RUNNING", "STOPPING"}:
                    continue
                dataset_path = str(job.get("dataset_path") or "").strip()
                if dataset_path:
                    return Path(dataset_path).expanduser().resolve()
        return Path(self._dataset_path_for(request)).expanduser().resolve()

    def isaac_rgbd_render_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Request a safe stop for post-record Isaac RGB-D rendering."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile_id = request.profile_id or self._selected_profile_id
        dataset_path = self._isaac_rgbd_post_render_dataset_path_for_stop_request(request)
        if not self._is_under_allowed_roots(dataset_path):
            return self._error(
                "lerobot.isaac_rgbd.render.stop",
                mode,
                profile_id,
                "LEROBOT_PATH_OUTSIDE_ALLOWED_ROOTS",
                f"Dataset path is outside allowed roots: {dataset_path}",
            )
        job_id = self._isaac_rgbd_post_render_job_id(dataset_path, request.session_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._isaac_rgbd_render_lock:
            job = dict(self._isaac_rgbd_render_jobs.get(job_id, {}))
            worker = self._isaac_rgbd_render_threads.get(job_id)
            worker_alive = bool(worker and worker.is_alive())
            if not job:
                episode_indices = self._isaac_rgbd_post_render_episode_filter(
                    getattr(request, "isaac_rgbd_post_render_episode_indices", "")
                )
                candidates = self._isaac_rgbd_post_render_candidates(
                    dataset_path,
                    request.session_id,
                    episode_indices=episode_indices,
                )
                job = self._new_isaac_rgbd_post_render_job(job_id, dataset_path, request.session_id, candidates)
                if episode_indices is not None:
                    job["episode_indices"] = sorted(episode_indices)
                done_index = self._isaac_rgbd_render_done_index(candidates)
                done = skipped = 0
                for candidate in candidates:
                    if self._isaac_rgbd_render_candidate_done(candidate, done_index=done_index):
                        done += 1
                        skipped += 1
                job.update(
                    {
                        "status": "STOPPED",
                        "stop_requested": True,
                        "done": done,
                        "skipped": skipped,
                        "pending": max(0, len(candidates) - done),
                        "percent": self._percent(done, len(candidates)),
                        "stopped_at": now,
                        "completed_at": now,
                    }
                )
            else:
                status = str(job.get("status") or "").upper()
                if status in {"RUNNING", "STOPPING"} and worker_alive:
                    job["status"] = "STOPPING"
                    job["stop_requested"] = True
                elif status in {"COMPLETED", "FAILED", "STOPPED"}:
                    job["stop_requested"] = True
                    if not job.get("stopped_at"):
                        job["stopped_at"] = now
                else:
                    job["status"] = "STOPPED"
                    job["stop_requested"] = True
                    job["pending"] = max(0, int(job.get("total") or 0) - int(job.get("done") or 0))
                    if not job.get("stopped_at"):
                        job["stopped_at"] = now
                    if not job.get("completed_at"):
                        job["completed_at"] = now
            job["updated_at"] = now
            self._isaac_rgbd_render_jobs[job_id] = job
            public_job = dict(job)
        return self._isaac_rgbd_post_render_response("lerobot.isaac_rgbd.render.stop", mode, profile_id, dataset_path, public_job)

    def _new_isaac_rgbd_post_render_job(
        self,
        job_id: str,
        dataset_path: Path,
        session_id: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        gap_filled = sum(1 for candidate in candidates if candidate.get("gap_filled"))
        return {
            "job_id": job_id,
            "status": "RUNNING" if candidates else "COMPLETED",
            "execution_mode": ISAAC_RGBD_POST_RENDER_EXECUTION_MODE,
            "preplay_policy": ISAAC_RGBD_POST_RENDER_PREPLAY_POLICY,
            "dataset_path": str(dataset_path),
            "session_id": session_id,
            "total": len(candidates),
            "gap_filled": gap_filled,
            "coverage_warning": f"{gap_filled} canonical frames were filled from nearest mirror samples." if gap_filled else "",
            "done": 0,
            "rendered": 0,
            "skipped": 0,
            "failed": 0,
            "pending": len(candidates),
            "percent": 100.0 if not candidates else 0.0,
            "started_at": now,
            "updated_at": now,
            "completed_at": now if not candidates else "",
            "stop_requested": False,
            "stopped_at": "",
            "last_frame_index": None,
            "last_error": "",
            "failed_frames": [],
        }

    @staticmethod
    def _isaac_rgbd_post_render_job_id(dataset_path: Path, session_id: str = "") -> str:
        clean_session = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "all").strip()).strip("._-") or "all"
        return f"{str(dataset_path)}::{clean_session}"

    def _isaac_rgbd_post_render_response(
        self,
        tool: str,
        mode: str,
        profile_id: str,
        dataset_path: Path,
        job: dict[str, Any],
        *,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        step_trace = [
            {"step": "RESOLVE_DATASET", "status": "ok", "detail": str(dataset_path)},
            {
                "step": "ISAAC_RGBD_POST_RENDER",
                "status": "active" if str(job.get("status") or "").upper() in {"RUNNING", "STOPPING"} else "ok",
                "detail": f"{job.get('done', 0)}/{job.get('total', 0)} frames ({job.get('percent', 0.0)}%)",
            },
        ]
        return {
            "ok": str(job.get("status") or "").upper() != "FAILED",
            "tool": tool,
            "mode": mode,
            "profile_id": profile_id,
            "status": job.get("status", "IDLE"),
            "dataset_path": str(dataset_path),
            "post_render": dict(job),
            "idempotent": idempotent,
            "step_trace": step_trace,
            "events": step_trace,
            "error": job.get("last_error") or None,
        }

    def _isaac_rgbd_post_render_stop_requested(self, job_id: str) -> bool:
        with self._isaac_rgbd_render_lock:
            return bool(self._isaac_rgbd_render_jobs.get(job_id, {}).get("stop_requested"))

    def _stop_isaac_rgbd_post_render_job(
        self,
        job_id: str,
        *,
        total: int,
        done: int,
        rendered: int,
        skipped: int,
        failed: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._update_isaac_rgbd_post_render_job(
            job_id,
            status="STOPPED",
            stop_requested=True,
            done=done,
            rendered=rendered,
            skipped=skipped,
            failed=failed,
            pending=max(0, total - done),
            percent=self._percent(done, total),
            stopped_at=now,
            completed_at=now,
        )

    def _run_isaac_rgbd_post_render_job(
        self,
        job_id: str,
        candidates: list[dict[str, Any]],
        *,
        post_timeout_s: float,
        poll_timeout_s: float,
    ) -> None:
        total = len(candidates)
        if self._isaac_rgbd_post_render_stop_requested(job_id):
            self._stop_isaac_rgbd_post_render_job(job_id, total=total, done=0, rendered=0, skipped=0, failed=0)
            return
        if total == 0:
            self._update_isaac_rgbd_post_render_job(job_id, status="COMPLETED", done=0, pending=0, percent=100.0, completed_at=datetime.now(timezone.utc).isoformat())
            return
        done = rendered = skipped = failed = 0
        failed_frames: list[dict[str, Any]] = []
        preplay_warnings = 0
        done_index = self._isaac_rgbd_render_done_index(candidates)
        preplayed_groups: set[tuple[str, int]] = set()
        overwrite_groups: dict[str, dict[str, Any]] = {}
        overwrite_committed: list[dict[str, Any]] = []
        overwrite_commit_failures: list[dict[str, Any]] = []
        for candidate in candidates:
            overwrite_key = self._isaac_rgbd_overwrite_group_key(candidate)
            if not overwrite_key:
                continue
            group = overwrite_groups.setdefault(overwrite_key, {"total": 0, "done": 0, "failed": 0, "candidates": []})
            group["total"] += 1
            group["candidates"].append(candidate)
        for candidate in candidates:
            if self._isaac_rgbd_post_render_stop_requested(job_id):
                self._stop_isaac_rgbd_post_render_job(
                    job_id,
                    total=total,
                    done=done,
                    rendered=rendered,
                    skipped=skipped,
                    failed=failed,
                )
                return
            frame_index = candidate.get("frame_index")
            if self._isaac_rgbd_render_candidate_done(candidate, done_index=done_index):
                skipped += 1
                done += 1
                self._update_isaac_rgbd_post_render_job(
                    job_id,
                    done=done,
                    skipped=skipped,
                    pending=max(0, total - done),
                    percent=self._percent(done, total),
                    last_frame_index=frame_index,
                )
                continue
            endpoint = str(candidate.get("endpoint") or "http://127.0.0.1:8766/render")
            group_key = (
                str(candidate.get("attempt_id") or (candidate.get("request") or {}).get("attempt_id") or ""),
                _safe_int(candidate.get("episode_index"), 0, minimum=0),
            )
            if group_key not in preplayed_groups:
                preplay = self._preplay_isaac_rgbd_first_frame(
                    candidate,
                    endpoint=endpoint,
                    post_timeout_s=post_timeout_s,
                    settle_timeout_s=max(2.0, min(8.0, poll_timeout_s)),
                )
                preplayed_groups.add(group_key)
                self._update_isaac_rgbd_post_render_job(
                    job_id,
                    preplay_count=len(preplayed_groups),
                    last_preplay=preplay,
                )
                if not preplay.get("ok"):
                    preplay_warnings += 1
                    self._update_isaac_rgbd_post_render_job(
                        job_id,
                        preplay_warning_count=preplay_warnings,
                        last_preplay_warning=preplay,
                        last_frame_index=frame_index,
                        last_preplay_warning_message=str(
                            preplay.get("message") or preplay.get("status") or "Isaac RGB-D preplay did not stabilize"
                        ),
                    )
            post_result = self._post_isaac_rgbd_render_payload(dict(candidate.get("payload") or {}), endpoint=endpoint, timeout_s=post_timeout_s)
            wait_result = (
                self._wait_for_isaac_rgbd_render_completion(candidate, endpoint=endpoint, timeout_s=poll_timeout_s)
                if post_result.get("ok")
                else {"ok": False, "status": "post_failed", "message": post_result.get("error") or post_result.get("response")}
            )
            if post_result.get("ok") and wait_result.get("ok"):
                rendered += 1
            else:
                failed += 1
                failure_message = str(wait_result.get("message") or post_result.get("error") or wait_result.get("status") or "")
                failed_frames.append(
                    {
                        "attempt_id": str(candidate.get("attempt_id") or ""),
                        "episode_index": _safe_int(candidate.get("episode_index"), 0, minimum=0),
                        "frame_index": _safe_int(candidate.get("frame_index"), 0, minimum=0),
                        "sample_index": _safe_int(candidate.get("sample_index"), 0, minimum=0),
                        "message": failure_message,
                        "status": str(wait_result.get("status") or post_result.get("status") or "failed"),
                    }
                )
            candidate_success = bool(post_result.get("ok") and wait_result.get("ok"))
            last_error = "" if candidate_success else str(wait_result.get("message") or post_result.get("error") or wait_result.get("status") or "")
            overwrite_key = self._isaac_rgbd_overwrite_group_key(candidate)
            if overwrite_key:
                group = overwrite_groups[overwrite_key]
                group["done"] += 1
                if not candidate_success:
                    group["failed"] += 1
                if group["done"] >= group["total"]:
                    if group["failed"] == 0:
                        commit_result = self._commit_isaac_rgbd_overwrite_group(list(group["candidates"]))
                        if commit_result.get("ok"):
                            overwrite_committed.append(commit_result)
                        else:
                            overwrite_commit_failures.append(commit_result)
                            failed += 1
                            last_error = str(commit_result.get("message") or commit_result.get("status") or "overwrite_commit_failed")
                    else:
                        overwrite_commit_failures.append(
                            {
                                "ok": False,
                                "status": "overwrite_group_failed_before_commit",
                                "final_output_dir": overwrite_key,
                                "failed_frame_count": group["failed"],
                            }
                        )
            done += 1
            progress_updates = {
                "done": done,
                "rendered": rendered,
                "skipped": skipped,
                "failed": failed,
                "pending": max(0, total - done),
                "percent": self._percent(done, total),
                "last_frame_index": frame_index,
                "last_error": last_error,
                "failed_frames": failed_frames[-50:],
            }
            if overwrite_groups:
                progress_updates["overwrite_summary"] = self._isaac_rgbd_overwrite_summary(
                    candidates,
                    overwrite_committed,
                    overwrite_commit_failures,
                )
            self._update_isaac_rgbd_post_render_job(job_id, **progress_updates)
            if self._isaac_rgbd_post_render_stop_requested(job_id):
                self._stop_isaac_rgbd_post_render_job(
                    job_id,
                    total=total,
                    done=done,
                    rendered=rendered,
                    skipped=skipped,
                    failed=failed,
                )
                return
        final_status = "COMPLETED" if failed == 0 else "FAILED"
        self._update_isaac_rgbd_post_render_job(
            job_id,
            status=final_status,
            done=done,
            rendered=rendered,
            skipped=skipped,
            failed=failed,
            pending=0,
            percent=100.0,
            failed_frames=failed_frames[-50:],
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _update_isaac_rgbd_post_render_job(self, job_id: str, **updates: Any) -> None:
        with self._isaac_rgbd_render_lock:
            job = self._isaac_rgbd_render_jobs.setdefault(job_id, {"job_id": job_id})
            job.update(updates)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _preplay_isaac_rgbd_first_frame(
        self,
        candidate: dict[str, Any],
        *,
        endpoint: str,
        post_timeout_s: float,
        settle_timeout_s: float,
    ) -> dict[str, Any]:
        payload = copy.deepcopy(candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {})
        if not payload:
            return {"ok": False, "status": "empty_preplay_payload", "message": "Isaac RGB-D preplay payload is empty."}
        payload.pop("render_request", None)
        payload["isaac_rgbd_preplay"] = {
            "reason": "first_frame_settle_before_render",
            "attempt_id": str(candidate.get("attempt_id") or ""),
            "episode_index": _safe_int(candidate.get("episode_index"), 0, minimum=0),
            "frame_index": _safe_int(candidate.get("frame_index"), 0, minimum=0),
        }
        stop = self._post_isaac_mirror_timeline_stop(
            endpoint,
            reason="isaac_rgbd_post_render_preplay_stop",
            timeout_s=post_timeout_s,
        )
        if not stop.get("ok"):
            return {
                "ok": False,
                "status": "timeline_stop_failed",
                "timeline_stop": stop,
                "message": str(stop.get("message") or stop.get("status") or "Isaac timeline stop failed."),
            }
        specimen_pose = payload.get("specimen_pose") if isinstance(payload.get("specimen_pose"), dict) else {}
        specimen_result: dict[str, Any] = {}
        if specimen_pose:
            specimen_result = self._post_isaac_mirror_specimen_pose(
                endpoint,
                dict(specimen_pose),
                timeout_s=post_timeout_s,
            )
            if not specimen_result.get("ok"):
                return {
                    "ok": False,
                    "status": "specimen_pose_failed",
                    "timeline_stop": stop,
                    "specimen_pose": specimen_result,
                    "message": str(
                        specimen_result.get("message")
                        or specimen_result.get("status")
                        or "Recorded specimen pose was not accepted by Isaac."
                    ),
                }
        timeline = self._post_isaac_mirror_timeline_play(
            endpoint,
            reason="isaac_rgbd_post_render_preplay",
            timeout_s=post_timeout_s,
        )
        if not timeline.get("ok"):
            return {
                "ok": False,
                "status": "timeline_play_failed",
                "timeline": timeline,
                "message": str(timeline.get("message") or timeline.get("status") or "Isaac timeline play failed."),
            }
        joint_endpoint = self._isaac_mirror_joint_url(endpoint)
        settle = self._wait_for_isaac_rgbd_joint_settle(
            joint_endpoint,
            payload,
            timeout_s=settle_timeout_s,
            tolerance_deg=5.0,
            velocity_tolerance_deg_s=10.0,
        )
        return {
            "ok": bool(settle.get("ok")),
            "status": "preplay_stable" if settle.get("ok") else "preplay_unstable",
            "timeline_stop": stop,
            "specimen_pose": specimen_result,
            "timeline": timeline,
            "joint_endpoint": joint_endpoint,
            "settle": settle,
            "message": "" if settle.get("ok") else str(settle.get("message") or settle.get("status") or "Isaac preplay did not stabilize."),
        }

    def _wait_for_isaac_rgbd_joint_settle(
        self,
        endpoint: str,
        payload: dict[str, object],
        *,
        timeout_s: float,
        tolerance_deg: float,
        velocity_tolerance_deg_s: float,
    ) -> dict[str, object]:
        deadline = time.monotonic() + max(0.1, timeout_s)
        last_summary: dict[str, object] = {"ok": False, "status": "not_checked"}
        attempts = 0
        while time.monotonic() <= deadline:
            attempts += 1
            post = self._post_isaac_mirror_state(endpoint, dict(payload), timeout_s=0.5)
            if not post.get("ok"):
                return {
                    "ok": False,
                    "status": "joint_post_failed",
                    "attempts": attempts,
                    "post": post,
                    "message": str(post.get("message") or post.get("error") or post.get("status") or "failed to post joint preplay payload"),
                }
            time.sleep(0.2)
            state = self._fetch_isaac_mirror_receiver_state(endpoint, timeout_s=0.5)
            last_summary = self._isaac_rgbd_joint_settle_summary(
                state,
                tolerance_deg=tolerance_deg,
                velocity_tolerance_deg_s=velocity_tolerance_deg_s,
            )
            last_summary["attempts"] = attempts
            if last_summary.get("ok"):
                return last_summary
            time.sleep(0.3)
        return {
            **last_summary,
            "ok": False,
            "status": "settle_timeout",
            "attempts": attempts,
            "message": (
                f"Timed out waiting for Isaac joint readback to settle within {tolerance_deg:g} deg "
                f"and {velocity_tolerance_deg_s:g} deg/s."
            ),
        }

    @staticmethod
    def _isaac_rgbd_joint_settle_summary(
        state: dict[str, Any],
        *,
        tolerance_deg: float,
        velocity_tolerance_deg_s: float,
    ) -> dict[str, object]:
        last_apply = state.get("last_apply_result") if isinstance(state.get("last_apply_result"), dict) else {}
        rows = last_apply.get("joint_readback") if isinstance(last_apply, dict) else []
        comparable: list[dict[str, object]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if row.get("state_position") is None or row.get("target_value") is None:
                continue
            error = row.get("target_minus_state")
            if error is None:
                error = _safe_float(row.get("target_value"), 0.0) - _safe_float(row.get("state_position"), 0.0)
            velocity = _safe_float(row.get("state_velocity"), 0.0)
            comparable.append(
                {
                    "motor_id": row.get("motor_id"),
                    "name": str(row.get("name") or ""),
                    "target_value": _safe_float(row.get("target_value"), 0.0),
                    "state_position": _safe_float(row.get("state_position"), 0.0),
                    "target_minus_state": _safe_float(error, 0.0),
                    "state_velocity": velocity,
                    "abs_error_deg": abs(_safe_float(error, 0.0)),
                    "abs_velocity_deg_s": abs(velocity),
                }
            )
        if not comparable:
            return {
                "ok": False,
                "status": "joint_readback_unavailable",
                "sample_count": state.get("sample_count"),
                "comparable_count": 0,
                "message": "Isaac receiver state did not include comparable joint_readback rows.",
            }
        max_error = max(_safe_float(row.get("abs_error_deg"), 0.0) for row in comparable)
        max_velocity = max(_safe_float(row.get("abs_velocity_deg_s"), 0.0) for row in comparable)
        stable = max_error <= tolerance_deg and max_velocity <= velocity_tolerance_deg_s
        return {
            "ok": stable,
            "status": "stable" if stable else "settling",
            "sample_count": state.get("sample_count"),
            "comparable_count": len(comparable),
            "max_abs_error_deg": max_error,
            "max_abs_velocity_deg_s": max_velocity,
            "tolerance_deg": tolerance_deg,
            "velocity_tolerance_deg_s": velocity_tolerance_deg_s,
            "joints": comparable[:12],
        }

    @staticmethod
    def _isaac_rgbd_expected_episode_lengths(dataset_path: Path) -> dict[int, int]:
        lengths: dict[int, int] = {}
        episodes_path = dataset_path / "meta" / "episodes.jsonl"
        for index, row in enumerate(LeRobotBridge._read_jsonl_rows(episodes_path)):
            episode_index = _safe_int(row.get("episode_index"), index, minimum=0)
            length = _safe_int(row.get("length", row.get("num_frames", row.get("frame_count"))), 0, minimum=0)
            if length > 0:
                lengths[episode_index] = length
        if lengths:
            return lengths
        info_path = dataset_path / "meta" / "info.json"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(info, dict):
            return {}
        episode_count = _safe_int(info.get("total_episodes"), 0, minimum=0)
        frame_count = _safe_int(info.get("total_frames"), 0, minimum=0)
        if episode_count <= 0 or frame_count <= 0:
            return {}
        base = frame_count // episode_count
        remainder = frame_count % episode_count
        return {episode_index: base + (1 if episode_index < remainder else 0) for episode_index in range(episode_count)}

    @staticmethod
    def _isaac_rgbd_nearest_source_candidate(candidates: list[dict[str, Any]], frame_index: int) -> dict[str, Any]:
        previous = [
            candidate
            for candidate in candidates
            if _safe_int(candidate.get("frame_index"), 0, minimum=0) <= frame_index
        ]
        if previous:
            return max(previous, key=lambda candidate: _safe_int(candidate.get("frame_index"), 0, minimum=0))
        return min(candidates, key=lambda candidate: _safe_int(candidate.get("frame_index"), 0, minimum=0))

    @staticmethod
    def _isaac_rgbd_gap_fill_candidate(source: dict[str, Any], frame_index: int) -> dict[str, Any]:
        candidate = copy.deepcopy(source)
        request = copy.deepcopy(source.get("request") if isinstance(source.get("request"), dict) else {})
        payload = copy.deepcopy(source.get("payload") if isinstance(source.get("payload"), dict) else {})
        source_frame_index = _safe_int(source.get("frame_index"), frame_index, minimum=0)
        source_sample_index = _safe_int(source.get("sample_index"), _safe_int(request.get("sample_index"), frame_index + 1, minimum=1), minimum=1)
        sample_index = max(1, source_sample_index + (frame_index - source_frame_index))
        request["frame_index"] = frame_index
        request["sample_index"] = sample_index
        payload["sample_index"] = sample_index
        payload["render_request"] = dict(request)
        payload["isaac_rgbd_gap_fill"] = {
            "reason": "canonical_frame_missing_from_mirror",
            "source_frame_index": source_frame_index,
            "source_sample_index": source_sample_index,
            "filled_frame_index": frame_index,
            "filled_sample_index": sample_index,
        }
        candidate.update(
            {
                "key": (str(source.get("attempt_id") or ""), _safe_int(source.get("episode_index"), 0, minimum=0), frame_index),
                "frame_index": frame_index,
                "sample_index": sample_index,
                "request": request,
                "payload": payload,
                "gap_filled": True,
                "gap_fill_source_frame_index": source_frame_index,
                "gap_fill_source_sample_index": source_sample_index,
            }
        )
        return candidate

    def _fill_missing_isaac_rgbd_post_render_candidates(
        self,
        dataset_path: Path,
        candidates_by_key: dict[tuple[str, int, int], dict[str, Any]],
    ) -> None:
        expected_lengths = self._isaac_rgbd_expected_episode_lengths(dataset_path)
        if not expected_lengths or not candidates_by_key:
            return
        groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for (attempt_id, episode_index, _frame_index), candidate in candidates_by_key.items():
            groups.setdefault((attempt_id, episode_index), []).append(candidate)
        for (attempt_id, episode_index), candidates in groups.items():
            expected_length = expected_lengths.get(episode_index)
            if not expected_length:
                continue
            frame_indices = {_safe_int(candidate.get("frame_index"), 0, minimum=0) for candidate in candidates}
            for frame_index in range(expected_length):
                if frame_index in frame_indices:
                    continue
                source = self._isaac_rgbd_nearest_source_candidate(candidates, frame_index)
                filled = self._isaac_rgbd_gap_fill_candidate(source, frame_index)
                key = (attempt_id, episode_index, frame_index)
                if key not in candidates_by_key:
                    candidates_by_key[key] = filled
                    candidates.append(filled)
                    frame_indices.add(frame_index)

    @staticmethod
    def _isaac_rgbd_episode_action_joint_states(
        dataset_path: Path,
        episode_index: int,
        *,
        calibration: dict[str, Any] | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        data_root = dataset_path / "data"
        episode_name = f"episode_{episode_index:06d}.parquet"
        episode_paths = [data_root / "chunk-000" / episode_name]
        episode_paths.extend(sorted(data_root.glob(f"chunk-*/{episode_name}")))
        episode_path = next((path for path in episode_paths if path.is_file()), None)
        if episode_path is None:
            return {}
        try:
            import pyarrow.parquet as pq
        except Exception:
            return {}
        try:
            table = pq.read_table(episode_path, columns=["action", "frame_index"])
        except Exception:
            try:
                table = pq.read_table(episode_path, columns=["action"])
            except Exception:
                return {}
        data = table.to_pydict()
        actions = data.get("action") or []
        frame_indices = data.get("frame_index")
        joint_states: dict[int, list[dict[str, Any]]] = {}
        for row_index, raw_action in enumerate(actions):
            if not isinstance(raw_action, (list, tuple)):
                continue
            frame_index = row_index
            if isinstance(frame_indices, list) and row_index < len(frame_indices):
                frame_index = _safe_int(frame_indices[row_index], row_index, minimum=0)
            action: dict[str, Any] = {}
            for joint_index, item in enumerate(ISAAC_OMX_JOINT_MAP):
                if joint_index >= len(raw_action):
                    break
                action[f"{item['motor_name']}.pos"] = raw_action[joint_index]
            converted = action_to_joint_state(action, calibration=calibration)
            if converted:
                joint_states[frame_index] = converted
        return joint_states

    def _attach_lerobot_action_pose_to_isaac_rgbd_candidates(
        self,
        dataset_path: Path,
        candidates_by_key: dict[tuple[str, int, int], dict[str, Any]],
    ) -> None:
        default_calibration = self._isaac_mirror_calibration()
        cache: dict[tuple[int, str], dict[int, list[dict[str, Any]]]] = {}
        for (_attempt_id, episode_index, frame_index), candidate in candidates_by_key.items():
            payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
            if not isinstance(payload, dict):
                continue
            calibration = payload.get("calibration") if isinstance(payload.get("calibration"), dict) else default_calibration
            try:
                calibration_key = json.dumps(calibration or {}, sort_keys=True, default=str)
            except TypeError:
                calibration_key = ""
            cache_key = (episode_index, calibration_key)
            if cache_key not in cache:
                cache[cache_key] = self._isaac_rgbd_episode_action_joint_states(
                    dataset_path,
                    episode_index,
                    calibration=calibration if isinstance(calibration, dict) else None,
                )
            joint_state = cache[cache_key].get(frame_index)
            if not joint_state:
                continue
            payload["joint_state"] = [dict(item) for item in joint_state]
            payload["isaac_rgbd_pose_source"] = "lerobot_episode_action"
            payload["isaac_rgbd_pose_frame_index"] = frame_index

    @staticmethod
    def _isaac_rgbd_post_render_episode_filter(raw_value: Any) -> set[int] | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple, set)):
            values = raw_value
        else:
            raw = str(raw_value or "").strip()
            if not raw or raw.lower() in {"all", "*"}:
                return None
            values = re.split(r"[\s,]+", raw)
        selected: set[int] = set()
        for item in values:
            token = str(item).strip()
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                start = _safe_int(left, -1)
                end = _safe_int(right, -1)
                if start >= 0 and end >= start:
                    selected.update(range(start, end + 1))
                continue
            index = _safe_int(token, -1)
            if index >= 0:
                selected.add(index)
        return selected if selected else None

    @staticmethod
    def _isaac_rgbd_specimen_pose_for_attempt(dataset_path: Path, *, episode_index: int, attempt_id: str) -> dict[str, Any]:
        attempts_root = (dataset_path / "sidecar" / "attempts").expanduser()
        pose_path = attempts_root / f"episode_{episode_index:03d}" / attempt_id / "specimen_pose.json"
        try:
            resolved = pose_path.resolve()
            resolved.relative_to(attempts_root.resolve())
        except (OSError, ValueError):
            return {}
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(loaded, dict):
            return {}
        enriched = copy.deepcopy(loaded)
        enriched["source_path"] = str(resolved)
        enriched.setdefault("source", "record_attempt_specimen_pose")
        return enriched

    def _stage_isaac_rgbd_overwrite_candidates(self, dataset_path: Path, candidates: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
        render_root = (dataset_path / "sidecar" / "isaac_rgbd").expanduser()
        try:
            resolved_root = render_root.resolve()
        except OSError:
            return {"mode": "staged_commit", "planned": [], "denied": [], "failure_code": "ISAAC_RGBD_RENDER_ROOT_UNRESOLVABLE"}
        staging_root = render_root / ".overwrite_staging" / uuid.uuid5(uuid.NAMESPACE_URL, job_id).hex
        if staging_root.exists():
            shutil.rmtree(staging_root)
        planned: dict[str, dict[str, str]] = {}
        denied: list[str] = []
        for candidate in candidates:
            output_dir = Path(str(candidate.get("output_dir") or "")).expanduser()
            if not str(output_dir):
                continue
            try:
                resolved = output_dir.resolve()
                resolved.relative_to(resolved_root)
            except (OSError, ValueError):
                denied.append(str(output_dir))
                continue
            episode_index = _safe_int(candidate.get("episode_index"), 0, minimum=0)
            attempt_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(candidate.get("attempt_id") or "attempt").strip()).strip("._-") or "attempt"
            staging_dir = staging_root / f"episode_{episode_index:03d}" / attempt_id
            final_output_dir = str(output_dir)
            staging_output_dir = str(staging_dir)
            candidate["overwrite_output_dir"] = final_output_dir
            candidate["overwrite_staging_dir"] = staging_output_dir
            candidate["output_dir"] = staging_output_dir
            candidate["manifest_path"] = str(staging_dir / "manifest.jsonl")
            request = candidate.get("request") if isinstance(candidate.get("request"), dict) else {}
            request["output_dir"] = staging_output_dir
            candidate["request"] = request
            payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
            render_request = payload.get("render_request") if isinstance(payload.get("render_request"), dict) else {}
            render_request["output_dir"] = staging_output_dir
            payload["render_request"] = render_request
            candidate["payload"] = payload
            planned.setdefault(
                final_output_dir,
                {
                    "final_output_dir": final_output_dir,
                    "staging_output_dir": staging_output_dir,
                    "episode_index": str(episode_index),
                    "attempt_id": attempt_id,
                },
            )
        return {
            "mode": "staged_commit",
            "staging_root": str(staging_root),
            "planned": list(planned.values()),
            "planned_count": len(planned),
            "denied": denied,
            "denied_count": len(denied),
            "committed": [],
            "committed_count": 0,
            "commit_failures": [],
            "commit_failure_count": 0,
        }

    @staticmethod
    def _isaac_rgbd_overwrite_group_key(candidate: dict[str, Any]) -> str:
        return str(candidate.get("overwrite_output_dir") or "")

    @staticmethod
    def _rewrite_isaac_rgbd_overwrite_manifest_paths(manifest_path: Path, staging_dir: Path, final_dir: Path) -> None:
        if not manifest_path.is_file():
            return
        staging_text = str(staging_dir)
        final_text = str(final_dir)
        text = manifest_path.read_text(encoding="utf-8")
        if staging_text in text:
            manifest_path.write_text(text.replace(staging_text, final_text), encoding="utf-8")

    @staticmethod
    def _cleanup_empty_isaac_rgbd_overwrite_staging_dirs(staging_dir: Path) -> None:
        parent = staging_dir.parent
        while parent.name and parent.name != "isaac_rgbd":
            try:
                parent.rmdir()
            except OSError:
                return
            parent = parent.parent

    def _commit_isaac_rgbd_overwrite_group(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {"ok": False, "status": "empty_overwrite_group"}
        final_dir = Path(str(candidates[0].get("overwrite_output_dir") or "")).expanduser()
        staging_dir = Path(str(candidates[0].get("overwrite_staging_dir") or "")).expanduser()
        if len(final_dir.parents) < 2:
            return {"ok": False, "status": "overwrite_final_path_invalid", "final_output_dir": str(final_dir), "staging_output_dir": str(staging_dir)}
        render_root = final_dir.parents[1].expanduser().resolve()
        try:
            final_resolved = final_dir.resolve()
            staging_resolved = staging_dir.resolve()
            final_resolved.relative_to(render_root)
            staging_resolved.relative_to(render_root)
        except (OSError, ValueError) as exc:
            return {"ok": False, "status": "overwrite_path_denied", "message": str(exc), "final_output_dir": str(final_dir), "staging_output_dir": str(staging_dir)}
        if not staging_dir.is_dir():
            return {"ok": False, "status": "overwrite_staging_missing", "final_output_dir": str(final_dir), "staging_output_dir": str(staging_dir)}
        for candidate in candidates:
            if not self._isaac_rgbd_render_candidate_done(candidate):
                return {
                    "ok": False,
                    "status": "overwrite_staging_incomplete",
                    "final_output_dir": str(final_dir),
                    "staging_output_dir": str(staging_dir),
                    "frame_index": _safe_int(candidate.get("frame_index"), 0, minimum=0),
                }
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.is_dir():
            shutil.rmtree(final_dir)
        elif final_dir.exists():
            final_dir.unlink()
        shutil.move(str(staging_dir), str(final_dir))
        self._rewrite_isaac_rgbd_overwrite_manifest_paths(final_dir / "manifest.jsonl", staging_dir, final_dir)
        self._cleanup_empty_isaac_rgbd_overwrite_staging_dirs(staging_dir)
        return {
            "ok": True,
            "status": "committed",
            "final_output_dir": str(final_dir),
            "staging_output_dir": str(staging_dir),
            "frame_count": len(candidates),
        }

    @staticmethod
    def _isaac_rgbd_overwrite_summary(
        candidates: list[dict[str, Any]],
        committed: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        planned = {
            str(candidate.get("overwrite_output_dir") or "")
            for candidate in candidates
            if candidate.get("overwrite_output_dir")
        }
        return {
            "mode": "staged_commit",
            "planned_count": len(planned),
            "committed": committed[-50:],
            "committed_count": len(committed),
            "commit_failures": failures[-50:],
            "commit_failure_count": len(failures),
        }

    def _isaac_rgbd_post_render_candidates(
        self,
        dataset_path: Path,
        session_id: str = "",
        *,
        episode_indices: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        mirror_paths = self._isaac_rgbd_post_render_mirror_paths(dataset_path, session_id)
        candidates_by_key: dict[tuple[str, int, int], dict[str, Any]] = {}
        for mirror_path in mirror_paths:
            for row in self._read_jsonl_rows(mirror_path):
                render_queue = row.get("render_queue") if isinstance(row.get("render_queue"), dict) else {}
                if not isinstance(render_queue, dict):
                    continue
                request = render_queue.get("render_request") if isinstance(render_queue.get("render_request"), dict) else {}
                if not isinstance(request, dict) or not request.get("enabled"):
                    continue
                status = str(render_queue.get("status") or "").lower()
                if status and status not in {"deferred_after_record", "queued", "queued_replaced_stale", "queue_full"}:
                    continue
                attempt_id = str(request.get("attempt_id") or render_queue.get("attempt_id") or "").strip()
                episode_index = _safe_int(request.get("episode_index"), _safe_int(render_queue.get("episode_index"), 0, minimum=0), minimum=0)
                frame_index = _safe_int(request.get("frame_index"), _safe_int(render_queue.get("frame_index"), 0, minimum=0), minimum=0)
                if episode_indices is not None and episode_index not in episode_indices:
                    continue
                if not attempt_id:
                    continue
                output_dir = Path(str(request.get("output_dir") or "")).expanduser()
                if not str(output_dir):
                    continue
                endpoint = str(render_queue.get("endpoint") or "").strip() or "http://127.0.0.1:8766/render"
                payload = {
                    key: value
                    for key, value in row.items()
                    if key not in {"render_queue", "isaac_post", "sync_metrics"}
                }
                payload["joint_state"] = [dict(item) for item in row.get("joint_state", []) if isinstance(item, dict)]
                payload["render_request"] = dict(request)
                key = (attempt_id, episode_index, frame_index)
                candidates_by_key[key] = {
                    "key": key,
                    "attempt_id": attempt_id,
                    "episode_index": episode_index,
                    "frame_index": frame_index,
                    "sample_index": request.get("sample_index", row.get("sample_index")),
                    "endpoint": endpoint,
                    "output_dir": str(output_dir),
                    "manifest_path": str(output_dir / "manifest.jsonl"),
                    "request": dict(request),
                    "payload": payload,
                    "mirror_record_path": str(mirror_path),
                    "gap_filled": False,
                }
        self._fill_missing_isaac_rgbd_post_render_candidates(dataset_path, candidates_by_key)
        self._attach_lerobot_action_pose_to_isaac_rgbd_candidates(dataset_path, candidates_by_key)
        self._attach_initial_specimen_pose_to_isaac_rgbd_candidates(dataset_path, candidates_by_key)
        return [
            candidates_by_key[key]
            for key in sorted(candidates_by_key, key=lambda item: (item[1], item[2], item[0]))
        ]

    def _attach_initial_specimen_pose_to_isaac_rgbd_candidates(
        self,
        dataset_path: Path,
        candidates_by_key: dict[tuple[str, int, int], dict[str, Any]],
    ) -> None:
        groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for (attempt_id, episode_index, _frame_index), candidate in candidates_by_key.items():
            payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
            if isinstance(payload, dict):
                payload.pop("specimen_pose", None)
                payload.pop("isaac_rgbd_episode_initial_state", None)
            groups.setdefault((attempt_id, episode_index), []).append(candidate)
        for (attempt_id, episode_index), candidates in groups.items():
            if not candidates:
                continue
            first = min(candidates, key=lambda item: _safe_int(item.get("frame_index"), 0, minimum=0))
            payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
            specimen_pose = self._isaac_rgbd_specimen_pose_for_attempt(
                dataset_path,
                episode_index=episode_index,
                attempt_id=attempt_id,
            )
            if not specimen_pose:
                continue
            if isinstance(payload, dict):
                payload["specimen_pose"] = specimen_pose

    @staticmethod
    def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
        except OSError:
            return []
        return rows

    @staticmethod
    def _isaac_rgbd_post_render_mirror_paths(dataset_path: Path, session_id: str = "") -> list[Path]:
        mirror_root = dataset_path / "sidecar" / "isaac_mirror"
        if session_id:
            direct = mirror_root / f"{session_id}.jsonl"
            return [direct] if direct.is_file() else []
        return sorted(mirror_root.glob("*.jsonl"))

    @staticmethod
    def _isaac_rgbd_render_candidate_done_key(candidate: dict[str, Any]) -> tuple[str, str, int, int, tuple[str, ...]]:
        manifest_path = str(Path(str(candidate.get("manifest_path") or "")).expanduser())
        request = candidate.get("request") if isinstance(candidate.get("request"), dict) else {}
        cameras = tuple(sorted({str(item).strip() for item in request.get("cameras", []) if str(item).strip()})) if isinstance(request.get("cameras"), list) else ()
        return (
            manifest_path,
            str(candidate.get("attempt_id") or ""),
            _safe_int(candidate.get("episode_index"), 0, minimum=0),
            _safe_int(candidate.get("frame_index"), 0, minimum=0),
            cameras,
        )

    @staticmethod
    def _isaac_rgbd_render_manifest_row_key(row: dict[str, Any]) -> tuple[str, int, int]:
        return (
            str(row.get("attempt_id") or ""),
            _safe_int(row.get("episode_index"), 0, minimum=0),
            _safe_int(row.get("frame_index"), 0, minimum=0),
        )

    def _isaac_rgbd_render_done_index(self, candidates: list[dict[str, Any]]) -> set[tuple[str, str, int, int, tuple[str, ...]]]:
        candidates_by_manifest: dict[Path, dict[tuple[str, int, int], list[dict[str, Any]]]] = {}
        for candidate in candidates:
            manifest_path = Path(str(candidate.get("manifest_path") or "")).expanduser()
            if not manifest_path.is_file():
                continue
            row_key = (
                str(candidate.get("attempt_id") or ""),
                _safe_int(candidate.get("episode_index"), 0, minimum=0),
                _safe_int(candidate.get("frame_index"), 0, minimum=0),
            )
            candidates_by_manifest.setdefault(manifest_path, {}).setdefault(row_key, []).append(candidate)
        done: set[tuple[str, str, int, int, tuple[str, ...]]] = set()
        for manifest_path, candidates_by_row_key in candidates_by_manifest.items():
            for row in reversed(self._read_jsonl_rows(manifest_path)):
                if str(row.get("status") or "").lower() != "rendered":
                    continue
                matching_candidates = candidates_by_row_key.get(self._isaac_rgbd_render_manifest_row_key(row), [])
                for candidate in matching_candidates:
                    if self._isaac_rgbd_manifest_files_exist(row, manifest_path=manifest_path, request=dict(candidate.get("request") or {})):
                        done.add(self._isaac_rgbd_render_candidate_done_key(candidate))
        return done

    def _isaac_rgbd_render_candidate_done(
        self,
        candidate: dict[str, Any],
        *,
        done_index: set[tuple[str, str, int, int, tuple[str, ...]]] | None = None,
    ) -> bool:
        if done_index is not None:
            return self._isaac_rgbd_render_candidate_done_key(candidate) in done_index
        manifest_path = Path(str(candidate.get("manifest_path") or "")).expanduser()
        if not manifest_path.is_file():
            return False
        attempt_id = str(candidate.get("attempt_id") or "")
        episode_index = _safe_int(candidate.get("episode_index"), 0, minimum=0)
        frame_index = _safe_int(candidate.get("frame_index"), 0, minimum=0)
        for row in reversed(self._read_jsonl_rows(manifest_path)):
            if str(row.get("attempt_id") or "") != attempt_id:
                continue
            if _safe_int(row.get("episode_index"), 0, minimum=0) != episode_index:
                continue
            if _safe_int(row.get("frame_index"), 0, minimum=0) != frame_index:
                continue
            if str(row.get("status") or "").lower() != "rendered":
                continue
            if self._isaac_rgbd_manifest_files_exist(row, manifest_path=manifest_path, request=dict(candidate.get("request") or {})):
                return True
        return False

    @staticmethod
    def _isaac_rgbd_manifest_files_exist(row: dict[str, Any], *, manifest_path: Path, request: dict[str, Any]) -> bool:
        files = row.get("files")
        if not isinstance(files, list) or not files:
            return False
        requested_cameras = {str(item).strip() for item in request.get("cameras", []) if str(item).strip()} if isinstance(request.get("cameras"), list) else set()
        seen_cameras: set[str] = set()
        for file_info in files:
            if not isinstance(file_info, dict):
                return False
            raw_path = str(file_info.get("path") or "").strip()
            if not raw_path:
                return False
            path = Path(raw_path)
            if not path.is_absolute():
                path = manifest_path.parent / path
            if not path.is_file():
                return False
            camera = str(file_info.get("camera") or "").strip()
            if camera:
                seen_cameras.add(camera)
        return requested_cameras.issubset(seen_cameras) if requested_cameras else True

    def _post_isaac_rgbd_render_payload(self, payload: dict[str, object], *, endpoint: str, timeout_s: float) -> dict[str, object]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {"ok": 200 <= response.status < 300, "status_code": response.status, "response": parsed}
        except Exception as exc:
            return {"ok": False, "status_code": None, "error": f"{exc.__class__.__name__}: {exc}"}

    def _wait_for_isaac_rgbd_render_completion(self, candidate: dict[str, Any], *, endpoint: str, timeout_s: float) -> dict[str, object]:
        deadline = time.monotonic() + max(0.1, timeout_s)
        while time.monotonic() <= deadline:
            if self._isaac_rgbd_render_candidate_done(candidate):
                return {"ok": True, "status": "rendered"}
            time.sleep(0.1)
        return {
            "ok": False,
            "status": "timeout",
            "message": f"Timed out waiting for Isaac RGB-D render frame={candidate.get('frame_index')} endpoint={endpoint}",
        }

    @staticmethod
    def _percent(done: int, total: int) -> float:
        if total <= 0:
            return 100.0
        return round(min(100.0, max(0.0, (float(done) / float(total)) * 100.0)), 1)

    def visualization_file_path(self, path_value: str) -> Path:
        """Resolve and validate a local media path for dataset visualization."""
        path = _resolve_path(self.config.repo_root, path_value).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"LeRobot visualization file not found: {path}")
        if not self._is_under_allowed_roots(path):
            raise PermissionError(f"LeRobot visualization file outside allowed roots: {path}")
        return path

    def policy_download(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a blocked/dry-run policy download preview."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        profile_id = profile.profile_id if profile else request.profile_id or self._selected_profile_id
        if mode == "live":
            return self._error("lerobot.policy.download", mode, profile_id, "LEROBOT_POLICY_DOWNLOAD_BLOCKED", "Policy download is blocked until explicit token/config gates are implemented.")
        policy_ref = request.policy_repo_id or request.policy_path or "fake/policy"
        return {
            "ok": True,
            "tool": "lerobot.policy.download",
            "mode": mode,
            "profile_id": profile_id,
            "status": "dry_run",
            "policy_ref": policy_ref,
            "command_preview": ["hf", "download", policy_ref],
            "step_trace": [{"step": "POLICY_DOWNLOAD_DRY_RUN", "status": "ok", "detail": policy_ref}],
            "error": None,
        }

    def sessions_recent(self) -> list[dict[str, Any]]:
        """Return recent sessions for GUI status."""
        for session in self._sessions.values():
            self._refresh_process_status(session)
        return [self._public_session(session) for session in sorted(self._sessions.values(), key=lambda item: item.get("created_at", ""))[-20:]]

    def _attach_isaac_mirror_loop_if_requested(self, response: dict[str, Any], payload: dict[str, Any], *, workflow: str) -> dict[str, Any]:
        """Start a follower-state Isaac mirror loop alongside teleop/record when requested."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        if not request.isaac_mirror_enabled:
            return response
        session_id = str(response.get("session_id") or "")
        if not response.get("ok") or not session_id:
            return response
        mode = str(response.get("mode") or request.runtime_mode or request.mode)
        if mode == "live" and workflow in {"teleoperate", "record"}:
            mirror_record_path = self._in_process_isaac_mirror_record_path(workflow, request, session_id, response)
            session = self._sessions.get(session_id)
            receiver_preflight = dict(session.get("isaac_mirror_receiver_preflight") or {}) if session is not None else {}
            response["isaac_mirror"] = {
                "ok": True,
                "session_id": session_id,
                "status": "IN_PROCESS",
                "sample_count": 0,
                "mirror_record_path": str(mirror_record_path),
                "attached_to_session_id": session_id,
                "receiver_preflight": receiver_preflight,
                "sync_summary": {
                    "target_sample_hz": self._isaac_mirror_sample_hz(request),
                    "sample_count": 0,
                    "source": "lerobot_in_process_send_action",
                },
            }
            if workflow == "record":
                dataset_path = Path(str(response.get("dataset_path") or self._dataset_path_for(request))).expanduser()
                record_attempt = self._record_attempt_summary(request, session_id, dataset_path=dataset_path)
                response["record_attempt"] = dict(record_attempt)
                response["isaac_mirror"]["record_attempt_id"] = record_attempt["attempt_id"]
                response["isaac_mirror"]["rgbd_render"] = dict(record_attempt.get("isaac_rgbd_render") or {})
            response["isaac_mirror_session_id"] = session_id
            if session is not None:
                session["isaac_mirror_session_id"] = session_id
                session["isaac_mirror_enabled"] = True
                session["isaac_mirror"] = dict(response["isaac_mirror"])
                session["isaac_mirror_endpoint"] = self._isaac_mirror_endpoint(request)
                session["isaac_mirror_sample_hz"] = self._isaac_mirror_sample_hz(request)
                if workflow == "record":
                    session["record_attempt"] = dict(response.get("record_attempt") or {})
                session.setdefault("step_trace", []).append(
                    {
                        "step": "ISAAC_MIRROR_IN_PROCESS",
                        "status": "ok",
                        "detail": f"{workflow} send_action wrapper -> {self._isaac_mirror_endpoint(request)}",
                    }
                )
                if workflow == "record":
                    metadata = self._write_record_pipeline_metadata(session, create_missing=False)
                    if metadata:
                        session["dataset_pipeline_metadata"] = metadata
                        response["dataset_pipeline_metadata"] = metadata
            self._attach_isaac_timeline_play_if_ready(response, session, request, workflow)
            self._attach_isaac_viewport_frame_if_ready(response, session, request, workflow)
            return response
        mirror_payload = request.model_dump()
        mirror_payload["session_id"] = ""
        mirror_payload["isaac_mirror_attached_to_session_id"] = session_id
        if workflow == "record" and not str(mirror_payload.get("isaac_mirror_record_path") or "").strip():
            dataset_path = Path(str(response.get("dataset_path") or self._dataset_path_for(request))).expanduser()
            mirror_payload["isaac_mirror_record_path"] = str(dataset_path / "sidecar" / "isaac_mirror" / f"{session_id}.jsonl")
        mirror = self.mirror_loop_start(mirror_payload)
        response["isaac_mirror"] = {
            "ok": mirror.get("ok"),
            "session_id": mirror.get("session_id", ""),
            "status": mirror.get("status", ""),
            "sample_count": mirror.get("sample_count", 0),
            "mirror_record_path": mirror.get("mirror_record_path", ""),
            "attached_to_session_id": session_id,
            "sync_summary": dict(mirror.get("sync_summary") or {}),
        }
        if workflow == "record":
            dataset_path = Path(str(response.get("dataset_path") or self._dataset_path_for(request))).expanduser()
            record_attempt = self._record_attempt_summary(request, session_id, dataset_path=dataset_path)
            response["record_attempt"] = dict(record_attempt)
            response["isaac_mirror"]["record_attempt_id"] = record_attempt["attempt_id"]
            response["isaac_mirror"]["rgbd_render"] = dict(record_attempt.get("isaac_rgbd_render") or {})
        response["isaac_mirror_session_id"] = mirror.get("session_id", "")
        session = self._sessions.get(session_id)
        if session is not None:
            session["isaac_mirror_session_id"] = mirror.get("session_id", "")
            session["isaac_mirror_enabled"] = True
            session["isaac_mirror"] = dict(response["isaac_mirror"])
            session["isaac_mirror_endpoint"] = mirror.get("mirror_endpoint", request.isaac_mirror_endpoint)
            session["isaac_mirror_sample_hz"] = mirror.get("mirror_sample_hz", request.isaac_mirror_sample_hz)
            if workflow == "record":
                session["record_attempt"] = dict(response.get("record_attempt") or {})
            session.setdefault("step_trace", []).append(
                {
                    "step": "ISAAC_MIRROR_ATTACHED",
                    "status": "ok" if mirror.get("ok") else "failed",
                    "detail": f"{workflow} -> {mirror.get('session_id', '')}",
                }
            )
            if workflow == "record":
                metadata = self._write_record_pipeline_metadata(session, create_missing=True)
                if metadata:
                    session["dataset_pipeline_metadata"] = metadata
                    response["dataset_pipeline_metadata"] = metadata
        self._attach_isaac_timeline_play_if_ready(response, session, request, workflow)
        self._attach_isaac_viewport_frame_if_ready(response, session, request, workflow)
        return response

    def _in_process_isaac_mirror_record_path(
        self,
        workflow: str,
        request: LeRobotSessionRequest,
        session_id: str,
        response: dict[str, Any] | None = None,
    ) -> Path:
        raw = str(request.isaac_mirror_record_path or "").strip()
        if raw:
            return _resolve_path(self.config.repo_root, raw)
        if workflow == "record":
            dataset_path = Path(str((response or {}).get("dataset_path") or self._dataset_path_for(request))).expanduser()
            return dataset_path / "sidecar" / "isaac_mirror" / f"{session_id}.jsonl"
        return self.config.repo_root / "runs" / "isaac_mirror_sessions" / f"{session_id}.jsonl"

    def _attach_isaac_viewport_frame_if_ready(
        self,
        response: dict[str, Any],
        session: dict[str, Any] | None,
        request: LeRobotSessionRequest,
        workflow: str,
    ) -> None:
        if not bool(getattr(request, "isaac_viewport_frame_on_start", True)):
            return
        if workflow not in {"teleoperate", "record"}:
            return
        receiver_preflight = dict((session or {}).get("isaac_mirror_receiver_preflight") or {})
        if str(receiver_preflight.get("status") or "") != "ready":
            return
        endpoint = self._isaac_mirror_endpoint(request)
        reason = f"{workflow}_start"
        result = self._post_isaac_mirror_viewport_frame(endpoint, reason=reason, timeout_s=self._isaac_mirror_timeout_s(request))
        response["isaac_viewport_frame"] = dict(result)
        if session is not None:
            session["isaac_viewport_frame"] = dict(result)
        trace = {
            "step": "ISAAC_VIEWPORT_FRAME",
            "status": "ok" if result.get("ok") else "warning",
            "detail": str(result.get("viewport_frame_url") or result.get("message") or reason),
        }
        response_trace = response.get("step_trace")
        if isinstance(response_trace, list):
            response_trace.append(trace)
        response_events = response.get("events")
        if isinstance(response_events, list) and response_events is not response_trace:
            response_events.append(trace)
        session_trace = session.get("step_trace") if isinstance(session, dict) else None
        if isinstance(session_trace, list) and session_trace is not response_trace and session_trace is not response_events:
            session_trace.append(trace)

    def _attach_isaac_timeline_play_if_ready(
        self,
        response: dict[str, Any],
        session: dict[str, Any] | None,
        request: LeRobotSessionRequest,
        workflow: str,
    ) -> None:
        if workflow not in {"teleoperate", "record"}:
            return
        if workflow == "record" and self._uses_in_process_lerobot_wrapper(workflow, request):
            return
        receiver_preflight = dict((session or {}).get("isaac_mirror_receiver_preflight") or {})
        if str(receiver_preflight.get("status") or "") != "ready":
            return
        endpoint = self._isaac_mirror_endpoint(request)
        reason = f"{workflow}_start"
        result = self._post_isaac_mirror_timeline_play(endpoint, reason=reason, timeout_s=self._isaac_mirror_timeout_s(request))
        response["isaac_timeline_play"] = dict(result)
        if session is not None:
            session["isaac_timeline_play"] = dict(result)
        trace = {
            "step": "ISAAC_TIMELINE_PLAY",
            "status": "ok" if result.get("ok") else "warning",
            "detail": str(result.get("timeline_play_url") or result.get("message") or result.get("status") or reason),
        }
        response_trace = response.get("step_trace")
        if isinstance(response_trace, list):
            response_trace.append(trace)
        response_events = response.get("events")
        if isinstance(response_events, list) and response_events is not response_trace:
            response_events.append(trace)
        session_trace = session.get("step_trace") if isinstance(session, dict) else None
        if isinstance(session_trace, list) and session_trace is not response_trace and session_trace is not response_events:
            session_trace.append(trace)

    @staticmethod
    def _record_attempt_id(session_id: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "").strip()).strip("._-")
        return f"attempt_{clean or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    @staticmethod
    def _strip_record_attempt_episode_suffix(attempt_id: str) -> str:
        if len(attempt_id) > 6 and attempt_id[-6:-3] == "_ep" and attempt_id[-3:].isdigit():
            return attempt_id[:-6]
        return attempt_id

    @classmethod
    def _record_attempt_id_for_episode(cls, session_id: str, episode_index: int) -> str:
        base_attempt_id = cls._strip_record_attempt_episode_suffix(cls._record_attempt_id(session_id))
        return f"{base_attempt_id}_ep{int(episode_index):03d}"

    def _record_attempt_summary(
        self,
        request: LeRobotSessionRequest,
        session_id: str,
        *,
        dataset_path: Path | None = None,
    ) -> dict[str, Any]:
        dataset = dataset_path or Path(self._dataset_path_for(request)).expanduser()
        episode_index = 0
        attempt_id = self._record_attempt_id_for_episode(session_id, episode_index)
        render_target_fps = _safe_float(
            getattr(request, "isaac_rgbd_render_target_fps", 15.0),
            15.0,
            minimum=0.1,
            maximum=120.0,
        )
        render_cameras = [
            item.strip()
            for item in str(
                getattr(request, "isaac_rgbd_render_cameras", LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS)
                or LEROBOT_DEFAULT_ISAAC_RGBD_RENDER_CAMERAS
            ).split(",")
            if item.strip()
        ]
        overwrite = bool(getattr(request, "record_attempt_overwrite", True))
        attempt_dir = dataset / "sidecar" / "attempts" / f"episode_{episode_index:03d}" / attempt_id
        render_dir = dataset / "sidecar" / "isaac_rgbd" / f"episode_{episode_index:03d}" / attempt_id
        render_enabled = bool(getattr(request, "isaac_rgbd_render_enabled", True))
        return {
            "enabled": True,
            "attempt_id": attempt_id,
            "session_id": session_id,
            "episode_index": episode_index,
            "dataset_path": str(dataset),
            "attempt_dir": str(attempt_dir),
            "manifest_path": str(dataset / "sidecar" / "attempts" / "manifest.jsonl"),
            "target_fps": render_target_fps,
            "overwrite": overwrite,
            "status": "configured",
            "isaac_rgbd_render": {
                "enabled": render_enabled,
                "target_fps": render_target_fps,
                "cameras": render_cameras,
                "output_dir": str(render_dir),
                "manifest_path": str(render_dir / "manifest.jsonl"),
            },
        }

    @staticmethod
    def _read_record_attempts_summary(dataset_path: Path) -> dict[str, Any]:
        manifest_path = dataset_path / "sidecar" / "attempts" / "manifest.jsonl"
        if not manifest_path.is_file():
            return {"available": False, "manifest_path": str(manifest_path), "event_count": 0}
        rows: list[dict[str, Any]] = []
        try:
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    rows.append(parsed)
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "available": False,
                "manifest_path": str(manifest_path),
                "event_count": 0,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        latest = rows[-1] if rows else {}
        attempt_ids = sorted({str(row.get("attempt_id") or "") for row in rows if str(row.get("attempt_id") or "").strip()})
        return {
            "available": bool(rows),
            "manifest_path": str(manifest_path),
            "event_count": len(rows),
            "attempt_count": len(attempt_ids),
            "attempt_ids": attempt_ids,
            "latest_attempt_id": str(latest.get("attempt_id") or ""),
            "latest_event": latest,
        }

    @staticmethod
    def _uses_in_process_isaac_mirror(session_payload: dict[str, Any]) -> bool:
        mirror = session_payload.get("isaac_mirror")
        if not isinstance(mirror, dict):
            return False
        return str(mirror.get("status") or "").upper() == "IN_PROCESS"

    def _refresh_in_process_isaac_mirror_progress(self, session_payload: dict[str, Any]) -> dict[str, Any]:
        """Update an in-process mirror summary from its JSONL sidecar."""
        mirror = session_payload.get("isaac_mirror")
        if not isinstance(mirror, dict):
            return {}
        if str(mirror.get("status") or "").upper() not in {"IN_PROCESS", "IN_PROCESS_STOPPED"}:
            return mirror
        raw_record_path = str(mirror.get("mirror_record_path") or "").strip()
        if not raw_record_path:
            return mirror
        mirror = dict(mirror)
        existing_summary = dict(mirror.get("sync_summary") or {})
        sync_summary = self._in_process_isaac_mirror_sidecar_sync_summary(
            Path(raw_record_path).expanduser(),
            fallback_target_hz=existing_summary.get("target_sample_hz") or session_payload.get("isaac_mirror_sample_hz"),
        )
        mirror["sample_count"] = sync_summary["sample_count"]
        mirror["sync_summary"] = sync_summary
        session_payload["isaac_mirror"] = mirror
        return mirror

    def _in_process_isaac_mirror_stop_summary(self, session_payload: dict[str, Any]) -> dict[str, Any]:
        self._refresh_in_process_isaac_mirror_progress(session_payload)
        mirror = dict(session_payload.get("isaac_mirror") or {})
        raw_record_path = str(mirror.get("mirror_record_path") or "").strip()
        record_path = Path(raw_record_path).expanduser() if raw_record_path else None
        sync_summary = dict(mirror.get("sync_summary") or {})
        if record_path is not None:
            sync_summary = self._in_process_isaac_mirror_sidecar_sync_summary(
                record_path,
                fallback_target_hz=sync_summary.get("target_sample_hz") or session_payload.get("isaac_mirror_sample_hz"),
            )
        sample_count = _safe_int(sync_summary.get("sample_count"), 0, minimum=0)
        return {
            "ok": True,
            "session_id": str(mirror.get("session_id") or session_payload.get("session_id") or ""),
            "status": "IN_PROCESS_STOPPED",
            "sample_count": sample_count,
            "mirror_record_path": str(record_path) if record_path is not None else "",
            "attached_to_session_id": str(session_payload.get("session_id") or ""),
            "sync_summary": sync_summary,
        }

    @staticmethod
    def _jsonl_line_count(path: Path) -> int:
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    @staticmethod
    def _in_process_isaac_mirror_sidecar_sync_summary(path: Path, *, fallback_target_hz: Any | None = None) -> dict[str, Any]:
        """Summarize in-process Isaac mirror JSONL metrics without loading large sidecars."""
        sample_count = 0
        post_latencies: list[float] = []
        post_ok_count = 0
        post_fail_count = 0
        target_hz = _safe_float(fallback_target_hz, 0.0, minimum=0.0)
        sample_period_s = round(1.0 / target_hz, 6) if target_hz > 0 else 0.0
        last_receiver_sample_count: int | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    sample_count += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        post_fail_count += 1
                        continue
                    metrics = record.get("sync_metrics")
                    if not isinstance(metrics, dict):
                        metrics = {}
                    target_hz = _safe_float(metrics.get("target_sample_hz"), target_hz, minimum=0.0)
                    sample_period_s = _safe_float(
                        metrics.get("sample_period_s"),
                        sample_period_s or (1.0 / target_hz if target_hz > 0 else 0.0),
                        minimum=0.0,
                    )
                    if "post_latency_ms" in metrics:
                        post_latencies.append(_safe_float(metrics.get("post_latency_ms"), 0.0, minimum=0.0))
                    if bool(metrics.get("receiver_accepted")):
                        post_ok_count += 1
                    else:
                        post_fail_count += 1
                    receiver_count = metrics.get("receiver_sample_count")
                    if receiver_count is None:
                        post = record.get("isaac_post")
                        if isinstance(post, dict):
                            receiver_count = LeRobotBridge._isaac_mirror_receiver_sample_count(post)
                    try:
                        if receiver_count is not None:
                            last_receiver_sample_count = int(receiver_count)
                    except (TypeError, ValueError):
                        pass
                    timestamp = str(record.get("timestamp") or "").strip()
                    if timestamp:
                        try:
                            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        except ValueError:
                            parsed = None
                        if parsed is not None:
                            first_timestamp = first_timestamp or parsed
                            last_timestamp = parsed
        except OSError:
            pass
        elapsed_s = 0.0
        if first_timestamp is not None and last_timestamp is not None:
            elapsed_s = max(0.0, (last_timestamp - first_timestamp).total_seconds())
        effective_hz = (sample_count - 1) / elapsed_s if sample_count > 1 and elapsed_s > 0 else 0.0
        return {
            "target_sample_hz": target_hz,
            "sample_period_s": round(sample_period_s, 6) if sample_period_s > 0 else 0.0,
            "sample_count": sample_count,
            "effective_sample_hz": round(effective_hz, 3),
            "mean_post_latency_ms": round(sum(post_latencies) / len(post_latencies), 3) if post_latencies else 0.0,
            "max_post_latency_ms": round(max(post_latencies), 3) if post_latencies else 0.0,
            "mean_loop_lag_ms": 0.0,
            "max_loop_lag_ms": 0.0,
            "post_ok_count": post_ok_count,
            "post_fail_count": post_fail_count,
            "last_receiver_sample_count": last_receiver_sample_count,
            "source": "lerobot_in_process_send_action",
        }

    def _refresh_record_isaac_mirror_metadata(self, record_session_id: Any, mirror_result: dict[str, Any]) -> None:
        """Update record-session metadata with final mirror loop status/sample count."""
        session_id = str(record_session_id or "")
        if not session_id:
            return
        session = self._sessions.get(session_id)
        if not session or str(session.get("workflow") or "").lower() != "record":
            return
        session["isaac_mirror_enabled"] = bool(session.get("isaac_mirror_enabled") or mirror_result.get("session_id"))
        session["isaac_mirror_session_id"] = str(mirror_result.get("session_id") or session.get("isaac_mirror_session_id") or "")
        mirror_sync_summary = dict(mirror_result.get("sync_summary") or {})
        if not mirror_sync_summary:
            mirror_sync_summary = self._isaac_mirror_sync_summary(
                self._sessions.get(session["isaac_mirror_session_id"], {}),
                fallback_sample_count=mirror_result.get("sample_count", 0),
            )
        session["isaac_mirror"] = {
            "ok": mirror_result.get("ok"),
            "session_id": session["isaac_mirror_session_id"],
            "status": mirror_result.get("status", ""),
            "sample_count": mirror_result.get("sample_count", 0),
            "mirror_record_path": mirror_result.get("mirror_record_path", ""),
            "attached_to_session_id": session_id,
            "sync_summary": mirror_sync_summary,
        }
        session["isaac_mirror_endpoint"] = mirror_result.get("mirror_endpoint", session.get("isaac_mirror_endpoint", ""))
        session["isaac_mirror_sample_hz"] = mirror_result.get("mirror_sample_hz", session.get("isaac_mirror_sample_hz", 0))
        endpoint = str(session.get("isaac_mirror_endpoint") or "")
        if endpoint:
            receiver_state = self._fetch_isaac_mirror_receiver_state(endpoint, timeout_s=_safe_float(mirror_result.get("mirror_timeout_s"), 0.5, minimum=0.05, maximum=10.0))
            session["isaac_mirror"]["receiver_state_at_stop"] = receiver_state
        metadata = self._write_record_pipeline_metadata(session, create_missing=True)
        if metadata:
            session["dataset_pipeline_metadata"] = metadata

    def _restart_record_isaac_receiver(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        """Restart Isaac Sim for a live recording with the timeline already playing."""
        payload = request.model_dump()
        mode = request.runtime_mode or request.mode
        payload.update(
            {
                "mode": mode,
                "runtime_mode": mode,
                "profile_id": request.profile_id or self._selected_profile_id,
                "isaac_mirror_endpoint": self._isaac_mirror_endpoint(request),
                "isaac_mirror_receiver_force_restart": True,
                "isaac_mirror_receiver_play_timeline_on_startup": True,
                # Record-start active-cam is owned by the LeRobot wrapper. Disabling
                # the extension-side fallback prevents a second capture on timeline play.
                "active_robot_cam_enabled": False,
            }
        )
        return self.mirror_receiver_process_start(payload)

    def _start_session(
        self,
        *,
        tool: str,
        workflow: str,
        request: LeRobotSessionRequest,
        status: str,
        trace: list[tuple[str, str, str]],
        allow_key: str,
        extra_args: list[str],
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error(tool, mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        observation_pipeline_id = self._request_observation_pipeline_id(request, profile)
        request = request.model_copy(update={"observation_pipeline_id": observation_pipeline_id})
        unsafe = self._unsafe_arguments(extra_args + [request.dataset_path, request.policy_path, request.policy_pretrained_path, request.output_dir])
        if unsafe:
            return self._error(tool, mode, profile.profile_id, "LEROBOT_UNSAFE_ARGUMENT", f"Unsafe command argument rejected: {unsafe}")
        blocked = self._live_block_if_needed(tool=tool, mode=mode, profile=profile, workflow=workflow, allow_key=allow_key)
        if blocked:
            return blocked
        port_blocked = self._live_port_block_if_needed(tool=tool, mode=mode, profile=profile, workflow=workflow)
        if port_blocked:
            return port_blocked
        camera_blocked = self._live_camera_block_if_needed(tool=tool, mode=mode, profile=profile, workflow=workflow, request=request)
        if camera_blocked:
            return camera_blocked
        if mode == "live" and not request.confirm_live_execute:
            return self._blocked(tool, mode, profile.profile_id, "LEROBOT_LIVE_CONFIRMATION_REQUIRED", "Live LeRobot execution requires confirm_live_execute=true.", workflow)
        receiver_start: dict[str, Any] | None = None
        record_start_timeline_play: dict[str, Any] | None = None
        if mode == "live" and workflow == "record" and request.isaac_mirror_enabled:
            receiver_start = self._restart_record_isaac_receiver(request)
            if not receiver_start.get("ok"):
                return self._error(
                    tool,
                    mode,
                    profile.profile_id,
                    str(receiver_start.get("failure_code") or "LEROBOT_ISAAC_MIRROR_RECEIVER_RECORD_START_FAILED"),
                    str(receiver_start.get("message") or receiver_start.get("error") or "Isaac Sim receiver failed to start for recording."),
                )
            trace = [
                *trace,
                (
                    "ISAAC_MIRROR_RECEIVER_RESTARTED",
                    "ok",
                    f"pid={receiver_start.get('pid')} playTimelineOnStartup=true",
                ),
            ]
        mirror_preflight = self._live_isaac_mirror_preflight_if_needed(tool=tool, mode=mode, profile=profile, workflow=workflow, request=request)
        if mirror_preflight:
            if not mirror_preflight.get("ok"):
                return mirror_preflight
            preflight_status = str(mirror_preflight.get("status") or "ready")
            trace = [
                *trace,
                (
                    "ISAAC_MIRROR_RECEIVER_READY" if preflight_status == "ready" else "ISAAC_MIRROR_RECEIVER_PENDING",
                    "ok" if preflight_status == "ready" else "warning",
                    str(mirror_preflight.get("detail") or mirror_preflight.get("health_url") or request.isaac_mirror_endpoint),
                ),
            ]
            if mode == "live" and workflow == "record" and request.isaac_mirror_enabled and preflight_status == "ready":
                record_start_timeline_play = self._post_isaac_mirror_timeline_play(
                    self._isaac_mirror_endpoint(request),
                    reason="record_start",
                    timeout_s=self._isaac_mirror_timeout_s(request),
                )
                trace = [
                    *trace,
                    (
                        "ISAAC_TIMELINE_PLAY",
                        "ok" if record_start_timeline_play.get("ok") else "warning",
                        str(
                            record_start_timeline_play.get("timeline_play_url")
                            or record_start_timeline_play.get("message")
                            or record_start_timeline_play.get("status")
                            or "record_start"
                        ),
                    ),
                ]
        session_id = request.session_id or self._new_session_id(workflow)
        step_trace = [{"step": step, "status": step_status, "detail": detail} for step, step_status, detail in trace]
        command_preview = self._workflow_command(profile, workflow, request, extra_args)
        session = {
            "session_id": session_id,
            "tool": tool,
            "workflow": workflow,
            "mode": mode,
            "profile_id": profile.profile_id,
            "observation_pipeline_id": observation_pipeline_id,
            "status": status,
            "command_preview": command_preview,
            "step_trace": step_trace,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_repo_id": request.dataset_repo_id,
            "dataset_root": request.dataset_root or str(self.config.dataset_root),
            "dataset_path": self._dataset_path_for(request),
            "output_dir": request.output_dir,
            "job_name": request.job_name,
            "checkpoint_path": self._train_checkpoint_path(profile, request)
            if workflow == "train"
            else request.policy_checkpoint_path
            or request.policy_path
            or str(self.config.fake_checkpoint_root / "policy.ckpt"),
            "policy_type": request.policy_type,
            "policy_path": request.policy_path,
            "policy_checkpoint_path": request.policy_checkpoint_path,
            "policy_repo_id": request.policy_repo_id,
            "rollout_inference_type": request.rollout_inference_type,
            "active_robot_cam_home_pose_path": self._active_robot_cam_home_pose_path(request),
            "active_robot_cam_capture_pose_path": self._active_robot_cam_capture_pose_path(request),
            "log_path": "",
            "pid": None,
            "returncode": None,
            "virtual_bridge_simulation": bool(request.virtual_bridge_simulation),
            "tts": self._tts_config_for_request(request) if workflow == "record" else {},
        }
        if mirror_preflight and request.isaac_mirror_enabled and workflow in {"teleoperate", "record"}:
            session["isaac_mirror_receiver_preflight"] = {
                "ok": bool(mirror_preflight.get("ok")),
                "status": str(mirror_preflight.get("status") or ""),
                "warning_code": str(mirror_preflight.get("warning_code") or ""),
                "health_url": str(mirror_preflight.get("health_url") or ""),
                "detail": str(mirror_preflight.get("detail") or ""),
                "receiver_health": dict(mirror_preflight.get("receiver_health") or {}),
            }
        if receiver_start is not None:
            session["isaac_mirror_receiver_start"] = dict(receiver_start)
        if record_start_timeline_play is not None:
            session["isaac_timeline_play"] = dict(record_start_timeline_play)
        if request.active_robot_cam_enabled and workflow in {"teleoperate", "record"}:
            session["active_robot_cam"] = self._active_robot_cam_summary(request, workflow=workflow)
            step_trace.append(
                {
                    "step": "ACTIVE_ROBOT_CAM_ENABLED",
                    "status": "ok",
                    "detail": "D405 wrist direct A4 mapping; D455F top fallback available",
                }
            )
        if workflow == "record":
            session["isaac_rgbd_post_render_auto_on_record_success"] = bool(
                getattr(request, "isaac_rgbd_post_render_auto_on_record_success", True)
            )
            if request.isaac_mirror_enabled:
                session["record_attempt"] = self._record_attempt_summary(request, session_id)
            session["expected_depth_features"] = self._expected_record_depth_features(profile, request)
            raw_depth_sidecar = self._record_raw_depth_sidecar(profile, request)
            if raw_depth_sidecar.get("enabled"):
                session["raw_depth_sidecar"] = raw_depth_sidecar
            metadata = self._write_record_pipeline_metadata(session, create_missing=(mode != "live"))
            if metadata:
                session["dataset_pipeline_metadata"] = metadata
        if workflow == "train":
            session["train_config"] = self._train_config_summary(profile, request)
            session["dataset_mix"] = dict(session["train_config"].get("dataset_mix") or self._train_dataset_mix_summary(request))
            session["fidelity_weights"] = dict(session["train_config"].get("fidelity_weights") or self._train_fidelity_summary(request))
            session["output_dir"] = session["train_config"].get("output_dir", "")
            session["job_name"] = session["train_config"].get("job_name", "")
            session["record_attempts"] = self._read_record_attempts_summary(Path(self._dataset_path_for(request)).expanduser())
            session["isaac_data_augmentation"] = self._read_latest_isaac_augmentation_summary(Path(self._dataset_path_for(request)).expanduser())
            session["isaac_lab_synthetic"] = self._read_latest_isaac_lab_synthetic_summary(Path(self._dataset_path_for(request)).expanduser())
            session["training_preflight"] = self._training_preflight_progress(session)
        if mode == "live":
            live_start = self._start_live_process(
                session_id=session_id,
                command=command_preview,
                env_overrides=self._workflow_env_overrides(workflow, request, session_id=session_id),
            )
            if live_start.get("session_updates"):
                session.update(dict(live_start["session_updates"]))
            if not live_start["ok"]:
                session["status"] = "FAILED"
                failure_trace = {
                    "step": str(live_start.get("failure_code", "PROCESS_START_FAILED")),
                    "status": "failed",
                    "detail": str(live_start.get("message", "Live LeRobot process failed during startup.")),
                }
                step_trace.append(failure_trace)
                session["step_trace"] = step_trace
                self._sessions[session_id] = session
                return self._session_response(
                    tool,
                    mode,
                    session,
                    step_trace,
                    ok=False,
                    failure_code=str(live_start.get("failure_code", "LEROBOT_PROCESS_START_FAILED")),
                    message=str(live_start.get("message", "")),
                    error=str(live_start.get("message", "")),
                )
            if live_start.get("completed_during_startup"):
                session["status"] = "COMPLETED"
                step_trace.append({"step": "PROCESS_COMPLETED", "status": "ok", "detail": f"returncode={session.get('returncode')}"})
            else:
                session["status"] = status if status != "COMPLETED" else "RUNNING"
                step_trace.append({"step": "PROCESS_STARTED", "status": "active", "detail": f"pid={session.get('pid')}"})
                if workflow == "train":
                    session["monitor"] = self._start_training_monitor(session, request)
        self._sessions[session_id] = session
        self._emit_trace(event_payload or request.model_dump(), tool, step_trace, profile.profile_id, mode, session_id)
        return self._session_response(tool, mode, session, step_trace)

    def _stop_session(
        self,
        tool: str,
        payload: dict[str, Any],
        workflow: str,
        *,
        stopped_status: str = "STOPPED",
    ) -> dict[str, Any]:
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        session = self._resolve_session(request.session_id, workflow, prefer_active=True)
        profile_id = str(session.get("profile_id") if session else request.profile_id or self._selected_profile_id)
        if session is None:
            cleanup_trace = self._cleanup_lerobot_processes(workflow)
            step_trace = cleanup_trace or [{"step": "STOP", "status": "ok", "detail": "no active session; idempotent stop"}]
            return {
                "ok": True,
                "tool": tool,
                "mode": mode,
                "profile_id": profile_id,
                "session_id": request.session_id,
                "status": stopped_status,
                "idempotent": True,
                "command_preview": [],
                "step_trace": step_trace,
                "events": step_trace,
                "error": None,
            }
        process = self._processes.get(str(session.get("session_id", "")))
        if process and process.poll() is None:
            self._terminate_live_process(process, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_live_process(process, signal.SIGKILL)
                process.wait(timeout=5)
            session["returncode"] = process.returncode
        self._stop_training_monitor(session)
        cleanup_trace = self._cleanup_lerobot_processes(workflow)
        self._close_log_handle(str(session.get("session_id", "")))
        session["status"] = stopped_status
        session["port_reclaim_status"] = "attempted"
        step_trace = [
            {"step": "STOPPING", "status": "ok", "detail": workflow},
            {"step": stopped_status, "status": "ok", "detail": "session stopped"},
        ] + cleanup_trace
        session.setdefault("step_trace", []).extend(step_trace)
        self._emit_trace(payload, tool, step_trace, profile_id, mode, session["session_id"])
        return self._session_response(tool, mode, session, step_trace, idempotent=True)

    def _stop_all_workflow_sessions(
        self,
        tool: str,
        payload: dict[str, Any],
        workflow: str,
        *,
        stopped_status: str = "STOPPED",
    ) -> dict[str, Any]:
        """Stop every tracked session for a workflow, then remove stale project subprocesses."""
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        sessions = [session for session in self._sessions.values() if session.get("workflow") == workflow]
        selected = self._resolve_session(request.session_id, workflow, prefer_active=True)
        if selected is None and sessions:
            selected = sessions[-1]
        profile_id = str((selected or {}).get("profile_id") or request.profile_id or self._selected_profile_id)

        step_trace: list[dict[str, Any]] = [{"step": "STOPPING", "status": "ok", "detail": f"{workflow}: all sessions"}]
        stopped_session_ids: list[str] = []
        for session in sessions:
            session_id = str(session.get("session_id", ""))
            process = self._processes.get(session_id)
            if process and process.poll() is None:
                self._terminate_live_process(process, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._terminate_live_process(process, signal.SIGKILL)
                    process.wait(timeout=5)
                session["returncode"] = process.returncode
                self._processes.pop(session_id, None)
                step_trace.append({"step": "STOP_TRACKED_PROCESS", "status": "ok", "detail": f"session={session_id} pid={process.pid}"})
            elif process:
                session["returncode"] = process.returncode
                self._processes.pop(session_id, None)
            self._stop_training_monitor(session)
            self._close_log_handle(session_id)
            session["status"] = stopped_status
            session.setdefault("step_trace", []).extend(
                [
                    {"step": "STOPPING", "status": "ok", "detail": workflow},
                    {"step": stopped_status, "status": "ok", "detail": "session stopped by workflow reset"},
                ]
            )
            if session_id:
                stopped_session_ids.append(session_id)

        cleanup_trace = self._cleanup_lerobot_processes(workflow)
        for session in sessions:
            session["port_reclaim_status"] = "attempted"
        step_trace.extend(cleanup_trace)
        step_trace.append({"step": stopped_status, "status": "ok", "detail": f"{workflow}: reset complete; sessions={len(stopped_session_ids)}"})

        if selected is None:
            return {
                "ok": True,
                "tool": tool,
                "mode": mode,
                "profile_id": profile_id,
                "session_id": request.session_id,
                "workflow": workflow,
                "status": stopped_status,
                "idempotent": True,
                "stopped_session_ids": stopped_session_ids,
                "command_preview": [],
                "step_trace": step_trace,
                "events": step_trace,
                "error": None,
            }

        selected["status"] = stopped_status
        selected.setdefault("step_trace", []).extend(step_trace)
        self._emit_trace(payload, tool, step_trace, profile_id, mode, str(selected.get("session_id", "")))
        return self._session_response(tool, mode, selected, step_trace, idempotent=True, stopped_session_ids=stopped_session_ids)

    def _session_status(self, tool: str, payload: dict[str, Any], workflow: str, *, prefer_active: bool = False) -> dict[str, Any]:
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        session = self._resolve_session(request.session_id, workflow, prefer_active=prefer_active)
        profile_id = str(session.get("profile_id") if session else request.profile_id or self._selected_profile_id)
        if session is None:
            step_trace = [{"step": "STATUS", "status": "idle", "detail": f"no active {workflow} session"}]
            return {
                "ok": True,
                "tool": tool,
                "mode": mode,
                "profile_id": profile_id,
                "session_id": request.session_id,
                "workflow": workflow,
                "status": "IDLE",
                "runtime": {
                    "phase": "IDLE",
                    "message": f"No active {workflow} session.",
                    "action_count": 0,
                    "max_abs_delta": None,
                    "warnings": [],
                    "log_path": "",
                    "pid": None,
                    "returncode": None,
                },
                "runtime_phase": "IDLE",
                "runtime_message": f"No active {workflow} session.",
                "command_preview": [],
                "events": step_trace,
                "step_trace": step_trace,
                "log_path": "",
                "log_tail": "",
                "pid": None,
                "returncode": None,
                "error": None,
            }
        self._refresh_process_status(session)
        return self._session_response(tool, mode, session, list(session.get("step_trace", [])))

    def _current_isaac_rgbd_post_render_for_session(self, session: dict[str, Any]) -> dict[str, Any]:
        if str(session.get("workflow") or "").lower() != "record":
            return {}
        dataset_path = str(session.get("dataset_path") or "").strip()
        if not dataset_path:
            return dict(session.get("isaac_rgbd_post_render") or {}) if isinstance(session.get("isaac_rgbd_post_render"), dict) else {}
        job_id = self._isaac_rgbd_post_render_job_id(Path(dataset_path).expanduser().resolve(), str(session.get("session_id") or ""))
        with self._isaac_rgbd_render_lock:
            job = dict(self._isaac_rgbd_render_jobs.get(job_id, {}))
        return job or (dict(session.get("isaac_rgbd_post_render") or {}) if isinstance(session.get("isaac_rgbd_post_render"), dict) else {})

    @staticmethod
    def _command_preview_option(command_preview: list[Any], option: str) -> str:
        prefix = f"{option}="
        for item in command_preview:
            text = str(item)
            if text.startswith(prefix):
                return text[len(prefix) :]
        return ""

    def _device_port_occupants(self, port: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Return processes currently holding a device/file path open."""
        raw = str(port or "").strip()
        if not raw:
            return []
        try:
            target = Path(raw).expanduser().resolve(strict=False)
        except OSError:
            target = Path(raw).expanduser()
        proc_root = Path("/proc")
        if not proc_root.exists():
            return []
        occupants: list[dict[str, Any]] = []
        for proc_dir in proc_root.iterdir():
            if not proc_dir.name.isdigit():
                continue
            fd_dir = proc_dir / "fd"
            if not fd_dir.is_dir():
                continue
            try:
                fd_entries = list(fd_dir.iterdir())
            except (OSError, PermissionError):
                continue
            matched_fd = ""
            for fd in fd_entries:
                try:
                    linked = Path(os.readlink(fd)).resolve(strict=False)
                except (OSError, PermissionError):
                    continue
                if linked == target:
                    matched_fd = fd.name
                    break
            if not matched_fd:
                continue
            try:
                pid = int(proc_dir.name)
            except ValueError:
                continue
            try:
                name = (proc_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                name = ""
            try:
                raw_cmdline = (proc_dir / "cmdline").read_bytes()
                cmdline = " ".join(part.decode("utf-8", "replace") for part in raw_cmdline.split(b"\0") if part)
            except OSError:
                cmdline = ""
            occupants.append({"pid": pid, "name": name or cmdline.split(" ", 1)[0], "fd": matched_fd, "cmdline": cmdline})
            if len(occupants) >= limit:
                break
        return sorted(occupants, key=lambda item: int(item.get("pid") or 0))

    def _session_runtime_contract_blocks(self, session: dict[str, Any], runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
        command_preview = list(session.get("command_preview", []))
        workflow = str(session.get("workflow") or "").strip().lower()
        status = str(session.get("status") or "unknown").strip() or "unknown"
        profile_id = str(session.get("profile_id") or "").strip()
        profile = self._profile(profile_id) if profile_id else None
        follower_port = self._command_preview_option(command_preview, "--robot.port")
        leader_port = self._command_preview_option(command_preview, "--teleop.port")
        if profile is not None:
            follower_port = follower_port or self._device_port(profile, "follower", allow_fake=True)
            leader_port = leader_port or self._device_port(profile, "leader", allow_fake=True)
        port_status = "ready" if follower_port or leader_port else "unknown"
        port_occupants: list[dict[str, Any]] = []
        for role, port in (("follower", follower_port), ("leader", leader_port)):
            for occupant in self._device_port_occupants(port):
                decorated = dict(occupant)
                decorated["role"] = role
                decorated["port"] = port
                port_occupants.append(decorated)
        availability = "occupied" if port_occupants else "available" if follower_port or leader_port else "unknown"
        occupant_process = ""
        if port_occupants:
            first = port_occupants[0]
            occupant_process = f"pid={first.get('pid')} {first.get('name') or first.get('cmdline') or 'process'}"

        active_robot_cam = session.get("active_robot_cam") if isinstance(session.get("active_robot_cam"), dict) else {}
        active_camera_status = str(active_robot_cam.get("status") or "").strip()
        camera_conflict = str(active_robot_cam.get("conflict_reason") or active_robot_cam.get("blocking_reason") or "").strip()
        if not active_camera_status:
            active_camera_status = "blocked" if camera_conflict else "ready" if workflow in {"teleoperate", "record", "rollout"} else "unknown"

        policy_ref = (
            str(session.get("policy_path") or "").strip()
            or str(session.get("policy_checkpoint_path") or "").strip()
            or str(session.get("policy_repo_id") or "").strip()
            or str(session.get("checkpoint_path") or "").strip()
        )
        visualization = session.get("visualization") if isinstance(session.get("visualization"), dict) else {}
        viewer_url = str(visualization.get("viewer_url") or visualization.get("rerun_web_url") or "").strip()
        rerun_status = "available" if viewer_url else "waiting" if bool(visualization) else "disabled"

        return {
            "port_lease": {
                "schema": "atr.lerobot.port_lease.v1",
                "status": port_status,
                "profile_id": profile_id,
                "workflow": workflow,
                "follower_port": follower_port,
                "leader_port": leader_port,
                "current_availability": availability,
                "occupant_process": occupant_process,
                "occupant_processes": port_occupants,
                "reclaim_status": str(session.get("port_reclaim_status") or "not_attempted"),
            },
            "active_camera_lease": {
                "schema": "atr.lerobot.active_camera_lease.v1",
                "status": active_camera_status,
                "owner": str(active_robot_cam.get("owner") or workflow or "idle"),
                "camera_key": str(active_robot_cam.get("camera_key") or active_robot_cam.get("primary_camera_key") or ""),
                "physical_path": str(active_robot_cam.get("physical_path") or active_robot_cam.get("path") or ""),
                "serial": str(active_robot_cam.get("serial") or ""),
                "returned_to_vla": bool(active_robot_cam.get("returned_to_vla", True)),
                "conflict_reason": camera_conflict,
            },
            "policy_runtime": {
                "schema": "atr.lerobot.policy_runtime.v1",
                "policy_type": str(session.get("policy_type") or "").strip(),
                "policy_ref": policy_ref,
                "inference_type": str(session.get("rollout_inference_type") or "").strip(),
                "session_id": str(session.get("session_id") or ""),
                "pid": session.get("pid"),
                "status": status,
                "phase": runtime.get("phase"),
                "message": runtime.get("message"),
                "action_count": runtime.get("action_count", 0),
                "max_abs_delta": runtime.get("max_abs_delta"),
                "action_rate_hz": runtime.get("action_rate_hz"),
                "latency_ms": runtime.get("latency_ms"),
                "warnings": list(runtime.get("warnings") or []),
                "log_path": str(session.get("log_path") or runtime.get("log_path") or ""),
                "fatal_marker": bool(str(runtime.get("phase") or "").upper() == "FAILED"),
            },
            "rerun_telemetry": {
                "schema": "atr.lerobot.rerun_telemetry.v1",
                "status": rerun_status,
                "viewer_pid": visualization.get("pid"),
                "viewer_url": str(visualization.get("viewer_url") or ""),
                "rerun_web_url": str(visualization.get("rerun_web_url") or ""),
                "rerun_ws_url": str(visualization.get("rerun_ws_url") or ""),
                "rrd_path": str(visualization.get("rrd_path") or visualization.get("output_path") or ""),
                "stream_keys": list(visualization.get("stream_keys") or []),
                "latest_frame_artifact": str(visualization.get("latest_frame_artifact") or ""),
            },
        }

    def _session_response(self, tool: str, mode: str, session: dict[str, Any], step_trace: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        self._refresh_in_process_isaac_mirror_progress(session)
        post_render = self._current_isaac_rgbd_post_render_for_session(session)
        if post_render:
            session["isaac_rgbd_post_render"] = post_render
        if str(session.get("workflow") or "").lower() == "record":
            metadata = self._write_record_pipeline_metadata(session, create_missing=False)
            if metadata:
                session["dataset_pipeline_metadata"] = metadata
        training = self._training_progress(session)
        log_tail = self._tail_file(str(session.get("log_path", "")))
        runtime = self._runtime_status_from_log(session, log_tail)
        depth_validation = self._record_depth_validation(session)
        depth_failed = bool(depth_validation and depth_validation.get("status") == "failed")
        if depth_failed:
            session["status"] = "FAILED"
            if not any(item.get("step") == "LEROBOT_REALSENSE_DEPTH_FEATURE_MISSING" for item in step_trace):
                step_trace.append(
                    {
                        "step": "LEROBOT_REALSENSE_DEPTH_FEATURE_MISSING",
                        "status": "failed",
                        "detail": str(depth_validation.get("message", "")),
                    }
                )
        payload = {
            "ok": not depth_failed,
            "tool": tool,
            "mode": mode,
            "profile_id": session.get("profile_id", ""),
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "observation_pipeline_id": session.get("observation_pipeline_id", ""),
            "status": session.get("status", ""),
            "runtime": runtime,
            "runtime_phase": runtime.get("phase"),
            "runtime_message": runtime.get("message"),
            "action_count": runtime.get("action_count"),
            "max_abs_delta": runtime.get("max_abs_delta"),
            "command_preview": list(session.get("command_preview", [])),
            "events": step_trace,
            "step_trace": step_trace,
            "dataset_repo_id": session.get("dataset_repo_id", ""),
            "dataset_root": session.get("dataset_root", ""),
            "dataset_path": session.get("dataset_path", ""),
            "output_dir": session.get("output_dir", ""),
            "job_name": session.get("job_name", ""),
            "checkpoint_path": session.get("checkpoint_path", ""),
            "log_path": session.get("log_path", ""),
            "log_tail": log_tail,
            "pid": session.get("pid"),
            "returncode": session.get("returncode"),
            "tts": session.get("tts", {}),
            "monitor": session.get("monitor", {}),
            "error": None,
            "virtual_bridge_simulation": bool(session.get("virtual_bridge_simulation")),
        }
        payload.update(self._session_runtime_contract_blocks(session, runtime))
        if str(session.get("workflow") or "").lower() == "rollout":
            payload.update(self._rollout_joint_telemetry_contract(session))
        if str(session.get("workflow") or "").lower() == "isaac_mirror":
            payload.update(
                {
                    "mirror_endpoint": session.get("mirror_endpoint", ""),
                    "mirror_sample_hz": session.get("mirror_sample_hz", 0),
                    "mirror_record_path": session.get("mirror_record_path", ""),
                    "attached_to_session_id": session.get("attached_to_session_id", ""),
                    "sample_count": session.get("sample_count", 0),
                    "last_joint_state": session.get("last_joint_state", []),
                    "last_isaac_post": session.get("last_isaac_post", {}),
                    "sync_summary": self._isaac_mirror_sync_summary(session),
                }
            )
        if isinstance(session.get("isaac_mirror"), dict):
            payload["isaac_mirror"] = dict(session["isaac_mirror"])
            payload["isaac_mirror_session_id"] = session.get("isaac_mirror_session_id", "")
        if isinstance(session.get("isaac_timeline_play"), dict):
            payload["isaac_timeline_play"] = dict(session["isaac_timeline_play"])
        if isinstance(session.get("active_robot_cam"), dict):
            payload["active_robot_cam"] = dict(session["active_robot_cam"])
        if isinstance(session.get("record_attempt"), dict):
            payload["record_attempt"] = dict(session["record_attempt"])
        if isinstance(session.get("record_attempts"), dict):
            payload["record_attempts"] = dict(session["record_attempts"])
        if isinstance(session.get("isaac_data_augmentation"), dict):
            payload["isaac_data_augmentation"] = dict(session["isaac_data_augmentation"])
        if isinstance(session.get("isaac_lab_synthetic"), dict):
            payload["isaac_lab_synthetic"] = dict(session["isaac_lab_synthetic"])
        if isinstance(session.get("dataset_mix"), dict):
            payload["dataset_mix"] = dict(session["dataset_mix"])
        if isinstance(session.get("fidelity_weights"), dict):
            payload["fidelity_weights"] = dict(session["fidelity_weights"])
        if isinstance(session.get("isaac_rgbd_post_render"), dict):
            payload["isaac_rgbd_post_render"] = dict(session["isaac_rgbd_post_render"])
        if session.get("raw_depth_sidecar"):
            payload["raw_depth_sidecar"] = self._record_raw_depth_sidecar_status(dict(session["raw_depth_sidecar"]))
        if depth_validation:
            payload["dataset_depth_validation"] = depth_validation
        if depth_failed:
            payload["failure_code"] = "LEROBOT_REALSENSE_DEPTH_FEATURE_MISSING"
            payload["message"] = str(depth_validation.get("message", "RealSense depth feature is missing from the recorded dataset."))
            payload["error"] = payload["message"]
        if str(session.get("workflow") or "").lower() == "train":
            payload["training"] = {**dict(session.get("train_config", {})), **dict(training or {})}
            if isinstance(session.get("training_preflight"), dict):
                payload["training_preflight"] = dict(session["training_preflight"])
        elif training:
            payload["training"] = training
        if session.get("visualization"):
            payload["visualization"] = session.get("visualization", {})
        payload.update(extra)
        return payload

    def _rollout_joint_telemetry_contract(self, session: dict[str, Any]) -> dict[str, Any]:
        """Expose measured motion state and the post-place gate without opening robot ports."""
        session_id = self._safe_session_id(str(session.get("session_id") or "live"))
        if bool(session.get("virtual_bridge_simulation")) and str(session.get("mode") or "") != "live":
            return {
                "joint_telemetry": {
                    "schema": TELEMETRY_SCHEMA,
                    "status": "simulated",
                    "session_id": session_id,
                    "log_path": "",
                    "packet": {
                        "sequence": 3,
                        "measured_base_state": "home",
                        "measured_gripper_state": "idle",
                        "source": "virtual_bridge",
                    },
                },
                "post_place_interlock": {
                    "schema": "post_place_interlock.v1",
                    "session_id": session_id,
                    "ungrasping_seen": True,
                    "ungrasping_sequence": 2,
                    "measured_base_state": "home",
                    "measured_gripper_state": "idle",
                    "home_gate_passed": True,
                    "home_after_ungrasping": True,
                    "ready_for_utm_snapshot": True,
                    "latest_sequence": 3,
                    "source": "virtual_bridge",
                },
            }
        log_path = self._omx_action_log_path(session_id)
        with self._joint_telemetry_gate_lock:
            packets = self._joint_telemetry_observer.poll(log_path, session)
            interlock = self._post_place_interlocks.setdefault(
                session_id,
                PostPlaceInterlock(session_id=session_id),
            )
            for packet in packets:
                interlock.observe(packet)
            if packets:
                self._latest_joint_telemetry_packets[session_id] = dict(packets[-1])
            latest_packet = self._latest_joint_telemetry_packets.get(session_id)
            interlock_snapshot = interlock.snapshot()
        return {
            "joint_telemetry": {
                "schema": TELEMETRY_SCHEMA,
                "status": "available" if latest_packet else "waiting",
                "session_id": session_id,
                "log_path": str(log_path),
                "packet": dict(latest_packet) if latest_packet else None,
            },
            "post_place_interlock": interlock_snapshot,
        }

    def _run_isaac_mirror_loop(
        self,
        session: dict[str, Any],
        request: LeRobotBaseRequest,
        stop_event: threading.Event,
        *,
        max_samples: int | None = None,
    ) -> None:
        """Read follower state, post it to Isaac, and persist one JSONL row per sample."""
        mode = str(session.get("mode") or request.runtime_mode or request.mode)
        profile_id = str(session.get("profile_id") or request.profile_id or self._selected_profile_id)
        endpoint = str(session.get("mirror_endpoint") or self._isaac_mirror_endpoint(request))
        timeout_s = _safe_float(session.get("mirror_timeout_s"), self._isaac_mirror_timeout_s(request), minimum=0.05, maximum=10.0)
        sample_hz = _safe_float(session.get("mirror_sample_hz"), self._isaac_mirror_sample_hz(request), minimum=0.1, maximum=120.0)
        period_s = 1.0 / sample_hz
        record_path = Path(str(session.get("mirror_record_path") or self._isaac_mirror_record_path(request, str(session.get("session_id", "")))))
        record_path.parent.mkdir(parents=True, exist_ok=True)
        session_id = str(session.get("session_id", ""))
        attached_to = str(session.get("attached_to_session_id") or request.isaac_mirror_attached_to_session_id or "")
        started = time.monotonic()
        sample_count = int(session.get("sample_count") or 0)
        live_reader_context = None
        live_joint_map: list[dict[str, Any]] = []
        live_follower_port = ""
        try:
            if mode == "live":
                profile = self._profile(profile_id)
                if profile is None:
                    raise RuntimeError(f"Robot profile not found: {profile_id}")
                live_joint_map = [dict(item) for item in ISAAC_OMX_JOINT_MAP]
                motor_ids = [int(item["motor_id"]) for item in live_joint_map]
                live_follower_port = self._device_port(profile, "follower", allow_fake=False)
                live_follower_port = self._runtime_device_port(live_follower_port, "follower", live=True)
                if not live_follower_port:
                    raise RuntimeError("Saved follower port is required before live mirror loop.")
                if live_follower_port.startswith("/dev/") and not Path(live_follower_port).exists():
                    raise RuntimeError(f"Follower port is not available: {live_follower_port}")
                live_reader_context = self._open_follower_joint_position_reader(live_follower_port, motor_ids)
            with ExitStack() as stack:
                live_reader = stack.enter_context(live_reader_context) if live_reader_context is not None else None
                with record_path.open("a", encoding="utf-8") as handle:
                    started = time.monotonic()
                    while not stop_event.is_set():
                        sample_started_monotonic = time.monotonic()
                        scheduled_sample_monotonic = started + (sample_count * period_s)
                        next_deadline = sample_started_monotonic + period_s
                        sample_count += 1
                        if live_reader is not None:
                            positions = live_reader.read()
                            probe = self._isaac_mirror_probe_from_positions(
                                mode=mode,
                                profile_id=profile_id,
                                follower_port=live_follower_port,
                                probe_source="live_dynamixel_present_position_persistent",
                                read_step={"step": "READ_LIVE_STATE", "status": "ok", "detail": f"persistent follower={live_follower_port}"},
                                joint_map=live_joint_map,
                                positions=positions,
                            )
                        else:
                            probe = self.mirror_joint_state_probe({"mode": mode, "runtime_mode": mode, "profile_id": profile_id})
                        timestamp = datetime.now(timezone.utc).isoformat()
                        if not probe.get("ok"):
                            failure = {
                                "step": str(probe.get("failure_code") or "LEROBOT_ISAAC_MIRROR_PROBE_FAILED"),
                                "status": "failed",
                                "detail": str(probe.get("message") or probe.get("error") or "Follower joint probe failed."),
                            }
                            session["status"] = "FAILED"
                            session["returncode"] = 1
                            session.setdefault("step_trace", []).append(failure)
                            handle.write(json.dumps({"timestamp": timestamp, "probe": probe, "failure": failure}, ensure_ascii=False) + "\n")
                            handle.flush()
                            break
                        post_payload = {
                            "session_id": session_id,
                            "attached_to_session_id": attached_to,
                            "sample_index": sample_count,
                            "timestamp": timestamp,
                            "elapsed_s": round(time.monotonic() - started, 6),
                            "mode": mode,
                            "profile_id": profile_id,
                            "scene_path": probe.get("scene_path", ""),
                            "articulation_root": probe.get("articulation_root", ""),
                            "follower_port": probe.get("follower_port", ""),
                            "joint_state": probe.get("joint_state", []),
                        }
                        post_started_monotonic = time.monotonic()
                        post_result = self._post_isaac_mirror_state(endpoint, post_payload, timeout_s=timeout_s)
                        post_latency_ms = round((time.monotonic() - post_started_monotonic) * 1000.0, 3)
                        loop_lag_ms = round(max(0.0, sample_started_monotonic - scheduled_sample_monotonic) * 1000.0, 3)
                        sample_total_latency_ms = round((time.monotonic() - sample_started_monotonic) * 1000.0, 3)
                        sync_metrics = {
                            "target_sample_hz": sample_hz,
                            "sample_period_s": period_s,
                            "sample_index": sample_count,
                            "loop_lag_ms": loop_lag_ms,
                            "post_latency_ms": post_latency_ms,
                            "sample_total_latency_ms": sample_total_latency_ms,
                            "receiver_accepted": bool(post_result.get("ok")),
                            "receiver_status_code": post_result.get("status_code"),
                            "receiver_sample_count": self._isaac_mirror_receiver_sample_count(post_result),
                        }
                        record = {**post_payload, "sync_metrics": sync_metrics, "isaac_post": post_result}
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        handle.flush()
                        session["sample_count"] = sample_count
                        session["last_joint_state"] = post_payload["joint_state"]
                        session["last_sample_at"] = timestamp
                        session["last_isaac_post"] = post_result
                        self._update_isaac_mirror_sync_summary(
                            session,
                            sync_metrics,
                            sample_started_monotonic=sample_started_monotonic,
                            sample_finished_monotonic=time.monotonic(),
                        )
                        if not post_result.get("ok"):
                            failure = {
                                "step": "LEROBOT_ISAAC_MIRROR_POST_FAILED",
                                "status": "failed",
                                "detail": str(post_result.get("message") or post_result.get("error") or endpoint),
                            }
                            session["status"] = "FAILED"
                            session["returncode"] = 1
                            session.setdefault("step_trace", []).append(failure)
                            break
                        if max_samples is not None and sample_count >= max_samples:
                            session["status"] = "COMPLETED"
                            session["returncode"] = 0
                            session.setdefault("step_trace", []).append(
                                {"step": "MIRROR_LOOP_COMPLETED", "status": "ok", "detail": f"samples={sample_count}"}
                            )
                            break
                        sleep_s = next_deadline - time.monotonic()
                        if sleep_s > 0:
                            stop_event.wait(timeout=sleep_s)
        except Exception as exc:
            session["status"] = "FAILED"
            session["returncode"] = 1
            session.setdefault("step_trace", []).append(
                {"step": "LEROBOT_ISAAC_MIRROR_LOOP_FAILED", "status": "failed", "detail": f"{exc.__class__.__name__}: {exc}"}
            )
        finally:
            if stop_event.is_set() and str(session.get("status") or "").upper() not in {"COMPLETED", "FAILED"}:
                session["status"] = "STOPPED"
                session["returncode"] = 0
            session.setdefault("step_trace", []).append(
                {"step": "MIRROR_LOOP_STOPPED", "status": "ok", "detail": f"samples={session.get('sample_count', 0)}"}
            )

    @staticmethod
    def _isaac_mirror_receiver_sample_count(post_result: dict[str, Any]) -> int | None:
        """Extract receiver sample count from direct or nested receiver responses."""
        candidates: list[Any] = [post_result.get("sample_count")]
        response = post_result.get("response")
        if isinstance(response, dict):
            candidates.append(response.get("sample_count"))
        for value in candidates:
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _update_isaac_mirror_sync_summary(
        session: dict[str, Any],
        metrics: dict[str, Any],
        *,
        sample_started_monotonic: float,
        sample_finished_monotonic: float,
    ) -> dict[str, Any]:
        """Maintain a compact synchronization summary for GUI/status/metadata evidence."""
        summary = dict(session.get("sync_summary") or {})
        previous_count = _safe_int(summary.get("sample_count"), 0, minimum=0)
        sample_count = _safe_int(metrics.get("sample_index"), previous_count + 1, minimum=previous_count + 1)
        target_hz = _safe_float(metrics.get("target_sample_hz"), _safe_float(summary.get("target_sample_hz"), 0.0, minimum=0.0), minimum=0.0)
        sample_period_s = _safe_float(metrics.get("sample_period_s"), (1.0 / target_hz if target_hz > 0 else 0.0), minimum=0.0)
        post_latency_ms = _safe_float(metrics.get("post_latency_ms"), 0.0, minimum=0.0)
        loop_lag_ms = _safe_float(metrics.get("loop_lag_ms"), 0.0, minimum=0.0)
        prior_n = max(previous_count, 0)
        denominator = max(prior_n + 1, 1)
        mean_post = ((_safe_float(summary.get("mean_post_latency_ms"), 0.0, minimum=0.0) * prior_n) + post_latency_ms) / denominator
        mean_lag = ((_safe_float(summary.get("mean_loop_lag_ms"), 0.0, minimum=0.0) * prior_n) + loop_lag_ms) / denominator
        first_monotonic = session.get("_sync_first_monotonic_s")
        if first_monotonic is None:
            first_monotonic = sample_started_monotonic
            session["_sync_first_monotonic_s"] = first_monotonic
        session["_sync_last_monotonic_s"] = sample_finished_monotonic
        elapsed = max(0.0, float(sample_finished_monotonic) - float(first_monotonic))
        effective_hz = (sample_count - 1) / elapsed if sample_count > 1 and elapsed > 0 else 0.0
        receiver_sample_count = metrics.get("receiver_sample_count")
        updated = {
            "target_sample_hz": target_hz,
            "sample_period_s": round(sample_period_s, 6),
            "sample_count": sample_count,
            "effective_sample_hz": round(effective_hz, 3),
            "mean_post_latency_ms": round(mean_post, 3),
            "max_post_latency_ms": round(max(_safe_float(summary.get("max_post_latency_ms"), 0.0, minimum=0.0), post_latency_ms), 3),
            "mean_loop_lag_ms": round(mean_lag, 3),
            "max_loop_lag_ms": round(max(_safe_float(summary.get("max_loop_lag_ms"), 0.0, minimum=0.0), loop_lag_ms), 3),
            "post_ok_count": _safe_int(summary.get("post_ok_count"), 0, minimum=0) + (1 if bool(metrics.get("receiver_accepted")) else 0),
            "post_fail_count": _safe_int(summary.get("post_fail_count"), 0, minimum=0) + (0 if bool(metrics.get("receiver_accepted")) else 1),
            "last_receiver_sample_count": receiver_sample_count,
        }
        session["sync_summary"] = updated
        return updated

    @staticmethod
    def _isaac_mirror_sync_summary(session: dict[str, Any], *, fallback_sample_count: Any | None = None) -> dict[str, Any]:
        """Return a public sync summary reconciled with the session sample count."""
        summary = dict(session.get("sync_summary") or {})
        fallback_count = _safe_int(
            fallback_sample_count if fallback_sample_count is not None else session.get("sample_count"),
            0,
            minimum=0,
        )
        if fallback_count:
            summary["sample_count"] = max(_safe_int(summary.get("sample_count"), 0, minimum=0), fallback_count)
        if "target_sample_hz" not in summary:
            summary["target_sample_hz"] = _safe_float(session.get("mirror_sample_hz"), 0.0, minimum=0.0)
        if "sample_period_s" not in summary:
            hz = _safe_float(summary.get("target_sample_hz"), 0.0, minimum=0.0)
            summary["sample_period_s"] = round(1.0 / hz, 6) if hz > 0 else 0.0
        summary.setdefault("effective_sample_hz", 0.0)
        summary.setdefault("mean_post_latency_ms", 0.0)
        summary.setdefault("max_post_latency_ms", 0.0)
        summary.setdefault("mean_loop_lag_ms", 0.0)
        summary.setdefault("max_loop_lag_ms", 0.0)
        summary.setdefault("post_ok_count", 0)
        summary.setdefault("post_fail_count", 0)
        summary.setdefault("last_receiver_sample_count", None)
        return summary

    def _post_isaac_mirror_state(self, endpoint: str, payload: dict[str, Any], *, timeout_s: float = 0.5) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: Any = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {"ok": 200 <= status_code < 300, "status_code": status_code, "response": parsed}
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "message": f"{exc.__class__.__name__}: {exc}"}

    def _fetch_isaac_mirror_receiver_health(self, endpoint: str, *, timeout_s: float = 0.5) -> dict[str, Any]:
        health_url = self._isaac_mirror_health_url(endpoint)
        request = Request(health_url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "health_url": health_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "health_url": health_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "health_url": health_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _fetch_isaac_mirror_receiver_state(self, endpoint: str, *, timeout_s: float = 0.5) -> dict[str, Any]:
        state_url = self._isaac_mirror_state_url(endpoint)
        request = Request(state_url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(16384).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "state_url": state_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "state_url": state_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "state_url": state_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _post_isaac_mirror_viewport_frame(self, endpoint: str, *, reason: str, timeout_s: float = 0.5) -> dict[str, Any]:
        frame_url = self._isaac_mirror_viewport_frame_url(endpoint)
        body = json.dumps({"reason": reason}).encode("utf-8")
        request = Request(frame_url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "viewport_frame_url": frame_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "viewport_frame_url": frame_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "viewport_frame_url": frame_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _post_isaac_mirror_timeline_play(self, endpoint: str, *, reason: str, timeout_s: float = 0.5) -> dict[str, Any]:
        play_url = self._isaac_mirror_timeline_play_url(endpoint)
        payload: dict[str, Any] = {"reason": reason}
        if str(reason).startswith("isaac_rgbd_post_render"):
            payload["skip_specimen_pose_on_play"] = True
        body = json.dumps(payload).encode("utf-8")
        request = Request(play_url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "timeline_play_url": play_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "timeline_play_url": play_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "timeline_play_url": play_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _post_isaac_mirror_specimen_pose(self, endpoint: str, payload: dict[str, Any], *, timeout_s: float = 0.5) -> dict[str, Any]:
        specimen_url = self._isaac_mirror_specimen_pose_url(endpoint)
        body = json.dumps(payload).encode("utf-8")
        request = Request(specimen_url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "specimen_pose_url": specimen_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "specimen_pose_url": specimen_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "specimen_pose_url": specimen_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _post_isaac_mirror_timeline_stop(self, endpoint: str, *, reason: str, timeout_s: float = 0.5) -> dict[str, Any]:
        stop_url = self._isaac_mirror_timeline_stop_url(endpoint)
        body = json.dumps({"reason": reason}).encode("utf-8")
        request = Request(stop_url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                raw = response.read(8192).decode("utf-8", errors="replace")
                parsed: dict[str, Any] = {}
                if raw.strip():
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        parsed = {"body": raw}
                status_code = int(getattr(response, "status", 200))
                return {
                    "ok": 200 <= status_code < 300 and bool(parsed.get("ok", True)),
                    "status_code": status_code,
                    "timeline_stop_url": stop_url,
                    **parsed,
                }
        except HTTPError as exc:
            return {"ok": False, "status_code": exc.code, "timeline_stop_url": stop_url, "message": exc.reason or str(exc)}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "status_code": None, "timeline_stop_url": stop_url, "message": f"{exc.__class__.__name__}: {exc}"}

    def _wait_for_isaac_mirror_receiver(
        self,
        endpoint: str,
        *,
        timeout_s: float,
        request_timeout_s: float,
        process: subprocess.Popen[str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] = {"ok": False, "message": "not checked"}
        while time.monotonic() < deadline:
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    return {
                        "ok": False,
                        "failure_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_EXITED",
                        "message": f"Receiver process exited before health became ready (returncode={returncode}).",
                        "returncode": returncode,
                    }
            last = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=request_timeout_s)
            if last.get("ok"):
                return last
            time.sleep(0.1)
        return last

    def _stop_receiver_process(self, endpoint_or_key: str) -> dict[str, Any]:
        process_key = self._isaac_mirror_process_key(endpoint_or_key)
        process = self._receiver_processes.pop(process_key, None)
        log_handle = self._receiver_log_handles.pop(process_key, None)
        self._receiver_commands.pop(process_key, None)
        try:
            if process and process.poll() is None:
                self._terminate_live_process(process, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._terminate_live_process(process, signal.SIGKILL)
                    process.wait(timeout=5)
            return {
                "pid": process.pid if process else None,
                "returncode": process.returncode if process else None,
                "detail": "receiver process stopped" if process else "no managed receiver process",
            }
        finally:
            if log_handle:
                try:
                    log_handle.close()
                except OSError:
                    pass

    def _stop_unmanaged_receiver_processes(self, endpoint: str) -> list[dict[str, Any]]:
        """Stop an Isaac receiver already listening on the endpoint but not tracked in memory."""
        _host, port = self._isaac_mirror_host_port(endpoint)
        try:
            completed = subprocess.run(
                ["ss", "-ltnp"],
                text=True,
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        stopped: list[dict[str, Any]] = []
        seen: set[int] = set()
        for line in (completed.stdout or "").splitlines():
            if f":{port}" not in line:
                continue
            for match in re.finditer(r"pid=(\d+)", line):
                pid = _safe_int(match.group(1), 0, minimum=0)
                if pid <= 0 or pid == os.getpid() or pid in seen:
                    continue
                seen.add(pid)
                try:
                    ps = subprocess.run(
                        ["ps", "-p", str(pid), "-o", "cmd="],
                        text=True,
                        capture_output=True,
                        timeout=2,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                command = (ps.stdout or "").strip()
                if not self._looks_like_isaac_receiver_command(command):
                    continue
                status = "terminated"
                try:
                    os.kill(pid, signal.SIGTERM)
                    deadline = time.monotonic() + 5.0
                    while time.monotonic() < deadline:
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.05)
                    else:
                        os.kill(pid, signal.SIGKILL)
                        status = "killed"
                except ProcessLookupError:
                    status = "already_exited"
                except OSError as exc:
                    status = f"error:{exc.__class__.__name__}"
                stopped.append({"pid": pid, "status": status, "command": command})
        return stopped

    @staticmethod
    def _looks_like_isaac_receiver_command(command: str) -> bool:
        lowered = str(command or "").lower()
        return any(
            marker in lowered
            for marker in (
                "isaacsim",
                "isaac-sim",
                "atr.omx.mirror",
                "isaac_omx_mirror_server.py",
            )
        )

    def _live_isaac_mirror_preflight_if_needed(
        self,
        *,
        tool: str,
        mode: str,
        profile: RobotProfile,
        workflow: str,
        request: LeRobotSessionRequest,
    ) -> dict[str, Any] | None:
        if mode != "live" or workflow not in {"teleoperate", "record"} or not request.isaac_mirror_enabled:
            return None
        endpoint = self._isaac_mirror_endpoint(request)
        timeout_s = self._isaac_mirror_timeout_s(request)
        health = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=timeout_s)
        health_url = str(health.get("health_url") or self._isaac_mirror_health_url(endpoint))
        if not health.get("ok"):
            message = str(health.get("message") or health.get("error") or "Isaac mirror receiver is unavailable.")
            return {
                "ok": True,
                "status": "warning",
                "warning_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE",
                "health_url": health_url,
                "receiver_health": health,
                "detail": (
                    f"Isaac mirror receiver is unavailable at {health_url}: {message}. "
                    "Live teleop/record will start; the in-process mirror publisher will attach when the receiver becomes reachable."
                ),
            }
        apply_mode = str(health.get("apply_mode") or "unknown")
        detail = f"{health_url} apply_mode={apply_mode}"
        if apply_mode != "deferred_update_tick":
            return {
                "ok": True,
                "status": "warning",
                "warning_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_NOT_IN_ISAAC_UPDATE_TICK",
                "health_url": health_url,
                "receiver_health": health,
                "detail": (
                    f"Isaac mirror receiver is reachable at {health_url}, but it is not running inside Isaac Kit update-tick mode: "
                    f"apply_mode={apply_mode}. Live teleop/record will start; use the ATR Isaac extension receiver for active-stage updates."
                ),
            }
        return {"ok": True, "status": "ready", "health_url": health_url, "receiver_health": health, "detail": detail}

    @staticmethod
    def _isaac_mirror_endpoint(request: LeRobotBaseRequest) -> str:
        return str(request.isaac_mirror_endpoint or "http://127.0.0.1:8766/joints").strip()

    @staticmethod
    def _isaac_mirror_process_key(endpoint: str) -> str:
        clean = str(endpoint or "http://127.0.0.1:8766/joints").strip()
        if "://" not in clean and "/" not in clean and ":" in clean:
            return clean
        parsed = urlparse(clean)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8766
        return f"{host}:{port}"

    @staticmethod
    def _isaac_mirror_host_port(endpoint: str) -> tuple[str, int]:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        return parsed.hostname or "127.0.0.1", int(parsed.port or 8766)

    def _isaac_mirror_receiver_command(self, payload: dict[str, Any], endpoint: str) -> dict[str, Any]:
        """Build the managed receiver command.

        The production default launches Isaac Sim with the ATR extension enabled,
        so the HTTP receiver runs inside the Isaac process and can update the
        active stage on Kit update ticks. A direct Python script launch remains
        available for bounded HTTP smoke tests.
        """
        launch_mode = self._isaac_mirror_receiver_launch_mode(payload)
        host, port = self._isaac_mirror_host_port(endpoint)
        scene_path = _resolve_path(self.config.repo_root, str(payload.get("isaac_mirror_receiver_scene") or ISAAC_OMX_SCENE_RELATIVE_PATH))
        if launch_mode == "isaac_extension":
            executable = self._isaac_mirror_receiver_isaac_sim_executable(payload)
            active_robot_cam_enabled = _safe_bool(payload.get("active_robot_cam_enabled"), True)
            play_timeline_on_startup = _safe_bool(payload.get("isaac_mirror_receiver_play_timeline_on_startup"), False)
            extension_root = self.config.repo_root / "sim" / "robotis_omx" / "extensions"
            manifest = extension_root / "atr.omx.mirror" / "config" / "extension.toml"
            if not manifest.exists():
                return {
                    "ok": False,
                    "launch_mode": launch_mode,
                    "failure_code": "LEROBOT_ISAAC_MIRROR_EXTENSION_NOT_FOUND",
                    "message": f"Isaac mirror extension manifest not found: {manifest}",
                }
            if not scene_path.exists():
                return {
                    "ok": False,
                    "launch_mode": launch_mode,
                    "failure_code": "LEROBOT_ISAAC_MIRROR_SCENE_NOT_FOUND",
                    "message": f"Isaac mirror scene not found: {scene_path}",
                }
            if not Path(executable).exists() and shutil.which(executable) is None:
                return {
                    "ok": False,
                    "launch_mode": launch_mode,
                    "failure_code": "LEROBOT_ISAAC_SIM_EXECUTABLE_NOT_FOUND",
                    "message": f"Isaac Sim executable not found: {executable}",
                }
            python_site_packages = self._isaac_sim_python_site_packages(executable)
            command = [
                executable,
                *(
                    [f"--/app/python/extraPaths/0={python_site_packages}"]
                    if python_site_packages
                    else []
                ),
                "--ext-folder",
                str(extension_root),
                "--enable",
                "atr.omx.mirror",
                f"--/exts/atr.omx.mirror/enabled=true",
                f"--/exts/atr.omx.mirror/host={host}",
                f"--/exts/atr.omx.mirror/port={port}",
                f"--/exts/atr.omx.mirror/scene={scene_path}",
                f"--/exts/atr.omx.mirror/useCurrentStage=true",
                f"--/exts/atr.omx.mirror/openSceneOnStartup=true",
                f"--/exts/atr.omx.mirror/playTimelineOnStartup={_bool_arg(play_timeline_on_startup)}",
                f"--/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing={_bool_arg(active_robot_cam_enabled)}",
            ]
            return {"ok": True, "launch_mode": launch_mode, "command": command, "scene_path": str(scene_path)}

        python_executable = self._isaac_mirror_receiver_python(payload)
        script_path = self.config.repo_root / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py"
        if not script_path.exists():
            return {
                "ok": False,
                "launch_mode": launch_mode,
                "failure_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_SCRIPT_NOT_FOUND",
                "message": f"Receiver script not found: {script_path}",
            }
        if not Path(python_executable).exists() and shutil.which(python_executable) is None:
            return {
                "ok": False,
                "launch_mode": launch_mode,
                "failure_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_PYTHON_NOT_FOUND",
                "message": f"Receiver Python not found: {python_executable}",
            }
        return {
            "ok": True,
            "launch_mode": launch_mode,
            "command": [python_executable, str(script_path), "--host", host, "--port", str(port), "--scene", str(scene_path)],
            "scene_path": str(scene_path),
        }

    @staticmethod
    def _isaac_mirror_receiver_launch_mode(payload: dict[str, Any]) -> str:
        explicit = str(payload.get("isaac_mirror_receiver_launch_mode") or "").strip().lower()
        if explicit in {"isaac_extension", "extension", "isaac"}:
            return "isaac_extension"
        if explicit in {"python_script", "script", "python"}:
            return "python_script"
        if str(payload.get("isaac_mirror_receiver_python") or "").strip():
            return "python_script"
        return "isaac_extension"

    @staticmethod
    def _isaac_mirror_receiver_isaac_sim_executable(payload: dict[str, Any]) -> str:
        explicit = str(payload.get("isaac_mirror_receiver_isaac_sim_executable") or "").strip()
        if explicit:
            return explicit
        env_value = os.environ.get("ATR_ISAAC_SIM_EXECUTABLE", "").strip()
        if env_value:
            return env_value
        isaac_sim = Path("/home/jin/IsaacSim/isaac-sim.sh")
        if isaac_sim.exists():
            return str(isaac_sim)
        return "isaac-sim.sh"

    @staticmethod
    def _isaac_sim_python_site_packages(executable: str) -> str:
        resolved = Path(executable)
        if not resolved.exists():
            found = shutil.which(executable)
            if not found:
                return ""
            resolved = Path(found)
        python_lib = resolved.parent / "kit" / "python" / "lib"
        candidates = sorted(p for p in python_lib.glob("python*/site-packages") if p.is_dir())
        return str(candidates[-1]) if candidates else ""

    @staticmethod
    def _isaac_mirror_receiver_python(payload: dict[str, Any]) -> str:
        explicit = str(payload.get("isaac_mirror_receiver_python") or "").strip()
        if explicit:
            return explicit
        env_value = os.environ.get("ATR_ISAAC_MIRROR_RECEIVER_PYTHON", "").strip()
        if env_value:
            return env_value
        isaac_python = Path("/home/jin/IsaacSim/python.sh")
        if isaac_python.exists():
            return str(isaac_python)
        return sys.executable

    @staticmethod
    def _isaac_mirror_health_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/health"
        return parsed._replace(path="/health", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_state_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/state"
        return parsed._replace(path="/state", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_joint_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/joints"
        return parsed._replace(path="/joints", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_viewport_frame_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/viewport/frame"
        return parsed._replace(path="/viewport/frame", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_timeline_play_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/timeline/play"
        return parsed._replace(path="/timeline/play", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_specimen_pose_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/specimen_pose"
        return parsed._replace(path="/specimen_pose", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_timeline_stop_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "http://127.0.0.1:8766/joints").strip())
        if not parsed.scheme or not parsed.netloc:
            return "http://127.0.0.1:8766/timeline/stop"
        return parsed._replace(path="/timeline/stop", params="", query="", fragment="").geturl()

    @staticmethod
    def _isaac_mirror_sample_hz(request: LeRobotBaseRequest) -> float:
        return _safe_float(request.isaac_mirror_sample_hz, 15.0, minimum=0.1, maximum=120.0)

    @staticmethod
    def _isaac_mirror_timeout_s(request: LeRobotBaseRequest) -> float:
        return _safe_float(request.isaac_mirror_timeout_s, 0.5, minimum=0.05, maximum=10.0)

    @staticmethod
    def _isaac_mirror_post_timeout_s(request: LeRobotBaseRequest) -> float:
        return LeRobotBridge._isaac_mirror_timeout_s(request)

    def _isaac_mirror_record_path(self, request: LeRobotBaseRequest, session_id: str) -> Path:
        raw = str(request.isaac_mirror_record_path or "").strip()
        if raw:
            return _resolve_path(self.config.repo_root, raw)
        return self.config.repo_root / "runs" / "isaac_mirror_sessions" / f"{session_id}.jsonl"

    def _resolve_mirror_session(self, session_id: str, attached_to_session_id: str = "", *, prefer_active: bool = False) -> dict[str, Any] | None:
        if session_id:
            session = self._resolve_session(session_id, "isaac_mirror", prefer_active=prefer_active)
            if session is not None:
                return session
        attached = str(attached_to_session_id or "").strip()
        if attached:
            matches = [
                session
                for session in self._sessions.values()
                if session.get("workflow") == "isaac_mirror" and str(session.get("attached_to_session_id") or "") == attached
            ]
            if prefer_active:
                for session in reversed(matches):
                    if self._session_is_active(session):
                        return session
            if matches:
                return matches[-1]
        return self._resolve_session("", "isaac_mirror", prefer_active=prefer_active)

    def _stop_all_mirror_loops(self) -> list[dict[str, Any]]:
        step_trace: list[dict[str, Any]] = []
        for session in [item for item in self._sessions.values() if item.get("workflow") == "isaac_mirror"]:
            session_id = str(session.get("session_id", ""))
            stop_event = self._mirror_stop_events.get(session_id)
            if stop_event:
                stop_event.set()
            thread = self._mirror_threads.get(session_id)
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
            if str(session.get("status") or "").upper() not in {"COMPLETED", "FAILED"}:
                session["status"] = "STOPPED"
                session["returncode"] = 0
            step_trace.append({"step": "STOP_ISAAC_MIRROR", "status": "ok", "detail": f"session={session_id}"})
            self._mirror_stop_events.pop(session_id, None)
            self._mirror_threads.pop(session_id, None)
        return step_trace

    def _write_record_pipeline_metadata(self, session: dict[str, Any], *, create_missing: bool) -> dict[str, Any] | None:
        """Persist the ATR dataset/profile/pipeline contract beside a recorded dataset."""
        if str(session.get("workflow") or "").lower() != "record":
            return None
        dataset_path = Path(str(session.get("dataset_path") or "")).expanduser()
        if not dataset_path:
            return None
        if not create_missing and not dataset_path.exists():
            return None
        pipeline_id = _normalize_observation_pipeline_id(session.get("observation_pipeline_id"))
        pipeline = LEROBOT_OBSERVATION_PIPELINES[pipeline_id]
        sidecar = dict(session.get("raw_depth_sidecar") or {})
        isaac_mirror = dict(session.get("isaac_mirror") or {})
        record_attempt = dict(session.get("record_attempt") or {})
        metadata_path = self._dataset_pipeline_metadata_path(dataset_path)
        payload = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile_id": str(session.get("profile_id") or ""),
            "observation_pipeline_id": pipeline_id,
            "pipeline_label": str(pipeline.get("label") or pipeline_id),
            "dataset_repo_id": str(session.get("dataset_repo_id") or ""),
            "dataset_root": str(session.get("dataset_root") or ""),
            "dataset_path": str(dataset_path),
            "raw_depth_sidecar": {
                "required": bool(pipeline.get("raw_depth_sidecar")),
                "adapter_required": bool(pipeline.get("requires_raw_depth")),
                "enabled": bool(sidecar.get("enabled")),
                "root": str(sidecar.get("root") or ""),
                "format": str(sidecar.get("format") or "png16"),
                "expected_camera_keys": list(sidecar.get("expected_camera_keys") or []),
                "aligned_to": str(sidecar.get("aligned_to") or ("color" if self.config.realsense_depth_align_to_color else "native_depth")),
                "depth_scale_m_per_unit": self.config.realsense_depth_scale_m_per_unit,
                "depth_clip_min_mm": self.config.realsense_depth_clip_min_mm,
                "depth_clip_max_mm": self.config.realsense_depth_clip_max_mm,
                "camera_depth_clip_mm": dict(sidecar.get("camera_depth_clip_mm") or {}),
            },
            "isaac_mirror": {
                "enabled": bool(session.get("isaac_mirror_enabled")),
                "session_id": str(session.get("isaac_mirror_session_id") or isaac_mirror.get("session_id") or ""),
                "attached_to_session_id": str(session.get("session_id") or ""),
                "record_path": str(isaac_mirror.get("mirror_record_path") or ""),
                "endpoint": str(session.get("isaac_mirror_endpoint") or ""),
                "sample_hz": _safe_float(session.get("isaac_mirror_sample_hz"), 0.0, minimum=0.0),
                "sample_count": _safe_int(isaac_mirror.get("sample_count"), 0, minimum=0),
                "status": str(isaac_mirror.get("status") or ""),
                "sync_summary": dict(isaac_mirror.get("sync_summary") or self._isaac_mirror_sync_summary(
                    self._sessions.get(str(session.get("isaac_mirror_session_id") or ""), {}),
                    fallback_sample_count=isaac_mirror.get("sample_count"),
                )),
                "receiver_state_at_stop": dict(isaac_mirror.get("receiver_state_at_stop") or {}),
            },
            "record_attempt": record_attempt,
            "isaac_rgbd_sidecar": dict(record_attempt.get("isaac_rgbd_render") or {}),
        }
        augmentation_summary = self._read_latest_isaac_augmentation_summary(dataset_path)
        if augmentation_summary.get("available"):
            payload["isaac_data_augmentation"] = augmentation_summary
        try:
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return None
        return {
            "path": str(metadata_path),
            "observation_pipeline_id": pipeline_id,
            "profile_id": payload["profile_id"],
        }

    @staticmethod
    def _dataset_pipeline_metadata_path(dataset_path: Path) -> Path:
        return dataset_path / "meta" / "atr_pipeline.json"

    @staticmethod
    def _dataset_raw_depth_manifest_path(dataset_path: Path) -> Path:
        return dataset_path / "sidecar" / "depth_raw" / "transform_manifest.json"

    @staticmethod
    def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not path.is_file():
            return rows
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def _allowed_file_or_none(self, raw_path: Any) -> Path | None:
        clean = str(raw_path or "").strip()
        if not clean:
            return None
        try:
            path = Path(clean).expanduser().resolve()
        except OSError:
            return None
        if not path.is_file() or not self._is_under_allowed_roots(path):
            return None
        return path

    def _resolve_manifest_file_path(self, raw_path: Any, *, dataset_path: Path, manifest_path: Path) -> Path | None:
        clean = str(raw_path or "").strip()
        if not clean:
            return None
        raw = Path(clean).expanduser()
        candidates = [raw] if raw.is_absolute() else [manifest_path.parent / raw, dataset_path / raw]
        for candidate in candidates:
            try:
                path = candidate.resolve()
            except OSError:
                continue
            if path.is_file() and self._is_under_allowed_roots(path):
                return path
        return None

    def _augmentation_source_files(self, row: dict[str, Any], *, dataset_path: Path) -> dict[str, dict[str, Path]]:
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        manifest_raw = str(source.get("manifest_path") or "").strip()
        if not manifest_raw:
            return {}
        manifest_path = Path(manifest_raw).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = dataset_path / manifest_path
        try:
            manifest_path = manifest_path.resolve()
        except OSError:
            return {}
        if not manifest_path.is_file() or not self._is_under_allowed_roots(manifest_path):
            return {}
        target_attempt = str(source.get("attempt_id") or "")
        target_episode = _safe_int(source.get("episode_index"), -1)
        target_frame = _safe_int(source.get("frame_index"), -1)
        for source_row in self._read_jsonl_file(manifest_path):
            attempt_id = str(source_row.get("attempt_id") or manifest_path.parent.name)
            episode_index = _safe_int(source_row.get("episode_index"), 0, minimum=0)
            frame_index = _safe_int(source_row.get("frame_index"), _safe_int(source_row.get("sample_index"), 0, minimum=0), minimum=0)
            if target_attempt and attempt_id != target_attempt:
                continue
            if target_episode >= 0 and episode_index != target_episode:
                continue
            if target_frame >= 0 and frame_index != target_frame:
                continue
            files: dict[str, dict[str, Path]] = {}
            file_infos = source_row.get("files") if isinstance(source_row.get("files"), list) else []
            for file_info in file_infos:
                if not isinstance(file_info, dict):
                    continue
                camera = str(file_info.get("camera") or "").strip()
                kind = str(file_info.get("kind") or "").strip()
                if not camera or kind not in {"rgb", "depth"}:
                    continue
                path = self._resolve_manifest_file_path(file_info.get("path"), dataset_path=dataset_path, manifest_path=manifest_path)
                if path is not None:
                    files.setdefault(camera, {})[kind] = path
            if files:
                return files
        return {}

    @staticmethod
    def _depth_preview_array(depth_path: Path) -> Any:
        from PIL import Image
        import numpy as np

        depth = np.asarray(Image.open(depth_path)).astype(np.float32)
        if depth.size <= 0:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        valid = depth > 0.0
        if not np.any(valid):
            normalized = np.zeros(depth.shape, dtype=np.uint8)
        else:
            valid_values = depth[valid]
            low = float(np.percentile(valid_values, 1.0))
            high = float(np.percentile(valid_values, 99.0))
            if high <= low:
                high = low + 1.0
            normalized_float = ((depth - low) / (high - low)) * 255.0
            normalized_float[~valid] = 0.0
            normalized = np.clip(normalized_float, 0.0, 255.0).astype(np.uint8)
        return np.stack([normalized, normalized, normalized], axis=-1)

    def _write_depth_preview_png(self, depth_path: Path, preview_path: Path) -> Path:
        from PIL import Image

        preview_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self._depth_preview_array(depth_path), mode="RGB").save(preview_path)
        return preview_path

    @staticmethod
    def _media_file_ref(path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        return {
            "path": str(path),
            "name": path.name,
            "size_bytes": path.stat().st_size if path.is_file() else 0,
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
        }

    def _normalize_train_raw_depth_sidecar(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        """Normalize raw depth PNG names to dataset-local frame indices before training."""
        if (request.runtime_mode or request.mode) != "live":
            return {"ok": True, "status": "skipped_non_live", "changed": False}
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        manifest_path = self._dataset_raw_depth_manifest_path(dataset_path)
        if not manifest_path.is_file():
            return {"ok": True, "status": "no_raw_depth_manifest", "changed": False}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Raw depth manifest is not readable: {manifest_path} ({exc.__class__.__name__}: {exc})") from exc

        root = manifest_path.parent
        camera_keys = [str(item).strip() for item in manifest.get("camera_keys", []) if str(item).strip()]
        if not camera_keys:
            camera_keys = sorted(path.name for path in root.iterdir() if path.is_dir())
        results = {camera_key: self._normalize_raw_depth_camera_indices(root / camera_key) for camera_key in camera_keys}
        changed = any(int(result.get("renamed_count", 0)) > 0 for result in results.values())
        if changed:
            normalization_path = root / "index_normalization.json"
            payload = {
                "schema": "atr.raw_depth.index_normalization.v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "dataset_path": str(dataset_path),
                "manifest_path": str(manifest_path),
                "camera_results": results,
            }
            tmp_path = normalization_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            tmp_path.replace(normalization_path)
        return {"ok": True, "status": "normalized" if changed else "already_normalized", "changed": changed, "camera_results": results}

    @staticmethod
    def _normalize_raw_depth_camera_indices(camera_dir: Path) -> dict[str, Any]:
        frame_pattern = re.compile(r"^frame_(\d+)[.]png$")
        if not camera_dir.is_dir():
            return {"camera_dir": str(camera_dir), "status": "missing", "input_count": 0, "renamed_count": 0}
        indexed_files: list[tuple[int, Path]] = []
        for path in camera_dir.glob("frame_*.png"):
            match = frame_pattern.match(path.name)
            if match:
                indexed_files.append((int(match.group(1)), path))
        indexed_files.sort(key=lambda item: (item[0], item[1].name))
        expected_names = [f"frame_{index:06d}.png" for index in range(len(indexed_files))]
        current_names = [path.name for _, path in indexed_files]
        result_base = {
            "camera_dir": str(camera_dir),
            "input_count": len(indexed_files),
            "first_source_index": indexed_files[0][0] if indexed_files else None,
            "last_source_index": indexed_files[-1][0] if indexed_files else None,
        }
        if current_names == expected_names:
            return {**result_base, "status": "already_normalized", "renamed_count": 0}

        staged: list[Path] = []
        token = f".atr_raw_depth_normalize.{os.getpid()}.{time.time_ns()}"
        try:
            for order, (_, source_path) in enumerate(indexed_files):
                temp_path = camera_dir / f"{token}.{order:06d}.tmp"
                source_path.rename(temp_path)
                staged.append(temp_path)
            for order, temp_path in enumerate(staged):
                temp_path.rename(camera_dir / f"frame_{order:06d}.png")
        except OSError as exc:
            raise ValueError(f"Raw depth index normalization failed for {camera_dir}: {exc}") from exc
        return {**result_base, "status": "normalized", "renamed_count": len(indexed_files)}

    @staticmethod
    def _dataset_isaac_augmentation_summary_path(dataset_path: Path) -> Path:
        return dataset_path / "sidecar" / "isaac_augmentation" / "latest" / "summary.json"

    def _read_latest_isaac_augmentation_summary(self, dataset_path: Path) -> dict[str, Any]:
        summary_path = self._dataset_isaac_augmentation_summary_path(dataset_path)
        if not summary_path.is_file():
            return {"available": False, "summary_path": str(summary_path), "variant_count": 0}
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "available": False,
                "summary_path": str(summary_path),
                "variant_count": 0,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        summary = loaded if isinstance(loaded, dict) else {}
        variant_count = _safe_int(summary.get("variant_count"), 0, minimum=0)
        valid_variant_count = _safe_int(summary.get("valid_variant_count"), variant_count, minimum=0)
        failed_variant_count = _safe_int(summary.get("failed_variant_count"), max(0, variant_count - valid_variant_count), minimum=0)
        return {
            **summary,
            "available": bool(summary.get("ok", True)),
            "summary_path": str(summary_path),
            "manifest_path": str(summary.get("manifest_path") or summary_path.parent / "manifest.jsonl"),
            "qa_summary_path": str(summary.get("qa_summary_path") or summary_path.parent / "qa_summary.json"),
            "variant_count": variant_count,
            "valid_variant_count": valid_variant_count,
            "failed_variant_count": failed_variant_count,
            "source_frame_count": _safe_int(summary.get("source_frame_count"), 0, minimum=0),
        }

    @staticmethod
    def _dataset_isaac_lab_synthetic_root(dataset_path: Path) -> Path:
        return dataset_path / "sidecar" / "isaac_lab_synthetic" / "latest"

    def _read_latest_isaac_lab_synthetic_summary(self, dataset_path: Path) -> dict[str, Any]:
        output_root = self._dataset_isaac_lab_synthetic_root(dataset_path)
        summary_path = output_root / "summary.json"
        training_summary_path = output_root / "training_import" / "summary.json"
        manifest_path = output_root / "training_import" / "manifest.jsonl"
        try:
            run_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            run_summary = {"error": f"{exc.__class__.__name__}: {exc}"}
        if not isinstance(run_summary, dict):
            run_summary = {}
        try:
            training_summary = json.loads(training_summary_path.read_text(encoding="utf-8")) if training_summary_path.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            training_summary = {"error": f"{exc.__class__.__name__}: {exc}"}
        if not isinstance(training_summary, dict):
            training_summary = {}
        if isinstance(training_summary.get("manifest_path"), str) and str(training_summary["manifest_path"]).strip():
            manifest_path = Path(str(training_summary["manifest_path"])).expanduser()
        source_counts = training_summary.get("source_counts") if isinstance(training_summary.get("source_counts"), dict) else {}
        if not source_counts and manifest_path.is_file():
            inferred_counts: dict[str, int] = {}
            for row in self._read_jsonl_file(manifest_path):
                source_type = str(row.get("source_type") or "isaac_lab_synthetic")
                inferred_counts[source_type] = inferred_counts.get(source_type, 0) + 1
            source_counts = inferred_counts
        row_count = _safe_int(training_summary.get("row_count"), 0, minimum=0)
        if row_count <= 0 and source_counts:
            row_count = sum(_safe_int(value, 0, minimum=0) for value in source_counts.values())
        if not source_counts and row_count > 0:
            source_counts = {"isaac_lab_synthetic": row_count}
        lab_synthetic_sources = {
            "isaac_lab_synthetic",
            "isaac_lab_mimic",
            "isaac_lab_mimic_rgbd",
            "isaac_lab_rl_teacher",
        }
        synthetic_row_count = sum(
            _safe_int(value, 0, minimum=0)
            for source_type, value in source_counts.items()
            if str(source_type) in lab_synthetic_sources
        )
        return {
            "available": bool(training_summary_path.is_file() and manifest_path.is_file() and synthetic_row_count > 0),
            "schema": str(training_summary.get("schema") or "atr.lerobot.training_import.summary.v1"),
            "status": str(training_summary.get("status") or run_summary.get("status") or "missing"),
            "output_root": str(output_root),
            "summary_path": str(summary_path),
            "training_import_summary_path": str(training_summary_path),
            "training_import_manifest_path": str(manifest_path),
            "row_count": row_count,
            "synthetic_row_count": synthetic_row_count,
            "source_counts": dict(source_counts),
            "run_summary": run_summary if isinstance(run_summary, dict) else {},
            "training_import": training_summary if isinstance(training_summary, dict) else {},
        }

    def _train_isaac_augmentation_qa_preflight(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        summary = self._read_latest_isaac_augmentation_summary(dataset_path)
        if not summary.get("available"):
            return {"blocked": False, "trace": [], "summary": summary}
        variant_count = _safe_int(summary.get("variant_count"), 0, minimum=0)
        valid_variant_count = _safe_int(summary.get("valid_variant_count"), variant_count, minimum=0)
        failed_variant_count = _safe_int(summary.get("failed_variant_count"), max(0, variant_count - valid_variant_count), minimum=0)
        failure_counts = summary.get("qa_failure_counts") if isinstance(summary.get("qa_failure_counts"), dict) else {}
        if variant_count > 0 and valid_variant_count <= 0:
            return {
                "blocked": True,
                "summary": summary,
                "message": (
                    f"Isaac augmentation QA has 0 valid Isaac augmentation variants "
                    f"out of {variant_count}; failures={failure_counts or failed_variant_count}."
                ),
                "trace": [],
            }
        if failed_variant_count > 0:
            detail = (
                f"valid={valid_variant_count} failed={failed_variant_count} "
                f"manifest={summary.get('manifest_path', '')} failures={failure_counts}"
            )
            return {
                "blocked": False,
                "summary": summary,
                "trace": [("ISAAC_AUGMENTATION_QA", "warning", detail)],
            }
        return {"blocked": False, "trace": [], "summary": summary}

    def _write_latest_isaac_augmentation_metadata(self, dataset_path: Path, summary: dict[str, Any]) -> None:
        metadata_path = self._dataset_pipeline_metadata_path(dataset_path)
        try:
            if metadata_path.is_file():
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata = loaded if isinstance(loaded, dict) else {}
            else:
                metadata = {}
            metadata["isaac_data_augmentation"] = {
                "available": bool(summary.get("ok")),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "summary_path": str(summary.get("summary_path") or self._dataset_isaac_augmentation_summary_path(dataset_path)),
                "manifest_path": str(summary.get("manifest_path") or ""),
                "output_dir": str(summary.get("output_dir") or ""),
                "variant_count": _safe_int(summary.get("variant_count"), 0, minimum=0),
                "source_frame_count": _safe_int(summary.get("source_frame_count"), 0, minimum=0),
                "common_augmentation_families": list(summary.get("common_augmentation_families") or []),
            }
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            return None

    def _isaac_lab_synthetic_request(self, payload: dict[str, Any] | None = None) -> IsaacLabSyntheticRequest:
        """Normalize LeRobot GUI payloads into the Isaac Lab synthetic request contract."""
        data = dict(payload or {})
        if not str(data.get("dataset_path") or "").strip():
            session_request = LeRobotSessionRequest.model_validate(data)
            data["dataset_path"] = self._dataset_path_for(session_request)
        if data.get("fallback_policy") == "legacy_only":
            data["pipeline_mode"] = "legacy_sidecar"
        if data.get("pipeline_mode") == "legacy_sidecar":
            data.setdefault("enable_replicator", False)
            data.setdefault("enable_mimic", False)
            data.setdefault("enable_rl_teacher", False)
        return IsaacLabSyntheticRequest.model_validate(data)

    def _isaac_lab_synthetic_pipeline(self) -> IsaacLabSyntheticPipeline:
        """Return the non-actuating Isaac Lab synthetic pipeline helper."""
        return IsaacLabSyntheticPipeline(repo_root=self.config.repo_root, allowed_roots=self._allowed_roots())

    def _read_dataset_pipeline_metadata(self, dataset_path: Path) -> dict[str, Any]:
        """Read ATR dataset pipeline metadata, or infer a conservative display-only value."""
        metadata_path = self._dataset_pipeline_metadata_path(dataset_path)
        if metadata_path.is_file():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                data = {}
            pipeline_id = _normalize_observation_pipeline_id(data.get("observation_pipeline_id"), self.config.default_observation_pipeline_id)
            return {
                **data,
                "exists": True,
                "source": "metadata",
                "path": str(metadata_path),
                "observation_pipeline_id": pipeline_id,
                "profile_id": str(data.get("profile_id") or ""),
            }
        inferred = "rgbd_sidecar" if self._dataset_raw_depth_manifest_path(dataset_path).is_file() else "legacy_lerobot"
        return {
            "exists": False,
            "source": "inferred_sidecar" if inferred == "rgbd_sidecar" else "inferred_legacy",
            "path": str(metadata_path),
            "observation_pipeline_id": inferred,
            "profile_id": "",
        }

    def _dataset_pipeline_block_if_needed(self, tool: str, mode: str, profile: RobotProfile, request: LeRobotSessionRequest, workflow: str) -> dict[str, Any] | None:
        """Block explicit train/rollout requests that conflict with dataset pipeline metadata."""
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        metadata = self._read_dataset_pipeline_metadata(dataset_path)
        requested = self._request_observation_pipeline_id(request, profile)
        recorded = _normalize_observation_pipeline_id(metadata.get("observation_pipeline_id"), requested)
        if metadata.get("source") == "metadata" and recorded != requested:
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_OBSERVATION_PIPELINE_MISMATCH",
                f"Selected pipeline '{requested}' does not match dataset metadata '{recorded}' at {metadata.get('path')}.",
                workflow,
            )
        should_validate_raw_depth = bool(
            requested == "raw_depth_adapter"
            and workflow in {"train", "rollout"}
            and (mode == "live" or bool(str(request.dataset_path or "").strip()) or self._is_trainable_lerobot_dataset(dataset_path))
        )
        if should_validate_raw_depth:
            raw_depth = self._dataset_raw_depth_health(dataset_path)
            if not raw_depth.get("available"):
                return self._blocked(
                    tool,
                    mode,
                    profile.profile_id,
                    "LEROBOT_RAW_DEPTH_ADAPTER_SOURCE_MISSING",
                    f"Raw Depth Adapter requires {raw_depth.get('manifest_path')}.",
                    workflow,
                )
            camera_counts = raw_depth.get("camera_counts") if isinstance(raw_depth.get("camera_counts"), dict) else {}
            missing_cameras = [str(camera) for camera, count in camera_counts.items() if _safe_int(count, 0, minimum=0) <= 0]
            if _safe_int(raw_depth.get("total_frame_count"), 0, minimum=0) <= 0 or missing_cameras:
                detail = f" missing cameras={','.join(missing_cameras)}" if missing_cameras else ""
                return self._blocked(
                    tool,
                    mode,
                    profile.profile_id,
                    "LEROBOT_RAW_DEPTH_FRAMES_MISSING",
                    f"Raw Depth Adapter requires uint16 PNG frames under {Path(str(raw_depth.get('manifest_path'))).parent}.{detail}",
                    workflow,
                )
        return None

    def _expected_record_depth_features(self, profile: RobotProfile, request: LeRobotSessionRequest) -> list[str]:
        if not request.camera_enabled:
            return []
        expected: list[str] = []
        for camera_key in self._profile_camera_keys(profile):
            camera_device = self._saved_camera_device(profile.profile_id, camera_key)
            backend = self._normalize_camera_backend((camera_device or {}).get("backend", "opencv"))
            if backend == LEROBOT_REALSENSE_TYPE and self._camera_use_depth(camera_device or {}, default=True):
                expected.append(f"observation.images.{camera_key}_depth")
        return expected

    def _record_depth_validation(self, session: dict[str, Any]) -> dict[str, Any] | None:
        if str(session.get("workflow") or "").lower() != "record":
            return None
        expected = [str(item) for item in session.get("expected_depth_features", []) if str(item).strip()]
        if not expected:
            return None

        dataset_path = Path(str(session.get("dataset_path") or "")).expanduser()
        info_path = dataset_path / "meta" / "info.json"
        terminal = str(session.get("status") or "").upper() in {"COMPLETED", "FAILED", "STOPPED", "CANCELLED"}
        if not info_path.is_file():
            status = "failed" if terminal else "waiting"
            return {
                "required": True,
                "status": status,
                "dataset_path": str(dataset_path),
                "expected_depth_features": expected,
                "present_depth_features": [],
                "missing_depth_features": expected,
                "message": f"Waiting for LeRobot dataset metadata at {info_path}."
                if status == "waiting"
                else f"LeRobot dataset metadata was not written at {info_path}.",
            }

        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as exc:
            status = "failed" if terminal else "waiting"
            return {
                "required": True,
                "status": status,
                "dataset_path": str(dataset_path),
                "expected_depth_features": expected,
                "present_depth_features": [],
                "missing_depth_features": expected,
                "message": f"Could not read LeRobot dataset metadata: {exc.__class__.__name__}: {exc}",
            }

        features = info.get("features") if isinstance(info, dict) else {}
        if not isinstance(features, dict):
            features = {}
        present_depth = sorted(key for key in features if str(key).startswith("observation.images.") and "depth" in str(key))
        missing = [key for key in expected if key not in features]
        if missing:
            status = "failed" if terminal else "waiting"
            return {
                "required": True,
                "status": status,
                "dataset_path": str(dataset_path),
                "expected_depth_features": expected,
                "present_depth_features": present_depth,
                "missing_depth_features": missing,
                "message": "RealSense depth was requested, but the recorded LeRobot dataset does not expose "
                f"the expected depth feature(s): {', '.join(missing)}.",
            }

        return {
            "required": True,
            "status": "ok",
            "dataset_path": str(dataset_path),
            "expected_depth_features": expected,
            "present_depth_features": present_depth,
            "missing_depth_features": [],
            "message": "Recorded LeRobot dataset exposes the expected RealSense depth visual features.",
        }

    def _record_raw_depth_sidecar(self, profile: RobotProfile, request: LeRobotSessionRequest) -> dict[str, Any]:
        pipeline_id = self._request_observation_pipeline_id(request, profile)
        pipeline = LEROBOT_OBSERVATION_PIPELINES[pipeline_id]
        if not bool(pipeline.get("raw_depth_sidecar")):
            return {
                "enabled": False,
                "root": "",
                "expected_camera_keys": [],
                "format": "png16",
                "pipeline_id": pipeline_id,
            }
        camera_keys = self._record_raw_depth_camera_keys(profile, request)
        if not camera_keys:
            return {"enabled": False, "root": "", "expected_camera_keys": [], "format": "png16", "pipeline_id": pipeline_id}
        root = Path(self._dataset_path_for(request)).expanduser() / "sidecar" / "depth_raw"
        camera_depth_scales = self._record_raw_depth_camera_scale_map(profile, camera_keys)
        camera_depth_clips = self._record_raw_depth_camera_clip_map(camera_keys)
        return {
            "enabled": True,
            "root": str(root),
            "expected_camera_keys": camera_keys,
            "format": "png16",
            "pipeline_id": pipeline_id,
            "aligned_to": "color" if self.config.realsense_depth_align_to_color else "native_depth",
            "depth_scale_m_per_unit": self.config.realsense_depth_scale_m_per_unit,
            "camera_depth_scale_m_per_unit": camera_depth_scales,
            "depth_clip_min_mm": self.config.realsense_depth_clip_min_mm,
            "depth_clip_max_mm": self.config.realsense_depth_clip_max_mm,
            "camera_depth_clip_mm": camera_depth_clips,
        }

    def _record_raw_depth_camera_scale_map(self, profile: RobotProfile, camera_keys: list[str]) -> dict[str, float]:
        scales: dict[str, float] = {}
        for camera_key in camera_keys:
            camera_device = self._saved_camera_device(profile.profile_id, camera_key)
            identifier = str((camera_device or {}).get("serial_number_or_name") or (camera_device or {}).get("port") or "").strip()
            scales[camera_key] = self._realsense_depth_scale_m_per_unit(camera_key, identifier, camera_device or {})
        return scales

    def _record_raw_depth_camera_clip_map(self, camera_keys: list[str]) -> dict[str, dict[str, float]]:
        clips: dict[str, dict[str, float]] = {}
        global_min = float(self.config.realsense_depth_clip_min_mm)
        global_max = float(self.config.realsense_depth_clip_max_mm)
        for camera_key in camera_keys:
            clip_min, clip_max = self._realsense_depth_clip_range_mm(camera_key)
            if abs(clip_min - global_min) > 1e-9 or abs(clip_max - global_max) > 1e-9:
                clips[camera_key] = {"min_mm": clip_min, "max_mm": clip_max}
        return clips

    def _record_raw_depth_camera_keys(self, profile: RobotProfile | None, request: LeRobotSessionRequest) -> list[str]:
        if profile is None or not request.camera_enabled:
            return []
        keys: list[str] = []
        for camera_key in self._profile_camera_keys(profile):
            camera_device = self._saved_camera_device(profile.profile_id, camera_key)
            backend = self._normalize_camera_backend((camera_device or {}).get("backend", "opencv"))
            if backend == LEROBOT_REALSENSE_TYPE and self._camera_use_depth(camera_device or {}, default=True):
                keys.append(camera_key)
        return sorted(dict.fromkeys(keys))

    @staticmethod
    def _record_raw_depth_sidecar_status(sidecar: dict[str, Any]) -> dict[str, Any]:
        root = Path(str(sidecar.get("root") or "")).expanduser()
        camera_keys = [str(item) for item in sidecar.get("expected_camera_keys", []) if str(item).strip()]
        file_counts: dict[str, int] = {}
        for camera_key in camera_keys:
            camera_dir = root / camera_key
            try:
                file_counts[camera_key] = LeRobotBridge._raw_depth_camera_frame_count(camera_dir)
            except OSError:
                file_counts[camera_key] = 0
        missing = [key for key, count in file_counts.items() if count <= 0]
        status = "disabled"
        if sidecar.get("enabled"):
            status = "ok" if file_counts and not missing else "waiting"
        return {
            **sidecar,
            "status": status,
            "file_counts": file_counts,
            "missing_camera_keys": missing,
        }

    def _runtime_status_from_log(self, session: dict[str, Any], log_tail: str) -> dict[str, Any]:
        """Summarize live LeRobot process state from its persisted session log."""
        if (
            bool(session.get("virtual_bridge_simulation"))
            and str(session.get("mode") or "") != "live"
            and str(session.get("workflow") or "").lower() == "rollout"
        ):
            return {
                "phase": "ACTION_ACTIVE",
                "message": "Virtual bridge rollout completed with simulated action evidence.",
                "action_count": 30,
                "max_abs_delta": 0.0,
                "warnings": [],
                "log_path": "",
                "pid": None,
                "returncode": 0,
            }
        status = str(session.get("status") or "").upper()
        returncode = session.get("returncode")
        text = str(log_tail or "")
        phase = "PROCESS_STARTED" if session.get("pid") else "NOT_STARTED"
        message = "Process has been requested."
        warnings: list[str] = []
        if "Using device:" in text:
            phase = "LOADING_POLICY"
            message = "Loading policy model on compute device."
        if "Loading model from:" in text:
            phase = "LOADING_CHECKPOINT"
            message = "Loading policy checkpoint."
        if "Loaded state dict" in text:
            phase = "CHECKPOINT_LOADED"
            message = "Policy checkpoint loaded; preparing robot runtime."
        if "Missing key(s)" in text:
            warnings.append("checkpoint_key_mismatch_warning")
        if "Initializing robot:" in text:
            phase = "INITIALIZING_ROBOT"
            message = "Connecting robot and cameras."
        if "OpenCVCamera" in text and " connected" in text:
            phase = "CAMERA_CONNECTED"
            message = "Camera stream connected; waiting for follower/actor."
        if "OmxFollower connected" in text:
            phase = "ROBOT_CONNECTED"
            message = "Follower robot connected; starting action threads."
        if "Started actor thread" in text:
            phase = "ACTOR_READY"
            message = "Actor thread ready; waiting for policy actions."
        if "Preprocessor/postprocessor loaded successfully" in text:
            phase = "POLICY_PREPROCESSOR_READY"
            message = "Policy pre/post processors loaded; action inference active."
        action_matches = list(re.finditer(r"\[ATR_ACTION\]\s+count=(\d+)\s+max_abs_delta=([0-9.+-]+)", text))
        action_count = 0
        max_abs_delta = None
        if action_matches:
            last = action_matches[-1]
            action_count = int(last.group(1))
            try:
                max_abs_delta = float(last.group(2))
            except ValueError:
                max_abs_delta = None
            phase = "ACTION_ACTIVE"
            delta_text = f" max_delta={max_abs_delta:.3f}" if max_abs_delta is not None else ""
            message = f"Robot action stream active: {action_count} actions sent.{delta_text}"
        if "Relative goal position magnitude had to be clamped" in text:
            warnings.append("safe_action_clamp_active")
        if "ACTION_QUEUE" in text:
            warnings.append("rtc_action_queue_timing_warning")
        if "Actor thread shutting down" in text:
            count_match = re.search(r"Total actions executed:\s*(\d+)", text)
            if count_match:
                action_count = int(count_match.group(1))
            phase = "ACTION_STOPPED"
            message = f"Actor stopped after {action_count} actions."
        workflow = str(session.get("workflow") or "").lower()
        workflow_label = "training" if workflow == "train" else "rollout" if workflow == "rollout" else workflow or "runtime"
        if "RTC demo finished" in text or (returncode == 0 and status == "COMPLETED"):
            phase = "COMPLETED"
            if workflow == "rollout":
                message = "RTC rollout completed and robot disconnected."
            elif workflow == "train":
                message = "Training completed successfully."
            else:
                message = f"{workflow_label.capitalize()} completed successfully."
        if status in {"STOPPED", "CANCELLED"}:
            phase = "STOPPED"
            if workflow == "rollout":
                message = f"Rollout stopped by operator/system after {action_count} actions."
            else:
                message = f"{workflow_label.capitalize()} stopped by operator/system."
        if "Fatal exception" in text or "Traceback" in text or status == "FAILED":
            phase = "FAILED"
            message = f"{workflow_label.capitalize()} failed; inspect log_tail for the stack trace."
            preflight_match = re.search(r"RecordStartPreflightError:\s*([A-Z0-9_]+)", text)
            if preflight_match:
                warnings.append("record_start_preflight_failed")
                failure_code = preflight_match.group(1)
                if failure_code == "SPECIMEN_OUTSIDE_A4":
                    message = "Record start blocked: detected specimen is outside the A4 workspace."
                else:
                    message = f"Record start blocked by preflight check: {failure_code}."
        return {
            "phase": phase,
            "message": message,
            "action_count": action_count,
            "max_abs_delta": max_abs_delta,
            "warnings": sorted(set(warnings)),
            "log_path": session.get("log_path", ""),
            "pid": session.get("pid"),
            "returncode": returncode,
        }

    def _training_progress(self, session: dict[str, Any]) -> dict[str, Any]:
        """Infer training progress/ETA from config, process status, and log tail."""
        if session.get("workflow") != "train":
            return {}
        config = dict(session.get("train_config") or {})
        total_steps = int(config.get("steps") or 0)
        log_tail = self._tail_file(str(session.get("log_path", "")), max_chars=20000)
        current_step, detected_total = self._parse_training_step(log_tail)
        if detected_total:
            total_steps = detected_total
        sample_count = self._parse_training_sample_count(log_tail)
        effective_batch_size = self._parse_training_effective_batch_size(log_tail, int(config.get("batch_size") or 0))
        if sample_count > 0 and effective_batch_size > 0:
            current_step = max(current_step, int(round(sample_count / effective_batch_size)))
        status = str(session.get("status") or "").upper()
        synthetic_complete = status == "COMPLETED" and not log_tail and bool(total_steps)
        if status == "COMPLETED" and total_steps:
            current_step = total_steps
        progress_percent = round((current_step / total_steps) * 100.0, 2) if total_steps else (100.0 if status == "COMPLETED" else 0.0)
        progress_percent = max(0.0, min(100.0, progress_percent))
        elapsed_sec = self._session_elapsed_sec(session)
        active_rate = self._parse_training_steps_per_sec(log_tail)
        steps_per_sec = (
            0.0
            if synthetic_complete
            else round(active_rate, 4)
            if active_rate > 0
            else round(current_step / elapsed_sec, 4)
            if current_step > 0 and elapsed_sec > 0
            else 0.0
        )
        eta_sec: float | None = None
        if steps_per_sec > 0 and total_steps and current_step < total_steps and status not in {"COMPLETED", "FAILED", "CANCELLED"}:
            eta_sec = round((total_steps - current_step) / steps_per_sec, 1)
        return {
            "status": session.get("status", ""),
            "current_step": current_step,
            "total_steps": total_steps,
            "progress_percent": progress_percent,
            "elapsed_sec": round(elapsed_sec, 1),
            "eta_sec": eta_sec,
            "steps_per_sec": steps_per_sec,
            "last_loss": 0.123 if synthetic_complete else self._parse_training_loss(log_tail),
            "config": config,
        }

    @staticmethod
    def _parse_training_step(log: str) -> tuple[int, int | None]:
        current = 0
        total: int | None = None
        count_pattern = r"(\d{1,9}(?:\.\d+)?)([kKmM]?)"
        for match in re.finditer(rf"(?<![\d.]){count_pattern}\s*/\s*{count_pattern}(?![\d.])", log):
            parsed_current = LeRobotBridge._parse_training_count(match.group(1), match.group(2))
            parsed_total = LeRobotBridge._parse_training_count(match.group(3), match.group(4))
            current = max(current, parsed_current)
            total = max(total or 0, parsed_total)
        for line in log.splitlines():
            if "cfg.steps" in line:
                continue
            match = re.search(rf"\b(?:step|global_step)\s*[=:]\s*{count_pattern}", line, flags=re.IGNORECASE)
            if match:
                current = max(current, LeRobotBridge._parse_training_count(match.group(1), match.group(2)))
        return current, total

    @staticmethod
    def _parse_training_count(value: str, suffix: str = "") -> int:
        multiplier = 1
        clean_suffix = str(suffix or "").lower()
        if clean_suffix == "k":
            multiplier = 1_000
        elif clean_suffix == "m":
            multiplier = 1_000_000
        try:
            return int(round(float(value) * multiplier))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_training_sample_count(log: str) -> int:
        samples = 0
        count_pattern = r"(\d{1,9}(?:\.\d+)?)([kKmM]?)"
        for line in log.splitlines():
            match = re.search(rf"\b(?:smpl|samples|sample)\s*[=:]\s*{count_pattern}", line, flags=re.IGNORECASE)
            if match:
                samples = max(samples, LeRobotBridge._parse_training_count(match.group(1), match.group(2)))
        return samples

    @staticmethod
    def _parse_training_effective_batch_size(log: str, fallback: int = 0) -> int:
        for line in reversed(log.splitlines()):
            match = re.search(r"\bEffective batch size:\s*\d+\s*x\s*\d+\s*=\s*(\d+)\b", line, flags=re.IGNORECASE)
            if match:
                return _safe_int(match.group(1), fallback, minimum=1)
        return max(0, int(fallback or 0))

    @staticmethod
    def _parse_training_loss(log: str) -> float | None:
        matches = list(re.finditer(r"(?:loss|train_loss|l1_loss)\s*[=:]\s*([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)", log, flags=re.IGNORECASE))
        if not matches:
            return None
        try:
            return float(matches[-1].group(1))
        except ValueError:
            return None

    @staticmethod
    def _parse_training_steps_per_sec(log: str) -> float:
        """Estimate active training throughput without counting model/dataset startup time."""
        step_records: list[tuple[int, datetime | None]] = []
        step_durations: list[float] = []
        count_pattern = r"(\d{1,9}(?:\.\d+)?)([kKmM]?)"
        for line in log.splitlines():
            if "cfg.steps" in line:
                continue
            step_match = re.search(rf"\b(?:step|global_step)\s*[=:]\s*{count_pattern}", line, flags=re.IGNORECASE)
            if not step_match:
                continue
            step = LeRobotBridge._parse_training_count(step_match.group(1), step_match.group(2))
            if step <= 0:
                continue
            timestamp = LeRobotBridge._parse_training_log_timestamp(line)
            step_records.append((step, timestamp))
            duration_parts = []
            for key in ("updt_s", "data_s"):
                match = re.search(rf"\b{key}\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)", line, flags=re.IGNORECASE)
                if match:
                    try:
                        duration_parts.append(float(match.group(1)))
                    except ValueError:
                        pass
            duration = sum(duration_parts)
            if duration > 0:
                step_durations.append(duration)
        rates: list[float] = []
        timestamped = [(step, timestamp) for step, timestamp in step_records if timestamp is not None]
        if len(timestamped) >= 2:
            first_step, first_timestamp = timestamped[0]
            last_step, last_timestamp = timestamped[-1]
            elapsed = max(0.0, (last_timestamp - first_timestamp).total_seconds())
            step_delta = max(0, last_step - first_step)
            if elapsed > 0 and step_delta > 0:
                rates.append(step_delta / elapsed)
        if step_durations:
            recent = step_durations[-10:]
            avg_duration = sum(recent) / len(recent)
            if avg_duration > 0:
                rates.append(1.0 / avg_duration)
        return max(rates) if rates else 0.0

    @staticmethod
    def _parse_training_log_timestamp(line: str) -> datetime | None:
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\b", line)
        if not match:
            return None
        try:
            return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _session_elapsed_sec(session: dict[str, Any]) -> float:
        try:
            created = datetime.fromisoformat(str(session.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())

    def _resolve_session(self, session_id: str, workflow: str, *, prefer_active: bool = False) -> dict[str, Any] | None:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if session.get("workflow") != workflow:
                active = self._latest_active_session(workflow) if prefer_active else None
                return active
            if not prefer_active or self._session_is_active(session):
                return session
            active = self._latest_active_session(workflow)
            return active or session
        if prefer_active:
            active = self._latest_active_session(workflow)
            if active is not None:
                return active
        for session in reversed(list(self._sessions.values())):
            if session.get("workflow") == workflow:
                return session
        return None

    def _latest_active_session(self, workflow: str) -> dict[str, Any] | None:
        for session in reversed(list(self._sessions.values())):
            if session.get("workflow") == workflow and self._session_is_active(session):
                return session
        return None

    def _session_is_active(self, session: dict[str, Any]) -> bool:
        self._refresh_process_status(session)
        status = str(session.get("status", "")).upper()
        terminal = {"STOPPED", "FAILED", "COMPLETED", "CANCELLED", "DATASET_COMPLETE"}
        return status not in terminal and session.get("returncode") is None

    def _profiles(self) -> list[RobotProfile]:
        return [RobotProfile.model_validate(profile) for profile in self.config.profiles.values()]

    def _profile(self, profile_id: str | None) -> RobotProfile | None:
        clean = str(profile_id or "").strip() or self._selected_profile_id or self.config.default_profile_id
        if clean not in self.config.profiles:
            clean = self.config.default_profile_id
        raw = self.config.profiles.get(clean)
        return RobotProfile.model_validate(raw) if raw else None

    @staticmethod
    def _public_profile(profile: RobotProfile) -> dict[str, Any]:
        data = profile.model_dump()
        data["observation_pipeline_id"] = _normalize_observation_pipeline_id(
            data.get("observation_pipeline_id") or LEROBOT_DEFAULT_OBSERVATION_PIPELINE_ID
        )
        data["live_gate_summary"] = LeRobotBridge._live_gate_summary(profile)
        return data

    @staticmethod
    def _observation_pipeline_options() -> list[dict[str, Any]]:
        """Return stable GUI choices for RGB-D dataset handling."""
        return [dict(item) for item in LEROBOT_OBSERVATION_PIPELINES.values()]

    def _request_observation_pipeline_id(self, request: Any, profile: RobotProfile | None = None) -> str:
        """Resolve the effective observation pipeline for a request/profile."""
        if isinstance(request, dict):
            requested = request.get("observation_pipeline_id")
        else:
            requested = getattr(request, "observation_pipeline_id", "")
        if requested:
            return _normalize_observation_pipeline_id(requested, self._selected_observation_pipeline_id)
        if profile and profile.observation_pipeline_id:
            return _normalize_observation_pipeline_id(profile.observation_pipeline_id, self.config.default_observation_pipeline_id)
        return _normalize_observation_pipeline_id(self._selected_observation_pipeline_id or self.config.default_observation_pipeline_id)

    def _public_session(self, session: dict[str, Any]) -> dict[str, Any]:
        self._refresh_in_process_isaac_mirror_progress(session)
        post_render = self._current_isaac_rgbd_post_render_for_session(session)
        if post_render:
            session["isaac_rgbd_post_render"] = post_render
        log_tail = self._tail_file(str(session.get("log_path", "")))
        runtime = self._runtime_status_from_log(session, log_tail)
        training = self._training_progress(session)
        public = {
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "profile_id": session.get("profile_id", ""),
            "observation_pipeline_id": session.get("observation_pipeline_id", ""),
            "mode": session.get("mode", ""),
            "status": session.get("status", ""),
            "runtime": runtime,
            "runtime_phase": runtime.get("phase"),
            "runtime_message": runtime.get("message"),
            "created_at": session.get("created_at", ""),
            "command_preview": list(session.get("command_preview", [])),
            "dataset_path": session.get("dataset_path", ""),
            "checkpoint_path": session.get("checkpoint_path", ""),
            "log_path": session.get("log_path", ""),
            "log_tail": log_tail,
            "pid": session.get("pid"),
            "returncode": session.get("returncode"),
            "training": {**dict(session.get("train_config", {})), **dict(training or {})},
            "monitor": session.get("monitor", {}),
            "visualization": session.get("visualization", {}),
        }
        if str(session.get("workflow") or "").lower() == "isaac_mirror":
            public.update(
                {
                    "mirror_endpoint": session.get("mirror_endpoint", ""),
                    "mirror_sample_hz": session.get("mirror_sample_hz", 0),
                    "mirror_record_path": session.get("mirror_record_path", ""),
                    "attached_to_session_id": session.get("attached_to_session_id", ""),
                    "sample_count": session.get("sample_count", 0),
                }
            )
        if isinstance(session.get("isaac_mirror"), dict):
            public["isaac_mirror"] = dict(session["isaac_mirror"])
            public["isaac_mirror_session_id"] = session.get("isaac_mirror_session_id", "")
        if isinstance(session.get("active_robot_cam"), dict):
            public["active_robot_cam"] = dict(session["active_robot_cam"])
        if isinstance(session.get("record_attempt"), dict):
            public["record_attempt"] = dict(session["record_attempt"])
        if isinstance(session.get("record_attempts"), dict):
            public["record_attempts"] = dict(session["record_attempts"])
        if isinstance(session.get("isaac_rgbd_post_render"), dict):
            public["isaac_rgbd_post_render"] = dict(session["isaac_rgbd_post_render"])
        return public

    @staticmethod
    def _live_gate_summary(profile: RobotProfile | None) -> dict[str, Any]:
        limits = dict(profile.safety_limits if profile else {})
        return {
            "live_enabled": bool(limits.get("live_enabled", False)),
            "allow_teleoperation": bool(limits.get("allow_teleoperation", False)),
            "allow_recording": bool(limits.get("allow_recording", False)),
            "allow_training": bool(limits.get("allow_training", False)),
            "allow_policy_rollout": bool(limits.get("allow_policy_rollout", False)),
            "require_operator_confirm": bool(limits.get("require_operator_confirm", True)),
        }

    def _live_block_if_needed(
        self,
        *,
        tool: str,
        mode: str,
        profile: RobotProfile,
        workflow: str,
        allow_key: str,
    ) -> dict[str, Any] | None:
        if mode != "live":
            return None
        limits = dict(profile.safety_limits)
        if not bool(limits.get("live_enabled", False)):
            return self._blocked(tool, mode, profile.profile_id, "LEROBOT_LIVE_GATE_DISABLED", "Live robot execution is disabled for the selected profile.", workflow)
        if allow_key and not bool(limits.get(allow_key, False)):
            return self._blocked(tool, mode, profile.profile_id, "LEROBOT_WORKFLOW_GATE_DISABLED", f"Live workflow gate disabled: {allow_key}", workflow)
        return None

    def _live_port_block_if_needed(self, *, tool: str, mode: str, profile: RobotProfile, workflow: str) -> dict[str, Any] | None:
        if mode != "live" or workflow not in {"teleoperate", "record", "rollout"}:
            return None
        missing: list[str] = []
        unavailable: list[str] = []
        required_roles = ["follower"]
        if workflow in {"teleoperate", "record"}:
            required_roles.append("leader")
        for role in required_roles:
            port = self._device_port(profile, role, allow_fake=False)
            if not port:
                missing.append(role)
            elif not self._device_port_available(port):
                unavailable.append(f"{role}={port}")
        if not missing:
            if not unavailable:
                return None
            blocked = self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_DEVICE_PORT_UNAVAILABLE",
                f"Saved LeRobot device ports are not present: {', '.join(unavailable)}. Reconnect the robot or rerun port detection.",
                workflow,
            )
            blocked["port_lease"] = {
                "schema": "atr.lerobot.port_lease.v1",
                "status": "blocked",
                "profile_id": profile.profile_id,
                "workflow": workflow,
                "follower_port": self._device_port(profile, "follower", allow_fake=False),
                "leader_port": self._device_port(profile, "leader", allow_fake=False),
                "current_availability": "unavailable",
                "occupant_process": "",
                "reclaim_status": "not_attempted",
                "unavailable_roles": [item.split("=", 1)[0] for item in unavailable],
                "missing_roles": [],
            }
            return blocked
        blocked = self._blocked(
            tool,
            mode,
            profile.profile_id,
            "LEROBOT_DEVICE_PORT_REQUIRED",
            f"Save required LeRobot device ports before live {workflow}: {', '.join(missing)}.",
            workflow,
        )
        blocked["port_lease"] = {
            "schema": "atr.lerobot.port_lease.v1",
            "status": "blocked",
            "profile_id": profile.profile_id,
            "workflow": workflow,
            "follower_port": self._device_port(profile, "follower", allow_fake=False),
            "leader_port": self._device_port(profile, "leader", allow_fake=False),
            "current_availability": "missing",
            "occupant_process": "",
            "reclaim_status": "not_attempted",
            "unavailable_roles": [],
            "missing_roles": list(missing),
        }
        return blocked

    def _live_camera_block_if_needed(
        self,
        *,
        tool: str,
        mode: str,
        profile: RobotProfile,
        workflow: str,
        request: LeRobotSessionRequest,
    ) -> dict[str, Any] | None:
        camera_required = bool(request.camera_enabled or self._uses_active_robot_cam(workflow, request))
        if mode != "live" or workflow not in {"teleoperate", "record", "rollout"} or not camera_required:
            return None
        missing: list[str] = []
        unavailable: list[str] = []
        realsense_entries: list[dict[str, str]] | None = None
        for camera_key in self._profile_camera_keys(profile):
            camera_port = self._device_port(profile, "camera", camera_key=camera_key, allow_fake=False)
            if not camera_port:
                missing.append(camera_key)
                continue
            saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
            backend = self._normalize_camera_backend(saved_camera.get("backend", "opencv"))
            if backend == LEROBOT_REALSENSE_TYPE:
                if realsense_entries is None:
                    realsense_entries = self._scan_live_realsense_camera_entries()
                identifier = str(saved_camera.get("serial_number_or_name") or camera_port).strip()
                if not self._realsense_identifier_available(identifier, realsense_entries):
                    unavailable.append(f"{camera_key}={identifier}")
                continue
            if not self._camera_port_available(camera_port):
                unavailable.append(f"{camera_key}={camera_port}")
        if missing:
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_CAMERA_PORT_REQUIRED",
                f"Save required LeRobot camera ports before live {workflow}: {', '.join(missing)}.",
                workflow,
            )
        if unavailable:
            visible = self._realsense_visible_summary(realsense_entries or []) if realsense_entries is not None else "opencv/v4l check"
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_REALSENSE_CAMERA_UNAVAILABLE",
                "Saved LeRobot cameras are not available: "
                f"{', '.join(unavailable)}; visible RealSense devices: {visible}. "
                "Reconnect the camera or rerun RealSense detect/save before starting live robot motion.",
                workflow,
            )
        return None

    def _blocked(self, tool: str, mode: str, profile_id: str, failure_code: str, message: str, workflow: str) -> dict[str, Any]:
        step_trace = [{"step": "PRECHECK", "status": "blocked", "detail": failure_code}]
        return {
            "ok": False,
            "tool": tool,
            "mode": mode,
            "profile_id": profile_id,
            "session_id": "",
            "workflow": workflow,
            "status": "blocked",
            "failure_code": failure_code,
            "message": message,
            "command_preview": [],
            "events": step_trace,
            "step_trace": step_trace,
            "error": message,
        }

    @staticmethod
    def _error(tool: str, mode: str, profile_id: str, failure_code: str, message: str) -> dict[str, Any]:
        step_trace = [{"step": "PRECHECK", "status": "failed", "detail": failure_code}]
        return {
            "ok": False,
            "tool": tool,
            "mode": mode,
            "profile_id": profile_id,
            "session_id": "",
            "status": "failed",
            "failure_code": failure_code,
            "message": message,
            "command_preview": [],
            "events": step_trace,
            "step_trace": step_trace,
            "error": message,
        }

    def _new_session_id(self, workflow: str) -> str:
        self._counter += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"lr-{workflow}-{stamp}-{self._counter:04d}"

    @staticmethod
    def _mode(payload: dict[str, Any]) -> str:
        return str(payload.get("runtime_mode") or payload.get("mode") or "test")

    @staticmethod
    def _fake_port(profile: RobotProfile, role: str) -> str:
        if role in {"robot", "follower"}:
            suffix = "FOLLOWER"
        elif role in {"teleop", "leader"}:
            suffix = "LEADER"
        else:
            suffix = "CAMERA0"
        family = profile.robot_family.upper().replace("-", "_")
        prefix = "/dev/video_FAKE" if suffix.startswith("CAMERA") else "/dev/ttyUSB_FAKE"
        return f"{prefix}_{family}_{suffix}"

    def _fake_camera_port(self, profile: RobotProfile, camera_key: str) -> str:
        family = profile.robot_family.upper().replace("-", "_")
        key = (camera_key or "camera").upper().replace("-", "_")
        return f"/dev/video_FAKE_{family}_{key}"

    def _device_port(self, profile: RobotProfile, role: str, *, camera_key: str = "", allow_fake: bool = True) -> str:
        saved = self._saved_devices(profile.profile_id).get(role, {})
        if role == "camera":
            key = camera_key or self._default_camera_key(profile)
            saved = self._saved_camera_device(profile.profile_id, key)
            saved_port = self._saved_device_identity_link(saved, "camera")
            if saved_port:
                return saved_port
            if profile.camera_ports.get(key, ""):
                return profile.camera_ports[key]
            return self._fake_camera_port(profile, key) if allow_fake else ""
        if isinstance(saved, dict):
            saved_port = self._saved_device_identity_link(saved, role)
            if saved_port:
                return saved_port
        if role in {"robot", "follower"}:
            return profile.robot_port or (self._fake_port(profile, "follower") if allow_fake else "")
        if role in {"teleop", "leader"}:
            return profile.teleop_port or (self._fake_port(profile, "leader") if allow_fake else "")
        return ""

    @staticmethod
    def _default_camera_keys(profile: RobotProfile) -> set[str]:
        return {"top", "wrist", *[str(key) for key in profile.camera_map.keys()]}

    def _profile_camera_keys(self, profile: RobotProfile) -> list[str]:
        keys = list(profile.camera_map.keys()) or list(profile.camera_ports.keys()) or ["top", "wrist"]
        if "top" not in keys:
            keys.insert(0, "top")
        if "wrist" not in keys:
            keys.append("wrist")
        return list(dict.fromkeys(str(key) for key in keys))

    def _default_camera_key(self, profile: RobotProfile) -> str:
        return self._profile_camera_keys(profile)[0]

    @staticmethod
    def _normalize_camera_backend(value: Any) -> str:
        raw = str(value or "opencv").strip().lower()
        return LEROBOT_REALSENSE_TYPE if raw in LEROBOT_REALSENSE_BACKENDS else "opencv"

    @staticmethod
    def _default_realsense_identifier(camera_key: str) -> str:
        key = str(camera_key or "").strip().lower()
        if key in LEROBOT_REALSENSE_DEFAULT_IDENTIFIERS:
            return LEROBOT_REALSENSE_DEFAULT_IDENTIFIERS[key]
        return "Intel RealSense"

    def _preferred_realsense_identifier(self, camera_key: str) -> str:
        """Prefer SDK serials for known physical RealSense camera roles."""
        key = str(camera_key or "").strip().lower()
        hints = LEROBOT_REALSENSE_CAMERA_MODEL_HINTS.get(key, ())
        if hints:
            for entry in self._scan_live_realsense_camera_entries():
                name = str(entry.get("name") or "").lower()
                product_line = str(entry.get("product_line") or "").lower()
                match_text = f"{name} {product_line}"
                if any(hint in match_text for hint in hints):
                    return str(
                        entry.get("serial")
                        or entry.get("configured_identifier")
                        or entry.get("name")
                        or self._default_realsense_identifier(camera_key)
                    )
        return self._default_realsense_identifier(camera_key)

    def _normalize_realsense_selected_identifier(self, request: LeRobotDevicePortRequest, selected: str, *, mode: str) -> str:
        """Convert UI-selected RealSense paths/names to SDK serials for runtime stability."""
        if request.device_role != "camera" or self._normalize_camera_backend(request.camera_backend) != LEROBOT_REALSENSE_TYPE:
            return selected
        raw = str(selected or "").strip()
        if mode != "live":
            return raw or self._preferred_realsense_identifier(request.camera_key)
        entries = self._scan_live_realsense_camera_entries()
        if not entries:
            return raw or self._preferred_realsense_identifier(request.camera_key)
        preferred = self._preferred_realsense_identifier(request.camera_key)
        visible_serials = {str(entry.get("serial") or "").strip() for entry in entries if str(entry.get("serial") or "").strip()}
        if preferred in visible_serials:
            return preferred
        if raw in visible_serials:
            return raw
        lowered = raw.lower()
        for entry in entries:
            serial = str(entry.get("serial") or "").strip()
            name = str(entry.get("name") or "").strip().lower()
            product_line = str(entry.get("product_line") or "").strip().lower()
            if serial and lowered and (lowered == name or lowered == product_line or name in lowered or product_line in lowered):
                return serial
        return raw or preferred

    def _request_camera_metadata(self, request: LeRobotDevicePortRequest) -> dict[str, Any]:
        backend = self._normalize_camera_backend(request.camera_backend)
        if backend != LEROBOT_REALSENSE_TYPE:
            return {"backend": "opencv"}
        identifier = str(request.port or "").strip() or self._preferred_realsense_identifier(request.camera_key)
        return {
            "backend": LEROBOT_REALSENSE_TYPE,
            "serial_number_or_name": identifier,
            "color_format": self._realsense_color_format(request.camera_key, identifier),
            "use_depth": True,
            "depth_scale_m_per_unit": self._realsense_depth_scale_m_per_unit(request.camera_key, identifier),
            "fps": _safe_int(request.camera_fps, LEROBOT_DEFAULT_REALSENSE_FPS, minimum=1),
            "width": _safe_int(request.camera_width, LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1),
            "height": _safe_int(request.camera_height, LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1),
        }

    @staticmethod
    def _realsense_color_format(camera_key: str | None = None, identifier: str | None = None, camera_device: dict[str, Any] | None = None) -> str:
        device = camera_device or {}
        explicit = str(device.get("color_format") or "").strip().lower()
        if explicit in {"rgb8", "bgr8"}:
            return explicit
        text = " ".join(
            str(value or "").lower()
            for value in (
                camera_key,
                identifier,
                device.get("camera_key"),
                device.get("serial_number_or_name"),
                device.get("port"),
                device.get("name"),
                device.get("model"),
            )
        )
        if "wrist" in text or "d405" in text or "405" in text or "352122273019" in text:
            return "bgr8"
        return "rgb8"

    @staticmethod
    def _realsense_depth_scale_m_per_unit(
        camera_key: str | None = None,
        identifier: str | None = None,
        camera_device: dict[str, Any] | None = None,
    ) -> float:
        device = camera_device or {}
        explicit = _safe_float(device.get("depth_scale_m_per_unit"), 0.0, minimum=0.0)
        if explicit > 0.0:
            return explicit
        text = " ".join(
            str(value or "").lower()
            for value in (
                camera_key,
                identifier,
                device.get("camera_key"),
                device.get("serial_number_or_name"),
                device.get("port"),
                device.get("name"),
                device.get("model"),
            )
        )
        if "wrist" in text or "d405" in text or "405" in text or "352122273019" in text:
            return LEROBOT_D405_DEPTH_SCALE_M_PER_UNIT
        return LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT

    @staticmethod
    def _camera_use_depth(camera_device: dict[str, Any], *, default: bool = False) -> bool:
        if "use_depth" in camera_device:
            return bool(camera_device.get("use_depth"))
        if "camera_use_depth" in camera_device:
            return bool(camera_device.get("camera_use_depth"))
        return default

    @staticmethod
    def _camera_fps(camera_device: dict[str, Any], request_fps: int | None = None) -> int:
        fps = _safe_int(camera_device.get("fps") or camera_device.get("camera_fps"), 0, minimum=0)
        if fps:
            return fps
        if request_fps:
            return _safe_int(request_fps, LEROBOT_DEFAULT_REALSENSE_FPS, minimum=1)
        return LEROBOT_DEFAULT_REALSENSE_FPS

    def _workflow_command(self, profile: RobotProfile, workflow: str, request: LeRobotSessionRequest, args: list[str]) -> list[str]:
        mode = request.runtime_mode or request.mode
        command = [self.config.conda_executable, "run", "--no-capture-output", "-n", self._workflow_conda_env_name(workflow, request)]
        if self._uses_in_process_lerobot_wrapper(workflow, request):
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_isaac_mirror_runtime_wrapper.py"), workflow])
        elif workflow == "rollout" and self._is_pi05_policy(request.policy_type):
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_pi05_rollout_wrapper.py")])
        elif workflow == "rollout" and self._uses_live_rollout_wrapper(request):
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_live_rollout_wrapper.py")])
        else:
            command.extend(self._workflow_entrypoint(profile, workflow))
        if workflow in {"teleoperate", "record", "rollout"}:
            command.extend(self._robot_args(profile, request=request, allow_fake=mode != "live", workflow=workflow))
        if workflow in {"teleoperate", "record"}:
            command.extend(self._teleop_args(profile, request=request, allow_fake=mode != "live"))
        command.extend([arg for arg in args if arg and not arg.endswith("=")])
        return command

    def _uses_live_rollout_wrapper(self, request: LeRobotSessionRequest) -> bool:
        return not self._is_pi05_policy(request.policy_type)

    def _workflow_conda_env_name(self, workflow: str, request: LeRobotSessionRequest) -> str:
        if workflow in {"train", "rollout"} and self._is_pi05_policy(request.policy_type):
            return self.config.pi05_conda_env_name
        if workflow in {"train", "rollout"} and self._is_xvla_policy(request.policy_type):
            return self.config.xvla_conda_env_name
        if workflow in {"train", "rollout"} and self._is_smolvla_policy(request.policy_type):
            return self.config.smolvla_conda_env_name
        return self.config.conda_env_name

    def _workflow_env_overrides(self, workflow: str, request: LeRobotSessionRequest, *, session_id: str = "") -> dict[str, str]:
        profile = self._profile(request.profile_id or self._selected_profile_id)
        pipeline_id = self._request_observation_pipeline_id(request, profile)
        env: dict[str, str] = {
            "ATR_LEROBOT_OBSERVATION_PIPELINE_ID": pipeline_id,
        }
        mode = request.runtime_mode or request.mode
        if mode == "live" and workflow in {"teleoperate", "record"} and request.isaac_mirror_enabled:
            mirror_session_id = session_id or request.session_id or ""
            env.update(
                {
                    "ATR_ISAAC_MIRROR_ENABLED": "1",
                    "ATR_ISAAC_MIRROR_ENDPOINT": self._isaac_mirror_endpoint(request),
                    "ATR_ISAAC_MIRROR_SAMPLE_HZ": str(self._isaac_mirror_sample_hz(request)),
                    "ATR_ISAAC_MIRROR_TIMEOUT_S": str(self._isaac_mirror_timeout_s(request)),
                    "ATR_ISAAC_MIRROR_POST_TIMEOUT_S": str(self._isaac_mirror_post_timeout_s(request)),
                    "ATR_ISAAC_MIRROR_SOURCE": "leader_action",
                    "ATR_ISAAC_MIRROR_SESSION_ID": mirror_session_id,
                    "ATR_ISAAC_MIRROR_ATTACHED_TO_SESSION_ID": mirror_session_id,
                    "ATR_ISAAC_MIRROR_PROFILE_ID": str(request.profile_id or self._selected_profile_id),
                    "ATR_ISAAC_MIRROR_CALIBRATION_PATH": str(default_isaac_omx_mirror_calibration_path(self.config.repo_root)),
                    "ATR_ISAAC_MIRROR_RECORD_PATH": str(self._in_process_isaac_mirror_record_path(workflow, request, mirror_session_id or "live")),
                }
            )
            if workflow == "record":
                attempt = self._record_attempt_summary(request, mirror_session_id or "live")
                render = dict(attempt.get("isaac_rgbd_render") or {})
                env.update(
                    {
                        "ATR_RECORD_ATTEMPT_ENABLED": "1",
                        "ATR_RECORD_ATTEMPT_DATASET_PATH": str(attempt.get("dataset_path") or ""),
                        "ATR_RECORD_ATTEMPT_SESSION_ID": mirror_session_id,
                        "ATR_RECORD_ATTEMPT_ID": str(attempt.get("attempt_id") or ""),
                        "ATR_RECORD_ATTEMPT_EPISODE_INDEX": str(attempt.get("episode_index") or 0),
                        "ATR_RECORD_ATTEMPT_TARGET_FPS": str(attempt.get("target_fps") or self._isaac_mirror_sample_hz(request)),
                        "ATR_RECORD_ATTEMPT_OVERWRITE": "1" if attempt.get("overwrite", True) else "0",
                        "ATR_ISAAC_RGBD_RENDER_ENABLED": "1" if render.get("enabled") else "0",
                        "ATR_ISAAC_RGBD_RENDER_MODE": "deferred_after_record",
                        "ATR_ISAAC_RGBD_RENDER_TARGET_FPS": str(render.get("target_fps") or 15.0),
                        "ATR_ISAAC_RGBD_RENDER_POST_TIMEOUT_S": str(self._isaac_mirror_post_timeout_s(request)),
                        "ATR_ISAAC_RGBD_RENDER_CAMERAS": ",".join(str(item) for item in render.get("cameras", []) if str(item).strip()),
                        "ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR": str(render.get("output_dir") or ""),
                    }
                )
        if self._uses_active_robot_cam(workflow, request):
            env.update(self._active_robot_cam_env_overrides(request))
        if pipeline_id == "raw_depth_adapter":
            env["ATR_LEROBOT_RAW_DEPTH_ADAPTER"] = "1"
            if workflow in {"train", "rollout"}:
                env.update(self._raw_depth_adapter_env_overrides(request))
            if workflow == "rollout":
                env.update(self._live_depth_env_overrides(request))
        if workflow == "train":
            env["ATR_LEROBOT_STANDARD_DATA_PIPELINE"] = "1"
            env.update(self._dataset_mix_env_overrides(request))
            env.update(self._fidelity_env_overrides(request))
            env.update(self._isaac_rgbd_source_train_env_overrides(request))
            env.update(self._isaac_augmentation_train_env_overrides(request))
            env.update(self._isaac_lab_synthetic_train_env_overrides(request))
        if workflow in {"train", "rollout"} and self._uses_pi05_dataset_runtime(request.policy_type):
            hf_home = self.config.pi05_hf_home
            env.update(
                {
                    "HF_HOME": str(hf_home),
                    "HF_HUB_CACHE": str(hf_home / "hub"),
                    "HF_HUB_DISABLE_XET": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                    "OMP_NUM_THREADS": "4",
                    "OPENBLAS_NUM_THREADS": "4",
                    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                    "ATR_PI05_ACTION_LOG_INTERVAL": "30",
                }
            )
            hf_token = self._hf_token_for_subprocess()
            if hf_token:
                env["HF_TOKEN"] = hf_token
                env["HUGGING_FACE_HUB_TOKEN"] = hf_token
        if mode == "live" and workflow == "rollout" and profile and profile.robot_type == "omx_follower":
            env.update(self._omx_action_log_env_overrides(session_id or request.session_id or "live"))
            env["ATR_LEROBOT_SHOULDER_LIFT_BACKSTOP"] = "1" if request.rollout_shoulder_lift_backstop else "0"
        wandb_mode = str(request.wandb_mode or "").strip().lower()
        if workflow == "train" and request.wandb_enable:
            wandb_base_url = str(request.wandb_base_url or "").strip().rstrip("/")
            if wandb_mode == "local" and not wandb_base_url:
                wandb_base_url = self._wandb_local_url(request)
            if wandb_base_url:
                env["WANDB_BASE_URL"] = wandb_base_url
        if workflow == "train" and request.wandb_enable and wandb_mode == "offline":
            env["WANDB_MODE"] = "offline"
        if workflow == "record":
            env.update(self._tts_env_overrides(request))
            env.update(self._raw_depth_env_overrides(request))
        return env

    def _omx_action_log_env_overrides(self, session_id: str) -> dict[str, str]:
        clean_session_id = self._safe_session_id(session_id or "live")
        log_dir = self._omx_action_log_dir(clean_session_id)
        return {
            "ATR_LEROBOT_OMX_ACTION_LOG": "1",
            "ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID": clean_session_id,
            "ATR_LEROBOT_OMX_ACTION_LOG_DIR": str(log_dir),
            "ATR_LEROBOT_OMX_ACTION_LOG_MOTORS": "shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper",
        }

    def _omx_action_log_dir(self, session_id: str) -> Path:
        clean_session_id = self._safe_session_id(session_id or "live")
        return self.config.session_log_root.parent / "lerobot_action_logs" / clean_session_id

    def _omx_action_log_path(self, session_id: str) -> Path:
        return self._omx_action_log_dir(session_id) / "motor_events.jsonl"

    @staticmethod
    def _safe_session_id(value: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip()).strip(".-")
        return clean or "live"

    def _live_depth_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        profile = self._profile(request.profile_id or self._selected_profile_id)
        if profile is None:
            return {}
        sidecar = self._record_raw_depth_sidecar(profile, request)
        if not sidecar.get("enabled"):
            return {}
        camera_keys = [str(item) for item in sidecar.get("expected_camera_keys", []) if str(item).strip()]
        env = {
            "ATR_LEROBOT_LIVE_DEPTH_FEATURES": "1",
            "ATR_LEROBOT_LIVE_DEPTH_STRICT": "1",
            "ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS": ",".join(camera_keys),
            "ATR_LEROBOT_DEPTH_ALIGNED_TO": str(sidecar.get("aligned_to") or "color"),
            "ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT": str(sidecar.get("depth_scale_m_per_unit")),
            "ATR_LEROBOT_DEPTH_CLIP_MIN_MM": str(sidecar.get("depth_clip_min_mm")),
            "ATR_LEROBOT_DEPTH_CLIP_MAX_MM": str(sidecar.get("depth_clip_max_mm")),
        }
        formatted = self._format_camera_depth_scale_env(sidecar.get("camera_depth_scale_m_per_unit"))
        if formatted:
            env["ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT"] = formatted
        formatted_clips = self._format_camera_depth_clip_env(sidecar.get("camera_depth_clip_mm"))
        if formatted_clips:
            env["ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM"] = formatted_clips
        return env

    @staticmethod
    def _dataset_mix_weight(value: Any, default: float) -> float:
        return _safe_float(value, default, minimum=0.0)

    @staticmethod
    def _dataset_source_selection(request: LeRobotSessionRequest) -> dict[str, bool]:
        return {
            "real_original": _safe_bool(getattr(request, "dataset_include_real_original", True), True),
            "isaac_rgbd": _safe_bool(getattr(request, "dataset_include_isaac_rgbd", True), True),
            "isaac_augmentation": _safe_bool(getattr(request, "dataset_include_isaac_augmentation", True), True),
            "isaac_lab_synthetic": _safe_bool(getattr(request, "dataset_include_isaac_lab_synthetic", True), True),
        }

    @classmethod
    def _dataset_source_enabled(cls, request: LeRobotSessionRequest, source: str) -> bool:
        return cls._dataset_source_selection(request).get(str(source), True)

    @staticmethod
    def _dataset_mix_max_samples(value: Any) -> int | None:
        if value is None:
            return None
        parsed = _safe_int(value, 0, minimum=0)
        return parsed

    @staticmethod
    def _dataset_mix_effective_count(available_count: int, base_count: int, weight: float, max_samples: int | None) -> int:
        available = max(0, int(available_count))
        base = max(0, int(base_count))
        if available <= 0 or base <= 0 or weight <= 0:
            return 0
        raw_desired = base * weight
        desired = int(raw_desired)
        if raw_desired > desired:
            desired += 1
        selected = min(available, desired)
        if max_samples is not None:
            selected = min(selected, max(0, int(max_samples)))
        return selected

    @staticmethod
    def _format_dataset_mix_env_float(value: float) -> str:
        return f"{float(value):g}"

    def _dataset_mix_summary_for_counts(
        self,
        request: LeRobotSessionRequest,
        *,
        real_available: int,
        isaac_rgbd_available: int,
        isaac_augmentation_available: int,
        isaac_lab_synthetic_available: int = 0,
    ) -> dict[str, Any]:
        weights = {
            "real_original": self._dataset_mix_weight(getattr(request, "dataset_mix_real_original_weight", 1.0), 1.0),
            "isaac_rgbd": self._dataset_mix_weight(getattr(request, "dataset_mix_isaac_rgbd_weight", 0.6), 0.6),
            "isaac_augmentation": self._dataset_mix_weight(getattr(request, "dataset_mix_isaac_augmentation_weight", 0.0), 0.0),
            "isaac_lab_synthetic": self._dataset_mix_weight(getattr(request, "dataset_mix_isaac_lab_synthetic_weight", 0.35), 0.35),
        }
        source_selection = self._dataset_source_selection(request)
        for source, enabled in source_selection.items():
            if not enabled:
                weights[source] = 0.0
        max_samples = {
            "real_original": self._dataset_mix_max_samples(getattr(request, "dataset_mix_real_original_max_samples", None)),
            "isaac_rgbd": self._dataset_mix_max_samples(getattr(request, "dataset_mix_isaac_rgbd_max_samples", None)),
            "isaac_augmentation": self._dataset_mix_max_samples(getattr(request, "dataset_mix_isaac_augmentation_max_samples", None)),
            "isaac_lab_synthetic": self._dataset_mix_max_samples(getattr(request, "dataset_mix_isaac_lab_synthetic_max_samples", None)),
        }
        available_counts = {
            "real_original": max(0, int(real_available)),
            "isaac_rgbd": max(0, int(isaac_rgbd_available)),
            "isaac_augmentation": max(0, int(isaac_augmentation_available)),
            "isaac_lab_synthetic": max(0, int(isaac_lab_synthetic_available)),
        }
        base_count = available_counts["real_original"]
        effective_counts = {
            source: self._dataset_mix_effective_count(available, base_count, weights[source], max_samples[source])
            for source, available in available_counts.items()
        }
        effective_counts["total"] = sum(effective_counts.values())
        return {
            "schema": "atr.lerobot.dataset_mix.v1",
            "weights": weights,
            "source_selection": source_selection,
            "max_samples": max_samples,
            "available_counts": available_counts,
            "effective_counts": effective_counts,
            "seed": _safe_int(getattr(request, "dataset_mix_seed", 0), 0),
        }

    def _dataset_base_frame_count(self, dataset_path: Path) -> int:
        info_path = dataset_path / "meta" / "info.json"
        try:
            loaded = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        return _safe_int(loaded.get("total_frames") if isinstance(loaded, dict) else None, 0, minimum=0)

    def _train_dataset_mix_summary(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        real_available = self._dataset_base_frame_count(dataset_path)
        isaac_rgbd = self._dataset_isaac_rgbd_health(dataset_path)
        isaac_augmentation = self._read_latest_isaac_augmentation_summary(dataset_path)
        isaac_lab_synthetic = self._read_latest_isaac_lab_synthetic_summary(dataset_path)
        variant_count = _safe_int(isaac_augmentation.get("variant_count"), 0, minimum=0)
        valid_variant_count = _safe_int(isaac_augmentation.get("valid_variant_count"), variant_count, minimum=0)
        summary = self._dataset_mix_summary_for_counts(
            request,
            real_available=real_available,
            isaac_rgbd_available=_safe_int(isaac_rgbd.get("rendered_count"), 0, minimum=0),
            isaac_augmentation_available=valid_variant_count,
            isaac_lab_synthetic_available=_safe_int(isaac_lab_synthetic.get("synthetic_row_count"), 0, minimum=0),
        )
        exclusions = self._read_contact_training_exclusion_manifest(dataset_path)
        if not exclusions.get("available") and isaac_rgbd.get("available"):
            exclusions = self._write_contact_training_exclusion_manifest(dataset_path, isaac_rgbd.get("contact_audit"))
        enabled = _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True)
        summary["training_exclusions"] = {
            **exclusions,
            "enabled": enabled,
            "applied_episode_indices": list(exclusions.get("episode_indices", [])) if enabled else [],
            "applied_episode_count": _safe_int(exclusions.get("episode_count"), 0, minimum=0) if enabled else 0,
        }
        return summary

    def _dataset_mix_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        summary = self._train_dataset_mix_summary(request)
        weights = dict(summary.get("weights") or {})
        max_samples = dict(summary.get("max_samples") or {})
        exclusions = summary.get("training_exclusions") if isinstance(summary.get("training_exclusions"), dict) else {}
        exclusion_indices = [
            str(_safe_int(item, -1))
            for item in exclusions.get("applied_episode_indices", [])
            if _safe_int(item, -1) >= 0
        ]
        env = {
            "ATR_LEROBOT_DATA_SOURCE_INCLUDE_REAL_ORIGINAL": "1" if self._dataset_source_enabled(request, "real_original") else "0",
            "ATR_LEROBOT_DATA_SOURCE_INCLUDE_ISAAC_RGBD": "1" if self._dataset_source_enabled(request, "isaac_rgbd") else "0",
            "ATR_LEROBOT_DATA_SOURCE_INCLUDE_ISAAC_AUGMENTATION": "1" if self._dataset_source_enabled(request, "isaac_augmentation") else "0",
            "ATR_LEROBOT_DATA_SOURCE_INCLUDE_ISAAC_LAB_SYNTHETIC": "1" if self._dataset_source_enabled(request, "isaac_lab_synthetic") else "0",
            "ATR_LEROBOT_DATA_MIX_REAL_ORIGINAL_WEIGHT": self._format_dataset_mix_env_float(weights.get("real_original", 1.0)),
            "ATR_LEROBOT_DATA_MIX_ISAAC_RGBD_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_rgbd", 0.6)),
            "ATR_LEROBOT_DATA_MIX_ISAAC_AUGMENTATION_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_augmentation", 0.0)),
            "ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_lab_synthetic", 0.35)),
            "ATR_LEROBOT_DATA_MIX_SEED": str(_safe_int(summary.get("seed"), 0)),
            "ATR_LEROBOT_KEEP_REAL_FLAGGED_EPISODES": "1",
            "ATR_LEROBOT_SIM_EXCLUDE_FLAGGED_EPISODES": "1" if exclusion_indices else "0",
            "ATR_LEROBOT_SIM_EXCLUDED_EPISODES": ",".join(exclusion_indices),
        }
        manifest_path = str(exclusions.get("manifest_path") or "").strip()
        if manifest_path:
            env["ATR_LEROBOT_TRAINING_EXCLUSION_MANIFEST"] = manifest_path
        max_env_keys = {
            "real_original": "ATR_LEROBOT_DATA_MIX_REAL_ORIGINAL_MAX_SAMPLES",
            "isaac_rgbd": "ATR_LEROBOT_DATA_MIX_ISAAC_RGBD_MAX_SAMPLES",
            "isaac_augmentation": "ATR_LEROBOT_DATA_MIX_ISAAC_AUGMENTATION_MAX_SAMPLES",
            "isaac_lab_synthetic": "ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_MAX_SAMPLES",
        }
        for source, env_key in max_env_keys.items():
            value = max_samples.get(source)
            if value is not None:
                env[env_key] = str(_safe_int(value, 0, minimum=0))
        return env

    @staticmethod
    def _fidelity_weight(value: Any, default: float) -> float:
        return _safe_float(value, default, minimum=0.0, maximum=1.0)

    def _train_fidelity_summary(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        weights = {
            "real_original": self._fidelity_weight(getattr(request, "fidelity_real_original_weight", 1.0), 1.0),
            "isaac_rgbd": self._fidelity_weight(getattr(request, "fidelity_isaac_rgbd_weight", 0.55), 0.55),
            "isaac_augmentation": self._fidelity_weight(getattr(request, "fidelity_isaac_augmentation_weight", 0.0), 0.0),
            "isaac_lab_synthetic": self._fidelity_weight(getattr(request, "fidelity_isaac_lab_synthetic_weight", 0.25), 0.25),
        }
        source_selection = self._dataset_source_selection(request)
        for source, enabled in source_selection.items():
            if not enabled:
                weights[source] = 0.0
        return {
            "schema": "atr.lerobot.fidelity_weights.v1",
            "enabled": _safe_bool(getattr(request, "fidelity_weighting_enabled", True), True),
            "mode": "source_loss_weight",
            "source_selection": source_selection,
            "weights": weights,
        }

    def _fidelity_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        summary = self._train_fidelity_summary(request)
        weights = dict(summary.get("weights") or {})
        return {
            "ATR_LEROBOT_FIDELITY_SCHEMA": str(summary.get("schema") or "atr.lerobot.fidelity_weights.v1"),
            "ATR_LEROBOT_FIDELITY_WEIGHTING_ENABLED": "1" if summary.get("enabled") else "0",
            "ATR_LEROBOT_FIDELITY_MODE": str(summary.get("mode") or "source_loss_weight"),
            "ATR_LEROBOT_FIDELITY_REAL_ORIGINAL_WEIGHT": self._format_dataset_mix_env_float(weights.get("real_original", 1.0)),
            "ATR_LEROBOT_FIDELITY_ISAAC_RGBD_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_rgbd", 0.55)),
            "ATR_LEROBOT_FIDELITY_ISAAC_AUGMENTATION_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_augmentation", 0.0)),
            "ATR_LEROBOT_FIDELITY_ISAAC_LAB_SYNTHETIC_WEIGHT": self._format_dataset_mix_env_float(weights.get("isaac_lab_synthetic", 0.25)),
        }

    def _raw_depth_adapter_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        if not self._dataset_source_enabled(request, "real_original"):
            return {}
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        manifest_path = self._dataset_raw_depth_manifest_path(dataset_path)
        env = {
            "ATR_LEROBOT_RAW_DEPTH_SOURCE_DIR": str(manifest_path.parent),
            "ATR_LEROBOT_RAW_DEPTH_ADAPTER_STRICT": "1",
        }
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if isinstance(manifest, dict):
            camera_keys = [str(item).strip() for item in manifest.get("camera_keys", []) if str(item).strip()]
            if camera_keys:
                env["ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS"] = ",".join(camera_keys)
            camera_scales = manifest.get("camera_depth_scale_m_per_unit")
            if isinstance(camera_scales, dict):
                formatted = self._format_camera_depth_scale_env(camera_scales)
                if formatted:
                    env["ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT"] = formatted
            camera_clips = manifest.get("camera_depth_clip_mm")
            formatted_clips = self._format_camera_depth_clip_env(camera_clips)
            if formatted_clips:
                env["ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM"] = formatted_clips
            for key in ("ATR_LEROBOT_DEPTH_ALIGNED_TO", "ATR_LEROBOT_RAW_DEPTH_FORMAT"):
                env.pop(key, None)
            aligned_to = str(manifest.get("aligned_to") or "").strip()
            if aligned_to:
                env["ATR_LEROBOT_DEPTH_ALIGNED_TO"] = aligned_to
            depth_encoding = str(manifest.get("depth_encoding") or "").strip()
            if depth_encoding:
                env["ATR_LEROBOT_RAW_DEPTH_FORMAT"] = depth_encoding
            for source_key, env_key in (
                ("depth_scale_m_per_unit", "ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT"),
                ("depth_clip_min_mm", "ATR_LEROBOT_DEPTH_CLIP_MIN_MM"),
                ("depth_clip_max_mm", "ATR_LEROBOT_DEPTH_CLIP_MAX_MM"),
            ):
                if source_key in manifest:
                    env[env_key] = str(manifest[source_key])
            visual = manifest.get("visual_depth_feature")
            if isinstance(visual, dict):
                if "clip_min_mm" in visual and "ATR_LEROBOT_DEPTH_CLIP_MIN_MM" not in env:
                    env["ATR_LEROBOT_DEPTH_CLIP_MIN_MM"] = str(visual["clip_min_mm"])
                if "clip_max_mm" in visual and "ATR_LEROBOT_DEPTH_CLIP_MAX_MM" not in env:
                    env["ATR_LEROBOT_DEPTH_CLIP_MAX_MM"] = str(visual["clip_max_mm"])
        return env

    def _isaac_augmentation_train_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        if not self._dataset_source_enabled(request, "isaac_augmentation"):
            return {}
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        summary = self._read_latest_isaac_augmentation_summary(dataset_path)
        if not summary.get("available") or _safe_int(summary.get("variant_count"), 0, minimum=0) <= 0:
            return {}
        manifest_path = Path(str(summary.get("manifest_path") or "")).expanduser()
        summary_path = Path(str(summary.get("summary_path") or "")).expanduser()
        if not manifest_path.is_file():
            return {}
        variant_count = _safe_int(summary.get("variant_count"), 0, minimum=0)
        valid_variant_count = _safe_int(summary.get("valid_variant_count"), variant_count, minimum=0)
        failed_variant_count = _safe_int(summary.get("failed_variant_count"), max(0, variant_count - valid_variant_count), minimum=0)
        qa_summary_path = Path(str(summary.get("qa_summary_path") or summary_path.parent / "qa_summary.json")).expanduser()
        exclusions = self._read_contact_training_exclusion_manifest(dataset_path)
        exclusion_indices = ",".join(
            str(_safe_int(item, -1))
            for item in exclusions.get("episode_indices", [])
            if _safe_int(item, -1) >= 0 and _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True)
        )
        env = {
            "ATR_LEROBOT_ISAAC_AUGMENTATION_ADAPTER": "1",
            "ATR_LEROBOT_ISAAC_AUGMENTATION_MANIFEST": str(manifest_path),
            "ATR_LEROBOT_ISAAC_AUGMENTATION_SUMMARY": str(summary_path),
            "ATR_LEROBOT_ISAAC_AUGMENTATION_QA_SUMMARY": str(qa_summary_path),
            "ATR_LEROBOT_ISAAC_AUGMENTATION_INCLUDE_ALL": "1",
            "ATR_LEROBOT_ISAAC_AUGMENTATION_REQUIRE_QA_OK": "1",
            "ATR_LEROBOT_ISAAC_AUGMENTATION_STRICT": "0",
            "ATR_LEROBOT_ISAAC_AUGMENTATION_VARIANT_COUNT": str(variant_count),
            "ATR_LEROBOT_ISAAC_AUGMENTATION_VALID_VARIANT_COUNT": str(valid_variant_count),
            "ATR_LEROBOT_ISAAC_AUGMENTATION_FAILED_VARIANT_COUNT": str(failed_variant_count),
        }
        if exclusion_indices:
            env["ATR_LEROBOT_ISAAC_AUGMENTATION_EXCLUDE_SOURCE_EPISODES"] = exclusion_indices
            env["ATR_LEROBOT_ISAAC_AUGMENTATION_EXCLUSION_MANIFEST"] = str(exclusions.get("manifest_path") or "")
        return env

    def _isaac_lab_synthetic_train_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        if not self._dataset_source_enabled(request, "isaac_lab_synthetic"):
            return {}
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        summary = self._read_latest_isaac_lab_synthetic_summary(dataset_path)
        if not summary.get("available") or _safe_int(summary.get("row_count"), 0, minimum=0) <= 0:
            return {}
        manifest_path = Path(str(summary.get("training_import_manifest_path") or "")).expanduser()
        summary_path = Path(str(summary.get("training_import_summary_path") or "")).expanduser()
        if not manifest_path.is_file() or not summary_path.is_file():
            return {}
        source_counts = summary.get("source_counts") if isinstance(summary.get("source_counts"), dict) else {}
        return {
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_ADAPTER": "1",
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_MANIFEST": str(manifest_path),
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_SUMMARY": str(summary_path),
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_OUTPUT_ROOT": str(summary.get("output_root") or manifest_path.parents[1]),
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_REQUIRE_SUCCESS": "1",
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_STRICT": "0",
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_ROW_COUNT": str(_safe_int(summary.get("row_count"), 0, minimum=0)),
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_SYNTHETIC_ROW_COUNT": str(_safe_int(summary.get("synthetic_row_count"), 0, minimum=0)),
            "ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_SOURCE_COUNTS": json.dumps(source_counts, sort_keys=True),
        }

    def _isaac_rgbd_source_train_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        if not self._dataset_source_enabled(request, "isaac_rgbd"):
            return {}
        dataset_path = Path(self._dataset_path_for(request)).expanduser()
        source_root = dataset_path / "sidecar" / "isaac_rgbd"
        if not any(source_root.glob("**/manifest.jsonl")):
            return {}
        exclusions = self._read_contact_training_exclusion_manifest(dataset_path)
        exclusion_indices = ",".join(
            str(_safe_int(item, -1))
            for item in exclusions.get("episode_indices", [])
            if _safe_int(item, -1) >= 0 and _safe_bool(getattr(request, "dataset_exclude_flagged_episodes", True), True)
        )
        env = {
            "ATR_LEROBOT_ISAAC_RGBD_SOURCE_ADAPTER": "1",
            "ATR_LEROBOT_ISAAC_RGBD_SOURCE_ROOT": str(source_root),
            "ATR_LEROBOT_ISAAC_RGBD_SOURCE_INCLUDE_ALL": "1",
            "ATR_LEROBOT_ISAAC_RGBD_SOURCE_STRICT": "0",
        }
        if exclusion_indices:
            env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_EXCLUDE_EPISODES"] = exclusion_indices
            env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_EXCLUSION_MANIFEST"] = str(exclusions.get("manifest_path") or "")
        return env

    def _raw_depth_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        profile = self._profile(request.profile_id or self._selected_profile_id)
        if profile is None:
            return {}
        sidecar = self._record_raw_depth_sidecar(profile, request)
        if not sidecar.get("enabled"):
            return {}
        camera_keys = [str(item) for item in sidecar.get("expected_camera_keys", []) if str(item).strip()]
        env = {
            "ATR_LEROBOT_RAW_DEPTH_DIR": str(sidecar["root"]),
            "ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS": ",".join(camera_keys),
            "ATR_LEROBOT_RAW_DEPTH_FORMAT": str(sidecar.get("format") or "png16"),
            "ATR_LEROBOT_DEPTH_ALIGNED_TO": str(sidecar.get("aligned_to") or "color"),
            "ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT": str(sidecar.get("depth_scale_m_per_unit")),
            "ATR_LEROBOT_DEPTH_CLIP_MIN_MM": str(sidecar.get("depth_clip_min_mm")),
            "ATR_LEROBOT_DEPTH_CLIP_MAX_MM": str(sidecar.get("depth_clip_max_mm")),
        }
        formatted = self._format_camera_depth_scale_env(sidecar.get("camera_depth_scale_m_per_unit"))
        if formatted:
            env["ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT"] = formatted
        formatted_clips = self._format_camera_depth_clip_env(sidecar.get("camera_depth_clip_mm"))
        if formatted_clips:
            env["ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM"] = formatted_clips
        return env

    @staticmethod
    def _format_camera_depth_scale_env(scales: Any) -> str:
        if not isinstance(scales, dict):
            return ""
        parts: list[str] = []
        for camera_key in sorted(str(key).strip() for key in scales if str(key).strip()):
            value = _safe_float(scales.get(camera_key), 0.0, minimum=0.0)
            if value > 0.0:
                parts.append(f"{camera_key}={value:g}")
        return ",".join(parts)

    @staticmethod
    def _format_camera_depth_clip_env(clips: Any) -> str:
        normalized = _normalize_camera_depth_clip_map(clips, default={})
        parts: list[str] = []
        for camera_key in sorted(normalized):
            clip = normalized[camera_key]
            parts.append(f"{camera_key}={clip['min_mm']:g}:{clip['max_mm']:g}")
        return ",".join(parts)

    def _start_training_monitor(self, session: dict[str, Any], request: LeRobotSessionRequest) -> dict[str, Any]:
        """Attach passive host diagnostics to GUI-started live training sessions."""
        session_id = str(session.get("session_id") or "")
        log_path = str(session.get("log_path") or "").strip()
        script = self.config.repo_root / "scripts" / "training_stability_monitor.py"
        if not script.is_file():
            return {"status": "unavailable", "reason": f"missing monitor script: {script}"}
        output_dir = self.config.repo_root / "runs" / "training_watch"
        command = [
            sys.executable or "python3",
            str(script),
            "--interval-seconds",
            "30",
            "--output-dir",
            str(output_dir),
        ]
        if log_path:
            command.extend(["--train-log", log_path])
        checkpoint_dir = self._checkpoint_dir_for_monitor(str(session.get("checkpoint_path") or ""))
        if checkpoint_dir:
            command.extend(["--checkpoint-dir", checkpoint_dir])
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.config.repo_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
        except Exception as exc:
            return {"status": "failed", "reason": f"{exc.__class__.__name__}: {exc}", "command_preview": command}
        if session_id:
            self._monitor_processes[session_id] = process
        return {
            "status": "running",
            "pid": process.pid,
            "output_dir": str(output_dir),
            "train_log": log_path,
            "checkpoint_dir": checkpoint_dir,
            "command_preview": command,
        }

    @staticmethod
    def _checkpoint_dir_for_monitor(checkpoint_path: str) -> str:
        path = Path(str(checkpoint_path or "")).expanduser()
        candidates = [path]
        if path.name == "pretrained_model":
            candidates.append(path.parent)
        for candidate in candidates:
            if (candidate / "training_state" / "training_step.json").exists():
                return str(candidate)
        return ""

    def _stop_training_monitor(self, session: dict[str, Any]) -> None:
        session_id = str(session.get("session_id") or "")
        process = self._monitor_processes.pop(session_id, None)
        if process is None:
            return
        if process.poll() is None:
            self._terminate_live_process(process, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_live_process(process, signal.SIGKILL)
                process.wait(timeout=5)
        monitor = dict(session.get("monitor") or {})
        monitor["status"] = "stopped"
        monitor["returncode"] = process.returncode
        session["monitor"] = monitor

    def _hf_token_for_subprocess(self) -> str:
        for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            token = os.environ.get(name, "").strip()
            if token:
                return token
        candidates = (
            self.config.hf_token_path,
            Path.home() / ".cache" / "huggingface" / "token",
            Path.home() / ".huggingface" / "token",
            self.config.pi05_hf_home / "token",
        )
        seen: set[Path] = set()
        for candidate in candidates:
            path = Path(candidate).expanduser()
            if path in seen:
                continue
            seen.add(path)
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if token:
                return token
        return ""

    def _tts_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        tts = self._tts_config_for_request(request)
        env = {
            "LEROBOT_TTS_ENGINE": tts["engine"],
            "LEROBOT_TTS_RATE": str(tts["rate"]),
        }
        if tts["voice"]:
            env["LEROBOT_TTS_VOICE"] = tts["voice"]
        if tts["engine"] == "piper":
            env.update(
                {
                    "ATR_REPO_ROOT": str(self.config.repo_root),
                    "LEROBOT_TTS_PIPER_PYTHON": str(self.config.tts_piper_python),
                    "LEROBOT_TTS_PIPER_SCRIPT": str(self.config.tts_piper_script),
                    "LEROBOT_TTS_PIPER_BIN": str(self.config.tts_piper_bin),
                    "LEROBOT_TTS_PIPER_MODEL": str(self.config.tts_piper_model),
                    "LEROBOT_TTS_PIPER_CONFIG": str(self.config.tts_piper_config),
                }
            )
        return env

    def _tts_config_for_request(self, request: LeRobotSessionRequest) -> dict[str, Any]:
        engine = self._normalize_tts_engine(request.tts_engine or self.config.tts_engine)
        voice_default = self.config.tts_voice if engine == "piper" else ""
        tts = {
            "engine": engine,
            "rate": _safe_int(request.tts_rate, self.config.tts_rate, minimum=-100, maximum=100),
            "voice": str(request.tts_voice or voice_default or "").strip(),
        }
        if tts["engine"] == "piper":
            tts["piper_model"] = str(self.config.tts_piper_model)
        return tts

    def _tts_config_public(self) -> dict[str, Any]:
        return {
            "engine": self._normalize_tts_engine(self.config.tts_engine),
            "rate": _safe_int(self.config.tts_rate, -35, minimum=-100, maximum=100),
            "voice": str(self.config.tts_voice or "").strip(),
            "supported_engines": ["piper", "spd-say", "espeak", "espeak-ng"],
            "rate_range": [-100, 100],
            "piper_model": str(self.config.tts_piper_model),
        }

    @staticmethod
    def _normalize_tts_engine(engine: str) -> str:
        clean = str(engine or "piper").strip().lower()
        return clean if clean in {"piper", "spd-say", "espeak", "espeak-ng"} else "piper"

    def _train_args(self, profile: RobotProfile, request: LeRobotSessionRequest) -> list[str]:
        """Build this repository's LeRobot train command arguments."""
        extra = self._validated_train_extra_args(self._train_extra_args_with_policy_defaults(request))
        dataset_repo = request.dataset_repo_id or "local/fake_lerobot_dataset"
        dataset_root = request.dataset_root or request.dataset_path or str(self.config.dataset_root)
        job_name = request.job_name or self._default_train_job_name(profile, request)
        output_dir = request.output_dir or str(self.config.output_root / job_name)
        policy_repo = request.policy_repo_id or self._default_train_policy_repo_id(profile, request)
        policy_type = self._canonical_policy_type(request.policy_type or "act")
        pretrained_policy = str(request.policy_pretrained_path or "").strip()
        is_pi05 = self._is_pi05_policy(policy_type)
        args = [
            f"--dataset.repo_id={dataset_repo}",
            f"--dataset.root={dataset_root}",
            f"--dataset.video_backend={self._train_video_backend(policy_type, request)}",
            f"--policy.type={policy_type}",
            f"--output_dir={output_dir}",
            f"--job_name={job_name}",
            f"--policy.device={request.device or 'cuda'}",
            f"--policy.repo_id={policy_repo}",
            f"--policy.push_to_hub={_bool_arg(request.push_to_hub)}",
            f"--batch_size={int(request.batch_size)}",
            f"--steps={int(request.steps)}",
            f"--num_workers={int(request.num_workers)}",
            f"--eval_freq={int(request.eval_freq)}",
            f"--log_freq={int(request.log_freq)}",
            f"--save_checkpoint={_bool_arg(request.save_checkpoint)}",
            f"--save_freq={int(request.save_freq)}",
            f"--resume={_bool_arg(request.resume)}",
            f"--wandb.enable={_bool_arg(request.wandb_enable)}",
        ]
        if not is_pi05:
            args.insert(8, f"--policy.use_amp={_bool_arg(request.policy_use_amp)}")
        if pretrained_policy:
            pretrained_key = "policy.pretrained_path" if self._uses_pi05_dataset_runtime(policy_type) else "policy.path"
            args.append(f"--{pretrained_key}={pretrained_policy}")
        optional: list[str] = []
        if request.seed is not None:
            optional.append(f"--seed={int(request.seed)}")
        if request.eval_batch_size is not None:
            optional.append(f"--eval.batch_size={int(request.eval_batch_size)}")
        if request.optimizer_type:
            optional.append(f"--optimizer.type={request.optimizer_type}")
            if request.optimizer_lr is not None:
                optional.append(f"--optimizer.lr={request.optimizer_lr}")
            if request.optimizer_weight_decay is not None:
                optional.append(f"--optimizer.weight_decay={request.optimizer_weight_decay}")
            if request.optimizer_grad_clip_norm is not None:
                optional.append(f"--optimizer.grad_clip_norm={request.optimizer_grad_clip_norm}")
        if request.scheduler_type:
            optional.append(f"--scheduler.type={request.scheduler_type}")
            if request.scheduler_warmup_steps is not None:
                optional.append(f"--scheduler.num_warmup_steps={int(request.scheduler_warmup_steps)}")
            if request.scheduler_decay_steps is not None:
                optional.append(f"--scheduler.num_decay_steps={int(request.scheduler_decay_steps)}")
            if request.scheduler_peak_lr is not None:
                optional.append(f"--scheduler.peak_lr={request.scheduler_peak_lr}")
            if request.scheduler_decay_lr is not None:
                optional.append(f"--scheduler.decay_lr={request.scheduler_decay_lr}")
        if request.policy_n_obs_steps is not None:
            optional.append(f"--policy.n_obs_steps={int(request.policy_n_obs_steps)}")
        if request.policy_chunk_size is not None:
            optional.append(f"--policy.chunk_size={int(request.policy_chunk_size)}")
        if request.policy_n_action_steps is not None:
            optional.append(f"--policy.n_action_steps={int(request.policy_n_action_steps)}")
        if request.wandb_project:
            optional.append(f"--wandb.project={request.wandb_project}")
        if request.wandb_mode:
            wandb_mode = "online" if str(request.wandb_mode).strip().lower() == "local" else request.wandb_mode
            optional.append(f"--wandb.mode={wandb_mode}")
        return args + optional + extra

    def _train_request_with_output_dir(self, profile: RobotProfile, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        """Avoid LeRobot's overwrite guard for fresh live training runs."""
        mode = request.runtime_mode or request.mode
        if mode != "live":
            return request, "training config accepted"

        job_name = request.job_name or self._default_train_job_name(profile, request)
        raw_output_dir = request.output_dir or str(self.config.output_root / job_name)
        output_base = raw_output_dir if request.resume else self._path_without_generated_suffixes(raw_output_dir)
        output_dir = _resolve_path(self.config.repo_root, output_base).resolve()
        if not self._is_under_allowed_roots(output_dir):
            raise ValueError(f"Training output_dir is outside allowed roots: {output_dir}")

        updates: dict[str, Any] = {"job_name": job_name, "output_dir": str(output_dir)}
        normalized = request.model_copy(update=updates)
        if normalized.resume or not output_dir.exists():
            return normalized, "training config accepted"

        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fresh_dir = output_dir.with_name(f"{output_dir.name}-{suffix}")
        counter = 1
        while fresh_dir.exists():
            counter += 1
            fresh_dir = output_dir.with_name(f"{output_dir.name}-{suffix}-{counter:02d}")
        next_request = normalized.model_copy(update={"output_dir": str(fresh_dir), "resume": False})
        return next_request, f"training output_dir exists; using fresh output_dir {fresh_dir}"

    def _train_request_with_resume_config(self, profile: RobotProfile, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        """LeRobot Pi0.5 resume requires the original checkpoint train_config.json."""
        mode = request.runtime_mode or request.mode
        if mode != "live" or not request.resume:
            return request, "resume disabled"
        if any(str(arg).split("=", 1)[0] == "--config_path" for arg in request.train_extra_args or []):
            return request, "resume config provided by user"

        job_name = request.job_name or self._default_train_job_name(profile, request)
        output_dir = _resolve_path(self.config.repo_root, request.output_dir or str(self.config.output_root / job_name)).resolve()
        if not self._is_under_allowed_roots(output_dir):
            raise ValueError(f"Training output_dir is outside allowed roots: {output_dir}")
        config_path = self._latest_train_config_path(output_dir)
        if config_path is None:
            raise ValueError(
                "Resume training requires an existing LeRobot checkpoint train_config.json. "
                f"No train_config.json was found under {output_dir / 'checkpoints'}. "
                "Start a fresh run with resume unchecked, or select an output_dir containing checkpoints/<step>/pretrained_model/train_config.json."
            )
        extra_args = list(request.train_extra_args or [])
        extra_args.append(f"--config_path={config_path}")
        return request.model_copy(update={"train_extra_args": extra_args}), f"resume config={config_path}"

    @staticmethod
    def _latest_train_config_path(output_dir: Path) -> Path | None:
        """Return the newest LeRobot checkpoint train_config.json for resume."""
        direct_candidates = [
            output_dir / "checkpoints" / "last" / "pretrained_model" / "train_config.json",
            output_dir / "checkpoints" / "last" / "train_config.json",
            output_dir / "train_config.json",
        ]
        for candidate in direct_candidates:
            if candidate.is_file():
                return candidate.resolve()

        checkpoint_root = output_dir / "checkpoints"
        candidates: list[tuple[int, float, str, Path]] = []
        try:
            children = list(checkpoint_root.iterdir())
        except OSError:
            children = []
        for checkpoint_dir in children:
            if not checkpoint_dir.is_dir():
                continue
            config_path = checkpoint_dir / "pretrained_model" / "train_config.json"
            if not config_path.is_file():
                config_path = checkpoint_dir / "train_config.json"
            if not config_path.is_file():
                continue
            name = checkpoint_dir.name
            step = int(name) if name.isdigit() else -1
            try:
                mtime = config_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            candidates.append((step, mtime, name, config_path.resolve()))
        if not candidates:
            return None
        return max(candidates)[3]

    def _train_request_with_policy_runtime(self, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        policy_type = self._canonical_policy_type(request.policy_type or "act")
        updates: dict[str, Any] = {"policy_type": policy_type}
        if self._is_pi05_policy(policy_type):
            fields_set = set(request.model_fields_set)
            self._validate_pi05_train_request(request)
            pi05_defaults: dict[str, Any] = {
                "batch_size": 16,
                "steps": 3000,
                "num_workers": 12,
                "eval_batch_size": None,
                "eval_freq": 500,
                "log_freq": 50,
                "save_freq": 500,
                "wandb_enable": True,
                "wandb_mode": "offline",
                "policy_n_obs_steps": 1,
                "policy_chunk_size": 50,
                "policy_n_action_steps": 50,
            }
            for field_name, value in pi05_defaults.items():
                if field_name not in fields_set or self._is_pi05_stale_training_default(field_name, getattr(request, field_name, None)):
                    updates[field_name] = value
            requested_wandb = bool(updates.get("wandb_enable", request.wandb_enable))
            requested_wandb_mode = str(updates.get("wandb_mode", request.wandb_mode or "") or "").strip().lower()
            requested_wandb_base_url = str(updates.get("wandb_base_url", request.wandb_base_url or "") or "").strip()
            if requested_wandb:
                if requested_wandb_mode == "local":
                    updates["wandb_mode"] = "online"
                    if not requested_wandb_base_url:
                        updates["wandb_base_url"] = self._wandb_local_url(request)
                elif requested_wandb_base_url and not requested_wandb_mode:
                    updates["wandb_mode"] = "online"
                elif (
                    not requested_wandb_mode
                    or (
                        requested_wandb_mode == "online"
                        and not self._wandb_api_key_available()
                        and not self._is_local_wandb_url(requested_wandb_base_url)
                    )
                ):
                    updates["wandb_mode"] = "offline"
            else:
                updates["wandb_mode"] = "disabled"
            pretrained = str(request.policy_pretrained_path or "").strip()
            if not self._is_valid_policy_source_ref(pretrained) or self._is_pi05_base_policy_ref(pretrained):
                updates["policy_pretrained_path"] = self._pi05_compatible_base_policy_ref()
        elif self._is_xvla_policy(policy_type):
            fields_set = set(request.model_fields_set)
            xvla_defaults: dict[str, Any] = {
                "steps": 20000,
            }
            for field_name, value in xvla_defaults.items():
                if field_name not in fields_set:
                    updates[field_name] = value
            pretrained = str(request.policy_pretrained_path or "").strip()
            if not self._is_valid_policy_source_ref(pretrained):
                updates["policy_pretrained_path"] = self.config.xvla_base_policy
        elif self._is_smolvla_policy(policy_type):
            fields_set = set(request.model_fields_set)
            smolvla_defaults: dict[str, Any] = {
                "batch_size": 8,
                "steps": 20000,
                "num_workers": 4,
                "eval_batch_size": None,
                "eval_freq": 20000,
                "log_freq": 200,
                "save_freq": 20000,
                "policy_n_obs_steps": 1,
                "policy_chunk_size": 50,
                "policy_n_action_steps": 50,
            }
            for field_name, value in smolvla_defaults.items():
                if field_name not in fields_set:
                    updates[field_name] = value
            pretrained = str(request.policy_pretrained_path or "").strip()
            if not self._is_valid_policy_source_ref(pretrained):
                updates["policy_pretrained_path"] = self.config.smolvla_base_policy
        next_request = request.model_copy(update=updates)
        if self._is_pi05_policy(policy_type):
            return (
                next_request,
                f"using Pi0.5 runtime env={self.config.pi05_conda_env_name} source={next_request.policy_pretrained_path}",
            )
        if self._is_xvla_policy(policy_type):
            return (
                next_request,
                f"using X-VLA runtime env={self.config.xvla_conda_env_name} source={next_request.policy_pretrained_path}",
            )
        if self._is_smolvla_policy(policy_type):
            return (
                next_request,
                f"using SmolVLA runtime env={self.config.smolvla_conda_env_name} source={next_request.policy_pretrained_path}",
            )
        return next_request, f"using LeRobot runtime env={self.config.conda_env_name}"

    @staticmethod
    def _is_pi05_stale_training_default(field_name: str, value: Any) -> bool:
        if field_name != "log_freq":
            return False
        try:
            return int(value) == 200
        except (TypeError, ValueError):
            return False

    def _validate_pi05_train_request(self, request: LeRobotSessionRequest) -> None:
        errors: list[str] = []
        if int(request.batch_size) > 32:
            errors.append(f"batch_size={request.batch_size} exceeds the Pi0.5 reference limit 32")
        if int(request.num_workers) > 20:
            errors.append(f"num_workers={request.num_workers} exceeds the local Pi0.5 limit 20")
        if request.policy_n_obs_steps is not None and int(request.policy_n_obs_steps) > 1:
            errors.append(f"policy.n_obs_steps={request.policy_n_obs_steps} is not a Pi0.5 default; use 1 unless you intentionally modify the policy")
        if request.eval_batch_size is not None and int(request.eval_batch_size) > 8:
            errors.append(f"eval.batch_size={request.eval_batch_size} exceeds the local Pi0.5 limit 8")
        if errors:
            raise ValueError("Pi0.5 training payload rejected: " + "; ".join(errors))

    @staticmethod
    def _wandb_api_key_available() -> bool:
        if os.environ.get("WANDB_API_KEY", "").strip():
            return True
        candidates = (
            Path.home() / ".netrc",
            Path.home() / ".config" / "wandb" / "settings",
            Path.home() / ".wandb" / "settings",
        )
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "api.wandb.ai" in text or "api_key" in text:
                return True
        return False

    @staticmethod
    def _is_local_wandb_url(value: str) -> bool:
        clean = str(value or "").strip().lower()
        return clean.startswith("http://127.0.0.1:") or clean.startswith("http://localhost:")

    def _wandb_local_port(self, request: LeRobotSessionRequest) -> int:
        if request.wandb_local_port:
            return _safe_int(request.wandb_local_port, self.config.wandb_local_port, minimum=1, maximum=65535)
        base_url = str(request.wandb_base_url or self.config.wandb_local_base_url or "").strip()
        match = re.search(r":(\d+)(?:/)?$", base_url)
        if match:
            return _safe_int(match.group(1), self.config.wandb_local_port, minimum=1, maximum=65535)
        return self.config.wandb_local_port

    def _wandb_local_url(self, request: LeRobotSessionRequest) -> str:
        clean = str(request.wandb_base_url or "").strip()
        if clean:
            return clean.rstrip("/")
        configured = str(self.config.wandb_local_base_url or "").strip().rstrip("/")
        if configured:
            return configured
        return f"http://127.0.0.1:{self._wandb_local_port(request)}"

    def _wandb_local_command(self, action: str, port: int) -> list[str]:
        base = [self.config.conda_executable, "run", "--no-capture-output", "-n", self.config.pi05_conda_env_name, "wandb", "server"]
        if action == "stop":
            return base + ["stop"]
        return base + ["start", "--port", str(port), "--no-daemon"]

    @staticmethod
    def _wandb_local_amd64_binfmt_command() -> list[str]:
        return ["docker", "run", "--privileged", "--rm", "tonistiigi/binfmt", "--install", "amd64"]

    def _install_wandb_local_amd64_binfmt(self) -> dict[str, Any]:
        command = self._wandb_local_amd64_binfmt_command()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "command": command, "error": str(exc)}
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        return {
            "ok": completed.returncode == 0,
            "command": command,
            "returncode": completed.returncode,
            "output": output[-4000:],
        }

    @staticmethod
    def _wandb_local_port_ready(url: str, *, timeout_s: float = 0.8) -> bool:
        parsed = urlparse(str(url or "").strip())
        host = parsed.hostname or "127.0.0.1"
        if parsed.port:
            port = parsed.port
        elif parsed.scheme == "https":
            port = 443
        else:
            port = 80
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except OSError:
            return False

    @staticmethod
    def _wandb_local_failure_from_log(log_tail: str) -> tuple[str, str] | None:
        text = str(log_tail or "")
        lowered = text.lower()
        if "exec format error" in lowered:
            return (
                "WANDB_LOCAL_PLATFORM_EMULATION_REQUIRED",
                "W&B local Docker image is amd64. Register linux/amd64 binfmt/QEMU support, then restart W&B local server.",
            )
        if "cannot connect to the docker daemon" in lowered:
            return ("WANDB_LOCAL_DOCKER_UNAVAILABLE", "Docker daemon is not reachable for W&B local server.")
        if "port is already allocated" in lowered or "address already in use" in lowered or "bind:" in lowered:
            return ("WANDB_LOCAL_PORT_BUSY", "W&B local server port is already in use.")
        if "docker: error" in lowered or "error response from daemon" in lowered:
            return ("WANDB_LOCAL_DOCKER_ERROR", "Docker failed while starting W&B local server.")
        return None

    def _wait_for_wandb_local_ready(
        self,
        url: str,
        session: dict[str, Any],
        *,
        timeout_s: float,
    ) -> tuple[bool, tuple[str, str] | None]:
        deadline = time.monotonic() + max(1.0, timeout_s)
        session_id = str(session.get("session_id") or "")
        while time.monotonic() < deadline:
            log_tail = self._tail_file(str(session.get("log_path", "")), max_chars=12000)
            failure = self._wandb_local_failure_from_log(log_tail)
            if failure:
                return False, failure
            if self._wandb_local_port_ready(url):
                return True, None
            process = self._processes.get(session_id)
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    session["returncode"] = returncode
                    self._close_log_handle(session_id)
                    failure = self._wandb_local_failure_from_log(self._tail_file(str(session.get("log_path", "")), max_chars=12000))
                    if failure:
                        return False, failure
                    return False, ("WANDB_LOCAL_EXITED_BEFORE_READY", f"W&B local server process exited before {url} started listening.")
            time.sleep(1.0)
        return False, None

    def _is_pi05_base_policy_ref(self, value: str) -> bool:
        clean = str(value or "").strip().rstrip("/")
        configured = str(self.config.pi05_base_policy or "lerobot/pi05_base").strip().rstrip("/")
        return clean in {"lerobot/pi05_base", configured}

    def _pi05_compatible_base_policy_ref(self) -> str:
        snapshots_root = self.config.pi05_hf_home / "hub" / "models--lerobot--pi05_base" / "snapshots"
        candidates: list[tuple[int, int, float, str]] = []
        try:
            snapshots = [path for path in snapshots_root.iterdir() if path.is_dir()]
        except OSError:
            snapshots = []
        for snapshot in snapshots:
            model_path = snapshot / "model.safetensors"
            preprocessor_path = snapshot / "policy_preprocessor.json"
            if not model_path.exists() or not preprocessor_path.exists():
                continue
            try:
                preprocessor_text = preprocessor_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "relative_actions_processor" in preprocessor_text:
                continue
            has_config = 1 if (snapshot / "config.json").exists() else 0
            has_postprocessor = 1 if (snapshot / "policy_postprocessor.json").exists() else 0
            try:
                modified = snapshot.stat().st_mtime
            except OSError:
                modified = 0.0
            candidates.append((has_config, has_postprocessor, modified, str(snapshot)))
        if not candidates:
            return self.config.pi05_base_policy
        return max(candidates)[3]

    def _train_extra_args_with_policy_defaults(self, request: LeRobotSessionRequest) -> list[str]:
        args = list(request.train_extra_args or [])
        policy_type = self._canonical_policy_type(request.policy_type)
        if self._is_pi05_policy(policy_type):
            defaults = [
                "--policy.compile_model=true",
                "--policy.gradient_checkpointing=true",
                "--policy.dtype=bfloat16",
                "--policy.freeze_vision_encoder=false",
                "--policy.train_expert_only=false",
            ]
        elif self._is_xvla_policy(policy_type):
            defaults = [
                "--policy.dtype=bfloat16",
                "--policy.action_mode=auto",
                "--policy.freeze_vision_encoder=false",
                "--policy.freeze_language_encoder=false",
                "--policy.train_policy_transformer=true",
                "--policy.train_soft_prompts=true",
            ]
        elif self._is_smolvla_policy(policy_type):
            defaults = [
                "--policy.freeze_vision_encoder=true",
                "--policy.train_expert_only=true",
                "--policy.train_state_proj=true",
            ]
        else:
            return args
        # Keep policy-specific LeRobot reference flags single-sourced when the GUI switches presets.
        forced_keys = {item.split("=", 1)[0] for item in defaults}
        if self._is_pi05_policy(policy_type):
            forced_keys.add("--policy.normalization_mapping")
        filtered = [item for item in args if str(item).split("=", 1)[0] not in forced_keys]
        return defaults + filtered

    @staticmethod
    def _canonical_policy_type(policy_type: str) -> str:
        clean = str(policy_type or "act").strip().lower().replace("_", "").replace("-", "").replace(".", "")
        if clean in {"pi05", "pi005", "pi05base"}:
            return "pi05"
        if clean == "pi0fast":
            return "pi0fast"
        if clean in {"xvla", "xvlabase"}:
            return "xvla"
        if clean in {"smolvla", "smolvlabase"}:
            return "smolvla"
        return str(policy_type or "act").strip() or "act"

    def _is_pi05_policy(self, policy_type: str) -> bool:
        return self._canonical_policy_type(policy_type) == "pi05"

    def _is_xvla_policy(self, policy_type: str) -> bool:
        return self._canonical_policy_type(policy_type) == "xvla"

    def _is_smolvla_policy(self, policy_type: str) -> bool:
        return self._canonical_policy_type(policy_type) == "smolvla"

    def _is_vla_policy(self, policy_type: str) -> bool:
        canonical = self._canonical_policy_type(policy_type)
        return canonical in {"xvla", "smolvla"}

    def _uses_pi05_dataset_runtime(self, policy_type: str) -> bool:
        canonical = self._canonical_policy_type(policy_type)
        return canonical in {"pi05", "xvla", "smolvla"}

    def _train_video_backend(self, policy_type: str, request: LeRobotSessionRequest | None = None) -> str:
        preferred = str(self.config.pi05_video_backend if self._is_pi05_policy(policy_type) else self.config.train_video_backend).strip() or "torchcodec"
        fallback = str(self.config.train_video_backend_fallback or "pyav").strip() or "pyav"
        if preferred != "torchcodec":
            return preferred
        if request is None or (request.runtime_mode or request.mode) != "live":
            return preferred
        if self._is_pi05_policy(policy_type):
            env_name = self.config.pi05_conda_env_name
        elif self._is_xvla_policy(policy_type):
            env_name = self.config.xvla_conda_env_name
        elif self._is_smolvla_policy(policy_type):
            env_name = self.config.smolvla_conda_env_name
        else:
            env_name = self.config.conda_env_name
        return preferred if self._conda_env_has_module(env_name, "torchcodec") else fallback

    def _conda_env_has_module(self, env_name: str, module_name: str) -> bool:
        cache_key = (str(env_name), str(module_name))
        if cache_key in self._module_available_cache:
            return self._module_available_cache[cache_key]
        env_python = Path.home() / "miniconda3" / "envs" / str(env_name) / "bin" / "python"
        if not env_python.exists():
            self._module_available_cache[cache_key] = False
            return False
        try:
            completed = subprocess.run(
                [str(env_python), "-c", f"import {module_name}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            available = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            available = False
        self._module_available_cache[cache_key] = available
        return available

    def _is_valid_policy_source_ref(self, value: str) -> bool:
        clean = str(value or "").strip()
        if not clean:
            return False
        if clean.startswith(("~", "/", ".")):
            return Path(clean).expanduser().exists()
        if "://" in clean:
            return False
        return "/" in clean

    def _validated_train_extra_args(self, raw_args: list[str]) -> list[str]:
        """Accept explicit advanced train args only as one safe `--key=value` item per line."""
        safe: list[str] = []
        for raw in raw_args or []:
            item = str(raw).strip()
            if not item:
                continue
            if not item.startswith("--") or " " in item or UNSAFE_ARGUMENT_RE.search(item):
                raise ValueError(f"Unsafe train extra argument rejected: {item}")
            safe.append(item)
        return safe

    def _train_config_summary(self, profile: RobotProfile, request: LeRobotSessionRequest) -> dict[str, Any]:
        dataset_mix = self._train_dataset_mix_summary(request)
        fidelity_weights = self._train_fidelity_summary(request)
        return {
            "profile_id": profile.profile_id,
            "policy_type": request.policy_type or "act",
            "policy_pretrained_path": request.policy_pretrained_path or "",
            "dataset_repo_id": request.dataset_repo_id or "local/fake_lerobot_dataset",
            "dataset_root": request.dataset_root or str(self.config.dataset_root),
            "dataset_video_backend": self._train_video_backend(request.policy_type or "act", request),
            "output_dir": request.output_dir or str(self.config.output_root / (request.job_name or self._default_train_job_name(profile, request))),
            "job_name": request.job_name or self._default_train_job_name(profile, request),
            "policy_repo_id": request.policy_repo_id or self._default_train_policy_repo_id(profile, request),
            "device": request.device or "cuda",
            "batch_size": int(request.batch_size),
            "steps": int(request.steps),
            "num_workers": int(request.num_workers),
            "eval_freq": int(request.eval_freq),
            "log_freq": int(request.log_freq),
            "save_freq": int(request.save_freq),
            "save_checkpoint": bool(request.save_checkpoint),
            "wandb_enable": bool(request.wandb_enable),
            "wandb_mode": request.wandb_mode or "",
            "wandb_project": request.wandb_project or "",
            "wandb_base_url": request.wandb_base_url or "",
            "dataset_mix": dataset_mix,
            "dataset_mix_weights": dataset_mix["weights"],
            "dataset_mix_effective_counts": dataset_mix["effective_counts"],
            "fidelity_weights": fidelity_weights,
            "fidelity_loss_weights": fidelity_weights["weights"],
        }

    @staticmethod
    def _training_preflight_progress(session: dict[str, Any]) -> dict[str, Any]:
        stages = [
            {"stage": "resolve_dataset", "status": "ok", "detail": str(session.get("dataset_path") or "")},
            {"stage": "inspect_sidecars", "status": "ok", "detail": "raw depth, Isaac RGB-D, Isaac augmentation, and Isaac Lab synthetic summaries inspected"},
            {"stage": "apply_dataset_mix", "status": "ok", "detail": json.dumps(session.get("dataset_mix") or {}, ensure_ascii=False)},
            {"stage": "apply_fidelity_weights", "status": "ok", "detail": json.dumps(session.get("fidelity_weights") or {}, ensure_ascii=False)},
            {"stage": "build_train_command", "status": "ok", "detail": str(session.get("job_name") or "")},
        ]
        total = len(stages)
        return {
            "stage": "ready_to_start",
            "done": total,
            "total": total,
            "percent": 100.0,
            "message": "Training preflight complete; process can start",
            "stages": stages,
        }

    def _visualization_episode_indices(self, request: LeRobotSessionRequest, dataset_path: Path | None = None) -> list[int]:
        total_episodes = self._dataset_total_episodes(dataset_path) if dataset_path is not None else 0
        raw = str(getattr(request, "episode_indices", "") or "").strip()
        fallback = [_safe_int(getattr(request, "episode_index", 0), 0, minimum=0)]
        if not raw:
            return fallback
        lowered = raw.lower()
        if lowered in {"all", "*"}:
            return list(range(total_episodes)) if total_episodes > 0 else fallback
        parsed: list[int] = []
        for part in re.split(r"[\s,;]+", raw):
            clean = part.strip()
            if not clean:
                continue
            if "-" in clean:
                left, right = clean.split("-", 1)
                try:
                    start = int(left)
                    end = int(right)
                except ValueError:
                    continue
                if end < start:
                    start, end = end, start
                parsed.extend(range(max(0, start), max(0, end) + 1))
                continue
            try:
                parsed.append(max(0, int(clean)))
            except ValueError:
                continue
        unique = sorted(dict.fromkeys(parsed))
        if total_episodes > 0:
            unique = [item for item in unique if item < total_episodes]
        return unique[:200] or fallback

    @staticmethod
    def _dataset_total_episodes(dataset_path: Path | None) -> int:
        if dataset_path is None:
            return 0
        info_path = Path(dataset_path) / "meta" / "info.json"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        return _safe_int(info.get("total_episodes"), 0, minimum=0)

    def _visualization_args(self, request: LeRobotSessionRequest) -> tuple[list[str], dict[str, Any]]:
        """Build the installed LeRobot dataset visualizer command arguments."""
        viz_info = self._visualization_dataset_refs(request)
        dataset_path = Path(str(viz_info["dataset_path"])).expanduser().resolve()
        episode_indices = self._visualization_episode_indices(request, dataset_path)
        episode_index = episode_indices[0]
        tool = request.visualization_tool or "rerun"
        dataset_root_for_lerobot = str(viz_info["dataset_path"])
        requested_web_port = _safe_int(request.visualization_web_port, 9092, minimum=1, maximum=65535)
        requested_ws_port = _safe_int(request.visualization_ws_port, 9089, minimum=1, maximum=65535)
        web_port = self._select_free_tcp_port(requested_web_port)
        ws_port = self._select_free_tcp_port(requested_ws_port, avoid={web_port})
        port_auto_selected = web_port != requested_web_port or ws_port != requested_ws_port
        rerun_ws_url = f"ws://localhost:{ws_port}"
        rerun_web_url = f"http://localhost:{web_port}"
        rerun_viewer_url = f"{rerun_web_url}/?url={quote(rerun_ws_url, safe=':/')}"
        viz_info.update(
            {
                "tool": tool,
                "episode_index": int(episode_index),
                "episode_indices": episode_indices,
                "episode_indices_input": str(getattr(request, "episode_indices", "") or ""),
                "visualization_mode": request.visualization_mode,
                "batch_size": int(request.visualization_batch_size),
                "num_workers": int(request.visualization_num_workers),
                "requested_web_port": requested_web_port,
                "requested_ws_port": requested_ws_port,
                "web_port": web_port,
                "ws_port": ws_port,
                "port_auto_selected": port_auto_selected,
                "rerun_ws_url": rerun_ws_url,
                "rerun_web_url": rerun_web_url,
                "save": bool(request.visualization_save),
                "lerobot_root": dataset_root_for_lerobot,
            }
        )
        if tool == "rerun" and request.visualization_mode == "distant" and not request.visualization_save:
            viz_info["viewer_url"] = rerun_viewer_url
        if tool == "html":
            output_dir = _resolve_path(
                self.config.repo_root,
                request.visualization_output_dir or str(self.config.output_root / "visualize_dataset" / self._slug(str(viz_info["repo_id"]))),
            ).resolve()
            if not self._is_under_allowed_roots(output_dir):
                raise ValueError(f"Visualization output_dir is outside allowed roots: {output_dir}")
            host = "127.0.0.1"
            repo_parts = str(viz_info["repo_id"]).split("/", 1)
            viewer_path = f"/{repo_parts[0]}/{repo_parts[1]}/episode_{episode_index}" if len(repo_parts) == 2 else f"/?dataset={viz_info['repo_id']}&episode={episode_index}"
            viz_info.update(
                {
                    "output_dir": str(output_dir),
                    "viewer_url": f"http://{host}:{web_port}{viewer_path}",
                }
            )
            return [
                f"--repo-id={viz_info['repo_id']}",
                f"--root={dataset_root_for_lerobot}",
                "--episodes",
                str(episode_index),
                f"--output-dir={output_dir}",
                "--serve=1",
                f"--host={host}",
                f"--port={web_port}",
                "--force-override=1",
                f"--tolerance-s={float(request.visualization_tolerance_s)}",
            ], viz_info
        args = [
            f"--repo-id={viz_info['repo_id']}",
            f"--episode-index={episode_index}",
            f"--root={dataset_root_for_lerobot}",
            f"--batch-size={int(request.visualization_batch_size)}",
            f"--num-workers={int(request.visualization_num_workers)}",
            f"--mode={request.visualization_mode}",
            f"--web-port={web_port}",
            f"--ws-port={ws_port}",
            f"--tolerance-s={float(request.visualization_tolerance_s)}",
        ]
        if request.visualization_save:
            output_dir = _resolve_path(
                self.config.repo_root,
                request.visualization_output_dir or str(self.config.output_root / "visualize_dataset"),
            ).resolve()
            if not self._is_under_allowed_roots(output_dir):
                raise ValueError(f"Visualization output_dir is outside allowed roots: {output_dir}")
            args.extend([f"--save={1}", f"--output-dir={output_dir}"])
            viz_info["output_dir"] = str(output_dir)
        return args, viz_info

    @staticmethod
    def _tcp_port_available(port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, int(port)))
            return True
        except OSError:
            return False

    def _select_free_tcp_port(self, preferred_port: int, *, avoid: set[int] | None = None) -> int:
        avoid_ports = set(avoid or set())
        preferred = _safe_int(preferred_port, 9090, minimum=1, maximum=65535)
        for offset in range(0, 100):
            candidate = preferred + offset
            if candidate > 65535:
                break
            if candidate in avoid_ports:
                continue
            if self._tcp_port_available(candidate):
                return candidate
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _visualization_command(self, request: LeRobotSessionRequest, viz_info: dict[str, Any], args: list[str]) -> list[str]:
        entrypoint = ["python", "-m", "lerobot.scripts.visualize_dataset_html"]
        if str(viz_info.get("tool") or "html") == "rerun":
            entrypoint = ["python", "-m", "lerobot.scripts.visualize_dataset"]
        return [self.config.conda_executable, "run", "--no-capture-output", "-n", self.config.conda_env_name] + entrypoint + args

    def _visualization_dataset_refs(self, request: LeRobotSessionRequest) -> dict[str, str]:
        configured_root = _resolve_path(self.config.repo_root, request.dataset_root).resolve() if request.dataset_root else self.config.dataset_root.resolve()
        repo_id = str(request.dataset_repo_id or "").strip().strip("/")
        raw_dataset_path = str(request.dataset_path or "").strip()
        if raw_dataset_path:
            dataset_path = _resolve_path(self.config.repo_root, raw_dataset_path).resolve()
            if not self._is_under_allowed_roots(dataset_path):
                raise ValueError(f"Dataset path is outside allowed roots: {dataset_path}")
            if not repo_id:
                repo_id, configured_root = self._repo_id_root_from_dataset_path(dataset_path, configured_root)
        else:
            if not repo_id:
                repo_id = "local/fake_lerobot_dataset"
            dataset_path = (configured_root / repo_id).resolve()
        if not repo_id:
            raise ValueError("LeRobot visualization requires dataset_repo_id or a dataset_path that can be mapped to repo-id/root.")
        info_path = dataset_path / "meta" / "info.json"
        if not info_path.is_file():
            raise ValueError(f"LeRobot visualization requires a completed local dataset with meta/info.json: {info_path}")
        return {
            "dataset_path": str(dataset_path),
            "dataset_root": str(configured_root),
            "repo_id": repo_id,
        }

    @staticmethod
    def _repo_id_root_from_dataset_path(dataset_path: Path, configured_root: Path) -> tuple[str, Path]:
        try:
            rel = dataset_path.relative_to(configured_root)
            if rel.parts:
                return "/".join(rel.parts), configured_root
        except ValueError:
            pass
        if len(dataset_path.parts) >= 2:
            return f"{dataset_path.parent.name}/{dataset_path.name}", dataset_path.parent.parent
        return dataset_path.name, dataset_path.parent

    def _train_request_with_local_dataset(self, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        """For live training, point LeRobot at a completed local dataset directory.

        The installed LeRobot train command treats --dataset.root as the dataset
        directory itself, not the parent cache directory. If the GUI still points
        at a base name such as jin/record-test, prefer the newest completed
        timestamped local recording from the same prefix.
        """
        mode = request.runtime_mode or request.mode
        if mode != "live":
            return request, request.dataset_path or request.dataset_repo_id or "fake dataset"

        configured_root = _resolve_path(self.config.repo_root, request.dataset_root).resolve() if request.dataset_root else self.config.dataset_root.resolve()
        repo_id = str(request.dataset_repo_id or "").strip().strip("/")
        raw_dataset_path = str(request.dataset_path or "").strip()

        if raw_dataset_path:
            dataset_path = _resolve_path(self.config.repo_root, raw_dataset_path).resolve()
            if not self._is_under_allowed_roots(dataset_path):
                raise ValueError(f"Training dataset path is outside allowed roots: {dataset_path}")
            if not repo_id:
                repo_id, _ = self._repo_id_root_from_dataset_path(dataset_path, configured_root)
            if self._is_trainable_lerobot_dataset(dataset_path):
                return self._train_request_for_dataset(request, repo_id, dataset_path), f"{repo_id} at {dataset_path}"
            latest = self._latest_local_train_dataset(configured_root, repo_id or dataset_path.name)
            if latest:
                latest_repo, latest_path = latest
                return self._train_request_for_dataset(request, latest_repo, latest_path), f"{latest_repo} at {latest_path}"
            raise ValueError(f"Live training dataset is incomplete or missing required LeRobot files: {dataset_path}")

        if repo_id:
            dataset_path = (configured_root / repo_id).resolve()
            if self._is_trainable_lerobot_dataset(dataset_path):
                return self._train_request_for_dataset(request, repo_id, dataset_path), f"{repo_id} at {dataset_path}"
        latest = self._latest_local_train_dataset(configured_root, repo_id)
        if latest:
            latest_repo, latest_path = latest
            return self._train_request_for_dataset(request, latest_repo, latest_path), f"{latest_repo} at {latest_path}"

        target = str((configured_root / repo_id).resolve()) if repo_id else str(configured_root)
        raise ValueError(
            "Live training requires a completed local LeRobot dataset. "
            f"No trainable dataset was found for repo_id='{repo_id or '<empty>'}' under {target}. "
            "Use a recorded dataset folder containing meta/tasks.jsonl, meta/episodes.jsonl, "
            "meta/episodes_stats.jsonl, and data/*.parquet."
        )

    @staticmethod
    def _train_request_for_dataset(request: LeRobotSessionRequest, repo_id: str, dataset_path: Path) -> LeRobotSessionRequest:
        dataset_path = dataset_path.resolve()
        return request.model_copy(
            update={
                "dataset_repo_id": repo_id,
                "dataset_root": str(dataset_path),
                "dataset_path": str(dataset_path),
            }
        )

    def _train_request_with_pi05_dataset_version(self, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        """Use a v3.0 local dataset copy for Pi0.5-family policies without mutating the recorded v2.1 dataset."""
        mode = request.runtime_mode or request.mode
        if mode != "live" or not self._uses_pi05_dataset_runtime(request.policy_type):
            return request, "dataset format unchanged"

        runtime_label = {
            "pi05": "Pi0.5",
            "xvla": "X-VLA",
            "smolvla": "SmolVLA",
        }.get(self._canonical_policy_type(request.policy_type), "Pi0.5-family")
        raw_dataset_path = str(request.dataset_path or request.dataset_root or "").strip()
        if not raw_dataset_path:
            return request, "dataset format unchanged"
        dataset_path = _resolve_path(self.config.repo_root, raw_dataset_path).resolve()
        dataset_version = self._lerobot_dataset_codebase_version(dataset_path)
        if dataset_version == "v3.0":
            repo_id, root = self._repo_id_root_from_dataset_path(dataset_path, self.config.dataset_root.resolve())
            self._ensure_pi05_quantile_stats(repo_id, root)
            return request, f"{runtime_label} dataset already v3.0 at {dataset_path}; quantile stats ready"
        if dataset_version != "v2.1":
            raise ValueError(
                f"{runtime_label} live training requires a LeRobot v3.0 dataset. "
                f"Selected dataset has codebase_version='{dataset_version or 'unknown'}' at {dataset_path}."
            )

        converted_repo_id = self._pi05_v30_dataset_repo_id(request.dataset_repo_id, dataset_path)
        converted_root = self.config.dataset_root.resolve()
        converted_path = (converted_root / converted_repo_id).resolve()
        if not self._is_under_allowed_roots(converted_path):
            raise ValueError(f"Pi0.5 converted dataset path is outside allowed roots: {converted_path}")
        if self._pi05_v30_dataset_is_current(dataset_path, converted_path):
            self._attach_pi05_sidecar_from_source(dataset_path, converted_path)
        else:
            self._prepare_pi05_v30_dataset_copy(dataset_path, converted_repo_id, converted_root)
        if self._lerobot_dataset_codebase_version(converted_path) != "v3.0":
            raise ValueError(f"Pi0.5 dataset conversion did not produce a v3.0 dataset at {converted_path}")
        self._ensure_pi05_quantile_stats(converted_repo_id, converted_root)

        return (
            self._train_request_for_dataset(request, converted_repo_id, converted_path),
            f"{runtime_label} converted {request.dataset_repo_id or dataset_path.name} v2.1 -> {converted_repo_id} v3.0 at {converted_path}",
        )

    def _ensure_train_dataset_jsonl_metadata_compat(self, request: LeRobotSessionRequest) -> str:
        """Materialize JSONL metadata that the installed LeRobot train runtime still requires.

        Some local v3 datasets keep metadata in parquet files only. The current
        training runtime loaded in this workspace still opens tasks.jsonl,
        episodes.jsonl, and episodes_stats.jsonl, then falls back to the Hub if
        those files are absent. Generate the compatibility files inside the
        selected local dataset without changing frames, videos, actions, or
        source parquet files.
        """
        if (request.runtime_mode or request.mode) != "live":
            return "metadata compatibility unchanged"
        raw_dataset_path = str(request.dataset_path or request.dataset_root or "").strip()
        if not raw_dataset_path:
            return "metadata compatibility unchanged"
        dataset_path = _resolve_path(self.config.repo_root, raw_dataset_path).resolve()
        info_path = dataset_path / "meta" / "info.json"
        if not info_path.is_file():
            return "metadata compatibility unchanged"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "metadata compatibility unchanged"
        if str(info.get("codebase_version") or "") != "v3.0":
            return "metadata compatibility unchanged"

        generated: list[str] = []
        tasks_path = dataset_path / "meta" / "tasks.jsonl"
        if not tasks_path.is_file():
            self._write_jsonl(tasks_path, self._v30_tasks_jsonl_rows(dataset_path))
            generated.append("meta/tasks.jsonl")
        episodes_path = dataset_path / "meta" / "episodes.jsonl"
        episode_rows, episode_stats_rows = self._v30_episode_jsonl_rows(dataset_path)
        if self._ensure_v30_legacy_loader_path_templates(dataset_path, info_path, info, episode_rows):
            generated.append("meta/info.json path templates")
        if not episodes_path.is_file():
            self._write_jsonl(episodes_path, episode_rows)
            generated.append("meta/episodes.jsonl")
        episode_stats_path = dataset_path / "meta" / "episodes_stats.jsonl"
        if not episode_stats_path.is_file():
            self._write_jsonl(episode_stats_path, episode_stats_rows)
            generated.append("meta/episodes_stats.jsonl")
        if generated:
            return "LeRobot v3 parquet metadata jsonl materialized: " + ", ".join(generated)
        return "LeRobot v3 metadata jsonl ready"

    def _ensure_v30_legacy_loader_path_templates(
        self,
        dataset_path: Path,
        info_path: Path,
        info: dict[str, Any],
        episode_rows: list[dict[str, Any]],
    ) -> bool:
        updates: dict[str, str] = {}
        data_path = str(info.get("data_path") or "")
        if self._has_v30_chunk_file_placeholders(data_path):
            data_file_index = self._constant_episode_metadata_int(episode_rows, "data/file_index")
            if data_file_index is not None and self._chunk_files_exist(dataset_path, episode_rows, "data", data_file_index, ".parquet"):
                updates["data_path"] = f"data/chunk-{{episode_chunk:03d}}/file-{data_file_index:03d}.parquet"

        video_path = str(info.get("video_path") or "")
        if self._has_v30_chunk_file_placeholders(video_path):
            video_keys = self._video_keys_from_info(info)
            video_file_index = self._constant_video_file_index(video_keys, episode_rows)
            if video_file_index is not None and self._video_chunk_files_exist(dataset_path, episode_rows, video_keys, video_file_index):
                updates["video_path"] = f"videos/{{video_key}}/chunk-{{episode_chunk:03d}}/file-{video_file_index:03d}.mp4"

        changed = False
        for key, value in updates.items():
            if info.get(key) != value:
                info[key] = value
                changed = True
        if changed:
            info_path.write_text(json.dumps(info, indent=4, ensure_ascii=False), encoding="utf-8")
        return changed

    @staticmethod
    def _has_v30_chunk_file_placeholders(template: str) -> bool:
        return "{chunk_index" in template or "{file_index" in template

    @staticmethod
    def _constant_episode_metadata_int(episode_rows: list[dict[str, Any]], key: str) -> int | None:
        values = {
            _safe_int(row.get(key), -1, minimum=-1)
            for row in episode_rows
            if row.get(key) is not None
        }
        if len(values) != 1:
            return None
        value = next(iter(values))
        return value if value >= 0 else None

    @staticmethod
    def _chunk_files_exist(dataset_path: Path, episode_rows: list[dict[str, Any]], prefix: str, file_index: int, suffix: str) -> bool:
        chunks = {
            _safe_int(row.get(f"{prefix}/chunk_index"), _safe_int(row.get("episode_index"), 0, minimum=0), minimum=0)
            for row in episode_rows
        }
        if not chunks:
            chunks = {0}
        for chunk_index in chunks:
            candidate = dataset_path / prefix / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}{suffix}"
            if not candidate.is_file():
                return False
        return True

    @staticmethod
    def _video_keys_from_info(info: dict[str, Any]) -> list[str]:
        return [
            key
            for key, feature in (info.get("features") or {}).items()
            if isinstance(feature, dict) and str(feature.get("dtype") or "") == "video"
        ]

    def _constant_video_file_index(self, video_keys: list[str], episode_rows: list[dict[str, Any]]) -> int | None:
        if not video_keys:
            return None
        values: set[int] = set()
        for video_key in video_keys:
            value = self._constant_episode_metadata_int(episode_rows, f"videos/{video_key}/file_index")
            if value is None:
                return None
            values.add(value)
        if len(values) != 1:
            return None
        return next(iter(values))

    @staticmethod
    def _video_chunk_files_exist(dataset_path: Path, episode_rows: list[dict[str, Any]], video_keys: list[str], file_index: int) -> bool:
        for video_key in video_keys:
            chunks = {
                _safe_int(row.get(f"videos/{video_key}/chunk_index"), _safe_int(row.get("episode_index"), 0, minimum=0), minimum=0)
                for row in episode_rows
            }
            if not chunks:
                chunks = {0}
            for chunk_index in chunks:
                candidate = dataset_path / "videos" / video_key / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.mp4"
                if not candidate.is_file():
                    return False
        return True

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def _v30_tasks_jsonl_rows(self, dataset_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for parquet_path in self._v30_metadata_parquet_paths(dataset_path, "tasks"):
            table = self._read_v30_metadata_parquet(parquet_path, "tasks")
            data = table.to_pydict()
            row_count = self._column_row_count(data)
            for row_index in range(row_count):
                task_index = _safe_int(self._column_value(data, "task_index", row_index), len(rows), minimum=0)
                task = self._task_name_from_v30_task_row(data, row_index)
                if not task:
                    continue
                rows.append({"task_index": task_index, "task": task})
        unique: dict[int, dict[str, Any]] = {}
        for row in rows:
            unique[int(row["task_index"])] = row
        if not unique:
            raise ValueError(f"LeRobot v3 metadata compatibility could not read any tasks from {dataset_path / 'meta'}")
        return [unique[index] for index in sorted(unique)]

    def _v30_episode_jsonl_rows(self, dataset_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        episode_rows: list[dict[str, Any]] = []
        episode_stats_rows: list[dict[str, Any]] = []
        global_stats = self._read_json_dict(dataset_path / "meta" / "stats.json")
        for parquet_path in self._v30_metadata_parquet_paths(dataset_path, "episodes"):
            table = self._read_v30_metadata_parquet(parquet_path, "episodes")
            data = table.to_pydict()
            row_count = self._column_row_count(data)
            for row_index in range(row_count):
                episode_index = _safe_int(self._column_value(data, "episode_index", row_index), len(episode_rows), minimum=0)
                length = _safe_int(self._column_value(data, "length", row_index), 0, minimum=0)
                if length <= 0:
                    start = _safe_int(self._column_value(data, "dataset_from_index", row_index), 0, minimum=0)
                    end = _safe_int(self._column_value(data, "dataset_to_index", row_index), start, minimum=start)
                    length = end - start
                tasks = self._episode_tasks_from_v30_row(data, row_index)
                episode_row = {
                    "episode_index": episode_index,
                    "tasks": tasks,
                    "length": length,
                }
                for key, values in data.items():
                    if key.startswith("stats/") or key in episode_row:
                        continue
                    if row_index < len(values):
                        episode_row[key] = self._json_safe(values[row_index])
                episode_rows.append(episode_row)

                stats = self._episode_stats_from_v30_row(data, row_index)
                if not stats:
                    stats = global_stats
                episode_stats_rows.append({"episode_index": episode_index, "stats": stats})

        episode_rows_by_index = {int(row["episode_index"]): row for row in episode_rows}
        episode_stats_by_index = {int(row["episode_index"]): row for row in episode_stats_rows}
        if not episode_rows_by_index:
            raise ValueError(f"LeRobot v3 metadata compatibility could not read any episodes from {dataset_path / 'meta'}")
        if not episode_stats_by_index:
            raise ValueError(f"LeRobot v3 metadata compatibility could not read any episode stats from {dataset_path / 'meta'}")
        return (
            [episode_rows_by_index[index] for index in sorted(episode_rows_by_index)],
            [episode_stats_by_index[index] for index in sorted(episode_stats_by_index)],
        )

    @staticmethod
    def _v30_metadata_parquet_paths(dataset_path: Path, stem: str) -> list[Path]:
        meta = dataset_path / "meta"
        direct = meta / f"{stem}.parquet"
        paths: list[Path] = []
        if direct.is_file():
            paths.append(direct)
        paths.extend(sorted((meta / stem).rglob("*.parquet")) if (meta / stem).is_dir() else [])
        return list(dict.fromkeys(path.resolve() for path in paths))

    @staticmethod
    def _read_v30_metadata_parquet(parquet_path: Path, label: str) -> Any:
        try:
            import pyarrow.parquet as pq
        except Exception as exc:  # noqa: BLE001 - optional outside the LeRobot runtime.
            raise ValueError(f"LeRobot v3 metadata compatibility requires pyarrow to read {label} parquet files.") from exc
        try:
            return pq.read_table(parquet_path)
        except Exception as exc:  # noqa: BLE001 - pyarrow has several concrete failures.
            raise ValueError(f"LeRobot v3 metadata compatibility could not read {label} parquet: {parquet_path}: {exc}") from exc

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _column_row_count(data: dict[str, list[Any]]) -> int:
        return max((len(values) for values in data.values() if isinstance(values, list)), default=0)

    @staticmethod
    def _column_value(data: dict[str, list[Any]], key: str, row_index: int) -> Any:
        values = data.get(key)
        if not isinstance(values, list) or row_index >= len(values):
            return None
        return values[row_index]

    def _task_name_from_v30_task_row(self, data: dict[str, list[Any]], row_index: int) -> str:
        for key in ("task", "__index_level_0__", "name"):
            value = self._column_value(data, key, row_index)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            task = str(value).strip()
            if task:
                return task
        return ""

    def _episode_tasks_from_v30_row(self, data: dict[str, list[Any]], row_index: int) -> list[str]:
        value = self._column_value(data, "tasks", row_index)
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is not None:
            task = str(value).strip()
            if task:
                return [task]
        return [row["task"] for row in self._v30_tasks_jsonl_rows_from_cacheable_data(data, row_index) if row.get("task")]

    def _v30_tasks_jsonl_rows_from_cacheable_data(self, data: dict[str, list[Any]], row_index: int) -> list[dict[str, Any]]:
        task = self._task_name_from_v30_task_row(data, row_index)
        if not task:
            return []
        return [{"task_index": _safe_int(self._column_value(data, "task_index", row_index), 0, minimum=0), "task": task}]

    def _episode_stats_from_v30_row(self, data: dict[str, list[Any]], row_index: int) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for key, values in data.items():
            if not key.startswith("stats/") or row_index >= len(values):
                continue
            self._set_nested_stats_value(stats, key.removeprefix("stats/").split("/"), self._json_safe(values[row_index]))
        return stats

    @classmethod
    def _set_nested_stats_value(cls, target: dict[str, Any], parts: list[str], value: Any) -> None:
        if not parts:
            return
        cursor = target
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = value

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass
        return value

    def _prepare_pi05_v30_dataset_copy(self, source_path: Path, converted_repo_id: str, converted_root: Path) -> None:
        converted_root = converted_root.resolve()
        target_path = (converted_root / converted_repo_id).resolve()
        if not self._is_generated_pi05_dataset_path(target_path):
            raise ValueError(f"Refusing to overwrite non-generated Pi0.5 dataset path: {target_path}")
        converted_root.mkdir(parents=True, exist_ok=True)
        generated_paths = [
            target_path,
            target_path.parent / f"{target_path.name}_old",
            target_path.parent / f"{target_path.name}_v30",
        ]
        for path in generated_paths:
            if not path.exists():
                continue
            if not self._is_generated_pi05_dataset_path(path):
                raise ValueError(f"Refusing to remove non-generated Pi0.5 dataset path: {path}")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, target_path, symlinks=True, ignore=shutil.ignore_patterns("sidecar"))
        self._run_pi05_v30_dataset_conversion(converted_repo_id, converted_root)
        self._attach_pi05_sidecar_from_source(source_path, target_path)

    def _run_pi05_v30_dataset_conversion(self, converted_repo_id: str, converted_root: Path) -> None:
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.pi05_conda_env_name,
            "python",
            "-m",
            "lerobot.datasets.v30.convert_dataset_v21_to_v30",
            "--repo-id",
            converted_repo_id,
            "--root",
            str(converted_root),
            "--push-to-hub=false",
            "--force-conversion",
        ]
        hf_home = self.config.pi05_hf_home
        env = {
            **os.environ,
            "HF_HOME": str(hf_home),
            "HF_HUB_CACHE": str(hf_home / "hub"),
            "HF_HUB_DISABLE_XET": "1",
            "PYTHONUNBUFFERED": "1",
        }
        cwd = self.config.pi05_repo_root if self.config.pi05_repo_root.exists() else self.config.repo_root
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=3600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Pi0.5 dataset v3.0 conversion timed out after 3600 seconds.") from exc
        if completed.returncode != 0:
            output = (completed.stdout or "").strip()
            tail = "\n".join(output.splitlines()[-30:])
            raise ValueError(f"Pi0.5 dataset v3.0 conversion failed with returncode={completed.returncode}:\n{tail}")

    def _attach_pi05_sidecar_from_source(self, source_path: Path, target_path: Path) -> None:
        """Preserve ATR sidecars after LeRobot v2.1->v3.0 conversion.

        The upstream converter rewrites the LeRobot dataset directory and only
        keeps standard meta/data files. ATR raw-depth, Isaac RGB-D, and
        augmentation sidecars are external to the LeRobot schema, so reattach
        them to the generated v3.0 copy for training-time adapters.
        """
        source_sidecar = source_path / "sidecar"
        target_sidecar = target_path / "sidecar"
        if not source_sidecar.is_dir():
            return
        if target_sidecar.is_symlink():
            try:
                if target_sidecar.resolve() == source_sidecar.resolve():
                    return
            except OSError:
                pass
        if target_sidecar.exists() or target_sidecar.is_symlink():
            if target_sidecar.is_symlink() or target_sidecar.is_file():
                target_sidecar.unlink()
            else:
                shutil.rmtree(target_sidecar)
        target_sidecar.parent.mkdir(parents=True, exist_ok=True)
        try:
            relative_source = os.path.relpath(source_sidecar, target_sidecar.parent)
            target_sidecar.symlink_to(relative_source, target_is_directory=True)
        except OSError as exc:
            raise ValueError(f"Pi0.5 v3.0 cache sidecar must be symlinked, not copied: {source_sidecar} -> {target_sidecar}") from exc

    def _ensure_pi05_quantile_stats(self, repo_id: str, dataset_root: Path) -> None:
        dataset_path = (Path(dataset_root).resolve() / repo_id).resolve()
        if self._pi05_dataset_has_quantile_stats(dataset_path):
            return
        self._run_pi05_quantile_stats_augmentation(repo_id, Path(dataset_root).resolve())
        if not self._pi05_dataset_has_quantile_stats(dataset_path):
            raise ValueError(f"Pi0.5 quantile stats augmentation did not produce q01/q99 stats at {dataset_path}")

    @staticmethod
    def _pi05_dataset_has_quantile_stats(dataset_path: Path) -> bool:
        stats_path = Path(dataset_path) / "meta" / "stats.json"
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(stats, dict):
            return False
        required_features = [feature for feature in ("observation.state", "action") if feature in stats]
        if not required_features:
            return False
        for feature in required_features:
            feature_stats = stats.get(feature)
            if not isinstance(feature_stats, dict) or "q01" not in feature_stats or "q99" not in feature_stats:
                return False
        return True

    def _run_pi05_quantile_stats_augmentation(self, repo_id: str, dataset_root: Path) -> None:
        script = """
from pathlib import Path
import json
import numpy as np
import pandas as pd

dataset_path = Path(__DATASET_PATH__)
stats_path = dataset_path / "meta" / "stats.json"
data_root = dataset_path / "data"

stats = json.loads(stats_path.read_text(encoding="utf-8"))
parquet_paths = sorted(data_root.glob("**/*.parquet"))
if not parquet_paths:
    raise RuntimeError(f"No parquet files found under {data_root}")

quantiles = {
    "q01": 0.01,
    "q10": 0.10,
    "q50": 0.50,
    "q90": 0.90,
    "q99": 0.99,
}

def _stack_vector_column(column):
    rows = []
    for value in column:
        arr = np.asarray(value, dtype=np.float32)
        if arr.ndim == 0:
            arr = arr.reshape(1)
        rows.append(arr.reshape(1, -1))
    if not rows:
        return None
    return np.concatenate(rows, axis=0)

updated = []
for key in ("observation.state", "action"):
    if key not in stats:
        continue
    chunks = []
    for parquet_path in parquet_paths:
        try:
            frame = pd.read_parquet(parquet_path, columns=[key])
        except Exception:
            continue
        if key not in frame:
            continue
        values = _stack_vector_column(frame[key].to_numpy())
        if values is not None:
            chunks.append(values)
    if not chunks:
        raise RuntimeError(f"No vector data found for {key}")
    data = np.concatenate(chunks, axis=0)
    feature_stats = dict(stats.get(key) or {})
    for label, q in quantiles.items():
        feature_stats[label] = np.quantile(data, q, axis=0).astype(float).tolist()
    feature_stats["count"] = [int(data.shape[0])]
    stats[key] = feature_stats
    updated.append(key)

if not updated:
    raise RuntimeError("No Pi0.5 state/action stats were updated")

stats_path.write_text(json.dumps(stats, indent=4), encoding="utf-8")
print("Updated Pi0.5 quantile stats for " + ", ".join(updated))
"""
        dataset_path = (Path(dataset_root).resolve() / repo_id).resolve()
        script = script.replace("__DATASET_PATH__", json.dumps(str(dataset_path)))
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.pi05_conda_env_name,
            "python",
            "-c",
            script,
        ]
        hf_home = self.config.pi05_hf_home
        env = {
            **os.environ,
            "HF_HOME": str(hf_home),
            "HF_HUB_CACHE": str(hf_home / "hub"),
            "HF_HUB_DISABLE_XET": "1",
            "PYTHONUNBUFFERED": "1",
        }
        cwd = self.config.pi05_repo_root if self.config.pi05_repo_root.exists() else self.config.repo_root
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=3600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Pi0.5 quantile stats augmentation timed out after 3600 seconds.") from exc
        if completed.returncode != 0:
            output = (completed.stdout or "").strip()
            tail = "\n".join(output.splitlines()[-30:])
            raise ValueError(f"Pi0.5 quantile stats augmentation failed with returncode={completed.returncode}:\n{tail}")

    def _pi05_v30_dataset_is_current(self, source_path: Path, converted_path: Path) -> bool:
        if self._lerobot_dataset_codebase_version(converted_path) != "v3.0":
            return False
        if (source_path / "sidecar").is_dir() and not (converted_path / "sidecar").exists():
            return False
        if self._dataset_raw_depth_manifest_path(source_path).is_file() and not self._dataset_raw_depth_manifest_path(converted_path).is_file():
            return False
        return self._dataset_tree_mtime(converted_path, exclude_dir_names={"sidecar"}) >= self._dataset_tree_mtime(
            source_path,
            exclude_dir_names={"sidecar"},
        )

    def _is_generated_pi05_dataset_path(self, path: Path) -> bool:
        generated_root = (self.config.dataset_root.resolve() / "local-pi05-v30").resolve()
        try:
            path.resolve().relative_to(generated_root)
            return True
        except ValueError:
            return False

    @classmethod
    def _pi05_v30_dataset_repo_id(cls, repo_id: str, dataset_path: Path) -> str:
        source = str(repo_id or "").strip().strip("/") or f"{dataset_path.parent.name}/{dataset_path.name}"
        slug = re.sub(r"[^A-Za-z0-9.-]+", "-", source).strip(".-").lower()
        return f"local-pi05-v30/{slug or 'dataset'}"

    @staticmethod
    def _dataset_tree_mtime(path: Path, *, exclude_dir_names: set[str] | None = None) -> float:
        if not path.exists():
            return 0.0
        newest = path.stat().st_mtime
        if not path.is_dir():
            return newest
        excluded = set(exclude_dir_names or set())
        for root, dirnames, filenames in os.walk(path):
            dirnames[:] = [name for name in dirnames if name not in excluded]
            for name in [*dirnames, *filenames]:
                item = Path(root) / name
                try:
                    newest = max(newest, item.stat().st_mtime)
                except OSError:
                    continue
        return newest

    @staticmethod
    def _lerobot_dataset_codebase_version(path: Path) -> str:
        info_path = path.expanduser() / "meta" / "info.json"
        if not info_path.is_file():
            return ""
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str(info.get("codebase_version") or "")

    def _latest_local_train_dataset(self, root: Path, preferred_repo_id: str) -> tuple[str, Path] | None:
        root = root.expanduser().resolve()
        preferred = str(preferred_repo_id or "").strip().strip("/")
        candidates: list[Path] = []

        if preferred:
            exact = (root / preferred).resolve()
            candidates.append(exact)
            if "/" in preferred:
                namespace, name = preferred.rsplit("/", 1)
                parent = (root / namespace).resolve()
                candidates.extend(parent.glob(f"{name}-*"))
            else:
                candidates.extend(root.glob(f"{preferred}-*"))
                candidates.extend(root.glob(f"*/{preferred}-*"))
        else:
            candidates.extend(root.glob("*"))
            candidates.extend(root.glob("*/*"))

        include_pi05_generated = preferred.startswith("local-pi05-v30/")
        valid = [
            path.resolve()
            for path in candidates
            if self._is_trainable_lerobot_dataset(path) and (include_pi05_generated or "local-pi05-v30" not in path.parts)
        ]
        if not valid:
            return None
        valid = sorted(set(valid), key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)
        path = valid[0]
        repo_id, _ = self._repo_id_root_from_dataset_path(path, root)
        return repo_id, path

    @staticmethod
    def _is_trainable_lerobot_dataset(path: Path) -> bool:
        path = path.expanduser()
        if not path.exists() or not path.is_dir():
            return False
        if not any((path / "data").rglob("*.parquet")):
            return False
        info_path = path / "meta" / "info.json"
        if not info_path.is_file():
            return False
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = {}
        version = str(info.get("codebase_version") or "")
        if version == "v3.0":
            has_tasks = (path / "meta" / "tasks.parquet").is_file() or any((path / "meta" / "tasks").rglob("*.parquet"))
            has_episodes = any((path / "meta" / "episodes").rglob("*.parquet"))
            has_stats = (path / "meta" / "stats.json").is_file() or any((path / "meta" / "episodes_stats").rglob("*.parquet"))
            return has_tasks and has_episodes and has_stats
        required = (
            "meta/tasks.jsonl",
            "meta/episodes.jsonl",
            "meta/episodes_stats.jsonl",
        )
        return all((path / rel).is_file() for rel in required)

    def _train_checkpoint_path(self, profile: RobotProfile, request: LeRobotSessionRequest) -> str:
        if (request.runtime_mode or request.mode) != "live":
            return str(self.config.fake_checkpoint_root / "policy.ckpt")
        job_name = request.job_name or self._default_train_job_name(profile, request)
        output_dir = Path(request.output_dir or str(self.config.output_root / job_name))
        if not output_dir.is_absolute():
            output_dir = self.config.repo_root / output_dir
        return str(output_dir / "checkpoints" / "last" / "pretrained_model")

    def _default_train_job_name(self, profile: RobotProfile, request: LeRobotSessionRequest) -> str:
        dataset = self._slug(request.dataset_repo_id or "local_fake_dataset")
        return self._slug(f"{profile.profile_id}_{request.policy_type or 'act'}_{dataset}")

    def _default_train_policy_repo_id(self, profile: RobotProfile, request: LeRobotSessionRequest) -> str:
        dataset = self._slug((request.dataset_repo_id or "record-test").split("/")[-1])
        policy_type = request.policy_type or "act"
        return f"jin/{self._slug(f'{profile.profile_id}_{policy_type}_{dataset}_policy')}"

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("_") or "lerobot"

    def _workflow_entrypoint(self, profile: RobotProfile, workflow: str) -> list[str]:
        if workflow == "visualize":
            return ["python", "-m", "lerobot.scripts.visualize_dataset_html"]
        if workflow == "rollout":
            # This workstation's LeRobot install uses lerobot-record for real-robot policy rollout.
            return ["lerobot-record"]
        template = [str(item) for item in profile.command_templates.get(workflow, []) if str(item).strip()]
        if template:
            return template
        script = {
            "teleoperate": "lerobot-teleoperate",
            "record": "lerobot-record",
            "train": "lerobot-train",
            "visualize": "python",
            # LeRobot 0.3.4 in this workstation does not expose lerobot-rollout;
            # real-robot policy inference is done through lerobot-record with a policy checkpoint/repo.
            "rollout": "lerobot-record",
        }.get(workflow, f"lerobot-{workflow}")
        return [script]

    def _robot_args(self, profile: RobotProfile, *, request: LeRobotSessionRequest, allow_fake: bool = True, workflow: str = "") -> list[str]:
        mode = request.runtime_mode or request.mode
        args = [
            f"--robot.type={profile.robot_type}",
            f"--robot.id={profile.robot_id}",
        ]
        calibration_dir = self._profile_calibration_dir(profile)
        if calibration_dir:
            args.append(f"--robot.calibration_dir={calibration_dir}")
        port = self._device_port(profile, "follower", allow_fake=allow_fake)
        if port:
            args.append(f"--robot.port={self._runtime_device_port(port, 'follower', live=mode == 'live')}")
        if workflow == "rollout" and self._is_pi05_policy(request.policy_type):
            # Pi0.5 OMX rollout can finish normally and then abort while disabling
            # torque on a hardware-error motor. Avoid converting a completed
            # rollout into FAILED during disconnect; operator stop remains explicit.
            args.append("--robot.disable_torque_on_disconnect=false")
        camera_map: dict[str, dict[str, Any]] = {}
        camera_required = bool(request.camera_enabled or self._uses_active_robot_cam(workflow, request))
        if camera_required:
            for camera_key in self._profile_camera_keys(profile):
                camera_port = self._device_port(profile, "camera", camera_key=camera_key, allow_fake=allow_fake)
                if camera_port:
                    runtime_port = self._runtime_device_port(camera_port, "camera", live=mode == "live")
                    saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
                    camera_map[camera_key] = self._camera_config_for_command(
                        runtime_port,
                        saved_camera,
                        camera_key=camera_key,
                        request_fps=request.camera_fps or request.fps or profile.fps,
                        include_color_format=workflow != "rollout",
                        include_depth_metadata=workflow != "rollout",
                    )
        if camera_map:
            args.append(f"--robot.cameras={json.dumps(camera_map, ensure_ascii=True)}")
        return args

    def _camera_config_for_command(
        self,
        port_or_identifier: str,
        camera_device: dict[str, Any] | None = None,
        *,
        camera_key: str = "",
        request_fps: int | None = None,
        include_color_format: bool = True,
        include_depth_metadata: bool = True,
    ) -> dict[str, Any]:
        device = camera_device or {}
        backend = self._normalize_camera_backend(device.get("backend", "opencv"))
        if backend == LEROBOT_REALSENSE_TYPE:
            identifier = str(device.get("serial_number_or_name") or port_or_identifier)
            return self._realsense_camera_config(
                identifier,
                camera_key=str(camera_key or device.get("camera_key") or ""),
                camera_device=device,
                fps=self._camera_fps(device, request_fps),
                use_depth=self._camera_use_depth(device, default=True),
                width=_safe_int(device.get("width"), LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1),
                height=_safe_int(device.get("height"), LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1),
                color_format=self._realsense_color_format(identifier=identifier, camera_device=device) if include_color_format else "",
                include_depth_metadata=include_depth_metadata,
            )
        return self._opencv_camera_config(port_or_identifier, request_fps)

    @staticmethod
    def _opencv_camera_config(index_or_path: str, fps: int | None) -> dict[str, Any]:
        path_or_index: str | int = index_or_path
        if index_or_path.isdigit():
            path_or_index = int(index_or_path)
        return {
            "type": "opencv",
            "index_or_path": path_or_index,
            "width": 640,
            "height": 480,
            "fps": fps or 30,
        }

    def _realsense_camera_config(
        self,
        serial_number_or_name: str,
        *,
        camera_key: str = "",
        camera_device: dict[str, Any] | None = None,
        fps: int,
        use_depth: bool,
        width: int,
        height: int,
        color_format: str,
        include_depth_metadata: bool = True,
    ) -> dict[str, Any]:
        clip_min_mm, clip_max_mm = self._realsense_depth_clip_range_mm(camera_key)
        data = {
            "type": LEROBOT_REALSENSE_TYPE,
            "serial_number_or_name": serial_number_or_name,
            "width": width,
            "height": height,
            "fps": fps,
            "use_depth": bool(use_depth),
            # LeRobot / RealSense D405 needs a real warmup period before
            # consuming frames; disabling warmup makes status=False failures
            # more likely after a previous session.
            "warmup_s": LEROBOT_DEFAULT_REALSENSE_WARMUP_S,
        }
        if include_depth_metadata:
            data["align_depth_to_color"] = bool(self.config.realsense_depth_align_to_color)
            data["depth_scale_m_per_unit"] = self._realsense_depth_scale_m_per_unit(
                camera_key,
                serial_number_or_name,
                camera_device,
            )
            data["depth_clip_min_mm"] = clip_min_mm
            data["depth_clip_max_mm"] = clip_max_mm
        if color_format:
            data["color_format"] = color_format
        return data

    def _realsense_depth_clip_range_mm(self, camera_key: str) -> tuple[float, float]:
        clean_key = str(camera_key or "").strip()
        camera_clips = self.config.realsense_camera_depth_clip_mm
        if clean_key and clean_key in camera_clips:
            clip = camera_clips[clean_key]
            return float(clip["min_mm"]), float(clip["max_mm"])
        return float(self.config.realsense_depth_clip_min_mm), float(self.config.realsense_depth_clip_max_mm)

    def _uses_in_process_lerobot_wrapper(self, workflow: str, request: LeRobotSessionRequest) -> bool:
        mode = request.runtime_mode or request.mode
        return bool(
            mode == "live"
            and workflow in {"teleoperate", "record"}
            and (request.isaac_mirror_enabled or self._uses_active_robot_cam(workflow, request))
        )

    @staticmethod
    def _uses_active_robot_cam(workflow: str, request: LeRobotSessionRequest) -> bool:
        return bool(workflow in {"teleoperate", "record"} and request.active_robot_cam_enabled)

    def _active_robot_cam_summary(self, request: LeRobotSessionRequest, *, workflow: str) -> dict[str, Any]:
        priority = self._active_robot_cam_priority(request)
        return {
            "enabled": True,
            "workflow": workflow,
            "primary_camera": priority[0] if priority else "d405",
            "camera_priority": priority,
            "primary_camera_key": self._active_robot_cam_primary_camera_key(request),
            "fallback_camera_key": self._active_robot_cam_fallback_camera_key(request),
            "d455f_fallback_enabled": bool(request.active_robot_cam_d455f_fallback_enabled),
            "resume_mode": str(request.active_robot_cam_resume_mode or "auto"),
            "capture_pose_path": self._active_robot_cam_capture_pose_path(request),
            "home_pose_path": self._active_robot_cam_home_pose_path(request),
            "motion": {
                "speed_scale": 0.7,
                "settle_before_capture_s": 1.0,
                "hold_after_capture_s": 1.0,
            },
            "pending_pose_path": "/tmp/atr_specimen_pose_pending/latest_specimen_pose_payload.json",
            "d405_mapping": {
                "a4_camera_to_isaac_transform": "direct",
                "a4_width_mm": 297.0,
                "a4_height_mm": 210.0,
                "a4_isaac_width_mm": 297.0,
                "a4_isaac_height_mm": 210.0,
                "depth_scale_m_per_unit": LEROBOT_D405_DEPTH_SCALE_M_PER_UNIT,
            },
            "d455f_fallback_mapping": {
                "a4_camera_to_isaac_transform": "robot_right_plane",
                "a4_width_mm": 210.0,
                "a4_height_mm": 297.0,
                "a4_isaac_width_mm": 297.0,
                "a4_isaac_height_mm": 210.0,
            },
        }

    def _active_robot_cam_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        priority = ",".join(self._active_robot_cam_priority(request))
        primary_key = self._active_robot_cam_primary_camera_key(request)
        fallback_key = self._active_robot_cam_fallback_camera_key(request)
        return {
            "ATR_ACTIVE_ROBOT_CAM_ENABLED": "1",
            "ATR_ACTIVE_ROBOT_CAM_RECORD_START_ENABLED": _bool_arg(request.active_robot_cam_record_start_enabled),
            "ATR_ACTIVE_ROBOT_CAM_TRIGGER_ON_FIRST_ACTION": _bool_arg(request.active_robot_cam_trigger_on_first_action),
            "ATR_ACTIVE_ROBOT_CAM_CAMERA_PRIORITY": priority,
            "ATR_ACTIVE_ROBOT_CAM_D455F_FALLBACK_ENABLED": _bool_arg(request.active_robot_cam_d455f_fallback_enabled),
            "ATR_ACTIVE_ROBOT_CAM_RESUME_MODE": str(request.active_robot_cam_resume_mode or "auto"),
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH": self._active_robot_cam_capture_pose_path(request),
            "ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH": self._active_robot_cam_home_pose_path(request),
            "ATR_ACTIVE_ROBOT_CAM_D455F_MANIFEST_PATH": "/tmp/atr_lerobot_latest_frame/latest_frame.json",
            "ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE": "0.7",
            "ATR_ACTIVE_ROBOT_CAM_RESUME_SPEED_SCALE": "0.5",
            "ATR_ACTIVE_ROBOT_CAM_TELEOP_TRANSITION_MAX_STEP": "3.0",
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TIMEOUT_S": "4.0",
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_POLL_S": "0.05",
            "ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TOLERANCE_DEG": "2.0",
            "ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TIMEOUT_S": "4.0",
            "ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_POLL_S": "0.05",
            "ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TOLERANCE_DEG": "5.0",
            "ATR_ACTIVE_ROBOT_CAM_SETTLE_S": "1.0",
            "ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S": "1.0",
            "ATR_SPECIMEN_POSE_PENDING_PATH": "/tmp/atr_specimen_pose_pending/latest_specimen_pose_payload.json",
            "ATR_ACTIVE_ROBOT_CAM_REQUEST_PATH": "/tmp/atr_active_robot_cam_request/request.json",
            "ATR_LEROBOT_LATEST_FRAME_ENABLED": "1",
            "ATR_LEROBOT_SPECIMEN_CAMERA_KEY": primary_key,
            "ATR_ACTIVE_ROBOT_CAM_PRIMARY_CAMERA_KEY": primary_key,
            "ATR_ACTIVE_ROBOT_CAM_FALLBACK_CAMERA_KEY": fallback_key,
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_CAMERA_TO_ISAAC_TRANSFORM": "direct",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_WIDTH_MM": "297.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_HEIGHT_MM": "210.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_ISAAC_WIDTH_MM": "297.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_ISAAC_HEIGHT_MM": "210.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_X_MM": "0.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_Y_MM": "0.0",
            "ATR_ACTIVE_ROBOT_CAM_D405_DEPTH_SCALE_M_PER_UNIT": str(LEROBOT_D405_DEPTH_SCALE_M_PER_UNIT),
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_CAMERA_TO_ISAAC_TRANSFORM": "robot_right_plane",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_WIDTH_MM": "210.0",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_HEIGHT_MM": "297.0",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_ISAAC_WIDTH_MM": "297.0",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_ISAAC_HEIGHT_MM": "210.0",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_WORLD_OFFSET_X_MM": "0.0",
            "ATR_ACTIVE_ROBOT_CAM_D455F_A4_WORLD_OFFSET_Y_MM": "0.0",
        }

    @staticmethod
    def _active_robot_cam_priority(request: LeRobotSessionRequest) -> list[str]:
        raw = str(request.active_robot_cam_camera_priority or "d405,d455f")
        priority = [item.strip().lower() for item in raw.split(",") if item.strip()]
        normalized = []
        for item in priority or ["d405", "d455f"]:
            if item in {"wrist", "active_robot_cam"}:
                item = "d405"
            if item in {"top", "d455"}:
                item = "d455f"
            if item not in normalized:
                normalized.append(item)
        if "d405" not in normalized:
            normalized.insert(0, "d405")
        return normalized

    @staticmethod
    def _active_robot_cam_primary_camera_key(request: LeRobotSessionRequest) -> str:
        return str(request.active_robot_cam_primary_camera_key or "wrist").strip() or "wrist"

    @staticmethod
    def _active_robot_cam_fallback_camera_key(request: LeRobotSessionRequest) -> str:
        return str(request.active_robot_cam_fallback_camera_key or "top").strip() or "top"

    def _active_robot_cam_capture_pose_path(self, request: LeRobotSessionRequest) -> str:
        raw = str(request.active_robot_cam_capture_pose_path or "").strip()
        if raw:
            return str(_resolve_path(self.config.repo_root, raw))
        return str(self.config.repo_root / "runs" / "active_robot_cam" / "latest_follower_capture_pose.json")

    def _active_robot_cam_home_pose_path(self, request: LeRobotSessionRequest) -> str:
        raw = str(request.active_robot_cam_home_pose_path or "").strip()
        if raw:
            return str(_resolve_path(self.config.repo_root, raw))
        return str(self.config.repo_root / "runs" / "active_robot_cam" / "latest_follower_home_pose.json")

    def _teleop_args(self, profile: RobotProfile, *, request: LeRobotSessionRequest, allow_fake: bool = True) -> list[str]:
        mode = request.runtime_mode or request.mode
        args = [
            f"--teleop.type={profile.teleop_type}",
            f"--teleop.id={profile.teleop_id}",
        ]
        calibration_dir = self._profile_calibration_dir(profile)
        if calibration_dir:
            args.append(f"--teleop.calibration_dir={calibration_dir}")
        port = self._device_port(profile, "leader", allow_fake=allow_fake)
        if port:
            args.append(f"--teleop.port={self._runtime_device_port(port, 'leader', live=mode == 'live')}")
        return args

    def _profile_calibration_dir(self, profile: RobotProfile) -> str:
        if not str(profile.calibration_dir or "").strip():
            return ""
        return str(_resolve_path(self.config.repo_root, profile.calibration_dir))

    def _command_preview(self, profile: RobotProfile, workflow: str, args: list[str]) -> list[str]:
        base = self._workflow_entrypoint(profile, workflow)
        defaults = [
            f"--robot.type={profile.robot_type}",
            f"--teleop.type={profile.teleop_type}",
            f"--robot.port={self._device_port(profile, 'follower')}",
            f"--teleop.port={self._device_port(profile, 'leader')}",
            f"--robot.id={profile.robot_id}",
            f"--teleop.id={profile.teleop_id}",
        ]
        if workflow in {"find_ports", "train"}:
            defaults = defaults[:0] if workflow == "find_ports" else defaults[:1]
        return base + [item for item in defaults + args if item and not item.endswith("=")]

    def _start_live_process(
        self,
        *,
        session_id: str,
        command: list[str],
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            self.config.session_log_root.mkdir(parents=True, exist_ok=True)
            log_path = self.config.session_log_root / f"{session_id}.log"
            log_handle = log_path.open("w", encoding="utf-8")
            log_handle.write(f"\n[{datetime.now(timezone.utc).isoformat()}] starting: {' '.join(command)}\n")
            log_handle.flush()
            process = subprocess.Popen(
                command,
                cwd=str(self.config.repo_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, **dict(env_overrides or {}), "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
            self._processes[session_id] = process
            self._log_handles[session_id] = log_handle
            time.sleep(3.0)
            returncode = process.poll()
            if returncode is not None:
                log_handle.flush()
                log_tail = self._tail_file(str(log_path))
                self._close_log_handle(session_id)
                if int(returncode) == 0:
                    return {
                        "ok": True,
                        "completed_during_startup": True,
                        "session_updates": {"pid": process.pid, "log_path": str(log_path), "returncode": returncode},
                    }
                failure_code = "LEROBOT_PROCESS_EXITED_DURING_STARTUP"
                message = f"Live LeRobot process exited during startup with returncode={returncode}."
                if "Running calibration" in log_tail or "EOFError: EOF when reading a line" in log_tail:
                    failure_code = "LEROBOT_CALIBRATION_REQUIRED"
                    message = "LeRobot requires interactive leader/follower calibration before GUI teleoperation can run. Run calibration in a terminal, then retry teleoperation."
                return {
                    "ok": False,
                    "failure_code": failure_code,
                    "message": message,
                    "session_updates": {"pid": process.pid, "log_path": str(log_path), "returncode": returncode},
                }
            return {
                "ok": True,
                "session_updates": {"pid": process.pid, "log_path": str(log_path), "returncode": None},
            }
        except Exception as exc:
            return {
                "ok": False,
                "failure_code": "LEROBOT_PROCESS_START_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
            }

    def _refresh_process_status(self, session: dict[str, Any]) -> None:
        session_id = str(session.get("session_id", ""))
        process = self._processes.get(session_id)
        if not process:
            pid = session.get("pid")
            if pid is not None:
                try:
                    pid_int = int(pid)
                except (TypeError, ValueError):
                    pid_int = 0
                if pid_int and not self._pid_alive(pid_int) and session.get("returncode") is None:
                    session["returncode"] = -999
                    session["status"] = "FAILED"
                    self._mark_visualization_stale(session, "process_not_alive")
            return
        returncode = process.poll()
        session["returncode"] = returncode
        if returncode is None:
            if str(session.get("workflow") or "").lower() == "visualize" and isinstance(session.get("visualization"), dict):
                visualization = dict(session["visualization"])
                visualization["stale"] = False
                visualization["stale_reason"] = ""
                session["visualization"] = visualization
            if str(session.get("workflow") or "").lower() == "rollout":
                log_tail = self._tail_file(str(session.get("log_path", "")), max_chars=20000)
                if self._rollout_log_has_fatal_runtime_failure(log_tail):
                    session["status"] = "FAILED"
                    session["returncode"] = -998
                    self._terminate_live_process(process, signal.SIGTERM)
                    return
            session["status"] = session.get("status") or "RUNNING"
            return
        self._close_log_handle(session_id)
        if str(session.get("status", "")).upper() in {"CANCELLED", "STOPPED"}:
            self._stop_training_monitor(session)
            return
        if int(returncode) == 0:
            session["status"] = "COMPLETED"
        else:
            session["status"] = "FAILED"
        self._mark_visualization_stale(session, f"process_returncode_{returncode}")
        if str(session.get("workflow") or "").lower() == "train":
            self._stop_training_monitor(session)
        if int(returncode) == 0 and str(session.get("workflow") or "").lower() == "record":
            self._start_isaac_rgbd_post_render_after_record(session)

    @staticmethod
    def _mark_visualization_stale(session: dict[str, Any], reason: str) -> None:
        if str(session.get("workflow") or "").lower() != "visualize":
            return
        visualization = dict(session.get("visualization") or {})
        visualization["stale"] = True
        visualization["stale_reason"] = str(reason or "stale")
        session["visualization"] = visualization

    def _start_isaac_rgbd_post_render_after_record(self, session: dict[str, Any]) -> None:
        if not bool(session.get("isaac_rgbd_post_render_auto_on_record_success", True)):
            return
        if bool(session.get("isaac_rgbd_post_render_auto_started")):
            return
        record_attempt = session.get("record_attempt")
        if isinstance(record_attempt, dict):
            render = record_attempt.get("isaac_rgbd_render")
            if isinstance(render, dict) and not bool(render.get("enabled", True)):
                return
        session["isaac_rgbd_post_render_auto_started"] = True
        payload = {
            "mode": session.get("mode", "live"),
            "runtime_mode": session.get("mode", "live"),
            "profile_id": session.get("profile_id", self._selected_profile_id),
            "dataset_path": session.get("dataset_path", ""),
            "session_id": session.get("session_id", ""),
            "isaac_mirror_endpoint": session.get("isaac_mirror_endpoint", "http://127.0.0.1:8766/joints"),
            "isaac_rgbd_post_render_auto_on_record_success": True,
        }
        result = self.isaac_rgbd_render_start(payload)
        session["isaac_rgbd_post_render"] = dict(result.get("post_render") or {})
        session.setdefault("step_trace", []).append(
            {
                "step": "ISAAC_RGBD_POST_RENDER_AUTO_START",
                "status": "ok" if result.get("ok") else "warning",
                "detail": str((result.get("post_render") or {}).get("job_id") or result.get("error") or ""),
            }
        )

    def _record_session_has_isaac_rgbd_post_render_candidates(self, session: dict[str, Any]) -> bool:
        dataset_path = str(session.get("dataset_path") or "").strip()
        session_id = str(session.get("session_id") or "").strip()
        if not dataset_path or not session_id:
            return False
        path = Path(dataset_path).expanduser()
        if not path.exists():
            return False
        return bool(self._isaac_rgbd_post_render_candidates(path, session_id))

    @staticmethod
    def _rollout_log_has_fatal_runtime_failure(log_tail: str) -> bool:
        text = str(log_tail or "")
        fatal_markers = (
            "[ACTOR] Fatal exception",
            "[GET_ACTIONS] Fatal exception",
            "device reports readiness to read but returned no data",
            "There is no status packet",
            "Failed to open OpenCVCamera",
        )
        return any(marker in text for marker in fatal_markers)

    @staticmethod
    def _terminate_live_process(process: subprocess.Popen[str], sig: signal.Signals) -> None:
        try:
            pgid = os.getpgid(process.pid)
            if pgid == process.pid:
                os.killpg(pgid, sig)
                return
        except ProcessLookupError:
            return
        except Exception:
            pass
        try:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def _cleanup_lerobot_processes(self, workflow: str) -> list[dict[str, Any]]:
        """Terminate stale LeRobot subprocesses without killing unrelated GUI/test processes."""
        matched = [*self._project_lerobot_pids(workflow), *self._lerobot_display_viewer_pids(workflow)]
        pids = self._expand_descendant_pids(matched)
        if not pids:
            return []
        current = {os.getpid(), os.getppid()}
        current_pgrp = os.getpgrp()
        safe_pids: list[int] = []
        for pid in pids:
            if pid in current:
                continue
            try:
                if os.getpgid(pid) == current_pgrp:
                    continue
            except ProcessLookupError:
                continue
            safe_pids.append(pid)
        safe_pids = sorted(set(safe_pids))
        if not safe_pids:
            return []

        for pid in safe_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.time() + 5.0
        while time.time() < deadline:
            remaining = [pid for pid in safe_pids if self._pid_alive(pid)]
            if not remaining:
                break
            time.sleep(0.1)
        for pid in safe_pids:
            if self._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        return [
            {
                "step": "CLEANUP_LEROBOT_PROCESSES",
                "status": "ok",
                "detail": f"{workflow}: pids={','.join(str(pid) for pid in safe_pids)}",
            }
        ]

    def _expand_descendant_pids(self, root_pids: list[int]) -> list[int]:
        """Return root PIDs plus descendants using /proc parent links."""
        roots = {int(pid) for pid in root_pids}
        if not roots:
            return []
        children_by_parent: dict[int, list[int]] = {}
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                stat = (Path("/proc") / name / "stat").read_text(encoding="utf-8", errors="replace")
                after_comm = stat.rsplit(")", 1)[1].strip().split()
                ppid = int(after_comm[1])
            except (OSError, IndexError, ValueError):
                continue
            children_by_parent.setdefault(ppid, []).append(pid)
        expanded = set(roots)
        stack = list(roots)
        while stack:
            parent = stack.pop()
            for child in children_by_parent.get(parent, []):
                if child in expanded:
                    continue
                expanded.add(child)
                stack.append(child)
        return sorted(expanded)

    def _project_lerobot_pids(self, workflow: str) -> list[int]:
        markers_by_workflow = {
            "teleoperate": (
                "lerobot-teleoperate",
                "lerobot.teleoperate",
                "lerobot_isaac_mirror_runtime_wrapper.py teleoperate",
            ),
            "record": (
                "lerobot-record",
                "lerobot.record",
                "lerobot_isaac_mirror_runtime_wrapper.py record",
            ),
            "train": ("lerobot-train", "lerobot.train"),
            "rollout": (
                "lerobot-rollout",
                "lerobot.rollout",
                "lerobot_pi05_rollout_wrapper.py",
                "lerobot_live_rollout_wrapper.py",
                "eval_with_real_robot.py",
                "rtc.enabled",
            ),
            "visualize": ("lerobot.scripts.visualize_dataset", "lerobot.scripts.visualize_dataset_html", "visualize_dataset.py", "visualize_dataset_html.py"),
        }
        markers = markers_by_workflow.get(workflow, ("lerobot-", "lerobot."))
        project = self.config.repo_root.resolve()
        current = {os.getpid(), os.getppid()}
        pids: list[int] = []
        proc_root = Path("/proc")
        if not proc_root.exists():
            return []
        for name in os.listdir(proc_root):
            if not name.isdigit():
                continue
            pid = int(name)
            if pid in current:
                continue
            proc_dir = Path("/proc") / name
            try:
                raw = (proc_dir / "cmdline").read_bytes()
            except OSError:
                continue
            parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
            if not parts:
                continue
            cmd = " ".join(parts)
            if not self._cmdline_matches_lerobot_marker(parts, markers):
                continue
            try:
                cwd = Path(os.readlink(proc_dir / "cwd")).resolve()
            except OSError:
                cwd = Path("/")
            if cwd == project or project in cwd.parents or str(project) in cmd:
                pids.append(pid)
        return sorted(set(pids))

    def _lerobot_display_viewer_pids(self, workflow: str) -> list[int]:
        """Return detached Rerun viewer PIDs spawned by LeRobot display_data=true."""
        if workflow not in {"teleoperate", "record", "rollout"}:
            return []
        current = {os.getpid(), os.getppid()}
        pids: list[int] = []
        proc_root = Path("/proc")
        if not proc_root.exists():
            return []
        for name in os.listdir(proc_root):
            if not name.isdigit():
                continue
            pid = int(name)
            if pid in current:
                continue
            try:
                raw = (proc_root / name / "cmdline").read_bytes()
            except OSError:
                continue
            parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
            if self._cmdline_matches_lerobot_display_viewer(parts):
                pids.append(pid)
        return sorted(set(pids))

    @staticmethod
    def _cmdline_matches_lerobot_marker(parts: list[str], markers: tuple[str, ...]) -> bool:
        """Match actual LeRobot commands without catching GUI DOM ids or test scripts."""
        for marker in markers:
            if " " in marker and LeRobotBridge._cmdline_matches_lerobot_marker_sequence(parts, marker.split()):
                return True
        for part in parts:
            base = Path(part).name
            for marker in markers:
                if " " in marker:
                    continue
                if marker.startswith("lerobot-"):
                    if part == marker or base == marker:
                        return True
                    continue
                if marker.startswith("lerobot."):
                    if part == marker:
                        return True
                    continue
                if marker.endswith(".py"):
                    if base == marker or part.endswith(f"/{marker}") or part.endswith(f"\\{marker}"):
                        return True
                    continue
                if marker == "rtc.enabled":
                    if part == "--rtc.enabled=true" or part == "--rtc.enabled" or part.startswith("--rtc.enabled="):
                        return True
                    continue
                if marker in part:
                    return True
        return False

    @staticmethod
    def _cmdline_matches_lerobot_marker_sequence(parts: list[str], markers: list[str]) -> bool:
        if not parts or not markers or len(markers) > len(parts):
            return False
        for start in range(0, len(parts) - len(markers) + 1):
            for offset, marker in enumerate(markers):
                part = parts[start + offset]
                base = Path(part).name
                if marker.endswith(".py"):
                    if not (base == marker or part.endswith(f"/{marker}") or part.endswith(f"\\{marker}")):
                        break
                    continue
                if part != marker:
                    break
            else:
                return True
        return False

    @staticmethod
    def _cmdline_matches_lerobot_display_viewer(parts: list[str]) -> bool:
        """Match the detached Rerun viewer LeRobot opens for display_data=true."""
        if not parts:
            return False
        has_rerun = any(Path(part).name == "rerun" or part.endswith("/rerun") for part in parts)
        if not has_rerun:
            return False
        has_expect_data = "--expect-data-soon" in parts
        has_lerobot_port = "--port=9876" in parts or any(
            part == "--port" and index + 1 < len(parts) and parts[index + 1] == "9876"
            for index, part in enumerate(parts)
        )
        return has_expect_data and has_lerobot_port

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _send_lerobot_record_control_key(self, action: str) -> dict[str, Any]:
        key_by_action = {
            "next": "right",
            "retry": "left",
            "finish": "esc",
        }
        key_name = key_by_action.get(action)
        if not key_name:
            return {"ok": False, "failure_code": "LEROBOT_RECORD_CONTROL_UNSUPPORTED", "message": f"Unsupported live recording action: {action}"}
        script = """
from pynput import keyboard
import json
import sys
import time

key_name = sys.argv[1]
key = {
    "right": keyboard.Key.right,
    "left": keyboard.Key.left,
    "esc": keyboard.Key.esc,
}[key_name]
controller = keyboard.Controller()
controller.press(key)
time.sleep(0.05)
controller.release(key)
print(json.dumps({"ok": True, "key": key_name}))
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
            key_name,
        ]
        try:
            result = subprocess.run(command, cwd=str(self.config.repo_root), text=True, capture_output=True, timeout=10)
        except Exception as exc:
            return {
                "ok": False,
                "failure_code": "LEROBOT_RECORD_CONTROL_SEND_FAILED",
                "message": f"Could not send LeRobot record control key {key_name}: {exc.__class__.__name__}: {exc}",
            }
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            return {
                "ok": False,
                "failure_code": "LEROBOT_RECORD_CONTROL_SEND_FAILED",
                "message": f"Could not send LeRobot record control key {key_name}; returncode={result.returncode}; output={stderr[-1000:]}",
            }
        return {"ok": True, "key": key_name, "detail": f"sent LeRobot {key_name} key for {action}"}

    def _record_log_phase(self, session: dict[str, Any]) -> str:
        """Infer coarse LeRobot recording phase from the subprocess log."""
        log = self._tail_file(str(session.get("log_path", "")), max_chars=20000)
        last_recording = log.rfind("Recording episode")
        last_reset = log.rfind("Reset the environment")
        saving_markers = ("Map:", "Creating parquet", "Svt[info]")
        last_saving = max(log.rfind(marker) for marker in saving_markers)
        last_failure = max(log.rfind("Traceback"), log.rfind("ValueError"), log.rfind("ERROR conda"))
        if last_failure > max(last_recording, last_reset, last_saving):
            return "failed"
        if last_saving > max(last_recording, last_reset):
            return "saving"
        if last_reset > last_recording:
            return "reset"
        if last_recording >= 0:
            return "recording"
        return "starting"

    def _close_log_handle(self, session_id: str) -> None:
        handle = self._log_handles.pop(session_id, None)
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    @staticmethod
    def _tail_file(path_value: str, *, max_chars: int = 6000) -> str:
        if not path_value:
            return ""
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return ""
        try:
            data = path.read_bytes()
            return data[-max_chars:].decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _dataset_path_for(self, request: LeRobotSessionRequest) -> str:
        if request.dataset_path:
            return str(_resolve_path(self.config.repo_root, request.dataset_path))
        root = _resolve_path(self.config.repo_root, request.dataset_root) if request.dataset_root else self.config.dataset_root
        if request.dataset_repo_id:
            return str(root / request.dataset_repo_id)
        if (request.runtime_mode or request.mode) == "test":
            return str(self.config.fake_dataset_root / (request.profile_id or self._selected_profile_id))
        return str(root)

    def _record_effective_resume(self, request: LeRobotSessionRequest) -> bool:
        return bool(request.resume)

    def _record_start_request(self, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, bool, str]:
        """Resolve recording dataset behavior without silently resuming stale data."""
        if request.resume:
            return request, True, "recording config accepted; resume=true"
        try:
            target = Path(self._dataset_path_for(request)).expanduser()
            exists = target.exists()
        except Exception:
            exists = False
            target = Path("")
        if not exists:
            return request, False, "recording config accepted"

        mode = request.runtime_mode or request.mode
        if mode != "live":
            return request, False, "existing dataset detected; test mode keeps resume=false"

        if self._record_start_should_resume_stopped_dataset(request, target):
            next_request = request.model_copy(update={"resume": True})
            return next_request, True, "existing stopped record dataset detected; resume=true"

        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        updates: dict[str, Any] = {"resume": False}
        if request.dataset_path:
            base_path = self._path_without_generated_suffixes(request.dataset_path)
            updates["dataset_path"] = f"{base_path.rstrip('/')}-{suffix}"
        else:
            repo_id = request.dataset_repo_id or "local/lerobot-record"
            updates["dataset_repo_id"] = self._dataset_repo_id_with_suffix(repo_id, suffix)
        next_request = request.model_copy(update=updates)
        return next_request, False, f"existing dataset detected; recording to fresh dataset {self._dataset_path_for(next_request)}"

    def _record_start_should_resume_stopped_dataset(self, request: LeRobotSessionRequest, target: Path) -> bool:
        """Resume only when restarting the same explicitly stopped live record dataset."""
        request_repo = str(request.dataset_repo_id or "").strip().strip("/")
        try:
            target_path = target.expanduser().resolve()
        except Exception:
            target_path = target.expanduser()
        for session in sorted(self._sessions.values(), key=lambda item: item.get("created_at", ""), reverse=True):
            if str(session.get("workflow") or "").lower() != "record":
                continue
            if str(session.get("mode") or "").lower() != "live":
                continue
            if str(session.get("status") or "").upper() != "STOPPED":
                continue
            session_repo = str(session.get("dataset_repo_id") or "").strip().strip("/")
            if request_repo and session_repo and request_repo == session_repo:
                return True
            session_path_value = str(session.get("dataset_path") or "").strip()
            if not session_path_value:
                continue
            try:
                session_path = Path(session_path_value).expanduser().resolve()
            except Exception:
                session_path = Path(session_path_value).expanduser()
            if session_path == target_path:
                return True
        return False

    @classmethod
    def _strip_generated_name_suffixes(cls, name: str) -> str:
        clean = str(name or "").strip()
        while True:
            next_name = GENERATED_PATH_SUFFIX_RE.sub("", clean)
            if next_name == clean:
                return clean
            clean = next_name or clean

    @classmethod
    def _path_without_generated_suffixes(cls, path_value: str) -> str:
        raw = str(path_value or "").strip().rstrip("/")
        if not raw:
            return raw
        path = Path(raw)
        base_name = cls._strip_generated_name_suffixes(path.name)
        if base_name == path.name:
            return raw
        return str(path.with_name(base_name))

    @classmethod
    def _dataset_repo_id_base(cls, repo_id: str) -> str:
        clean = str(repo_id or "local/lerobot-record").strip().strip("/")
        if "/" not in clean:
            return cls._strip_generated_name_suffixes(clean)
        namespace, name = clean.rsplit("/", 1)
        return f"{namespace}/{cls._strip_generated_name_suffixes(name)}"

    @classmethod
    def _dataset_repo_id_with_suffix(cls, repo_id: str, suffix: str) -> str:
        clean = cls._dataset_repo_id_base(repo_id)
        if "/" not in clean:
            return f"{clean}-{suffix}"
        namespace, name = clean.rsplit("/", 1)
        return f"{namespace}/{name}-{suffix}"

    @staticmethod
    def _eval_dataset_repo_id(repo_id: str) -> str:
        clean = str(repo_id or "local/eval_lerobot_policy").strip().strip("/")
        if "/" not in clean:
            return clean if clean.startswith("eval_") else f"eval_{clean}"
        namespace, name = clean.rsplit("/", 1)
        return clean if name.startswith("eval_") else f"{namespace}/eval_{name}"

    def _rollout_request_with_eval_dataset(self, request: LeRobotSessionRequest) -> LeRobotSessionRequest:
        """LeRobot requires eval_* dataset names when a policy is provided."""
        return request.model_copy(update={"dataset_repo_id": self._eval_dataset_repo_id(request.dataset_repo_id)})

    @staticmethod
    def _rollout_request_with_manual_stop(request: LeRobotSessionRequest) -> LeRobotSessionRequest:
        """Use a long LeRobot episode when rollout should run until operator Stop."""
        if not request.continuous_rollout:
            return request
        return request.model_copy(
            update={
                "episode_s": max(float(request.episode_s or 0), MANUAL_STOP_ROLLOUT_EPISODE_S),
                "num_episodes": 1,
            }
        )

    def _rollout_request_with_local_policy(self, request: LeRobotSessionRequest) -> LeRobotSessionRequest:
        """Normalize explicit policy refs; only standalone rollout may select the latest local policy."""
        mode = request.runtime_mode or request.mode
        raw_path = str(request.policy_path or request.policy_checkpoint_path or "").strip()
        if raw_path and not raw_path.startswith("fake://"):
            path = _resolve_path(self.config.repo_root, raw_path).resolve()
            if not self._is_under_allowed_roots(path):
                raise ValueError(f"Policy checkpoint path is outside allowed roots: {path}")
            checkpoint = self._policy_checkpoint_from_path(path)
            return request.model_copy(
                update={
                    "policy_checkpoint_path": str(checkpoint),
                    "policy_path": str(checkpoint),
                    "policy_repo_id": "",
                }
            )

        repo_id = str(request.policy_repo_id or "").strip().strip("/")
        if repo_id:
            local = self._find_local_policy_by_repo_id(repo_id)
            if local:
                return request.model_copy(
                    update={
                        "policy_checkpoint_path": str(local),
                        "policy_path": str(local),
                        "policy_repo_id": "",
                    }
                )
            return request

        manipulation_task = bool(str(request.task_id or request.skill_id or "").strip())
        if mode == "live" and not manipulation_task:
            latest = self._latest_local_policy_checkpoint()
            if latest:
                return request.model_copy(
                    update={
                        "policy_checkpoint_path": str(latest),
                        "policy_path": str(latest),
                        "policy_repo_id": "",
                    }
                )
        return request

    def _policy_checkpoint_from_path(self, path: Path) -> Path:
        """Resolve an output directory or selected model file to a LeRobot pretrained_model folder."""
        if path.is_file():
            if not self._is_policy_output_file(path):
                raise ValueError(f"Selected policy file is not a recognized LeRobot output file: {path}")
            parent = path.parent.resolve()
            if self._is_pretrained_policy_dir(parent):
                return parent
            return path
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Policy checkpoint path does not exist: {path}")
        candidates = [
            path,
            path / "pretrained_model",
            path / "checkpoints" / "last" / "pretrained_model",
        ]
        candidates.extend(sorted(path.glob("checkpoints/*/pretrained_model"), key=lambda item: (item.stat().st_mtime, str(item)), reverse=True))
        candidates.extend(sorted(path.glob("*/pretrained_model"), key=lambda item: (item.stat().st_mtime, str(item)), reverse=True))
        for candidate in candidates:
            if self._is_pretrained_policy_dir(candidate):
                return candidate.resolve()
        raise ValueError(
            "Policy checkpoint folder must contain a LeRobot pretrained model "
            f"(config.json plus model.safetensors or equivalent): {path}"
        )

    def _find_local_policy_by_repo_id(self, repo_id: str) -> Path | None:
        target = str(repo_id or "").strip().strip("/")
        if not target:
            return None
        for item in self._discover_local_policies():
            if str(item.get("repo_id") or "").strip().strip("/") == target:
                path = Path(str(item.get("path") or ""))
                if path.exists():
                    return path.resolve()
        return None

    def _latest_local_policy_checkpoint(self) -> Path | None:
        policies = self._discover_local_policies()
        paths = [Path(str(item.get("path") or "")) for item in policies if item.get("path")]
        valid = [path.resolve() for path in paths if self._is_pretrained_policy_dir(path)]
        if not valid:
            return None
        return sorted(valid, key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)[0]

    @staticmethod
    def _is_policy_output_file(path: Path) -> bool:
        name = path.name.lower()
        return name in POLICY_OUTPUT_FILE_NAMES or path.suffix.lower() in POLICY_OUTPUT_FILE_SUFFIXES

    def _is_pretrained_policy_dir(self, path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        if not (path / "config.json").is_file():
            return False
        return any(self._is_policy_output_file(item) for item in path.iterdir() if item.is_file())

    @staticmethod
    def _policy_ref(request: LeRobotSessionRequest) -> str:
        return request.policy_path or request.policy_checkpoint_path or request.policy_repo_id

    def _rollout_task_instruction(self, request: LeRobotSessionRequest, *, is_pi05: bool) -> str:
        """Use the trained language command for known Pi0.5 local policies when safe to normalize."""
        task = str(request.task_instruction or "").strip()
        if not is_pi05:
            return task or "pick and place specimen"
        default_task = self._known_pi05_policy_task(request)
        if not default_task:
            return task or "pick and place specimen"
        lowered = task.lower()
        generic = lowered in {"", "pick and place specimen", "pick up the cube", "pick cube"}
        same_cube_goal = "cube" in lowered and "metal plate" in lowered
        if generic or same_cube_goal:
            return default_task
        return task

    def _known_pi05_policy_task(self, request: LeRobotSessionRequest) -> str:
        policy_ref = self._policy_ref(request)
        if not policy_ref:
            return ""
        policy_path = _resolve_path(self.config.repo_root, policy_ref)
        config_path = policy_path / "train_config.json" if policy_path.is_dir() else Path("")
        dataset_repo_id = ""
        try:
            if config_path.is_file():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                dataset = config.get("dataset") if isinstance(config, dict) else {}
                if isinstance(dataset, dict):
                    dataset_repo_id = str(dataset.get("repo_id") or "")
        except Exception:
            dataset_repo_id = ""
        known_tasks = {
            "local-pi05-v30/jin-pp-cube": "Pick up the cube and put on the metal plate",
            "jin/pp-cube": "Pick up the cube and put on the metal plate",
        }
        if dataset_repo_id in known_tasks:
            return known_tasks[dataset_repo_id]
        if "pp_cube_train" in str(policy_path) or "jin-pp-cube" in dataset_repo_id:
            return "Pick up the cube and put on the metal plate"
        return ""


    def _scan_serial_ports(self) -> list[str]:
        patterns = ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/serial/by-id/*"]
        ports: list[str] = []
        for pattern in patterns:
            ports.extend(glob.glob(pattern))
        return sorted(dict.fromkeys(ports))

    def _scan_camera_ports(self) -> list[str]:
        patterns = ["/dev/video*", "/dev/v4l/by-id/*", "/dev/v4l/by-path/*"]
        ports: list[str] = []
        for pattern in patterns:
            ports.extend(glob.glob(pattern))
        return sorted(dict.fromkeys(ports))

    def _scan_camera_candidates(self, request: LeRobotDevicePortRequest) -> list[str]:
        if self._normalize_camera_backend(request.camera_backend) == LEROBOT_REALSENSE_TYPE:
            return self._scan_live_realsense_camera_ids()
        return self._scan_camera_ports()

    def _scan_live_realsense_camera_ids(self) -> list[str]:
        ids: list[str] = []
        for entry in self._scan_live_realsense_camera_entries():
            serial = str(entry.get("serial") or "").strip()
            configured_identifier = str(entry.get("configured_identifier") or "").strip()
            name = str(entry.get("name") or "").strip()
            product_line = str(entry.get("product_line") or "").strip()
            if serial:
                ids.append(serial)
            elif configured_identifier:
                ids.append(configured_identifier)
            if name:
                ids.append(name)
            if product_line and name and product_line not in name:
                ids.append(f"{name} {product_line}")
        return sorted(dict.fromkeys(ids))

    def _scan_realsense_camera_ids(self) -> list[str]:
        """Enumerate RealSense serials/names without starting streams."""
        ids: list[str] = []
        for entry in self._scan_realsense_camera_entries():
            serial = str(entry.get("serial") or "").strip()
            name = str(entry.get("name") or "").strip()
            product_line = str(entry.get("product_line") or "").strip()
            if serial:
                ids.append(serial)
            if name:
                ids.append(name)
            if product_line and name and product_line not in name:
                ids.append(f"{name} {product_line}")
        return sorted(dict.fromkeys(ids))

    def _scan_realsense_camera_entries(self) -> list[dict[str, Any]]:
        """Enumerate RealSense devices as SDK entries without starting streams."""
        entries: list[dict[str, Any]] = []
        try:
            import pyrealsense2 as rs  # type: ignore[import-not-found]
        except Exception:
            return []
        try:
            devices = rs.context().query_devices()
        except Exception:
            return []
        try:
            for device in devices:
                serial = self._safe_realsense_info(rs, device, "serial_number")
                name = self._safe_realsense_info(rs, device, "name")
                product_line = self._safe_realsense_info(rs, device, "product_line")
                usb_type = self._safe_realsense_info(rs, device, "usb_type_descriptor")
                physical_port = self._safe_realsense_info(rs, device, "physical_port")
                asic_serial = self._safe_realsense_info(rs, device, "asic_serial_number")
                if serial or name:
                    entry: dict[str, Any] = {
                        "serial": serial,
                        "name": name,
                        "product_line": product_line,
                        "usb_type": usb_type,
                        "physical_port": physical_port,
                        "asic_serial": asic_serial,
                    }
                    entry.update(self._realsense_usb_link_metadata(entry))
                    entries.append(entry)
        except Exception:
            return []
        return entries

    @staticmethod
    def _safe_realsense_info(rs: Any, device: Any, info_name: str) -> str:
        try:
            info = getattr(rs.camera_info, info_name)
            if device.supports(info):
                return str(device.get_info(info) or "").strip()
        except Exception:
            return ""
        return ""

    def _scan_live_realsense_camera_entries(
        self,
        *,
        sysfs_root: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Enumerate RealSense devices from the runtime env used by LeRobot."""
        # The USB descriptor serial exposed through sysfs is not necessarily the
        # SDK serial accepted by rs.config.enable_device() (notably on D405).
        # Keep the committed, proven rollout route: runtime identities come from
        # the RealSense SDK; sysfs is used only to enrich USB link metadata.
        entries = self._scan_realsense_camera_entries()
        if entries:
            return entries
        return self._scan_realsense_camera_entries_via_lerobot_env()

    def _scan_realsense_camera_entries_from_sysfs(self, *, sysfs_root: Path) -> list[dict[str, Any]]:
        """Read physical RealSense identity/link state without opening a camera SDK context."""
        if not sysfs_root.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for device_path in sorted(sysfs_root.iterdir()):
            if not device_path.is_dir():
                continue
            vendor = self._read_sysfs_text(device_path / "idVendor").lower()
            product_name = self._read_sysfs_text(device_path / "product")
            if vendor != "8086" or "realsense" not in product_name.lower():
                continue
            serial = self._read_sysfs_text(device_path / "serial")
            configured_identifier = ""
            product_text = product_name.lower()
            for camera_key, hints in LEROBOT_REALSENSE_CAMERA_MODEL_HINTS.items():
                if any(hint in product_text for hint in hints):
                    configured_identifier = LEROBOT_REALSENSE_DEFAULT_IDENTIFIERS.get(camera_key, "")
                    break
            if not serial and not configured_identifier:
                continue
            entry: dict[str, Any] = {
                "serial": serial,
                "name": product_name,
                "product_line": "D400" if re.search(r"\b(?:d)?4\d{2}f?\b", product_name, re.IGNORECASE) else "",
                "usb_type": "",
                "physical_port": device_path.name,
                "asic_serial": "",
            }
            if not serial:
                entry["configured_identifier"] = configured_identifier
            entry.update(self._realsense_usb_link_metadata(entry, sysfs_root=sysfs_root))
            entries.append(entry)
        return entries

    def _scan_realsense_camera_entries_via_lerobot_env(self) -> list[dict[str, Any]]:
        script = r"""
import json
import pyrealsense2 as rs

entries = []
ctx = rs.context()
for device in ctx.query_devices():
    row = {}
    key_map = {
        "name": "name",
        "serial_number": "serial",
        "product_line": "product_line",
        "usb_type_descriptor": "usb_type",
        "physical_port": "physical_port",
        "asic_serial_number": "asic_serial",
    }
    for key, output_key in key_map.items():
        try:
            info = getattr(rs.camera_info, key)
            row[output_key] = str(device.get_info(info) or "").strip() if device.supports(info) else ""
        except Exception:
            row[output_key] = ""
    if row.get("serial") or row.get("name"):
        entries.append(row)
print(json.dumps(entries))
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        for line in reversed((completed.stdout or "").splitlines()):
            text = line.strip()
            if not text.startswith("["):
                continue
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            if isinstance(parsed, list):
                entries: list[dict[str, Any]] = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    entry = dict(item)
                    entry.update(self._realsense_usb_link_metadata(entry))
                    entries.append(entry)
                return entries
        return []

    @classmethod
    def _realsense_entry_for_identifier(cls, identifier: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        needle = cls._device_match_token(identifier)
        if not needle:
            return {}
        for entry in entries:
            values = [
                str(entry.get("serial") or ""),
                str(entry.get("configured_identifier") or ""),
                str(entry.get("name") or ""),
                str(entry.get("product_line") or ""),
                f"{entry.get('name') or ''} {entry.get('product_line') or ''}",
            ]
            if any(needle == cls._device_match_token(value) for value in values):
                return dict(entry)
        return {}

    @classmethod
    def _realsense_usb_link_metadata(
        cls,
        entry: dict[str, Any],
        *,
        sysfs_root: Path = Path("/sys/bus/usb/devices"),
    ) -> dict[str, Any]:
        raw_usb_type = str(entry.get("usb_type") or entry.get("usb_type_descriptor") or "").strip()
        type_match = re.search(r"(\d+(?:\.\d+)?)", raw_usb_type)
        usb_type = type_match.group(1) if type_match else ""
        speed = cls._realsense_sysfs_usb_speed_mbps(entry, sysfs_root=sysfs_root)
        major = int(usb_type.split(".", 1)[0]) if usb_type else 0
        if speed is None:
            speed = 5000 if major >= 3 else 480 if major == 2 else 12 if major == 1 else None
        if not usb_type and speed is not None:
            usb_type = "3.x" if speed >= 5000 else "2.x" if speed >= 480 else "1.x"
        if speed is None and not usb_type:
            return {
                "usb_type": "",
                "usb_speed_mbps": None,
                "usb_link_label": "USB link unknown",
                "usb_link_status": "unknown",
            }
        status = "ok" if speed is not None and speed >= 5000 else "warning"
        label = f"USB {usb_type}"
        if speed is not None:
            label += f" · {speed} Mbps"
        if status == "warning":
            label += " · rollout risk"
        return {
            "usb_type": usb_type,
            "usb_speed_mbps": speed,
            "usb_link_label": label,
            "usb_link_status": status,
        }

    @classmethod
    def _realsense_sysfs_usb_speed_mbps(cls, entry: dict[str, Any], *, sysfs_root: Path) -> int | None:
        if not sysfs_root.is_dir():
            return None
        asic_serial = str(entry.get("asic_serial") or entry.get("asic_serial_number") or "").strip()
        physical_port = str(entry.get("physical_port") or "").strip()
        topology_match = re.search(r"(\d+-\d+(?:\.\d+)*)", physical_port)
        topology = topology_match.group(1) if topology_match else ""
        for device_path in sorted(sysfs_root.iterdir()):
            if not device_path.is_dir():
                continue
            vendor = cls._read_sysfs_text(device_path / "idVendor").lower()
            if vendor and vendor != "8086":
                continue
            serial = cls._read_sysfs_text(device_path / "serial")
            serial_match = bool(asic_serial and serial == asic_serial)
            topology_match_found = bool(topology and device_path.name == topology)
            if not serial_match and not topology_match_found:
                continue
            raw_speed = cls._read_sysfs_text(device_path / "speed")
            try:
                return int(round(float(raw_speed)))
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _read_sysfs_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""

    @classmethod
    def _realsense_identifier_available(cls, identifier: str, entries: list[dict[str, Any]]) -> bool:
        return bool(cls._realsense_entry_for_identifier(identifier, entries))

    @classmethod
    def _realsense_visible_summary(cls, entries: list[dict[str, Any]]) -> str:
        visible: list[str] = []
        for entry in entries:
            serial = str(entry.get("serial") or "").strip()
            configured_identifier = str(entry.get("configured_identifier") or "").strip()
            name = str(entry.get("name") or "").strip()
            if serial:
                visible.append(serial)
            elif configured_identifier:
                visible.append(f"{configured_identifier} ({name})" if name else configured_identifier)
            elif name:
                visible.append(name)
        return ", ".join(visible) if visible else "none"

    @staticmethod
    def _device_match_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    @staticmethod
    def _camera_port_available(port: str) -> bool:
        raw = str(port or "").strip()
        if not raw:
            return False
        if raw.isdigit():
            return Path(f"/dev/video{raw}").exists()
        if raw.startswith("/dev/"):
            return Path(raw).exists()
        return True

    def _load_device_memory(self) -> dict[str, Any]:
        path = self.config.device_memory_path
        if not path.exists():
            return {"version": 1, "profiles": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "profiles": {}}
        if not isinstance(data, dict):
            return {"version": 1, "profiles": {}}
        data.setdefault("version", 1)
        data.setdefault("profiles", {})
        return data

    def _save_device_memory(self, memory: dict[str, Any]) -> None:
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.config.device_memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.device_memory_path.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _profile_device_memory(memory: dict[str, Any], profile_id: str) -> dict[str, Any]:
        profiles = memory.setdefault("profiles", {})
        profile_memory = profiles.setdefault(profile_id, {})
        devices = profile_memory.setdefault("devices", {})
        devices.setdefault("cameras", {})
        profile_memory.setdefault("baselines", {})
        return profile_memory

    @staticmethod
    def _device_memory_key(role: str, camera_key: str = "") -> str:
        return f"camera:{camera_key or 'top'}" if role == "camera" else role

    def _save_device_port(
        self,
        profile_id: str,
        role: str,
        port: str,
        *,
        camera_key: str = "top",
        source: str = "manual",
        memory: dict[str, Any] | None = None,
        prefer_identity_link: bool = True,
        camera_backend: str = "opencv",
        camera_use_depth: bool = False,
        camera_fps: int | None = None,
        camera_width: int = LEROBOT_DEFAULT_CAMERA_WIDTH,
        camera_height: int = LEROBOT_DEFAULT_CAMERA_HEIGHT,
        raw_port: str = "",
        camera_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = memory or self._load_device_memory()
        profile_memory = self._profile_device_memory(data, profile_id)
        backend = self._normalize_camera_backend(camera_backend) if role == "camera" else ""
        stable_port = (
            str(port or "").strip()
            if role == "camera" and backend == LEROBOT_REALSENSE_TYPE
            else self._stable_device_port(port, role)
            if prefer_identity_link
            else str(port or "").strip()
        )
        device = {
            "role": role,
            "port": stable_port,
            "source": source,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        original_port = str(raw_port or port or "").strip()
        if original_port and stable_port != original_port:
            device["raw_port"] = original_port
            device["stability"] = "persistent_path"
        if self._is_device_identity_link(stable_port):
            device["device_id"] = Path(stable_port).name
            device["device_link"] = stable_port
            serial_number = self._serial_number_from_device_id(device["device_id"])
            if serial_number:
                device["serial_number"] = serial_number
        if role == "camera":
            key = camera_key or "top"
            device["camera_key"] = key
            device["backend"] = backend or "opencv"
            if backend == LEROBOT_REALSENSE_TYPE:
                device["serial_number_or_name"] = stable_port
                device["color_format"] = self._realsense_color_format(key, stable_port)
                device["use_depth"] = True
                device["depth_scale_m_per_unit"] = self._realsense_depth_scale_m_per_unit(key, stable_port)
                device["fps"] = _safe_int(camera_fps, LEROBOT_DEFAULT_REALSENSE_FPS, minimum=1)
                device["width"] = _safe_int(camera_width, LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1)
                device["height"] = _safe_int(camera_height, LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1)
                device["channel_plan"] = "rgb_plus_depth"
                link_metadata = camera_metadata or self._realsense_usb_link_metadata({})
                for field in ("usb_type", "usb_speed_mbps", "usb_link_label", "usb_link_status"):
                    device[field] = link_metadata.get(field)
            devices = profile_memory.setdefault("devices", {})
            devices.setdefault("cameras", {})[key] = device
            if key == "top":
                devices["camera"] = device
        else:
            profile_memory.setdefault("devices", {})[role] = device
        self._save_device_memory(data)
        return device

    def _serial_identity_map(self, ports: list[str]) -> dict[str, dict[str, str]]:
        identity_map: dict[str, dict[str, str]] = {}
        for raw_port in ports:
            port = str(raw_port or "").strip()
            if not port:
                continue
            identity = port if self._is_device_identity_link(port) else self._matching_symlink(port, ["/dev/serial/by-id/*"])
            if not identity:
                continue
            device_id = Path(identity).name
            serial_number = self._serial_number_from_device_id(device_id)
            identity_map[port] = {
                "port": identity,
                "device_id": device_id,
                "device_link": identity,
                "serial_number": serial_number,
            }
            identity_map.setdefault(identity, identity_map[port])
        return identity_map

    @staticmethod
    def _expected_motor_ids_for_role(role: str) -> set[int]:
        if role in {"follower", "robot"}:
            return {11, 12, 13, 14, 15, 16}
        if role in {"leader", "teleop"}:
            return {1, 2, 3, 4, 5, 6}
        return set()

    @staticmethod
    def _conflicting_motor_ids_for_role(role: str) -> set[int]:
        if role in {"follower", "robot"}:
            return {1, 2, 3, 4, 5, 6}
        if role in {"leader", "teleop"}:
            return {11, 12, 13, 14, 15, 16}
        return set()

    def _serial_candidate_role_verification(self, candidate: str, role: str) -> dict[str, Any]:
        expected = self._expected_motor_ids_for_role(role)
        conflicting = self._conflicting_motor_ids_for_role(role)
        motor_ids = set(self._serial_motor_ids(candidate))
        matched = sorted(expected & motor_ids)
        unexpected_role_motor_ids = sorted(conflicting & motor_ids)
        minimum_match_count = min(3, len(expected)) if expected else 0
        exact = bool(expected and expected.issubset(motor_ids))
        partial = bool(len(matched) >= minimum_match_count and not unexpected_role_motor_ids)
        ok = bool(exact or partial)
        return {
            "port": str(candidate),
            "role": role,
            "ok": ok,
            "status": "exact" if exact else "partial" if ok else "failed",
            "motor_ids": sorted(motor_ids),
            "expected_motor_ids": sorted(expected),
            "matched_motor_ids": matched,
            "missing_motor_ids": sorted(expected - motor_ids),
            "unexpected_role_motor_ids": unexpected_role_motor_ids,
        }

    def _select_serial_candidate_with_role_verification(self, candidates: list[str], role: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        verifications: list[dict[str, Any]] = []
        for candidate in candidates:
            verification = self._serial_candidate_role_verification(candidate, role)
            verifications.append(verification)
            if verification.get("ok"):
                return str(candidate), verification, verifications
        return "", {}, verifications

    def _select_serial_candidate_by_motor_ids(self, candidates: list[str], role: str) -> str:
        selected, _, _ = self._select_serial_candidate_with_role_verification(candidates, role)
        return selected

    def _open_follower_joint_position_reader(self, port: str, motor_ids: list[int]) -> _SubprocessFollowerJointPositionReader:
        """Open a reusable OMX follower joint reader without commanding motion."""
        return _SubprocessFollowerJointPositionReader(self, port, motor_ids)

    def _read_follower_joint_positions(self, port: str, motor_ids: list[int]) -> dict[int, float]:
        """Read current OMX follower positions in Isaac joint units without writing motor state."""
        with self._open_follower_joint_position_reader(port, motor_ids) as reader:
            return reader.read()

    def _read_follower_joint_positions_legacy_subprocess(self, port: str, motor_ids: list[int]) -> dict[int, float]:
        """Legacy one-shot reader kept for diagnostics and fallback comparisons."""
        raw_port = str(port or "").strip()
        requested_ids = [int(item) for item in motor_ids]
        if not raw_port:
            raise ValueError("follower port is empty")
        script = r"""
import importlib
import json
import sys
from pathlib import Path

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.dynamixel import DynamixelMotorsBus

port = sys.argv[1]
requested_ids = {int(item) for item in json.loads(sys.argv[2])}
motors = {
    "shoulder_pan": Motor(11, "xl430-w250", MotorNormMode.DEGREES),
    "shoulder_lift": Motor(12, "xl430-w250", MotorNormMode.RANGE_M100_100),
    "elbow_flex": Motor(13, "xl430-w250", MotorNormMode.RANGE_M100_100),
    "wrist_flex": Motor(14, "xl330-m288", MotorNormMode.RANGE_M100_100),
    "wrist_roll": Motor(15, "xl330-m288", MotorNormMode.DEGREES),
    "gripper": Motor(16, "xl330-m288", MotorNormMode.RANGE_0_100),
}
limits = {
    11: (-270.0, 360.0, "degrees"),
    12: (-120.0, 90.0, "range_m100_100"),
    13: (-120.0, 90.0, "range_m100_100"),
    14: (-100.0, 100.0, "range_m100_100"),
    15: (-270.0, 270.0, "degrees"),
    16: (0.0, 100.0, "range_0_100"),
}
calibration = {}
try:
    module = importlib.import_module("lerobot.robots.omx_follower.omx_follower")
    calib_path = Path(module.__file__).parent / "calibration" / "omx_follower_arm.json"
    if calib_path.exists():
        raw_calib = json.loads(calib_path.read_text(encoding="utf-8"))
        calibration = {name: MotorCalibration(**value) for name, value in raw_calib.items()}
except Exception:
    calibration = {}
bus = DynamixelMotorsBus(port, motors, calibration=calibration)
full_turn_deg_per_norm = 1.8
try:
    bus.connect(handshake=False)
    bus.set_baudrate(bus.default_baudrate)
    raw = bus.sync_read("Present_Position", normalize=False, num_retry=1)
    normalized = {}
    if calibration:
        try:
            normalized = bus.sync_read("Present_Position", normalize=True, num_retry=1)
        except Exception:
            normalized = {}
    values = {}
    for name, motor in motors.items():
        if motor.id not in requested_ids:
            continue
        lower, upper, norm_mode = limits[motor.id]
        raw_value = float(raw.get(name, 0.0))
        if name in normalized:
            norm_value = float(normalized[name])
            if norm_mode == "range_m100_100":
                value = norm_value * full_turn_deg_per_norm
            else:
                value = norm_value
        else:
            if norm_mode == "range_m100_100":
                value = ((raw_value / 4095.0) * 360.0) - 180.0
            else:
                value = lower + (raw_value / 4095.0) * (upper - lower)
        values[str(motor.id)] = value
finally:
    try:
        bus.port_handler.closePort()
    except Exception:
        pass
print(json.dumps(values, sort_keys=True))
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
            raw_port,
            json.dumps(requested_ids),
        ]
        completed = subprocess.run(
            command,
            cwd=str(self.config.repo_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=12,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stdout or "").strip() or f"returncode={completed.returncode}")
        for line in reversed((completed.stdout or "").splitlines()):
            text = line.strip()
            if not text.startswith("{"):
                continue
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return {
                    _safe_int(key, -1, minimum=0): _safe_float(value, 0.0)
                    for key, value in parsed.items()
                    if _safe_int(key, -1, minimum=0) in requested_ids
                }
        raise RuntimeError("no JSON joint position payload returned")

    def _serial_motor_ids(self, port: str) -> list[int]:
        raw_port = str(port or "").strip()
        if not raw_port:
            return []
        script = r"""
import json
import sys
from lerobot.motors.dynamixel import DynamixelMotorsBus

port = sys.argv[1]
bus = DynamixelMotorsBus(port, {})
ids = []
try:
    bus._connect(handshake=False)
    bus.set_baudrate(bus.default_baudrate)
    for motor_id in range(1, 17):
        if bus.ping(motor_id) is not None:
            ids.append(motor_id)
finally:
    try:
        bus.port_handler.closePort()
    except Exception:
        pass
print(json.dumps(ids))
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "--no-capture-output",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
            raw_port,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=12,
                check=False,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        for line in reversed((completed.stdout or "").splitlines()):
            text = line.strip()
            if not text.startswith("["):
                continue
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            if isinstance(parsed, list):
                return [_safe_int(item, -1, minimum=0) for item in parsed if _safe_int(item, -1, minimum=0) >= 0]
        return []

    @staticmethod
    def _baseline_serial_identity_port(baseline: dict[str, Any], port: str) -> str:
        raw = str(port or "").strip()
        if not raw:
            return raw
        serial_map = baseline.get("serial_identity_map", {})
        if not isinstance(serial_map, dict):
            return raw
        entry = serial_map.get(raw)
        if not isinstance(entry, dict):
            return raw
        return str(entry.get("port") or entry.get("device_link") or raw)

    @staticmethod
    def _serial_number_from_device_id(device_id: str) -> str:
        name = Path(str(device_id or "").strip()).name
        if not name:
            return ""
        match = re.search(r"_([A-Za-z0-9]+)-if\d+$", name)
        if match:
            return match.group(1)
        return name

    def _saved_device_identity_link(self, saved: dict[str, Any], role: str) -> str:
        fallback = ""
        for key in ("device_link", "port"):
            value = str(saved.get(key) or "").strip()
            if value:
                if self._is_device_identity_link(value):
                    try:
                        if Path(value).resolve(strict=True):
                            return value
                    except Exception:
                        fallback = fallback or value
                        continue
                return value
        device_id = str(saved.get("device_id") or "").strip()
        if not device_id:
            return fallback
        return self._device_id_link(device_id, role) or fallback

    def _device_id_link(self, device_id: str, role: str) -> str:
        name = Path(device_id).name
        patterns = ["/dev/v4l/by-id/*", "/dev/v4l/by-path/*"] if role == "camera" else ["/dev/serial/by-id/*"]
        for pattern in patterns:
            for candidate in sorted(glob.glob(pattern)):
                if Path(candidate).name == name:
                    return candidate
        return ""

    @staticmethod
    def _is_device_identity_link(port: str) -> bool:
        return port.startswith("/dev/serial/by-id/") or port.startswith("/dev/v4l/by-id/") or port.startswith("/dev/v4l/by-path/")

    @staticmethod
    def _device_port_available(port: str) -> bool:
        raw = str(port or "").strip()
        return bool(raw) and Path(raw).exists()

    def _runtime_device_port(self, port: str, role: str, *, live: bool) -> str:
        """Use stable live device identity paths when available.

        PySerial can open /dev/serial/by-id symlinks directly. Keeping the identity
        path in the LeRobot command avoids baking in a transient /dev/ttyACM* name
        after USB re-enumeration.
        """
        raw = str(port or "").strip()
        if not raw or not live:
            return raw
        return raw

    def _stable_device_port(self, port: str, role: str) -> str:
        """Prefer persistent Linux by-id/by-path symlinks over ttyACM/video numbers."""
        raw = str(port or "").strip()
        if not raw:
            return raw
        if raw.startswith("/dev/serial/by-id/") or raw.startswith("/dev/v4l/by-id/") or raw.startswith("/dev/v4l/by-path/"):
            return raw
        if role == "camera":
            if raw.isdigit():
                candidate = f"/dev/video{raw}"
            elif raw.startswith("/dev/video"):
                candidate = raw
            else:
                return raw
            return self._matching_symlink(candidate, ["/dev/v4l/by-id/*", "/dev/v4l/by-path/*"]) or candidate
        if not (raw.startswith("/dev/ttyACM") or raw.startswith("/dev/ttyUSB")):
            return raw
        return self._matching_symlink(raw, ["/dev/serial/by-id/*"]) or raw

    @staticmethod
    def _matching_symlink(device_path: str, patterns: list[str]) -> str:
        try:
            target = Path(device_path).resolve(strict=True)
        except Exception:
            return ""
        for pattern in patterns:
            for symlink in sorted(glob.glob(pattern)):
                try:
                    if Path(symlink).resolve(strict=True) == target:
                        return symlink
                except Exception:
                    continue
        return ""

    def _saved_devices(self, profile_id: str) -> dict[str, dict[str, Any]]:
        memory = self._load_device_memory()
        profile_memory = memory.get("profiles", {}).get(profile_id, {})
        devices = profile_memory.get("devices", {})
        saved = {str(role): dict(value) for role, value in devices.items() if isinstance(value, dict)}
        cameras = devices.get("cameras", {})
        if isinstance(cameras, dict):
            saved["cameras"] = {str(key): dict(value) for key, value in cameras.items() if isinstance(value, dict)}
        if "camera" in saved and "cameras" not in saved:
            camera = saved["camera"]
            key = str(camera.get("camera_key") or "top")
            saved["cameras"] = {key: camera}
        return saved

    def _saved_camera_device(self, profile_id: str, camera_key: str) -> dict[str, Any]:
        saved = self._saved_devices(profile_id)
        cameras = saved.get("cameras", {})
        if isinstance(cameras, dict):
            camera = cameras.get(camera_key)
            if isinstance(camera, dict):
                return camera
        legacy = saved.get("camera", {})
        if isinstance(legacy, dict) and str(legacy.get("camera_key") or "top") == camera_key:
            return legacy
        return {}

    def _device_memory_public(self) -> dict[str, Any]:
        memory = self._load_device_memory()
        return {
            "path": str(self.config.device_memory_path),
            "updated_at": memory.get("updated_at", ""),
            "profiles": memory.get("profiles", {}),
        }

    def _fake_camera_capture(self, profile: RobotProfile, camera_key: str, camera_port: str) -> dict[str, Any]:
        capture_dir = self.config.repo_root / "artifacts" / "lerobot" / "camera_tests"
        capture_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = capture_dir / f"{profile.profile_id}_{camera_key}_{timestamp}.png"
        image = Image.new("RGB", (960, 540), (210, 210, 210))
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 930, 510), fill=(245, 245, 245), outline=(20, 54, 179), width=4)
        # Test-mode ActiveCam evidence includes a deterministic red specimen in
        # the same workspace ROI consumed by VisionAgent.
        draw.rectangle((410, 150, 550, 300), fill=(225, 30, 35))
        image.save(path, format="PNG")
        return {
            "ok": True,
            "path": str(path),
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
            "width": 960,
            "height": 540,
            "synthetic": True,
        }

    def _live_camera_capture(self, profile: RobotProfile, camera_key: str, camera_port: str, *, camera_device: dict[str, Any] | None = None) -> dict[str, Any]:
        capture_dir = self.config.repo_root / "artifacts" / "lerobot" / "camera_tests"
        capture_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = capture_dir / f"{profile.profile_id}_{camera_key}_{timestamp}.jpg"
        if self._normalize_camera_backend((camera_device or {}).get("backend")) == LEROBOT_REALSENSE_TYPE:
            return self._live_realsense_camera_capture(camera_device or {}, path)
        capture_ref = self._opencv_capture_ref(camera_port)
        try:
            import cv2  # type: ignore[import-not-found]
        except Exception as exc:
            return self._live_camera_capture_via_lerobot_env(capture_ref, path, exc)
        cap = cv2.VideoCapture(capture_ref)
        try:
            if not cap.isOpened():
                return {"ok": False, "failure_code": "LEROBOT_CAMERA_OPEN_FAILED", "message": f"Could not open camera: {camera_port}"}
            ok, frame = cap.read()
            if not ok or frame is None:
                return {"ok": False, "failure_code": "LEROBOT_CAMERA_FRAME_FAILED", "message": f"Could not read frame from camera: {camera_port}"}
            if not cv2.imwrite(str(path), frame):
                return {"ok": False, "failure_code": "LEROBOT_CAMERA_WRITE_FAILED", "message": f"Could not write camera frame: {path}"}
            height, width = frame.shape[:2]
            return {
                "ok": True,
                "path": str(path),
                "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
                "width": width,
                "height": height,
                "synthetic": False,
            }
        finally:
            cap.release()

    def _live_realsense_camera_capture(self, camera_device: dict[str, Any], path: Path) -> dict[str, Any]:
        identifier = str(camera_device.get("serial_number_or_name") or camera_device.get("port") or "").strip()
        if not identifier:
            return {"ok": False, "failure_code": "LEROBOT_REALSENSE_IDENTIFIER_REQUIRED", "message": "RealSense serial_number_or_name is required."}
        try:
            from lerobot.cameras.realsense import RealSenseCamera, RealSenseCameraConfig  # type: ignore[import-not-found]
        except Exception as exc:
            return self._live_realsense_camera_capture_via_lerobot_env(camera_device, path, exc)
        try:
            config = RealSenseCameraConfig(
                serial_number_or_name=identifier,
                fps=self._camera_fps(camera_device),
                width=_safe_int(camera_device.get("width"), LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1),
                height=_safe_int(camera_device.get("height"), LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1),
                color_format=self._realsense_color_format(identifier=identifier, camera_device=camera_device),
                use_depth=self._camera_use_depth(camera_device, default=True),
            )
            camera = RealSenseCamera(config)
            camera.connect(warmup=True)
            try:
                frame = camera.read()
            finally:
                camera.disconnect()
        except Exception as exc:
            return {"ok": False, "failure_code": "LEROBOT_REALSENSE_CAPTURE_FAILED", "message": f"RealSense capture failed for {identifier}: {exc}"}
        try:
            import cv2  # type: ignore[import-not-found]
            if not cv2.imwrite(str(path), frame):
                return {"ok": False, "failure_code": "LEROBOT_CAMERA_WRITE_FAILED", "message": f"Could not write RealSense frame: {path}"}
            height, width = frame.shape[:2]
        except Exception as exc:
            return {"ok": False, "failure_code": "LEROBOT_CAMERA_WRITE_FAILED", "message": f"Could not write RealSense frame: {exc}"}
        return {
            "ok": True,
            "path": str(path),
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
            "width": int(width),
            "height": int(height),
            "synthetic": False,
            "backend": LEROBOT_REALSENSE_TYPE,
            "use_depth": self._camera_use_depth(camera_device, default=True),
        }

    def _live_realsense_camera_capture_via_lerobot_env(
        self,
        camera_device: dict[str, Any],
        path: Path,
        import_error: Exception,
    ) -> dict[str, Any]:
        """Capture a RealSense frame from the LeRobot conda env when the app env lacks lerobot."""
        device = dict(camera_device or {})
        identifier = str(device.get("serial_number_or_name") or device.get("port") or "").strip()
        if not identifier:
            return {"ok": False, "failure_code": "LEROBOT_REALSENSE_IDENTIFIER_REQUIRED", "message": "RealSense serial_number_or_name is required."}
        payload = {
            "serial_number_or_name": identifier,
            "fps": self._camera_fps(device),
            "width": _safe_int(device.get("width"), LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1),
            "height": _safe_int(device.get("height"), LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1),
            "color_format": self._realsense_color_format(identifier=identifier, camera_device=device),
            "use_depth": self._camera_use_depth(device, default=True),
            "align_depth_to_color": bool(self.config.realsense_depth_align_to_color),
            "depth_scale_m_per_unit": self._realsense_depth_scale_m_per_unit(
                str(device.get("camera_key") or ""),
                identifier,
                device,
            ),
            "depth_clip_min_mm": float(self.config.realsense_depth_clip_min_mm),
            "depth_clip_max_mm": float(self.config.realsense_depth_clip_max_mm),
            "warmup_s": LEROBOT_DEFAULT_REALSENSE_WARMUP_S,
        }
        script = """
import cv2
import json
import sys

from lerobot.cameras.realsense import RealSenseCamera, RealSenseCameraConfig

device = json.loads(sys.argv[1])
output_path = sys.argv[2]
camera = RealSenseCamera(
    RealSenseCameraConfig(
        serial_number_or_name=device["serial_number_or_name"],
        fps=int(device["fps"]),
        width=int(device["width"]),
        height=int(device["height"]),
        color_format=str(device["color_format"]),
        use_depth=bool(device["use_depth"]),
        align_depth_to_color=bool(device["align_depth_to_color"]),
        depth_scale_m_per_unit=float(device["depth_scale_m_per_unit"]),
        depth_clip_min_mm=float(device["depth_clip_min_mm"]),
        depth_clip_max_mm=float(device["depth_clip_max_mm"]),
        warmup_s=int(device["warmup_s"]),
    )
)
try:
    camera.connect(warmup=True)
    frame = camera.read()
finally:
    try:
        camera.disconnect()
    except Exception:
        pass
if frame is None:
    print(json.dumps({"ok": False, "failure_code": "LEROBOT_REALSENSE_FRAME_FAILED", "message": "RealSense frame is empty"}))
    sys.exit(3)
height, width = frame.shape[:2]
frame_to_write = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR) if len(frame.shape) == 3 and frame.shape[2] >= 3 else frame
if not cv2.imwrite(output_path, frame_to_write):
    print(json.dumps({"ok": False, "failure_code": "LEROBOT_CAMERA_WRITE_FAILED", "message": f"Could not write RealSense frame: {output_path}"}))
    sys.exit(4)
print(json.dumps({"ok": True, "width": int(width), "height": int(height)}))
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
            json.dumps(payload, ensure_ascii=True),
            str(path),
        ]
        try:
            result = subprocess.run(command, cwd=str(self.config.repo_root), text=True, capture_output=True, timeout=60)
        except Exception as exc:
            return {
                "ok": False,
                "failure_code": "LEROBOT_REALSENSE_BACKEND_MISSING",
                "message": (
                    f"RealSense import failed in app env ({import_error.__class__.__name__}: {import_error}) "
                    f"and conda capture failed: {exc.__class__.__name__}: {exc}"
                ),
            }
        parsed: dict[str, Any] = {}
        for line in reversed((result.stdout or "").splitlines()):
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                parsed = value
                break
        if not parsed:
            return {
                "ok": False,
                "failure_code": "LEROBOT_REALSENSE_BACKEND_MISSING",
                "message": (
                    f"RealSense import failed in app env ({import_error.__class__.__name__}: {import_error}); "
                    f"conda capture returncode={result.returncode}; stderr={result.stderr[-1000:]}"
                ),
            }
        if not parsed.get("ok"):
            return parsed
        return {
            "ok": True,
            "path": str(path),
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
            "width": int(parsed.get("width", 0) or 0),
            "height": int(parsed.get("height", 0) or 0),
            "synthetic": False,
            "backend": "conda_lerobot_realsense",
            "use_depth": self._camera_use_depth(device, default=True),
        }

    @staticmethod
    def _opencv_capture_ref(camera_port: str) -> int | str:
        value = str(camera_port)
        if value.isdigit():
            return int(value)
        return value

    def _live_camera_capture_via_lerobot_env(self, capture_ref: int | str, path: Path, import_error: Exception) -> dict[str, Any]:
        script = """
import cv2
import json
import sys

capture_ref_raw = sys.argv[1]
output_path = sys.argv[2]
capture_ref = int(capture_ref_raw) if capture_ref_raw.isdigit() else capture_ref_raw
cap = cv2.VideoCapture(capture_ref)
try:
    if not cap.isOpened():
        print(json.dumps({"ok": False, "failure_code": "LEROBOT_CAMERA_OPEN_FAILED", "message": f"Could not open camera: {capture_ref_raw}"}))
        sys.exit(2)
    ok, frame = cap.read()
    if not ok or frame is None:
        print(json.dumps({"ok": False, "failure_code": "LEROBOT_CAMERA_FRAME_FAILED", "message": f"Could not read frame from camera: {capture_ref_raw}"}))
        sys.exit(3)
    if not cv2.imwrite(output_path, frame):
        print(json.dumps({"ok": False, "failure_code": "LEROBOT_CAMERA_WRITE_FAILED", "message": f"Could not write camera frame: {output_path}"}))
        sys.exit(4)
    height, width = frame.shape[:2]
    print(json.dumps({"ok": True, "width": width, "height": height}))
finally:
    cap.release()
""".strip()
        command = [
            self.config.conda_executable,
            "run",
            "-n",
            self.config.conda_env_name,
            "python",
            "-c",
            script,
            str(capture_ref),
            str(path),
        ]
        try:
            result = subprocess.run(command, cwd=str(self.config.repo_root), text=True, capture_output=True, timeout=20)
        except Exception as exc:
            return {
                "ok": False,
                "failure_code": "LEROBOT_CAMERA_BACKEND_MISSING",
                "message": f"OpenCV import failed in app env ({import_error.__class__.__name__}: {import_error}) and conda capture failed: {exc.__class__.__name__}: {exc}",
            }
        parsed: dict[str, Any] = {}
        for line in reversed((result.stdout or "").splitlines()):
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                parsed = value
                break
        if not parsed:
            return {
                "ok": False,
                "failure_code": "LEROBOT_CAMERA_BACKEND_MISSING",
                "message": f"OpenCV import failed in app env ({import_error.__class__.__name__}: {import_error}); conda capture returncode={result.returncode}; stderr={result.stderr[-1000:]}",
            }
        if not parsed.get("ok"):
            return parsed
        return {
            "ok": True,
            "path": str(path),
            "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
            "width": int(parsed.get("width", 0) or 0),
            "height": int(parsed.get("height", 0) or 0),
            "synthetic": False,
            "backend": "conda_lerobot_opencv",
        }

    def _path_status(self) -> dict[str, Any]:
        return {
            "device_memory_path": str(self.config.device_memory_path),
            "dataset_root": str(self.config.dataset_root),
            "output_root": str(self.config.output_root),
            "policy_root": str(self.config.policy_root),
            "session_log_root": str(self.config.session_log_root),
            "fake_dataset_root": str(self.config.fake_dataset_root),
            "fake_checkpoint_root": str(self.config.fake_checkpoint_root),
        }

    def _workflow_defaults_status(self) -> dict[str, Any]:
        """Return date-scoped GUI defaults for recording, training, and rollout."""
        run_name = self._next_recording_run_name()
        train_name = f"{run_name}_train({LEROBOT_DEFAULT_TRAIN_POLICY_TYPE})"
        return {
            "run_name": run_name,
            "dataset_repo_id": f"jin/{run_name}",
            "train_name": train_name,
            "output_dir": str((self.config.output_root / train_name).resolve()),
            "job_name": train_name,
            "record_task_instruction": LEROBOT_DEFAULT_TASK_INSTRUCTION,
            "rollout_task_instruction": LEROBOT_DEFAULT_TASK_INSTRUCTION,
            "record_num_episodes": LEROBOT_DEFAULT_RECORD_NUM_EPISODES,
            "record_episode_time_s": 60,
        }

    def _next_recording_run_name(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        next_index = self._highest_date_run_index(today) + 1
        return f"{today}_{next_index}"

    def _highest_date_run_index(self, date_prefix: str) -> int:
        pattern = re.compile(rf"^{re.escape(date_prefix)}_(\d+)(?:_train(?:\([A-Za-z0-9_.-]+\))?)?$")
        highest = 0
        candidates: list[Path] = []
        dataset_namespace = self.config.dataset_root / "jin"
        if dataset_namespace.exists():
            candidates.extend(dataset_namespace.iterdir())
        if self.config.output_root.exists():
            candidates.extend(self.config.output_root.iterdir())
        for path in candidates:
            match = pattern.match(path.name)
            if not match:
                continue
            try:
                highest = max(highest, int(match.group(1)))
            except ValueError:
                continue
        return highest

    def _environment_status(self) -> dict[str, Any]:
        conda = shutil.which(self.config.conda_executable) or self.config.conda_executable
        return {
            "conda_executable": conda,
            "conda_env_name": self.config.conda_env_name,
            "available": bool(conda),
            "expected_python": str(Path.home() / "miniconda3" / "envs" / self.config.conda_env_name / "bin" / "python"),
            "train_video_backend": self.config.train_video_backend,
            "train_video_backend_fallback": self.config.train_video_backend_fallback,
            "pi05": {
                "conda_env_name": self.config.pi05_conda_env_name,
                "repo_root": str(self.config.pi05_repo_root),
                "hf_home": str(self.config.pi05_hf_home),
                "hf_hub_cache": str(self.config.pi05_hf_home / "hub"),
                "base_policy": self.config.pi05_base_policy,
                "train_video_backend": self.config.pi05_video_backend,
                "train_video_backend_fallback": self.config.train_video_backend_fallback,
                "available": (Path.home() / "miniconda3" / "envs" / self.config.pi05_conda_env_name / "bin" / "lerobot-train").exists(),
            },
            "xvla": {
                "conda_env_name": self.config.xvla_conda_env_name,
                "base_policy": self.config.xvla_base_policy,
                "train_video_backend": self.config.train_video_backend,
                "train_video_backend_fallback": self.config.train_video_backend_fallback,
                "available": (Path.home() / "miniconda3" / "envs" / self.config.xvla_conda_env_name / "bin" / "lerobot-train").exists(),
            },
            "smolvla": {
                "conda_env_name": self.config.smolvla_conda_env_name,
                "base_policy": self.config.smolvla_base_policy,
                "train_video_backend": self.config.train_video_backend,
                "train_video_backend_fallback": self.config.train_video_backend_fallback,
                "available": (Path.home() / "miniconda3" / "envs" / self.config.smolvla_conda_env_name / "bin" / "lerobot-train").exists(),
            },
        }

    def _policy_presets(self) -> list[dict[str, str]]:
        defaults = [
            {"label": "Manual policy path", "value": "", "source": "manual", "policy_type": ""},
            {"label": "lerobot/act_koch_real", "value": "lerobot/act_koch_real", "repo_id": "lerobot/act_koch_real", "source": "huggingface", "policy_type": "act"},
            {"label": "Pi0.5 base", "value": self.config.pi05_base_policy, "repo_id": self.config.pi05_base_policy, "source": "huggingface", "policy_type": "pi05"},
            {"label": "X-VLA base", "value": self.config.xvla_base_policy, "repo_id": self.config.xvla_base_policy, "source": "huggingface", "policy_type": "xvla"},
            {"label": "SmolVLA base", "value": self.config.smolvla_base_policy, "repo_id": self.config.smolvla_base_policy, "source": "huggingface", "policy_type": "smolvla"},
            {"label": "Pi0 base", "value": "lerobot/pi0_base", "repo_id": "lerobot/pi0_base", "source": "huggingface", "policy_type": "pi0"},
            {"label": "Pi0FAST base", "value": "lerobot/pi0fast-base", "repo_id": "lerobot/pi0fast-base", "source": "huggingface", "policy_type": "pi0fast"},
        ]
        presets = []
        for item in self.config.policy_presets:
            value = str(item.get("value") or item.get("path") or item.get("repo_id") or "")
            presets.append(
                {
                    "label": str(item.get("label") or value or "policy"),
                    "value": value,
                    "path": str(item.get("path") or ""),
                    "repo_id": str(item.get("repo_id") or ""),
                    "source": str(item.get("source") or "config"),
                    "policy_type": str(item.get("policy_type") or item.get("type") or ""),
                }
            )
        unique: dict[str, dict[str, str]] = {}
        for item in defaults + presets:
            key = item.get("value") or item.get("path") or item.get("repo_id") or item.get("label") or ""
            if key not in unique:
                unique[key] = item
        return list(unique.values())

    def _discover_local_policies(self) -> list[dict[str, Any]]:
        roots = [self.config.policy_root, self.config.output_root]
        candidates: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            candidates.extend(root.glob("*/checkpoints/last/pretrained_model"))
            candidates.extend(root.glob("*/checkpoints/*/pretrained_model"))
            candidates.extend(root.glob("*/pretrained_model"))
        policies: list[dict[str, Any]] = []
        ordered = sorted({item.resolve() for item in candidates if item.exists()}, key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)
        for path in ordered:
            if not self._is_pretrained_policy_dir(path):
                continue
            repo_id = ""
            policy_type = ""
            train_config_path = path / "train_config.json"
            train_config: dict[str, Any] = {}
            try:
                config = json.loads((path / "config.json").read_text(encoding="utf-8"))
                repo_id = str(config.get("repo_id") or "")
                policy_type = self._canonical_policy_type(str(config.get("type") or config.get("policy_type") or ""))
            except Exception:
                repo_id = ""
                policy_type = ""
            try:
                loaded_train_config = json.loads(train_config_path.read_text(encoding="utf-8"))
                if isinstance(loaded_train_config, dict):
                    train_config = loaded_train_config
            except Exception:
                train_config = {}
            if not policy_type and isinstance(train_config.get("policy"), dict):
                policy_type = self._canonical_policy_type(str(train_config["policy"].get("type") or train_config["policy"].get("policy_type") or ""))
            label = path.parent.parent.parent.name if "checkpoints" in str(path) else path.name
            if repo_id:
                label = f"{label} ({repo_id})"
            output_dir = str(train_config.get("output_dir") or "")
            if not output_dir and path.name == "pretrained_model" and path.parent.parent.name == "checkpoints":
                output_dir = str(path.parent.parent.parent)
            job_name = str(train_config.get("job_name") or (Path(output_dir).name if output_dir else ""))
            policy: dict[str, Any] = {
                "label": label,
                "value": str(path),
                "path": str(path),
                "repo_id": repo_id,
                "source": "local",
                "policy_type": policy_type,
            }
            if output_dir:
                policy["output_dir"] = output_dir
            if job_name:
                policy["job_name"] = job_name
            if train_config_path.is_file():
                policy["train_config_path"] = str(train_config_path)
            if train_config:
                policy["train_config"] = train_config
            policies.append(policy)
        return policies[:100]

    def _allowed_roots(self) -> list[Path]:
        return [
            Path.home().resolve(),
            self.config.repo_root.resolve(),
            self.config.dataset_root.resolve(),
            self.config.output_root.resolve(),
            self.config.policy_root.resolve(),
            self.config.fake_dataset_root.resolve(),
            self.config.fake_checkpoint_root.resolve(),
            self.config.session_log_root.resolve(),
            Path("/tmp/atr_lerobot_latest_frame").resolve(),
        ]

    def _is_under_allowed_roots(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            return False
        for root in self._allowed_roots():
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _browse_base(self, kind: str, path_value: str) -> Path:
        if path_value:
            return _resolve_path(self.config.repo_root, path_value).resolve()
        if kind == "dataset":
            return self.config.dataset_root.resolve()
        if kind == "policy":
            return self.config.policy_root.resolve()
        if kind == "output":
            return self.config.output_root.resolve()
        return self.config.repo_root.resolve()

    def _read_dataset_metadata(self, dataset_path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {"exists": dataset_path.exists(), "path": str(dataset_path)}
        for rel in ("meta/info.json", "meta/stats.json", "meta/tasks.jsonl", "tasks.jsonl"):
            path = dataset_path / rel
            if not path.exists() or not path.is_file():
                continue
            try:
                if path.suffix == ".json":
                    metadata[rel] = json.loads(path.read_text(encoding="utf-8"))
                else:
                    metadata[rel] = path.read_text(encoding="utf-8")[:4000]
            except Exception as exc:
                metadata[rel] = f"{exc.__class__.__name__}: {exc}"
        if dataset_path.exists():
            metadata["top_level"] = sorted(item.name for item in dataset_path.iterdir())[:80] if dataset_path.is_dir() else []
        return metadata

    def _dataset_media(self, dataset_path: Path, *, episode_index: int = 0) -> list[dict[str, Any]]:
        if not dataset_path.exists() or not dataset_path.is_dir():
            return []
        exts = {
            ".mp4": "video",
            ".webm": "video",
            ".avi": "video",
            ".mov": "video",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".parquet": "data",
            ".json": "data",
            ".jsonl": "data",
        }
        episode_tokens = self._dataset_episode_tokens(episode_index)
        out: list[dict[str, Any]] = []
        counts_by_source_type: dict[tuple[str, str], int] = {}
        paths = sorted(dataset_path.rglob("*"), key=self._dataset_media_sort_key)
        for path in paths:
            if not path.is_file():
                continue
            media_type = exts.get(path.suffix.lower())
            if not media_type:
                continue
            text = str(path)
            source = self._dataset_media_source(path)
            explicit_episode = self._dataset_explicit_episode_index(text)
            if explicit_episode is not None and explicit_episode != episode_index:
                continue
            has_episode_token = explicit_episode == episode_index or any(token in text for token in episode_tokens)
            if media_type in {"video", "image"} and episode_index >= 0 and not has_episode_token:
                # Keep a few unfiltered media files for datasets that do not encode episode id in filenames.
                if counts_by_source_type.get((source, media_type), 0) >= 4:
                    continue
            if media_type == "data" and source in {"isaac_rgbd", "isaac_mirror"} and episode_index >= 0 and not has_episode_token:
                if counts_by_source_type.get((source, media_type), 0) >= 8:
                    continue
            counts_by_source_type[(source, media_type)] = counts_by_source_type.get((source, media_type), 0) + 1
            out.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "media_type": media_type,
                    "source": source,
                    "episode_index": episode_index,
                    "size_bytes": path.stat().st_size,
                    "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
                }
            )
            if len(out) >= 140:
                break
        return out

    @staticmethod
    def _dataset_episode_tokens(episode_index: int) -> list[str]:
        return [
            f"episode_{episode_index}",
            f"episode_{episode_index:03d}",
            f"episode_{episode_index:06d}",
            f"episode-{episode_index}",
            f"episode={episode_index}",
            f"/{episode_index}/",
            f"_ep{episode_index}",
            f"_ep{episode_index:03d}",
            f"ep{episode_index:03d}",
        ]

    @staticmethod
    def _dataset_explicit_episode_index(text: str) -> int | None:
        for pattern in (r"episode[_=\-]0*(\d+)", r"(?:^|[\/_\-])ep0*(\d+)(?:[._\/\-]|$)"):
            match = re.search(pattern, text)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _dataset_media_source(path: Path) -> str:
        text = str(path)
        if "/sidecar/isaac_rgbd/" in text:
            return "isaac_rgbd"
        if "/sidecar/isaac_mirror/" in text or "/sidecar/isaac_mirror" in text:
            return "isaac_mirror"
        if "/sidecar/isaac_augmentation/" in text:
            return "isaac_augmentation"
        if "/sidecar/depth_raw/" in text or "/sidecar/raw_depth/" in text:
            return "raw_depth"
        if "/sidecar/" in text:
            return "sidecar"
        if "/videos/" in text:
            return "lerobot_video"
        if "/data/" in text:
            return "lerobot_data"
        if "/meta/" in text:
            return "lerobot_meta"
        return "dataset"

    @staticmethod
    def _dataset_media_source_counts(media: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in media:
            source = str(item.get("source") or "dataset")
            counts[source] = counts.get(source, 0) + 1
        return counts

    @staticmethod
    def _dataset_media_sort_key(path: Path) -> tuple[int, str]:
        text = str(path)
        source_rank = 0
        if "/videos/" in text:
            source_rank = 0
        elif "/sidecar/isaac_rgbd/" in text:
            source_rank = 1
        elif "/sidecar/isaac_mirror/" in text:
            source_rank = 2
        elif "/sidecar/isaac_augmentation/" in text:
            source_rank = 3
        elif "/sidecar/depth_raw/" in text:
            source_rank = 4
        elif "/data/" in text:
            source_rank = 5
        camera_rank = 0 if "top" in text else 1 if "front" in text else 2 if "right" in text else 3 if "wrist" in text else 4
        return source_rank, camera_rank, text

    @staticmethod
    def _unsafe_arguments(args: list[str]) -> str:
        for arg in args:
            if arg and UNSAFE_ARGUMENT_RE.search(str(arg)):
                return str(arg)
        return ""

    def _emit_trace(
        self,
        payload: dict[str, Any] | None,
        tool: str,
        step_trace: list[dict[str, Any]],
        profile_id: str,
        mode: str,
        session_id: str = "",
    ) -> None:
        callback = (payload or {}).get("_event_callback")
        if not callable(callback):
            return
        for step in step_trace:
            event = {
                "tool": tool,
                "step": step.get("step", "STEP"),
                "status": step.get("status", "unknown"),
                "detail": step.get("detail", ""),
                "profile_id": profile_id,
                "mode": mode,
                "session_id": session_id,
            }
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    # Tool callbacks in this project are sync dispatchers. Avoid
                    # awaiting here because bridges are intentionally sync.
                    pass
            except Exception:
                continue


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path


def _resolve_conda_executable(value: str) -> str:
    configured = str(value or "conda").strip() or "conda"
    expanded = Path(configured).expanduser()
    if configured.lower() != "conda":
        return str(expanded)
    found = shutil.which(configured)
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / "miniconda3" / "Scripts" / "conda.exe",
        home / "miniconda3" / "bin" / "conda",
        home / "anaconda3" / "Scripts" / "conda.exe",
        home / "anaconda3" / "bin" / "conda",
    ):
        if candidate.exists():
            return str(candidate)
    return configured


def _bool_arg(value: bool) -> str:
    return "true" if bool(value) else "false"


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        if normalized == "":
            return bool(default)
    return bool(default)


def _safe_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    if maximum is not None:
        result = min(int(maximum), result)
    return result


def _safe_float(
    value: Any, default: float, *, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def _normalize_camera_depth_clip_map(
    raw: Any, *, default: dict[str, dict[str, float]] | None = None
) -> dict[str, dict[str, float]]:
    source = raw if isinstance(raw, dict) else (default or {})
    normalized: dict[str, dict[str, float]] = {}
    if not isinstance(source, dict):
        return normalized
    for key, value in source.items():
        camera_key = str(key or "").strip()
        if not camera_key:
            continue
        if isinstance(value, dict):
            min_value = value.get("min_mm", value.get("min", value.get("clip_min_mm")))
            max_value = value.get("max_mm", value.get("max", value.get("clip_max_mm")))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            min_value, max_value = value[0], value[1]
        elif isinstance(value, str) and ":" in value:
            min_value, max_value = value.split(":", 1)
        else:
            continue
        clip_min = _safe_float(min_value, LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM)
        clip_max = _safe_float(max_value, LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM, minimum=clip_min + 1e-6)
        if clip_max > clip_min:
            normalized[camera_key] = {"min_mm": clip_min, "max_mm": clip_max}
    return normalized


def _resolve_profiles(raw_profiles: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> dict[str, Any]:
        if name in profiles:
            return copy.deepcopy(profiles[name])
        if name not in raw_profiles:
            raise ValueError(f"Unknown inherited LeRobot profile: {name}")
        if name in resolving:
            raise ValueError(f"Circular LeRobot profile inheritance: {name}")
        resolving.add(name)
        current = dict(raw_profiles[name] or {})
        parent_name = str(current.pop("inherits", "") or "")
        if parent_name:
            merged = resolve(parent_name)
            merged.update(current)
            current = merged
        current.setdefault("profile_id", name)
        profiles[name] = copy.deepcopy(current)
        resolving.discard(name)
        return copy.deepcopy(current)

    for profile_name in raw_profiles:
        resolve(profile_name)
    return profiles
