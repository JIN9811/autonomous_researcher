"""Unit tests for the optional Windows PyAutoGUI bridge helper."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeImage:
    def save(self, path: Path) -> None:
        path.write_bytes(TINY_PNG_BYTES)


class _FakeInvalidImage:
    def save(self, path: Path) -> None:
        path.write_bytes(b"not-an-image")


class _FakeBox:
    left = 1
    top = 1
    width = 10
    height = 10


class _FakeWindow:
    def __init__(self, title: str) -> None:
        self.title = title
        self.isMinimized = False
        self.activated = False
        self.restored = False
        self.minimized = False
        self.maximized = False
        self.moves: list[tuple[int, int]] = []
        self.resizes: list[tuple[int, int]] = []

    def activate(self) -> None:
        self.activated = True

    def restore(self) -> None:
        self.restored = True
        self.isMinimized = False

    def minimize(self) -> None:
        self.minimized = True

    def maximize(self) -> None:
        self.maximized = True

    def moveTo(self, x: int, y: int) -> None:  # noqa: N802
        self.moves.append((x, y))

    def resizeTo(self, width: int, height: int) -> None:  # noqa: N802
        self.resizes.append((width, height))


class _FakeRecordingOverlay:
    def __init__(self) -> None:
        self.show_calls: list[tuple[str, float]] = []
        self.hide_calls = 0
        self.shutdown_calls = 0
        self.visible = False

    def show(self, recording_id: str, started_monotonic: float) -> None:
        self.show_calls.append((recording_id, started_monotonic))
        self.visible = True

    def hide(self) -> None:
        self.hide_calls += 1
        self.visible = False

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.visible = False

    def status(self) -> dict[str, Any]:
        return {"available": True, "visible": self.visible, "error": None}


class _FakeUiaElement:
    def __init__(self) -> None:
        self.clicked = False

    def exists(self, timeout: float = 0.0) -> bool:
        return True

    def click_input(self) -> None:
        self.clicked = True


class _FakePyAutoGUI:
    def __init__(self) -> None:
        self.FAILSAFE = True
        self.PAUSE = 0.1
        self.clicks: list[tuple[int, int]] = []
        self.moves: list[tuple[int, int, float]] = []
        self.relative_moves: list[tuple[int, int, float]] = []
        self.drags: list[tuple[str, int, int, float, str]] = []
        self.button_events: list[tuple[str, str]] = []
        self.scrolls: list[tuple[str, int]] = []
        self.key_events: list[tuple[str, str]] = []
        self.presses: list[tuple[str, int, float]] = []
        self.alerts: list[str] = []
        self.confirms: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []
        self.writes: list[str] = []
        self.save_csv_on_write = False
        self.locate_matches = False
        self.locate_match_paths: set[str] = set()
        self.locate_match_after_click_paths: set[str] = set()
        self.locate_calls: list[tuple[str, dict[str, object]]] = []
        self.screenshot_regions: list[tuple[int, int, int, int] | None] = []
        self.windows_by_title: dict[str, list[_FakeWindow]] = {}
        self.all_windows: list[_FakeWindow] = []

    def size(self) -> tuple[int, int]:
        return (1920, 1080)

    def getWindowsWithTitle(self, title: str) -> list[_FakeWindow]:  # noqa: N802 - mirrors PyAutoGUI API
        return list(self.windows_by_title.get(title, []))

    def getAllWindows(self) -> list[_FakeWindow]:  # noqa: N802 - mirrors PyAutoGUI API
        return list(self.all_windows)

    def locateOnScreen(self, image_path: str, **kwargs: object) -> object | None:  # noqa: N802 - mirrors PyAutoGUI API
        self.locate_calls.append((image_path, dict(kwargs)))
        path_text = str(image_path)
        if self.locate_matches or path_text in self.locate_match_paths:
            return _FakeBox()
        if self.clicks and path_text in self.locate_match_after_click_paths:
            return _FakeBox()
        return None

    def click(self, x: int | None = None, y: int | None = None, clicks: int = 1, interval: float = 0.0, button: str = "left") -> None:
        self.clicks.extend((int(x or 0), int(y or 0)) for _ in range(clicks))

    def moveTo(self, x: int, y: int, duration: float = 0.0) -> None:  # noqa: N802 - mirrors PyAutoGUI API
        self.moves.append((x, y, duration))

    def moveRel(self, x: int, y: int, duration: float = 0.0) -> None:  # noqa: N802
        self.relative_moves.append((x, y, duration))

    def dragTo(self, x: int, y: int, duration: float = 0.0, button: str = "left") -> None:  # noqa: N802
        self.drags.append(("to", x, y, duration, button))

    def dragRel(self, x: int, y: int, duration: float = 0.0, button: str = "left") -> None:  # noqa: N802
        self.drags.append(("rel", x, y, duration, button))

    def mouseDown(self, button: str = "left") -> None:  # noqa: N802
        self.button_events.append(("down", button))

    def mouseUp(self, button: str = "left") -> None:  # noqa: N802
        self.button_events.append(("up", button))

    def scroll(self, clicks: int) -> None:
        self.scrolls.append(("vertical", clicks))

    def hscroll(self, clicks: int) -> None:
        self.scrolls.append(("horizontal", clicks))

    def vscroll(self, clicks: int) -> None:
        self.scrolls.append(("vertical_explicit", clicks))

    def hotkey(self, *keys: str, interval: float = 0.0) -> None:
        self.hotkeys.append(tuple(keys))

    def press(self, key: str, presses: int = 1, interval: float = 0.0) -> None:
        self.presses.append((key, presses, interval))

    def keyDown(self, key: str) -> None:  # noqa: N802
        self.key_events.append(("down", key))

    def keyUp(self, key: str) -> None:  # noqa: N802
        self.key_events.append(("up", key))

    def write(self, value: str, interval: float = 0.0) -> None:
        self.writes.append(value)
        if self.save_csv_on_write:
            path = Path(value)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n", encoding="utf-8")

    def center(self, box: object) -> object:
        return SimpleNamespace(x=1, y=1)

    def screenshot(self, region: tuple[int, int, int, int] | None = None) -> _FakeImage:
        self.screenshot_regions.append(region)
        return _FakeImage()

    def position(self) -> tuple[int, int]:
        return (640, 360)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return (10, 20, 30)

    def pixelMatchesColor(self, x: int, y: int, color: tuple[int, int, int], tolerance: int = 0) -> bool:  # noqa: N802
        return (x, y, color, tolerance) == (10, 20, (10, 20, 30), 5)

    def alert(self, text: str, title: str = "") -> str:
        self.alerts.append(text)
        return "OK"

    def confirm(self, text: str, title: str = "", buttons: list[str] | None = None) -> str:
        self.confirms.append(text)
        return (buttons or ["OK"])[0]


class _FakeInvalidScreenshotPyAutoGUI(_FakePyAutoGUI):
    def screenshot(self, region: tuple[int, int, int, int] | None = None) -> _FakeInvalidImage:
        self.screenshot_regions.append(region)
        return _FakeInvalidImage()


def _load_helper_module():
    helper_path = Path(__file__).resolve().parents[2] / "install" / "windows_pyautogui_bridge_server.py"
    spec = importlib.util.spec_from_file_location("windows_pyautogui_bridge_server_under_test", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module



def _load_packaged_helper_module():
    helper_path = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py"
    spec = importlib.util.spec_from_file_location("packaged_windows_pyautogui_bridge_server_under_test", helper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bridge_platform_auto_resolves_linux() -> None:
    module = _load_packaged_helper_module()

    assert module._normalize_bridge_platform("auto", system_name="linux") == "linux"
    assert module._normalize_bridge_platform("windows", system_name="linux") == "windows"


def test_linux_platform_health_requires_x11(monkeypatch) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "BRIDGE_PLATFORM", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", "")

    status = module._desktop_platform_status()

    assert status["name"] == "linux"
    assert status["desktop_control_ready"] is False
    assert status["failure_code"] == "PYAUTOGUI_LOCAL_DISPLAY_UNSUPPORTED"


def test_linux_platform_health_accepts_x11(monkeypatch) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "BRIDGE_PLATFORM", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":1")

    status = module._desktop_platform_status()

    assert status["desktop_control_ready"] is True
    assert status["display"] == ":1"
    assert status["scope"] == "localhost"


def test_token_file_is_loaded_without_exposing_value(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    token_file = tmp_path / "local.token"
    token_file.write_text("local-secret\n", encoding="utf-8")

    token = module._read_bridge_token_file(token_file)

    assert token == "local-secret"


def test_linux_validation_marks_windows_specific_locators_for_recalibration(monkeypatch) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "BRIDGE_PLATFORM", "linux")

    result = module._validate_program_definition(
        {
            "schema": "atr.pyautogui_program.v1",
            "program_id": "portable_demo",
            "name": "Portable Demo",
            "sequence": [
                {"action": "click", "x": 100, "y": 100},
                {"action": "click", "target": "start_button"},
            ],
            "locators": {
                "start_button": {
                    "locator_backend": "uia",
                    "auto_id": "StartButton",
                }
            },
        }
    )

    assert result["ok"] is True
    assert result["platform_tested"] == "linux"
    assert "click" in result["portable_actions"]
    assert result["platform_specific_locators"] == ["start_button"]
    assert result["requires_windows_recalibration"] is True


def test_linux_focus_window_uses_wmctrl(monkeypatch) -> None:
    module = _load_packaged_helper_module()
    calls: list[list[str]] = []

    class _RunResult:
        def __init__(self, stdout: str = "") -> None:
            self.stdout = stdout
            self.returncode = 0

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        if command[:2] == ["wmctrl", "-l"]:
            return _RunResult("0x03c00007  0 host UTM Demo Window\n")
        return _RunResult()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    ok, detail = module._focus_linux_window(["UTM Demo"], [])

    assert ok is True
    assert "UTM Demo Window" in detail
    assert ["wmctrl", "-ia", "0x03c00007"] in calls

def test_sequence_warnings_do_not_fake_locator_success_when_not_required() -> None:
    module = _load_helper_module()
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={"sequence": [{"action": "assert_visible", "target": "ready_state"}, {"action": "click", "target": "start_button"}]},
        run_id="run-test",
        specimen_id="specimen-test",
        trace=trace,
    )

    assert result["ok"] is True
    assert any(item["status"] == "warning" for item in trace)


def test_required_screen_assertion_blocks_without_locator() -> None:
    module = _load_helper_module()
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={"sequence": [{"action": "assert_visible", "target": "ready_state"}]},
        run_id="run-test",
        specimen_id="specimen-test",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UI_LOCATOR_NOT_FOUND"
    assert trace[-1]["status"] == "blocked"



def test_bridge_save_dialog_wait_timeout_has_specific_failure_code() -> None:
    for loader in (_load_helper_module, _load_packaged_helper_module):
        module = loader()
        module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
        trace: list[dict[str, object]] = []

        result = module._execute_protocol_sequence(
            _FakePyAutoGUI(),
            program_id="utm_manual_save_csv_v1",
            payload={
                "locators": {"save_dialog": {"image_path": "save_dialog.png"}},
                "sequence": [{"action": "wait_until", "target": "save_dialog", "timeout_s": 0.1, "required": True}],
            },
            run_id="run-save-dialog-timeout",
            specimen_id="specimen-save-dialog-timeout",
            trace=trace,
        )

        assert result["ok"] is False
        assert result["failure_code"] == "UTM_SAVE_DIALOG_TIMEOUT"
        assert trace[-1]["status"] == "blocked"
        assert "UTM_SAVE_DIALOG_TIMEOUT" in trace[-1]["detail"]


def test_bridge_text_assertion_uses_optional_ocr_primitive() -> None:
    for loader in (_load_helper_module, _load_packaged_helper_module):
        module = loader()
        fake = _FakePyAutoGUI()
        fake.ocr_text = "Status: Running - force curve active"
        trace: list[dict[str, object]] = []

        result = module._execute_protocol_sequence(
            fake,
            program_id="utm_compression_start_v1",
            payload={
                "locators": {"status_text": {"contains": "running"}},
                "sequence": [{"action": "assert_text", "target": "status_text", "required": True}],
            },
            run_id="run-ocr-status",
            specimen_id="specimen-ocr-status",
            trace=trace,
        )

        assert result["ok"] is True
        assert trace[-1]["status"] == "ok"
        assert "status_text via ocr" in trace[-1]["detail"]


def test_install_bridge_click_without_running_state_returns_transition_failure() -> None:
    module = _load_helper_module()
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    fake = _FakePyAutoGUI()
    fake.locate_match_paths = {"ready.png", "start.png"}
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "locators": {
                "ready_state": {"image_path": "ready.png"},
                "start_button": {"image_path": "start.png"},
                "running_state": {"image_path": "running.png"},
            },
            "sequence": [
                {"action": "assert_visible", "target": "ready_state", "required": True},
                {"action": "click", "target": "start_button", "required": True},
                {"action": "wait_until", "target": "running_state", "timeout_s": 0.1, "required": True},
            ],
        },
        run_id="run-no-transition",
        specimen_id="specimen-no-transition",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "CLICK_NO_STATE_CHANGE"
    assert result["timeout_failure_code"] == "UTM_RUNNING_STATE_TIMEOUT"
    assert fake.clicks
    assert trace[-1]["status"] == "blocked"
    assert "CLICK_NO_STATE_CHANGE" in trace[-1]["detail"]


def test_packaged_bridge_detects_configured_error_popup_after_click() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_match_paths = {"start.png"}
    fake.locate_match_after_click_paths = {"error.png"}
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "locators": {
                "start_button": {"image_path": "start.png"},
                "error_popup": {"image_path": "error.png"},
            },
            "sequence": [
                {"action": "click", "target": "start_button", "required": True},
                {"action": "wait", "seconds": 0.01},
            ],
        },
        run_id="run-popup",
        specimen_id="specimen-popup",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_ERROR_POPUP_DETECTED"
    assert fake.clicks
    assert any(item["status"] == "blocked" and "error_popup" in item.get("detail", "") for item in trace)



def test_capture_locator_writes_locator_file_and_metadata(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    module.LOCATOR_ROOT = tmp_path / "locators"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._capture_locator(
        {
            "program_id": "utm_compression_start_v1",
            "name": "start_button",
            "region": [10, 20, 120, 60],
            "confidence": 0.87,
        }
    )

    assert result["ok"] is True
    assert result["locator_name"] == "start_button"
    assert result["locator"]["image_path"].endswith("start_button.png")
    assert Path(result["locator"]["image_path"]).exists()
    assert fake.screenshot_regions == [(10, 20, 120, 60)]
    assert result["output_artifacts"][0]["kind"] == "locator_png"


def test_capture_locator_requires_region() -> None:
    module = _load_helper_module()
    module._load_pyautogui = lambda: (_FakePyAutoGUI(), "")

    result = module._capture_locator({"program_id": "utm_compression_start_v1", "name": "ready_state"})

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_LOCATOR_REGION_REQUIRED"


def test_packaged_bridge_utm_simulation_creates_pullable_csv_artifact(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.LOCATOR_ROOT = tmp_path / "locators"
    module.ARTIFACT_INDEX.clear()
    module.get_pyautogui = lambda: (fake, None)
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )

    result = module.execute_payload(
        {
            "sequence_id": "utm-sim-unit",
            "program_id": "utm_compression_start_v1",
            "run_id": "run-unit",
            "specimen_id": "specimen-unit",
            "simulate_utm_protocol": True,
        },
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["program_type"] == "utm_protocol"
    artifact = result["output_artifacts"][0]
    assert artifact["kind"] == "utm_csv"
    assert artifact["row_count_probe"] == 80
    assert {"time_s", "displacement_mm", "force_N"}.issubset(set(artifact["columns_probe"]))

    status, pulled = module._get_artifact(artifact["artifact_id"])
    assert status == 200
    assert pulled["content_base64"]
    assert pulled["sha256"] == artifact["sha256"]


def _assert_existing_artifacts_are_reindexed(module, tmp_path: Path) -> None:
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_INDEX.clear()
    csv_path = module.UTM_EXPORT_ROOT / "run-existing" / "specimen-existing.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n", encoding="utf-8")
    screen_path = module.ARTIFACT_ROOT / "run-existing" / "screenshots" / "screen_before_start_existing.png"
    screen_path.parent.mkdir(parents=True, exist_ok=True)
    screen_path.write_bytes(TINY_PNG_BYTES)

    listing = module._list_artifacts()

    assert listing["ok"] is True
    assert listing["artifact_count"] == 2
    assert listing["indexed_from_disk_count"] == 2
    by_kind = {item["kind"]: item for item in listing["artifacts"]}
    assert by_kind["utm_csv"]["row_count_probe"] == 2
    assert by_kind["utm_csv"]["columns_probe"] == ["time_s", "displacement_mm", "force_N"]
    assert by_kind["utm_csv"]["indexed_from_disk"] is True
    assert by_kind["screen_png"]["content_type"] == "image/png"

    status, pulled = module._get_artifact(by_kind["utm_csv"]["artifact_id"])
    assert status == 200
    assert pulled["content_base64"]
    assert pulled["sha256"] == by_kind["utm_csv"]["sha256"]


def test_install_bridge_reindexes_existing_artifacts_after_restart(tmp_path: Path) -> None:
    _assert_existing_artifacts_are_reindexed(_load_helper_module(), tmp_path)


def test_packaged_bridge_reindexes_existing_artifacts_after_restart(tmp_path: Path) -> None:
    _assert_existing_artifacts_are_reindexed(_load_packaged_helper_module(), tmp_path)


def _assert_registered_utm_program_contract(programs: list[dict[str, object]]) -> None:
    by_id = {str(item.get("program_id")): item for item in programs}
    expected = {"utm_compression_start_v1", "utm_export_csv_v1", "utm_manual_save_csv_v1", "utm_stop_or_abort_v1"}
    assert expected.issubset(by_id)
    compression = by_id["utm_compression_start_v1"]
    assert compression["program_type"] == "utm_protocol"
    assert compression["preconditions"] == ["windows_bridge_ready", "utm_app_visible", "specimen_verified_on_fixture", "robot_clear_of_utm"]
    assert compression["expected_screen_before"][0]["name"] == "ready_state"
    assert any(item.get("target") == "running_state" for item in compression["sequence"] if isinstance(item, dict))
    assert any(item.get("target") == "complete_state" for item in compression["sequence"] if isinstance(item, dict))
    assert compression["save_policy"]["manual_save_required_if_no_artifact"] is True
    assert compression["output_artifacts"][0]["kind"] == "utm_csv"
    assert compression["safe_abort"]["program_id"] == "utm_stop_or_abort_v1"
    export = by_id["utm_export_csv_v1"]
    assert export["program_type"] == "utm_export"
    assert export["target_window"] == "main_window_title_or_regex"
    assert export["expected_screen_before"][0]["name"] == "complete_state"
    assert export["save_policy"]["save_method"] == "export_menu"
    manual = by_id["utm_manual_save_csv_v1"]
    assert manual["target_window"] == "main_window_title_or_regex"
    assert manual["save_policy"]["save_method"] == "manual_save_dialog"
    assert manual["save_policy"]["manual_save_required_if_no_artifact"] is False
    abort = by_id["utm_stop_or_abort_v1"]
    assert abort["program_type"] == "utm_abort"
    assert abort["target_window"] == "main_window_title_or_regex"
    assert abort["preconditions"] == ["windows_bridge_ready", "utm_app_visible_or_focused"]
    assert abort["expected_screen_before"][0]["name"] == "running_or_unknown_state"
    assert abort["expected_screen_after"][0]["name"] == "stopped_or_idle_state"
    assert abort["save_policy"]["save_method"] == "not_applicable"
    assert abort["output_artifacts"] == []
    assert abort["sequence"][0]["action"] == "press"
    assert abort["safe_abort"]["action"] == "press"


def test_install_and_packaged_bridge_list_full_utm_program_contract() -> None:
    install_module = _load_helper_module()
    packaged_module = _load_packaged_helper_module()

    _assert_registered_utm_program_contract(install_module._programs()["programs"])
    _assert_registered_utm_program_contract(packaged_module.public_programs())


def test_install_bridge_utm_readiness_blocks_when_required_locators_missing(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.LOCATOR_ROOT = tmp_path / "locators"
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.LOCATOR_ROOT.joinpath("utm_compression_start_v1").mkdir(parents=True)
    module.LOCATOR_ROOT.joinpath("utm_compression_start_v1", "ready_state.png").write_bytes(TINY_PNG_BYTES)
    module._load_pyautogui = lambda: (_FakePyAutoGUI(), "")

    result = module._utm_readiness()

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "UTM_REQUIRED_LOCATORS_MISSING" in result["blockers"]
    assert result["required_locator_names"] == ["ready_state", "start_button", "running_state", "complete_state"]
    assert result["configured_locator_names"] == ["ready_state"]
    assert result["missing_required_locators"] == ["start_button", "running_state", "complete_state"]
    assert result["gates"]["required_locators_complete"] is False


def test_packaged_bridge_utm_readiness_ready_with_required_locators(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    module.LOCATOR_ROOT = tmp_path / "locators"
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.UTM_EXPORT_ROOT.mkdir(parents=True)
    locator_dir = module.LOCATOR_ROOT / "utm_compression_start_v1"
    locator_dir.mkdir(parents=True)
    for name in ("ready_state", "start_button", "running_state", "complete_state"):
        locator_dir.joinpath(f"{name}.png").write_bytes(TINY_PNG_BYTES)
    module.get_pyautogui = lambda: (_FakePyAutoGUI(), None)

    result = module._utm_readiness()

    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["blockers"] == []
    assert result["missing_required_locators"] == []
    assert result["gates"]["locator_count"] == 4
    assert result["gates"]["required_locators_complete"] is True


def test_install_bridge_readiness_endpoint_is_token_protected_and_reports_missing_locators(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "readiness-token"
    module.LOCATOR_ROOT = tmp_path / "locators"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module._load_pyautogui = lambda: (_FakePyAutoGUI(), "")
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        blocked_req = urllib.request.Request(base + "/readiness", headers={"X-Bridge-Token": "wrong"})
        try:
            urllib.request.urlopen(blocked_req, timeout=5)
            raise AssertionError("unauthorized readiness request unexpectedly succeeded")
        except Exception:
            pass

        good_req = urllib.request.Request(base + "/readiness", headers={"X-Bridge-Token": "readiness-token"})
        with urllib.request.urlopen(good_req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.TOKEN = ""

    assert payload["tool"] == "equipment.pyautogui.windows_readiness"
    assert payload["status"] == "blocked"
    assert "UTM_REQUIRED_LOCATORS_MISSING" in payload["blockers"]
    assert payload["gates"]["required_locator_names"] == ["ready_state", "start_button", "running_state", "complete_state"]




def _utm_locator_payload() -> dict[str, object]:
    return {
        "ready_state": {"image_path": "C:/ATR/locators/ready.png", "confidence": 0.8},
        "start_button": {"image_path": "C:/ATR/locators/start.png", "confidence": 0.8},
        "running_state": {"image_path": "C:/ATR/locators/running.png", "confidence": 0.8},
        "complete_state": {"image_path": "C:/ATR/locators/complete.png", "confidence": 0.8},
    }


def test_install_bridge_required_screen_assertions_execute_locator_sequence(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = True
    fake.save_csv_on_write = True
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._run_utm_protocol(
        "seq-required-screen",
        "utm_compression_start_v1",
        {
            "run_id": "run-required-screen",
            "specimen_id": "specimen-required-screen",
            "locators": _utm_locator_payload(),
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        },
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert fake.locate_calls
    assert any(item["step"].endswith("ASSERT_VISIBLE") and item["status"] == "ok" for item in result["step_trace"])
    assert any(item["step"].endswith("WAIT_UNTIL") and item["status"] == "ok" for item in result["step_trace"])
    screen_checks = {item["checkpoint"]: item for item in result["screen_checks"]}
    assert screen_checks["after_start"]["ok"] is True
    assert screen_checks["after_start"]["screenshot_artifact"]
    assert screen_checks["after_complete"]["ok"] is True
    assert screen_checks["after_complete"]["screenshot_artifact"]
    artifact_ids = {item["artifact_id"] for item in result["output_artifacts"] if item.get("kind") == "screen_png"}
    assert screen_checks["after_start"]["screenshot_artifact"] in artifact_ids
    assert screen_checks["after_complete"]["screenshot_artifact"] in artifact_ids


def test_packaged_bridge_required_screen_assertions_execute_locator_sequence(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = True
    fake.save_csv_on_write = True
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module.get_pyautogui = lambda: (fake, None)
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )

    result = module.execute_payload(
        {
            "sequence_id": "seq-packaged-required-screen",
            "program_id": "utm_compression_start_v1",
            "run_id": "run-packaged-required-screen",
            "specimen_id": "specimen-packaged-required-screen",
            "locators": _utm_locator_payload(),
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        },
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert fake.locate_calls
    assert any(item["step"].endswith("ASSERT_VISIBLE") and item["status"] == "ok" for item in result["step_trace"])
    assert any(item["step"].endswith("WAIT_UNTIL") and item["status"] == "ok" for item in result["step_trace"])
    screen_checks = {item["checkpoint"]: item for item in result["screen_checks"]}
    assert screen_checks["after_start"]["ok"] is True
    assert screen_checks["after_start"]["screenshot_artifact"]
    assert screen_checks["after_complete"]["ok"] is True
    assert screen_checks["after_complete"]["screenshot_artifact"]
    artifact_ids = {item["artifact_id"] for item in result["output_artifacts"] if item.get("kind") == "screen_png"}
    assert screen_checks["after_start"]["screenshot_artifact"] in artifact_ids
    assert screen_checks["after_complete"]["screenshot_artifact"] in artifact_ids


def _assert_failure_screen_evidence(result: dict[str, object], *, expect_running: bool = False, expect_complete: bool = False) -> None:
    assert result["ok"] is False
    artifacts = result.get("output_artifacts")
    assert isinstance(artifacts, list) and artifacts
    screen_artifact_ids = {item["artifact_id"] for item in artifacts if isinstance(item, dict) and item.get("kind") == "screen_png"}
    assert screen_artifact_ids
    checks = {item["checkpoint"]: item for item in result.get("screen_checks", []) if isinstance(item, dict)}
    assert checks["before_start"]["screenshot_artifact"] in screen_artifact_ids
    assert checks["failure"]["ok"] is False
    assert checks["failure"]["screenshot_artifact"] in screen_artifact_ids
    if expect_running:
        assert checks["after_start"]["screenshot_artifact"] in screen_artifact_ids
    if expect_complete:
        assert checks["after_complete"]["screenshot_artifact"] in screen_artifact_ids


def test_install_bridge_sequence_failure_preserves_screen_evidence(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = False
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._run_utm_protocol(
        "seq-fails-screen",
        "utm_compression_start_v1",
        {
            "run_id": "run-fails-screen",
            "specimen_id": "specimen-fails-screen",
            "locators": _utm_locator_payload(),
            "artifact_timeout_s": 0.1,
            "stable_for_sec": 0.01,
        },
    )

    assert result["failure_code"] == "UI_LOCATOR_NOT_FOUND"
    _assert_failure_screen_evidence(result)


def test_packaged_bridge_export_failure_preserves_transition_and_failure_evidence(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = True
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module.get_pyautogui = lambda: (fake, None)
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )

    result = module.execute_payload(
        {
            "sequence_id": "seq-export-fails",
            "program_id": "utm_compression_start_v1",
            "run_id": "run-export-fails",
            "specimen_id": "specimen-export-fails",
            "locators": _utm_locator_payload(),
            "manual_save_required_if_no_artifact": False,
            "artifact_timeout_s": 0.1,
            "stable_for_sec": 0.01,
        },
        config,
    )

    assert result["failure_code"] == "UTM_EXPORT_FILE_MISSING"
    assert result["cross_checks"]["save_export_responsibility_ok"] is False
    _assert_failure_screen_evidence(result, expect_running=True, expect_complete=True)


def test_install_bridge_manual_save_fallback_exports_parseable_csv(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    fake.save_csv_on_write = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._run_utm_protocol(
        "seq-manual",
        "utm_compression_start_v1",
        {
            "run_id": "run-manual",
            "specimen_id": "specimen-manual",
            "sequence": [{"action": "health"}, {"action": "screenshot", "checkpoint": "after_start"}],
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        },
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert result["data_acquisition"]["save_attempted_by_agent"] is True
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert result["output_artifacts"][0]["kind"] == "utm_csv"
    assert result["output_artifacts"][0]["artifact_id"] in module.ARTIFACT_INDEX
    assert ("ctrl", "s") in fake.hotkeys
    assert fake.writes and fake.writes[0].endswith("specimen-manual.csv")
    steps = [item["step"] for item in result["step_trace"]]
    assert "AUTO_SAVE_MISSING" in steps
    assert "MANUAL_SAVE_EXPORT" in steps


def test_packaged_bridge_manual_save_fallback_exports_parseable_csv(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.save_csv_on_write = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module.get_pyautogui = lambda: (fake, None)
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )

    result = module.execute_payload(
        {
            "sequence_id": "seq-packaged-manual",
            "program_id": "utm_compression_start_v1",
            "run_id": "run-packaged-manual",
            "specimen_id": "specimen-packaged-manual",
            "sequence": [{"action": "health"}, {"action": "screenshot", "checkpoint": "after_start"}],
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        },
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert result["cross_checks"]["data_parse_probe_ok"] is True
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert ("ctrl", "s") in fake.hotkeys
    assert fake.writes and fake.writes[0].endswith("specimen-packaged-manual.csv")
    status, pulled = module._get_artifact(result["output_artifacts"][0]["artifact_id"])
    assert status == 200
    assert pulled["content_base64"]


def test_windows_bridge_invalid_screenshot_blocks_verified_complete(tmp_path: Path) -> None:
    for loader, packaged in ((_load_helper_module, False), (_load_packaged_helper_module, True)):
        module = loader()
        fake = _FakeInvalidScreenshotPyAutoGUI()
        fake.save_csv_on_write = True
        module.UTM_EXPORT_ROOT = tmp_path / ("packaged_utm_exports" if packaged else "install_utm_exports")
        module.ARTIFACT_ROOT = tmp_path / ("packaged_artifacts" if packaged else "install_artifacts")
        module.ARTIFACT_INDEX.clear()
        payload = {
            "sequence_id": "seq-invalid-screen-packaged" if packaged else "seq-invalid-screen-install",
            "program_id": "utm_compression_start_v1",
            "run_id": "run-invalid-screen-packaged" if packaged else "run-invalid-screen-install",
            "specimen_id": "specimen-invalid-screen-packaged" if packaged else "specimen-invalid-screen-install",
            "sequence": [{"action": "health"}, {"action": "screenshot", "checkpoint": "after_start"}],
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        }
        if packaged:
            module.get_pyautogui = lambda: (fake, None)
            config = module.BridgeConfig(
                host="127.0.0.1",
                port=0,
                token="",
                token_header="X-Bridge-Token",
                artifact_dir=module.ARTIFACT_ROOT,
                reference_dir=tmp_path / "reference_images",
            )
            result = module.execute_payload(payload, config)
        else:
            module._load_pyautogui = lambda: (fake, "")
            result = module._run_utm_protocol(payload["sequence_id"], payload["program_id"], payload)

        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert result["failure_code"] == "UTM_SCREEN_EVIDENCE_FILES_REQUIRED"
        assert result["output_artifacts"][0]["kind"] == "utm_csv"
        checks = {item["checkpoint"]: item for item in result["screen_checks"]}
        assert checks["before_start"]["ok"] is False
        assert checks["after_start"]["ok"] is False
        assert checks["after_complete"]["ok"] is False
        assert any(item["step"] == "SCREEN_EVIDENCE" and item["status"] == "blocked" for item in result["step_trace"])
        assert any("invalid image signature" in str(item.get("detail", "")) for item in result["step_trace"])


def test_install_bridge_export_program_uses_export_save_method(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = True
    fake.save_csv_on_write = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._run_utm_protocol(
        "seq-export",
        "utm_export_csv_v1",
        {"run_id": "run-export", "specimen_id": "specimen-export", "artifact_timeout_s": 1.0, "stable_for_sec": 0.01},
    )

    assert result["ok"] is True
    assert result["status"] == "verified_complete"
    assert result["program_id"] == "utm_export_csv_v1"
    assert result["data_acquisition"]["save_method"] == "export_menu"
    assert any(item["step"] == "EXECUTE_EXPORT_MACRO" for item in result["step_trace"])
    assert ("ctrl", "s") in fake.hotkeys


def test_install_bridge_abort_program_does_not_wait_for_export(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._run_utm_protocol(
        "seq-abort",
        "utm_stop_or_abort_v1",
        {"run_id": "run-abort", "specimen_id": "specimen-abort", "artifact_timeout_s": 0.01, "stable_for_sec": 0.01},
    )

    assert result["ok"] is True
    assert result["status"] == "recovery_macro_dispatched"
    assert result["program_type"] == "utm_abort"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert result["data_acquisition"]["save_method"] == "not_applicable"
    assert any(item["step"].endswith("PRESS") and item["status"] == "ok" for item in result["step_trace"])
    assert any(item["step"] == "RECOVERY_ABORT_MACRO" for item in result["step_trace"])
    assert not any(item["step"] == "WAIT_FOR_EXPORT" for item in result["step_trace"])


def test_packaged_bridge_abort_program_does_not_wait_for_export(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module.get_pyautogui = lambda: (fake, None)
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )

    result = module.execute_payload(
        {
            "sequence_id": "seq-packaged-abort",
            "program_id": "utm_stop_or_abort_v1",
            "run_id": "run-packaged-abort",
            "specimen_id": "specimen-packaged-abort",
            "artifact_timeout_s": 0.01,
            "stable_for_sec": 0.01,
        },
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "recovery_macro_dispatched"
    assert result["program_type"] == "utm_abort"
    assert any(item["step"] == "RECOVERY_ABORT_MACRO" for item in result["step_trace"])
    assert not any(item["step"] == "WAIT_FOR_EXPORT" for item in result["step_trace"])


def test_install_bridge_focus_window_activates_configured_title() -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    window = _FakeWindow("Instron UTM Software - Compression")
    fake.windows_by_title["Instron UTM Software"] = [window]
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "target_window": "Instron UTM Software",
            "sequence": [{"action": "focus_window", "window": "main", "required": True}],
        },
        run_id="run-focus",
        specimen_id="specimen-focus",
        trace=trace,
    )

    assert result["ok"] is True
    assert window.activated is True
    assert trace[-1]["status"] == "ok"
    assert "Instron UTM Software" in trace[-1]["detail"]


def test_packaged_bridge_focus_window_activates_regex_title() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    window = _FakeWindow("Vendor UTM Controller - Running")
    fake.all_windows = [window]
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "target_window_regex": "UTM Controller",
            "sequence": [{"action": "focus_window", "window": "main", "required": True}],
        },
        run_id="run-focus-regex",
        specimen_id="specimen-focus-regex",
        trace=trace,
    )

    assert result["ok"] is True
    assert window.activated is True
    assert trace[-1]["status"] == "ok"
    assert "regex=UTM Controller" in trace[-1]["detail"]


def test_install_bridge_required_focus_blocks_when_window_missing() -> None:
    module = _load_helper_module()
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={
            "target_window": "Missing UTM Window",
            "sequence": [{"action": "focus_window", "window": "main", "required": True}],
        },
        run_id="run-focus-missing",
        specimen_id="specimen-focus-missing",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_WINDOW_NOT_FOUND"
    assert trace[-1]["status"] == "blocked"



def test_install_bridge_uia_locator_is_preferred_for_assert_and_click(monkeypatch) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_matches = False
    element = _FakeUiaElement()
    trace: list[dict[str, object]] = []

    def fake_find(locator, payload, program):
        assert locator["auto_id"] in {"readyStatus", "startButton"}
        return element, f"uia:auto_id={locator['auto_id']}"

    monkeypatch.setattr(module, "_find_uia_element", fake_find)
    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "target_window": "Instron UTM Software",
            "locators": {
                "ready_state": {"locator_backend": "uia", "auto_id": "readyStatus", "control_type": "Text"},
                "start_button": {"locator_backend": "uia", "auto_id": "startButton", "control_type": "Button"},
            },
            "sequence": [
                {"action": "assert_visible", "target": "ready_state", "required": True},
                {"action": "click", "target": "start_button", "required": True},
            ],
        },
        run_id="run-uia",
        specimen_id="specimen-uia",
        trace=trace,
    )

    assert result["ok"] is True
    assert element.clicked is True
    assert fake.locate_calls == []
    assert any("via uia" in str(item.get("detail")) for item in trace)


def test_packaged_bridge_uia_locator_blocks_when_required_and_missing(monkeypatch) -> None:
    module = _load_packaged_helper_module()
    trace: list[dict[str, object]] = []

    def fake_find(locator, payload, program):
        return None, "uia target not found"

    monkeypatch.setattr(module, "_find_uia_element", fake_find)
    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={
            "locators": {"ready_state": {"locator_backend": "uia", "auto_id": "missingReady", "control_type": "Text"}},
            "sequence": [{"action": "assert_visible", "target": "ready_state", "required": True}],
        },
        run_id="run-uia-missing",
        specimen_id="specimen-uia-missing",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UI_LOCATOR_NOT_FOUND"
    assert trace[-1]["status"] == "blocked"
    assert "uia target not found" in trace[-1]["detail"]




def _extract_index_script(html: str) -> str:
    assert "<script>" in html
    return html.split("<script>", 1)[1].split("</script>", 1)[0]


def _run_windows_gui_node_harness(tmp_path: Path, html: str, scenario: str, click_mode: str = "direct-live") -> dict[str, object]:
    script_path = tmp_path / f"windows_bridge_gui_{scenario}.js"
    script_path.write_text(_extract_index_script(html), encoding="utf-8")
    harness = tmp_path / f"windows_bridge_gui_harness_{scenario}.js"
    harness.write_text(
        """
