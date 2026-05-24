"""
Minimal Windows PyAutoGUI bridge server.

Run on Windows:
  py windows_pyautogui_bridge_server.py

Environment:
  WINDOWS_PYAUTOGUI_BRIDGE_HOST=0.0.0.0
  WINDOWS_PYAUTOGUI_BRIDGE_PORT=8765
  WINDOWS_PYAUTOGUI_BRIDGE_TOKEN=<token>

Endpoints:
  GET  /health
  GET  /programs
  POST /execute
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


HOST = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN", "")
TOKEN_HEADER = os.getenv("WINDOWS_PYAUTOGUI_BRIDGE_TOKEN_HEADER", "X-Bridge-Token")

PROGRAMS = {
    "program1": {
        "description": "Demo macro: verify PyAutoGUI, move mouse briefly, and return completion log.",
        "requires_pyautogui": True,
        "safe_test": True,
    }
}


def _load_pyautogui() -> tuple[Any | None, str]:
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
        return pyautogui, ""
    except Exception as exc:
        return None, exc.__class__.__name__


def _health() -> dict[str, Any]:
    pyautogui, error = _load_pyautogui()
    if pyautogui is None:
        return {
            "ok": True,
            "status": "degraded",
            "bridge": "windows_pyautogui",
            "auth": {"token_required": True, "authenticated": True},
            "screen": None,
            "pyautogui": {"available": False, "error": error},
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
    }


def _programs() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ready",
        "bridge": "windows_pyautogui",
        "auth": {"token_required": True, "authenticated": True},
        "programs": [{"program_id": key, **value} for key, value in sorted(PROGRAMS.items())],
    }


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


def _execute(payload: dict[str, Any]) -> dict[str, Any]:
    sequence_id = str(payload.get("sequence_id") or f"win-{int(time.time())}")
    program_id = str(payload.get("program_id") or "").strip()
    if program_id:
        if program_id != "program1":
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
        return _run_program1(sequence_id)
    return {
        "ok": True,
        "status": "completed",
        "bridge": "windows_pyautogui",
        "sequence_id": sequence_id,
        "step_trace": [{"step": "DONE", "status": "ok", "detail": "no-op sequence accepted"}],
        "failure_code": None,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "WindowsPyAutoGUIBridge/0.1"

    def _authorized(self) -> bool:
        return self.headers.get(TOKEN_HEADER, "") == TOKEN

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"ok": False, "status": "auth_required", "failure_code": "PYAUTOGUI_AUTH_FAILED"})
            return
        if self.path == "/health":
            self._send(200, _health())
            return
        if self.path == "/programs":
            self._send(200, _programs())
            return
        self._send(404, {"ok": False, "status": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"ok": False, "status": "auth_required", "failure_code": "PYAUTOGUI_AUTH_FAILED"})
            return
        if self.path != "/execute":
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
        self._send(200, _execute(payload))

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {format % args}")


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "WINDOWS_PYAUTOGUI_BRIDGE_TOKEN is required. "
            "Set it before starting the bridge, for example: "
            "$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN='<random-token>'"
        )
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    pyautogui, _ = _load_pyautogui()
    print(f"Windows PyAutoGUI bridge listening on {HOST}:{PORT}")
    print("Token authentication: enabled")
    print(f"PyAutoGUI available: {str(pyautogui is not None).lower()}")
    print("PyAutoGUI FAILSAFE: True when available")
    server.serve_forever()


if __name__ == "__main__":
    main()
