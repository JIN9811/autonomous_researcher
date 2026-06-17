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
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, IO
from urllib.parse import quote

from mcp_tools.lerobot_schemas import (
    LeRobotBaseRequest,
    LeRobotDevicePortRequest,
    LeRobotRecordControlRequest,
    LeRobotSessionRequest,
    RobotProfile,
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
LEROBOT_DEFAULT_REALSENSE_WARMUP_S = 1
LEROBOT_DEFAULT_CAMERA_WIDTH = 640
LEROBOT_DEFAULT_CAMERA_HEIGHT = 480
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
    pi05_repo_root: Path = Path("~/lerobot_pi05")
    pi05_hf_home: Path = Path("~/.cache/huggingface_pi05")
    train_video_backend: str = "torchcodec"
    train_video_backend_fallback: str = "pyav"
    pi05_video_backend: str = "torchcodec"
    hf_token_path: Path = Path("~/.cache/huggingface/token")
    pi05_base_policy: str = "lerobot/pi05_base"
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
            pi05_repo_root=pi05_repo_root,
            pi05_hf_home=pi05_hf_home,
            train_video_backend=str(root.get("train_video_backend", "torchcodec")),
            train_video_backend_fallback=str(root.get("train_video_backend_fallback", "pyav")),
            pi05_video_backend=str(root.get("pi05_video_backend", root.get("train_video_backend", "torchcodec"))),
            hf_token_path=hf_token_path,
            pi05_base_policy=str(root.get("pi05_base_policy", "lerobot/pi05_base")),
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
        self._log_handles: dict[str, IO[str]] = {}
        self._counter = 0
        self._selected_profile_id = config.default_profile_id
        self._module_available_cache: dict[tuple[str, str], bool] = {}

    def shutdown(self) -> dict[str, Any]:
        """Stop tracked and stale LeRobot live subprocesses before the GUI server exits."""
        step_trace = self.cleanup_all_lerobot_processes()
        for session_id in list(self._log_handles):
            self._close_log_handle(session_id)
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
            "profiles": profiles,
            "sessions": self.sessions_recent(),
            "live_gate_summary": self._live_gate_summary(self._profile(self._selected_profile_id)),
            "paths": self._path_status(),
            "policy_presets": self._policy_presets(),
            "tts": self._tts_config_public(),
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
        if not chosen:
            chosen = candidates[0] if candidates else ""
        if not chosen:
            return self._error("lerobot.ports.detect", mode, profile.profile_id, "LEROBOT_PORT_NOT_FOUND", f"No candidate found for {request.device_role}.")
        stable_chosen = self._stable_device_port(chosen, request.device_role) if mode == "live" else str(chosen or "").strip()
        conflict = self._serial_role_port_conflict(profile.profile_id, request.device_role, stable_chosen, memory=memory)
        if conflict:
            return self._error(
                "lerobot.ports.detect",
                mode,
                profile.profile_id,
                "LEROBOT_SERIAL_ROLE_PORT_CONFLICT",
                f"{request.device_role} port conflicts with saved {conflict} port: {stable_chosen}",
            )
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            chosen,
            camera_key=request.camera_key,
            source=f"detect_delta:{change_type}",
            memory=memory,
            prefer_identity_link=mode == "live",
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
            "raw_selected_port": chosen,
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
        memory = self._load_device_memory()
        stable_port = self._stable_device_port(port, request.device_role) if mode == "live" else str(port or "").strip()
        conflict = self._serial_role_port_conflict(profile.profile_id, request.device_role, stable_port, memory=memory)
        if conflict:
            return self._error(
                "lerobot.ports.save",
                mode,
                profile.profile_id,
                "LEROBOT_SERIAL_ROLE_PORT_CONFLICT",
                f"{request.device_role} port conflicts with saved {conflict} port: {stable_port}",
            )
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            port,
            camera_key=request.camera_key,
            source="manual",
            memory=memory,
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
        return self._start_session(
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

    def teleoperate_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop a teleoperation session idempotently."""
        return self._stop_session("lerobot.teleoperate.stop", payload or {}, "teleoperate")

    def teleoperate_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return teleoperation session status."""
        return self._session_status("lerobot.teleoperate.status", payload or {}, "teleoperate")

    def record_start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start a LeRobot recording session."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        request, effective_resume, ready_detail = self._record_start_request(request)
        active_detail = "LeRobot recording process starting" if mode == "live" else "synthetic recording session active"
        return self._start_session(
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

    def record_control(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply a deterministic recording control action."""
        request = LeRobotRecordControlRequest.model_validate(payload or {})
        if request.action == "stop":
            stopped = self._stop_session("lerobot.record.control", payload or {}, "record", stopped_status="STOPPED")
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
            request, dataset_version_detail = self._train_request_with_pi05_dataset_version(request)
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
        if not is_pi05:
            policy_args.append(f"--policy.type={policy_type}")
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
        if request.rollout_temporal_ensemble and not is_pi05:
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

    def dataset_inspect(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return deterministic fake LeRobotDataset-like metadata."""
        request = LeRobotSessionRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        profile = self._profile(request.profile_id)
        if profile is None:
            return self._error("lerobot.dataset.inspect", mode, request.profile_id, "LEROBOT_PROFILE_NOT_FOUND", "Robot profile not found.")
        dataset_path = request.dataset_path or self._dataset_path_for(request)
        return {
            "ok": True,
            "tool": "lerobot.dataset.inspect",
            "mode": mode,
            "profile_id": profile.profile_id,
            "status": "ready",
            "dataset": {
                "path": dataset_path,
                "root": request.dataset_root or str(self.config.dataset_root),
                "robot_profile_id": profile.profile_id,
                "robot_type": profile.robot_type,
                "teleop_type": profile.teleop_type,
                "episode_count": request.num_episodes,
                "fps": request.fps or profile.fps,
                "tasks": [request.task_instruction],
                "camera_keys": sorted(profile.camera_map.values()),
                "metadata_files": ["meta/info.json", "tasks.jsonl"],
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
        session_id = request.session_id or self._new_session_id(workflow)
        step_trace = [{"step": step, "status": step_status, "detail": detail} for step, step_status, detail in trace]
        command_preview = self._workflow_command(profile, workflow, request, extra_args)
        session = {
            "session_id": session_id,
            "tool": tool,
            "workflow": workflow,
            "mode": mode,
            "profile_id": profile.profile_id,
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
        if workflow == "train":
            session["train_config"] = self._train_config_summary(profile, request)
            session["output_dir"] = session["train_config"].get("output_dir", "")
            session["job_name"] = session["train_config"].get("job_name", "")
        if mode == "live":
            live_start = self._start_live_process(
                session_id=session_id,
                command=command_preview,
                env_overrides=self._workflow_env_overrides(workflow, request),
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
        training = self._training_progress(session)
        log_tail = self._tail_file(str(session.get("log_path", "")))
        runtime = self._runtime_status_from_log(session, log_tail)
        payload = {
            "ok": True,
            "tool": tool,
            "mode": mode,
            "profile_id": session.get("profile_id", ""),
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "status": session.get("status", ""),
            "runtime": runtime,
            "runtime_phase": runtime.get("phase"),
            "runtime_message": runtime.get("message"),
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
            "error": None,
        }
        if training:
            payload["training"] = training
        if session.get("visualization"):
            payload["visualization"] = session.get("visualization", {})
        payload.update(extra)
        return payload

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
        batch_size = int(config.get("batch_size") or 0)
        sample_count = self._parse_training_sample_count(log_tail)
        if batch_size > 0 and sample_count > 0:
            current_step = max(current_step, sample_count // batch_size)
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
        data["live_gate_summary"] = LeRobotBridge._live_gate_summary(profile)
        return data

    def _public_session(self, session: dict[str, Any]) -> dict[str, Any]:
        log_tail = self._tail_file(str(session.get("log_path", "")))
        runtime = self._runtime_status_from_log(session, log_tail)
        training = self._training_progress(session)
        return {
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "profile_id": session.get("profile_id", ""),
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
            "visualization": session.get("visualization", {}),
        }

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
            for entry in self._scan_realsense_camera_entries():
                name = str(entry.get("name") or "").lower()
                product_line = str(entry.get("product_line") or "").lower()
                match_text = f"{name} {product_line}"
                if any(hint in match_text for hint in hints):
                    return str(entry.get("serial") or entry.get("name") or self._default_realsense_identifier(camera_key))
        return self._default_realsense_identifier(camera_key)

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
        if workflow == "rollout" and self._is_pi05_policy(request.policy_type):
            command.extend(["python", str(self.config.repo_root / "scripts" / "lerobot_pi05_rollout_wrapper.py")])
        else:
            command.extend(self._workflow_entrypoint(profile, workflow))
        if workflow in {"teleoperate", "record", "rollout"}:
            command.extend(self._robot_args(profile, request=request, allow_fake=mode != "live"))
        if workflow in {"teleoperate", "record"}:
            command.extend(self._teleop_args(profile, request=request, allow_fake=mode != "live"))
        command.extend([arg for arg in args if arg and not arg.endswith("=")])
        return command

    def _workflow_conda_env_name(self, workflow: str, request: LeRobotSessionRequest) -> str:
        if workflow in {"train", "rollout"} and self._is_pi05_policy(request.policy_type):
            return self.config.pi05_conda_env_name
        return self.config.conda_env_name

    def _workflow_env_overrides(self, workflow: str, request: LeRobotSessionRequest) -> dict[str, str]:
        env: dict[str, str] = {}
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
            if workflow == "train" and request.wandb_enable and str(request.wandb_mode or "").strip().lower() == "offline":
                env["WANDB_MODE"] = "offline"
        if workflow == "record":
            env.update(self._tts_env_overrides(request))
        return env

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
            optional.append(f"--wandb.mode={request.wandb_mode}")
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
                "batch_size": 32,
                "steps": 3000,
                "num_workers": 12,
                "eval_batch_size": None,
                "eval_freq": 500,
                "log_freq": 5,
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
            if requested_wandb:
                if not requested_wandb_mode or (requested_wandb_mode == "online" and not self._wandb_api_key_available()):
                    updates["wandb_mode"] = "offline"
            else:
                updates["wandb_mode"] = "disabled"
            pretrained = str(request.policy_pretrained_path or "").strip()
            if not self._is_valid_policy_source_ref(pretrained) or self._is_pi05_base_policy_ref(pretrained):
                updates["policy_pretrained_path"] = self._pi05_compatible_base_policy_ref()
        next_request = request.model_copy(update=updates)
        if self._is_pi05_policy(policy_type):
            return (
                next_request,
                f"using Pi0.5 runtime env={self.config.pi05_conda_env_name} source={next_request.policy_pretrained_path}",
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
        if not self._is_pi05_policy(request.policy_type):
            return args
        defaults = [
            "--policy.compile_model=false",
            "--policy.gradient_checkpointing=true",
            "--policy.dtype=bfloat16",
            "--policy.freeze_vision_encoder=false",
            "--policy.train_expert_only=false",
        ]
        # Match the upstream LeRobot Pi0.5 reference command. Remove stale local overrides.
        forced_keys = {item.split("=", 1)[0] for item in defaults}
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
        return str(policy_type or "act").strip() or "act"

    def _is_pi05_policy(self, policy_type: str) -> bool:
        return self._canonical_policy_type(policy_type) == "pi05"

    def _train_video_backend(self, policy_type: str, request: LeRobotSessionRequest | None = None) -> str:
        preferred = str(self.config.pi05_video_backend if self._is_pi05_policy(policy_type) else self.config.train_video_backend).strip() or "torchcodec"
        fallback = str(self.config.train_video_backend_fallback or "pyav").strip() or "pyav"
        if preferred != "torchcodec":
            return preferred
        if request is None or (request.runtime_mode or request.mode) != "live":
            return preferred
        env_name = self.config.pi05_conda_env_name if self._is_pi05_policy(policy_type) else self.config.conda_env_name
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

    def _robot_args(self, profile: RobotProfile, *, request: LeRobotSessionRequest, allow_fake: bool = True) -> list[str]:
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
                    )
        if camera_map:
            args.append(f"--robot.cameras={json.dumps(camera_map, ensure_ascii=True)}")
        return args

    def _camera_config_for_command(self, port_or_identifier: str, camera_device: dict[str, Any] | None = None, *, request_fps: int | None = None) -> dict[str, Any]:
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
                color_format=self._realsense_color_format(identifier=identifier, camera_device=device),
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

    @staticmethod
    def _realsense_camera_config(
        serial_number_or_name: str,
        *,
        fps: int,
        use_depth: bool,
        width: int,
        height: int,
        color_format: str,
    ) -> dict[str, Any]:
        return {
            "type": LEROBOT_REALSENSE_TYPE,
            "serial_number_or_name": serial_number_or_name,
            "width": width,
            "height": height,
            "fps": fps,
            "color_format": color_format,
            "use_depth": bool(use_depth),
            # LeRobot / RealSense D405 needs a real warmup period before
            # consuming frames; disabling warmup makes status=False failures
            # more likely after a previous session.
            "warmup_s": LEROBOT_DEFAULT_REALSENSE_WARMUP_S,
        }

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
            return
        if int(returncode) == 0:
            session["status"] = "COMPLETED"
        else:
            session["status"] = "FAILED"

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
            return self._scan_realsense_camera_ids()
        return self._scan_camera_ports()

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
        if stable_port != port:
            device["raw_port"] = port
            device["stability"] = "persistent_path"
        if self._is_device_identity_link(stable_port):
            device["device_id"] = Path(stable_port).name
            device["device_link"] = stable_port
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

    def _serial_role_port_conflict(self, profile_id: str, role: str, port: str, *, memory: dict[str, Any] | None = None) -> str:
        if role not in {"follower", "leader"}:
            return ""
        raw = str(port or "").strip()
        if not raw:
            return ""
        other_role = "leader" if role == "follower" else "follower"
        data = memory or self._load_device_memory()
        profile_memory = data.get("profiles", {}).get(profile_id, {})
        devices = profile_memory.get("devices", {})
        other = devices.get(other_role, {})
        if not isinstance(other, dict):
            return ""
        other_port = str(other.get("port") or other.get("device_link") or "").strip()
        if not other_port:
            return ""
        if raw == other_port:
            return other_role
        try:
            if Path(raw).resolve(strict=True) == Path(other_port).resolve(strict=True):
                return other_role
        except Exception:
            return ""
        return ""

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
        }

    def _policy_presets(self) -> list[dict[str, str]]:
        defaults = [
            {"label": "Manual policy path", "value": "", "source": "manual", "policy_type": ""},
            {"label": "lerobot/act_koch_real", "value": "lerobot/act_koch_real", "repo_id": "lerobot/act_koch_real", "source": "huggingface", "policy_type": "act"},
            {"label": "Pi0.5 base", "value": self.config.pi05_base_policy, "repo_id": self.config.pi05_base_policy, "source": "huggingface", "policy_type": "pi05"},
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