const fs = require('fs');
const vm = require('vm');
const script = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];
const elements = new Map();
const fetchCalls = [];

function makeElement(id = '') {
  const childSpan = {textContent: '', className: '', dataset: {}, style: {}};
  const dotSpan = {textContent: '', className: 'dot', dataset: {}, style: {}};
  const element = {
    id,
    value: '',
    checked: false,
    disabled: false,
    className: '',
    textContent: '',
    innerHTML: '',
    dataset: {},
    style: {},
    children: [],
    listeners: {},
    appendChild(child) { this.children.push(child); return child; },
    prepend(child) { this.children.unshift(child); return child; },
    removeChild(child) { this.children = this.children.filter((item) => item !== child); return child; },
    addEventListener(type, callback) { this.listeners[type] = callback; },
    click() {
      const callback = this.listeners.click;
      if (typeof callback === 'function') return callback({target: this});
      return undefined;
    },
    querySelector(selector) {
      if (selector === 'span:last-child') return childSpan;
      if (selector === '.dot') return dotSpan;
      if (selector === 'span') return childSpan;
      return null;
    },
    querySelectorAll(_selector) { return []; },
  };
  return element;
}

function getElement(id) {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
}

const proxyElements = [];
for (const proxyClick of ['safePreflight', 'refreshEvidence', 'utmSim', 'utmLive', 'utmAbort']) {
  const proxy = makeElement(`proxy-${proxyClick}`);
  proxy.dataset.proxyClick = proxyClick;
  proxyElements.push(proxy);
}

