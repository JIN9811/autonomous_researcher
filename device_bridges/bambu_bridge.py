"""
File purpose:
- Bambu Lab / multi-printer bridge manager foundation for printer.prepare.

Key classes/functions:
- PrinterProfile, BambuBridgeConfig, PrinterDeviceBridgeManager

Inputs/outputs:
- Input: devices.yaml printer config and printer.prepare payloads
- Output: selected-printer workflow results with user-facing device screen payloads

Dependencies:
- pathlib/json/socket/ssl from the standard library

Modification guide:
- Safe places to edit: virtual payload shape, profile capability defaults
- Risky places to edit: live action gates and command generation policy
- Related files: mcp_tools/printer_tools.py, device_bridges/prusa_bridge.py, web/static/printer.js
"""

from __future__ import annotations

import copy
import json
import hashlib
import ipaddress
import io
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from ftplib import FTP_TLS
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from device_bridges.bambu_autoejection import BambuGcodeAutoejectionPatcher

try:  # Optional until dependencies are installed in downstream deployments.
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover - exercised when dependency is absent.
    mqtt = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLEET_MEMORY = REPO_ROOT / "memory" / "printer_fleet.json"
DEFAULT_BAMBU_MEMORY = REPO_ROOT / "memory" / "bambu_connection.json"
DEFAULT_BAMBU_AUTOEJECTION_MEMORY = REPO_ROOT / "memory" / "bambu_autoejection.json"
DEFAULT_BAMBU_BED_CLEAR_MEMORY = REPO_ROOT / "memory" / "bambu_bed_clear_evidence.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _resolve_path(value: str | Path | None, *, repo_root: Path) -> Path:
    raw = Path(str(value or DEFAULT_BAMBU_MEMORY))
    return raw if raw.is_absolute() else repo_root / raw


def _sanitize_bambu_remote_dir(value: str) -> str:
    cleaned = str(value or "").strip().replace("\\", "/").strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return ""
    return "/".join(parts)


@dataclass(slots=True)
class PrinterProfile:
    """Selectable printer profile owned by the fleet manager."""

    profile_id: str
    provider: str
    label: str
    enabled: bool = True
    connection_memory_path: Path = DEFAULT_BAMBU_MEMORY
    capabilities: dict[str, Any] = field(default_factory=dict)
    priority: int = 0

    @classmethod
    def from_dict(cls, profile_id: str, raw: dict[str, Any], *, repo_root: Path) -> "PrinterProfile":
        provider = str(raw.get("provider") or profile_id or "bambulab_x2d").strip()
        memory = _resolve_path(raw.get("connection_memory_path"), repo_root=repo_root)
        return cls(
            profile_id=str(profile_id),
            provider=provider,
            label=str(raw.get("label") or profile_id),
            enabled=_as_bool(raw.get("enabled"), True),
            connection_memory_path=memory,
            capabilities=dict(raw.get("capabilities", {})) if isinstance(raw.get("capabilities"), dict) else {},
            priority=int(raw.get("priority", 0) or 0),
        )

    def redacted(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "provider": self.provider,
            "label": self.label,
            "enabled": self.enabled,
            "capabilities": self.capabilities,
        }


@dataclass(slots=True)
class BambuSlicerConfig:
    enabled: bool = False
    executable_env: str = "BAMBU_STUDIO_EXECUTABLE"
    executable_path: str = "install/bambustudio/bambu-studio-wrapper"
    output_dir: str = "artifacts/bambu_sliced"
    timeout_sec: float = 900.0
    auto_no_skirt_profile: bool = True
    default_machine_profile: str = ""
    default_process_profile: str = ""
    default_filament_profile: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BambuSlicerConfig":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=_as_bool(raw.get("enabled"), False),
            executable_env=str(raw.get("executable_env", "BAMBU_STUDIO_EXECUTABLE")),
            executable_path=str(raw.get("executable_path", "install/bambustudio/bambu-studio-wrapper")),
            output_dir=str(raw.get("output_dir", "artifacts/bambu_sliced")),
            timeout_sec=float(raw.get("timeout_sec", 900) or 900),
            auto_no_skirt_profile=_as_bool(raw.get("auto_no_skirt_profile"), True),
            default_machine_profile=str(raw.get("default_machine_profile", "") or ""),
            default_process_profile=str(raw.get("default_process_profile", "") or ""),
            default_filament_profile=str(raw.get("default_filament_profile", "") or ""),
        )

    def resolved_payload(self, *, repo_root: Path | None = None) -> dict[str, Any]:
        """Resolve the Bambu Studio CLI path without treating a missing wrapper as final."""
        root = repo_root or REPO_ROOT
        output_dir = _resolve_path(self.output_dir, repo_root=root)
        configured_path = str(self.executable_path or "").strip()
        env_name = str(self.executable_env or "").strip()
        env_value = str(os.environ.get(env_name, "")).strip() if env_name else ""
        candidates: list[tuple[str, str]] = []
        if env_value:
            candidates.append(("env", env_value))
        if configured_path:
            candidates.append(("configured", configured_path))
        for name in ("bambu-studio", "BambuStudio", "bambu-studio.AppImage"):
            found = shutil.which(name)
            if found:
                candidates.append(("path", found))

        checked: list[dict[str, str]] = []
        resolved_path = ""
        source = "missing"
        for candidate_source, candidate in candidates:
            candidate_path = Path(candidate).expanduser()
            if not candidate_path.is_absolute():
                candidate_path = root / candidate_path
            checked.append({"source": candidate_source, "path": str(candidate_path)})
            if candidate_path.exists() and os.access(candidate_path, os.X_OK):
                resolved_path = str(candidate_path)
                source = candidate_source
                break

        return {
            "enabled": self.enabled,
            "available": bool(resolved_path),
            "source": source,
            "executable_env": env_name,
            "executable_path": configured_path,
            "configured_executable_path": configured_path,
            "resolved_executable_path": resolved_path,
            "output_dir": str(output_dir),
            "timeout_sec": self.timeout_sec,
            "checked": checked,
        }


class BambuStudioSlicerRunner:
    """Run Bambu Studio CLI to create a real printer artifact without publishing."""

    def __init__(self, config: BambuSlicerConfig, *, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or REPO_ROOT

    def slice(
        self,
        source_path: str | Path,
        *,
        specimen_id: str = "",
        load_settings: str | Path | None = None,
        load_filaments: str | Path | None = None,
        extra_args: list[str] | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        """Slice an STL/3MF into a Bambu artifact and return manifest evidence."""
        source = Path(str(source_path or "")).expanduser()
        if not source.is_absolute():
            source = (self.repo_root / source).resolve()
        else:
            source = source.resolve()
        if not source.exists() or not source.is_file():
            return self._blocked("BAMBU_SLICER_SOURCE_FILE_NOT_FOUND", source_path=str(source))
        if source.suffix.lower() not in {".stl", ".3mf"}:
            return self._blocked("BAMBU_SLICER_SOURCE_EXTENSION_UNSUPPORTED", source_path=str(source))

        resolved = self.config.resolved_payload(repo_root=self.repo_root)
        if not resolved.get("enabled"):
            return self._blocked("BAMBU_STUDIO_SLICER_DISABLED", source_path=str(source), slicer=resolved)
        executable = str(resolved.get("resolved_executable_path") or "")
        if not executable:
            return self._blocked("BAMBU_STUDIO_SLICER_UNAVAILABLE", source_path=str(source), slicer=resolved)

        output_root = Path(str(resolved.get("output_dir") or self.config.output_dir)).expanduser()
        if not output_root.is_absolute():
            output_root = self.repo_root / output_root
        safe_id = self._safe_name(specimen_id or source.stem)
        output_dir = (output_root / safe_id).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        export_path = output_dir / f"{safe_id}.gcode.3mf"
        slicer_profile = self._default_no_skirt_profile(output_dir) if not load_settings else {
            "auto_no_skirt_profile": False,
            "reason": "explicit_load_settings_supplied",
        }
        effective_load_settings = load_settings
        effective_load_filaments = load_filaments
        if not effective_load_settings and slicer_profile.get("ok"):
            effective_load_settings = str(slicer_profile.get("load_settings") or "")
            if not effective_load_filaments:
                effective_load_filaments = str(slicer_profile.get("load_filaments") or "")

        before = {path.resolve() for path in self._candidate_outputs(output_dir)}
        command = [
            executable,
            "--slice",
            "0",
            "--arrange",
            "1",
            "--ensure-on-bed",
            "--outputdir",
            str(output_dir),
            "--export-3mf",
            export_path.name,
            "--debug",
            "2",
        ]
        if effective_load_settings:
            command.extend(["--load-settings", str(self._resolve_existing_optional(effective_load_settings))])
        if effective_load_filaments:
            command.extend(["--load-filaments", str(self._resolve_existing_optional(effective_load_filaments))])
        if extra_args:
            command.extend(str(item) for item in extra_args)
        command.append(str(source))

        started_at = _utc_now()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=float(timeout_sec if timeout_sec is not None else self.config.timeout_sec),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                **self._blocked("BAMBU_STUDIO_SLICE_TIMEOUT", source_path=str(source), slicer=resolved),
                "command": command,
                "timeout_sec": float(timeout_sec if timeout_sec is not None else self.config.timeout_sec),
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "slicer_profile": slicer_profile,
            }
        except OSError as exc:
            return {
                **self._blocked("BAMBU_STUDIO_SLICE_EXEC_FAILED", source_path=str(source), slicer=resolved),
                "command": command,
                "error": str(exc),
                "slicer_profile": slicer_profile,
            }

        outputs = [path for path in self._candidate_outputs(output_dir) if path.resolve() not in before]
        if not outputs:
            outputs = self._candidate_outputs(output_dir)
        outputs = sorted(outputs, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        selected = outputs[0] if outputs else None
        if completed.returncode != 0 or selected is None or not selected.exists():
            return {
                **self._blocked(
                    "BAMBU_STUDIO_SLICE_FAILED" if completed.returncode != 0 else "BAMBU_STUDIO_SLICE_OUTPUT_MISSING",
                    source_path=str(source),
                    slicer=resolved,
                ),
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "output_dir": str(output_dir),
                "outputs": [str(path) for path in outputs[:12]],
                "slicer_profile": slicer_profile,
            }

        data = selected.read_bytes()
        return {
            "ok": True,
            "tool": "printer.bambu.slice_artifact",
            "status": "sliced_not_published",
            "source_path": str(source),
            "sliced_artifact_path": str(selected),
            "output_dir": str(output_dir),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "slicer": resolved,
            "slicer_profile": slicer_profile,
            "created_at": _utc_now(),
            "started_at": started_at,
            "will_publish": False,
            "start_enabled": False,
            "next_step": "Use /api/printer/http-artifact-route to expose this sliced artifact before any guarded start command.",
        }

    def _candidate_outputs(self, output_dir: Path) -> list[Path]:
        allowed_suffixes = (".gcode.3mf", ".3mf", ".gcode")
        if not output_dir.exists():
            return []
        return [
            path
            for path in output_dir.rglob("*")
            if path.is_file() and any(path.name.lower().endswith(suffix) for suffix in allowed_suffixes)
        ]

    def _default_no_skirt_profile(self, output_dir: Path) -> dict[str, Any]:
        if not self.config.auto_no_skirt_profile:
            return {"ok": False, "auto_no_skirt_profile": False, "reason": "disabled"}
        machine = self._resolve_bambu_profile(
            self.config.default_machine_profile,
            "system/BBL/machine/Bambu Lab X2D 0.4 nozzle.json",
        )
        process = self._resolve_bambu_profile(
            self.config.default_process_profile,
            "system/BBL/process/0.20mm Standard @BBL X2D.json",
        )
        filament = self._resolve_bambu_profile(
            self.config.default_filament_profile,
            "system/BBL/filament/Bambu PLA Basic @BBL X2D 0.4 nozzle.json",
        )
        missing = [
            name
            for name, path in {"machine": machine, "process": process, "filament": filament}.items()
            if path is None
        ]
        if missing:
            return {
                "ok": False,
                "auto_no_skirt_profile": False,
                "reason": "default_profile_source_missing",
                "missing": missing,
            }

        profile_dir = output_dir / "_atr_no_skirt_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        machine_out = profile_dir / "machine.json"
        process_out = profile_dir / "process.no-skirt.json"
        filament_out = profile_dir / "filament.json"
        machine_out.write_bytes(machine.read_bytes())
        filament_out.write_bytes(filament.read_bytes())
        try:
            process_payload = json.loads(process.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            process_payload = {}
        if not isinstance(process_payload, dict):
            process_payload = {}
        process_payload.update(
            {
                "skirt_loops": "0",
                "skirt_height": "0",
                "skirt_distance": "0",
                "brim_type": "no_brim",
                "brim_width": "0",
                "brim_object_gap": "0",
                "raft_layers": "0",
                "prime_tower_brim_width": "0",
                "enable_prime_tower": "0",
            }
        )
        process_out.write_text(json.dumps(process_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "ok": True,
            "auto_no_skirt_profile": True,
            "machine_profile_path": str(machine),
            "process_profile_path": str(process),
            "filament_profile_path": str(filament),
            "machine_override_path": str(machine_out),
            "process_override_path": str(process_out),
            "filament_override_path": str(filament_out),
            "load_settings": f"{machine_out};{process_out}",
            "load_filaments": str(filament_out),
            "overrides": {
                "skirt_loops": "0",
                "skirt_height": "0",
                "brim_type": "no_brim",
                "brim_width": "0",
                "raft_layers": "0",
            },
        }

    def _resolve_bambu_profile(self, configured: str, relative_default: str) -> Path | None:
        candidates: list[Path] = []
        if configured:
            configured_path = Path(configured).expanduser()
            candidates.append(configured_path if configured_path.is_absolute() else self.repo_root / configured_path)
        rel = Path(relative_default)
        candidates.extend(
            [
                Path.home() / ".config" / "BambuStudio" / rel,
                Path.home() / ".var" / "app" / "com.bambulab.BambuStudio" / "config" / "BambuStudio" / rel,
            ]
        )
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None

    def _resolve_existing_optional(self, value: str | Path) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def _safe_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
        return safe.strip("._-") or f"bambu-slice-{uuid.uuid4().hex[:8]}"

    def _blocked(self, failure_code: str, **extra: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": "printer.bambu.slice_artifact",
            "status": "blocked",
            "failure_code": failure_code,
            "will_publish": False,
            "start_enabled": False,
            **extra,
        }


@dataclass(slots=True)
class BambuMqttConfig:
    port: int = 8883
    timeout_sec: float = 5.0
    publish_timeout_sec: float = 180.0
    username: str = "bblp"
    report_topic_template: str = "device/{serial}/report"
    request_topic_template: str = "device/{serial}/request"
    snapshot_cache_ttl_sec: float = 1.5

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BambuMqttConfig":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            port=int(raw.get("port", 8883) or 8883),
            timeout_sec=float(raw.get("timeout_sec", 5.0) or 5.0),
            publish_timeout_sec=max(60.0, _as_float(raw.get("publish_timeout_sec"), 180.0)),
            username=str(raw.get("username", "bblp") or "bblp"),
            report_topic_template=str(raw.get("report_topic_template", "device/{serial}/report")),
            request_topic_template=str(raw.get("request_topic_template", "device/{serial}/request")),
            snapshot_cache_ttl_sec=max(0.0, float(raw.get("snapshot_cache_ttl_sec", 1.5) or 0.0)),
        )


@dataclass(slots=True)
class BambuVideoConfig:
    enabled: bool = True
    rtsps_port: int = 322
    jpeg_stream_port: int = 6000
    timeout_sec: float = 3.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BambuVideoConfig":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=_as_bool(raw.get("enabled"), True),
            rtsps_port=int(raw.get("rtsps_port", 322) or 322),
            jpeg_stream_port=int(raw.get("jpeg_stream_port", 6000) or 6000),
            timeout_sec=float(raw.get("timeout_sec", 3.0) or 3.0),
        )


@dataclass(slots=True)
class AutoEjectionConfig:
    enabled: bool = False
    provider: str = "none"
    verified_routine_id: str = ""
    pre_eject_vision_profile: str = ""
    post_eject_vision_profile: str = ""
    require_verified_routine: bool = True
    require_pre_eject_vision: bool = True
    require_post_eject_vision: bool = True
    recovery_to_robot_pickoff: bool = True
    push_direction: str = "center"
    z_push_offset_mm: float = 30.0
    push_lane_offset_mm: float = 30.0
    push_speed_mm_min: int = 300
    enable_full_bed_sweep: bool = False
    sweep_z_mm: float = 1.0
    sweep_speed_mm_min: int = 300

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "AutoEjectionConfig":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=_as_bool(raw.get("enabled"), False),
            provider=str(raw.get("provider", "none") or "none"),
            verified_routine_id=str(raw.get("verified_routine_id", "") or ""),
            pre_eject_vision_profile=str(raw.get("pre_eject_vision_profile", "") or ""),
            post_eject_vision_profile=str(raw.get("post_eject_vision_profile", "") or ""),
            require_verified_routine=_as_bool(raw.get("require_verified_routine"), True),
            require_pre_eject_vision=_as_bool(raw.get("require_pre_eject_vision"), True),
            require_post_eject_vision=_as_bool(raw.get("require_post_eject_vision"), True),
            recovery_to_robot_pickoff=_as_bool(
                raw.get("recovery_to_robot_pickoff", raw.get("fallback_to_robot_pickoff")),
                True,
            ),
            push_direction=cls._clean_push_direction(raw.get("push_direction")),
            z_push_offset_mm=max(0.0, min(200.0, _as_float(raw.get("z_push_offset_mm"), 30.0))),
            push_lane_offset_mm=max(0.0, min(120.0, _as_float(raw.get("push_lane_offset_mm"), 30.0))),
            push_speed_mm_min=max(100, min(1000, _as_int(raw.get("push_speed_mm_min"), 300))),
            enable_full_bed_sweep=_as_bool(raw.get("enable_full_bed_sweep"), False),
            sweep_z_mm=max(0.5, min(50.0, _as_float(raw.get("sweep_z_mm"), 1.0))),
            sweep_speed_mm_min=max(100, min(1000, _as_int(raw.get("sweep_speed_mm_min"), 300))),
        )

    @staticmethod
    def _clean_push_direction(value: Any) -> str:
        clean = str(value or "center").strip().lower()
        return clean if clean in {"left", "center", "right"} else "center"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "verified_routine_id": self.verified_routine_id,
            "pre_eject_vision_profile": self.pre_eject_vision_profile,
            "post_eject_vision_profile": self.post_eject_vision_profile,
            "require_verified_routine": self.require_verified_routine,
            "require_pre_eject_vision": self.require_pre_eject_vision,
            "require_post_eject_vision": self.require_post_eject_vision,
            "recovery_to_robot_pickoff": self.recovery_to_robot_pickoff,
            "push_direction": self.push_direction,
            "z_push_offset_mm": self.z_push_offset_mm,
            "push_lane_offset_mm": self.push_lane_offset_mm,
            "push_speed_mm_min": self.push_speed_mm_min,
            "enable_full_bed_sweep": self.enable_full_bed_sweep,
            "sweep_z_mm": self.sweep_z_mm,
            "sweep_speed_mm_min": self.sweep_speed_mm_min,
        }

    def native_gcode_parameters(self) -> dict[str, Any]:
        return {
            "push_direction": self.push_direction,
            "z_push_offset_mm": self.z_push_offset_mm,
            "push_lane_offset_mm": self.push_lane_offset_mm,
            "push_speed_mm_min": self.push_speed_mm_min,
            "enable_full_bed_sweep": self.enable_full_bed_sweep,
            "sweep_z_mm": self.sweep_z_mm,
            "sweep_speed_mm_min": self.sweep_speed_mm_min,
        }

    def status_payload(self) -> dict[str, Any]:
        requested = bool(self.enabled)
        provider_configured = self.provider not in {"", "none"}
        native_gcode_patch = self.provider in {"bambu_gcode_patch", "native_gcode", "gcode_patch"}
        blockers: list[str] = []
        if not requested:
            blockers.append("BAMBU_AUTOEJECTION_NOT_REQUESTED")
        if requested and not provider_configured:
            blockers.append("BAMBU_AUTOEJECTION_PROVIDER_NOT_CONFIGURED")
        if (
            requested
            and provider_configured
            and not native_gcode_patch
            and self.require_verified_routine
            and not self.verified_routine_id
        ):
            blockers.append("BAMBU_AUTOEJECTION_ROUTINE_NOT_VERIFIED")
        if (
            requested
            and provider_configured
            and not native_gcode_patch
            and self.require_pre_eject_vision
            and not self.pre_eject_vision_profile
        ):
            blockers.append("BAMBU_PRE_EJECT_VISION_PROFILE_REQUIRED")
        if (
            requested
            and provider_configured
            and not native_gcode_patch
            and self.require_post_eject_vision
            and not self.post_eject_vision_profile
        ):
            blockers.append("BAMBU_POST_EJECT_VISION_PROFILE_REQUIRED")
        configured = requested and provider_configured and not blockers
        return {
            "enabled": bool(configured),
            "requested": requested,
            "provider": self.provider,
            "native_gcode_patch": native_gcode_patch,
            "status": "configured" if configured else ("not_configured" if not requested else "blocked"),
            "can_run_test": bool(configured),
            "blockers": blockers,
            "verified_routine_id": self.verified_routine_id,
            "pre_eject_vision_profile": self.pre_eject_vision_profile,
            "post_eject_vision_profile": self.post_eject_vision_profile,
            "require_verified_routine": self.require_verified_routine,
            "require_pre_eject_vision": self.require_pre_eject_vision,
            "require_post_eject_vision": self.require_post_eject_vision,
            "recovery_to_robot_pickoff": self.recovery_to_robot_pickoff,
            "native_gcode_parameters": self.native_gcode_parameters(),
        }


