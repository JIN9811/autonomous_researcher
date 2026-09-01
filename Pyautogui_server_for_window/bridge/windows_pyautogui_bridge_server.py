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
  GET  /recordings/{recording_id}/package
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
import locale
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
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


def _bridge_package_root() -> Path:
    configured = str(os.getenv("ATR_WINDOWS_BRIDGE_PACKAGE_ROOT") or "").strip()
    if configured:
        return Path(configured)
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "bridge" else script.parent


def _bridge_release_manifest(package_root: Path | None = None) -> dict[str, Any]:
    manifest_path = (package_root or _bridge_package_root()) / "release_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


BRIDGE_CODE_RELEASE_FLOOR = "2026.08.29.17"


def _release_version_key(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", str(value or "")))


def _bridge_release_version(package_root: Path | None = None) -> str:
    version = str(_bridge_release_manifest(package_root).get("version") or "").strip()
    if _release_version_key(version) >= _release_version_key(BRIDGE_CODE_RELEASE_FLOOR):
        return version
    return BRIDGE_CODE_RELEASE_FLOOR


def _bridge_update_allowed_paths(package_root: Path | None = None) -> set[str]:
    files = _bridge_release_manifest(package_root).get("files")
    if not isinstance(files, list):
        return {"release_manifest.json"}
    return {str(item).strip().replace("\\", "/") for item in files if str(item).strip()} | {"release_manifest.json"}


HOST = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "")
TOKEN_HEADER = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN_HEADER", "X-Bridge-Token")
ARTIFACT_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT", r"C:\ATR\bridge_artifacts"))
LOCATOR_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_LOCATOR_ROOT", r"C:\ATR\equipment_locators"))
UTM_EXPORT_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR", r"C:\ATR\utm_exports"))
PROGRAM_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_PROGRAM_DIR", r"C:\ATR\programs"))
RECORDING_ROOT = Path(os.getenv("WINDOWS_PYAUTOGUI_RECORDING_DIR", r"C:\ATR\recordings"))
BRIDGE_RELEASE_VERSION = _bridge_release_version()
UPDATE_ALLOWED_PATHS = _bridge_update_allowed_paths()
MAX_UPDATE_FILE_BYTES = 12 * 1024 * 1024
MAX_UPDATE_PACKAGE_BYTES = 24 * 1024 * 1024


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


def _windows_input_language_state(
    *,
    user32: Any | None = None,
    imm32: Any | None = None,
    windows_locale: dict[int, str] | None = None,
) -> dict[str, str]:
    """Read the foreground Windows keyboard layout and Korean IME mode."""
    injected_api = user32 is not None or imm32 is not None
    if not injected_api and not sys.platform.startswith("win"):
        return {
            "status": "unavailable",
            "layout_id": "",
            "locale": "",
            "language": "",
            "ime_mode": "unknown",
            "typing_mode": "unknown",
        }
    try:
        import ctypes

        if user32 is None or imm32 is None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            imm32 = ctypes.WinDLL("imm32", use_last_error=True)
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetKeyboardLayout.restype = ctypes.c_void_p
            imm32.ImmGetContext.restype = ctypes.c_void_p

        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, None)
        raw_layout = user32.GetKeyboardLayout(thread_id)
        layout_value = int(raw_layout or 0) & 0xFFFFFFFF
        language_id = layout_value & 0xFFFF
        locale_name = str((windows_locale or locale.windows_locale).get(language_id) or f"lang_{language_id:04x}")
        language = re.split(r"[-_]", locale_name, maxsplit=1)[0].lower()

        ime_mode = "unknown"
        typing_mode = "unknown" if language == "ko" else (language or "unknown")
        context = imm32.ImmGetContext(hwnd)
        if context:
            conversion = ctypes.c_uint32(0)
            sentence = ctypes.c_uint32(0)
            try:
                if imm32.ImmGetConversionStatus(context, ctypes.byref(conversion), ctypes.byref(sentence)):
                    ime_mode = "native" if conversion.value & 0x0001 else "alphanumeric"
                    typing_mode = language if ime_mode == "native" else "latin"
            finally:
                imm32.ImmReleaseContext(hwnd, context)
        if ime_mode == "unknown":
            get_default_ime_window = getattr(imm32, "ImmGetDefaultIMEWnd", None)
            send_message = getattr(user32, "SendMessageW", None)
            ime_window = get_default_ime_window(hwnd) if callable(get_default_ime_window) else 0
            if ime_window and callable(send_message):
                conversion_mode = int(send_message(ime_window, 0x0283, 0x0001, 0))
                ime_mode = "native" if conversion_mode & 0x0001 else "alphanumeric"
                typing_mode = language if ime_mode == "native" else "latin"
        if ime_mode == "unknown" and language != "ko":
            ime_mode = "alphanumeric"

        return {
            "status": "available",
            "layout_id": f"{language_id:08X}",
            "locale": locale_name,
            "language": language,
            "ime_mode": ime_mode,
            "typing_mode": typing_mode,
        }
    except Exception:
        return {
            "status": "unavailable",
            "layout_id": "",
            "locale": "",
            "language": "",
            "ime_mode": "unknown",
            "typing_mode": "unknown",
        }