const ids = [
  'token','output','trace','artifactTable','tileStatus','tilePyAutoGUI','tileFailure','tileArtifact','authPill','headerProofPill','sequence','log',
  'stepAuth','stepGui','stepProgram','stepEvidence','stepArtifact','runSummaryPill','summaryProgram','summaryRun','summaryData','summaryGate',
  'pathArtifactRoot','pathRequestLog','pathLocatorRoot','pathUtmExportRoot','preflightBanner','preflightTitle','preflightText','artifactPreview',
  'runId','specimenId','targetWindow','exportGlob','artifactTimeout','stableForSec','expectedExportPath','requireFocus','requireAssertions',
  'manualSave','confirmLive','locatorName','regionX','regionY','regionW','regionH','confidence','health','healthInline','healthTop',
  'safePreflight','preflightRefreshInline','programs','locators','readiness','program1','utmSim','utmLive','utmAbort','screenshot','artifacts','requestLog',
  'refreshEvidence','refreshAll','autoAudit','captureLocator','execute','fillUtmJson','copyUtmPayload','formatJson','clearResult','copyResult','copyBase','copyLinuxEnv','clearToken',
  'baseUrlLabel','gateMeterFill','gateMeterText','gateMeterNext','liveInterlockCard','liveInterlockText',
  'operatorHud','opsSafety','opsCommand','opsEvidence','opsData','opsNext',
  'operatorConsolePanel','payloadPreviewPill','payloadPreview','intentMode','intentRoute','intentPreflight','intentPayload',
  'timelinePanel','timelinePill','timelineTrack','timelineClear',
  'operatorSituationPanel','situationBridge','situationLocators','situationAudit','situationExport','situationLive',
  'missingLocatorShortcuts','requestAuditRunIds','requestAuditSpecimenIds','requestAuditProgramIds','requestAuditLastAt',
  'previewSimPayload','previewLivePayload','previewAbortPayload','copyPreviewPayload'
];
ids.forEach(getElement);
getElement('runId').value = 'utm-test-run';
getElement('specimenId').value = 'specimen-001';
getElement('exportGlob').value = '*.csv';
getElement('artifactTimeout').value = '20';
getElement('stableForSec').value = '2.0';
getElement('requireFocus').checked = true;
getElement('manualSave').checked = true;
getElement('confirmLive').checked = true;
getElement('sequence').value = '{"sequence_id":"manual-check-001","sequence":[{"action":"health"}]}';