@dataclass(slots=True)
class BambuBridgeConfig:
    """Configuration for the printer fleet and Bambu adapter defaults."""

    mode: str = "test"
    default_profile_id: str = "bambulab_x2d_lab_01"
    allow_automatic_fallback: bool = False
    connection_memory_path: Path = DEFAULT_FLEET_MEMORY
    profiles: dict[str, PrinterProfile] = field(default_factory=dict)
    slicer: BambuSlicerConfig = field(default_factory=BambuSlicerConfig)
    mqtt: BambuMqttConfig = field(default_factory=BambuMqttConfig)
    video: BambuVideoConfig = field(default_factory=BambuVideoConfig)
    autoejection: AutoEjectionConfig = field(default_factory=AutoEjectionConfig)
    autoejection_memory_path: Path = DEFAULT_BAMBU_AUTOEJECTION_MEMORY

    @classmethod
    def from_devices_config(cls, cfg: dict[str, Any] | None, *, repo_root: Path | None = None) -> "BambuBridgeConfig":
        root = repo_root or REPO_ROOT
        cfg = cfg if isinstance(cfg, dict) else {}
        devices = cfg.get("devices") if isinstance(cfg.get("devices"), dict) else cfg
        printer = devices.get("printer", {}) if isinstance(devices, dict) else {}
        if not isinstance(printer, dict):
            printer = {}

        raw_profiles = printer.get("profiles") if isinstance(printer.get("profiles"), dict) else {}
        profiles = {
            str(profile_id): PrinterProfile.from_dict(str(profile_id), raw, repo_root=root)
            for profile_id, raw in raw_profiles.items()
            if isinstance(raw, dict)
        }
        if not profiles:
            profiles = cls._default_profiles(root)

        default_profile_id = str(printer.get("default_profile_id") or printer.get("provider") or "bambulab_x2d_lab_01")
        if default_profile_id == "bambulab_x2d":
            default_profile_id = "bambulab_x2d_lab_01"
        if default_profile_id == "prusa_mk4s":
            default_profile_id = "prusa_mk4s_lab_01"
        if default_profile_id not in profiles:
            default_profile_id = next(iter(profiles))

        bambu = printer.get("bambu") if isinstance(printer.get("bambu"), dict) else {}
        autoejection_raw = printer.get("autoejection") if isinstance(printer.get("autoejection"), dict) else {}
        memory_path = _resolve_path(printer.get("connection_memory_path", DEFAULT_FLEET_MEMORY), repo_root=root)
        autoejection_memory_path = _resolve_path(
            autoejection_raw.get("memory_path") or printer.get("autoejection_memory_path") or "memory/bambu_autoejection.json",
            repo_root=root,
        )
        return cls(
            mode=str(printer.get("mode", "test") or "test").strip().lower(),
            default_profile_id=default_profile_id,
            allow_automatic_fallback=_as_bool(printer.get("allow_automatic_fallback"), False),
            connection_memory_path=memory_path,
            profiles=profiles,
            slicer=BambuSlicerConfig.from_dict(bambu.get("slicer") if isinstance(bambu, dict) else {}),
            mqtt=BambuMqttConfig.from_dict(bambu.get("mqtt") if isinstance(bambu, dict) else {}),
            video=BambuVideoConfig.from_dict(bambu.get("video") if isinstance(bambu, dict) else {}),
            autoejection=AutoEjectionConfig.from_dict(autoejection_raw),
            autoejection_memory_path=autoejection_memory_path,
        )

    @staticmethod
    def _default_profiles(repo_root: Path) -> dict[str, PrinterProfile]:
        return {
            "bambulab_x2d_lab_01": PrinterProfile(
                profile_id="bambulab_x2d_lab_01",
                provider="bambulab_x2d",
                label="Bambu Lab X2D - Lab 01",
                connection_memory_path=repo_root / "memory" / "bambu_connection.json",
                priority=10,
                capabilities={
                    "slicer": "bambu_studio_cli",
                    "transfer": ["ftps", "bambu_connect"],
                    "telemetry": "mqtt",
                    "live_view": "lan_video_stream",
                    "nozzle_modes": ["main", "auxiliary", "dual"],
                    "build_volume_main_mm": [256, 256, 260],
                    "build_volume_dual_mm": [235.5, 256, 256],
                },
            ),
            "prusa_mk4s_lab_01": PrinterProfile(
                profile_id="prusa_mk4s_lab_01",
                provider="prusa_mk4s",
                label="Prusa MK4S - Lab 01",
                connection_memory_path=repo_root / "memory" / "prusa_connection.json",
                priority=5,
                capabilities={
                    "slicer": "prusa_slicer",
                    "transfer": "prusalink_http",
                    "telemetry": "prusalink_rest",
                    "live_view": "none",
                },
            ),
        }

    @property
    def default_profile(self) -> PrinterProfile:
        return self.profiles[self.default_profile_id]

    def profile(self, profile_id: str) -> PrinterProfile:
        try:
            return self.profiles[str(profile_id)]
        except KeyError as exc:
            raise KeyError(f"Unknown printer profile: {profile_id}") from exc


