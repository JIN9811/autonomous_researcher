"""Unit tests for the optional Windows PyAutoGUI bridge helper."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import inspect
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


class _FakeClipboard:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def paste(self) -> str:
        return self.value

    def copy(self, value: str) -> None:
        self.value = value


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


def _valid_raw_csv_export_payload(mode: str = "live") -> dict[str, Any]:
    return {
        "export_context": {
            "mode": mode,
            "session_id": "session-20260902-A",
            "specimen_id": "cube-03",
            "loop_index": 2,
            "repeat_index": 4,
        }
    }


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_plan_uses_package_artifacts_root_and_single_underscore_separators(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    monkeypatch.setattr(module, "BRIDGE_PACKAGE_ROOT", tmp_path / "server")
    plan = module._raw_csv_export_plan(
        {
            "export_context": {
                "mode": "live",
                "session_id": "session_ 20260902-A",
                "specimen_id": "cube_03",
                "loop_index": 2,
                "repeat_index": 4,
            }
        }
    )

    assert plan["ok"] is True
    assert plan["filename"] == "live_session-20260902-A_cube-03_loop-0002_rep-0004.csv"
    assert Path(plan["windows_path"]) == tmp_path / "server" / "artifacts" / "raw_csv" / plan["filename"]
    assert Path(plan["windows_directory"]) == tmp_path / "server" / "artifacts" / "raw_csv"
    assert "__" not in plan["filename"]


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_plan_rejects_invalid_context(loader: Any) -> None:
    module = loader()
    plan = module._raw_csv_export_plan(
        {
            "export_context": {
                "mode": "live",
                "session_id": "..",
                "specimen_id": "",
                "loop_index": 0,
                "repeat_index": -1,
            }
        }
    )

    assert plan["ok"] is False
    assert plan["failure_code"] == "UTM_RAW_CSV_CONTEXT_INVALID"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_plan_blocks_existing_file_before_reservation(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path)
    first = module._raw_csv_export_plan(_valid_raw_csv_export_payload("test"))
    target = Path(first["windows_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("existing", encoding="utf-8")

    blocked = module._raw_csv_export_plan(_valid_raw_csv_export_payload("test"))

    assert blocked["available"] is False
    assert blocked["failure_code"] == "UTM_RAW_CSV_ALREADY_EXISTS"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_reservation_is_atomic_and_second_attempt_is_blocked(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path)
    plan = module._raw_csv_export_plan(_valid_raw_csv_export_payload("live"))

    reservation = module._reserve_raw_csv_export(plan)
    with pytest.raises(module.RawCsvExportError) as error:
        module._reserve_raw_csv_export(plan)

    assert error.value.failure_code == "UTM_RAW_CSV_NAME_RESERVED"
    module._release_raw_csv_reservation(reservation)
    assert not reservation.exists()


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_save_raw_csv_dry_run_resolves_without_gui_or_reservation(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    raw_csv_root = tmp_path / "raw_csv"
    monkeypatch.setattr(module, "RAW_CSV_ROOT", raw_csv_root)
    monkeypatch.setattr(
        module,
        "_load_pyautogui",
        lambda: (_ for _ in ()).throw(AssertionError("GUI touched")),
    )
    program_id = "utm_save_raw_data_1_0_7_segment_001"
    module.PROGRAMS[program_id] = {
        "program_id": program_id,
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "enabled": True,
        "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
    }
    payload = {
        **_valid_raw_csv_export_payload("dry_run"),
        "sequence_id": "seq-raw-csv-preview",
        "program_id": program_id,
        "runtime_mode": "dry_run",
    }

    result = module._execute(payload)

    assert result["ok"] is True
    assert result["status"] == "dry_run_ready"
    assert result["raw_csv_export"]["available"] is True
    assert result["raw_csv_export"]["filename"].startswith("dry_run_")
    assert not raw_csv_root.exists()


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_paste_runtime_value_preserves_clipboard_and_never_types(
    loader: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    fake = _FakePyAutoGUI()
    clipboard = _FakeClipboard("operator value")
    monkeypatch.setattr(module, "_load_pyperclip", lambda: clipboard, raising=False)
    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_save_raw_data_1_0_7_segment_001",
        payload={
            "runtime_values": {"raw_csv_path": r"C:\worker\artifacts\raw_csv\test_s_x_loop-0001_rep-0001.csv"},
            "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
        },
        run_id="run",
        specimen_id="specimen",
        trace=[],
        screen_artifacts=[],
    )

    assert result["ok"] is True
    assert fake.hotkeys == [("ctrl", "v"), ("ctrl", "a"), ("ctrl", "c")]
    assert fake.writes == []
    assert clipboard.value == "operator value"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_paste_runtime_value_blocks_when_focused_field_round_trip_differs(
    loader: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    clipboard = _FakeClipboard("operator value")

    class _CorruptingFieldPyAutoGUI(_FakePyAutoGUI):
        def hotkey(self, *keys: str, interval: float = 0.0) -> None:
            super().hotkey(*keys, interval=interval)
            if keys == ("ctrl", "v"):
                clipboard.value = "wrong-field-value"
            elif keys == ("ctrl", "c"):
                clipboard.value = "wrong-field-value"

    fake = _CorruptingFieldPyAutoGUI()
    monkeypatch.setattr(module, "_load_pyperclip", lambda: clipboard, raising=False)
    expected = r"C:\worker\artifacts\raw_csv\test_s_x_loop-0001_rep-0001.csv"

    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_save_raw_data_1_0_9_segment_001",
        payload={
            "runtime_values": {"raw_csv_path": expected},
            "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
        },
        run_id="run",
        specimen_id="specimen",
        trace=[],
        screen_artifacts=[],
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_RAW_CSV_FIELD_VERIFY_FAILED"
    assert fake.hotkeys == [("ctrl", "v"), ("ctrl", "a"), ("ctrl", "c")]
    assert clipboard.value == "operator value"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_clipboard_failure_has_no_write_fallback(
    loader: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    fake = _FakePyAutoGUI()
    monkeypatch.setattr(module, "_load_pyperclip", lambda: None, raising=False)
    result = module._execute_protocol_sequence(
        fake,
        program_id="utm_save_raw_data_1_0_7_segment_001",
        payload={
            "runtime_values": {"raw_csv_path": r"C:\worker\artifacts\raw_csv\test_s_x_loop-0001_rep-0001.csv"},
            "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
        },
        run_id="run",
        specimen_id="specimen",
        trace=[],
        screen_artifacts=[],
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_RAW_CSV_CLIPBOARD_FAILED"
    assert fake.writes == []


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_reservation_is_released_when_save_execution_fails(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path / "raw_csv")
    program_id = "utm_save_raw_data_1_0_7_segment_001"
    module.PROGRAMS[program_id] = {
        "program_id": program_id,
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "enabled": True,
        "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
    }

    def fail_after_reservation(sequence_id: str, selected_program_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert selected_program_id == program_id
        assert payload["runtime_values"]["raw_csv_path"].endswith(".csv")
        assert payload["runtime_values"]["raw_csv_filename"].endswith(".csv")
        assert payload["runtime_values"]["raw_csv_directory"] == str(tmp_path / "raw_csv")
        assert list((tmp_path / "raw_csv" / ".reservations").glob("*.lock"))
        return {"ok": False, "status": "blocked", "failure_code": "UI_LOCATOR_NOT_FOUND"}

    monkeypatch.setattr(module, "_run_utm_protocol_impl", fail_after_reservation, raising=False)
    result = module._run_utm_protocol(
        "seq-save-failure",
        program_id,
        {
            **_valid_raw_csv_export_payload("test"),
            "confirm_execute": True,
        },
    )

    assert result["ok"] is False
    assert result["raw_csv_export"]["filename"].startswith("test_")
    assert not list((tmp_path / "raw_csv" / ".reservations").glob("*.lock"))


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_raw_csv_existing_file_blocks_before_save_execution(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path / "raw_csv")
    program_id = "utm_save_raw_data_1_0_7_segment_001"
    module.PROGRAMS[program_id] = {
        "program_id": program_id,
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "enabled": True,
        "sequence": [],
    }
    plan = module._raw_csv_export_plan(_valid_raw_csv_export_payload("live"))
    target = Path(plan["windows_path"])
    target.parent.mkdir(parents=True)
    target.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_run_utm_protocol_impl",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GUI execution touched")),
        raising=False,
    )

    result = module._run_utm_protocol(
        "seq-save-collision",
        program_id,
        {**_valid_raw_csv_export_payload("live"), "confirm_execute": True},
    )

    assert result["ok"] is False
    assert result["failure_code"] == "UTM_RAW_CSV_ALREADY_EXISTS"


def _update_package(files: dict[str, bytes], *, version: str = "2026.08.28.2") -> dict[str, Any]:
    metadata = []
    encoded = []
    for path, raw in files.items():
        sha256 = hashlib.sha256(raw).hexdigest()
        metadata.append({"path": path, "size_bytes": len(raw), "sha256": sha256})
        encoded.append(
            {
                "path": path,
                "size_bytes": len(raw),
                "sha256": sha256,
                "data_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    canonical = json.dumps(
        {"schema": "atr.windows_bridge_update_package.v1", "version": version, "files": metadata},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return {
        "schema": "atr.windows_bridge_update_package.v1",
        "version": version,
        "files": encoded,
        "package_sha256": hashlib.sha256(canonical).hexdigest(),
        "total_bytes": sum(len(raw) for raw in files.values()),
    }


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_routes_are_never_unauthenticated_local_setup_routes(loader) -> None:
    module = loader()

    assert module.Handler._is_local_setup_path("/update/status", "GET") is False
    assert module.Handler._is_local_setup_path("/update/stage", "POST") is False
    assert module.Handler._is_local_setup_path("/update/apply", "POST") is False
    assert module.Handler._is_local_setup_path("/update/rollback", "POST") is False


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_package_root_prefers_active_package_environment(loader, monkeypatch, tmp_path: Path) -> None:
    module = loader()
    package_root = tmp_path / "active-package"
    monkeypatch.setenv("ATR_WINDOWS_BRIDGE_INSTALL_ROOT", str(tmp_path / "stale-installed-worker"))
    monkeypatch.setenv("ATR_WINDOWS_BRIDGE_PACKAGE_ROOT", str(package_root))

    assert module._bridge_package_root() == package_root


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_restart_command_uses_active_package_server(loader, monkeypatch, tmp_path: Path) -> None:
    module = loader()
    package_root = tmp_path / "active-package"
    monkeypatch.setenv("ATR_WINDOWS_BRIDGE_INSTALL_ROOT", str(tmp_path / "stale-installed-worker"))
    monkeypatch.setenv("ATR_WINDOWS_BRIDGE_PACKAGE_ROOT", str(package_root))
    monkeypatch.setattr(module.sys, "argv", ["old-server.py", "--port", "8765"])

    command = module._restart_command()

    assert command[1] == str(package_root / "bridge" / "windows_pyautogui_bridge_server.py")
    assert command[2:] == ["--port", "8765"]


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_helper_detaches_standard_handles(loader, monkeypatch, tmp_path: Path) -> None:
    module = loader()
    installed_updater = tmp_path / "scripts" / "bridge_self_updater.py"
    installed_updater.parent.mkdir(parents=True)
    installed_updater.write_text("# installed helper\n", encoding="utf-8")
    stage_dir = tmp_path / "stage"
    staged_updater = stage_dir / "scripts" / "bridge_self_updater.py"
    staged_updater.parent.mkdir(parents=True)
    staged_updater.write_text("# staged helper\n", encoding="utf-8")
    monkeypatch.setattr(module, "_bridge_package_root", lambda: tmp_path)
    update_root = tmp_path / "updates"
    monkeypatch.setattr(module, "UPDATE_MANAGER", SimpleNamespace(update_root=update_root))
    observed: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return SimpleNamespace(pid=42)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    result = module._launch_self_updater(
        "apply",
        {"stage_dir": str(stage_dir), "version": "2026.08.29.7"},
    )

    assert result["ok"] is True
    assert observed["command"][1] == str(staged_updater)
    assert observed["stdin"] is module.subprocess.DEVNULL
    assert observed["stdout"] is module.subprocess.DEVNULL
    assert observed["stderr"] is module.subprocess.DEVNULL
    assert (update_root / "update_in_progress.json").is_file()


def test_packaged_worker_update_allowlist_matches_repository_release_manifest() -> None:
    module = _load_packaged_helper_module()
    manifest_path = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window" / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert module.UPDATE_ALLOWED_PATHS == set(manifest["files"]) | {"release_manifest.json"}


def test_update_allowlist_bootstraps_release_manifest_for_future_updates(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    (tmp_path / "release_manifest.json").write_text(
        json.dumps({"version": "2026.08.29.15", "files": ["bridge/windows_pyautogui_bridge_server.py"]}),
        encoding="utf-8",
    )

    assert "release_manifest.json" in module._bridge_update_allowed_paths(tmp_path)
    assert module._bridge_release_version(tmp_path) == "2026.08.29.17"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_manager_stages_only_allowlisted_verified_files(loader, tmp_path: Path) -> None:
    module = loader()
    package_root = tmp_path / "package"
    update_root = tmp_path / "updates"
    package_root.mkdir()
    manager = module.UpdateManager(
        package_root=package_root,
        update_root=update_root,
        allowed_paths={"bridge/windows_pyautogui_bridge_server.py"},
        recording_status_provider=lambda: {"status": "idle"},
    )
    raw = b"print('updated')\n"

    result = manager.stage(_update_package({"bridge/windows_pyautogui_bridge_server.py": raw}))

    assert result["ok"] is True
    assert result["status"] == "staged"
    assert result["version"] == "2026.08.28.2"
    assert (Path(result["stage_dir"]) / "bridge" / "windows_pyautogui_bridge_server.py").read_bytes() == raw
    assert manager.status()["staged_version"] == "2026.08.28.2"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_manager_rejects_traversal_and_digest_mismatch(loader, tmp_path: Path) -> None:
    module = loader()
    manager = module.UpdateManager(
        package_root=tmp_path / "package",
        update_root=tmp_path / "updates",
        allowed_paths={"bridge/windows_pyautogui_bridge_server.py"},
        recording_status_provider=lambda: {"status": "idle"},
    )
    traversal = _update_package({"../outside.py": b"bad"})
    mismatched = _update_package({"bridge/windows_pyautogui_bridge_server.py": b"good"})
    mismatched["files"][0]["data_base64"] = base64.b64encode(b"changed").decode("ascii")

    traversal_result = manager.stage(traversal)
    mismatch_result = manager.stage(mismatched)

    assert traversal_result["failure_code"] == "PYAUTOGUI_UPDATE_PATH_NOT_ALLOWED"
    assert mismatch_result["failure_code"] == "PYAUTOGUI_UPDATE_FILE_SIZE_MISMATCH"


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_update_manager_blocks_apply_and_rollback_while_recording(loader, tmp_path: Path) -> None:
    module = loader()
    manager = module.UpdateManager(
        package_root=tmp_path / "package",
        update_root=tmp_path / "updates",
        allowed_paths={"bridge/windows_pyautogui_bridge_server.py"},
        recording_status_provider=lambda: {"status": "recording", "recording_id": "rec-1"},
    )

    apply_result = manager.prepare_apply()
    rollback_result = manager.prepare_rollback()

    assert apply_result["failure_code"] == "PYAUTOGUI_UPDATE_RECORDING_ACTIVE"
    assert rollback_result["failure_code"] == "PYAUTOGUI_UPDATE_RECORDING_ACTIVE"






























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
    expected = {"utm_compression_start_v1", "utm_export_csv_v1", "utm_stop_or_abort_v1"}
    assert expected.issubset(by_id)
    assert "utm_manual_save_csv_v1" not in by_id
    compression = by_id["utm_compression_start_v1"]
    assert compression["program_type"] == "utm_protocol"
    assert compression["preconditions"] == ["windows_bridge_ready", "utm_app_visible", "specimen_verified_on_fixture", "robot_clear_of_utm"]
    assert compression["expected_screen_before"][0]["name"] == "ready_state"
    assert any(item.get("target") == "running_state" for item in compression["sequence"] if isinstance(item, dict))
    assert any(item.get("target") == "complete_state" for item in compression["sequence"] if isinstance(item, dict))
    assert compression["save_policy"]["manual_save_required_if_no_artifact"] is False
    assert not any(item.get("action") == "wait_for_file" for item in compression["sequence"] if isinstance(item, dict))
    assert compression["output_artifacts"] == []
    assert compression["safe_abort"]["program_id"] == "utm_stop_or_abort_v1"
    export = by_id["utm_export_csv_v1"]
    assert export["program_type"] == "utm_export"
    assert export["target_window"] == "main_window_title_or_regex"
    assert export["expected_screen_before"][0]["name"] == "complete_state"
    assert export["save_policy"]["save_method"] == "raw_csv_button"
    assert any(
        item.get("action") == "click" and item.get("target") == "save_raw_data_csv"
        for item in export["sequence"]
        if isinstance(item, dict)
    )
    assert not any(
        item.get("action") == "hotkey" and item.get("keys") == ["ctrl", "s"]
        for item in export["sequence"]
        if isinstance(item, dict)
    )
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
        "save_raw_data_csv": {"image_path": "C:/ATR/locators/save_raw_data_csv.png", "confidence": 0.8},
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
    assert result["status"] == "completed"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert result["data_acquisition"]["save_attempted_by_agent"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert ("ctrl", "s") not in fake.hotkeys
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
    assert result["status"] == "completed"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert result["data_acquisition"]["save_attempted_by_agent"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert ("ctrl", "s") not in fake.hotkeys
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


def test_packaged_bridge_raw_csv_export_failure_preserves_failure_evidence(tmp_path: Path) -> None:
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
            "program_id": "utm_export_csv_v1",
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
    assert result["data_acquisition"]["save_method"] == "raw_csv_button"
    assert result["data_acquisition"]["save_attempted_by_agent"] is True
    assert ("ctrl", "s") not in fake.hotkeys
    _assert_failure_screen_evidence(result)


def test_install_bridge_compression_never_falls_back_to_test_save(tmp_path: Path) -> None:
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
    assert result["status"] == "completed"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert result["data_acquisition"]["save_attempted_by_agent"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert not any(item.get("kind") == "utm_csv" for item in result["output_artifacts"])
    assert ("ctrl", "s") not in fake.hotkeys
    assert fake.writes == []
    steps = [item["step"] for item in result["step_trace"]]
    assert "AUTO_SAVE_MISSING" not in steps
    assert "MANUAL_SAVE_EXPORT" not in steps


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_managed_equipment_skill_without_file_contract_never_triggers_manual_save(
    loader: Any,
    tmp_path: Path,
) -> None:
    """Catch hidden Ctrl+S/export side effects after non-export Equipment Skills."""
    module = loader()
    fake = _FakePyAutoGUI()
    fake.save_csv_on_write = True
    module.UTM_EXPORT_ROOT = tmp_path / "utm_exports"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module.PROGRAMS["utm_prepare_next_specimen_test"] = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "utm_prepare_next_specimen_test",
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "sequence": [{"action": "screenshot", "checkpoint": "prepare_complete"}],
    }
    payload = {
        "sequence_id": "seq-managed-no-save",
        "program_id": "utm_prepare_next_specimen_test",
        "run_id": "run-managed-no-save",
        "specimen_id": "specimen-managed-no-save",
        "artifact_timeout_s": 0.01,
        "stable_for_sec": 0.01,
    }
    if loader is _load_packaged_helper_module:
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

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["program_type"] == "macro"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert fake.hotkeys == []
    steps = [item["step"] for item in result["step_trace"]]
    assert "WAIT_FOR_EXPORT" not in steps
    assert "AUTO_SAVE_MISSING" not in steps
    assert "MANUAL_SAVE_EXPORT" not in steps


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_dynamically_registered_managed_save_skill_is_classified_as_export(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")
    program_id = "utm_save_raw_data_1_0_7_segment_001"
    program = {
        "program_id": program_id,
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "sequence": [
            {"action": "wait_for_file", "pattern": "{raw_csv_path}", "timeout_s": 1, "stable_for_sec": 0.01, "required": True},
        ],
    }
    monkeypatch.setattr(module, "_all_programs", lambda: {program_id: program})
    target = tmp_path / "raw_csv" / "test_session_specimen_loop-0001_rep-0001.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n",
        encoding="utf-8",
    )

    result = module._run_utm_protocol_impl(
        "seq-dynamic-save",
        program_id,
        {
            "run_id": "run-dynamic-save",
            "specimen_id": "specimen",
            "runtime_values": {"raw_csv_path": str(target)},
            "expected_export_path": str(target),
            "stable_for_sec": 0.01,
            "artifact_timeout_s": 1,
        },
    )

    assert result["ok"] is True, result
    assert result["data_acquisition"]["status"] == "exported_on_windows"
    assert any(item.get("kind") == "utm_csv" for item in result["output_artifacts"])


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_managed_raw_csv_validation_does_not_require_test_start_screen_evidence(
    loader: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = loader()
    fake = _FakePyAutoGUI()
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.ARTIFACT_INDEX.clear()
    module._load_pyautogui = lambda: (fake, "")
    program_id = "utm_validate_raw_data_1_0_7_segment_001"
    program = {
        "program_id": program_id,
        "program_type": "macro",
        "managed_by": "atr_equipment_skill",
        "integrity_ok": True,
        "sequence": [
            {"action": "wait_for_file", "pattern": "{raw_csv_path}", "timeout_s": 1, "stable_for_sec": 0.01, "required": True},
            {"action": "screenshot", "checkpoint": "raw_csv_validation_boundary"},
        ],
    }
    monkeypatch.setattr(module, "_all_programs", lambda: {program_id: program})
    target = tmp_path / "raw_csv" / "test_session_specimen_loop-0001_rep-0001.csv"
    target.parent.mkdir(parents=True)
    target.write_text(
        "time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n",
        encoding="utf-8",
    )

    result = module._run_utm_protocol_impl(
        "seq-dynamic-validation",
        program_id,
        {
            "run_id": "run-dynamic-validation",
            "specimen_id": "specimen",
            "runtime_values": {"raw_csv_path": str(target)},
            "stable_for_sec": 0.01,
            "artifact_timeout_s": 1,
        },
    )

    assert result["ok"] is True, result
    assert result["status"] == "verified_complete"
    assert result["data_acquisition"]["status"] == "exported_on_windows"
    assert result["cross_checks"]["data_parse_probe_ok"] is True
    steps = [item["step"] for item in result["step_trace"]]
    assert "EXECUTE_VALIDATION_MACRO" in steps
    assert "EXECUTE_START_MACRO" not in steps


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_trapezium_vendor_raw_csv_probe_accepts_multiline_equipment_export(loader: Any, tmp_path: Path) -> None:
    module = loader()
    path = tmp_path / "trapezium-raw.csv"
    path.write_text(
        '"1 _ 1",,,,,,,,\n'
        'Name,Force,Stroke,Height,,,,,\n'
        'Unit,N,mm,mm,,,,,\n'
        '0,0.20,0.000,30.500,,,,,\n'
        '1,1.20,0.010,30.490,,,,,\n'
        '2,2.20,0.020,30.480,,,,,\n',
        encoding="utf-8",
    )

    result = module._probe_utm_csv(path)

    assert result["ok"] is True
    assert result["data_quality"]["format"] == "trapeziumx_raw"
    assert result["row_count_probe"] == 5


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_trapezium_artifact_metadata_uses_parsed_rows_and_canonical_columns(loader: Any, tmp_path: Path) -> None:
    module = loader()
    module.ARTIFACT_INDEX.clear()
    path = tmp_path / "trapezium-raw.csv"
    path.write_bytes(
        (
            '"1 _ 1",,,,,,,,\n'
            '"Time","Force","스트로크","Height","Stress","스트로크 (신율)","변위","변위 (신율)","Height (Strain)"\n'
            '"sec","N","mm","mm","N/mm2","%","mm","%","%"\n'
            '0,0.20,0.000,30.500,0,0,0,0,0\n'
            '1,1.20,0.010,30.490,0,0,0,0,0\n'
        ).encode("cp949")
    )

    artifact = module._artifact_payload(
        path,
        artifact_id="utm_csv_specimen_1",
        kind="utm_csv",
        windows_path=str(path),
    )

    assert artifact["parse_ok"] is True
    assert artifact["row_count_probe"] == 2
    assert artifact["columns_probe"] == ["time_s", "force_N", "displacement_mm", "height_mm"]
    assert artifact["source_format"] == "trapeziumx_raw"
    assert artifact["encoding"] == "cp949"


def test_packaged_bridge_compression_never_falls_back_to_test_save(tmp_path: Path) -> None:
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
    assert result["status"] == "completed"
    assert result["data_acquisition"]["status"] == "not_applicable"
    assert result["data_acquisition"]["save_attempted_by_agent"] is False
    assert result["cross_checks"]["save_export_responsibility_ok"] is True
    assert not any(item.get("kind") == "utm_csv" for item in result["output_artifacts"])
    assert ("ctrl", "s") not in fake.hotkeys
    assert fake.writes == []


def test_windows_bridge_invalid_screenshot_is_not_reported_as_raw_csv_or_screen_evidence(tmp_path: Path) -> None:
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

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["data_acquisition"]["status"] == "not_applicable"
        assert result["output_artifacts"] == []
        assert result["screen_checks"]
        assert all(not item["ok"] and not item["screenshot_artifact"] for item in result["screen_checks"])
        assert any("invalid image signature" in str(item.get("detail", "")) for item in result["step_trace"])


def test_install_bridge_export_program_uses_raw_csv_button(tmp_path: Path) -> None:
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
        {
            "run_id": "run-export",
            "specimen_id": "specimen-export",
            "locators": _utm_locator_payload(),
            "artifact_timeout_s": 1.0,
            "stable_for_sec": 0.01,
        },
    )

    assert result["ok"] is True, result
    assert result["status"] == "verified_complete"
    assert result["program_id"] == "utm_export_csv_v1"
    assert result["data_acquisition"]["save_method"] == "raw_csv_button"
    assert result["data_acquisition"]["save_attempted_by_agent"] is True
    assert any(item["step"] == "EXECUTE_EXPORT_MACRO" for item in result["step_trace"])
    assert ("ctrl", "s") not in fake.hotkeys
    assert ("ctrl", "a") in fake.hotkeys
    assert fake.writes and fake.writes[0].endswith("specimen-export.csv")


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






def test_windows_bridge_console_matches_the_four_section_worker_scope() -> None:
    required_sections = (
        'id="bridgeStatusPanel"',
        'id="programManagerPanel"',
        'id="recordingPanel"',
        'id="latestLocalResultPanel"',
        'id="diagnosticsPanel"',
    )
    forbidden_ownership = (
        "UTM Protocol",
        "Live Proof Checklist",
        "Analysis Handoff",
        "Vision Proof",
        "ATR Controller",
        'data-manager-tab="skills"',
        'id="managerSkillsView"',
        'id="token"',
    )

    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        for marker in required_sections:
            assert marker in html
        for marker in forbidden_ownership:
            assert marker not in html
        assert "Bridge Status" in html
        assert "Program Manager" in html
        assert "Recording" in html
        assert "Latest Local Result" in html
        assert "program1" in html
        assert '<details id="diagnosticsPanel"' in html


def test_windows_bridge_server_does_not_proxy_linux_skill_or_controller_ownership() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert 'path == "/skills"' not in source
        assert 'path.startswith("/skills/")' not in source
        assert '"/controller/discover"' not in source
        assert '"/controller/select"' not in source
        assert "class ATRControllerResolver" not in source
        assert "CONTROLLER_RESOLVER" not in source
        assert "_atr_api_request" not in source
        assert '"atr_controller"' not in source


def test_windows_bridge_recording_delete_removes_only_the_saved_local_recording(tmp_path: Path) -> None:
    module = _load_helper_module()
    manager = module.RecordingManager(tmp_path / "recordings", listener_factory=lambda _manager: [])
    started = manager.start(
        name="delete fixture",
        target_app="fixture",
        target_window="fixture",
    )
    manager.stop()
    manager.save(started["recording_id"])

    deleted = manager.delete(started["recording_id"])

    assert deleted == {
        "ok": True,
        "status": "deleted",
        "recording_id": started["recording_id"],
    }
    assert manager.get(started["recording_id"])["status"] == "not_found"


def test_windows_bridge_pairing_uses_one_time_four_digit_code_and_persists_internal_key(tmp_path: Path) -> None:
    module = _load_helper_module()
    now = [1000.0]
    manager = module.PairingManager(
        tmp_path / "pairing.json",
        clock=lambda: now[0],
        code_factory=lambda: "0427",
        key_factory=lambda: "internal-key-fixture",
    )

    issued = manager.issue_code()

    assert issued["pairing_code"] == "0427"
    assert issued["expires_in_sec"] == 300
    completed = manager.complete("0427")
    assert completed == {
        "ok": True,
        "status": "paired",
        "paired": True,
        "internal_key": "internal-key-fixture",
    }
    assert manager.status() == {"ok": True, "status": "paired", "paired": True}
    assert "0427" not in (tmp_path / "pairing.json").read_text(encoding="utf-8")

    retried = manager.complete("0427")
    assert retried == {
        "ok": True,
        "status": "paired_retry",
        "paired": True,
        "internal_key": "internal-key-fixture",
    }
    assert manager.complete("9999")["failure_code"] == "PAIRING_ALREADY_COMPLETE"


def test_windows_bridge_pairing_can_be_reset_locally_after_a_half_completed_exchange(tmp_path: Path) -> None:
    module = _load_helper_module()
    codes = iter(("0427", "1357"))
    manager = module.PairingManager(
        tmp_path / "pairing.json",
        code_factory=lambda: next(codes),
        key_factory=lambda: "internal-key-fixture",
    )
    manager.issue_code()
    assert manager.complete("0427")["ok"] is True

    reset = manager.reset()

    assert reset["ok"] is True
    assert reset["status"] == "pairing_available"
    assert reset["pairing_code"] == "1357"
    assert not (tmp_path / "pairing.json").exists()
    assert manager.complete("1357")["ok"] is True


def test_windows_bridge_pairing_expires_codes_and_locks_after_five_failures(tmp_path: Path) -> None:
    module = _load_helper_module()
    now = [1000.0]
    manager = module.PairingManager(
        tmp_path / "pairing.json",
        clock=lambda: now[0],
        code_factory=lambda: "1357",
        key_factory=lambda: "internal-key-fixture",
    )
    manager.issue_code()

    for attempt in range(5):
        result = manager.complete("9999")
        assert result["ok"] is False
        assert result["attempts_remaining"] == max(0, 4 - attempt)

    assert result["status"] == "locked"
    assert result["retry_after_sec"] == 30
    now[0] += 31
    invalidated = manager.complete("1357")
    assert invalidated["ok"] is False
    assert invalidated["failure_code"] == "PAIRING_CODE_REQUIRED"
    manager.issue_code()
    assert manager.complete("1357")["ok"] is True

    second = module.PairingManager(
        tmp_path / "expired.json",
        clock=lambda: now[0],
        code_factory=lambda: "2468",
        key_factory=lambda: "second-key",
    )
    second.issue_code()
    now[0] += 301
    expired = second.complete("2468")
    assert expired["status"] == "expired"
    assert expired["failure_code"] == "PAIRING_CODE_EXPIRED"


def test_windows_bridge_pairing_routes_keep_execution_protected_while_local_setup_remains_available(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = ""
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.PROGRAM_ROOT = tmp_path / "programs"
    module.RECORDING_MANAGER = module.RecordingManager(tmp_path / "recordings", listener_factory=lambda _manager: [])
    module.PAIRING_MANAGER = module.PairingManager(
        tmp_path / "pairing.json",
        code_factory=lambda: "3141",
        key_factory=lambda: "paired-internal-key",
    )
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, key: str = ""):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if key:
            headers[module.TOKEN_HEADER] = key
        return urllib.request.urlopen(
            urllib.request.Request(base + path, data=data, method=method, headers=headers),
            timeout=5,
        )

    try:
        for path in ("/health", "/programs", "/recordings", "/pairing/status", "/request-log"):
            with request(path) as response:
                assert response.status == 200
        with request(
            "/execute",
            method="POST",
            payload={"sequence_id": "local-console-test", "program_id": "program1"},
        ) as response:
            local_execute = json.loads(response.read())
        assert local_execute.get("failure_code") != "PYAUTOGUI_AUTH_FAILED"
        with pytest.raises(urllib.error.HTTPError) as protected:
            request("/artifacts")
        assert protected.value.code == 401

        with request("/pairing/new-code", method="POST", payload={}) as response:
            assert json.loads(response.read())["pairing_code"] == "3141"
        with request("/pairing/complete", method="POST", payload={"pairing_code": "3141"}) as response:
            paired = json.loads(response.read())
        assert paired["internal_key"] == "paired-internal-key"
        with pytest.raises(urllib.error.HTTPError) as paired_local_without_key:
            request("/artifacts")
        assert paired_local_without_key.value.code == 401
        with request("/artifacts", key=paired["internal_key"]) as response:
            assert response.status == 200
        with request("/pairing/reset", method="POST", payload={}) as response:
            reset = json.loads(response.read())
        assert reset["status"] == "pairing_available"
        assert reset["pairing_code"] == "3141"
        with pytest.raises(urllib.error.HTTPError) as old_key_after_reset:
            request("/artifacts", key=paired["internal_key"])
        assert old_key_after_reset.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_windows_bridge_keeps_saved_connection_secret_valid_after_pairing(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "saved-connection-secret"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    module.PAIRING_MANAGER = module.PairingManager(
        tmp_path / "pairing.json",
        code_factory=lambda: "3141",
        key_factory=lambda: "paired-internal-key",
    )
    module.PAIRING_MANAGER.issue_code()
    assert module.PAIRING_MANAGER.complete("3141")["ok"] is True
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/artifacts",
        headers={module.TOKEN_HEADER: module.TOKEN},
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_windows_bridge_pairing_complete_rejects_oversized_request_body(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = ""
    module.PAIRING_MANAGER = module.PairingManager(tmp_path / "pairing.json", code_factory=lambda: "3141")
    module.PAIRING_MANAGER.issue_code()
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/pairing/complete",
        data=json.dumps({"pairing_code": "3141", "padding": "x" * 20000}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=5)
        assert rejected.value.code == 413
        assert json.loads(rejected.value.read())["failure_code"] == "PYAUTOGUI_REQUEST_TOO_LARGE"
        assert module.PAIRING_MANAGER.status()["paired"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_windows_bridge_public_health_reports_pairing_state_without_exposing_code(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.PAIRING_MANAGER = module.PairingManager(
        tmp_path / "pairing.json",
        code_factory=lambda: "8080",
    )
    module.PAIRING_MANAGER.issue_code()
    module.get_pyautogui = lambda: (None, "not installed")

    health = module._health()

    assert health["pairing"] == {"paired": False, "status": "pairing_available"}
    assert "8080" not in json.dumps(health)


def test_windows_bridge_main_starts_unpaired_without_legacy_token(monkeypatch, tmp_path: Path, capsys) -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        module.TOKEN = ""
        module.ARTIFACT_ROOT = tmp_path / module.__name__ / "artifacts"
        module.LOCATOR_ROOT = tmp_path / module.__name__ / "locators"
        module.RECORDING_ROOT = tmp_path / module.__name__ / "recordings"
        module.PAIRING_MANAGER = module.PairingManager(module.ARTIFACT_ROOT / "pairing.json", code_factory=lambda: "2718")
        module.PAIRING_MANAGER.issue_code()

        class _Server:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def serve_forever(self) -> None:
                return

            def server_close(self) -> None:
                return

        monkeypatch.setattr(module, "_parse_cli_args", lambda: module.argparse.Namespace(allow_no_token=False, open_browser=False))
        monkeypatch.setattr(module, "ThreadingHTTPServer", _Server)
        monkeypatch.setattr(module, "_load_pyautogui", lambda: (None, "not installed"))
        monkeypatch.setattr(module.RECORDING_MANAGER, "shutdown", lambda: None)

        module.main()

    output = capsys.readouterr().out
    assert "Pairing: required" in output
    assert "Token authentication:" not in output




def test_windows_bridge_program_editor_opens_only_for_add_or_edit() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML
        assert 'id="programEditor" class="editor" hidden' in html
        assert "openEditor(" in html
        assert '$("programEditor").hidden = false' in html
        assert '$("programEditor").hidden=true' in html


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
    persisted = json.loads((module.PROGRAM_ROOT / "fixture_prepare.json").read_text(encoding="utf-8"))
    assert registered["program_sha256"] == hashlib.sha256(
        json.dumps(persisted, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
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


def test_windows_bridge_managed_skill_program_is_immutable_and_hash_checked(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.PROGRAM_ROOT = tmp_path / "programs"
    definition = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "managed_fixture_prepare",
        "name": "Managed Fixture Prepare",
        "description": "Linux-owned deployed Skill program",
        "enabled": True,
        "program_type": "macro",
        "requires_pyautogui": True,
        "safe_test": False,
        "sequence": [{"action": "log", "message": "fixture ready"}],
    }
    digest = hashlib.sha256(
        json.dumps(definition, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    registered = module._register_program_definition(
        definition,
        managed=True,
        deployment_sha256=digest,
    )

    assert registered["ok"] is True
    assert registered["program"]["managed_by"] == "atr_equipment_skill"
    assert module._delete_custom_program("managed_fixture_prepare")["failure_code"] == "PYAUTOGUI_PROGRAM_MANAGED_IMMUTABLE"
    assert module._register_program_definition({**definition, "description": "local mutation"})["failure_code"] == "PYAUTOGUI_PROGRAM_MANAGED_IMMUTABLE"

    persisted_path = module.PROGRAM_ROOT / "managed_fixture_prepare.json"
    persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
    persisted["sequence"] = [{"action": "log", "message": "tampered"}]
    persisted_path.write_text(json.dumps(persisted), encoding="utf-8")
    module.get_pyautogui = lambda: (_FakePyAutoGUI(), None)

    executed = module._execute({"sequence_id": "managed-hash-check", "program_id": "managed_fixture_prepare"})

    assert executed["ok"] is False
    assert executed["failure_code"] == "PYAUTOGUI_PROGRAM_HASH_MISMATCH"


def test_windows_bridge_managed_skill_program_allows_explicit_atr_replace_and_delete(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.PROGRAM_ROOT = tmp_path / "programs"
    definition = {
        "schema": "atr.pyautogui_program.v1",
        "program_id": "managed_fixture_replace",
        "name": "Managed Fixture Replace",
        "description": "Linux-owned replacement fixture",
        "enabled": True,
        "program_type": "macro",
        "requires_pyautogui": True,
        "safe_test": False,
        "sequence": [{"action": "log", "message": "version one"}],
    }
    first_digest = hashlib.sha256(
        json.dumps(definition, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert module._register_program_definition(
        definition,
        managed=True,
        deployment_sha256=first_digest,
    )["ok"] is True

    replacement = {**definition, "sequence": [{"action": "log", "message": "version two"}]}
    replacement_digest = hashlib.sha256(
        json.dumps(replacement, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    replaced = module._register_program_definition(
        replacement,
        managed=True,
        deployment_sha256=replacement_digest,
    )

    assert replaced["ok"] is True
    assert replaced["program_sha256"] == replacement_digest
    assert module._delete_custom_program("managed_fixture_replace", allow_managed=True)["ok"] is True


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
        assert '>Template<' in html
        assert '>Save<' in html
        assert 'call("/programs/validate"' in html
        assert 'call("/programs/register"' in html
        assert 'atr.windowsBridge.programShortcuts.v1' not in html
        assert 'data-proxy-click="program1"' not in html
        assert 'data-proxy-click="utmSim"' not in html
        assert 'data-proxy-click="utmLive"' not in html
        assert 'data-proxy-click="utmAbort"' not in html
        assert 'id="program1"' not in html


def test_windows_bridge_locator_defaults_to_point_nine() -> None:
    import inspect

    for module in (_load_helper_module(), _load_packaged_helper_module()):
        matcher_source = inspect.getsource(module._best_inline_image_match)
        capture_source = inspect.getsource(module._capture_locator)
        recording_source = inspect.getsource(module.RecordingManager.capture_visual_locator)

        assert 'candidate.get("confidence", 0.9)' in matcher_source
        assert 'payload.get("confidence", 0.9)' in capture_source
        assert '("tight", 64, 64, 0.9)' in recording_source
        assert '("context", 192, 128, 0.9)' in recording_source




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


def test_windows_bridge_mutating_routes_require_json_content_type(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = "content-type-token"
    module.PROGRAM_ROOT = tmp_path / "programs"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    request = urllib.request.Request(
        base + "/programs/validate",
        data=b"{}",
        headers={"X-Bridge-Token": "content-type-token", "Content-Type": "text/plain"},
        method="POST",
    )

    try:
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=5)
        assert rejected.value.code == 415
        payload = json.loads(rejected.value.read().decode("utf-8"))
        assert payload["failure_code"] == "PYAUTOGUI_JSON_CONTENT_TYPE_REQUIRED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)











def test_install_bridge_request_audit_allows_local_health_without_secret_leak(tmp_path: Path) -> None:
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
    assert events[1]["auth_ok"] is True
    assert events[2]["auth_ok"] is True
    assert events[3]["status"] == "authorized"
    assert events[4]["audit_kind"] == "execute_payload"
    assert events[4]["run_id"] == "run-audit"
    assert events[5]["audit_kind"] == "execute_result"
    assert events[6]["auth_ok"] is True
    assert "audit-token" not in log_path.read_text(encoding="utf-8")
    assert "wrong-token" not in log_path.read_text(encoding="utf-8")



def test_packaged_bridge_request_log_allows_local_health_without_secret_leak(tmp_path: Path) -> None:
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
    assert payload["events"][0]["auth_ok"] is True
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
    assert saved["events"][0]["kind"] == "key_press"
    assert saved["events"][0]["key"] == "a"
    assert isinstance(saved["events"][0]["at_ms"], int)
    assert "text" not in saved["events"][0]
    assert saved["checkpoints"][0]["sha256"]
    assert (tmp_path / started["recording_id"] / "recording.json").exists()


def test_recording_manager_masks_sensitive_screen_regions_in_all_evidence(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (100, 80), color=(255, 255, 255)),
    )
    fake = _FakePyAutoGUI()
    fake.screenshot = lambda: pillow.new("RGB", (100, 80), color=(255, 255, 255))

    started = manager.start(
        name="masked demo",
        target_app="Program 1",
        target_window="Program 1",
        mask_regions=[{"x": 10, "y": 12, "width": 30, "height": 20}],
    )
    assert started["mask_regions"] == [{"x": 10, "y": 12, "width": 30, "height": 20}]
    assert manager._frame_buffer.capture_once() is True
    checkpoint = manager.checkpoint(label="masked checkpoint", pyautogui=fake)
    completed = manager.stop()

    checkpoint_image = pillow.open(checkpoint["artifact_path"]).convert("RGB")
    frame_image = pillow.open(completed["time_series_evidence"]["frames"][0]["artifact_path"]).convert("RGB")
    assert checkpoint_image.getpixel((15, 15)) == (0, 0, 0)
    assert frame_image.getpixel((15, 15)) == (0, 0, 0)
    assert frame_image.getpixel((60, 60)) != (0, 0, 0)


def test_recording_manager_persists_bounded_event_keyframes(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    frame_number = 0

    def screenshot() -> object:
        nonlocal frame_number
        frame_number += 1
        return pillow.new("RGB", (640, 480), color=(frame_number % 255, 40, 80))

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=screenshot,
        frame_buffer_fps=2,
        frame_buffer_retention_sec=20,
    )
    started = manager.start(name="Buffered demo", target_app="Program 1", target_window="Program 1")
    assert started["schema"] == "atr.equipment_recording.v3"
    assert manager._frame_buffer.capture_once() is True
    manager.record_event({"kind": "key_press", "key": "enter"})
    assert manager._frame_buffer.capture_once() is True

    completed = manager.stop()
    timeline = completed["time_series_evidence"]

    assert timeline["schema"] == "atr.equipment_recording_frames.v1"
    assert timeline["fps"] == 2.0
    assert timeline["retention_sec"] == 20.0
    assert timeline["sampled_frame_count"] >= 2
    assert 1 <= timeline["persisted_frame_count"] <= timeline["sampled_frame_count"]
    assert all(Path(item["artifact_path"]).is_file() for item in timeline["frames"])
    assert manager._frame_buffer.status()["active"] is False


def test_recording_manager_persists_complete_two_fps_fullscreen_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    frame_number = {"value": 0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])

    def screenshot() -> object:
        frame_number["value"] += 1
        return pillow.new("RGB", (1200, 600), color=(frame_number["value"] % 255, 40, 80))

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=screenshot,
        frame_buffer_fps=2,
        frame_buffer_retention_sec=20,
    )
    started = manager.start(name="full timeline", target_app="Program 1", target_window="Program 1")
    for frame_index in range(1, 66):
        clock["value"] = 100.0 + frame_index * 0.5
        assert manager._frame_buffer.capture_once() is True

    completed = manager.stop()
    timeline = completed["time_series_evidence"]
    periodic = [item for item in timeline["frames"] if item["reason"] == "periodic"]

    assert timeline["fps"] == 2.0
    assert timeline["sampled_frame_count"] == 66
    assert timeline["persisted_frame_count"] == 66
    assert len(periodic) == 66
    assert periodic[0]["width"] == 1200
    assert periodic[0]["height"] == 600
    assert all(Path(item["artifact_path"]).is_file() for item in periodic)
    assert Path(timeline["timeline_path"]).is_file()
    timeline_rows = [json.loads(line) for line in Path(timeline["timeline_path"]).read_text().splitlines()]
    periodic_rows = [row for row in timeline_rows if row["reason"] == "periodic"]
    assert [row["frame_id"] for row in periodic_rows] == [item["frame_id"] for item in periodic]
    assert {row["reason"] for row in timeline_rows} >= {"recording_start", "recording_stop"}
    assert manager._frame_buffer.status()["buffer_bytes"] == 0
    assert started["time_series_evidence"]["fps"] == 2.0


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_recording_frame_loop_compensates_for_capture_processing_time(loader) -> None:
    module = loader()
    clock = {"value": 0.0}
    capture_times: list[float] = []

    class FakeStopEvent:
        def wait(self, timeout: float) -> bool:
            if len(capture_times) >= 3:
                return True
            clock["value"] += timeout
            return False

    frame_buffer = module.RecordingFrameBuffer(screenshot_provider=lambda: None, fps=2)
    frame_buffer._stop_event = FakeStopEvent()

    def capture_once() -> bool:
        capture_times.append(clock["value"])
        clock["value"] += 0.1
        return True

    frame_buffer.capture_once = capture_once
    original_monotonic = module.time.monotonic
    module.time.monotonic = lambda: clock["value"]
    try:
        frame_buffer._capture_loop()
    finally:
        module.time.monotonic = original_monotonic

    assert capture_times == pytest.approx([0.5, 1.0, 1.5])


def test_recording_timeline_marks_incomplete_when_disk_is_critically_low(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    usage = type("Usage", (), {"total": 2_000_000_000, "used": 1_950_000_000, "free": 50_000_000})()
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _path: usage)
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (160, 120), color=(40, 50, 60)),
    )
    started = manager.start(name="low disk", target_app="Program 1", target_window="Program 1")

    assert manager._frame_buffer.capture_once() is False
    completed = manager.stop()

    assert completed["time_series_evidence"]["writer_status"] == "incomplete"
    assert completed["time_series_evidence"]["storage_state"] == "critical"
    assert completed["time_series_evidence"]["evidence_complete"] is False
    assert (tmp_path / started["recording_id"] / "recording.json").is_file()


def test_recording_stop_captures_final_state_after_last_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    frame_number = {"value": 0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])

    def screenshot() -> object:
        frame_number["value"] += 1
        return pillow.new("RGB", (320, 240), color=(frame_number["value"], 40, 80))

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=screenshot,
        frame_buffer_fps=2,
    )
    manager.start(name="final-state", target_app="Program 1", target_window="Program 1")
    clock["value"] = 101.0
    assert manager._frame_buffer.capture_once() is True
    clock["value"] = 102.0
    assert manager.record_event({"kind": "key_press", "key": "enter"}) is True
    clock["value"] = 103.0

    completed = manager.stop()

    frames = completed["time_series_evidence"]["frames"]
    assert max(item["at_ms"] for item in frames) == 3000
    assert max(item["at_ms"] for item in frames) > completed["events"][-1]["at_ms"]


def test_recording_event_keyframe_survives_rolling_buffer_eviction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (320, 240), color=(10, 20, 30)),
        frame_buffer_fps=2,
        frame_buffer_retention_sec=20,
    )
    manager.start(name="long recording", target_app="Program 1", target_window="Program 1")
    clock["value"] = 101.0
    assert manager._frame_buffer.capture_once() is True
    assert manager.record_event({"kind": "key_press", "key": "enter"}) is True
    for elapsed in (10, 20, 25, 30):
        clock["value"] = 100.0 + elapsed
        assert manager._frame_buffer.capture_once() is True

    completed = manager.stop()
    evidence = completed["events"][0]["frame_evidence"]

    assert evidence["at_ms"] == 1000
    assert evidence["event_at_ms"] == 1000
    assert Path(evidence["artifact_path"]).is_file()
    assert evidence["sha256"] == hashlib.sha256(Path(evidence["artifact_path"]).read_bytes()).hexdigest()


def test_recording_event_links_pre_exact_and_post_frames_with_png_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    frame_number = {"value": 0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])

    def screenshot() -> object:
        frame_number["value"] += 1
        return pillow.new("RGB", (320, 180), color=(frame_number["value"] % 255, 30, 60))

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=screenshot,
        frame_buffer_fps=2,
    )
    manager.start(name="linked evidence", target_app="Program 1", target_window="Program 1")
    clock["value"] = 100.5
    assert manager._frame_buffer.capture_once() is True
    clock["value"] = 101.0
    assert manager.record_event({"kind": "key_press", "key": "enter"}) is True
    clock["value"] = 101.5
    assert manager._frame_buffer.capture_once() is True
    clock["value"] = 102.0

    completed = manager.stop()
    evidence = completed["events"][0]["frame_evidence"]
    frames = completed["time_series_evidence"]["frames"]
    frame_ids = {item["frame_id"] for item in frames}
    boundary_frames = [item for item in frames if item["reason"] in {"recording_start", "recording_stop"}]

    assert evidence["pre_frame_id"] in frame_ids
    assert evidence["event_frame_id"] in frame_ids
    assert evidence["post_frame_id"] in frame_ids
    assert Path(evidence["event_artifact_path"]).suffix.lower() == ".png"
    assert Path(evidence["post_artifact_path"]).suffix.lower() == ".png"
    assert Path(evidence["event_artifact_path"]).is_file()
    assert Path(evidence["post_artifact_path"]).is_file()
    assert {item["reason"] for item in boundary_frames} == {"recording_start", "recording_stop"}
    assert all(Path(item["artifact_path"]).suffix.lower() == ".png" for item in boundary_frames)


def test_recording_package_contains_bounded_hash_verified_artifacts(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (160, 120), color=(40, 50, 60)),
    )
    started = manager.start(name="portable recording", target_app="Program 1", target_window="Program 1")
    manager.record_event({"kind": "key_press", "key": "enter"})
    manager.stop()

    package = manager.package(started["recording_id"])

    assert package["ok"] is True
    assert package["schema"] == "atr.equipment_recording_package.v1"
    assert package["recording"]["recording_id"] == started["recording_id"]
    assert package["artifacts"]
    for artifact in package["artifacts"]:
        raw = base64.b64decode(artifact["data_base64"], validate=True)
        assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
        assert ".." not in Path(artifact["relative_path"]).parts


def test_recording_package_has_no_default_completed_evidence_byte_cap() -> None:
    module = _load_packaged_helper_module()

    parameter = inspect.signature(module.RecordingManager.package).parameters["max_total_bytes"]

    assert parameter.default is None


def test_recording_preview_returns_bounded_browser_ready_keyframes(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (160, 120), color=(40, 50, 60)),
    )
    started = manager.start(name="preview recording", target_app="Program 1", target_window="Program 1")
    assert manager._frame_buffer.capture_once() is True
    manager.record_event({"kind": "key_press", "key": "enter"})
    manager.stop()

    preview = manager.preview(started["recording_id"])

    assert preview["ok"] is True
    assert preview["schema"] == "atr.equipment_recording_preview.v1"
    assert preview["recording_id"] == started["recording_id"]
    assert preview["frames"]
    assert preview["frames"][0]["data_base64"]
    assert preview["frames"][0]["media_type"] in {"image/jpeg", "image/png"}
    assert "artifact_path" not in preview["frames"][0]


def test_recording_preview_paginates_without_loading_complete_timeline(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (160, 120), color=(40, 50, 60)),
    )
    started = manager.start(name="paginated preview", target_app="Program 1", target_window="Program 1")
    for _ in range(5):
        assert manager._frame_buffer.capture_once() is True
    manager.stop()

    preview = manager.preview(started["recording_id"], cursor=1, limit=2)

    assert preview["ok"] is True
    assert preview["cursor"] == 1
    assert preview["limit"] == 2
    assert preview["returned_frame_count"] == 2
    assert preview["total_frame_count"] >= 5
    assert preview["next_cursor"] == 3
    assert len(preview["frames"]) == 2


def test_embedded_recording_preview_fetches_paginated_pages() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "Pyautogui_server_for_window"
        / "bridge"
        / "windows_pyautogui_bridge_server.py"
    ).read_text(encoding="utf-8")

    assert "cursor=${recordingPreviewCursor}" in source
    assert "limit=${recordingPreviewLimit}" in source
    assert "recordingPreviewNextCursor" in source


def test_recording_package_route_is_not_an_unauthenticated_local_setup_route() -> None:
    module = _load_packaged_helper_module()

    assert module.Handler._is_local_setup_path("/recordings/rec-20260827T010203-12345678", "GET") is True
    assert module.Handler._is_local_setup_path("/recordings/rec-20260827T010203-12345678/package", "GET") is False
    assert module.Handler._is_local_setup_path("/recordings/rec-20260827T010203-12345678/preview", "GET") is True


def test_recording_console_routes_do_not_require_pairing_from_a_saved_worker_connection(tmp_path: Path) -> None:
    module = _load_helper_module()
    module.TOKEN = ""
    module.PAIRING_MANAGER = module.PairingManager(tmp_path / "pairing.json")
    handler = object.__new__(module.Handler)
    handler.client_address = ("192.168.50.10", 54321)
    handler.headers = {}

    assert handler._has_route_access("/recordings", "GET") is True
    assert handler._has_route_access("/recordings/status", "GET") is True
    assert handler._has_route_access("/recordings/start", "POST") is True
    assert handler._has_route_access("/recordings/checkpoint", "POST") is True
    assert handler._has_route_access("/recordings/stop", "POST") is True
    assert handler._has_route_access("/recordings/rec-20260827T010203-12345678/preview", "GET") is True
    assert handler._has_route_access("/recordings/rec-20260827T010203-12345678/save", "POST") is True
    assert handler._has_route_access("/recordings/rec-20260827T010203-12345678", "DELETE") is True
    assert handler._has_route_access("/recordings/rec-20260827T010203-12345678/package", "GET") is False
    assert handler._has_route_access("/update/status", "GET") is False


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_public_discovery_route_does_not_expose_protected_health(loader, tmp_path: Path) -> None:
    module = loader()
    module.TOKEN = "saved-connection-secret"
    module.PAIRING_MANAGER = module.PairingManager(tmp_path / "pairing.json")
    handler = object.__new__(module.Handler)
    handler.client_address = ("192.168.50.146", 54321)
    handler.headers = {}

    assert handler._has_route_access("/discovery", "GET") is True
    assert handler._has_route_access("/health", "GET") is False
    assert handler._has_route_access("/update/status", "GET") is False


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_compact_ping_is_plaintext_public_and_not_written_to_request_audit(loader, tmp_path: Path) -> None:
    module = loader()
    module.TOKEN = "saved-connection-secret"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/ping", timeout=5) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "text/plain"
            assert response.read().decode("ascii") == f"ok {module.BRIDGE_RELEASE_VERSION}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.TOKEN = ""

    assert not (module.ARTIFACT_ROOT / "bridge_requests.jsonl").exists()


@pytest.mark.parametrize("loader", [_load_helper_module, _load_packaged_helper_module])
def test_local_legacy_discovery_is_compact_and_not_written_to_request_audit(loader, tmp_path: Path) -> None:
    module = loader()
    module.TOKEN = "saved-connection-secret"
    module.ARTIFACT_ROOT = tmp_path / "artifacts"
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/discovery", timeout=5) as response:
            payload = json.loads(response.read().decode("ascii"))
        assert payload == {
            "ok": True,
            "server_version": f"WindowsPyAutoGUIBridge/{module.BRIDGE_RELEASE_VERSION}",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        module.TOKEN = ""

    assert not (module.ARTIFACT_ROOT / "bridge_requests.jsonl").exists()


def test_recording_manager_persists_bounded_exception_window_on_same_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (320, 240), color=(30, 80, 120)),
        frame_buffer_fps=2,
        frame_buffer_retention_sec=20,
        exception_pre_sec=3,
        exception_post_sec=2,
    )
    started = manager.start(name="exception evidence", target_app="Program 1", target_window="Program 1")
    for elapsed in (1, 3, 5, 7, 9):
        clock["value"] = 100.0 + elapsed
        assert manager._frame_buffer.capture_once() is True
    clock["value"] = 106.0
    marked = manager.record_exception(
        failure_code="LOCATOR_NOT_FOUND",
        detail="expected completion image was not found",
    )
    clock["value"] = 110.0
    completed = manager.stop()

    assert marked["ok"] is True
    assert marked["timeline_id"] == started["timeline_id"]
    timeline = completed["time_series_evidence"]
    assert timeline["timeline_id"] == started["timeline_id"]
    assert timeline["exception_window_count"] == 1
    window = timeline["exception_windows"][0]
    assert window["failure_code"] == "LOCATOR_NOT_FOUND"
    assert window["pre_window_ms"] == 3000
    assert window["post_window_ms"] == 2000
    assert [item["at_ms"] for item in timeline["frames"] if item["frame_id"] in window["frame_ids"]] == [
        3000,
        5000,
        7000,
    ]
    assert all(Path(item["artifact_path"]).is_file() for item in timeline["frames"])
    assert manager._frame_buffer.status()["sampled_frame_count"] == 0


def test_recording_manager_pins_exception_window_before_rolling_history_eviction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaged_helper_module()
    pillow = pytest.importorskip("PIL.Image")
    clock = {"value": 100.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        screenshot_provider=lambda: pillow.new("RGB", (320, 240), color=(30, 80, 120)),
        frame_buffer_fps=2,
        frame_buffer_retention_sec=20,
        exception_pre_sec=3,
        exception_post_sec=2,
    )
    started = manager.start(name="eviction proof", target_app="Program 1", target_window="Program 1")
    for elapsed in (1, 3, 5):
        clock["value"] = 100.0 + elapsed
        assert manager._frame_buffer.capture_once() is True
    clock["value"] = 106.0
    manager.record_exception(failure_code="LOCATOR_NOT_FOUND", detail="pin this window")
    clock["value"] = 107.0
    assert manager._frame_buffer.capture_once() is True

    # Force the rolling history beyond retention before the recording is stopped.
    clock["value"] = 140.0
    assert manager._frame_buffer.capture_once() is True
    completed = manager.stop()

    timeline = completed["time_series_evidence"]
    assert timeline["timeline_id"] == started["timeline_id"]
    assert timeline["exception_window_count"] == 1
    window = timeline["exception_windows"][0]
    pinned_frames = [item for item in timeline["frames"] if item["frame_id"] in window["frame_ids"]]
    assert [item["at_ms"] for item in pinned_frames] == [3000, 5000, 7000]
    assert all(Path(item["artifact_path"]).is_file() for item in pinned_frames)


def test_recording_exception_marker_is_redacted_and_requires_active_recording(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()
    manager = module.RecordingManager(tmp_path, listener_factory=lambda _manager: [])

    idle = manager.record_exception(failure_code="TOKEN_secret-value", detail="api_token=do-not-save")
    assert idle["failure_code"] == "SKILL_RECORDING_NOT_ACTIVE"

    manager.start(name="redacted exception", target_app="Program 1", target_window="Program 1")
    marked = manager.record_exception(
        failure_code="LOCATOR_NOT_FOUND",
        detail="token=secret-value expected image missing",
    )
    completed = manager.stop()

    serialized = json.dumps(completed["exceptions"])
    assert marked["failure_code"] == "LOCATOR_NOT_FOUND"
    assert "secret-value" not in serialized


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

    stop_requests: list[str] = []

    class FakeOverlayWindow:
        def __init__(self, on_stop) -> None:
            self.elapsed: list[float] = []
            self.closed = False
            self.on_stop = on_stop

        def update_elapsed(self, elapsed_s: float) -> None:
            self.elapsed.append(elapsed_s)

        def pump(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    def create_window(on_stop) -> FakeOverlayWindow:
        window = FakeOverlayWindow(on_stop)
        windows.append(window)
        return window

    controller = module.RecordingOverlayController(
        platform_name="win32",
        window_factory=create_window,
        monotonic=lambda: 12.5,
        poll_interval=0.005,
        on_stop=lambda: stop_requests.append("stop"),
    )
    controller.show("rec-overlay-test", 10.0)
    deadline = time.monotonic() + 1.0
    while not controller.status()["visible"] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert controller.status() == {"available": True, "visible": True, "error": None}
    assert windows and windows[0].elapsed[-1] == pytest.approx(2.5)
    windows[0].on_stop()
    deadline = time.monotonic() + 1.0
    while stop_requests != ["stop"] and time.monotonic() < deadline:
        time.sleep(0.005)
    assert stop_requests == ["stop"]

    controller.hide()
    deadline = time.monotonic() + 1.0
    while controller.status()["visible"] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert windows[0].closed is True
    assert controller.status()["visible"] is False
    controller.shutdown()


def test_recording_overlay_stop_returns_without_waiting_for_recording_finalization() -> None:
    module = _load_packaged_helper_module()
    windows: list[Any] = []
    stop_started = threading.Event()
    release_stop = threading.Event()

    class FakeOverlayWindow:
        def __init__(self, on_stop) -> None:
            self.on_stop = on_stop

        def update_elapsed(self, _elapsed_s: float) -> None:
            return None

        def pump(self) -> None:
            return None

        def close(self) -> None:
            return None

    def create_window(on_stop) -> FakeOverlayWindow:
        window = FakeOverlayWindow(on_stop)
        windows.append(window)
        return window

    def slow_finalize() -> None:
        stop_started.set()
        release_stop.wait(timeout=2.0)

    controller = module.RecordingOverlayController(
        platform_name="win32",
        window_factory=create_window,
        poll_interval=0.005,
        on_stop=slow_finalize,
    )
    controller.show("rec-overlay-async-stop", time.monotonic())
    deadline = time.monotonic() + 1.0
    while not controller.status()["visible"] and time.monotonic() < deadline:
        time.sleep(0.005)

    click_returned = threading.Event()

    def click_stop() -> None:
        windows[0].on_stop()
        click_returned.set()

    click_thread = threading.Thread(target=click_stop)
    click_thread.start()
    try:
        assert stop_started.wait(timeout=1.0)
        assert click_returned.wait(timeout=0.2), "overlay STOP blocked on recording finalization"
    finally:
        release_stop.set()
        click_thread.join(timeout=1.0)
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


def test_recording_manager_marks_overlay_stop_click_as_recording_control(tmp_path: Path) -> None:
    module = _load_packaged_helper_module()

    class OverlayWithStopEvidence(_FakeRecordingOverlay):
        def consume_stop_request(self) -> dict[str, Any]:
            return {"control": "overlay_stop", "x": 984, "y": 46}

    overlay = OverlayWithStopEvidence()
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        overlay_controller=overlay,
    )
    manager.start(name="Program 1 demo", target_app="Program 1", target_window="Program 1")
    manager.record_event({"kind": "mouse_click", "x": 984, "y": 46, "button": "left"})

    stopped = manager.stop()

    assert stopped["events"][-1]["recording_control"] == "overlay_stop"


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


def test_frozen_runtime_dependency_probe_imports_bundled_lazy_module(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_packaged_helper_module()
    imported: list[str] = []
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(module.importlib, "import_module", lambda name: imported.append(name) or object())

    assert module._runtime_module_available("pynput") is True
    assert imported == ["pynput"]


def test_self_updater_verifies_restart_through_compact_ping_route() -> None:
    module = _load_packaged_helper_module()
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert 'f"http://127.0.0.1:{PORT}/ping"' in source


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
    assert started["schema"] == "atr.equipment_recording.v3"
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

    assert len(stopped["events"]) == 1
    assert stopped["events"][0]["kind"] == "hotkey"
    assert stopped["events"][0]["keys"] == ["ctrl", "s"]


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


def test_recording_manager_captures_initial_typing_language(tmp_path: Path) -> None:
    module = _load_helper_module()
    language = {
        "status": "available",
        "layout_id": "00000412",
        "locale": "ko_KR",
        "language": "ko",
        "ime_mode": "native",
        "typing_mode": "ko",
    }
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        input_language_provider=lambda: dict(language),
    )

    started = manager.start(name="typing", target_app="editor", target_window="editor")

    assert started["input_language"] == language
    assert started["input_language_history"] == [{"at_ms": 0, **language}]


def test_windows_input_language_state_reads_layout_and_ime_mode() -> None:
    module = _load_helper_module()

    class FakeUser32:
        @staticmethod
        def GetForegroundWindow() -> int:
            return 100

        @staticmethod
        def GetWindowThreadProcessId(_hwnd: int, _process_id: object) -> int:
            return 42

        @staticmethod
        def GetKeyboardLayout(_thread_id: int) -> int:
            return 0x04120412

    class FakeImm32:
        @staticmethod
        def ImmGetContext(_hwnd: int) -> int:
            return 200

        @staticmethod
        def ImmGetConversionStatus(_context: int, conversion: object, sentence: object) -> int:
            conversion._obj.value = 0x0001
            sentence._obj.value = 0
            return 1

        @staticmethod
        def ImmReleaseContext(_hwnd: int, _context: int) -> int:
            return 1

    state = module._windows_input_language_state(
        user32=FakeUser32(),
        imm32=FakeImm32(),
        windows_locale={0x0412: "ko_KR"},
    )

    assert state == {
        "status": "available",
        "layout_id": "00000412",
        "locale": "ko_KR",
        "language": "ko",
        "ime_mode": "native",
        "typing_mode": "ko",
    }


def test_windows_input_language_state_uses_default_ime_window_fallback() -> None:
    module = _load_helper_module()

    class FakeUser32:
        @staticmethod
        def GetForegroundWindow() -> int:
            return 100

        @staticmethod
        def GetWindowThreadProcessId(_hwnd: int, _process_id: object) -> int:
            return 42

        @staticmethod
        def GetKeyboardLayout(_thread_id: int) -> int:
            return 0x04120412

        @staticmethod
        def SendMessageW(_hwnd: int, message: int, command: int, _value: int) -> int:
            assert message == 0x0283
            assert command == 0x0001
            return 0x0001

    class FakeImm32:
        @staticmethod
        def ImmGetContext(_hwnd: int) -> int:
            return 0

        @staticmethod
        def ImmGetDefaultIMEWnd(_hwnd: int) -> int:
            return 300

    state = module._windows_input_language_state(
        user32=FakeUser32(),
        imm32=FakeImm32(),
        windows_locale={0x0412: "ko_KR"},
    )

    assert state["layout_id"] == "00000412"
    assert state["ime_mode"] == "native"
    assert state["typing_mode"] == "ko"


def test_protocol_sequence_replays_recorded_input_language(monkeypatch) -> None:
    target = {
        "layout_id": "00000412",
        "locale": "ko_KR",
        "language": "ko",
        "ime_mode": "alphanumeric",
        "typing_mode": "latin",
    }
    for loader in (_load_helper_module, _load_packaged_helper_module):
        module = loader()
        calls: list[dict[str, str]] = []
        monkeypatch.setattr(
            module,
            "_set_windows_input_language",
            lambda value, calls=calls: calls.append(dict(value)) or {"ok": True, "observed": dict(value)},
        )
        trace: list[dict[str, object]] = []

        result = module._execute_protocol_sequence(
            _FakePyAutoGUI(),
            program_id="input_language_replay",
            payload={"sequence": [{"action": "set_input_language", **target}]},
            run_id="run-input-language",
            specimen_id="specimen-input-language",
            trace=trace,
        )

        assert result["ok"] is True
        assert calls == [target]
        assert trace[-1]["status"] == "ok"


def test_set_windows_input_language_restores_layout_and_ime_mode() -> None:
    module = _load_helper_module()

    class FakeUser32:
        def __init__(self) -> None:
            self.loaded: list[tuple[str, int]] = []
            self.activated: list[tuple[int, int]] = []
            self.messages: list[tuple[int, int, int, int]] = []

        @staticmethod
        def GetForegroundWindow() -> int:
            return 100

        def LoadKeyboardLayoutW(self, layout_id: str, flags: int) -> int:
            self.loaded.append((layout_id, flags))
            return 0x04120412

        def ActivateKeyboardLayout(self, layout: int, flags: int) -> int:
            self.activated.append((layout, flags))
            return layout

        def PostMessageW(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
            self.messages.append((hwnd, message, wparam, lparam))
            return 1

    class FakeImm32:
        def __init__(self) -> None:
            self.conversions: list[tuple[int, int, int]] = []

        @staticmethod
        def ImmGetContext(_hwnd: int) -> int:
            return 200

        @staticmethod
        def ImmGetConversionStatus(_context: int, conversion: object, sentence: object) -> int:
            conversion._obj.value = 0x0001
            sentence._obj.value = 7
            return 1

        def ImmSetConversionStatus(self, context: int, conversion: int, sentence: int) -> int:
            self.conversions.append((context, conversion, sentence))
            return 1

        @staticmethod
        def ImmReleaseContext(_hwnd: int, _context: int) -> int:
            return 1

    user32 = FakeUser32()
    imm32 = FakeImm32()
    result = module._set_windows_input_language(
        {
            "layout_id": "00000412",
            "locale": "ko_KR",
            "language": "ko",
            "ime_mode": "alphanumeric",
            "typing_mode": "latin",
        },
        user32=user32,
        imm32=imm32,
    )

    assert result["ok"] is True
    assert user32.loaded == [("00000412", 0x00000001)]
    assert user32.activated == [(0x04120412, 0x00000100)]
    assert user32.messages == [(100, 0x0050, 0, 0x04120412)]
    assert imm32.conversions == [(200, 0, 7)]


def test_recording_keyboard_capture_records_typing_language_changes_once(tmp_path: Path) -> None:
    module = _load_helper_module()
    korean = {
        "status": "available",
        "layout_id": "00000412",
        "locale": "ko_KR",
        "language": "ko",
        "ime_mode": "native",
        "typing_mode": "ko",
    }
    latin = {**korean, "ime_mode": "alphanumeric", "typing_mode": "latin"}
    states = iter((korean, korean, latin, latin))
    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        input_language_provider=lambda: dict(next(states)),
    )
    manager.start(name="typing", target_app="editor", target_window="editor")
    capture = module._RecordingKeyboardCapture(manager)

    capture.on_press("a")
    capture.on_press("b")
    capture.on_press("c")
    stopped = manager.stop()

    assert [event["kind"] for event in stopped["events"]] == [
        "key_press",
        "input_language_changed",
        "key_press",
        "key_press",
    ]
    assert stopped["events"][0]["input_language"]["typing_mode"] == "ko"
    assert stopped["events"][1]["input_language"]["typing_mode"] == "latin"
    assert stopped["events"][2]["input_language"]["typing_mode"] == "latin"
    assert stopped["events"][3]["input_language"]["typing_mode"] == "latin"
    assert len(stopped["input_language_history"]) == 2


def test_recording_language_probe_failure_does_not_block_recording(tmp_path: Path) -> None:
    module = _load_helper_module()

    def unavailable() -> dict[str, str]:
        raise OSError("input method unavailable")

    manager = module.RecordingManager(
        tmp_path,
        listener_factory=lambda _manager: [],
        input_language_provider=unavailable,
    )

    started = manager.start(name="typing", target_app="editor", target_window="editor")
    capture = module._RecordingKeyboardCapture(manager)
    capture.on_press("a")
    stopped = manager.stop()

    assert started["ok"] is True
    assert started["input_language"]["status"] == "unavailable"
    assert stopped["events"][0]["kind"] == "key_press"
    assert stopped["events"][0]["input_language"]["status"] == "unavailable"


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


def test_windows_bridge_resolves_normalized_search_roi_against_current_screen(tmp_path: Path, monkeypatch) -> None:
    for index, module in enumerate((_load_helper_module(), _load_packaged_helper_module())):
        monkeypatch.setattr(module, "LOCATOR_ROOT", tmp_path / f"normalized-roi-{index}")
        fake = _FakePyAutoGUI()

        module._locate_on_screen(
            fake,
            {
                "image_candidates": [_recorded_image_candidate("tight")],
                "region_normalized": [0.1, 0.2, 0.5, 0.4],
            },
            run_id="run-normalized-roi",
            specimen_id="specimen-normalized-roi",
        )

        assert fake.locate_calls[-1][1]["region"] == (192, 216, 960, 432)


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


def test_windows_bridge_inline_locator_tolerates_hover_state_at_recorded_origin(tmp_path: Path) -> None:
    """A recorded hover background must not hide an otherwise unchanged control."""
    from PIL import Image, ImageDraw

    candidate = Image.new("RGB", (64, 64), "#f4f4f4")
    candidate_draw = ImageDraw.Draw(candidate)
    candidate_draw.rounded_rectangle((4, 4, 43, 43), radius=10, fill="#d9d9d9")
    candidate_draw.line((16, 23, 31, 23), fill="#222222", width=2)
    candidate_draw.line((23, 16, 23, 31), fill="#222222", width=2)

    screen = Image.new("RGB", (320, 180), "#ffffff")
    screen_draw = ImageDraw.Draw(screen)
    screen_draw.rectangle((120, 20, 183, 83), fill="#f4f4f4")
    screen_draw.line((128, 45, 143, 45), fill="#222222", width=2)
    screen_draw.line((135, 38, 135, 53), fill="#222222", width=2)

    class _ScreenPyAutoGUI(_FakePyAutoGUI):
        def screenshot(self, region: tuple[int, int, int, int] | None = None) -> Image.Image:
            return screen.copy()

    for index, module in enumerate((_load_helper_module(), _load_packaged_helper_module())):
        path = tmp_path / f"hover-candidate-{index}.png"
        candidate.save(path)
        attempted, match = module._best_inline_image_match(
            _ScreenPyAutoGUI(),
            [
                (
                    str(path),
                    {"confidence": 0.99, "crop_origin": [120, 20]},
                    100.0,
                )
            ],
        )

        assert attempted is True
        assert match == (120, 20, 64, 64)


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


def test_input_language_action_is_advertised_and_accepted_by_program_contract() -> None:
    module = _load_packaged_helper_module()
    action = {
        "action": "set_input_language",
        "layout_id": "00000412",
        "locale": "ko_KR",
        "language": "ko",
        "ime_mode": "alphanumeric",
        "typing_mode": "latin",
    }

    result = module._validate_program_definition(
        {
            "schema": module.PROGRAM_SCHEMA,
            "program_id": "input_language_contract_demo",
            "name": "Input language contract demo",
            "sequence": [action],
        }
    )
    capabilities = module._capability_catalog()

    assert result["ok"] is True
    assert "set_input_language" in capabilities["families"]["keyboard"]


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
        package = request(f"/recordings/{recording_id}/package")
        detail = request(f"/recordings/{recording_id}")
        listed = request("/recordings")

        assert status["status"] == "recording"
        assert stopped["status"] == "completed"
        assert saved["status"] == "saved"
        assert package["schema"] == "atr.equipment_recording_package.v1"
        assert package["recording"]["recording_id"] == recording_id
        assert detail["recording_id"] == recording_id
        assert [item["recording_id"] for item in listed["recordings"]] == [recording_id]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)




def test_recording_console_uses_start_control_and_native_overlay_stop_only() -> None:
    for module in (_load_helper_module(), _load_packaged_helper_module()):
        html = module.INDEX_HTML

        assert 'id="recordToggle"' in html
        assert 'id="recordStart"' not in html
        assert 'id="recordStop"' not in html
        assert "const RECORDING_COUNTDOWN_SECONDS = 5;" in html
        assert "function beginRecordingCountdown()" in html
        assert "function syncRecordingToggle()" in html
        assert "STOP RECORDING" not in html
        assert "stopActiveRecording" not in html
        assert '$(' + '"recordToggle").hidden=active' in html
        assert "async function refreshRecordingStatus()" in html
        assert "function startRecordingStatusWatch()" in html
        assert 'call("/recordings/status")' in html
        assert 'id="recordingCountdown"' in html
        assert '$("recordingCountdown").textContent=remaining' in html
        assert 'id="recordingPreview"' in html
        assert '/preview?cursor=${recordingPreviewCursor}&limit=${recordingPreviewLimit}`' in html
        assert 'id="recordingPreviewPrevious"' in html
        assert 'id="recordingPreviewNext"' in html
        assert 'id="managerSkillsView"' not in html
        assert 'id="recordSkill"' not in html
        assert 'id="recordingOverlay"' not in html
        assert 'class="record-banner"' not in html
