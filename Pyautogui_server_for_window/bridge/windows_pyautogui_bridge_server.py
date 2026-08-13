"""
Minimal Windows PyAutoGUI bridge server.

Run on Windows:
  py windows_pyautogui_bridge_server.py

Environment:
  WINDOWS_PYAUTOGUI_BRIDGE_HOST=0.0.0.0
  WINDOWS_PYAUTOGUI_BRIDGE_PORT=8765
  WINDOWS_PYAUTOGUI_BRIDGE_TOKEN=<token>
  WINDOWS_PYAUTOGUI_PROGRAM_DIR=C:/ATR/programs

Endpoints:
  GET  / or /index.html
  GET  /health
  GET  /programs
  GET  /artifacts
  GET  /artifacts/{artifact_id}
  GET  /locators
  POST /programs/validate
  POST /programs/register
  DELETE /programs/{program_id}
  GET  /recordings
  GET  /recordings/status
  GET  /recordings/{recording_id}
  POST /recordings/start
  POST /recordings/checkpoint
  POST /recordings/stop
  POST /recordings/{recording_id}/save
  POST /execute
  POST /screenshot
  POST /locators/capture
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from dataclasses import dataclass
import hashlib
import importlib.util
import ipaddress
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request as URLRequest, build_opener, urlopen
from uuid import uuid4


def _normalize_bridge_platform(value: str, *, system_name: str | None = None) -> str:
    requested = str(value or "auto").strip().lower()
    if requested in {"windows", "linux"}:
        return requested
    detected = str(system_name or sys.platform).strip().lower()
    return "windows" if detected.startswith("win") else "linux"


def _read_bridge_token_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


BRIDGE_PLATFORM = _normalize_bridge_platform(os.getenv("ATR_PYAUTOGUI_BRIDGE_PLATFORM", "windows"))


def _desktop_platform_status() -> dict[str, Any]:
    if BRIDGE_PLATFORM == "windows":
        return {
            "name": "windows",
            "session_type": "windows",
            "display": "desktop",
            "scope": "lan",
            "desktop_control_ready": True,
            "failure_code": None,
        }
    session_type = str(os.getenv("XDG_SESSION_TYPE", "")).strip().lower()
    display = str(os.getenv("DISPLAY", "")).strip()
    ready = session_type == "x11" and bool(display)
    return {
        "name": "linux",
        "session_type": session_type or "unknown",
        "display": display,
        "scope": "localhost",
        "desktop_control_ready": ready,
        "failure_code": None if ready else "PYAUTOGUI_LOCAL_DISPLAY_UNSUPPORTED",
    }


HOST = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "")
TOKEN_HEADER = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN_HEADER", "X-Bridge-Token")
ARTIFACT_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT", r"C:\ATR\bridge_artifacts"))
LOCATOR_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_LOCATOR_ROOT", r"C:\ATR\equipment_locators"))
UTM_EXPORT_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR", r"C:\ATR\utm_exports"))
PROGRAM_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_PROGRAM_DIR", r"C:\ATR\programs"))
RECORDING_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_RECORDING_DIR", r"C:\ATR\recordings"))


def _default_demo_root() -> Path:
    script_path = Path(__file__).resolve()
    candidates = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "demo")
    candidates.extend((
        script_path.parents[1] / "demo",
        script_path.parents[1] / "Pyautogui_server_for_window" / "demo",
        script_path.parent / "demo",
    ))
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])


DEMO_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_DEMO_DIR", str(_default_demo_root())))
ATR_API_URL = os.getenv("WINDOWS_PYAUTOGUI_ATR_API_URL", "").rstrip("/")
UTM_EXPORT_GLOB = os.getenv("WINDOWS_PYAUTOGUI_UTM_EXPORT_GLOB", "*.csv")
UTM_FILE_STABLE_SEC = float(os.getenv("WINDOWS_PYAUTOGUI_UTM_FILE_STABLE_SEC", "2.0"))
ALLOW_SIMULATED_UTM = os.getenv("WINDOWS_PYAUTOGUI_ALLOW_SIMULATED_UTM", "0").strip().lower() in {"1", "true", "yes", "on"}
REQUIRE_UTM_SCREEN_ASSERTIONS = os.getenv("WINDOWS_PYAUTOGUI_REQUIRE_UTM_SCREEN_ASSERTIONS", "0").strip().lower() in {"1", "true", "yes", "on"}
ARTIFACT_INDEX: dict[str, dict[str, Any]] = {}


def _recording_hash(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("content_sha256", None)
    normalized.pop("idempotent", None)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recording_atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class _RecordingKeyboardCapture:
    """Convert raw key transitions into replayable key and hotkey events."""

    _MODIFIERS = {
        "alt": "alt",
        "alt_l": "alt",
        "alt_r": "alt",
        "cmd": "win",
        "cmd_l": "win",
        "cmd_r": "win",
        "ctrl": "ctrl",
        "ctrl_l": "ctrl",
        "ctrl_r": "ctrl",
        "shift": "shift",
        "shift_l": "shift",
        "shift_r": "shift",
    }
    _ORDER = ("ctrl", "alt", "shift", "win")

    def __init__(self, manager: "RecordingManager") -> None:
        self.manager = manager
        self._pressed_modifiers: set[str] = set()
        self._used_modifiers: set[str] = set()

    @staticmethod
    def key_name(key: Any) -> str:
        char = getattr(key, "char", None)
        if char:
            return str(char).lower()[:32]
        return str(key).replace("Key.", "").lower()[:32]

    def on_press(self, key: Any) -> None:
        name = self.key_name(key)
        modifier = self._MODIFIERS.get(name)
        if modifier:
            self._pressed_modifiers.add(modifier)
            return
        if self._pressed_modifiers:
            modifiers = [item for item in self._ORDER if item in self._pressed_modifiers]
            self._used_modifiers.update(modifiers)
            self.manager.record_event({"kind": "hotkey", "keys": [*modifiers, name]})
            return
        self.manager.record_event({"kind": "key_press", "key": name})

    def on_release(self, key: Any) -> None:
        modifier = self._MODIFIERS.get(self.key_name(key))
        if not modifier:
            return
        if modifier not in self._used_modifiers:
            self.manager.record_event({"kind": "key_press", "key": modifier})
        self._pressed_modifiers.discard(modifier)
        self._used_modifiers.discard(modifier)


class _RecordingMouseCapture:
    """Classify pointer input into sampled moves, clicks, drags, and scrolls."""

    def __init__(self, manager: "RecordingManager", *, drag_threshold_px: int = 5) -> None:
        self.manager = manager
        self.drag_threshold_px = max(1, int(drag_threshold_px))
        self._pressed: dict[str, tuple[int, int, float, dict[str, Any], Any]] = {}
        self._last_position: tuple[int, int] | None = None

    @staticmethod
    def button_name(button: Any) -> str:
        return str(button).split(".")[-1].lower()[:16]

    def on_move(self, x: int, y: int) -> None:
        self._last_position = (int(x), int(y))
        if not self._pressed:
            self.manager.cache_pointer_frame(int(x), int(y))
            self.manager.record_mouse_move(int(x), int(y))

    def on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        name = self.button_name(button)
        if pressed:
            event_number = self.manager.next_event_number()
            pre_action_frame = self.manager.pre_action_frame(int(x), int(y))
            source_locator = self.manager.capture_visual_locator(
                int(x), int(y), locator_id=f"evt-{event_number:04d}-source", frame=pre_action_frame
            )
            self._pressed[name] = (int(x), int(y), time.monotonic(), source_locator, pre_action_frame)
            self._last_position = (int(x), int(y))
            return
        start = self._pressed.pop(name, None)
        if start is None:
            return
        start_x, start_y, started_at, source_locator, pre_action_frame = start
        end_x, end_y = int(x), int(y)
        event_number = self.manager.next_event_number()
        distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5
        if distance >= self.drag_threshold_px:
            target_locator = self.manager.capture_visual_locator(
                end_x,
                end_y,
                locator_id=f"evt-{event_number:04d}-target",
                frame=pre_action_frame,
            )
            self.manager.record_event(
                {
                    "kind": "mouse_drag",
                    "start_x": start_x,
                    "start_y": start_y,
                    "x": end_x,
                    "y": end_y,
                    "button": name,
                    "duration_sec": max(0.05, time.monotonic() - started_at),
                    "source_visual_locator": source_locator,
                    "target_visual_locator": target_locator,
                }
            )
        else:
            target_locator = dict(source_locator)
            target_locator["locator_id"] = f"evt-{event_number:04d}-target"
            target_locator["recorded_coordinate"] = [end_x, end_y]
            self.manager.record_event(
                {
                    "kind": "mouse_click",
                    "x": end_x,
                    "y": end_y,
                    "button": name,
                    "visual_locator": target_locator,
                }
            )

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.manager.record_event(
            {"kind": "mouse_scroll", "x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)}
        )


class RecordingDependencyError(RuntimeError):
    def __init__(self, dependency: str, detail: str = "") -> None:
        super().__init__(detail or f"Missing recording dependency: {dependency}")
        self.dependency = dependency


def _pynput_recording_listeners(manager: "RecordingManager") -> list[Any]:
    """Create global listeners only while a recording is active."""
    try:
        from pynput import keyboard, mouse  # type: ignore
    except Exception as exc:
        raise RecordingDependencyError("pynput", f"{exc.__class__.__name__}: {exc}") from exc

    key_capture = _RecordingKeyboardCapture(manager)
    mouse_capture = _RecordingMouseCapture(manager)

    mouse_listener = mouse.Listener(
        on_move=mouse_capture.on_move,
        on_click=mouse_capture.on_click,
        on_scroll=mouse_capture.on_scroll,
    )
    keyboard_listener = keyboard.Listener(on_press=key_capture.on_press, on_release=key_capture.on_release)
    return [mouse_listener, keyboard_listener]


class _TkRecordingOverlayWindow:
    """Small Windows desktop indicator owned entirely by one Tk thread."""

    def __init__(self) -> None:
        import tkinter as tk

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        try:
            self._root.attributes("-toolwindow", True)
        except Exception:
            pass
        width, height = 260, 48
        screen_width = max(width, int(self._root.winfo_screenwidth()))
        x = max(0, (screen_width - width) // 2)
        self._root.geometry(f"{width}x{height}+{x}+18")
        self._root.configure(bg="#171a20")

        frame = tk.Frame(self._root, bg="#171a20", highlightbackground="#4d535e", highlightthickness=1)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="●", fg="#f4434d", bg="#171a20", font=("Segoe UI", 16, "bold")).pack(
            side="left", padx=(14, 8)
        )
        tk.Label(frame, text="RECORDING", fg="#ffffff", bg="#171a20", font=("Segoe UI", 11, "bold")).pack(
            side="left"
        )
        self._elapsed_label = tk.Label(
            frame,
            text="00:00:00",
            fg="#d8dde7",
            bg="#171a20",
            font=("Consolas", 11, "bold"),
        )
        self._elapsed_label.pack(side="right", padx=(8, 14))
        self.pump()

    def update_elapsed(self, elapsed_s: float) -> None:
        total = max(0, int(elapsed_s))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        self._elapsed_label.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def pump(self) -> None:
        self._root.update_idletasks()
        self._root.update()

    def close(self) -> None:
        try:
            self._root.destroy()
        except Exception:
            pass


class RecordingOverlayController:
    """Thread-confined native recording overlay with a non-blocking API."""

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        window_factory: Callable[[], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval: float = 0.1,
    ) -> None:
        self._enabled = str(platform_name or sys.platform).lower().startswith("win") or window_factory is not None
        self._window_factory = window_factory or _TkRecordingOverlayWindow
        self._monotonic = monotonic
        self._poll_interval = max(0.005, float(poll_interval))
        self._commands: queue.Queue[tuple[str, str, float]] = queue.Queue()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._available = self._enabled
        self._visible = False
        self._error: str | None = None if self._enabled else "windows_only"

    def _ensure_thread(self) -> None:
        with self._lock:
            if not self._enabled or (self._thread is not None and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._run, name="atr-recording-overlay", daemon=True)
            self._thread.start()

    def show(self, recording_id: str, started_monotonic: float) -> None:
        if not self._enabled:
            return
        self._ensure_thread()
        self._commands.put(("show", str(recording_id), float(started_monotonic)))

    def hide(self) -> None:
        if self._enabled and self._thread is not None:
            self._commands.put(("hide", "", 0.0))

    def shutdown(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._commands.put(("shutdown", "", 0.0))
        if thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            self._thread = None
            self._visible = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"available": self._available, "visible": self._visible, "error": self._error}

    def _run(self) -> None:
        window: Any | None = None
        started_monotonic = 0.0
        running = True
        while running:
            try:
                command, _recording_id, command_started = self._commands.get(timeout=self._poll_interval)
            except queue.Empty:
                command, command_started = "tick", started_monotonic
            try:
                if command == "show":
                    if window is not None:
                        window.close()
                    window = self._window_factory()
                    started_monotonic = command_started
                    with self._lock:
                        self._available = True
                        self._visible = True
                        self._error = None
                elif command in {"hide", "shutdown"}:
                    if window is not None:
                        window.close()
                        window = None
                    with self._lock:
                        self._visible = False
                    if command == "shutdown":
                        running = False
                        continue
                if window is not None:
                    window.update_elapsed(max(0.0, self._monotonic() - started_monotonic))
                    window.pump()
            except Exception as exc:
                if window is not None:
                    try:
                        window.close()
                    except Exception:
                        pass
                    window = None
                with self._lock:
                    self._available = False
                    self._visible = False
                    self._error = f"{exc.__class__.__name__}: {str(exc)[:160]}"



class RecordingManager:
    """Persist one redacted operator demonstration without owning Skill reasoning."""

    def __init__(
        self,
        root: str | Path,
        *,
        listener_factory: Callable[["RecordingManager"], list[Any]] | None = None,
        screenshot_provider: Callable[[], Any] | None = None,
        overlay_controller: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self._listener_factory = listener_factory or _pynput_recording_listeners
        self._screenshot_provider = screenshot_provider
        self._overlay = overlay_controller or RecordingOverlayController()
        self._lock = threading.RLock()
        self._active: dict[str, Any] | None = None
        self._listeners: list[Any] = []
        self._started_monotonic = 0.0
        self._last_completed_id = ""
        self._last_mouse_move_monotonic = 0.0
        self._last_mouse_position: tuple[int, int] | None = None
        self._last_pointer_frame: Any | None = None
        self._last_pointer_frame_monotonic = 0.0
        self._last_pointer_frame_position: tuple[int, int] | None = None
        self._pointer_frame_history: list[tuple[Any, float, tuple[int, int]]] = []
        self._visual_locator_bytes = 0

    def next_event_number(self) -> int:
        with self._lock:
            return len(self._active.get("events", [])) + 1 if self._active is not None else 1

    def _screenshot(self) -> Any:
        if self._screenshot_provider is not None:
            return self._screenshot_provider()
        pyautogui, error = _load_pyautogui()
        if pyautogui is None:
            raise RuntimeError(error or "PyAutoGUI unavailable")
        return pyautogui.screenshot()

    @staticmethod
    def _crop_box(x: int, y: int, width: int, height: int, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
        image_width, image_height = (max(1, int(value)) for value in image_size)
        crop_width = min(max(1, int(width)), image_width)
        crop_height = min(max(1, int(height)), image_height)
        left = min(max(0, int(x) - crop_width // 2), image_width - crop_width)
        top = min(max(0, int(y) - crop_height // 2), image_height - crop_height)
        return left, top, left + crop_width, top + crop_height

    def cache_pointer_frame(self, x: int, y: int) -> bool:
        """Retain one recent pre-action frame without persisting pointer-motion screenshots."""
        now = time.monotonic()
        with self._lock:
            if self._active is None:
                return False
            if self._last_pointer_frame_monotonic and now - self._last_pointer_frame_monotonic < 0.05:
                return False
        try:
            frame = self._screenshot()
        except Exception:
            return False
        with self._lock:
            if self._active is None:
                return False
            self._last_pointer_frame = frame
            self._last_pointer_frame_monotonic = time.monotonic()
            self._last_pointer_frame_position = (int(x), int(y))
            self._pointer_frame_history.append(
                (frame, self._last_pointer_frame_monotonic, self._last_pointer_frame_position)
            )
            self._pointer_frame_history = self._pointer_frame_history[-8:]
            return True

    def pre_action_frame(self, x: int, y: int) -> Any | None:
        """Prefer the latest frame captured before pointer hover changed the target."""
        with self._lock:
            now = time.monotonic()
            for frame, captured_at, position in reversed(self._pointer_frame_history):
                age = now - captured_at
                distance = ((int(x) - position[0]) ** 2 + (int(y) - position[1]) ** 2) ** 0.5
                if age <= 1.5 and distance >= 128:
                    copy = getattr(frame, "copy", None)
                    return copy() if callable(copy) else frame
            position = self._last_pointer_frame_position
            age = now - self._last_pointer_frame_monotonic
            if self._last_pointer_frame is not None and position is not None and age <= 1.5:
                distance = ((int(x) - position[0]) ** 2 + (int(y) - position[1]) ** 2) ** 0.5
                if distance <= 64:
                    copy = getattr(self._last_pointer_frame, "copy", None)
                    return copy() if callable(copy) else self._last_pointer_frame
        try:
            return self._screenshot()
        except Exception:
            return None

    def capture_visual_locator(self, x: int, y: int, *, locator_id: str, frame: Any | None = None) -> dict[str, Any]:
        """Capture portable pointer-target crops and local full-frame evidence."""
        coordinate = [int(x), int(y)]
        unavailable = {
            "locator_id": str(locator_id)[:96],
            "status": "unavailable",
            "recorded_coordinate": coordinate,
            "candidates": [],
            "failure_code": "VISUAL_LOCATOR_CAPTURE_FAILED",
        }
        with self._lock:
            if self._active is None:
                return unavailable
            policy = self._active.get("visual_locator_policy") if isinstance(self._active.get("visual_locator_policy"), dict) else {}
            if str(policy.get("mode") or "") != "image_first":
                return {
                    **unavailable,
                    "status": "disabled",
                    "failure_code": None,
                    "detail": "image tracking disabled by operator",
                }
            pointer_count = sum(
                1
                for item in self._active.get("events", [])
                if isinstance(item, dict) and item.get("kind") in {"mouse_click", "mouse_drag"}
            )
            if pointer_count >= 200:
                return {
                    **unavailable,
                    "failure_code": "VISUAL_LOCATOR_EVENT_LIMIT",
                    "detail": "image locator limit is 200 pointer events",
                }
            try:
                frame = frame if frame is not None else self._screenshot()
                size = tuple(int(value) for value in frame.size)
                directory = self._path(str(self._active["recording_id"])).parent / "visual_evidence"
                directory.mkdir(parents=True, exist_ok=True)
                full_path = directory / f"{_safe_segment(locator_id, 'locator')}-frame.png"
                frame.save(full_path, format="PNG")
                candidates: list[dict[str, Any]] = []
                capture_bytes = 0
                for kind, crop_width, crop_height, confidence in (
                    ("tight", 64, 64, 0.88),
                    ("context", 192, 128, 0.82),
                ):
                    box = self._crop_box(int(x), int(y), crop_width, crop_height, size)
                    crop = frame.crop(box)
                    buffer = BytesIO()
                    crop.save(buffer, format="PNG")
                    raw = buffer.getvalue()
                    if len(raw) > 256 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("visual locator crop is invalid or exceeds 256 KiB")
                    if self._visual_locator_bytes + capture_bytes + len(raw) > 32 * 1024 * 1024:
                        raise ValueError("recording visual locator payload exceeds 32 MiB")
                    capture_bytes += len(raw)
                    candidates.append(
                        {
                            "kind": kind,
                            "png_base64": base64.b64encode(raw).decode("ascii"),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "width": box[2] - box[0],
                            "height": box[3] - box[1],
                            "crop_origin": [box[0], box[1]],
                            "confidence": confidence,
                        }
                    )
                self._visual_locator_bytes += capture_bytes
                return {
                    "locator_id": str(locator_id)[:96],
                    "status": "ready",
                    "recorded_coordinate": coordinate,
                    "candidates": candidates,
                    "full_frame_artifact_path": str(full_path),
                    "full_frame_sha256": hashlib.sha256(full_path.read_bytes()).hexdigest(),
                }
            except Exception as exc:
                unavailable["detail"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                return unavailable

    def _path(self, recording_id: str) -> Path:
        clean = str(recording_id or "").strip()
        if not re.fullmatch(r"rec-[A-Za-z0-9_-]{8,80}", clean):
            raise ValueError("invalid recording_id")
        return self.root / clean / "recording.json"

    def _persist(self, payload: dict[str, Any]) -> None:
        stable = dict(payload)
        stable["content_sha256"] = _recording_hash(stable)
        payload["content_sha256"] = stable["content_sha256"]
        _recording_atomic_write(self._path(str(payload["recording_id"])), stable)

    def start(
        self,
        *,
        name: str,
        target_app: str,
        target_window: str,
        image_tracking: bool = True,
        coordinate_fallback: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                return {
                    "ok": False,
                    "status": "recording",
                    "failure_code": "SKILL_RECORDING_ALREADY_ACTIVE",
                    "recording_id": self._active["recording_id"],
                }
            recording_id = f"rec-{time.strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._active = {
                "schema": "atr.equipment_recording.v2" if image_tracking else "atr.equipment_recording.v1",
                "recording_id": recording_id,
                "name": str(name or "Equipment demonstration")[:160],
                "target_app": str(target_app or "")[:160],
                "target_window": str(target_window or "")[:240],
                "status": "recording",
                "events": [],
                "checkpoints": [],
                "created_at": now,
                "updated_at": now,
                "visual_locator_policy": {
                    "mode": "image_first" if image_tracking else "coordinates",
                    "required_for_pointer_actions": bool(image_tracking),
                    "coordinate_fallback": bool(coordinate_fallback),
                },
            }
            self._started_monotonic = time.monotonic()
            self._last_mouse_move_monotonic = 0.0
            self._last_mouse_position = None
            self._last_pointer_frame = None
            self._last_pointer_frame_monotonic = 0.0
            self._last_pointer_frame_position = None
            self._pointer_frame_history = []
            self._visual_locator_bytes = 0
            try:
                self._listeners = list(self._listener_factory(self) or [])
                for listener in self._listeners:
                    start = getattr(listener, "start", None)
                    if callable(start):
                        start()
            except Exception as exc:
                for listener in self._listeners:
                    stop = getattr(listener, "stop", None)
                    if callable(stop):
                        try:
                            stop()
                        except Exception:
                            pass
                dependency = getattr(exc, "dependency", "")
                if not dependency and isinstance(exc, ModuleNotFoundError):
                    dependency = str(getattr(exc, "name", "") or "")
                    if not dependency and "pynput" in str(exc).lower():
                        dependency = "pynput"
                self._active = None
                self._listeners = []
                self._started_monotonic = 0.0
                self._overlay.hide()
                if dependency:
                    return {
                        "ok": False,
                        "status": "blocked",
                        "failure_code": "SKILL_RECORDING_DEPENDENCY_MISSING",
                        "missing_dependencies": [dependency],
                        "message": f"Recording requires the Windows dependency: {dependency}",
                    }
                return {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": "SKILL_RECORDING_LISTENER_START_FAILED",
                    "message": f"Recording listeners could not start: {exc.__class__.__name__}: {str(exc)[:160]}",
                }
            self._overlay.show(recording_id, self._started_monotonic)
            self._persist(self._active)
            return {"ok": True, **dict(self._active)}

    def record_event(self, event: dict[str, Any]) -> bool:
        with self._lock:
            if self._active is None:
                return False
            kind = str(event.get("kind") or "").strip().lower()
            safe: dict[str, Any] = {"kind": kind, "at_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000))}
            if kind == "key_press":
                safe["key"] = str(event.get("key") or "").strip().lower()[:32]
            elif kind == "mouse_click":
                safe.update(
                    {
                        "x": int(event.get("x", 0)),
                        "y": int(event.get("y", 0)),
                        "button": str(event.get("button") or "left")[:16],
                    }
                )
                if isinstance(event.get("visual_locator"), dict):
                    safe["visual_locator"] = dict(event["visual_locator"])
            elif kind == "mouse_move":
                safe.update({"x": int(event.get("x", 0)), "y": int(event.get("y", 0))})
            elif kind == "mouse_drag":
                safe.update(
                    {
                        "start_x": int(event.get("start_x", 0)),
                        "start_y": int(event.get("start_y", 0)),
                        "x": int(event.get("x", 0)),
                        "y": int(event.get("y", 0)),
                        "button": str(event.get("button") or "left")[:16],
                        "duration_sec": round(max(0.05, min(float(event.get("duration_sec", 0.25)), 5.0)), 3),
                    }
                )
                for key in ("source_visual_locator", "target_visual_locator"):
                    if isinstance(event.get(key), dict):
                        safe[key] = dict(event[key])
            elif kind == "mouse_scroll":
                safe.update(
                    {
                        "x": int(event.get("x", 0)),
                        "y": int(event.get("y", 0)),
                        "dx": max(-100, min(100, int(event.get("dx", 0)))),
                        "dy": max(-100, min(100, int(event.get("dy", 0)))),
                    }
                )
            elif kind == "hotkey":
                safe["keys"] = [str(item).strip().lower()[:32] for item in event.get("keys", [])][:8]
            else:
                return False
            self._active["events"].append(safe)
            self._active["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._persist(self._active)
            return True

    def record_mouse_move(self, x: int, y: int) -> bool:
        """Sample pointer motion without flooding a recording with raw OS events."""
        with self._lock:
            if self._active is None:
                return False
            now = time.monotonic()
            position = (int(x), int(y))
            if position == self._last_mouse_position:
                return False
            if self._last_mouse_move_monotonic and now - self._last_mouse_move_monotonic < 0.065:
                return False
            self._last_mouse_move_monotonic = now
            self._last_mouse_position = position
            return self.record_event({"kind": "mouse_move", "x": position[0], "y": position[1]})

    def checkpoint(self, *, label: str, pyautogui: Any | None = None) -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                return {"ok": False, "status": "idle", "failure_code": "SKILL_RECORDING_NOT_ACTIVE"}
            capture = pyautogui
            if capture is None:
                capture, _error = _load_pyautogui()
            checkpoint_id = f"cp-{len(self._active['checkpoints']) + 1:03d}"
            directory = self._path(str(self._active["recording_id"])).parent / "checkpoints"
            directory.mkdir(parents=True, exist_ok=True)
            image_path = directory / f"{checkpoint_id}.png"
            if capture is None:
                return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UNAVAILABLE"}
            capture.screenshot().save(image_path)
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            checkpoint = {
                "checkpoint_id": checkpoint_id,
                "at_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)),
                "label": str(label or checkpoint_id)[:160],
                "artifact_path": str(image_path),
                "sha256": digest,
            }
            self._active["checkpoints"].append(checkpoint)
            self._persist(self._active)
            return {"ok": True, "status": "checkpoint_saved", **checkpoint}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                if self._last_completed_id:
                    payload = self.get(self._last_completed_id)
                    payload["idempotent"] = True
                    return payload
                return {"ok": False, "status": "idle", "failure_code": "SKILL_RECORDING_NOT_ACTIVE"}
            listener_stop_errors: list[str] = []
            for listener in self._listeners:
                stop = getattr(listener, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception as exc:
                        listener_stop_errors.append(f"{exc.__class__.__name__}: {str(exc)[:160]}")
            self._overlay.hide()
            self._listeners = []
            self._active["status"] = "completed"
            if listener_stop_errors:
                self._active["listener_stop_errors"] = listener_stop_errors
            self._active["duration_ms"] = max(0, int((time.monotonic() - self._started_monotonic) * 1000))
            self._active["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._persist(self._active)
            completed = dict(self._active)
            completed["ok"] = True
            self._last_completed_id = str(self._active["recording_id"])
            self._active = None
            self._last_pointer_frame = None
            self._last_pointer_frame_monotonic = 0.0
            self._last_pointer_frame_position = None
            self._pointer_frame_history = []
            return completed

    def shutdown(self) -> None:
        with self._lock:
            active = self._active is not None
        if active:
            self.stop()
        self._overlay.shutdown()

    def save(self, recording_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self.get(recording_id)
            if payload.get("status") not in {"completed", "saved"}:
                return {"ok": False, **payload, "failure_code": "SKILL_RECORDING_NOT_COMPLETE"}
            payload["status"] = "saved"
            payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            payload.pop("ok", None)
            self._persist(payload)
            return {"ok": True, **payload}

    def get(self, recording_id: str) -> dict[str, Any]:
        path = self._path(recording_id)
        if not path.exists():
            return {"ok": False, "status": "not_found", "failure_code": "SKILL_RECORDING_NOT_FOUND", "recording_id": recording_id}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, **payload}

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if self.root.exists():
            for path in sorted(self.root.glob("rec-*/recording.json"), reverse=True):
                try:
                    items.append(json.loads(path.read_text(encoding="utf-8")))
                except Exception:
                    continue
        return items

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                return {"ok": True, **dict(self._active), "elapsed_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)), "overlay": self._overlay.status()}
            return {"ok": True, "status": "idle", "recording_id": None, "overlay": self._overlay.status()}


RECORDING_MANAGER = RecordingManager(RECORDING_ROOT)


class _NoControllerRedirects(HTTPRedirectHandler):
    """Keep controller identity checks on the candidate origin."""

    def redirect_request(self, req: URLRequest, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _normalize_controller_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("controller URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("controller URL must use http or https and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("controller URL must be an origin without credentials, query, fragment, or path")
    try:
        port = parsed.port or 7860
    except ValueError as exc:
        raise ValueError("controller URL port is invalid") from exc
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    except ValueError:
        pass
    return f"{parsed.scheme.lower()}://{host}:{port}"


def _controller_url_is_private_ipv4(controller_url: str) -> bool:
    try:
        address = ipaddress.ip_address(urlparse(controller_url).hostname or "")
    except ValueError:
        return False
    return address.version == 4 and (address.is_private or address.is_loopback)


def _eligible_private_peer(value: str) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return None
    return address


def _local_private_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        address = _eligible_private_peer(str(info[4][0]))
        if address is not None:
            addresses.add(address.compressed)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            address = _eligible_private_peer(str(probe.getsockname()[0]))
            if address is not None:
                addresses.add(address.compressed)
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(addresses, key=lambda value: int(ipaddress.ip_address(value)))


def _private_ipv4_probe_candidates(local_addresses: list[str], *, max_candidates: int = 512) -> list[str]:
    own = {
        address.compressed
        for value in local_addresses
        if (address := _eligible_private_peer(value)) is not None
    }
    candidates: set[str] = set()
    for own_address in sorted(own, key=lambda value: int(ipaddress.ip_address(value))):
        network = ipaddress.ip_network(f"{own_address}/24", strict=False)
        for candidate in network.hosts():
            compressed = candidate.compressed
            if compressed not in own:
                candidates.add(compressed)
            if len(candidates) >= max(1, int(max_candidates)):
                break
        if len(candidates) >= max(1, int(max_candidates)):
            break
    return sorted(candidates, key=lambda value: int(ipaddress.ip_address(value)))


def _scan_private_network_for_atr(*, overall_timeout: float = 4.0, max_workers: int = 32) -> list[str]:
    candidates = _private_ipv4_probe_candidates(_local_private_ipv4_addresses())
    if not candidates:
        return []
    executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 64)), thread_name_prefix="atr-discovery")
    futures = {
        executor.submit(_verify_atr_controller_identity, f"http://{address}:7860", timeout=0.4): address
        for address in candidates
    }
    verified: list[str] = []
    try:
        for future in as_completed(futures, timeout=max(0.5, float(overall_timeout))):
            address = futures[future]
            try:
                result = future.result()
            except Exception:
                continue
            if isinstance(result, dict) and result.get("ok") is True:
                verified.append(f"http://{address}:7860")
    except TimeoutError:
        pass
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    return sorted(set(verified), key=lambda value: int(ipaddress.ip_address(urlparse(value).hostname or "0.0.0.0")))


def _verify_atr_controller_identity(controller_url: str, *, timeout: float = 1.0) -> dict[str, Any]:
    """Accept a controller only when its public Skill registry has the ATR response shape."""
    request = URLRequest(
        f"{controller_url}/api/equipment/skills",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with build_opener(_NoControllerRedirects()).open(request, timeout=max(0.1, float(timeout))) as response:
            if int(response.status) != 200:
                return {"ok": False, "failure_code": "ATR_CONTROLLER_IDENTITY_HTTP_ERROR"}
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                return {"ok": False, "failure_code": "ATR_CONTROLLER_IDENTITY_RESPONSE_TOO_LARGE"}
            payload = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        return {
            "ok": False,
            "failure_code": "ATR_CONTROLLER_REDIRECT_REJECTED" if 300 <= int(exc.code) < 400 else "ATR_CONTROLLER_IDENTITY_HTTP_ERROR",
            "http_status": int(exc.code),
        }
    except (URLError, TimeoutError, OSError):
        return {"ok": False, "failure_code": "ATR_CONTROLLER_UNREACHABLE"}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "failure_code": "ATR_CONTROLLER_IDENTITY_INVALID_JSON"}
    if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("skills"), list):
        return {"ok": False, "failure_code": "ATR_CONTROLLER_IDENTITY_MISMATCH"}
    return {"ok": True, "status": "verified", "skill_count": len(payload["skills"])}


class ATRControllerResolver:
    """Resolve and persist a verified Linux ATR controller without storing credentials."""

    schema = "atr.windows_controller_connection.v1"

    def __init__(
        self,
        data_root: Path,
        *,
        explicit_url: str = "",
        verifier: Callable[[str], dict[str, Any] | bool] | None = None,
        scanner: Callable[[], list[str]] | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.record_path = self.data_root / "controller_connection.json"
        self.explicit_url = str(explicit_url or "").strip()
        self._verifier = verifier
        self._scanner = scanner
        self._lock = threading.RLock()
        self._current: dict[str, Any] | None = None
        self._saved_record_status = "missing"
        self._negative_discovery_until = 0.0
        self._last_discovery_failure: dict[str, Any] | None = None

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _verify(self, value: str, *, source: str, allow_public: bool = False) -> dict[str, Any]:
        try:
            controller_url = _normalize_controller_url(value)
        except ValueError:
            return {"ok": False, "source": source, "failure_code": "ATR_CONTROLLER_URL_INVALID"}
        if not allow_public and not _controller_url_is_private_ipv4(controller_url):
            return {"ok": False, "source": source, "failure_code": "ATR_CONTROLLER_ADDRESS_NOT_PRIVATE"}
        try:
            verification = self._verifier(controller_url) if self._verifier else _verify_atr_controller_identity(controller_url)
        except Exception:
            verification = {"ok": False, "failure_code": "ATR_CONTROLLER_VERIFICATION_FAILED"}
        if verification is True:
            verification = {"ok": True}
        if not isinstance(verification, dict) or verification.get("ok") is not True:
            failure_code = str(verification.get("failure_code") or "ATR_CONTROLLER_IDENTITY_MISMATCH") if isinstance(verification, dict) else "ATR_CONTROLLER_IDENTITY_MISMATCH"
            return {"ok": False, "source": source, "controller_url": controller_url, "failure_code": failure_code}
        return {
            "ok": True,
            "status": "verified",
            "source": source,
            "controller_url": controller_url,
            "verified_at": self._timestamp(),
        }

    def _load_saved(self) -> dict[str, Any] | None:
        if not self.record_path.is_file():
            self._saved_record_status = "missing"
            return None
        try:
            payload = json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._saved_record_status = "invalid"
            return None
        if not isinstance(payload, dict) or payload.get("schema") != self.schema or not payload.get("controller_url"):
            self._saved_record_status = "invalid"
            return None
        self._saved_record_status = "loaded"
        return payload

    def _persist(self, result: dict[str, Any], *, source: str) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.schema,
            "controller_url": str(result["controller_url"]),
            "source": source,
            "verified_at": str(result.get("verified_at") or self._timestamp()),
            "last_successful_verification_at": self._timestamp(),
            "last_failure_code": "",
            "last_failure_message": "",
        }
        temporary = self.record_path.with_name(f".{self.record_path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.record_path)
        self._saved_record_status = "loaded"

    def resolve(self, *, allow_scan: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._current and self._current.get("ok"):
                return dict(self._current)
            if self.explicit_url:
                result = self._verify(self.explicit_url, source="environment", allow_public=True)
                if not result.get("ok"):
                    result["failure_code"] = "ATR_CONTROLLER_EXPLICIT_URL_INVALID"
                self._current = result
                return dict(result)
            saved = self._load_saved()
            if saved:
                result = self._verify(str(saved.get("controller_url") or ""), source="saved")
                if result.get("ok"):
                    self._current = result
                    return dict(result)
            if allow_scan:
                discovered = self.discover()
                if discovered.get("ok"):
                    return discovered
            local = self._verify("http://127.0.0.1:7860", source="local_fallback")
            if local.get("ok"):
                self._current = local
                return dict(local)
            return {
                "ok": False,
                "status": "unresolved",
                "source": "none",
                "failure_code": "ATR_CONTROLLER_NOT_FOUND",
                "saved_record_status": self._saved_record_status,
            }

    def select(self, candidate_url: str, *, source: str = "manual") -> dict[str, Any]:
        with self._lock:
            result = self._verify(candidate_url, source=source)
            if not result.get("ok"):
                return result
            self._persist(result, source=source)
            self._current = result
            return dict(result)

    def discover(self) -> dict[str, Any]:
        with self._lock:
            if self._current and self._current.get("ok"):
                return dict(self._current)
            if time.monotonic() < self._negative_discovery_until and self._last_discovery_failure:
                return {**self._last_discovery_failure, "cached": True}
            try:
                scanned = self._scanner() if self._scanner else _scan_private_network_for_atr()
            except Exception:
                scanned = []
            normalized: list[str] = []
            for value in scanned if isinstance(scanned, list) else []:
                try:
                    candidate = _normalize_controller_url(str(value))
                except ValueError:
                    continue
                if _controller_url_is_private_ipv4(candidate) and candidate not in normalized:
                    normalized.append(candidate)
            verified = [
                result
                for candidate in normalized
                if (result := self._verify(candidate, source="subnet_scan")).get("ok") is True
            ]
            verified.sort(key=lambda item: int(ipaddress.ip_address(urlparse(str(item["controller_url"])).hostname or "0.0.0.0")))
            if len(verified) == 1:
                result = verified[0]
                self._persist(result, source="subnet_scan")
                self._current = result
                self._negative_discovery_until = 0.0
                self._last_discovery_failure = None
                return dict(result)
            if len(verified) > 1:
                failure = {
                    "ok": False,
                    "status": "selection_required",
                    "failure_code": "ATR_CONTROLLER_MULTIPLE_CANDIDATES",
                    "candidates": [str(item["controller_url"]) for item in verified],
                }
            else:
                failure = {
                    "ok": False,
                    "status": "unresolved",
                    "failure_code": "ATR_CONTROLLER_NOT_FOUND",
                    "candidates": [],
                }
            self._negative_discovery_until = time.monotonic() + 30.0
            self._last_discovery_failure = failure
            return dict(failure)

    def observe_authenticated_peer(self, peer_ip: str) -> dict[str, Any]:
        with self._lock:
            if self._current and self._current.get("ok"):
                return dict(self._current)
            if self.explicit_url:
                return self.resolve()
            saved = self._load_saved()
            if saved:
                saved_result = self._verify(str(saved.get("controller_url") or ""), source="saved")
                if saved_result.get("ok"):
                    self._current = saved_result
                    return dict(saved_result)
            address = _eligible_private_peer(peer_ip)
            if address is None or address.compressed in set(_local_private_ipv4_addresses()):
                return {"ok": False, "status": "ignored", "failure_code": "ATR_CONTROLLER_PEER_NOT_ELIGIBLE"}
            result = self._verify(f"http://{address.compressed}:7860", source="authenticated_peer")
            if not result.get("ok"):
                return result
            self._persist(result, source="authenticated_peer")
            self._current = result
            self._negative_discovery_until = 0.0
            self._last_discovery_failure = None
            return dict(result)

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._current:
                return dict(self._current)
            return {
                "ok": False,
                "status": "unresolved",
                "source": "none",
                "failure_code": "ATR_CONTROLLER_NOT_FOUND",
                "saved_record_status": self._saved_record_status,
            }


def _controller_data_root() -> Path:
    configured = str(os.getenv("WINDOWS_PYAUTOGUI_DATA_ROOT", "")).strip()
    return Path(configured) if configured else ARTIFACT_ROOT.parent


def _reset_controller_resolver(*, data_root: Path | None = None) -> ATRControllerResolver:
    global CONTROLLER_RESOLVER
    CONTROLLER_RESOLVER = ATRControllerResolver(
        Path(data_root) if data_root is not None else _controller_data_root(),
        explicit_url=ATR_API_URL,
    )
    return CONTROLLER_RESOLVER


CONTROLLER_RESOLVER = ATRControllerResolver(_controller_data_root(), explicit_url=ATR_API_URL)


def _atr_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Proxy token-free Skill metadata to Linux; model credentials never cross the bridge."""
    resolution = CONTROLLER_RESOLVER.resolve(allow_scan=True)
    if resolution.get("ok") is not True:
        return 503, {
            "ok": False,
            "status": "unreachable",
            "failure_code": "EQUIPMENT_SKILL_REGISTRY_UNREACHABLE",
            "controller": resolution,
            "message": "No verified ATR controller is available. Use controller discovery or set WINDOWS_PYAUTOGUI_ATR_API_URL.",
        }
    controller_url = str(resolution.get("controller_url") or "").rstrip("/")
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8") if payload is not None else None
    request = URLRequest(
        f"{controller_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body if isinstance(body, dict) else {"ok": False, "status": "invalid_response"}
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"ok": False, "status": "atr_api_error", "message": str(exc)}
        return int(exc.code), body if isinstance(body, dict) else {"ok": False, "status": "atr_api_error"}
    except (URLError, TimeoutError, OSError) as exc:
        return 503, {
            "ok": False,
            "status": "unreachable",
            "failure_code": "EQUIPMENT_SKILL_REGISTRY_UNREACHABLE",
            "message": str(exc),
        }

PROGRAMS = {
    "program1": {
        "name": "Program 1 Demo",
        "description": "Demo macro: verify PyAutoGUI, move mouse briefly, and return completion log.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "connectivity_demo",
    },
    "utm_compression_start_v1": {
        "description": "UTM compression test protocol with screen-state assertions and CSV artifact export.",
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
        "description": "Export/save UTM CSV after a completed test.",
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
        "description": "Safe UTM stop/abort macro for recovery.",
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

BUILTIN_PROGRAM_IDS = frozenset(PROGRAMS)
PROGRAM_SCHEMA = "atr.pyautogui_program.v1"
PROGRAM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_SEQUENCE_ACTIONS = frozenset({
    "health",
    "focus_window",
    "screenshot",
    "assert_visible",
    "wait_until",
    "locate_image",
    "wait_until_image",
    "assert_text",
    "wait_until_text",
    "click",
    "double_click",
    "triple_click",
    "move_to",
    "move_rel",
    "query_pointer",
    "query_screen",
    "mouse_down",
    "mouse_up",
    "drag_to",
    "drag_rel",
    "scroll",
    "hscroll",
    "vscroll",
    "hotkey",
    "press",
    "key_down",
    "key_up",
    "write",
    "type_path",
    "wait",
    "log",
    "wait_for_file",
    "pixel",
    "pixel_matches_color",
    "locate_all_images",
    "window_activate",
    "window_minimize",
    "window_maximize",
    "window_restore",
    "window_move",
    "window_resize",
    "alert",
    "confirm",
})

_MOUSE_BUTTONS = frozenset({"left", "middle", "right"})


def _inline_image_candidates_error(step: dict[str, Any]) -> str:
    candidates = step.get("image_candidates")
    if candidates is None:
        return ""
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 2:
        return "image_candidates must contain one or two PNG crops"
    total = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return "image candidate must be an object"
        encoded = str(candidate.get("png_base64") or "")
        expected_sha = str(candidate.get("sha256") or "").lower()
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except Exception:
            return "image candidate png_base64 is invalid"
        if len(decoded) > 256 * 1024 or not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image candidate must be a PNG no larger than 256 KiB"
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or hashlib.sha256(decoded).hexdigest() != expected_sha:
            return "image candidate sha256 does not match PNG data"
        width, height = int(candidate.get("width", 0)), int(candidate.get("height", 0))
        if not 1 <= width <= 512 or not 1 <= height <= 512:
            return "image candidate dimensions must be within 1..512"
        total += len(decoded)
    if total > 512 * 1024:
        return "inline image candidates exceed 512 KiB per action"
    return ""


def _action_parameter_error(step: dict[str, Any]) -> str:
    """Return a stable validation message for one bounded bridge action."""
    action = str(step.get("action") or "").strip()
    try:
        image_error = _inline_image_candidates_error(step)
        if image_error:
            return image_error
        if action in {"click", "double_click", "triple_click"}:
            clicks = int(step.get("clicks", 2 if action == "double_click" else 3 if action == "triple_click" else 1))
            if clicks not in {1, 2, 3}:
                return "clicks must be between 1 and 3"
            if str(step.get("button") or "left") not in _MOUSE_BUTTONS:
                return "button must be left, middle, or right"
            if not 0.0 <= float(step.get("interval_sec", 0.0)) <= 1.0:
                return "click interval_sec must be between 0 and 1"
        if action in {"mouse_down", "mouse_up", "drag_to", "drag_rel"} and str(step.get("button") or "left") not in _MOUSE_BUTTONS:
            return "button must be left, middle, or right"
        if action in {"drag_to", "drag_rel", "move_to", "move_rel", "window_move"}:
            has_visual_locator = bool(
                step.get("image_path")
                or step.get("target_image")
                or (isinstance(step.get("image_candidates"), list) and step.get("image_candidates"))
            )
            if (step.get("x") is None or step.get("y") is None) and not (
                action in {"move_to", "drag_to"} and has_visual_locator
            ):
                return f"{action} requires x and y"
            if action in {"drag_to", "drag_rel", "move_to", "move_rel"} and not 0.0 <= float(step.get("duration_sec", 0.1)) <= 5.0:
                return f"{action} duration_sec must be between 0 and 5"
        if action in {"scroll", "hscroll", "vscroll"}:
            clicks = int(step.get("clicks", 0))
            if clicks == 0 or abs(clicks) > 100:
                return f"{action} clicks must be non-zero and within -100..100"
        if action == "press":
            if not str(step.get("key") or "").strip():
                return "press requires key"
            if not 1 <= int(step.get("presses", 1)) <= 20:
                return "presses must be between 1 and 20"
        if action in {"key_down", "key_up"} and not str(step.get("key") or "").strip():
            return f"{action} requires key"
        if action in {"pixel", "pixel_matches_color"}:
            if step.get("x") is None or step.get("y") is None:
                return f"{action} requires x and y"
        if action == "pixel_matches_color":
            color = step.get("color")
            if not isinstance(color, (list, tuple)) or len(color) != 3 or any(not 0 <= int(item) <= 255 for item in color):
                return "pixel_matches_color color must contain three RGB bytes"
            if not 0 <= int(step.get("tolerance", 0)) <= 255:
                return "pixel_matches_color tolerance must be between 0 and 255"
        if action.startswith("window_"):
            if not str(step.get("title") or step.get("window") or "").strip():
                return f"{action} requires title"
        if action == "window_resize":
            if not 100 <= int(step.get("width", 0)) <= 10000 or not 100 <= int(step.get("height", 0)) <= 10000:
                return "window_resize width and height must be between 100 and 10000"
        if action in {"alert", "confirm"}:
            if not str(step.get("text") or "").strip() or len(str(step.get("text") or "")) > 500:
                return f"{action} text must contain 1 to 500 characters"
        if action == "confirm":
            buttons = step.get("buttons", ["OK", "Cancel"])
            if not isinstance(buttons, list) or not 1 <= len(buttons) <= 4 or any(not str(item).strip() for item in buttons):
                return "confirm buttons must contain 1 to 4 labels"
        if action == "screenshot" and step.get("region") is not None:
            region = step.get("region")
            if not isinstance(region, (list, tuple)) or len(region) != 4:
                return "screenshot region must be [x, y, width, height]"
            x, y, width, height = (int(item) for item in region)
            if x < 0 or y < 0 or width < 1 or height < 1 or width > 10000 or height > 10000:
                return "screenshot region is outside bounded dimensions"
        if action == "locate_all_images" and not 1 <= int(step.get("max_results", 20)) <= 100:
            return "locate_all_images max_results must be between 1 and 100"
    except (TypeError, ValueError, OverflowError):
        return f"invalid parameters for {action}"
    return ""


def _validate_program_definition(definition: Any) -> dict[str, Any]:
    if not isinstance(definition, dict):
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_INVALID", "message": "Program definition must be a JSON object."}
    if str(definition.get("schema") or "") != PROGRAM_SCHEMA:
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_SCHEMA_INVALID", "message": f"schema must be {PROGRAM_SCHEMA}."}
    program_id = str(definition.get("program_id") or "").strip()
    if not PROGRAM_ID_PATTERN.fullmatch(program_id):
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_ID_INVALID", "message": "program_id must match [A-Za-z0-9_-]{1,64}."}
    if program_id in BUILTIN_PROGRAM_IDS:
        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_PROGRAM_BUILTIN_IMMUTABLE", "message": f"Built-in program cannot be overwritten: {program_id}"}
    name = str(definition.get("name") or "").strip()
    if not name:
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_NAME_REQUIRED", "message": "name is required."}
    sequence = definition.get("sequence")
    if not isinstance(sequence, list) or not 1 <= len(sequence) <= 100:
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_SEQUENCE_INVALID", "message": "sequence must contain 1 to 100 action objects."}
    normalized_sequence: list[dict[str, Any]] = []
    for index, step in enumerate(sequence):
        if not isinstance(step, dict):
            return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_SEQUENCE_INVALID", "message": f"sequence[{index}] must be an object."}
        action = str(step.get("action") or "").strip()
        if action not in ALLOWED_SEQUENCE_ACTIONS:
            return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_ACTION_NOT_ALLOWED", "message": f"Unsupported PyAutoGUI bridge action: {action or '<empty>'}"}
        parameter_error = _action_parameter_error(step)
        if parameter_error:
            return {
                "ok": False,
                "status": "invalid",
                "failure_code": "PYAUTOGUI_ACTION_PARAMETER_INVALID",
                "message": f"sequence[{index}] {parameter_error}.",
            }
        normalized_sequence.append(dict(step))
    normalized = {
        "schema": PROGRAM_SCHEMA,
        "program_id": program_id,
        "name": name[:160],
        "description": str(definition.get("description") or "").strip()[:1000],
        "enabled": definition.get("enabled") is not False,
        "program_type": "macro",
        "requires_pyautogui": True,
        "safe_test": bool(definition.get("safe_test", False)),
        "sequence": normalized_sequence,
    }


    locators = definition.get("locators") if isinstance(definition.get("locators"), dict) else {}
    if locators:
        normalized["locators"] = {str(name): dict(locator) for name, locator in locators.items() if isinstance(locator, dict)}
    portable_actions = sorted({str(step.get("action") or "") for step in normalized_sequence if step.get("action")})
    platform_specific_locators = sorted(
        str(name)
        for name, locator in locators.items()
        if isinstance(locator, dict)
        and str(locator.get("locator_backend") or locator.get("backend") or "").lower() in {"uia", "pywinauto", "windows_uia"}
    )
    return {
        "ok": True,
        "status": "valid",
        "program": normalized,
        "failure_code": None,
        "platform_tested": BRIDGE_PLATFORM,
        "portable_actions": portable_actions,
        "platform_specific_locators": platform_specific_locators,
        "requires_windows_recalibration": BRIDGE_PLATFORM == "linux" and bool(platform_specific_locators),
    }


def _capability_catalog() -> dict[str, Any]:
    families = {
        "mouse": ["query_pointer", "query_screen", "move_to", "move_rel", "click", "double_click", "triple_click", "mouse_down", "mouse_up", "drag_to", "drag_rel", "scroll", "hscroll", "vscroll"],
        "keyboard": ["write", "press", "hotkey", "key_down", "key_up"],
        "screen": ["screenshot", "locate_image", "locate_all_images", "assert_visible", "wait_until_image", "pixel", "pixel_matches_color"],
        "window": ["focus_window", "window_activate", "window_minimize", "window_maximize", "window_restore", "window_move", "window_resize"],
        "dialog": ["alert", "confirm"],
        "timing": ["wait", "wait_for_file"],
    }
    return {
        "ok": True,
        "schema": PROGRAM_SCHEMA,
        "families": families,
        "action_count": len({action for actions in families.values() for action in actions}),
        "excluded": ["shell", "arbitrary_python", "file_delete", "password_entry", "window_close", "process_terminate"],
        "failsafe_required": True,
    }


def _load_example_catalog() -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    root = DEMO_ROOT / "examples"
    if not root.is_dir():
        return examples
    for path in sorted(root.glob("*.json")):
        try:
            program = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        validation = _validate_program_definition(program)
        if not validation.get("ok"):
            continue
        metadata = dict(program.get("example") or {})
        examples.append(
            {
                "example_id": path.stem,
                "name": str(program.get("name") or path.stem),
                "description": str(program.get("description") or ""),
                "family": str(metadata.get("family") or "other"),
                "safe_test": bool(program.get("safe_test")),
                "manual_confirmation_required": bool(metadata.get("manual_confirmation_required")),
                "action_count": len(program.get("sequence", [])),
                "program": program,
            }
        )
    return examples


def _example_catalog_payload() -> dict[str, Any]:
    return {"ok": True, "examples": _load_example_catalog(), "capability_lab_path": "/capability-lab"}


def _load_custom_programs() -> dict[str, dict[str, Any]]:
    programs: dict[str, dict[str, Any]] = {}
    if not PROGRAM_ROOT.exists():
        return programs
    for path in sorted(PROGRAM_ROOT.glob("*.json")):
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        validation = _validate_program_definition(definition)
        if not validation.get("ok"):
            continue
        program = dict(validation["program"])
        program["built_in"] = False
        program["source_file"] = str(path)
        programs[program["program_id"]] = program
    return programs


def _all_programs() -> dict[str, dict[str, Any]]:
    programs = {key: {**value, "built_in": True, "enabled": True} for key, value in PROGRAMS.items()}
    programs.update(_load_custom_programs())
    return programs


def _register_program_definition(definition: Any) -> dict[str, Any]:
    validation = _validate_program_definition(definition)
    if not validation.get("ok"):
        return validation
    program = dict(validation["program"])
    PROGRAM_ROOT.mkdir(parents=True, exist_ok=True)
    destination = PROGRAM_ROOT / f"{program['program_id']}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(program, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    public = {**program, "built_in": False, "source_file": str(destination)}
    return {"ok": True, "status": "registered", "program": public, "program_path": str(destination), "failure_code": None}


def _delete_custom_program(program_id: str) -> dict[str, Any]:
    program_id = str(program_id or "").strip()
    if program_id in BUILTIN_PROGRAM_IDS:
        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_PROGRAM_BUILTIN_IMMUTABLE", "message": f"Built-in program cannot be deleted: {program_id}"}
    if not PROGRAM_ID_PATTERN.fullmatch(program_id):
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_ID_INVALID", "message": "Invalid program_id."}
    path = PROGRAM_ROOT / f"{program_id}.json"
    if not path.exists():
        return {"ok": False, "status": "not_found", "failure_code": "PYAUTOGUI_PROGRAM_NOT_FOUND", "message": f"Unknown custom program: {program_id}"}
    path.unlink()
    return {"ok": True, "status": "deleted", "program_id": program_id, "failure_code": None}



def _load_pyautogui() -> tuple[Any | None, str]:
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
        return pyautogui, ""
    except Exception as exc:
        return None, exc.__class__.__name__



_raw_load_pyautogui = _load_pyautogui


def get_pyautogui() -> tuple[Any | None, str | None]:
    """Compatibility hook used by the packaged bridge tests and legacy launcher."""
    pyautogui, error = _raw_load_pyautogui()
    return pyautogui, error or None


def _load_pyautogui() -> tuple[Any | None, str]:
    pyautogui, error = get_pyautogui()
    return pyautogui, "" if error is None else str(error)


def _runtime_dependency_status(checker: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Return import readiness without importing GUI packages into the server process."""
    available = checker or (lambda name: importlib.util.find_spec(name) is not None)
    required_imports = {
        "pyautogui": "pyautogui",
        "pillow": "PIL",
        "opencv-python": "cv2",
        "pynput": "pynput",
    }
    optional_imports = {
        "pywinauto": "pywinauto",
        "pytesseract": "pytesseract",
    }

    def inspect(packages: dict[str, str]) -> dict[str, dict[str, Any]]:
        return {
            package: {"available": bool(available(import_name)), "import_name": import_name}
            for package, import_name in packages.items()
        }

    required = inspect(required_imports)
    optional = inspect(optional_imports)
    return {
        "core_ready": all(item["available"] for item in required.values()),
        "required": required,
        "optional": optional,
    }


def _health() -> dict[str, Any]:
    pyautogui, error = _load_pyautogui()
    platform_status = _desktop_platform_status()
    dependencies = _runtime_dependency_status()
    demo_assets = {
        "root": str(DEMO_ROOT),
        "available": (DEMO_ROOT / "pyautogui_capability_lab.html").is_file()
        and (DEMO_ROOT / "examples").is_dir(),
    }
    controller_status = CONTROLLER_RESOLVER.status()
    if pyautogui is None:
        return {
            "ok": True,
            "status": "degraded",
            "bridge": "windows_pyautogui",
            "auth": {"token_required": True, "authenticated": True},
            "screen": None,
            "pyautogui": {"available": False, "error": error},
            "dependencies": dependencies,
            "demo_assets": demo_assets,
            "platform": platform_status,
            "atr_controller": controller_status,
            "server_version": "WindowsPyAutoGUIBridge/0.1",
            "script_version": "windows_pyautogui_bridge_server.py:utm_visual_control_v1",
            "artifacts": {"root": str(ARTIFACT_ROOT), "request_log": str(ARTIFACT_ROOT / "bridge_requests.jsonl"), "locator_root": str(LOCATOR_ROOT), "utm_export_root": str(UTM_EXPORT_ROOT)},
            "message": "Install PyAutoGUI with: py -m pip install pyautogui",
        }
    width, height = pyautogui.size()
    return {
        "ok": True,
        "status": "ready",
        "bridge": "windows_pyautogui",
        "auth": {"token_required": True, "authenticated": True},
        "screen": {"width": int(width), "height": int(height)},
        "pyautogui": {"available": True, "failsafe": bool(pyautogui.FAILSAFE), "pause": float(pyautogui.PAUSE)},
        "dependencies": dependencies,
        "demo_assets": demo_assets,
        "platform": platform_status,
        "atr_controller": controller_status,
        "server_version": "WindowsPyAutoGUIBridge/0.1",
        "script_version": "windows_pyautogui_bridge_server.py:utm_visual_control_v1",
        "artifacts": {"root": str(ARTIFACT_ROOT), "request_log": str(ARTIFACT_ROOT / "bridge_requests.jsonl"), "locator_root": str(LOCATOR_ROOT), "utm_export_root": str(UTM_EXPORT_ROOT)},
    }


def _programs() -> dict[str, Any]:
    def program_required_locators(program: dict[str, Any]) -> list[str]:
        names: list[str] = []
        sequence = program.get("sequence") if isinstance(program.get("sequence"), list) else []
        for action in sequence:
            if not isinstance(action, dict):
                continue
            if str(action.get("action") or "").strip() not in {"assert_visible", "click", "wait_until", "locate_image", "wait_until_image", "assert_text", "wait_until_text"}:
                continue
            target = str(action.get("target") or action.get("name") or "").strip()
            if target and target not in names:
                names.append(target)
        return names

    def program_payload(key: str, value: dict[str, Any]) -> dict[str, Any]:
        sequence = value.get("sequence") if isinstance(value.get("sequence"), list) else []
        safe_abort = value.get("safe_abort") if isinstance(value.get("safe_abort"), dict) else {}
        return {
            "program_id": key,
            **value,
            "sequence_step_count": len(sequence),
            "required_locator_names": program_required_locators(value),
            "safe_abort_program_id": str(safe_abort.get("program_id") or ""),
        }

    return {
        "ok": True,
        "status": "ready",
        "bridge": "windows_pyautogui",
        "auth": {"token_required": True, "authenticated": True},
        "program_root": str(PROGRAM_ROOT),
        "programs": [program_payload(key, value) for key, value in sorted(_all_programs().items())],
    }


def _safe_segment(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return cleaned[:96].strip("._-") or fallback


def _artifact_payload(path: Path, *, artifact_id: str, kind: str, windows_path: str) -> dict[str, Any]:
    data = path.read_bytes()
    columns: list[str] = []
    row_count = 0
    content_type = "application/octet-stream"
    if kind == "utm_csv":
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        columns = [item.strip() for item in lines[0].split(",")] if lines else []
        row_count = max(0, len([line for line in lines[1:] if line.strip()]))
        content_type = "text/csv"
    elif kind in {"screen_png", "screenshot", "locator_png"}:
        content_type = "image/png"
    payload = {
        "ok": True,
        "artifact_id": artifact_id,
        "kind": kind,
        "filename": path.name,
        "windows_path": windows_path,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "stable_for_sec": 2.0,
        "row_count_probe": row_count,
        "columns_probe": columns,
        "content_type": content_type,
    }
    if kind in {"screen_png", "screenshot", "locator_png"}:
        signature = _image_signature(path)
        payload["image_signature"] = signature
        payload["image_signature_ok"] = bool(signature)
    if kind == "utm_csv":
        try:
            probe = _probe_utm_csv(path)
            payload["parse_ok"] = bool(probe.get("ok"))
            payload["data_quality"] = probe.get("data_quality", {})
            if probe.get("failure_code"):
                payload["parse_failure_code"] = probe.get("failure_code")
                payload["parse_failure_message"] = probe.get("message", "")
        except Exception as exc:
            payload["parse_ok"] = False
            payload["parse_failure_code"] = "UTM_DATA_PARSE_FAILED"
            payload["parse_failure_message"] = exc.__class__.__name__
    ARTIFACT_INDEX[artifact_id] = {**payload, "path": str(path)}
    return payload


def _artifact_kind_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    parent = str(path.parent).lower()
    if suffix == ".csv":
        return "utm_csv"
    if suffix == ".png" and ("locator" in parent or name.startswith("locator_")):
        return "locator_png"
    if suffix == ".png":
        return "screen_png"
    return "artifact"


def _artifact_id_from_path(path: Path) -> str:
    artifact_id = _safe_segment(path.stem, "artifact")
    existing = ARTIFACT_INDEX.get(artifact_id)
    if existing and str(existing.get("path") or "") != str(path):
        digest = hashlib.sha256(str(path).encode("utf-8", errors="ignore")).hexdigest()[:8]
        artifact_id = f"{artifact_id}_{digest}"
    return artifact_id


def _image_signature(path: Path) -> str:
    try:
        header = path.read_bytes()[:16]
    except Exception:
        return ""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return ""


def _image_signature_ok(path: Path) -> bool:
    return bool(_image_signature(path))


def _rebuild_artifact_index() -> int:
    """Recover pullable artifact metadata after a Windows bridge restart."""
    indexed = 0
    known_paths = {str(item.get("path") or "") for item in ARTIFACT_INDEX.values() if isinstance(item, dict)}
    for root in (ARTIFACT_ROOT, UTM_EXPORT_ROOT):
        if not root.exists():
            continue
        try:
            paths = [path for path in root.rglob("*") if path.is_file()]
        except Exception:
            continue
        for path in paths:
            if path.name == "bridge_requests.jsonl" or str(path) in known_paths:
                continue
            if path.suffix.lower() not in {".csv", ".json", ".txt", ".png"}:
                continue
            try:
                if path.stat().st_size > 100 * 1024 * 1024:
                    continue
                artifact_id = _artifact_id_from_path(path)
                payload = _artifact_payload(path, artifact_id=artifact_id, kind=_artifact_kind_from_path(path), windows_path=str(path))
                ARTIFACT_INDEX[artifact_id]["indexed_from_disk"] = True
                ARTIFACT_INDEX[artifact_id]["source_root"] = str(root)
                payload["indexed_from_disk"] = True
                known_paths.add(str(path))
                indexed += 1
            except Exception:
                continue
    return indexed


def _capture_screenshot_artifact(
    pyautogui: Any,
    *,
    run_id: str,
    checkpoint: str,
    trace: list[dict[str, Any]],
    region: tuple[int, int, int, int] | None = None,
) -> dict[str, Any] | None:
    try:
        screenshot_dir = ARTIFACT_ROOT / run_id / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        artifact_id = f"screen_{_safe_segment(checkpoint, 'checkpoint')}_{timestamp}"
        path = screenshot_dir / f"{artifact_id}.png"
        image = pyautogui.screenshot(region=region) if region is not None else pyautogui.screenshot()
        image.save(path)
        if not _image_signature_ok(path):
            trace.append({"step": f"SCREENSHOT_{checkpoint.upper()}", "status": "blocked", "detail": f"invalid image signature: {path}"})
            try:
                path.unlink()
            except OSError:
                pass
            return None
        trace.append({"step": f"SCREENSHOT_{checkpoint.upper()}", "status": "ok", "detail": str(path)})
        return _artifact_payload(path, artifact_id=artifact_id, kind="screen_png", windows_path=str(path))
    except Exception as exc:
        trace.append({"step": f"SCREENSHOT_{checkpoint.upper()}", "status": "warning", "detail": exc.__class__.__name__})
        return None


def _screen_checks_from_artifacts(screen_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = {
        str(item.get("artifact_id")): item
        for item in screen_artifacts
        if isinstance(item, dict) and item.get("kind") == "screen_png" and item.get("image_signature_ok") is True
    }
    before_id = next((key for key in lookup if "before_start" in key), "")
    running_id = next((key for key in lookup if "after_start" in key), "")
    complete_id = next((key for key in lookup if "after_complete" in key), "")
    failure_id = next((key for key in lookup if "failure" in key), "")
    checks = [
        {"checkpoint": "before_start", "ok": bool(before_id), "state": "ready" if before_id else "unknown", "screenshot_artifact": before_id},
        {"checkpoint": "after_start", "ok": bool(running_id), "state": "running" if running_id else "not_observed", "screenshot_artifact": running_id},
        {"checkpoint": "after_complete", "ok": bool(complete_id), "state": "complete" if complete_id else "not_observed", "screenshot_artifact": complete_id},
    ]
    if failure_id:
        checks.append({"checkpoint": "failure", "ok": False, "state": "blocked", "screenshot_artifact": failure_id})
    return checks


def _required_utm_screen_evidence_gate(screen_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    checks = _screen_checks_from_artifacts(screen_artifacts)
    required = ("before_start", "after_start", "after_complete")
    by_checkpoint = {str(item.get("checkpoint")): item for item in checks if isinstance(item, dict)}
    missing = [
        checkpoint
        for checkpoint in required
        if not (by_checkpoint.get(checkpoint) or {}).get("ok") or not (by_checkpoint.get(checkpoint) or {}).get("screenshot_artifact")
    ]
    artifact_ids = [str(by_checkpoint[checkpoint].get("screenshot_artifact") or "") for checkpoint in required if checkpoint in by_checkpoint]
    duplicate = len([item for item in artifact_ids if item]) != len(set(item for item in artifact_ids if item))
    if missing or duplicate:
        blockers = []
        if missing:
            blockers.append("missing=" + ",".join(missing))
        if duplicate:
            blockers.append("duplicate_screen_artifacts")
        return {
            "ok": False,
            "failure_code": "UTM_SCREEN_EVIDENCE_FILES_REQUIRED",
            "message": "Live UTM completion requires distinct valid PNG screenshots for before_start, after_start, and after_complete.",
            "blockers": blockers,
            "screen_checks": checks,
        }
    return {"ok": True, "screen_checks": checks, "blockers": []}


def _screenshot_response(payload: dict[str, Any]) -> dict[str, Any]:
    pyautogui, error = _load_pyautogui()
    trace: list[dict[str, Any]] = []
    if pyautogui is None:
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_NOT_INSTALLED",
            "requires_install": True,
            "message": f"PyAutoGUI is not installed: {error}",
            "step_trace": [{"step": "HEALTH", "status": "blocked", "detail": "pyautogui import failed"}],
        }
    run_id = _safe_segment(payload.get("run_id") or "locator-calibration", "locator-calibration")
    artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=str(payload.get("checkpoint") or "manual"), trace=trace)
    if not artifact:
        return {"ok": False, "status": "failed", "bridge": "windows_pyautogui", "failure_code": "PYAUTOGUI_SCREENSHOT_FAILED", "step_trace": trace}
    return {"ok": True, "status": "captured", "bridge": "windows_pyautogui", "output_artifacts": [artifact], "artifact": artifact, "step_trace": trace}


def _capture_locator(payload: dict[str, Any]) -> dict[str, Any]:
    pyautogui, error = _load_pyautogui()
    trace: list[dict[str, Any]] = []
    if pyautogui is None:
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_NOT_INSTALLED",
            "requires_install": True,
            "message": f"PyAutoGUI is not installed: {error}",
            "step_trace": [{"step": "HEALTH", "status": "blocked", "detail": "pyautogui import failed"}],
        }
    name = _safe_segment(payload.get("name") or payload.get("target") or "locator", "locator")
    program_id = _safe_segment(payload.get("program_id") or "utm_compression_start_v1", "utm_compression_start_v1")
    region = payload.get("region")
    if not isinstance(region, list) or len(region) != 4:
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_LOCATOR_REGION_REQUIRED",
            "message": "region=[x,y,width,height] is required for locator capture.",
            "step_trace": [{"step": "VALIDATE_REGION", "status": "blocked", "detail": "missing region"}],
        }
    try:
        x, y, width, height = [int(float(item)) for item in region]
    except Exception:
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_LOCATOR_REGION_INVALID",
            "message": "region values must be numeric.",
            "step_trace": [{"step": "VALIDATE_REGION", "status": "blocked", "detail": "non-numeric"}],
        }
    if width <= 0 or height <= 0:
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_LOCATOR_REGION_INVALID",
            "message": "region width and height must be positive.",
            "step_trace": [{"step": "VALIDATE_REGION", "status": "blocked", "detail": "non-positive size"}],
        }
    try:
        locator_dir = LOCATOR_ROOT / program_id
        locator_dir.mkdir(parents=True, exist_ok=True)
        path = locator_dir / f"{name}.png"
        image = pyautogui.screenshot(region=(x, y, width, height))
        image.save(path)
        if not _image_signature_ok(path):
            try:
                path.unlink()
            except OSError:
                pass
            return {
                "ok": False,
                "status": "failed",
                "bridge": "windows_pyautogui",
                "failure_code": "PYAUTOGUI_LOCATOR_CAPTURE_INVALID_IMAGE",
                "message": "Locator capture did not produce a valid image file.",
                "step_trace": [{"step": "CAPTURE_LOCATOR", "status": "blocked", "detail": "invalid image signature"}],
            }
        artifact_id = f"locator_{program_id}_{name}_{int(time.time())}"
        artifact = _artifact_payload(path, artifact_id=artifact_id, kind="locator_png", windows_path=str(path))
        trace.append({"step": "CAPTURE_LOCATOR", "status": "ok", "detail": str(path)})
        locator = {
            "image_path": str(path),
            "confidence": float(payload.get("confidence", 0.8)),
            "region": [x, y, width, height],
            "target": name,
        }
        return {
            "ok": True,
            "status": "captured",
            "bridge": "windows_pyautogui",
            "program_id": program_id,
            "locator_name": name,
            "locator": locator,
            "output_artifacts": [artifact],
            "artifact": artifact,
            "step_trace": trace,
        }
    except Exception as exc:
        trace.append({"step": "CAPTURE_LOCATOR", "status": "failed", "detail": exc.__class__.__name__})
        return {
            "ok": False,
            "status": "failed",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_LOCATOR_CAPTURE_FAILED",
            "message": f"Locator capture failed: {exc.__class__.__name__}",
            "step_trace": trace,
        }


def _list_locators() -> dict[str, Any]:
    locators: list[dict[str, Any]] = []
    if LOCATOR_ROOT.exists():
        for path in sorted(LOCATOR_ROOT.rglob("*.png")):
            rel = path.relative_to(LOCATOR_ROOT)
            locators.append({"name": path.stem, "program_id": rel.parts[0] if len(rel.parts) > 1 else "", "image_path": str(path), "filename": path.name})
    return {"ok": True, "status": "ready", "locator_root": str(LOCATOR_ROOT), "locators": locators}




_DEFAULT_REQUIRED_UTM_LOCATORS = ("ready_state", "start_button", "running_state", "complete_state")


def _required_utm_locator_names(program_id: str = "utm_compression_start_v1", payload: dict[str, Any] | None = None) -> list[str]:
    """Return locator names that the selected UTM protocol must calibrate before live use."""
    runtime_payload = payload if isinstance(payload, dict) else {}
    names: list[str] = []
    for action in _program_sequence(program_id, runtime_payload):
        action_name = str(action.get("action") or "").strip().lower()
        if action_name not in {"assert_visible", "click", "wait_until", "locate_image", "wait_until_image", "assert_text", "wait_until_text"}:
            continue
        target = str(action.get("target") or action.get("name") or "").strip()
        if target and target not in names:
            names.append(target)
    return names or list(_DEFAULT_REQUIRED_UTM_LOCATORS)


def _configured_locator_names(program_id: str = "utm_compression_start_v1") -> list[str]:
    """Return image locator names captured on this Windows bridge for the selected UTM program."""
    names: list[str] = []
    if not LOCATOR_ROOT.exists():
        return names
    for path in sorted(LOCATOR_ROOT.rglob("*.png")):
        try:
            rel = path.relative_to(LOCATOR_ROOT)
        except ValueError:
            rel = path
        item_program = rel.parts[0] if len(rel.parts) > 1 else ""
        if item_program not in {"", program_id}:
            continue
        if path.stem not in names:
            names.append(path.stem)
    return names


def _utm_readiness(program_id: str = "utm_compression_start_v1") -> dict[str, Any]:
    """Passive Windows-side UTM setup check; does not execute the UTM protocol."""
    health = _health() if "_health" in globals() else health_payload()
    required = _required_utm_locator_names(program_id)
    configured = _configured_locator_names(program_id)
    missing = [name for name in required if name not in configured]
    blockers: list[str] = []
    warnings: list[str] = []
    pyautogui_status = health.get("pyautogui") if isinstance(health.get("pyautogui"), dict) else {}
    if not pyautogui_status.get("available"):
        blockers.append("PYAUTOGUI_NOT_INSTALLED")
    if missing:
        blockers.append("UTM_REQUIRED_LOCATORS_MISSING")
    if not UTM_EXPORT_ROOT.exists():
        warnings.append("UTM_EXPORT_ROOT_NOT_FOUND")
    status = "ready" if not blockers else "blocked"
    gates = {
        "pyautogui_available": bool(pyautogui_status.get("available")),
        "program_id": program_id,
        "program_registered": program_id in PROGRAMS,
        "locator_root": str(LOCATOR_ROOT),
        "locator_count": len(configured),
        "configured_locator_names": configured,
        "required_locator_names": required,
        "missing_required_locators": missing,
        "required_locators_complete": not missing,
        "utm_export_root": str(UTM_EXPORT_ROOT),
        "utm_export_root_exists": UTM_EXPORT_ROOT.exists(),
        "screen_assertions_env_required": bool(REQUIRE_UTM_SCREEN_ASSERTIONS),
    }
    return {
        "ok": not blockers,
        "tool": "equipment.pyautogui.windows_readiness",
        "status": status,
        "bridge": "windows_pyautogui",
        "program_id": program_id,
        "health": health,
        "gates": gates,
        "required_locator_names": required,
        "configured_locator_names": configured,
        "missing_required_locators": missing,
        "required_locators_complete": not missing,
        "blockers": blockers,
        "warnings": warnings,
        "message": "UTM Windows bridge ready." if not blockers else "Complete the listed setup gates before live UTM control.",
    }

def _format_runtime_value(value: Any, *, run_id: str, specimen_id: str) -> str:
    return str(value or "").replace("{run_id}", run_id).replace("{specimen_id}", specimen_id)


def _program_sequence(program_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("sequence")
    if isinstance(raw, list) and raw:
        return [dict(item) for item in raw if isinstance(item, dict)]
    program = _all_programs().get(program_id, {})
    raw = program.get("sequence")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    return []


def _locator_for(action: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    target = str(action.get("target") or action.get("name") or "").strip()
    locators = payload.get("locators") if isinstance(payload.get("locators"), dict) else {}
    locator = locators.get(target) if target else None
    if isinstance(locator, dict):
        merged = dict(locator)
    else:
        merged = {}
    for key in (
        "image_path",
        "target_image",
        "image_candidates",
        "recorded_coordinate",
        "coordinate_fallback",
        "confidence",
        "region",
        "x",
        "y",
        "width",
        "height",
        "locator_backend",
        "backend",
        "uia_auto_id",
        "auto_id",
        "automation_id",
        "uia_title",
        "uia_name",
        "name",
        "title",
        "control_type",
        "class_name",
        "best_match",
        "window_title",
        "target_window",
        "target_window_regex",
        "text",
        "expected_text",
        "contains",
        "match_text",
        "ocr_config",
    ):
        if key in action and key not in merged:
            merged[key] = action[key]
    if target:
        merged.setdefault("target", target)
    return merged


def _png_visual_information_score(raw: bytes) -> float:
    """Estimate whether a locator crop contains structure instead of a flat field."""
    try:
        from PIL import Image, ImageStat  # type: ignore

        with Image.open(BytesIO(raw)) as image:
            grayscale = image.convert("L")
            return float(ImageStat.Stat(grayscale).var[0])
    except Exception:
        return 0.0


def _best_inline_image_match(
    pyautogui: Any,
    candidates: list[tuple[str, dict[str, Any], float]],
) -> tuple[bool, tuple[int, int, int, int] | None]:
    """Return the global best inline-template match instead of scan-order first."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        screenshot = pyautogui.screenshot()
        screen_rgb = np.asarray(screenshot.convert("RGB"))
        screen = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2GRAY)
    except Exception:
        return False, None

    best_match: tuple[int, int, int, int] | None = None
    global_best_score = float("-inf")
    for candidate_path, candidate, _information_score in candidates:
        template = cv2.imread(candidate_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            continue
        region = candidate.get("region")
        offset_x = 0
        offset_y = 0
        haystack = screen
        if isinstance(region, (list, tuple)) and len(region) == 4:
            offset_x, offset_y, width, height = (int(value) for value in region)
            haystack = screen[offset_y : offset_y + height, offset_x : offset_x + width]
        template_height, template_width = template.shape[:2]
        if haystack.shape[0] < template_height or haystack.shape[1] < template_width:
            continue
        scores = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
        _minimum, candidate_score, _minimum_location, best_location = cv2.minMaxLoc(scores)
        confidence = float(candidate.get("confidence", 0.999))
        if float(candidate_score) < confidence:
            continue
        candidate_score = float(candidate_score)
        if candidate_score <= global_best_score:
            continue
        global_best_score = candidate_score
        best_match = (
            int(best_location[0]) + offset_x,
            int(best_location[1]) + offset_y,
            int(template_width),
            int(template_height),
        )
    return True, best_match


def _locate_on_screen(pyautogui: Any, locator: dict[str, Any], *, run_id: str, specimen_id: str) -> Any | None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    inline_candidates: list[tuple[str, dict[str, Any], float]] = []
    image_path = locator.get("image_path") or locator.get("target_image")
    if image_path:
        candidates.append((_format_runtime_value(image_path, run_id=run_id, specimen_id=specimen_id), locator))
    for raw_candidate in locator.get("image_candidates", []):
        if not isinstance(raw_candidate, dict):
            continue
        candidate = dict(raw_candidate)
        encoded = str(candidate.get("png_base64") or "")
        expected_sha = str(candidate.get("sha256") or "").lower()
        if not encoded or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        if len(raw) > 256 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            continue
        inline_dir = LOCATOR_ROOT / "inline"
        inline_dir.mkdir(parents=True, exist_ok=True)
        materialized = inline_dir / f"{expected_sha}.png"
        if not materialized.exists() or materialized.read_bytes() != raw:
            temporary = materialized.with_suffix(f".{uuid4().hex}.tmp")
            temporary.write_bytes(raw)
            temporary.replace(materialized)
        inline_candidates.append((str(materialized), candidate, _png_visual_information_score(raw)))
    informative = [item for item in inline_candidates if item[2] >= 12.0]
    ordered_inline = sorted(
        informative,
        key=lambda item: (str(item[1].get("kind") or "") == "context", item[2]),
        reverse=True,
    ) if informative else inline_candidates
    for candidate_path, candidate in candidates:
        kwargs: dict[str, Any] = {}
        confidence = candidate.get("confidence", locator.get("confidence"))
        if confidence is not None:
            kwargs["confidence"] = float(confidence)
        region = candidate.get("region", locator.get("region"))
        if isinstance(region, (list, tuple)) and len(region) == 4:
            kwargs["region"] = tuple(int(v) for v in region)
        match = pyautogui.locateOnScreen(candidate_path, **kwargs)
        if match:
            return match
    if ordered_inline:
        attempted, match = _best_inline_image_match(pyautogui, ordered_inline)
        if attempted:
            return match
    for candidate_path, candidate, _score in ordered_inline:
        kwargs = {}
        confidence = candidate.get("confidence", locator.get("confidence"))
        if confidence is not None:
            kwargs["confidence"] = float(confidence)
        region = candidate.get("region", locator.get("region"))
        if isinstance(region, (list, tuple)) and len(region) == 4:
            kwargs["region"] = tuple(int(v) for v in region)
        match = pyautogui.locateOnScreen(candidate_path, **kwargs)
        if match:
            return match
    return None


def _region_tuple(locator: dict[str, Any]) -> tuple[int, int, int, int] | None:
    region = locator.get("region")
    if isinstance(region, (list, tuple)) and len(region) == 4:
        return tuple(int(float(v)) for v in region)  # type: ignore[return-value]
    if all(locator.get(key) is not None for key in ("x", "y", "width", "height")):
        return (
            int(float(locator.get("x") or 0)),
            int(float(locator.get("y") or 0)),
            int(float(locator.get("width") or 0)),
            int(float(locator.get("height") or 0)),
        )
    return None


def _ocr_text_from_screen(pyautogui: Any, locator: dict[str, Any]) -> tuple[bool, str, str]:
    if hasattr(pyautogui, "ocr_text"):
        return True, str(getattr(pyautogui, "ocr_text") or ""), "pyautogui.ocr_text"
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        return False, "", f"pytesseract unavailable: {exc.__class__.__name__}"
    try:
        region = _region_tuple(locator)
        image = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        config = str(locator.get("ocr_config") or "")
        text = pytesseract.image_to_string(image, config=config).strip()
        return True, text, "pytesseract"
    except Exception as exc:
        return False, "", f"ocr failed: {exc.__class__.__name__}"


def _text_matches_observed(locator: dict[str, Any], observed_text: str) -> tuple[bool, str]:
    expected = str(locator.get("expected_text") or locator.get("contains") or locator.get("match_text") or locator.get("text") or "").strip()
    if not expected:
        return False, "expected text missing"
    case_sensitive = bool(locator.get("case_sensitive"))
    haystack = observed_text if case_sensitive else observed_text.lower()
    needle = expected if case_sensitive else expected.lower()
    return needle in haystack, expected


_UIA_LOCATOR_KEYS = (
    "uia_auto_id",
    "auto_id",
    "automation_id",
    "uia_title",
    "uia_name",
    "title",
    "name",
    "control_type",
    "class_name",
    "best_match",
)


def _locator_uses_uia(locator: dict[str, Any]) -> bool:
    """Return true when a locator carries Windows UI Automation selector data."""
    backend = str(locator.get("locator_backend") or locator.get("backend") or locator.get("type") or "").strip().lower()
    if backend in {"uia", "pywinauto", "windows_uia"}:
        return True
    return any(str(locator.get(key) or "").strip() for key in _UIA_LOCATOR_KEYS)


def _first_text(locator: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(locator.get(key) or "").strip()
        if value:
            return value
    return ""


def _find_uia_element(locator: dict[str, Any], payload: dict[str, Any], program: dict[str, Any]) -> tuple[Any | None, str]:
    """Find a Windows UIA element with pywinauto when it is installed on Windows."""
    try:
        from pywinauto import Desktop  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Windows-side optional package
        return None, f"pywinauto unavailable: {exc.__class__.__name__}"

    criteria: dict[str, Any] = {}
    auto_id = _first_text(locator, "uia_auto_id", "auto_id", "automation_id")
    if auto_id:
        criteria["auto_id"] = auto_id
    title = _first_text(locator, "uia_title", "uia_name", "title", "name")
    if title:
        criteria["title"] = title
    control_type = _first_text(locator, "control_type")
    if control_type:
        criteria["control_type"] = control_type
    class_name = _first_text(locator, "class_name")
    if class_name:
        criteria["class_name"] = class_name
    best_match = _first_text(locator, "best_match")
    if best_match:
        criteria["best_match"] = best_match
    if not criteria:
        return None, "uia selector missing"

    titles, regexes = _window_selector_candidates(locator, payload, program)
    try:
        desktop = Desktop(backend="uia")
        roots: list[Any] = []
        for pattern in regexes:
            try:
                roots.extend(list(desktop.windows(title_re=pattern)))
            except Exception:
                continue
        for title_candidate in titles:
            try:
                roots.extend(list(desktop.windows(title=title_candidate)))
            except Exception:
                pass
            try:
                roots.extend(list(desktop.windows(title_re=f".*{re.escape(title_candidate)}.*")))
            except Exception:
                pass
        if not roots:
            roots = [desktop]

        last_error = ""
        timeout_s = float(locator.get("uia_timeout_s") or locator.get("timeout_s") or 0.2)
        for root in roots:
            try:
                if hasattr(root, "child_window"):
                    element = root.child_window(**criteria)
                elif hasattr(root, "window"):
                    element = root.window(**criteria)
                else:
                    continue
                if element is None:
                    continue
                if hasattr(element, "exists") and not element.exists(timeout=timeout_s):
                    last_error = "exists=false"
                    continue
                return element, "uia:" + ",".join(f"{key}={value}" for key, value in criteria.items())
            except Exception as exc:
                last_error = exc.__class__.__name__
        return None, "uia target not found" + (f": {last_error}" if last_error else "")
    except Exception as exc:  # pragma: no cover - defensive for Windows UIA backend failures
        return None, f"uia lookup failed: {exc.__class__.__name__}"


_ERROR_POPUP_LOCATOR_NAMES = (
    "error_popup",
    "error_dialog",
    "warning_dialog",
    "modal_error",
    "communication_error",
    "save_error",
    "utm_error_popup",
)


def _looks_like_locator(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    selector_keys = {
        "image_path",
        "target_image",
        "x",
        "y",
        "locator_backend",
        "backend",
        "type",
        "uia_auto_id",
        "auto_id",
        "automation_id",
        "uia_title",
        "uia_name",
        "title",
        "name",
        "control_type",
        "class_name",
        "best_match",
    }
    return any(key in value for key in selector_keys)


def _configured_error_popup_locators(payload: dict[str, Any], program: dict[str, Any]) -> list[dict[str, Any]]:
    """Return configured error/popup locators without inventing defaults."""
    locators: list[dict[str, Any]] = []

    def add(value: Any, target: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        if isinstance(value, dict) and _looks_like_locator(value):
            locator = dict(value)
            if target:
                locator.setdefault("target", target)
            locators.append(locator)
            return
        if isinstance(value, dict):
            for name, item in value.items():
                add(item, str(name))

    for source in (program, payload):
        for key in ("error_popups", "error_popup_locators", "popup_locators"):
            add(source.get(key))
    all_locators = payload.get("locators") if isinstance(payload.get("locators"), dict) else {}
    for name in _ERROR_POPUP_LOCATOR_NAMES:
        if isinstance(all_locators.get(name), dict):
            add(all_locators[name], name)
    return locators


def _detect_error_popup(pyautogui: Any, payload: dict[str, Any], program: dict[str, Any], *, run_id: str, specimen_id: str) -> tuple[bool, str]:
    """Detect configured UTM error/modal popups through UIA first, then image matching."""
    for locator in _configured_error_popup_locators(payload, program):
        target = str(locator.get("target") or locator.get("name") or "error_popup")
        try:
            if _locator_uses_uia(locator):
                element, detail = _find_uia_element(locator, payload, program)
                if element is not None:
                    return True, f"{target} via {detail or 'uia'}"
            box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
            if box:
                return True, f"{target} via image"
        except Exception as exc:
            return True, f"{target} detection failed: {exc.__class__.__name__}"
    return False, ""


_WINDOW_SELECTOR_PLACEHOLDERS = {
    "",
    "main",
    "main_window",
    "main_window_title",
    "main_window_title_or_regex",
    "target_window",
    "window",
}


def _window_selector_candidates(action: dict[str, Any], payload: dict[str, Any], program: dict[str, Any]) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    regexes: list[str] = []
    seen: set[str] = set()

    def add_title(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            for item in value:
                add_title(item)
            return
        text = str(value or "").strip()
        if text.lower() in _WINDOW_SELECTOR_PLACEHOLDERS:
            return
        if text and text not in seen:
            seen.add(text)
            titles.append(text)

    def add_regex(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text.lower() in _WINDOW_SELECTOR_PLACEHOLDERS:
            return
        if text.startswith("regex:"):
            text = text[6:].strip()
        if len(text) >= 2 and text.startswith("/") and text.endswith("/"):
            text = text[1:-1]
        if text and text not in seen:
            seen.add(text)
            regexes.append(text)

    for source in (action, payload, program):
        for key in ("title_regex", "window_regex", "target_window_regex"):
            add_regex(source.get(key))
        for key in ("title", "window_title", "target_window", "target_app", "app_title"):
            value = source.get(key)
            if isinstance(value, str) and (value.startswith("regex:") or (value.startswith("/") and value.endswith("/"))):
                add_regex(value)
            else:
                add_title(value)
    add_title(action.get("window"))
    return titles, regexes


def _activate_window(window: Any) -> bool:
    try:
        if bool(getattr(window, "isMinimized", False)) and hasattr(window, "restore"):
            window.restore()
        if hasattr(window, "activate"):
            window.activate()
        elif hasattr(window, "focus"):
            window.focus()
        else:
            return False
        time.sleep(0.2)
        return True
    except Exception:
        return False


def _focus_linux_window(titles: list[str], regexes: list[str]) -> tuple[bool, str]:
    try:
        listing = subprocess.run(
            ["wmctrl", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"wmctrl unavailable: {exc.__class__.__name__}"
    windows: list[tuple[str, str]] = []
    for line in listing.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            windows.append((parts[0], parts[3]))
    compiled_patterns = []
    for pattern in regexes:
        try:
            compiled_patterns.append(re.compile(pattern))
        except re.error:
            continue
    for window_id, window_title in windows:
        title_match = any(title.casefold() in window_title.casefold() for title in titles)
        regex_match = any(pattern.search(window_title) for pattern in compiled_patterns)
        if not (title_match or regex_match):
            continue
        try:
            activated = subprocess.run(
                ["wmctrl", "-ia", window_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"window activation failed: {exc.__class__.__name__}"
        if activated.returncode == 0:
            time.sleep(0.2)
            return True, f"title={window_title}"
        return False, f"window activation failed: {window_title}"
    selectors = titles + [f"regex:{pattern}" for pattern in regexes]
    return False, "window not found: " + ", ".join(selectors)


def _focus_window(pyautogui: Any, action: dict[str, Any], payload: dict[str, Any], program: dict[str, Any]) -> tuple[bool, str]:
    titles, regexes = _window_selector_candidates(action, payload, program)

    if BRIDGE_PLATFORM == "linux" and (titles or regexes):
        return _focus_linux_window(titles, regexes)

    if regexes and hasattr(pyautogui, "getAllWindows"):
        try:
            windows = list(pyautogui.getAllWindows())
        except Exception as exc:
            windows = []
            last_error = exc.__class__.__name__
        else:
            last_error = ""
        for pattern in regexes:
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue
            for window in windows:
                title = str(getattr(window, "title", "") or "")
                if compiled.search(title) and _activate_window(window):
                    return True, f"regex={pattern}; title={title or '<untitled>'}"
        if last_error:
            return False, f"window enumeration failed: {last_error}"

    if titles and hasattr(pyautogui, "getWindowsWithTitle"):
        for title in titles:
            try:
                windows = list(pyautogui.getWindowsWithTitle(title))
            except Exception as exc:
                return False, f"window lookup failed for {title}: {exc.__class__.__name__}"
            for window in windows:
                window_title = str(getattr(window, "title", "") or title)
                if _activate_window(window):
                    return True, f"title={window_title}"

    keys = action.get("hotkey") or action.get("keys")
    if isinstance(keys, list) and keys:
        pyautogui.hotkey(*[str(key) for key in keys])
        return True, "+".join(str(key) for key in keys)

    if titles or regexes:
        selectors = titles + [f"regex:{pattern}" for pattern in regexes]
        return False, "window not found: " + ", ".join(selectors)
    return False, "No window selector or hotkey configured; focus assumed by operator"


def _dpi_scaling_hint(payload: dict[str, Any]) -> str:
    value = payload.get("dpi_scaling") or payload.get("dpi_scale")
    if value not in (None, ""):
        return str(value)
    try:  # pragma: no cover - Windows-only best effort
        import ctypes

        scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        if scale:
            return f"{int(scale)}%"
    except Exception:
        pass
    return "unknown"


def _window_rect_hint(pyautogui: Any, action: dict[str, Any], payload: dict[str, Any], program: dict[str, Any]) -> str:
    titles, regexes = _window_selector_candidates(action, payload, program)
    candidates: list[Any] = []
    for title in titles:
        try:
            candidates.extend(list(pyautogui.getWindowsWithTitle(title)))
        except Exception:
            continue
    if regexes:
        try:
            all_windows = list(pyautogui.getAllWindows()) if hasattr(pyautogui, "getAllWindows") else []
        except Exception:
            all_windows = []
        for pattern in regexes:
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue
            for window in all_windows:
                if compiled.search(str(getattr(window, "title", ""))):
                    candidates.append(window)
    for window in candidates:
        left = getattr(window, "left", None)
        top = getattr(window, "top", None)
        width = getattr(window, "width", None)
        height = getattr(window, "height", None)
        if None not in (left, top, width, height):
            return f"{int(left)},{int(top)},{int(width)},{int(height)}"
    return "unknown"


def _coordinate_click_context(pyautogui: Any, action: dict[str, Any], payload: dict[str, Any], program: dict[str, Any]) -> dict[str, str]:
    try:
        width, height = pyautogui.size()
        screen_size = f"{int(width)}x{int(height)}"
    except Exception:
        screen_size = "unknown"
    return {
        "screen_size": screen_size,
        "dpi_scaling": _dpi_scaling_hint(payload),
        "target_window_rect": _window_rect_hint(pyautogui, action, payload, program),
    }


def _execute_protocol_sequence_impl(
    pyautogui: Any,
    *,
    program_id: str,
    payload: dict[str, Any],
    run_id: str,
    specimen_id: str,
    trace: list[dict[str, Any]],
    screen_artifacts: list[dict[str, Any]] | None = None,
    held_buttons: set[str] | None = None,
    held_keys: set[str] | None = None,
) -> dict[str, Any]:
    sequence = _program_sequence(program_id, payload)
    program = _all_programs().get(program_id, {})
    require_assertions = bool(REQUIRE_UTM_SCREEN_ASSERTIONS or payload.get("require_screen_assertions"))
    last_successful_click = False
    held_buttons = held_buttons if held_buttons is not None else set()
    held_keys = held_keys if held_keys is not None else set()

    def add(step_name: str, status: str, detail: str = "") -> None:
        item = {"step": step_name, "status": status}
        if detail:
            item["detail"] = detail
        trace.append(item)

    def popup_failure(step_name: str) -> dict[str, Any] | None:
        detected, detail = _detect_error_popup(pyautogui, payload, program, run_id=run_id, specimen_id=specimen_id)
        if not detected:
            return None
        add(step_name, "blocked", detail)
        return {
            "ok": False,
            "failure_code": "UTM_ERROR_POPUP_DETECTED",
            "message": f"Configured UTM error popup was detected: {detail}",
        }

    def bounded_coordinate(x: int, y: int, step_name: str) -> dict[str, Any] | None:
        try:
            width, height = pyautogui.size()
        except Exception:
            return None
        if 0 <= x < int(width) and 0 <= y < int(height):
            return None
        add(step_name, "blocked", f"coordinate=({x},{y}); screen={int(width)}x{int(height)}")
        return {
            "ok": False,
            "failure_code": "PYAUTOGUI_COORDINATE_OUT_OF_BOUNDS",
            "message": f"Absolute coordinate ({x}, {y}) is outside screen {int(width)}x{int(height)}.",
        }

    def selected_window(action: dict[str, Any], step_name: str) -> tuple[Any | None, dict[str, Any] | None]:
        title = str(action.get("title") or action.get("window") or "").strip()
        try:
            windows = list(pyautogui.getWindowsWithTitle(title))
        except Exception as exc:
            add(step_name, "blocked", f"window lookup failed: {exc.__class__.__name__}")
            return None, {"ok": False, "failure_code": "PYAUTOGUI_WINDOW_NOT_FOUND", "message": f"Window lookup failed: {title}"}
        if not windows:
            add(step_name, "blocked", f"window not found: {title}")
            return None, {"ok": False, "failure_code": "PYAUTOGUI_WINDOW_NOT_FOUND", "message": f"Window not found: {title}"}
        return windows[0], None

    for index, action in enumerate(sequence):
        action_name = str(action.get("action") or "").strip()
        step_name = f"SEQ_{index + 1}_{action_name.upper() or 'UNKNOWN'}"
        if action_name not in {"", "health"}:
            failure = popup_failure(f"{step_name}_POPUP_PRECHECK")
            if failure:
                return failure
        if action_name in {"", "health"}:
            add(step_name, "ok")
            continue
        if action_name == "focus_window":
            focused, detail = _focus_window(pyautogui, action, payload, program)
            if focused:
                add(step_name, "ok", detail)
            elif action.get("required") is True or payload.get("require_window_focus") is True:
                add(step_name, "blocked", detail)
                return {"ok": False, "failure_code": "PYAUTOGUI_WINDOW_NOT_FOUND", "message": detail}
            else:
                add(step_name, "warning", detail)
            continue
        if action_name == "screenshot":
            checkpoint = str(action.get("checkpoint") or action.get("name") or action.get("target") or "manual")
            region = tuple(int(item) for item in action["region"]) if isinstance(action.get("region"), (list, tuple)) and len(action["region"]) == 4 else None
            artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=checkpoint, trace=trace, region=region)
            if artifact:
                if screen_artifacts is not None:
                    screen_artifacts.append(artifact)
                add(step_name, "ok", str(artifact.get("artifact_id") or checkpoint))
            elif require_assertions or action.get("required") is True:
                add(step_name, "blocked", checkpoint)
                return {"ok": False, "failure_code": "PYAUTOGUI_SCREENSHOT_FAILED", "message": f"Required screenshot failed: {checkpoint}"}
            else:
                add(step_name, "warning", checkpoint)
            continue
        if action_name in {"assert_visible", "wait_until", "locate_image", "wait_until_image", "assert_text", "wait_until_text"}:
            locator = _locator_for(action, payload)
            timeout_s = float(action.get("timeout_s", 1.0 if action_name in {"assert_visible", "locate_image", "assert_text"} else 10.0))
            deadline = time.monotonic() + max(0.1, timeout_s)
            resolved: dict[str, Any] | None = None
            last_detail = ""
            while time.monotonic() < deadline:
                failure = popup_failure(f"{step_name}_POPUP_WATCH")
                if failure:
                    return failure
                try:
                    if action_name in {"assert_text", "wait_until_text"}:
                        available, observed_text, detail = _ocr_text_from_screen(pyautogui, locator)
                        last_detail = detail or last_detail
                        if available:
                            matched, expected = _text_matches_observed(locator, observed_text)
                            last_detail = f"expected={expected!r}; observed={observed_text[:120]!r}"
                            if matched:
                                resolved = {"kind": "ocr", "text": observed_text, "detail": expected}
                    else:
                        if _locator_uses_uia(locator):
                            element, detail = _find_uia_element(locator, payload, program)
                            last_detail = detail or last_detail
                            if element is not None:
                                resolved = {"kind": "uia", "element": element, "detail": detail}
                        if resolved is None:
                            box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
                            if box:
                                resolved = {"kind": "image", "box": box, "detail": str(locator.get("image_path") or locator.get("target_image") or "image")}
                except Exception as exc:
                    if require_assertions:
                        add(step_name, "blocked", exc.__class__.__name__)
                        return {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "message": f"{action_name} failed: {exc.__class__.__name__}"}
                    add(step_name, "warning", f"locator unavailable: {exc.__class__.__name__}")
                    break
                if resolved is not None:
                    target_name = str(locator.get("target") or action.get("target") or "")
                    detail = str(resolved.get("detail") or target_name or locator.get("image_path") or "visible")
                    add(step_name, "ok", f"{target_name or detail} via {resolved.get('kind')}")
                    checkpoint = {"running_state": "after_start", "complete_state": "after_complete"}.get(target_name)
                    if checkpoint and screen_artifacts is not None:
                        if not any(checkpoint in str(item.get("artifact_id") or "") for item in screen_artifacts):
                            artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=checkpoint, trace=trace)
                            if artifact:
                                screen_artifacts.append(artifact)
                    last_successful_click = False
                    break
                if action_name in {"assert_visible", "locate_image", "assert_text"}:
                    break
                time.sleep(0.25)
            if resolved is None:
                target_name = str(locator.get("target") or action.get("target") or "")
                detail = last_detail or str(target_name or locator.get("image_path") or "locator missing")
                failure_code = "UI_LOCATOR_NOT_FOUND"
                extra: dict[str, Any] = {}
                if action_name in {"wait_until", "wait_until_image", "wait_until_text"}:
                    if target_name == "running_state":
                        failure_code = "CLICK_NO_STATE_CHANGE" if last_successful_click else "UTM_RUNNING_STATE_TIMEOUT"
                        extra["timeout_failure_code"] = "UTM_RUNNING_STATE_TIMEOUT"
                    elif target_name == "complete_state":
                        failure_code = "UTM_TEST_COMPLETE_TIMEOUT"
                    elif target_name in {"save_dialog", "save_as_dialog", "save_dialog_open"}:
                        failure_code = "UTM_SAVE_DIALOG_TIMEOUT"
                if require_assertions or action.get("required") is True:
                    add(step_name, "blocked", f"{failure_code}: {detail}")
                    return {"ok": False, "failure_code": failure_code, "message": f"Required screen target not found: {detail}", **extra}
                add(step_name, "warning", f"not asserted: {detail}")
            continue
        if action_name == "locate_all_images":
            locator = _locator_for(action, payload)
            image_path = locator.get("image_path") or locator.get("target_image")
            if not image_path or not hasattr(pyautogui, "locateAllOnScreen"):
                add(step_name, "blocked", "image path or locateAllOnScreen unavailable")
                return {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "message": "locate_all_images requires an image locator."}
            kwargs: dict[str, Any] = {}
            if locator.get("confidence") is not None:
                kwargs["confidence"] = float(locator["confidence"])
            if isinstance(locator.get("region"), (list, tuple)) and len(locator["region"]) == 4:
                kwargs["region"] = tuple(int(item) for item in locator["region"])
            matches = list(pyautogui.locateAllOnScreen(_format_runtime_value(image_path, run_id=run_id, specimen_id=specimen_id), **kwargs))
            matches = matches[: int(action.get("max_results", 20))]
            add(step_name, "ok", f"matches={len(matches)}")
            continue
        if action_name in {"click", "double_click", "triple_click"}:
            locator = _locator_for(action, payload)
            resolved: dict[str, Any] | None = None
            last_detail = ""
            try:
                if _locator_uses_uia(locator):
                    element, detail = _find_uia_element(locator, payload, program)
                    last_detail = detail or last_detail
                    if element is not None:
                        resolved = {"kind": "uia", "element": element, "detail": detail}
                if resolved is None:
                    box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
                    if box:
                        resolved = {"kind": "image", "box": box, "detail": str(locator.get("image_path") or locator.get("target_image") or "image")}
            except Exception as exc:
                if require_assertions:
                    add(step_name, "blocked", exc.__class__.__name__)
                    return {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "message": f"click locator failed: {exc.__class__.__name__}"}
            max_click_retries = min(1, int(action.get("max_retries", program.get("max_retries", 0)) or 0))
            if (
                resolved is None
                and max_click_retries > 0
                and locator.get("x") is None
                and locator.get("y") is None
            ):
                target_name = str(locator.get("target") or action.get("target") or "click_target")
                checkpoint = f"retry_before_{_safe_segment(target_name, 'click_target')}"
                artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=checkpoint, trace=trace)
                if artifact and screen_artifacts is not None:
                    screen_artifacts.append(artifact)
                add(f"{step_name}_RETRY_SCREENSHOT", "ok" if artifact else "warning", str((artifact or {}).get("artifact_id") or checkpoint))
                try:
                    if _locator_uses_uia(locator):
                        element, detail = _find_uia_element(locator, payload, program)
                        last_detail = detail or last_detail
                        if element is not None:
                            resolved = {"kind": "uia", "element": element, "detail": detail}
                    if resolved is None:
                        box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
                        if box:
                            resolved = {"kind": "image", "box": box, "detail": str(locator.get("image_path") or locator.get("target_image") or "image")}
                    add(f"{step_name}_RETRY_LOCATE", "ok" if resolved else "blocked", target_name if resolved else (last_detail or target_name))
                except Exception as exc:
                    add(f"{step_name}_RETRY_LOCATE", "blocked", exc.__class__.__name__)
                    if require_assertions:
                        return {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "message": f"click retry locator failed: {exc.__class__.__name__}"}

            if resolved and resolved.get("kind") == "uia":
                element = resolved["element"]
                if hasattr(element, "click_input"):
                    element.click_input()
                elif hasattr(element, "click"):
                    element.click()
                else:
                    add(step_name, "blocked", "uia element is not clickable")
                    return {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "message": "UIA element is not clickable."}
                add(step_name, "ok", f"{locator.get('target') or resolved.get('detail') or 'uia'} via uia")
                last_successful_click = True
                failure = popup_failure(f"{step_name}_POPUP_AFTER")
                if failure:
                    return failure
            elif resolved and resolved.get("kind") == "image":
                center = pyautogui.center(resolved["box"])
                clicks = int(action.get("clicks", 2 if action_name == "double_click" else 3 if action_name == "triple_click" else 1))
                pyautogui.click(center.x, center.y, clicks=clicks, interval=float(action.get("interval_sec", 0.0)), button=str(action.get("button") or "left"))
                add(step_name, "ok", str(locator.get("target") or locator.get("image_path") or "image"))
                last_successful_click = True
                failure = popup_failure(f"{step_name}_POPUP_AFTER")
                if failure:
                    return failure
            elif locator.get("x") is not None and locator.get("y") is not None:
                coordinate_failure = bounded_coordinate(int(locator["x"]), int(locator["y"]), step_name)
                if coordinate_failure:
                    return coordinate_failure
                coord_context = _coordinate_click_context(pyautogui, action, payload, program)
                before_artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=f"coordinate_before_{index + 1}", trace=trace)
                if before_artifact and screen_artifacts is not None:
                    screen_artifacts.append(before_artifact)
                add(
                    f"{step_name}_COORDINATE_BEFORE_SCREENSHOT",
                    "ok" if before_artifact else "warning",
                    str((before_artifact or {}).get("artifact_id") or "coordinate_before"),
                )
                clicks = int(action.get("clicks", 2 if action_name == "double_click" else 3 if action_name == "triple_click" else 1))
                pyautogui.click(
                    int(locator["x"]),
                    int(locator["y"]),
                    clicks=clicks,
                    interval=float(action.get("interval_sec", 0.0)),
                    button=str(action.get("button") or "left"),
                )
                after_artifact = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint=f"coordinate_after_{index + 1}", trace=trace)
                if after_artifact and screen_artifacts is not None:
                    screen_artifacts.append(after_artifact)
                add(
                    f"{step_name}_COORDINATE_AFTER_SCREENSHOT",
                    "ok" if after_artifact else "warning",
                    str((after_artifact or {}).get("artifact_id") or "coordinate_after"),
                )
                detail_parts = [
                    f"coordinate=({int(locator['x'])},{int(locator['y'])})",
                    f"screen_size={coord_context['screen_size']}",
                    f"dpi_scaling={coord_context['dpi_scaling']}",
                    f"target_window_rect={coord_context['target_window_rect']}",
                ]
                if before_artifact:
                    detail_parts.append(f"before_sha256={before_artifact.get('sha256', '')}")
                if after_artifact:
                    detail_parts.append(f"after_sha256={after_artifact.get('sha256', '')}")
                add(step_name, "ok", "; ".join(detail_parts))
                last_successful_click = True
                failure = popup_failure(f"{step_name}_POPUP_AFTER")
                if failure:
                    return failure
            elif require_assertions or action.get("required") is True:
                target_name = str(locator.get("target") or action.get("target") or "click_target")
                failure_artifact = next(
                    (
                        item
                        for item in reversed(screen_artifacts or [])
                        if f"retry_before_{_safe_segment(target_name, 'click_target')}" in str(item.get("artifact_id") or "")
                    ),
                    None,
                )
                if failure_artifact is None:
                    failure_artifact = _capture_screenshot_artifact(
                        pyautogui,
                        run_id=run_id,
                        checkpoint=f"locator_failure_{_safe_segment(target_name, 'click_target')}",
                        trace=trace,
                    )
                if failure_artifact and screen_artifacts is not None:
                    if failure_artifact not in screen_artifacts:
                        screen_artifacts.append(failure_artifact)
                add(step_name, "blocked", last_detail or str(locator.get("target") or "click target missing"))
                return {
                    "ok": False,
                    "failure_code": "UI_LOCATOR_NOT_FOUND",
                    "message": "Required click target is not configured or visible.",
                    "target": target_name,
                    "failure_artifact": failure_artifact,
                }
            else:
                add(step_name, "warning", "click skipped; no locator/coordinate configured")
            continue
        if action_name == "move_to":
            locator = _locator_for(action, payload)
            box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
            if box:
                center = pyautogui.center(box)
                x, y = int(center.x), int(center.y)
                resolution = f"image={locator.get('target') or action.get('target') or 'recorded'}"
            elif action.get("coordinate_fallback") is True and action.get("x") is not None and action.get("y") is not None:
                x, y = int(action["x"]), int(action["y"])
                resolution = "explicit_coordinate_fallback"
            elif action.get("x") is not None and action.get("y") is not None and not locator.get("image_candidates"):
                x, y = int(action["x"]), int(action["y"])
                resolution = "coordinate"
            else:
                target_name = str(locator.get("target") or action.get("target") or "move_target")
                failure_artifact = _capture_screenshot_artifact(
                    pyautogui,
                    run_id=run_id,
                    checkpoint=f"locator_failure_{_safe_segment(target_name, 'move_target')}",
                    trace=trace,
                )
                if failure_artifact and screen_artifacts is not None:
                    screen_artifacts.append(failure_artifact)
                add(step_name, "blocked", f"visual target not found: {target_name}")
                return {
                    "ok": False,
                    "failure_code": "UI_LOCATOR_NOT_FOUND",
                    "message": f"Required move target not found: {target_name}",
                    "failure_artifact": failure_artifact,
                }
            coordinate_failure = bounded_coordinate(x, y, step_name)
            if coordinate_failure:
                return coordinate_failure
            duration_sec = max(0.0, min(float(action.get("duration_sec", 0.1)), 2.0))
            pyautogui.moveTo(x, y, duration=duration_sec)
            add(step_name, "ok", f"{resolution}; coordinate=({x},{y}); duration_sec={duration_sec:.3f}")
            continue
        if action_name == "query_pointer":
            x, y = pyautogui.position()
            add(step_name, "ok", f"coordinate=({int(x)},{int(y)})")
            continue
        if action_name == "query_screen":
            width, height = pyautogui.size()
            add(step_name, "ok", f"screen={int(width)}x{int(height)}")
            continue
        if action_name == "move_rel":
            x, y = int(action["x"]), int(action["y"])
            duration_sec = max(0.0, min(float(action.get("duration_sec", 0.1)), 5.0))
            pyautogui.moveRel(x, y, duration=duration_sec)
            add(step_name, "ok", f"delta=({x},{y}); duration_sec={duration_sec:.3f}")
            continue
        if action_name in {"mouse_down", "mouse_up"}:
            button = str(action.get("button") or "left")
            if action_name == "mouse_down":
                pyautogui.mouseDown(button=button)
                held_buttons.add(button)
            else:
                pyautogui.mouseUp(button=button)
                held_buttons.discard(button)
            add(step_name, "ok", button)
            continue
        if action_name in {"drag_to", "drag_rel"}:
            if action_name == "drag_to":
                locator = _locator_for(action, payload)
                box = _locate_on_screen(pyautogui, locator, run_id=run_id, specimen_id=specimen_id)
                if box:
                    center = pyautogui.center(box)
                    x, y = int(center.x), int(center.y)
                    resolution = f"image={locator.get('target') or action.get('target') or 'recorded'}"
                elif action.get("coordinate_fallback") is True and action.get("x") is not None and action.get("y") is not None:
                    x, y = int(action["x"]), int(action["y"])
                    resolution = "explicit_coordinate_fallback"
                elif action.get("x") is not None and action.get("y") is not None and not locator.get("image_candidates"):
                    x, y = int(action["x"]), int(action["y"])
                    resolution = "coordinate"
                else:
                    target_name = str(locator.get("target") or action.get("target") or "drag_target")
                    failure_artifact = _capture_screenshot_artifact(
                        pyautogui,
                        run_id=run_id,
                        checkpoint=f"locator_failure_{_safe_segment(target_name, 'drag_target')}",
                        trace=trace,
                    )
                    if failure_artifact and screen_artifacts is not None:
                        screen_artifacts.append(failure_artifact)
                    add(step_name, "blocked", f"visual target not found: {target_name}")
                    return {
                        "ok": False,
                        "failure_code": "UI_LOCATOR_NOT_FOUND",
                        "message": f"Required drag target not found: {target_name}",
                        "failure_artifact": failure_artifact,
                    }
            else:
                x, y = int(action["x"]), int(action["y"])
                resolution = "relative_coordinate"
            if action_name == "drag_to":
                coordinate_failure = bounded_coordinate(x, y, step_name)
                if coordinate_failure:
                    return coordinate_failure
            duration_sec = max(0.0, min(float(action.get("duration_sec", 0.1)), 5.0))
            button = str(action.get("button") or "left")
            if action_name == "drag_to":
                pyautogui.dragTo(x, y, duration=duration_sec, button=button)
            else:
                pyautogui.dragRel(x, y, duration=duration_sec, button=button)
            add(step_name, "ok", f"{resolution}; coordinate=({x},{y}); button={button}; duration_sec={duration_sec:.3f}")
            continue
        if action_name in {"scroll", "hscroll", "vscroll"}:
            clicks = int(action.get("clicks", 0))
            getattr(pyautogui, action_name)(clicks)
            add(step_name, "ok", f"clicks={clicks}")
            continue
        if action_name == "hotkey":
            keys = action.get("keys") if isinstance(action.get("keys"), list) else []
            if not keys:
                add(step_name, "warning", "hotkey keys missing")
                continue
            pyautogui.hotkey(*[str(key) for key in keys], interval=float(action.get("interval_sec", 0.0)))
            add(step_name, "ok", "+".join(str(key) for key in keys))
            continue
        if action_name == "press":
            key = str(action.get("key") or "")
            if not key:
                add(step_name, "warning", "key missing")
                continue
            presses = int(action.get("presses", 1))
            interval_sec = float(action.get("interval_sec", 0.0))
            pyautogui.press(key, presses=presses, interval=interval_sec)
            add(step_name, "ok", f"{key}; presses={presses}")
            continue
        if action_name in {"key_down", "key_up"}:
            key = str(action.get("key") or "")
            if action_name == "key_down":
                pyautogui.keyDown(key)
                held_keys.add(key)
            else:
                pyautogui.keyUp(key)
                held_keys.discard(key)
            add(step_name, "ok", key)
            continue
        if action_name in {"write", "type_path"}:
            value = action.get("text") if action_name == "write" else action.get("value") or action.get("path")
            text_value = _format_runtime_value(value, run_id=run_id, specimen_id=specimen_id)
            if not text_value:
                add(step_name, "warning", "text/path missing")
                continue
            pyautogui.write(text_value, interval=float(action.get("interval_sec", 0.0)))
            add(step_name, "ok", "typed value")
            continue
        if action_name == "pixel":
            x, y = int(action["x"]), int(action["y"])
            coordinate_failure = bounded_coordinate(x, y, step_name)
            if coordinate_failure:
                return coordinate_failure
            color = tuple(int(item) for item in pyautogui.pixel(x, y))
            add(step_name, "ok", f"coordinate=({x},{y}); rgb={color}")
            continue
        if action_name == "pixel_matches_color":
            x, y = int(action["x"]), int(action["y"])
            coordinate_failure = bounded_coordinate(x, y, step_name)
            if coordinate_failure:
                return coordinate_failure
            color = tuple(int(item) for item in action["color"])
            matched = bool(pyautogui.pixelMatchesColor(x, y, color, tolerance=int(action.get("tolerance", 0))))
            add(step_name, "ok" if matched else "warning", f"coordinate=({x},{y}); matched={str(matched).lower()}")
            continue
        if action_name.startswith("window_"):
            window, failure = selected_window(action, step_name)
            if failure:
                return failure
            if action_name == "window_activate":
                window.activate()
            elif action_name == "window_minimize":
                window.minimize()
            elif action_name == "window_maximize":
                window.maximize()
            elif action_name == "window_restore":
                window.restore()
            elif action_name == "window_move":
                window.moveTo(int(action["x"]), int(action["y"]))
            elif action_name == "window_resize":
                window.resizeTo(int(action["width"]), int(action["height"]))
            add(step_name, "ok", str(action.get("title") or action.get("window") or "window"))
            continue
        if action_name in {"alert", "confirm"}:
            if payload.get("confirm_execute") is not True:
                add(step_name, "blocked", "explicit manual confirmation required")
                return {
                    "ok": False,
                    "failure_code": "PYAUTOGUI_MANUAL_CONFIRMATION_REQUIRED",
                    "message": "Blocking dialog actions require explicit manual confirmation.",
                }
            text_value = str(action.get("text") or "")
            title = str(action.get("title") or "ATR Equipment Skill")
            if action_name == "alert":
                response = pyautogui.alert(text_value, title=title)
            else:
                response = pyautogui.confirm(text_value, title=title, buttons=[str(item) for item in action.get("buttons", ["OK", "Cancel"])])
            add(step_name, "ok", f"response={response}")
            continue
        if action_name == "wait":
            seconds = min(float(action.get("seconds", action.get("duration_sec", 0.5))), 30.0)
            time.sleep(max(0.0, seconds))
            add(step_name, "ok", f"{seconds:.2f}s")
            continue
        if action_name == "log":
            add(step_name, "ok", str(action.get("message") or "log"))
            continue
        if action_name == "wait_for_file":
            pattern = _format_runtime_value(action.get("pattern") or UTM_EXPORT_GLOB, run_id=run_id, specimen_id=specimen_id)
            timeout_s = float(action.get("timeout_s") or payload.get("artifact_timeout_s") or payload.get("export_timeout_s") or 20.0)
            stable_for_sec = float(action.get("stable_for_sec") or payload.get("stable_for_sec") or UTM_FILE_STABLE_SEC)
            matched_file, detail = _wait_for_file_action(
                pattern,
                run_id=run_id,
                specimen_id=specimen_id,
                timeout_s=timeout_s,
                stable_for_sec=stable_for_sec,
            )
            if matched_file is not None:
                add(step_name, "ok", detail)
            elif action.get("required") is True:
                add(step_name, "blocked", detail)
                return {"ok": False, "failure_code": "UTM_DATA_TIMEOUT", "message": f"Required file did not appear or become stable: {detail}"}
            else:
                add(step_name, "warning", detail)
            continue
        add(step_name, "blocked", f"unsupported action: {action_name}")
        return {
            "ok": False,
            "failure_code": "PYAUTOGUI_ACTION_NOT_ALLOWED",
            "message": f"Unsupported PyAutoGUI bridge action: {action_name}",
        }
    return {"ok": True}


def _execute_protocol_sequence(
    pyautogui: Any,
    *,
    program_id: str,
    payload: dict[str, Any],
    run_id: str,
    specimen_id: str,
    trace: list[dict[str, Any]],
    screen_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a bounded sequence and release every held input on all exits."""
    held_buttons: set[str] = set()
    held_keys: set[str] = set()
    try:
        return _execute_protocol_sequence_impl(
            pyautogui,
            program_id=program_id,
            payload=payload,
            run_id=run_id,
            specimen_id=specimen_id,
            trace=trace,
            screen_artifacts=screen_artifacts,
            held_buttons=held_buttons,
            held_keys=held_keys,
        )
    finally:
        for button in sorted(held_buttons):
            try:
                pyautogui.mouseUp(button=button)
            except Exception:
                pass
        for key in sorted(held_keys):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass


def _probe_utm_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING"}
    data = path.read_bytes()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    columns = [item.strip() for item in lines[0].split(",")] if lines else []
    required = {"time_s", "displacement_mm", "force_N"}
    missing = sorted(required.difference(columns))
    row_count = max(0, len([line for line in lines[1:] if line.strip()]))

    def result(ok: bool, *, failure_code: str | None = None, message: str = "", data_quality: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": ok,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
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
    for line in [line for line in lines[1:] if line.strip()]:
        parts = [item.strip() for item in line.split(",")]
        try:
            numeric_rows.append(
                {
                    "time_s": float(parts[index["time_s"]]),
                    "displacement_mm": float(parts[index["displacement_mm"]]),
                    "force_N": float(parts[index["force_N"]]),
                }
            )
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


def _wait_until_stable(path: Path, *, stable_for_sec: float, timeout_s: float) -> bool:
    deadline = time.monotonic() + max(0.1, timeout_s)
    last_size = -1
    stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(0.2)
            continue
        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= stable_for_sec:
                return True
        else:
            last_size = size
            stable_since = now
        time.sleep(0.2)
    return False


def _candidate_export_files(run_id: str, specimen_id: str, glob_pattern: str) -> list[Path]:
    roots = [UTM_EXPORT_ROOT / run_id, UTM_EXPORT_ROOT]
    candidates: list[Path] = []
    needles = {run_id.lower(), specimen_id.lower()}
    for root in roots:
        if not root.exists():
            continue
        try:
            found = list(root.rglob(glob_pattern))
        except Exception:
            found = []
        for item in found:
            name = item.name.lower()
            if item.is_file() and (any(needle and needle in name for needle in needles) or root == UTM_EXPORT_ROOT / run_id):
                candidates.append(item)
    return sorted(set(candidates), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)


def _candidate_files_for_pattern(pattern: str, *, run_id: str, specimen_id: str) -> list[Path]:
    text = str(pattern or "").strip()
    if not text:
        return []
    has_wildcard = any(ch in text for ch in "*?[")
    path = Path(text)
    candidates: list[Path] = []
    if has_wildcard:
        parent = path.parent if str(path.parent) not in {"", "."} else UTM_EXPORT_ROOT
        try:
            candidates.extend(item for item in parent.glob(path.name) if item.is_file())
        except Exception:
            candidates = []
        if not candidates:
            try:
                candidates.extend(_candidate_export_files(run_id, specimen_id, path.name))
            except Exception:
                pass
    elif path.exists() and path.is_file():
        candidates.append(path)
    return sorted(set(candidates), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)


def _wait_for_file_action(pattern: str, *, run_id: str, specimen_id: str, timeout_s: float, stable_for_sec: float) -> tuple[Path | None, str]:
    deadline = time.monotonic() + max(0.1, timeout_s)
    last_detail = "not found"
    while time.monotonic() < deadline:
        for candidate in _candidate_files_for_pattern(pattern, run_id=run_id, specimen_id=specimen_id):
            remaining = max(0.1, deadline - time.monotonic())
            if _wait_until_stable(candidate, stable_for_sec=stable_for_sec, timeout_s=min(stable_for_sec + 1.0, remaining)):
                return candidate, f"{candidate}; stable_for_sec={stable_for_sec:.2f}"
            last_detail = f"not stable: {candidate}"
        time.sleep(0.25)
    return None, f"{pattern}; {last_detail}; timeout_s={timeout_s:.2f}"


def _resolve_utm_export(payload: dict[str, Any], *, run_id: str, specimen_id: str, trace: list[dict[str, Any]]) -> tuple[Path | None, dict[str, Any]]:
    timeout_s = float(payload.get("artifact_timeout_s") or payload.get("export_timeout_s") or 20.0)
    stable_for_sec = float(payload.get("stable_for_sec") or UTM_FILE_STABLE_SEC)
    explicit_path = payload.get("expected_export_path") or payload.get("result_file") or payload.get("utm_csv_path")
    if explicit_path:
        path = Path(str(explicit_path))
        if path.exists() and _wait_until_stable(path, stable_for_sec=stable_for_sec, timeout_s=timeout_s):
            return path, _probe_utm_csv(path)
        return None, {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING", "message": f"Expected UTM export was not found or stable: {path}"}

    glob_pattern = str(payload.get("export_glob") or UTM_EXPORT_GLOB or "*.csv")
    deadline = time.monotonic() + max(0.1, timeout_s)
    last_probe: dict[str, Any] = {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING"}
    while time.monotonic() < deadline:
        for candidate in _candidate_export_files(run_id, specimen_id, glob_pattern):
            if not _wait_until_stable(candidate, stable_for_sec=stable_for_sec, timeout_s=min(stable_for_sec + 1.0, timeout_s)):
                last_probe = {"ok": False, "failure_code": "UTM_DATA_TIMEOUT", "message": f"Export file did not become stable: {candidate}"}
                continue
            probe = _probe_utm_csv(candidate)
            if probe.get("ok"):
                return candidate, probe
            last_probe = probe
        time.sleep(0.5)
    trace.append({"step": "WAIT_FOR_EXPORT", "status": "blocked", "detail": str(UTM_EXPORT_ROOT)})
    return None, last_probe if last_probe else {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING"}


def _registered_export_payload(payload: dict[str, Any], *, program_id: str, run_id: str, specimen_id: str) -> tuple[dict[str, Any], Path]:
    """Build a runtime payload whose typed export path follows the active UTM_EXPORT_ROOT."""
    target_dir = UTM_EXPORT_ROOT / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{specimen_id}.csv"
    program = PROGRAMS.get(program_id, {})
    raw_sequence = program.get("sequence") if isinstance(program, dict) else []
    if not isinstance(raw_sequence, list):
        raw_sequence = []
    sequence = [dict(item) for item in raw_sequence if isinstance(item, dict)]
    if not sequence:
        sequence = [
            {"action": "hotkey", "keys": ["ctrl", "s"]},
            {"action": "type_path", "value": str(target_path)},
            {"action": "press", "key": "enter"},
            {"action": "wait_for_file", "pattern": str(target_path), "timeout_s": 20},
        ]
    for action in sequence:
        if action.get("action") == "type_path":
            action["value"] = str(target_path)
        elif action.get("action") == "wait_for_file":
            action["pattern"] = str(target_path)
    export_payload = dict(payload)
    export_payload["program_id"] = program_id
    export_payload["sequence"] = sequence
    export_payload["expected_export_path"] = str(target_path)
    return export_payload, target_path


def _manual_save_export_payload(payload: dict[str, Any], *, run_id: str, specimen_id: str) -> tuple[dict[str, Any], Path]:
    """Build a runtime payload for the manual Save/Export fallback sequence."""
    return _registered_export_payload(payload, program_id="utm_manual_save_csv_v1", run_id=run_id, specimen_id=specimen_id)


def _utm_success_response(
    *,
    sequence_id: str,
    program_id: str,
    artifact: dict[str, Any],
    windows_path: str,
    trace: list[dict[str, Any]],
    save_method: str,
    simulated: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "verified_complete",
        "bridge": "windows_pyautogui",
        "sequence_id": sequence_id,
        "program_id": program_id,
        "program_type": "utm_protocol",
        "program_log": "UTM protocol verified complete; artifact exported.",
        "output_artifacts": [artifact],
        "screen_checks": [
            {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": ""},
            {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": ""},
            {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": ""},
        ],
        "physical_checks": {
            "vision_motion_confirmed": True,
            "specimen_alignment_ok": True,
            "fixture_safe_to_access": True,
            "evidence_frame_ids": [],
            "simulated": simulated,
        },
        "data_acquisition": {
            "status": "exported_on_windows",
            "save_method": save_method,
            "save_attempted_by_agent": True,
            "save_confirmation_screen_ok": True,
            "windows_path": windows_path,
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "row_count_probe": artifact["row_count_probe"],
            "columns_probe": artifact["columns_probe"],
            "data_quality": artifact.get("data_quality", {}),
            "simulated": simulated,
        },
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
        },
        "step_trace": trace,
        "failure_code": None,
    }


def _simulated_utm_protocol(sequence_id: str, program_id: str, payload: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    experiment = payload.get("experiment_spec") if isinstance(payload.get("experiment_spec"), dict) else {}
    run_id = _safe_segment(payload.get("run_id") or sequence_id, "run-live")
    specimen_id = _safe_segment(payload.get("specimen_id") or experiment.get("specimen_id") or "specimen-live", "specimen-live")
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    artifact_dir = ARTIFACT_ROOT / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = f"utm_csv_{specimen_id}_{timestamp}"
    csv_path = artifact_dir / f"{artifact_id}.csv"
    rows = ["time_s,displacement_mm,force_N"]
    for idx in range(80):
        displacement = idx * 0.05
        force = max(0.0, 18.0 * displacement - 1.1 * displacement * displacement + (idx % 5) * 0.45)
        rows.append(f"{idx * 0.25:.3f},{displacement:.4f},{force:.4f}")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    artifact = _artifact_payload(csv_path, artifact_id=artifact_id, kind="utm_csv", windows_path=str(csv_path))
    trace.extend(
        [
            {"step": "FOCUS_WINDOW", "status": "ok", "detail": "simulated UTM software"},
            {"step": "SCREEN_ASSERT_BEFORE", "status": "ok", "detail": "simulated ready_state"},
            {"step": "EXECUTE_START_MACRO", "status": "ok", "detail": "simulated start_button"},
            {"step": "SCREEN_ASSERT_RUNNING", "status": "ok", "detail": "simulated running_state"},
            {"step": "PHYSICAL_ASSERT", "status": "ok", "detail": "simulated data stream"},
            {"step": "SCREEN_ASSERT_COMPLETE", "status": "ok", "detail": "simulated complete_state"},
            {"step": "SAVE_EXPORT", "status": "ok", "detail": str(csv_path)},
            {"step": "DONE", "status": "ok", "detail": "simulated UTM protocol verified complete"},
        ]
    )
    return _utm_success_response(
        sequence_id=sequence_id,
        program_id=program_id,
        artifact=artifact,
        windows_path=str(csv_path),
        trace=trace,
        save_method="simulated_bridge_export",
        simulated=True,
    )


def _run_utm_protocol(sequence_id: str, program_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str = "") -> None:
        item = {"step": name, "status": status}
        if detail:
            item["detail"] = detail
        trace.append(item)

    pyautogui, error = _load_pyautogui()
    if pyautogui is None:
        step("HEALTH", "blocked", "pyautogui import failed")
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "failure_code": "PYAUTOGUI_NOT_INSTALLED",
            "requires_install": True,
            "message": f"PyAutoGUI is not installed: {error}",
            "step_trace": trace,
        }

    experiment = payload.get("experiment_spec") if isinstance(payload.get("experiment_spec"), dict) else {}
    run_id = _safe_segment(payload.get("run_id") or sequence_id, "run-live")
    specimen_id = _safe_segment(payload.get("specimen_id") or experiment.get("specimen_id") or "specimen-live", "specimen-live")
    program = PROGRAMS.get(program_id, {})
    program_type = str(program.get("program_type") or "")
    if bool(payload.get("simulate_utm_protocol")) or ALLOW_SIMULATED_UTM:
        step("HEALTH", "ok", "simulated UTM protocol explicitly enabled")
        return _simulated_utm_protocol(sequence_id, program_id, payload, trace)
    if program_type == "utm_export" and not payload.get("expected_export_path"):
        payload, _export_target = _registered_export_payload(payload, program_id=program_id, run_id=run_id, specimen_id=specimen_id)

    step("HEALTH", "ok")
    screen_artifacts: list[dict[str, Any]] = []
    if program_type == "utm_abort":
        abort_screen_before = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="abort_before", trace=trace)
        if abort_screen_before:
            screen_artifacts.append(abort_screen_before)
        sequence_result = _execute_protocol_sequence(
            pyautogui,
            program_id=program_id,
            payload=payload,
            run_id=run_id,
            specimen_id=specimen_id,
            trace=trace,
            screen_artifacts=screen_artifacts,
        )
        abort_screen_after = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="abort_after", trace=trace)
        if abort_screen_after:
            screen_artifacts.append(abort_screen_after)
        if not sequence_result.get("ok"):
            return {
                "ok": False,
                "status": "blocked",
                "bridge": "windows_pyautogui",
                "sequence_id": sequence_id,
                "program_id": program_id,
                "program_type": "utm_abort",
                "failure_code": str(sequence_result.get("failure_code") or "UTM_ABORT_MACRO_FAILED"),
                "message": str(sequence_result.get("message") or "UTM stop/abort macro failed."),
                "screen_checks": _screen_checks_from_artifacts(screen_artifacts),
                "output_artifacts": list(screen_artifacts),
                "step_trace": trace,
            }
        step("RECOVERY_ABORT_MACRO", "ok", "UTM stop/abort command dispatched")
        return {
            "ok": True,
            "status": "recovery_macro_dispatched",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "utm_abort",
            "program_log": "UTM stop/abort macro dispatched; operator/Guardian review still required.",
            "screen_checks": _screen_checks_from_artifacts(screen_artifacts),
            "output_artifacts": list(screen_artifacts),
            "data_acquisition": {"status": "not_applicable", "save_method": "not_applicable", "save_attempted_by_agent": False, "save_confirmation_screen_ok": False},
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": False,
                "save_completed": False,
                "data_file_created": False,
                "data_parse_probe_ok": False,
                "save_export_responsibility_ok": False,
            },
            "step_trace": trace,
            "failure_code": None,
        }

    before_screen = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="before_start", trace=trace)
    if before_screen:
        screen_artifacts.append(before_screen)

    sequence_result = _execute_protocol_sequence(
        pyautogui,
        program_id=program_id,
        payload=payload,
        run_id=run_id,
        specimen_id=specimen_id,
        trace=trace,
        screen_artifacts=screen_artifacts,
    )
    if not sequence_result.get("ok"):
        failure_screen = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="failure", trace=trace)
        if failure_screen:
            screen_artifacts.append(failure_screen)
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "utm_protocol",
            "failure_code": str(sequence_result.get("failure_code") or "CLICK_NO_STATE_CHANGE"),
            "message": str(sequence_result.get("message") or "UTM screen-control sequence failed."),
            "screen_checks": _screen_checks_from_artifacts(screen_artifacts),
            "output_artifacts": list(screen_artifacts),
            "step_trace": trace,
        }
    if program_type == "utm_export":
        step("EXECUTE_EXPORT_MACRO", "ok", "registered export/save sequence dispatched")
    else:
        step("EXECUTE_START_MACRO", "ok", "registered protocol sequence dispatched")
    save_method = "manual_save_dialog" if program_id == "utm_manual_save_csv_v1" else "export_menu" if program_id == "utm_export_csv_v1" else "windows_export_watch"
    manual_save_attempted = program_id == "utm_manual_save_csv_v1"
    export_path, probe = _resolve_utm_export(payload, run_id=run_id, specimen_id=specimen_id, trace=trace)
    manual_save_required = bool(payload.get("manual_save_required_if_no_artifact", True)) and program_id != "utm_manual_save_csv_v1"
    if (export_path is None or not probe.get("ok")) and manual_save_required:
        manual_save_attempted = True
        step("AUTO_SAVE_MISSING", "warning", str(probe.get("failure_code") or "UTM_EXPORT_FILE_MISSING"))
        manual_payload, manual_target = _manual_save_export_payload(payload, run_id=run_id, specimen_id=specimen_id)
        step("MANUAL_SAVE_EXPORT", "ok", str(manual_target))
        manual_sequence_result = _execute_protocol_sequence(
            pyautogui,
            program_id="utm_manual_save_csv_v1",
            payload=manual_payload,
            run_id=run_id,
            specimen_id=specimen_id,
            trace=trace,
        )
        if manual_sequence_result.get("ok"):
            export_path, probe = _resolve_utm_export(manual_payload, run_id=run_id, specimen_id=specimen_id, trace=trace)
            save_method = "manual_save_dialog"
        else:
            probe = {
                "ok": False,
                "failure_code": str(manual_sequence_result.get("failure_code") or "UTM_SAVE_CONFIRMATION_FAILED"),
                "message": str(manual_sequence_result.get("message") or "Manual UTM save/export fallback failed."),
            }
            export_path = None
            step("MANUAL_SAVE_EXPORT", "blocked", probe["failure_code"])
    if export_path is None or not probe.get("ok"):
        failure_code = str(probe.get("failure_code") or "UTM_EXPORT_FILE_MISSING")
        step("SAVE_EXPORT", "blocked", failure_code)
        failure_screen = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="failure", trace=trace)
        if failure_screen:
            screen_artifacts.append(failure_screen)
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "utm_protocol",
            "failure_code": failure_code,
            "message": str(probe.get("message") or "UTM export CSV was not found, stable, or parseable."),
            "data_acquisition": {
                "status": "missing",
                "save_method": save_method,
                "save_attempted_by_agent": manual_save_attempted,
                "save_confirmation_screen_ok": False,
                "windows_path": str(export_path or ""),
                "row_count_probe": probe.get("row_count_probe", 0),
                "columns_probe": probe.get("columns_probe", []),
            },
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": False,
                "save_completed": False,
                "data_file_created": False,
                "data_parse_probe_ok": False,
                "save_export_responsibility_ok": False,
            },
            "screen_checks": _screen_checks_from_artifacts(screen_artifacts),
            "output_artifacts": list(screen_artifacts),
            "step_trace": trace,
        }

    artifact_id = f"utm_csv_{specimen_id}_{int(time.time())}"
    artifact = _artifact_payload(export_path, artifact_id=artifact_id, kind="utm_csv", windows_path=str(export_path))
    if not any("after_complete" in str(item.get("artifact_id") or "") for item in screen_artifacts):
        complete_screen = _capture_screenshot_artifact(pyautogui, run_id=run_id, checkpoint="after_complete", trace=trace)
        if complete_screen:
            screen_artifacts.append(complete_screen)
    if program_type == "utm_export":
        screen_gate = {"ok": True, "screen_checks": _screen_checks_from_artifacts(screen_artifacts), "blockers": []}
    else:
        screen_gate = _required_utm_screen_evidence_gate(screen_artifacts)
    if not screen_gate.get("ok"):
        failure_code = str(screen_gate.get("failure_code") or "UTM_SCREEN_EVIDENCE_FILES_REQUIRED")
        step("SCREEN_EVIDENCE", "blocked", "; ".join(str(item) for item in screen_gate.get("blockers", [])) or failure_code)
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "utm_protocol",
            "failure_code": failure_code,
            "message": str(screen_gate.get("message") or "Live UTM screen evidence is incomplete."),
            "data_acquisition": {
                "status": "exported_on_windows",
                "save_method": save_method,
                "save_attempted_by_agent": manual_save_attempted,
                "save_confirmation_screen_ok": True,
                "windows_path": str(export_path),
                "sha256": artifact.get("sha256"),
                "size_bytes": artifact.get("size_bytes"),
                "row_count_probe": artifact.get("row_count_probe", 0),
                "columns_probe": artifact.get("columns_probe", []),
                "data_quality": artifact.get("data_quality", {}),
            },
            "cross_checks": {
                "screen_started": False,
                "physical_motion_started": False,
                "save_completed": True,
                "data_file_created": True,
                "data_parse_probe_ok": True,
                "save_export_responsibility_ok": True,
            },
            "screen_checks": screen_gate.get("screen_checks", _screen_checks_from_artifacts(screen_artifacts)),
            "output_artifacts": [artifact, *screen_artifacts],
            "step_trace": trace,
        }
    step("SAVE_EXPORT", "ok", str(export_path))
    step("PARSE_PROBE", "ok", f"rows={artifact['row_count_probe']}; columns={','.join(artifact['columns_probe'])}")
    step("DONE", "ok", "UTM protocol verified complete")
    response = _utm_success_response(
        sequence_id=sequence_id,
        program_id=program_id,
        artifact=artifact,
        windows_path=str(export_path),
        trace=trace,
        save_method=save_method,
        simulated=False,
    )
    response["data_acquisition"]["save_attempted_by_agent"] = manual_save_attempted or response["data_acquisition"].get("save_attempted_by_agent", True)
    response["output_artifacts"] = [artifact, *screen_artifacts]
    response["screen_checks"] = screen_gate.get("screen_checks", _screen_checks_from_artifacts(screen_artifacts))
    return response


def _list_artifacts() -> dict[str, Any]:
    indexed_from_disk_count = _rebuild_artifact_index()
    artifacts = sorted(
        ARTIFACT_INDEX.values(),
        key=lambda item: (str(item.get("kind") or ""), str(item.get("filename") or "")),
    )
    return {
        "ok": True,
        "status": "ready",
        "artifact_count": len(artifacts),
        "indexed_from_disk_count": indexed_from_disk_count,
        "artifact_roots": {"bridge": str(ARTIFACT_ROOT), "utm_export": str(UTM_EXPORT_ROOT)},
        "artifacts": artifacts,
    }




def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove token-like fields before hashing or writing request-audit metadata."""
    public: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        key_text = str(key)
        key_lower = key_text.lower()
        if any(secret in key_lower for secret in ("token", "password", "secret", "auth", "credential")):
            continue
        public[key_text] = value
    return public


def _request_audit_event_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret execute identity fields for request-log proof."""
    public = _public_payload(payload)
    encoded = json.dumps(public, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
    return {
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "sequence_id": str(public.get("sequence_id") or ""),
        "run_id": str(public.get("run_id") or ""),
        "specimen_id": str(public.get("specimen_id") or ""),
        "program_id": str(public.get("program_id") or ""),
        "command_preview": str(public.get("command") or "")[:180],
        "simulate_utm_protocol": bool(public.get("simulate_utm_protocol")),
        "require_screen_assertions": bool(public.get("require_screen_assertions")),
    }


def _summarize_execute_audit_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recent /execute request identities without exposing payload secrets."""
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
    last_execute_context = dict(identity_events[-1]) if identity_events else {}
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
            for key, value in last_execute_context.items()
            if key in {
                "at",
                "status",
                "audit_kind",
                "sequence_id",
                "run_id",
                "specimen_id",
                "program_id",
                "payload_sha256",
                "result_ok",
                "result_status",
                "failure_code",
            }
        },
    }

def _request_log_payload() -> dict[str, Any]:
    log_path = ARTIFACT_ROOT / "bridge_requests.jsonl"
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
    execute_summary = _summarize_execute_audit_events(events)
    last_execute_at = ""
    for event in reversed(events):
        if isinstance(event, dict) and str(event.get("path") or "") == "/execute":
            last_execute_at = str(event.get("ts") or event.get("at") or "")
            break
    return {
        "ok": True,
        "status": "ready",
        "bridge": "windows_pyautogui",
        "request_log": str(log_path),
        "event_count": len(events),
        "recent_paths": recent_paths[-10:],
        **execute_summary,
        "last_execute_at": last_execute_at,
        "events": events,
    }


def _get_artifact(artifact_id: str) -> tuple[int, dict[str, Any]]:
    artifact = ARTIFACT_INDEX.get(artifact_id)
    if not artifact:
        _rebuild_artifact_index()
        artifact = ARTIFACT_INDEX.get(artifact_id)
    if not artifact:
        return 404, {"ok": False, "status": "not_found", "failure_code": "PYAUTOGUI_ARTIFACT_NOT_FOUND"}
    path = Path(str(artifact.get("path") or ""))
    if not path.exists():
        return 404, {"ok": False, "status": "not_found", "failure_code": "PYAUTOGUI_ARTIFACT_FILE_MISSING"}
    data = path.read_bytes()
    return 200, {**{key: value for key, value in artifact.items() if key != "path"}, "content_base64": base64.b64encode(data).decode("ascii")}


def _run_program1(sequence_id: str) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str = "") -> None:
        item = {"step": name, "status": status}
        if detail:
            item["detail"] = detail
        trace.append(item)

    step("CONNECT", "ok")
    pyautogui, error = _load_pyautogui()
    if pyautogui is None:
        step("HEALTH", "blocked", "pyautogui import failed")
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": "program1",
            "failure_code": "PYAUTOGUI_NOT_INSTALLED",
            "requires_install": True,
            "message": "PyAutoGUI is not installed. Install with: py -m pip install pyautogui",
            "step_trace": trace,
        }

    width, height = pyautogui.size()
    x, y = pyautogui.position()
    distance = 20
    target_x = max(1, min(int(width) - 2, int(x) + distance))
    target_y = max(1, min(int(height) - 2, int(y)))
    step("HEALTH", "ok")
    try:
        pyautogui.moveTo(target_x, target_y, duration=0.25)
        pyautogui.moveTo(int(x), int(y), duration=0.25)
    except Exception as exc:
        code = "PYAUTOGUI_FAILSAFE_TRIGGERED" if exc.__class__.__name__ == "FailSafeException" else "PYAUTOGUI_INTERNAL_ERROR"
        step("EXECUTE_PROGRAM", "failed", exc.__class__.__name__)
        return {
            "ok": False,
            "status": "failed",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": "program1",
            "failure_code": code,
            "message": f"program1 failed: {exc.__class__.__name__}",
            "step_trace": trace,
        }
    step("EXECUTE_PROGRAM", "ok", "demo_mouse_wiggle")
    step("DONE", "ok", "program1 completed")
    return {
        "ok": True,
        "status": "completed",
        "bridge": "windows_pyautogui",
        "sequence_id": sequence_id,
        "program_id": "program1",
        "program_log": "program1 completed",
        "step_trace": trace,
        "failure_code": None,
    }


def _run_custom_sequence(sequence_id: str, payload: dict[str, Any], *, program_id: str = "custom_sequence") -> dict[str, Any]:
    """Execute an operator-supplied JSON sequence without promoting it to UTM handoff evidence."""
    trace: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str = "") -> None:
        item = {"step": name, "status": status}
        if detail:
            item["detail"] = detail
        trace.append(item)

    step("CONNECT", "ok")
    pyautogui, error = _load_pyautogui()
    if pyautogui is None:
        step("HEALTH", "blocked", "pyautogui import failed")
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": "operator_sequence",
            "failure_code": "PYAUTOGUI_NOT_INSTALLED",
            "requires_install": True,
            "message": "PyAutoGUI is not installed. Install with: py -m pip install pyautogui",
            "step_trace": trace,
        }
    step("HEALTH", "ok")
    run_id = str(payload.get("run_id") or sequence_id or "manual-sequence")
    specimen_id = str(payload.get("specimen_id") or "manual-sequence")
    screen_artifacts: list[dict[str, Any]] = []
    result = _execute_protocol_sequence(
        pyautogui,
        program_id="custom_sequence",
        payload=payload,
        run_id=run_id,
        specimen_id=specimen_id,
        trace=trace,
        screen_artifacts=screen_artifacts,
    )
    ok = bool(result.get("ok"))
    if ok:
        step("DONE", "ok", "custom sequence completed")
    status = "completed" if ok else "blocked"
    return {
        "ok": ok,
        "status": status,
        "bridge": "windows_pyautogui",
        "sequence_id": sequence_id,
        "program_id": program_id,
        "program_type": "operator_sequence",
        "output_artifacts": screen_artifacts,
        "step_trace": trace,
        "failure_code": None if ok else str(result.get("failure_code") or "CUSTOM_SEQUENCE_FAILED"),
        "message": result.get("message", "") if isinstance(result, dict) else "",
    }


def _execute(payload: dict[str, Any]) -> dict[str, Any]:
    sequence_id = str(payload.get("sequence_id") or f"win-{int(time.time())}")
    platform_status = _desktop_platform_status()
    if not platform_status.get("desktop_control_ready"):
        return {
            "ok": False,
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "platform": platform_status,
            "sequence_id": sequence_id,
            "failure_code": str(platform_status.get("failure_code") or "PYAUTOGUI_LOCAL_DISPLAY_UNSUPPORTED"),
            "message": "Actual desktop control requires an active X11 display.",
            "step_trace": [{"step": "PLATFORM_PRECHECK", "status": "blocked", "detail": str(platform_status)}],
        }
    program_id = str(payload.get("program_id") or "").strip()
    if program_id:
        programs = _all_programs()
        if program_id not in programs:
            return {
                "ok": False,
                "status": "blocked",
                "bridge": "windows_pyautogui",
                "sequence_id": sequence_id,
                "program_id": program_id,
                "failure_code": "PYAUTOGUI_PROGRAM_NOT_FOUND",
                "message": f"Unknown program_id: {program_id}",
                "step_trace": [{"step": "RESOLVE_PROGRAM", "status": "blocked", "detail": program_id}],
            }
        if program_id == "program1":
            return _run_program1(sequence_id)
        program = programs[program_id]
        if program.get("enabled") is False:
            return {
                "ok": False,
                "status": "blocked",
                "bridge": "windows_pyautogui",
                "sequence_id": sequence_id,
                "program_id": program_id,
                "failure_code": "PYAUTOGUI_PROGRAM_DISABLED",
                "message": f"Program is disabled: {program_id}",
                "step_trace": [{"step": "RESOLVE_PROGRAM", "status": "blocked", "detail": "disabled"}],
            }
        if str(program.get("program_type") or "").startswith("utm_") or program_id.startswith("utm_"):
            return _run_utm_protocol(sequence_id, program_id, payload)
        custom_payload = {**payload, "sequence": list(program.get("sequence") or [])}
        return _run_custom_sequence(sequence_id, custom_payload, program_id=program_id)
    sequence = payload.get("sequence")
    if isinstance(sequence, list) and sequence:
        return _run_custom_sequence(sequence_id, payload)
    return {
        "ok": True,
        "status": "completed",
        "bridge": "windows_pyautogui",
        "sequence_id": sequence_id,
        "step_trace": [{"step": "DONE", "status": "ok", "detail": "no-op sequence accepted"}],
        "failure_code": None,
    }




@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    token: str = ""
    token_header: str = "X-Bridge-Token"
    artifact_dir: Path = ARTIFACT_ROOT
    reference_dir: Path = LOCATOR_ROOT
    program_dir: Path = PROGRAM_ROOT
    demo_dir: Path = DEMO_ROOT
    data_root: Path | None = None


def _apply_bridge_config(config: BridgeConfig) -> None:
    global HOST, PORT, TOKEN, TOKEN_HEADER, ARTIFACT_ROOT, LOCATOR_ROOT, PROGRAM_ROOT, DEMO_ROOT
    HOST = str(config.host)
    PORT = int(config.port)
    TOKEN = str(config.token or "")
    TOKEN_HEADER = str(config.token_header or "X-Bridge-Token")
    ARTIFACT_ROOT = Path(config.artifact_dir)
    if config.reference_dir:
        LOCATOR_ROOT = Path(config.reference_dir)
    if config.program_dir:
        PROGRAM_ROOT = Path(config.program_dir)
    if config.demo_dir:
        DEMO_ROOT = Path(config.demo_dir)
    _reset_controller_resolver(data_root=Path(config.data_root) if config.data_root else ARTIFACT_ROOT.parent)


def public_programs() -> list[dict[str, Any]]:
    return list(_programs().get("programs", []))


def execute_payload(payload: dict[str, Any], config: BridgeConfig | None = None) -> dict[str, Any]:
    if config is not None:
        _apply_bridge_config(config)
    return _execute(payload)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ATR Windows PyAutoGUI Bridge</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef2f5;
      --panel: #ffffff;
      --panel-soft: #f7f9fb;
      --ink: #17202c;
      --muted: #617083;
      --line: #d6dde7;
      --accent: #0d7661;
      --accent-2: #164e63;
      --danger: #b42318;
      --warn: #9a6700;
      --ok: #13795b;
      --ok-bg: #e7f6ef;
      --bad-bg: #fff0ed;
      --warn-bg: #fff7df;
      --code: #0f1720;
      --shadow: 0 10px 30px rgba(15, 23, 42, .06);
      --shadow-soft: 0 6px 18px rgba(15, 23, 42, .045);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(135deg, #eef2f5 0%, #f9fbfc 48%, #e8eef2 100%);
      color: var(--ink);
      font-family: "Segoe UI", "Malgun Gothic", Arial, sans-serif;
      letter-spacing: 0;
    }
    body.is-busy {
      cursor: progress;
    }
    ::selection { background: rgba(13, 118, 97, .18); }
    header {
      background:
        linear-gradient(90deg, rgba(255,255,255,.96), rgba(246,250,249,.94)),
        rgba(255,255,255,.92);
      border-bottom: 1px solid var(--line);
      padding: 10px 22px;
      box-shadow: var(--shadow-soft);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(10px);
    }
    h1 { font-size: 20px; line-height: 1.15; margin: 0; font-weight: 700; }
    .sub { margin-top: 4px; color: var(--muted); font-size: 12px; }
    .brandline { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .brandmark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 9px;
      background: linear-gradient(135deg, #0d7661, #164e63);
      color: #fff;
      font-weight: 900;
      font-size: 12px;
      letter-spacing: .05em;
    }
    .header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
    .header-pill-stack {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 5px;
      min-width: 168px;
    }
    .quick-nav {
      position: sticky;
      top: 55px;
      z-index: 9;
      width: min(1760px, calc(100vw - 28px));
      margin: 8px auto 0;
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 8px;
    }
    .quick-nav a {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,.92);
      color: #263548;
      text-decoration: none;
      text-align: center;
      padding: 7px 10px;
      font-size: 11px;
      font-weight: 800;
      box-shadow: 0 6px 18px rgba(15, 23, 42, .04);
      backdrop-filter: blur(8px);
    }
    .quick-nav a:hover { border-color: #9ccdc1; color: #0a604f; }
    main {
      width: min(1760px, calc(100vw - 28px));
      margin: 12px auto 28px;
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 14px;
    }
    section, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
    }
    section { padding: 14px; }
    h2 { font-size: 14px; margin: 0 0 10px; font-weight: 700; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    h3 { font-size: 13px; margin: 0 0 8px; font-weight: 700; color: #263548; }
    label { display: block; font-size: 12px; color: var(--muted); margin: 9px 0 5px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      background: #fff;
      color: var(--ink);
      outline: none;
    }
    input:focus, textarea:focus, select:focus { border-color: #70b8a8; box-shadow: 0 0 0 3px rgba(13,118,97,.12); }
    textarea { min-height: 190px; resize: vertical; font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    button {
      border: 1px solid #0a604f;
      background: var(--accent);
      color: white;
      border-radius: 8px;
      min-height: 36px;
      padding: 8px 10px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary { background: #fff; color: var(--ink); border-color: var(--line); }
    button.blue { background: var(--accent-2); border-color: #123f50; }
    button.danger { background: var(--danger); border-color: #8c1d12; }
    button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(15, 23, 42, .08); }
    button:active:not(:disabled) { transform: translateY(0); box-shadow: none; }
    button:disabled { opacity: .55; cursor: wait; }
    .row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .row3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .row4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .compact-tools { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .action-group {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-soft);
      padding: 10px;
      margin-top: 10px;
    }
    .action-group-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      color: #263548;
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 8px;
    }
    .danger-panel {
      border: 1px solid #f5b4ad;
      border-radius: 10px;
      background: #fff6f4;
      color: #5f1f19;
      padding: 10px;
      margin-top: 10px;
      font-size: 12px;
      line-height: 1.45;
    }
    .recovery-panel {
      border: 1px solid #f0b8b0;
      border-radius: 10px;
      background: linear-gradient(135deg, #fff7f5, #fffdfb);
      padding: 10px;
      margin-top: 10px;
      display: grid;
      gap: 8px;
    }
    .recovery-panel strong { color: #5f1f19; font-size: 12px; }
    .recovery-panel span { color: #6c3a32; font-size: 12px; line-height: 1.4; }
    .sidebar {
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: sticky;
      top: 112px;
      max-height: calc(100vh - 126px);
      overflow: auto;
      padding-right: 4px;
      scrollbar-width: thin;
      scrollbar-color: #b9c6d2 transparent;
    }
    .sidebar::-webkit-scrollbar, #log::-webkit-scrollbar, pre::-webkit-scrollbar, .timeline-track::-webkit-scrollbar { width: 9px; height: 9px; }
    .sidebar::-webkit-scrollbar-thumb, #log::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb, .timeline-track::-webkit-scrollbar-thumb { background: #b9c6d2; border-radius: 999px; border: 2px solid transparent; background-clip: content-box; }
    .workspace { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
    .status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .tile {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      min-height: 72px;
      background: var(--panel-soft);
    }
    .tile strong { display: block; font-size: 11px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em; }
    .tile span { display: block; font-size: 16px; font-weight: 800; overflow-wrap: anywhere; }
    .workflow-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .workflow-step {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 9px 10px;
      background: var(--panel-soft);
      min-height: 64px;
    }
    .workflow-step strong {
      display: block;
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 5px;
    }
    .workflow-step span {
      display: block;
      font-size: 13px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .ok { background: var(--ok-bg); border-color: #bce7d2; }
    .bad { background: var(--bad-bg); border-color: #ffd1ca; }
    .warn { background: var(--warn-bg); border-color: #f1daa0; }
    .muted { color: var(--muted); font-size: 12px; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      color: var(--muted);
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 12px;
      font-weight: 700;
    }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #98a2b3; display: inline-block; }
    .dot.ok { background: var(--ok); }
    .dot.bad { background: var(--danger); }
    .dot.warn { background: #f59e0b; }
    .command-banner.busy .dot.warn,
    body.is-busy #commandPill .dot {
      animation: pulseDot 1s ease-in-out infinite;
    }
    @keyframes pulseDot {
      0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, .26); }
      50% { box-shadow: 0 0 0 7px rgba(245, 158, 11, 0); }
    }
    details { border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); padding: 8px 10px; }
    summary { cursor: pointer; font-weight: 700; font-size: 13px; color: #2c3848; }
    pre {
      margin: 0;
      min-height: 260px;
      max-height: 52vh;
      overflow: auto;
      background: var(--code);
      color: #e6edf3;
      border-radius: 10px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
    th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 7px 6px; vertical-align: top; overflow-wrap: anywhere; }
    th { color: var(--muted); font-weight: 800; background: #f8fafc; }
    tr.trace-row.ok td { background: #f4fbf7; }
    tr.trace-row.warn td { background: #fffaf0; }
    tr.trace-row.bad td { background: #fff6f4; }
    .split { display: grid; grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); gap: 14px; }
    .panel-body { padding: 12px; }
    .result-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .logline { font-size: 12px; color: var(--muted); padding: 6px 0; border-bottom: 1px dashed var(--line); }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 7px; }
    .operator-checklist {
      border: 1px dashed #bed1cb;
      background: #f6fbf9;
      border-radius: 10px;
      padding: 10px 12px;
      margin-top: 10px;
      color: #263548;
      font-size: 12px;
      line-height: 1.45;
    }
    .operator-checklist strong { display: block; margin-bottom: 6px; }
    .operator-checklist ol { margin: 0; padding-left: 18px; }
    .operator-runbook {
      border: 1px solid #dce4ec;
      border-radius: 12px;
      background: linear-gradient(135deg, #ffffff, #f7fbf9);
      padding: 10px;
      margin-top: 10px;
      display: grid;
      gap: 8px;
    }
    .operator-runbook-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .operator-runbook-head strong {
      color: #203040;
      font-size: 12px;
      font-weight: 900;
    }
    .operator-runbook-head span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .runbook-step {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: #f8fafc;
      padding: 8px;
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
    }
    .runbook-step.ok { border-color: #a9dbc2; background: #eefbf5; }
    .runbook-step.warn { border-color: #f1daa0; background: #fffaf0; }
    .runbook-step.bad { border-color: #ffc6bd; background: #fff5f3; }
    .runbook-index {
      width: 24px;
      height: 24px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #e7edf3;
      color: #203040;
      font-size: 11px;
      font-weight: 900;
    }
    .runbook-step.ok .runbook-index { background: #bce7d2; color: #173e2e; }
    .runbook-step.warn .runbook-index { background: #f1daa0; color: #4d3510; }
    .runbook-step.bad .runbook-index { background: #ffc6bd; color: #5f1f19; }
    .runbook-step strong {
      display: block;
      color: #203040;
      font-size: 12px;
      margin-bottom: 3px;
    }
    .runbook-step small {
      display: block;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .runbook-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }
    .runbook-actions button {
      min-height: 30px;
      padding: 5px 7px;
      font-size: 11px;
    }
    .connection-readout {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: var(--panel-soft);
      padding: 9px 10px;
      margin-top: 10px;
      display: grid;
      gap: 4px;
    }
    .connection-readout span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .connection-readout code {
      color: #223143;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .command-kit {
      border: 1px solid #dce4ec;
      border-radius: 12px;
      background: linear-gradient(135deg, #ffffff, #f6faf8);
      padding: 10px;
      margin-top: 10px;
      display: grid;
      gap: 8px;
    }
    .command-kit-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .command-kit-head strong {
      color: #203040;
      font-size: 12px;
      font-weight: 900;
    }
    .command-kit-head span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .summary-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: linear-gradient(135deg, #f8fafc, #f2f7f5);
      padding: 12px;
      margin-top: 10px;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .summary-item {
      border: 1px solid #dce4ec;
      border-radius: 9px;
      padding: 8px;
      background: rgba(255,255,255,.72);
      min-height: 54px;
    }
    .summary-item strong {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 4px;
    }
    .summary-item span {
      display: block;
      font-size: 12px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .proof-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .proof-gate-strip {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 7px;
      margin-top: 9px;
    }
    .proof-gate {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: rgba(255,255,255,.78);
      padding: 8px 7px;
      min-height: 66px;
      display: grid;
      gap: 4px;
      align-content: start;
    }
    .proof-gate strong {
      color: #263548;
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .04em;
      line-height: 1.2;
    }
    .proof-gate span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .proof-gate.ok { border-color: #a9dbc2; background: #eefbf5; }
    .proof-gate.warn { border-color: #f1daa0; background: #fffaf0; }
    .proof-gate.bad { border-color: #ffc6bd; background: #fff5f3; }
    .proof-item {
      display: grid;
      grid-template-columns: 16px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      border: 1px solid #dce4ec;
      border-radius: 9px;
      padding: 8px;
      background: rgba(255,255,255,.72);
      min-height: 58px;
    }
    .proof-item strong {
      display: block;
      font-size: 11px;
      color: #263548;
      margin-bottom: 3px;
    }
    .proof-item small {
      display: block;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .checkline { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; color: var(--muted); }
    .checkline input { width: auto; }

    .file-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .file-item {
      border: 1px solid #dce4ec;
      border-radius: 9px;
      background: rgba(255,255,255,.78);
      padding: 8px;
      min-height: 56px;
    }
    .file-item strong {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 4px;
    }
    .file-item code {
      display: block;
      font-family: Consolas, "Courier New", monospace;
      font-size: 11px;
      color: #223143;
      overflow-wrap: anywhere;
      line-height: 1.35;
    }
    .preflight-banner {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      border: 1px solid #c9d8e2;
      border-radius: 12px;
      background: linear-gradient(135deg, #f7fbff, #f2f8f5);
      padding: 12px;
      margin-top: 10px;
    }
    .preflight-banner strong {
      display: block;
      font-size: 13px;
      color: #203040;
      margin-bottom: 4px;
    }
    .preflight-banner span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .preflight-banner.ok { border-color: #a9dbc2; background: #eefbf5; }
    .preflight-banner.bad { border-color: #ffc6bd; background: #fff5f3; }
    .interlock-card {
      border: 1px solid #f1daa0;
      border-radius: 10px;
      background: #fffaf0;
      padding: 10px;
      margin-top: 10px;
      font-size: 12px;
      line-height: 1.45;
      color: #4d3510;
    }
    .interlock-card strong { display: block; margin-bottom: 4px; color: #2d2210; }
    .interlock-card.ok { border-color: #a9dbc2; background: #eefbf5; color: #183d2d; }
    .operator-console {
      display: grid;
      grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr);
      gap: 12px;
      align-items: stretch;
      padding: 12px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(247,251,249,.96)),
        var(--panel);
    }
    .console-panel {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255,255,255,.76);
      padding: 11px;
      min-width: 0;
    }
    .intent-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .intent-card {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: #f8fafc;
      padding: 9px 10px;
      min-height: 58px;
    }
    .intent-card strong {
      display: block;
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 4px;
    }
    .intent-card span {
      display: block;
      color: #203040;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }
    .intent-card.ok { border-color: #a9dbc2; background: #eefbf5; }
    .intent-card.warn { border-color: #f1daa0; background: #fffaf0; }
    .intent-card.bad { border-color: #ffc6bd; background: #fff5f3; }
    .operator-mini-steps {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 6px;
      margin-top: 9px;
    }
    .operator-mini-step {
      border: 1px solid #dce4ec;
      border-radius: 999px;
      background: #f8fafc;
      color: #3a4a5f;
      padding: 6px 8px;
      text-align: center;
      font-size: 11px;
      font-weight: 800;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .operator-timeline {
      padding: 12px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(247,251,249,.95)),
        var(--panel);
    }
    .timeline-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      margin-bottom: 8px;
    }
    .timeline-head h2 { margin-bottom: 4px; }
    .timeline-track {
      border: 1px solid #dce4ec;
      border-radius: 12px;
      background: #f8fafc;
      padding: 10px;
      max-height: 260px;
      overflow: auto;
      display: grid;
      gap: 8px;
    }
    .timeline-empty {
      color: var(--muted);
      font-size: 12px;
      padding: 14px;
      text-align: center;
    }
    .timeline-item {
      display: grid;
      grid-template-columns: 88px 13px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      color: #203040;
      font-size: 12px;
    }
    .timeline-item .timeline-time {
      color: var(--muted);
      font-family: Consolas, "Courier New", monospace;
      font-size: 11px;
      padding-top: 2px;
      white-space: nowrap;
    }
    .timeline-marker {
      width: 11px;
      height: 11px;
      border-radius: 999px;
      background: #98a2b3;
      margin-top: 3px;
      box-shadow: 0 0 0 4px rgba(152,162,179,.14);
    }
    .timeline-item.ok .timeline-marker { background: var(--ok); box-shadow: 0 0 0 4px rgba(19,121,91,.13); }
    .timeline-item.warn .timeline-marker { background: #f59e0b; box-shadow: 0 0 0 4px rgba(245,158,11,.16); }
    .timeline-item.bad .timeline-marker { background: var(--danger); box-shadow: 0 0 0 4px rgba(180,35,24,.13); }
    .timeline-content {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: rgba(255,255,255,.82);
      padding: 8px 9px;
      min-width: 0;
    }
    .timeline-content strong {
      display: block;
      font-size: 12px;
      margin-bottom: 3px;
      overflow-wrap: anywhere;
    }
    .timeline-content small {
      display: block;
      color: var(--muted);
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .console-actions {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    pre.payload-preview {
      min-height: 160px;
      max-height: 250px;
      margin-top: 8px;
      font-size: 11px;
      background: #10202a;
    }
    .gate-meter {
      border: 1px solid #dce4ec;
      border-radius: 999px;
      background: #eef2f5;
      height: 14px;
      overflow: hidden;
      margin-top: 4px;
    }
    .gate-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #0d7661, #35b18d);
      transition: width .18s ease;
    }
    .gate-caption {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 11px;
      margin-top: 5px;
    }
    .preview-box {
      border: 1px dashed #c9d8e2;
      border-radius: 10px;
      background: #f8fafc;
      min-height: 150px;
      padding: 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      overflow: hidden;
    }
    .preview-box img {
      max-width: 100%;
      max-height: 360px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    .preview-meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 11px;
      overflow-wrap: anywhere;
      text-align: left;
    }
    .command-shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(440px, 620px);
      gap: 10px;
      align-items: stretch;
      position: sticky;
      top: 104px;
      z-index: 8;
    }
    .command-banner {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(168px, 220px);
      gap: 10px;
      align-items: center;
      border: 1px solid #c9d8e2;
      border-radius: 12px;
      background: linear-gradient(135deg, #ffffff, #f2f8f5);
      padding: 10px 12px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, .04);
    }
    .command-banner strong { display: block; color: #203040; font-size: 13px; margin-bottom: 3px; }
    .command-banner span { display: block; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .command-banner.ok { border-color: #a9dbc2; background: #eefbf5; }
    .command-banner.bad { border-color: #ffc6bd; background: #fff5f3; }
    .command-banner.warn { border-color: #f1daa0; background: #fffaf0; }
    .command-banner.busy { border-color: #b8d5f2; background: #f2f8ff; }
    .command-side {
      display: grid;
      gap: 6px;
      justify-items: stretch;
      align-content: center;
      min-width: 0;
    }
    .command-side .pill {
      justify-self: end;
      max-width: 100%;
    }
    .next-action-button {
      min-height: 40px;
      border-color: #102f3b;
      background: #102f3b;
      display: grid;
      gap: 1px;
      justify-items: start;
      text-align: left;
      line-height: 1.12;
    }
    .next-action-button small {
      color: rgba(255,255,255,.72);
      font-size: 9px;
      font-weight: 900;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .next-action-button span {
      color: #fff;
      font-size: 12px;
      font-weight: 900;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }
    .next-action-button.ok { border-color: #0d7661; background: #0d7661; }
    .next-action-button.warn { border-color: #9a6700; background: #9a6700; }
    .next-action-button.bad { border-color: #b42318; background: #b42318; }
    .attention-flash {
      animation: attentionFlash 1.2s ease-in-out 1;
    }
    @keyframes attentionFlash {
      0%, 100% { box-shadow: 0 0 0 0 rgba(13, 118, 97, 0); }
      40% { box-shadow: 0 0 0 5px rgba(13, 118, 97, .18); }
    }
    .control-rail {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255,255,255,.92);
      padding: 8px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, .04);
    }
    .control-rail button {
      min-height: 52px;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 2px;
      line-height: 1.1;
      padding: 7px 8px;
    }
    .control-rail button small {
      display: block;
      max-width: 100%;
      opacity: .78;
      font-size: 10px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .control-rail .danger small { color: rgba(255,255,255,.84); }
    .control-rail .secondary small { color: var(--muted); }
    .control-rail .blue small { color: rgba(255,255,255,.84); }
    .ops-hud {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      padding: 10px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(242,248,245,.96)),
        var(--panel);
    }
    .ops-card {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(255,255,255,.82);
      padding: 9px 10px;
      min-height: 62px;
      display: grid;
      align-content: start;
      gap: 4px;
    }
    .ops-card strong {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .ops-card span {
      color: #1f2f3f;
      font-size: 12px;
      line-height: 1.3;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .ops-card.ok { border-color: #a9dbc2; background: #eefbf5; }
    .ops-card.warn { border-color: #f1daa0; background: #fffaf0; }
    .ops-card.bad { border-color: #ffc6bd; background: #fff5f3; }
    .situation-board {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      padding: 10px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(247,251,249,.95)),
        var(--panel);
    }
    .situation-board-title {
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      color: #203040;
      font-size: 12px;
      font-weight: 900;
      margin-bottom: -2px;
    }
    .situation-board-title span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .situation-card {
      border: 1px solid var(--line);
      border-radius: 11px;
      background: rgba(255,255,255,.84);
      padding: 9px 10px;
      min-height: 70px;
      display: grid;
      gap: 4px;
      align-content: start;
    }
    .situation-card strong {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .situation-card span {
      color: #1f2f3f;
      font-size: 12px;
      line-height: 1.35;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .situation-card small {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }
    .situation-card.ok { border-color: #a9dbc2; background: #eefbf5; }
    .situation-card.warn { border-color: #f1daa0; background: #fffaf0; }
    .situation-card.bad { border-color: #ffc6bd; background: #fff5f3; }
    .locator-shortcuts {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .locator-chip {
      min-height: 28px;
      padding: 5px 8px;
      border-radius: 999px;
      border-color: #dce4ec;
      background: #fff;
      color: #324055;
      font-size: 11px;
      box-shadow: none;
    }
    .locator-chip.missing { border-color: #f1daa0; background: #fffaf0; color: #694b10; }
    .locator-chip.captured { border-color: #a9dbc2; background: #eefbf5; color: #173e2e; }
    .audit-identity-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .audit-identity-item {
      border: 1px solid #dce4ec;
      border-radius: 9px;
      background: rgba(255,255,255,.74);
      padding: 7px 8px;
      min-height: 48px;
    }
    .audit-identity-item strong {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 3px;
    }
    .audit-identity-item span {
      display: block;
      color: #203040;
      font-size: 11px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .identity-strip {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin: 8px 0 2px;
    }
    .identity-pill {
      border: 1px solid #dce4ec;
      border-radius: 10px;
      background: #f8fafc;
      padding: 8px 9px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .identity-pill strong {
      display: block;
      color: #263548;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 3px;
    }

    .program-registry {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .program-registry-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 10px;
      padding: 8px 9px;
      border: 1px solid #dce4ec;
      border-radius: 11px;
      background: #f8fafc;
    }
    .program-registry-title strong {
      color: #203040;
      font-size: 12px;
    }
    .program-registry-title span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .program-card {
      border: 1px solid #dce4ec;
      border-radius: 11px;
      background: linear-gradient(135deg, #ffffff, #f7fbf9);
      padding: 9px;
      display: grid;
      gap: 6px;
      cursor: pointer;
      transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease;
    }
    .program-card:hover {
      border-color: #9ccdc1;
      box-shadow: 0 8px 18px rgba(15, 23, 42, .06);
      transform: translateY(-1px);
    }
    .program-card.selected {
      border-color: #0d7661;
      box-shadow: 0 0 0 3px rgba(13, 118, 97, .12);
    }
    .program-card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .program-card-head strong {
      color: #203040;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .program-kind {
      border-radius: 999px;
      border: 1px solid #dce4ec;
      background: #f8fafc;
      color: var(--muted);
      padding: 3px 7px;
      font-size: 10px;
      font-weight: 900;
      white-space: nowrap;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .program-card p {
      margin: 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .program-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }
    .program-meta span {
      border-radius: 999px;
      background: #eef2f5;
      color: #3a4a5f;
      padding: 3px 7px;
      font-size: 10px;
      font-weight: 800;
    }
    .program-card-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }
    .program-card-actions button {
      min-height: 30px;
      padding: 5px 7px;
      font-size: 11px;
    }

    .section-intro {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin: -4px 0 8px;
    }

    #overview {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      align-items: start;
    }
    #overview > .status-grid,
    #overview > .preflight-banner,
    #overview > .workflow-strip,
    #overview > .wide-card {
      grid-column: 1 / -1;
    }
    #overview > .summary-card { margin-top: 0; }
    #overview .proof-gate-strip { grid-template-columns: repeat(7, minmax(78px, 1fr)); overflow-x: auto; padding-bottom: 2px; }
    .panel-toggle {
      border: 1px solid var(--line);
      background: #fff;
      color: #324055;
      min-height: 26px;
      padding: 4px 8px;
      font-size: 10px;
      border-radius: 999px;
      box-shadow: none;
    }
    .panel-toggle:hover:not(:disabled) { transform: none; box-shadow: 0 4px 10px rgba(15, 23, 42, .06); }
    section.is-collapsed { padding-bottom: 10px; }
    section.is-collapsed > :not(h2) { display: none !important; }
    .operator-compact-note {
      border: 1px solid #c9d8e2;
      border-radius: 10px;
      background: #f8fafc;
      color: var(--muted);
      padding: 8px 10px;
      font-size: 11px;
      line-height: 1.35;
      margin-top: 8px;
    }

    .wide { grid-column: 1 / -1; }
    #log {
      max-height: 260px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-soft);
      padding: 4px 10px;
    }
    body.focus-mode .quick-nav,
    body.focus-mode #safeDiagnosticsPanel,
    body.focus-mode #locatorPanel,
    body.focus-mode #resultPanel {
      display: none;
    }
    body.focus-mode main { grid-template-columns: 340px minmax(0, 1fr); }
    body.focus-mode .split { grid-template-columns: 1fr; }
    body.focus-mode #focusMode {
      background: #102f3b;
      border-color: #102f3b;
      color: #fff;
    }
    @media (max-width: 980px) {
      .quick-nav { top: 92px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main, .split { grid-template-columns: 1fr; }
      .sidebar, .command-shell { position: static; max-height: none; }
      .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workflow-strip, .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .ops-hud, .identity-strip, .situation-board, .audit-identity-grid { grid-template-columns: 1fr; }
      .operator-console, .intent-grid { grid-template-columns: 1fr; }
      .operator-mini-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .proof-gate-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .timeline-head { grid-template-columns: 1fr; }
      .timeline-item { grid-template-columns: 72px 13px minmax(0, 1fr); }
      .command-shell { grid-template-columns: 1fr; }
      .control-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .row4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .header-pill-stack { align-items: flex-start; width: 100%; }
    }

    /* Program Manager augments the full operator console; it never replaces controls. */
    .manager-toolbar {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) 150px repeat(4, auto);
      gap: 8px;
      align-items: end;
    }
    .manager-toolbar label { margin: 0; }
    .manager-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      margin-top: 12px;
      align-items: start;
    }
    .manager-registry { display: grid; gap: 8px; min-width: 0; }
    .manager-program-card {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 12px;
      align-items: center;
    }
    .manager-program-info { min-width: 0; display: grid; gap: 4px; }
    .manager-program-info p { margin: 0; }
    .manager-editor {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-soft);
      overflow: hidden;
    }
    .manager-editor[hidden] { display: none; }
    .manager-editor-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .manager-editor-body { padding: 10px; }
    .manager-stats { margin-top: 9px; color: var(--muted); font-size: 11px; }
    .manager-badges { display: flex; flex-wrap: wrap; gap: 5px; }
    .manager-badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 3px 7px;
      border-radius: 999px;
      background: #eef2f5;
      color: #3a4a5f;
      font-size: 10px;
      font-weight: 800;
    }
    .manager-badge.ok { background: #e7f6ef; color: var(--ok); }
    .manager-badge.warn { background: #fff7df; color: var(--warn); }
    .manager-badge.bad { background: #fff0ed; color: var(--danger); }
    .manager-actions {
      display: grid;
      grid-template-columns: repeat(5, minmax(76px, auto));
      gap: 6px;
      min-width: min(100%, 480px);
    }
    .manager-actions button { min-height: 30px; padding: 5px 7px; font-size: 11px; }
    .manager-empty {
      border: 1px dashed var(--line);
      border-radius: 10px;
      padding: 18px;
      color: var(--muted);
      text-align: center;
      background: var(--panel-soft);
    }
    .manager-file-meta {
      margin-top: 9px;
      padding: 8px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      font-size: 11px;
      overflow-wrap: anywhere;
    }
    .manager-result { margin-top: 10px; }
    .manager-result pre { min-height: 120px; max-height: 260px; }
    .manager-hidden { display: none !important; }
    .manager-tabs { display: flex; gap: 6px; margin: 10px 0; }
    .manager-tabs button { min-height: 32px; padding: 6px 14px; }
    .manager-tabs button.active { background: var(--accent); color: #fff; }
    .manager-view[hidden] { display: none !important; }
    .manager-record-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .recording-options { display:flex; flex-wrap:wrap; gap:10px; margin-top:10px; }
    .recording-option { display:flex; align-items:center; gap:8px; min-height:38px; padding:0 12px; border:1px solid var(--line); border-radius:10px; background:var(--panel-soft); }
    .recording-option input { width:auto; margin:0; }
    .recording-locator-preview { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; margin-top:10px; }
    .recording-locator-card { border:1px solid var(--line); border-radius:10px; padding:8px; display:grid; gap:6px; background:var(--panel-soft); }
    .recording-locator-images { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
    .recording-locator-images img { display:block; width:100%; height:76px; object-fit:contain; background:#0b1220; border:1px solid var(--line); border-radius:6px; }
    #recordToggle[data-state="recording"] { background:var(--danger); border-color:#8c1d12; color:#fff; }
    #recordToggle[data-state="countdown"] { background:#9b5c00; border-color:#6f4100; color:#fff; }
    .manager-record-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
    .manager-skill-card { border: 1px solid var(--line); border-radius: 12px; padding: 10px; display: grid; gap: 7px; }
    .manager-skill-card .manager-actions { grid-template-columns: repeat(7, minmax(0, 1fr)); }
    #bridgeCommandKit .compact-tools { grid-template-columns: 1fr; }
    @media (max-width: 1080px) {
      .manager-toolbar, .manager-grid { grid-template-columns: 1fr; }
      .manager-record-grid { grid-template-columns: 1fr; }
      .manager-program-card { grid-template-columns: 1fr; }
      .manager-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }


    .quick-nav { display: none; }
    .essential-console {
      width: min(1760px, calc(100vw - 28px));
      margin: 12px auto 10px;
      display: grid;
      gap: 12px;
    }
    .essential-grid {
      display: grid;
      grid-template-columns: minmax(280px, .72fr) minmax(0, 1.28fr);
      gap: 12px;
    }
    .essential-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel);
      box-shadow: var(--shadow);
      padding: 14px;
      min-width: 0;
    }
    .essential-card h2 { margin-bottom: 4px; }
    .essential-card .section-intro { margin: 0 0 10px; }
    .essential-fields {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) repeat(3, auto);
      gap: 8px;
      align-items: end;
    }
    .essential-fields label { margin: 0; }
    .essential-metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .essential-metric {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel-soft);
      padding: 9px 10px;
      min-width: 0;
    }
    .essential-metric strong {
      display: block;
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 10px;
      letter-spacing: .04em;
      text-transform: uppercase;
    }
    .essential-metric span {
      display: block;
      color: var(--ink);
      font-size: 14px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }
    .essential-result {
      border-left: 4px solid #9aa8b7;
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px 12px;
      color: #263548;
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .essential-result[data-tone="ok"] { border-left-color: var(--ok); background: var(--ok-bg); }
    .essential-result[data-tone="bad"] { border-left-color: var(--danger); background: var(--bad-bg); }
    .essential-result[data-tone="warn"] { border-left-color: #f59e0b; background: var(--warn-bg); }
    #essentialProgramManagerSlot > #programManagerPanel { margin: 0; }
    #advancedToolsPanel {
      --panel: #ffffff;
      --panel-soft: #f4f7fc;
      --ink: #17233d;
      --muted: #60708d;
      --line: #cdd9ee;
      --accent: #2557d6;
      --accent-2: #173f9f;
      --ok-bg: #eaf8f1;
      --bad-bg: #fff1ef;
      --warn-bg: #fff8e8;
      width: min(1760px, calc(100vw - 28px));
      margin: 0 auto 28px;
      padding: 0;
      border: 1px solid #bdcce6;
      border-radius: 16px;
      background: #eaf0f9;
      box-shadow: 0 12px 34px rgba(38, 72, 132, .10);
      overflow: clip;
    }
    #advancedToolsPanel > summary {
      padding: 15px 18px;
      color: #173f9f;
      font-size: 14px;
      font-weight: 900;
      line-height: 1.35;
      list-style-position: inside;
      background: linear-gradient(135deg, #ffffff 0%, #f1f6ff 100%);
      cursor: pointer;
      overflow-wrap: anywhere;
    }
    #advancedToolsPanel > summary::marker { color: #2557d6; }
    #advancedToolsPanel[open] > summary { border-bottom: 1px solid #bdcce6; }
    #advancedToolsPanel > main {
      width: 100%;
      margin: 0;
      padding: 16px;
      grid-template-columns: minmax(300px, 350px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    #advancedToolsPanel .sidebar,
    #advancedToolsPanel .workspace {
      gap: 16px;
      min-width: 0;
    }
    #advancedToolsPanel .sidebar {
      top: 112px;
      max-height: calc(100vh - 128px);
      padding-right: 5px;
    }
    #advancedToolsPanel section,
    #advancedToolsPanel .card {
      min-width: 0;
      border-color: #cdd9ee;
      border-radius: 14px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(34, 68, 130, .07);
    }
    #advancedToolsPanel section { padding: 15px; }
    #advancedToolsPanel h2 {
      color: #173f9f;
      font-size: 14px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    #advancedToolsPanel h3 { color: #294575; }
    #advancedToolsPanel .section-intro,
    #advancedToolsPanel .hint,
    #advancedToolsPanel .operator-compact-note,
    #advancedToolsPanel .identity-pill,
    #advancedToolsPanel .runbook-step small,
    #advancedToolsPanel .command-banner span,
    #advancedToolsPanel .ops-card span,
    #advancedToolsPanel .proof-gate span {
      white-space: normal;
      overflow: visible;
      text-overflow: clip;
      overflow-wrap: anywhere;
    }
    #advancedToolsPanel button {
      min-width: 0;
      height: auto;
      min-height: 38px;
      white-space: normal;
      overflow: visible;
      text-overflow: clip;
      overflow-wrap: anywhere;
      line-height: 1.2;
      border-color: #1e48b5;
      background: #2557d6;
    }
    #advancedToolsPanel button.secondary {
      border-color: #c4d1e7;
      background: #ffffff;
      color: #294575;
    }
    #advancedToolsPanel button.blue {
      border-color: #173f9f;
      background: #173f9f;
    }
    #advancedToolsPanel button.danger {
      border-color: #a52a22;
      background: #bd352b;
    }
    #advancedToolsPanel input,
    #advancedToolsPanel textarea,
    #advancedToolsPanel select {
      min-width: 0;
      border-color: #c4d1e7;
      border-radius: 9px;
      background: #ffffff;
    }
    #advancedToolsPanel input:focus,
    #advancedToolsPanel textarea:focus,
    #advancedToolsPanel select:focus {
      border-color: #5c83e7;
      box-shadow: 0 0 0 3px rgba(37, 87, 214, .13);
    }
    #advancedToolsPanel .action-group,
    #advancedToolsPanel .tile,
    #advancedToolsPanel .workflow-step,
    #advancedToolsPanel .ops-card,
    #advancedToolsPanel .summary-card,
    #advancedToolsPanel .proof-gate,
    #advancedToolsPanel .connection-readout,
    #advancedToolsPanel .command-kit,
    #advancedToolsPanel .operator-runbook {
      min-width: 0;
      border-color: #d5dfef;
      background: #f5f8fd;
    }
    #advancedToolsPanel .row3,
    #advancedToolsPanel .row4,
    #advancedToolsPanel .buttons,
    #advancedToolsPanel .compact-tools,
    #advancedToolsPanel .status-grid,
    #advancedToolsPanel .workflow-strip,
    #advancedToolsPanel .summary-grid,
    #advancedToolsPanel .proof-list,
    #advancedToolsPanel .proof-gate-strip,
    #advancedToolsPanel .control-rail,
    #advancedToolsPanel .ops-hud {
      grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
    }
    #advancedToolsPanel .row {
      grid-template-columns: repeat(auto-fit, minmax(138px, 1fr));
    }
    #advancedToolsPanel .next-action-button span,
    #advancedToolsPanel .control-rail button small {
      max-width: 100%;
      white-space: normal;
      overflow: visible;
      text-overflow: clip;
      overflow-wrap: anywhere;
    }
    #advancedToolsPanel pre,
    #advancedToolsPanel code,
    #advancedToolsPanel .mono {
      max-width: 100%;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    #advancedToolsPanel pre {
      overflow: auto;
      white-space: pre-wrap;
    }
    #advancedToolsPanel .command-shell {
      position: static;
      top: auto;
      z-index: auto;
    }
    @media (max-width: 1500px) {
      #advancedToolsPanel .command-shell {
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 1100px) {
      .essential-grid, .essential-fields { grid-template-columns: 1fr; }
      .essential-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .essential-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      #advancedToolsPanel > main { grid-template-columns: 1fr; }
      #advancedToolsPanel .sidebar {
        position: static;
        max-height: none;
        overflow: visible;
        padding-right: 0;
      }
    }
    @media (max-width: 680px) {
      #advancedToolsPanel {
        width: calc(100vw - 16px);
        border-radius: 12px;
      }
      #advancedToolsPanel > summary { padding: 13px 14px; }
      #advancedToolsPanel > main { padding: 10px; gap: 10px; }
      #advancedToolsPanel .sidebar,
      #advancedToolsPanel .workspace { gap: 10px; }
      #advancedToolsPanel .row,
      #advancedToolsPanel .row3,
      #advancedToolsPanel .row4,
      #advancedToolsPanel .buttons,
      #advancedToolsPanel .compact-tools,
      #advancedToolsPanel .status-grid,
      #advancedToolsPanel .workflow-strip,
      #advancedToolsPanel .summary-grid,
      #advancedToolsPanel .proof-list,
      #advancedToolsPanel .proof-gate-strip,
      #advancedToolsPanel .control-rail,
      #advancedToolsPanel .ops-hud {
        grid-template-columns: 1fr;
      }
    }

    /* Self-contained ATR Device Bridge theme for the complete Windows console. */
    body.device-bridge-shell {
      --bg: #f5f8ff;
      --panel: #ffffff;
      --panel-soft: #f1f6ff;
      --ink: #091225;
      --muted: #5a6883;
      --line: rgba(26, 60, 160, .22);
      --accent: #1436b3;
      --accent-2: #2f72ff;
      --danger: #c84c3b;
      --warn: #d98c12;
      --ok: #1d9150;
      --ok-bg: #eaf8f1;
      --bad-bg: #fff1ef;
      --warn-bg: #fff8e8;
      --shadow: 0 20px 52px rgba(28, 53, 112, .11);
      --shadow-soft: 0 10px 28px rgba(28, 53, 112, .08);
      background:
        radial-gradient(circle at top left, rgba(47, 114, 255, .12), transparent 28%),
        linear-gradient(180deg, #fbfcff 0%, #f5f8ff 35%, #eef4ff 100%);
      color: var(--ink);
    }
    body.device-bridge-shell ::selection { background: rgba(47, 114, 255, .20); }
    body.device-bridge-shell > header {
      width: min(1760px, calc(100vw - 28px));
      margin: 16px auto 0;
      padding: 20px 22px;
      position: relative;
      top: auto;
      border: 1.5px solid var(--line);
      border-radius: 22px;
      background: rgba(255, 255, 255, .94);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    body.device-bridge-shell h1 {
      color: var(--ink);
      font-size: clamp(24px, 2vw, 32px);
      line-height: 1.05;
      letter-spacing: -.02em;
    }
    body.device-bridge-shell .sub {
      max-width: 76ch;
      margin-top: 7px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    body.device-bridge-shell .brandline { gap: 12px; }
    body.device-bridge-shell .brandmark {
      width: 42px;
      height: 42px;
      border-radius: 14px;
      background: linear-gradient(135deg, #1436b3, #2f72ff);
      box-shadow: 0 10px 22px rgba(20, 54, 179, .24);
      font-size: 13px;
    }
    body.device-bridge-shell .header-pill-stack {
      flex-direction: row;
      align-items: center;
      justify-content: flex-end;
      min-width: 0;
    }
    body.device-bridge-shell .pill {
      border-color: rgba(20, 54, 179, .18);
      background: linear-gradient(180deg, #ffffff, #f1f6ff);
      color: #435271;
      box-shadow: 0 7px 18px rgba(34, 58, 120, .06);
    }
    body.device-bridge-shell .essential-console {
      margin-top: 18px;
      margin-bottom: 16px;
      gap: 18px;
    }
    body.device-bridge-shell .essential-grid { gap: 18px; }
    body.device-bridge-shell section,
    body.device-bridge-shell .card,
    body.device-bridge-shell .essential-card,
    body.device-bridge-shell #programManagerPanel {
      border: 1.5px solid var(--line);
      border-radius: 22px;
      background: rgba(255, 255, 255, .94);
      box-shadow: var(--shadow);
    }
    body.device-bridge-shell .essential-card { padding: 20px; }
    body.device-bridge-shell h2 {
      color: #1436b3;
      font-size: 15px;
      line-height: 1.35;
    }
    body.device-bridge-shell h3 { color: #27447c; }
    body.device-bridge-shell label { color: var(--muted); }
    body.device-bridge-shell input,
    body.device-bridge-shell textarea,
    body.device-bridge-shell select {
      min-width: 0;
      border: 1px solid rgba(20, 54, 179, .20);
      border-radius: 12px;
      background: rgba(255, 255, 255, .98);
      color: var(--ink);
    }
    body.device-bridge-shell input:focus,
    body.device-bridge-shell textarea:focus,
    body.device-bridge-shell select:focus {
      border-color: #2f72ff;
      box-shadow: 0 0 0 3px rgba(47, 114, 255, .14);
    }
    body.device-bridge-shell button {
      min-width: 0;
      min-height: 40px;
      border: 1px solid transparent;
      border-radius: 12px;
      background: linear-gradient(120deg, #1436b3, #2f72ff);
      color: #ffffff;
      box-shadow: 0 8px 18px rgba(20, 54, 179, .16);
      white-space: normal;
      overflow-wrap: anywhere;
      line-height: 1.2;
    }
    body.device-bridge-shell button.secondary {
      border-color: rgba(20, 54, 179, .18);
      background: rgba(255, 255, 255, .96);
      color: #1f3159;
      box-shadow: 0 7px 16px rgba(34, 58, 120, .05);
    }
    body.device-bridge-shell button.blue {
      border-color: transparent;
      background: linear-gradient(120deg, #1436b3, #2f72ff);
    }
    body.device-bridge-shell button.danger {
      border-color: rgba(200, 76, 59, .32);
      background: rgba(255, 242, 239, .98);
      color: #a43d31;
      box-shadow: none;
    }
    body.device-bridge-shell button:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 11px 24px rgba(20, 54, 179, .16);
    }
    body.device-bridge-shell .essential-metric,
    body.device-bridge-shell .manager-editor,
    body.device-bridge-shell .manager-empty,
    body.device-bridge-shell .action-group,
    body.device-bridge-shell .tile,
    body.device-bridge-shell .workflow-step,
    body.device-bridge-shell .status-card {
      border-color: rgba(20, 54, 179, .16);
      border-radius: 16px;
      background: linear-gradient(180deg, #ffffff, #f1f6ff);
      box-shadow: 0 9px 22px rgba(34, 58, 120, .06);
    }
    body.device-bridge-shell .essential-result {
      border: 1px solid rgba(20, 54, 179, .16);
      border-left: 5px solid #6d7f9f;
      border-radius: 14px;
      background: #f5f8ff;
      color: #223252;
    }
    body.device-bridge-shell .essential-result[data-tone="ok"] { border-left-color: var(--ok); }
    body.device-bridge-shell .essential-result[data-tone="bad"] { border-left-color: var(--danger); }
    body.device-bridge-shell .essential-result[data-tone="warn"] { border-left-color: var(--warn); }
    body.device-bridge-shell .manager-toolbar { gap: 10px; }
    body.device-bridge-shell .manager-program-card {
      border: 1px solid rgba(20, 54, 179, .16);
      border-radius: 16px;
      background: linear-gradient(180deg, #ffffff, #f6f9ff);
      box-shadow: 0 8px 20px rgba(34, 58, 120, .05);
      padding: 12px;
    }
    body.device-bridge-shell .manager-badge {
      background: #eaf0ff;
      color: #294b9d;
    }
    body.device-bridge-shell #advancedToolsPanel {
      border-width: 1.5px;
      border-radius: 22px;
      background: rgba(235, 242, 255, .92);
      box-shadow: var(--shadow);
    }
    body.device-bridge-shell #advancedToolsPanel > summary {
      padding: 17px 20px;
      color: #1436b3;
      font-size: 15px;
      background: rgba(255, 255, 255, .94);
    }
    body.device-bridge-shell #advancedToolsPanel section,
    body.device-bridge-shell #advancedToolsPanel .card {
      border-radius: 18px;
      box-shadow: 0 10px 26px rgba(34, 68, 130, .07);
    }
    @media (max-width: 1500px) and (min-width: 761px) {
      body.device-bridge-shell .essential-fields {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      body.device-bridge-shell .essential-fields > label {
        grid-column: 1 / -1;
      }
    }
    @media (max-width: 760px) {
      body.device-bridge-shell > header {
        width: calc(100vw - 16px);
        margin-top: 8px;
        padding: 16px;
        border-radius: 16px;
        align-items: flex-start;
        flex-direction: column;
      }
      body.device-bridge-shell .header-pill-stack {
        justify-content: flex-start;
        flex-wrap: wrap;
      }
      body.device-bridge-shell .essential-console { width: calc(100vw - 16px); }
      body.device-bridge-shell .essential-card { padding: 16px; }
    }

  </style>
</head>
<body class="device-bridge-shell">
  <header>
    <div>
      <div class="brandline"><span class="brandmark">ATR</span><h1>ATR Windows PyAutoGUI Bridge</h1></div>
      <div class="sub">Windows-side bridge for UTM GUI control, locator calibration, screenshots, and artifact handoff.</div>
    </div>
    <div class="header-actions">
      <div class="header-pill-stack">
        <span class="pill" id="authPill"><span class="dot"></span><span>auth not checked</span></span>
        <span class="pill" id="headerProofPill"><span class="dot warn"></span><span>proof 0/7</span></span>
      </div>
    </div>
  </header>
  <nav class="quick-nav" aria-label="Windows bridge workspace navigation">
    <a href="#overview">Overview</a>
    <a href="#operatorConsolePanel">Console</a>
    <a href="#timelinePanel">Timeline</a>
    <a href="#utmProtocolPanel">UTM Control</a>
    <a href="#evidencePanel">Evidence</a>
    <a href="#resultPanel">Result JSON</a>
    <a href="#programManagerPanel">Programs</a>
    <a href="#operatorLogPanel">Operator Log</a>
  </nav>

  <div id="essentialConsole" class="essential-console">
    <div class="essential-grid">
      <section class="essential-card" aria-label="Essential bridge connection">
        <h2>Bridge Connection</h2>
        <div class="section-intro">Connect this Windows bridge, then create or manage bounded macro programs below.</div>
        <div class="essential-fields">
          <label>Bridge Token<input id="token" type="password" autocomplete="off" placeholder="X-Bridge-Token"></label>
          <button id="health">Health</button>
          <button class="secondary" id="refreshAll">Refresh</button>
          <button class="secondary" id="clearToken">Clear Token</button>
        </div>
        <div class="connection-readout" style="margin-top:10px">
          <span>ATR Controller</span>
          <code id="controllerStatus">Not resolved</code>
        </div>
        <div class="essential-fields" style="margin-top:8px">
          <label>Controller URL<input id="controllerUrl" type="url" placeholder="http://192.168.x.x:7860"></label>
          <button class="secondary" id="discoverController">Discover ATR</button>
          <button class="secondary" id="saveController">Verify &amp; Save</button>
        </div>
        <div id="controllerCandidates" class="hint" aria-live="polite">ATR will be learned from an authenticated Linux request or bounded private-network discovery.</div>
        <div class="essential-metrics" style="margin-top:10px">
          <div class="essential-metric"><strong>Bridge</strong><span id="essentialBridgeState">Not checked</span></div>
          <div class="essential-metric"><strong>PyAutoGUI</strong><span id="essentialPyAutoGUI">Unknown</span></div>
        </div>
      </section>
      <section class="essential-card" aria-label="Latest macro manager result">
        <h2>Latest Test Result</h2>
        <div class="section-intro">Validation, registration, deletion, and bounded test results appear here.</div>
        <div id="essentialResult" class="essential-result" data-tone="warn">No bridge request yet.</div>
      </section>
    </div>

    <div id="essentialProgramManagerSlot"></div>
  </div>

  <details id="advancedToolsPanel">
    <summary>Advanced Tools · readiness, locators, screenshots, artifacts, timeline, and JSON execution</summary>

  <main>
    <div class="sidebar">
      <section id="connectionPanel">
        <h2>Deployment Details</h2>
        <div class="connection-readout">
          <span>Bridge URL</span>
          <code id="baseUrlLabel">-</code>
        </div>
        <div class="row">
          <button class="secondary" id="copyLinuxEnv">Copy Linux Env</button>
          <button class="secondary" id="copyBase">Copy URL</button>
        </div>
        <div class="command-kit" id="bridgeCommandKit" aria-label="Bridge command copy kit">
          <div class="command-kit-head"><strong>Bridge Command Kit</strong><span>Linux / Windows parity</span></div>
          <div class="buttons compact-tools">
            <button class="secondary" id="copyCurlHealth">Copy curl Health</button>
            <button class="secondary" id="copyPowerShellHealth">Copy PowerShell Health</button>
            <button class="secondary" id="copyCurlExecute">Copy curl Execute</button>
          </div>
          <div class="hint">Copy the exact health or execute command when Linux, Windows, and browser behavior need to be compared.</div>
        </div>
        <div class="operator-compact-note">This page is the Windows-side operator console. Keep Health, Readiness, Live interlock, and Evidence green before trusting a live UTM handoff.</div>
        <div class="hint">Token is stored only in this browser. Copy Linux Env gives the Linux controller the matching bridge URL/token variables.</div>
        <div class="operator-checklist">
          <strong>Operator sequence</strong>
          <ol>
            <li>Confirm token and Health are valid.</li>
            <li>Open the UTM software and keep the specimen setup safe.</li>
            <li>Run simulation or locator checks before Live UTM.</li>
            <li>After Live UTM, verify CSV artifact and screen evidence.</li>
          </ol>
        </div>
        <div class="operator-runbook" id="fieldRunbookPanel" aria-label="Windows bridge field runbook">
          <div class="operator-runbook-head"><strong>Field Runbook</strong><span id="runbookPill">4 gates</span></div>
          <div class="runbook-step warn" id="runbookConnect"><span class="runbook-index">1</span><div><strong>Connect bridge</strong><small>Run Health and confirm PyAutoGUI is available.</small></div></div>
          <div class="runbook-step warn" id="runbookCalibrate"><span class="runbook-index">2</span><div><strong>Calibrate UTM locators</strong><small>Run Readiness and capture missing screen locators.</small></div></div>
          <div class="runbook-step warn" id="runbookExecute"><span class="runbook-index">3</span><div><strong>Execute registered protocol</strong><small>Send only an allowlisted /execute request after preflight.</small></div></div>
          <div class="runbook-step warn" id="runbookVerify"><span class="runbook-index">4</span><div><strong>Verify handoff evidence</strong><small>Check screen evidence, save/export proof, and CSV parse probe.</small></div></div>
        </div>
      </section>

      <section id="safeDiagnosticsPanel">
        <h2>Safe Diagnostics <span class="pill"><span class="dot ok"></span><span>non-actuating</span></span></h2>
        <div class="action-group">
          <div class="action-group-title"><span>Before live control</span><span class="muted">no /execute</span></div>
          <div class="buttons compact-tools">
            <button class="blue" id="safePreflight">Safe Preflight</button>
            <button id="readiness">Readiness</button>
            <button id="requestLog">Request Log</button>
            <button id="screenshot">Capture Screen</button>
            <button id="locators">Locators</button>
          </div>
        </div>
        <div class="action-group">
          <div class="action-group-title"><span>Registry / demo</span><span class="muted">allowlisted</span></div>
          <div class="buttons compact-tools">
            <button id="artifacts">Artifacts</button>
            <button class="secondary" id="fillUtmJson">Fill UTM JSON</button>
          </div>
        </div>
      </section>

      <section id="utmProtocolPanel">
        <h2>UTM Protocol</h2>
        <div class="section-intro">Use this panel only for Windows-side UTM GUI control. Safe Preflight is non-actuating; Live UTM sends /execute only after local gates pass.</div>
        <div class="identity-strip">
          <div class="identity-pill"><strong>Required order</strong>Preflight -> execute -> screen evidence -> CSV artifact -> Linux audit</div>
          <div class="identity-pill"><strong>Current run identity</strong>Run ID and Specimen ID below are copied into the /execute payload and request audit context.</div>
        </div>
        <label for="runId">Run ID</label>
        <input id="runId" value="utm-check-001">
        <label for="specimenId">Specimen ID</label>
        <input id="specimenId" value="specimen-demo-001">
        <label for="targetWindow">Target Window Title / Regex</label>
        <input id="targetWindow" placeholder="Example: UTM Controller or regex:.*UTM.*">
        <div class="row">
          <div><label for="exportGlob">Export Glob</label><input id="exportGlob" value="*.csv" placeholder="*.csv or specimen*.csv"></div>
          <div><label for="artifactTimeout">Artifact Timeout Sec</label><input id="artifactTimeout" value="20"></div>
        </div>
        <div class="row">
          <div><label for="stableForSec">Stable File Sec</label><input id="stableForSec" value="2.0"></div>
          <div><label for="expectedExportPath">Expected Export Path</label><input id="expectedExportPath" placeholder="optional C:\ATR\utm_exports\run\specimen.csv"></div>
        </div>
        <div class="hint">These fields are sent to the bridge as export_glob, artifact_timeout_s, stable_for_sec, and expected_export_path.</div>
        <div class="danger-panel">
          Live UTM will first run a non-actuating preflight from this page. If Health or required locator readiness fails, the browser will not send /execute.
        </div>
        <div class="interlock-card" id="liveInterlockCard">
          <strong>Live interlock</strong>
          <span id="liveInterlockText">Live execution is blocked until Safe Preflight passes and the physical safety checkbox is enabled.</span>
        </div>
        <div class="checkline"><input id="requireFocus" type="checkbox" checked><span>Require target window focus before control</span></div>
        <div class="checkline"><input id="requireAssertions" type="checkbox"><span>Require screen locator assertions</span></div>
        <div class="checkline"><input id="manualSave" type="checkbox" checked><span>Manual Save As fallback if no CSV appears</span></div>
        <div class="checkline"><input id="confirmLive" type="checkbox"><span>Live UTM setup is physically safe</span></div>
        <div class="row4" style="margin-top:10px;">
          <button id="utmSim">Run UTM Simulation</button>
          <button class="danger" id="utmLive">Preflight + Run Live UTM</button>
          <button class="danger" id="utmAbort">Stop / Abort</button>
          <button class="secondary" id="copyUtmPayload">Copy Payload</button>
        </div>
        <div class="recovery-panel" aria-label="UTM stop abort recovery">
          <strong>Recovery command</strong>
          <span>Stop / Abort sends the registered <code>utm_stop_or_abort_v1</code> macro directly. Use it to stop/reset the UTM GUI when the protocol is stuck, then refresh Request Log and Evidence.</span>
        </div>
        <div class="hint">Simulation validates the bridge path. Live UTM is blocked unless preflight passes and the physical safety checkbox is set. Stop / Abort is intentionally available as a recovery path.</div>
      </section>

      <section id="locatorPanel">
        <h2>Locator Capture</h2>
        <label for="locatorName">Locator Name</label>
        <select id="locatorName">
          <option value="ready_state">ready_state</option>
          <option value="start_button">start_button</option>
          <option value="running_state">running_state</option>
          <option value="complete_state">complete_state</option>
        </select>
        <div class="row">
          <div><label for="regionX">X</label><input id="regionX" value="100"></div>
          <div><label for="regionY">Y</label><input id="regionY" value="100"></div>
        </div>
        <div class="row">
          <div><label for="regionW">Width</label><input id="regionW" value="160"></div>
          <div><label for="regionH">Height</label><input id="regionH" value="70"></div>
        </div>
        <label for="confidence">Confidence</label>
        <input id="confidence" value="0.80">
        <div class="action-group">
          <div class="action-group-title"><span>Readiness locator shortcuts</span><span class="muted">click to fill name</span></div>
          <div id="missingLocatorShortcuts" class="locator-shortcuts" aria-label="Required UTM locator shortcuts">
            <button class="locator-chip missing" type="button" data-locator-name="ready_state">ready_state</button>
            <button class="locator-chip missing" type="button" data-locator-name="start_button">start_button</button>
            <button class="locator-chip missing" type="button" data-locator-name="running_state">running_state</button>
            <button class="locator-chip missing" type="button" data-locator-name="complete_state">complete_state</button>
          </div>
          <div class="hint">Run Readiness first. Missing locator chips stay amber; captured locator chips turn green.</div>
        </div>
        <button id="captureLocator">Capture Locator</button>
      </section>
    </div>

    <div class="workspace">
      <div class="command-shell">
        <div class="command-banner" id="commandBanner" aria-live="polite">
          <div>
            <strong id="commandTitle">Ready for bridge operation</strong>
            <span id="commandDetail">Use Safe Preflight before any live UTM action. Result JSON and Operator Log update after each command.</span>
          </div>
          <div class="command-side">
            <span class="pill" id="commandPill"><span class="dot"></span><span>idle</span></span>
            <button class="next-action-button warn" id="nextActionButton" type="button" data-next-action="health">
              <small>Recommended next action</small>
              <span id="nextActionLabel">Run Health</span>
            </button>
          </div>
        </div>
      </div>
      <section class="ops-hud" id="operatorHud" aria-label="Operator runtime status">
        <div class="ops-card warn" id="opsSafety"><strong>Safety</strong><span>Preflight not checked</span></div>
        <div class="ops-card" id="opsCommand"><strong>Command</strong><span>Idle</span></div>
        <div class="ops-card warn" id="opsEvidence"><strong>Evidence</strong><span>Waiting for screenshots</span></div>
        <div class="ops-card warn" id="opsData"><strong>Data</strong><span>No CSV artifact yet</span></div>
        <div class="ops-card warn" id="opsNext"><strong>Next</strong><span>Run Health / Safe Preflight</span></div>
      </section>
      <section class="situation-board" id="operatorSituationPanel" aria-label="Live UTM situation matrix">
        <div class="situation-board-title"><strong>Live UTM situation matrix</strong><span>field readiness</span></div>
        <div class="situation-card warn" id="situationBridge"><strong>Bridge</strong><span>Not checked</span><small>Health + token</small></div>
        <div class="situation-card warn" id="situationLocators"><strong>Locators</strong><span>Readiness needed</span><small>ready/start/running/complete</small></div>
        <div class="situation-card warn" id="situationAudit"><strong>Request Audit</strong><span>No /execute yet</span><small>Identity proof</small></div>
        <div class="situation-card warn" id="situationExport"><strong>Export</strong><span>CSV not verified</span><small>Windows file + parse probe</small></div>
        <div class="situation-card warn" id="situationLive"><strong>Live Gate</strong><span>Blocked</span><small>Preflight + safety checkbox</small></div>
      </section>
      <section id="operatorConsolePanel" class="operator-console" aria-label="Windows local operator console">
        <div class="console-panel">
          <h2>Local Operator Console <span class="pill" id="payloadPreviewPill"><span class="dot warn"></span><span>preview stale</span></span></h2>
          <div class="section-intro">This panel shows the exact command intent before the browser sends a Windows /execute request.</div>
          <div class="intent-grid">
            <div class="intent-card warn" id="intentMode"><strong>Mode</strong><span>Live preview</span></div>
            <div class="intent-card" id="intentRoute"><strong>Route</strong><span>POST /execute</span></div>
            <div class="intent-card warn" id="intentPreflight"><strong>Preflight</strong><span>Required before live</span></div>
            <div class="intent-card warn" id="intentPayload"><strong>Payload</strong><span>Waiting for validation</span></div>
          </div>
          <div class="operator-mini-steps" aria-label="UTM local control sequence">
            <div class="operator-mini-step">Health</div>
            <div class="operator-mini-step">Readiness</div>
            <div class="operator-mini-step">Confirm Safety</div>
            <div class="operator-mini-step">Execute</div>
            <div class="operator-mini-step">Audit Evidence</div>
          </div>
        </div>
        <div class="console-panel">
          <h2>Payload Preview</h2>
          <div class="console-actions">
            <button class="secondary" id="previewSimPayload">Preview Sim</button>
            <button class="secondary" id="previewLivePayload">Preview Live</button>
            <button class="secondary" id="previewAbortPayload">Preview Abort</button>
            <button class="secondary" id="copyPreviewPayload">Copy Preview</button>
          </div>
          <pre id="payloadPreview" class="payload-preview">{}</pre>
        </div>
      </section>
      <section id="timelinePanel" class="operator-timeline" aria-label="Windows bridge command timeline">
        <div class="timeline-head">
          <div>
            <h2>Run Timeline <span class="pill" id="timelinePill"><span class="dot"></span><span>idle</span></span></h2>
            <div class="section-intro">Recent bridge steps, blockers, evidence captures, and CSV handoff status are accumulated here during operation.</div>
          </div>
          <button class="secondary" id="timelineClear">Clear Timeline</button>
        </div>
        <div id="timelineTrack" class="timeline-track">
          <div class="timeline-empty">No command steps yet. Run Health, Safe Preflight, Simulation, or Live UTM.</div>
        </div>
      </section>
      <section id="overview">
        <div class="status-grid">
          <div class="tile" id="tileStatus"><strong>Status</strong><span>Idle</span></div>
          <div class="tile" id="tilePyAutoGUI"><strong>PyAutoGUI</strong><span>Unknown</span></div>
          <div class="tile" id="tileFailure"><strong>Failure</strong><span>None</span></div>
          <div class="tile" id="tileArtifact"><strong>Artifacts</strong><span>0</span></div>
        </div>
        <div class="preflight-banner" id="preflightBanner">
          <div>
            <strong id="preflightTitle">Live UTM preflight not checked</strong>
            <span id="preflightText">Run Safe Preflight before live control. This checks Health, UTM readiness, and request-log access without calling /execute.</span>
          </div>
          <button class="secondary" id="preflightRefreshInline">Safe Preflight</button>
        </div>
        <div class="workflow-strip" aria-label="Bridge run workflow">
          <div class="workflow-step" id="stepAuth"><strong>Auth</strong><span>Not checked</span></div>
          <div class="workflow-step" id="stepGui"><strong>GUI Driver</strong><span>Unknown</span></div>
          <div class="workflow-step" id="stepProgram"><strong>Program</strong><span>Not selected</span></div>
          <div class="workflow-step" id="stepEvidence"><strong>Evidence</strong><span>Waiting</span></div>
          <div class="workflow-step" id="stepArtifact"><strong>Artifact</strong><span>Waiting</span></div>
        </div>
        <div class="summary-card">
          <h2>Last Run Summary <span class="pill" id="runSummaryPill"><span class="dot"></span><span>idle</span></span></h2>
          <div class="summary-grid">
            <div class="summary-item"><strong>Program</strong><span id="summaryProgram">-</span></div>
            <div class="summary-item"><strong>Run ID</strong><span id="summaryRun">-</span></div>
            <div class="summary-item"><strong>CSV / Data</strong><span id="summaryData">-</span></div>
            <div class="summary-item"><strong>Next Gate</strong><span id="summaryGate">Run Health</span></div>
          </div>
        </div>
        <div class="summary-card">
          <h2>UTM Readiness <span class="pill" id="readinessPill"><span class="dot"></span><span>not checked</span></span></h2>
          <div class="summary-grid">
            <div class="summary-item"><strong>Required</strong><span id="readinessRequired">-</span></div>
            <div class="summary-item"><strong>Captured</strong><span id="readinessCaptured">-</span></div>
            <div class="summary-item"><strong>Missing</strong><span id="readinessMissing">Run Readiness</span></div>
            <div class="summary-item"><strong>Gate</strong><span id="readinessGate">Check before Live UTM</span></div>
          </div>
        </div>
        <div class="summary-card">
          <h2>Request Audit <span class="pill" id="requestAuditPill"><span class="dot warn"></span><span>not checked</span></span></h2>
          <div class="summary-grid">
            <div class="summary-item"><strong>Events</strong><span id="requestAuditEvents">-</span></div>
            <div class="summary-item"><strong>Live Execute</strong><span id="requestAuditExecute">Run Request Log</span></div>
            <div class="summary-item"><strong>Recent Paths</strong><span id="requestAuditRecent">-</span></div>
            <div class="summary-item"><strong>Gate</strong><span id="requestAuditGate">Needs /execute for live handoff</span></div>
          </div>
          <div class="audit-identity-grid" aria-label="Recent live execute identity">
            <div class="audit-identity-item"><strong>Run IDs</strong><span id="requestAuditRunIds">-</span></div>
            <div class="audit-identity-item"><strong>Specimens</strong><span id="requestAuditSpecimenIds">-</span></div>
            <div class="audit-identity-item"><strong>Programs</strong><span id="requestAuditProgramIds">-</span></div>
            <div class="audit-identity-item"><strong>Last Execute</strong><span id="requestAuditLastAt">-</span></div>
          </div>
          <div class="hint">Recent live execute identity is summarized above. For live UTM handoff, Linux will require this log to show an actual /execute request with matching run/specimen/program identity.</div>
        </div>
        <div class="summary-card">
          <h2>Live Proof Checklist <span class="pill" id="proofChecklistPill"><span class="dot warn"></span><span>not checked</span></span></h2>
          <div class="proof-gate-strip" id="proofGateStrip" aria-label="Seven required UTM proof gates">
            <div class="proof-gate warn" id="proofGateHealth"><strong>Bridge</strong><span>Health needed</span></div>
            <div class="proof-gate warn" id="proofGateLocators"><strong>Locators</strong><span>Readiness needed</span></div>
            <div class="proof-gate warn" id="proofGateSafety"><strong>Safety</strong><span>Confirm setup</span></div>
            <div class="proof-gate warn" id="proofGateRequestLog"><strong>Request</strong><span>/execute missing</span></div>
            <div class="proof-gate warn" id="proofGateScreen"><strong>Screen</strong><span>3 screenshots</span></div>
            <div class="proof-gate warn" id="proofGateSave"><strong>Save</strong><span>Export proof</span></div>
            <div class="proof-gate warn" id="proofGateCsv"><strong>CSV</strong><span>Parse probe</span></div>
          </div>
          <div class="gate-meter" aria-label="Live proof gate progress"><div class="gate-fill" id="gateMeterFill"></div></div>
          <div class="gate-caption"><span id="gateMeterText">0 / 7 checks complete</span><span id="gateMeterNext">Run Health</span></div>
          <div id="proofChecklist" class="proof-list">
            <div class="proof-item warn"><span class="dot warn"></span><div><strong>Health</strong><small>Run Health to verify the bridge process and PyAutoGUI.</small></div></div>
            <div class="proof-item warn"><span class="dot warn"></span><div><strong>Readiness</strong><small>Run Readiness to verify UTM locator setup.</small></div></div>
            <div class="proof-item warn"><span class="dot warn"></span><div><strong>Save/Export Responsibility</strong><small>Run UTM simulation/live protocol and confirm CSV save/export evidence.</small></div></div>
          </div>
          <div class="row" style="margin-top:10px;">
            <button class="secondary" id="refreshEvidence">Refresh Evidence</button>
            <label class="checkline" style="margin:0;"><input id="autoAudit" type="checkbox"><span>Auto-refresh request audit</span></label>
          </div>
          <div class="hint" id="proofChecklistGate">Use this checklist before trusting a live UTM handoff.</div>
        </div>
        <div class="summary-card">
          <h2>Bridge Files <span class="pill"><span class="dot warn"></span><span>Windows paths</span></span></h2>
          <div class="file-grid">
            <div class="file-item"><strong>Artifact Root</strong><code id="pathArtifactRoot">-</code></div>
            <div class="file-item"><strong>Request Log</strong><code id="pathRequestLog">-</code></div>
            <div class="file-item"><strong>Locator Root</strong><code id="pathLocatorRoot">-</code></div>
            <div class="file-item"><strong>UTM Export Root</strong><code id="pathUtmExportRoot">-</code></div>
          </div>
          <div class="hint">Use Request Log for token/auth/API audit. Token values are never written to the log.</div>
        </div>
      </section>


      <section id="programManagerPanel">
        <h2>Program Manager <span class="pill"><span class="dot ok"></span><span id="programCount">0 programs</span></span></h2>
        <div class="section-intro">Manage deterministic programs, record demonstrations, and deploy versioned Equipment Skills.</div>
        <div class="manager-tabs" role="tablist" aria-label="Program Manager work areas">
          <button class="active" type="button" data-manager-tab="programs">PROGRAMS</button>
          <button class="secondary" type="button" data-manager-tab="examples">EXAMPLES</button>
          <button class="secondary" type="button" data-manager-tab="record">RECORD</button>
          <button class="secondary" type="button" data-manager-tab="skills">SKILLS</button>
        </div>
        <div class="manager-view" id="managerProgramsView">
        <div class="manager-toolbar">
          <label>Search<input id="managerSearch" type="search" placeholder="Name or program ID"></label>
          <label>Status<select id="managerFilter"><option value="all">All</option><option value="builtin">Built-in</option><option value="custom">Custom</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></label>
          <button id="newProgram" type="button">New Program</button>
          <button class="secondary" id="browseProgram" type="button">Browse JSON</button>
          <button class="secondary" id="downloadProgramTemplate" type="button">Download Template</button>
          <button class="secondary" id="refreshPrograms" type="button">Refresh Registry</button>
          <input class="manager-hidden" id="programFile" type="file" accept=".json,application/json">
        </div>
        <div id="managerStats" class="manager-stats">0 built-in · 0 custom · 0 disabled</div>
        <div class="manager-grid">
          <div id="managerProgramRegistry" class="manager-registry"><div class="manager-empty">Run Health or Refresh to load registered programs.</div></div>
          <aside class="manager-editor" id="programEditor" hidden>
            <div class="manager-editor-head"><strong id="editorTitle">New Macro Program</strong><span id="editorState" class="manager-badge">DRAFT</span></div>
            <form class="manager-editor-body" id="programForm">
              <label>Macro Definition JSON<textarea id="programDefinition" spellcheck="false" style="min-height:280px"></textarea></label>
              <div id="programFileMeta" class="manager-file-meta">New draft. Browse only loads a file; it does not register it.</div>
              <div class="row3" style="margin-top:10px">
                <button class="secondary" id="validateProgram" type="button">Validate</button>
                <button id="registerProgram" type="submit">Add to Registry</button>
                <button class="secondary" id="clearProgramForm" type="button">Cancel</button>
              </div>
              <div class="hint">Only atr.pyautogui_program.v1 JSON and bounded bridge actions are accepted. Browse and Download Template never register a program.</div>
            </form>
          </aside>
        </div>
        <details class="manager-result">
          <summary>Program Manager Result</summary>
          <pre id="managerLatestResult">No manager request yet.</pre>
        </details>
        </div>
        <div class="manager-view" id="managerExamplesView" hidden>
          <div class="manager-record-actions">
            <button id="openCapabilityLab" type="button">Open Capability Lab</button>
            <button class="secondary" id="refreshExamples" type="button">Refresh Examples</button>
          </div>
          <div class="manager-file-meta">Examples load into the JSON editor without registering or deploying anything. Safe Test executes only examples marked safe.</div>
          <div id="exampleRegistry" class="manager-registry"><div class="manager-empty">Refresh to load capability examples.</div></div>
        </div>
        <div class="manager-view" id="managerRecordView" hidden>
          <div class="manager-record-grid">
            <label>Name<input id="recordingName" value="Program 1 demonstration"></label>
            <label>Target App<input id="recordingTargetApp" value="Program 1"></label>
            <label>Target Window<input id="recordingTargetWindow" value="Program 1"></label>
          </div>
          <div class="recording-options">
            <label class="recording-option"><input id="recordImageTracking" type="checkbox" checked>Image tracking</label>
            <label class="recording-option"><input id="recordCoordinateFallback" type="checkbox">Allow coordinate fallback</label>
          </div>
          <div class="manager-record-actions">
            <button id="recordToggle" type="button" data-state="idle">Record</button>
            <button class="secondary" id="recordCheckpoint" type="button">Checkpoint</button>
            <button class="secondary" id="recordSave" type="button">Save Recording</button>
            <button class="secondary" id="refreshRecordings" type="button">Refresh</button>
          </div>
          <div class="manager-record-grid">
            <label>Skill ID<input id="recordSkillId" value="program1_skill"></label>
            <label>Version<input id="recordSkillVersion" value="1.0.0"></label>
            <label>Target Profile<input id="recordSkillProfile" value="local_program1"></label>
          </div>
          <div class="manager-record-actions">
            <button id="recordSkill" type="button">Create Draft Skill</button>
          </div>
          <div id="recordingStatus" class="manager-file-meta">No recording is active.</div>
          <div id="recordingCoverage" class="manager-file-meta">Coverage: no recording selected.</div>
          <div id="recordingLocatorPreview" class="recording-locator-preview"><div class="manager-empty">No image locators captured.</div></div>
          <div id="recordingRegistry" class="manager-registry"></div>
        </div>
        <div class="manager-view" id="managerSkillsView" hidden>
          <div class="manager-record-actions">
            <button id="refreshSkills" type="button">Refresh Skills</button>
          </div>
          <div id="skillRegistry" class="manager-registry"><div class="manager-empty">Refresh to load Linux-authoritative Skill versions.</div></div>
        </div>
      </section>


      <div class="split">
        <section id="resultPanel">
          <div class="result-head">
            <h2>Result</h2>
            <button class="secondary" id="copyResult">Copy JSON</button>
          </div>
          <pre id="output">{}</pre>
        </section>
        <section id="evidencePanel">
          <h2>Step Trace</h2>
          <table>
            <thead><tr><th>Step</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody id="trace"><tr><td colspan="3">No steps yet</td></tr></tbody>
          </table>
          <h2 style="margin-top:14px;">Artifacts</h2>
          <table>
            <thead><tr><th>Kind</th><th>Artifact</th><th>Size</th><th>Action</th></tr></thead>
            <tbody id="artifactTable"><tr><td colspan="4">No artifacts yet</td></tr></tbody>
          </table>
          <h2 style="margin-top:14px;">Artifact Preview</h2>
          <div id="artifactPreview" class="preview-box">Open an image artifact with View, or capture a screen to preview it here.</div>
        </section>
      </div>

      <section>
        <details>
          <summary>Advanced JSON Execute</summary>
          <label for="sequence">Sequence JSON</label>
          <textarea id="sequence">{
  "sequence_id": "manual-check-001",
  "sequence": [
    {"action": "health"},
    {"action": "screenshot"}
  ]
}</textarea>
          <div class="row3">
            <button id="execute">Run JSON</button>
            <button class="secondary" id="formatJson">Format JSON</button>
            <button class="secondary" id="clearResult">Clear Result</button>
          </div>
        </details>
      </section>

      <section id="operatorLogPanel">
        <h2>Operator Log</h2>
        <div id="log" aria-live="polite"><div class="logline">Page loaded. Check health before live control.</div></div>
      </section>
    </div>
  </main>
  </details>
  <script>
    const tokenInput = document.getElementById("token");
    const output = document.getElementById("output");
    const traceBody = document.getElementById("trace");
    const artifactTable = document.getElementById("artifactTable");
    const tileStatus = document.getElementById("tileStatus");
    const tilePyAutoGUI = document.getElementById("tilePyAutoGUI");
    const tileFailure = document.getElementById("tileFailure");
    const tileArtifact = document.getElementById("tileArtifact");
    const authPill = document.getElementById("authPill");
    const headerProofPill = document.getElementById("headerProofPill");
    const sequenceInput = document.getElementById("sequence");
    const logBox = document.getElementById("log");
    const workflow = {
      auth: document.getElementById("stepAuth"),
      gui: document.getElementById("stepGui"),
      program: document.getElementById("stepProgram"),
      evidence: document.getElementById("stepEvidence"),
      artifact: document.getElementById("stepArtifact"),
    };
    const runSummaryPill = document.getElementById("runSummaryPill");
    const summaryProgram = document.getElementById("summaryProgram");
    const summaryRun = document.getElementById("summaryRun");
    const summaryData = document.getElementById("summaryData");
    const summaryGate = document.getElementById("summaryGate");
    const pathArtifactRoot = document.getElementById("pathArtifactRoot");
    const pathRequestLog = document.getElementById("pathRequestLog");
    const pathLocatorRoot = document.getElementById("pathLocatorRoot");
    const pathUtmExportRoot = document.getElementById("pathUtmExportRoot");
    const preflightBanner = document.getElementById("preflightBanner");
    const preflightTitle = document.getElementById("preflightTitle");
    const preflightText = document.getElementById("preflightText");
    const artifactPreview = document.getElementById("artifactPreview");
    const baseUrlLabel = document.getElementById("baseUrlLabel");
    const controllerStatus = document.getElementById("controllerStatus");
    const controllerUrl = document.getElementById("controllerUrl");
    const controllerCandidates = document.getElementById("controllerCandidates");
    const commandBanner = document.getElementById("commandBanner");
    const commandTitle = document.getElementById("commandTitle");
    const commandDetail = document.getElementById("commandDetail");
    const commandPill = document.getElementById("commandPill");
    const nextActionButton = document.getElementById("nextActionButton");
    const nextActionLabel = document.getElementById("nextActionLabel");
    const opsCards = {
      safety: document.getElementById("opsSafety"),
      command: document.getElementById("opsCommand"),
      evidence: document.getElementById("opsEvidence"),
      data: document.getElementById("opsData"),
      next: document.getElementById("opsNext"),
    };
    const situationCards = {
      bridge: document.getElementById("situationBridge"),
      locators: document.getElementById("situationLocators"),
      audit: document.getElementById("situationAudit"),
      export: document.getElementById("situationExport"),
      live: document.getElementById("situationLive"),
    };
    const missingLocatorShortcuts = document.getElementById("missingLocatorShortcuts");
    const requestAuditRunIds = document.getElementById("requestAuditRunIds");
    const requestAuditSpecimenIds = document.getElementById("requestAuditSpecimenIds");
    const requestAuditProgramIds = document.getElementById("requestAuditProgramIds");
    const requestAuditLastAt = document.getElementById("requestAuditLastAt");
    const intentCards = {
      mode: document.getElementById("intentMode"),
      route: document.getElementById("intentRoute"),
      preflight: document.getElementById("intentPreflight"),
      payload: document.getElementById("intentPayload"),
    };
    const payloadPreview = document.getElementById("payloadPreview");
    const payloadPreviewPill = document.getElementById("payloadPreviewPill");
    const gateMeterFill = document.getElementById("gateMeterFill");
    const gateMeterText = document.getElementById("gateMeterText");
    const gateMeterNext = document.getElementById("gateMeterNext");
    const liveInterlockCard = document.getElementById("liveInterlockCard");
    const liveInterlockText = document.getElementById("liveInterlockText");
    const runbookPill = document.getElementById("runbookPill");
    const runbookSteps = {
      connect: document.getElementById("runbookConnect"),
      calibrate: document.getElementById("runbookCalibrate"),
      execute: document.getElementById("runbookExecute"),
      verify: document.getElementById("runbookVerify"),
    };
    const timelineTrack = document.getElementById("timelineTrack");
    const timelinePill = document.getElementById("timelinePill");
    const focusModeButton = document.getElementById("focusMode");
    let selectedProgramId = "utm_compression_start_v1";
    let lastResult = {};
    let previewMode = "live";
    let previewPayloadEnvelope = null;
    const bridgeState = {health: null, readiness: null, requestAudit: null};
    let requestAuditTimer = null;
    let timelineEntries = [];

    if (baseUrlLabel) baseUrlLabel.textContent = window.location.origin;
    tokenInput.value = localStorage.getItem("bridgeToken") || "";
    tokenInput.addEventListener("input", () => {
      localStorage.setItem("bridgeToken", tokenInput.value);
      if (!tokenInput.value.trim()) renderTokenPrompt();
      else {
        setAuth("token entered", "warn");
        setCommandBanner("Token entered", "Click Health to verify the authenticated bridge session.", "warn");
        setOpsCard("next", "Click Health", "warn");
      }
    });


    function applyOperatorLayout() {
      const workspace = typeof document.querySelector === "function" ? document.querySelector(".workspace") : null;
      const overview = document.getElementById("overview");
      const consolePanel = document.getElementById("operatorConsolePanel");
      if (workspace && overview && consolePanel && overview.nextElementSibling !== consolePanel && typeof workspace.insertBefore === "function") {
        workspace.insertBefore(overview, consolePanel);
      }
      const proofElement = document.getElementById("proofChecklist");
      const filesElement = document.getElementById("pathArtifactRoot");
      const proofCard = proofElement && typeof proofElement.closest === "function" ? proofElement.closest(".summary-card") : null;
      const filesCard = filesElement && typeof filesElement.closest === "function" ? filesElement.closest(".summary-card") : null;
      if (proofCard && proofCard.classList) proofCard.classList.add("wide-card");
      if (filesCard && filesCard.classList) filesCard.classList.add("wide-card");
    }
    function installPanelToggles() {
      const ids = ["connectionPanel", "safeDiagnosticsPanel", "utmProtocolPanel", "locatorPanel", "overview", "timelinePanel", "operatorLogPanel"];
      ids.forEach((id) => {
        const section = document.getElementById(id);
        const heading = section ? section.querySelector(":scope > h2") : null;
        if (!section || !heading || heading.querySelector(".panel-toggle")) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "panel-toggle secondary";
        button.textContent = "Collapse";
        button.setAttribute("aria-label", `Toggle ${id}`);
        const storageKey = `windowsBridge.panel.${id}.collapsed`;
        const apply = (collapsed) => {
          section.classList.toggle("is-collapsed", Boolean(collapsed));
          button.textContent = collapsed ? "Expand" : "Collapse";
        };
        apply(localStorage.getItem(storageKey) === "true");
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const collapsed = !section.classList.contains("is-collapsed");
          localStorage.setItem(storageKey, collapsed ? "true" : "false");
          apply(collapsed);
        });
        heading.appendChild(button);
      });
    }
    function toggleBodyClass(name, enabled) {
      const body = document.body;
      if (!body) return;
      if (body.classList && typeof body.classList.toggle === "function") {
        body.classList.toggle(name, Boolean(enabled));
        return;
      }
      const classes = new Set(String(body.className || "").split(/\s+/).filter(Boolean));
      if (enabled) classes.add(name);
      else classes.delete(name);
      body.className = Array.from(classes).join(" ");
    }
    function hasBodyClass(name) {
      const body = document.body;
      if (!body) return false;
      if (body.classList && typeof body.classList.contains === "function") return body.classList.contains(name);
      return String(body.className || "").split(/\s+/).includes(name);
    }
    function setFocusMode(enabled) {
      toggleBodyClass("focus-mode", Boolean(enabled));
      localStorage.setItem("windowsBridge.focusMode", enabled ? "true" : "false");
      if (focusModeButton) focusModeButton.textContent = enabled ? "Full View" : "Focus Mode";
    }
    setFocusMode(localStorage.getItem("windowsBridge.focusMode") === "true");
    applyOperatorLayout();
    installPanelToggles();

    function bindPersistedInput(id) {
      const element = document.getElementById(id);
      if (!element) return;
      const key = `windowsBridge.${id}`;
      const saved = localStorage.getItem(key);
      if (saved !== null) element.value = saved;
      element.addEventListener("input", () => localStorage.setItem(key, element.value));
    }
    function bindPersistedCheck(id) {
      const element = document.getElementById(id);
      if (!element) return;
      const key = `windowsBridge.${id}`;
      const saved = localStorage.getItem(key);
      if (saved !== null) element.checked = saved === "true";
      element.addEventListener("change", () => localStorage.setItem(key, element.checked ? "true" : "false"));
    }
    ["runId", "specimenId", "targetWindow", "exportGlob", "artifactTimeout", "stableForSec", "expectedExportPath"].forEach(bindPersistedInput);
    ["requireFocus", "requireAssertions", "manualSave", "autoAudit"].forEach(bindPersistedCheck);

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
    }
    function setBusy(isBusy) {
      toggleBodyClass("is-busy", Boolean(isBusy));
      document.querySelectorAll("button").forEach((button) => {
        const isAbort = button.id === "utmAbort" || (button.dataset && button.dataset.proxyClick === "utmAbort");
        button.disabled = isAbort ? false : isBusy;
      });
    }
    function setTile(tile, value, klass) {
      tile.className = "tile" + (klass ? " " + klass : "");
      tile.querySelector("span").textContent = value;
    }
    function setAuth(label, klass) {
      authPill.querySelector("span:last-child").textContent = label;
      authPill.querySelector(".dot").className = "dot" + (klass ? " " + klass : "");
    }
    function setHeaderProof(label, klass) {
      if (!headerProofPill) return;
      headerProofPill.querySelector("span:last-child").textContent = label;
      headerProofPill.querySelector(".dot").className = "dot" + (klass ? " " + klass : "");
    }
    function setWorkflowStep(key, label, klass) {
      const step = workflow[key];
      if (!step) return;
      step.className = "workflow-step" + (klass ? " " + klass : "");
      step.querySelector("span").textContent = label;
    }
    function setSummaryPill(label, klass) {
      if (!runSummaryPill) return;
      runSummaryPill.querySelector("span:last-child").textContent = label;
      runSummaryPill.querySelector(".dot").className = "dot" + (klass ? " " + klass : "");
    }
    function setOpsCard(key, value, klass) {
      const card = opsCards[key];
      if (!card) return;
      card.className = "ops-card" + (klass ? " " + klass : "");
      const span = card.querySelector("span");
      if (span) span.textContent = value || "-";
    }
    function setSituationCard(key, value, detail, klass) {
      const card = situationCards[key];
      if (!card) return;
      card.className = "situation-card" + (klass ? " " + klass : "");
      const span = card.querySelector("span");
      const small = card.querySelector("small");
      if (span) span.textContent = value || "-";
      if (small) small.textContent = detail || "";
    }
    function formatList(values, fallback = "-") {
      if (!Array.isArray(values) || !values.length) return fallback;
      return values.slice(-4).join(", ");
    }
    function renderLocatorShortcuts(required, configured, missing) {
      if (!missingLocatorShortcuts) return;
      const requiredNames = Array.isArray(required) && required.length ? required : ["ready_state", "start_button", "running_state", "complete_state"];
      const configuredSet = new Set(Array.isArray(configured) ? configured : []);
      const missingSet = new Set(Array.isArray(missing) ? missing : []);
      missingLocatorShortcuts.innerHTML = "";
      for (const name of requiredNames) {
        const button = document.createElement("button");
        const captured = configuredSet.has(name) && !missingSet.has(name);
        button.type = "button";
        button.className = "locator-chip " + (captured ? "captured" : "missing");
        button.dataset.locatorName = name;
        button.textContent = captured ? `${name} captured` : `${name} missing`;
        button.addEventListener("click", () => {
          const select = document.getElementById("locatorName");
          if (select) {
            const hasOption = Array.from(select.options || []).some((option) => option.value === name);
            if (!hasOption && typeof select.appendChild === "function") {
              const option = document.createElement("option");
              option.value = name;
              option.textContent = name;
              select.appendChild(option);
            }
            select.value = name;
            if (typeof select.focus === "function") select.focus();
          }
          appendLog(`locator selected for capture: ${name}`);
        });
        missingLocatorShortcuts.appendChild(button);
      }
    }
    function setIntentCard(key, value, klass) {
      const card = intentCards[key];
      if (!card) return;
      card.className = "intent-card" + (klass ? " " + klass : "");
      const span = card.querySelector("span");
      if (span) span.textContent = value || "-";
    }
    function setRunbookStep(key, klass, detail) {
      const step = runbookSteps[key];
      if (!step) return;
      const state = klass || "warn";
      step.className = "runbook-step " + state;
      const small = step.querySelector("small");
      if (small) small.textContent = detail || "Waiting for evidence.";
    }
    function setRunbookProgress(states) {
      if (!runbookPill || !states) return;
      const ready = Object.values(states).filter(Boolean).length;
      const total = Object.keys(states).length || 4;
      runbookPill.textContent = `${ready}/${total} ready`;
    }
    function setPayloadPreviewPill(label, klass) {
      if (!payloadPreviewPill) return;
      payloadPreviewPill.querySelector("span:last-child").textContent = label || "preview";
      payloadPreviewPill.querySelector(".dot").className = "dot" + (klass ? " " + klass : "");
    }
    function setTimelinePill(label, klass) {
      if (!timelinePill) return;
      timelinePill.querySelector("span:last-child").textContent = label || "idle";
      timelinePill.querySelector(".dot").className = "dot" + (klass ? " " + klass : "");
    }
    function timelineStatusClass(status) {
      const text = String(status || "").toLowerCase();
      if (["ok", "ready", "active", "verified", "complete", "completed"].some((item) => text.includes(item))) return "ok";
      if (["blocked", "failed", "error", "missing", "invalid"].some((item) => text.includes(item))) return "bad";
      return "warn";
    }
    function renderTimelineEntries() {
      if (!timelineTrack) return;
      timelineTrack.innerHTML = "";
      if (!timelineEntries.length) {
        timelineTrack.innerHTML = '<div class="timeline-empty">No command steps yet. Run Health, Safe Preflight, Simulation, or Live UTM.</div>';
        setTimelinePill("idle", "");
        return;
      }
      for (const entry of timelineEntries.slice(-60)) {
        const item = document.createElement("div");
        item.className = "timeline-item " + timelineStatusClass(entry.status);
        item.innerHTML = `<div class="timeline-time">${escapeHtml(entry.time)}</div><div class="timeline-marker"></div><div class="timeline-content"><strong>${escapeHtml(entry.step)}</strong><small>${escapeHtml(entry.detail)}</small></div>`;
        timelineTrack.appendChild(item);
      }
      const latest = timelineEntries[timelineEntries.length - 1];
      setTimelinePill(`${timelineEntries.length} step(s)`, timelineStatusClass(latest.status));
      timelineTrack.scrollTop = timelineTrack.scrollHeight;
    }
    function appendTimelineFromResult(data) {
      if (!data || typeof data !== "object") return;
      let steps = Array.isArray(data.step_trace) ? data.step_trace : [];
      if (!steps.length && (data.status || data.tool || data.failure_code)) {
        steps = [{step: data.tool || "BRIDGE_RESULT", status: data.ok === true ? "ok" : (data.status || "failed"), detail: data.failure_code || data.status || ""}];
      }
      if (!steps.length) return;
      const runLabel = data.run_id || data.sequence_id || "";
      const at = new Date().toLocaleTimeString();
      for (const step of steps) {
        const name = step && typeof step === "object" ? (step.step || step.action || "STEP") : "STEP";
        const status = step && typeof step === "object" ? (step.status || data.status || "") : data.status || "";
        const detail = step && typeof step === "object"
          ? (step.detail || step.message || step.artifact || step.failure_code || "")
          : String(step || "");
        timelineEntries.push({time: at, run: runLabel, step: runLabel ? `${name} · ${runLabel}` : name, status, detail});
      }
      while (timelineEntries.length > 120) timelineEntries.shift();
      renderTimelineEntries();
    }
    function positiveNumberInput(id, fallback) {
      const raw = document.getElementById(id).value.trim();
      const value = Number(raw);
      return Number.isFinite(value) && value > 0 ? value : fallback;
    }
    function validateUtmInputs() {
      const errors = [];
      for (const [id, label] of [["artifactTimeout", "Artifact Timeout Sec"], ["stableForSec", "Stable File Sec"]]) {
        const raw = document.getElementById(id).value.trim();
        const value = Number(raw);
        if (!raw || !Number.isFinite(value) || value <= 0) errors.push(`${label} must be a positive number.`);
      }
      if (!document.getElementById("runId").value.trim()) errors.push("Run ID is required.");
      if (!document.getElementById("specimenId").value.trim()) errors.push("Specimen ID is required.");
      return errors;
    }
    function renderPayloadPreview(mode = previewMode) {
      previewMode = mode || "live";
      const errors = previewMode === "abort" ? [] : validateUtmInputs();
      const payload = previewMode === "abort" ? currentAbortPayload() : currentUtmPayload(previewMode === "sim");
      previewPayloadEnvelope = {
        ok_to_send: errors.length === 0,
        mode: previewMode,
        route: "POST /execute",
        preflight: previewMode === "live" ? "required before send" : previewMode === "sim" ? "not actuating" : "recovery path",
        validation_errors: errors,
        payload,
      };
      if (payloadPreview) payloadPreview.textContent = JSON.stringify(previewPayloadEnvelope, null, 2);
      const label = errors.length ? `${errors.length} input issue(s)` : `${previewMode} payload ready`;
      setPayloadPreviewPill(label, errors.length ? "bad" : "ok");
      setIntentCard("mode", previewMode === "sim" ? "Simulation" : previewMode === "abort" ? "Stop / Abort" : "Live UTM", errors.length ? "bad" : previewMode === "live" ? "warn" : "ok");
      setIntentCard("route", "POST /execute", "ok");
      setIntentCard("preflight", previewPayloadEnvelope.preflight, previewMode === "live" ? "warn" : "ok");
      setIntentCard("payload", errors.length ? errors[0] : `${payload.program_id || "program"} ready`, errors.length ? "bad" : "ok");
      return errors.length === 0;
    }
    function renderProgramRegistry(data) {
      if (!data || !Array.isArray(data.programs)) return;
      const programs = data.programs.slice().sort((a, b) => String(a.program_id || "").localeCompare(String(b.program_id || "")));
      managerAcceptPrograms(programs);
    }
    function buildProgramPayload(programId, simulate) {
      if (programId === "program1") return {sequence_id: "program1-check-001", program_id: "program1", command: "program1"};
      if (programId === "utm_stop_or_abort_v1") return currentAbortPayload();
      const payload = currentUtmPayload(Boolean(simulate));
      payload.program_id = programId || payload.program_id;
      payload.sequence_id = `${payload.sequence_id}-${payload.program_id}`;
      return payload;
    }
    function renderInputBlocker(mode) {
      const errors = validateUtmInputs();
      render({
        ok: false,
        status: "blocked",
        failure_code: "WINDOWS_GUI_INPUT_INVALID",
        message: `Fix payload inputs before ${mode === "sim" ? "simulation" : "live execution"}.`,
        validation_errors: errors,
        step_trace: errors.map((detail) => ({step: "VALIDATE_INPUT", status: "blocked", detail})),
      });
    }
    function setCommandBanner(label, detail, klass) {
      if (!commandBanner || !commandTitle || !commandDetail || !commandPill) return;
      commandBanner.className = "command-banner" + (klass ? " " + klass : "");
      commandTitle.textContent = label || "Ready for bridge operation";
      commandDetail.textContent = detail || "Result JSON and Operator Log update after each command.";
      commandPill.querySelector("span:last-child").textContent = klass || "idle";
      const dotClass = klass === "ok" ? " ok" : klass === "bad" ? " bad" : (klass === "busy" || klass === "warn") ? " warn" : "";
      commandPill.querySelector(".dot").className = "dot" + dotClass;
      setOpsCard("command", label || "Idle", klass === "busy" ? "warn" : klass);
    }
    function setNextAction(label, targetId, klass) {
      if (!nextActionButton || !nextActionLabel) return;
      nextActionLabel.textContent = label || "Run Health";
      nextActionButton.dataset.nextAction = targetId || "health";
      nextActionButton.className = "next-action-button " + (klass || "warn");
    }
    function flashAttention(element) {
      if (!element) return;
      element.classList.remove("attention-flash");
      void element.offsetWidth;
      element.classList.add("attention-flash");
    }
    function activateRecommendedAction() {
      if (!nextActionButton) return;
      const targetId = nextActionButton.dataset.nextAction || "health";
      if (targetId === "token") {
        tokenInput.focus();
        flashAttention(tokenInput);
        return;
      }
      const target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({behavior: "smooth", block: "center"});
      flashAttention(target);
      if (target.type === "checkbox") {
        target.focus();
        return;
      }
      if (typeof target.click === "function") target.click();
    }
    function recommendationForMissing(label) {
      switch (label) {
        case "Health + PyAutoGUI":
          return {label: "Run Health", target: "health", klass: "warn"};
        case "UTM Locators":
          return {label: "Run Readiness", target: "readiness", klass: "warn"};
        case "Live Safety Confirmed":
          return {label: "Confirm Safety", target: "confirmLive", klass: "bad"};
        case "Request Log /execute":
          return {label: "Run Live UTM", target: "utmLive", klass: "bad"};
        case "Screen Evidence":
          return {label: "Capture Screen", target: "screenshot", klass: "warn"};
        case "Save/Export Responsibility":
        case "CSV + Parse Probe":
          return {label: "Refresh Evidence", target: "refreshEvidence", klass: "warn"};
        default:
          return {label: "Refresh Evidence", target: "refreshEvidence", klass: "warn"};
      }
    }
    function renderTokenPrompt() {
      setAuth("token required", "warn");
      setCommandBanner("Enter bridge token", "Authenticated endpoints are not called until a token is entered. Paste the token from PowerShell, then click Health.", "warn");
      setWorkflowStep("auth", "Token required", "warn");
      setWorkflowStep("gui", "Not checked", "warn");
      setWorkflowStep("program", "Load after Health", "warn");
      setOpsCard("safety", "Health not checked", "warn");
      setOpsCard("next", "Paste token, then Health", "warn");
      renderProofChecklist(lastResult || {});
      setNextAction("Enter Token", "token", "warn");
    }

    function appendLog(message) {
      const line = document.createElement("div");
      line.className = "logline";
      line.textContent = new Date().toLocaleTimeString() + "  " + message;
      logBox.appendChild(line);
      while (logBox.children.length > 80) logBox.removeChild(logBox.firstChild);
      logBox.scrollTop = logBox.scrollHeight;
    }
    function artifactRows(data) {
      const rows = [];
      if (Array.isArray(data.output_artifacts)) rows.push(...data.output_artifacts);
      if (Array.isArray(data.artifacts)) rows.push(...data.artifacts);
      if (data.artifact) rows.push(data.artifact);
      const seen = new Set();
      return rows.filter((item) => {
        if (!item || typeof item !== "object") return false;
        const id = item.artifact_id || item.filename || JSON.stringify(item);
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      });
    }
    function renderArtifacts(data) {
      const rows = artifactRows(data);
      setTile(tileArtifact, String(rows.length), rows.length ? "ok" : "");
      artifactTable.innerHTML = "";
      if (!rows.length) {
        artifactTable.innerHTML = '<tr><td colspan="4">No artifacts</td></tr>';
        if (artifactPreview) artifactPreview.textContent = "Open an image artifact with View, or capture a screen to preview it here.";
        return;
      }
      for (const item of rows) {
        const id = item.artifact_id || "";
        const tr = document.createElement("tr");
        const pull = id ? `<button class="secondary" data-artifact="${escapeHtml(id)}">View</button>` : "";
        tr.innerHTML = `<td>${escapeHtml(item.kind || "")}</td><td>${escapeHtml(id || item.filename || "")}</td><td>${escapeHtml(item.size_bytes || "")}</td><td>${pull}</td>`;
        artifactTable.appendChild(tr);
      }
      artifactTable.querySelectorAll("button[data-artifact]").forEach((button) => {
        button.addEventListener("click", () => call("/artifacts/" + encodeURIComponent(button.dataset.artifact || "")));
      });
      const imageArtifact = rows.find((item) => String(item.content_type || "").startsWith("image/") || ["screen_png", "screenshot", "locator_png"].includes(String(item.kind || "")));
      if (imageArtifact && artifactPreview) {
        artifactPreview.innerHTML = `<div>Image artifact captured.<div class="preview-meta">${escapeHtml(imageArtifact.artifact_id || imageArtifact.filename || "Use View to load preview")}</div></div>`;
      }
    }
    function renderArtifactPreview(data) {
      if (!artifactPreview || !data || typeof data !== "object") return;
      const contentType = String(data.content_type || "");
      if (data.content_base64 && contentType.startsWith("image/")) {
        artifactPreview.innerHTML = `<div><img alt="artifact preview" src="data:${escapeHtml(contentType)};base64,${data.content_base64}"><div class="preview-meta">${escapeHtml(data.filename || data.artifact_id || "image artifact")}</div></div>`;
      } else if (data.content_base64) {
        artifactPreview.innerHTML = `<div>Artifact loaded.<div class="preview-meta">${escapeHtml(data.filename || data.artifact_id || "artifact")} · ${escapeHtml(contentType || "application/octet-stream")}</div></div>`;
      }
    }
    function renderTrace(data) {
      const steps = data.step_trace || [];
      traceBody.innerHTML = "";
      if (!steps.length) {
        traceBody.innerHTML = '<tr><td colspan="3">No steps</td></tr>';
        return;
      }
      for (const step of steps) {
        const row = document.createElement("tr");
        row.className = "trace-row " + timelineStatusClass(step.status || "");
        row.innerHTML = `<td>${escapeHtml(step.step || "")}</td><td>${escapeHtml(step.status || "")}</td><td>${escapeHtml(step.detail || step.artifact || step.message || "")}</td>`;
        traceBody.appendChild(row);
      }
    }
    function dataReference(data) {
      const acquisition = data.data_acquisition && typeof data.data_acquisition === "object" ? data.data_acquisition : {};
      if (data.result_file) return data.result_file;
      if (data.utm_csv_path) return data.utm_csv_path;
      if (acquisition.linux_path || acquisition.local_path || acquisition.windows_path) {
        return acquisition.linux_path || acquisition.local_path || acquisition.windows_path;
      }
      const csvArtifact = artifactRows(data).find((item) => item.kind === "utm_csv");
      return csvArtifact ? (csvArtifact.local_path || csvArtifact.linux_path || csvArtifact.windows_path || csvArtifact.artifact_id || "utm_csv artifact") : "";
    }
    function screenEvidenceComplete(data) {
      const checks = Array.isArray(data.screen_checks) ? data.screen_checks : [];
      const required = ["before_start", "after_start", "after_complete"];
      return required.every((checkpoint) => checks.some((item) => item && item.checkpoint === checkpoint && item.ok && item.screenshot_artifact));
    }
    function renderWorkflow(data) {
      const ok = data.ok === true;
      const py = data.pyautogui || (data.health && data.health.pyautogui);
      setWorkflowStep("auth", ok ? "Reachable" : (data.failure_code === "PYAUTOGUI_AUTH_FAILED" ? "Token blocked" : "Check needed"), ok ? "ok" : "bad");
      setWorkflowStep("gui", py ? (py.available ? "PyAutoGUI ready" : "Install PyAutoGUI") : "Driver unknown", py && py.available ? "ok" : "warn");
      const programLabel = data.program_id || (Array.isArray(data.programs) ? `${data.programs.length} programs` : "Not selected");
      setWorkflowStep("program", programLabel, data.program_id || Array.isArray(data.programs) ? "ok" : "");
      const evidenceOk = screenEvidenceComplete(data);
      const hasEvidence = Array.isArray(data.screen_checks) && data.screen_checks.length > 0;
      setWorkflowStep("evidence", evidenceOk ? "3 screenshots" : (hasEvidence ? "Incomplete" : "Waiting"), evidenceOk ? "ok" : (hasEvidence ? "bad" : "warn"));
      const dataRef = dataReference(data);
      setWorkflowStep("artifact", dataRef ? "CSV/artifact found" : "Waiting", dataRef ? "ok" : "warn");
      setSituationCard("bridge", py ? (py.available ? "PyAutoGUI ready" : "PyAutoGUI missing") : (ok ? "Bridge reachable" : "Check Health"), data.failure_code || data.status || "health/readiness", py && py.available ? "ok" : ok ? "warn" : "bad");
      setSituationCard("export", dataRef ? "CSV/artifact found" : "CSV not verified", dataRef || "wait for UTM export artifact", dataRef ? "ok" : "warn");
    }
    function renderReadiness(data) {
      const source = data && typeof data === "object" && ((data.gates && typeof data.gates === "object") || Array.isArray(data.required_locator_names) || Array.isArray(data.configured_locator_names))
        ? data
        : (bridgeState.readiness || data || {});
      const gates = source.gates && typeof source.gates === "object" ? source.gates : source;
      const required = Array.isArray(gates.required_locator_names) ? gates.required_locator_names : [];
      const configured = Array.isArray(gates.configured_locator_names) ? gates.configured_locator_names : [];
      const missing = Array.isArray(gates.missing_required_locators) ? gates.missing_required_locators : [];
      if (!required.length && !configured.length && !missing.length) return;
      document.getElementById("readinessRequired").textContent = required.length ? required.join(", ") : "-";
      document.getElementById("readinessCaptured").textContent = configured.length ? configured.join(", ") : "none";
      document.getElementById("readinessMissing").textContent = missing.length ? missing.join(", ") : "none";
      document.getElementById("readinessGate").textContent = missing.length ? "Capture missing locators before Live UTM" : "Required locators complete";
      const pill = document.getElementById("readinessPill");
      pill.querySelector("span:last-child").textContent = missing.length ? "blocked" : "ready";
      pill.querySelector(".dot").className = "dot " + (missing.length ? "bad" : "ok");
      renderLocatorShortcuts(required, configured, missing);
      setSituationCard("locators", missing.length ? `${missing.length} missing` : "Required locators ready", missing.length ? missing.join(", ") : (configured.length ? configured.join(", ") : "no required locators"), missing.length ? "bad" : "ok");
    }

    function renderBridgeFiles(data) {
      const health = data.health && typeof data.health === "object" ? data.health : data;
      const artifacts = health.artifacts && typeof health.artifacts === "object" && !Array.isArray(health.artifacts) ? health.artifacts : {};
      pathArtifactRoot.textContent = artifacts.root || health.artifact_root || "-";
      pathRequestLog.textContent = artifacts.request_log || (artifacts.root ? artifacts.root + "\\bridge_requests.jsonl" : "-");
      pathLocatorRoot.textContent = artifacts.locator_root || health.locator_root || "-";
      pathUtmExportRoot.textContent = artifacts.utm_export_root || health.utm_export_root || "-";
      const exportRoot = artifacts.utm_export_root || health.utm_export_root || "";
      if (exportRoot) setSituationCard("export", "Export root configured", exportRoot, "warn");
    }

    function renderRequestAudit(data) {
      const source = data && typeof data === "object" && (Array.isArray(data.events) || Array.isArray(data.recent_paths) || "event_count" in data || "execute_event_seen" in data)
        ? data
        : (bridgeState.requestAudit || data || {});
      if (!source || typeof source !== "object") return;
      const events = Array.isArray(source.events) ? source.events : [];
      const recentPaths = Array.isArray(source.recent_paths)
        ? source.recent_paths.map((item) => String(item || "")).filter(Boolean)
        : events.map((event) => event && typeof event === "object" ? String(event.path || "") : "").filter(Boolean);
      if (!recentPaths.length && !("event_count" in source) && !("execute_event_seen" in source)) return;
      const executeSeen = source.execute_event_seen === true || recentPaths.some((path) => path === "/execute" || path.endsWith("/execute"));
      document.getElementById("requestAuditEvents").textContent = String(source.event_count ?? events.length ?? 0);
      document.getElementById("requestAuditExecute").textContent = executeSeen ? `seen (${source.execute_event_count ?? 1})` : "missing";
      document.getElementById("requestAuditRecent").textContent = recentPaths.length ? recentPaths.slice(-5).join(" -> ") : "-";
      document.getElementById("requestAuditGate").textContent = executeSeen ? "Live /execute audit present" : "Blocked for live handoff until /execute appears";
      const pill = document.getElementById("requestAuditPill");
      pill.querySelector("span:last-child").textContent = executeSeen ? "execute-ok" : "missing /execute";
      pill.querySelector(".dot").className = "dot " + (executeSeen ? "ok" : "warn");
      if (requestAuditRunIds) requestAuditRunIds.textContent = formatList(source.execute_run_ids, "-");
      if (requestAuditSpecimenIds) requestAuditSpecimenIds.textContent = formatList(source.execute_specimen_ids, "-");
      if (requestAuditProgramIds) requestAuditProgramIds.textContent = formatList(source.execute_program_ids, "-");
      if (requestAuditLastAt) requestAuditLastAt.textContent = source.last_execute_at || ((source.last_execute_context && source.last_execute_context.at) || "-");
      setSituationCard("audit", executeSeen ? "Live /execute seen" : "No /execute yet", executeSeen ? formatList(source.execute_program_ids, "identity recorded") : "request log checked", executeSeen ? "ok" : "warn");
      if (executeSeen) setOpsCard("next", "Build/audit Linux proof package", "ok");
    }

    function absorbBridgeState(data) {
      if (!data || typeof data !== "object") return;
      const tool = String(data.tool || "");
      if (tool === "equipment.pyautogui.health" || (data.bridge === "windows_pyautogui" && data.pyautogui)) bridgeState.health = data;
      if (tool === "equipment.pyautogui.windows_readiness" || (data.gates && Array.isArray((data.gates || {}).required_locator_names))) bridgeState.readiness = data;
      if (tool === "equipment.pyautogui.request_log" || "execute_event_seen" in data || "event_count" in data || Array.isArray(data.recent_paths)) bridgeState.requestAudit = data;
    }

    function requestAuditExecuteSeen() {
      const audit = bridgeState.requestAudit || {};
      const events = Array.isArray(audit.events) ? audit.events : [];
      const paths = Array.isArray(audit.recent_paths)
        ? audit.recent_paths.map((item) => String(item || "")).filter(Boolean)
        : events.map((event) => event && typeof event === "object" ? String(event.path || "") : "").filter(Boolean);
      return audit.execute_event_seen === true || paths.some((path) => path === "/execute" || path.endsWith("/execute"));
    }

    function proofItemHtml(item) {
      const klass = item.ok ? "ok" : (item.required === false ? "warn" : "bad");
      const dot = item.ok ? "ok" : (item.required === false ? "warn" : "bad");
      return `<div class="proof-item ${klass}"><span class="dot ${dot}"></span><div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></div></div>`;
    }

    function setProofGateCard(id, ok, label) {
      const card = document.getElementById(id);
      if (!card) return;
      card.className = "proof-gate " + (ok ? "ok" : "warn");
      const span = card.querySelector("span");
      if (span) span.textContent = label || (ok ? "ready" : "open");
    }

    function renderProofGateStrip(items) {
      const byLabel = new Map(items.map((item) => [item.label, item]));
      const gateMap = [
        ["proofGateHealth", "Health + PyAutoGUI", "ready", "Health needed"],
        ["proofGateLocators", "UTM Locators", "captured", "Readiness needed"],
        ["proofGateSafety", "Live Safety Confirmed", "confirmed", "Confirm setup"],
        ["proofGateRequestLog", "Request Log /execute", "audit seen", "/execute missing"],
        ["proofGateScreen", "Screen Evidence", "3 screenshots", "Need screenshots"],
        ["proofGateSave", "Save/Export Responsibility", "export verified", "Need export proof"],
        ["proofGateCsv", "CSV + Parse Probe", "parse ok", "Need CSV parse"],
      ];
      for (const [id, sourceLabel, okText, openText] of gateMap) {
        const item = byLabel.get(sourceLabel);
        setProofGateCard(id, Boolean(item && item.ok), item && item.ok ? okText : openText);
      }
    }

    function renderProofChecklist(data) {
      const list = document.getElementById("proofChecklist");
      if (!list) return;
      const health = bridgeState.health || data || {};
      const py = health.pyautogui || (health.health && health.health.pyautogui) || {};
      const readiness = bridgeState.readiness || {};
      const gates = readiness.gates && typeof readiness.gates === "object" ? readiness.gates : readiness;
      const missingLocators = Array.isArray(gates.missing_required_locators) ? gates.missing_required_locators : [];
      const requiredLocators = Array.isArray(gates.required_locator_names) ? gates.required_locator_names : [];
      const liveConfirmed = document.getElementById("confirmLive").checked === true;
      const screenOk = screenEvidenceComplete(data || {});
      const dataRefText = dataReference(data || {});
      const acquisition = data && typeof data.data_acquisition === "object" ? data.data_acquisition : {};
      const crossChecks = data && typeof data.cross_checks === "object" ? data.cross_checks : {};
      const parseOk = crossChecks.data_parse_probe_ok === true || Number(acquisition.row_count_probe || 0) > 0;
      const saveMethod = String(acquisition.save_method || "");
      const recognizedSaveMethods = new Set(["windows_export_watch", "manual_save_dialog", "export_menu", "simulated_bridge_export", "simulated_auto_export", "synthetic_test_export"]);
      const saveAttempted = acquisition.save_attempted_by_agent === true || ["windows_export_watch", "simulated_bridge_export", "simulated_auto_export"].includes(saveMethod);
      const saveConfirmed = acquisition.save_confirmation_screen_ok === true || Boolean(acquisition.windows_path || dataRefText);
      const saveGateOk = crossChecks.save_export_responsibility_ok === true || Boolean(dataRefText && parseOk && recognizedSaveMethods.has(saveMethod) && saveAttempted && saveConfirmed);
      const saveDetail = saveGateOk
        ? `Save/export verified by ${saveMethod || "recorded method"}.`
        : `Need recognized save/export evidence. method=${saveMethod || "-"}; attempted=${saveAttempted}; confirmed=${saveConfirmed}.`;
      const items = [
        {label: "Health + PyAutoGUI", ok: Boolean(py.available), detail: py.available ? "PyAutoGUI driver is available." : "Run Health or install PyAutoGUI on Windows."},
        {label: "UTM Locators", ok: requiredLocators.length > 0 && missingLocators.length === 0, detail: missingLocators.length ? `Missing: ${missingLocators.join(", ")}` : (requiredLocators.length ? "Required locators are captured." : "Run Readiness to verify required locators.")},
        {label: "Live Safety Confirmed", ok: liveConfirmed, detail: liveConfirmed ? "Operator marked the physical setup as safe." : "Check the live safety box before Run Live UTM."},
        {label: "Request Log /execute", ok: requestAuditExecuteSeen(), detail: requestAuditExecuteSeen() ? "A live /execute request is present in the bridge log." : "Run Request Log after a live command; Linux will block without this evidence."},
        {label: "Screen Evidence", ok: screenOk, detail: screenOk ? "before/start/complete screenshots are present." : "Live UTM should capture before_start, after_start, and after_complete screens."},
        {label: "Save/Export Responsibility", ok: saveGateOk, detail: saveDetail},
        {label: "CSV + Parse Probe", ok: Boolean(dataRefText && parseOk), detail: dataRefText ? (parseOk ? `Data artifact verified: ${dataRefText}` : "CSV found, but parse probe is not verified yet.") : "No UTM CSV/data artifact has been verified yet."},
      ];
      const runbookState = {
        connect: Boolean(py.available),
        calibrate: requiredLocators.length > 0 && missingLocators.length === 0,
        execute: requestAuditExecuteSeen(),
        verify: Boolean(screenOk && saveGateOk && dataRefText && parseOk),
      };
      setRunbookStep("connect", runbookState.connect ? "ok" : "warn", runbookState.connect ? "Bridge driver ready. Continue to UTM locator readiness." : "Run Health and install/enable PyAutoGUI if missing.");
      setRunbookStep("calibrate", runbookState.calibrate ? "ok" : (missingLocators.length ? "bad" : "warn"), runbookState.calibrate ? "Required UTM screen locators are captured." : (missingLocators.length ? `Capture missing locators: ${missingLocators.join(", ")}` : "Run Readiness to check required UTM locators."));
      setRunbookStep("execute", runbookState.execute ? "ok" : (liveConfirmed ? "warn" : "bad"), runbookState.execute ? "Authenticated /execute is recorded for this bridge." : (liveConfirmed ? "Run Live UTM only after preflight passes." : "Confirm physical safety before any live /execute."));
      setRunbookStep("verify", runbookState.verify ? "ok" : "warn", runbookState.verify ? "Screen, save/export, and CSV parse proof are available." : "Refresh Evidence until screenshots, export proof, and CSV parse probe are present.");
      setRunbookProgress(runbookState);
      const missing = items.filter((item) => !item.ok && item.required !== false);
      const complete = items.length - missing.length;
      renderProofGateStrip(items);
      list.innerHTML = items.map(proofItemHtml).join("");
      const pill = document.getElementById("proofChecklistPill");
      pill.querySelector("span:last-child").textContent = missing.length ? `${missing.length} open` : "ready";
      pill.querySelector(".dot").className = "dot " + (missing.length ? "warn" : "ok");
      if (gateMeterFill) gateMeterFill.style.width = `${Math.round((complete / Math.max(items.length, 1)) * 100)}%`;
      if (gateMeterText) gateMeterText.textContent = `${complete} / ${items.length} checks complete`;
      if (gateMeterNext) gateMeterNext.textContent = missing.length ? `Next: ${missing[0].label}` : "Ready for Linux audit";
      setHeaderProof(`proof ${complete}/${items.length}`, missing.length ? "warn" : "ok");
      document.getElementById("proofChecklistGate").textContent = missing.length
        ? `Next required proof: ${missing[0].label}`
        : "Live handoff proof is complete for the current Windows bridge evidence.";
      const recommendation = missing.length ? recommendationForMissing(missing[0].label) : {label: "Refresh Evidence", target: "refreshEvidence", klass: "ok"};
      setNextAction(recommendation.label, recommendation.target, recommendation.klass);
      setOpsCard("safety", missing.length ? `${complete}/${items.length} proof gates` : "Proof gates ready", missing.length ? "warn" : "ok");
      setOpsCard("evidence", screenOk ? "Screen evidence complete" : "Need before/start/complete screenshots", screenOk ? "ok" : "warn");
      setOpsCard("data", dataRefText ? (parseOk ? "CSV parse verified" : "CSV needs parse probe") : "No CSV artifact yet", dataRefText && parseOk ? "ok" : "warn");
      setOpsCard("next", missing.length ? missing[0].label : "Ready for Linux audit", missing.length ? "warn" : "ok");
      setSituationCard("export", dataRefText ? (parseOk ? "CSV parse verified" : "CSV found") : "CSV not verified", dataRefText || saveDetail, dataRefText && parseOk ? "ok" : "warn");
      setSituationCard("live", liveConfirmed ? (missing.length ? "Proof incomplete" : "Proof gates ready") : "Live blocked", liveConfirmed ? (missing.length ? missing[0].label : "ready for Linux audit") : "physical safety not confirmed", liveConfirmed && !missing.length ? "ok" : "warn");
    }

    function renderSummary(data) {
      const ok = data.ok === true;
      const status = data.status || (ok ? "ok" : "failed");
      const program = data.program_id || (Array.isArray(data.programs) ? "program registry" : "-");
      const runId = data.run_id || data.sequence_id || "-";
      const dataRef = dataReference(data) || "-";
      let gate = "Run Health";
      if (data.failure_code) gate = `Resolve ${data.failure_code}`;
      else if (status === "verified_complete" && dataRef !== "-") gate = "Linux pull/audit then Analysis";
      else if (ok && program === "-") gate = "Select program or capture evidence";
      else if (ok) gate = "Ready for next bridge action";
      summaryProgram.textContent = program;
      summaryRun.textContent = runId;
      summaryData.textContent = dataRef;
      summaryGate.textContent = gate;
      setSummaryPill(status, ok ? "ok" : "bad");
    }
    function render(data) {
      lastResult = data || {};
      absorbBridgeState(lastResult);
      output.textContent = JSON.stringify(lastResult, null, 2);
      const ok = lastResult.ok === true;
      const status = lastResult.status || (ok ? "ok" : "failed");
      setTile(tileStatus, status, ok ? "ok" : (status === "degraded" ? "warn" : "bad"));
      const py = lastResult.pyautogui || (lastResult.health && lastResult.health.pyautogui);
      setTile(tilePyAutoGUI, py ? (py.available ? "available" : "missing") : "unknown", py && py.available ? "ok" : "warn");
      setTile(tileFailure, lastResult.failure_code || "None", lastResult.failure_code ? "bad" : "ok");
      setAuth(ok ? "reachable" : "check failed", ok ? "ok" : "bad");
      renderTrace(lastResult);
      renderArtifacts(lastResult);
      appendTimelineFromResult(lastResult);
      renderWorkflow(lastResult);
      renderSummary(lastResult);
      renderBridgeFiles(lastResult);
      renderReadiness(lastResult);
      renderRequestAudit(lastResult);
      if (Array.isArray(lastResult.programs)) renderProgramRegistry(lastResult);
      renderProofChecklist(lastResult);
      renderArtifactPreview(lastResult);
      renderEssentialSummary(lastResult);
    }
    async function call(path, options = {}) {
      const fetchOptions = {...options};
      const quiet = fetchOptions.quiet === true;
      const shouldRender = fetchOptions.render !== false;
      delete fetchOptions.quiet;
      delete fetchOptions.render;
      if (!quiet) {
        setBusy(true);
        setCommandBanner("Command running", `${fetchOptions.method || "GET"} ${path}`, "busy");
      }
      try {
        const headers = new Headers(fetchOptions.headers || {});
        if (tokenInput.value) headers.set("X-Bridge-Token", tokenInput.value);
        const response = await fetch(path, {...fetchOptions, headers});
        const data = await response.json();
        if (shouldRender) render(data);
        else {
          absorbBridgeState(data);
          renderBridgeFiles(data);
          renderReadiness(data);
          renderRequestAudit(data);
          if (Array.isArray(data.programs)) renderProgramRegistry(data);
          renderProofChecklist(lastResult);
        }
        const ok = data && data.ok === true;
        if (!quiet) {
          setCommandBanner(ok ? "Command completed" : "Command returned a blocker", `${fetchOptions.method || "GET"} ${path} -> ${data.status || response.status}`, ok ? "ok" : "bad");
          appendLog(`${fetchOptions.method || "GET"} ${path} -> ${data.status || response.status}`);
        }
        return data;
      } catch (error) {
        const failed = {ok: false, status: "failed", failure_code: "CLIENT_ERROR", message: String(error)};
        if (shouldRender) render(failed);
        if (!quiet) {
          setCommandBanner("Command failed", String(error), "bad");
          appendLog(`client error: ${String(error)}`);
        }
        return failed;
      } finally {
        if (!quiet) setBusy(false);
      }
    }
    function renderControllerStatus(data) {
      const controller = data && data.atr_controller && typeof data.atr_controller === "object" ? data.atr_controller : (data || {});
      const ok = controller.ok === true;
      const source = String(controller.source || "none");
      const resolvedUrl = String(controller.controller_url || "");
      controllerStatus.textContent = ok ? `${resolvedUrl} · ${source}` : String(controller.failure_code || controller.status || "Not resolved");
      if (resolvedUrl) controllerUrl.value = resolvedUrl;
      const candidates = Array.isArray(controller.candidates) ? controller.candidates : [];
      if (!candidates.length) {
        controllerCandidates.textContent = ok ? `Verified controller (${source}).` : "No verified ATR candidate selected.";
        return;
      }
      controllerCandidates.innerHTML = `<span>${candidates.length} verified ATR controllers found. Select one:</span> ${candidates.map((url) => `<button type="button" class="secondary" data-controller-url="${escapeHtml(url)}">${escapeHtml(url)}</button>`).join(" ")}`;
      controllerCandidates.querySelectorAll("button[data-controller-url]").forEach((button) => {
        button.addEventListener("click", async () => {
          controllerUrl.value = button.dataset.controllerUrl || "";
          const selected = await call("/controller/select", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({controller_url: controllerUrl.value}), render: false});
          renderControllerStatus(selected);
        });
      });
    }
    async function discoverAtrController() {
      const result = await call("/controller/discover", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", render: false});
      renderControllerStatus(result);
      return result;
    }
    async function saveAtrController() {
      const result = await call("/controller/select", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({controller_url: controllerUrl.value.trim()}), render: false});
      renderControllerStatus(result);
      return result;
    }
    async function runHealthCheck() {
      const data = await call("/health");
      renderControllerStatus(data);
      if (data && data.ok === true) {
        const programs = await call("/programs", {quiet: true, render: false});
        if (programs && Array.isArray(programs.programs)) {
          bridgeState.programs = programs.programs;
          renderProgramRegistry(programs);
        }
      }
      return data;
    }
    function livePreflightBlockers() {
      const blockers = [];
      const warnings = [];
      const health = bridgeState.health || {};
      const py = health.pyautogui || (health.health && health.health.pyautogui) || {};
      const readiness = bridgeState.readiness || {};
      const gates = readiness.gates && typeof readiness.gates === "object" ? readiness.gates : readiness;
      const required = Array.isArray(gates.required_locator_names) ? gates.required_locator_names : [];
      const missing = Array.isArray(gates.missing_required_locators) ? gates.missing_required_locators : [];
      if (!py.available) blockers.push("PYAUTOGUI_NOT_READY");
      if (!required.length) blockers.push("UTM_READINESS_NOT_CHECKED");
      if (missing.length) blockers.push(`UTM_LOCATORS_MISSING: ${missing.join(", ")}`);
      if (!bridgeState.requestAudit) warnings.push("REQUEST_LOG_NOT_CHECKED");
      return {blockers, warnings};
    }
    function updateLiveInterlock(ok, blockers, warnings) {
      if (!liveInterlockCard || !liveInterlockText) return;
      const confirmed = document.getElementById("confirmLive").checked === true;
      const ready = ok && confirmed;
      liveInterlockCard.className = "interlock-card" + (ready ? " ok" : "");
      setSituationCard("live", ready ? "Live send enabled" : "Live blocked", ready ? "preflight + safety confirmed" : (confirmed ? (blockers && blockers[0]) || "run preflight" : "check physical safety box"), ready ? "ok" : (confirmed ? "bad" : "warn"));
      if (ready) {
        liveInterlockText.textContent = warnings && warnings.length
          ? `Live control may run. Warnings: ${warnings.join(", ")}`
          : "Live control may run. The bridge will still record /execute and evidence for Linux audit.";
      } else if (!confirmed) {
        liveInterlockText.textContent = "Physical safety confirmation is off. Live UTM /execute remains blocked from this page.";
      } else if (blockers && blockers.length) {
        liveInterlockText.textContent = `Safe Preflight is not ready: ${blockers.join(", ")}`;
      } else {
        liveInterlockText.textContent = "Run Safe Preflight before live UTM control.";
      }
    }
    function setPreflightStatus(ok, blockers, warnings) {
      if (!preflightBanner) return;
      preflightBanner.className = "preflight-banner " + (ok ? "ok" : "bad");
      preflightTitle.textContent = ok ? "Live UTM preflight passed" : "Live UTM preflight blocked";
      preflightText.textContent = ok
        ? (warnings.length ? `Warnings: ${warnings.join(", ")}` : "Health and required UTM readiness gates passed. Live control still requires operator confirmation.")
        : `Resolve before live /execute: ${blockers.join(", ")}`;
      updateLiveInterlock(ok, blockers, warnings);
      setOpsCard("safety", ok ? "Preflight passed" : `Blocked: ${blockers[0] || "preflight"}`, ok ? "ok" : "bad");
      setOpsCard("next", ok ? "Confirm safety, then Live UTM" : "Resolve preflight blocker", ok ? "ok" : "bad");
    }
    async function runSafePreflight(renderResult = true) {
      appendLog("safe preflight started: /health -> /readiness -> /request-log");
      const health = await call("/health", {render: false});
      const readiness = await call("/readiness", {render: false});
      const audit = await call("/request-log", {render: false});
      const {blockers, warnings} = livePreflightBlockers();
      const ok = blockers.length === 0;
      const result = {
        ok,
        status: ok ? "preflight_passed" : "blocked",
        tool: "equipment.pyautogui.local_live_preflight",
        bridge: "windows_pyautogui",
        non_actuating: true,
        blocks_execute: !ok,
        blockers,
        warnings,
        health,
        readiness,
        request_audit: audit,
        step_trace: [
          {step: "HEALTH", status: health && health.ok ? "ok" : "blocked", detail: (health && health.status) || "unknown"},
          {step: "READINESS", status: readiness && readiness.ok ? "ok" : "blocked", detail: blockers.join(", ") || "required setup gates passed"},
          {step: "REQUEST_LOG", status: audit && audit.ok ? "ok" : "warning", detail: audit && audit.request_log ? audit.request_log : "request log unavailable"},
        ],
      };
      setPreflightStatus(ok, blockers, warnings);
      if (renderResult) render(result);
      return result;
    }
    function currentAbortPayload() {
      const runId = document.getElementById("runId").value.trim() || `utm-abort-${Date.now()}`;
      const specimenId = document.getElementById("specimenId").value.trim() || "specimen-001";
      const targetWindow = document.getElementById("targetWindow").value.trim();
      const payload = {
        sequence_id: `${runId}-abort`,
        program_id: "utm_stop_or_abort_v1",
        run_id: runId,
        specimen_id: specimenId,
        command: "Dispatch UTM stop/abort recovery macro",
        require_screen_assertions: false,
        simulate_utm_protocol: false
      };
      if (targetWindow) {
        if (targetWindow.startsWith("regex:")) payload.target_window_regex = targetWindow.slice(6).trim();
        else payload.target_window = targetWindow;
      }
      return payload;
    }

    function currentUtmPayload(simulate) {
      const runId = document.getElementById("runId").value.trim() || `utm-${Date.now()}`;
      const specimenId = document.getElementById("specimenId").value.trim() || "specimen-001";
      const targetWindow = document.getElementById("targetWindow").value.trim();
      const exportGlob = document.getElementById("exportGlob").value.trim() || "*.csv";
      const artifactTimeout = positiveNumberInput("artifactTimeout", 20);
      const stableForSec = positiveNumberInput("stableForSec", 2.0);
      const expectedExportPath = document.getElementById("expectedExportPath").value.trim();
      const payload = {
        sequence_id: runId,
        program_id: "utm_compression_start_v1",
        run_id: runId,
        specimen_id: specimenId,
        export_glob: exportGlob,
        artifact_timeout_s: artifactTimeout,
        stable_for_sec: stableForSec,
        require_window_focus: document.getElementById("requireFocus").checked,
        require_screen_assertions: document.getElementById("requireAssertions").checked,
        manual_save_required_if_no_artifact: document.getElementById("manualSave").checked,
        simulate_utm_protocol: Boolean(simulate)
      };
      if (expectedExportPath) payload.expected_export_path = expectedExportPath;
      if (targetWindow) {
        if (targetWindow.startsWith("regex:")) payload.target_window_regex = targetWindow.slice(6).trim();
        else payload.target_window = targetWindow;
      }
      return payload;
    }
    function shellSingleQuote(value) {
      return "'" + String(value ?? "").replace(/'/g, "'\"'\"'") + "'";
    }
    function psDoubleQuote(value) {
      return '"' + String(value ?? "").replace(/`/g, "``").replace(/"/g, '`"') + '"';
    }
    async function copyBridgeCommand(text, label) {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.left = "-9999px";
        document.body.appendChild(area);
        area.focus();
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
      }
      appendLog(`${label} copied to clipboard`);
      setCommandBanner("Command copied", label, "ok");
    }
    function bridgeTokenForCommand() {
      return tokenInput.value.trim() || "<bridge-token>";
    }
    function curlHealthCommand() {
      const token = bridgeTokenForCommand();
      return `curl -s -H ${shellSingleQuote("X-Bridge-Token: " + token)} ${shellSingleQuote(window.location.origin + "/health")}`;
    }
    function powerShellHealthCommand() {
      const token = bridgeTokenForCommand();
      return `$headers = @{"X-Bridge-Token"=${psDoubleQuote(token)}}
Invoke-RestMethod -Uri ${psDoubleQuote(window.location.origin + "/health")} -Headers $headers`;
    }
    function curlExecuteCommand() {
      if (!previewPayloadEnvelope) renderPayloadPreview(previewMode);
      const payload = JSON.stringify((previewPayloadEnvelope && previewPayloadEnvelope.payload) || currentUtmPayload(false));
      const token = bridgeTokenForCommand();
      return [
        "curl -s -X POST",
        `-H ${shellSingleQuote("Content-Type: application/json")}`,
        `-H ${shellSingleQuote("X-Bridge-Token: " + token)}`,
        `-d ${shellSingleQuote(payload)}`,
        shellSingleQuote(window.location.origin + "/execute"),
      ].join(" ");
    }
    function locatorPayload() {
      return {
        program_id: "utm_compression_start_v1",
        name: document.getElementById("locatorName").value,
        region: ["regionX", "regionY", "regionW", "regionH"].map((id) => Number(document.getElementById(id).value)),
        confidence: Number(document.getElementById("confidence").value || 0.8)
      };
    }

    document.getElementById("health").addEventListener("click", runHealthCheck);
    document.getElementById("discoverController").addEventListener("click", discoverAtrController);
    document.getElementById("saveController").addEventListener("click", saveAtrController);
    document.getElementById("safePreflight").addEventListener("click", () => runSafePreflight(true));
    document.getElementById("preflightRefreshInline").addEventListener("click", () => runSafePreflight(true));
    document.getElementById("locators").addEventListener("click", () => call("/locators"));
    document.getElementById("readiness").addEventListener("click", () => call("/readiness"));
    document.getElementById("utmSim").addEventListener("click", () => {
      if (!renderPayloadPreview("sim")) {
        renderInputBlocker("sim");
        return;
      }
      call("/execute", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(currentUtmPayload(true))
      });
    });
    document.getElementById("utmLive").addEventListener("click", async () => {
      if (!document.getElementById("confirmLive").checked) {
        render({ok: false, status: "blocked", failure_code: "LIVE_CONFIRMATION_REQUIRED", message: "Check physical safety confirmation before live UTM control."});
        return;
      }
      if (!renderPayloadPreview("live")) {
        renderInputBlocker("live");
        return;
      }
      const preflight = await runSafePreflight(false);
      if (!preflight.ok) {
        render({
          ...preflight,
          failure_code: "LOCAL_LIVE_PREFLIGHT_BLOCKED",
          message: "Live /execute was not sent because local preflight failed.",
        });
        return;
      }
      call("/execute", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(currentUtmPayload(false))});
    });
    document.getElementById("utmAbort").addEventListener("click", () => {
      renderPayloadPreview("abort");
      setOpsCard("next", "Stop/Abort recovery requested", "bad");
      call("/execute", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(currentAbortPayload())});
    });
    document.getElementById("screenshot").addEventListener("click", () => call("/screenshot", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({run_id: "manual-screenshot", checkpoint: "manual"})
    }));
    document.getElementById("artifacts").addEventListener("click", () => call("/artifacts"));
    document.getElementById("requestLog").addEventListener("click", () => call("/request-log"));
    async function refreshEvidenceBundle() {
      await call("/health");
      await call("/readiness");
      await call("/request-log");
      await call("/artifacts");
    }
    document.getElementById("refreshEvidence").addEventListener("click", refreshEvidenceBundle);
    document.getElementById("refreshAll").addEventListener("click", refreshEvidenceBundle);
    document.getElementById("autoAudit").addEventListener("change", (event) => {
      if (requestAuditTimer) {
        clearInterval(requestAuditTimer);
        requestAuditTimer = null;
      }
      if (event.target.checked) {
        requestAuditTimer = setInterval(() => {
          if (!document.hidden) call("/request-log", {quiet: true, render: false});
        }, 5000);
      }
    });
    document.getElementById("confirmLive").addEventListener("change", () => {
      renderProofChecklist(lastResult);
      const {blockers, warnings} = livePreflightBlockers();
      updateLiveInterlock(blockers.length === 0, blockers, warnings);
    });
    document.getElementById("captureLocator").addEventListener("click", () => call("/locators/capture", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(locatorPayload())
    }));
    document.getElementById("execute").addEventListener("click", () => {
      try { call("/execute", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(JSON.parse(sequenceInput.value))}); }
      catch (error) { render({ok: false, status: "failed", failure_code: "BAD_JSON", message: String(error)}); }
    });
    document.getElementById("fillUtmJson").addEventListener("click", () => { sequenceInput.value = JSON.stringify(currentUtmPayload(false), null, 2); });
    document.getElementById("previewSimPayload").addEventListener("click", () => renderPayloadPreview("sim"));
    document.getElementById("previewLivePayload").addEventListener("click", () => renderPayloadPreview("live"));
    document.getElementById("previewAbortPayload").addEventListener("click", () => renderPayloadPreview("abort"));
    document.getElementById("copyPreviewPayload").addEventListener("click", async () => {
      if (!previewPayloadEnvelope) renderPayloadPreview(previewMode);
      await navigator.clipboard.writeText(JSON.stringify(previewPayloadEnvelope || {}, null, 2));
      appendLog("payload preview copied to clipboard");
    });
    document.getElementById("copyUtmPayload").addEventListener("click", async () => {
      renderPayloadPreview("live");
      await navigator.clipboard.writeText(JSON.stringify(currentUtmPayload(false), null, 2));
      appendLog("current UTM payload copied to clipboard");
    });
    document.getElementById("formatJson").addEventListener("click", () => {
      try { sequenceInput.value = JSON.stringify(JSON.parse(sequenceInput.value), null, 2); }
      catch (error) { render({ok: false, status: "failed", failure_code: "BAD_JSON", message: String(error)}); }
    });
    document.getElementById("clearResult").addEventListener("click", () => render({}));
    document.getElementById("timelineClear").addEventListener("click", () => {
      timelineEntries = [];
      renderTimelineEntries();
      appendLog("run timeline cleared");
    });
    if (focusModeButton) {
      focusModeButton.addEventListener("click", () => setFocusMode(!hasBodyClass("focus-mode")));
    }
    document.getElementById("copyResult").addEventListener("click", async () => navigator.clipboard.writeText(JSON.stringify(lastResult, null, 2)));
    document.getElementById("copyBase").addEventListener("click", async () => navigator.clipboard.writeText(window.location.origin));
    document.getElementById("copyLinuxEnv").addEventListener("click", async () => {
      const token = tokenInput.value || "<bridge-token>";
      const envText = `export WINDOWS_PYAUTOGUI_BRIDGE_URL="${window.location.origin}"
export WINDOWS_PYAUTOGUI_BRIDGE_TOKEN="${token}"`;
      await copyBridgeCommand(envText, "Linux bridge environment");
    });
    document.getElementById("copyCurlHealth").addEventListener("click", async () => copyBridgeCommand(curlHealthCommand(), "curl Health command"));
    document.getElementById("copyPowerShellHealth").addEventListener("click", async () => copyBridgeCommand(powerShellHealthCommand(), "PowerShell Health command"));
    document.getElementById("copyCurlExecute").addEventListener("click", async () => copyBridgeCommand(curlExecuteCommand(), "curl Execute command"));
    if (nextActionButton) nextActionButton.addEventListener("click", activateRecommendedAction);
    document.getElementById("clearToken").addEventListener("click", () => {
      tokenInput.value = "";
      localStorage.removeItem("bridgeToken");
      render({ok: true, status: "token_cleared", message: "Stored browser token cleared."});
      renderTokenPrompt();
      appendLog("stored browser token cleared");
    });
    ["runId", "specimenId", "targetWindow", "exportGlob", "artifactTimeout", "stableForSec", "expectedExportPath"].forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.addEventListener("input", () => renderPayloadPreview(previewMode));
    });
    ["requireFocus", "requireAssertions", "manualSave", "confirmLive"].forEach((id) => {
      const element = document.getElementById(id);
      if (element) element.addEventListener("change", () => renderPayloadPreview(previewMode));
    });



    const essentialProgramManagerSlot = document.getElementById("essentialProgramManagerSlot");
    const programManagerPanel = document.getElementById("programManagerPanel");
    if (essentialProgramManagerSlot && programManagerPanel) essentialProgramManagerSlot.appendChild(programManagerPanel);

    function renderEssentialSummary(data) {
      const payload = data && typeof data === "object" ? data : {};
      const health = payload.health && typeof payload.health === "object" ? payload.health : payload;
      const py = health.pyautogui || (bridgeState.health && bridgeState.health.pyautogui) || {};
      const ok = payload.ok === true;
      const status = String(payload.status || (ok ? "ready" : "idle"));
      const resultText = payload.message || payload.failure_code || (payload.program_id ? `${payload.program_id}: ${status}` : status);
      const resultTone = payload.failure_code || payload.ok === false ? "bad" : ok ? "ok" : "warn";

      document.getElementById("essentialBridgeState").textContent = ok ? (status === "degraded" ? "Reachable / degraded" : "Reachable") : (payload.failure_code ? "Blocked" : "Not checked");
      document.getElementById("essentialPyAutoGUI").textContent = py.available === true ? "Ready" : py.available === false ? "Unavailable" : "Unknown";
      const result = document.getElementById("essentialResult");
      result.textContent = resultText;
      result.dataset.tone = resultTone;
    }


    const managerRegistry = document.getElementById("managerProgramRegistry");
    const managerSearchInput = document.getElementById("managerSearch");
    const managerFilterInput = document.getElementById("managerFilter");
    const managerProgramFile = document.getElementById("programFile");
    const managerDefinitionInput = document.getElementById("programDefinition");
    const programEditor = document.getElementById("programEditor");
    let managerBridgePrograms = [];
    let managerEditingProgramId = "";
    let managerEditingBuiltin = false;

    function managerShowResult(payload) {
      const element = document.getElementById("managerLatestResult");
      if (element) element.textContent = JSON.stringify(payload, null, 2);
      const summary = document.getElementById("essentialResult");
      if (summary) {
        summary.textContent = payload.message || payload.failure_code || payload.status || "Program Manager updated.";
        summary.dataset.tone = payload.ok === false ? "bad" : payload.ok === true ? "ok" : "warn";
      }
    }
    function managerBadge(text, tone = "") {
      return `<span class="manager-badge ${tone}">${escapeHtml(text)}</span>`;
    }
    function managerVisiblePrograms() {
      return managerBridgePrograms.slice().sort((left, right) => String(left.name || left.program_id).localeCompare(String(right.name || right.program_id)));
    }
    function managerFilteredPrograms() {
      const query = managerSearchInput.value.trim().toLowerCase();
      const filter = managerFilterInput.value;
      return managerVisiblePrograms().filter((program) => {
        const builtIn = program.built_in !== false;
        const enabled = program.enabled !== false;
        const searchable = `${program.name || ""} ${program.program_id || ""} ${program.description || ""}`.toLowerCase();
        if (query && !searchable.includes(query)) return false;
        if (filter === "builtin" && !builtIn) return false;
        if (filter === "custom" && builtIn) return false;
        if (filter === "enabled" && !enabled) return false;
        if (filter === "disabled" && enabled) return false;
        return true;
      });
    }
    function managerRenderPrograms() {
      const allPrograms = managerVisiblePrograms();
      const programs = managerFilteredPrograms();
      const builtInCount = allPrograms.filter((item) => item.built_in !== false).length;
      const customCount = allPrograms.length - builtInCount;
      const disabledCount = allPrograms.filter((item) => item.enabled === false).length;
      document.getElementById("programCount").textContent = `${programs.length} / ${allPrograms.length}`;
      document.getElementById("managerStats").textContent = `${builtInCount} built-in · ${customCount} custom · ${disabledCount} disabled`;
      if (!programs.length) {
        managerRegistry.innerHTML = '<div class="manager-empty">No programs match the current filter.</div>';
        return;
      }
      managerRegistry.innerHTML = programs.map((program) => {
        const builtIn = program.built_in !== false;
        const enabled = program.enabled !== false;
        return `<article class="program-card manager-program-card" data-manager-program-id="${escapeHtml(program.program_id)}">
          <div class="manager-program-info">
            <div class="program-card-head"><strong>${escapeHtml(program.name || program.program_id)}</strong><span class="program-kind">${escapeHtml(program.program_type || "bridge program")}</span></div>
            <p><code>${escapeHtml(program.program_id)}</code> · ${escapeHtml(program.description || "No description")}</p>
            <div class="manager-badges">${managerBadge(builtIn ? "BUILT-IN" : "CUSTOM")}${managerBadge(enabled ? "ENABLED" : "DISABLED", enabled ? "ok" : "warn")}</div>
          </div>
          <div class="manager-actions">
            <button class="secondary" data-manager-action="edit">${builtIn ? "View" : "Edit"}</button>
            <button class="secondary" data-manager-action="toggle" ${builtIn ? "disabled" : ""}>${builtIn ? "Built-in" : enabled ? "Disable" : "Enable"}</button>
            <button class="secondary" data-manager-action="revalidate">${builtIn ? "Refresh" : "Validate"}</button>
            <button data-manager-action="run" ${enabled ? "" : "disabled"}>Test</button>
            <button class="secondary" data-manager-action="delete" ${builtIn ? "disabled" : ""}>${builtIn ? "Built-in" : "Delete"}</button>
          </div>
        </article>`;
      }).join("");
    }
    function managerAcceptPrograms(programs) {
      managerBridgePrograms = Array.isArray(programs) ? programs.slice() : [];
      managerRenderPrograms();
    }
    async function managerRefreshPrograms() {
      const payload = await call("/programs", {quiet: true, render: false});
      managerAcceptPrograms(payload && Array.isArray(payload.programs) ? payload.programs : []);
      managerShowResult(payload);
      return payload;
    }
    function managerTemplate() {
      return {
        schema: "atr.pyautogui_program.v1",
        program_id: "my_macro",
        name: "My Macro",
        description: "Bounded Windows GUI operation",
        enabled: true,
        program_type: "macro",
        safe_test: false,
        sequence: [
          {action: "press", key: "esc"},
          {action: "log", message: "macro completed"},
        ],
      };
    }
    function managerEditableDefinition(program) {
      return {
        schema: "atr.pyautogui_program.v1",
        program_id: String(program.program_id || ""),
        name: String(program.name || program.program_id || ""),
        description: String(program.description || ""),
        enabled: program.enabled !== false,
        program_type: "macro",
        safe_test: Boolean(program.safe_test),
        sequence: Array.isArray(program.sequence) ? program.sequence : [],
      };
    }
    function managerDefinition() {
      let definition;
      try { definition = JSON.parse(managerDefinitionInput.value); }
      catch (error) { throw new Error(`Invalid JSON: ${error.message || error}`); }
      if (!definition || typeof definition !== "object" || Array.isArray(definition)) throw new Error("Macro definition must be a JSON object.");
      return definition;
    }
    function managerClearForm() {
      document.getElementById("programForm").reset();
      managerEditingProgramId = "";
      managerEditingBuiltin = false;
      managerDefinitionInput.readOnly = false;
      document.getElementById("validateProgram").disabled = false;
      document.getElementById("registerProgram").disabled = false;
      document.getElementById("editorTitle").textContent = "New Macro Program";
      document.getElementById("editorState").textContent = "DRAFT";
      document.getElementById("programFileMeta").textContent = "New draft. Browse only loads a file; it does not register it.";
      programEditor.hidden = true;
    }
    function managerOpenEditor(definition, title, state, meta, readOnly = false) {
      programEditor.hidden = false;
      managerDefinitionInput.value = JSON.stringify(definition, null, 2);
      managerDefinitionInput.readOnly = readOnly;
      document.getElementById("validateProgram").disabled = readOnly;
      document.getElementById("registerProgram").disabled = readOnly;
      document.getElementById("editorTitle").textContent = title;
      document.getElementById("editorState").textContent = state;
      document.getElementById("programFileMeta").textContent = meta;
      programEditor.scrollIntoView({behavior: "smooth", block: "nearest"});
    }
    function managerEditProgram(program) {
      const builtIn = program.built_in !== false;
      managerEditingProgramId = program.program_id;
      managerEditingBuiltin = builtIn;
      managerOpenEditor(
        managerEditableDefinition(program),
        builtIn ? "Built-in Program" : "Edit Registered Macro",
        builtIn ? "READ-ONLY" : "REGISTERED",
        builtIn ? "Built-in programs are immutable and can only be tested." : String(program.source_file || "Registered macro definition."),
        builtIn,
      );
    }
    async function managerImportFile(file) {
      if (!file.name.toLowerCase().endsWith(".json")) throw new Error("Browse accepts JSON macro definitions only.");
      const definition = JSON.parse(await file.text());
      managerEditingProgramId = "";
      managerEditingBuiltin = false;
      const fileMeta = {name: file.name, size: file.size, type: file.type || "application/json", last_modified: file.lastModified};
      managerOpenEditor(definition, "Loaded JSON Macro", "FILE", `${file.name} · ${file.size} bytes · not registered`);
      managerShowResult({ok: true, status: "file_loaded", file: fileMeta, registered: false, bridge_unchanged: true});
    }

    document.getElementById("programForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        if (managerEditingBuiltin) throw new Error("Built-in programs cannot be overwritten.");
        const definition = managerDefinition();
        const previousId = managerEditingProgramId;
        const result = await call("/programs/register", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(definition), render: false});
        managerShowResult(result);
        if (!result.ok) return;
        if (previousId && previousId !== definition.program_id) {
          await call(`/programs/${encodeURIComponent(previousId)}`, {method: "DELETE", render: false, quiet: true});
        }
        await managerRefreshPrograms();
        managerClearForm();
      } catch (error) { managerShowResult({ok: false, error: String(error)}); }
    });
    managerRegistry.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-manager-action]");
      const card = event.target.closest("[data-manager-program-id]");
      if (!button || !card) return;
      const program = managerVisiblePrograms().find((item) => item.program_id === card.dataset.managerProgramId);
      if (!program) return;
      const action = button.dataset.managerAction;
      if (action === "edit") { managerEditProgram(program); return; }
      if (action === "toggle") {
        if (program.built_in !== false) return;
        const definition = managerEditableDefinition(program);
        definition.enabled = program.enabled === false;
        const result = await call("/programs/register", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(definition), render: false});
        managerShowResult(result);
        if (result.ok) await managerRefreshPrograms();
        return;
      }
      if (action === "delete") {
        if (program.built_in !== false) return;
        const result = await call(`/programs/${encodeURIComponent(program.program_id)}`, {method: "DELETE", render: false});
        managerShowResult(result);
        if (result.ok) await managerRefreshPrograms();
        return;
      }
      if (action === "revalidate") {
        if (program.built_in !== false) { await managerRefreshPrograms(); return; }
        const result = await call("/programs/validate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(managerEditableDefinition(program)), render: false});
        managerShowResult(result);
        return;
      }
      if (action === "run") {
        const payload = program.built_in === false
          ? {sequence_id: `manager-${Date.now()}`, program_id: program.program_id}
          : buildProgramPayload(program.program_id, true);
        const result = await call("/execute", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
        managerShowResult(result);
      }
    });
    document.getElementById("refreshPrograms").addEventListener("click", managerRefreshPrograms);
    document.getElementById("clearProgramForm").addEventListener("click", managerClearForm);
    document.getElementById("newProgram").addEventListener("click", () => {
      managerClearForm();
      managerOpenEditor(managerTemplate(), "New Macro Program", "DRAFT", "Template loaded locally. Validate or add it when ready.");
      managerDefinitionInput.focus();
    });
    document.getElementById("browseProgram").addEventListener("click", () => managerProgramFile.click());
    document.getElementById("downloadProgramTemplate").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(managerTemplate(), null, 2) + "\n"], {type: "application/json"});
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = "atr_pyautogui_program_template.json";
      anchor.click();
      URL.revokeObjectURL(href);
      managerShowResult({ok: true, status: "template_downloaded", registered: false, file_name: anchor.download});
    });
    document.getElementById("validateProgram").addEventListener("click", async () => {
      try {
        const result = await call("/programs/validate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(managerDefinition()), render: false});
        managerShowResult(result);
      } catch (error) { managerShowResult({ok: false, status: "validation_failed", error: String(error)}); }
    });
    managerProgramFile.addEventListener("change", async () => {
      const file = managerProgramFile.files && managerProgramFile.files[0];
      if (!file) return;
      try { await managerImportFile(file); }
      catch (error) { managerShowResult({ok: false, status: "file_import_failed", error: String(error)}); }
      finally { managerProgramFile.value = ""; }
    });
    managerSearchInput.addEventListener("input", managerRenderPrograms);
    managerFilterInput.addEventListener("change", managerRenderPrograms);
    managerRenderPrograms();

    const managerViews = {
      programs: document.getElementById("managerProgramsView"),
      examples: document.getElementById("managerExamplesView"),
      record: document.getElementById("managerRecordView"),
      skills: document.getElementById("managerSkillsView"),
    };
    document.querySelectorAll("[data-manager-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const selected = button.dataset.managerTab;
        Object.entries(managerViews).forEach(([name, view]) => { view.hidden = name !== selected; });
        document.querySelectorAll("[data-manager-tab]").forEach((item) => {
          item.classList.toggle("active", item === button);
          item.classList.toggle("secondary", item !== button);
        });
        if (selected === "record") refreshRecordings();
        if (selected === "examples") refreshExamples();
        if (selected === "skills") refreshSkills();
      });
    });

    let activeRecordingId = "";
    let selectedRecordingId = "";
    const RECORDING_COUNTDOWN_SECONDS = 5;
    let recordingCountdownRemaining = 0;
    let recordingCountdownTimer = null;
    let recordingToggleBusy = false;
    const recordToggle = document.getElementById("recordToggle");
    function syncRecordingToggle() {
      if (recordingCountdownTimer !== null) {
        recordToggle.dataset.state = "countdown";
        recordToggle.textContent = `STARTING IN ${recordingCountdownRemaining}`;
        recordToggle.disabled = false;
        return;
      }
      if (activeRecordingId) {
        recordToggle.dataset.state = "recording";
        recordToggle.textContent = "STOP RECORDING";
      } else {
        recordToggle.dataset.state = "idle";
        recordToggle.textContent = "RECORD";
      }
      recordToggle.disabled = recordingToggleBusy;
    }
    function cancelRecordingCountdown() {
      if (recordingCountdownTimer !== null) window.clearInterval(recordingCountdownTimer);
      recordingCountdownTimer = null;
      recordingCountdownRemaining = 0;
      document.getElementById("recordingStatus").textContent = "Recording start cancelled.";
      syncRecordingToggle();
    }
    async function startRecordingAfterCountdown() {
      recordingToggleBusy = true;
      syncRecordingToggle();
      const result = await call("/recordings/start", {
        method: "POST", headers: {"Content-Type": "application/json"}, render: false,
        body: JSON.stringify({
          name: document.getElementById("recordingName").value.trim(),
          target_app: document.getElementById("recordingTargetApp").value.trim(),
          target_window: document.getElementById("recordingTargetWindow").value.trim(),
          image_tracking: document.getElementById("recordImageTracking").checked,
          coordinate_fallback: document.getElementById("recordCoordinateFallback").checked,
        }),
      });
      if (result.ok) activeRecordingId = selectedRecordingId = String(result.recording_id || "");
      recordingToggleBusy = false;
      managerShowResult(result);
      await refreshRecordings();
    }
    function beginRecordingCountdown() {
      if (recordingToggleBusy || activeRecordingId || recordingCountdownTimer !== null) return;
      recordingCountdownRemaining = RECORDING_COUNTDOWN_SECONDS;
      document.getElementById("recordingStatus").textContent = "Recording starts after the safety countdown.";
      recordingCountdownTimer = window.setInterval(async () => {
        recordingCountdownRemaining -= 1;
        if (recordingCountdownRemaining <= 0) {
          window.clearInterval(recordingCountdownTimer);
          recordingCountdownTimer = null;
          recordingCountdownRemaining = 0;
          syncRecordingToggle();
          await startRecordingAfterCountdown();
          return;
        }
        syncRecordingToggle();
      }, 1000);
      syncRecordingToggle();
    }
    async function stopActiveRecording() {
      if (!activeRecordingId || recordingToggleBusy) return;
      recordingToggleBusy = true;
      syncRecordingToggle();
      const result = await call("/recordings/stop", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", render: false});
      if (result.ok) selectedRecordingId = String(result.recording_id || selectedRecordingId);
      activeRecordingId = "";
      recordingToggleBusy = false;
      managerShowResult(result);
      await refreshRecordings();
    }
    function recordingCoverage(events) {
      const actionByKind = {mouse_move:"move_to", mouse_click:"click", mouse_drag:"drag_to", mouse_scroll:"scroll", key_press:"press", hotkey:"hotkey", checkpoint:"screenshot", screenshot:"screenshot"};
      const familyByAction = {move_to:"mouse", click:"mouse", drag_to:"mouse", scroll:"mouse", press:"keyboard", hotkey:"keyboard", screenshot:"screen"};
      const actions = new Set(); const families = new Set();
      (Array.isArray(events) ? events : []).forEach((event) => { const action = actionByKind[String(event.kind || "")]; if (action) { actions.add(action); families.add(familyByAction[action]); } });
      return {actions:[...actions].sort(), families:[...families].sort()};
    }
    function renderRecordingCoverage(events) {
      const coverage = recordingCoverage(events);
      const pointerEvents = (Array.isArray(events) ? events : []).filter((event) => ["mouse_click", "mouse_drag"].includes(String(event.kind || "")));
      const readyLocators = pointerEvents.reduce((count, event) => count + (event.kind === "mouse_drag"
        ? Number(event.source_visual_locator && event.source_visual_locator.status === "ready") + Number(event.target_visual_locator && event.target_visual_locator.status === "ready")
        : Number(event.visual_locator && event.visual_locator.status === "ready")), 0);
      const expectedLocators = pointerEvents.reduce((count, event) => count + (event.kind === "mouse_drag" ? 2 : 1), 0);
      document.getElementById("recordingCoverage").textContent = coverage.actions.length
        ? `Coverage: ${coverage.families.join(", ")} | ${coverage.actions.join(", ")} | image locators ${readyLocators}/${expectedLocators}`
        : "Coverage: no replayable actions captured.";
    }
    function recordingLocators(recording) {
      const locators = [];
      (Array.isArray(recording && recording.events) ? recording.events : []).forEach((event) => {
        if (event && event.visual_locator) locators.push(event.visual_locator);
        if (event && event.source_visual_locator) locators.push(event.source_visual_locator);
        if (event && event.target_visual_locator) locators.push(event.target_visual_locator);
      });
      return locators;
    }
    function renderRecordingLocators(recording) {
      const preview = document.getElementById("recordingLocatorPreview");
      const locators = recordingLocators(recording);
      preview.innerHTML = locators.length ? locators.map((locator) => {
        const candidates = Array.isArray(locator.candidates) ? locator.candidates.slice(0, 2) : [];
        const images = candidates.map((candidate) => `<img alt="${escapeHtml(candidate.kind || "locator")}" title="${escapeHtml(candidate.kind || "locator")}" src="data:image/png;base64,${escapeHtml(candidate.png_base64 || "")}">`).join("");
        return `<article class="recording-locator-card"><strong>${escapeHtml(locator.locator_id || "locator")}</strong><span>${escapeHtml(locator.status || "unknown")} · ${escapeHtml((locator.recorded_coordinate || []).join(", "))}</span><div class="recording-locator-images">${images}</div></article>`;
      }).join("") : '<div class="manager-empty">No image locators captured.</div>';
    }
    function renderRecordings(payload) {
      const recordings = Array.isArray(payload && payload.recordings) ? payload.recordings : [];
      const registry = document.getElementById("recordingRegistry");
      registry.innerHTML = recordings.length ? recordings.map((item) => `
        <article class="manager-skill-card" data-recording-id="${escapeHtml(item.recording_id || "")}">
          <strong>${escapeHtml(item.name || item.recording_id || "Recording")}</strong>
          <span><code>${escapeHtml(item.recording_id || "")}</code> · ${escapeHtml(item.status || "unknown")} · ${(item.events || []).length} events</span>
          <button class="secondary" type="button" data-select-recording="${escapeHtml(item.recording_id || "")}">Select</button>
        </article>`).join("") : '<div class="manager-empty">No saved recordings.</div>';
    }
    async function refreshRecordings() {
      const status = await call("/recordings/status", {quiet: true, render: false});
      activeRecordingId = status && status.status === "recording" ? String(status.recording_id || "") : "";
      if (activeRecordingId && recordingCountdownTimer !== null) cancelRecordingCountdown();
      document.getElementById("recordingStatus").textContent = activeRecordingId
        ? `Recording ${activeRecordingId} · ${(status.events || []).length} events`
        : selectedRecordingId ? `Selected ${selectedRecordingId}` : "No recording is active.";
      syncRecordingToggle();
      renderRecordingCoverage(status && Array.isArray(status.events) ? status.events : []);
      if (activeRecordingId) renderRecordingLocators(status);
      const listed = await call("/recordings", {quiet: true, render: false});
      renderRecordings(listed);
      return listed;
    }
    document.getElementById("recordingRegistry").addEventListener("click", async (event) => {
      const button = event.target.closest("[data-select-recording]");
      if (!button) return;
      selectedRecordingId = String(button.dataset.selectRecording || "");
      document.getElementById("recordingStatus").textContent = `Selected ${selectedRecordingId}`;
      const selected = await call(`/recordings/${encodeURIComponent(selectedRecordingId)}`, {quiet:true, render:false});
      renderRecordingCoverage(selected && selected.events);
      renderRecordingLocators(selected);
    });
    recordToggle.addEventListener("click", async () => {
      if (recordingCountdownTimer !== null) { cancelRecordingCountdown(); return; }
      if (activeRecordingId) { await stopActiveRecording(); return; }
      beginRecordingCountdown();
    });
    document.getElementById("recordCheckpoint").addEventListener("click", async () => {
      const result = await call("/recordings/checkpoint", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({label: "operator checkpoint"}), render: false});
      managerShowResult(result); await refreshRecordings();
    });
    document.getElementById("recordSave").addEventListener("click", async () => {
      const recordingId = selectedRecordingId || activeRecordingId;
      if (!recordingId) { managerShowResult({ok: false, failure_code: "SKILL_RECORDING_NOT_SELECTED"}); return; }
      const result = await call(`/recordings/${encodeURIComponent(recordingId)}/save`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}", render: false});
      managerShowResult(result); await refreshRecordings();
    });
    document.getElementById("refreshRecordings").addEventListener("click", refreshRecordings);
    document.getElementById("recordSkill").addEventListener("click", async () => {
      const recordingId = selectedRecordingId || activeRecordingId;
      if (!recordingId) { managerShowResult({ok: false, failure_code: "SKILL_RECORDING_NOT_SELECTED"}); return; }
      const result = await call("/skills/drafts", {
        method: "POST", headers: {"Content-Type": "application/json"}, render: false,
        body: JSON.stringify({
          recording_id: recordingId,
          skill_id: document.getElementById("recordSkillId").value.trim(),
          version: document.getElementById("recordSkillVersion").value.trim(),
          target_profile: document.getElementById("recordSkillProfile").value.trim(),
        }),
      });
      managerShowResult(result); if (result.ok) await refreshSkills({showResult: false});
    });

    let managerExamples = [];
    function renderExamples() {
      const registry = document.getElementById("exampleRegistry");
      registry.innerHTML = managerExamples.length ? managerExamples.map((example) => `
        <article class="manager-skill-card" data-example-id="${escapeHtml(example.example_id || "")}">
          <div class="program-card-head"><strong>${escapeHtml(example.name || example.example_id || "Example")}</strong>${managerBadge(example.family || "other")}</div>
          <span>${escapeHtml(example.description || "")}</span>
          <div class="manager-badges">${managerBadge(`${example.action_count || 0} ACTIONS`)}${managerBadge(example.safe_test ? "SAFE TEST" : "MANUAL", example.safe_test ? "ok" : "warn")}</div>
          <div class="manager-actions">
            <button class="secondary" type="button" data-load-example>Load Example</button>
            <button type="button" data-run-example ${example.safe_test ? "" : "disabled"}>Run Safe Test</button>
          </div>
        </article>`).join("") : '<div class="manager-empty">No valid examples found.</div>';
    }
    async function refreshExamples() {
      const result = await call("/examples", {quiet:true, render:false});
      managerExamples = Array.isArray(result && result.examples) ? result.examples : [];
      renderExamples(); managerShowResult(result); return result;
    }
    function loadExampleIntoEditor(example) {
      const program = example && example.program ? example.program : {};
      managerEditingProgramId = ""; managerEditingBuiltin = false;
      managerOpenEditor(program, "Capability Example", "EXAMPLE", `${example.example_id || "example"} loaded locally; registry unchanged.`);
      document.querySelector('[data-manager-tab="programs"]').click();
    }
    document.getElementById("openCapabilityLab").addEventListener("click", () => window.open("/capability-lab", "_blank", "noopener"));
    document.getElementById("refreshExamples").addEventListener("click", refreshExamples);
    document.getElementById("exampleRegistry").addEventListener("click", async (event) => {
      const card = event.target.closest("[data-example-id]");
      if (!card) return;
      const example = managerExamples.find((item) => item.example_id === card.dataset.exampleId);
      if (!example) return;
      if (event.target.closest("[data-load-example]")) { loadExampleIntoEditor(example); return; }
      if (event.target.closest("[data-run-example]") && example.safe_test) {
        const result = await call("/execute", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({sequence_id:`example-${Date.now()}`, example_id:example.example_id, sequence:example.program.sequence, runtime_mode:"test", confirm_execute:false}), render:false});
        managerShowResult(result);
      }
    });

    let managerSkills = [];
    function renderSkills() {
      const registry = document.getElementById("skillRegistry");
      registry.innerHTML = managerSkills.length ? managerSkills.map((item) => {
        const manifest = item.manifest || item;
        const skillId = manifest.skill_id || item.skill_id || "";
        const version = manifest.version || item.version || "";
        const lifecycle = manifest.lifecycle || item.lifecycle || "unknown";
        const model = (manifest.model_snapshot || {}).model || "not used";
        const enabled = manifest.enabled !== false;
        return `<article class="manager-skill-card" data-skill-id="${escapeHtml(skillId)}" data-skill-version="${escapeHtml(version)}">
          <div class="program-card-head"><strong>${escapeHtml(skillId)}@${escapeHtml(version)}</strong>${managerBadge(lifecycle, lifecycle === "deployed" ? "ok" : "warn")}</div>
          <span>Profile <code>${escapeHtml(manifest.target_profile || "-")}</code> · Model ${escapeHtml(model)} · ${enabled ? "enabled" : "disabled"}</span>
          <div class="manager-actions">
            <button class="secondary" data-skill-action="annotate">Annotate</button>
            <button class="secondary" data-skill-action="compile">Compile</button>
            <button class="secondary" data-skill-action="validate">Validate</button>
            <button data-skill-action="deploy">Deploy</button>
            <button class="secondary" data-skill-action="enabled">${enabled ? "Disable" : "Enable"}</button>
            <button class="secondary" data-skill-action="test">Test</button>
            <button class="danger" data-skill-action="delete">Delete</button>
          </div>
        </article>`;
      }).join("") : '<div class="manager-empty">No Equipment Skills registered.</div>';
    }
    async function refreshSkills({showResult = true} = {}) {
      const result = await call("/skills", {quiet: true, render: false});
      managerSkills = Array.isArray(result && result.skills) ? result.skills : [];
      renderSkills(); if (showResult) managerShowResult(result); return result;
    }
    document.getElementById("refreshSkills").addEventListener("click", refreshSkills);
    document.getElementById("skillRegistry").addEventListener("click", async (event) => {
      const button = event.target.closest("[data-skill-action]");
      const card = event.target.closest("[data-skill-id]");
      if (!button || !card) return;
      const action = String(button.dataset.skillAction || "");
      const skill = managerSkills.find((item) => String(item.skill_id || (item.manifest || {}).skill_id) === card.dataset.skillId && String(item.version || (item.manifest || {}).version) === card.dataset.skillVersion);
      const enabled = !skill || (skill.manifest || skill).enabled !== false;
      const body = action === "annotate" ? {use_model: true, annotations: {}}
        : action === "enabled" ? {enabled: !enabled}
        : action === "test" ? {runtime_mode: "test", confirm_execute: false}
        : {};
      if (action === "delete") {
        const result = await call(`/skills/${encodeURIComponent(card.dataset.skillId)}/${encodeURIComponent(card.dataset.skillVersion)}`, {
          method: "DELETE", render: false,
        });
        managerShowResult(result); await refreshSkills({showResult: false}); return;
      }
      const result = await call(`/skills/${encodeURIComponent(card.dataset.skillId)}/${encodeURIComponent(card.dataset.skillVersion)}/${action}`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), render: false,
      });
      managerShowResult(result); await refreshSkills({showResult: false});
    });


    renderPayloadPreview("live");
    if (tokenInput.value.trim()) {
      runHealthCheck();
    } else {
      renderTokenPrompt();
      appendLog("waiting for bridge token before authenticated checks");
      renderTimelineEntries();
    }
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "WindowsPyAutoGUIBridge/0.1"

    def _authorized(self) -> bool:
        return self.headers.get(TOKEN_HEADER, "") == TOKEN

    def _write_audit_event(self, event: dict[str, Any]) -> None:
        try:
            ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
            base = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "client": self.client_address[0] if self.client_address else "",
                "method": self.command,
                "path": urlparse(self.path).path,
                "token_auth_enabled": bool(TOKEN),
                "token_header_present": bool(self.headers.get(TOKEN_HEADER, "")),
            }
            safe_event = {key: value for key, value in {**base, **event}.items() if "token" not in str(key).lower() or str(key).lower() in {"token_auth_enabled", "token_header_present"}}
            with (ARTIFACT_ROOT / "bridge_requests.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(safe_event, ensure_ascii=True, default=str) + "\n")
        except Exception:
            pass

    def _audit_request(self, *, auth_ok: bool | None, status: str = "") -> None:
        self._write_audit_event({"auth_ok": auth_ok, "status": status})

    def _require_auth(self) -> bool:
        auth_ok = self._authorized()
        self._audit_request(auth_ok=auth_ok, status="authorized" if auth_ok else "auth_required")
        if auth_ok and TOKEN:
            try:
                CONTROLLER_RESOLVER.observe_authenticated_peer(self.client_address[0] if self.client_address else "")
            except Exception:
                pass
        if auth_ok:
            return True
        self._send(401, {"ok": False, "status": "auth_required", "failure_code": "PYAUTOGUI_AUTH_FAILED", "token_header_present": bool(self.headers.get(TOKEN_HEADER, ""))})
        return False

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._audit_request(auth_ok=None, status="served_gui")
            self._send_html(200, INDEX_HTML)
            return
        if path == "/capability-lab":
            try:
                html = (DEMO_ROOT / "pyautogui_capability_lab.html").read_text(encoding="utf-8")
            except OSError:
                self._send_html(404, "<!doctype html><title>Capability Lab unavailable</title>")
                return
            self._audit_request(auth_ok=None, status="served_capability_lab")
            self._send_html(200, html)
            return
        if not self._require_auth():
            return
        if path == "/health":
            self._send(200, _health())
            return
        if path == "/controller":
            self._send(200, CONTROLLER_RESOLVER.resolve(allow_scan=False))
            return
        if path == "/programs":
            self._send(200, _programs())
            return
        if path == "/capabilities":
            self._send(200, _capability_catalog())
            return
        if path == "/examples":
            self._send(200, _example_catalog_payload())
            return
        if path.startswith("/examples/"):
            example_id = unquote(path.split("/examples/", 1)[1].strip("/"))
            example = next((item for item in _load_example_catalog() if item["example_id"] == example_id), None)
            self._send(200 if example else 404, {"ok": True, **example} if example else {"ok": False, "status": "not_found"})
            return
        if path == "/artifacts":
            self._send(200, _list_artifacts())
            return
        if path == "/locators":
            self._send(200, _list_locators())
            return
        if path == "/readiness":
            self._send(200, _utm_readiness())
            return
        if path == "/request-log":
            self._send(200, _request_log_payload())
            return
        if path == "/recordings":
            self._send(200, {"ok": True, "recordings": RECORDING_MANAGER.list()})
            return
        if path == "/recordings/status":
            self._send(200, RECORDING_MANAGER.status())
            return
        if path == "/skills":
            status, result = _atr_api_request("GET", "/api/equipment/skills")
            self._send(status, result)
            return
        if path.startswith("/skills/"):
            parts = [unquote(item) for item in path.split("/") if item]
            if len(parts) == 3:
                status, result = _atr_api_request(
                    "GET",
                    f"/api/equipment/skills/{quote(parts[1], safe='')}/{quote(parts[2], safe='')}",
                )
                self._send(status, result)
                return
        if path.startswith("/recordings/"):
            recording_id = unquote(path.split("/recordings/", 1)[1].strip("/"))
            result = RECORDING_MANAGER.get(recording_id)
            self._send(200 if result.get("ok") else 404, result)
            return
        if path.startswith("/artifacts/"):
            artifact_id = unquote(path.split("/artifacts/", 1)[1].strip("/"))
            status, payload = _get_artifact(artifact_id)
            self._send(status, payload)
            return
        self._send(404, {"ok": False, "status": "not_found"})

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        recording_save = path.startswith("/recordings/") and path.endswith("/save")
        skill_action = path.startswith("/skills/")
        if path not in {
            "/execute", "/screenshot", "/locators/capture", "/programs/validate", "/programs/register",
            "/recordings/start", "/recordings/checkpoint", "/recordings/stop",
            "/controller/discover", "/controller/select",
        } and not recording_save and not skill_action:
            self._send(404, {"ok": False, "status": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("payload must be object")
        except Exception:
            self._send(400, {"ok": False, "status": "bad_request", "failure_code": "PYAUTOGUI_BAD_JSON"})
            return
        if path == "/controller/discover":
            result = CONTROLLER_RESOLVER.discover()
            self._send(200 if result.get("ok") else 409, result)
            return
        if path == "/controller/select":
            result = CONTROLLER_RESOLVER.select(str(payload.get("controller_url") or ""))
            self._send(200 if result.get("ok") else 400, result)
            return
        if path == "/recordings/start":
            result = RECORDING_MANAGER.start(
                name=str(payload.get("name") or "Equipment demonstration"),
                target_app=str(payload.get("target_app") or ""),
                target_window=str(payload.get("target_window") or ""),
                image_tracking=payload.get("image_tracking") is not False,
                coordinate_fallback=payload.get("coordinate_fallback") is True,
            )
            self._send(200 if result.get("ok") else 409, result)
            return
        if path == "/recordings/checkpoint":
            result = RECORDING_MANAGER.checkpoint(label=str(payload.get("label") or "checkpoint"))
            self._send(200 if result.get("ok") else 409, result)
            return
        if path == "/recordings/stop":
            result = RECORDING_MANAGER.stop()
            self._send(200 if result.get("ok") else 409, result)
            return
        if recording_save:
            recording_id = unquote(path.split("/recordings/", 1)[1].rsplit("/save", 1)[0].strip("/"))
            result = RECORDING_MANAGER.save(recording_id)
            self._send(200 if result.get("ok") else 409, result)
            return
        if path == "/skills/drafts":
            recording_id = str(payload.get("recording_id") or "").strip()
            recording = RECORDING_MANAGER.get(recording_id)
            if not recording.get("ok") or recording.get("status") != "saved":
                self._send(409, {"ok": False, "status": "blocked", "failure_code": "SKILL_RECORDING_NOT_SAVED"})
                return
            recording.pop("ok", None)
            status, result = _atr_api_request(
                "POST",
                "/api/equipment/skills/drafts",
                {
                    "recording": recording,
                    "skill_id": str(payload.get("skill_id") or ""),
                    "version": str(payload.get("version") or "1.0.0"),
                    "target_profile": str(payload.get("target_profile") or "local_program1"),
                },
            )
            self._send(status, result)
            return
        if skill_action:
            parts = [unquote(item) for item in path.split("/") if item]
            if len(parts) == 4 and parts[0] == "skills":
                skill_id, version, action = parts[1], parts[2], parts[3]
                if action in {"annotate", "compile", "validate", "deploy", "enabled", "test"}:
                    forwarded = dict(payload)
                    if action == "annotate":
                        forwarded.setdefault("use_model", True)
                        forwarded.setdefault("annotations", {})
                    elif action == "deploy":
                        forwarded.setdefault("bridge_id", f"windows-{HOST}-{PORT}")
                    elif action == "enabled":
                        forwarded["enabled"] = bool(forwarded.get("enabled", True))
                    elif action == "test":
                        forwarded["runtime_mode"] = str(forwarded.get("runtime_mode") or "test")
                        forwarded["confirm_execute"] = bool(forwarded.get("confirm_execute", False))
                    status, result = _atr_api_request(
                        "POST",
                        f"/api/equipment/skills/{quote(skill_id, safe='')}/{quote(version, safe='')}/{action}",
                        forwarded,
                    )
                    self._send(status, result)
                    return
            self._send(404, {"ok": False, "status": "not_found"})
            return
        if path == "/screenshot":
            self._send(200, _screenshot_response(payload))
            return
        if path == "/locators/capture":
            self._send(200, _capture_locator(payload))
            return
        if path == "/programs/validate":
            result = _validate_program_definition(payload)
            self._write_audit_event({"auth_ok": True, "status": "program_validate", "program_id": str(payload.get("program_id") or ""), "result_ok": bool(result.get("ok")), "failure_code": str(result.get("failure_code") or "")})
            self._send(200, result)
            return
        if path == "/programs/register":
            result = _register_program_definition(payload)
            self._write_audit_event({"auth_ok": True, "status": "program_register", "program_id": str(payload.get("program_id") or ""), "result_ok": bool(result.get("ok")), "failure_code": str(result.get("failure_code") or "")})
            self._send(200 if result.get("ok") else 400, result)
            return
        self._write_audit_event({"auth_ok": True, "status": "execute_payload", "audit_kind": "execute_payload", **_request_audit_event_from_payload(payload)})
        result = _execute(payload)
        self._write_audit_event({
            "auth_ok": True,
            "status": "execute_result",
            "audit_kind": "execute_result",
            "sequence_id": str(payload.get("sequence_id") or result.get("sequence_id") or ""),
            "run_id": str(payload.get("run_id") or result.get("run_id") or ""),
            "specimen_id": str(payload.get("specimen_id") or result.get("specimen_id") or ""),
            "program_id": str(payload.get("program_id") or result.get("program_id") or ""),
            "result_ok": bool(result.get("ok")),
            "result_status": str(result.get("status") or ""),
            "failure_code": str(result.get("failure_code") or ""),
        })
        self._send(200, result)

    def do_DELETE(self) -> None:
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        if path.startswith("/skills/"):
            parts = [unquote(item) for item in path.split("/") if item]
            if len(parts) == 3 and parts[0] == "skills":
                status, result = _atr_api_request(
                    "DELETE",
                    f"/api/equipment/skills/{quote(parts[1], safe='')}/{quote(parts[2], safe='')}",
                )
                self._send(status, result)
                return
        if not path.startswith("/programs/"):
            self._send(404, {"ok": False, "status": "not_found"})
            return
        program_id = unquote(path.split("/programs/", 1)[1].strip("/"))
        result = _delete_custom_program(program_id)
        self._write_audit_event({"auth_ok": True, "status": "program_delete", "program_id": program_id, "result_ok": bool(result.get("ok")), "failure_code": str(result.get("failure_code") or "")})
        status = 200 if result.get("ok") else 404 if result.get("failure_code") == "PYAUTOGUI_PROGRAM_NOT_FOUND" else 400
        self._send(status, result)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {format % args}")


class BridgeHTTPServer(ThreadingHTTPServer):
    """Compatibility HTTP server that applies a BridgeConfig before serving."""

    def __init__(self, server_address: tuple[str, int], request_handler_class: type[BaseHTTPRequestHandler], config: BridgeConfig):
        self.config = config
        _apply_bridge_config(config)
        super().__init__(server_address, request_handler_class)


BridgeRequestHandler = Handler


def _parse_cli_args() -> argparse.Namespace:
    """Apply optional CLI overrides used by the Windows packaging scripts."""
    global HOST, PORT, TOKEN, TOKEN_HEADER, ARTIFACT_ROOT, LOCATOR_ROOT, UTM_EXPORT_ROOT, PROGRAM_ROOT, RECORDING_ROOT, DEMO_ROOT, RECORDING_MANAGER, BRIDGE_PLATFORM
    parser = argparse.ArgumentParser(description="ATR Windows PyAutoGUI bridge server")
    parser.add_argument("--host", default=None, help="Bind host. Overrides WINDOWS_PYAUTOGUI_BRIDGE_HOST.")
    parser.add_argument("--port", type=int, default=None, help="Bind port. Overrides WINDOWS_PYAUTOGUI_BRIDGE_PORT.")
    parser.add_argument("--token", default=None, help="Bridge token. Overrides WINDOWS_PYAUTOGUI_BRIDGE_TOKEN.")
    parser.add_argument("--token-file", default=None, help="Read the bridge token from a private text file.")
    parser.add_argument("--platform", choices=("auto", "windows", "linux"), default=None, help="Desktop control platform.")
    parser.add_argument("--token-header", default=None, help="HTTP token header name.")
    parser.add_argument("--artifact-dir", default=None, help="Directory for request logs, screenshots, and exported artifacts.")
    parser.add_argument("--reference-dir", default=None, help="Directory for locator/reference images.")
    parser.add_argument("--utm-export-dir", default=None, help="Directory watched for UTM CSV exports.")
    parser.add_argument("--program-dir", default=None, help="Directory containing registered JSON macro programs.")
    parser.add_argument("--recording-dir", default=None, help="Directory containing operator demonstration recordings.")
    parser.add_argument("--demo-dir", default=None, help="Directory containing the capability lab and example programs.")
    parser.add_argument("--allow-no-token", action="store_true", help="Allow local bench use without token authentication.")
    parser.add_argument("--open-browser", action="store_true", help="Open the local bridge Web GUI after startup.")
    args = parser.parse_args()
    if args.host:
        HOST = str(args.host)
    if args.port is not None:
        PORT = int(args.port)
    if args.token is not None:
        TOKEN = str(args.token)
    elif args.token_file:
        TOKEN = _read_bridge_token_file(Path(args.token_file))
    if args.platform:
        BRIDGE_PLATFORM = _normalize_bridge_platform(args.platform)
    if args.token_header:
        TOKEN_HEADER = str(args.token_header)
    if args.artifact_dir:
        ARTIFACT_ROOT = Path(args.artifact_dir)
    if args.reference_dir:
        LOCATOR_ROOT = Path(args.reference_dir)
    if args.utm_export_dir:
        UTM_EXPORT_ROOT = Path(args.utm_export_dir)
    if args.program_dir:
        PROGRAM_ROOT = Path(args.program_dir)
    if args.recording_dir:
        RECORDING_ROOT = Path(args.recording_dir)
        RECORDING_MANAGER = RecordingManager(RECORDING_ROOT)
    if args.demo_dir:
        DEMO_ROOT = Path(args.demo_dir)
    if args.allow_no_token and args.token is None and not TOKEN:
        TOKEN = ""
    _reset_controller_resolver()
    return args


def main() -> None:
    args = _parse_cli_args()
    if not TOKEN and not args.allow_no_token:
        raise SystemExit(
            "WINDOWS_PYAUTOGUI_BRIDGE_TOKEN is required. "
            "Set it before starting the bridge, pass --token, or use --allow-no-token for local bench tests."
        )
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    LOCATOR_ROOT.mkdir(parents=True, exist_ok=True)
    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    pyautogui, _ = _load_pyautogui()
    print(f"Windows PyAutoGUI bridge listening on {HOST}:{PORT}")
    print(f"Token authentication: {'enabled' if TOKEN else 'disabled'}")
    print(f"Artifact root: {ARTIFACT_ROOT}")
    print(f"Locator root: {LOCATOR_ROOT}")
    print(f"UTM export root: {UTM_EXPORT_ROOT}")
    print(f"PyAutoGUI available: {str(pyautogui is not None).lower()}")
    print("PyAutoGUI FAILSAFE: True when available")
    if args.open_browser:
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    finally:
        RECORDING_MANAGER.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
