#!/usr/bin/env python3
"""Local smoke test for the packaged Windows PyAutoGUI bridge server.

The test intentionally uses the packaged public compatibility API
(`BridgeConfig`, `BridgeHTTPServer`, `BridgeRequestHandler`) because that is the
API available to Windows-side packaging/tests. It does not require PyAutoGUI to
be installed; a missing PyAutoGUI driver is accepted for `program1` as long as
the bridge blocks explicitly.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "bridge"))

import windows_pyautogui_bridge_server as bridge


def request_json(base: str, path: str, token: str | None = None, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Bridge-Token"] = token
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def request_text(base: str, path: str) -> tuple[int, str]:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(base: str, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            request_text(base, "/")
            return
        except Exception as exc:  # pragma: no cover - startup timing only
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"server did not become ready: {last_error}")


def smoke_cli_launch(root: Path) -> None:
    """Verify the packaged script honors PowerShell-style CLI overrides."""
    port = free_port()
    token = "cli-token"
    artifact_dir = root / "cli_artifacts"
    reference_dir = root / "cli_reference_images"
    process = subprocess.Popen(
        [
            sys.executable,
            str(PROJECT_ROOT / "bridge" / "windows_pyautogui_bridge_server.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--token",
            token,
            "--artifact-dir",
            str(artifact_dir),
            "--reference-dir",
            str(reference_dir),
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for_http(base)
        status, data = request_json(base, "/health", token=token)
        assert status == 200, data
        assert data["artifacts"]["root"] == str(artifact_dir), data
        assert data["artifacts"]["locator_root"] == str(reference_dir), data
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        stdout, stderr = process.communicate(timeout=1)
        if process.returncode not in {0, -15, 1}:
            raise RuntimeError(f"unexpected CLI process exit {process.returncode}: stdout={stdout} stderr={stderr}")


def main() -> int:
    token = "test-token"
    with tempfile.TemporaryDirectory(prefix="atr_windows_bridge_smoke_") as tmp:
        root = Path(tmp)
        config = bridge.BridgeConfig(
            host="127.0.0.1",
            port=0,
            token=token,
            token_header="X-Bridge-Token",
            artifact_dir=root / "artifacts",
            reference_dir=root / "reference_images",
        )
        config.artifact_dir.mkdir(parents=True, exist_ok=True)
        config.reference_dir.mkdir(parents=True, exist_ok=True)
        server = bridge.BridgeHTTPServer(("127.0.0.1", 0), bridge.BridgeRequestHandler, config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, html = request_text(base, "/")
            assert status == 200, html[:200]
            for token_text in ("Run Timeline", "Live Proof Checklist", "Operator runtime status", "Recommended next action"):
                assert token_text in html, token_text

            status, data = request_json(base, "/health")
            assert status == 401, data
            assert data["failure_code"] == "PYAUTOGUI_AUTH_FAILED", data

            status, data = request_json(base, "/health", token=token)
            assert status == 200, data
            assert data["bridge"] == "windows_pyautogui", data
            assert data["artifacts"]["request_log"].endswith("bridge_requests.jsonl"), data

            status, data = request_json(base, "/programs", token=token)
            assert status == 200, data
            program_ids = {item["program_id"] for item in data["programs"]}
            for program_id in {"program1", "utm_compression_start_v1", "utm_export_csv_v1", "utm_manual_save_csv_v1", "utm_stop_or_abort_v1"}:
                assert program_id in program_ids, data

            status, data = request_json(base, "/readiness", token=token)
            assert status == 200, data
            assert data["tool"] in {"equipment.pyautogui.utm_readiness", "equipment.pyautogui.windows_readiness"}, data
            assert "gates" in data and "blockers" in data, data

            status, data = request_json(base, "/request-log", token=token)
            assert status == 200, data
            assert data["ok"] is True, data
            assert str(data.get("request_log", "")).endswith("bridge_requests.jsonl"), data

            status, data = request_json(
                base,
                "/execute",
                token=token,
                payload={"sequence_id": "bad-action", "sequence": [{"action": "shell"}]},
            )
            assert status in {200, 400}, data
            assert data["failure_code"] in {"PYAUTOGUI_ACTION_NOT_ALLOWED", "PYAUTOGUI_NOT_INSTALLED"}, data

            status, data = request_json(
                base,
                "/execute",
                token=token,
                payload={"sequence_id": "program1-check", "program_id": "program1"},
            )
            assert status in {200, 400}, data
            assert data.get("failure_code") in {None, "PYAUTOGUI_NOT_INSTALLED"}, data
            assert data["program_id"] == "program1", data

            status, data = request_json(base, "/artifacts", token=token)
            assert status == 200, data
            assert data["ok"] is True, data
            print("smoke test passed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        smoke_cli_launch(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
