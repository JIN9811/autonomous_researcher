"""
File purpose:
- Safe Prusa MK4S bridge foundation for printer.prepare workflows.

Key classes/functions:
- PrusaBridgeConfig, PrusaConnectionMemory, PrusaLinkClient
- PrusaSlicerRunner, GCodeSafetyValidator, PaddleEjectionRoutineBuilder
- PrinterAgenticWorkflow, PrusaBridge

Inputs/outputs:
- Input: printer.prepare payloads and devices.yaml printer config
- Output: structured printer workflow results with hard live-action gates

Dependencies:
- httpx for optional live PrusaLink calls
- subprocess for optional PrusaSlicer CLI calls without shell=True

Modification guide:
- Safe places to edit: config defaults, failure codes, virtual responses
- Risky places to edit: live upload/start/ejection gates and G-code validation policy
- Related files: mcp_tools/printer_tools.py, device_bridges/simulator/printer_sim.py, agents/specimen_agent.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from device_bridges.base_bridge import BaseBridge


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONNECTION_MEMORY = REPO_ROOT / "memory" / "prusa_connection.json"


@dataclass(slots=True)
class SlicerConfig:
    enabled: bool = False
    executable_env: str = "PRUSA_SLICER_EXECUTABLE"
    executable_path: str = "install/prusaslicer/prusa-slicer-docker"
    output_dir: str = "artifacts/gcode"
    timeout_sec: float = 300.0
    profile_map: dict[str, str] = field(default_factory=dict)
    command_template: list[str] = field(
        default_factory=lambda: ["{executable}", "--export-gcode", "--output", "{output_path}", "{stl_path}"]
    )

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "SlicerConfig":
        raw = raw if isinstance(raw, dict) else {}
        template = raw.get("command_template")
        return cls(
            enabled=bool(raw.get("enabled", False)),
            executable_env=str(raw.get("executable_env", "PRUSA_SLICER_EXECUTABLE")),
            executable_path=str(raw.get("executable_path", "install/prusaslicer/prusa-slicer-docker")),
            output_dir=str(raw.get("output_dir", "artifacts/gcode")),
            timeout_sec=float(raw.get("timeout_sec", 300)),
            profile_map={str(key): str(value) for key, value in raw.get("profile_map", {}).items()}
            if isinstance(raw.get("profile_map"), dict)
            else {},
            command_template=[str(item) for item in template] if isinstance(template, list) and template else cls().command_template,
        )


@dataclass(slots=True)
class EjectionConfig:
    enabled: bool = False
    method: str = "toolhead_paddle"
    mode: str = "separate_job"
    require_cooldown: bool = True
    max_bed_temp_c: float = 35.0
    require_pre_eject_vision: bool = True
    require_post_eject_vision: bool = True
    calibration_id: str = "unset"
    safe_envelope: dict[str, float] = field(
        default_factory=lambda: {
            "x_min_mm": 0.0,
            "x_max_mm": 250.0,
            "y_min_mm": 0.0,
            "y_max_mm": 210.0,
            "z_min_mm": 0.0,
            "z_max_mm": 220.0,
        }
    )
    paddle: dict[str, float | None] = field(
        default_factory=lambda: {
            "offset_x_mm": None,
            "offset_y_mm": None,
            "safe_z_mm": None,
            "sweep_z_mm": None,
            "sweep_start_x_mm": None,
            "sweep_start_y_mm": None,
            "sweep_end_x_mm": None,
            "sweep_end_y_mm": None,
            "sweep_feedrate_mm_min": None,
            "park_x_mm": None,
            "park_y_mm": None,
        }
    )
    bed_sweep: dict[str, float | int | bool] = field(
        default_factory=lambda: {
            "cooldown_bed_temp_c": 40.0,
            "bed_forward_y_mm": 210.0,
            "bed_back_y_mm": 6.0,
            "head_center_x_mm": 125.0,
            "head_z_mm": 1.0,
            "object_z_offset_mm": 10.0,
            "travel_feedrate_mm_min": 6000.0,
            "z_feedrate_mm_min": 3000.0,
            "eject_feedrate_mm_min": 25000.0,
            "cycles": 2,
            "use_object_bounds": True,
            "object_x_offset_mm": 0.0,
            "home_xy_after": True,
            "disable_motors_after": True,
            "turn_off_heaters_after": True,
        }
    )
    max_feedrate_mm_min: float = 25000.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "EjectionConfig":
        raw = raw if isinstance(raw, dict) else {}
        default = cls()
        safe_envelope = dict(default.safe_envelope)
        if isinstance(raw.get("safe_envelope"), dict):
            safe_envelope.update({key: float(value) for key, value in raw["safe_envelope"].items() if value is not None})
        paddle = dict(default.paddle)
        if isinstance(raw.get("paddle"), dict):
            for key, value in raw["paddle"].items():
                paddle[key] = None if value is None else float(value)
        bed_sweep = dict(default.bed_sweep)
        if isinstance(raw.get("bed_sweep"), dict):
            for key, value in raw["bed_sweep"].items():
                if isinstance(value, bool):
                    bed_sweep[key] = value
                elif key == "cycles":
                    bed_sweep[key] = int(value)
                else:
                    bed_sweep[key] = float(value)
        return cls(
            enabled=bool(raw.get("enabled", False)),
            method=str(raw.get("method", "toolhead_paddle")),
            mode=str(raw.get("mode", "separate_job")),
            require_cooldown=bool(raw.get("require_cooldown", True)),
            max_bed_temp_c=float(raw.get("max_bed_temp_c", 35.0)),
            require_pre_eject_vision=bool(raw.get("require_pre_eject_vision", True)),
            require_post_eject_vision=bool(raw.get("require_post_eject_vision", True)),
            calibration_id=str(raw.get("calibration_id", "unset")),
            safe_envelope=safe_envelope,
            paddle=paddle,
            bed_sweep=bed_sweep,
            max_feedrate_mm_min=float(raw.get("max_feedrate_mm_min", 6000.0)),
        )

    def missing_calibration_fields(self) -> list[str]:
        required = [
            "safe_z_mm",
            "sweep_z_mm",
            "sweep_start_x_mm",
            "sweep_start_y_mm",
            "sweep_end_x_mm",
            "sweep_end_y_mm",
            "sweep_feedrate_mm_min",
            "park_x_mm",
            "park_y_mm",
        ]
        return [key for key in required if self.paddle.get(key) is None]


@dataclass(slots=True)
class PrusaBridgeConfig:
    mode: str = "test"
    provider: str = "prusa_mk4s"
    virtual_prusalink_dry_run: bool = True
    simulator: dict[str, Any] = field(default_factory=dict)
    virtual_prusalink: dict[str, Any] = field(default_factory=dict)
    test_printer_live_promotion: dict[str, Any] = field(default_factory=dict)
    live: dict[str, Any] = field(default_factory=dict)
    slicer: SlicerConfig = field(default_factory=SlicerConfig)
    ejection: EjectionConfig = field(default_factory=EjectionConfig)
    connection_memory_path: Path = DEFAULT_CONNECTION_MEMORY

    @classmethod
    def from_devices_config(cls, cfg: dict[str, Any] | None, *, repo_root: Path | None = None) -> "PrusaBridgeConfig":
        root = repo_root or REPO_ROOT
        cfg = cfg if isinstance(cfg, dict) else {}
        devices = cfg.get("devices") if isinstance(cfg.get("devices"), dict) else cfg
        printer = devices.get("printer", {}) if isinstance(devices, dict) else {}
        if not isinstance(printer, dict):
            printer = {}
        memory_path = Path(str(printer.get("connection_memory_path", DEFAULT_CONNECTION_MEMORY)))
        if not memory_path.is_absolute():
            memory_path = root / memory_path
        return cls(
            mode=str(printer.get("mode", "test")).strip().lower() or "test",
            provider=str(printer.get("provider", "prusa_mk4s")),
            virtual_prusalink_dry_run=bool(printer.get("virtual_prusalink_dry_run", True)),
            simulator=dict(printer.get("simulator", {})) if isinstance(printer.get("simulator"), dict) else {},
            virtual_prusalink=dict(printer.get("virtual_prusalink", {})) if isinstance(printer.get("virtual_prusalink"), dict) else {},
            test_printer_live_promotion=(
                dict(printer.get("test_printer_live_promotion", {}))
                if isinstance(printer.get("test_printer_live_promotion"), dict)
                else {}
            ),
            live=dict(printer.get("live", {})) if isinstance(printer.get("live"), dict) else {},
            slicer=SlicerConfig.from_dict(printer.get("slicer") if isinstance(printer.get("slicer"), dict) else {}),
            ejection=EjectionConfig.from_dict(printer.get("ejection") if isinstance(printer.get("ejection"), dict) else {}),
            connection_memory_path=memory_path,
        )

    def live_gate(self, name: str, default: bool = False) -> bool:
        return bool(self.live.get(name, default))


class PrusaConnectionMemory:
    """Small local memory file for editable PrusaLink connection information."""

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

    def ensure_template(self, live_cfg: dict[str, Any]) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        auth = live_cfg.get("auth") if isinstance(live_cfg.get("auth"), dict) else {}
        template = {
            "host": "",
            "scheme": str(live_cfg.get("scheme", "http")),
            "port": int(live_cfg.get("port", 80)),
            "storage": str(live_cfg.get("storage", "usb")),
            "auth": {
                "mode": str(auth.get("mode", "digest")),
                "username": "",
                "password": "",
                "api_key": "",
                "api_key_header": str(auth.get("api_key_header", "X-Api-Key")),
            },
            "notes": "Edit this file if printer communication info changes. Keep file permissions private.",
        }
        self.path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def save_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("connection_info") or payload.get("printer_connection")
        if not isinstance(raw, dict):
            return self.load()
        current = self.load()
        for key in ("host", "scheme", "port", "storage"):
            if key in raw and raw[key] not in (None, ""):
                current[key] = raw[key]
        if isinstance(raw.get("auth"), dict):
            auth = dict(current.get("auth", {})) if isinstance(current.get("auth"), dict) else {}
            for key in ("mode", "username", "password", "api_key", "api_key_header"):
                if key in raw["auth"] and raw["auth"][key] not in (None, ""):
                    auth[key] = raw["auth"][key]
            current["auth"] = auth
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return current

    def resolve(self, live_cfg: dict[str, Any]) -> dict[str, Any]:
        stored = self.load()
        auth_cfg = live_cfg.get("auth") if isinstance(live_cfg.get("auth"), dict) else {}
        stored_auth = stored.get("auth") if isinstance(stored.get("auth"), dict) else {}

        host = os.getenv(str(live_cfg.get("host_env", "PRUSA_HOST")), "").strip() or str(stored.get("host", "")).strip()
        scheme = str(stored.get("scheme") or live_cfg.get("scheme", "http")).strip() or "http"
        port = int(stored.get("port") or live_cfg.get("port", 80) or 80)
        storage = str(stored.get("storage") or live_cfg.get("storage", "usb")).strip() or "usb"

        mode = str(stored_auth.get("mode") or auth_cfg.get("mode", "api_key")).strip().lower()
        username = os.getenv(str(auth_cfg.get("username_env", "PRUSA_USERNAME")), "") or str(stored_auth.get("username", ""))
        password = os.getenv(str(auth_cfg.get("password_env", "PRUSA_PASSWORD")), "") or str(stored_auth.get("password", ""))
        api_key = os.getenv(str(auth_cfg.get("api_key_env", "PRUSA_API_KEY")), "") or str(stored_auth.get("api_key", ""))
        api_key_header = str(stored_auth.get("api_key_header") or auth_cfg.get("api_key_header", "X-Api-Key"))

        return {
            "host": host,
            "scheme": scheme,
            "port": port,
            "storage": storage,
            "auth": {
                "mode": mode,
                "username": username,
                "password": password,
                "api_key": api_key,
                "api_key_header": api_key_header,
            },
        }


class PrusaLinkClient:
    """PrusaLink API client with virtual transport support and live write gates."""

    def __init__(
        self,
        *,
        config: PrusaBridgeConfig,
        connection: dict[str, Any],
        transport: str = "real",
    ) -> None:
        self.config = config
        self.connection = connection
        self.transport = transport

    def _base_url(self) -> str:
        host = str(self.connection.get("host", "")).strip()
        if not host and self.transport != "virtual":
            raise ValueError("PRINTER_HOST_MISSING")
        if self.transport == "virtual" and not host:
            host = "virtual-prusalink"
        scheme = str(self.connection.get("scheme", "http")).strip() or "http"
        port = int(self.connection.get("port", 80) or 80)
        return f"{scheme}://{host}:{port}"

    def _auth_kwargs(self) -> dict[str, Any]:
        auth = self.connection.get("auth") if isinstance(self.connection.get("auth"), dict) else {}
        mode = str(auth.get("mode", "none")).strip().lower()
        if mode == "api_key":
            key = str(auth.get("api_key", ""))
            header = str(auth.get("api_key_header", "X-Api-Key"))
            return {"headers": {header: key} if key else {}}
        if mode == "basic":
            return {"auth": (str(auth.get("username", "")), str(auth.get("password", "")))}
        if mode == "digest":
            return {"auth": httpx.DigestAuth(str(auth.get("username", "")), str(auth.get("password", "")))}
        return {}

    def _timeout_budget(self, kind: str = "request") -> tuple[float, float]:
        timeouts = self.config.live.get("timeouts") if isinstance(self.config.live.get("timeouts"), dict) else {}
        connect = float(timeouts.get("connect_sec", 5))
        request = float(timeouts.get(f"{kind}_sec", timeouts.get("request_sec", 30)))
        return connect, request

    def timeout_seconds(self, kind: str = "request") -> float:
        """Return the configured timeout budget for operator-facing diagnostics."""
        return self._timeout_budget(kind)[1]

    def _timeout(self, kind: str = "request") -> httpx.Timeout:
        connect, request = self._timeout_budget(kind)
        return httpx.Timeout(timeout=request, connect=connect)

    def _virtual_response(self, command: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        virtual = self.config.virtual_prusalink
        payload = {
            "ok": True,
            "transport": "virtual_prusalink",
            "command": command,
            "provider": self.config.provider,
            "state": str(virtual.get("virtual_state", "IDLE")),
            "storage": str(virtual.get("virtual_storage", "usb")),
            "version": "virtual-prusalink-phase1",
        }
        if extra:
            payload.update(extra)
        return payload

    def _request_json(self, method: str, path: str, *, timeout_kind: str = "request", **kwargs: Any) -> dict[str, Any]:
        if self.transport == "virtual":
            return self._virtual_response(f"{method} {path}")
        url = f"{self._base_url()}{path}"
        start = time.perf_counter()
        try:
            auth_kwargs = self._auth_kwargs()
            headers = {**auth_kwargs.pop("headers", {}), **kwargs.pop("headers", {})}
            with httpx.Client(timeout=self._timeout(timeout_kind), **auth_kwargs) as client:
                resp = client.request(method, url, headers=headers, **kwargs)
            elapsed = time.perf_counter() - start
            if resp.status_code in {401, 403}:
                return {"ok": False, "failure_code": "PRINTER_UNAUTHORIZED", "status_code": resp.status_code, "elapsed_sec": elapsed}
            if resp.status_code == 507:
                return {
                    "ok": False,
                    "failure_code": "PRINTER_STORAGE_UNAVAILABLE",
                    "status_code": resp.status_code,
                    "elapsed_sec": elapsed,
                    "message": resp.text[:500],
                }
            if resp.status_code < 200 or resp.status_code >= 300:
                return {
                    "ok": False,
                    "failure_code": "PRINTER_HTTP_ERROR",
                    "status_code": resp.status_code,
                    "elapsed_sec": elapsed,
                    "message": resp.text[:500],
                }
            if not resp.content:
                return {"ok": True, "status_code": resp.status_code, "elapsed_sec": elapsed}
            try:
                payload = resp.json()
            except ValueError:
                return {"ok": False, "failure_code": "PRINTER_INVALID_JSON", "status_code": resp.status_code, "elapsed_sec": elapsed}
            return {"ok": True, "status_code": resp.status_code, "elapsed_sec": elapsed, "payload": payload}
        except ValueError as exc:
            return {"ok": False, "failure_code": str(exc) or "PRINTER_CONFIG_ERROR"}
        except httpx.TimeoutException:
            return {
                "ok": False,
                "failure_code": "PRINTER_TIMEOUT",
                "timeout_kind": timeout_kind,
                "timeout_sec": self.timeout_seconds(timeout_kind),
                "elapsed_sec": time.perf_counter() - start,
            }
        except httpx.HTTPError as exc:
            return {"ok": False, "failure_code": "PRINTER_UNREACHABLE", "message": str(exc)[:500]}

    def get_version(self) -> dict[str, Any]:
        if not self.config.live_gate("allow_status", True) and self.transport != "virtual":
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        return self._request_json("GET", "/api/version")

    def get_status(self) -> dict[str, Any]:
        if not self.config.live_gate("allow_status", True) and self.transport != "virtual":
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        return self._request_json("GET", "/api/v1/status")

    def get_storage(self) -> dict[str, Any]:
        if not self.config.live_gate("allow_status", True) and self.transport != "virtual":
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        return self._request_json("GET", "/api/v1/storage")

    def get_job(self) -> dict[str, Any]:
        if not self.config.live_gate("allow_status", True) and self.transport != "virtual":
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        return self._request_json("GET", "/api/v1/job")

    def get_transfer(self) -> dict[str, Any]:
        if self.transport == "virtual":
            return self._virtual_response("GET /api/v1/transfer")
        if not self.config.live_gate("allow_status", True):
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        return self._request_json("GET", "/api/v1/transfer")

    def get_file_metadata(self, storage: str, remote_path: str) -> dict[str, Any]:
        endpoint = self._files_endpoint(storage, remote_path)
        if self.transport == "virtual":
            return self._virtual_response(
                f"GET {endpoint}",
                {
                    "storage": self._storage_segment(storage),
                    "remote_path": self._remote_segment(remote_path),
                    "endpoint": endpoint,
                    "payload": {"name": self._remote_segment(remote_path)},
                },
            )
        if not self.config.live_gate("allow_status", True):
            return {"ok": False, "failure_code": "PRINTER_STATUS_DISABLED"}
        result = self._request_json("GET", endpoint)
        result.update({"storage": self._storage_segment(storage), "remote_path": self._remote_segment(remote_path), "endpoint": endpoint})
        return result

    @staticmethod
    def _structured_bool(value: bool) -> str:
        """RFC 8941 boolean used by the PrusaLink OpenAPI upload headers."""
        return "?1" if value else "?0"

    @staticmethod
    def _storage_segment(storage: str) -> str:
        text = str(storage or "usb").strip().strip("/")
        return text or "usb"

    @staticmethod
    def _remote_segment(remote_path: str) -> str:
        text = str(remote_path or "").strip().lstrip("/")
        return text or "specimen.gcode"

    def _files_endpoint(self, storage: str, remote_path: str) -> str:
        storage_segment = quote(self._storage_segment(storage), safe="")
        path_segment = quote(self._remote_segment(remote_path), safe="/")
        return f"/api/v1/files/{storage_segment}/{path_segment}"

    def upload_file(
        self,
        local_path: str | Path,
        storage: str,
        remote_path: str,
        *,
        overwrite: bool = False,
        print_after_upload: bool = False,
    ) -> dict[str, Any]:
        local = Path(local_path)
        if not local.exists():
            return {"ok": False, "failure_code": "UPLOAD_INPUT_MISSING", "local_path": str(local)}
        if self.transport == "virtual":
            return self._virtual_response(
                "UPLOAD",
                {
                    "status": "virtual_ack",
                    "local_path": str(local),
                    "storage": self._storage_segment(storage),
                    "remote_path": self._remote_segment(remote_path),
                    "endpoint": self._files_endpoint(storage, remote_path),
                    "overwrite": overwrite,
                    "print_after_upload": print_after_upload,
                },
            )
        if not self.config.live_gate("allow_upload", False):
            return {"ok": False, "status": "not_enabled", "failure_code": "UPLOAD_DISABLED"}
        endpoint = self._files_endpoint(storage, remote_path)
        url = f"{self._base_url()}{endpoint}"
        headers = {
            "Content-Type": "application/octet-stream",
            "Overwrite": self._structured_bool(overwrite),
            "Print-After-Upload": self._structured_bool(print_after_upload),
        }
        start = time.perf_counter()

        try:
            auth_kwargs = self._auth_kwargs()
            headers = {**auth_kwargs.pop("headers", {}), **headers}
            # Digest auth performs an initial challenge/response round-trip and
            # may need to replay the request body. A generator stream cannot be
            # replayed by httpx, so live uploads use a bytes payload.
            payload = local.read_bytes()
            with httpx.Client(timeout=self._timeout("upload"), **auth_kwargs) as client:
                resp = client.request("PUT", url, headers=headers, content=payload)
            elapsed = time.perf_counter() - start
            if resp.status_code in {401, 403}:
                return {"ok": False, "failure_code": "PRINTER_UNAUTHORIZED", "status_code": resp.status_code, "elapsed_sec": elapsed}
            if resp.status_code == 507:
                return {
                    "ok": False,
                    "failure_code": "PRINTER_STORAGE_UNAVAILABLE",
                    "status_code": resp.status_code,
                    "elapsed_sec": elapsed,
                    "message": resp.text[:500],
                }
            if resp.status_code < 200 or resp.status_code >= 300:
                return {
                    "ok": False,
                    "failure_code": "PRINTER_HTTP_ERROR",
                    "status_code": resp.status_code,
                    "elapsed_sec": elapsed,
                    "message": resp.text[:500],
                }
            return {
                "ok": True,
                "status": "uploaded",
                "status_code": resp.status_code,
                "elapsed_sec": elapsed,
                "timeout_kind": "upload",
                "timeout_sec": self.timeout_seconds("upload"),
                "local_path": str(local),
                "storage": self._storage_segment(storage),
                "remote_path": self._remote_segment(remote_path),
                "endpoint": endpoint,
                "bytes": local.stat().st_size,
                "overwrite": overwrite,
                "print_after_upload": print_after_upload,
            }
        except httpx.TimeoutException:
            return {
                "ok": False,
                "failure_code": "PRINTER_TIMEOUT",
                "timeout_kind": "upload",
                "timeout_sec": self.timeout_seconds("upload"),
                "elapsed_sec": time.perf_counter() - start,
                "local_path": str(local),
                "bytes": local.stat().st_size if local.exists() else None,
            }
        except httpx.HTTPError as exc:
            return {"ok": False, "failure_code": "PRINTER_UNREACHABLE", "message": str(exc)[:500]}

    def start_file(self, storage: str, remote_path: str) -> dict[str, Any]:
        if self.transport == "virtual":
            return self._virtual_response(
                "START",
                {
                    "status": "virtual_ack",
                    "storage": self._storage_segment(storage),
                    "remote_path": self._remote_segment(remote_path),
                    "endpoint": self._files_endpoint(storage, remote_path),
                },
            )
        if not self.config.live_gate("allow_start_print", False):
            return {"ok": False, "status": "not_enabled", "failure_code": "START_PRINT_DISABLED"}
        endpoint = self._files_endpoint(storage, remote_path)
        result = self._request_json("POST", endpoint)
        result.update({"storage": self._storage_segment(storage), "remote_path": self._remote_segment(remote_path), "endpoint": endpoint})
        return result

class PrusaSlicerRunner:
    """Safe PrusaSlicer CLI wrapper with deterministic simulation support."""

    ALLOWED_EXTENSIONS = {".stl", ".3mf", ".obj", ".amf", ".step", ".stp"}

    def __init__(self, config: SlicerConfig, *, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or REPO_ROOT

    def _output_path(self, stl_path: Path, specimen_id: str) -> Path:
        output_dir = Path(self.config.output_dir)
        if not output_dir.is_absolute():
            output_dir = self.repo_root / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", specimen_id).strip(".-") or "specimen"
        return output_dir / f"{safe_id}.gcode"

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _layer_height_from_hint(value: Any) -> float:
        text = str(value or "").strip().lower()
        match = re.search(r"(\d+)p(\d+)", text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        match = re.search(r"(?<![\d.])(\d+(?:[._]\d+)?)\s*mm", text)
        if match:
            return float(match.group(1).replace("_", "."))
        return 0.2

    @staticmethod
    def _nozzle_from_profile(value: Any) -> float:
        text = str(value or "").strip().lower()
        match = re.search(r"(\d+)p(\d+)[^a-z0-9]*nozzle", text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        match = re.search(r"(\d+(?:\.\d+)?)\s*mm[^a-z0-9]*nozzle", text)
        if match:
            return float(match.group(1))
        return 0.4

    def _profile_path(self, printer_profile: Any, slicer_profile_hint: Any) -> str:
        for key in (str(slicer_profile_hint or ""), str(printer_profile or "")):
            path = self.config.profile_map.get(key)
            if path:
                profile_path = Path(path)
                if not profile_path.is_absolute():
                    profile_path = self.repo_root / profile_path
                return str(profile_path)
        return ""

    @staticmethod
    def _bool_option(raw: dict[str, Any], key: str, default: bool) -> bool:
        value = raw.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    @staticmethod
    def _float_option(raw: dict[str, Any], key: str, default: float, *, min_value: float, max_value: float) -> float:
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            value = float(default)
        if value < min_value or value > max_value:
            return float(default)
        return value

    def _slicer_option_args(self, experiment_spec: dict[str, Any] | None) -> list[str]:
        spec = experiment_spec if isinstance(experiment_spec, dict) else {}
        print_options = spec.get("print") if isinstance(spec.get("print"), dict) else {}
        constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}
        merged_options = {**constraints, **spec, **print_options}
        args: list[str] = []
        layer_height = self._float_option(merged_options, "layer_height_mm", 0.2, min_value=0.02, max_value=1.0)
        first_layer_height = self._float_option(
            merged_options,
            "first_layer_height_mm",
            layer_height,
            min_value=0.02,
            max_value=1.0,
        )
        args.extend([f"--layer-height={layer_height:g}", f"--first-layer-height={first_layer_height:g}"])
        bed_temperature = self._float_option(merged_options, "bed_temperature_c", 60.0, min_value=0.0, max_value=120.0)
        first_layer_bed_temperature = self._float_option(
            merged_options,
            "first_layer_bed_temperature_c",
            bed_temperature,
            min_value=0.0,
            max_value=120.0,
        )
        args.extend(
            [
                f"--bed-temperature={bed_temperature:g}",
                f"--first-layer-bed-temperature={first_layer_bed_temperature:g}",
            ]
        )
        slow_first_layer = self._bool_option(merged_options, "slow_first_layer_enabled", True)
        if slow_first_layer:
            first_layer_speed = self._float_option(
                merged_options,
                "first_layer_speed_mm_s",
                10.0,
                min_value=3.0,
                max_value=60.0,
            )
            args.append(f"--first-layer-speed={first_layer_speed:g}")
        # Default is no auxiliary adhesion geometry. The GUI may enable it for
        # difficult adhesion cases, but TPMS experiment geometry should not get
        # skirt/brim/raft by accident.
        skirt_enabled = self._bool_option(merged_options, "skirt_enabled", False)
        if not skirt_enabled:
            args.extend(["--skirts=0", "--brim-width=0", "--raft-layers=0"])
        return args

    def _executable(self) -> str:
        executable = os.getenv(self.config.executable_env, "").strip()
        if executable:
            return executable
        configured = str(self.config.executable_path or "").strip()
        if not configured:
            return ""
        path = Path(configured)
        if not path.is_absolute():
            path = self.repo_root / path
        return str(path)

    def _settings_snapshot(
        self,
        *,
        source: Path | None,
        output_path: Path | None,
        simulate: bool,
        specimen_id: str,
        printer_profile: Any,
        material: Any,
        slicer_profile_hint: Any,
        experiment_spec: dict[str, Any] | None,
    ) -> dict[str, Any]:
        spec = experiment_spec if isinstance(experiment_spec, dict) else {}
        output_dir = Path(self.config.output_dir)
        if not output_dir.is_absolute():
            output_dir = self.repo_root / output_dir
        executable = self._executable()
        executable_preview = executable or f"${self.config.executable_env}"
        source_preview = str(source) if source is not None else "{stl_path}"
        output_preview = str(output_path) if output_path is not None else str(output_dir / f"{specimen_id}.gcode")
        profile_path = self._profile_path(printer_profile, slicer_profile_hint)
        argv_preview = [
            item.format(
                executable=executable_preview,
                output_path=output_preview,
                stl_path=source_preview,
                profile_path=profile_path,
            )
            for item in self.config.command_template
        ] + self._slicer_option_args(spec)
        constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}
        print_options = spec.get("print") if isinstance(spec.get("print"), dict) else {}
        merged_settings = {**constraints, **spec, **print_options}
        layer_height = self._float_or_none(merged_settings.get("layer_height_mm"))
        if layer_height is None:
            layer_height = self._layer_height_from_hint(slicer_profile_hint)
        first_layer_height = self._float_or_none(merged_settings.get("first_layer_height_mm"))
        if first_layer_height is None:
            first_layer_height = layer_height
        nozzle_diameter = self._float_or_none(merged_settings.get("nozzle_diameter_mm"))
        if nozzle_diameter is None:
            nozzle_diameter = self._nozzle_from_profile(printer_profile)
        bed_temperature = self._float_option(merged_settings, "bed_temperature_c", 60.0, min_value=0.0, max_value=120.0)
        first_layer_bed_temperature = self._float_option(
            merged_settings,
            "first_layer_bed_temperature_c",
            bed_temperature,
            min_value=0.0,
            max_value=120.0,
        )
        legacy_cap = self._bool_option(spec, "top_bottom_cap", False)
        top_cap_enabled = self._bool_option(spec, "top_cap_enabled", legacy_cap)
        bottom_cap_enabled = self._bool_option(spec, "bottom_cap_enabled", legacy_cap)
        return {
            "enabled": bool(self.config.enabled),
            "simulated": bool(simulate),
            "input_model_path": str(source) if source is not None else "",
            "input_model_format": source.suffix.lower() if source is not None else "",
            "output_gcode_path": str(output_path) if output_path is not None else None,
            "output_dir": str(output_dir),
            "executable_env": self.config.executable_env,
            "executable_path": self.config.executable_path,
            "executable_configured": bool(executable),
            "command_template": list(self.config.command_template),
            "resolved_command": argv_preview,
            "timeout_sec": float(self.config.timeout_sec),
            "profile_path": profile_path,
            "printer_profile": str(printer_profile or ""),
            "material": str(material or ""),
            "slicer_profile_hint": str(slicer_profile_hint or ""),
            "layer_height_mm": layer_height,
            "first_layer_height_mm": first_layer_height,
            "nozzle_diameter_mm": nozzle_diameter,
            "bed_temperature_c": bed_temperature,
            "first_layer_bed_temperature_c": first_layer_bed_temperature,
            "slow_first_layer_enabled": self._bool_option(
                merged_settings,
                "slow_first_layer_enabled",
                True,
            ),
            "first_layer_speed_mm_s": self._float_option(
                merged_settings,
                "first_layer_speed_mm_s",
                10.0,
                min_value=3.0,
                max_value=60.0,
            ),
            "wall_thickness_mm": self._float_or_none(spec.get("wall_thickness_mm")),
            "cell_size_mm": self._float_or_none(spec.get("cell_size_mm")),
            "relative_density": self._float_or_none(spec.get("relative_density")),
            "expected_mass_g": self._float_or_none(spec.get("expected_mass_g")),
            "expected_print_time_min": self._float_or_none(spec.get("expected_print_time_min")),
            "skirt_enabled": self._bool_option(spec, "skirt_enabled", False),
            "top_cap_enabled": top_cap_enabled,
            "bottom_cap_enabled": bottom_cap_enabled,
            "top_bottom_cap": bool(top_cap_enabled or bottom_cap_enabled),
            "skin_thickness_mm": self._float_or_none(spec.get("skin_thickness_mm")),
        }

    def slice(
        self,
        stl_path: str | Path | None,
        *,
        specimen_id: str,
        simulate: bool,
        printer_profile: Any = "",
        material: Any = "",
        slicer_profile_hint: Any = "",
        experiment_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not stl_path:
            settings = self._settings_snapshot(
                source=None,
                output_path=None,
                simulate=simulate,
                specimen_id=specimen_id,
                printer_profile=printer_profile,
                material=material,
                slicer_profile_hint=slicer_profile_hint,
                experiment_spec=experiment_spec,
            )
            return {"ok": False, "failure_code": "SLICER_INPUT_MISSING", "slicer_settings": settings}
        source = Path(stl_path)
        output_path = self._output_path(source, specimen_id)
        settings = self._settings_snapshot(
            source=source,
            output_path=output_path,
            simulate=simulate,
            specimen_id=specimen_id,
            printer_profile=printer_profile,
            material=material,
            slicer_profile_hint=slicer_profile_hint,
            experiment_spec=experiment_spec,
        )
        if not source.exists():
            return {"ok": False, "failure_code": "SLICER_INPUT_MISSING", "stl_path": str(source), "slicer_settings": settings}
        if source.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return {"ok": False, "failure_code": "SLICER_BAD_INPUT_EXTENSION", "stl_path": str(source), "slicer_settings": settings}
        if simulate:
            output_path.write_text(
                f"; VIRTUAL PRUSASLICER OUTPUT\n; specimen_id={specimen_id}\n; source={source}\nM84\n",
                encoding="utf-8",
            )
            return {
                "ok": True,
                "sliced_path": str(output_path),
                "stdout": "virtual slicer completed",
                "stderr": "",
                "elapsed_sec": 0.0,
                "failure_code": None,
                "simulated": True,
                "slicer_settings": settings,
            }
        if not self.config.enabled:
            return {"ok": False, "failure_code": "SLICER_DISABLED", "sliced_path": None, "slicer_settings": settings}
        executable = self._executable()
        if not executable:
            return {"ok": False, "failure_code": "SLICER_EXECUTABLE_NOT_CONFIGURED", "slicer_settings": settings}
        if not Path(executable).exists() and "/" in executable:
            return {
                "ok": False,
                "failure_code": "SLICER_EXECUTABLE_NOT_FOUND",
                "executable": executable,
                "slicer_settings": settings,
            }
        argv = [
            item.format(
                executable=executable,
                output_path=str(output_path),
                stl_path=str(source),
                profile_path=self._profile_path(printer_profile, slicer_profile_hint),
            )
            for item in self.config.command_template
        ] + self._slicer_option_args(experiment_spec)
        start = time.perf_counter()
        try:
            result = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.config.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "sliced_path": str(output_path),
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "elapsed_sec": self.config.timeout_sec,
                "failure_code": "SLICER_TIMEOUT",
                "slicer_settings": settings,
            }
        elapsed = time.perf_counter() - start
        return {
            "ok": result.returncode == 0 and output_path.exists(),
            "sliced_path": str(output_path) if output_path.exists() else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_sec": elapsed,
            "failure_code": None if result.returncode == 0 and output_path.exists() else "SLICER_FAILED",
            "slicer_settings": settings,
        }


class GCodeSafetyValidator:
    """Strict validator for deterministic ejection G-code."""

    ALLOWED_COMMANDS = {"G0", "G1", "G4", "G28", "G90", "G91", "M73", "M84", "M104", "M107", "M140", "M190", "M400"}
    PARAM_PATTERN = re.compile(r"([A-Z])([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")

    def __init__(self, ejection: EjectionConfig) -> None:
        self.ejection = ejection

    def validate_ejection_gcode(self, gcode: str) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        env = self.ejection.safe_envelope
        command_lines: list[tuple[int, str, str]] = []
        for line_no, raw_line in enumerate(gcode.splitlines(), start=1):
            line = raw_line.split(";", 1)[0].strip()
            if not line:
                continue
            command = line.split()[0].upper()
            command_lines.append((line_no, command, raw_line))
            if command not in self.ALLOWED_COMMANDS:
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_COMMAND", "line_text": raw_line})
                continue
            param_text = line[len(command) :]
            values = {axis: float(value) for axis, value in self.PARAM_PATTERN.findall(param_text)}
            if "E" in values:
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_EXTRUSION", "line_text": raw_line})
            if command in {"M104", "M140"} and float(values.get("S", 0.0)) != 0.0:
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_HEATING", "line_text": raw_line})
            if command == "M190":
                target = values.get("R", values.get("S"))
                if target is None:
                    violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_HEATING", "line_text": raw_line})
                elif float(target) > float(self.ejection.max_bed_temp_c):
                    violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_HEATING", "line_text": raw_line})
            if "X" in values and not float(env["x_min_mm"]) <= values["X"] <= float(env["x_max_mm"]):
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_COORDINATE", "axis": "X", "value": values["X"]})
            if "Y" in values and not float(env["y_min_mm"]) <= values["Y"] <= float(env["y_max_mm"]):
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_COORDINATE", "axis": "Y", "value": values["Y"]})
            if "Z" in values and not float(env["z_min_mm"]) <= values["Z"] <= float(env["z_max_mm"]):
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_COORDINATE", "axis": "Z", "value": values["Z"]})
            if "F" in values and values["F"] > float(self.ejection.max_feedrate_mm_min):
                violations.append({"line": line_no, "failure_code": "GCODE_UNSAFE_FEEDRATE", "value": values["F"]})
        return {
            "ok": not violations,
            "failure_code": None if not violations else str(violations[0]["failure_code"]),
            "violations": violations,
        }

    @staticmethod
    def validate_print_gcode(path: str | Path | None) -> dict[str, Any]:
        if not path:
            return {"ok": False, "failure_code": "GCODE_INPUT_MISSING"}
        gcode_path = Path(path)
        if not gcode_path.exists():
            return {"ok": False, "failure_code": "GCODE_INPUT_MISSING", "path": str(gcode_path)}
        return {"ok": True, "failure_code": None, "violations": []}


@dataclass(slots=True)
class GCodeObjectBounds:
    """Extrusion-derived object bounds from a sliced print G-code file."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    extrusion_move_count: int

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_min_mm": round(self.x_min, 4),
            "x_max_mm": round(self.x_max, 4),
            "y_min_mm": round(self.y_min, 4),
            "y_max_mm": round(self.y_max, 4),
            "z_min_mm": round(self.z_min, 4),
            "z_max_mm": round(self.z_max, 4),
            "center_x_mm": round(self.center_x, 4),
            "center_y_mm": round(self.center_y, 4),
            "extrusion_move_count": int(self.extrusion_move_count),
        }