const responses = {
  blocked: {
    '/health': {ok: true, status: 'ready', tool: 'equipment.pyautogui.health', bridge: 'windows_pyautogui', pyautogui: {available: false}, artifacts: {request_log: 'bridge_requests.jsonl'}},
    '/readiness': {ok: false, status: 'blocked', tool: 'equipment.pyautogui.windows_readiness', gates: {required_locator_names: ['ready_state'], configured_locator_names: [], missing_required_locators: ['ready_state']}},
    '/request-log': {ok: true, status: 'ready', tool: 'equipment.pyautogui.request_log', request_log: 'bridge_requests.jsonl', event_count: 1, recent_paths: ['/health'], execute_event_seen: false, execute_event_count: 0},
  },
  ready: {
    '/health': {ok: true, status: 'ready', tool: 'equipment.pyautogui.health', bridge: 'windows_pyautogui', pyautogui: {available: true}, artifacts: {request_log: 'bridge_requests.jsonl'}},
    '/readiness': {ok: true, status: 'ready', tool: 'equipment.pyautogui.windows_readiness', gates: {required_locator_names: ['ready_state'], configured_locator_names: ['ready_state'], missing_required_locators: []}},
    '/request-log': {ok: true, status: 'ready', tool: 'equipment.pyautogui.request_log', request_log: 'bridge_requests.jsonl', event_count: 1, recent_paths: ['/health'], execute_event_seen: false, execute_event_count: 0},
    '/execute': {
      ok: true,
      status: 'verified_complete',
      bridge: 'windows_pyautogui',
      program_id: 'utm_compression_start_v1',
      result_file: 'C:/ATR/utm_exports/utm-test-run/specimen-001.csv',
      data_acquisition: {
        status: 'exported_on_windows',
        save_method: 'windows_export_watch',
        save_attempted_by_agent: true,
        save_confirmation_screen_ok: true,
        windows_path: 'C:/ATR/utm_exports/utm-test-run/specimen-001.csv',
        row_count_probe: 80,
      },
      cross_checks: {data_parse_probe_ok: true, save_export_responsibility_ok: true},
      step_trace: [{step: 'SAVE_EXPORT', status: 'ok'}, {step: 'DONE', status: 'ok'}]
    },
  },
};

const localStorageData = new Map();
global.document = {
  hidden: false,
  getElementById: getElement,
  createElement: (tag) => makeElement(tag),
  querySelectorAll: (selector) => {
    if (selector === 'button') return ids.map(getElement).concat(proxyElements);
    if (selector === '[data-proxy-click]') return proxyElements;
    return [];
  },
};
global.localStorage = {
  getItem: (key) => localStorageData.has(key) ? localStorageData.get(key) : null,
  setItem: (key, value) => { localStorageData.set(key, String(value)); },
  removeItem: (key) => { localStorageData.delete(key); },
};
global.navigator = {clipboard: {writeText: async () => {}}};
global.window = {location: {origin: 'http://127.0.0.1:8765'}};
global.Headers = class HeadersMock {
  constructor() { this.values = {}; }
  set(key, value) { this.values[key] = value; }
};
global.fetch = async (path, options = {}) => {
  fetchCalls.push({path, method: options.method || 'GET', body: options.body || ''});
  const payload = (responses[scenario] && responses[scenario][path]) || {ok: false, status: 'missing_mock', path};
  return {status: payload.ok === false ? 400 : 200, json: async () => payload};
};
global.setInterval = () => 1;
global.clearInterval = () => {};

