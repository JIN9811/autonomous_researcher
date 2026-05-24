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
import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from device_bridges.base_bridge import BaseBridge


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONNECTION_MEMORY = REPO_ROOT / "memory" / "windows_pyautogui_connection.json"
DEFAULT_ALLOWED_ACTIONS = {
    "health",
    "screenshot",
    "locate_image",
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
        "sequence": [
            {"action": "health"},
            {"action": "demo_mouse_wiggle", "duration_sec": 1.0, "distance_px": 20},
            {"action": "log", "message": "program1 completed"},
        ],
    }
}


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

        allowed_actions = bridge.get("allowed_actions")
        registered = bridge.get("registered_programs")
        default_sequence = bridge.get("default_sequence")

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
            allowed_actions={str(item) for item in allowed_actions}
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
            registered_programs={
                str(program_id): dict(program)
                for program_id, program in registered.items()
                if isinstance(program, dict)
            }
            if isinstance(registered, dict) and registered
            else dict(DEFAULT_REGISTERED_PROGRAMS),
            connection_memory_path=memory_path,
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
                "program_count": len(self.config.registered_programs),
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

        if not self._should_use_live(payload, for_execution=True):
            return self._run_simulator(payload)

        precheck = self._live_precheck(require_execute=True, payload=payload)
        if precheck:
            precheck["tool"] = "equipment.pyautogui.run"
            return precheck
        validation = self._validate_sequence_payload(payload)
        if validation:
            return validation
        return self._live_post("equipment.pyautogui.run", "/execute", self._public_payload(payload))

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
                    "program_log": "program1 completed",
                    "step_trace": trace,
                    "failure_code": None,
                }

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
        return self._normalize_live_response(tool, data)

    def _live_post(self, tool: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        return self._normalize_live_response(tool, data)

    def _normalize_live_response(self, tool: str, data: Any) -> dict[str, Any]:
        response = dict(data) if isinstance(data, dict) else {"raw_response": data}
        response.setdefault("ok", bool(response.get("status") in {"ready", "completed"}))
        response.setdefault("tool", tool)
        response.setdefault("mode", "live")
        response.setdefault("bridge", "windows_pyautogui")
        response.setdefault("step_trace", [])
        response.setdefault("failure_code", None if response.get("ok") else "PYAUTOGUI_BRIDGE_ERROR")
        return response

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
            out.append(
                {
                    "program_id": program_id,
                    "description": str(program.get("description", "")),
                    "requires_pyautogui": bool(program.get("requires_pyautogui", True)),
                    "safe_test": bool(program.get("safe_test", False)),
                }
            )
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