class GCodeObjectBoundsExtractor:
    """Infer printed object bounds from extrusion moves, not slicer comments."""

    PARAM_PATTERN = re.compile(r"([A-Z])([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")

    @classmethod
    def from_text(cls, gcode: str) -> GCodeObjectBounds | None:
        absolute_xyz = True
        absolute_e = True
        current: dict[str, float | None] = {"X": None, "Y": None, "Z": None}
        last_abs_e = 0.0
        points: list[tuple[float, float, float]] = []
        extrusion_moves = 0

        for raw_line in gcode.splitlines():
            line = raw_line.split(";", 1)[0].strip()
            if not line:
                continue
            command = line.split()[0].upper()
            if command == "G90":
                absolute_xyz = True
                continue
            if command == "G91":
                absolute_xyz = False
                continue
            if command == "M82":
                absolute_e = True
                continue
            if command == "M83":
                absolute_e = False
                continue
            values = {axis: float(value) for axis, value in cls.PARAM_PATTERN.findall(line)}
            if command == "G92":
                if "E" in values:
                    last_abs_e = values["E"]
                for axis in ("X", "Y", "Z"):
                    if axis in values:
                        current[axis] = values[axis]
                continue
            if command not in {"G0", "G1"}:
                continue
            previous = dict(current)
            for axis in ("X", "Y", "Z"):
                if axis not in values:
                    continue
                if absolute_xyz or current[axis] is None:
                    current[axis] = values[axis]
                else:
                    current[axis] = float(current[axis] or 0.0) + values[axis]

            extruding = False
            if "E" in values:
                if absolute_e:
                    extruding = values["E"] > last_abs_e + 1e-7
                    last_abs_e = values["E"]
                else:
                    extruding = values["E"] > 1e-7
            if not extruding or current["X"] is None or current["Y"] is None:
                continue

            z_value = float(current["Z"] if current["Z"] is not None else previous.get("Z") or 0.0)
            for item in (previous, current):
                if item.get("X") is None or item.get("Y") is None:
                    continue
                points.append((float(item["X"]), float(item["Y"]), z_value))
            extrusion_moves += 1

        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]
        return GCodeObjectBounds(
            x_min=min(xs),
            x_max=max(xs),
            y_min=min(ys),
            y_max=max(ys),
            z_min=min(zs),
            z_max=max(zs),
            extrusion_move_count=extrusion_moves,
        )

    @classmethod
    def from_path(cls, path: str | Path | None) -> GCodeObjectBounds | None:
        if not path:
            return None
        gcode_path = Path(path)
        if not gcode_path.exists():
            return None
        return cls.from_text(gcode_path.read_text(encoding="utf-8", errors="replace"))