def _set_windows_input_language(
    target: dict[str, Any],
    *,
    user32: Any | None = None,
    imm32: Any | None = None,
) -> dict[str, Any]:
    """Restore a recorded Windows keyboard layout and foreground IME mode."""
    layout_id = str(target.get("layout_id") or "").strip().upper()
    typing_mode = str(target.get("typing_mode") or "").strip().lower()
    ime_mode = str(target.get("ime_mode") or "unknown").strip().lower()
    language = str(target.get("language") or "").strip().lower()
    if not re.fullmatch(r"[0-9A-F]{8}", layout_id):
        return {
            "ok": False,
            "failure_code": "WINDOWS_INPUT_LAYOUT_INVALID",
            "message": "set_input_language requires an 8-digit hexadecimal layout_id.",
        }
    if not typing_mode or typing_mode == "unknown":
        return {
            "ok": False,
            "failure_code": "WINDOWS_INPUT_MODE_INVALID",
            "message": "set_input_language requires a known typing_mode.",
        }
    injected_api = user32 is not None or imm32 is not None
    if not injected_api and not sys.platform.startswith("win"):
        return {
            "ok": False,
            "failure_code": "WINDOWS_INPUT_LANGUAGE_UNAVAILABLE",
            "message": "Windows input-language APIs are unavailable on this platform.",
        }
    try:
        import ctypes

        if user32 is None or imm32 is None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            imm32 = ctypes.WinDLL("imm32", use_last_error=True)
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
            user32.ActivateKeyboardLayout.restype = ctypes.c_void_p
            imm32.ImmGetContext.restype = ctypes.c_void_p

        layout = user32.LoadKeyboardLayoutW(layout_id, 0x00000001)
        layout_value = int(getattr(layout, "value", layout) or 0)
        if not layout_value:
            raise RuntimeError("LoadKeyboardLayoutW failed")
        user32.ActivateKeyboardLayout(layout, 0x00000100)
        hwnd = user32.GetForegroundWindow()
        post_message = getattr(user32, "PostMessageW", None)
        if hwnd and callable(post_message):
            post_message(hwnd, 0x0050, 0, layout)

        desired_native = ime_mode == "native" or (ime_mode == "unknown" and typing_mode not in {"latin", "en"})
        ime_required = language == "ko" or ime_mode in {"native", "alphanumeric"}
        ime_updated = not ime_required
        context = imm32.ImmGetContext(hwnd) if hwnd else 0
        if context:
            conversion = ctypes.c_uint32(0)
            sentence = ctypes.c_uint32(0)
            try:
                if imm32.ImmGetConversionStatus(context, ctypes.byref(conversion), ctypes.byref(sentence)):
                    next_conversion = conversion.value | 0x0001 if desired_native else conversion.value & ~0x0001
                    ime_updated = bool(imm32.ImmSetConversionStatus(context, next_conversion, sentence.value))
            finally:
                imm32.ImmReleaseContext(hwnd, context)
        if ime_required and not ime_updated:
            get_default_ime_window = getattr(imm32, "ImmGetDefaultIMEWnd", None)
            send_message = getattr(user32, "SendMessageW", None)
            ime_window = get_default_ime_window(hwnd) if hwnd and callable(get_default_ime_window) else 0
            if ime_window and callable(send_message):
                send_message(ime_window, 0x0283, 0x0002, 0x0001 if desired_native else 0)
                ime_updated = True
        if ime_required and not ime_updated:
            raise RuntimeError("foreground IME mode could not be restored")
        return {"ok": True, "target": dict(target), "layout_id": layout_id, "typing_mode": typing_mode}
    except Exception as exc:
        return {
            "ok": False,
            "failure_code": "WINDOWS_INPUT_LANGUAGE_SET_FAILED",
            "message": f"Windows input language could not be restored: {exc}",
        }


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
            self.manager.record_keyboard_event({"kind": "hotkey", "keys": [*modifiers, name]})
            return
        self.manager.record_keyboard_event({"kind": "key_press", "key": name})

    def on_release(self, key: Any) -> None:
        modifier = self._MODIFIERS.get(self.key_name(key))
        if not modifier:
            return
        if modifier not in self._used_modifiers:
            self.manager.record_keyboard_event({"kind": "key_press", "key": modifier})
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

    def __init__(self, on_stop: Callable[[], None] | None = None) -> None:
        import tkinter as tk

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        try:
            self._root.attributes("-toolwindow", True)
        except Exception:
            pass
        width, height = 340, 48
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
        def request_stop() -> None:
            if not callable(on_stop):
                return
            on_stop(
                {
                    "control": "overlay_stop",
                    "x": int(self._root.winfo_pointerx()),
                    "y": int(self._root.winfo_pointery()),
                }
            )

        tk.Button(
            frame,
            text="STOP",
            command=request_stop,
            fg="#ffffff",
            bg="#b42318",
            activeforeground="#ffffff",
            activebackground="#8f1c14",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(side="right", padx=(10, 2), pady=8)
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
        window_factory: Callable[[Callable[[], None]], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval: float = 0.1,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._enabled = str(platform_name or sys.platform).lower().startswith("win") or window_factory is not None
        self._window_factory = window_factory or _TkRecordingOverlayWindow
        self._monotonic = monotonic
        self._poll_interval = max(0.005, float(poll_interval))
        self._stop_callback = on_stop
        self._commands: queue.Queue[tuple[str, str, float]] = queue.Queue()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._available = self._enabled
        self._visible = False
        self._error: str | None = None if self._enabled else "windows_only"
        self._stop_requested = False
        self._stop_request: dict[str, Any] | None = None
        self._stop_thread: threading.Thread | None = None

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

    def set_stop_callback(self, callback: Callable[[], None] | None) -> None:
        self._stop_callback = callback

    def request_stop(self, evidence: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._stop_requested:
                return
            callback = self._stop_callback
            if not callable(callback):
                return
            self._stop_requested = True
            value = dict(evidence or {})
            self._stop_request = {
                "control": str(value.get("control") or "overlay_stop")[:64],
                "x": int(value.get("x", 0)),
                "y": int(value.get("y", 0)),
            }
            self._commands.put(("hide", "", 0.0))
            self._stop_thread = threading.Thread(
                target=self._run_stop_callback,
                args=(callback,),
                name="atr-recording-stop",
                daemon=True,
            )
            self._stop_thread.start()

    def consume_stop_request(self) -> dict[str, Any]:
        with self._lock:
            value = dict(self._stop_request or {})
            self._stop_request = None
            return value

    def _run_stop_callback(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            with self._lock:
                self._error = f"recording stop failed: {exc.__class__.__name__}: {str(exc)[:120]}"
        finally:
            with self._lock:
                self._stop_requested = False

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
        stop_thread = self._stop_thread
        if stop_thread is not None and stop_thread is not threading.current_thread():
            stop_thread.join(timeout=2.0)

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
                    window = self._window_factory(self.request_stop)
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
class RecordingFrameBuffer:
    """Disk-backed low-rate recording timeline with a bounded recent-frame cache."""

    SCHEMA = "atr.equipment_recording_frames.v1"
    DISK_WARNING_BYTES = 2 * 1024 * 1024 * 1024
    DISK_CRITICAL_BYTES = 512 * 1024 * 1024

    def __init__(
        self,
        *,
        screenshot_provider: Callable[[], Any],
        fps: float = 2.0,
        retention_sec: float = 20.0,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._screenshot_provider = screenshot_provider
        self.fps = max(2.0, min(float(fps), 5.0))
        self.retention_sec = max(20.0, min(float(retention_sec), 30.0))
        self.max_bytes = max(4 * 1024 * 1024, min(int(max_bytes), 256 * 1024 * 1024))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._recording_id = ""
        self._recording_dir: Path | None = None
        self._timeline_path: Path | None = None
        self._started_monotonic = 0.0
        self._frames: list[dict[str, Any]] = []
        self._supplemental_frames: list[dict[str, Any]] = []
        self._pending_event_links: list[dict[str, Any]] = []
        self._start_boundary_pending = False
        self._total_bytes = 0
        self._persisted_frame_count = 0
        self._next_frame_number = 1
        self._writer_status = "idle"
        self._storage_state = "unknown"
        self._disk_free_bytes = -1
        self._capture_errors = 0
        self._last_error = ""
        self._pinned_exception_windows: dict[str, dict[str, Any]] = {}

    def empty_manifest(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "fps": self.fps,
            "retention_sec": self.retention_sec,
            "max_bytes": self.max_bytes,
            "storage_mode": "full_session_disk",
            "sampled_frame_count": 0,
            "persisted_frame_count": 0,
            "periodic_frame_count": 0,
            "timeline_path": "",
            "writer_status": self._writer_status,
            "storage_state": self._storage_state,
            "disk_free_bytes": self._disk_free_bytes,
            "evidence_complete": self._writer_status != "incomplete" and self._storage_state != "critical",
            "frames": [],
            "event_frame_count": 0,
            "event_frames": [],
            "exception_window_count": 0,
            "exception_windows": [],
            "capture_errors": 0,
        }

    def start(self, recording_id: str, started_monotonic: float, recording_dir: Path | None = None) -> None:
        self.stop()
        with self._lock:
            self._recording_id = str(recording_id)
            self._recording_dir = Path(recording_dir) if recording_dir is not None else None
            self._timeline_path = self._recording_dir / "timeline.jsonl" if self._recording_dir is not None else None
            self._started_monotonic = float(started_monotonic)
            self._frames = []
            self._supplemental_frames = []
            self._pending_event_links = []
            self._start_boundary_pending = True
            self._total_bytes = 0
            self._persisted_frame_count = 0
            self._next_frame_number = 1
            self._writer_status = "recording"
            self._storage_state = "healthy"
            self._disk_free_bytes = -1
            self._capture_errors = 0
            self._last_error = ""
            self._pinned_exception_windows = {}
            self._stop_event.clear()
            if self._recording_dir is not None:
                (self._recording_dir / "frames" / "periodic").mkdir(parents=True, exist_ok=True)
                self._timeline_path.parent.mkdir(parents=True, exist_ok=True)
                self._timeline_path.write_text("", encoding="utf-8")
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"atr-recording-frames-{recording_id[-8:]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, 2.0 / self.fps))
        self._thread = None
        with self._lock:
            if self._writer_status == "recording":
                self._writer_status = "stopped"

    def capture_once(self) -> bool:
        with self._lock:
            started = self._started_monotonic
            recording_dir = self._recording_dir
        if not started:
            return False
        if recording_dir is not None and not self._check_storage_health(recording_dir):
            return False
        try:
            image = self._screenshot_provider()
            raw, media_type, suffix, width, height = self._encode_frame(image)
        except Exception as exc:
            with self._lock:
                self._capture_errors += 1
                self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
            return False
        captured = time.monotonic()
        with self._lock:
            frame_number = self._next_frame_number
            self._next_frame_number += 1
            recording_dir = self._recording_dir
            timeline_path = self._timeline_path
        frame_id = f"frame-{frame_number:08d}"
        artifact_path = ""
        if recording_dir is not None and timeline_path is not None:
            artifact = recording_dir / "frames" / "periodic" / f"{frame_id}{suffix}"
            temporary = artifact.with_name(f".{artifact.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(raw)
                os.replace(temporary, artifact)
                artifact_path = str(artifact)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                with self._lock:
                    self._capture_errors += 1
                    self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                    self._writer_status = "incomplete"
                return False
        frame = {
            "frame_id": frame_id,
            "at_ms": max(0, int((captured - started) * 1000)),
            "captured_monotonic": captured,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "media_type": media_type,
            "suffix": suffix,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "artifact_path": artifact_path,
            "reason": "periodic",
            "bytes": raw,
        }
        if timeline_path is not None:
            timeline_row = {key: value for key, value in frame.items() if key not in {"bytes", "suffix", "captured_monotonic"}}
            try:
                with timeline_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(timeline_row, ensure_ascii=True, separators=(",", ":")) + "\n")
            except Exception as exc:
                Path(artifact_path).unlink(missing_ok=True)
                with self._lock:
                    self._capture_errors += 1
                    self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                    self._writer_status = "incomplete"
                return False
        with self._lock:
            self._frames.append(frame)
            self._total_bytes += len(raw)
            self._persisted_frame_count += 1
            self._persist_pending_exception_frame_locked(frame)
            cutoff = captured - self.retention_sec
            while self._frames and (
                float(self._frames[0]["captured_monotonic"]) < cutoff or self._total_bytes > self.max_bytes
            ):
                removed = self._frames.pop(0)
                self._total_bytes -= len(removed["bytes"])
            start_boundary_pending = self._start_boundary_pending
            self._start_boundary_pending = False
        if start_boundary_pending:
            self._persist_boundary_image(image, "recording_start", at_ms=0)
        self._persist_pending_event_posts(image, captured)
        return True

    def _check_storage_health(self, recording_dir: Path) -> bool:
        try:
            free_bytes = int(shutil.disk_usage(recording_dir).free)
        except OSError as exc:
            with self._lock:
                self._writer_status = "incomplete"
                self._storage_state = "critical"
                self._last_error = f"disk usage unavailable: {exc}"
            return False
        with self._lock:
            self._disk_free_bytes = free_bytes
            if free_bytes < self.DISK_CRITICAL_BYTES:
                self._writer_status = "incomplete"
                self._storage_state = "critical"
                self._last_error = f"recording stopped: only {free_bytes} disk bytes remain"
                return False
            if free_bytes < self.DISK_WARNING_BYTES:
                if self._writer_status == "recording":
                    self._writer_status = "warning"
                self._storage_state = "warning"
            else:
                if self._writer_status == "warning":
                    self._writer_status = "recording"
                self._storage_state = "healthy"
        return True

    @staticmethod
    def _encode_png(image: Any) -> tuple[bytes, int, int]:
        frame = image.copy() if callable(getattr(image, "copy", None)) else image
        size = getattr(frame, "size", (0, 0))
        width, height = (int(size[0]), int(size[1])) if isinstance(size, tuple) and len(size) >= 2 else (0, 0)
        buffer = BytesIO()
        frame.save(buffer, format="PNG")
        return buffer.getvalue(), width, height

    def _append_supplemental_frame(self, frame: dict[str, Any]) -> None:
        with self._lock:
            timeline_path = self._timeline_path
        if timeline_path is not None:
            with timeline_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(frame, ensure_ascii=True, separators=(",", ":")) + "\n")
        with self._lock:
            self._supplemental_frames.append(frame)

    def _persist_boundary_image(self, image: Any, reason: str, *, at_ms: int) -> dict[str, Any] | None:
        if reason not in {"recording_start", "recording_stop"}:
            raise ValueError("unsupported recording boundary")
        with self._lock:
            recording_dir = self._recording_dir
        if recording_dir is None:
            return None
        try:
            raw, width, height = self._encode_png(image)
            frame_at_ms = max(0, int(at_ms))
            frame_id = f"boundary-{'start' if reason == 'recording_start' else 'stop'}"
            directory = recording_dir / "frames" / "boundaries"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{frame_id}.png"
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            temporary.write_bytes(raw)
            os.replace(temporary, path)
            frame = {
                "frame_id": frame_id,
                "at_ms": frame_at_ms,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "media_type": "image/png",
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "artifact_path": str(path),
                "reason": reason,
            }
            self._append_supplemental_frame(frame)
            return frame
        except Exception as exc:
            with self._lock:
                self._capture_errors += 1
                self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                self._writer_status = "incomplete"
            return None

    def capture_boundary_frame(self, reason: str, *, at_ms: int | None = None) -> dict[str, Any] | None:
        """Persist a clean PNG at a recording start or stop boundary."""
        with self._lock:
            started = self._started_monotonic
        if not started:
            return None
        try:
            image = self._screenshot_provider()
        except Exception as exc:
            with self._lock:
                self._capture_errors += 1
                self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                self._writer_status = "incomplete"
            return None
        frame_at_ms = max(0, int(at_ms if at_ms is not None else (time.monotonic() - started) * 1000))
        return self._persist_boundary_image(image, reason, at_ms=frame_at_ms)

    def persist_event_frame(
        self,
        recording_dir: Path,
        *,
        event_number: int,
        event_at_ms: int,
        max_delta_ms: int = 1000,
    ) -> dict[str, Any] | None:
        """Persist an exact event PNG and link it to pre/post source frames."""
        with self._lock:
            frames = list(self._frames)
        pre_candidates = [item for item in frames if int(item["at_ms"]) <= int(event_at_ms)]
        nearest = max(pre_candidates, key=lambda item: int(item["at_ms"])) if pre_candidates else None
        if nearest is None and frames:
            nearest = min(frames, key=lambda item: abs(int(item["at_ms"]) - event_at_ms))
        if nearest is None or abs(int(nearest["at_ms"]) - event_at_ms) > max(100, int(max_delta_ms)):
            return None
        try:
            image = self._screenshot_provider()
            raw, width, height = self._encode_png(image)
        except Exception as exc:
            with self._lock:
                self._capture_errors += 1
                self._last_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
            return None
        output_dir = recording_dir / "frames" / "events"
        output_dir.mkdir(parents=True, exist_ok=True)
        event_frame_id = f"event-{event_number:04d}"
        path = output_dir / f"{event_frame_id}-{event_at_ms:08d}ms.png"
        path.write_bytes(raw)
        event_frame = {
            "frame_id": event_frame_id,
            "at_ms": int(event_at_ms),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artifact_path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "media_type": "image/png",
            "width": width,
            "height": height,
            "reason": "event",
            "event_number": int(event_number),
        }
        self._append_supplemental_frame(event_frame)
        linkage = {
            "event_number": int(event_number),
            "event_at_ms": int(event_at_ms),
            "at_ms": int(event_at_ms),
            "artifact_path": str(path),
            "sha256": event_frame["sha256"],
            "media_type": "image/png",
            "width": width,
            "height": height,
            "reason": "event",
            "pre_frame_id": str(nearest["frame_id"]),
            "pre_frame_sha256": str(nearest["sha256"]),
            "event_frame_id": event_frame_id,
            "event_frame_sha256": event_frame["sha256"],
            "event_artifact_path": str(path),
            "post_frame_id": "",
            "post_frame_sha256": "",
            "post_artifact_path": "",
        }
        with self._lock:
            self._pending_event_links.append(linkage)
        return linkage

    def _persist_pending_event_posts(self, image: Any, captured_monotonic: float) -> None:
        with self._lock:
            started = self._started_monotonic
            recording_dir = self._recording_dir
            pending = [item for item in self._pending_event_links if not item.get("post_frame_id")]
        if not pending or not started or recording_dir is None:
            return
        frame_at_ms = max(0, int((captured_monotonic - started) * 1000))
        due = [item for item in pending if frame_at_ms > int(item.get("event_at_ms", 0))]
        if not due:
            return
        try:
            raw, width, height = self._encode_png(image)
        except Exception:
            return
        output_dir = recording_dir / "frames" / "events"
        output_dir.mkdir(parents=True, exist_ok=True)
        for linkage in due:
            event_number = int(linkage["event_number"])
            frame_id = f"event-{event_number:04d}-post"
            path = output_dir / f"{frame_id}-{frame_at_ms:08d}ms.png"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            frame = {
                "frame_id": frame_id,
                "at_ms": frame_at_ms,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "artifact_path": str(path),
                "sha256": digest,
                "media_type": "image/png",
                "width": width,
                "height": height,
                "reason": "post_action",
                "event_number": event_number,
            }
            self._append_supplemental_frame(frame)
            linkage["post_frame_id"] = frame_id
            linkage["post_frame_sha256"] = digest
            linkage["post_artifact_path"] = str(path)

    def pin_exception_window(
        self,
        recording_dir: Path,
        exception: dict[str, Any],
        *,
        pre_sec: float,
        post_sec: float,
    ) -> dict[str, Any]:
        """Persist exception-adjacent frames immediately so rolling eviction cannot remove them."""
        exception_id = str(exception.get("exception_id") or "exception-unknown")[:96]
        exception_at_ms = max(0, int(exception.get("at_ms", 0)))
        pre_window_ms = max(0, min(int(float(pre_sec) * 1000), int(self.retention_sec * 1000)))
        post_window_ms = max(0, min(int(float(post_sec) * 1000), int(self.retention_sec * 1000)))
        with self._lock:
            output_dir = recording_dir / "timeline" / "exception_windows" / exception_id
            output_dir.mkdir(parents=True, exist_ok=True)
            window = {
                "exception_id": exception_id,
                "failure_code": str(exception.get("failure_code") or "RECORDING_EXCEPTION")[:96],
                "at_ms": exception_at_ms,
                "pre_window_ms": pre_window_ms,
                "post_window_ms": post_window_ms,
                "end_at_ms": exception_at_ms + post_window_ms,
                "output_dir": output_dir,
                "frames": [],
                "seen_at_ms": set(),
            }
            candidates = [
                frame
                for frame in self._frames
                if exception_at_ms - pre_window_ms <= int(frame["at_ms"]) <= exception_at_ms + post_window_ms
            ]
            if not candidates and self._frames:
                candidates = [min(self._frames, key=lambda item: abs(int(item["at_ms"]) - exception_at_ms))]
            self._pinned_exception_windows[exception_id] = window
            for frame in candidates:
                self._persist_exception_frame_locked(window, frame)
            return {
                "exception_id": exception_id,
                "pre_window_ms": pre_window_ms,
                "post_window_ms": post_window_ms,
                "pinned_frame_count": len(window["frames"]),
            }

    def _persist_pending_exception_frame_locked(self, frame: dict[str, Any]) -> None:
        frame_at_ms = int(frame["at_ms"])
        for window in self._pinned_exception_windows.values():
            lower = int(window["at_ms"]) - int(window["pre_window_ms"])
            if lower <= frame_at_ms <= int(window["end_at_ms"]):
                self._persist_exception_frame_locked(window, frame)

    @staticmethod
    def _persist_exception_frame_locked(window: dict[str, Any], frame: dict[str, Any]) -> None:
        frame_at_ms = int(frame["at_ms"])
        seen_at_ms = window["seen_at_ms"]
        if frame_at_ms in seen_at_ms:
            return
        path = Path(window["output_dir"]) / f"frame-{frame_at_ms:08d}ms{frame['suffix']}"
        path.write_bytes(frame["bytes"])
        seen_at_ms.add(frame_at_ms)
        window["frames"].append(
            {
                "at_ms": frame_at_ms,
                "artifact_path": str(path),
                "sha256": str(frame["sha256"]),
                "media_type": str(frame["media_type"]),
                "width": int(frame["width"]),
                "height": int(frame["height"]),
                "reason": "exception_window",
                "exception_ids": [str(window["exception_id"])],
            }
        )

    def _persisted_periodic_frames(self) -> list[dict[str, Any]]:
        with self._lock:
            timeline_path = self._timeline_path
        if timeline_path is None or not timeline_path.is_file():
            return []
        frames: list[dict[str, Any]] = []
        for raw_line in timeline_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(item, dict)
                or not str(item.get("frame_id") or "")
                or str(item.get("reason") or "") != "periodic"
            ):
                continue
            frames.append(item)
        return sorted(frames, key=lambda item: (int(item.get("at_ms", 0)), str(item.get("frame_id") or "")))

    def _disk_timeline_manifest(
        self,
        *,
        exceptions: Any,
        timeline_id: str,
        exception_pre_sec: float,
        exception_post_sec: float,
    ) -> dict[str, Any] | None:
        frames = self._persisted_periodic_frames()
        with self._lock:
            timeline_path = self._timeline_path
            capture_errors = self._capture_errors
            last_error = self._last_error
            writer_status = self._writer_status
            supplemental_frames = [dict(item) for item in self._supplemental_frames]
            storage_state = self._storage_state
            disk_free_bytes = self._disk_free_bytes
        if timeline_path is None:
            return None
        manifest = self.empty_manifest()
        manifest.update(
            {
                "timeline_id": str(timeline_id or ""),
                "timeline_path": str(timeline_path),
                "sampled_frame_count": len(frames),
                "persisted_frame_count": len(frames),
                "periodic_frame_count": len(frames),
                "frames": sorted(
                    frames + supplemental_frames,
                    key=lambda item: (int(item.get("at_ms", 0)), str(item.get("frame_id") or "")),
                ),
                "capture_errors": capture_errors,
                "writer_status": writer_status,
                "storage_state": storage_state,
                "disk_free_bytes": disk_free_bytes,
                "evidence_complete": writer_status != "incomplete" and storage_state != "critical",
            }
        )
        event_frames = [
            item for item in supplemental_frames if item.get("reason") in {"event", "post_action"}
        ]
        manifest["event_frame_count"] = len(event_frames)
        manifest["event_frames"] = event_frames
        if last_error:
            manifest["last_capture_error"] = last_error
        windows: list[dict[str, Any]] = []
        pre_window_ms = max(0, int(float(exception_pre_sec) * 1000))
        post_window_ms = max(0, int(float(exception_post_sec) * 1000))
        for ordinal, exception in enumerate(exceptions or [], start=1):
            if not isinstance(exception, dict):
                continue
            exception_at = max(0, int(exception.get("at_ms", 0)))
            candidates = [
                frame
                for frame in frames
                if exception_at - pre_window_ms <= int(frame.get("at_ms", 0)) <= exception_at + post_window_ms
            ]
            if not candidates and frames:
                candidates = [min(frames, key=lambda item: abs(int(item.get("at_ms", 0)) - exception_at))]
            windows.append(
                {
                    "exception_id": str(exception.get("exception_id") or f"exception-{ordinal:03d}")[:96],
                    "failure_code": str(exception.get("failure_code") or "RECORDING_EXCEPTION")[:96],
                    "at_ms": exception_at,
                    "pre_window_ms": pre_window_ms,
                    "post_window_ms": post_window_ms,
                    "frame_ids": [str(item.get("frame_id") or "") for item in candidates],
                }
            )
        manifest["exception_window_count"] = len(windows)
        manifest["exception_windows"] = windows
        return manifest

    def persist_event_keyframes(
        self,
        recording_dir: Path,
        events: Any,
        *,
        exceptions: Any = None,
        timeline_id: str = "",
        exception_pre_sec: float = 5.0,
        exception_post_sec: float = 5.0,
    ) -> dict[str, Any]:
        disk_manifest = self._disk_timeline_manifest(
            exceptions=exceptions,
            timeline_id=timeline_id,
            exception_pre_sec=exception_pre_sec,
            exception_post_sec=exception_post_sec,
        )
        if disk_manifest is not None:
            return disk_manifest
        with self._lock:
            frames = [dict(item) for item in self._frames]
            pinned_windows = [
                {
                    key: ([dict(frame) for frame in value] if key == "frames" else value)
                    for key, value in window.items()
                    if key not in {"output_dir", "seen_at_ms", "end_at_ms"}
                }
                for window in self._pinned_exception_windows.values()
            ]
            capture_errors = self._capture_errors
            last_error = self._last_error
        manifest = self.empty_manifest()
        manifest["timeline_id"] = str(timeline_id or "")
        manifest["sampled_frame_count"] = len(frames)
        manifest["capture_errors"] = capture_errors
        if last_error:
            manifest["last_capture_error"] = last_error
        if not frames and not pinned_windows:
            return manifest
        event_times = [
            max(0, int(item.get("at_ms", 0)))
            for item in events
            if isinstance(item, dict) and item.get("kind") != "mouse_move"
        ]
        selected_indices = ({0, len(frames) - 1} if frames else set())
        exception_indices: dict[str, set[int]] = {}
        for event_at in event_times[:200]:
            selected_indices.add(min(range(len(frames)), key=lambda index: abs(int(frames[index]["at_ms"]) - event_at)))
        pre_window_ms = max(0, min(int(float(exception_pre_sec) * 1000), int(self.retention_sec * 1000)))
        post_window_ms = max(0, min(int(float(exception_post_sec) * 1000), int(self.retention_sec * 1000)))
        pinned_exception_ids = {str(item["exception_id"]) for item in pinned_windows}
        for ordinal, exception in enumerate(exceptions or [], start=1):
            if not isinstance(exception, dict):
                continue
            exception_id = str(exception.get("exception_id") or f"exception-{ordinal:03d}")[:96]
            if exception_id in pinned_exception_ids:
                continue
            exception_at = max(0, int(exception.get("at_ms", 0)))
            indices = {
                index
                for index, frame in enumerate(frames)
                if exception_at - pre_window_ms <= int(frame["at_ms"]) <= exception_at + post_window_ms
            }
            if not indices:
                indices.add(min(range(len(frames)), key=lambda index: abs(int(frames[index]["at_ms"]) - exception_at)))
            exception_indices[exception_id] = indices
            selected_indices.update(indices)
        output_dir = recording_dir / "timeline" / "keyframes"
        output_dir.mkdir(parents=True, exist_ok=True)
        persisted: list[dict[str, Any]] = []
        for ordinal, index in enumerate(sorted(selected_indices), start=1):
            frame = frames[index]
            path = output_dir / f"frame-{ordinal:04d}-{int(frame['at_ms']):08d}ms{frame['suffix']}"
            path.write_bytes(frame["bytes"])
            exception_reasons = sorted(
                exception_id for exception_id, indices in exception_indices.items() if index in indices
            )
            persisted.append(
                {
                    "frame_id": f"frame-{ordinal:04d}",
                    "at_ms": int(frame["at_ms"]),
                    "artifact_path": str(path),
                    "sha256": str(frame["sha256"]),
                    "media_type": str(frame["media_type"]),
                    "width": int(frame["width"]),
                    "height": int(frame["height"]),
                    "reason": (
                        "exception_window"
                        if exception_reasons
                        else ("boundary" if index in {0, len(frames) - 1} else "event_nearest")
                    ),
                    "exception_ids": exception_reasons,
                }
            )
        frame_id_by_index = {
            index: f"frame-{ordinal:04d}"
            for ordinal, index in enumerate(sorted(selected_indices), start=1)
        }
        windows: list[dict[str, Any]] = []
        exception_lookup = {
            str(item.get("exception_id") or f"exception-{ordinal:03d}")[:96]: item
            for ordinal, item in enumerate(exceptions or [], start=1)
            if isinstance(item, dict)
        }
        for exception_id, indices in exception_indices.items():
            exception = exception_lookup.get(exception_id, {})
            windows.append(
                {
                    "exception_id": exception_id,
                    "failure_code": str(exception.get("failure_code") or "RECORDING_EXCEPTION")[:96],
                    "at_ms": max(0, int(exception.get("at_ms", 0))),
                    "pre_window_ms": pre_window_ms,
                    "post_window_ms": post_window_ms,
                    "frame_ids": [frame_id_by_index[index] for index in sorted(indices)],
                }
            )
        for pinned_window in pinned_windows:
            frame_ids: list[str] = []
            for frame in sorted(pinned_window.get("frames", []), key=lambda item: int(item["at_ms"])):
                frame_id = f"frame-{len(persisted) + 1:04d}"
                persisted.append({"frame_id": frame_id, **frame})
                frame_ids.append(frame_id)
            windows.append(
                {
                    "exception_id": str(pinned_window["exception_id"]),
                    "failure_code": str(pinned_window["failure_code"]),
                    "at_ms": int(pinned_window["at_ms"]),
                    "pre_window_ms": int(pinned_window["pre_window_ms"]),
                    "post_window_ms": int(pinned_window["post_window_ms"]),
                    "frame_ids": frame_ids,
                }
            )
        manifest["persisted_frame_count"] = len(persisted)
        manifest["frames"] = persisted
        manifest["exception_window_count"] = len(windows)
        manifest["exception_windows"] = windows
        return manifest

    def release(self) -> None:
        """Release image bytes after the selected evidence has been persisted."""
        with self._lock:
            self._frames = []
            self._supplemental_frames = []
            self._pending_event_links = []
            self._start_boundary_pending = False
            self._total_bytes = 0
            self._pinned_exception_windows = {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.empty_manifest(),
                "active": self._thread is not None and self._thread.is_alive(),
                "sampled_frame_count": len(self._frames),
                "persisted_frame_count": self._persisted_frame_count,
                "periodic_frame_count": self._persisted_frame_count,
                "timeline_path": str(self._timeline_path or ""),
                "writer_status": self._writer_status,
                "storage_state": self._storage_state,
                "disk_free_bytes": self._disk_free_bytes,
                "evidence_complete": self._writer_status != "incomplete" and self._storage_state != "critical",
                "buffer_bytes": self._total_bytes,
                "capture_errors": self._capture_errors,
                "last_capture_error": self._last_error,
            }

    def _capture_loop(self) -> None:
        interval = 1.0 / self.fps
        next_capture = time.monotonic() + interval
        while not self._stop_event.wait(max(0.0, next_capture - time.monotonic())):
            self.capture_once()
            next_capture += interval
            now = time.monotonic()
            if next_capture <= now:
                missed_intervals = int((now - next_capture) // interval) + 1
                next_capture += missed_intervals * interval

    @staticmethod
    def _encode_frame(image: Any) -> tuple[bytes, str, str, int, int]:
        frame = image.copy() if callable(getattr(image, "copy", None)) else image
        size = getattr(frame, "size", (0, 0))
        width, height = (int(size[0]), int(size[1])) if isinstance(size, tuple) and len(size) >= 2 else (0, 0)
        convert = getattr(frame, "convert", None)
        if callable(convert):
            frame = convert("RGB")
        buffer = BytesIO()
        try:
            frame.save(buffer, format="JPEG", quality=82, optimize=True)
            return buffer.getvalue(), "image/jpeg", ".jpg", width, height
        except Exception:
            buffer = BytesIO()
            frame.save(buffer, format="PNG")
            return buffer.getvalue(), "image/png", ".png", width, height


class RecordingManager:
    """Persist one redacted operator demonstration without owning Skill reasoning."""

    def __init__(
        self,
        root: str | Path,
        *,
        listener_factory: Callable[["RecordingManager"], list[Any]] | None = None,
        screenshot_provider: Callable[[], Any] | None = None,
        input_language_provider: Callable[[], dict[str, str]] | None = None,
        overlay_controller: Any | None = None,
        frame_buffer_fps: float = 2.0,
        frame_buffer_retention_sec: float = 20.0,
        frame_buffer_max_bytes: int = 64 * 1024 * 1024,
        exception_pre_sec: float = 5.0,
        exception_post_sec: float = 5.0,
    ) -> None:
        self.root = Path(root)
        self._listener_factory = listener_factory or _pynput_recording_listeners
        self._screenshot_provider = screenshot_provider
        self._input_language_provider = input_language_provider or _windows_input_language_state
        self._overlay = overlay_controller or RecordingOverlayController(on_stop=self.stop)
        set_stop_callback = getattr(self._overlay, "set_stop_callback", None)
        if callable(set_stop_callback):
            set_stop_callback(self.stop)
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
        self._last_input_language: dict[str, str] | None = None
        self._exception_pre_sec = max(0.0, min(float(exception_pre_sec), float(frame_buffer_retention_sec)))
        self._exception_post_sec = max(0.0, min(float(exception_post_sec), float(frame_buffer_retention_sec)))
        self._frame_buffer = RecordingFrameBuffer(
            screenshot_provider=self._screenshot,
            fps=frame_buffer_fps,
            retention_sec=frame_buffer_retention_sec,
            max_bytes=frame_buffer_max_bytes,
        )

    def next_event_number(self) -> int:
        with self._lock:
            return len(self._active.get("events", [])) + 1 if self._active is not None else 1

    def _input_language_state(self) -> dict[str, str]:
        unavailable = {
            "status": "unavailable",
            "layout_id": "",
            "locale": "",
            "language": "",
            "ime_mode": "unknown",
            "typing_mode": "unknown",
        }
        try:
            state = self._input_language_provider()
        except Exception:
            return unavailable
        if not isinstance(state, dict):
            return unavailable
        return {
            "status": str(state.get("status") or "unavailable")[:24],
            "layout_id": str(state.get("layout_id") or "")[:32],
            "locale": str(state.get("locale") or "")[:32],
            "language": str(state.get("language") or "")[:16],
            "ime_mode": str(state.get("ime_mode") or "unknown")[:24],
            "typing_mode": str(state.get("typing_mode") or "unknown")[:24],
        }

    def record_keyboard_event(self, event: dict[str, Any]) -> bool:
        state = self._input_language_state()
        with self._lock:
            if self._active is None:
                return False
            if self._last_input_language != state:
                at_ms = max(0, int((time.monotonic() - self._started_monotonic) * 1000))
                self._active["input_language_history"].append({"at_ms": at_ms, **state})
                self.record_event({"kind": "input_language_changed", "input_language": state})
                self._last_input_language = dict(state)
            enriched = dict(event)
            enriched["input_language"] = state
            return self.record_event(enriched)

    def _screenshot(self) -> Any:
        if self._screenshot_provider is not None:
            image = self._screenshot_provider()
        else:
            pyautogui, error = _load_pyautogui()
            if pyautogui is None:
                raise RuntimeError(error or "PyAutoGUI unavailable")
            image = pyautogui.screenshot()
        return self._apply_mask_regions(image)

    @staticmethod
    def _normalize_mask_regions(regions: Any) -> list[dict[str, int]]:
        normalized: list[dict[str, int]] = []
        for item in regions if isinstance(regions, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                region = {
                    "x": max(0, int(item.get("x", 0))),
                    "y": max(0, int(item.get("y", 0))),
                    "width": max(1, min(16384, int(item.get("width", 0)))),
                    "height": max(1, min(16384, int(item.get("height", 0)))),
                }
            except (TypeError, ValueError):
                continue
            normalized.append(region)
            if len(normalized) >= 32:
                break
        return normalized

    def _apply_mask_regions(self, image: Any) -> Any:
        with self._lock:
            regions = list(self._active.get("mask_regions", [])) if self._active is not None else []
        if not regions:
            return image
        frame = image.copy() if callable(getattr(image, "copy", None)) else image
        try:
            from PIL import ImageDraw

            draw = ImageDraw.Draw(frame)
            for region in regions:
                left = int(region["x"])
                top = int(region["y"])
                draw.rectangle(
                    (left, top, left + int(region["width"]) - 1, top + int(region["height"]) - 1),
                    fill=(0, 0, 0),
                )
            return frame
        except Exception as exc:
            raise RuntimeError(f"recording mask application failed: {exc}") from exc

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
                    ("tight", 64, 64, 0.9),
                    ("context", 192, 128, 0.9),
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
        mask_regions: Any = None,
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
            timeline_id = f"timeline-{recording_id[4:]}"
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            input_language = self._input_language_state()
            self._active = {
                "schema": "atr.equipment_recording.v3" if image_tracking else "atr.equipment_recording.v1",
                "recording_id": recording_id,
                "timeline_id": timeline_id,
                "name": str(name or "Equipment demonstration")[:160],
                "target_app": str(target_app or "")[:160],
                "target_window": str(target_window or "")[:240],
                "status": "recording",
                "events": [],
                "checkpoints": [],
                "exceptions": [],
                "mask_regions": self._normalize_mask_regions(mask_regions),
                "created_at": now,
                "updated_at": now,
                "input_language": input_language,
                "input_language_history": [{"at_ms": 0, **input_language}],
                "visual_locator_policy": {
                    "mode": "image_first" if image_tracking else "coordinates",
                    "required_for_pointer_actions": bool(image_tracking),
                    "coordinate_fallback": bool(coordinate_fallback),
                },
                "time_series_evidence": self._frame_buffer.empty_manifest(),
            }
            self._started_monotonic = time.monotonic()
            self._last_mouse_move_monotonic = 0.0
            self._last_mouse_position = None
            self._last_pointer_frame = None
            self._last_pointer_frame_monotonic = 0.0
            self._last_pointer_frame_position = None
            self._pointer_frame_history = []
            self._visual_locator_bytes = 0
            self._last_input_language = dict(input_language)
            self._frame_buffer.start(
                recording_id,
                self._started_monotonic,
                self._path(recording_id).parent,
            )
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
                self._frame_buffer.stop()
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
                if isinstance(event.get("input_language"), dict):
                    safe["input_language"] = dict(event["input_language"])
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
                if isinstance(event.get("input_language"), dict):
                    safe["input_language"] = dict(event["input_language"])
            elif kind == "input_language_changed":
                if not isinstance(event.get("input_language"), dict):
                    return False
                safe["input_language"] = dict(event["input_language"])
            else:
                return False
            self._active["events"].append(safe)
            if kind not in {"mouse_move", "input_language_changed"}:
                evidence = self._frame_buffer.persist_event_frame(
                    self._path(str(self._active["recording_id"])).parent,
                    event_number=len(self._active["events"]),
                    event_at_ms=int(safe["at_ms"]),
                )
                if evidence:
                    safe["frame_evidence"] = evidence
            self._active["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._persist(self._active)
            return True

    def record_exception(self, *, failure_code: str, detail: str = "") -> dict[str, Any]:
        """Mark an exception without persisting credentials or the complete desktop stream."""
        with self._lock:
            if self._active is None:
                return {"ok": False, "status": "idle", "failure_code": "SKILL_RECORDING_NOT_ACTIVE"}
            code = re.sub(r"[^A-Z0-9_]+", "_", str(failure_code or "RECORDING_EXCEPTION").upper()).strip("_")
            code = (code or "RECORDING_EXCEPTION")[:96]
            safe_detail = re.sub(
                r"(?i)\b(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*\S+",
                r"\1=<redacted>",
                str(detail or "")[:512],
            )
            marker = {
                "exception_id": f"exception-{len(self._active['exceptions']) + 1:03d}",
                "timeline_id": str(self._active["timeline_id"]),
                "at_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)),
                "failure_code": code,
                "detail": safe_detail,
            }
            marker["frame_window"] = self._frame_buffer.pin_exception_window(
                self._path(str(self._active["recording_id"])).parent,
                marker,
                pre_sec=self._exception_pre_sec,
                post_sec=self._exception_post_sec,
            )
            self._active["exceptions"].append(marker)
            self._active["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._persist(self._active)
            return {"ok": True, "status": "exception_marked", **marker}

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
            self._apply_mask_regions(capture.screenshot()).save(image_path)
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
            consume_stop_request = getattr(self._overlay, "consume_stop_request", None)
            stop_request = consume_stop_request() if callable(consume_stop_request) else {}
            if isinstance(stop_request, dict) and stop_request.get("control"):
                stop_x = int(stop_request.get("x", 0))
                stop_y = int(stop_request.get("y", 0))
                for event in reversed(self._active.get("events", [])):
                    if not isinstance(event, dict) or event.get("kind") == "mouse_move":
                        continue
                    if (
                        event.get("kind") == "mouse_click"
                        and abs(int(event.get("x", -1000)) - stop_x) <= 8
                        and abs(int(event.get("y", -1000)) - stop_y) <= 8
                    ):
                        event["recording_control"] = str(stop_request["control"])[:64]
                    break
            self._overlay.hide()
            self._listeners = []
            self._active["status"] = "completed"
            if listener_stop_errors:
                self._active["listener_stop_errors"] = listener_stop_errors
            self._active["duration_ms"] = max(0, int((time.monotonic() - self._started_monotonic) * 1000))
            # Persist one clean post-action frame after the recording overlay is gone.
            self._frame_buffer.capture_boundary_frame(
                "recording_stop",
                at_ms=int(self._active["duration_ms"]),
            )
            self._frame_buffer.capture_once()
            self._frame_buffer.stop()
            self._active["time_series_evidence"] = self._frame_buffer.persist_event_keyframes(
                self._path(str(self._active["recording_id"])).parent,
                self._active.get("events", []),
                exceptions=self._active.get("exceptions", []),
                timeline_id=str(self._active.get("timeline_id") or ""),
                exception_pre_sec=self._exception_pre_sec,
                exception_post_sec=self._exception_post_sec,
            )
            event_frames = [
                dict(item["frame_evidence"])
                for item in self._active.get("events", [])
                if isinstance(item, dict) and isinstance(item.get("frame_evidence"), dict)
            ]
            self._active["time_series_evidence"]["event_frame_count"] = len(event_frames)
            self._active["time_series_evidence"]["event_frames"] = event_frames
            self._frame_buffer.release()
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
        else:
            self._frame_buffer.stop()
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

    def package(
        self,
        recording_id: str,
        *,
        max_total_bytes: int | None = None,
        max_file_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Return the complete hash-addressed recording package for Linux import."""
        with self._lock:
            recording = self.get(recording_id)
            if not recording.get("ok"):
                return recording
            recording_dir = self._path(recording_id).parent.resolve()
            artifacts: list[dict[str, Any]] = []
            total_bytes = 0
            for path in sorted(recording_dir.rglob("*")):
                if not path.is_file() or path.is_symlink() or path.name == "recording.json":
                    continue
                resolved = path.resolve()
                try:
                    relative = resolved.relative_to(recording_dir)
                except ValueError:
                    continue
                raw = resolved.read_bytes()
                if (
                    (max_file_bytes is not None and len(raw) > max(0, int(max_file_bytes)))
                    or (
                        max_total_bytes is not None
                        and total_bytes + len(raw) > max(0, int(max_total_bytes))
                    )
                ):
                    return {
                        "ok": False,
                        "status": "blocked",
                        "failure_code": "SKILL_RECORDING_PACKAGE_TOO_LARGE",
                        "message": "Recording evidence exceeds the explicitly configured transfer limit.",
                    }
                total_bytes += len(raw)
                suffix = resolved.suffix.lower()
                media_type = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".json": "application/json",
                    ".csv": "text/csv",
                }.get(suffix, "application/octet-stream")
                artifacts.append(
                    {
                        "relative_path": relative.as_posix(),
                        "source_path": str(resolved),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size_bytes": len(raw),
                        "media_type": media_type,
                        "data_base64": base64.b64encode(raw).decode("ascii"),
                    }
                )
            recording.pop("ok", None)
            return {
                "ok": True,
                "schema": "atr.equipment_recording_package.v1",
                "recording": recording,
                "artifact_count": len(artifacts),
                "total_bytes": total_bytes,
                "artifacts": artifacts,
            }

    def preview(
        self,
        recording_id: str,
        *,
        cursor: int = 0,
        limit: int | None = None,
        max_frames: int = 48,
        max_total_bytes: int = 24 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Return one bounded visual page without exposing Windows filesystem paths."""
        recording = self.get(recording_id)
        if not recording.get("ok"):
            return recording
        recording_dir = self._path(recording_id).parent.resolve()
        timeline = recording.get("time_series_evidence") if isinstance(recording.get("time_series_evidence"), dict) else {}
        candidates: list[dict[str, Any]] = []
        for item in timeline.get("frames", []):
            if isinstance(item, dict):
                candidates.append(dict(item))
        for item in timeline.get("event_frames", []):
            if isinstance(item, dict):
                candidates.append(dict(item))
        for item in recording.get("checkpoints", []):
            if isinstance(item, dict):
                candidates.append({**item, "reason": "checkpoint", "at_ms": int(item.get("at_ms", 0))})

        available: list[tuple[dict[str, Any], Path, str]] = []
        seen: set[str] = set()
        for item in sorted(candidates, key=lambda value: int(value.get("at_ms", 0))):
            raw_path = str(item.get("artifact_path") or "").strip()
            if not raw_path or raw_path in seen:
                continue
            seen.add(raw_path)
            path = Path(raw_path).resolve()
            try:
                path.relative_to(recording_dir)
            except ValueError:
                continue
            if not path.is_file() or path.is_symlink():
                continue
            suffix = path.suffix.lower()
            media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(suffix)
            if not media_type:
                continue
            available.append((item, path, media_type))

        page_cursor = max(0, int(cursor))
        page_limit = max(1, min(int(limit if limit is not None else max_frames), 96))
        frames: list[dict[str, Any]] = []
        total_bytes = 0
        for item, path, media_type in available[page_cursor : page_cursor + page_limit]:
            raw = path.read_bytes()
            if not raw or total_bytes + len(raw) > max_total_bytes:
                break
            total_bytes += len(raw)
            frames.append(
                {
                    "frame_id": str(item.get("frame_id") or item.get("checkpoint_id") or f"frame-{len(frames) + 1:04d}"),
                    "at_ms": max(0, int(item.get("at_ms", 0))),
                    "reason": str(item.get("reason") or "recording_evidence"),
                    "media_type": media_type,
                    "width": max(0, int(item.get("width", 0))),
                    "height": max(0, int(item.get("height", 0))),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "data_base64": base64.b64encode(raw).decode("ascii"),
                }
            )
        next_cursor = page_cursor + len(frames)
        if next_cursor >= len(available):
            next_cursor = None
        return {
            "ok": True,
            "schema": "atr.equipment_recording_preview.v1",
            "recording_id": recording_id,
            "name": str(recording.get("name") or recording_id),
            "status": str(recording.get("status") or "unknown"),
            "duration_ms": max(0, int(recording.get("duration_ms", 0))),
            "event_count": len(recording.get("events", [])),
            "frame_count": len(frames),
            "returned_frame_count": len(frames),
            "total_frame_count": len(available),
            "cursor": page_cursor,
            "limit": page_limit,
            "next_cursor": next_cursor,
            "total_bytes": total_bytes,
            "frames": frames,
        }

    def get(self, recording_id: str) -> dict[str, Any]:
        path = self._path(recording_id)
        if not path.exists():
            return {"ok": False, "status": "not_found", "failure_code": "SKILL_RECORDING_NOT_FOUND", "recording_id": recording_id}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, **payload}

    def delete(self, recording_id: str) -> dict[str, Any]:
        with self._lock:
            if self._active is not None and self._active.get("recording_id") == recording_id:
                return {
                    "ok": False,
                    "status": "blocked",
                    "failure_code": "SKILL_RECORDING_ACTIVE",
                    "recording_id": recording_id,
                }
            path = self._path(recording_id)
            if not path.exists():
                return {
                    "ok": False,
                    "status": "not_found",
                    "failure_code": "SKILL_RECORDING_NOT_FOUND",
                    "recording_id": recording_id,
                }
            shutil.rmtree(path.parent)
            if self._last_completed_id == recording_id:
                self._last_completed_id = ""
            return {"ok": True, "status": "deleted", "recording_id": recording_id}

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
                return {"ok": True, **dict(self._active), "elapsed_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)), "overlay": self._overlay.status(), "frame_buffer": self._frame_buffer.status()}
            return {"ok": True, "status": "idle", "recording_id": None, "overlay": self._overlay.status()}


RECORDING_MANAGER = RecordingManager(RECORDING_ROOT)


class UpdateManager:
    """Stage only verified Worker files and prepare bounded process replacement."""

    def __init__(
        self,
        *,
        package_root: str | Path,
        update_root: str | Path,
        allowed_paths: set[str],
        recording_status_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.package_root = Path(package_root).resolve()
        self.update_root = Path(update_root).resolve()
        self.allowed_paths = {self._safe_path(path) for path in allowed_paths}
        self.recording_status_provider = recording_status_provider
        self._lock = threading.RLock()

    @staticmethod
    def _safe_path(value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError(f"invalid update path: {raw!r}")
        return path.as_posix()

    @property
    def state_path(self) -> Path:
        return self.update_root / "status.json"

    @property
    def staged_pointer_path(self) -> Path:
        return self.update_root / "staged.json"

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        _recording_atomic_write(path, payload)

    def _recording_gate(self) -> dict[str, Any] | None:
        status = self.recording_status_provider()
        if status.get("recording_id") or str(status.get("status") or "idle").lower() not in {"idle", "stopped", "completed"}:
            return {
                "ok": False,
                "status": "blocked",
                "failure_code": "PYAUTOGUI_UPDATE_RECORDING_ACTIVE",
                "message": "Stop and save the active recording before updating the Worker.",
                "recording": status,
            }
        return None

    def stage(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            try:
                if payload.get("schema") != "atr.windows_bridge_update_package.v1":
                    raise ValueError("unsupported update package schema")
                version = str(payload.get("version") or "").strip()
                files = payload.get("files")
                if not version or not isinstance(files, list) or not files:
                    raise ValueError("update package requires version and files")
                decoded: list[tuple[str, bytes, str]] = []
                metadata: list[dict[str, Any]] = []
                total_bytes = 0
                for item in files:
                    if not isinstance(item, dict):
                        raise ValueError("update file entry must be an object")
                    try:
                        relative = self._safe_path(item.get("path"))
                    except ValueError as exc:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_PATH_NOT_ALLOWED", "message": str(exc)}
                    if relative not in self.allowed_paths:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_PATH_NOT_ALLOWED", "message": relative}
                    try:
                        raw = base64.b64decode(str(item.get("data_base64") or ""), validate=True)
                    except Exception:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_BASE64_INVALID", "message": relative}
                    expected_size = int(item.get("size_bytes", -1))
                    if len(raw) != expected_size:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_FILE_SIZE_MISMATCH", "message": relative}
                    if len(raw) > MAX_UPDATE_FILE_BYTES:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_FILE_TOO_LARGE", "message": relative}
                    sha256 = hashlib.sha256(raw).hexdigest()
                    if not secrets.compare_digest(sha256, str(item.get("sha256") or "")):
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_FILE_HASH_MISMATCH", "message": relative}
                    total_bytes += len(raw)
                    if total_bytes > MAX_UPDATE_PACKAGE_BYTES:
                        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_PACKAGE_TOO_LARGE"}
                    metadata.append({"path": relative, "size_bytes": len(raw), "sha256": sha256})
                    decoded.append((relative, raw, sha256))
                if len({item["path"] for item in metadata}) != len(metadata):
                    raise ValueError("duplicate update paths")
                digest_payload = {"schema": payload["schema"], "version": version, "files": metadata}
                canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
                package_sha256 = hashlib.sha256(canonical).hexdigest()
                if not secrets.compare_digest(package_sha256, str(payload.get("package_sha256") or "")):
                    return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_PACKAGE_HASH_MISMATCH"}
                stage_dir = self.update_root / "staging" / re.sub(r"[^A-Za-z0-9_.-]+", "_", version)
                if stage_dir.exists():
                    shutil.rmtree(stage_dir)
                for relative, raw, _sha256 in decoded:
                    destination = stage_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(raw)
                stage_manifest = {**digest_payload, "package_sha256": package_sha256, "total_bytes": total_bytes}
                self._atomic_json(stage_dir / "manifest.json", stage_manifest)
                self._atomic_json(self.staged_pointer_path, {"version": version, "stage_dir": str(stage_dir), "package_sha256": package_sha256})
                return {"ok": True, "status": "staged", "version": version, "stage_dir": str(stage_dir), "package_sha256": package_sha256, "total_bytes": total_bytes}
            except (OSError, TypeError, ValueError) as exc:
                return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_PACKAGE_INVALID", "message": str(exc)}

    def _staged(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.staged_pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        stage_dir = Path(str(payload.get("stage_dir") or ""))
        if not stage_dir.is_dir() or not (stage_dir / "manifest.json").is_file():
            return {}
        return payload

    def _latest_backup(self) -> Path | None:
        backup_root = self.update_root / "backups"
        candidates = sorted((path for path in backup_root.glob("*") if (path / "backup_manifest.json").is_file()), reverse=True)
        return candidates[0] if candidates else None

    def prepare_apply(self) -> dict[str, Any]:
        blocked = self._recording_gate()
        if blocked:
            return blocked
        staged = self._staged()
        if not staged:
            return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_NOT_STAGED"}
        return {"ok": True, "status": "apply_ready", **staged}

    def prepare_rollback(self) -> dict[str, Any]:
        blocked = self._recording_gate()
        if blocked:
            return blocked
        backup_dir = self._latest_backup()
        if backup_dir is None:
            return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_UPDATE_BACKUP_NOT_FOUND"}
        return {"ok": True, "status": "rollback_ready", "backup_id": backup_dir.name, "backup_dir": str(backup_dir)}

    def status(self) -> dict[str, Any]:
        try:
            persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            persisted = {}
        staged = self._staged()
        backup = self._latest_backup()
        return {
            "ok": True,
            "status": str(persisted.get("status") or "ready"),
            "current_version": BRIDGE_RELEASE_VERSION,
            "staged_version": str(staged.get("version") or ""),
            "last_result": persisted,
            "rollback_available": backup is not None,
            "backup_id": backup.name if backup else "",
            "recording_active": self._recording_gate() is not None,
        }


UPDATE_MANAGER = UpdateManager(
    package_root=_bridge_package_root(),
    update_root=ARTIFACT_ROOT.parent / "updates",
    allowed_paths=UPDATE_ALLOWED_PATHS,
    recording_status_provider=lambda: RECORDING_MANAGER.status(),
)


def _new_update_manager() -> UpdateManager:
    return UpdateManager(
        package_root=_bridge_package_root(),
        update_root=ARTIFACT_ROOT.parent / "updates",
        allowed_paths=UPDATE_ALLOWED_PATHS,
        recording_status_provider=lambda: RECORDING_MANAGER.status(),
    )


def _restart_command() -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        return [sys.executable, *sys.argv[1:]]
    server_path = _bridge_package_root() / "bridge" / "windows_pyautogui_bridge_server.py"
    return [sys.executable, str(server_path), *sys.argv[1:]]


def _launch_self_updater(mode: str, prepared: dict[str, Any]) -> dict[str, Any]:
    package_root = _bridge_package_root().resolve()
    updater_root = Path(str(prepared.get("stage_dir") or "")).resolve() if mode == "apply" else package_root
    updater_path = updater_root / "scripts" / "bridge_self_updater.py"
    if mode == "apply" and not updater_path.resolve().is_relative_to(updater_root):
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": "PYAUTOGUI_UPDATE_HELPER_INVALID",
            "message": str(updater_path),
        }
    if not updater_path.is_file():
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": "PYAUTOGUI_UPDATE_HELPER_MISSING",
            "message": str(updater_path),
        }
    command = [
        sys.executable,
        str(updater_path),
        "--mode",
        mode,
        "--pid",
        str(os.getpid()),
        "--package-root",
        str(package_root),
        "--update-root",
        str(UPDATE_MANAGER.update_root),
        "--command-json",
        json.dumps(_restart_command(), ensure_ascii=True),
        "--health-url",
        f"http://127.0.0.1:{PORT}/ping",
        "--health-timeout-s",
        "30",
    ]
    if mode == "apply":
        command.extend(("--stage-root", str(prepared["stage_dir"])))
    else:
        command.extend(("--backup-dir", str(prepared["backup_dir"])))
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )  # type: ignore[attr-defined]
    update_lock = UPDATE_MANAGER.update_root / "update_in_progress.json"
    update_lock.parent.mkdir(parents=True, exist_ok=True)
    lock_payload = {
        "status": "starting_updater",
        "mode": mode,
        "worker_pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    lock_temporary = update_lock.with_name(f".{update_lock.name}.{os.getpid()}.tmp")
    lock_temporary.write_text(json.dumps(lock_payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(lock_temporary, update_lock)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(package_root),
            creationflags=flags,
            close_fds=os.name != "nt",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        update_lock.unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "status": "update_restarting" if mode == "apply" else "rollback_restarting",
        "updater_pid": process.pid,
        "version": str(prepared.get("version") or ""),
        "backup_id": str(prepared.get("backup_id") or ""),
    }


class PairingManager:
    """Exchange one short-lived operator code for one persistent internal key."""

    CODE_TTL_SEC = 300
    MAX_ATTEMPTS = 5
    LOCKOUT_SEC = 30
    RETRY_TTL_SEC = 30

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        code_factory: Callable[[], str] | None = None,
        key_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock
        self._code_factory = code_factory or (lambda: f"{secrets.randbelow(10000):04d}")
        self._key_factory = key_factory or (lambda: secrets.token_urlsafe(32))
        self._lock = threading.RLock()
        self._code = ""
        self._expires_at = 0.0
        self._attempts = 0
        self._locked_until = 0.0
        self._internal_key = self._load_key()
        self._completed_code_digest = b""
        self._completed_until = 0.0

    @staticmethod
    def _code_digest(code: str) -> bytes:
        return hashlib.sha256(str(code).encode("utf-8")).digest()

    def _load_key(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(payload.get("internal_key") or "")

    def _persist_key(self, internal_key: str) -> None:
        payload = {
            "schema": "atr.windows_bridge_pairing.v1",
            "internal_key": internal_key,
            "paired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _recording_atomic_write(self.path, payload)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def issue_code(self) -> dict[str, Any]:
        with self._lock:
            if self._internal_key:
                return {"ok": False, "status": "paired", "paired": True, "failure_code": "PAIRING_ALREADY_COMPLETE"}
            code = str(self._code_factory())
            if not re.fullmatch(r"\d{4}", code):
                raise ValueError("pairing code factory must return exactly four digits")
            self._code = code
            self._expires_at = self._clock() + self.CODE_TTL_SEC
            self._attempts = 0
            self._locked_until = 0.0
            return {
                "ok": True,
                "status": "pairing_available",
                "paired": False,
                "pairing_code": code,
                "expires_in_sec": self.CODE_TTL_SEC,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._internal_key:
                return {"ok": True, "status": "paired", "paired": True}
            now = self._clock()
            if self._locked_until > now:
                return {
                    "ok": True,
                    "status": "locked",
                    "paired": False,
                    "retry_after_sec": max(1, int(self._locked_until - now + 0.999)),
                }
            if self._code and self._expires_at > now:
                return {
                    "ok": True,
                    "status": "pairing_available",
                    "paired": False,
                    "pairing_code": self._code,
                    "expires_in_sec": max(1, int(self._expires_at - now + 0.999)),
                }
            return {"ok": True, "status": "unpaired", "paired": False}

    def complete(self, code: str) -> dict[str, Any]:
        with self._lock:
            if self._internal_key:
                if (
                    self._completed_code_digest
                    and self._completed_until >= self._clock()
                    and secrets.compare_digest(self._code_digest(code), self._completed_code_digest)
                ):
                    return {
                        "ok": True,
                        "status": "paired_retry",
                        "paired": True,
                        "internal_key": self._internal_key,
                    }
                return {"ok": False, "status": "paired", "paired": True, "failure_code": "PAIRING_ALREADY_COMPLETE"}
            now = self._clock()
            if self._locked_until > now:
                return {
                    "ok": False,
                    "status": "locked",
                    "paired": False,
                    "retry_after_sec": max(1, int(self._locked_until - now + 0.999)),
                    "attempts_remaining": 0,
                    "failure_code": "PAIRING_LOCKED",
                }
            if self._locked_until:
                self._locked_until = 0.0
                self._attempts = 0
            if not self._code:
                return {"ok": False, "status": "unpaired", "paired": False, "failure_code": "PAIRING_CODE_REQUIRED"}
            if self._expires_at <= now:
                self._code = ""
                self._expires_at = 0.0
                return {"ok": False, "status": "expired", "paired": False, "failure_code": "PAIRING_CODE_EXPIRED"}
            if not secrets.compare_digest(str(code), self._code):
                self._attempts += 1
                remaining = max(0, self.MAX_ATTEMPTS - self._attempts)
                if remaining == 0:
                    self._locked_until = now + self.LOCKOUT_SEC
                    self._code = ""
                    self._expires_at = 0.0
                return {
                    "ok": False,
                    "status": "locked" if remaining == 0 else "invalid_code",
                    "paired": False,
                    "attempts_remaining": remaining,
                    "retry_after_sec": self.LOCKOUT_SEC if remaining == 0 else 0,
                    "failure_code": "PAIRING_LOCKED" if remaining == 0 else "PAIRING_CODE_INVALID",
                }
            internal_key = str(self._key_factory())
            self._persist_key(internal_key)
            self._internal_key = internal_key
            self._completed_code_digest = self._code_digest(code)
            self._completed_until = now + self.RETRY_TTL_SEC
            self._code = ""
            self._expires_at = 0.0
            self._attempts = 0
            self._locked_until = 0.0
            return {"ok": True, "status": "paired", "paired": True, "internal_key": internal_key}

    def reset(self) -> dict[str, Any]:
        """Clear a half-completed pairing from the Windows-local console only."""
        with self._lock:
            self._internal_key = ""
            self._completed_code_digest = b""
            self._completed_until = 0.0
            self._code = ""
            self._expires_at = 0.0
            self._attempts = 0
            self._locked_until = 0.0
            self.path.unlink(missing_ok=True)
            return self.issue_code()

    def authorized(self, supplied_key: str) -> bool:
        with self._lock:
            return bool(self._internal_key) and secrets.compare_digest(str(supplied_key or ""), self._internal_key)


PAIRING_MANAGER = PairingManager(ARTIFACT_ROOT / "pairing.json")
if not PAIRING_MANAGER.status().get("paired"):
    PAIRING_MANAGER.issue_code()



























PROGRAMS = {
    "program1": {
        "name": "Program 1 Demo",
        "description": "Demo macro: verify PyAutoGUI, move mouse briefly, and return completion log.",
        "requires_pyautogui": True,
        "safe_test": True,
        "program_type": "connectivity_demo",
    },
    "utm_compression_start_v1": {
        "description": "UTM compression test protocol through the completed-test screen; raw CSV export is a separate step.",
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
        ],
        "expected_screen_after": [{"name": "running_state", "required": True}, {"name": "complete_state", "required": True}],
        "save_policy": {
            "auto_save_expected": False,
            "manual_save_required_if_no_artifact": False,
            "windows_export_root": "C:/ATR/utm_exports",
            "save_actions": [],
        },
        "output_artifacts": [],
        "safe_abort": {"program_id": "utm_stop_or_abort_v1"},
    },
    "utm_export_csv_v1": {
        "description": "Save raw test data to CSV after a completed test.",
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
            {"action": "click", "target": "save_raw_data_csv"},
            {"action": "wait", "seconds": 1.0},
            {"action": "hotkey", "keys": ["ctrl", "a"]},
            {"action": "write", "text": "C:/ATR/utm_exports/{run_id}/{specimen_id}.csv", "interval_sec": 0.01},
            {"action": "press", "key": "enter"},
            {"action": "wait_for_file", "pattern": "C:/ATR/utm_exports/{run_id}/{specimen_id}*.csv", "timeout_s": 20},
        ],
        "expected_screen_after": [{"name": "complete_state", "required": True}],
        "save_policy": {
            "auto_save_expected": False,
            "manual_save_required_if_no_artifact": False,
            "windows_export_root": "C:/ATR/utm_exports",
            "save_method": "raw_csv_button",
            "save_actions": ["assert_complete_state", "click_save_raw_data_csv", "type_standard_path", "press_enter", "wait_for_file"],
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
    "set_input_language",
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
        if action == "set_input_language":
            if not re.fullmatch(r"[0-9A-Fa-f]{8}", str(step.get("layout_id") or "").strip()):
                return "set_input_language layout_id must be 8 hexadecimal digits"
            if str(step.get("typing_mode") or "").strip().lower() not in {"latin", "native"}:
                return "set_input_language typing_mode must be latin or native"
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
        "keyboard": ["write", "press", "hotkey", "key_down", "key_up", "set_input_language"],
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
        deployment = definition.get("_atr_deployment") if isinstance(definition.get("_atr_deployment"), dict) else {}
        actual_digest = _program_definition_sha256(program)
        expected_digest = str(deployment.get("program_sha256") or "").strip().lower()
        if str(deployment.get("managed_by") or "") == "atr_equipment_skill":
            program["managed_by"] = "atr_equipment_skill"
            program["deployment_sha256"] = expected_digest
            program["program_sha256"] = actual_digest
            program["integrity_ok"] = bool(expected_digest) and secrets.compare_digest(actual_digest, expected_digest)
        program["built_in"] = False
        program["source_file"] = str(path)
        programs[program["program_id"]] = program
    return programs


def _all_programs() -> dict[str, dict[str, Any]]:
    programs = {key: {**value, "built_in": True, "enabled": True} for key, value in PROGRAMS.items()}
    programs.update(_load_custom_programs())
    return programs


def _program_definition_sha256(program: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(program, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _register_program_definition(
    definition: Any,
    *,
    managed: bool = False,
    deployment_sha256: str = "",
) -> dict[str, Any]:
    validation = _validate_program_definition(definition)
    if not validation.get("ok"):
        return validation
    program = dict(validation["program"])
    PROGRAM_ROOT.mkdir(parents=True, exist_ok=True)
    destination = PROGRAM_ROOT / f"{program['program_id']}.json"
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        existing_deployment = existing.get("_atr_deployment") if isinstance(existing.get("_atr_deployment"), dict) else {}
        if str(existing_deployment.get("managed_by") or "") == "atr_equipment_skill" and not managed:
            return {
                "ok": False,
                "status": "blocked",
                "failure_code": "PYAUTOGUI_PROGRAM_MANAGED_IMMUTABLE",
                "message": "ATR-deployed Skill programs can only be replaced by the authenticated deployment path.",
            }
    digest = _program_definition_sha256(program)
    persisted = dict(program)
    if managed:
        expected_digest = str(deployment_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or not secrets.compare_digest(digest, expected_digest):
            return {
                "ok": False,
                "status": "blocked",
                "failure_code": "PYAUTOGUI_PROGRAM_HASH_MISMATCH",
                "message": "Managed program content does not match the deployment hash.",
            }
        persisted["_atr_deployment"] = {
            "managed_by": "atr_equipment_skill",
            "program_sha256": expected_digest,
        }
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(persisted, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    public = {**program, "built_in": False, "source_file": str(destination)}
    if managed:
        public.update({"managed_by": "atr_equipment_skill", "deployment_sha256": digest, "program_sha256": digest, "integrity_ok": True})
    return {
        "ok": True,
        "status": "registered",
        "program": public,
        "program_path": str(destination),
        "program_sha256": digest,
        "failure_code": None,
    }


def _delete_custom_program(program_id: str, *, allow_managed: bool = False) -> dict[str, Any]:
    program_id = str(program_id or "").strip()
    if program_id in BUILTIN_PROGRAM_IDS:
        return {"ok": False, "status": "blocked", "failure_code": "PYAUTOGUI_PROGRAM_BUILTIN_IMMUTABLE", "message": f"Built-in program cannot be deleted: {program_id}"}
    if not PROGRAM_ID_PATTERN.fullmatch(program_id):
        return {"ok": False, "status": "invalid", "failure_code": "PYAUTOGUI_PROGRAM_ID_INVALID", "message": "Invalid program_id."}
    path = PROGRAM_ROOT / f"{program_id}.json"
    if not path.exists():
        return {"ok": False, "status": "not_found", "failure_code": "PYAUTOGUI_PROGRAM_NOT_FOUND", "message": f"Unknown custom program: {program_id}"}
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        persisted = {}
    deployment = persisted.get("_atr_deployment") if isinstance(persisted.get("_atr_deployment"), dict) else {}
    if str(deployment.get("managed_by") or "") == "atr_equipment_skill" and not allow_managed:
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": "PYAUTOGUI_PROGRAM_MANAGED_IMMUTABLE",
            "message": "ATR-deployed Skill programs can only be deleted by the authenticated deployment path.",
        }
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


def _runtime_module_available(name: str) -> bool:
    if name in sys.modules or importlib.util.find_spec(name) is not None:
        return True
    if not bool(getattr(sys, "frozen", False)):
        return False
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _runtime_dependency_status(checker: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Return import readiness without importing GUI packages into the server process."""
    available = checker or _runtime_module_available
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


def _public_pairing_status() -> dict[str, Any]:
    status = PAIRING_MANAGER.status()
    return {"paired": bool(status.get("paired")), "status": str(status.get("status") or "unpaired")}


def _health() -> dict[str, Any]:
    pyautogui, error = _load_pyautogui()
    platform_status = _desktop_platform_status()
    dependencies = _runtime_dependency_status()
    demo_assets = {
        "root": str(DEMO_ROOT),
        "available": (DEMO_ROOT / "pyautogui_capability_lab.html").is_file()
        and (DEMO_ROOT / "examples").is_dir(),
    }
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
            "pairing": _public_pairing_status(),
            "server_version": f"WindowsPyAutoGUIBridge/{BRIDGE_RELEASE_VERSION}",
            "release_version": BRIDGE_RELEASE_VERSION,
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
        "pairing": _public_pairing_status(),
        "server_version": f"WindowsPyAutoGUIBridge/{BRIDGE_RELEASE_VERSION}",
        "release_version": BRIDGE_RELEASE_VERSION,
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
            "confidence": float(payload.get("confidence", 0.9)),
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
        "region_normalized",
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
    anchored_match: tuple[int, int, int, int] | None = None
    anchored_best_score = float("-inf")
    global_best_score = float("-inf")
    for candidate_path, candidate, information_score in candidates:
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
        confidence = float(candidate.get("confidence", 0.9))
        crop_origin = candidate.get("crop_origin")
        if (
            float(information_score) >= 12.0
            and isinstance(crop_origin, (list, tuple))
            and len(crop_origin) == 2
        ):
            origin_x, origin_y = (int(value) for value in crop_origin)
            if (
                origin_x >= 0
                and origin_y >= 0
                and origin_x + template_width <= screen.shape[1]
                and origin_y + template_height <= screen.shape[0]
            ):
                recorded_region = screen[
                    origin_y : origin_y + template_height,
                    origin_x : origin_x + template_width,
                ]
                anchor_score = float(
                    cv2.matchTemplate(recorded_region, template, cv2.TM_CCORR_NORMED)[0, 0]
                )
                # Hover/focus backgrounds can defeat zero-mean correlation while
                # preserving the control structure at its recorded screen anchor.
                if anchor_score >= 0.985 and anchor_score > anchored_best_score:
                    anchored_best_score = anchor_score
                    anchored_match = (origin_x, origin_y, template_width, template_height)
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
    return True, best_match or anchored_match


def _resolved_search_region(pyautogui: Any, locator: dict[str, Any]) -> tuple[int, int, int, int] | None:
    region = locator.get("region")
    if isinstance(region, (list, tuple)) and len(region) == 4:
        return tuple(int(value) for value in region)  # type: ignore[return-value]
    normalized = locator.get("region_normalized")
    if not isinstance(normalized, (list, tuple)) or len(normalized) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in normalized)
        screen_width, screen_height = (int(value) for value in pyautogui.size())
    except (TypeError, ValueError, AttributeError):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        return None
    return (
        round(x * screen_width),
        round(y * screen_height),
        max(1, round(width * screen_width)),
        max(1, round(height * screen_height)),
    )


def _locate_on_screen(pyautogui: Any, locator: dict[str, Any], *, run_id: str, specimen_id: str) -> Any | None:
    search_region = _resolved_search_region(pyautogui, locator)
    candidates: list[tuple[str, dict[str, Any]]] = []
    inline_candidates: list[tuple[str, dict[str, Any], float]] = []
    image_path = locator.get("image_path") or locator.get("target_image")
    if image_path:
        candidates.append((_format_runtime_value(image_path, run_id=run_id, specimen_id=specimen_id), locator))
    for raw_candidate in locator.get("image_candidates", []):
        if not isinstance(raw_candidate, dict):
            continue
        candidate = dict(raw_candidate)
        if search_region is not None and "region" not in candidate:
            candidate["region"] = list(search_region)
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
        region = candidate.get("region", search_region)
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
        region = candidate.get("region", search_region)
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
        if action_name == "set_input_language":
            target = {
                key: str(action.get(key) or "").strip()
                for key in ("layout_id", "locale", "language", "ime_mode", "typing_mode")
            }
            result = _set_windows_input_language(target)
            if not result.get("ok"):
                detail = str(result.get("message") or "input language restoration failed")
                add(step_name, "blocked", detail)
                return result
            add(step_name, "ok", f"layout={target['layout_id']}; typing_mode={target['typing_mode']}")
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
            {"action": "click", "target": "save_raw_data_csv"},
            {"action": "wait", "seconds": 1.0},
            {"action": "hotkey", "keys": ["ctrl", "a"]},
            {"action": "write", "text": str(target_path), "interval_sec": 0.01},
            {"action": "press", "key": "enter"},
            {"action": "wait_for_file", "pattern": str(target_path), "timeout_s": 20},
        ]
    for action in sequence:
        if action.get("action") == "type_path":
            action["value"] = str(target_path)
        elif action.get("action") == "write":
            action["text"] = str(target_path)
        elif action.get("action") == "wait_for_file":
            action["pattern"] = str(target_path)
    export_payload = dict(payload)
    export_payload["program_id"] = program_id
    export_payload["sequence"] = sequence
    export_payload["expected_export_path"] = str(target_path)
    return export_payload, target_path


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
    program_sequence = program.get("sequence") if isinstance(program.get("sequence"), list) else []
    requires_export_artifact = program_type == "utm_export" or any(
        isinstance(action, dict) and action.get("action") == "wait_for_file"
        for action in program_sequence
    )
    if not requires_export_artifact:
        managed_skill = program.get("managed_by") == "atr_equipment_skill"
        step("EXECUTE_SKILL_MACRO" if managed_skill else "EXECUTE_TEST_MACRO", "ok", "registered non-export sequence dispatched")
        step("DONE", "ok", "Program completed without export side effects")
        return {
            "ok": True,
            "status": "completed",
            "bridge": "windows_pyautogui",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "program_type": program_type or "macro",
            "output_artifacts": list(screen_artifacts),
            "data_acquisition": {
                "status": "not_applicable",
                "save_method": "not_applicable",
                "save_attempted_by_agent": False,
                "save_confirmation_screen_ok": False,
            },
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": False,
                "save_completed": False,
                "data_file_created": False,
                "data_parse_probe_ok": False,
                "save_export_responsibility_ok": True,
            },
            "screen_checks": _screen_checks_from_artifacts(screen_artifacts),
            "step_trace": trace,
            "failure_code": None,
        }
    if program_type == "utm_export":
        step("EXECUTE_EXPORT_MACRO", "ok", "registered export/save sequence dispatched")
    else:
        step("EXECUTE_START_MACRO", "ok", "registered protocol sequence dispatched")
    raw_csv_save_attempted = any(
        isinstance(action, dict)
        and action.get("action") == "click"
        and action.get("target") == "save_raw_data_csv"
        for action in program_sequence
    )
    save_method = "raw_csv_button" if raw_csv_save_attempted else "windows_export_watch"
    export_path, probe = _resolve_utm_export(payload, run_id=run_id, specimen_id=specimen_id, trace=trace)
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
                "save_attempted_by_agent": raw_csv_save_attempted,
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
                "save_attempted_by_agent": raw_csv_save_attempted,
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
    response["data_acquisition"]["save_attempted_by_agent"] = raw_csv_save_attempted
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
        if program.get("managed_by") == "atr_equipment_skill" and program.get("integrity_ok") is not True:
            return {
                "ok": False,
                "status": "blocked",
                "bridge": "windows_pyautogui",
                "sequence_id": sequence_id,
                "program_id": program_id,
                "failure_code": "PYAUTOGUI_PROGRAM_HASH_MISMATCH",
                "message": "ATR-deployed Skill program content changed after deployment.",
                "step_trace": [{"step": "VERIFY_PROGRAM_HASH", "status": "blocked", "detail": program_id}],
            }
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
    global HOST, PORT, TOKEN, TOKEN_HEADER, ARTIFACT_ROOT, LOCATOR_ROOT, PROGRAM_ROOT, DEMO_ROOT, PAIRING_MANAGER, UPDATE_MANAGER
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
    PAIRING_MANAGER = PairingManager(ARTIFACT_ROOT / "pairing.json")
    if not PAIRING_MANAGER.status().get("paired"):
        PAIRING_MANAGER.issue_code()
    UPDATE_MANAGER = _new_update_manager()


def public_programs() -> list[dict[str, Any]]:
    return list(_programs().get("programs", []))


def execute_payload(payload: dict[str, Any], config: BridgeConfig | None = None) -> dict[str, Any]:
    if config is not None:
        _apply_bridge_config(config)
    return _execute(payload)


INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ATR Windows PyAutoGUI Bridge</title>
  <style>
    :root { color-scheme: light; --bg:#edf2f6; --panel:#fff; --soft:#f5f8fb; --ink:#172331; --muted:#66778a; --line:#d4dee8; --accent:#147a68; --accent2:#18556c; --ok:#15805f; --warn:#a06700; --bad:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--ink); font:14px/1.45 "Segoe UI","Malgun Gothic",sans-serif; }
    header { position:sticky; top:0; z-index:5; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 22px; background:#f9fbfc; border-bottom:1px solid var(--line); }
    h1,h2,h3,p { margin:0; }
    h1 { font-size:20px; } h2 { font-size:16px; } h3 { font-size:14px; }
    .eyebrow { color:var(--accent); font-size:11px; font-weight:800; letter-spacing:.09em; text-transform:uppercase; }
    .muted { color:var(--muted); }
    .shell { width:min(1440px,100%); margin:auto; padding:18px; display:grid; gap:14px; grid-template-columns:repeat(12,1fr); }
    .panel { grid-column:span 6; min-width:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:0 7px 20px rgba(31,48,65,.05); }
    .wide { grid-column:1/-1; }
    .panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; border-bottom:1px solid var(--line); background:var(--soft); }
    .panel-body { padding:15px; display:grid; gap:12px; }
    .status-grid,.form-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
    .status-tile { padding:11px; border:1px solid var(--line); border-radius:9px; background:#fff; }
    .status-tile small { display:block; color:var(--muted); margin-bottom:4px; }
    .status-tile strong { overflow-wrap:anywhere; }
    .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    label { display:grid; gap:5px; color:var(--muted); font-size:12px; }
    input,textarea,select,button { font:inherit; }
    input,textarea,select { width:100%; border:1px solid var(--line); border-radius:8px; padding:9px 10px; color:var(--ink); background:#fff; }
    textarea { min-height:190px; resize:vertical; font-family:Consolas,monospace; font-size:12px; }
    button,.button-link { border:1px solid var(--accent); border-radius:8px; padding:8px 11px; background:var(--accent); color:#fff; font-weight:700; cursor:pointer; text-decoration:none; }
    button.secondary,.button-link.secondary { color:var(--accent2); border-color:var(--line); background:#fff; }
    button.danger { color:var(--bad); border-color:#efc4bf; background:#fff; }
    button:disabled { cursor:not-allowed; opacity:.5; }
    .pill { display:inline-flex; align-items:center; min-height:24px; padding:3px 9px; border-radius:999px; background:#e8eef3; color:var(--muted); font-size:12px; font-weight:800; }
    .pill.ok { color:var(--ok); background:#e7f6ef; } .pill.warn { color:var(--warn); background:#fff3d6; } .pill.bad { color:var(--bad); background:#fff0ed; }
    .registry,.recording-list { display:grid; gap:8px; max-height:330px; overflow:auto; }
    .item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; padding:10px; border:1px solid var(--line); border-radius:9px; background:#fff; }
    .item strong,.item span { display:block; overflow-wrap:anywhere; }
    .item span { color:var(--muted); font-size:12px; }
    .editor[hidden] { display:none; }
    .countdown { font-size:30px; font-weight:900; color:var(--bad); text-align:center; }
    pre { margin:0; max-height:280px; overflow:auto; padding:12px; border-radius:9px; background:#111b25; color:#dce8f2; font:12px/1.5 Consolas,monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
    .recording-preview { display:grid; gap:9px; padding:10px; border:1px solid var(--line); border-radius:9px; background:#111b25; color:#dce8f2; }
    .recording-preview[hidden] { display:none; }
    .recording-preview img { display:block; width:100%; max-height:430px; object-fit:contain; border-radius:7px; background:#080e14; }
    .recording-preview .row { justify-content:space-between; }
    .recording-preview-meta { color:#aebdca; font:12px/1.4 Consolas,monospace; }
    details > summary { cursor:pointer; font-weight:800; }
    #diagnosticsPanel { grid-column:1/-1; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:13px 15px; }
    @media (max-width:900px) { .panel { grid-column:1/-1; } .status-grid,.form-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">Low-Level Worker</div><h1>ATR Windows PyAutoGUI Bridge</h1><p class="muted">Desktop execution, local programs, and bounded recording.</p></div>
    <span id="headerStatus" class="pill warn">not checked</span>
  </header>
  <main class="shell" id="essentialConsole">
    <section class="panel wide" id="bridgeStatusPanel">
      <div class="panel-head"><div><div class="eyebrow">Connection</div><h2>Bridge Status</h2></div><div class="row"><button id="health" type="button">Health</button><button id="refreshAll" class="secondary" type="button">Refresh</button></div></div>
      <div class="panel-body">
        <div class="status-grid">
          <div class="status-tile"><small>Server</small><strong id="bridgeServerState">not checked</strong></div>
          <div class="status-tile"><small>Linux ATR</small><strong id="bridgeAtrState">not paired</strong></div>
          <div class="status-tile"><small>Desktop Control</small><strong id="bridgeDesktopState">unknown</strong></div>
          <div class="status-tile"><small>PyAutoGUI</small><strong id="bridgePyAutoGuiState">unknown</strong></div>
          <div class="status-tile"><small>Endpoint</small><strong id="bridgeEndpoint">local console</strong></div>
          <div class="status-tile"><small>Data Root</small><strong id="bridgeDataRoot">-</strong></div>
        </div>
        <div id="pairingPanel" class="row"><span class="pill" id="pairingState">pairing status unavailable</span><strong id="pairingCode" aria-label="one-time pairing code">----</strong><button id="newPairingCode" class="secondary" type="button">New Code</button><button id="resetPairing" class="danger" type="button">Reset Pairing</button></div>
      </div>
    </section>

    <section class="panel" id="programManagerPanel">
      <div class="panel-head"><div><div class="eyebrow">Local Cache</div><h2>Program Manager</h2></div><div class="row"><button id="newProgram" type="button">Add</button><button id="browseProgram" class="secondary" type="button">Browse JSON</button><button id="downloadProgramTemplate" class="secondary" type="button">Template</button></div></div>
      <div class="panel-body">
        <div class="muted">Built-in program1 is available for local verification and cannot be modified or deleted.</div>
        <input id="programFile" type="file" accept="application/json,.json" hidden>
        <div class="row"><input id="managerSearch" placeholder="Filter programs" aria-label="Filter programs"><button id="refreshPrograms" class="secondary" type="button">Refresh</button></div>
        <div id="managerStats" class="muted">No program catalog loaded.</div>
        <div id="managerProgramRegistry" class="registry"></div>
        <div id="programEditor" class="editor" hidden>
          <label>Program JSON<textarea id="programDefinition" spellcheck="false"></textarea></label>
          <div class="row"><button id="validateProgram" class="secondary" type="button">Validate</button><button id="registerProgram" type="button">Save</button><button id="closeProgramEditor" class="secondary" type="button">Close</button></div>
        </div>
      </div>
    </section>

    <section class="panel" id="recordingPanel">
      <div class="panel-head"><div><div class="eyebrow">Bounded Evidence</div><h2>Recording</h2></div><span id="recordingStatus" class="pill">idle</span></div>
      <div class="panel-body">
        <div class="form-grid">
          <label>Name<input id="recordingName" value="Equipment demonstration"></label>
          <label>Target Program<input id="recordingTargetApp" placeholder="Program name"></label>
          <label>Target Window<input id="recordingTargetWindow" placeholder="Window title"></label>
        </div>
        <div class="row"><label><input id="recordingImageTracking" type="checkbox" checked> Image tracking</label><label><input id="recordingCoordinateFallback" type="checkbox"> Coordinate fallback</label></div>
        <div id="recordingCountdown" class="countdown" hidden></div>
        <div class="row"><button id="recordToggle" type="button">START RECORDING</button><button id="recordCheckpoint" class="secondary" type="button" disabled>Checkpoint</button><button id="refreshRecordings" class="secondary" type="button">Refresh</button></div>
        <div id="recordingList" class="recording-list"></div>
        <div id="recordingPreview" class="recording-preview" hidden>
          <img id="recordingPreviewImage" alt="Recording keyframe preview">
          <div class="row"><button id="recordingPreviewPrevious" class="secondary" type="button">Previous</button><span id="recordingPreviewMeta" class="recording-preview-meta">No preview selected.</span><button id="recordingPreviewNext" class="secondary" type="button">Next</button><button id="recordingPreviewClose" class="secondary" type="button">Close</button></div>
        </div>
      </div>
    </section>

    <section class="panel wide" id="latestLocalResultPanel">
      <div class="panel-head"><div><div class="eyebrow">Worker Feedback</div><h2>Latest Local Result</h2></div><span id="latestResultStatus" class="pill">idle</span></div>
      <div class="panel-body"><p id="latestResultSummary" class="muted">No local action result yet.</p><details><summary>Raw JSON</summary><pre id="managerLatestResult">{}</pre></details></div>
    </section>

    <details id="diagnosticsPanel">
      <summary>Diagnostics</summary>
      <div class="panel-body"><div class="row"><button id="diagnosticHealth" class="secondary" type="button">Health JSON</button><button id="diagnosticRequestLog" class="secondary" type="button">Request Log</button></div><pre id="diagnosticOutput">Diagnostics are loaded only on request.</pre></div>
    </details>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const TEMPLATE = {schema:"atr.pyautogui_program.v1",program_id:"custom_program",name:"Custom Program",description:"Bounded local draft",enabled:true,program_type:"macro",safe_test:true,sequence:[{action:"log",message:"program started"}]};
    let programs = [];
    let recordings = [];
    let activeRecordingId = "";
    let countdownTimer = 0;
    let recordingStatusTimer = 0;
    let recordingPreviewFrames = [];
    let recordingPreviewIndex = 0;
    let recordingPreviewRecordingId = "";
    let recordingPreviewCursor = 0;
    let recordingPreviewNextCursor = null;
    let recordingPreviewTotal = 0;
    const recordingPreviewLimit = 16;
    const RECORDING_COUNTDOWN_SECONDS = 5;

    function safe(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch])); }
    async function call(path, options={}) {
      const response = await fetch(path, options);
      const data = await response.json().catch(() => ({ok:false,status:"invalid_response",message:`HTTP ${response.status}`}));
      if (!response.ok && data.ok !== false) data.ok = false;
      return data;
    }
    function showResult(data, label="Local action") {
      const ok = data && data.ok !== false;
      const status = String(data && (data.status || data.failure_code) || (ok ? "ok" : "failed"));
      $("latestResultStatus").textContent = status;
      $("latestResultStatus").className = `pill ${ok ? "ok" : "bad"}`;
      $("latestResultSummary").textContent = `${label}: ${data && (data.message || data.failure_code || data.status) || "completed"}`;
      $("managerLatestResult").textContent = JSON.stringify(data || {}, null, 2);
      return data;
    }
    async function refreshHealth(renderRaw=false) {
      const data = await call("/health");
      $("bridgeServerState").textContent = data.status || (data.ok ? "ready" : "unreachable");
      $("bridgeDesktopState").textContent = data.screen ? `${data.screen.width || "-"}x${data.screen.height || "-"}` : "unknown";
      $("bridgePyAutoGuiState").textContent = data.pyautogui && data.pyautogui.available ? "available" : "unavailable";
      $("bridgeEndpoint").textContent = location.host || "local console";
      $("bridgeDataRoot").textContent = data.artifacts && data.artifacts.root || "-";
      $("headerStatus").textContent = data.ok ? "ready" : "attention";
      $("headerStatus").className = `pill ${data.ok ? "ok" : "warn"}`;
      if (renderRaw) $("diagnosticOutput").textContent = JSON.stringify(data, null, 2);
      return data;
    }
    async function refreshPairing() {
      const data = await call("/pairing/status");
      $("bridgeAtrState").textContent = data.paired ? "connected" : "not paired";
      $("pairingState").textContent = data.paired ? "paired" : data.status || "pairing available";
      $("pairingState").className = `pill ${data.paired ? "ok" : "warn"}`;
      $("pairingCode").textContent = data.pairing_code || "----";
      $("pairingCode").hidden = Boolean(data.paired);
      $("newPairingCode").hidden = Boolean(data.paired);
      return data;
    }
    async function refreshPrograms() {
      const data = await call("/programs");
      programs = Array.isArray(data.programs) ? data.programs : [];
      renderPrograms(); return data;
    }
    function renderPrograms() {
      const query = $("managerSearch").value.trim().toLowerCase();
      const rows = programs.filter((p) => !query || `${p.program_id} ${p.name || ""}`.toLowerCase().includes(query));
      $("managerStats").textContent = `${rows.length}/${programs.length} programs · builtin read-only · local drafts editable`;
      $("managerProgramRegistry").innerHTML = rows.map((p) => { const immutable=Boolean(p.built_in||p.managed_by==="atr_equipment_skill"); const source=p.built_in?"builtin":p.managed_by==="atr_equipment_skill"?"atr_skill":"local_draft"; return `<article class="item" data-program-id="${safe(p.program_id)}"><div><strong>${safe(p.name || p.program_id)}</strong><span>${safe(p.program_id)} · ${source} · ${p.enabled === false ? "disabled" : "enabled"}</span></div><div class="row"><button class="secondary" data-action="test">Test</button>${immutable ? "" : '<button class="secondary" data-action="edit">Edit</button><button class="danger" data-action="delete">Delete</button>'}</div></article>`; }).join("") || '<p class="muted">No matching programs.</p>';
    }
    function openEditor(definition=TEMPLATE) { $("programDefinition").value = JSON.stringify(definition, null, 2); $("programEditor").hidden = false; }
    function currentDefinition() { try { return JSON.parse($("programDefinition").value); } catch (error) { return {__parse_error__:String(error)}; } }
    async function validateProgram() { const data = await call("/programs/validate", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(currentDefinition())}); showResult(data,"Program validation"); }
    async function registerProgram() { const data = await call("/programs/register", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(currentDefinition())}); showResult(data,"Program save"); if (data.ok) { $("programEditor").hidden=true; await refreshPrograms(); } }
    async function testProgram(programId) { const data = await call("/execute", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sequence_id:`console-${Date.now()}`,run_id:`console-${Date.now()}`,specimen_id:"local-test",program_id:programId,command:programId})}); showResult(data,"Program test"); }
    async function deleteProgram(programId) { const data = await call(`/programs/${encodeURIComponent(programId)}`, {method:"DELETE"}); showResult(data,"Program delete"); await refreshPrograms(); }
    function downloadJson(name, value) { const blob=new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"}); const link=document.createElement("a"); link.href=URL.createObjectURL(blob); link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),0); }

    function syncRecordingToggle() { const active=Boolean(activeRecordingId); $("recordToggle").textContent="START RECORDING"; $("recordToggle").className=""; $("recordToggle").hidden=active; $("recordCheckpoint").disabled=!active; $("recordingStatus").textContent=active?"recording":"idle"; $("recordingStatus").className=`pill ${active?"bad":""}`; }
    function stopRecordingStatusWatch() { if(recordingStatusTimer){clearInterval(recordingStatusTimer);recordingStatusTimer=0;} }
    function startRecordingStatusWatch() { if(recordingStatusTimer)return; recordingStatusTimer=setInterval(()=>refreshRecordingStatus().catch(()=>{}),500); }
    async function refreshRecordingStatus() { const previous=activeRecordingId; const data=await call("/recordings/status"); activeRecordingId=data.status==="recording"?String(data.recording_id||activeRecordingId||""):""; syncRecordingToggle(); if(activeRecordingId)startRecordingStatusWatch();else stopRecordingStatusWatch(); if(previous&&!activeRecordingId)await refreshRecordings(); return data; }
    function beginRecordingCountdown() {
      let remaining=RECORDING_COUNTDOWN_SECONDS; $("recordingCountdown").hidden=false; $("recordingCountdown").textContent=remaining;
      $("recordToggle").disabled=true;
      countdownTimer=setInterval(async()=>{ remaining-=1; $("recordingCountdown").textContent=remaining; if(remaining<=0){ clearInterval(countdownTimer); countdownTimer=0; $("recordingCountdown").hidden=true; $("recordToggle").disabled=false; await startRecording(); } },1000);
    }
    async function startRecording() { const data=await call("/recordings/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:$("recordingName").value,target_app:$("recordingTargetApp").value,target_window:$("recordingTargetWindow").value,image_tracking:$("recordingImageTracking").checked,coordinate_fallback:$("recordingCoordinateFallback").checked})}); showResult(data,"Recording start"); if(data.ok){activeRecordingId=data.recording_id;syncRecordingToggle();startRecordingStatusWatch();} }
    async function toggleRecording() { if(!activeRecordingId)beginRecordingCountdown(); }
    async function refreshRecordings() { const data=await call("/recordings"); recordings=Array.isArray(data.recordings)?data.recordings:[]; $("recordingList").innerHTML=recordings.map((r)=>`<article class="item" data-recording-id="${safe(r.recording_id)}"><div><strong>${safe(r.name||r.recording_id)}</strong><span>${safe(r.recording_id)} · ${safe(r.status||"recorded")} · ${Number(r.event_count||0)} events</span></div><div class="row"><button class="secondary" data-action="preview">Preview</button><button class="secondary" data-action="export">Export</button><button class="danger" data-action="delete">Delete</button></div></article>`).join("")||'<p class="muted">No recordings.</p>'; return data; }
    async function recordingDetail(id) { return call(`/recordings/${encodeURIComponent(id)}`); }
    function renderRecordingPreview() {
      const preview = $("recordingPreview");
      const frame = recordingPreviewFrames[recordingPreviewIndex];
      preview.hidden = !frame;
      if (!frame) return;
      $("recordingPreviewImage").src = `data:${frame.media_type};base64,${frame.data_base64}`;
      $("recordingPreviewMeta").textContent = `${recordingPreviewCursor + recordingPreviewIndex + 1}/${recordingPreviewTotal} · ${frame.frame_id || "frame"} · ${(Number(frame.at_ms || 0) / 1000).toFixed(2)}s · ${frame.reason || "evidence"}`;
      $("recordingPreviewPrevious").disabled = recordingPreviewIndex <= 0 && recordingPreviewCursor <= 0;
      $("recordingPreviewNext").disabled = recordingPreviewIndex >= recordingPreviewFrames.length - 1 && recordingPreviewNextCursor == null;
    }
    async function loadRecordingPreviewPage(id, cursor=0, initialIndex=0) {
      recordingPreviewRecordingId = id;
      recordingPreviewCursor = Math.max(0, Number(cursor || 0));
      const data = await call(`/recordings/${encodeURIComponent(id)}/preview?cursor=${recordingPreviewCursor}&limit=${recordingPreviewLimit}`);
      recordingPreviewFrames = Array.isArray(data.frames) ? data.frames : [];
      recordingPreviewNextCursor = data.next_cursor == null ? null : Number(data.next_cursor);
      recordingPreviewTotal = Number(data.total_frame_count || recordingPreviewFrames.length);
      recordingPreviewIndex = Math.max(0, Math.min(Number(initialIndex || 0), recordingPreviewFrames.length - 1));
      renderRecordingPreview();
      showResult(data, recordingPreviewFrames.length ? "Recording preview" : "Recording preview has no visual frames");
    }
    async function openRecordingPreview(id) { await loadRecordingPreviewPage(id, 0, 0); }
    async function recordingAction(id,action) { if(action==="preview") await openRecordingPreview(id); if(action==="export"){const detail=await recordingDetail(id);downloadJson(`${id}.json`,detail);} if(action==="delete"){const data=await call(`/recordings/${encodeURIComponent(id)}`,{method:"DELETE"});showResult(data,"Recording delete");await refreshRecordings();} }

    $("health").addEventListener("click",()=>refreshHealth().then((d)=>showResult(d,"Health")));
    $("refreshAll").addEventListener("click",()=>Promise.all([refreshHealth(),refreshPairing(),refreshPrograms(),refreshRecordings()]));
    $("newPairingCode").addEventListener("click",async()=>{const d=await call("/pairing/new-code",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});showResult(d,"New pairing code");await refreshPairing();});
    $("resetPairing").addEventListener("click",async()=>{if(!confirm("Reset this bridge pairing and issue a new code?"))return;const d=await call("/pairing/reset",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});showResult(d,"Pairing reset");await refreshPairing();});
    $("managerSearch").addEventListener("input",renderPrograms);
    $("newProgram").addEventListener("click",()=>openEditor(TEMPLATE));
    $("browseProgram").addEventListener("click",()=>$("programFile").click());
    $("programFile").addEventListener("change",async()=>{const file=$("programFile").files&&$("programFile").files[0];if(file)openEditor(JSON.parse(await file.text()));});
    $("downloadProgramTemplate").addEventListener("click",()=>downloadJson("atr_pyautogui_program_template.json",TEMPLATE));
    $("validateProgram").addEventListener("click",validateProgram); $("registerProgram").addEventListener("click",registerProgram); $("closeProgramEditor").addEventListener("click",()=>$("programEditor").hidden=true); $("refreshPrograms").addEventListener("click",refreshPrograms);
    $("managerProgramRegistry").addEventListener("click",(event)=>{const button=event.target.closest("[data-action]");const card=event.target.closest("[data-program-id]");if(!button||!card)return;const id=card.dataset.programId;const program=programs.find((p)=>p.program_id===id);if(button.dataset.action==="test")testProgram(id);if(button.dataset.action==="edit"&&program)openEditor(program);if(button.dataset.action==="delete")deleteProgram(id);});
    $("recordToggle").addEventListener("click",toggleRecording); $("recordCheckpoint").addEventListener("click",async()=>showResult(await call("/recordings/checkpoint",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({label:"operator checkpoint"})}),"Recording checkpoint")); $("refreshRecordings").addEventListener("click",refreshRecordings); $("recordingList").addEventListener("click",(event)=>{const button=event.target.closest("[data-action]");const card=event.target.closest("[data-recording-id]");if(button&&card)recordingAction(card.dataset.recordingId,button.dataset.action);});
    $("recordingPreviewPrevious").addEventListener("click",async()=>{if(recordingPreviewIndex>0){recordingPreviewIndex-=1;renderRecordingPreview();return;}if(recordingPreviewCursor>0)await loadRecordingPreviewPage(recordingPreviewRecordingId,Math.max(0,recordingPreviewCursor-recordingPreviewLimit),recordingPreviewLimit-1);});
    $("recordingPreviewNext").addEventListener("click",async()=>{if(recordingPreviewIndex<recordingPreviewFrames.length-1){recordingPreviewIndex+=1;renderRecordingPreview();return;}if(recordingPreviewNextCursor!=null)await loadRecordingPreviewPage(recordingPreviewRecordingId,recordingPreviewNextCursor,0);});
    $("recordingPreviewClose").addEventListener("click",()=>{$("recordingPreview").hidden=true;});
    $("diagnosticHealth").addEventListener("click",()=>refreshHealth(true)); $("diagnosticRequestLog").addEventListener("click",async()=>$("diagnosticOutput").textContent=JSON.stringify(await call("/request-log"),null,2));
    syncRecordingToggle(); Promise.all([refreshHealth(),refreshPairing(),refreshPrograms(),refreshRecordings(),refreshRecordingStatus()]).catch((error)=>showResult({ok:false,status:"startup_failed",message:String(error)},"Console startup"));
  </script>
</body>
</html>

"""


class Handler(BaseHTTPRequestHandler):
    server_version = f"WindowsPyAutoGUIBridge/{BRIDGE_RELEASE_VERSION}"

    def _authorized(self) -> bool:
        supplied = self.headers.get(TOKEN_HEADER, "")
        paired = PAIRING_MANAGER.authorized(supplied)
        saved_connection = bool(TOKEN) and secrets.compare_digest(supplied, TOKEN)
        return paired or saved_connection

    def _is_local_request(self) -> bool:
        peer = self.client_address[0] if self.client_address else ""
        return peer in {"127.0.0.1", "::1", "localhost"}

    @staticmethod
    def _is_local_setup_path(path: str, method: str) -> bool:
        if method == "GET":
            return path in {"/health", "/programs", "/recordings", "/recordings/status", "/pairing/status", "/request-log"} or (
                path.startswith("/recordings/") and not path.endswith("/package")
            )
        if method == "POST":
            return path in {
                "/pairing/new-code",
                "/pairing/reset",
                "/execute",
                "/programs/validate",
                "/programs/register",
                "/recordings/start",
                "/recordings/checkpoint",
                "/recordings/stop",
            } or (path.startswith("/recordings/") and path.endswith("/save"))
        if method == "DELETE":
            return path.startswith("/programs/") or path.startswith("/recordings/")
        return False

    @staticmethod
    def _is_public_discovery_path(path: str, method: str) -> bool:
        return method == "GET" and path == "/discovery"

    @staticmethod
    def _is_pairing_optional_recording_path(path: str, method: str) -> bool:
        if method == "GET":
            return path in {"/recordings", "/recordings/status"} or (
                path.startswith("/recordings/") and not path.endswith("/package")
            )
        if method == "POST":
            return path in {
                "/recordings/start",
                "/recordings/checkpoint",
                "/recordings/stop",
            } or (path.startswith("/recordings/") and path.endswith("/save"))
        if method == "DELETE":
            return path.startswith("/recordings/")
        return False

    def _has_route_access(self, path: str, method: str) -> bool:
        if self._is_public_discovery_path(path, method):
            return True
        if self._is_pairing_optional_recording_path(path, method):
            return True
        if self._is_local_request() and self._is_local_setup_path(path, method):
            return True
        return self._authorized()

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

    def _require_auth(self, path: str, method: str) -> bool:
        auth_ok = self._has_route_access(path, method)
        self._audit_request(auth_ok=auth_ok, status="authorized" if auth_ok else "auth_required")
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

    def _send_text(self, status: int, value: str) -> None:
        data = value.encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=us-ascii")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _require_json_content_type(self) -> bool:
        media_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media_type == "application/json":
            return True
        self._send(
            415,
            {
                "ok": False,
                "status": "unsupported_media_type",
                "failure_code": "PYAUTOGUI_JSON_CONTENT_TYPE_REQUIRED",
                "message": "Mutating Bridge requests require Content-Type: application/json.",
            },
        )
        return False

    def _read_json_body(self, *, max_bytes: int) -> tuple[bool, dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except (TypeError, ValueError):
            length = -1
        if length < 0 or length > max_bytes:
            self._send(
                413,
                {
                    "ok": False,
                    "status": "request_too_large",
                    "failure_code": "PYAUTOGUI_REQUEST_TOO_LARGE",
                    "message": f"JSON request body must not exceed {max_bytes} bytes.",
                },
            )
            return False, {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("payload must be object")
        except Exception:
            self._send(400, {"ok": False, "status": "bad_request", "failure_code": "PYAUTOGUI_BAD_JSON"})
            return False, {}
        return True, payload

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        if path == "/ping":
            # Supervisor probes must stay tiny and out of the operator audit stream.
            self._send_text(200, f"ok {BRIDGE_RELEASE_VERSION}")
            return
        if path == "/discovery" and self._is_local_request():
            # Compatibility for a supervisor launched before /ping existed.
            self._send(200, {"ok": True, "server_version": self.server_version})
            return
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
        if not self._require_auth(path, "GET"):
            return
        if path == "/discovery":
            self._send(
                200,
                {
                    "ok": True,
                    "status": "ready",
                    "bridge": "windows_pyautogui",
                    "server_version": self.server_version,
                    "hostname": socket.gethostname(),
                    "platform": "windows" if os.name == "nt" else sys.platform,
                    "pairing": PAIRING_MANAGER.status(),
                },
            )
            return
        if path == "/pairing/status":
            self._send(200, PAIRING_MANAGER.status())
            return
        if path == "/health":
            self._send(200, _health())
            return
        if path == "/update/status":
            self._send(200, UPDATE_MANAGER.status())
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
        if path.startswith("/recordings/") and path.endswith("/preview"):
            recording_id = unquote(path.split("/recordings/", 1)[1].rsplit("/preview", 1)[0].strip("/"))
            try:
                cursor = int((query.get("cursor") or ["0"])[0])
                limit = int((query.get("limit") or ["16"])[0])
            except (TypeError, ValueError):
                cursor, limit = 0, 16
            payload = RECORDING_MANAGER.preview(recording_id, cursor=cursor, limit=limit)
            self._send(200 if payload.get("ok") else 404, payload)
            return
        if path.startswith("/recordings/") and path.endswith("/package"):
            recording_id = unquote(path.split("/recordings/", 1)[1].rsplit("/package", 1)[0].strip("/"))
            result = RECORDING_MANAGER.package(recording_id)
            status = 200 if result.get("ok") else 404 if result.get("status") == "not_found" else 413
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
        path = urlparse(self.path).path
        if path != "/pairing/complete" and not self._require_auth(path, "POST"):
            return
        if not self._require_json_content_type():
            return
        if path == "/update/stage":
            body_ok, payload = self._read_json_body(max_bytes=36 * 1024 * 1024)
            if not body_ok:
                return
            result = UPDATE_MANAGER.stage(payload)
            self._write_audit_event({"auth_ok": True, "status": "update_stage", "result_ok": bool(result.get("ok")), "version": str(result.get("version") or ""), "failure_code": str(result.get("failure_code") or "")})
            self._send(200 if result.get("ok") else 400, result)
            return
        if path in {"/update/apply", "/update/rollback"}:
            body_ok, _payload = self._read_json_body(max_bytes=16 * 1024)
            if not body_ok:
                return
            mode = "apply" if path.endswith("/apply") else "rollback"
            prepared = UPDATE_MANAGER.prepare_apply() if mode == "apply" else UPDATE_MANAGER.prepare_rollback()
            if not prepared.get("ok"):
                self._send(409, prepared)
                return
            result = _launch_self_updater(mode, prepared)
            self._write_audit_event({"auth_ok": True, "status": f"update_{mode}", "result_ok": bool(result.get("ok")), "version": str(result.get("version") or ""), "failure_code": str(result.get("failure_code") or "")})
            self._send(202 if result.get("ok") else 500, result)
            if result.get("ok"):
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path in {"/pairing/new-code", "/pairing/reset", "/pairing/complete"}:
            body_ok, payload = self._read_json_body(max_bytes=16 * 1024)
            if not body_ok:
                return
            if path == "/pairing/new-code":
                result = PAIRING_MANAGER.issue_code()
                self._send(200 if result.get("ok") else 409, result)
                return
            if path == "/pairing/reset":
                result = PAIRING_MANAGER.reset()
                self._send(200, result)
                return
            result = PAIRING_MANAGER.complete(str(payload.get("pairing_code") or ""))
            self._send(200 if result.get("ok") else 429 if result.get("status") == "locked" else 400, result)
            return
        recording_save = path.startswith("/recordings/") and path.endswith("/save")
        if path not in {
            "/execute", "/screenshot", "/locators/capture", "/programs/validate", "/programs/register",
            "/recordings/start", "/recordings/checkpoint", "/recordings/stop",
        } and not recording_save:
            self._send(404, {"ok": False, "status": "not_found"})
            return
        body_ok, payload = self._read_json_body(max_bytes=2 * 1024 * 1024)
        if not body_ok:
            return
        if path == "/recordings/start":
            result = RECORDING_MANAGER.start(
                name=str(payload.get("name") or "Equipment demonstration"),
                target_app=str(payload.get("target_app") or ""),
                target_window=str(payload.get("target_window") or ""),
                image_tracking=payload.get("image_tracking") is not False,
                coordinate_fallback=payload.get("coordinate_fallback") is True,
                mask_regions=payload.get("mask_regions"),
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
            deployment = payload.get("_atr_deployment") if isinstance(payload.get("_atr_deployment"), dict) else {}
            managed = self._authorized() and str(deployment.get("managed_by") or "") == "atr_equipment_skill"
            definition = payload.get("program") if managed and isinstance(payload.get("program"), dict) else payload
            result = _register_program_definition(
                definition,
                managed=managed,
                deployment_sha256=str(deployment.get("program_sha256") or "") if managed else "",
            )
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
        path = urlparse(self.path).path
        if not self._require_auth(path, "DELETE"):
            return
        if path.startswith("/recordings/"):
            recording_id = unquote(path.split("/recordings/", 1)[1].strip("/"))
            result = RECORDING_MANAGER.delete(recording_id)
            status = 200 if result.get("ok") else 404 if result.get("status") == "not_found" else 409
            self._send(status, result)
            return
        if not path.startswith("/programs/"):
            self._send(404, {"ok": False, "status": "not_found"})
            return
        program_id = unquote(path.split("/programs/", 1)[1].strip("/"))
        query = parse_qs(urlparse(self.path).query)
        allow_managed = self._authorized() and str((query.get("source") or [""])[0]) == "atr"
        result = _delete_custom_program(program_id, allow_managed=allow_managed)
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
    global HOST, PORT, TOKEN, TOKEN_HEADER, ARTIFACT_ROOT, LOCATOR_ROOT, UTM_EXPORT_ROOT, PROGRAM_ROOT, RECORDING_ROOT, DEMO_ROOT, RECORDING_MANAGER, BRIDGE_PLATFORM, PAIRING_MANAGER, UPDATE_MANAGER
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
    PAIRING_MANAGER = PairingManager(ARTIFACT_ROOT / "pairing.json")
    if not PAIRING_MANAGER.status().get("paired"):
        PAIRING_MANAGER.issue_code()
    UPDATE_MANAGER = _new_update_manager()
    return args


def main() -> None:
    args = _parse_cli_args()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    LOCATOR_ROOT.mkdir(parents=True, exist_ok=True)
    RECORDING_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    pyautogui, _ = _load_pyautogui()
    print(f"Windows PyAutoGUI bridge listening on {HOST}:{PORT}")
    print(f"Pairing: {'paired' if PAIRING_MANAGER.status().get('paired') else 'required'}")
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