class BambuConnectionMemory:
    """Small local memory reader for Bambu LAN connection information."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def redacted(self) -> dict[str, Any]:
        payload = self.load()
        auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
        return {
            "host": str(payload.get("host", "")),
            "serial": str(payload.get("serial", "")),
            "printer_name": str(payload.get("printer_name", "")),
            "model": str(payload.get("model", "Bambu Lab X2D") or "Bambu Lab X2D"),
            "lan_mode_confirmed": bool(payload.get("lan_mode_confirmed", False)),
            "developer_mode_confirmed": bool(payload.get("developer_mode_confirmed", False)),
            "auth_mode": str(auth.get("mode", "lan_access_code") or "lan_access_code"),
            "username": str(auth.get("username", "bblp") or "bblp"),
            "access_code_set": bool(auth.get("access_code")),
            "connection_memory_path": str(self.path),
        }

    def save_from_payload(self, payload: dict[str, Any]) -> None:
        """Persist Bambu LAN connection fields while keeping the file local-only."""
        source = payload if isinstance(payload, dict) else {}
        auth = source.get("auth") if isinstance(source.get("auth"), dict) else {}
        existing = self.load()
        existing_auth = existing.get("auth") if isinstance(existing.get("auth"), dict) else {}
        access_code = str(auth.get("access_code") or source.get("access_code") or "")
        if not access_code:
            access_code = str(existing_auth.get("access_code") or "")
        record = {
            "host": str(source.get("host") or existing.get("host") or "").strip(),
            "model": str(source.get("model") or existing.get("model") or "Bambu Lab X2D"),
            "serial": str(source.get("serial") or existing.get("serial") or "").strip(),
            "printer_name": str(source.get("printer_name") or existing.get("printer_name") or "").strip(),
            "lan_mode_confirmed": bool(source.get("lan_mode_confirmed", existing.get("lan_mode_confirmed", False))),
            "developer_mode_confirmed": bool(
                source.get("developer_mode_confirmed", existing.get("developer_mode_confirmed", False))
            ),
            "auth": {
                "mode": str(auth.get("mode") or source.get("auth_mode") or "lan_access_code"),
                "username": str(auth.get("username") or source.get("username") or "bblp"),
                "access_code": access_code,
            },
            "transfer": {
                "preferred": str(source.get("transfer_preferred") or existing.get("transfer", {}).get("preferred") or "ftps"),
                "ftps_port": int(source.get("ftps_port") or existing.get("transfer", {}).get("ftps_port") or 990),
                "mqtt_port": int(source.get("mqtt_port") or existing.get("transfer", {}).get("mqtt_port") or 8883),
            },
            "live_view": {
                "enabled": bool(source.get("live_view_enabled", existing.get("live_view", {}).get("enabled", True))),
                "preferred": str(source.get("live_view_preferred") or existing.get("live_view", {}).get("preferred") or "auto"),
                "rtsps_port": int(source.get("rtsps_port") or existing.get("live_view", {}).get("rtsps_port") or 322),
                "jpeg_stream_port": int(
                    source.get("jpeg_stream_port") or existing.get("live_view", {}).get("jpeg_stream_port") or 6000
                ),
            },
            "updated_at": _utc_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


class BambuAutoejectionMemory:
    """Local operator-verified Bambu autoejection configuration overlay."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def config_with_defaults(self, defaults: AutoEjectionConfig) -> AutoEjectionConfig:
        payload = self.load()
        if not payload:
            return defaults
        raw = defaults.to_dict()
        for key in raw:
            if key in payload:
                raw[key] = payload[key]
        return AutoEjectionConfig.from_dict(raw)

    def runtime_paths(self) -> dict[str, Any]:
        payload = self.load()
        paths = payload.get("runtime_paths") if isinstance(payload.get("runtime_paths"), dict) else {}
        if paths:
            return paths
        return {
            "standalone_endpoint": "/api/printer/autoejection-test",
            "standalone_transport": "mqtt_gcode_line",
            "actual_print_transport": "project_file",
            "virtual_bridge_transport": "virtual",
            "artifact_dir": "artifacts/bambu_autoejection",
            "validation_summary_path": "runs/manual_bambu_validation/direct_gcode_line_validation_summary.json",
            "home_after_standalone": False,
            "skipped_direct_commands": ["M190"],
        }

    def save_from_payload(self, payload: dict[str, Any], defaults: AutoEjectionConfig) -> AutoEjectionConfig:
        source = payload if isinstance(payload, dict) else {}
        existing = self.load()
        raw = defaults.to_dict()
        for key in raw:
            if key in source:
                raw[key] = source[key]
        config = AutoEjectionConfig.from_dict(raw)
        runtime_paths = existing.get("runtime_paths") if isinstance(existing.get("runtime_paths"), dict) else {}
        if isinstance(source.get("runtime_paths"), dict):
            runtime_paths = {**runtime_paths, **source["runtime_paths"]}
        record = {
            "schema": "bambu_autoejection.v1",
            **config.to_dict(),
            "runtime_paths": runtime_paths or self.runtime_paths(),
            "updated_at": _utc_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return config


class BambuBedClearMemory:
    """Local Bambu post-ejection bed-clear evidence gate."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_payload()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_payload()
        if not isinstance(payload, dict):
            return self._default_payload()
        return self._normalize(payload)

    def save_from_payload(self, payload: dict[str, Any], *, printer_profile_id: str) -> dict[str, Any]:
        source = payload if isinstance(payload, dict) else {}
        existing = self.load()

        def _payload_string(key: str) -> str:
            if key in source:
                return str(source.get(key) or "")
            return str(existing.get(key) or "")

        record = self._normalize(
            {
                **existing,
                "printer_profile_id": str(printer_profile_id or ""),
                "remote_path": _payload_string("remote_path"),
                "subtask_name": _payload_string("subtask_name"),
                "source_artifact_path": _payload_string("source_artifact_path"),
                "source_artifact_sha256": _payload_string("source_artifact_sha256"),
                "patched_artifact_path": _payload_string("patched_artifact_path"),
                "patched_artifact_sha256": _payload_string("patched_artifact_sha256"),
                "manifest_path": _payload_string("manifest_path"),
                "publish_sequence_id": _payload_string("publish_sequence_id"),
                "publish_topic": _payload_string("publish_topic"),
                "post_publish_status": _payload_string("post_publish_status"),
                "bed_clear_required": _as_bool(
                    source.get("bed_clear_required"),
                    _as_bool(existing.get("bed_clear_required"), False),
                ),
                "bed_clear_verified": _as_bool(
                    source.get("bed_clear_verified"),
                    _as_bool(existing.get("bed_clear_verified"), False),
                ),
                "verification_method": _payload_string("verification_method") or "operator",
                "camera_snapshot_path": _payload_string("camera_snapshot_path"),
                "updated_at": _utc_now(),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return record

    def _default_payload(self) -> dict[str, Any]:
        return self._normalize({"schema": "bambu_bed_clear_evidence.v1"})

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = _as_bool(payload.get("bed_clear_required"), False)
        verified = _as_bool(payload.get("bed_clear_verified"), not required)
        blocking_code = "BAMBU_POST_EJECT_BED_NOT_CLEAR" if required and not verified else ""
        return {
            "schema": "bambu_bed_clear_evidence.v1",
            "printer_profile_id": str(payload.get("printer_profile_id") or ""),
            "remote_path": str(payload.get("remote_path") or ""),
            "subtask_name": str(payload.get("subtask_name") or ""),
            "source_artifact_path": str(payload.get("source_artifact_path") or ""),
            "source_artifact_sha256": str(payload.get("source_artifact_sha256") or ""),
            "patched_artifact_path": str(payload.get("patched_artifact_path") or ""),
            "patched_artifact_sha256": str(payload.get("patched_artifact_sha256") or ""),
            "manifest_path": str(payload.get("manifest_path") or ""),
            "publish_sequence_id": str(payload.get("publish_sequence_id") or ""),
            "publish_topic": str(payload.get("publish_topic") or ""),
            "post_publish_status": str(payload.get("post_publish_status") or ""),
            "bed_clear_required": required,
            "bed_clear_verified": verified,
            "verification_method": str(payload.get("verification_method") or ""),
            "camera_snapshot_path": str(payload.get("camera_snapshot_path") or ""),
            "blocking_code": blocking_code,
            "updated_at": str(payload.get("updated_at") or ""),
        }


class PrinterFleetMemory:
    """Local selected-printer memory for explicit operator profile selection."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def active_profile_id(self, *, default_profile_id: str, profiles: dict[str, PrinterProfile]) -> tuple[str, str]:
        payload = self.load()
        profile_id = str(payload.get("active_profile_id") or "").strip()
        if profile_id and profile_id in profiles and profiles[profile_id].enabled:
            return profile_id, "fleet_memory_profile_id"
        return default_profile_id, "default_profile"

    def save(self, profile_id: str, *, profiles: dict[str, PrinterProfile]) -> None:
        clean = str(profile_id or "").strip()
        if clean not in profiles:
            raise KeyError(f"Unknown printer profile: {clean}")
        if not profiles[clean].enabled:
            raise ValueError(f"Printer profile is disabled: {clean}")
        record = {
            "schema": "printer_fleet_selection.v1",
            "active_profile_id": clean,
            "updated_at": _utc_now(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


class BambuLiveProbe:
    """Live preflight helper that only proves network reachability; it does not start prints."""

    def __init__(self, config: BambuBridgeConfig) -> None:
        self.config = config

    def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        try:
            raw_sock = socket.create_connection((host, int(port)), timeout=float(timeout_sec))
            try:
                # Bambu LAN services use printer-local TLS certificates. Public CA
                # verification fails even when the printer is reachable and the
                # access code is valid, so this probe only verifies encrypted LAN
                # connectivity, not public certificate trust.
                ctx = ssl._create_unverified_context()
                with ctx.wrap_socket(raw_sock, server_hostname=host):
                    pass
            except ssl.SSLError:
                raw_sock.close()
                return {
                    "ok": False,
                    "failure_code": "BAMBU_TLS_HANDSHAKE_FAILED",
                    "port": int(port),
                    "checked_at": started.isoformat(),
                }
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "failure_code": "BAMBU_PORT_UNREACHABLE",
                "port": int(port),
                "error": str(exc),
                "checked_at": started.isoformat(),
            }
        return {"ok": True, "port": int(port), "checked_at": started.isoformat()}


class BambuVideoStreamClient:
    """Probe Bambu LAN video ports and report whether a local proxy can be started."""

    def __init__(self, config: BambuBridgeConfig) -> None:
        self.config = config

    def probe_live_view(
        self,
        *,
        host: str,
        access_code: str,
        reported_rtsp_url: str = "",
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        checked_at = _utc_now()
        if not self.config.video.enabled:
            return {
                "ok": False,
                "status": "disabled",
                "failure_code": "BAMBU_VIDEO_DISABLED",
                "stream_kind": "unavailable",
                "host": str(host or ""),
                "port": None,
                "stream_url": "",
                "proxy_ready": False,
                "proxy_url": "",
                "blockers": ["BAMBU_VIDEO_DISABLED"],
                "checked_at": checked_at,
            }
        if not host or not access_code:
            return {
                "ok": False,
                "status": "blocked",
                "failure_code": "BAMBU_VIDEO_CONNECTION_INFO_INCOMPLETE",
                "stream_kind": "unavailable",
                "host": str(host or ""),
                "port": None,
                "stream_url": "",
                "proxy_ready": False,
                "proxy_url": "",
                "blockers": ["BAMBU_VIDEO_CONNECTION_INFO_INCOMPLETE"],
                "checked_at": checked_at,
            }

        timeout = float(timeout_sec if timeout_sec is not None else self.config.video.timeout_sec)
        rtsps_probe = self._probe_tcp_port(host, self.config.video.rtsps_port, timeout)
        jpeg_probe = {"ok": False, "port": self.config.video.jpeg_stream_port, "error": ""}
        selected_probe = rtsps_probe
        stream_kind = "rtsps"
        if not rtsps_probe.get("ok"):
            jpeg_probe = self._probe_tcp_port(host, self.config.video.jpeg_stream_port, timeout)
            selected_probe = jpeg_probe
            stream_kind = "jpeg" if jpeg_probe.get("ok") else "unavailable"

        reachable = bool(selected_probe.get("ok"))
        ffmpeg_path = shutil.which("ffmpeg")
        proxy_ready = bool(reachable and ffmpeg_path)
        stream_url = self._stream_url(host=host, stream_kind=stream_kind, reported_rtsp_url=reported_rtsp_url)
        blockers: list[str] = []
        if not reachable:
            blockers.append("BAMBU_VIDEO_PORT_UNREACHABLE")
        elif not ffmpeg_path:
            blockers.append("BAMBU_VIDEO_PROXY_FFMPEG_MISSING")
        return {
            "ok": reachable,
            "status": "streaming_candidate" if reachable else "blocked",
            "failure_code": "" if reachable else "BAMBU_VIDEO_PORT_UNREACHABLE",
            "stream_kind": stream_kind,
            "host": str(host),
            "port": selected_probe.get("port") if reachable else None,
            "stream_url": stream_url if reachable else "",
            "proxy_ready": proxy_ready,
            "proxy_url": "/api/printer/video-stream.mjpeg" if proxy_ready else "",
            "snapshot_url": "/api/printer/video-frame.jpg" if proxy_ready else "",
            "ffmpeg_available": bool(ffmpeg_path),
            "blockers": blockers,
            "probes": {"rtsps": rtsps_probe, "jpeg": jpeg_probe},
            "checked_at": checked_at,
        }

    def _probe_tcp_port(self, host: str, port: int, timeout_sec: float) -> dict[str, Any]:
        try:
            sock = socket.create_connection((host, int(port)), timeout=float(timeout_sec))
            try:
                sock.close()
            except Exception:
                pass
            return {"ok": True, "port": int(port), "checked_at": _utc_now()}
        except (OSError, ValueError) as exc:
            return {"ok": False, "port": int(port), "error": str(exc), "checked_at": _utc_now()}

    def _stream_url(self, *, host: str, stream_kind: str, reported_rtsp_url: str) -> str:
        if stream_kind == "rtsps":
            reported = str(reported_rtsp_url or "").strip()
            return reported if reported.startswith("rtsps://") else f"rtsps://{host}:{self.config.video.rtsps_port}/streaming/live/1"
        if stream_kind == "jpeg":
            return f"http://{host}:{self.config.video.jpeg_stream_port}/?action=stream"
        return ""


def _number_or_none(value: Any) -> float | int | None:
    try:
        if value in {"", None}:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _first_number(*values: Any) -> float | int | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _normalize_ams_slots(ams: Any) -> list[dict[str, Any]]:
    if not isinstance(ams, dict):
        return []
    slots: list[dict[str, Any]] = []
    for ams_unit in ams.get("ams", []) if isinstance(ams.get("ams"), list) else []:
        if not isinstance(ams_unit, dict):
            continue
        unit_id = str(ams_unit.get("id", ""))
        unit_temp = _number_or_none(ams_unit.get("temp"))
        unit_humidity = str(ams_unit.get("humidity") or "")
        unit_humidity_raw = str(ams_unit.get("humidity_raw") or "")
        for tray in ams_unit.get("tray", []) if isinstance(ams_unit.get("tray"), list) else []:
            if not isinstance(tray, dict):
                continue
            slots.append(
                {
                    "ams_id": unit_id,
                    "tray_id": str(tray.get("id", "")),
                    "tray_type": str(tray.get("tray_type") or ""),
                    "tray_sub_brands": str(tray.get("tray_sub_brands") or ""),
                    "tray_color": str(tray.get("tray_color") or ""),
                    "remain_percent": _number_or_none(tray.get("remain")),
                    "state": tray.get("state"),
                    "ams_temp_c": unit_temp,
                    "ams_humidity": unit_humidity,
                    "ams_humidity_raw": unit_humidity_raw,
                }
            )
    return slots


def _normalize_ams_units(ams: Any) -> list[dict[str, Any]]:
    if not isinstance(ams, dict):
        return []
    units: list[dict[str, Any]] = []
    for ams_unit in ams.get("ams", []) if isinstance(ams.get("ams"), list) else []:
        if not isinstance(ams_unit, dict):
            continue
        trays = ams_unit.get("tray") if isinstance(ams_unit.get("tray"), list) else []
        units.append(
            {
                "id": str(ams_unit.get("id", "")),
                "temp_c": _number_or_none(ams_unit.get("temp")),
                "humidity": str(ams_unit.get("humidity") or ""),
                "humidity_raw": str(ams_unit.get("humidity_raw") or ""),
                "tray_count": len(trays),
            }
        )
    return units


def _normalize_nozzles(device: dict[str, Any]) -> list[dict[str, Any]]:
    nozzle = device.get("nozzle") if isinstance(device.get("nozzle"), dict) else {}
    raw_info = nozzle.get("info") if isinstance(nozzle.get("info"), list) else []
    nozzles: list[dict[str, Any]] = []
    for item in raw_info:
        if not isinstance(item, dict):
            continue
        nozzles.append(
            {
                "id": item.get("id"),
                "diameter_mm": _number_or_none(item.get("diameter")),
                "type": str(item.get("type") or ""),
                "wear": _number_or_none(item.get("wear")),
                "state": item.get("stat"),
            }
        )
    return nozzles


def _normalize_extruders(device: dict[str, Any]) -> list[dict[str, Any]]:
    extruder = device.get("extruder") if isinstance(device.get("extruder"), dict) else {}
    raw_info = extruder.get("info") if isinstance(extruder.get("info"), list) else []
    extruders: list[dict[str, Any]] = []
    for item in raw_info:
        if not isinstance(item, dict):
            continue
        extruders.append(
            {
                "id": item.get("id"),
                "temp_c": _number_or_none(item.get("temp")),
                "state": item.get("stat"),
                "z_bias": _number_or_none(item.get("z_bias")),
            }
        )
    return extruders


def _decode_bambu_ipv4(value: Any) -> str:
    """Decode Bambu's little-endian integer IPv4 values from MQTT reports."""
    number = _number_or_none(value)
    if number is None or int(number) == 0:
        return ""
    try:
        return socket.inet_ntoa(int(number).to_bytes(4, byteorder="little", signed=False))
    except (OverflowError, OSError, ValueError):
        return ""


def _normalize_network(net: Any) -> dict[str, Any]:
    if not isinstance(net, dict):
        return {"conf": None, "interfaces": []}
    interfaces: list[dict[str, Any]] = []
    for item in net.get("info", []) if isinstance(net.get("info"), list) else []:
        if not isinstance(item, dict):
            continue
        raw_ip = _number_or_none(item.get("ip"))
        raw_mask = _number_or_none(item.get("mask"))
        if raw_ip in {None, 0} and raw_mask in {None, 0}:
            continue
        interfaces.append(
            {
                "ip": _decode_bambu_ipv4(raw_ip),
                "mask": _decode_bambu_ipv4(raw_mask),
                "raw_ip": raw_ip,
                "raw_mask": raw_mask,
            }
        )
    return {"conf": net.get("conf"), "interfaces": interfaces}


def _safe_command_remote_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw.startswith(("file://", "http://", "https://", "ftp://")):
        return raw
    parts = [part for part in raw.strip("/").split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _http_url_is_printer_reachable_candidate(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return True
    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_loopback or ip.is_unspecified)


def _is_http_artifact_url(value: str) -> bool:
    return urlparse(str(value or "").strip()).scheme in {"http", "https"}


def _remote_path_for_suffix_check(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme:
        return parsed.path
    return str(value or "")


def _safe_bambu_subtask_name(value: str, fallback_remote: str) -> str:
    candidate = str(value or "").strip() or Path(_remote_path_for_suffix_check(fallback_remote)).stem
    if not candidate:
        return ""
    if "/" in candidate or "\\" in candidate:
        return ""
    if any(ord(char) < 32 for char in candidate):
        return ""
    return candidate[:128]


def build_bambu_project_file_command_draft(
    *,
    serial: str,
    remote_path: str,
    subtask_name: str = "",
    plate_id: int = 1,
    use_ams: bool = False,
    ams_mapping: list[int] | None = None,
    timelapse: bool = False,
    bed_leveling: bool = False,
    flow_cali: bool = False,
    vibration_cali: bool = False,
    layer_inspect: bool = False,
) -> dict[str, Any]:
    """Build a guarded Bambu MQTT project_file command draft without publishing it."""
    cleaned_serial = str(serial or "").strip()
    cleaned_remote = _safe_command_remote_path(remote_path)
    if not cleaned_remote:
        return {
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_REMOTE_PATH_REQUIRED",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    if not _http_url_is_printer_reachable_candidate(cleaned_remote):
        return {
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_HTTP_URL_NOT_PRINTER_REACHABLE",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    if not _remote_path_for_suffix_check(cleaned_remote).lower().endswith(".gcode.3mf"):
        return {
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
            "message": "Bambu project_file requires a plate-sliced .gcode.3mf artifact so param can match Metadata/plate_#.gcode.",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    if use_ams and ams_mapping is None:
        return {
            "ok": False,
            "failure_code": "BAMBU_AMS_MAPPING_REQUIRED",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    if ams_mapping is not None:
        try:
            normalized_mapping = [int(item) for item in ams_mapping]
        except Exception:
            normalized_mapping = []
        if len(normalized_mapping) != 5 or any(item < -1 or item > 3 for item in normalized_mapping):
            return {
                "ok": False,
                "failure_code": "BAMBU_AMS_MAPPING_INVALID",
                "will_publish": False,
                "start_enabled": False,
                "requires_guardian": True,
            }
    else:
        normalized_mapping = None
    if cleaned_remote.startswith(("file://", "http://", "https://", "ftp://")):
        url = cleaned_remote
    else:
        url = f"file:///{cleaned_remote}"
    try:
        safe_plate_id = int(plate_id)
    except (TypeError, ValueError):
        safe_plate_id = 0
    if safe_plate_id < 1:
        return {
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
            "message": "Bambu project_file plate_id must be >= 1 so param can match Metadata/plate_#.gcode.",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    safe_subtask_name = _safe_bambu_subtask_name(subtask_name, cleaned_remote)
    if not safe_subtask_name:
        return {
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_SUBTASK_NAME_INVALID",
            "message": "Bambu project_file subtask_name must be a display name, not a path or control-string.",
            "will_publish": False,
            "start_enabled": False,
            "requires_guardian": True,
        }
    payload: dict[str, Any] = {
        "print": {
            "command": "project_file",
            "sequence_id": str(uuid.uuid4().int % 9000 + 1000),
            "url": url,
            "param": f"Metadata/plate_{safe_plate_id}.gcode",
            "subtask_name": safe_subtask_name,
            "use_ams": bool(use_ams),
            "timelapse": bool(timelapse),
            "bed_leveling": bool(bed_leveling),
            "flow_cali": bool(flow_cali),
            "vibration_cali": bool(vibration_cali),
            "layer_inspect": bool(layer_inspect),
        }
    }
    if normalized_mapping is not None:
        payload["print"]["ams_mapping"] = normalized_mapping
    return {
        "ok": True,
        "schema": "bambu_project_file_command_draft.v1",
        "topic": f"device/{cleaned_serial}/request" if cleaned_serial else "",
        "payload": payload,
        "will_publish": False,
        "start_enabled": False,
        "requires_guardian": True,
        "guard_reason": "draft_only_until_upload_path_and_operator_approval_are_verified",
    }


def validate_bambu_project_file_local_artifact(local_path: str | Path, *, plate_id: int = 1) -> dict[str, Any]:
    """Verify a local .gcode.3mf contains the plate path used by project_file.param."""
    source = Path(str(local_path or "")).expanduser()
    try:
        source = source.resolve()
    except OSError:
        source = source.absolute()
    try:
        safe_plate_id = int(plate_id)
    except (TypeError, ValueError):
        safe_plate_id = 0
    expected_plate_path = f"Metadata/plate_{safe_plate_id}.gcode" if safe_plate_id >= 1 else ""
    base: dict[str, Any] = {
        "schema": "bambu_project_file_artifact_plate_validation.v1",
        "source_path": str(source),
        "plate_id": safe_plate_id,
        "expected_plate_path": expected_plate_path,
        "will_publish": False,
        "start_enabled": False,
    }
    if safe_plate_id < 1:
        return {
            **base,
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
            "message": "Bambu project_file plate_id must be >= 1 so param can match Metadata/plate_#.gcode.",
        }
    if not source.exists() or not source.is_file():
        return {
            **base,
            "ok": False,
            "failure_code": "BAMBU_LOCAL_ARTIFACT_NOT_FOUND",
            "message": "Local Bambu artifact path does not exist.",
        }
    if not source.name.lower().endswith(".gcode.3mf"):
        return {
            **base,
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
            "message": "Bambu project_file requires a local plate-sliced .gcode.3mf artifact.",
        }
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            plate_paths = sorted(name for name in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", name))
            if expected_plate_path not in names:
                return {
                    **base,
                    "ok": False,
                    "failure_code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
                    "available_plate_paths": plate_paths,
                    "message": "Local .gcode.3mf does not contain the plate G-code path required by MQTT project_file.param.",
                }
    except zipfile.BadZipFile:
        return {
            **base,
            "ok": False,
            "failure_code": "BAMBU_PROJECT_FILE_ARTIFACT_INVALID",
            "message": "Local Bambu artifact is not a valid .gcode.3mf zip container.",
        }
    return {
        **base,
        "ok": True,
        "failure_code": "",
        "available_plate_paths": plate_paths,
        "source_plate_path": expected_plate_path,
        "message": "Local Bambu artifact plate path matches MQTT project_file.param.",
    }


def normalize_bambu_report(report: dict[str, Any], *, received_at: str = "") -> dict[str, Any]:
    """Map Bambu MQTT report JSON into the UI's stable device-screen fields."""
    root = report if isinstance(report, dict) else {}
    print_data = root.get("print") if isinstance(root.get("print"), dict) else root
    print_2d = print_data.get("2D") if isinstance(print_data.get("2D"), dict) else {}
    print_3d = print_data.get("3D") if isinstance(print_data.get("3D"), dict) else {}
    device = print_data.get("device") if isinstance(print_data.get("device"), dict) else {}
    job = print_data.get("job") if isinstance(print_data.get("job"), dict) else {}
    ipcam = print_data.get("ipcam") if isinstance(print_data.get("ipcam"), dict) else {}
    upload = print_data.get("upload") if isinstance(print_data.get("upload"), dict) else {}
    hms = print_data.get("hms") if isinstance(print_data.get("hms"), list) else []
    care = print_data.get("care") if isinstance(print_data.get("care"), list) else []
    xcam = print_data.get("xcam") if isinstance(print_data.get("xcam"), dict) else {}
    lights = print_data.get("lights_report") if isinstance(print_data.get("lights_report"), list) else []
    state = str(print_data.get("gcode_state") or print_data.get("stg_cur") or "UNKNOWN")
    return {
        "state": state,
        "job": {
            "file_name": str(print_data.get("subtask_name") or print_data.get("gcode_file") or ""),
            "progress_percent": _first_number(print_data.get("mc_percent"), print_data.get("percent")),
            "layer": _first_number(print_data.get("layer_num"), print_3d.get("layer_num")),
            "total_layers": _first_number(print_data.get("total_layer_num"), print_3d.get("total_layer_num")),
            "remaining_sec": _first_number(print_data.get("mc_remaining_time"), print_data.get("remain_time")),
            "prepare_percent": _first_number(print_data.get("gcode_file_prepare_percent"), print_data.get("prepare_per")),
            "task_id": str(print_data.get("task_id") or ""),
            "project_id": str(print_data.get("project_id") or ""),
            "model_id": str(print_data.get("model_id") or ""),
            "print_type": str(print_data.get("print_type") or ""),
            "plate_id": _number_or_none(print_data.get("plate_id")),
            "plate_index": _number_or_none(print_data.get("plate_idx")),
            "plate_count": _number_or_none(print_data.get("plate_cnt")),
            "job_state": job.get("job_state"),
            "cur_stage": job.get("cur_stage") if isinstance(job.get("cur_stage"), dict) else {},
            "stage_count": len(job.get("stage")) if isinstance(job.get("stage"), list) else 0,
        },
        "temperatures": {
            "nozzle_c": _number_or_none(print_data.get("nozzle_temper")),
            "nozzle_target_c": _number_or_none(print_data.get("nozzle_target_temper")),
            "bed_c": _first_number(print_data.get("bed_temper"), device.get("bed_temp")),
            "bed_target_c": _number_or_none(print_data.get("bed_target_temper")),
            "chamber_c": _first_number(
                print_data.get("chamber_temper"),
                (device.get("ctc") if isinstance(device.get("ctc"), dict) else {}).get("info", {}).get("temp")
                if isinstance((device.get("ctc") if isinstance(device.get("ctc"), dict) else {}).get("info"), dict)
                else None,
            ),
        },
        "fans": {
            "part_percent": _number_or_none(print_data.get("fan_gear")),
            "cooling_percent": _number_or_none(print_data.get("cooling_fan_speed")),
            "big_fan1_percent": _number_or_none(print_data.get("big_fan1_speed")),
            "big_fan2_percent": _number_or_none(print_data.get("big_fan2_speed")),
            "heatbreak_percent": _number_or_none(print_data.get("heatbreak_fan_speed")),
            "aux_part_fan_on": _as_bool(print_data.get("aux_part_fan"), False),
        },
        "camera": {
            "liveview_preview": bool(ipcam.get("liveview_preview", False)),
            "resolution": str(ipcam.get("resolution") or ""),
            "recording": str(ipcam.get("ipcam_record") or ""),
            "mode_bits": ipcam.get("mode_bits"),
            "rtsp_url": str(ipcam.get("rtsp_url") or ""),
            "brtc_service": str(ipcam.get("brtc_service") or ""),
            "tutk_server": str(ipcam.get("tutk_server") or ""),
        },
        "upload": {
            "status": str(upload.get("status") or upload.get("state") or ""),
            "progress": _number_or_none(upload.get("progress")),
            "message": str(upload.get("message") or ""),
        },
        "storage": {
            "sdcard_available": print_data.get("sdcard") if isinstance(print_data.get("sdcard"), bool) else None,
            "file": str(print_data.get("file") or ""),
            "gcode_file": str(print_data.get("gcode_file") or ""),
            "internal_free_kb": _number_or_none(ipcam.get("tl_internal_free_kb")),
            "internal_total_kb": _number_or_none(ipcam.get("tl_internal_total_kb")),
            "external_free_kb": _number_or_none(ipcam.get("tl_external_free_kb")),
            "external_total_kb": _number_or_none(ipcam.get("tl_external_total_kb")),
            "timelapse_store_path_type": _number_or_none(ipcam.get("tl_store_path_type")),
            "timelapse_store_hpd_type": _number_or_none(ipcam.get("tl_store_hpd_type")),
        },
        "health": {
            "hms_count": len(hms),
            "hms": hms[:8],
            "care": care[:8],
            "error": str(print_data.get("err") or ""),
            "err2": print_data.get("err2") if isinstance(print_data.get("err2"), dict) else {},
            "fail_reason": str(print_data.get("fail_reason") or ""),
        },
        "diagnostics": {
            "wifi_signal": str(print_data.get("wifi_signal") or ""),
            "home_flag": print_data.get("home_flag"),
            "hw_switch_state": print_data.get("hw_switch_state"),
            "online": print_data.get("online") if isinstance(print_data.get("online"), dict) else {},
        },
        "network": _normalize_network(print_data.get("net")),
        "queue": {
            "enabled": _number_or_none(print_data.get("queue")),
            "status": _number_or_none(print_data.get("queue_sts")),
            "number": _number_or_none(print_data.get("queue_number")),
            "total": _number_or_none(print_data.get("queue_total")),
            "estimated_sec": _number_or_none(print_data.get("queue_est")),
        },
        "control": {
            "mc_action": _number_or_none(print_data.get("mc_action")),
            "mc_stage": _number_or_none(print_data.get("mc_stage")),
            "mc_print_stage": _number_or_none(print_data.get("mc_print_stage")),
            "mc_print_sub_stage": _number_or_none(print_data.get("mc_print_sub_stage")),
            "mc_print_error_code": str(print_data.get("mc_print_error_code") or ""),
            "mc_error": _number_or_none(print_data.get("mc_err")),
            "print_real_action": _number_or_none(print_data.get("print_real_action")),
            "print_gcode_action": _number_or_none(print_data.get("print_gcode_action")),
            "print_error": _number_or_none(print_data.get("print_error")),
            "state_code": _number_or_none(print_data.get("state")),
            "stat": str(print_data.get("stat") or ""),
            "sequence_id": str(print_data.get("sequence_id") or ""),
        },
        "speed": {
            "level": _number_or_none(print_data.get("spd_lvl")),
            "magnitude_percent": _number_or_none(print_data.get("spd_mag")),
        },
        "monitoring": {
            "xcam": {
                "spaghetti_detector": bool(xcam.get("spaghetti_detector", False)),
                "first_layer_inspector": bool(xcam.get("first_layer_inspector", False)),
                "printing_monitor": bool(xcam.get("printing_monitor", False)),
                "print_halt": bool(xcam.get("print_halt", False)),
                "buildplate_marker_detector": bool(xcam.get("buildplate_marker_detector", False)),
                "halt_print_sensitivity": str(xcam.get("halt_print_sensitivity") or ""),
            },
            "xcam_status": str(print_data.get("xcam_status") or ""),
        },
        "device": {
            "type": device.get("type"),
            "bed_state": (device.get("bed") if isinstance(device.get("bed"), dict) else {}).get("state"),
            "plate": device.get("plate") if isinstance(device.get("plate"), dict) else {},
            "nozzles": _normalize_nozzles(device),
            "extruders": _normalize_extruders(device),
            "nozzle_exist_bits": (device.get("nozzle") if isinstance(device.get("nozzle"), dict) else {}).get("exist"),
            "active_nozzle_id": (device.get("nozzle") if isinstance(device.get("nozzle"), dict) else {}).get("src_id"),
            "target_nozzle_id": (device.get("nozzle") if isinstance(device.get("nozzle"), dict) else {}).get("tar_id"),
        },
        "modes": {
            "print_2d": {
                "makeable": print_2d.get("makeable"),
                "cond": print_2d.get("cond"),
                "material": print_2d.get("material") if isinstance(print_2d.get("material"), dict) else {},
            },
            "print_3d": {
                "enc_type": print_3d.get("enc_type"),
                "print_cali_option": print_3d.get("print_cali_option"),
                "ventobox": print_3d.get("ventobox") if isinstance(print_3d.get("ventobox"), dict) else {},
            },
        },
        "lights": lights[:8],
        "materials": {
            "slots": _normalize_ams_slots(print_data.get("ams")),
            "ams_units": _normalize_ams_units(print_data.get("ams")),
            "ams_exist_bits": (print_data.get("ams") if isinstance(print_data.get("ams"), dict) else {}).get("ams_exist_bits"),
            "tray_exist_bits": (print_data.get("ams") if isinstance(print_data.get("ams"), dict) else {}).get("tray_exist_bits"),
            "ams_status": _number_or_none(print_data.get("ams_status")),
            "ams_rfid_status": _number_or_none(print_data.get("ams_rfid_status")),
        },
        "raw_keys": sorted(str(key) for key in print_data.keys()),
        "received_at": received_at,
    }


class BambuMqttReportClient:
    """Read a single authenticated Bambu LAN MQTT report without issuing print commands."""

    def __init__(self, config: BambuBridgeConfig) -> None:
        self.config = config
        self._snapshot_cache: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}
        self._snapshot_cache_lock = threading.Lock()

    def read_snapshot(
        self,
        *,
        host: str,
        serial: str,
        username: str,
        access_code: str,
        timeout_sec: float,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if mqtt is None:
            return {"ok": False, "failure_code": "PAHO_MQTT_NOT_INSTALLED"}
        if not host or not serial or not access_code:
            return {"ok": False, "failure_code": "BAMBU_MQTT_CONNECTION_INFO_INCOMPLETE"}

        report_topic = self.config.mqtt.report_topic_template.format(serial=serial)
        request_topic = self.config.mqtt.request_topic_template.format(serial=serial)
        access_hash = hashlib.sha256(str(access_code).encode("utf-8")).hexdigest()[:16]
        cache_key = (str(host), str(serial), str(username or self.config.mqtt.username), access_hash)
        cache_ttl = max(0.0, float(getattr(self.config.mqtt, "snapshot_cache_ttl_sec", 0.0) or 0.0))
        if cache_ttl > 0 and not force_refresh:
            now = time.monotonic()
            with self._snapshot_cache_lock:
                cached = self._snapshot_cache.get(cache_key)
            if cached:
                cached_at, cached_result = cached
                age = now - cached_at
                if age <= cache_ttl:
                    result = copy.deepcopy(cached_result)
                    result["cache_status"] = "cache_hit"
                    result["cache_age_sec"] = round(age, 3)
                    return result
        result: dict[str, Any] = {"ok": False, "topic": report_topic}
        event = threading.Event()

        client_id = f"atr-bambu-{uuid.uuid4().hex[:10]}"
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:  # pragma: no cover - paho<2 compatibility.
            client = mqtt.Client(client_id=client_id)

        def on_connect(client, userdata, flags, reason_code, properties=None):  # noqa: ANN001
            code = int(reason_code.value) if hasattr(reason_code, "value") else int(reason_code)
            result["connack"] = code
            if code != 0:
                result["failure_code"] = f"BAMBU_MQTT_CONNACK_{code}"
                event.set()
                return
            client.subscribe(report_topic, qos=0)
            pushall = {"pushing": {"sequence_id": "1", "command": "pushall"}, "user_id": "atr"}
            client.publish(request_topic, json.dumps(pushall), qos=0)

        def on_message(client, userdata, msg):  # noqa: ANN001
            try:
                payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
            except Exception as exc:
                result.update({"ok": False, "failure_code": "BAMBU_MQTT_REPORT_PARSE_FAILED", "error": str(exc)})
                event.set()
                return
            result.update({"ok": True, "topic": msg.topic, "report": payload, "received_at": _utc_now()})
            event.set()

        client.on_connect = on_connect
        client.on_message = on_message
        client.username_pw_set(username, access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        try:
            client.connect(host, self.config.mqtt.port, keepalive=30)
            client.loop_start()
            if not event.wait(float(timeout_sec)):
                result.update({"ok": False, "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT"})
        except Exception as exc:
            result.update({"ok": False, "failure_code": "BAMBU_MQTT_CONNECT_FAILED", "error": str(exc)})
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        if result.get("ok"):
            result["cache_status"] = "refreshed"
            if cache_ttl > 0:
                with self._snapshot_cache_lock:
                    self._snapshot_cache[cache_key] = (time.monotonic(), copy.deepcopy(result))
        return result

    def publish_project_file_command(
        self,
        *,
        host: str,
        serial: str,
        username: str,
        access_code: str,
        topic: str,
        payload: dict[str, Any],
        timeout_sec: float,
    ) -> dict[str, Any]:
        """Publish a Guardian-approved Bambu project_file command over LAN MQTT."""
        if mqtt is None:
            return {"ok": False, "failure_code": "PAHO_MQTT_NOT_INSTALLED", "will_publish": False, "published": False}
        if not host or not serial or not access_code:
            return {
                "ok": False,
                "failure_code": "BAMBU_MQTT_CONNECTION_INFO_INCOMPLETE",
                "will_publish": False,
                "published": False,
            }
        expected_topic = self.config.mqtt.request_topic_template.format(serial=serial)
        if str(topic or "") != expected_topic:
            return {
                "ok": False,
                "failure_code": "BAMBU_MQTT_TOPIC_MISMATCH",
                "expected_topic": expected_topic,
                "topic": str(topic or ""),
                "will_publish": False,
                "published": False,
            }
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        if print_payload.get("command") != "project_file":
            return {
                "ok": False,
                "failure_code": "BAMBU_MQTT_UNSUPPORTED_COMMAND",
                "topic": expected_topic,
                "will_publish": False,
                "published": False,
            }

        result: dict[str, Any] = {
            "ok": False,
            "tool": "printer.bambu.mqtt_publish",
            "topic": expected_topic,
            "status": "pending",
            "will_publish": True,
            "published": False,
        }
        event = threading.Event()
        published_mid: dict[str, int | None] = {"value": None}
        client_id = f"atr-bambu-publish-{uuid.uuid4().hex[:10]}"
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:  # pragma: no cover - paho<2 compatibility.
            client = mqtt.Client(client_id=client_id)

        def on_connect(client, userdata, flags, reason_code, properties=None):  # noqa: ANN001
            code = int(reason_code.value) if hasattr(reason_code, "value") else int(reason_code)
            result["connack"] = code
            if code != 0:
                result.update({"ok": False, "status": "connack_failed", "failure_code": f"BAMBU_MQTT_CONNACK_{code}"})
                event.set()
                return
            try:
                info = client.publish(expected_topic, json.dumps(payload), qos=1)
                rc = int(getattr(info, "rc", 0) or 0)
                if rc != 0:
                    result.update({"ok": False, "status": "publish_failed", "failure_code": f"BAMBU_MQTT_PUBLISH_RC_{rc}"})
                else:
                    published_mid["value"] = getattr(info, "mid", None)
                    if published_mid["value"] is None:
                        result.update(
                            {
                                "ok": True,
                                "status": "published",
                                "published": True,
                                "published_at": _utc_now(),
                                "sequence_id": str(print_payload.get("sequence_id") or ""),
                                "command": "project_file",
                                "url": str(print_payload.get("url") or ""),
                            }
                        )
                        event.set()
            except Exception as exc:
                result.update({"ok": False, "status": "publish_failed", "failure_code": "BAMBU_MQTT_PUBLISH_FAILED", "error": str(exc)})
            finally:
                if result.get("status") == "publish_failed":
                    event.set()

        def on_publish(client, userdata, mid, *args):  # noqa: ANN001
            expected_mid = published_mid.get("value")
            if expected_mid is not None and int(mid) != int(expected_mid):
                return
            result.update(
                {
                    "ok": True,
                    "status": "published",
                    "published": True,
                    "published_at": _utc_now(),
                    "sequence_id": str(print_payload.get("sequence_id") or ""),
                    "command": "project_file",
                    "url": str(print_payload.get("url") or ""),
                }
            )
            event.set()

        client.on_connect = on_connect
        client.on_publish = on_publish
        client.username_pw_set(username or self.config.mqtt.username, access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        try:
            client.connect(host, self.config.mqtt.port, keepalive=30)
            client.loop_start()
            if not event.wait(float(timeout_sec)):
                result.update({"ok": False, "status": "timeout", "failure_code": "BAMBU_MQTT_PUBLISH_TIMEOUT"})
        except Exception as exc:
            result.update({"ok": False, "status": "connect_failed", "failure_code": "BAMBU_MQTT_CONNECT_FAILED", "error": str(exc)})
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        return result

    def publish_gcode_line_command(
        self,
        *,
        host: str,
        serial: str,
        username: str,
        access_code: str,
        topic: str,
        gcode: str,
        timeout_sec: float,
    ) -> dict[str, Any]:
        """Publish a guarded Bambu gcode_line command over LAN MQTT."""
        if mqtt is None:
            return {"ok": False, "failure_code": "PAHO_MQTT_NOT_INSTALLED", "will_publish": False, "published": False}
        if not host or not serial or not access_code:
            return {
                "ok": False,
                "failure_code": "BAMBU_MQTT_CONNECTION_INFO_INCOMPLETE",
                "will_publish": False,
                "published": False,
            }
        expected_topic = self.config.mqtt.request_topic_template.format(serial=serial)
        if str(topic or "") != expected_topic:
            return {
                "ok": False,
                "failure_code": "BAMBU_MQTT_TOPIC_MISMATCH",
                "expected_topic": expected_topic,
                "topic": str(topic or ""),
                "will_publish": False,
                "published": False,
            }
        clean_gcode = str(gcode or "").strip()
        if not clean_gcode:
            return {
                "ok": False,
                "failure_code": "BAMBU_GCODE_LINE_EMPTY",
                "topic": expected_topic,
                "will_publish": False,
                "published": False,
            }
        param = clean_gcode.rstrip() + "\n"
        sequence_id = str(uuid.uuid4().int % 9000 + 1000)
        payload = {"print": {"sequence_id": sequence_id, "command": "gcode_line", "param": param}}
        result: dict[str, Any] = {
            "ok": False,
            "tool": "printer.bambu.mqtt_gcode_line",
            "topic": expected_topic,
            "status": "pending",
            "will_publish": True,
            "published": False,
            "payload": payload,
        }
        event = threading.Event()
        published_mid: dict[str, int | None] = {"value": None}
        client_id = f"atr-bambu-gcode-{uuid.uuid4().hex[:10]}"
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:  # pragma: no cover - paho<2 compatibility.
            client = mqtt.Client(client_id=client_id)

        def on_connect(client, userdata, flags, reason_code, properties=None):  # noqa: ANN001
            code = int(reason_code.value) if hasattr(reason_code, "value") else int(reason_code)
            result["connack"] = code
            if code != 0:
                result.update({"ok": False, "status": "connack_failed", "failure_code": f"BAMBU_MQTT_CONNACK_{code}"})
                event.set()
                return
            try:
                info = client.publish(expected_topic, json.dumps(payload), qos=1)
                rc = int(getattr(info, "rc", 0) or 0)
                if rc != 0:
                    result.update({"ok": False, "status": "publish_failed", "failure_code": f"BAMBU_MQTT_PUBLISH_RC_{rc}"})
                    event.set()
                else:
                    published_mid["value"] = getattr(info, "mid", None)
                    if published_mid["value"] is None:
                        result.update(
                            {
                                "ok": True,
                                "status": "published",
                                "published": True,
                                "published_at": _utc_now(),
                                "sequence_id": sequence_id,
                                "command": "gcode_line",
                                "gcode_line_count": len(param.splitlines()),
                            }
                        )
                        event.set()
            except Exception as exc:
                result.update({"ok": False, "status": "publish_failed", "failure_code": "BAMBU_MQTT_PUBLISH_FAILED", "error": str(exc)})
                event.set()

        def on_publish(client, userdata, mid, *args):  # noqa: ANN001
            expected_mid = published_mid.get("value")
            if expected_mid is not None and int(mid) != int(expected_mid):
                return
            result.update(
                {
                    "ok": True,
                    "status": "published",
                    "published": True,
                    "published_at": _utc_now(),
                    "sequence_id": sequence_id,
                    "command": "gcode_line",
                    "gcode_line_count": len(param.splitlines()),
                }
            )
            event.set()

        client.on_connect = on_connect
        client.on_publish = on_publish
        client.username_pw_set(username or self.config.mqtt.username, access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        try:
            client.connect(host, self.config.mqtt.port, keepalive=30)
            client.loop_start()
            if not event.wait(float(timeout_sec)):
                result.update({"ok": False, "status": "timeout", "failure_code": "BAMBU_MQTT_PUBLISH_TIMEOUT"})
        except Exception as exc:
            result.update({"ok": False, "status": "connect_failed", "failure_code": "BAMBU_MQTT_CONNECT_FAILED", "error": str(exc)})
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        return result


class _ImplicitFTP_TLS(FTP_TLS):
    """Implicit FTPS client for Bambu LAN storage on port 990."""

    def connect(self, host: str = "", port: int = 0, timeout: float | None = -999, source_address=None):  # type: ignore[override]
        if host:
            self.host = host
        if port > 0:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        if self.timeout is not None and not self.timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        if source_address is not None:
            self.source_address = source_address
        sys.audit("ftplib.connect", self, self.host, self.port)
        raw_sock = socket.create_connection((self.host, self.port), self.timeout, source_address=self.source_address)
        self.sock = self.context.wrap_socket(raw_sock, server_hostname=self.host)
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):  # noqa: ANN001
        conn, size = super(FTP_TLS, self).ntransfercmd(cmd, rest)
        if self._prot_p:
            session = getattr(getattr(self, "sock", None), "session", None)
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=session)
        return conn, size


class BambuFtpsClient:
    """Probe Bambu implicit-FTPS storage without uploading or deleting files."""

    def __init__(self, config: BambuBridgeConfig) -> None:
        self.config = config

    def probe_storage(
        self,
        *,
        host: str,
        username: str,
        access_code: str,
        timeout_sec: float,
        write_probe: bool = False,
    ) -> dict[str, Any]:
        if not host or not access_code:
            return {"ok": False, "failure_code": "BAMBU_FTPS_CONNECTION_INFO_INCOMPLETE"}
        client = _ImplicitFTP_TLS(context=ssl._create_unverified_context())
        try:
            client.connect(host, 990, timeout=float(timeout_sec))
            client.login(username or "bblp", access_code)
            client.prot_p()
            entries = client.nlst()
            if write_probe:
                marker_name = f"atr-ftps-write-probe-{uuid.uuid4().hex[:8]}.txt"
                try:
                    client.storbinary(f"STOR {marker_name}", io.BytesIO(b"ATR write probe\n"))
                    client.delete(marker_name)
                except Exception as exc:
                    return {
                        "ok": False,
                        "read_ok": True,
                        "storage": "ftps",
                        "entries_sample": entries[:8],
                        "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                        "error": str(exc),
                        "checked_at": _utc_now(),
                    }
            return {
                "ok": True,
                "read_ok": True,
                "write_ok": bool(write_probe),
                "storage": "ftps",
                "entries_sample": entries[:8],
                "checked_at": _utc_now(),
            }
        except Exception as exc:
            return self._classified_ftps_failure(
                exc,
                host=host,
                timeout_sec=timeout_sec,
                default_code="BAMBU_FTPS_PROBE_FAILED",
            )
        finally:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass

    def probe_upload_paths(
        self,
        *,
        host: str,
        username: str,
        access_code: str,
        timeout_sec: float,
        candidate_dirs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Try safe marker write/delete against candidate Bambu storage locations."""
        if not host or not access_code:
            return {"ok": False, "failure_code": "BAMBU_FTPS_CONNECTION_INFO_INCOMPLETE", "candidates": []}
        dirs = candidate_dirs or ["", "cache", "sdcard", "Metadata", "data/Metadata"]
        marker = "atr-ftps-path-probe.txt"
        payload = b"ATR Bambu upload path probe\n"
        client = _ImplicitFTP_TLS(context=ssl._create_unverified_context())
        candidates: list[dict[str, Any]] = []
        try:
            client.connect(host, 990, timeout=float(timeout_sec))
            client.login(username or "bblp", access_code)
            client.prot_p()
            try:
                root_entries = client.nlst()
            except Exception:
                root_entries = []
            for raw_dir in dirs:
                remote_dir = self._sanitize_probe_dir(raw_dir)
                remote_path = f"{remote_dir}/{marker}" if remote_dir else marker
                item: dict[str, Any] = {"remote_dir": remote_dir, "remote_path": remote_path, "ok": False}
                try:
                    self._cwd_remote_dir(client, remote_dir)
                    client.storbinary(f"STOR {marker}", io.BytesIO(payload))
                    client.delete(marker)
                    item.update({"ok": True, "status": "write_delete_ok"})
                except Exception as exc:
                    item.update({"ok": False, "failure_code": "BAMBU_FTPS_WRITE_FAILED", "error": str(exc)})
                finally:
                    self._reset_cwd(client)
                candidates.append(item)
            selected = next((item for item in candidates if item.get("ok")), None)
            return {
                "ok": bool(selected),
                "write_ok": bool(selected),
                "storage": "ftps",
                "selected_remote_dir": selected.get("remote_dir", "") if selected else "",
                "selected_remote_path": selected.get("remote_path", "") if selected else "",
                "candidates": candidates,
                "entries_sample": root_entries[:8],
                "checked_at": _utc_now(),
                "failure_code": "" if selected else "BAMBU_FTPS_NO_WRITABLE_PATH",
            }
        except Exception as exc:
            return self._classified_ftps_failure(
                exc,
                host=host,
                timeout_sec=timeout_sec,
                default_code="BAMBU_FTPS_PATH_PROBE_FAILED",
                extra={"write_ok": False, "candidates": candidates},
            )
        finally:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass

    def _sanitize_probe_dir(self, value: str) -> str:
        return _sanitize_bambu_remote_dir(value)

    def _cwd_remote_dir(self, client: FTP_TLS, remote_dir: str) -> None:
        """Move to a Bambu FTPS directory before STOR/DELE.

        Bambu's FTPS server is stricter than a general-purpose FTP daemon on
        some firmware. Uploading with a slash-bearing STOR target can fail even
        when CWD + basename upload is accepted.
        """
        cleaned = self._sanitize_probe_dir(remote_dir)
        if not cleaned:
            return
        absolute = f"/{cleaned}"
        try:
            client.cwd(absolute)
            return
        except Exception:
            client.cwd("/")
        for part in cleaned.split("/"):
            client.cwd(part)

    def _reset_cwd(self, client: FTP_TLS) -> None:
        try:
            client.cwd("/")
        except Exception:
            pass

    def upload_file(
        self,
        *,
        local_path: str | Path,
        remote_path: str,
        host: str,
        username: str,
        access_code: str,
        timeout_sec: float,
        delete_after: bool = False,
    ) -> dict[str, Any]:
        """Upload a pre-sliced artifact to Bambu FTPS storage without starting a print."""
        if not host or not access_code:
            return {"ok": False, "failure_code": "BAMBU_FTPS_CONNECTION_INFO_INCOMPLETE"}
        source = Path(local_path)
        if not source.exists() or not source.is_file():
            return {"ok": False, "failure_code": "BAMBU_UPLOAD_INPUT_MISSING", "local_path": str(source)}

        remote = str(remote_path or source.name).strip().replace("\\", "/")
        parts = [part for part in remote.split("/") if part]
        if not parts or remote.startswith("/") or any(part in {".", ".."} for part in parts):
            return {"ok": False, "failure_code": "BAMBU_UPLOAD_BAD_REMOTE_PATH", "remote_path": remote}
        remote = "/".join(parts)
        remote_dir = "/".join(parts[:-1])
        remote_name = parts[-1]

        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        client = _ImplicitFTP_TLS(context=ssl._create_unverified_context())
        deleted = False
        try:
            client.connect(host, 990, timeout=float(timeout_sec))
            client.login(username or "bblp", access_code)
            client.prot_p()
            self._cwd_remote_dir(client, remote_dir)
            with source.open("rb") as handle:
                client.storbinary(f"STOR {remote_name}", handle)
            if delete_after:
                client.delete(remote_name)
                deleted = True
            return {
                "ok": True,
                "status": "uploaded_deleted" if deleted else "uploaded",
                "remote_path": remote,
                "size_bytes": len(data),
                "sha256": digest,
                "delete_after": bool(delete_after),
                "deleted": deleted,
                "checked_at": _utc_now(),
            }
        except Exception as exc:
            return self._classified_ftps_failure(
                exc,
                host=host,
                timeout_sec=timeout_sec,
                default_code="BAMBU_FTPS_UPLOAD_FAILED",
                extra={"remote_path": remote},
            )
        finally:
            self._reset_cwd(client)
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass

    def _classified_ftps_failure(
        self,
        exc: Exception,
        *,
        host: str,
        timeout_sec: float,
        default_code: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        error = str(exc)
        payload: dict[str, Any] = {
            "ok": False,
            "storage": "ftps",
            "failure_code": default_code,
            "error": error,
            "checked_at": _utc_now(),
        }
        if extra:
            payload.update(extra)
        if self._looks_like_plaintext_tls_mismatch(error):
            banner = self._read_plain_ftp_banner(host=host, timeout_sec=timeout_sec)
            if banner:
                payload["plaintext_banner"] = banner
                payload["error"] = f"{error}; plaintext_banner={banner}"
            lowered = banner.lower()
            if banner.startswith("421") and "too many connections" in lowered:
                payload["failure_code"] = "BAMBU_FTPS_TOO_MANY_CONNECTIONS"
                payload["operator_action"] = (
                    "Close other Bambu Studio/FTP sessions or wait for stale FTPS sessions to expire before retrying."
                )
        return payload

    def _looks_like_plaintext_tls_mismatch(self, error: str) -> bool:
        lowered = str(error or "").lower()
        return "wrong_version_number" in lowered or "wrong version number" in lowered

    def _read_plain_ftp_banner(self, *, host: str, timeout_sec: float) -> str:
        sock = None
        try:
            sock = socket.create_connection((host, 990), timeout=float(timeout_sec))
            try:
                sock.settimeout(float(timeout_sec))
            except Exception:
                pass
            return sock.recv(512).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass


class PrinterDeviceBridgeManager:
    """Select and execute the correct vendor bridge for a printer.prepare request."""

    def __init__(self, config: BambuBridgeConfig, *, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or REPO_ROOT
        self.live_probe = BambuLiveProbe(config)
        self.mqtt_client = BambuMqttReportClient(config)
        self.ftps_client = BambuFtpsClient(config)
        self.video_client = BambuVideoStreamClient(config)

    @classmethod
    def from_devices_config(
        cls, cfg: dict[str, Any] | None, *, repo_root: Path | None = None
    ) -> "PrinterDeviceBridgeManager":
        return cls(BambuBridgeConfig.from_devices_config(cfg or {}, repo_root=repo_root), repo_root=repo_root)

    def available_printers(self) -> list[dict[str, Any]]:
        return [profile.redacted() for profile in self.config.profiles.values()]

    def fleet_memory(self) -> PrinterFleetMemory:
        return PrinterFleetMemory(self.config.connection_memory_path)

    def fleet_selection(self) -> tuple[PrinterProfile, str]:
        profile_id, reason = self.fleet_memory().active_profile_id(
            default_profile_id=self.config.default_profile_id,
            profiles=self.config.profiles,
        )
        return self.config.profile(profile_id), reason

    def fleet_payload(self) -> dict[str, Any]:
        profile, reason = self.fleet_selection()
        return {
            "ok": True,
            "tool": "printer.fleet",
            "active_profile_id": profile.profile_id,
            "default_profile_id": self.config.default_profile_id,
            "selected_printer": self._selected_printer_payload(profile, reason),
            "available_printers": self.available_printers(),
            "automatic_fallback": False,
            "settings_path": str(self.config.connection_memory_path),
        }

    def save_fleet_selection(self, profile_id: str) -> dict[str, Any]:
        self.fleet_memory().save(profile_id, profiles=self.config.profiles)
        return self.fleet_payload()

    def autoejection_memory(self) -> BambuAutoejectionMemory:
        return BambuAutoejectionMemory(self.config.autoejection_memory_path)

    def bed_clear_memory(self) -> BambuBedClearMemory:
        return BambuBedClearMemory(self.repo_root / "memory" / "bambu_bed_clear_evidence.json")

    def autoejection_config(self) -> AutoEjectionConfig:
        return self.autoejection_memory().config_with_defaults(self.config.autoejection)

    def autoejection_status(self) -> dict[str, Any]:
        status = self.autoejection_config().status_payload()
        status["runtime_paths"] = self.autoejection_memory().runtime_paths()
        return status

    def save_autoejection_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self.autoejection_memory().save_from_payload(payload, self.config.autoejection)
        status = config.status_payload()
        status["runtime_paths"] = self.autoejection_memory().runtime_paths()
        return status

    def bed_clear_status(self) -> dict[str, Any]:
        return self.bed_clear_memory().load()

    def save_bed_clear_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile, _reason = self.fleet_selection()
        return self.bed_clear_memory().save_from_payload(payload, printer_profile_id=profile.profile_id)

    def _corexy_autoejection_family_blocker(
        self,
        profile: PrinterProfile,
        selected_printer: dict[str, Any],
        *,
        tool: str,
    ) -> dict[str, Any] | None:
        family = str(profile.capabilities.get("model_family") or "").strip().lower()
        label = str(profile.label or "").strip().lower()
        profile_id = str(profile.profile_id or "").strip().lower()
        family_hint = " ".join(part for part in (family, label, profile_id) if part)
        is_a1_family = any(token in family_hint for token in ("a1", "bed_slinger", "bed-slinger"))
        if not is_a1_family:
            return None
        return {
            "ok": False,
            "tool": tool,
            "provider": profile.provider,
            "selected_printer": selected_printer,
            "status": "blocked",
            "failure_code": "BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED",
            "blockers": ["BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED"],
            "message": (
                "Bambu A1/A1 Mini bed-slinger autoejection needs a separate Y-axis/wiggle generator; "
                "the CoreXY X-lane Bambu tail was not generated."
            ),
            "model_family": family or "inferred_a1_family",
            "will_publish": False,
            "start_enabled": False,
        }

    def patch_bambu_autoejection_artifact(
        self,
        *,
        source_path: str | Path,
        specimen_id: str = "",
        position: str = "",
        plate_id: int = 1,
        loop_index: int = 1,
        run_id: str = "",
        validate_only: bool = False,
    ) -> dict[str, Any]:
        """Patch or validate a Bambu sliced artifact with native G-code autoejection, without publishing."""
        profile, reason = self.fleet_selection()
        selected_printer = self._selected_printer_payload(profile, reason)
        if profile.provider != "bambulab_x2d":
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_patch",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_AUTOEJECTION_PATCH_NOT_APPLICABLE",
                "blockers": ["BAMBU_AUTOEJECTION_PATCH_NOT_APPLICABLE"],
                "will_publish": False,
                "start_enabled": False,
            }
        family_blocker = self._corexy_autoejection_family_blocker(
            profile,
            selected_printer,
            tool="printer.bambu.autoejection_patch",
        )
        if family_blocker:
            return family_blocker
        config = self.autoejection_config()
        autoejection = config.status_payload()
        if not autoejection.get("can_run_test") or not autoejection.get("native_gcode_patch"):
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_patch",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED",
                "blockers": [*list(autoejection.get("blockers", [])), "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED"],
                "autoejection": autoejection,
                "will_publish": False,
                "start_enabled": False,
            }
        native_params = config.native_gcode_parameters()
        effective_position = str(position or native_params.get("push_direction") or "center")
        patcher = BambuGcodeAutoejectionPatcher(
            output_dir=self.repo_root / "artifacts" / "bambu_autoejection",
            z_push_offset_mm=float(native_params.get("z_push_offset_mm") or 30.0),
            push_lane_offset_mm=float(native_params.get("push_lane_offset_mm") or 30.0),
            sweep_feedrate_mm_min=int(native_params.get("push_speed_mm_min") or 300),
            enable_full_bed_sweep=bool(native_params.get("enable_full_bed_sweep")),
            sweep_z_mm=float(native_params.get("sweep_z_mm") or 1.0),
            full_bed_sweep_feedrate_mm_min=int(native_params.get("sweep_speed_mm_min") or 300),
        )
        if validate_only:
            result = patcher.validate_artifact(
                source_path=source_path,
                specimen_id=specimen_id,
                position=effective_position,
                plate_id=plate_id,
                loop_index=loop_index,
            )
        else:
            result = patcher.patch_artifact(
                source_path=source_path,
                specimen_id=specimen_id,
                position=effective_position,
                plate_id=plate_id,
                loop_index=loop_index,
            )
        payload = {
            **result,
            "provider": profile.provider,
            "selected_printer": selected_printer,
            "autoejection": autoejection,
            "handoff_required": False,
            "validate_only": bool(validate_only),
            "will_publish": False,
            "start_enabled": False,
            "workspace_manifest_path": "",
        }
        if not validate_only:
            workspace_manifest = self._write_bambu_workspace_manifest(run_id=run_id, payload=payload)
            if workspace_manifest:
                payload["workspace_manifest_path"] = workspace_manifest
        return payload

    def _write_bambu_workspace_manifest(self, *, run_id: str, payload: dict[str, Any]) -> str:
        safe_run = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(run_id or "").strip()).strip(".-")
        if not safe_run:
            return ""
        manifest_dir = self.repo_root / "runs" / safe_run / "workspace" / "printer"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "bambu_autoejection_manifest.json"
        manifest_payload = {
            **payload,
            "schema": "bambu_autoejection_workspace_manifest.v1",
            "artifact_manifest_schema": payload.get("schema", ""),
            "run_id": safe_run,
            "sidecar_manifest_path": payload.get("manifest_path", ""),
            "manifest_created_at": _utc_now(),
        }
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return str(manifest_path)

    def build_standalone_bambu_autoejection_artifact(
        self,
        *,
        specimen_id: str = "standalone-ejection-test",
        position: str = "center",
        object_size_mm: list[float] | None = None,
    ) -> dict[str, Any]:
        """Build a standalone Bambu ejection validation artifact without publishing."""
        profile, reason = self.fleet_selection()
        selected_printer = self._selected_printer_payload(profile, reason)
        if profile.provider != "bambulab_x2d":
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_standalone",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_AUTOEJECTION_STANDALONE_NOT_APPLICABLE",
                "blockers": ["BAMBU_AUTOEJECTION_STANDALONE_NOT_APPLICABLE"],
                "will_publish": False,
                "start_enabled": False,
            }
        family_blocker = self._corexy_autoejection_family_blocker(
            profile,
            selected_printer,
            tool="printer.bambu.autoejection_standalone",
        )
        if family_blocker:
            return family_blocker
        config = self.autoejection_config()
        autoejection = config.status_payload()
        if not autoejection.get("can_run_test") or not autoejection.get("native_gcode_patch"):
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_standalone",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED",
                "blockers": [*list(autoejection.get("blockers", [])), "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED"],
                "autoejection": autoejection,
                "will_publish": False,
                "start_enabled": False,
            }
        native_params = config.native_gcode_parameters()
        effective_position = str(position or native_params.get("push_direction") or "center")
        patcher = BambuGcodeAutoejectionPatcher(
            output_dir=self.repo_root / "artifacts" / "bambu_autoejection",
            z_push_offset_mm=float(native_params.get("z_push_offset_mm") or 30.0),
            push_lane_offset_mm=float(native_params.get("push_lane_offset_mm") or 30.0),
            sweep_feedrate_mm_min=int(native_params.get("push_speed_mm_min") or 300),
            enable_full_bed_sweep=bool(native_params.get("enable_full_bed_sweep")),
            sweep_z_mm=float(native_params.get("sweep_z_mm") or 1.0),
            full_bed_sweep_feedrate_mm_min=int(native_params.get("sweep_speed_mm_min") or 300),
        )
        result = patcher.build_standalone_ejection_artifact(
            position=effective_position,
            specimen_id=specimen_id,
            object_size_mm=object_size_mm,
        )
        return {
            **result,
            "provider": profile.provider,
            "selected_printer": selected_printer,
            "autoejection": autoejection,
            "handoff_required": False,
            "will_publish": False,
            "start_enabled": False,
        }

    def build_bambu_autoejection_sweep_test_artifact(
        self,
        *,
        specimen_id: str = "sweep-test",
    ) -> dict[str, Any]:
        """Build a full-bed sweep validation artifact without publishing."""
        profile, reason = self.fleet_selection()
        selected_printer = self._selected_printer_payload(profile, reason)
        if profile.provider != "bambulab_x2d":
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_sweep_test",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_AUTOEJECTION_SWEEP_TEST_NOT_APPLICABLE",
                "blockers": ["BAMBU_AUTOEJECTION_SWEEP_TEST_NOT_APPLICABLE"],
                "will_publish": False,
                "start_enabled": False,
            }
        family_blocker = self._corexy_autoejection_family_blocker(
            profile,
            selected_printer,
            tool="printer.bambu.autoejection_sweep_test",
        )
        if family_blocker:
            return family_blocker
        config = self.autoejection_config()
        autoejection = config.status_payload()
        if not autoejection.get("can_run_test") or not autoejection.get("native_gcode_patch"):
            return {
                "ok": False,
                "tool": "printer.bambu.autoejection_sweep_test",
                "provider": profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED",
                "blockers": [*list(autoejection.get("blockers", [])), "BAMBU_NATIVE_GCODE_AUTOEJECTION_NOT_CONFIGURED"],
                "autoejection": autoejection,
                "will_publish": False,
                "start_enabled": False,
            }
        native_params = config.native_gcode_parameters()
        patcher = BambuGcodeAutoejectionPatcher(
            output_dir=self.repo_root / "artifacts" / "bambu_autoejection",
            z_push_offset_mm=float(native_params.get("z_push_offset_mm") or 30.0),
            push_lane_offset_mm=float(native_params.get("push_lane_offset_mm") or 30.0),
            sweep_feedrate_mm_min=int(native_params.get("push_speed_mm_min") or 300),
            enable_full_bed_sweep=True,
            sweep_z_mm=float(native_params.get("sweep_z_mm") or 1.0),
            full_bed_sweep_feedrate_mm_min=int(native_params.get("sweep_speed_mm_min") or 300),
        )
        result = patcher.build_sweep_test_artifact(specimen_id=specimen_id)
        return {
            **result,
            "provider": profile.provider,
            "selected_printer": selected_printer,
            "autoejection": autoejection,
            "handoff_required": False,
            "will_publish": False,
            "start_enabled": False,
        }

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        profile, reason = self._select_profile(normalized)
        if profile.provider == "bambulab_x2d":
            return self._prepare_bambu(profile, normalized, selection_reason=reason)
        return self._prepare_non_bambu(profile, normalized, selection_reason=reason)

    def health(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        profile, reason = self._select_profile(normalized)
        if profile.provider == "bambulab_x2d":
            result = self._prepare_bambu(profile, {**normalized, "health_only": True}, selection_reason=reason)
            return {
                "ok": bool(result.get("ok")),
                "state": result.get("status", "unknown"),
                "provider": profile.provider,
                "selected_printer": result.get("selected_printer", {}),
                "device_screen": result.get("device_screen", {}),
                "failure_code": result.get("failure_code", ""),
                "requires_connection_info": bool(result.get("requires_connection_info", False)),
            }
        return {
            "ok": True,
            "state": "SELECTED_NON_BAMBU_PROFILE",
            "provider": profile.provider,
            "selected_printer": self._selected_printer_payload(profile, reason),
        }

    def video_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Probe selected-printer live view without issuing print or motion commands."""
        normalized = dict(payload or {})
        profile, reason = self._select_profile(normalized)
        result = self._base_result(profile, {"runtime_mode": "live", **normalized}, selection_reason=reason)
        result["tool"] = "printer.bambu.video_status"
        if profile.provider != "bambulab_x2d":
            result.update(
                {
                    "ok": False,
                    "status": "not_applicable",
                    "failure_code": "BAMBU_VIDEO_STATUS_REQUIRES_BAMBU_PROFILE",
                    "video_status": {"ok": False, "status": "not_applicable", "blockers": ["BAMBU_PROFILE_NOT_SELECTED"]},
                    "device_screen": self._device_screen_payload(
                        profile=profile,
                        connection={"mqtt": "not_applicable", "video": "not_applicable", "transfer": "unknown"},
                        job_source="video_probe",
                    ),
                }
            )
            return result

        memory = BambuConnectionMemory(profile.connection_memory_path)
        raw_connection = memory.load()
        raw_auth = raw_connection.get("auth") if isinstance(raw_connection.get("auth"), dict) else {}
        connection = memory.redacted()
        host = str(connection.get("host") or "")
        access_code = str(raw_auth.get("access_code") or "")
        report_camera = normalized.get("camera") if isinstance(normalized.get("camera"), dict) else {}
        video_status = self.video_client.probe_live_view(
            host=host,
            access_code=access_code,
            reported_rtsp_url=str(normalized.get("reported_rtsp_url") or report_camera.get("rtsp_url") or ""),
            timeout_sec=float(normalized.get("timeout_sec") or self.config.video.timeout_sec),
        )
        if video_status.get("proxy_ready"):
            video_connection = "streaming"
        elif video_status.get("ok"):
            video_connection = "streaming_candidate"
        elif video_status.get("status") == "disabled":
            video_connection = "disabled"
        else:
            video_connection = "unavailable"
        device_screen = self._device_screen_payload(
            profile=profile,
            connection={
                "mqtt": "unknown",
                "video": video_connection,
                "transfer": "unknown",
                "last_seen_at": video_status.get("checked_at", ""),
                "lan_mode_confirmed": bool(connection.get("lan_mode_confirmed")),
                "developer_mode_confirmed": bool(connection.get("developer_mode_confirmed")),
            },
            job_source="video_probe",
            video_probe=video_status,
        )
        result.update(
            {
                "ok": bool(video_status.get("ok")),
                "status": video_status.get("status", "unknown"),
                "failure_code": str(video_status.get("failure_code") or ""),
                "connection": connection,
                "video_status": video_status,
                "device_screen": device_screen,
                "step_trace": [
                    {"step": "SELECT_PRINTER_PROFILE", "status": "ok", "detail": profile.profile_id},
                    {
                        "step": "BAMBU_VIDEO_STATUS",
                        "status": "ok" if video_status.get("ok") else "blocked",
                        "detail": str(video_status.get("stream_kind") or video_status.get("failure_code") or ""),
                    },
                ],
            }
        )
        return result

    def _select_profile(self, payload: dict[str, Any]) -> tuple[PrinterProfile, str]:
        requested = str(payload.get("printer_profile_id") or "").strip()
        if requested:
            return self.config.profile(requested), "explicit_profile_id"
        hinted = " ".join(
            str(payload.get(key) or "").strip().lower()
            for key in ("printer_provider", "provider", "printer_model", "printer_profile")
            if payload.get(key)
        )
        if hinted:
            for profile in self.config.profiles.values():
                needles = {
                    profile.profile_id.lower(),
                    profile.provider.lower(),
                    profile.label.lower(),
                }
                capability_profile = str(profile.capabilities.get("printer_profile") or "").strip().lower()
                if capability_profile:
                    needles.add(capability_profile)
                if any(needle and needle in hinted for needle in needles):
                    return profile, "explicit_profile_hint"
            if "prusa" in hinted:
                for profile in self.config.profiles.values():
                    if profile.provider == "prusa_mk4s":
                        return profile, "explicit_profile_hint"
            if "bambu" in hinted or "x2d" in hinted:
                for profile in self.config.profiles.values():
                    if profile.provider == "bambulab_x2d":
                        return profile, "explicit_profile_hint"
        return self.fleet_selection()

    def _selected_printer_payload(self, profile: PrinterProfile, reason: str) -> dict[str, Any]:
        return {
            **profile.redacted(),
            "locked": True,
            "selection_reason": reason,
            "automatic_fallback_allowed": self.config.allow_automatic_fallback,
        }

    def _base_result(self, profile: PrinterProfile, payload: dict[str, Any], *, selection_reason: str) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "printer.prepare",
            "mode": str(payload.get("runtime_mode") or self.config.mode or "test"),
            "provider": profile.provider,
            "specimen_id": str(payload.get("specimen_id", "")),
            "run_id": str(payload.get("run_id", "")),
            "selected_printer": self._selected_printer_payload(profile, selection_reason),
            "available_printers": self.available_printers(),
            "automatic_fallback": False,
            "created_at": _utc_now(),
        }

    def _prepare_non_bambu(self, profile: PrinterProfile, payload: dict[str, Any], *, selection_reason: str) -> dict[str, Any]:
        result = self._base_result(profile, payload, selection_reason=selection_reason)
        result.update(
            {
                "status": "selected_non_bambu_profile",
                "message": "Selected printer profile is handled by its vendor adapter.",
                "device_screen": self._device_screen_payload(
                    profile=profile,
                    connection={"mqtt": "not_applicable", "video": "not_applicable", "transfer": "unknown"},
                    job_source="none",
                ),
            }
        )
        return result

    def _prepare_bambu(self, profile: PrinterProfile, payload: dict[str, Any], *, selection_reason: str) -> dict[str, Any]:
        mode = str(payload.get("runtime_mode") or self.config.mode or "test").lower()
        health_only = _as_bool(payload.get("health_only"), False)
        result = self._base_result(profile, payload, selection_reason=selection_reason)
        result["autoejection"] = self.autoejection_status()
        if mode != "live":
            result.update(
                {
                    "status": "VIRTUAL_BAMBU_READY",
                    "preprint_gate": self._preprint_gate("virtual"),
                    "device_screen": self._device_screen_payload(
                        profile=profile,
                        connection={
                            "mqtt": "virtual",
                            "video": "virtual",
                            "transfer": "virtual",
                            "last_seen_at": _utc_now(),
                        },
                        job_source="none",
                    ),
                    "step_trace": [
                        {"step": "SELECT_PRINTER_PROFILE", "status": "ok", "detail": profile.profile_id},
                        {"step": "VIRTUAL_BAMBU_BRIDGE", "status": "ok", "detail": "No physical communication in test mode"},
                    ],
                }
            )
            return result

        memory = BambuConnectionMemory(profile.connection_memory_path)
        raw_connection = memory.load()
        raw_auth = raw_connection.get("auth") if isinstance(raw_connection.get("auth"), dict) else {}
        connection = memory.redacted()
        missing = [
            key
            for key, value in {
                "host": connection.get("host"),
                "serial": connection.get("serial"),
                "access_code": connection.get("access_code_set"),
            }.items()
            if not value
        ]
        if missing:
            result.update(
                {
                    "ok": False,
                    "status": "connection_info_required",
                    "failure_code": "BAMBU_CONNECTION_INFO_REQUIRED",
                    "requires_connection_info": True,
                    "missing_connection_fields": missing,
                    "connection": connection,
                    "preprint_gate": self._preprint_gate("blocked", blockers=["BAMBU_CONNECTION_INFO_REQUIRED"]),
                    "device_screen": self._device_screen_payload(
                        profile=profile,
                        connection={"mqtt": "unknown", "video": "unknown", "transfer": "unknown"},
                        job_source="none",
                    ),
                    "step_trace": [
                        {"step": "SELECT_PRINTER_PROFILE", "status": "ok", "detail": profile.profile_id},
                        {"step": "LOAD_BAMBU_CONNECTION", "status": "blocked", "detail": ",".join(missing)},
                    ],
                }
            )
            return result

        mqtt_probe = self.live_probe.probe_tls_port(
            str(connection["host"]),
            self.config.mqtt.port,
            self.config.mqtt.timeout_sec,
        )
        if mqtt_probe.get("ok"):
            mqtt_snapshot_kwargs = {
                "host": str(connection["host"]),
                "serial": str(connection["serial"]),
                "username": str(connection.get("username") or self.config.mqtt.username),
                "access_code": str(raw_auth.get("access_code") or ""),
                "timeout_sec": self.config.mqtt.timeout_sec,
            }
            if payload.get("post_publish_observation") or payload.get("force_mqtt_refresh"):
                mqtt_snapshot_kwargs["force_refresh"] = True
            mqtt_snapshot = self.mqtt_client.read_snapshot(**mqtt_snapshot_kwargs)
        else:
            mqtt_snapshot = {"ok": False, "failure_code": mqtt_probe.get("failure_code", "BAMBU_MQTT_UNAVAILABLE")}
        mqtt_state = "connected" if mqtt_snapshot.get("ok") else "disconnected"
        normalized_report = (
            normalize_bambu_report(mqtt_snapshot.get("report", {}), received_at=str(mqtt_snapshot.get("received_at", "")))
            if mqtt_snapshot.get("ok")
            else {}
        )
        if mqtt_snapshot.get("ok"):
            ftps_probe = self.ftps_client.probe_storage(
                host=str(connection["host"]),
                username=str(connection.get("username") or self.config.mqtt.username),
                access_code=str(raw_auth.get("access_code") or ""),
                timeout_sec=self.config.mqtt.timeout_sec,
                write_probe=not health_only,
            )
            if (
                not health_only
                and not ftps_probe.get("ok")
                and ftps_probe.get("read_ok")
                and str(ftps_probe.get("failure_code") or "") == "BAMBU_FTPS_WRITE_FAILED"
            ):
                root_probe = dict(ftps_probe)
                path_probe_fn = getattr(self.ftps_client, "probe_upload_paths", None)
                path_probe = (
                    path_probe_fn(
                        host=str(connection["host"]),
                        username=str(connection.get("username") or self.config.mqtt.username),
                        access_code=str(raw_auth.get("access_code") or ""),
                        timeout_sec=self.config.mqtt.timeout_sec,
                        candidate_dirs=["cache", "sdcard", "Metadata", "data/Metadata"],
                    )
                    if callable(path_probe_fn)
                    else {"ok": False, "failure_code": "BAMBU_FTPS_PATH_PROBE_UNAVAILABLE"}
                )
                if path_probe.get("ok"):
                    ftps_probe = {
                        **path_probe,
                        "read_ok": True,
                        "root_probe": root_probe,
                        "path_probe_recovered": True,
                    }
                else:
                    ftps_probe = {
                        **root_probe,
                        "upload_path_probe": path_probe,
                    }
        else:
            ftps_probe = {"ok": False, "failure_code": "BAMBU_MQTT_REQUIRED_BEFORE_FTPS"}
        transfer_state = "connected" if ftps_probe.get("ok") else ("read_only" if ftps_probe.get("read_ok") else "disconnected")
        gate_ready = bool(mqtt_snapshot.get("ok") and ftps_probe.get("ok"))
        gate_state = "ready_to_upload" if gate_ready else "blocked"
        failure_code = ""
        if not mqtt_snapshot.get("ok"):
            failure_code = str(mqtt_snapshot.get("failure_code", "BAMBU_MQTT_REPORT_UNAVAILABLE"))
        elif not ftps_probe.get("ok"):
            failure_code = str(ftps_probe.get("failure_code", "BAMBU_FTPS_UNAVAILABLE"))
        upload_result: dict[str, Any] = {}
        artifact_path = self._bambu_sliced_artifact_path(payload)
        artifact_url = self._bambu_artifact_url(payload)
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        plate_id = payload.get("plate_id") or print_payload.get("plate_id") or 1
        artifact_plate_validation: dict[str, Any] = {}
        wants_upload = self._wants_bambu_upload(payload)
        if artifact_path and not health_only:
            artifact_plate_validation = validate_bambu_project_file_local_artifact(artifact_path, plate_id=plate_id)
            if not artifact_plate_validation.get("ok"):
                gate_ready = False
                gate_state = "blocked"
                failure_code = str(artifact_plate_validation.get("failure_code") or "BAMBU_PROJECT_FILE_PARAM_MISMATCH")
        if gate_ready and artifact_path and not health_only:
            upload_result = self.ftps_client.upload_file(
                local_path=artifact_path,
                remote_path=self._bambu_remote_artifact_path(
                    payload,
                    artifact_path,
                    verified_remote_dir=str(ftps_probe.get("selected_remote_dir") or ""),
                ),
                host=str(connection["host"]),
                username=str(connection.get("username") or self.config.mqtt.username),
                access_code=str(raw_auth.get("access_code") or ""),
                timeout_sec=self.config.mqtt.timeout_sec,
                delete_after=False,
            )
            gate_ready = bool(upload_result.get("ok"))
            gate_state = "uploaded_not_started" if gate_ready else "blocked"
            if not gate_ready:
                failure_code = str(upload_result.get("failure_code", "BAMBU_FTPS_UPLOAD_FAILED"))
        elif gate_ready and wants_upload and not artifact_path:
            gate_ready = False
            gate_state = "blocked"
            failure_code = "BAMBU_SLICED_ARTIFACT_REQUIRED"
        if artifact_plate_validation and not artifact_plate_validation.get("ok"):
            project_file_draft = {
                **artifact_plate_validation,
                "schema": "bambu_project_file_command_draft.v1",
                "topic": "",
                "payload": {},
                "requires_guardian": True,
                "guard_reason": "local_artifact_plate_validation_failed",
            }
        else:
            project_file_draft = self._bambu_project_file_draft(
                connection=connection,
                payload=payload,
                upload_result=upload_result,
                artifact_url=artifact_url,
            )
            if artifact_url and not project_file_draft.get("ok"):
                gate_ready = False
                gate_state = "blocked"
                failure_code = str(project_file_draft.get("failure_code") or failure_code or "BAMBU_PROJECT_FILE_DRAFT_INVALID")
        http_artifact_ready = bool(
            mqtt_snapshot.get("ok")
            and artifact_url
            and _is_http_artifact_url(artifact_url)
            and project_file_draft.get("ok")
            and not upload_result.get("ok")
        )
        if http_artifact_ready:
            upload_result = {
                "ok": True,
                "status": "http_artifact_ready",
                "route": "http_artifact",
                "remote_path": artifact_url,
                "url": artifact_url,
                "size_bytes": None,
                "sha256": "",
                "delete_after": False,
                "deleted": False,
            }
            transfer_state = "connected"
            gate_ready = True
            gate_state = "http_artifact_ready_not_started"
            failure_code = ""
        result.update(
            {
                "ok": gate_ready,
                "status": self._bambu_prepare_status(gate_ready, upload_result, failure_code),
                "failure_code": failure_code,
                "connection": connection,
                "mqtt_probe": mqtt_probe,
                "mqtt_snapshot": {k: v for k, v in mqtt_snapshot.items() if k != "report"},
                "ftps_probe": ftps_probe,
                "upload": upload_result,
                "artifact_plate_validation": artifact_plate_validation,
                "project_file_draft": project_file_draft,
                "operator_actions": self._bambu_operator_actions(
                    connection=connection,
                    failure_code=failure_code,
                    ftps_probe=ftps_probe,
                    normalized_report=normalized_report,
                    http_artifact_ready=http_artifact_ready,
                ),
                "preprint_gate": self._preprint_gate(
                    gate_state,
                    blockers=[] if gate_ready else [str(failure_code)],
                    mqtt_authenticated_or_virtual=bool(mqtt_snapshot.get("ok")),
                    latest_report_fresh=bool(mqtt_snapshot.get("ok")),
                    live_view_status_known=False,
                    storage_transfer_path_verified=bool(ftps_probe.get("ok") or upload_result.get("ok")),
                    slicer_artifact_hash_recorded=bool(upload_result.get("ok") and upload_result.get("sha256")),
                    start_command_draft_prepared=bool(project_file_draft.get("ok")),
                    printer_safe_state_verified=normalized_report.get("state") in {"IDLE", "FINISH", "UNKNOWN"},
                    lan_mode_confirmed=bool(connection.get("lan_mode_confirmed")),
                    developer_mode_confirmed=bool(connection.get("developer_mode_confirmed")),
                ),
                "device_screen": self._device_screen_payload(
                    profile=profile,
                    connection={
                        "mqtt": mqtt_state,
                        "video": "unknown",
                        "transfer": transfer_state,
                        "last_seen_at": str(mqtt_snapshot.get("received_at") or ""),
                        "lan_mode_confirmed": bool(connection.get("lan_mode_confirmed")),
                        "developer_mode_confirmed": bool(connection.get("developer_mode_confirmed")),
                    },
                    job_source="none",
                    normalized_report=normalized_report,
                    upload_result=upload_result,
                    project_file_draft=project_file_draft,
                ),
                "step_trace": [
                    {"step": "SELECT_PRINTER_PROFILE", "status": "ok", "detail": profile.profile_id},
                    {"step": "BAMBU_MQTT_TLS_PREFLIGHT", "status": "ok" if mqtt_probe.get("ok") else "blocked"},
                    {"step": "BAMBU_MQTT_REPORT", "status": "ok" if mqtt_snapshot.get("ok") else "blocked"},
                    {"step": "BAMBU_FTPS_STORAGE", "status": "ok" if ftps_probe.get("ok") else "blocked"},
                    {
                        "step": "BAMBU_FTPS_UPLOAD",
                        "status": (
                            "skipped"
                            if http_artifact_ready
                            else ("ok" if upload_result.get("ok") else ("blocked" if wants_upload or artifact_path else "skipped"))
                        ),
                        "detail": str(upload_result.get("remote_path") or failure_code or ""),
                    },
                    {
                        "step": "BAMBU_ARTIFACT_ROUTE",
                        "status": "ok" if project_file_draft.get("ok") else "blocked",
                        "detail": str(project_file_draft.get("payload", {}).get("print", {}).get("url", "")),
                    },
                    {
                        "step": "BAMBU_PROJECT_FILE_DRAFT",
                        "status": "ok" if project_file_draft.get("ok") else "skipped",
                        "detail": str(project_file_draft.get("payload", {}).get("print", {}).get("url", "")),
                    },
                ],
            }
        )
        return result

    def _bambu_sliced_artifact_path(self, payload: dict[str, Any]) -> Path | None:
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        for key in ("bambu_artifact_path", "sliced_artifact_path", "artifact_path", "gcode_path", "gcode_3mf_path"):
            value = payload.get(key) or print_payload.get(key)
            if value:
                return Path(str(value))
        return None

    def _wants_bambu_upload(self, payload: dict[str, Any]) -> bool:
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        for key in ("upload_artifact", "start_print", "actual_print", "physical_print"):
            if _as_bool(payload.get(key), False) or _as_bool(print_payload.get(key), False):
                return True
        mode = str(payload.get("print_mode") or print_payload.get("mode") or "").strip().lower()
        return mode in {"live", "actual", "physical", "real_print", "실제 출력"}

    def _bambu_artifact_url(self, payload: dict[str, Any]) -> str:
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        for key in ("bambu_artifact_url", "artifact_url", "sliced_artifact_url", "gcode_3mf_url"):
            value = payload.get(key) or print_payload.get(key)
            if value:
                return str(value).strip()
        return ""

    def _bambu_project_file_draft(
        self,
        *,
        connection: dict[str, Any],
        payload: dict[str, Any],
        upload_result: dict[str, Any],
        artifact_url: str,
    ) -> dict[str, Any]:
        if upload_result.get("ok") and upload_result.get("remote_path"):
            remote_path = str(upload_result.get("remote_path"))
        else:
            remote_path = artifact_url
        if not remote_path:
            return {}
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        return build_bambu_project_file_command_draft(
            serial=str(connection.get("serial") or ""),
            remote_path=remote_path,
            subtask_name=str(payload.get("specimen_id") or print_payload.get("subtask_name") or ""),
            plate_id=payload.get("plate_id") or print_payload.get("plate_id") or 1,
            use_ams=_as_bool(payload.get("use_ams", print_payload.get("use_ams")), False),
            ams_mapping=payload.get("ams_mapping") if isinstance(payload.get("ams_mapping"), list) else print_payload.get("ams_mapping"),
            timelapse=_as_bool(payload.get("timelapse", print_payload.get("timelapse")), False),
            bed_leveling=_as_bool(payload.get("bed_leveling", print_payload.get("bed_leveling")), False),
            flow_cali=_as_bool(payload.get("flow_cali", print_payload.get("flow_cali")), False),
            vibration_cali=_as_bool(payload.get("vibration_cali", print_payload.get("vibration_cali")), False),
            layer_inspect=_as_bool(payload.get("layer_inspect", print_payload.get("layer_inspect")), False),
        )

    def _bambu_remote_artifact_path(
        self,
        payload: dict[str, Any],
        artifact_path: Path,
        *,
        verified_remote_dir: str = "",
    ) -> str:
        print_payload = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        remote = str(
            payload.get("bambu_remote_path")
            or payload.get("remote_path")
            or print_payload.get("remote_path")
            or ""
        ).strip()
        if remote:
            return remote
        remote_dir = _sanitize_bambu_remote_dir(verified_remote_dir)
        return f"{remote_dir}/{artifact_path.name}" if remote_dir else artifact_path.name

    def _bambu_prepare_status(self, ok: bool, upload_result: dict[str, Any], failure_code: str) -> str:
        if ok and upload_result.get("ok"):
            if str(upload_result.get("route") or "") == "http_artifact":
                return "HTTP_ARTIFACT_READY_NOT_STARTED"
            return "UPLOADED_NOT_STARTED"
        if ok:
            return "READY_TO_UPLOAD"
        if failure_code == "BAMBU_SLICED_ARTIFACT_REQUIRED":
            return "sliced_artifact_required"
        if str(failure_code).startswith("BAMBU_FTPS_UPLOAD"):
            return "artifact_upload_failed"
        return "preprint_communication_failed"

    def _bambu_operator_actions(
        self,
        *,
        connection: dict[str, Any],
        failure_code: str,
        ftps_probe: dict[str, Any],
        normalized_report: dict[str, Any],
        http_artifact_ready: bool = False,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        if not connection.get("lan_mode_confirmed"):
            actions.append(
                {
                    "code": "BAMBU_LAN_MODE_NOT_CONFIRMED",
                    "severity": "warning",
                    "message": "Confirm LAN-only mode on the Bambu printer, then save the connection setting.",
                }
            )
        if not connection.get("developer_mode_confirmed"):
            actions.append(
                {
                    "code": "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED",
                    "severity": "blocking" if failure_code == "BAMBU_FTPS_WRITE_FAILED" else "warning",
                    "message": "Enable Developer Mode for local write/control actions, then save the connection setting.",
                }
            )
        storage = normalized_report.get("storage") if isinstance(normalized_report.get("storage"), dict) else {}
        if storage.get("sdcard_available") is False:
            actions.append(
                {
                    "code": "BAMBU_SDCARD_REPORTED_FALSE",
                    "severity": "warning",
                    "message": "MQTT reports sdcard=false; use Bambu internal/approved upload path or confirm storage availability.",
                }
            )
        if failure_code == "BAMBU_FTPS_WRITE_FAILED":
            actions.append(
                {
                    "code": "BAMBU_FTPS_WRITE_FAILED",
                    "severity": "blocking",
                    "message": "FTPS login/read succeeded but marker upload failed; verify Developer Mode, writeable target path, or Bambu Connect route.",
                }
            )
        elif failure_code == "BAMBU_FTPS_TOO_MANY_CONNECTIONS":
            actions.append(
                {
                    "code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS",
                    "severity": "blocking",
                    "message": "The Bambu FTPS endpoint reports too many active sessions; close Bambu Studio/FTP clients or wait for stale sessions before retrying.",
                }
            )
        elif http_artifact_ready and not ftps_probe.get("ok"):
            ftps_code = str(ftps_probe.get("failure_code") or "BAMBU_FTPS_NOT_UPLOAD_READY")
            actions.append(
                {
                    "code": "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE",
                    "severity": "warning",
                    "message": "FTPS upload is not writable, so the prepared Bambu command uses a printer-reachable HTTP artifact URL.",
                }
            )
            if ftps_code == "BAMBU_FTPS_TOO_MANY_CONNECTIONS":
                actions.append(
                    {
                        "code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS",
                        "severity": "warning",
                        "message": "FTPS still reports too many active sessions; HTTP artifact routing is active for this start path.",
                    }
                )
        elif failure_code == "BAMBU_PROJECT_FILE_PARAM_MISMATCH":
            actions.append(
                {
                    "code": "BAMBU_PROJECT_FILE_PARAM_MISMATCH",
                    "severity": "blocking",
                    "message": "The selected .gcode.3mf does not match the requested Metadata/plate_#.gcode path; reslice or select the correct plate.",
                }
            )
        elif ftps_probe.get("read_ok") and not ftps_probe.get("ok") and not http_artifact_ready:
            actions.append(
                {
                    "code": str(ftps_probe.get("failure_code") or "BAMBU_FTPS_NOT_UPLOAD_READY"),
                    "severity": "blocking",
                    "message": "FTPS storage is readable but not upload-ready.",
                }
            )
        elif ftps_probe.get("read_ok") and not ftps_probe.get("ok") and http_artifact_ready:
            actions.append(
                {
                    "code": "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE",
                    "severity": "warning",
                    "message": "FTPS upload is not writable, so the prepared Bambu command uses a printer-reachable HTTP artifact URL.",
                }
            )
        return actions

    def _preprint_gate(
        self,
        state: str,
        blockers: list[str] | None = None,
        *,
        mqtt_authenticated_or_virtual: bool | None = None,
        latest_report_fresh: bool | None = None,
        live_view_status_known: bool | None = None,
        storage_transfer_path_verified: bool | None = None,
        slicer_artifact_hash_recorded: bool | None = None,
        start_command_draft_prepared: bool | None = None,
        printer_safe_state_verified: bool | None = None,
        lan_mode_confirmed: bool | None = None,
        developer_mode_confirmed: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": "preprint_real_communication_gate.v1",
            "state": state,
            "blockers": blockers or [],
            "checks": {
                "selected_printer_profile_locked": True,
                "mqtt_authenticated_or_virtual": (
                    state in {"virtual", "ready_to_upload", "uploaded_not_started"}
                    if mqtt_authenticated_or_virtual is None
                    else mqtt_authenticated_or_virtual
                ),
                "latest_report_fresh": state == "virtual" if latest_report_fresh is None else latest_report_fresh,
                "live_view_status_known": state == "virtual" if live_view_status_known is None else live_view_status_known,
                "storage_transfer_path_verified": state == "virtual" if storage_transfer_path_verified is None else storage_transfer_path_verified,
                "slicer_artifact_hash_recorded": bool(slicer_artifact_hash_recorded),
                "start_command_draft_prepared": bool(start_command_draft_prepared),
                "material_nozzle_profile_checked": False,
                "printer_safe_state_verified": state == "virtual" if printer_safe_state_verified is None else printer_safe_state_verified,
                "lan_mode_confirmed": state == "virtual" if lan_mode_confirmed is None else lan_mode_confirmed,
                "developer_mode_confirmed": state == "virtual" if developer_mode_confirmed is None else developer_mode_confirmed,
                "upload_permission_evaluated": True,
                "start_permission_evaluated": True,
                "guardian_state_attached": False,
            },
        }

    def _device_screen_payload(
        self,
        *,
        profile: PrinterProfile,
        connection: dict[str, Any],
        job_source: str,
        normalized_report: dict[str, Any] | None = None,
        upload_result: dict[str, Any] | None = None,
        project_file_draft: dict[str, Any] | None = None,
        video_probe: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        normalized_report = normalized_report if isinstance(normalized_report, dict) else {}
        report_job = normalized_report.get("job") if isinstance(normalized_report.get("job"), dict) else {}
        report_temperatures = (
            normalized_report.get("temperatures") if isinstance(normalized_report.get("temperatures"), dict) else {}
        )
        report_fans = normalized_report.get("fans") if isinstance(normalized_report.get("fans"), dict) else {}
        report_camera = normalized_report.get("camera") if isinstance(normalized_report.get("camera"), dict) else {}
        report_upload = normalized_report.get("upload") if isinstance(normalized_report.get("upload"), dict) else {}
        report_storage = normalized_report.get("storage") if isinstance(normalized_report.get("storage"), dict) else {}
        report_health = normalized_report.get("health") if isinstance(normalized_report.get("health"), dict) else {}
        report_materials = normalized_report.get("materials") if isinstance(normalized_report.get("materials"), dict) else {}
        report_device = normalized_report.get("device") if isinstance(normalized_report.get("device"), dict) else {}
        report_monitoring = normalized_report.get("monitoring") if isinstance(normalized_report.get("monitoring"), dict) else {}
        report_diagnostics = (
            normalized_report.get("diagnostics") if isinstance(normalized_report.get("diagnostics"), dict) else {}
        )
        report_modes = normalized_report.get("modes") if isinstance(normalized_report.get("modes"), dict) else {}
        report_queue = normalized_report.get("queue") if isinstance(normalized_report.get("queue"), dict) else {}
        report_control = normalized_report.get("control") if isinstance(normalized_report.get("control"), dict) else {}
        report_speed = normalized_report.get("speed") if isinstance(normalized_report.get("speed"), dict) else {}
        report_network = normalized_report.get("network") if isinstance(normalized_report.get("network"), dict) else {}
        upload_result = upload_result if isinstance(upload_result, dict) else {}
        project_file_draft = project_file_draft if isinstance(project_file_draft, dict) else {}
        video_probe = video_probe if isinstance(video_probe, dict) else {}
        upload_payload = dict(report_upload)
        if upload_result:
            upload_payload["artifact"] = {
                "status": upload_result.get("status", ""),
                "remote_path": upload_result.get("remote_path", ""),
                "size_bytes": upload_result.get("size_bytes"),
                "sha256": upload_result.get("sha256", ""),
                "deleted": bool(upload_result.get("deleted", False)),
            }
        if project_file_draft:
            upload_payload["start_command_draft"] = project_file_draft
        state = str(normalized_report.get("state") or ("idle" if connection.get("mqtt") == "virtual" else "unknown"))
        source = "mqtt_report" if normalized_report else ("virtual" if connection.get("mqtt") == "virtual" else job_source)
        remaining_sec = report_job.get("remaining_sec")
        remaining_min = round(float(remaining_sec) / 60.0, 1) if isinstance(remaining_sec, (int, float)) else None
        can_upload = connection.get("mqtt") == "virtual" or (
            connection.get("mqtt") == "connected" and connection.get("transfer") == "connected"
        )
        safe_state = state.upper() in {"IDLE", "FINISH", "UNKNOWN"}
        can_start_print = bool(can_upload and safe_state and project_file_draft.get("ok") and upload_result.get("ok"))
        action_payload = {
            "can_upload": can_upload,
            "can_prepare_start_command": bool(project_file_draft.get("ok")),
            "can_start_print": can_start_print,
            "can_pause": False,
            "can_cancel": False,
            "can_jog": False,
            "can_load_unload": False,
            "requires_guardian": True,
        }
        camera_status = "unavailable"
        camera_stream_kind = "unavailable"
        camera_proxy_ready = bool(video_probe.get("proxy_ready"))
        camera_proxy_url = str(video_probe.get("proxy_url") or "")
        camera_snapshot_url = str(video_probe.get("snapshot_url") or "")
        camera_blockers = (
            list(video_probe.get("blockers", [])) if isinstance(video_probe.get("blockers"), list) else []
        )
        if video_probe:
            camera_status = "proxy_ready" if camera_proxy_ready else str(video_probe.get("status") or "blocked")
            camera_stream_kind = str(video_probe.get("stream_kind") or "unavailable")
        elif connection.get("video") == "virtual":
            camera_status = "virtual"
            camera_stream_kind = "virtual"
        elif report_camera.get("liveview_preview"):
            camera_status = "preview_available"
            camera_stream_kind = "liveview_preview"
        elif report_camera.get("rtsp_url"):
            camera_status = "stream_reported"
            camera_stream_kind = "rtsps"
        elif report_camera.get("brtc_service"):
            camera_status = "stream_reported"
            camera_stream_kind = "brtc"
        elif report_camera.get("tutk_server"):
            camera_status = "stream_reported"
            camera_stream_kind = "tutk"
        elif connection.get("video") in {"streaming", "streaming_candidate", "snapshot"}:
            camera_status = str(connection.get("video"))
            camera_stream_kind = str(connection.get("video"))
        if not camera_blockers and camera_status == "unavailable":
            camera_blockers = ["BAMBU_VIDEO_PROXY_NOT_CONNECTED"]
        material_slots = [
            {
                "label": f"AMS {slot.get('ams_id', '')}-{slot.get('tray_id', '')}".strip("-"),
                "tray_type": slot.get("tray_type", ""),
                "tray_sub_brands": slot.get("tray_sub_brands", ""),
                "tray_color": slot.get("tray_color", ""),
                "remain_percent": slot.get("remain_percent"),
                "state": slot.get("state"),
            }
            for slot in report_materials.get("slots", [])[:8]
            if isinstance(slot, dict)
        ]
        evidence_cards = [
            {
                "id": "mqtt",
                "label": "MQTT telemetry",
                "status": connection.get("mqtt", "unknown"),
                "detail": f"last_seen={connection.get('last_seen_at', '') or 'n/a'}",
            },
            {
                "id": "transfer",
                "label": "Artifact transfer",
                "status": connection.get("transfer", "unknown"),
                "detail": str(upload_result.get("remote_path") or upload_result.get("failure_code") or "no artifact transfer yet"),
            },
            {
                "id": "video",
                "label": "Live view",
                "status": connection.get("video", "unknown"),
                "detail": camera_status,
            },
            {
                "id": "safe_state",
                "label": "Printer safe state",
                "status": "ready" if safe_state else "attention",
                "detail": state,
            },
        ]
        return {
            "schema": "printer_device_screen.v1",
            "profile_id": profile.profile_id,
            "provider": profile.provider,
            "connection": {
                "mqtt": connection.get("mqtt", "unknown"),
                "video": connection.get("video", "unknown"),
                "transfer": connection.get("transfer", "unknown"),
                "last_seen_at": connection.get("last_seen_at", ""),
                "lan_mode_confirmed": bool(connection.get("lan_mode_confirmed", False)),
                "developer_mode_confirmed": bool(connection.get("developer_mode_confirmed", False)),
            },
            "camera": {
                "mode": "unavailable" if connection.get("video") not in {"virtual", "streaming", "snapshot"} else connection.get("video"),
                "proxy_url": camera_proxy_url or report_camera.get("rtsp_url", ""),
                "snapshot_url": camera_snapshot_url,
                "frame_age_ms": None,
                "error": "" if camera_proxy_url or report_camera.get("rtsp_url") or connection.get("video") == "virtual" else "video stream not connected",
                "liveview_preview": bool(report_camera.get("liveview_preview", False)),
                "resolution": report_camera.get("resolution", ""),
                "recording": report_camera.get("recording", ""),
                "mode_bits": report_camera.get("mode_bits"),
                "rtsp_url": report_camera.get("rtsp_url", ""),
                "brtc_service": report_camera.get("brtc_service", ""),
                "tutk_server": report_camera.get("tutk_server", ""),
            },
            "camera_panel": {
                "status": camera_status,
                "stream_kind": camera_stream_kind,
                "summary": "Live preview reported by MQTT" if camera_status == "preview_available" else camera_status.replace("_", " "),
                "resolution": report_camera.get("resolution", ""),
                "recording": report_camera.get("recording", ""),
                "proxy_ready": camera_proxy_ready or connection.get("video") in {"streaming", "snapshot"},
                "proxy_url": camera_proxy_url,
                "snapshot_url": camera_snapshot_url,
                "blockers": camera_blockers,
            },
            "job": {
                "name": report_job.get("file_name", ""),
                "state": state,
                "progress_percent": report_job.get("progress_percent"),
                "current_layer": report_job.get("layer"),
                "layer": report_job.get("layer"),
                "total_layers": report_job.get("total_layers"),
                "remaining_sec": report_job.get("remaining_sec"),
                "prepare_percent": report_job.get("prepare_percent"),
                "task_id": report_job.get("task_id", ""),
                "project_id": report_job.get("project_id", ""),
                "model_id": report_job.get("model_id", ""),
                "print_type": report_job.get("print_type", ""),
                "plate_id": report_job.get("plate_id"),
                "plate_index": report_job.get("plate_index"),
                "plate_count": report_job.get("plate_count"),
                "source": job_source,
            },
            "progress_panel": {
                "state": state,
                "job_name": report_job.get("file_name", ""),
                "progress_percent": report_job.get("progress_percent"),
                "prepare_percent": report_job.get("prepare_percent"),
                "current_layer": report_job.get("layer"),
                "total_layers": report_job.get("total_layers"),
                "remaining_min": remaining_min,
                "source": source,
            },
            "temperatures": report_temperatures,
            "fans": report_fans,
            "upload": upload_payload,
            "storage": report_storage,
            "health": report_health,
            "device": report_device,
            "monitoring": report_monitoring,
            "diagnostics": report_diagnostics,
            "network": report_network,
            "modes": report_modes,
            "lights": normalized_report.get("lights", []),
            "thermal": {
                "main_nozzle_current_c": report_temperatures.get("nozzle_c"),
                "main_nozzle_target_c": report_temperatures.get("nozzle_target_c"),
                "aux_nozzle_current_c": (
                    report_device.get("extruders", [None, {}])[1].get("temp_c")
                    if len(report_device.get("extruders", [])) > 1
                    else None
                ),
                "aux_nozzle_target_c": None,
                "bed_current_c": report_temperatures.get("bed_c"),
                "bed_target_c": report_temperatures.get("bed_target_c"),
                "chamber_current_c": report_temperatures.get("chamber_c"),
                "fan_percent": report_fans.get("part_percent"),
            },
            "motion": {
                "jog_available": False,
                "homed": None,
                "safe_to_jog": False,
                "speed": report_speed,
                "queue": report_queue,
                "control": report_control,
            },
            "control_panel": {
                "state": state,
                "speed_percent": report_speed.get("magnitude_percent"),
                "queue_label": (
                    f"{report_queue.get('number')}/{report_queue.get('total')}"
                    if report_queue.get("number") is not None and report_queue.get("total") is not None
                    else "--"
                ),
                "can_upload": action_payload["can_upload"],
                "can_prepare_start_command": action_payload["can_prepare_start_command"],
                "can_start_print": action_payload["can_start_print"],
                "requires_guardian": True,
                "motion_enabled": False,
                "blockers": [] if can_upload else ["BAMBU_UPLOAD_GATE_BLOCKED"],
            },
            "materials": {
                "active_path": "unknown",
                "slots": report_materials.get("slots", []),
                "ams_units": report_materials.get("ams_units", []),
                "ams_status": report_materials.get("ams_status"),
                "ams_rfid_status": report_materials.get("ams_rfid_status"),
            },
            "material_panel": {
                "active_path": "unknown",
                "slot_count": len(material_slots),
                "ams_unit_count": len(report_materials.get("ams_units", [])),
                "ams_status": report_materials.get("ams_status"),
                "rfid_status": report_materials.get("ams_rfid_status"),
                "slots": material_slots,
            },
            "actions": action_payload,
            "evidence_cards": evidence_cards,
            "evidence_refs": [],
            "updated_at": now,
        }