class PaddleEjectionRoutineBuilder:
    """Build deterministic toolhead-paddle ejection G-code from calibration config."""

    def __init__(self, ejection: EjectionConfig) -> None:
        self.ejection = ejection
        self.validator = GCodeSafetyValidator(ejection)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def build(
        self,
        *,
        object_bounds: GCodeObjectBounds | None = None,
        include_temperature_commands: bool = True,
    ) -> dict[str, Any]:
        if self.ejection.method == "bed_sweep":
            return self._build_bed_sweep(
                object_bounds=object_bounds,
                include_temperature_commands=include_temperature_commands,
            )
        if self.ejection.method != "toolhead_paddle":
            return {"ok": False, "failure_code": "EJECTION_METHOD_UNSUPPORTED", "gcode": ""}
        missing = self.ejection.missing_calibration_fields()
        if missing:
            return {"ok": False, "failure_code": "EJECTION_NOT_CALIBRATED", "missing_fields": missing, "gcode": ""}
        p = self.ejection.paddle
        lines = [
                "; AUTO-GENERATED PADDLE EJECTION ROUTINE",
                f"; calibration_id={self.ejection.calibration_id}",
                "M400",
                "G90",
                f"G1 Z{p['safe_z_mm']} F1200",
                f"G1 X{p['sweep_start_x_mm']} Y{p['sweep_start_y_mm']} F3000",
                f"G1 Z{p['sweep_z_mm']} F600",
                f"G1 X{p['sweep_end_x_mm']} Y{p['sweep_end_y_mm']} F{p['sweep_feedrate_mm_min']}",
                f"G1 Z{p['safe_z_mm']} F1200",
                f"G1 X{p['park_x_mm']} Y{p['park_y_mm']} F3000",
                "M400",
                "",
            ]
        if include_temperature_commands:
            lines[3:3] = ["M104 S0", "M140 S0"]
        gcode = "\n".join(lines)
        validation = self.validator.validate_ejection_gcode(gcode)
        return {"ok": bool(validation["ok"]), "failure_code": validation["failure_code"], "gcode": gcode, "validation": validation}

    def _build_bed_sweep(
        self,
        *,
        object_bounds: GCodeObjectBounds | None = None,
        include_temperature_commands: bool = True,
    ) -> dict[str, Any]:
        p = self.ejection.bed_sweep
        cycles = max(1, int(p.get("cycles", 2)))
        env = self.ejection.safe_envelope
        configured_head_x = float(p["head_center_x_mm"])
        configured_head_z = float(p["head_z_mm"])
        object_x_offset = float(p.get("object_x_offset_mm", 0.0) or 0.0)
        object_z_offset = float(p.get("object_z_offset_mm", 10.0) or 10.0)
        object_bounds_payload = object_bounds.to_dict() if object_bounds is not None else None
        head_x = configured_head_x
        head_x_source = "configured"
        head_z = configured_head_z
        head_z_source = "configured"
        if bool(p.get("use_object_bounds", True)) and object_bounds is not None:
            head_x = self._clamp(
                float(object_bounds.center_x) + object_x_offset,
                float(env["x_min_mm"]),
                float(env["x_max_mm"]),
            )
            head_x_source = "gcode_object_bounds"
            head_z = self._clamp(
                max(1.0, float(object_bounds.z_max) - object_z_offset),
                max(1.0, float(env["z_min_mm"])),
                float(env["z_max_mm"]),
            )
            head_z_source = "gcode_object_top_minus_offset"
        lines = [
            "; AUTO-GENERATED BED-SWEEP EJECTION ROUTINE",
            "; adapted_for=Prusa MK4S Buddy firmware",
            f"; calibration_id={self.ejection.calibration_id}",
            f"; object_bounds_source={head_x_source}",
            f"; resolved_head_x_mm={head_x:g}",
            f"; resolved_head_z_mm={head_z:g}",
        ]
        if object_bounds_payload:
            lines.append(
                "; object_bounds_mm="
                + json.dumps(object_bounds_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            )
        lines.append("M400")
        if include_temperature_commands:
            lines.append(f"M190 R{float(p['cooldown_bed_temp_c']):g}")
        lines.extend(
            [
                "G90",
                f"G0 Y{float(p['bed_forward_y_mm']):g} F{float(p['travel_feedrate_mm_min']):g}",
                "M73 P99 R0",
                "M73 Q99 S0",
                f"G0 X{head_x:g} F{float(p['travel_feedrate_mm_min']):g}",
                f"G0 Z{head_z:g} F{float(p['z_feedrate_mm_min']):g}",
            ]
        )
        for cycle in range(cycles):
            lines.append(f"G0 Y{float(p['bed_back_y_mm']):g} F{float(p['eject_feedrate_mm_min']):g}")
            if cycle < cycles - 1:
                lines.append(f"G0 Y{float(p['bed_forward_y_mm']):g} F{float(p['travel_feedrate_mm_min']):g}")
        if bool(p.get("home_xy_after", True)):
            lines.append("G28 X Y")
        if bool(p.get("disable_motors_after", True)):
            lines.append("M84 X Y E")
        if include_temperature_commands and bool(p.get("turn_off_heaters_after", True)):
            lines.extend(["M104 S0", "M140 S0"])
        lines.extend(
            [
                "M400",
                "M73 P100 R0",
                "M73 Q100 S0",
            ]
        )
        lines.append("")
        gcode = "\n".join(lines)
        validation = self.validator.validate_ejection_gcode(gcode)
        return {
            "ok": bool(validation["ok"]),
            "failure_code": validation["failure_code"],
            "gcode": gcode,
            "validation": validation,
            "resolved": {
                "head_x_mm": round(head_x, 4),
                "head_x_source": head_x_source,
                "configured_head_x_mm": configured_head_x,
                "head_z_mm": round(head_z, 4),
                "head_z_source": head_z_source,
                "configured_head_z_mm": configured_head_z,
                "object_z_offset_mm": object_z_offset,
                "object_x_offset_mm": object_x_offset,
                "object_bounds": object_bounds_payload,
                "temperature_commands_included": bool(include_temperature_commands),
            },
        }


class PrinterAgenticWorkflow:
    """Deterministic printer.prepare workflow with test, virtual, and live paths."""

    def __init__(self, config: PrusaBridgeConfig, *, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or REPO_ROOT
        self.connection_memory = PrusaConnectionMemory(config.connection_memory_path)
        self.slicer = PrusaSlicerRunner(config.slicer, repo_root=self.repo_root)
        self.ejection_builder = PaddleEjectionRoutineBuilder(config.ejection)

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        runtime_mode = str(payload.get("runtime_mode") or self.config.mode or "test").strip().lower()
        if runtime_mode in {"live", "production"}:
            return self._prepare_live(payload)
        return self._prepare_test(payload)

    def health(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        mode = str(payload.get("runtime_mode") or self.config.mode or "test").strip().lower()
        if mode == "live":
            connection = self.connection_memory.resolve(self.config.live)
            if not str(connection.get("host", "")).strip():
                self.connection_memory.ensure_template(self.config.live)
                return {
                    "ok": False,
                    "mode": "live",
                    "provider": self.config.provider,
                    "reachable": False,
                    "state": None,
                    "allow_upload": self.config.live_gate("allow_upload", False),
                    "allow_start_print": self.config.live_gate("allow_start_print", False),
                    "allow_ejection": self.config.live_gate("allow_ejection", False),
                    "failure_code": "PRINTER_CONNECTION_INFO_REQUIRED",
                    "requires_connection_info": True,
                    "connection_memory_path": str(self.connection_memory.path),
                }
            client = PrusaLinkClient(config=self.config, connection=connection, transport="real")
            status = client.get_status()
            return {
                "ok": bool(status.get("ok")),
                "mode": "live",
                "provider": self.config.provider,
                "reachable": bool(status.get("ok")),
                "state": self._state_from_status(status),
                "allow_upload": self.config.live_gate("allow_upload", False),
                "allow_start_print": self.config.live_gate("allow_start_print", False),
                "allow_ejection": self.config.live_gate("allow_ejection", False),
                "failure_code": status.get("failure_code"),
            }
        return {
            "ok": True,
            "mode": "test",
            "provider": self.config.provider,
            "reachable": True,
            "state": "VIRTUAL_PRUSALINK_READY" if self.config.virtual_prusalink_dry_run else "SIMULATED_READY",
            "allow_upload": False,
            "allow_start_print": False,
            "allow_ejection": False,
            "failure_code": None,
        }

    def _prepare_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        selected_path = self._selected_test_printer_path(payload)
        if selected_path == "virtual_bridge":
            result = self._prepare_virtual(payload, promoted=True, simulate_slicer=False)
            result.setdefault("operator_messages", []).append(
                "Specimen Making Agent selected virtual PrusaLink bridge after real PrusaSlicer slicing."
            )
            return result
        if selected_path == "installed_printer":
            return self._prepare_test_installed_printer(payload)
        if selected_path == "physical_print":
            return self._prepare_test_physical_print(payload)
        if self._test_live_promotion_enabled(payload):
            return self._prepare_test_virtual_or_promoted(payload)
        if self.config.virtual_prusalink_dry_run:
            return self._prepare_virtual(payload, promoted=False)
        return self._prepare_simple_sim(payload)

    @staticmethod
    def _selected_test_printer_path(payload: dict[str, Any]) -> str:
        text = str(
            payload.get("test_printer_path")
            or payload.get("printer_test_path")
            or payload.get("printer_bridge_mode")
            or ""
        ).strip().lower().replace("-", "_").replace(" ", "_")
        if any(token in text for token in ("virtual", "가상", "bridge", "브릿지", "브리지")):
            return "virtual_bridge"
        compact = text.replace("_", "")
        if any(token in compact for token in ("actualprint", "physicalprint", "startprint", "실제출력", "출력")):
            return "physical_print"
        if any(token in text for token in ("installed", "real", "prusa", "printer", "설치", "실제", "프린터")):
            return "installed_printer"
        return ""

    def _test_live_promotion_enabled(self, payload: dict[str, Any]) -> bool:
        cfg = self.config.test_printer_live_promotion
        if "allow_test_printer_live" in payload:
            return bool(payload.get("allow_test_printer_live"))
        return bool(cfg.get("enabled", False))

    def _prepare_test_virtual_or_promoted(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = ["Specimen stage reached printer.prepare; checking printer connectivity before selecting printer path."]
        transport = str(self.config.test_printer_live_promotion.get("transport", "virtual")).strip().lower()
        if transport == "real" and bool(self.config.test_printer_live_promotion.get("allow_real_network_in_test", False)):
            connection = self.connection_memory.resolve(self.config.live)
            client = PrusaLinkClient(config=self.config, connection=connection, transport="real")
            status = client.get_status()
            if status.get("ok"):
                result = self._prepare_live(payload, force_transport="real", runtime_mode_override="test_printer_live")
                result.setdefault("operator_messages", []).extend(messages)
                result["printer_path"] = "test_printer_live"
                return result
            messages.append("Printer connectivity unavailable; falling back to virtual PrusaLink bridge.")
        else:
            messages.append("Using virtual PrusaLink connectivity bridge for test-mode printer boundary validation.")
        result = self._prepare_virtual(payload, promoted=True)
        result.setdefault("operator_messages", []).extend(messages)
        return result

    def _prepare_test_installed_printer(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = ["Specimen Making Agent selected installed-printer PrusaLink communication test."]
        self.connection_memory.save_from_payload(payload)
        connection = self.connection_memory.resolve(self.config.live)
        if not str(connection.get("host", "")).strip():
            self.connection_memory.ensure_template(self.config.live)
            result = self._connection_required_result(
                mode="test_printer_live",
                printer_path="test_printer_live",
                specimen_id=self._specimen_id(payload),
            )
            result.setdefault("operator_messages", []).extend(messages)
            return result

        client = PrusaLinkClient(config=self.config, connection=connection, transport="real")
        status = client.get_status()
        if not status.get("ok"):
            return {
                "ok": False,
                "tool": "printer.prepare",
                "mode": "test_printer_live",
                "printer_path": "test_printer_live",
                "status": "communication_failed",
                "specimen_id": self._specimen_id(payload),
                "failure_code": status.get("failure_code", "PRINTER_COMMUNICATION_FAILED"),
                "printer": {"provider": self.config.provider, "state": None, "status": status},
                "print_result": {"status": "not_started", "failure_code": status.get("failure_code")},
                "ejection_result": {"status": "disabled", "attempts": 0, "failure_code": None},
                "step_trace": [self._step("PRUSALINK_STATUS", "blocked", status.get("failure_code"))],
                "operator_messages": messages,
            }

        result = self._run_pipeline(
            payload,
            client=client,
            runtime_mode="test_printer_live",
            simulate_slicer=False,
            allow_physical=False,
            specimen_id=self._specimen_id(payload),
        )
        result.setdefault("operator_messages", []).extend(messages)
        result["printer_path"] = "test_printer_live"
        return result

    def _prepare_test_physical_print(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = ["Specimen Making Agent selected actual print for the test-mode generated specimen."]
        self.connection_memory.save_from_payload(payload)
        connection = self.connection_memory.resolve(self.config.live)
        if not str(connection.get("host", "")).strip():
            self.connection_memory.ensure_template(self.config.live)
            result = self._connection_required_result(
                mode="test_printer_physical_print",
                printer_path="test_printer_physical_print",
                specimen_id=self._specimen_id(payload),
            )
            result.setdefault("operator_messages", []).extend(messages)
            return result
        client = PrusaLinkClient(config=self.config, connection=connection, transport="real")
        print_request = dict(payload.get("print", {})) if isinstance(payload.get("print"), dict) else {}
        print_request.update(
            {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
            }
        )
        physical_payload = dict(payload)
        physical_payload["print"] = print_request
        result = self._run_pipeline(
            physical_payload,
            client=client,
            runtime_mode="test_printer_physical_print",
            simulate_slicer=False,
            allow_physical=True,
            specimen_id=self._specimen_id(payload),
        )
        result.setdefault("operator_messages", []).extend(messages)
        result["printer_path"] = "test_printer_physical_print"
        return result

    def _prepare_simple_sim(self, payload: dict[str, Any]) -> dict[str, Any]:
        specimen_id = self._specimen_id(payload)
        stl_path = payload.get("stl_path")
        trace = [self._step("PRECHECK", "ok"), self._step("RESOLVE_STL", "ok"), self._step("DONE", "ok")]
        slicer_settings = self.slicer._settings_snapshot(
            source=Path(stl_path) if stl_path else None,
            output_path=None,
            simulate=True,
            specimen_id=specimen_id,
            printer_profile=payload.get("printer_profile"),
            material=payload.get("material"),
            slicer_profile_hint=payload.get("slicer_profile_hint"),
            experiment_spec=payload.get("experiment_spec") if isinstance(payload.get("experiment_spec"), dict) else {},
        )
        return {
            "ok": True,
            "tool": "printer.prepare",
            "mode": "test",
            "printer_path": "simulator",
            "status": "prepared",
            "specimen_id": specimen_id,
            "stl_path": stl_path,
            "sliced_path": None,
            "slicer_settings": slicer_settings,
            "slicer_result": {"ok": True, "sliced_path": None, "simulated": True, "failure_code": None},
            "gcode_validation": {"ok": True, "failure_code": None, "violations": []},
            "printer": {"provider": self.config.provider, "host_configured": False, "state": "SIMULATED_READY"},
            "print_result": {"status": "prepared", "failure_code": None},
            "ejection_result": {"status": "disabled", "attempts": 0, "failure_code": None},
            "step_trace": trace,
            "artifacts": {"stl_path": stl_path},
            "failure_code": None,
        }

    def _prepare_virtual(self, payload: dict[str, Any], *, promoted: bool, simulate_slicer: bool = True) -> dict[str, Any]:
        specimen_id = self._specimen_id(payload)
        connection = {"host": "virtual-prusalink", "scheme": "http", "port": 80, "storage": "usb", "auth": {"mode": "none"}}
        client = PrusaLinkClient(config=self.config, connection=connection, transport="virtual")
        return self._run_pipeline(
            payload,
            client=client,
            runtime_mode="test_printer_live_virtual" if promoted else "test_virtual_prusalink",
            simulate_slicer=simulate_slicer,
            allow_physical=False,
            specimen_id=specimen_id,
        )

    def _prepare_live(
        self,
        payload: dict[str, Any],
        *,
        force_transport: str | None = None,
        runtime_mode_override: str | None = None,
    ) -> dict[str, Any]:
        transport = force_transport or str(self.config.live.get("transport", "real")).strip().lower() or "real"
        self.connection_memory.save_from_payload(payload)
        connection = self.connection_memory.resolve(self.config.live)
        if not str(connection.get("host", "")).strip() and transport != "virtual":
            self.connection_memory.ensure_template(self.config.live)
            return self._connection_required_result(
                mode=runtime_mode_override or "live",
                printer_path="live",
                specimen_id=self._specimen_id(payload),
            )
        client = PrusaLinkClient(config=self.config, connection=connection, transport=transport)
        return self._run_pipeline(
            payload,
            client=client,
            runtime_mode=runtime_mode_override or "live",
            simulate_slicer=transport == "virtual",
            allow_physical=True,
            specimen_id=self._specimen_id(payload),
        )

    def _run_pipeline(
        self,
        payload: dict[str, Any],
        *,
        client: PrusaLinkClient,
        runtime_mode: str,
        simulate_slicer: bool,
        allow_physical: bool,
        specimen_id: str,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        def record_step(step: str, status: str, detail: Any | None = None) -> dict[str, Any]:
            item = self._step(step, status, detail)
            trace.append(item)
            self._emit_step_event(payload, runtime_mode=runtime_mode, specimen_id=specimen_id, step=item)
            return item

        stl_path = payload.get("stl_path")
        record_step("PRECHECK", "ok")
        record_step("RESOLVE_STL", "ok" if stl_path else "warning", None if stl_path else "missing stl_path")

        status = client.get_status()
        storage = client.get_storage()
        job = client.get_job()
        transfer = client.get_transfer()
        print_request = payload.get("print") if isinstance(payload.get("print"), dict) else {}
        storage_name = str(print_request.get("storage") or client.connection.get("storage") or "usb")
        should_start = bool(print_request.get("start_immediately", False))
        set_ready_result: dict[str, Any] | None = None
        storage_check = self._storage_ready(storage, storage_name, virtual=client.transport == "virtual")
        record_step(
            "PRUSALINK_STORAGE",
            "ok" if storage_check.get("ok") else "blocked",
            storage_check.get("failure_code"),
        )
        if not storage_check.get("ok"):
            return self._failed_result(
                runtime_mode,
                specimen_id,
                stl_path,
                trace,
                storage_check.get("failure_code"),
                status=status,
                storage=storage,
                job=job,
                transfer=transfer,
            )
        record_step("VALIDATE_MESH", "ok")

        experiment_spec = payload.get("experiment_spec") if isinstance(payload.get("experiment_spec"), dict) else {}
        slice_result = self.slicer.slice(
            stl_path,
            specimen_id=specimen_id,
            simulate=simulate_slicer,
            printer_profile=payload.get("printer_profile"),
            material=payload.get("material"),
            slicer_profile_hint=payload.get("slicer_profile_hint"),
            experiment_spec=experiment_spec,
        )
        slicer_settings = slice_result.get("slicer_settings", {})
        record_step("SLICE", "ok" if slice_result.get("ok") else "blocked", slice_result.get("failure_code"))
        if not slice_result.get("ok"):
            return self._failed_result(
                runtime_mode,
                specimen_id,
                stl_path,
                trace,
                slice_result.get("failure_code"),
                status=status,
                storage=storage,
                job=job,
                transfer=transfer,
                slice_result=slice_result,
            )

        gcode_validation = GCodeSafetyValidator.validate_print_gcode(slice_result.get("sliced_path"))
        record_step("VALIDATE_GCODE", "ok" if gcode_validation.get("ok") else "blocked", gcode_validation.get("failure_code"))
        if not gcode_validation.get("ok"):
            return self._failed_result(
                runtime_mode,
                specimen_id,
                stl_path,
                trace,
                gcode_validation.get("failure_code"),
                status=status,
                storage=storage,
                job=job,
                transfer=transfer,
                slice_result=slice_result,
                gcode_validation=gcode_validation,
            )

        ejection_result = self._prepare_append_ejection(
            payload,
            client=client,
            allow_physical=allow_physical,
            printer_status=status,
            slice_result=slice_result,
        )
        if ejection_result is not None:
            record_step("APPEND_EJECTION_GCODE", ejection_result.get("status", "blocked"), ejection_result.get("failure_code"))
            if ejection_result.get("status") == "appended_to_print_gcode":
                appended_path = ejection_result.get("appended_gcode_path")
                if appended_path:
                    slice_result["sliced_path"] = appended_path
                    slicer_settings["output_gcode_path"] = appended_path

        remote_path = f"{specimen_id}.gcode"
        if client.transport != "virtual" and allow_physical and should_start and self.config.live_gate("allow_start_print", False):
            record_step("READY_FOR_START", "active", "waiting for any previous job to clear before short-name start")
            set_ready_result = self._ensure_ready_for_new_start(client, status, job)
            record_step(
                "READY_FOR_START",
                "ok" if set_ready_result.get("ok") else "blocked",
                set_ready_result.get("failure_code") or set_ready_result.get("status"),
            )
            if not set_ready_result.get("ok"):
                return self._failed_result(
                    runtime_mode,
                    specimen_id,
                    stl_path,
                    trace,
                    set_ready_result.get("failure_code", "PRINTER_JOB_ACTIVE"),
                    status=status,
                    storage=storage,
                    job=job,
                    transfer=transfer,
                )
            status = client.get_status()
            job = client.get_job()
            transfer = client.get_transfer()
        if client.transport != "virtual" and not allow_physical:
            upload = {"ok": False, "status": "not_enabled", "failure_code": "PHYSICAL_WRITE_DISABLED_IN_TEST"}
        else:
            if client.transport != "virtual":
                record_step(
                    "UPLOAD_TRANSFER",
                    "active",
                    self._upload_transfer_detail(slice_result.get("sliced_path"), client.timeout_seconds("upload")),
                )
            upload = client.upload_file(
                slice_result["sliced_path"],
                storage_name,
                remote_path,
                overwrite=bool(print_request.get("overwrite", False)),
            )
        upload_status = "ok" if upload.get("ok") else str(upload.get("status") or "blocked")
        record_step("UPLOAD", upload_status, upload.get("failure_code"))

        start_result = {"ok": False, "status": "not_enabled", "failure_code": "START_PRINT_DISABLED"}
        transfer_wait: dict[str, Any] | None = None
        if upload.get("ok") and allow_physical and should_start and self.config.live_gate("allow_start_print", False):
            if client.transport != "virtual":
                record_step("WAIT_UPLOAD_READY", "active", "waiting for PrusaLink transfer to become idle before short-name start")
                transfer_wait = self._wait_for_transfer_idle(client)
                record_step(
                    "WAIT_UPLOAD_READY",
                    "ok" if transfer_wait.get("ok") else "blocked",
                    transfer_wait.get("failure_code") or transfer_wait.get("status"),
                )
            if transfer_wait is None or transfer_wait.get("ok"):
                start_result = self._start_file_with_retry(client, storage_name, remote_path, require_metadata_resolution=True)
            else:
                start_result = {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": transfer_wait.get("failure_code", "PRINTER_TRANSFER_NOT_IDLE_TIMEOUT"),
                    "transfer_wait": transfer_wait,
                }
        record_step("START_PRINT", "ok" if start_result.get("ok") else str(start_result.get("status") or "not_enabled"), start_result.get("failure_code"))

        monitor_status = "virtual_finished" if client.transport == "virtual" else ("not_started" if not start_result.get("ok") else "started")
        record_step("MONITOR_PRINT", monitor_status)
        record_step("COOLDOWN", "ok" if client.transport == "virtual" else "not_verified")

        if ejection_result is None:
            ejection_result = self._handle_ejection(
                payload,
                client=client,
                storage=storage_name,
                allow_physical=allow_physical,
                printer_status=status,
            )
        record_step("AUTO_EJECT", ejection_result.get("status", "disabled"), ejection_result.get("failure_code"))
        record_step(
            "VERIFY_EJECTED",
            "ok" if ejection_result.get("status") in {"simulated_verified_ejected", "virtual_ack", "started"} else "not_verified",
        )
        record_step("DONE", "ok")

        print_status = self._print_status(client, upload, start_result)
        status_value = self._overall_status(print_status, ejection_result)
        return {
            "ok": True,
            "tool": "printer.prepare",
            "mode": runtime_mode,
            "printer_path": "virtual_prusalink" if client.transport == "virtual" else "live",
            "status": status_value,
            "specimen_id": specimen_id,
            "stl_path": stl_path,
            "sliced_path": slice_result.get("sliced_path"),
            "slicer_settings": slicer_settings,
            "slicer_result": {
                "ok": bool(slice_result.get("ok")),
                "sliced_path": slice_result.get("sliced_path"),
                "stdout": slice_result.get("stdout", ""),
                "stderr": slice_result.get("stderr", ""),
                "elapsed_sec": slice_result.get("elapsed_sec"),
                "failure_code": slice_result.get("failure_code"),
                "simulated": bool(slice_result.get("simulated", False)),
            },
            "gcode_validation": gcode_validation,
            "prusalink": {
                "transport": client.transport,
                "storage": storage_name,
                "remote_path": remote_path,
                "upload_endpoint": client._files_endpoint(storage_name, remote_path),
                "start_endpoint": client._files_endpoint(storage_name, remote_path),
            },
            "printer": {
                "provider": self.config.provider,
                "host_configured": bool(client.connection.get("host")),
                "state": self._state_from_status(status),
                "status": status,
                "storage": storage,
                "job": job,
                "transfer": transfer,
            },
            "print_result": {
                "status": print_status,
                "failure_code": upload.get("failure_code") or start_result.get("failure_code"),
                "set_ready": set_ready_result,
                "upload": upload,
                "transfer_wait": transfer_wait,
                "start": start_result,
            },
            "ejection_result": ejection_result,
            "step_trace": trace,
            "artifacts": {
                "stl_path": stl_path,
                "sliced_path": slice_result.get("sliced_path"),
                "ejection_gcode_path": ejection_result.get("appended_gcode_path"),
            },
            "failure_code": None,
        }

    def _prepare_append_ejection(
        self,
        payload: dict[str, Any],
        *,
        client: PrusaLinkClient,
        allow_physical: bool,
        printer_status: dict[str, Any] | None,
        slice_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if str(self.config.ejection.mode).strip().lower() != "append_end_gcode":
            return None
        ejection_request = payload.get("ejection") if isinstance(payload.get("ejection"), dict) else {}
        requested = bool(ejection_request.get("enabled", self.config.ejection.enabled))
        if not requested:
            return {"status": "disabled", "attempts": 0, "failure_code": None, "mode": "append_end_gcode"}
        if bool(payload.get("stop_requested")) or bool(payload.get("safe_stop_requested")):
            return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_STOP_REQUESTED", "mode": "append_end_gcode"}
        if client.transport != "virtual":
            if not allow_physical:
                return {
                    "status": "not_enabled",
                    "attempts": 0,
                    "failure_code": "PHYSICAL_WRITE_DISABLED_IN_TEST",
                    "mode": "append_end_gcode",
                }
        source = Path(str(slice_result.get("sliced_path") or ""))
        if not source.exists():
            return {"status": "failed", "attempts": 0, "failure_code": "GCODE_INPUT_MISSING", "mode": "append_end_gcode"}
        object_bounds = GCodeObjectBoundsExtractor.from_path(source)
        built = self.ejection_builder.build(object_bounds=object_bounds)
        if not built.get("ok"):
            return {
                "status": "failed",
                "attempts": 0,
                "failure_code": built.get("failure_code"),
                "mode": "append_end_gcode",
                "validation": built.get("validation"),
                "resolved": built.get("resolved"),
            }
        appended = source.with_name(f"{source.stem}.autoeject{source.suffix or '.gcode'}")
        source_text = source.read_text(encoding="utf-8", errors="replace").rstrip()
        appended.write_text(f"{source_text}\n\n{str(built['gcode']).strip()}\n", encoding="utf-8")
        validation = GCodeSafetyValidator.validate_print_gcode(appended)
        if not validation.get("ok"):
            return {
                "status": "failed",
                "attempts": 0,
                "failure_code": validation.get("failure_code"),
                "mode": "append_end_gcode",
                "validation": validation,
            }
        return {
            "status": "appended_to_print_gcode",
            "attempts": 1,
            "failure_code": None,
            "mode": "append_end_gcode",
            "method": self.config.ejection.method,
            "source_gcode_path": str(source),
            "appended_gcode_path": str(appended),
            "validation": built.get("validation"),
            "resolved": built.get("resolved"),
            "object_bounds": object_bounds.to_dict() if object_bounds is not None else None,
            "gcode_tail": str(built["gcode"]).strip().splitlines(),
            "printer_state_at_append": self._state_from_status(printer_status or {}),
        }

    def _handle_ejection(
        self,
        payload: dict[str, Any],
        *,
        client: PrusaLinkClient,
        storage: str,
        allow_physical: bool,
        printer_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ejection_request = payload.get("ejection") if isinstance(payload.get("ejection"), dict) else {}
        requested = bool(ejection_request.get("enabled", self.config.ejection.enabled))
        if not requested:
            return {"status": "disabled", "attempts": 0, "failure_code": None}
        if not self.config.ejection.enabled:
            return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_DISABLED"}
        if bool(payload.get("stop_requested")) or bool(payload.get("safe_stop_requested")):
            return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_STOP_REQUESTED"}
        if client.transport != "virtual" and not allow_physical:
            return {"status": "not_enabled", "attempts": 0, "failure_code": "PHYSICAL_WRITE_DISABLED_IN_TEST"}
        if client.transport != "virtual" and allow_physical and self.config.live_gate("allow_ejection", False):
            job = client.get_job()
            set_ready_result = self._ensure_ready_for_new_start(client, printer_status or {}, job)
            if not set_ready_result.get("ok"):
                return {
                    "status": "not_enabled",
                    "attempts": 0,
                    "failure_code": set_ready_result.get("failure_code", "EJECTION_PRINTER_NOT_IDLE"),
                    "printer_state": self._state_from_status(printer_status or {}),
                    "set_ready": set_ready_result,
                }
            printer_status = client.get_status()
            if self.config.ejection.require_cooldown:
                bed_temp = self._bed_temp_from_status(printer_status or {})
                if bed_temp is None:
                    return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_COOLDOWN_NOT_VERIFIED"}
                if bed_temp > float(self.config.ejection.max_bed_temp_c):
                    return {
                        "status": "not_enabled",
                        "attempts": 0,
                        "failure_code": "EJECTION_COOLDOWN_NOT_SATISFIED",
                        "bed_temp_c": bed_temp,
                        "max_bed_temp_c": float(self.config.ejection.max_bed_temp_c),
                    }
            if self.config.ejection.require_pre_eject_vision and not bool(ejection_request.get("pre_eject_vision_ok", False)):
                return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_PRE_VISION_REQUIRED"}
        built = self.ejection_builder.build()
        if not built.get("ok"):
            return {"status": "failed", "attempts": 0, "failure_code": built.get("failure_code"), "validation": built.get("validation")}
        ejection_path = self.repo_root / "artifacts" / "gcode" / "ejection.gcode"
        ejection_path.parent.mkdir(parents=True, exist_ok=True)
        ejection_path.write_text(str(built["gcode"]), encoding="utf-8")
        upload = client.upload_file(ejection_path, storage, ejection_path.name, overwrite=True, print_after_upload=False)
        if client.transport == "virtual":
            return {"status": "virtual_ack", "attempts": 1, "failure_code": None, "upload": upload}
        if not allow_physical or not self.config.live_gate("allow_ejection", False):
            return {"status": "not_enabled", "attempts": 0, "failure_code": "EJECTION_DISABLED", "upload": upload}
        set_ready_result = self._ensure_ready_for_new_start(client, client.get_status(), client.get_job())
        if not set_ready_result.get("ok"):
            return {
                "status": "not_enabled",
                "attempts": 0,
                "failure_code": set_ready_result.get("failure_code", "PRINTER_JOB_ACTIVE"),
                "upload": upload,
                "set_ready": set_ready_result,
            }
        transfer_wait = self._wait_for_transfer_idle(client)
        if not transfer_wait.get("ok"):
            return {
                "status": "failed",
                "attempts": 0,
                "failure_code": transfer_wait.get("failure_code", "PRINTER_TRANSFER_NOT_IDLE_TIMEOUT"),
                "upload": upload,
                "set_ready": set_ready_result,
                "transfer_wait": transfer_wait,
            }
        start = self._start_file_with_retry(client, storage, ejection_path.name, require_metadata_resolution=True)
        return {
            "status": "started" if start.get("ok") else "failed",
            "attempts": 1,
            "failure_code": start.get("failure_code"),
            "upload": upload,
            "set_ready": set_ready_result,
            "transfer_wait": transfer_wait,
            "start": start,
        }

    def run_autoejection_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the same bed-sweep ejection program with synthetic object bounds."""
        position = str(payload.get("position", "center")).strip().lower()
        if position not in {"left", "center", "right"}:
            return {"ok": False, "tool": "printer.autoejection_test", "failure_code": "BAD_EJECTION_TEST_POSITION"}
        runtime_mode = str(payload.get("runtime_mode", "live")).strip().lower()
        specimen_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"autoeject-test-{position}").strip(".-")
        trace: list[dict[str, Any]] = []

        def record_step(step: str, status: str, detail: Any | None = None) -> None:
            trace.append(self._step(step, status, detail))

        record_step("PRECHECK", "ok", "standalone autoejection test uses existing ejection G-code builder")
        if runtime_mode == "live":
            self.connection_memory.save_from_payload(payload)
            connection = self.connection_memory.resolve(self.config.live)
            if not str(connection.get("host", "")).strip():
                self.connection_memory.ensure_template(self.config.live)
                return {
                    "ok": False,
                    "tool": "printer.autoejection_test",
                    "mode": "live",
                    "position": position,
                    "status": "connection_info_required",
                    "failure_code": "PRINTER_CONNECTION_INFO_REQUIRED",
                    "requires_connection_info": True,
                    "connection_memory_path": str(self.connection_memory.path),
                    "step_trace": trace + [self._step("PRUSALINK_STATUS", "blocked", "PRINTER_CONNECTION_INFO_REQUIRED")],
                }
            client = PrusaLinkClient(config=self.config, connection=connection, transport="real")
        else:
            connection = {"host": "virtual-prusalink", "scheme": "http", "port": 80, "storage": "usb", "auth": {"mode": "none"}}
            client = PrusaLinkClient(config=self.config, connection=connection, transport="virtual")

        status = client.get_status()
        record_step("PRUSALINK_STATUS", "ok" if status.get("ok") else "blocked", status.get("failure_code"))
        if not status.get("ok"):
            return {
                "ok": False,
                "tool": "printer.autoejection_test",
                "mode": runtime_mode,
                "position": position,
                "status": "communication_failed",
                "failure_code": status.get("failure_code", "PRINTER_COMMUNICATION_FAILED"),
                "printer": {"provider": self.config.provider, "state": None, "status": status},
                "step_trace": trace,
            }
        storage = client.get_storage()
        storage_name = str(payload.get("storage") or client.connection.get("storage") or "usb")
        storage_check = self._storage_ready(storage, storage_name, virtual=client.transport == "virtual")
        record_step("PRUSALINK_STORAGE", "ok" if storage_check.get("ok") else "blocked", storage_check.get("failure_code"))
        if not storage_check.get("ok"):
            return {
                "ok": False,
                "tool": "printer.autoejection_test",
                "mode": runtime_mode,
                "position": position,
                "status": "storage_failed",
                "failure_code": storage_check.get("failure_code"),
                "printer": {"provider": self.config.provider, "state": self._state_from_status(status), "status": status, "storage": storage},
                "step_trace": trace,
            }
        set_ready_result: dict[str, Any] | None = None
        if client.transport != "virtual" and bool(payload.get("start_immediately", True)):
            record_step("READY_FOR_START", "active", "waiting for any previous job to clear before short-name start")
            set_ready_result = self._ensure_ready_for_new_start(client, status, client.get_job())
            record_step(
                "READY_FOR_START",
                "ok" if set_ready_result.get("ok") else "blocked",
                set_ready_result.get("failure_code") or set_ready_result.get("status"),
            )
            if not set_ready_result.get("ok"):
                return {
                    "ok": False,
                    "tool": "printer.autoejection_test",
                    "mode": runtime_mode,
                    "position": position,
                    "status": "not_enabled",
                    "failure_code": set_ready_result.get("failure_code", "PRINTER_JOB_ACTIVE"),
                    "set_ready": set_ready_result,
                    "printer": {
                        "provider": self.config.provider,
                        "state": self._state_from_status(status),
                        "status": status,
                        "storage": storage,
                    },
                    "step_trace": trace,
                }
            status = client.get_status()

        object_bounds = self._synthetic_ejection_test_bounds(position, payload.get("object_size_mm"))
        built = self.ejection_builder.build(
            object_bounds=object_bounds,
            include_temperature_commands=True,
        )
        record_step("BUILD_EJECTION_GCODE", "ok" if built.get("ok") else "blocked", built.get("failure_code"))
        if not built.get("ok"):
            return {
                "ok": False,
                "tool": "printer.autoejection_test",
                "mode": runtime_mode,
                "position": position,
                "status": "failed",
                "failure_code": built.get("failure_code"),
                "validation": built.get("validation"),
                "resolved": built.get("resolved"),
                "object_bounds": object_bounds.to_dict(),
                "step_trace": trace,
            }

        output_dir = self.repo_root / "artifacts" / "gcode"
        output_dir.mkdir(parents=True, exist_ok=True)
        ejection_path = output_dir / f"{specimen_id}.gcode"
        ejection_path.write_text(str(built["gcode"]).strip() + "\n", encoding="utf-8")
        validation = GCodeSafetyValidator.validate_print_gcode(ejection_path)
        record_step("VALIDATE_GCODE", "ok" if validation.get("ok") else "blocked", validation.get("failure_code"))
        if not validation.get("ok"):
            return {
                "ok": False,
                "tool": "printer.autoejection_test",
                "mode": runtime_mode,
                "position": position,
                "status": "failed",
                "failure_code": validation.get("failure_code"),
                "validation": validation,
                "ejection_gcode_path": str(ejection_path),
                "step_trace": trace,
            }

        remote_path = ejection_path.name
        upload = client.upload_file(ejection_path, storage_name, remote_path, overwrite=True, print_after_upload=False)
        record_step("UPLOAD", "ok" if upload.get("ok") else str(upload.get("status") or "blocked"), upload.get("failure_code"))
        start = {"ok": False, "status": "not_enabled", "failure_code": "START_PRINT_DISABLED"}
        transfer_wait: dict[str, Any] | None = None
        if upload.get("ok") and bool(payload.get("start_immediately", True)):
            if client.transport != "virtual":
                record_step("WAIT_UPLOAD_READY", "active", "waiting for PrusaLink transfer to become idle before short-name start")
                transfer_wait = self._wait_for_transfer_idle(client)
                record_step(
                    "WAIT_UPLOAD_READY",
                    "ok" if transfer_wait.get("ok") else "blocked",
                    transfer_wait.get("failure_code") or transfer_wait.get("status"),
                )
            if transfer_wait is None or transfer_wait.get("ok"):
                start = self._start_file_with_retry(client, storage_name, remote_path, require_metadata_resolution=True)
            else:
                start = {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": transfer_wait.get("failure_code", "PRINTER_TRANSFER_NOT_IDLE_TIMEOUT"),
                    "transfer_wait": transfer_wait,
                }
        record_step("START_EJECTION_PROGRAM", "ok" if start.get("ok") else str(start.get("status") or "blocked"), start.get("failure_code"))
        ok = bool(upload.get("ok")) and bool(start.get("ok") or client.transport == "virtual")
        return {
            "ok": ok,
            "tool": "printer.autoejection_test",
            "mode": runtime_mode,
            "position": position,
            "status": "started" if start.get("ok") else ("virtual_ack" if client.transport == "virtual" else "failed"),
            "failure_code": None if ok else (start.get("failure_code") or upload.get("failure_code")),
            "method": self.config.ejection.method,
            "program_mode": "standalone_same_bed_sweep_builder",
            "ejection_gcode_path": str(ejection_path),
            "gcode_tail": str(built["gcode"]).strip().splitlines(),
            "resolved": built.get("resolved"),
            "object_bounds": object_bounds.to_dict(),
            "upload": upload,
            "transfer_wait": transfer_wait,
            "set_ready": set_ready_result,
            "start": start,
            "printer": {"provider": self.config.provider, "state": self._state_from_status(status), "status": status, "storage": storage},
            "prusalink": {
                "transport": client.transport,
                "storage": storage_name,
                "remote_path": remote_path,
                "upload_endpoint": client._files_endpoint(storage_name, remote_path),
                "start_endpoint": client._files_endpoint(storage_name, remote_path),
            },
            "step_trace": trace,
        }

    def _synthetic_ejection_test_bounds(self, position: str, object_size_mm: Any) -> GCodeObjectBounds:
        env = self.config.ejection.safe_envelope
        try:
            size = [float(item) for item in object_size_mm] if isinstance(object_size_mm, (list, tuple)) else [30.0, 30.0, 20.0]
        except (TypeError, ValueError):
            size = [30.0, 30.0, 20.0]
        if len(size) != 3:
            size = [30.0, 30.0, 20.0]
        sx = max(5.0, min(float(size[0]), 80.0))
        sy = max(5.0, min(float(size[1]), 80.0))
        sz = max(1.0, min(float(size[2]), 120.0))
        x_min_env = float(env["x_min_mm"])
        x_max_env = float(env["x_max_mm"])
        y_min_env = float(env["y_min_mm"])
        y_max_env = float(env["y_max_mm"])
        x_centers = {
            "left": x_min_env + sx / 2.0 + 25.0,
            "center": (x_min_env + x_max_env) / 2.0,
            "right": x_max_env - sx / 2.0 - 25.0,
        }
        cx = max(x_min_env + sx / 2.0, min(x_max_env - sx / 2.0, x_centers.get(position, (x_min_env + x_max_env) / 2.0)))
        cy = (y_min_env + y_max_env) / 2.0
        return GCodeObjectBounds(
            x_min=cx - sx / 2.0,
            x_max=cx + sx / 2.0,
            y_min=cy - sy / 2.0,
            y_max=cy + sy / 2.0,
            z_min=0.2,
            z_max=sz,
            extrusion_move_count=0,
        )

    @staticmethod
    def _specimen_id(payload: dict[str, Any]) -> str:
        text = str(payload.get("specimen_id", "specimen")).strip()
        return re.sub(r"[^a-zA-Z0-9_.-]+", "-", text).strip(".-") or "specimen"

    @staticmethod
    def _step(step: str, status: str, detail: Any | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"step": step, "status": status}
        if detail is not None:
            payload["detail"] = detail
        return payload

    @staticmethod
    def _emit_step_event(
        payload: dict[str, Any],
        *,
        runtime_mode: str,
        specimen_id: str,
        step: dict[str, Any],
    ) -> None:
        callback = payload.get("_event_callback")
        if not callable(callback):
            return
        event = {
            "tool": "printer.prepare",
            "mode": runtime_mode,
            "specimen_id": specimen_id,
            "step": step.get("step"),
            "status": step.get("status"),
            "detail": step.get("detail"),
            "timestamp": time.time(),
        }
        try:
            callback(event)
        except Exception:
            # Progress callbacks are best-effort and must never alter hardware gates.
            return

    @staticmethod
    def _state_from_status(status: dict[str, Any]) -> str | None:
        if not isinstance(status, dict) or not status.get("ok"):
            return None
        payload = status.get("payload") if isinstance(status.get("payload"), dict) else status
        printer = payload.get("printer") if isinstance(payload.get("printer"), dict) else {}
        return str(printer.get("state") or payload.get("state") or payload.get("printer_state") or payload.get("status") or payload.get("command") or "UNKNOWN")

    @staticmethod
    def _bed_temp_from_status(status: dict[str, Any]) -> float | None:
        if not isinstance(status, dict) or not status.get("ok"):
            return None
        payload = status.get("payload") if isinstance(status.get("payload"), dict) else status
        printer = payload.get("printer") if isinstance(payload.get("printer"), dict) else payload
        for key in ("temp_bed", "bed_temp", "bed_temperature"):
            try:
                return float(printer[key])
            except (KeyError, TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _storage_ready(storage: dict[str, Any], storage_name: str, *, virtual: bool) -> dict[str, Any]:
        if virtual:
            return {"ok": True, "failure_code": None}
        if not isinstance(storage, dict) or not storage.get("ok"):
            return {
                "ok": False,
                "failure_code": storage.get("failure_code", "PRINTER_STORAGE_STATUS_FAILED") if isinstance(storage, dict) else "PRINTER_STORAGE_STATUS_FAILED",
            }
        payload = storage.get("payload") if isinstance(storage.get("payload"), dict) else storage
        entries = payload.get("storage_list") if isinstance(payload.get("storage_list"), list) else []
        if not entries:
            return {"ok": True, "failure_code": None, "storage": None}
        target = str(storage_name or "usb").strip("/").lower()
        selected = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            names = {
                str(entry.get("name", "")).strip("/").lower(),
                str(entry.get("path", "")).strip("/").lower(),
            }
            if target in names:
                selected = entry
                break
        if selected is None:
            return {"ok": False, "failure_code": "PRINTER_STORAGE_NOT_FOUND", "storage": storage_name}
        if bool(selected.get("read_only", False)):
            return {"ok": False, "failure_code": "PRINTER_STORAGE_READ_ONLY", "storage": selected}
        if "available" in selected and not bool(selected.get("available")):
            return {"ok": False, "failure_code": "PRINTER_STORAGE_UNAVAILABLE", "storage": selected}
        return {"ok": True, "failure_code": None, "storage": selected}

    @staticmethod
    def _upload_transfer_detail(path: Any, timeout_sec: float) -> str:
        gcode_path = Path(str(path)) if path else None
        size = gcode_path.stat().st_size if gcode_path and gcode_path.exists() else None
        if size is None:
            return f"PrusaLink upload in progress; timeout={timeout_sec:.0f}s"
        return f"PrusaLink upload in progress; size={size / (1024 * 1024):.1f} MiB timeout={timeout_sec:.0f}s"

    @staticmethod
    def _job_payload(job: dict[str, Any] | None, status: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(job, dict) and job.get("ok") and int(job.get("status_code") or 0) != 204:
            payload = job.get("payload") if isinstance(job.get("payload"), dict) else job
            if payload:
                return payload
        if isinstance(status, dict):
            payload = status.get("payload") if isinstance(status.get("payload"), dict) else status
            embedded = payload.get("job") if isinstance(payload.get("job"), dict) else {}
            if embedded:
                return embedded
        return {}

    @staticmethod
    def _printer_payload(status: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(status, dict):
            return {}
        payload = status.get("payload") if isinstance(status.get("payload"), dict) else status
        return payload.get("printer") if isinstance(payload.get("printer"), dict) else {}

    @classmethod
    def _job_summary(cls, status: dict[str, Any] | None, job: dict[str, Any] | None) -> dict[str, Any]:
        job_payload = cls._job_payload(job, status)
        printer = cls._printer_payload(status)
        file_payload = job_payload.get("file") if isinstance(job_payload.get("file"), dict) else {}
        return {
            "job_id": job_payload.get("id"),
            "job_state": job_payload.get("state"),
            "printer_state": printer.get("state"),
            "progress": job_payload.get("progress"),
            "time_remaining": job_payload.get("time_remaining"),
            "time_printing": job_payload.get("time_printing"),
            "target_bed": printer.get("target_bed"),
            "target_nozzle": printer.get("target_nozzle"),
            "display_name": file_payload.get("display_name") or file_payload.get("name"),
        }

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_completed_job_ready_candidate(cls, status: dict[str, Any] | None, job: dict[str, Any] | None) -> bool:
        return cls._is_completed_job_ready_candidate_from_summary(cls._job_summary(status, job))

    @staticmethod
    def _is_active_printer_state(summary: dict[str, Any]) -> bool:
        state = str(summary.get("job_state") or summary.get("printer_state") or "").strip().upper()
        return state in {"PRINTING", "PAUSED", "BUSY", "ATTENTION", "FINISHING"}

    @staticmethod
    def _is_started_print_state(summary: dict[str, Any]) -> bool:
        state = str(summary.get("job_state") or summary.get("printer_state") or "").strip().upper()
        return state in {"PRINTING", "PAUSED", "BUSY", "FINISHING"} and not PrinterAgenticWorkflow._is_completed_job_ready_candidate_from_summary(summary)

    @classmethod
    def _is_completed_job_ready_candidate_from_summary(cls, summary: dict[str, Any]) -> bool:
        if summary.get("job_id") is None:
            return False
        state = str(summary.get("job_state") or summary.get("printer_state") or "").strip().upper()
        progress = cls._float_or_none(summary.get("progress"))
        if progress is not None and progress >= 100.0:
            return True
        return state in {"FINISHED", "COMPLETED"} and (progress is None or progress >= 99.999)

    def _ready_wait_timeout_sec(self, client: PrusaLinkClient) -> float:
        timeouts = self.config.live.get("timeouts") if isinstance(self.config.live.get("timeouts"), dict) else {}
        configured = timeouts.get("ready_wait_sec", timeouts.get("print_sec", client.timeout_seconds("request")))
        try:
            return max(1.0, float(configured))
        except (TypeError, ValueError):
            return max(1.0, client.timeout_seconds("request"))

    def _ensure_ready_for_new_start(
        self,
        client: PrusaLinkClient,
        status: dict[str, Any],
        job: dict[str, Any],
    ) -> dict[str, Any]:
        if client.transport == "virtual":
            return {"ok": True, "status": "virtual_ready", "job": {}}
        timeout_sec = self._ready_wait_timeout_sec(client)
        interval = float(self.config.live.get("poll_interval_sec", 5))
        deadline = time.monotonic() + timeout_sec
        samples: list[dict[str, Any]] = []
        current_status = status
        current_job = job
        while True:
            summary = self._job_summary(current_status, current_job)
            samples.append(summary)
            if not summary.get("job_id") and not self._is_active_printer_state(summary):
                return {"ok": True, "status": "ready", "attempts": len(samples), "job": summary, "samples": samples[-5:]}
            completed_candidate = self._is_completed_job_ready_candidate(current_status, current_job)
            if not self._is_active_printer_state(summary):
                if completed_candidate:
                    pass
                else:
                    return {
                        "ok": False,
                        "status": "blocked",
                        "failure_code": "PRINTER_JOB_ACTIVE",
                        "attempts": len(samples),
                        "job": summary,
                        "samples": samples[-5:],
                    }
            if time.monotonic() >= deadline:
                failure_code = "PRINTER_JOB_NOT_CLEARED_TIMEOUT" if completed_candidate else "PRINTER_JOB_NOT_COMPLETE_TIMEOUT"
                return {
                    "ok": False,
                    "status": "timeout",
                    "failure_code": failure_code,
                    "attempts": len(samples),
                    "job": summary,
                    "samples": samples[-5:],
                }
            time.sleep(max(0.2, interval))
            current_status = client.get_status()
            current_job = client.get_job()

    @staticmethod
    def _transfer_summary(transfer: dict[str, Any]) -> dict[str, Any]:
        payload = transfer.get("payload") if isinstance(transfer.get("payload"), dict) else {}
        summary: dict[str, Any] = {
            "ok": bool(transfer.get("ok")),
            "status_code": transfer.get("status_code"),
            "failure_code": transfer.get("failure_code"),
        }
        for key in ("state", "status", "type", "progress", "transferred", "size", "time_remaining", "to_print", "path"):
            if key in payload:
                summary[key] = payload.get(key)
        return {key: value for key, value in summary.items() if value is not None}

    @classmethod
    def _transfer_is_idle(cls, transfer: dict[str, Any]) -> bool:
        if not isinstance(transfer, dict):
            return False
        if transfer.get("ok") and int(transfer.get("status_code") or 0) == 204:
            return True
        payload = transfer.get("payload") if isinstance(transfer.get("payload"), dict) else {}
        status = str(payload.get("state") or payload.get("status") or "").strip().lower()
        if status in {"idle", "finished", "complete", "completed", "success", "none"}:
            return True
        if payload.get("transferred") is not None and payload.get("size") is not None:
            try:
                return float(payload["size"]) > 0 and float(payload["transferred"]) >= float(payload["size"])
            except (TypeError, ValueError):
                return False
        return False

    def _wait_for_transfer_idle(
        self,
        client: PrusaLinkClient,
        *,
        timeout_sec: float = 180.0,
        poll_interval_sec: float = 2.0,
    ) -> dict[str, Any]:
        if client.transport == "virtual":
            return {"ok": True, "status": "virtual_idle", "samples": []}
        deadline = time.monotonic() + max(1.0, timeout_sec)
        samples: list[dict[str, Any]] = []
        while True:
            transfer = client.get_transfer()
            summary = self._transfer_summary(transfer)
            samples.append(summary)
            if self._transfer_is_idle(transfer):
                return {
                    "ok": True,
                    "status": "idle",
                    "attempts": len(samples),
                    "last_transfer": summary,
                    "samples": samples[-5:],
                }
            if not transfer.get("ok") and transfer.get("failure_code") not in {None, "PRINTER_HTTP_ERROR"}:
                return {
                    "ok": False,
                    "status": "failed",
                    "failure_code": transfer.get("failure_code", "PRINTER_TRANSFER_STATUS_FAILED"),
                    "attempts": len(samples),
                    "last_transfer": summary,
                    "samples": samples[-5:],
                }
            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "status": "timeout",
                    "failure_code": "PRINTER_TRANSFER_NOT_IDLE_TIMEOUT",
                    "attempts": len(samples),
                    "last_transfer": summary,
                    "samples": samples[-5:],
                }
            time.sleep(max(0.2, poll_interval_sec))

    def _confirm_print_started(self, client: PrusaLinkClient) -> dict[str, Any]:
        if client.transport == "virtual":
            return {"ok": True, "status": "virtual_started", "job": {}}
        status = client.get_status()
        job = client.get_job()
        summary = self._job_summary(status, job)
        return {
            "ok": self._is_started_print_state(summary),
            "status": "started" if self._is_started_print_state(summary) else "not_started",
            "job": summary,
            "status_response": {
                "ok": status.get("ok") if isinstance(status, dict) else None,
                "failure_code": status.get("failure_code") if isinstance(status, dict) else None,
                "status_code": status.get("status_code") if isinstance(status, dict) else None,
            },
            "job_response": {
                "ok": job.get("ok") if isinstance(job, dict) else None,
                "failure_code": job.get("failure_code") if isinstance(job, dict) else None,
                "status_code": job.get("status_code") if isinstance(job, dict) else None,
            },
        }

    @staticmethod
    def _start_path_from_file_metadata(metadata: dict[str, Any], fallback: str) -> str:
        payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else {}
        fallback_segment = PrusaLinkClient._remote_segment(fallback)
        name = str(payload.get("name") or "").strip().lstrip("/")
        if name:
            return name
        refs = payload.get("refs") if isinstance(payload.get("refs"), dict) else {}
        for key in ("resource", "download"):
            value = str(refs.get(key) or "").strip()
            if not value:
                continue
            marker = "/usb/"
            if marker in value:
                return value.split(marker, 1)[1].lstrip("/") or fallback_segment
            parts = [part for part in value.split("/") if part]
            if parts:
                return parts[-1] or fallback_segment
        return fallback_segment

    def _resolve_start_remote_path(self, client: PrusaLinkClient, storage: str, remote_path: str) -> dict[str, Any]:
        requested = PrusaLinkClient._remote_segment(remote_path)
        if client.transport == "virtual":
            return {
                "ok": True,
                "status": "virtual",
                "remote_path": requested,
                "start_remote_path": requested,
            }
        metadata = client.get_file_metadata(storage, requested)
        if not metadata.get("ok"):
            return {
                "ok": True,
                "status": "metadata_unavailable_fallback",
                "remote_path": requested,
                "start_remote_path": requested,
                "metadata": metadata,
            }
        resolved = self._start_path_from_file_metadata(metadata, requested)
        return {
            "ok": True,
            "status": "resolved" if resolved != requested else "unchanged",
            "remote_path": requested,
            "start_remote_path": resolved,
            "metadata": metadata,
        }

    def _start_file_with_retry(
        self,
        client: PrusaLinkClient,
        storage: str,
        remote_path: str,
        *,
        attempts: int = 10,
        retry_delay_sec: float = 1.0,
        require_metadata_resolution: bool = False,
    ) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        for attempt in range(1, max(1, attempts) + 1):
            path_resolution = self._resolve_start_remote_path(client, storage, remote_path)
            if (
                require_metadata_resolution
                and client.transport != "virtual"
                and path_resolution.get("status") == "metadata_unavailable_fallback"
            ):
                return {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": "PRINTER_START_PATH_METADATA_UNAVAILABLE",
                    "attempts": attempt,
                    "requested_remote_path": PrusaLinkClient._remote_segment(remote_path),
                    "path_resolution": path_resolution,
                    "retry_history": history,
                }
            start_remote_path = str(path_resolution.get("start_remote_path") or remote_path)
            result = client.start_file(storage, start_remote_path)
            result["attempt"] = attempt
            result["requested_remote_path"] = PrusaLinkClient._remote_segment(remote_path)
            result["start_remote_path"] = PrusaLinkClient._remote_segment(start_remote_path)
            result["path_resolution"] = path_resolution
            confirm = self._confirm_print_started(client)
            result["start_confirm"] = confirm
            history.append(
                {
                    "ok": result.get("ok"),
                    "status": result.get("status"),
                    "failure_code": result.get("failure_code"),
                    "status_code": result.get("status_code"),
                    "attempt": attempt,
                    "requested_remote_path": result.get("requested_remote_path"),
                    "start_remote_path": result.get("start_remote_path"),
                    "path_resolution_status": path_resolution.get("status"),
                    "confirm_status": confirm.get("status"),
                    "confirm_job_state": confirm.get("job", {}).get("job_state") if isinstance(confirm.get("job"), dict) else None,
                    "confirm_printer_state": confirm.get("job", {}).get("printer_state") if isinstance(confirm.get("job"), dict) else None,
                }
            )
            if result.get("ok") and confirm.get("ok"):
                result["ok"] = True
                result["status"] = "started"
                result["attempts"] = attempt
                result["retry_history"] = history
                return result
            if attempt >= attempts:
                if result.get("ok") and not confirm.get("ok"):
                    result["ok"] = False
                    result["status"] = "not_started"
                    result["failure_code"] = "START_PRINT_NOT_CONFIRMED"
                result["attempts"] = attempt
                result["retry_history"] = history
                return result
            if int(result.get("status_code") or 0) == 409:
                ready = self._ensure_ready_for_new_start(client, client.get_status(), client.get_job())
                result["ready_before_retry"] = ready
                if not ready.get("ok"):
                    result["attempts"] = attempt
                    result["retry_history"] = history
                    result["failure_code"] = ready.get("failure_code", result.get("failure_code"))
                    return result
            # PrusaLink can briefly expose the uploaded file before the USB
            # transfer/index state is fully settled. Recheck transfer before retrying start.
            self._wait_for_transfer_idle(client, timeout_sec=20.0, poll_interval_sec=1.0)
            time.sleep(max(0.2, retry_delay_sec))
        return {"ok": False, "status": "failed", "failure_code": "START_PRINT_RETRY_EXHAUSTED", "retry_history": history}

    @staticmethod
    def _print_status(client: PrusaLinkClient, upload: dict[str, Any], start: dict[str, Any]) -> str:
        if client.transport == "virtual":
            return "virtual_finished"
        if start.get("ok"):
            return "started"
        if upload.get("ok"):
            return "uploaded_not_started"
        if upload.get("failure_code") == "UPLOAD_DISABLED":
            return "not_enabled"
        return "not_started"

    @staticmethod
    def _overall_status(print_status: str, ejection: dict[str, Any]) -> str:
        if ejection.get("status") in {"virtual_ack", "simulated_verified_ejected"}:
            return "simulated_printed_and_ejected"
        if print_status == "virtual_finished":
            return "simulated_printed"
        if print_status == "uploaded_not_started":
            return "prepared"
        if print_status == "not_enabled":
            return "not_enabled"
        return print_status

    def _connection_required_result(self, *, mode: str, printer_path: str, specimen_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": "printer.prepare",
            "mode": mode,
            "printer_path": printer_path,
            "status": "connection_info_required",
            "specimen_id": specimen_id,
            "failure_code": "PRINTER_CONNECTION_INFO_REQUIRED",
            "requires_connection_info": True,
            "connection_memory_path": str(self.connection_memory.path),
            "message": (
                "PrusaLink connection info is required. Fill memory/prusa_connection.json "
                "or provide connection_info in printer.prepare payload."
            ),
            "print_result": {"status": "not_started", "failure_code": "PRINTER_CONNECTION_INFO_REQUIRED"},
            "ejection_result": {"status": "disabled", "attempts": 0, "failure_code": None},
            "step_trace": [self._step("PRECHECK", "blocked", "PRINTER_CONNECTION_INFO_REQUIRED")],
        }

    @staticmethod
    def _failed_result(
        runtime_mode: str,
        specimen_id: str,
        stl_path: Any,
        trace: list[dict[str, Any]],
        failure_code: Any,
        *,
        status: dict[str, Any] | None = None,
        storage: dict[str, Any] | None = None,
        job: dict[str, Any] | None = None,
        transfer: dict[str, Any] | None = None,
        slice_result: dict[str, Any] | None = None,
        gcode_validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        slice_payload = slice_result if isinstance(slice_result, dict) else {}
        return {
            "ok": False,
            "tool": "printer.prepare",
            "mode": runtime_mode,
            "status": "failed",
            "specimen_id": specimen_id,
            "stl_path": stl_path,
            "sliced_path": None,
            "slicer_settings": slice_payload.get("slicer_settings", {}),
            "slicer_result": slice_payload,
            "gcode_validation": gcode_validation or {"ok": False, "failure_code": failure_code, "violations": []},
            "printer": {
                "provider": "prusa_mk4s",
                "state": None,
                "status": status or {},
                "storage": storage or {},
                "job": job or {},
                "transfer": transfer or {},
            },
            "print_result": {"status": "failed", "failure_code": failure_code},
            "ejection_result": {"status": "disabled", "attempts": 0, "failure_code": None},
            "step_trace": trace,
            "artifacts": {"stl_path": stl_path},
            "failure_code": failure_code,
        }


class PrusaBridge(BaseBridge):
    """Live bridge facade for Prusa printer control."""

    def __init__(self, config: PrusaBridgeConfig | None = None, *, repo_root: Path | None = None) -> None:
        self.workflow = PrinterAgenticWorkflow(config or PrusaBridgeConfig(), repo_root=repo_root)

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "prepare":
            return self.workflow.prepare(payload)
        if command == "health":
            return self.workflow.health(payload)
        return {"ok": False, "bridge": "prusa", "command": command, "failure_code": "UNKNOWN_PRINTER_COMMAND"}