(async () => {
  vm.runInThisContext(script, {filename: 'windows_bridge_gui_under_test.js'});
  await new Promise((resolve) => setImmediate(resolve));
  fetchCalls.length = 0;
  const clickMode = process.argv[4] || 'direct-live';
  let clickTarget = getElement('utmLive');
  if (clickMode === 'proxy-live') clickTarget = proxyElements.find((item) => item.dataset.proxyClick === 'utmLive');
  if (clickMode === 'proxy-preflight') clickTarget = proxyElements.find((item) => item.dataset.proxyClick === 'safePreflight');
  if (clickMode === 'proxy-abort') clickTarget = proxyElements.find((item) => item.dataset.proxyClick === 'utmAbort');
  if (clickMode === 'live-invalid') {
    getElement('artifactTimeout').value = '0';
    clickTarget = getElement('utmLive');
  }
  const click = clickTarget && clickTarget.listeners.click;
  if (typeof click !== 'function') throw new Error(`${clickMode} click listener missing`);
  await click({target: clickTarget});
  await new Promise((resolve) => setImmediate(resolve));
  const outputText = getElement('output').textContent || '{}';
  let output = {};
  try { output = JSON.parse(outputText); } catch (_err) { output = {parse_error: outputText}; }
  console.log(JSON.stringify({
    paths: fetchCalls.map((item) => item.path),
    executeCalls: fetchCalls.filter((item) => item.path === '/execute'),
    output,
    preflightTitle: getElement('preflightTitle').textContent,
    preflightText: getElement('preflightText').textContent,
  }));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(harness), str(script_path), scenario, click_mode],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_windows_bridge_index_html_combines_operator_console_and_program_manager() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        for element_id in (
            'id="connectionPanel"',
            'id="token"',
            'id="health"',
            'id="programManagerPanel"',
            'id="managerProgramRegistry"',
            'id="refreshPrograms"',
            'id="managerSearch"',
            'id="managerFilter"',
            'id="managerStats"',
            'id="newProgram"',
            'id="browseProgram"',
            'id="downloadProgramTemplate"',
            'id="programFile"',
            'id="programEditor"',
            'id="programForm"',
            'id="programDefinition"',
            'id="validateProgram"',
            'id="registerProgram"',
            'id="managerLatestResult"',
        ):
            assert element_id in html
        assert "Bridge Connection" in html
        assert "Program Manager" in html
        assert "Browse JSON" in html
        assert "Download Template" in html
        assert "Add to Registry" in html
        assert 'data-manager-action="edit"' in html
        assert 'data-manager-action="toggle"' in html
        assert 'data-manager-action="revalidate"' in html
        assert "atr.windowsBridge.programShortcuts.v1" not in html
        assert 'call("/programs"' in html
        assert 'call("/execute"' in html
        assert 'call("/programs/register"' in html
        assert 'call("/programs/validate"' in html
        assert "storage: \"browser_local_only\"" not in html
        assert "UTM Protocol" in html
        assert "Live Proof Checklist" in html
        assert "Run Timeline" in html


def test_windows_bridge_console_simplification_keeps_all_operator_functions() -> None:
    """The Program Manager is additive; it must not replace the full console."""
    legacy_control_ids = (
        'id="safePreflight"',
        'id="utmSim"',
        'id="utmLive"',
        'id="utmAbort"',
        'id="screenshot"',
        'id="captureLocator"',
        'id="locators"',
        'id="artifacts"',
        'id="requestLog"',
        'id="execute"',
        'id="sequence"',
        'id="trace"',
        'id="artifactPreview"',
        'id="timelineTrack"',
    )
    manager_control_ids = (
        'id="programManagerPanel"',
        'id="managerSearch"',
        'id="managerFilter"',
        'id="newProgram"',
        'id="browseProgram"',
        'id="downloadProgramTemplate"',
        'id="programEditor"',
    )

    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        for element_id in legacy_control_ids + manager_control_ids:
            assert element_id in html
        assert "UTM Protocol" in html
        assert "Live Proof Checklist" in html
        assert "Run Timeline" in html
        assert "Program Manager" in html


def test_windows_bridge_console_defaults_to_essential_operator_surface() -> None:
    essential_ids = (
        'id="essentialConsole"',
        'id="token"',
        'id="health"',
        'id="refreshAll"',
        'id="clearToken"',
        'id="essentialBridgeState"',
        'id="essentialPyAutoGUI"',
        'id="essentialResult"',
        'id="essentialProgramManagerSlot"',
        'id="advancedToolsPanel"',
    )
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        for element_id in essential_ids:
            assert element_id in html
        assert 'data-proxy-click=' not in html
        assert '<details id="advancedToolsPanel">' in html
        assert 'essentialProgramManagerSlot.appendChild(programManagerPanel)' in html
        assert "function renderEssentialSummary(data)" in html


def test_windows_bridge_program_editor_opens_only_for_add_or_edit() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        assert 'class="manager-editor" id="programEditor" hidden' in html
        assert "programEditor.hidden = false" in html
        assert "programEditor.hidden = true" in html


def test_windows_bridge_custom_macro_registry_persists_and_executes(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.PROGRAM_ROOT = tmp_path / "programs"
    definition = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "fixture_prepare",
        "name": "Fixture Prepare",
        "description": "Bounded fixture preparation macro",
        "enabled": True,
        "program_type": "macro",
        "sequence": [
            {"action": "press", "key": "esc"},
            {"action": "log", "message": "fixture ready"},
        ],
    }

    validation = module._validate_program_definition(definition)
    assert validation["ok"] is True

    registered = module._register_program_definition(definition)
    assert registered["ok"] is True
    assert (module.PROGRAM_ROOT / "fixture_prepare.json").exists()
    assert module._all_programs()["fixture_prepare"]["sequence"] == definition["sequence"]

    fake = _FakePyAutoGUI()
    module.get_pyautogui = lambda: (fake, None)
    result = module._execute({"sequence_id": "fixture-check", "program_id": "fixture_prepare"})
    assert result["ok"] is True
    assert result["program_id"] == "fixture_prepare"

    deleted = module._delete_custom_program("fixture_prepare")
    assert deleted["ok"] is True
    assert "fixture_prepare" not in module._all_programs()


def test_windows_bridge_custom_macro_registry_rejects_unsafe_or_builtin_definitions(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.PROGRAM_ROOT = tmp_path / "programs"

    builtin = module._validate_program_definition({
        "schema": "atr.pyautogui_program.v1",
        "program_id": "program1",
        "name": "Overwrite Program1",
        "sequence": [{"action": "press", "key": "esc"}],
    })
    unsafe = module._validate_program_definition({
        "schema": "atr.pyautogui_program.v1",
        "program_id": "unsafe_shell",
        "name": "Unsafe Shell",
        "sequence": [{"action": "shell", "command": "whoami"}],
    })

    assert builtin["ok"] is False
    assert builtin["failure_code"] == "PYAUTOGUI_PROGRAM_BUILTIN_IMMUTABLE"
    assert unsafe["ok"] is False
    assert unsafe["failure_code"] == "PYAUTOGUI_ACTION_NOT_ALLOWED"
    assert not module.PROGRAM_ROOT.exists()


def test_windows_bridge_setup_surface_separates_browse_template_and_registration() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        assert 'id="newProgram"' in html
        assert 'id="browseProgram"' in html
        assert 'id="downloadProgramTemplate"' in html
        assert 'id="validateProgram"' in html
        assert 'id="registerProgram"' in html
        assert 'Browse JSON' in html
        assert 'Download Template' in html
        assert 'Add to Registry' in html
        assert 'call("/programs/validate"' in html
        assert 'call("/programs/register"' in html
        assert 'atr.windowsBridge.programShortcuts.v1' not in html
        assert 'data-proxy-click="program1"' not in html
        assert 'data-proxy-click="utmSim"' not in html
        assert 'data-proxy-click="utmLive"' not in html
        assert 'data-proxy-click="utmAbort"' not in html
        assert 'id="program1"' not in html


def test_program_manager_exposes_examples_without_implicit_registration() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        assert 'data-manager-tab="examples"' in html
        assert 'id="managerExamplesView"' in html
        assert 'id="openCapabilityLab"' in html
        assert 'id="refreshExamples"' in html
        assert 'id="exampleRegistry"' in html
        assert 'id="recordingCoverage"' in html
        assert 'id="recordImageTracking"' in html
        assert 'id="recordCoordinateFallback"' in html
        assert 'id="recordingLocatorPreview"' in html
        assert 'call("/examples"' in html
        assert 'data-load-example' in html
        assert 'data-run-example' in html
        assert "loadExampleIntoEditor" in html
        assert "registerProgramDefinition(example" not in html
    assert "program_id:example.program.program_id" not in html


def test_source_and_install_helpers_load_the_same_example_catalog() -> None:
    source_module = _load_packaged_helper_module()
    install_module = _load_helper_module()

    source_examples = source_module._load_example_catalog()
    install_examples = install_module._load_example_catalog()

    assert len(source_examples) == 8
    assert [item["example_id"] for item in install_examples] == [
        item["example_id"] for item in source_examples
    ]


def test_windows_bridge_program_registry_http_lifecycle(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "registry-token"
    module.PROGRAM_ROOT = tmp_path / "programs"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    definition = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "http_fixture_macro",
        "name": "HTTP Fixture Macro",
        "description": "HTTP lifecycle fixture",
        "enabled": True,
        "program_type": "macro",
        "sequence": [{"action": "log", "message": "fixture"}],
    }

    def request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"X-Bridge-Token": "registry-token"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        validation = request("/programs/validate", method="POST", payload=definition)
        assert validation["ok"] is True
        assert not module.PROGRAM_ROOT.exists(), "validation must not persist a program"

        registered = request("/programs/register", method="POST", payload=definition)
        assert registered["status"] == "registered"
        programs = request("/programs")
        assert any(item["program_id"] == "http_fixture_macro" and item["built_in"] is False for item in programs["programs"])

        deleted = request("/programs/http_fixture_macro", method="DELETE")
        assert deleted["status"] == "deleted"
        assert not (module.PROGRAM_ROOT / "http_fixture_macro.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)











def test_install_bridge_request_audit_log_records_auth_without_token_leak(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "audit-token"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            assert response.status == 200

        bad_req = urllib.request.Request(base + "/health", headers={"X-Bridge-Token": "wrong-token"})
        try:
            urllib.request.urlopen(bad_req, timeout=5)
        except Exception:
            pass

        good_req = urllib.request.Request(base + "/health", headers={"X-Bridge-Token": "audit-token"})
        with urllib.request.urlopen(good_req, timeout=5) as response:
            assert response.status == 200

        execute_payload = {"sequence_id": "seq-audit", "run_id": "run-audit", "specimen_id": "specimen-audit", "program_id": "program1", "command": "program1"}
        execute_req = urllib.request.Request(
            base + "/execute",
            data=json.dumps(execute_payload).encode("utf-8"),
            headers={"X-Bridge-Token": "audit-token", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(execute_req, timeout=5) as response:
            assert response.status == 200

        log_req = urllib.request.Request(base + "/request-log", headers={"X-Bridge-Token": "audit-token"})
        with urllib.request.urlopen(log_req, timeout=5) as response:
            log_payload = json.loads(response.read().decode("utf-8"))
        assert log_payload["ok"] is True
        assert log_payload["event_count"] >= 1
        assert log_payload["request_log"].endswith("bridge_requests.jsonl")
        assert log_payload["execute_event_seen"] is True
        assert log_payload["execute_event_count"] >= 2
        assert log_payload["execute_payload_event_count"] == 1
        assert log_payload["execute_result_event_count"] == 1
        assert log_payload["execute_run_ids"] == ["run-audit"]
        assert log_payload["execute_sequence_ids"] == ["seq-audit"]
        assert log_payload["execute_specimen_ids"] == ["specimen-audit"]
        assert log_payload["execute_program_ids"] == ["program1"]
        assert log_payload["last_execute_context"]["run_id"] == "run-audit"
        assert log_payload["recent_paths"][-1] == "/request-log"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.TOKEN = ""

    log_path = module.ARTIFACT_ROOT / "bridge_requests.jsonl"
    assert log_path.exists()
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [event["path"] for event in events] == ["/", "/health", "/health", "/execute", "/execute", "/execute", "/request-log"]
    assert events[0]["auth_ok"] is None
    assert events[1]["auth_ok"] is False
    assert events[2]["auth_ok"] is True
    assert events[3]["status"] == "authorized"
    assert events[4]["audit_kind"] == "execute_payload"
    assert events[4]["run_id"] == "run-audit"
    assert events[5]["audit_kind"] == "execute_result"
    assert events[6]["auth_ok"] is True
    assert "audit-token" not in log_path.read_text(encoding="utf-8")
    assert "wrong-token" not in log_path.read_text(encoding="utf-8")

def test_install_bridge_root_serves_complete_program_console() -> None:
    module = _load_helper_module()
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "ATR Windows PyAutoGUI Bridge" in body
        assert 'id="connectionPanel"' in body
        assert 'id="programManagerPanel"' in body
        assert 'id="programEditor"' in body
        assert 'id="utmLive"' in body
        assert 'id="program1"' not in body
        assert any(program["program_id"] == "program1" for program in module._programs()["programs"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_packaged_bridge_request_log_endpoint_records_auth_without_token_leak(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    config = module.BridgeConfig(
        host="127.0.0.1",
        port=0,
        token="packaged-audit-token",
        token_header="X-Bridge-Token",
        artifact_dir=tmp_path / "artifacts",
        reference_dir=tmp_path / "reference_images",
    )
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    server = module.BridgeHTTPServer(("127.0.0.1", 0), module.BridgeRequestHandler, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        bad_req = urllib.request.Request(base + "/health", headers={"X-Bridge-Token": "wrong-token"})
        try:
            urllib.request.urlopen(bad_req, timeout=5)
        except Exception:
            pass

        execute_payload = {"sequence_id": "seq-packaged", "run_id": "run-packaged", "specimen_id": "specimen-packaged", "program_id": "program1", "command": "program1"}
        execute_req = urllib.request.Request(
            base + "/execute",
            data=json.dumps(execute_payload).encode("utf-8"),
            headers={"X-Bridge-Token": "packaged-audit-token", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(execute_req, timeout=5) as response:
            assert response.status == 200

        good_req = urllib.request.Request(base + "/request-log", headers={"X-Bridge-Token": "packaged-audit-token"})
        with urllib.request.urlopen(good_req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert payload["ok"] is True
    assert payload["request_log"].endswith("bridge_requests.jsonl")
    assert payload["execute_event_seen"] is True
    assert payload["execute_event_count"] >= 2
    assert payload["execute_payload_event_count"] == 1
    assert payload["execute_result_event_count"] == 1
    assert payload["execute_run_ids"] == ["run-packaged"]
    assert payload["execute_sequence_ids"] == ["seq-packaged"]
    assert payload["execute_specimen_ids"] == ["specimen-packaged"]
    assert payload["execute_program_ids"] == ["program1"]
    assert payload["recent_paths"][-1] == "/request-log"
    assert [event["path"] for event in payload["events"]] == ["/health", "/execute", "/execute", "/execute", "/request-log"]
    assert payload["events"][0]["auth_ok"] is False
    assert payload["events"][1]["status"] == "authorized"
    assert payload["events"][2]["audit_kind"] == "execute_payload"
    assert payload["events"][3]["audit_kind"] == "execute_result"
    log_text = (config.artifact_dir / "bridge_requests.jsonl").read_text(encoding="utf-8")
    assert "packaged-audit-token" not in log_text
    assert "wrong-token" not in log_text


def test_install_bridge_execute_sequence_supports_screenshot_action(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    trace: list[dict[str, object]] = []
    screen_artifacts: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={"sequence": [{"action": "screenshot", "checkpoint": "pre_start", "required": True}]},
        run_id="run-screen-action",
        specimen_id="specimen-screen-action",
        trace=trace,
        screen_artifacts=screen_artifacts,
    )

    assert result["ok"] is True
    assert fake.screenshot_regions == [None]
    assert screen_artifacts and screen_artifacts[0]["kind"] == "screen_png"
    assert Path(str(module.ARTIFACT_INDEX[screen_artifacts[0]["artifact_id"]]["path"])).exists()
    assert any(item["step"] == "SCREENSHOT_PRE_START" and item["status"] == "ok" for item in trace)
    assert any(item["step"] == "SEQ_1_SCREENSHOT" and item["status"] == "ok" for item in trace)


def test_packaged_bridge_execute_sequence_supports_locate_image_aliases() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_match_paths = {"ready.png", "running.png"}
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "locators": {
                "ready_state": {"image_path": "ready.png"},
                "running_state": {"image_path": "running.png"},
            },
            "sequence": [
                {"action": "locate_image", "target": "ready_state", "required": True},
                {"action": "wait_until_image", "target": "running_state", "timeout_s": 0.1, "required": True},
            ],
        },
        run_id="run-image-alias",
        specimen_id="specimen-image-alias",
        trace=trace,
    )

    assert result["ok"] is True
    assert [call[0] for call in fake.locate_calls] == ["ready.png", "running.png"]
    assert any(item["step"] == "SEQ_1_LOCATE_IMAGE" and item["status"] == "ok" for item in trace)
    assert any(item["step"] == "SEQ_2_WAIT_UNTIL_IMAGE" and item["status"] == "ok" for item in trace)


def test_install_bridge_required_locator_names_include_image_action_aliases() -> None:
    module = _load_helper_module()

    names = module._required_utm_locator_names(
        "utm_compression_start_v1",
        {
            "sequence": [
                {"action": "locate_image", "target": "ready_state"},
                {"action": "wait_until_image", "target": "running_state"},
                {"action": "screenshot", "checkpoint": "before_start"},
            ]
        },
    )

    assert names == ["ready_state", "running_state"]


def test_install_bridge_execute_runs_custom_sequence_from_gui_json(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._execute(
        {
            "sequence_id": "json-seq-001",
            "run_id": "run-json-seq",
            "specimen_id": "specimen-json-seq",
            "sequence": [{"action": "screenshot", "checkpoint": "manual", "required": True}],
        }
    )

    assert result["ok"] is True
    assert result["program_id"] == "custom_sequence"
    assert result["program_type"] == "operator_sequence"
    assert fake.screenshot_regions == [None]
    assert result["output_artifacts"] and result["output_artifacts"][0]["kind"] == "screen_png"
    assert any(item["step"] == "SEQ_1_SCREENSHOT" and item["status"] == "ok" for item in result["step_trace"])
    assert result["step_trace"][-1] == {"step": "DONE", "status": "ok", "detail": "custom sequence completed"}


def test_install_bridge_rejects_unsupported_custom_sequence_action(tmp_path: Path) -> None:
    module = _load_helper_module()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")

    result = module._execute(
        {
            "sequence_id": "json-seq-unsupported",
            "sequence": [{"action": "shell", "cmd": "dir"}],
        }
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["program_id"] == "custom_sequence"
    assert result["failure_code"] == "PYAUTOGUI_ACTION_NOT_ALLOWED"
    assert result["step_trace"][-1]["status"] == "blocked"
    assert "unsupported action: shell" in result["step_trace"][-1]["detail"]


def test_packaged_bridge_execute_runs_custom_sequence_without_program_id() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    fake.locate_match_paths = {"ready.png"}
    module._load_pyautogui = lambda: (fake, "")

    result = module._execute(
        {
            "sequence_id": "json-seq-packaged-001",
            "locators": {"ready_state": {"image_path": "ready.png"}},
            "sequence": [{"action": "locate_image", "target": "ready_state", "required": True}],
        }
    )

    assert result["ok"] is True
    assert result["program_id"] == "custom_sequence"
    assert [call[0] for call in fake.locate_calls] == ["ready.png"]
    assert any(item["step"] == "SEQ_1_LOCATE_IMAGE" and item["status"] == "ok" for item in result["step_trace"])








def test_packaged_bridge_rejects_unsupported_custom_sequence_action() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    module._load_pyautogui = lambda: (fake, "")

    result = module._execute(
        {
            "sequence_id": "json-seq-packaged-unsupported",
            "sequence": [{"action": "shell", "cmd": "dir"}],
        }
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["program_id"] == "custom_sequence"
    assert result["failure_code"] == "PYAUTOGUI_ACTION_NOT_ALLOWED"
    assert result["step_trace"][-1]["status"] == "blocked"
    assert "unsupported action: shell" in result["step_trace"][-1]["detail"]


def test_install_bridge_click_retry_captures_screenshot_before_second_locator_attempt(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()

    class _RetryPyAutoGUI(_FakePyAutoGUI):
        def locateOnScreen(self, image_path: str, **kwargs: object) -> object | None:  # noqa: N802
            self.locate_calls.append((image_path, dict(kwargs)))
            if len(self.locate_calls) >= 2:
                return _FakeBox()
            return None

    fake = _RetryPyAutoGUI()
    trace: list[dict[str, object]] = []
    screen_artifacts: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "locators": {"start_button": {"image_path": "start.png"}},
            "sequence": [{"action": "click", "target": "start_button", "required": True}],
        },
        run_id="run-click-retry",
        specimen_id="specimen-click-retry",
        trace=trace,
        screen_artifacts=screen_artifacts,
    )

    assert result["ok"] is True
    assert [call[0] for call in fake.locate_calls] == ["start.png", "start.png"]
    assert fake.screenshot_regions == [None]
    assert fake.clicks == [(1, 1)]
    assert screen_artifacts and "retry_before_start_button" in screen_artifacts[0]["artifact_id"]
    assert any(item["step"] == "SEQ_1_CLICK_RETRY_SCREENSHOT" and item["status"] == "ok" for item in trace)
    assert any(item["step"] == "SEQ_1_CLICK_RETRY_LOCATE" and item["status"] == "ok" for item in trace)


def test_packaged_bridge_click_retry_remains_single_retry_on_required_missing_locator(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    module.REQUIRE_UTM_SCREEN_ASSERTIONS = True
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    fake = _FakePyAutoGUI()
    trace: list[dict[str, object]] = []
    screen_artifacts: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "locators": {"start_button": {"image_path": "start.png"}},
            "sequence": [{"action": "click", "target": "start_button", "required": True}],
        },
        run_id="run-click-retry-fail",
        specimen_id="specimen-click-retry-fail",
        trace=trace,
        screen_artifacts=screen_artifacts,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UI_LOCATOR_NOT_FOUND"
    assert [call[0] for call in fake.locate_calls] == ["start.png", "start.png"]
    assert fake.screenshot_regions == [None]
    assert not fake.clicks
    assert screen_artifacts and "retry_before_start_button" in screen_artifacts[0]["artifact_id"]
    assert any(item["step"] == "SEQ_1_CLICK_RETRY_LOCATE" and item["status"] == "blocked" for item in trace)


def test_install_bridge_coordinate_click_records_screen_dpi_window_and_hash_evidence(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    fake = _FakePyAutoGUI()
    window = _FakeWindow("Instron UTM Software")
    window.left = 10
    window.top = 20
    window.width = 800
    window.height = 600
    fake.windows_by_title["Instron UTM Software"] = [window]
    trace: list[dict[str, object]] = []
    screen_artifacts: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={
            "target_window": "Instron UTM Software",
            "dpi_scaling": "125%",
            "sequence": [{"action": "click", "target": "start_button", "x": 320, "y": 240}],
        },
        run_id="run-coordinate-evidence",
        specimen_id="specimen-coordinate-evidence",
        trace=trace,
        screen_artifacts=screen_artifacts,
    )

    assert result["ok"] is True
    assert fake.clicks == [(320, 240)]
    assert fake.screenshot_regions == [None, None]
    assert len(screen_artifacts) == 2
    step = next(item for item in trace if item["step"] == "SEQ_1_CLICK")
    detail = str(step["detail"])
    assert "coordinate=(320,240)" in detail
    assert "screen_size=1920x1080" in detail
    assert "dpi_scaling=125%" in detail
    assert "target_window_rect=10,20,800,600" in detail
    assert "before_sha256=" in detail
    assert "after_sha256=" in detail
    assert any(item["step"] == "SEQ_1_CLICK_COORDINATE_BEFORE_SCREENSHOT" and item["status"] == "ok" for item in trace)
    assert any(item["step"] == "SEQ_1_CLICK_COORDINATE_AFTER_SCREENSHOT" and item["status"] == "ok" for item in trace)


def test_packaged_bridge_coordinate_click_records_unknown_window_rect_when_unavailable(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    fake = _FakePyAutoGUI()
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_compression_start_v1",
        payload={"sequence": [{"action": "click", "target": "fallback", "x": 10, "y": 20}]},
        run_id="run-coordinate-unknown",
        specimen_id="specimen-coordinate-unknown",
        trace=trace,
    )

    assert result["ok"] is True
    step = next(item for item in trace if item["step"] == "SEQ_1_CLICK")
    detail = str(step["detail"])
    assert "coordinate=(10,20)" in detail
    assert "screen_size=1920x1080" in detail
    assert "dpi_scaling=unknown" in detail
    assert "target_window_rect=unknown" in detail


def test_install_bridge_wait_for_file_action_checks_stable_file(tmp_path: Path) -> None:
    module = _load_helper_module()
    export_path = tmp_path / "run-wait" / "specimen-wait.csv"
    export_path.parent.mkdir(parents=True)
    export_path.write_text("time_s,displacement_mm,force_N\n0,0,0\n", encoding="utf-8")
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={
            "sequence": [
                {
                    "action": "wait_for_file",
                    "pattern": str(export_path),
                    "timeout_s": 0.6,
                    "stable_for_sec": 0.01,
                    "required": True,
                }
            ]
        },
        run_id="run-wait",
        specimen_id="specimen-wait",
        trace=trace,
    )

    assert result["ok"] is True
    assert trace[-1]["step"] == "SEQ_1_WAIT_FOR_FILE"
    assert trace[-1]["status"] == "ok"
    assert str(export_path) in str(trace[-1]["detail"])
    assert "stable_for_sec=0.01" in str(trace[-1]["detail"])


def test_packaged_bridge_wait_for_file_required_blocks_when_missing(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    missing_path = tmp_path / "missing" / "specimen.csv"
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={
            "sequence": [
                {
                    "action": "wait_for_file",
                    "pattern": str(missing_path),
                    "timeout_s": 0.01,
                    "stable_for_sec": 0.01,
                    "required": True,
                }
            ]
        },
        run_id="run-wait-missing",
        specimen_id="specimen-wait-missing",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_DATA_TIMEOUT"
    assert trace[-1]["step"] == "SEQ_1_WAIT_FOR_FILE"
    assert trace[-1]["status"] == "blocked"
    assert str(missing_path) in str(trace[-1]["detail"])


def test_install_bridge_wait_for_file_optional_warns_and_allows_manual_fallback(tmp_path: Path) -> None:
    module = _load_helper_module()
    missing_path = tmp_path / "missing" / "optional.csv"
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="utm_compression_start_v1",
        payload={
            "sequence": [
                {
                    "action": "wait_for_file",
                    "pattern": str(missing_path),
                    "timeout_s": 0.01,
                    "stable_for_sec": 0.01,
                }
            ]
        },
        run_id="run-wait-optional",
        specimen_id="specimen-wait-optional",
        trace=trace,
    )

    assert result["ok"] is True
    assert trace[-1]["step"] == "SEQ_1_WAIT_FOR_FILE"
    assert trace[-1]["status"] == "warning"


def test_windows_bridge_probe_rejects_no_force_signal(tmp_path: Path) -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        path = tmp_path / f"{module.__name__}_zero_force.csv"
        path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,0.0\n2,0.2,0.0\n", encoding="utf-8")

        result = module._probe_utm_csv(path)

        assert result["ok"] is False
        assert result["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
        assert result["data_quality"]["force_nonzero"] is False
        assert result["data_quality"]["displacement_changes"] is True


def test_windows_bridge_probe_rejects_flat_displacement_signal(tmp_path: Path) -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        path = tmp_path / f"{module.__name__}_flat_displacement.csv"
        path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.0,1.2\n2,0.0,2.4\n", encoding="utf-8")

        result = module._probe_utm_csv(path)

        assert result["ok"] is False
        assert result["failure_code"] == "UTM_DATA_NO_DISPLACEMENT_SIGNAL"
        assert result["data_quality"]["force_nonzero"] is True
        assert result["data_quality"]["displacement_changes"] is False


def test_windows_bridge_probe_accepts_monotonic_negative_displacement(tmp_path: Path) -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        path = tmp_path / f"{module.__name__}_negative_displacement.csv"
        path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,-0.1,1.2\n2,-0.2,2.4\n", encoding="utf-8")

        result = module._probe_utm_csv(path)

        assert result["ok"] is True
        assert result["data_quality"]["displacement_monotonic"] is True
        assert result["data_quality"]["displacement_direction"] == "decreasing"
        assert result["data_quality"]["force_changes"] is True


def test_recording_manager_persists_redacted_events_and_checkpoint(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    fake = _FakePyAutoGUI()

    started = manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")
    manager.record_event({"kind": "key_press", "key": "a", "text": "secret-value"})
    manager.record_event({"kind": "mouse_click", "x": 20, "y": 30, "button": "left"})
    checkpoint = manager.checkpoint(label="Program completed", pyautogui=fake)
    stopped = manager.stop()
    saved = manager.save(started["recording_id"])

    assert checkpoint["ok"] is True
    assert stopped["status"] == "completed"
    assert saved["status"] == "saved"
    assert saved["events"][0] == {"kind": "key_press", "key": "a", "at_ms": saved["events"][0]["at_ms"]}
    assert "text" not in saved["events"][0]
    assert saved["checkpoints"][0]["sha256"]
    assert (tmp_path / started["recording_id"] / "recording.json").exists()


def test_recording_manager_fails_closed_when_listener_dependency_is_missing(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()

    def missing_listener_dependency(_manager: object) -> list[object]:
        raise ModuleNotFoundError("No module named 'pynput'")

    manager = module.RecordingManager(tmp_path, listener_factory=missing_listener_dependency)
    result = manager.start(name="recording", target_app="UTM", target_window="UTM")

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "SKILL_RECORDING_DEPENDENCY_MISSING"
    assert result["missing_dependencies"] == ["pynput"]
    assert manager.status()["status"] == "idle"


def test_recording_overlay_controller_shows_updates_and_hides_banner() -> None:
    module = _load_packaged_helper_module()
    windows: list[Any] = []

    class FakeOverlayWindow:
        def __init__(self) -> None:
            self.elapsed: list[float] = []
            self.closed = False

        def update_elapsed(self, elapsed_s: float) -> None:
            self.elapsed.append(elapsed_s)

        def pump(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    def create_window() -> FakeOverlayWindow:
        window = FakeOverlayWindow()
        windows.append(window)
        return window

    controller = module.RecordingOverlayController(
        platform_name="win32",
        window_factory=create_window,
        monotonic=lambda: 12.5,
        poll_interval=0.005,
    )
    controller.show("rec-overlay-test", 10.0)
    deadline = time.monotonic() + 1.0
    while not controller.status()["visible"] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert controller.status() == {"available": True, "visible": True, "error": None}
    assert windows and windows[0].elapsed[-1] == pytest.approx(2.5)

    controller.hide()
    deadline = time.monotonic() + 1.0
    while controller.status()["visible"] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert windows[0].closed is True
    assert controller.status()["visible"] is False
    controller.shutdown()


def test_recording_manager_owns_overlay_lifecycle(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    overlay = _FakeRecordingOverlay()
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        overlay_controller=overlay,
    )

    started = manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")

    assert overlay.show_calls == [(started["recording_id"], manager._started_monotonic)]
    assert manager.status()["overlay"]["visible"] is True

    manager.stop()
    assert overlay.hide_calls == 1
    assert manager.status()["overlay"]["visible"] is False

    manager.shutdown()
    assert overlay.shutdown_calls == 1


def test_recording_manager_keeps_overlay_hidden_when_listener_start_fails(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    overlay = _FakeRecordingOverlay()

    def fail_listener(_manager: object) -> list[object]:
        raise RuntimeError("listener failed")

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=fail_listener,
        overlay_controller=overlay,
    )

    result = manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")

    assert result["failure_code"] == "SKILL_RECORDING_LISTENER_START_FAILED"
    assert overlay.show_calls == []
    assert overlay.hide_calls == 1


def test_recording_manager_shutdown_stops_active_recording_and_overlay(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    overlay = _FakeRecordingOverlay()
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        overlay_controller=overlay,
    )
    manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")

    manager.shutdown()

    assert manager.status()["status"] == "idle"
    assert overlay.hide_calls == 1
    assert overlay.shutdown_calls == 1


def test_recording_manager_hides_overlay_when_listener_stop_raises(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    overlay = _FakeRecordingOverlay()

    class BadStopListener:
        def start(self) -> None:
            return None

        def stop(self) -> None:
            raise RuntimeError("listener stop failed")

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [BadStopListener()],
        overlay_controller=overlay,
    )
    manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")

    stopped = manager.stop()

    assert stopped["status"] == "completed"
    assert stopped["listener_stop_errors"] == ["RuntimeError: listener stop failed"]
    assert overlay.hide_calls == 1


def test_runtime_dependency_status_distinguishes_required_and_optional_packages() -> None:
    module = _load_packaged_helper_module()
    installed = {"pyautogui", "PIL", "cv2", "pynput"}

    result = module._runtime_dependency_status(lambda name: name in installed)

    assert result["core_ready"] is True
    assert result["required"]["pynput"]["available"] is True
    assert result["optional"]["pywinauto"]["available"] is False
    assert result["optional"]["pytesseract"]["available"] is False


def test_default_demo_root_supports_pyinstaller_bundle(monkeypatch, tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    bundled_demo = tmp_path / "demo"
    bundled_demo.mkdir()
    monkeypatch.setattr(module.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert module._default_demo_root() == bundled_demo


def test_recording_manager_persists_mouse_move_coordinates(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    started = manager.start(name="Mouse square", target_app="Desktop", target_window="Desktop")

    accepted = manager.record_event({"kind": "mouse_move", "x": 780, "y": 440})
    stopped = manager.stop()

    assert accepted is True
    assert stopped["events"] == [
        {"kind": "mouse_move", "x": 780, "y": 440, "at_ms": stopped["events"][0]["at_ms"]}
    ]
    assert manager.save(started["recording_id"])["status"] == "saved"


def test_image_first_recording_captures_click_locator_crops(tmp_path: Path) -> None:
    image_module = pytest.importorskip("PIL.Image")
    module = _load_packaged_helper_module()
    screenshot = image_module.new("RGB", (320, 240), color=(20, 80, 120))
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: screenshot.copy(),
    )
    started = manager.start(name="visual click", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager)

    capture.on_click(100, 120, "Button.left", True)
    capture.on_click(100, 120, "Button.left", False)
    stopped = manager.stop()

    event = stopped["events"][0]
    locator = event["visual_locator"]
    assert started["schema"] == "atr.equipment_recording.v2"
    assert started["visual_locator_policy"]["coordinate_fallback"] is False
    assert locator["status"] == "ready"
    assert locator["recorded_coordinate"] == [100, 120]
    assert [item["kind"] for item in locator["candidates"]] == ["tight", "context"]
    assert all(base64.b64decode(item["png_base64"]).startswith(b"\x89PNG") for item in locator["candidates"])
    assert Path(locator["full_frame_artifact_path"]).exists()


def test_image_first_recording_uses_pointer_frame_from_before_click(tmp_path: Path) -> None:
    from io import BytesIO

    image_module = pytest.importorskip("PIL.Image")
    module = _load_packaged_helper_module()
    before_click = image_module.new("RGB", (320, 240), color=(20, 180, 90))
    after_press = image_module.new("RGB", (320, 240), color=(210, 40, 60))
    state = {"pressed": False}
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: (after_press if state["pressed"] else before_click).copy(),
    )
    manager.start(name="pre-action visual click", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager)

    capture.on_move(100, 120)
    state["pressed"] = True
    capture.on_click(100, 120, "Button.left", True)
    capture.on_click(100, 120, "Button.left", False)
    locator = manager.stop()["events"][-1]["visual_locator"]

    tight = image_module.open(BytesIO(base64.b64decode(locator["candidates"][0]["png_base64"])))
    assert tight.getpixel((32, 32)) == (20, 180, 90)


def test_image_first_recording_uses_recent_frame_before_pointer_hover(tmp_path: Path) -> None:
    from io import BytesIO
    import time

    image_module = pytest.importorskip("PIL.Image")
    module = _load_packaged_helper_module()
    stable = image_module.new("RGB", (320, 240), color=(20, 180, 90))
    hovered = image_module.new("RGB", (320, 240), color=(240, 240, 240))
    frames = iter((stable, hovered))
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: next(frames).copy(),
    )
    manager.start(name="hover-stable visual click", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager)

    capture.on_move(20, 20)
    time.sleep(0.06)
    capture.on_move(100, 120)
    capture.on_click(100, 120, "Button.left", True)
    capture.on_click(100, 120, "Button.left", False)
    locator = manager.stop()["events"][-1]["visual_locator"]

    tight = image_module.open(BytesIO(base64.b64decode(locator["candidates"][0]["png_base64"])))
    assert tight.getpixel((32, 32)) == (20, 180, 90)


def test_image_first_recording_captures_drag_source_and_target(tmp_path: Path) -> None:
    image_module = pytest.importorskip("PIL.Image")
    module = _load_packaged_helper_module()
    screenshot = image_module.new("RGB", (320, 240), color=(100, 40, 20))
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: screenshot.copy(),
    )
    manager.start(name="visual drag", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager, drag_threshold_px=5)

    capture.on_click(30, 40, "Button.left", True)
    capture.on_click(180, 160, "Button.left", False)
    event = manager.stop()["events"][0]

    assert event["source_visual_locator"]["recorded_coordinate"] == [30, 40]
    assert event["target_visual_locator"]["recorded_coordinate"] == [180, 160]
    assert event["source_visual_locator"]["locator_id"].endswith("-source")
    assert event["target_visual_locator"]["locator_id"].endswith("-target")


def test_image_first_recording_marks_capture_failure_without_fake_locator(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()

    def fail_capture() -> object:
        raise RuntimeError("screen unavailable")

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=fail_capture,
    )
    manager.start(name="failed visual", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager)

    capture.on_click(20, 30, "Button.left", True)
    capture.on_click(20, 30, "Button.left", False)
    locator = manager.stop()["events"][0]["visual_locator"]

    assert locator["status"] == "unavailable"
    assert locator["candidates"] == []
    assert locator["failure_code"] == "VISUAL_LOCATOR_CAPTURE_FAILED"


def test_recording_keyboard_capture_groups_modifier_chord_as_hotkey(tmp_path: Path) -> None:
    module = _load_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    manager.start(name="shortcut", target_app="editor", target_window="editor")
    capture = module._RecordingKeyboardCapture(manager)

    capture.on_press("Key.ctrl_l")
    capture.on_press("s")
    capture.on_release("s")
    capture.on_release("Key.ctrl_l")
    stopped = manager.stop()

    assert stopped["events"] == [{"kind": "hotkey", "at_ms": stopped["events"][0]["at_ms"], "keys": ["ctrl", "s"]}]


def test_recording_keyboard_capture_keeps_plain_key_press(tmp_path: Path) -> None:
    module = _load_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    manager.start(name="typing", target_app="editor", target_window="editor")
    capture = module._RecordingKeyboardCapture(manager)

    capture.on_press("a")
    capture.on_release("a")
    stopped = manager.stop()

    assert stopped["events"][0]["kind"] == "key_press"
    assert stopped["events"][0]["key"] == "a"


def test_recording_keyboard_capture_preserves_unused_modifier(tmp_path: Path) -> None:
    module = _load_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    manager.start(name="modifier", target_app="desktop", target_window="desktop")
    capture = module._RecordingKeyboardCapture(manager)

    capture.on_press("Key.shift")
    capture.on_release("Key.shift")
    stopped = manager.stop()

    assert stopped["events"][0]["kind"] == "key_press"
    assert stopped["events"][0]["key"] == "shift"


def test_windows_bridge_executes_move_to_program_action() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        fake = _FakePyAutoGUI()
        trace: list[dict[str, object]] = []

        result = module._execute_protocol_sequence(
            fake,
            program_id="mouse_square_demo",
            payload={"sequence": [{"action": "move_to", "x": 900, "y": 520, "duration_sec": 0.25}]},
            run_id="run-mouse-square",
            specimen_id="specimen-mouse-square",
            trace=trace,
        )

        assert result["ok"] is True
        assert fake.moves == [(900, 520, 0.25)]
        assert any(item["step"] == "SEQ_1_MOVE_TO" and item["status"] == "ok" for item in trace)


def _recorded_image_candidate(kind: str = "tight") -> dict[str, object]:
    import hashlib

    return {
        "kind": kind,
        "png_base64": base64.b64encode(TINY_PNG_BYTES).decode("ascii"),
        "sha256": hashlib.sha256(TINY_PNG_BYTES).hexdigest(),
        "width": 64,
        "height": 64,
        "confidence": 0.88,
    }


def _information_test_candidate(kind: str, *, informative: bool) -> dict[str, object]:
    import hashlib
    from io import BytesIO

    from PIL import Image, ImageDraw

    size = (192, 128) if kind == "context" else (64, 64)
    image = Image.new("RGB", size, "#dceaff")
    if informative:
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, size[0] - 5, size[1] - 5), outline="#17233a", width=3)
        draw.text((12, 12), "SAMPLE COUNT", fill="#10213a")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    return {
        "kind": kind,
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": size[0],
        "height": size[1],
        "confidence": 0.88,
    }


def test_windows_bridge_prefers_informative_context_over_uniform_tight(tmp_path: Path, monkeypatch) -> None:
    for index, module in enumerate((_load_helper_module(), _load_packaged_helper_module())):
        locator_root = tmp_path / f"locators-{index}"
        monkeypatch.setattr(module, "LOCATOR_ROOT", locator_root)
        tight = _information_test_candidate("tight", informative=False)
        context = _information_test_candidate("context", informative=True)
        context_path = locator_root / "inline" / f"{context['sha256']}.png"
        fake = _FakePyAutoGUI()
        fake.locate_match_paths.add(str(context_path))

        match = module._locate_on_screen(
            fake,
            {"image_candidates": [tight, context]},
            run_id="run-context-priority",
            specimen_id="specimen-context-priority",
        )

        assert match is not None
        assert fake.locate_calls[0][0] == str(context_path)


def test_windows_bridge_inline_locator_selects_best_match_not_first_threshold_match(
    tmp_path: Path, monkeypatch
) -> None:
    import hashlib
    from io import BytesIO

    from PIL import Image, ImageDraw

    template = Image.new("RGB", (80, 48), "#dceaff")
    draw = ImageDraw.Draw(template)
    draw.rectangle((1, 1, 78, 46), outline="#17233a", width=3)
    draw.text((8, 15), "COUNT", fill="#10213a")

    similar = template.copy()
    similar_draw = ImageDraw.Draw(similar)
    similar_draw.rectangle((22, 14, 58, 31), fill="#7f91aa")

    screen = Image.new("RGB", (360, 140), "#0f1828")
    screen.paste(similar, (20, 46))
    screen.paste(template, (240, 46))

    buffer = BytesIO()
    template.save(buffer, format="PNG")
    raw = buffer.getvalue()
    candidate = {
        "kind": "context",
        "png_base64": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": 80,
        "height": 48,
        "confidence": 0.80,
    }

    class _ScanOrderPyAutoGUI(_FakePyAutoGUI):
        def screenshot(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
            self.screenshot_regions.append(region)
            return screen.copy()

        def locateOnScreen(self, image_path: str, **kwargs: object) -> object:  # noqa: N802
            self.locate_calls.append((image_path, dict(kwargs)))
            return (20, 46, 80, 48)

    for index, module in enumerate((_load_helper_module(), _load_packaged_helper_module())):
        monkeypatch.setattr(module, "LOCATOR_ROOT", tmp_path / f"best-match-{index}")
        match = module._locate_on_screen(
            _ScanOrderPyAutoGUI(),
            {"image_candidates": [candidate]},
            run_id="run-best-match",
            specimen_id="specimen-best-match",
        )

        assert match == (240, 46, 80, 48)


def test_windows_bridge_inline_locator_selects_global_best_candidate(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    screen = Image.new("RGB", (420, 160), "#0f1828")
    weaker = Image.new("RGB", (100, 60), "#dceaff")
    weaker_draw = ImageDraw.Draw(weaker)
    weaker_draw.rectangle((2, 2, 97, 57), outline="#17233a", width=3)
    weaker_draw.text((10, 20), "WEAKER", fill="#10213a")
    similar = weaker.copy()
    ImageDraw.Draw(similar).rectangle((70, 12, 88, 45), fill="#7f91aa")
    stronger = Image.new("RGB", (100, 60), "#18345f")
    stronger_draw = ImageDraw.Draw(stronger)
    stronger_draw.rectangle((2, 2, 97, 57), outline="#55e6b1", width=3)
    stronger_draw.text((10, 20), "STRONGER", fill="#ffffff")
    screen.paste(similar, (30, 50))
    screen.paste(stronger, (280, 50))

    class _ScreenPyAutoGUI(_FakePyAutoGUI):
        def screenshot(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
            return screen.copy()

    for index, module in enumerate((_load_helper_module(), _load_packaged_helper_module())):
        paths = []
        for name, image in (("weaker", weaker), ("stronger", stronger)):
            path = tmp_path / f"{index}-{name}.png"
            image.save(path)
            paths.append(path)
        attempted, match = module._best_inline_image_match(
            _ScreenPyAutoGUI(),
            [
                (str(paths[0]), {"confidence": 0.75}, 100.0),
                (str(paths[1]), {"confidence": 0.75}, 100.0),
            ],
        )

        assert attempted is True
        assert match == (280, 50, 100, 60)


def test_windows_bridge_executes_image_resolved_move_and_drag(tmp_path: Path, monkeypatch) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "LOCATOR_ROOT", tmp_path / "locators")
    fake = _FakePyAutoGUI()
    fake.locate_matches = True

    result = module._execute_protocol_sequence(
        fake,
        program_id="recorded_visual_drag",
        payload={
            "sequence": [
                {
                    "action": "move_to",
                    "target": "drag-source",
                    "required": True,
                    "image_candidates": [_recorded_image_candidate("tight")],
                    "duration_sec": 0.05,
                },
                {
                    "action": "drag_to",
                    "target": "drag-target",
                    "required": True,
                    "image_candidates": [_recorded_image_candidate("context")],
                    "duration_sec": 0.2,
                    "button": "left",
                },
            ]
        },
        run_id="run-image-drag",
        specimen_id="specimen-image-drag",
        trace=[],
    )

    assert result["ok"] is True
    assert fake.moves == [(1, 1, 0.05)]
    assert fake.drags == [("to", 1, 1, 0.2, "left")]
    assert len(fake.locate_calls) == 2
    assert all(Path(call[0]).exists() for call in fake.locate_calls)


def test_required_recorded_image_miss_never_uses_recorded_coordinate(tmp_path: Path, monkeypatch) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "LOCATOR_ROOT", tmp_path / "locators")
    monkeypatch.setattr(module, "ARTIFACT_ROOT", tmp_path / "artifacts")
    fake = _FakePyAutoGUI()

    result = module._execute_protocol_sequence(
        fake,
        program_id="recorded_visual_click",
        payload={
            "sequence": [
                {
                    "action": "click",
                    "target": "save-button",
                    "required": True,
                    "recorded_coordinate": [900, 520],
                    "image_candidates": [_recorded_image_candidate()],
                }
            ]
        },
        run_id="run-image-miss",
        specimen_id="specimen-image-miss",
        trace=[],
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UI_LOCATOR_NOT_FOUND"
    assert fake.clicks == []
    assert fake.moves == []
    assert list((tmp_path / "artifacts").rglob("*.png"))


def test_program_contract_rejects_tampered_inline_locator() -> None:
    module = _load_packaged_helper_module()
    candidate = _recorded_image_candidate()
    candidate["sha256"] = "0" * 64

    result = module._validate_program_definition(
        {
            "schema": module.PROGRAM_SCHEMA,
            "program_id": "tampered_inline_locator",
            "name": "Tampered inline locator",
            "sequence": [
                {
                    "action": "click",
                    "target": "button",
                    "required": True,
                    "image_candidates": [candidate],
                }
            ],
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_ACTION_PARAMETER_INVALID"
    assert "sha256" in result["message"]


def test_extended_pyautogui_actions_are_accepted_by_program_contract() -> None:
    module = _load_packaged_helper_module()
    actions = [
        {"action": "query_pointer"},
        {"action": "move_rel", "x": 5, "y": -5},
        {"action": "click", "x": 100, "y": 100, "clicks": 2, "button": "left"},
        {"action": "double_click", "x": 100, "y": 100},
        {"action": "triple_click", "x": 100, "y": 100},
        {"action": "mouse_down", "button": "left"},
        {"action": "mouse_up", "button": "left"},
        {"action": "drag_to", "x": 200, "y": 200, "duration_sec": 0.2},
        {"action": "drag_rel", "x": 20, "y": 20, "duration_sec": 0.2},
        {"action": "scroll", "clicks": 2},
        {"action": "hscroll", "clicks": -2},
        {"action": "vscroll", "clicks": 2},
        {"action": "key_down", "key": "shift"},
        {"action": "key_up", "key": "shift"},
        {"action": "pixel", "x": 10, "y": 20},
        {"action": "pixel_matches_color", "x": 10, "y": 20, "color": [10, 20, 30], "tolerance": 5},
        {"action": "window_activate", "title": "Capability Lab"},
        {"action": "window_minimize", "title": "Capability Lab"},
        {"action": "window_maximize", "title": "Capability Lab"},
        {"action": "window_restore", "title": "Capability Lab"},
        {"action": "window_move", "title": "Capability Lab", "x": 40, "y": 50},
        {"action": "window_resize", "title": "Capability Lab", "width": 900, "height": 700},
        {"action": "alert", "text": "Manual check"},
        {"action": "confirm", "text": "Manual check", "buttons": ["Continue", "Cancel"]},
    ]
    definition = {
        "schema": module.PROGRAM_SCHEMA,
        "program_id": "capability_contract_demo",
        "name": "Capability contract demo",
        "safe_test": False,
        "sequence": actions,
    }

    result = module._validate_program_definition(definition)

    assert result["ok"] is True
    assert result["portable_actions"] == sorted({item["action"] for item in actions})


def test_extended_action_validation_rejects_unbounded_parameters() -> None:
    module = _load_packaged_helper_module()
    invalid_sequences = [
        [{"action": "click", "x": 10, "y": 10, "clicks": 20}],
        [{"action": "scroll", "clicks": 1000}],
        [{"action": "drag_to", "x": 10, "y": 10, "duration_sec": 20}],
        [{"action": "window_resize", "title": "Lab", "width": 10, "height": 10}],
        [{"action": "pixel_matches_color", "x": 1, "y": 1, "color": [1, 2]}],
    ]

    for index, sequence in enumerate(invalid_sequences):
        result = module._validate_program_definition(
            {
                "schema": module.PROGRAM_SCHEMA,
                "program_id": f"invalid_capability_{index}",
                "name": "Invalid capability",
                "sequence": sequence,
            }
        )
        assert result["ok"] is False
        assert result["failure_code"] == "PYAUTOGUI_ACTION_PARAMETER_INVALID"


def test_extended_pyautogui_actions_execute_and_emit_runtime_evidence(monkeypatch, tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    monkeypatch.setattr(module, "ARTIFACT_ROOT", tmp_path / "artifacts")
    fake = _FakePyAutoGUI()
    window = _FakeWindow("Capability Lab")
    fake.windows_by_title["Capability Lab"] = [window]
    trace: list[dict[str, object]] = []
    sequence = [
        {"action": "query_pointer"},
        {"action": "move_rel", "x": 5, "y": -5, "duration_sec": 0.1},
        {"action": "click", "x": 100, "y": 100, "clicks": 2, "interval_sec": 0.05, "button": "right"},
        {"action": "drag_to", "x": 200, "y": 210, "duration_sec": 0.2, "button": "left"},
        {"action": "drag_rel", "x": 20, "y": -10, "duration_sec": 0.2, "button": "middle"},
        {"action": "scroll", "clicks": 3},
        {"action": "hscroll", "clicks": -2},
        {"action": "vscroll", "clicks": 1},
        {"action": "press", "key": "tab", "presses": 2, "interval_sec": 0.1},
        {"action": "key_down", "key": "shift"},
        {"action": "key_up", "key": "shift"},
        {"action": "write", "text": "atr", "interval_sec": 0.05},
        {"action": "pixel", "x": 10, "y": 20},
        {"action": "pixel_matches_color", "x": 10, "y": 20, "color": [10, 20, 30], "tolerance": 5},
        {"action": "window_activate", "title": "Capability Lab"},
        {"action": "window_move", "title": "Capability Lab", "x": 40, "y": 50},
        {"action": "window_resize", "title": "Capability Lab", "width": 900, "height": 700},
        {"action": "window_minimize", "title": "Capability Lab"},
        {"action": "window_maximize", "title": "Capability Lab"},
        {"action": "window_restore", "title": "Capability Lab"},
    ]

    result = module._execute_protocol_sequence(
        fake,
        program_id="capability_runtime_demo",
        payload={"sequence": sequence, "runtime_mode": "test"},
        run_id="run-capabilities",
        specimen_id="specimen-capabilities",
        trace=trace,
    )

    assert result["ok"] is True
    assert fake.relative_moves == [(5, -5, 0.1)]
    assert fake.clicks[-2:] == [(100, 100), (100, 100)]
    assert fake.drags == [("to", 200, 210, 0.2, "left"), ("rel", 20, -10, 0.2, "middle")]
    assert fake.scrolls == [("vertical", 3), ("horizontal", -2), ("vertical_explicit", 1)]
    assert ("down", "shift") in fake.key_events and ("up", "shift") in fake.key_events
    assert fake.presses == [("tab", 2, 0.1)]
    assert fake.writes[-1] == "atr"
    assert window.activated is True
    assert window.moves == [(40, 50)]
    assert window.resizes == [(900, 700)]
    assert window.minimized is True and window.maximized is True and window.restored is True
    assert any(item.get("step") == "SEQ_1_QUERY_POINTER" and "640,360" in str(item.get("detail")) for item in trace)
    assert any(item.get("step") == "SEQ_14_PIXEL_MATCHES_COLOR" and item.get("status") == "ok" for item in trace)


def test_blocking_dialog_requires_explicit_manual_confirmation() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()
    trace: list[dict[str, object]] = []

    result = module._execute_protocol_sequence(
        fake,
        program_id="manual_dialog_demo",
        payload={"sequence": [{"action": "alert", "text": "Review"}], "runtime_mode": "test", "confirm_execute": False},
        run_id="run-dialog",
        specimen_id="specimen-dialog",
        trace=trace,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_MANUAL_CONFIRMATION_REQUIRED"
    assert fake.alerts == []


def test_executor_rejects_absolute_coordinate_outside_screen() -> None:
    module = _load_packaged_helper_module()
    result = module._execute_protocol_sequence(
        _FakePyAutoGUI(),
        program_id="bad_coordinate_demo",
        payload={"sequence": [{"action": "move_to", "x": 5000, "y": 20}]},
        run_id="run-bad-coordinate",
        specimen_id="specimen-bad-coordinate",
        trace=[],
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PYAUTOGUI_COORDINATE_OUT_OF_BOUNDS"


def test_executor_releases_held_mouse_and_keyboard_inputs_after_failure() -> None:
    module = _load_packaged_helper_module()
    fake = _FakePyAutoGUI()

    result = module._execute_protocol_sequence(
        fake,
        program_id="held_input_cleanup_demo",
        payload={
            "sequence": [
                {"action": "mouse_down", "button": "left"},
                {"action": "key_down", "key": "shift"},
                {"action": "unsupported_after_hold"},
            ]
        },
        run_id="run-held-cleanup",
        specimen_id="specimen-held-cleanup",
        trace=[],
    )

    assert result["ok"] is False
    assert fake.button_events == [("down", "left"), ("up", "left")]
    assert fake.key_events == [("down", "shift"), ("up", "shift")]


def test_recording_mouse_capture_classifies_click_drag_and_scroll(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    manager.start(name="mouse", target_app="lab", target_window="lab")
    capture = module._RecordingMouseCapture(manager, drag_threshold_px=5)

    capture.on_click(10, 20, "Button.left", True)
    capture.on_click(10, 20, "Button.left", False)
    capture.on_click(30, 40, "Button.left", True)
    capture.on_move(80, 90)
    capture.on_click(80, 90, "Button.left", False)
    capture.on_scroll(80, 90, -2, 3)
    stopped = manager.stop()

    assert [item["kind"] for item in stopped["events"]] == ["mouse_click", "mouse_drag", "mouse_scroll"]
    assert stopped["events"][1]["start_x"] == 30
    assert stopped["events"][1]["start_y"] == 40
    assert stopped["events"][1]["x"] == 80
    assert stopped["events"][1]["y"] == 90
    assert stopped["events"][2]["dx"] == -2
    assert stopped["events"][2]["dy"] == 3


def test_capability_and_example_catalog_endpoints_are_read_only() -> None:
    module = _load_packaged_helper_module()
    module.TOKEN = "catalog-token"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(path: str) -> dict[str, Any]:
        request = urllib.request.Request(base + path, headers={"X-Bridge-Token": "catalog-token"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        capabilities = get("/capabilities")
        examples = get("/examples")
        detail = get("/examples/drag_scroll")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.TOKEN = ""

    assert capabilities["ok"] is True
    assert set(capabilities["families"]) >= {"mouse", "keyboard", "screen", "window", "dialog"}
    assert len(examples["examples"]) == 8
    assert detail["program"]["program_id"] == "example_drag_scroll"
    assert all(item.get("built_in") is not False for item in module._programs()["programs"])


def test_recording_manager_allows_only_one_active_session(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    first = manager.start(name="one", target_app="Program 1", target_window="Program 1")

    second = manager.start(name="two", target_app="Program 1", target_window="Program 1")

    assert second["ok"] is False
    assert second["failure_code"] == "SKILL_RECORDING_ALREADY_ACTIVE"
    assert second["recording_id"] == first["recording_id"]


def test_recording_manager_stop_is_idempotent_and_reloads(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])
    started = manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")
    manager.record_event({"kind": "key_press", "key": "enter"})
    first = manager.stop()
    second = manager.stop()

    assert second["recording_id"] == first["recording_id"]
    assert second["idempotent"] is True
    reloaded = module.RecordingManager(tmp_path, listener_factory=lambda _manager: []).get(started["recording_id"])
    assert reloaded["content_sha256"] == first["content_sha256"]


def test_recording_http_routes_cover_start_status_stop_save_and_list(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "record-token"
    module.RECORDING_MANAGER = module.RecordingManager(tmp_path / "recordings", listener_factory=lambda _manager: [])
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={"X-Bridge-Token": "record-token", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        started = request(
            "/recordings/start",
            method="POST",
            payload={"name": "Program 1", "target_app": "Program 1", "target_window": "Program 1"},
        )
        recording_id = started["recording_id"]
        status = request("/recordings/status")
        stopped = request("/recordings/stop", method="POST", payload={})
        saved = request(f"/recordings/{recording_id}/save", method="POST", payload={})
        detail = request(f"/recordings/{recording_id}")
        listed = request("/recordings")

        assert status["status"] == "recording"
        assert stopped["status"] == "completed"
        assert saved["status"] == "saved"
        assert detail["recording_id"] == recording_id
        assert [item["recording_id"] for item in listed["recordings"]] == [recording_id]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_program_manager_exposes_program_record_and_skill_tabs_without_model_secrets() -> None:
    module = _load_helper_module()
    html = module.INDEX_HTML

    assert 'data-manager-tab="programs"' in html
    assert 'data-manager-tab="record"' in html
    assert 'data-manager-tab="skills"' in html


def test_recording_console_uses_one_five_second_start_stop_toggle() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML

        assert 'id="recordToggle"' in html
        assert 'id="recordStart"' not in html
        assert 'id="recordStop"' not in html
        assert "const RECORDING_COUNTDOWN_SECONDS = 5;" in html
        assert "function beginRecordingCountdown()" in html
        assert "async function stopActiveRecording()" in html
        assert "function syncRecordingToggle()" in html
        assert 'recordToggle.textContent = "STOP RECORDING"' in html
        assert 'recordToggle.textContent = `STARTING IN ${recordingCountdownRemaining}`' in html
    assert 'id="managerRecordView"' in html
    assert 'id="managerSkillsView"' in html
    assert 'id="recordSkill"' in html
    assert 'id="skillRegistry"' in html
    assert 'data-skill-action="test"' in html
    assert 'data-skill-action="delete"' in html
    manager_slice = html[html.index('id="programManagerPanel"') : html.index('id="resultPanel"')]
    assert "api key" not in manager_slice.lower()
    assert "base url" not in manager_slice.lower()


def test_skill_manager_preserves_action_result_while_refreshing_registry() -> None:
    module = _load_helper_module()
    html = module.INDEX_HTML

    assert "async function refreshSkills({showResult = true} = {})" in html
    assert "if (showResult) managerShowResult(result);" in html
    assert "await refreshSkills({showResult: false})" in html


def test_skill_proxy_creates_draft_from_saved_windows_recording(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "skill-token"
    module.RECORDING_MANAGER = module.RecordingManager(tmp_path / "recordings", listener_factory=lambda _manager: [])
    started = module.RECORDING_MANAGER.start(name="Program 1", target_app="Program 1", target_window="Program 1")
    module.RECORDING_MANAGER.record_event({"kind": "key_press", "key": "enter"})
    module.RECORDING_MANAGER.stop()
    module.RECORDING_MANAGER.save(started["recording_id"])
    forwarded: list[tuple[str, str, dict[str, Any]]] = []

    def atr_request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        forwarded.append((method, path, dict(payload or {})))
        return 200, {"ok": True, "manifest": {"skill_id": "program1_skill", "version": "1.0.0"}}

    module._atr_api_request = atr_request
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        req = urllib.request.Request(
            base + "/skills/drafts",
            data=json.dumps(
                {
                    "recording_id": started["recording_id"],
                    "skill_id": "program1_skill",
                    "version": "1.0.0",
                    "target_profile": "local_program1",
                }
            ).encode("utf-8"),
            method="POST",
            headers={"X-Bridge-Token": "skill-token", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))

        assert result["ok"] is True
        assert forwarded[0][0:2] == ("POST", "/api/equipment/skills/drafts")
        assert forwarded[0][2]["recording"]["recording_id"] == started["recording_id"]
        assert "token" not in json.dumps(forwarded[0][2]).lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_skill_proxy_forwards_test_and_delete_to_exact_linux_version() -> None:
    module = _load_helper_module()
    module.TOKEN = "skill-token"
    forwarded: list[tuple[str, str, dict[str, Any]]] = []

    def atr_request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        forwarded.append((method, path, dict(payload or {})))
        return 200, {"ok": True, "status": "passed" if method == "POST" else "deleted"}

    module._atr_api_request = atr_request
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    headers = {"X-Bridge-Token": "skill-token", "Content-Type": "application/json"}
    try:
        test_req = urllib.request.Request(
            base + "/skills/program1_skill/1.0.0/test",
            data=json.dumps({"runtime_mode": "test", "confirm_execute": False}).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(test_req, timeout=5) as response:
            tested = json.loads(response.read().decode("utf-8"))
        delete_req = urllib.request.Request(
            base + "/skills/program1_skill/1.0.0",
            method="DELETE",
            headers=headers,
        )
        with urllib.request.urlopen(delete_req, timeout=5) as response:
            deleted = json.loads(response.read().decode("utf-8"))

        assert tested["status"] == "passed"
        assert deleted["status"] == "deleted"
        assert forwarded == [
            (
                "POST",
                "/api/equipment/skills/program1_skill/1.0.0/test",
                {"runtime_mode": "test", "confirm_execute": False},
            ),
            ("DELETE", "/api/equipment/skills/program1_skill/1.0.0", {}),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
