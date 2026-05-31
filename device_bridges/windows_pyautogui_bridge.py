"""
File purpose:
- Safe simulator/live bridge client for Windows PyAutoGUI equipment macros.

Key classes/functions:
- WindowsPyAutoGUIBridgeConfig
- WindowsPyAutoGUIBridge

Inputs/outputs:
- Input: equipment.pyautogui.* tool payloads and devices.yaml config.
- Output: structured bridge health/program/run responses.

Dependencies:
- httpx for optional live bridge HTTP calls.

Modification guide:
- Safe places to edit: allowed actions, simulator defaults, program metadata.
- Risky places to edit: live execution gates and action validation.
- Related files: mcp_tools/equipment_tools.py, agents/equipment_agent.py,
  install/windows_pyautogui_bridge_server.py.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from device_bridges.base_bridge import BaseBridge


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONNECTION_MEMORY = REPO_ROOT / "memory" / "windows_pyautogui_connection.json"
DEFAULT_UTM_PROFILE_MEMORY = REPO_ROOT / "memory" / "equipment_utm_profile.json"
DEFAULT_ALLOWED_ACTIONS = {
    "health",
    "screenshot",
    "locate_image",
    "type_path",
    "wait_for_file",
    "wait_until",
    "wait_until_image",
    "assert_visible",
    "assert_text",
    "wait_until_text",
    "focus_window",
    "wait",
    "move_to",
    "click",
    "double_click",
    "press",
    "hotkey",
    "write",
    "scroll",
    "run_registered_program",
    "demo_mouse_wiggle",
    "log",
}
DEFAULT_REGISTERED_PROGRAMS = {
    "program1": {
        "description": "Connectivity demo: bounded mouse wiggle and completion log.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "connectivity_demo",
        "sequence": [
            {"action": "health"},
            {"action": "demo_mouse_wiggle", "duration_sec": 1.0, "distance_px": 20},
            {"action": "log", "message": "program1 completed"},
        ],
    },
    "utm_compression_start_v1": {
        "description": "UTM compression protocol: focus app, assert ready/running/complete, save/export CSV, and expose artifact metadata.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "utm_protocol",
        "target_app": "UTM software",
        "target_window": "main_window_title_or_regex",
        "locator_backend": "image",
        "max_retries": 1,
        "preconditions": ["windows_bridge_ready", "utm_app_visible", "specimen_verified_on_fixture", "robot_clear_of_utm"],
        "expected_screen_before": [{"name": "ready_state", "required": True}],
        "sequence": [
            {"action": "health"},
            {"action": "focus_window", "window": "main"},
            {"action": "assert_visible", "target": "ready_state"},
            {"action": "click", "target": "start_button"},
            {"action": "wait_until", "target": "running_state", "timeout_s": 10},
            {"action": "wait_until", "target": "complete_state", "timeout_s": 300},
            {"action": "wait_for_file", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv", "timeout_s": 20},
        ],
        "expected_screen_after": [{"name": "running_state", "required": True}, {"name": "complete_state", "required": True}],
        "save_policy": {
            "auto_save_expected": False,
            "manual_save_required_if_no_artifact": True,
            "windows_export_root": "C:/ATR/utm_exports",
            "save_actions": ["wait_until_complete_state", "hotkey_ctrl_s", "type_standard_path", "press_enter", "wait_for_file"],
        },
        "output_artifacts": [{"kind": "utm_csv", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv"}],
        "safe_abort": {"program_id": "utm_stop_or_abort_v1"},
    },
    "utm_export_csv_v1": {
        "description": "UTM CSV export protocol after test completion.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "utm_export",
        "target_app": "UTM software",
        "target_window": "main_window_title_or_regex",
        "locator_backend": "image",
        "max_retries": 1,
        "preconditions": ["windows_bridge_ready", "utm_app_visible", "complete_state_visible"],
        "expected_screen_before": [{"name": "complete_state", "required": True}],
        "sequence": [
            {"action": "assert_visible", "target": "complete_state"},
            {"action": "hotkey", "keys": ["ctrl", "s"]},
            {"action": "type_path", "value": "C:/ATR/utm_exports/{run_id}/{specimen_id}.csv"},
            {"action": "press", "key": "enter"},
            {"action": "wait_for_file", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv", "timeout_s": 20},
        ],
        "expected_screen_after": [{"name": "complete_state", "required": True}],
        "save_policy": {
            "auto_save_expected": False,
            "manual_save_required_if_no_artifact": True,
            "windows_export_root": "C:/ATR/utm_exports",
            "save_method": "export_menu",
            "save_actions": ["assert_complete_state", "hotkey_ctrl_s", "type_standard_path", "press_enter", "wait_for_file"],
        },
        "output_artifacts": [{"kind": "utm_csv", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv"}],
        "safe_abort": {"program_id": "utm_stop_or_abort_v1"},
    },
    "utm_manual_save_csv_v1": {
        "description": "Manual Save As fallback for UTM CSV data.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "utm_export",
        "target_app": "UTM software",
        "target_window": "main_window_title_or_regex",
        "locator_backend": "image",
        "max_retries": 1,
        "preconditions": ["windows_bridge_ready", "utm_app_visible"],
        "expected_screen_before": [{"name": "complete_state", "required": False}],
        "sequence": [
            {"action": "hotkey", "keys": ["ctrl", "s"]},
            {"action": "type_path", "value": "C:/ATR/utm_exports/{run_id}/{specimen_id}.csv"},
            {"action": "press", "key": "enter"},
            {"action": "wait_for_file", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv", "timeout_s": 20},
        ],
        "expected_screen_after": [{"name": "save_dialog_closed", "required": False}],
        "save_policy": {
            "auto_save_expected": False,
            "manual_save_required_if_no_artifact": False,
            "windows_export_root": "C:/ATR/utm_exports",
            "save_method": "manual_save_dialog",
            "save_actions": ["hotkey_ctrl_s", "type_standard_path", "press_enter", "wait_for_file"],
        },
        "output_artifacts": [{"kind": "utm_csv", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv"}],
        "safe_abort": {"program_id": "utm_stop_or_abort_v1"},
    },
    "utm_stop_or_abort_v1": {
        "description": "Safe UTM stop/abort macro for operator or Guardian recovery.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "utm_abort",
        "target_app": "UTM software",
        "target_window": "main_window_title_or_regex",
        "locator_backend": "keyboard",
        "max_retries": 0,
        "preconditions": ["windows_bridge_ready", "utm_app_visible_or_focused"],
        "expected_screen_before": [{"name": "running_or_unknown_state", "required": False}],
        "sequence": [{"action": "press", "key": "esc"}, {"action": "log", "message": "UTM stop/abort requested"}],
        "expected_screen_after": [{"name": "stopped_or_idle_state", "required": False}],
        "save_policy": {"save_method": "not_applicable", "manual_save_required_if_no_artifact": False},
        "output_artifacts": [],
        "safe_abort": {"action": "press", "key": "esc"},
    },
}



UTM_PROFILE_PROGRAM_KEYS = (
    "locators",
    "export_glob",
    "artifact_timeout_s",
    "stable_for_sec",
    "expected_export_path",
    "require_window_focus",
    "manual_save_required_if_no_artifact",
    "target_window",
    "target_window_regex",
    "require_screen_assertions",
    "simulate_utm_protocol",
    "sequence",
)


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk, returning an empty object on absence or invalid data."""
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sanitize_utm_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only UTM profile fields that can safely override the registered protocol."""
    if not isinstance(raw, dict):
        return {}
    program_id = str(raw.get("program_id") or "utm_compression_start_v1").strip() or "utm_compression_start_v1"
    profile: dict[str, Any] = {"program_id": program_id}
    export_glob = str(raw.get("export_glob") or "").strip()
    if export_glob:
        profile["export_glob"] = export_glob
    expected_export_path = str(raw.get("expected_export_path") or "").strip()
    if expected_export_path:
        profile["expected_export_path"] = expected_export_path
    for key in ("target_window", "target_window_regex"):
        value = str(raw.get(key) or "").strip()
        if value:
            profile[key] = value
    for key in ("artifact_timeout_s", "stable_for_sec"):
        if raw.get(key) is None or raw.get(key) == "":
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            continue
        if value > 0:
            profile[key] = value
    for key in ("require_window_focus", "manual_save_required_if_no_artifact", "require_screen_assertions", "simulate_utm_protocol"):
        if key in raw:
            profile[key] = bool(raw.get(key))
    locators = raw.get("locators")
    if isinstance(locators, dict):
        clean_locators: dict[str, dict[str, Any]] = {}
        for name, locator in locators.items():
            if isinstance(locator, dict):
                clean_locators[str(name)] = dict(locator)
        if clean_locators:
            profile["locators"] = clean_locators
    sequence = raw.get("sequence")
    if isinstance(sequence, list) and sequence:
        clean_sequence = [dict(item) for item in sequence if isinstance(item, dict)]
        if clean_sequence:
            profile["sequence"] = clean_sequence
    if raw.get("updated_at"):
        profile["updated_at"] = str(raw.get("updated_at"))
    return profile


def _apply_utm_profile_to_programs(
    programs: dict[str, dict[str, Any]],
    profile_raw: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Merge the persisted UTM GUI profile into the registered UTM program."""
    profile = _sanitize_utm_profile(profile_raw)
    if not profile:
        return programs
    program_id = str(profile.get("program_id") or "utm_compression_start_v1")
    merged = dict(programs.get(program_id, DEFAULT_REGISTERED_PROGRAMS.get(program_id, {})))
    for key in UTM_PROFILE_PROGRAM_KEYS:
        if key in profile:
            merged[key] = profile[key]
    merged["utm_profile_memory_applied"] = True
    programs = dict(programs)
    programs[program_id] = merged
    return programs


ToolEventCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class WindowsPyAutoGUIBridgeConfig:
    """Config for a Windows PyAutoGUI bridge host or simulator."""

    mode: str = "simulator"
    provider: str = "windows_pyautogui"
    enabled: bool = True
    bridge_url_env: str = "WINDOWS_PYAUTOGUI_BRIDGE_URL"
    token_env: str = "WINDOWS_PYAUTOGUI_BRIDGE_TOKEN"
    token_header: str = "X-Bridge-Token"
    request_timeout_sec: float = 10.0
    discovery_timeout_sec: float = 0.45
    discovery_port: int = 8765
    allow_live_execute: bool = False
    allow_screenshot: bool = True
    artifact_dir: Path = REPO_ROOT / "artifacts" / "equipment"
    allowed_actions: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_ACTIONS))
    allowed_hotkeys: list[list[str]] = field(default_factory=lambda: [["ctrl", "s"], ["ctrl", "o"], ["enter"], ["esc"]])
    limits: dict[str, Any] = field(
        default_factory=lambda: {"max_wait_sec": 30.0, "max_write_chars": 512, "max_steps": 50}
    )
    simulator: dict[str, Any] = field(
        default_factory=lambda: {
            "screen_width": 1920,
            "screen_height": 1080,
            "screenshot_name": "simulated_windows_screen.png",
            "pyautogui_available": True,
        }
    )
    test_live_promotion: dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "transport": "virtual", "allow_real_network_in_test": False}
    )
    default_sequence: list[dict[str, Any]] = field(default_factory=lambda: [{"action": "health"}, {"action": "screenshot"}])
    registered_programs: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(DEFAULT_REGISTERED_PROGRAMS))
    connection_memory_path: Path = DEFAULT_CONNECTION_MEMORY
    utm_profile_memory_path: Path = DEFAULT_UTM_PROFILE_MEMORY

    @classmethod
    def from_devices_config(
        cls,
        cfg: dict[str, Any] | None,
        *,
        repo_root: Path | None = None,
    ) -> "WindowsPyAutoGUIBridgeConfig":
        """Build config from the project devices config."""
        root = repo_root or REPO_ROOT
        cfg = cfg if isinstance(cfg, dict) else {}
        devices = cfg.get("devices") if isinstance(cfg.get("devices"), dict) else cfg
        equipment = devices.get("equipment", {}) if isinstance(devices, dict) else {}
        if not isinstance(equipment, dict):
            equipment = {}
        bridge_raw = equipment.get("windows_pyautogui", {})
        bridge = bridge_raw if isinstance(bridge_raw, dict) else {}

        artifact_dir = Path(str(bridge.get("artifact_dir", "artifacts/equipment")))
        if not artifact_dir.is_absolute():
            artifact_dir = root / artifact_dir
        memory_path = Path(str(bridge.get("connection_memory_path", DEFAULT_CONNECTION_MEMORY)))
        if not memory_path.is_absolute():
            memory_path = root / memory_path
        raw_utm_profile_path = bridge.get("utm_profile_memory_path")
        utm_profile_path = Path(str(raw_utm_profile_path)) if raw_utm_profile_path else root / "memory" / "equipment_utm_profile.json"
        if not utm_profile_path.is_absolute():
            utm_profile_path = root / utm_profile_path

        allowed_actions = bridge.get("allowed_actions")
        registered = bridge.get("registered_programs")
        default_sequence = bridge.get("default_sequence")
        registered_programs = {
            **dict(DEFAULT_REGISTERED_PROGRAMS),
            **(
                {
                    str(program_id): dict(program)
                    for program_id, program in registered.items()
                    if isinstance(program, dict)
                }
                if isinstance(registered, dict) and registered
                else {}
            ),
        }
        registered_programs = _apply_utm_profile_to_programs(registered_programs, _read_json_object(utm_profile_path))

        return cls(
            mode=str(equipment.get("mode", bridge.get("mode", "simulator"))).strip().lower() or "simulator",
            provider=str(equipment.get("provider", "windows_pyautogui")),
            enabled=bool(bridge.get("enabled", True)),
            bridge_url_env=str(bridge.get("bridge_url_env", "WINDOWS_PYAUTOGUI_BRIDGE_URL")),
            token_env=str(bridge.get("token_env", "WINDOWS_PYAUTOGUI_BRIDGE_TOKEN")),
            token_header=str(bridge.get("token_header", "X-Bridge-Token")),
            request_timeout_sec=float(bridge.get("request_timeout_sec", 10)),
            discovery_timeout_sec=float(bridge.get("discovery_timeout_sec", 0.45)),
            discovery_port=int(bridge.get("discovery_port", 8765)),
            allow_live_execute=bool(bridge.get("allow_live_execute", False)),
            allow_screenshot=bool(bridge.get("allow_screenshot", True)),
            artifact_dir=artifact_dir,
            allowed_actions=(set(DEFAULT_ALLOWED_ACTIONS) | {str(item) for item in allowed_actions})
            if isinstance(allowed_actions, list) and allowed_actions
            else set(DEFAULT_ALLOWED_ACTIONS),
            allowed_hotkeys=[
                [str(key) for key in item]
                for item in bridge.get("allowed_hotkeys", [["ctrl", "s"], ["ctrl", "o"], ["enter"], ["esc"]])
                if isinstance(item, list)
            ],
            limits=dict(bridge.get("limits", {})) if isinstance(bridge.get("limits"), dict) else cls().limits,
            simulator=dict(bridge.get("simulator", {})) if isinstance(bridge.get("simulator"), dict) else cls().simulator,
            test_live_promotion=(
                dict(bridge.get("test_live_promotion", {}))
                if isinstance(bridge.get("test_live_promotion"), dict)
                else cls().test_live_promotion
            ),
            default_sequence=[dict(item) for item in default_sequence]
            if isinstance(default_sequence, list) and default_sequence
            else cls().default_sequence,
            registered_programs=registered_programs,
            connection_memory_path=memory_path,
            utm_profile_memory_path=utm_profile_path,
        )


