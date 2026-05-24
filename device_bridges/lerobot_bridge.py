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
POLICY_OUTPUT_FILE_NAMES = {"model.safetensors", "pytorch_model.bin", "policy.ckpt", "policy.pt", "policy.pth"}
POLICY_OUTPUT_FILE_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
MANUAL_STOP_ROLLOUT_EPISODE_S = 86400.0


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
    pi05_conda_env_name: str = "lerobot-pi05"
    pi05_repo_root: Path = Path("~/lerobot_pi05")
    pi05_hf_home: Path = Path("~/.cache/huggingface_pi05")
    pi05_base_policy: str = "lerobot/pi05_base"
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
            conda_executable=str(Path(str(root.get("conda_executable", "conda"))).expanduser()),
            pi05_conda_env_name=str(root.get("pi05_conda_env_name", "lerobot-pi05")),
            pi05_repo_root=pi05_repo_root,
            pi05_hf_home=pi05_hf_home,
            pi05_base_policy=str(root.get("pi05_base_policy", "lerobot/pi05_base")),
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
            ports = [
                {"role": "candidate", "port": port, "port_type": "serial", "detected": True}
                for port in scanned
            ]
            ports.extend({"role": "camera_candidate", "port": port, "port_type": "camera", "detected": True} for port in scanned_cameras)
            serial_ports = scanned
            camera_ports = scanned_cameras
            detail = f"{len(scanned)} local serial candidate ports"
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
        camera_ports = [] if mode == "test" else self._scan_camera_ports()
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
            candidates = [self._fake_camera_port(profile, request.camera_key) if request.device_role == "camera" else self._fake_port(profile, request.device_role)]
            change_type = "test"
        else:
            now = self._scan_camera_ports() if request.device_role == "camera" else self._scan_serial_ports()
            before = baseline.get("camera_ports" if request.device_role == "camera" else "serial_ports", [])
            added = sorted(set(now) - set(before))
            removed = sorted(set(before) - set(now))
            candidates = added or removed or list(now)
            change_type = "added" if added else "removed" if removed else "unchanged"
        chosen = request.port or (candidates[0] if candidates else "")
        if not chosen:
            return self._error("lerobot.ports.detect", mode, profile.profile_id, "LEROBOT_PORT_NOT_FOUND", f"No candidate found for {request.device_role}.")
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            chosen,
            camera_key=request.camera_key,
            source=f"detect_delta:{change_type}",
            memory=memory,
            prefer_identity_link=mode == "live",
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
        if not port:
            return self._error("lerobot.ports.save", mode, profile.profile_id, "LEROBOT_PORT_REQUIRED", "A port or camera index is required.")
        saved = self._save_device_port(
            profile.profile_id,
            request.device_role,
            port,
            camera_key=request.camera_key,
            source="manual",
            prefer_identity_link=mode == "live",
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
        capture = self._fake_camera_capture(profile, camera_key, runtime_camera_port) if mode != "live" else self._live_camera_capture(profile, camera_key, runtime_camera_port)
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
            train_args = self._train_args(profile, request)
        except ValueError as exc:
            return self._error("lerobot.train.start", mode, profile.profile_id, "LEROBOT_TRAIN_CONFIG_INVALID", str(exc))
        status = "COMPLETED" if mode != "live" else "TRAINING"
        trace = [
            ("PRECHECK", "ok", f"{train_detail}; {runtime_detail}"),
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
        policy_args = [f"--policy.path={policy_ref or str(self.config.fake_checkpoint_root / 'policy.ckpt')}"]
        device_override = str(raw_payload.get("device") or "").strip()
        if device_override:
            policy_args.append(f"--policy.device={device_override}")
        if "policy_use_amp" in raw_payload:
            policy_args.append(f"--policy.use_amp={_bool_arg(request.policy_use_amp)}")
        if request.rollout_temporal_ensemble:
            coeff = float(request.rollout_temporal_ensemble_coeff or 0.01)
            policy_args.append(f"--policy.temporal_ensemble_coeff={coeff}")
            policy_args.append("--policy.n_action_steps=1")
        if request.rollout_action_clamp:
            max_relative_target = max(1, int(round(float(request.rollout_max_relative_target or 5))))
            policy_args.append(f"--robot.max_relative_target={max_relative_target}")
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
            extra_args=policy_args
            + [
                f"--dataset.repo_id={request.dataset_repo_id or 'local/eval_lerobot_policy'}",
                f"--dataset.root={self._dataset_path_for(request)}",
                f"--dataset.single_task={request.task_instruction}",
                f"--dataset.fps={request.fps or ''}",
                f"--dataset.episode_time_s={request.episode_s}",
                f"--dataset.num_episodes={request.num_episodes}",
                f"--dataset.push_to_hub={_bool_arg(request.push_to_hub)}",
                f"--display_data={_bool_arg(request.display_data)}",
            ],
            event_payload=payload or {},
        )

    def rollout_stop(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stop rollout idempotently."""
        return self._stop_session("lerobot.rollout.stop", payload or {}, "rollout")

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
        policies = self._policy_presets()
        policies.extend(self._discover_local_policies())
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

    def _session_status(self, tool: str, payload: dict[str, Any], workflow: str) -> dict[str, Any]:
        request = LeRobotBaseRequest.model_validate(payload or {})
        mode = request.runtime_mode or request.mode
        session = self._resolve_session(request.session_id, workflow)
        profile_id = str(session.get("profile_id") if session else request.profile_id or self._selected_profile_id)
        if session is None:
            return self._error(tool, mode, profile_id, "LEROBOT_SESSION_NOT_FOUND", "Session not found.")
        self._refresh_process_status(session)
        return self._session_response(tool, mode, session, list(session.get("step_trace", [])))

    def _session_response(self, tool: str, mode: str, session: dict[str, Any], step_trace: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        training = self._training_progress(session)
        payload = {
            "ok": True,
            "tool": tool,
            "mode": mode,
            "profile_id": session.get("profile_id", ""),
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "status": session.get("status", ""),
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
            "log_tail": self._tail_file(str(session.get("log_path", ""))),
            "pid": session.get("pid"),
            "returncode": session.get("returncode"),
            "error": None,
        }
        if training:
            payload["training"] = training
        if session.get("visualization"):
            payload["visualization"] = session.get("visualization", {})
        payload.update(extra)
        return payload

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
        for match in re.finditer(r"(?<![\d.])(\d{1,9})\s*/\s*(\d{1,9})(?![\d.])", log):
            current = max(current, int(match.group(1)))
            total = max(total or 0, int(match.group(2)))
        for line in log.splitlines():
            if "cfg.steps" in line:
                continue
            match = re.search(r"\b(?:step|global_step)\s*[=:]\s*(\d{1,9})", line, flags=re.IGNORECASE)
            if match:
                current = max(current, int(match.group(1)))
        return current, total

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

    @staticmethod
    def _public_session(session: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": session.get("session_id", ""),
            "workflow": session.get("workflow", ""),
            "profile_id": session.get("profile_id", ""),
            "mode": session.get("mode", ""),
            "status": session.get("status", ""),
            "created_at": session.get("created_at", ""),
            "command_preview": list(session.get("command_preview", [])),
            "dataset_path": session.get("dataset_path", ""),
            "checkpoint_path": session.get("checkpoint_path", ""),
            "log_path": session.get("log_path", ""),
            "pid": session.get("pid"),
            "returncode": session.get("returncode"),
            "training": session.get("train_config", {}),
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

    def _workflow_command(self, profile: RobotProfile, workflow: str, request: LeRobotSessionRequest, args: list[str]) -> list[str]:
        mode = request.runtime_mode or request.mode
        command = [self.config.conda_executable, "run", "--no-capture-output", "-n", self._workflow_conda_env_name(workflow, request)]
        command.extend(self._workflow_entrypoint(profile, workflow))
        if workflow in {"teleoperate", "record", "rollout"}:
            command.extend(self._robot_args(profile, request=request, allow_fake=mode != "live"))
        if workflow in {"teleoperate", "record"}:
            command.extend(self._teleop_args(profile, request=request, allow_fake=mode != "live"))
        command.extend([arg for arg in args if arg and not arg.endswith("=")])
        return command

    def _workflow_conda_env_name(self, workflow: str, request: LeRobotSessionRequest) -> str:
        if workflow == "train" and self._is_pi05_policy(request.policy_type):
            return self.config.pi05_conda_env_name
        return self.config.conda_env_name

    def _workflow_env_overrides(self, workflow: str, request: LeRobotSessionRequest) -> dict[str, str]:
        if workflow == "train" and self._is_pi05_policy(request.policy_type):
            hf_home = self.config.pi05_hf_home
            return {
                "HF_HOME": str(hf_home),
                "HF_HUB_CACHE": str(hf_home / "hub"),
                "HF_HUB_DISABLE_XET": "1",
            }
        return {}

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
        args = [
            f"--dataset.repo_id={dataset_repo}",
            f"--dataset.root={dataset_root}",
            "--dataset.video_backend=pyav",
            f"--policy.type={policy_type}",
            f"--output_dir={output_dir}",
            f"--job_name={job_name}",
            f"--policy.device={request.device or 'cuda'}",
            f"--policy.repo_id={policy_repo}",
            f"--policy.push_to_hub={_bool_arg(request.push_to_hub)}",
            f"--policy.use_amp={_bool_arg(request.policy_use_amp)}",
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
        output_dir = _resolve_path(self.config.repo_root, request.output_dir or str(self.config.output_root / job_name)).resolve()
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

    def _train_request_with_policy_runtime(self, request: LeRobotSessionRequest) -> tuple[LeRobotSessionRequest, str]:
        policy_type = self._canonical_policy_type(request.policy_type or "act")
        updates: dict[str, Any] = {"policy_type": policy_type}
        if self._is_pi05_policy(policy_type):
            fields_set = set(request.model_fields_set)
            shifted_gui_payload = (
                int(request.batch_size) > 512
                or int(request.num_workers) > 256
                or (int(request.batch_size) == 3000 and int(request.steps) <= 16)
            )
            pi05_defaults: dict[str, Any] = {
                "batch_size": 32,
                "steps": 3000,
                "num_workers": 4,
                "eval_freq": 20000,
                "log_freq": 200,
                "save_freq": 20000,
                "policy_n_obs_steps": 1,
                "policy_chunk_size": 50,
                "policy_n_action_steps": 50,
            }
            for field_name, value in pi05_defaults.items():
                if field_name not in fields_set or shifted_gui_payload:
                    updates[field_name] = value
            pretrained = str(request.policy_pretrained_path or "").strip()
            if not self._is_valid_policy_source_ref(pretrained):
                updates["policy_pretrained_path"] = self.config.pi05_base_policy
        next_request = request.model_copy(update=updates)
        if self._is_pi05_policy(policy_type):
            return (
                next_request,
                f"using Pi0.5 runtime env={self.config.pi05_conda_env_name} source={next_request.policy_pretrained_path}",
            )
        return next_request, f"using LeRobot runtime env={self.config.conda_env_name}"

    def _train_extra_args_with_policy_defaults(self, request: LeRobotSessionRequest) -> list[str]:
        args = list(request.train_extra_args or [])
        if not self._is_pi05_policy(request.policy_type):
            return args
        defaults = [
            "--policy.compile_model=true",
            "--policy.gradient_checkpointing=true",
            "--policy.dtype=bfloat16",
            "--policy.freeze_vision_encoder=false",
            "--policy.train_expert_only=false",
            '--policy.normalization_mapping={"ACTION":"MEAN_STD","STATE":"MEAN_STD","VISUAL":"IDENTITY"}',
        ]
        keys = {str(item).split("=", 1)[0] for item in args}
        return [item for item in defaults if item.split("=", 1)[0] not in keys] + args

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
            "dataset_video_backend": "pyav",
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
            return request, f"Pi0.5 dataset already v3.0 at {dataset_path}"
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
                    camera_map[camera_key] = self._opencv_camera_config(runtime_port, request.fps or profile.fps)
        if camera_map:
            args.append(f"--robot.cameras={json.dumps(camera_map, ensure_ascii=True)}")
        return args

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
        """Terminate stale LeRobot process groups started from this checkout."""
        pids_by_group: dict[int, list[int]] = {}
        for pid in self._project_lerobot_pids(workflow):
            try:
                pgid = os.getpgid(pid)
            except ProcessLookupError:
                continue
            if pgid == os.getpgrp():
                continue
            pids_by_group.setdefault(pgid, []).append(pid)
        if not pids_by_group:
            return []

        for pgid in sorted(pids_by_group):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.time() + 5.0
        while time.time() < deadline:
            remaining = [pid for pids in pids_by_group.values() for pid in pids if self._pid_alive(pid)]
            if not remaining:
                break
            time.sleep(0.1)
        for pgid, pids in pids_by_group.items():
            if any(self._pid_alive(pid) for pid in pids):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        details = []
        for pgid, pids in sorted(pids_by_group.items()):
            details.append(f"pgid={pgid} pids={','.join(str(pid) for pid in sorted(pids))}")
        return [{"step": "CLEANUP_LEROBOT_PROCESS_GROUPS", "status": "ok", "detail": f"{workflow}: {'; '.join(details)}"}]

    def _project_lerobot_pids(self, workflow: str) -> list[int]:
        markers_by_workflow = {
            "teleoperate": ("lerobot-teleoperate", "lerobot.teleoperate"),
            "record": ("lerobot-record", "lerobot.record"),
            "train": ("lerobot-train", "lerobot.train"),
            "rollout": ("lerobot-rollout", "lerobot.rollout"),
            "visualize": ("lerobot.scripts.visualize_dataset", "lerobot.scripts.visualize_dataset_html", "visualize_dataset.py", "visualize_dataset_html.py"),
        }
        markers = markers_by_workflow.get(workflow, ("lerobot-", "lerobot."))
        project = self.config.repo_root.resolve()
        current = {os.getpid(), os.getppid()}
        pids: list[int] = []
        for name in os.listdir("/proc"):
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
            if not any(marker in cmd for marker in markers):
                continue
            try:
                cwd = Path(os.readlink(proc_dir / "cwd")).resolve()
            except OSError:
                cwd = Path("/")
            if cwd == project or project in cwd.parents or str(project) in cmd:
                pids.append(pid)
        return sorted(set(pids))

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

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
            updates["dataset_path"] = f"{request.dataset_path.rstrip('/')}-{suffix}"
        else:
            repo_id = request.dataset_repo_id or "local/lerobot-record"
            updates["dataset_repo_id"] = self._dataset_repo_id_with_suffix(repo_id, suffix)
        next_request = request.model_copy(update=updates)
        return next_request, False, f"existing dataset detected; recording to fresh dataset {self._dataset_path_for(next_request)}"

    @staticmethod
    def _dataset_repo_id_with_suffix(repo_id: str, suffix: str) -> str:
        clean = str(repo_id or "local/lerobot-record").strip().strip("/")
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
    ) -> dict[str, Any]:
        data = memory or self._load_device_memory()
        profile_memory = self._profile_device_memory(data, profile_id)
        stable_port = self._stable_device_port(port, role) if prefer_identity_link else str(port or "").strip()
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
            devices = profile_memory.setdefault("devices", {})
            devices.setdefault("cameras", {})[key] = device
            if key == "top":
                devices["camera"] = device
        else:
            profile_memory.setdefault("devices", {})[role] = device
        self._save_device_memory(data)
        return device

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
        """Resolve live serial identity links while preserving camera paths for OpenCV."""
        raw = str(port or "").strip()
        if not raw or not live:
            return raw
        if role == "camera":
            return raw
        if not self._is_device_identity_link(raw):
            return raw
        try:
            return str(Path(raw).resolve(strict=True))
        except Exception:
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

    def _live_camera_capture(self, profile: RobotProfile, camera_key: str, camera_port: str) -> dict[str, Any]:
        capture_dir = self.config.repo_root / "artifacts" / "lerobot" / "camera_tests"
        capture_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = capture_dir / f"{profile.profile_id}_{camera_key}_{timestamp}.jpg"
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
            "pi05": {
                "conda_env_name": self.config.pi05_conda_env_name,
                "repo_root": str(self.config.pi05_repo_root),
                "hf_home": str(self.config.pi05_hf_home),
                "hf_hub_cache": str(self.config.pi05_hf_home / "hub"),
                "base_policy": self.config.pi05_base_policy,
                "available": (Path.home() / "miniconda3" / "envs" / self.config.pi05_conda_env_name / "bin" / "lerobot-train").exists(),
            },
        }

    def _policy_presets(self) -> list[dict[str, str]]:
        defaults = [
            {"label": "Manual policy path", "value": "", "source": "manual"},
            {"label": "lerobot/act_koch_real", "value": "lerobot/act_koch_real", "repo_id": "lerobot/act_koch_real", "source": "huggingface"},
            {"label": "Pi0.5 base", "value": self.config.pi05_base_policy, "repo_id": self.config.pi05_base_policy, "source": "huggingface"},
            {"label": "Pi0 base", "value": "lerobot/pi0_base", "repo_id": "lerobot/pi0_base", "source": "huggingface"},
            {"label": "Pi0FAST base", "value": "lerobot/pi0fast-base", "repo_id": "lerobot/pi0fast-base", "source": "huggingface"},
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
            try:
                config = json.loads((path / "config.json").read_text(encoding="utf-8"))
                repo_id = str(config.get("repo_id") or "")
            except Exception:
                repo_id = ""
            label = path.parent.parent.parent.name if "checkpoints" in str(path) else path.name
            if repo_id:
                label = f"{label} ({repo_id})"
            policies.append({"label": label, "value": str(path), "path": str(path), "repo_id": repo_id, "source": "local"})
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


def _bool_arg(value: bool) -> str:
    return "true" if bool(value) else "false"


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
