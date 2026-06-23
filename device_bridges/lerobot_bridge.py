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
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, IO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from mcp_tools.lerobot_schemas import (
    LeRobotBaseRequest,
    LeRobotDevicePortRequest,
    LeRobotRecordControlRequest,
    LeRobotSessionRequest,
    RobotProfile,
)
from utils.isaac_omx_mirror_mapping import (
    ISAAC_OMX_ARTICULATION_ROOT,
    ISAAC_OMX_JOINT_MAP,
    ISAAC_OMX_SCENE_RELATIVE_PATH,
    ISAAC_OMX_TEST_JOINT_STATE_DEG,
    default_isaac_omx_mirror_calibration_path,
    load_isaac_omx_mirror_calibration,
    positions_to_joint_state,
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
LEROBOT_DEFAULT_REALSENSE_WARMUP_S = 5
LEROBOT_DEFAULT_CAMERA_WIDTH = 640
LEROBOT_DEFAULT_CAMERA_HEIGHT = 480
LEROBOT_DEFAULT_DEPTH_SCALE_M_PER_UNIT = 0.001
LEROBOT_DEFAULT_DEPTH_CLIP_MIN_MM = 0.0
LEROBOT_DEFAULT_DEPTH_CLIP_MAX_MM = 2000.0
LEROBOT_REALSENSE_MODEL_NAMES = {
    "405": "Intel(R) RealSense(TM) Depth Camera 405",
    "455": "Intel(R) RealSense(TM) Depth Camera 455",
    "455f": "Intel(R) RealSense(TM) Depth Camera 455f",
}
LEROBOT_REALSENSE_DEFAULT_IDENTIFIERS = {
    "top": "Intel RealSense D455F",
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
                value = lower + ((norm_value + 100.0) / 200.0) * (upper - lower)
            else:
                value = norm_value
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
        self._mirror_stop_events: dict[str, threading.Event] = {}
        self._mirror_threads: dict[str, threading.Thread] = {}
        self._counter = 0
        self._selected_profile_id = config.default_profile_id
        self._selected_observation_pipeline_id = _normalize_observation_pipeline_id(config.default_observation_pipeline_id)
        self._module_available_cache: dict[tuple[str, str], bool] = {}

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
        existing = self._receiver_processes.get(process_key)
        if existing and existing.poll() is None:
            return self.mirror_receiver_process_status(raw_payload)
        self._stop_receiver_process(process_key)

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

        log_dir = self.config.repo_root / "runs" / "isaac_mirror_receiver"
        log_dir.mkdir(parents=True, exist_ok=True)
        launch_mode = str(command_info.get("launch_mode") or "python_script")
        log_path = log_dir / f"receiver_{launch_mode}_{host.replace('.', '_')}_{port}.log"
        command = [str(item) for item in command_info["command"]]
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
        default_timeout_s = 180.0 if launch_mode == "isaac_extension" else 5.0
        timeout_s = _safe_float(raw_payload.get("isaac_mirror_receiver_start_timeout_s"), default_timeout_s, minimum=0.1, maximum=300.0)
        health = self._wait_for_isaac_mirror_receiver(endpoint, timeout_s=timeout_s, request_timeout_s=self._isaac_mirror_timeout_s(request))
        if not health.get("ok"):
            return {
                "ok": False,
                "tool": "lerobot.mirror.receiver_process.start",
                "mode": mode,
                "profile_id": profile_id,
                "status": "STARTING",
                "failure_code": "LEROBOT_ISAAC_MIRROR_RECEIVER_HEALTH_TIMEOUT",
                "message": f"Receiver process started but health did not become ready within {timeout_s:g}s.",
                "pid": process.pid,
                "launch_mode": launch_mode,
                "command_preview": command,
                "log_path": str(log_path),
                "health": health,
                "step_trace": [{"step": "RECEIVER_PROCESS_STARTED", "status": "active", "detail": f"pid={process.pid}"}],
                "events": [{"step": "RECEIVER_PROCESS_STARTED", "status": "active", "detail": f"pid={process.pid}"}],
                "error": f"Receiver process started but health did not become ready within {timeout_s:g}s.",
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
                "For follower/leader, save a baseline, disconnect or reconnect one target MotorBus, then detect and save the changed serial port.",
                "Repeat the same process separately for follower and leader.",
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
            {"step": "WAIT_DEVICE_CHANGE", "status": "operator", "detail": "Disconnect or reconnect the target device, then run detect/save."},
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
        """Detect the newly appearing device relative to the saved baseline and persist it."""
        request = LeRobotDevicePortRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.ports.detect", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        memory = self._load_device_memory()
        profile_memory = self._profile_device_memory(memory, profile.profile_id)
        baseline_key = self._device_memory_key(request.device_role, request.camera_key)
        baseline = dict(profile_memory.get("baselines", {}).get(baseline_key, {}))
        if mode == "test":
            candidates = [
                self._default_realsense_identifier(request.camera_key)
                if request.device_role == "camera" and self._normalize_camera_backend(request.camera_backend) == LEROBOT_REALSENSE_TYPE
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
            candidates = added or removed or list(now)
            change_type = "added" if added else "removed" if removed else "unchanged"
        chosen = request.port or ""
        if not chosen and candidates and request.device_role == "camera" and self._normalize_camera_backend(request.camera_backend) == LEROBOT_REALSENSE_TYPE:
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
        if not chosen and mode == "live" and request.device_role in {"follower", "leader"}:
            chosen = self._select_serial_candidate_by_motor_ids(candidates, request.device_role)
        if not chosen:
            chosen = candidates[0] if candidates else ""
        if not chosen:
            return self._error("lerobot.ports.detect", mode, profile.profile_id, "LEROBOT_PORT_NOT_FOUND", f"No candidate found for {request.device_role}.")
        raw_chosen = chosen
        if mode == "live" and request.device_role in {"follower", "leader"}:
            chosen = self._baseline_serial_identity_port(baseline, chosen)
        chosen = self._normalize_realsense_selected_identifier(request, chosen, mode=mode)
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            chosen,
            camera_key=request.camera_key,
            source=f"detect_delta:{change_type}",
            memory=memory,
            prefer_identity_link=mode == "live",
            raw_port=raw_chosen,
            camera_backend=request.camera_backend,
            camera_use_depth=request.camera_use_depth,
            camera_fps=request.camera_fps,
            camera_width=request.camera_width,
            camera_height=request.camera_height,
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
        if not port and request.device_role == "camera" and self._normalize_camera_backend(request.camera_backend) == LEROBOT_REALSENSE_TYPE:
            port = self._preferred_realsense_identifier(request.camera_key)
        if not port:
            return self._error("lerobot.ports.save", mode, profile.profile_id, "LEROBOT_PORT_REQUIRED", "A port or camera index is required.")
        raw_port = port
        port = self._normalize_realsense_selected_identifier(request, port, mode=mode)
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
        request = LeRobotDevicePortRequest.model_validate(payload or {})
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
        request_camera = self._request_camera_metadata(request)
        camera_device = {**saved_camera, **{key: value for key, value in request_camera.items() if value not in ("", None)}}
        capture = (
            self._fake_camera_capture(profile, camera_key, runtime_camera_port)
            if mode != "live"
            else self._live_camera_capture(profile, camera_key, runtime_camera_port, camera_device=camera_device)
        )
        if not capture.get("ok"):
            return self._error("lerobot.camera.test", mode, profile.profile_id, str(capture.get("failure_code")), str(capture.get("message")))
        step_trace = [
            {"step": "RESOLVE_CAMERA_PORT", "status": "ok", "detail": f"{camera_port} -> {runtime_camera_port}"},
            {"step": "OPEN_CAMERA", "status": "ok", "detail": runtime_camera_port},
            {"step": "CAPTURE_FRAME", "status": "ok", "detail": str(capture.get("path", ""))},
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
            "capture": capture,
            "step_trace": step_trace,
            "events": step_trace,
            "error": None,
        }

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
            pipeline_block = self._dataset_pipeline_block_if_needed("lerobot.train.start", mode, profile, request, "train")
            if pipeline_block:
                return pipeline_block
            request, dataset_version_detail = self._train_request_with_pi05_dataset_version(request)
            pipeline_block = self._dataset_pipeline_block_if_needed("lerobot.train.start", mode, profile, request, "train")
            if pipeline_block:
                return pipeline_block
            request, train_detail = self._train_request_with_output_dir(profile, request)
            request, resume_detail = self._train_request_with_resume_config(profile, request)
            train_args = self._train_args(profile, request)
        except ValueError as exc:
            return self._error("lerobot.train.start", mode, profile.profile_id, "LEROBOT_TRAIN_CONFIG_INVALID", str(exc))
        status = "COMPLETED" if mode != "live" else "TRAINING"
        trace = [
            ("PRECHECK", "ok", f"{train_detail}; {runtime_detail}; {resume_detail}"),
            ("LOAD_DATASET", "ok", f"{dataset_detail}; {dataset_version_detail}"),
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
            {"step": "START_VISUALIZER", "status": "active", "detail": f"tool={viz_info.get('tool')} episode={request.episode_index}"},
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
        return self._session_status("lerobot.visualize.status", payload or {}, "visualize")

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
        if mode != "test":
            if self._wandb_local_port_ready(url):
                session["status"] = "WANDB_LOCAL_RUNNING"
                session.setdefault("step_trace", []).append({"step": "PORT_READY", "status": "ok", "detail": url})
                self._sessions[session_id] = session
                return self._session_response("lerobot.wandb_local.start", mode, session, session["step_trace"], url=url, port=port, idempotent=True)
            live_start = self._start_live_process(
                session_id=session_id,
                command=command,
                env_overrides={"WANDB_BASE_URL": url, "DOCKER_DEFAULT_PLATFORM": "linux/amd64"},
            )
            if live_start.get("session_updates"):
                session.update(dict(live_start["session_updates"]))
            if not live_start["ok"]:
                session["status"] = "FAILED"
                session["step_trace"] = step_trace + [
                    {
                        "step": str(live_start.get("failure_code", "WANDB_LOCAL_PROCESS_START_FAILED")),
                        "status": "failed",
                        "detail": str(live_start.get("message", "Local W&B server failed during startup.")),
                    }
                ]
                self._sessions[session_id] = session
                return self._session_response(
                    "lerobot.wandb_local.start",
                    mode,
                    session,
                    session["step_trace"],
                    ok=False,
                    failure_code=str(live_start.get("failure_code", "WANDB_LOCAL_PROCESS_START_FAILED")),
                    message=str(live_start.get("message", "")),
                    error=str(live_start.get("message", "")),
                    url=url,
                    port=port,
                )
            session.setdefault("step_trace", []).append({"step": "PROCESS_STARTED", "status": "active", "detail": f"pid={session.get('pid')}"})
            ready, failure = self._wait_for_wandb_local_ready(url, session, timeout_s=45.0)
            if ready:
                session["status"] = "WANDB_LOCAL_RUNNING"
                session.setdefault("step_trace", []).append({"step": "PORT_READY", "status": "ok", "detail": url})
            elif failure:
                failure_code, message = failure
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
        return {
            "ok": True,
            "tool": "lerobot.dataset.inspect",
            "mode": mode,
            "profile_id": effective_profile.profile_id,
            "status": "ready",
            "dataset": {
                "path": dataset_path,
                "root": request.dataset_root or str(self.config.dataset_root),
                "robot_profile_id": effective_profile.profile_id,
                "robot_type": str(info.get("robot_type") or effective_profile.robot_type),
                "teleop_type": effective_profile.teleop_type,
                "observation_pipeline_id": pipeline_metadata["observation_pipeline_id"],
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
            },
            "step_trace": [{"step": "INSPECT_DATASET", "status": "ok", "detail": dataset_path}],
            "error": None,
        }

    def policies_list(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """List configured, local, and likely cached policy choices."""
        mode = self._mode(payload or {})
        policies = self._discover_local_policies()
        policies.extend(self._policy_presets())
        unique: dict[str, dict[str, str]] = {}
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
        media = self._dataset_media(dataset_path, episode_index=request.episode_index)
        return {
            "ok": True,
            "tool": "lerobot.dataset.visualize",
            "mode": request.runtime_mode or request.mode,
            "profile_id": request.profile_id or self._selected_profile_id,
            "dataset_path": str(dataset_path),
            "episode_index": request.episode_index,
            "metadata": metadata,
            "media": media,
            "summary": {
                "video_count": len([item for item in media if item.get("media_type") == "video"]),
                "image_count": len([item for item in media if item.get("media_type") == "image"]),
                "data_files": len([item for item in media if item.get("media_type") == "data"]),
            },
            "step_trace": [{"step": "VISUALIZE_DATASET", "status": "ok", "detail": str(dataset_path)}],
            "error": None,
        }

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
            response["isaac_mirror"] = {
                "ok": True,
                "session_id": session_id,
                "status": "IN_PROCESS",
                "sample_count": 0,
                "mirror_record_path": str(mirror_record_path),
                "attached_to_session_id": session_id,
                "sync_summary": {
                    "target_sample_hz": self._isaac_mirror_sample_hz(request),
                    "sample_count": 0,
                    "source": "lerobot_in_process_send_action",
                },
            }
            response["isaac_mirror_session_id"] = session_id
            session = self._sessions.get(session_id)
            if session is not None:
                session["isaac_mirror_session_id"] = session_id
                session["isaac_mirror_enabled"] = True
                session["isaac_mirror"] = dict(response["isaac_mirror"])
                session["isaac_mirror_endpoint"] = self._isaac_mirror_endpoint(request)
                session["isaac_mirror_sample_hz"] = self._isaac_mirror_sample_hz(request)
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
        response["isaac_mirror_session_id"] = mirror.get("session_id", "")
        session = self._sessions.get(session_id)
        if session is not None:
            session["isaac_mirror_session_id"] = mirror.get("session_id", "")
            session["isaac_mirror_enabled"] = True
            session["isaac_mirror"] = dict(response["isaac_mirror"])
            session["isaac_mirror_endpoint"] = mirror.get("mirror_endpoint", request.isaac_mirror_endpoint)
            session["isaac_mirror_sample_hz"] = mirror.get("mirror_sample_hz", request.isaac_mirror_sample_hz)
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
        mirror_preflight = self._live_isaac_mirror_preflight_if_needed(tool=tool, mode=mode, profile=profile, workflow=workflow, request=request)
        if mirror_preflight:
            if not mirror_preflight.get("ok"):
                return mirror_preflight
            trace = [
                *trace,
                (
                    "ISAAC_MIRROR_RECEIVER_READY",
                    "ok",
                    str(mirror_preflight.get("detail") or mirror_preflight.get("health_url") or request.isaac_mirror_endpoint),
                ),
            ]
        if mode == "live" and not request.confirm_live_execute:
            return self._blocked(tool, mode, profile.profile_id, "LEROBOT_LIVE_CONFIRMATION_REQUIRED", "Live LeRobot execution requires confirm_live_execute=true.", workflow)
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
            "log_path": "",
            "pid": None,
            "returncode": None,
            "tts": self._tts_config_for_request(request) if workflow == "record" else {},
        }
        if workflow == "record":
            session["expected_depth_features"] = self._expected_record_depth_features(profile, request)
            raw_depth_sidecar = self._record_raw_depth_sidecar(profile, request)
            if raw_depth_sidecar.get("enabled"):
                session["raw_depth_sidecar"] = raw_depth_sidecar
            metadata = self._write_record_pipeline_metadata(session, create_missing=(mode != "live"))
            if metadata:
                session["dataset_pipeline_metadata"] = metadata
        if workflow == "train":
            session["train_config"] = self._train_config_summary(profile, request)
            session["output_dir"] = session["train_config"].get("output_dir", "")
            session["job_name"] = session["train_config"].get("job_name", "")
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

    def _session_status(self, tool: str, payload: dict[str, Any], workflow: str) -> dict[str, Any]:
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        session = self._resolve_session(request.session_id, workflow)
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

    def _session_response(self, tool: str, mode: str, session: dict[str, Any], step_trace: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        self._refresh_in_process_isaac_mirror_progress(session)
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
        }
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
        elif training:
            payload["training"] = training
        if session.get("visualization"):
            payload["visualization"] = session.get("visualization", {})
        payload.update(extra)
        return payload

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

    def _wait_for_isaac_mirror_receiver(self, endpoint: str, *, timeout_s: float, request_timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] = {"ok": False, "message": "not checked"}
        while time.monotonic() < deadline:
            last = self._fetch_isaac_mirror_receiver_health(endpoint, timeout_s=request_timeout_s)
            if last.get("ok"):
                return last
            time.sleep(0.1)
        return last

    def _stop_receiver_process(self, endpoint_or_key: str) -> dict[str, Any]:
        process_key = self._isaac_mirror_process_key(endpoint_or_key)
        process = self._receiver_processes.pop(process_key, None)
        log_handle = self._receiver_log_handles.pop(process_key, None)
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
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE",
                f"Isaac mirror receiver is unavailable at {health_url}: {message}",
                workflow,
            )
        apply_mode = str(health.get("apply_mode") or "unknown")
        detail = f"{health_url} apply_mode={apply_mode}"
        if apply_mode != "deferred_update_tick":
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_ISAAC_MIRROR_RECEIVER_NOT_IN_ISAAC_UPDATE_TICK",
                f"Isaac mirror receiver is reachable at {health_url}, but it is not running inside Isaac Kit update-tick mode: apply_mode={apply_mode}. Start the ATR Isaac extension receiver before live teleop/record.",
                workflow,
            )
        return {"ok": True, "health_url": health_url, "receiver_health": health, "detail": detail}

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
            command = [
                executable,
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
                f"--/exts/atr.omx.mirror/playTimelineOnStartup=true",
                str(scene_path),
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
    def _isaac_mirror_sample_hz(request: LeRobotBaseRequest) -> float:
        return _safe_float(request.isaac_mirror_sample_hz, 15.0, minimum=0.1, maximum=120.0)

    @staticmethod
    def _isaac_mirror_timeout_s(request: LeRobotBaseRequest) -> float:
        return _safe_float(request.isaac_mirror_timeout_s, 0.5, minimum=0.05, maximum=10.0)

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
        }
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
        if requested == "raw_depth_adapter" and mode == "live" and not self._dataset_raw_depth_manifest_path(dataset_path).is_file():
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_RAW_DEPTH_ADAPTER_SOURCE_MISSING",
                f"Raw Depth Adapter requires {self._dataset_raw_depth_manifest_path(dataset_path)}.",
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
        return {
            "enabled": True,
            "root": str(root),
            "expected_camera_keys": camera_keys,
            "format": "png16",
            "pipeline_id": pipeline_id,
            "aligned_to": "color" if self.config.realsense_depth_align_to_color else "native_depth",
            "depth_scale_m_per_unit": self.config.realsense_depth_scale_m_per_unit,
            "depth_clip_min_mm": self.config.realsense_depth_clip_min_mm,
            "depth_clip_max_mm": self.config.realsense_depth_clip_max_mm,
        }

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
                file_counts[camera_key] = len(list(camera_dir.glob("frame_*.png")))
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
        status = str(session.get("status") or "").upper()
        synthetic_complete = status == "COMPLETED" and not log_tail and bool(total_steps)
        if status == "COMPLETED" and total_steps:
            current_step = total_steps
        progress_percent = round((current_step / total_steps) * 100.0, 2) if total_steps else (100.0 if status == "COMPLETED" else 0.0)
        progress_percent = max(0.0, min(100.0, progress_percent))
        elapsed_sec = self._session_elapsed_sec(session)
        steps_per_sec = 0.0 if synthetic_complete else round(current_step / elapsed_sec, 4) if current_step > 0 and elapsed_sec > 0 else 0.0
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
    def _parse_training_loss(log: str) -> float | None:
        matches = list(re.finditer(r"(?:loss|train_loss|l1_loss)\s*[=:]\s*([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)", log, flags=re.IGNORECASE))
        if not matches:
            return None
        try:
            return float(matches[-1].group(1))
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
            return self._blocked(
                tool,
                mode,
                profile.profile_id,
                "LEROBOT_DEVICE_PORT_UNAVAILABLE",
                f"Saved LeRobot device ports are not present: {', '.join(unavailable)}. Reconnect the robot or rerun port detection.",
                workflow,
            )
        return self._blocked(
            tool,
            mode,
            profile.profile_id,
            "LEROBOT_DEVICE_PORT_REQUIRED",
            f"Save required LeRobot device ports before live {workflow}: {', '.join(missing)}.",
            workflow,
        )

    def _live_camera_block_if_needed(
        self,
        *,
        tool: str,
        mode: str,
        profile: RobotProfile,
        workflow: str,
        request: LeRobotSessionRequest,
    ) -> dict[str, Any] | None:
        if mode != "live" or workflow not in {"teleoperate", "record", "rollout"} or not request.camera_enabled:
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
                    return str(entry.get("serial") or entry.get("name") or self._default_realsense_identifier(camera_key))
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
        if mode == "live" and workflow in {"teleoperate", "record"} and request.isaac_mirror_enabled:
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_isaac_mirror_runtime_wrapper.py"), workflow])
        elif workflow == "rollout" and self._is_pi05_policy(request.policy_type):
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_pi05_rollout_wrapper.py")])
        else:
            command.extend(self._workflow_entrypoint(profile, workflow))
        if workflow in {"teleoperate", "record", "rollout"}:
            command.extend(self._robot_args(profile, request=request, allow_fake=mode != "live", workflow=workflow))
        if workflow in {"teleoperate", "record"}:
            command.extend(self._teleop_args(profile, request=request, allow_fake=mode != "live"))
        command.extend([arg for arg in args if arg and not arg.endswith("=")])
        return command

    def _workflow_conda_env_name(self, workflow: str, request: LeRobotSessionRequest) -> str:
        if workflow in {"train", "rollout"} and self._is_pi05_policy(request.policy_type):
            return self.config.pi05_conda_env_name
        if workflow in {"train", "rollout"} and self._is_xvla_policy(request.policy_type):
            return self.config.xvla_conda_env_name
        if workflow in {"train", "rollout"} and self._is_smolvla_policy(request.policy_type):
            return self.config.smolvla_conda_env_name
        return self.config.conda_env_name

    def _workflow_env_overrides(self, workflow: str, request: LeRobotSessionRequest, *, session_id: str = "") -> dict[str, str]:
        pipeline_id = self._request_observation_pipeline_id(request, self._profile(request.profile_id or self._selected_profile_id))
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
                    "ATR_ISAAC_MIRROR_SESSION_ID": mirror_session_id,
                    "ATR_ISAAC_MIRROR_ATTACHED_TO_SESSION_ID": mirror_session_id,
                    "ATR_ISAAC_MIRROR_PROFILE_ID": str(request.profile_id or self._selected_profile_id),
                    "ATR_ISAAC_MIRROR_CALIBRATION_PATH": str(default_isaac_omx_mirror_calibration_path(self.config.repo_root)),
                    "ATR_ISAAC_MIRROR_RECORD_PATH": str(self._in_process_isaac_mirror_record_path(workflow, request, mirror_session_id or "live")),
                }
            )
        if pipeline_id == "raw_depth_adapter":
            env["ATR_LEROBOT_RAW_DEPTH_ADAPTER"] = "1"
            if workflow in {"train", "rollout"}:
                env.update(self._raw_depth_adapter_env_overrides(request))
        if workflow in {"train", "rollout"} and self._is_pi05_policy(request.policy_type):
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

    def _raw_depth_adapter_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
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

    def _raw_depth_env_overrides(self, request: LeRobotSessionRequest) -> dict[str, str]:
        profile = self._profile(request.profile_id or self._selected_profile_id)
        if profile is None:
            return {}
        sidecar = self._record_raw_depth_sidecar(profile, request)
        if not sidecar.get("enabled"):
            return {}
        camera_keys = [str(item) for item in sidecar.get("expected_camera_keys", []) if str(item).strip()]
        return {
            "ATR_LEROBOT_RAW_DEPTH_DIR": str(sidecar["root"]),
            "ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS": ",".join(camera_keys),
            "ATR_LEROBOT_RAW_DEPTH_FORMAT": str(sidecar.get("format") or "png16"),
            "ATR_LEROBOT_DEPTH_ALIGNED_TO": str(sidecar.get("aligned_to") or "color"),
            "ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT": str(sidecar.get("depth_scale_m_per_unit")),
            "ATR_LEROBOT_DEPTH_CLIP_MIN_MM": str(sidecar.get("depth_clip_min_mm")),
            "ATR_LEROBOT_DEPTH_CLIP_MAX_MM": str(sidecar.get("depth_clip_max_mm")),
        }

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
            pretrained_key = "policy.pretrained_path" if self._is_pi05_policy(policy_type) else "policy.path"
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
        }

    def _visualization_args(self, request: LeRobotSessionRequest) -> tuple[list[str], dict[str, Any]]:
        """Build the installed LeRobot dataset visualizer command arguments."""
        viz_info = self._visualization_dataset_refs(request)
        tool = request.visualization_tool or "html"
        dataset_root_for_lerobot = str(viz_info["dataset_path"])
        viz_info.update(
            {
                "tool": tool,
                "episode_index": int(request.episode_index),
                "visualization_mode": request.visualization_mode,
                "batch_size": int(request.visualization_batch_size),
                "num_workers": int(request.visualization_num_workers),
                "web_port": int(request.visualization_web_port),
                "ws_port": int(request.visualization_ws_port),
                "rerun_ws_url": f"ws://localhost:{int(request.visualization_ws_port)}",
                "rerun_web_url": f"http://localhost:{int(request.visualization_web_port)}",
                "save": bool(request.visualization_save),
                "lerobot_root": dataset_root_for_lerobot,
            }
        )
        if tool == "html":
            output_dir = _resolve_path(
                self.config.repo_root,
                request.visualization_output_dir or str(self.config.output_root / "visualize_dataset" / self._slug(str(viz_info["repo_id"]))),
            ).resolve()
            if not self._is_under_allowed_roots(output_dir):
                raise ValueError(f"Visualization output_dir is outside allowed roots: {output_dir}")
            host = "127.0.0.1"
            repo_parts = str(viz_info["repo_id"]).split("/", 1)
            viewer_path = f"/{repo_parts[0]}/{repo_parts[1]}/episode_{int(request.episode_index)}" if len(repo_parts) == 2 else f"/?dataset={viz_info['repo_id']}&episode={int(request.episode_index)}"
            viz_info.update(
                {
                    "output_dir": str(output_dir),
                    "viewer_url": f"http://{host}:{int(request.visualization_web_port)}{viewer_path}",
                }
            )
            return [
                f"--repo-id={viz_info['repo_id']}",
                f"--root={dataset_root_for_lerobot}",
                "--episodes",
                str(int(request.episode_index)),
                f"--output-dir={output_dir}",
                "--serve=1",
                f"--host={host}",
                f"--port={int(request.visualization_web_port)}",
                "--force-override=1",
                f"--tolerance-s={float(request.visualization_tolerance_s)}",
            ], viz_info
        args = [
            f"--repo-id={viz_info['repo_id']}",
            f"--episode-index={int(request.episode_index)}",
            f"--root={dataset_root_for_lerobot}",
            f"--batch-size={int(request.visualization_batch_size)}",
            f"--num-workers={int(request.visualization_num_workers)}",
            f"--mode={request.visualization_mode}",
            f"--web-port={int(request.visualization_web_port)}",
            f"--ws-port={int(request.visualization_ws_port)}",
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
        """Use a v3.0 local dataset copy for Pi0.5 without mutating the recorded v2.1 dataset."""
        mode = request.runtime_mode or request.mode
        if mode != "live" or not self._is_pi05_policy(request.policy_type):
            return request, "dataset format unchanged"

        raw_dataset_path = str(request.dataset_path or request.dataset_root or "").strip()
        if not raw_dataset_path:
            return request, "dataset format unchanged"
        dataset_path = _resolve_path(self.config.repo_root, raw_dataset_path).resolve()
        dataset_version = self._lerobot_dataset_codebase_version(dataset_path)
        if dataset_version == "v3.0":
            repo_id, root = self._repo_id_root_from_dataset_path(dataset_path, self.config.dataset_root.resolve())
            self._ensure_pi05_quantile_stats(repo_id, root)
            return request, f"Pi0.5 dataset already v3.0 at {dataset_path}; quantile stats ready"
        if dataset_version != "v2.1":
            raise ValueError(
                "Pi0.5 live training requires a LeRobot v3.0 dataset. "
                f"Selected dataset has codebase_version='{dataset_version or 'unknown'}' at {dataset_path}."
            )

        converted_repo_id = self._pi05_v30_dataset_repo_id(request.dataset_repo_id, dataset_path)
        converted_root = self.config.dataset_root.resolve()
        converted_path = (converted_root / converted_repo_id).resolve()
        if not self._is_under_allowed_roots(converted_path):
            raise ValueError(f"Pi0.5 converted dataset path is outside allowed roots: {converted_path}")
        if not self._pi05_v30_dataset_is_current(dataset_path, converted_path):
            self._prepare_pi05_v30_dataset_copy(dataset_path, converted_repo_id, converted_root)
        if self._lerobot_dataset_codebase_version(converted_path) != "v3.0":
            raise ValueError(f"Pi0.5 dataset conversion did not produce a v3.0 dataset at {converted_path}")
        self._ensure_pi05_quantile_stats(converted_repo_id, converted_root)

        return (
            self._train_request_for_dataset(request, converted_repo_id, converted_path),
            f"Pi0.5 converted {request.dataset_repo_id or dataset_path.name} v2.1 -> {converted_repo_id} v3.0 at {converted_path}",
        )

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
        shutil.copytree(source_path, target_path, symlinks=True)
        self._run_pi05_v30_dataset_conversion(converted_repo_id, converted_root)

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
        if self._dataset_raw_depth_manifest_path(source_path).is_file() and not self._dataset_raw_depth_manifest_path(converted_path).is_file():
            return False
        return self._dataset_tree_mtime(converted_path) >= self._dataset_tree_mtime(source_path)

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
    def _dataset_tree_mtime(path: Path) -> float:
        if not path.exists():
            return 0.0
        newest = path.stat().st_mtime
        if not path.is_dir():
            return newest
        for item in path.rglob("*"):
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
        if request.camera_enabled:
            for camera_key in self._profile_camera_keys(profile):
                camera_port = self._device_port(profile, "camera", camera_key=camera_key, allow_fake=allow_fake)
                if camera_port:
                    runtime_port = self._runtime_device_port(camera_port, "camera", live=mode == "live")
                    saved_camera = self._saved_camera_device(profile.profile_id, camera_key)
                    camera_map[camera_key] = self._camera_config_for_command(
                        runtime_port,
                        saved_camera,
                        request_fps=request.camera_fps or request.fps or profile.fps,
                        include_color_format=not (workflow == "rollout" and self._is_pi05_policy(request.policy_type)),
                    )
        if camera_map:
            args.append(f"--robot.cameras={json.dumps(camera_map, ensure_ascii=True)}")
        return args

    def _camera_config_for_command(
        self,
        port_or_identifier: str,
        camera_device: dict[str, Any] | None = None,
        *,
        request_fps: int | None = None,
        include_color_format: bool = True,
    ) -> dict[str, Any]:
        device = camera_device or {}
        backend = self._normalize_camera_backend(device.get("backend", "opencv"))
        if backend == LEROBOT_REALSENSE_TYPE:
            identifier = str(device.get("serial_number_or_name") or port_or_identifier)
            return self._realsense_camera_config(
                identifier,
                fps=self._camera_fps(device, request_fps),
                use_depth=self._camera_use_depth(device, default=True),
                width=_safe_int(device.get("width"), LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1),
                height=_safe_int(device.get("height"), LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1),
                color_format=self._realsense_color_format(identifier=identifier, camera_device=device) if include_color_format else "",
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
        fps: int,
        use_depth: bool,
        width: int,
        height: int,
        color_format: str,
    ) -> dict[str, Any]:
        data = {
            "type": LEROBOT_REALSENSE_TYPE,
            "serial_number_or_name": serial_number_or_name,
            "width": width,
            "height": height,
            "fps": fps,
            "use_depth": bool(use_depth),
            "align_depth_to_color": bool(self.config.realsense_depth_align_to_color),
            "depth_scale_m_per_unit": self.config.realsense_depth_scale_m_per_unit,
            "depth_clip_min_mm": self.config.realsense_depth_clip_min_mm,
            "depth_clip_max_mm": self.config.realsense_depth_clip_max_mm,
            # LeRobot / RealSense D405 needs a real warmup period before
            # consuming frames; disabling warmup makes status=False failures
            # more likely after a previous session.
            "warmup_s": LEROBOT_DEFAULT_REALSENSE_WARMUP_S,
        }
        if color_format:
            data["color_format"] = color_format
        return data

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
            return
        returncode = process.poll()
        session["returncode"] = returncode
        if returncode is None:
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
        if str(session.get("workflow") or "").lower() == "train":
            self._stop_training_monitor(session)

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
            "teleoperate": ("lerobot-teleoperate", "lerobot.teleoperate"),
            "record": ("lerobot-record", "lerobot.record"),
            "train": ("lerobot-train", "lerobot.train"),
            "rollout": (
                "lerobot-rollout",
                "lerobot.rollout",
                "lerobot_pi05_rollout_wrapper.py",
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
        for part in parts:
            base = Path(part).name
            for marker in markers:
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
        """Prefer local trained checkpoints for rollout and normalize selected output files."""
        mode = request.runtime_mode or request.mode
        raw_path = str(request.policy_checkpoint_path or request.policy_path or "").strip()
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

        if mode == "live":
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
        return request.policy_checkpoint_path or request.policy_path or request.policy_repo_id

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
            name = str(entry.get("name") or "").strip()
            product_line = str(entry.get("product_line") or "").strip()
            if serial:
                ids.append(serial)
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

    def _scan_realsense_camera_entries(self) -> list[dict[str, str]]:
        """Enumerate RealSense devices as SDK entries without starting streams."""
        entries: list[dict[str, str]] = []
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
                if serial or name:
                    entries.append({"serial": serial, "name": name, "product_line": product_line})
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

    def _scan_live_realsense_camera_entries(self) -> list[dict[str, str]]:
        """Enumerate RealSense devices from the runtime env used by LeRobot."""
        entries = self._scan_realsense_camera_entries()
        if entries:
            return entries
        return self._scan_realsense_camera_entries_via_lerobot_env()

    def _scan_realsense_camera_entries_via_lerobot_env(self) -> list[dict[str, str]]:
        script = r"""
import json
import pyrealsense2 as rs

entries = []
ctx = rs.context()
for device in ctx.query_devices():
    row = {}
    for key in ("name", "serial_number", "product_line"):
        try:
            info = getattr(rs.camera_info, key)
            row["serial" if key == "serial_number" else key] = str(device.get_info(info) or "").strip() if device.supports(info) else ""
        except Exception:
            row["serial" if key == "serial_number" else key] = ""
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
                return [dict(item) for item in parsed if isinstance(item, dict)]
        return []

    @classmethod
    def _realsense_identifier_available(cls, identifier: str, entries: list[dict[str, str]]) -> bool:
        needle = cls._device_match_token(identifier)
        if not needle:
            return False
        for entry in entries:
            values = [
                str(entry.get("serial") or ""),
                str(entry.get("name") or ""),
                str(entry.get("product_line") or ""),
                f"{entry.get('name') or ''} {entry.get('product_line') or ''}",
            ]
            if any(needle == cls._device_match_token(value) for value in values):
                return True
        return False

    @classmethod
    def _realsense_visible_summary(cls, entries: list[dict[str, str]]) -> str:
        visible: list[str] = []
        for entry in entries:
            serial = str(entry.get("serial") or "").strip()
            name = str(entry.get("name") or "").strip()
            if serial:
                visible.append(serial)
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
                device["fps"] = _safe_int(camera_fps, LEROBOT_DEFAULT_REALSENSE_FPS, minimum=1)
                device["width"] = _safe_int(camera_width, LEROBOT_DEFAULT_CAMERA_WIDTH, minimum=1)
                device["height"] = _safe_int(camera_height, LEROBOT_DEFAULT_CAMERA_HEIGHT, minimum=1)
                device["channel_plan"] = "rgb_plus_depth"
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

    def _select_serial_candidate_by_motor_ids(self, candidates: list[str], role: str) -> str:
        expected = self._expected_motor_ids_for_role(role)
        if not expected:
            return ""
        for candidate in candidates:
            motor_ids = set(self._serial_motor_ids(candidate))
            if expected.issubset(motor_ids):
                return str(candidate)
        return ""

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
                value = lower + ((norm_value + 100.0) / 200.0) * (upper - lower)
            else:
                value = norm_value
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
        path = capture_dir / f"{profile.profile_id}_{camera_key}_{timestamp}.svg"
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <rect width="960" height="540" fill="#f8fbff"/>
  <rect x="30" y="30" width="900" height="480" rx="28" fill="#ffffff" stroke="#1436b3" stroke-width="4"/>
  <text x="70" y="140" font-family="Arial, sans-serif" font-size="44" font-weight="700" fill="#091225">LeRobot Camera Test</text>
  <text x="70" y="220" font-family="Arial, sans-serif" font-size="30" fill="#1436b3">profile={profile.profile_id}</text>
  <text x="70" y="280" font-family="Arial, sans-serif" font-size="30" fill="#1436b3">camera_key={camera_key}</text>
  <text x="70" y="340" font-family="Arial, sans-serif" font-size="30" fill="#1436b3">port={camera_port}</text>
  <circle cx="805" cy="170" r="56" fill="#28a1ff" opacity="0.28"/>
  <circle cx="805" cy="170" r="22" fill="#28a1ff"/>
</svg>
"""
        path.write_text(svg, encoding="utf-8")
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
            return {"ok": False, "failure_code": "LEROBOT_REALSENSE_BACKEND_MISSING", "message": f"RealSense backend import failed: {exc}"}
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

    def _discover_local_policies(self) -> list[dict[str, str]]:
        roots = [self.config.policy_root, self.config.output_root]
        candidates: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            candidates.extend(root.glob("*/checkpoints/last/pretrained_model"))
            candidates.extend(root.glob("*/checkpoints/*/pretrained_model"))
            candidates.extend(root.glob("*/pretrained_model"))
        policies: list[dict[str, str]] = []
        ordered = sorted({item.resolve() for item in candidates if item.exists()}, key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)
        for path in ordered:
            if not self._is_pretrained_policy_dir(path):
                continue
            repo_id = ""
            policy_type = ""
            try:
                config = json.loads((path / "config.json").read_text(encoding="utf-8"))
                repo_id = str(config.get("repo_id") or "")
                policy_type = self._canonical_policy_type(str(config.get("type") or config.get("policy_type") or ""))
            except Exception:
                repo_id = ""
                policy_type = ""
            label = path.parent.parent.parent.name if "checkpoints" in str(path) else path.name
            if repo_id:
                label = f"{label} ({repo_id})"
            policies.append({"label": label, "value": str(path), "path": str(path), "repo_id": repo_id, "source": "local", "policy_type": policy_type})
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
        episode_tokens = [f"episode_{episode_index}", f"episode-{episode_index}", f"episode={episode_index}", f"/{episode_index}/"]
        out: list[dict[str, Any]] = []
        paths = sorted(dataset_path.rglob("*"), key=self._dataset_media_sort_key)
        for path in paths:
            if not path.is_file():
                continue
            media_type = exts.get(path.suffix.lower())
            if not media_type:
                continue
            text = str(path)
            if media_type in {"video", "image"} and episode_index >= 0 and not any(token in text for token in episode_tokens):
                # Keep a few unfiltered media files for datasets that do not encode episode id in filenames.
                if len([item for item in out if item.get("media_type") == media_type]) >= 4:
                    continue
            out.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "media_type": media_type,
                    "size_bytes": path.stat().st_size,
                    "serve_url": f"/api/lerobot/visualization/file?path={quote(str(path))}",
                }
            )
            if len(out) >= 80:
                break
        return out

    @staticmethod
    def _dataset_media_sort_key(path: Path) -> tuple[int, str]:
        text = str(path)
        camera_rank = 0 if "observation.images.top" in text else 1 if "observation.images.wrist" in text else 2
        return camera_rank, text

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