class WindowsPyAutoGUIBridge(BaseBridge):
    """Simulator/live client for Windows PyAutoGUI bridge commands."""

    def __init__(self, config: WindowsPyAutoGUIBridgeConfig) -> None:
        self.config = config

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one bridge command."""
        if command == "health":
            return self.health(payload)
        if command == "list_programs":
            return self.list_programs(payload)
        if command == "run":
            return self.run(payload)
        if command == "screenshot":
            return self.screenshot(payload)
        if command == "list_locators":
            return self.list_locators(payload)
        if command == "capture_locator":
            return self.capture_locator(payload)
        if command == "request_log":
            return self.request_log(payload)
        return self._failure(
            tool=f"equipment.pyautogui.{command}",
            status="blocked",
            failure_code="PYAUTOGUI_UNKNOWN_COMMAND",
            message=f"Unknown Windows PyAutoGUI bridge command: {command}",
            step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "unknown command"}],
        )

    def health(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return Windows bridge health or simulator health."""
        payload = payload or {}
        if not self._should_use_live(payload, for_execution=False):
            return {
                "ok": True,
                "tool": "equipment.pyautogui.health",
                "mode": "simulator",
                "bridge": "windows_pyautogui",
                "status": "ready",
                "screen": self._simulated_screen(),
                "pyautogui": {
                    "available": bool(self.config.simulator.get("pyautogui_available", True)),
                    "failsafe": True,
                    "pause": 0.1,
                    "simulated": True,
                },
                "artifact_root": str(self.config.artifact_dir),
                "locator_root": str(self.config.artifact_dir / "simulated_locators"),
                "utm_export_root": str(self.config.artifact_dir / "simulated_utm_exports"),
                "artifacts": {
                    "root": str(self.config.artifact_dir),
                    "request_log": str(self.config.artifact_dir / "bridge_requests.jsonl"),
                    "locator_root": str(self.config.artifact_dir / "simulated_locators"),
                    "utm_export_root": str(self.config.artifact_dir / "simulated_utm_exports"),
                },
                "program_count": len(self.config.registered_programs),
                "server_version": "simulator",
                "bridge_url": "simulator://windows_pyautogui",
                "bridge_host": "simulator",
                "client_latency_ms": 0.0,
            }
        precheck = self._live_precheck(require_execute=False, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.health"
            return precheck
        return self._live_get("equipment.pyautogui.health", "/health")

    def list_programs(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return registered macro programs."""
        payload = payload or {}
        if not self._should_use_live(payload, for_execution=False):
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_programs",
                "mode": "simulator",
                "bridge": "windows_pyautogui",
                "status": "ready",
                "programs": self._program_metadata(self.config.registered_programs),
            }
        precheck = self._live_precheck(require_execute=False, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.list_programs"
            return precheck
        response = self._live_get("equipment.pyautogui.list_programs", "/programs")
        if isinstance(response.get("programs"), dict):
            response["programs"] = self._program_metadata(response["programs"])
        return response

    @staticmethod
    def _request_log_execute_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
        execute_events = [event for event in events if isinstance(event, dict) and str(event.get("path") or "") == "/execute"]
        payload_events = [event for event in execute_events if str(event.get("audit_kind") or "") == "execute_payload"]
        result_events = [event for event in execute_events if str(event.get("audit_kind") or "") == "execute_result"]
        identity_events = payload_events or execute_events

        def uniq(key: str) -> list[str]:
            values: list[str] = []
            seen: set[str] = set()
            for event in identity_events:
                value = str(event.get(key) or "").strip()
                if value and value not in seen:
                    seen.add(value)
                    values.append(value)
            return values[-10:]

        last_context = dict(identity_events[-1]) if identity_events else {}
        return {
            "execute_event_seen": bool(execute_events),
            "execute_event_count": len(execute_events),
            "execute_payload_event_count": len(payload_events),
            "execute_result_event_count": len(result_events),
            "execute_run_ids": uniq("run_id"),
            "execute_sequence_ids": uniq("sequence_id"),
            "execute_specimen_ids": uniq("specimen_id"),
            "execute_program_ids": uniq("program_id"),
            "last_execute_context": {
                key: value
                for key, value in last_context.items()
                if key in {"at", "status", "audit_kind", "sequence_id", "run_id", "specimen_id", "program_id", "payload_sha256", "result_ok", "result_status", "failure_code"}
            },
        }

    def request_log(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return recent Windows bridge request-audit entries without exposing tokens."""
        payload = dict(payload or {})
        if not self._should_use_live(payload, for_execution=False):
            log_path = self.config.artifact_dir / "bridge_requests.jsonl"
            events: list[dict[str, Any]] = []
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        item = {"raw": line}
                    if isinstance(item, dict):
                        events.append(item)
            recent_paths = [str(event.get("path") or "") for event in events if isinstance(event, dict) and str(event.get("path") or "").strip()]
            execute_summary = self._request_log_execute_summary(events)
            last_execute_at = ""
            for event in reversed(events):
                if isinstance(event, dict) and str(event.get("path") or "") == "/execute":
                    last_execute_at = str(event.get("ts") or event.get("at") or "")
                    break
            return {
                "ok": True,
                "tool": "equipment.pyautogui.request_log",
                "mode": "simulator",
                "bridge": "windows_pyautogui",
                "status": "ready",
                "request_log": str(log_path),
                "event_count": len(events),
                "recent_paths": recent_paths[-10:],
                **execute_summary,
                "last_execute_at": last_execute_at,
                "events": events,
            }
        precheck = self._live_precheck(require_execute=False, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.request_log"
            return precheck
        return self._live_get("equipment.pyautogui.request_log", "/request-log")

    def screenshot(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Capture a Windows bridge screenshot for UTM UI calibration."""
        payload = dict(payload or {})
        if not self.config.allow_screenshot:
            return self._failure(
                tool="equipment.pyautogui.screenshot",
                status="blocked",
                failure_code="PYAUTOGUI_SCREENSHOT_BLOCKED",
                message="Screenshot action is disabled by config.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "allow_screenshot=false"}],
            )
        if not self._should_use_live(payload, for_execution=False):
            return self._simulated_screenshot(payload)
        precheck = self._live_precheck(require_execute=False, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.screenshot"
            return precheck
        public_payload = self._public_payload({**payload, "runtime_mode": "live"})
        return self._live_post("equipment.pyautogui.screenshot", "/screenshot", public_payload)

    def list_locators(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """List saved Windows-side image locators for registered equipment protocols."""
        payload = dict(payload or {})
        if not self._should_use_live(payload, for_execution=False):
            return {
                "ok": True,
                "tool": "equipment.pyautogui.list_locators",
                "mode": "simulator",
                "bridge": "windows_pyautogui",
                "status": "ready",
                "locator_root": str(self.config.artifact_dir / "simulated_locators"),
                "locators": [],
            }
        precheck = self._live_precheck(require_execute=False, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.list_locators"
            return precheck
        return self._live_get("equipment.pyautogui.list_locators", "/locators")

    def capture_locator(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Capture a Windows screen region as an image locator for UTM protocol assertions."""
        payload = dict(payload or {})
        if not self.config.allow_screenshot:
            return self._failure(
                tool="equipment.pyautogui.capture_locator",
                status="blocked",
                failure_code="PYAUTOGUI_SCREENSHOT_BLOCKED",
                message="Locator capture requires screenshots, but screenshots are disabled by config.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "allow_screenshot=false"}],
            )
        region = payload.get("region")
        if not isinstance(region, list) or len(region) != 4:
            return self._failure(
                tool="equipment.pyautogui.capture_locator",
                status="blocked",
                failure_code="PYAUTOGUI_LOCATOR_REGION_REQUIRED",
                message="region=[x,y,width,height] is required for locator capture.",
                step_trace=[{"step": "VALIDATE_REGION", "status": "blocked", "detail": "missing region"}],
            )
        if not self._should_use_live(payload, for_execution=True):
            return self._simulated_capture_locator(payload)
        precheck = self._live_precheck(require_execute=True, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.capture_locator"
            return precheck
        public_payload = self._public_payload({**payload, "runtime_mode": "live"})
        return self._live_post("equipment.pyautogui.capture_locator", "/locators/capture", public_payload)

    def utm_profile_status(self) -> dict[str, Any]:
        """Return the active UTM protocol profile used by autonomous Equipment runs."""
        stored = _sanitize_utm_profile(_read_json_object(self.config.utm_profile_memory_path))
        program_id = str(stored.get("program_id") or "utm_compression_start_v1")
        program = dict(self.config.registered_programs.get(program_id, {}))
        profile = {"program_id": program_id}
        source = "memory" if stored else "registered_program"
        for key in UTM_PROFILE_PROGRAM_KEYS:
            if key in stored:
                profile[key] = stored[key]
            elif key in program:
                profile[key] = program[key]
        if stored.get("updated_at"):
            profile["updated_at"] = stored["updated_at"]
        return {
            "ok": True,
            "tool": "equipment.pyautogui.utm_profile",
            "mode": self.config.mode,
            "bridge": "windows_pyautogui",
            "status": "ready",
            "source": source,
            "profile_exists": self.config.utm_profile_memory_path.exists(),
            "profile_memory_path": str(self.config.utm_profile_memory_path),
            "profile": profile,
            "program": program,
        }

    def save_utm_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist UTM locator/export settings so GUI, CUI, and autonomous loop stay aligned."""
        profile = _sanitize_utm_profile(dict(payload or {}))
        if not profile:
            return self._failure(
                tool="equipment.pyautogui.save_utm_profile",
                status="blocked",
                failure_code="PYAUTOGUI_UTM_PROFILE_INVALID",
                message="A valid UTM profile payload is required.",
                step_trace=[{"step": "SAVE_UTM_PROFILE", "status": "blocked", "detail": "invalid profile"}],
            )
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.config.utm_profile_memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.utm_profile_memory_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
        try:
            self.config.utm_profile_memory_path.chmod(0o600)
        except OSError:
            pass
        self.config.registered_programs = _apply_utm_profile_to_programs(self.config.registered_programs, profile)
        status = self.utm_profile_status()
        status.update(
            {
                "tool": "equipment.pyautogui.save_utm_profile",
                "status": "saved",
                "message": "UTM protocol profile saved and will be merged into autonomous Equipment Agent runs.",
            }
        )
        return status

    def connection_status(self) -> dict[str, Any]:
        """Return saved Windows bridge candidate settings without exposing the full token."""
        memory = self.load_connection_memory()
        token = self._token()
        url = self._bridge_url()
        selected_alias, selected = self._selected_candidate(memory)
        candidates = []
        stored_candidates = self._candidate_map(memory)
        for alias, raw in sorted(stored_candidates.items()):
            candidate = raw if isinstance(raw, dict) else {}
            candidates.append(
                {
                    "candidate_alias": str(alias),
                    "bridge_url": str(candidate.get("bridge_url", "")),
                    "host": str(candidate.get("host", "")),
                    "port": candidate.get("port", self.config.discovery_port),
                    "selected": str(alias) == selected_alias,
                    "token_configured": bool(candidate.get("token")),
                    "allow_live_execute": bool(candidate.get("allow_live_execute", False)),
                    "last_status": candidate.get("last_status"),
                    "last_checked": candidate.get("last_checked"),
                }
            )
        return {
            "ok": True,
            "tool": "equipment.pyautogui.connection_status",
            "mode": self.config.mode,
            "bridge": "windows_pyautogui",
            "connection_memory_path": str(self.config.connection_memory_path),
            "selected_candidate": selected_alias,
            "bridge_url": url,
            "host": selected.get("host", memory.get("host", "")),
            "port": selected.get("port", memory.get("port", self.config.discovery_port)),
            "token_configured": bool(token),
            "selected": bool(url),
            "last_checked": selected.get("last_checked", memory.get("last_checked")),
            "last_status": selected.get("last_status", memory.get("last_status")),
            "candidates": candidates,
        }

    def save_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a selected Windows bridge candidate for quick connection."""
        alias = self._clean_candidate_alias(
            payload.get("candidate_alias")
            or payload.get("alias")
            or payload.get("name")
            or payload.get("profile_name")
            or payload.get("connection_name")
        )
        if not alias:
            return self._failure(
                tool="equipment.pyautogui.save_connection",
                status="blocked",
                failure_code="PYAUTOGUI_CANDIDATE_ALIAS_REQUIRED",
                message="A candidate alias is required.",
                step_trace=[{"step": "SAVE_CANDIDATE", "status": "blocked", "detail": "missing candidate alias"}],
            )
        host = str(payload.get("host") or "").strip()
        raw_url = str(payload.get("bridge_url") or payload.get("url") or "").strip().rstrip("/")
        port = int(payload.get("port") or self.config.discovery_port)
        if not raw_url and host:
            raw_url = f"http://{host}:{port}"
        if not raw_url:
            return self._failure(
                tool="equipment.pyautogui.save_connection",
                status="blocked",
                failure_code="PYAUTOGUI_BRIDGE_URL_REQUIRED",
                message="bridge_url or host is required.",
                step_trace=[{"step": "SAVE_CONNECTION", "status": "blocked", "detail": "missing url"}],
            )
        token = str(payload.get("token") or "").strip()
        existing = self.load_connection_memory()
        candidates = self._candidate_map(existing)
        previous = candidates.get(alias) if isinstance(candidates.get(alias), dict) else {}
        if not token and previous:
            token = str(previous.get("token", "")).strip()
        if not token:
            return self._failure(
                tool="equipment.pyautogui.save_connection",
                status="blocked",
                failure_code="PYAUTOGUI_TOKEN_REQUIRED",
                message="A valid token is required before saving a Windows PyAutoGUI bridge candidate.",
                step_trace=[{"step": "SAVE_CANDIDATE", "status": "blocked", "detail": "missing token"}],
            )
        candidate = {
            "candidate_alias": alias,
            "bridge_url": raw_url,
            "host": host or raw_url.split("//", 1)[-1].split(":", 1)[0],
            "port": port,
            "token": token,
            "token_header": str(payload.get("token_header") or self.config.token_header),
            "allow_live_execute": bool(payload.get("allow_live_execute", True)),
            "last_checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "last_status": str(payload.get("last_status") or "selected"),
        }
        candidates[alias] = candidate
        memory = {
            "selected_candidate": alias,
            "candidates": candidates,
            **candidate,
        }
        self._write_connection_memory(memory)
        return self.connection_status()

    def select_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Select a saved Windows bridge candidate for quick connection."""
        alias = self._clean_candidate_alias(payload.get("candidate_alias") or payload.get("alias"))
        memory = self.load_connection_memory()
        candidates = self._candidate_map(memory)
        if not alias or alias not in candidates:
            return self._failure(
                tool="equipment.pyautogui.select_candidate",
                status="blocked",
                failure_code="PYAUTOGUI_CANDIDATE_NOT_FOUND",
                message=f"Saved Windows PyAutoGUI bridge candidate not found: {alias}",
                step_trace=[{"step": "SELECT_CANDIDATE", "status": "blocked", "detail": alias}],
            )
        selected = dict(candidates[alias])
        selected["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        selected["last_status"] = "selected"
        candidates[alias] = selected
        memory = {"selected_candidate": alias, "candidates": candidates, **selected}
        self._write_connection_memory(memory)
        return self.connection_status()

    def delete_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delete a saved Windows bridge candidate."""
        alias = self._clean_candidate_alias(payload.get("candidate_alias") or payload.get("alias"))
        memory = self.load_connection_memory()
        candidates = self._candidate_map(memory)
        if not alias or alias not in candidates:
            return self._failure(
                tool="equipment.pyautogui.delete_candidate",
                status="blocked",
                failure_code="PYAUTOGUI_CANDIDATE_NOT_FOUND",
                message=f"Saved Windows PyAutoGUI bridge candidate not found: {alias}",
                step_trace=[{"step": "DELETE_CANDIDATE", "status": "blocked", "detail": alias}],
            )
        candidates.pop(alias, None)
        next_alias = sorted(candidates)[0] if candidates else ""
        if next_alias:
            selected = dict(candidates[next_alias])
            memory = {"selected_candidate": next_alias, "candidates": candidates, **selected}
        else:
            memory = {"selected_candidate": "", "candidates": {}}
        self._write_connection_memory(memory)
        return self.connection_status()

    def run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an allowlisted sequence or registered program."""
        payload = dict(payload or {})
        if not self.config.enabled:
            return self._failure(
                tool="equipment.pyautogui.run",
                mode="disabled",
                status="blocked",
                failure_code="PYAUTOGUI_BRIDGE_DISABLED",
                message="Windows PyAutoGUI bridge is disabled in config.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "bridge disabled"}],
            )

        runtime_payload = self._runtime_program_payload(payload)
        if not self._should_use_live(payload, for_execution=True):
            return self._attach_control_profile(self._run_simulator(runtime_payload), runtime_payload)

        precheck = self._live_precheck(require_execute=True, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.run"
            return precheck
        validation = self._validate_sequence_payload(runtime_payload)
        if validation:
            return validation
        result = self._live_post("equipment.pyautogui.run", "/execute", self._public_payload(runtime_payload))
        return self._attach_control_profile(result, runtime_payload)

    def _should_use_live(self, payload: dict[str, Any], *, for_execution: bool) -> bool:
        if bool(payload.get("force_live_bridge")):
            return True
        runtime_mode = str(payload.get("runtime_mode", "")).strip().lower()
        if runtime_mode != "live":
            test_promotion = self.config.test_live_promotion
            return bool(
                for_execution
                and runtime_mode == "test"
                and test_promotion.get("enabled")
                and test_promotion.get("transport") == "real"
                and test_promotion.get("allow_real_network_in_test")
            )
        return True

    def _live_precheck(self, *, require_execute: bool, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        payload = payload or {}
        setup_gui_execute = bool(payload.get("confirm_setup_gui_execute"))
        memory = self.load_connection_memory()
        _, selected = self._selected_candidate(memory)
        profile_allows_execute = bool(selected.get("allow_live_execute", False))
        if require_execute and not self.config.allow_live_execute and not setup_gui_execute and not profile_allows_execute:
            return self._failure(
                tool="equipment.pyautogui.run",
                mode="live",
                status="blocked",
                failure_code="PYAUTOGUI_LIVE_EXECUTION_BLOCKED",
                message="Live Windows PyAutoGUI execution is disabled by config.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "allow_live_execute=false"}],
            )
        if not self._bridge_url():
            return self._failure(
                tool="equipment.pyautogui",
                mode="live",
                status="connection_info_required",
                failure_code="PYAUTOGUI_BRIDGE_URL_REQUIRED",
                requires_connection_info=True,
                message=f"Set {self.config.bridge_url_env}=http://<windows-private-ip>:8765.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "missing bridge URL"}],
            )
        if self.config.token_env and not self._token():
            return self._failure(
                tool="equipment.pyautogui",
                mode="live",
                status="connection_info_required",
                failure_code="PYAUTOGUI_TOKEN_REQUIRED",
                requires_connection_info=True,
                message=f"Set {self.config.token_env} before live Windows bridge calls.",
                step_trace=[{"step": "PRECHECK", "status": "blocked", "detail": "missing bridge token"}],
            )
        return None

    def _run_simulator(self, payload: dict[str, Any]) -> dict[str, Any]:
        sequence_id = str(payload.get("sequence_id") or f"sim-{int(time.time())}")
        program_id = str(payload.get("program_id") or "").strip()
        callback = payload.get("_event_callback")
        event_callback = callback if callable(callback) else None

        trace: list[dict[str, Any]] = []

        def step(name: str, status: str, detail: str = "") -> None:
            item = {"step": name, "status": status}
            if detail:
                item["detail"] = detail
            trace.append(item)
            self._emit(event_callback, "equipment.pyautogui.run", name, status, detail=detail, sequence_id=sequence_id, program_id=program_id)

        step("PRECHECK", "ok", "simulator")
        if program_id:
            programs = self.config.registered_programs
            if program_id not in programs:
                step("RESOLVE_PROGRAM", "blocked", program_id)
                return self._failure(
                    tool="equipment.pyautogui.run",
                    mode="simulator",
                    status="blocked",
                    failure_code="PYAUTOGUI_PROGRAM_NOT_FOUND",
                    message=f"Registered PyAutoGUI macro program not found: {program_id}",
                    program_id=program_id,
                    sequence_id=sequence_id,
                    step_trace=trace,
                )
            step("RESOLVE_PROGRAM", "ok", program_id)
            pyautogui_available = bool(payload.get("simulate_pyautogui_available", self.config.simulator.get("pyautogui_available", True)))
            if programs[program_id].get("requires_pyautogui", False) and not pyautogui_available:
                step("HEALTH", "blocked", "pyautogui import failed")
                return self._failure(
                    tool="equipment.pyautogui.run",
                    mode="simulator",
                    status="blocked",
                    failure_code="PYAUTOGUI_NOT_INSTALLED",
                    requires_install=True,
                    message="PyAutoGUI is not installed on the Windows bridge host. Install with: py -m pip install pyautogui",
                    program_id=program_id,
                    sequence_id=sequence_id,
                    step_trace=trace,
                )
            if program_id == "program1":
                step("HEALTH", "ok")
                step("EXECUTE_PROGRAM", "ok", "demo_mouse_wiggle")
                step("DONE", "ok", "program1 completed")
                return {
                    "ok": True,
                    "tool": "equipment.pyautogui.run",
                    "mode": "simulator",
                    "bridge": "windows_pyautogui",
                    "status": "completed",
                    "sequence_id": sequence_id,
                    "program_id": program_id,
                    "program_type": "connectivity_demo",
                    "program_log": "program1 completed",
                    "step_trace": trace,
                    "failure_code": None,
                }
            program_type = str(programs[program_id].get("program_type") or "")
            if program_type.startswith("utm_") or program_id.startswith("utm_"):
                return self._run_simulated_utm_protocol(
                    payload=payload,
                    sequence_id=sequence_id,
                    program_id=program_id,
                    trace=trace,
                    event_callback=event_callback,
                )

        sequence = self._sequence_from_payload(payload)
        validation = self._validate_actions(sequence)
        if validation:
            validation["sequence_id"] = sequence_id
            validation["step_trace"] = trace + validation.get("step_trace", [])
            return validation
        for action in sequence:
            action_name = str(action.get("action", "")).strip()
            if action_name == "health":
                step("HEALTH", "ok")
            elif action_name == "screenshot":
                if not self.config.allow_screenshot:
                    step("SCREENSHOT", "blocked", "screenshot disabled")
                    return self._failure(
                        tool="equipment.pyautogui.run",
                        mode="simulator",
                        status="blocked",
                        failure_code="PYAUTOGUI_SCREENSHOT_BLOCKED",
                        message="Screenshot action is disabled by config.",
                        sequence_id=sequence_id,
                        step_trace=trace,
                    )
                step("SCREENSHOT", "ok", str(self.config.artifact_dir / str(self.config.simulator.get("screenshot_name", "simulated_windows_screen.png"))))
            elif action_name == "wait":
                step("WAIT", "ok", f"{float(action.get('seconds', 0.1)):.2f}s")
            elif action_name == "log":
                step("LOG", "ok", str(action.get("message", "")))
            else:
                step("EXECUTE_STEP", "ok", action_name)
        step("DONE", "ok")
        return {
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "mode": "simulator",
            "bridge": "windows_pyautogui",
            "status": "completed",
            "sequence_id": sequence_id,
            "step_trace": trace,
            "failure_code": None,
        }

    def _run_simulated_utm_protocol(
        self,
        *,
        payload: dict[str, Any],
        sequence_id: str,
        program_id: str,
        trace: list[dict[str, Any]],
        event_callback: ToolEventCallback | None,
    ) -> dict[str, Any]:
        run_id = str(payload.get("run_id") or sequence_id or f"sim-{int(time.time())}")
        experiment = payload.get("experiment_spec") if isinstance(payload.get("experiment_spec"), dict) else {}
        specimen_id = str(
            payload.get("specimen_id")
            or experiment.get("specimen_id")
            or experiment.get("candidate_id")
            or "specimen-simulated"
        )
        safe_specimen = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in specimen_id)[:96]
        artifact_dir = self.config.artifact_dir / run_id / "utm"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        artifact_id = f"utm_csv_{safe_specimen}_{timestamp}"
        local_path = artifact_dir / f"{artifact_id}.csv"
        columns = ["time_s", "displacement_mm", "force_N"]
        rows: list[str] = [",".join(columns)]
        for idx in range(80):
            t = idx * 0.25
            displacement = idx * 0.05
            force = max(0.0, 18.0 * displacement - 1.1 * displacement * displacement + (idx % 5) * 0.45)
            rows.append(f"{t:.3f},{displacement:.4f},{force:.4f}")
        local_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        data = local_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)
        row_count = len(rows) - 1
        windows_path = f"C:/ATR/utm_exports/{run_id}/{local_path.name}"

        def step(name: str, status: str, detail: str = "") -> None:
            item = {"step": name, "status": status}
            if detail:
                item["detail"] = detail
            trace.append(item)
            self._emit(event_callback, "equipment.pyautogui.run", name, status, detail=detail, sequence_id=sequence_id, program_id=program_id)

        step("HEALTH", "ok")
        step("FOCUS_WINDOW", "ok", "UTM software")
        step("SCREEN_ASSERT_BEFORE", "ok", "ready_state")
        step("EXECUTE_START_MACRO", "ok", "start_button")
        step("SCREEN_ASSERT_RUNNING", "ok", "running_state")
        step("PHYSICAL_ASSERT", "ok", "simulated crosshead motion and force curve")
        step("SCREEN_ASSERT_COMPLETE", "ok", "complete_state")
        step("SAVE_EXPORT", "ok", windows_path)
        step("PULL_ARTIFACT", "ok", str(local_path))
        step("PARSE_PROBE", "ok", f"rows={row_count}; columns={','.join(columns)}")
        step("DONE", "ok", "UTM protocol verified complete")

        artifact = {
            "kind": "utm_csv",
            "artifact_id": artifact_id,
            "windows_path": windows_path,
            "local_path": str(local_path),
            "path": str(local_path),
            "filename": local_path.name,
            "size_bytes": size_bytes,
            "sha256": digest,
            "stable_for_sec": 2.0,
            "row_count_probe": row_count,
            "columns_probe": columns,
        }
        screen_checks = [
            {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "simulated_before_start"},
            {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "simulated_after_start"},
            {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": "simulated_after_complete"},
        ]
        physical_checks = {
            "vision_motion_confirmed": True,
            "specimen_alignment_ok": True,
            "fixture_safe_to_access": True,
            "evidence_frame_ids": ["sim-frame-pre", "sim-frame-motion", "sim-frame-complete"],
            "simulated": True,
        }
        data_acquisition = {
            "status": "pulled_to_linux",
            "save_method": "simulated_auto_export",
            "save_attempted_by_agent": True,
            "save_confirmation_screen_ok": True,
            "windows_path": windows_path,
            "linux_path": str(local_path),
            "sha256": digest,
            "size_bytes": size_bytes,
            "row_count_probe": row_count,
            "columns_probe": columns,
        }
        return {
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "mode": "simulator",
            "bridge": "windows_pyautogui",
            "status": "verified_complete",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "utm_protocol",
            "program_log": "UTM protocol verified complete in simulator.",
            "result_file": str(local_path),
            "utm_csv_path": str(local_path),
            "output_artifacts": [artifact],
            "data_integrity": artifact,
            "screen_checks": screen_checks,
            "physical_checks": physical_checks,
            "data_acquisition": data_acquisition,
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": True,
                "save_completed": True,
                "data_file_created": True,
                "data_parse_probe_ok": True,
            },
            "step_trace": trace,
            "failure_code": None,
        }

    def _simulated_screenshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        checkpoint = str(payload.get("checkpoint") or "manual")
        run_id = str(payload.get("run_id") or "simulated-calibration")
        artifact_id = f"sim_screen_{checkpoint}_{int(time.time())}"
        path = self.config.artifact_dir / run_id / "screenshots" / f"{artifact_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
        data = path.read_bytes()
        artifact = {
            "kind": "screen_png",
            "artifact_id": artifact_id,
            "filename": path.name,
            "local_path": str(path),
            "path": str(path),
            "windows_path": f"simulator://{path.name}",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": "image/png",
        }
        return {
            "ok": True,
            "tool": "equipment.pyautogui.screenshot",
            "mode": "simulator",
            "bridge": "windows_pyautogui",
            "status": "captured",
            "artifact": artifact,
            "output_artifacts": [artifact],
            "step_trace": [{"step": "SCREENSHOT", "status": "ok", "detail": str(path)}],
            "failure_code": None,
        }

    def _simulated_capture_locator(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = self._clean_candidate_alias(payload.get("name") or payload.get("target") or "locator") or "locator"
        program_id = self._clean_candidate_alias(payload.get("program_id") or "utm_compression_start_v1") or "utm_compression_start_v1"
        region = [int(float(item)) for item in payload.get("region", [0, 0, 1, 1])]
        artifact_id = f"sim_locator_{program_id}_{name}_{int(time.time())}"
        path = self.config.artifact_dir / "simulated_locators" / program_id / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
        data = path.read_bytes()
        locator = {
            "image_path": str(path),
            "confidence": float(payload.get("confidence", 0.8)),
            "region": region,
            "target": name,
        }
        artifact = {
            "kind": "locator_png",
            "artifact_id": artifact_id,
            "filename": path.name,
            "local_path": str(path),
            "path": str(path),
            "windows_path": f"simulator://{program_id}/{path.name}",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": "image/png",
        }
        return {
            "ok": True,
            "tool": "equipment.pyautogui.capture_locator",
            "mode": "simulator",
            "bridge": "windows_pyautogui",
            "status": "captured",
            "program_id": program_id,
            "locator_name": name,
            "locator": locator,
            "artifact": artifact,
            "output_artifacts": [artifact],
            "step_trace": [{"step": "CAPTURE_LOCATOR", "status": "ok", "detail": str(path)}],
            "failure_code": None,
        }

    def _validate_sequence_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._validate_actions(self._sequence_from_payload(payload))

    def _validate_actions(self, sequence: list[dict[str, Any]]) -> dict[str, Any] | None:
        max_steps = int(self.config.limits.get("max_steps", 50))
        if len(sequence) > max_steps:
            return self._failure(
                tool="equipment.pyautogui.run",
                status="blocked",
                failure_code="PYAUTOGUI_TOO_MANY_STEPS",
                message=f"PyAutoGUI sequence has {len(sequence)} steps; max is {max_steps}.",
                step_trace=[{"step": "VALIDATE_SEQUENCE", "status": "blocked", "detail": "too many steps"}],
            )
        for action in sequence:
            action_name = str(action.get("action", "")).strip()
            if action_name not in self.config.allowed_actions:
                return self._failure(
                    tool="equipment.pyautogui.run",
                    status="blocked",
                    failure_code="PYAUTOGUI_ACTION_NOT_ALLOWED",
                    message=f"PyAutoGUI action is not allowed: {action_name}",
                    step_trace=[{"step": "VALIDATE_SEQUENCE", "status": "blocked", "detail": action_name}],
                )
            if action_name == "wait":
                seconds = float(action.get("seconds", action.get("duration_sec", 0)))
                max_wait = float(self.config.limits.get("max_wait_sec", 30))
                if seconds < 0 or seconds > max_wait:
                    return self._failure(
                        tool="equipment.pyautogui.run",
                        status="blocked",
                        failure_code="PYAUTOGUI_WAIT_OUT_OF_BOUNDS",
                        message=f"Wait duration {seconds} exceeds allowed range 0..{max_wait}.",
                        step_trace=[{"step": "VALIDATE_SEQUENCE", "status": "blocked", "detail": "wait"}],
                    )
            if action_name == "write":
                max_chars = int(self.config.limits.get("max_write_chars", 512))
                if len(str(action.get("text", ""))) > max_chars:
                    return self._failure(
                        tool="equipment.pyautogui.run",
                        status="blocked",
                        failure_code="PYAUTOGUI_WRITE_TOO_LONG",
                        message=f"Write text exceeds max length {max_chars}.",
                        step_trace=[{"step": "VALIDATE_SEQUENCE", "status": "blocked", "detail": "write"}],
                    )
        return None

    def _sequence_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        sequence = payload.get("sequence")
        if isinstance(sequence, list) and sequence:
            return [dict(item) for item in sequence if isinstance(item, dict)]
        program_id = str(payload.get("program_id") or "").strip()
        if program_id and program_id in self.config.registered_programs:
            raw = self.config.registered_programs[program_id].get("sequence", [])
            if isinstance(raw, list):
                return [dict(item) for item in raw if isinstance(item, dict)]
        return [dict(item) for item in self.config.default_sequence]

    def _live_get(self, tool: str, path: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.config.request_timeout_sec) as client:
                response = client.get(self._url(path), headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            failure_code = "PYAUTOGUI_AUTH_FAILED" if exc.response.status_code in {401, 403} else "PYAUTOGUI_BRIDGE_HTTP_ERROR"
            return self._failure(
                tool=tool,
                mode="live",
                status="blocked",
                failure_code=failure_code,
                message=f"Windows PyAutoGUI bridge returned HTTP {exc.response.status_code}.",
                step_trace=[{"step": "CONNECT", "status": "blocked", "detail": str(exc.response.status_code)}],
            )
        except Exception as exc:
            return self._failure(
                tool=tool,
                mode="live",
                status="unreachable",
                failure_code="PYAUTOGUI_BRIDGE_UNREACHABLE",
                message=f"Windows PyAutoGUI bridge unreachable: {exc.__class__.__name__}",
                step_trace=[{"step": "CONNECT", "status": "failed", "detail": exc.__class__.__name__}],
            )
        return self._normalize_live_response(tool, data, latency_ms=(time.perf_counter() - started) * 1000.0)

    def _live_post(self, tool: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.config.request_timeout_sec) as client:
                response = client.post(self._url(path), headers=self._headers(), json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            failure_code = "PYAUTOGUI_AUTH_FAILED" if exc.response.status_code in {401, 403} else "PYAUTOGUI_BRIDGE_HTTP_ERROR"
            return self._failure(
                tool=tool,
                mode="live",
                status="blocked",
                failure_code=failure_code,
                message=f"Windows PyAutoGUI bridge returned HTTP {exc.response.status_code}.",
                step_trace=[{"step": "CONNECT", "status": "blocked", "detail": str(exc.response.status_code)}],
            )
        except Exception as exc:
            return self._failure(
                tool=tool,
                mode="live",
                status="unreachable",
                failure_code="PYAUTOGUI_BRIDGE_UNREACHABLE",
                message=f"Windows PyAutoGUI bridge unreachable: {exc.__class__.__name__}",
                step_trace=[{"step": "CONNECT", "status": "failed", "detail": exc.__class__.__name__}],
            )
        normalized = self._normalize_live_response(tool, data, latency_ms=(time.perf_counter() - started) * 1000.0)
        if normalized.get("output_artifacts"):
            normalized = self._pull_live_artifacts(normalized)
        return normalized

    @staticmethod
    def _probe_utm_csv_bytes(data: bytes) -> dict[str, Any]:
        text = data.decode("utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        columns = [item.strip() for item in lines[0].split(",")] if lines else []
        row_count = max(0, len(lines) - 1)
        required = {"time_s", "displacement_mm", "force_N"}
        missing = sorted(required.difference(columns))

        def result(ok: bool, *, failure_code: str | None = None, message: str = "", data_quality: dict[str, Any] | None = None) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "ok": ok,
                "row_count_probe": row_count,
                "columns_probe": columns,
                "missing_columns": missing,
                "data_quality": data_quality or {},
            }
            if failure_code:
                payload["failure_code"] = failure_code
            if message:
                payload["message"] = message
            return payload

        if missing:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message=f"Missing UTM columns: {', '.join(missing)}")
        if row_count < 2:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message="UTM export must contain at least two data rows for signal validation.")
        index = {name: columns.index(name) for name in required}
        numeric_rows: list[dict[str, float]] = []
        invalid_numeric_rows = 0
        for line in lines[1:]:
            parts = [item.strip() for item in line.split(",")]
            try:
                numeric_rows.append({"time_s": float(parts[index["time_s"]]), "displacement_mm": float(parts[index["displacement_mm"]]), "force_N": float(parts[index["force_N"]])})
            except (IndexError, TypeError, ValueError):
                invalid_numeric_rows += 1
        if len(numeric_rows) < 2:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message="UTM export must contain at least two numeric data rows.")
        eps = 1e-9
        time_values = [row["time_s"] for row in numeric_rows]
        displacement_values = [row["displacement_mm"] for row in numeric_rows]
        force_values = [row["force_N"] for row in numeric_rows]
        force_range = max(force_values) - min(force_values)
        displacement_range = max(displacement_values) - min(displacement_values)
        time_monotonic = all((b - a) >= -eps for a, b in zip(time_values, time_values[1:]))
        displacement_increasing = all((b - a) >= -eps for a, b in zip(displacement_values, displacement_values[1:]))
        displacement_decreasing = all((b - a) <= eps for a, b in zip(displacement_values, displacement_values[1:]))
        displacement_monotonic = displacement_increasing or displacement_decreasing
        force_nonzero = any(abs(value) > eps for value in force_values)
        force_changes = force_range > eps
        displacement_changes = displacement_range > eps
        quality = {
            "numeric_row_count": len(numeric_rows),
            "invalid_numeric_row_count": invalid_numeric_rows,
            "force_nonzero": force_nonzero,
            "force_changes": force_changes,
            "force_range_N": force_range,
            "force_min_N": min(force_values),
            "force_max_N": max(force_values),
            "displacement_changes": displacement_changes,
            "displacement_range_mm": displacement_range,
            "displacement_min_mm": min(displacement_values),
            "displacement_max_mm": max(displacement_values),
            "displacement_monotonic": displacement_monotonic,
            "displacement_direction": "increasing" if displacement_increasing else "decreasing" if displacement_decreasing else "mixed",
            "time_monotonic_non_decreasing": time_monotonic,
            "time_min_s": min(time_values),
            "time_max_s": max(time_values),
        }
        if not time_monotonic:
            return result(False, failure_code="UTM_DATA_NON_MONOTONIC_TIME", message="UTM time_s values are not monotonic non-decreasing.", data_quality=quality)
        if not displacement_changes:
            return result(False, failure_code="UTM_DATA_NO_DISPLACEMENT_SIGNAL", message="UTM displacement_mm does not change across samples.", data_quality=quality)
        if not displacement_monotonic:
            return result(False, failure_code="UTM_DATA_NON_MONOTONIC_DISPLACEMENT", message="UTM displacement_mm is not monotonic in either direction.", data_quality=quality)
        if not force_nonzero or not force_changes:
            return result(False, failure_code="UTM_DATA_NO_FORCE_SIGNAL", message="UTM force_N has no nonzero changing load signal.", data_quality=quality)
        return result(True, data_quality=quality)


    def _pull_live_artifacts(self, response: dict[str, Any]) -> dict[str, Any]:
        artifacts = response.get("output_artifacts") if isinstance(response.get("output_artifacts"), list) else []
        if not artifacts:
            return response
        run_id = str(response.get("run_id") or response.get("sequence_id") or "live")
        pulled: list[dict[str, Any]] = []
        ledger: dict[str, Any] = {
            "status": "pending",
            "attempted_count": 0,
            "pulled_count": 0,
            "failed_count": 0,
            "metadata_only_count": 0,
            "pulled_artifacts": [],
            "failed_artifacts": [],
            "local_paths": [],
            "data_artifact_pulled": False,
            "screen_artifact_count": 0,
            "screen_artifact_paths": [],
        }

        def record_failure(artifact: dict[str, Any], reason: str, detail: str = "") -> None:
            ledger["failed_count"] = int(ledger["failed_count"]) + 1
            ledger["failed_artifacts"].append(
                {
                    "artifact_id": str(artifact.get("artifact_id") or ""),
                    "kind": str(artifact.get("kind") or ""),
                    "reason": reason,
                    "detail": detail,
                }
            )

        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            if not artifact_id:
                record_failure(artifact, "ARTIFACT_ID_MISSING")
                pulled.append(artifact)
                continue
            ledger["attempted_count"] = int(ledger["attempted_count"]) + 1
            try:
                with httpx.Client(timeout=self.config.request_timeout_sec) as client:
                    reply = client.get(self._url(f"/artifacts/{artifact_id}"), headers=self._headers())
                    reply.raise_for_status()
                    payload = reply.json()
            except Exception as exc:
                record_failure(artifact, "ARTIFACT_PULL_FAILED", exc.__class__.__name__)
                pulled.append(artifact)
                continue
            if not isinstance(payload, dict):
                record_failure(artifact, "ARTIFACT_PAYLOAD_INVALID", type(payload).__name__)
                pulled.append(artifact)
                continue
            filename = str(payload.get("filename") or artifact.get("filename") or f"{artifact_id}.dat")
            content_bytes: bytes | None = None
            if isinstance(payload.get("content_base64"), str) and payload.get("content_base64"):
                try:
                    content_bytes = base64.b64decode(str(payload["content_base64"]))
                except Exception as exc:
                    record_failure(artifact, "ARTIFACT_BASE64_DECODE_FAILED", exc.__class__.__name__)
                    content_bytes = None
            elif isinstance(payload.get("content_text"), str):
                content_bytes = str(payload["content_text"]).encode("utf-8")
            if content_bytes is None:
                ledger["metadata_only_count"] = int(ledger["metadata_only_count"]) + 1
                record_failure(artifact, "ARTIFACT_CONTENT_MISSING")
                pulled.append({**artifact, **{key: value for key, value in payload.items() if key != "content_base64"}})
                continue
            safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in filename)[:160] or f"{artifact_id}.dat"
            kind = str(artifact.get("kind") or payload.get("kind") or "")
            if kind == "utm_csv":
                local_dir = self.config.artifact_dir / run_id / "utm"
            elif kind in {"screen_png", "screenshot"}:
                local_dir = self.config.artifact_dir / run_id / "screenshots"
            elif kind == "locator_png":
                local_dir = self.config.artifact_dir / run_id / "locators"
            else:
                local_dir = self.config.artifact_dir / run_id / "artifacts"
            local_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_dir / safe_name
            local_path.write_bytes(content_bytes)
            digest = hashlib.sha256(content_bytes).hexdigest()
            merged = {**artifact, **{key: value for key, value in payload.items() if key != "content_base64"}}
            local_parse_probe: dict[str, Any] = {}
            if kind == "utm_csv":
                local_parse_probe = self._probe_utm_csv_bytes(content_bytes)
                merged.update(
                    {
                        "local_parse_probe": local_parse_probe,
                        "local_parse_ok": bool(local_parse_probe.get("ok")),
                        "row_count_probe": local_parse_probe.get("row_count_probe", merged.get("row_count_probe", 0)),
                        "columns_probe": local_parse_probe.get("columns_probe", merged.get("columns_probe", [])),
                        "missing_columns": local_parse_probe.get("missing_columns", []),
                        "data_quality": local_parse_probe.get("data_quality", {}),
                        "parse_failure_code": local_parse_probe.get("failure_code"),
                        "parse_failure_message": local_parse_probe.get("message", ""),
                    }
                )
            merged.update({"local_path": str(local_path), "path": str(local_path), "sha256": digest, "size_bytes": len(content_bytes), "pulled_to_linux": True})
            pulled.append(merged)
            ledger["pulled_count"] = int(ledger["pulled_count"]) + 1
            pulled_record = {
                "artifact_id": artifact_id,
                "kind": kind,
                "local_path": str(local_path),
                "sha256": digest,
                "size_bytes": len(content_bytes),
            }
            if kind == "utm_csv":
                pulled_record.update(
                    {
                        "parse_ok": bool(local_parse_probe.get("ok")),
                        "row_count_probe": local_parse_probe.get("row_count_probe", 0),
                        "columns_probe": local_parse_probe.get("columns_probe", []),
                        "missing_columns": local_parse_probe.get("missing_columns", []),
                        "data_quality": local_parse_probe.get("data_quality", {}),
                        "parse_failure_code": local_parse_probe.get("failure_code"),
                    }
                )
                ledger["data_artifact_probe"] = local_parse_probe
                ledger["data_artifact_parse_ok"] = bool(local_parse_probe.get("ok"))
            ledger["pulled_artifacts"].append(pulled_record)
            ledger["local_paths"].append(str(local_path))
            if kind in {"screen_png", "screenshot"}:
                ledger["screen_artifact_count"] = int(ledger["screen_artifact_count"]) + 1
                ledger["screen_artifact_paths"].append(str(local_path))
            if str(merged.get("kind") or "") == "utm_csv":
                parse_ok = bool(local_parse_probe.get("ok"))
                ledger["data_artifact_pulled"] = True
                if parse_ok:
                    response["result_file"] = str(local_path)
                    response["utm_csv_path"] = str(local_path)
                response["data_integrity"] = merged
                data_acquisition = response.get("data_acquisition") if isinstance(response.get("data_acquisition"), dict) else {}
                data_acquisition = dict(data_acquisition)
                data_acquisition.update(
                    {
                        "status": "pulled_to_linux" if parse_ok else "pulled_to_linux_parse_failed",
                        "linux_path": str(local_path),
                        "local_path": str(local_path),
                        "sha256": digest,
                        "size_bytes": len(content_bytes),
                        "artifact_pull_status": "pulled_parse_ok" if parse_ok else "pulled_parse_failed",
                        "local_parse_probe": local_parse_probe,
                        "local_parse_ok": parse_ok,
                    }
                )
                if merged.get("windows_path") and not data_acquisition.get("windows_path"):
                    data_acquisition["windows_path"] = str(merged["windows_path"])
                for key in ("row_count_probe", "columns_probe", "missing_columns", "data_quality", "parse_failure_code", "parse_failure_message", "stable_for_sec", "filename", "artifact_id"):
                    if key in merged:
                        data_acquisition[key] = merged[key]
                response["data_acquisition"] = data_acquisition
        ledger["status"] = "complete" if int(ledger["failed_count"]) == 0 else "partial" if int(ledger["pulled_count"]) > 0 else "failed"
        response["output_artifacts"] = pulled
        existing_records = response.get("artifact_records") if isinstance(response.get("artifact_records"), list) else []
        deduped_records: list[dict[str, Any]] = []
        seen_records: set[str] = set()
        for record in [*existing_records, *pulled]:
            if not isinstance(record, dict):
                continue
            key = str(
                record.get("artifact_id")
                or record.get("local_path")
                or record.get("linux_path")
                or record.get("path")
                or record.get("filename")
                or len(deduped_records)
            )
            if key in seen_records:
                continue
            seen_records.add(key)
            deduped_records.append(record)
        response["artifact_records"] = deduped_records
        response["artifact_pull"] = ledger
        return response

    def _normalize_live_response(self, tool: str, data: Any, *, latency_ms: float | None = None) -> dict[str, Any]:
        response = dict(data) if isinstance(data, dict) else {"raw_response": data}
        response.setdefault("ok", bool(response.get("status") in {"ready", "captured", "completed", "verified_complete", "data_ready", "exported_on_windows"}))
        response.setdefault("tool", tool)
        response.setdefault("mode", "live")
        response.setdefault("bridge", "windows_pyautogui")
        response.setdefault("step_trace", [])
        response.setdefault("failure_code", None if response.get("ok") else "PYAUTOGUI_BRIDGE_ERROR")
        bridge_url = self._bridge_url()
        response.setdefault("bridge_url", bridge_url)
        response.setdefault("bridge_host", self._bridge_host(bridge_url))
        if latency_ms is not None:
            response.setdefault("client_latency_ms", round(float(latency_ms), 2))
        return response

    @staticmethod
    def _bridge_host(bridge_url: str) -> str:
        try:
            parsed = urlparse(str(bridge_url or ""))
            return parsed.hostname or ""
        except Exception:
            return ""

    def _bridge_url(self) -> str:
        env_url = os.getenv(self.config.bridge_url_env, "").strip().rstrip("/")
        if env_url:
            return env_url
        memory = self.load_connection_memory()
        _, selected = self._selected_candidate(memory)
        return str(selected.get("bridge_url") or memory.get("bridge_url", "")).strip().rstrip("/")

    def _url(self, path: str) -> str:
        return urljoin(self._bridge_url() + "/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        token = self._token()
        headers = {"Accept": "application/json"}
        if token:
            headers[self.config.token_header] = token
        return headers

    def _token(self) -> str:
        env_token = os.getenv(self.config.token_env, "").strip() if self.config.token_env else ""
        if env_token:
            return env_token
        memory = self.load_connection_memory()
        _, selected = self._selected_candidate(memory)
        return str(selected.get("token") or memory.get("token", "")).strip()

    def load_connection_memory(self) -> dict[str, Any]:
        """Read persisted bridge selection, returning empty dict when absent/invalid."""
        try:
            if not self.config.connection_memory_path.exists():
                return {}
            data = json.loads(self.config.connection_memory_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_connection_memory(self, memory: dict[str, Any]) -> None:
        self.config.connection_memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.connection_memory_path.write_text(json.dumps(memory, indent=2, ensure_ascii=True), encoding="utf-8")
        try:
            self.config.connection_memory_path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _clean_candidate_alias(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text)
        return cleaned[:64].strip("._-")

    @staticmethod
    def _candidate_map(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
        candidates = memory.get("candidates") if isinstance(memory.get("candidates"), dict) else {}
        if candidates:
            return {str(alias): dict(value) for alias, value in candidates.items() if isinstance(value, dict)}
        connections = memory.get("connections") if isinstance(memory.get("connections"), dict) else {}
        if connections:
            return {str(alias): dict(value) for alias, value in connections.items() if isinstance(value, dict)}
        return {}

    @staticmethod
    def _selected_candidate(memory: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        candidates = WindowsPyAutoGUIBridge._candidate_map(memory)
        selected_alias = str(memory.get("selected_candidate") or memory.get("selected", "")).strip()
        if selected_alias and isinstance(candidates.get(selected_alias), dict):
            return selected_alias, dict(candidates[selected_alias])
        if candidates:
            first_alias = sorted(str(alias) for alias in candidates)[0]
            raw = candidates.get(first_alias)
            return first_alias, dict(raw) if isinstance(raw, dict) else {}
        # Legacy flat memory format.
        if memory.get("bridge_url"):
            return str(memory.get("candidate_alias") or memory.get("name") or "default"), dict(memory)
        return "", {}

    def _runtime_program_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        runtime = dict(payload or {})
        program_id = str(runtime.get("program_id") or "").strip()
        program = self.config.registered_programs.get(program_id, {}) if program_id else {}
        if isinstance(program, dict) and program:
            if "sequence" not in runtime and isinstance(program.get("sequence"), list):
                runtime["sequence"] = [dict(item) for item in program["sequence"] if isinstance(item, dict)]
            if "locators" not in runtime and isinstance(program.get("locators"), dict):
                runtime["locators"] = dict(program["locators"])
            for key in (
                "export_glob",
                "artifact_timeout_s",
                "stable_for_sec",
                "expected_export_path",
                "require_window_focus",
                "manual_save_required_if_no_artifact",
                "target_window",
                "target_window_regex",
                "screen_assertions_verified",
            ):
                if key not in runtime and key in program:
                    runtime[key] = program[key]
            if "require_screen_assertions" not in runtime:
                runtime["require_screen_assertions"] = bool(
                    program.get("require_screen_assertions", program.get("screen_assertions_required", False))
                )
            if "simulate_utm_protocol" not in runtime and "simulate_utm_protocol" in program:
                runtime["simulate_utm_protocol"] = bool(program.get("simulate_utm_protocol"))
        return runtime

    def _control_profile_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return non-secret UTM control-profile metadata for reports and traces."""
        program_id = str(payload.get("program_id") or "").strip()
        if not self._is_utm_program_id(program_id):
            return {}
        locators = payload.get("locators") if isinstance(payload.get("locators"), dict) else {}
        program = self.config.registered_programs.get(program_id, {}) if program_id else {}
        return {
            "program_id": program_id,
            "profile_memory_path": str(self.config.utm_profile_memory_path),
            "profile_memory_applied": bool(program.get("utm_profile_memory_applied")),
            "export_glob": str(payload.get("export_glob") or ""),
            "artifact_timeout_s": payload.get("artifact_timeout_s"),
            "stable_for_sec": payload.get("stable_for_sec"),
            "expected_export_path": str(payload.get("expected_export_path") or ""),
            "target_window": str(payload.get("target_window") or ""),
            "target_window_regex": str(payload.get("target_window_regex") or ""),
            "require_window_focus": bool(payload.get("require_window_focus", False)),
            "manual_save_required_if_no_artifact": bool(payload.get("manual_save_required_if_no_artifact", True)),
            "require_screen_assertions": bool(payload.get("require_screen_assertions", False)),
            "simulate_utm_protocol": bool(payload.get("simulate_utm_protocol", False)),
            "locator_count": len(locators),
            "locator_names": sorted(str(name) for name in locators),
        }

    def _attach_control_profile(self, response: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._control_profile_metadata(payload)
        if profile:
            response = dict(response)
            response.setdefault("control_profile", profile)
        return response

    @staticmethod
    def _is_utm_program_id(program_id: str) -> bool:
        return str(program_id or "").startswith("utm_")

    def _public_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if not key.startswith("_")}

    def _simulated_screen(self) -> dict[str, int]:
        return {
            "width": int(self.config.simulator.get("screen_width", 1920)),
            "height": int(self.config.simulator.get("screen_height", 1080)),
        }

    @staticmethod
    def _program_metadata(programs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for program_id, program in sorted(programs.items()):
            metadata = {
                "program_id": program_id,
                "description": str(program.get("description", "")),
                "requires_pyautogui": bool(program.get("requires_pyautogui", True)),
                "safe_test": bool(program.get("safe_test", False)),
                "program_type": str(program.get("program_type", "macro")),
                "target_app": str(program.get("target_app", "")),
                "target_window": str(program.get("target_window", "")),
                "locator_backend": str(program.get("locator_backend", "")),
                "max_retries": int(program.get("max_retries", 0) or 0),
            }
            for key in (
                "preconditions",
                "expected_screen_before",
                "sequence",
                "expected_screen_after",
                "save_policy",
                "output_artifacts",
                "safe_abort",
            ):
                if key in program:
                    metadata[key] = program[key]
            out.append(metadata)
        return out

    @staticmethod
    def _emit(
        callback: ToolEventCallback | None,
        tool: str,
        step: str,
        status: str,
        *,
        detail: str = "",
        sequence_id: str = "",
        program_id: str = "",
    ) -> None:
        if not callback:
            return
        event = {
            "tool": tool,
            "step": step,
            "status": status,
            "detail": detail,
            "sequence_id": sequence_id,
        }
        if program_id:
            event["program_id"] = program_id
        callback(event)

    @staticmethod
    def _failure(
        *,
        tool: str,
        status: str,
        failure_code: str,
        message: str,
        step_trace: list[dict[str, Any]],
        mode: str = "simulator",
        program_id: str = "",
        sequence_id: str = "",
        requires_connection_info: bool = False,
        requires_install: bool = False,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "ok": False,
            "tool": tool,
            "mode": mode,
            "bridge": "windows_pyautogui",
            "status": status,
            "failure_code": failure_code,
            "message": message,
            "step_trace": step_trace,
        }
        if program_id:
            response["program_id"] = program_id
        if sequence_id:
            response["sequence_id"] = sequence_id
        if requires_connection_info:
            response["requires_connection_info"] = True
        if requires_install:
            response["requires_install"] = True
        return response


def local_ipv4_scan_targets(*, port: int, subnet: str = "", max_hosts: int = 256) -> list[dict[str, Any]]:
    """Return local-network HTTP bridge URLs to probe."""
    networks: list[ipaddress.IPv4Network] = []
    if subnet:
        try:
            networks.append(ipaddress.ip_network(subnet, strict=False))  # type: ignore[arg-type]
        except ValueError:
            return []
    else:
        addresses: set[str] = set()
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addresses.add(str(item[4][0]))
        except socket.gaierror:
            pass
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                addresses.add(sock.getsockname()[0])
        except OSError:
            pass
        for address in sorted(addresses):
            if address.startswith("127."):
                continue
            try:
                networks.append(ipaddress.ip_network(f"{address}/24", strict=False))  # type: ignore[arg-type]
            except ValueError:
                continue

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for network in networks:
        for ip in network.hosts():
            host = str(ip)
            if host in seen:
                continue
            seen.add(host)
            out.append({"host": host, "port": port, "bridge_url": f"http://{host}:{port}"})
            if len(out) >= max_hosts:
                return out
    return out


async def discover_windows_pyautogui_bridges(
    config: WindowsPyAutoGUIBridgeConfig,
    *,
    subnet: str = "",
    port: int | None = None,
    token: str = "",
    timeout_sec: float | None = None,
    max_hosts: int = 256,
) -> dict[str, Any]:
    """Scan the current LAN for bridge hosts answering /health."""
    header_token = token.strip()
    if not header_token:
        return {
            "ok": False,
            "tool": "equipment.pyautogui.discover",
            "status": "token_required",
            "failure_code": "PYAUTOGUI_TOKEN_REQUIRED",
            "message": "Enter the Windows bridge token before scanning. Hosts are listed only when the token matches.",
            "subnet": subnet,
            "port": int(port or config.discovery_port),
            "scanned": 0,
            "candidates": [],
        }
    scan_port = int(port or config.discovery_port)
    timeout = float(timeout_sec or config.discovery_timeout_sec)
    targets = local_ipv4_scan_targets(port=scan_port, subnet=subnet, max_hosts=max_hosts)
    headers = {"Accept": "application/json"}
    headers[config.token_header] = header_token

    semaphore = asyncio.Semaphore(48)

    async def probe(target: dict[str, Any]) -> dict[str, Any] | None:
        url = str(target["bridge_url"]).rstrip("/")
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(f"{url}/health", headers=headers)
                if response.status_code in {401, 403}:
                    return None
                if response.status_code != 200:
                    return None
                data = response.json()
                if not isinstance(data, dict):
                    return None
                bridge_name = str(data.get("bridge", "windows_pyautogui"))
                if bridge_name and "pyautogui" not in bridge_name.lower():
                    return None
                auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
                token_verified = bool(auth.get("token_required")) and bool(auth.get("authenticated"))
                if not token_verified and str(data.get("token_auth", "")).strip().lower() == "enabled":
                    token_verified = True
                if not token_verified:
                    try:
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            no_token = await client.get(f"{url}/health", headers={"Accept": "application/json"})
                        token_verified = no_token.status_code in {401, 403}
                    except Exception:
                        token_verified = False
                if not token_verified:
                    # Do not list no-token bridge servers.
                    return None
                return {
                    **target,
                    "ok": bool(data.get("ok", True)),
                    "reachable": True,
                    "auth_required": False,
                    "token_verified": True,
                    "status": str(data.get("status", "ready")),
                    "screen": data.get("screen"),
                    "pyautogui": data.get("pyautogui", {}),
                    "raw": data,
                }
            except Exception:
                return None

    results = await asyncio.gather(*(probe(target) for target in targets))
    candidates = [item for item in results if isinstance(item, dict)]
    return {
        "ok": True,
        "tool": "equipment.pyautogui.discover",
        "subnet": subnet,
        "port": scan_port,
        "scanned": len(targets),
        "candidates": candidates,
    }
