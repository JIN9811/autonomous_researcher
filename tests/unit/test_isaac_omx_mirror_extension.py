"""Tests for the Isaac Sim in-process ROBOTIS OMX mirror extension."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import time
import types
from pathlib import Path
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = REPO_ROOT / "sim" / "robotis_omx" / "extensions" / "atr.omx.mirror"
EXTENSION_MODULE = EXTENSION_ROOT / "atr" / "omx" / "mirror" / "extension.py"


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeSettings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, key: str) -> object:
        return self.values.get(key)

    def get_as_string(self, key: str) -> str:
        value = self.values.get(key)
        return "" if value is None else str(value)

    def get_as_int(self, key: str) -> int:
        value = self.values.get(key)
        return int(value) if value is not None else 0

    def get_as_bool(self, key: str) -> bool:
        value = self.values.get(key)
        return bool(value)


def _install_fake_isaac_modules(monkeypatch, settings: _FakeSettings) -> tuple[list, list[str], list[str]]:
    callbacks: list = []
    opened_stages: list[str] = []
    timeline_events: list[str] = []

    omni = types.ModuleType("omni")
    omni_ext = types.ModuleType("omni.ext")

    class _FakeIExt:
        def __init__(self) -> None:
            self._fake_iext_initialized = True

    omni_ext.IExt = _FakeIExt
    omni.ext = omni_ext

    omni_kit = types.ModuleType("omni.kit")
    omni_kit_app = types.ModuleType("omni.kit.app")

    class _FakeStream:
        def create_subscription_to_pop(self, callback, name=""):
            callbacks.append((name, callback))
            return {"name": name, "callback": callback}

    class _FakeApp:
        def get_update_event_stream(self):
            return _FakeStream()

    omni_kit_app.get_app = lambda: _FakeApp()
    omni_kit.app = omni_kit_app
    omni.kit = omni_kit

    omni_usd = types.ModuleType("omni.usd")

    def _open_stage(path: str):
        opened_stages.append(path)
        return True

    omni_usd.get_context = lambda: types.SimpleNamespace(get_stage=lambda: None, open_stage=_open_stage)
    omni.usd = omni_usd

    omni_timeline = types.ModuleType("omni.timeline")

    class _FakeTimeline:
        def play(self):
            timeline_events.append("play")

        def stop(self):
            timeline_events.append("stop")

        def is_playing(self):
            return "play" in timeline_events and (not timeline_events or timeline_events[-1] != "stop")

    omni_timeline.get_timeline_interface = lambda: _FakeTimeline()
    omni.timeline = omni_timeline

    carb = types.ModuleType("carb")
    carb_settings = types.ModuleType("carb.settings")
    carb_settings.get_settings = lambda: settings
    carb.settings = carb_settings

    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ext", omni_ext)
    monkeypatch.setitem(sys.modules, "omni.kit", omni_kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", omni_kit_app)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)
    monkeypatch.setitem(sys.modules, "omni.timeline", omni_timeline)
    monkeypatch.setitem(sys.modules, "carb", carb)
    monkeypatch.setitem(sys.modules, "carb.settings", carb_settings)
    return callbacks, opened_stages, timeline_events


def _load_extension_module():
    spec = importlib.util.spec_from_file_location("atr_omx_mirror_extension_under_test", EXTENSION_MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json_get(url: str) -> dict:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def test_extension_manifest_registers_python_module() -> None:
    manifest = EXTENSION_ROOT / "config" / "extension.toml"
    text = manifest.read_text(encoding="utf-8")
    assert 'title = "ATR ROBOTIS OMX Mirror Receiver"' in text
    assert 'name = "atr.omx.mirror.extension"' in text
    assert '"omni.kit.app"' not in text
    assert '"omni.usd"' not in text


def test_extension_startup_serves_receiver_inside_isaac_process(monkeypatch) -> None:
    port = _free_tcp_port()
    callbacks, opened_stages, timeline_events = _install_fake_isaac_modules(
        monkeypatch,
        _FakeSettings(
            {
                "/exts/atr.omx.mirror/enabled": True,
                "/exts/atr.omx.mirror/host": "127.0.0.1",
                "/exts/atr.omx.mirror/port": port,
                "/exts/atr.omx.mirror/scene": str(REPO_ROOT / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"),
                "/exts/atr.omx.mirror/useCurrentStage": True,
                "/exts/atr.omx.mirror/openSceneOnStartup": True,
                "/exts/atr.omx.mirror/playTimelineOnStartup": True,
            }
        ),
    )
    module = _load_extension_module()
    extension = module.AtrOmxMirrorExtension()
    assert extension._fake_iext_initialized is True

    try:
        extension.on_startup("atr.omx.mirror")
        deadline = time.time() + 3
        health = {}
        while time.time() < deadline:
            try:
                health = _json_get(f"http://127.0.0.1:{port}/health")
                break
            except OSError:
                time.sleep(0.05)
        assert health["ok"] is True
        assert health["apply_mode"] == "deferred_update_tick"
        assert callbacks and callbacks[0][0] == "atr-isaac-omx-mirror-apply"
        assert opened_stages == [str(REPO_ROOT / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda")]
        assert timeline_events == []

        payload = {
            "session_id": "test-extension-session",
            "sample_index": 1,
            "joint_state": [
                {
                    "motor_id": 11,
                    "isaac_joint_path": "/World/Robot/Geometry/link0/link1/Joint1",
                    "position_deg": 12.5,
                    "unit": "deg",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(f"http://127.0.0.1:{port}/joints", data=body, method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=2) as response:
            queued = json.loads(response.read().decode("utf-8"))
        assert queued["ok"] is True
        assert queued["status"] == "queued"
        assert _json_get(f"http://127.0.0.1:{port}/state")["last_payload_summary"]["session_id"] == "test-extension-session"
    finally:
        extension.on_shutdown()

    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            _json_get(f"http://127.0.0.1:{port}/health")
            time.sleep(0.05)
        except OSError:
            break
    else:
        raise AssertionError("receiver port remained open after extension shutdown")


def test_extension_defers_timeline_play_until_update_ticks(monkeypatch) -> None:
    port = _free_tcp_port()
    callbacks, _opened_stages, timeline_events = _install_fake_isaac_modules(
        monkeypatch,
        _FakeSettings(
            {
                "/exts/atr.omx.mirror/enabled": True,
                "/exts/atr.omx.mirror/host": "127.0.0.1",
                "/exts/atr.omx.mirror/port": port,
                "/exts/atr.omx.mirror/scene": str(REPO_ROOT / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"),
                "/exts/atr.omx.mirror/useCurrentStage": True,
                "/exts/atr.omx.mirror/openSceneOnStartup": False,
                "/exts/atr.omx.mirror/playTimelineOnStartup": True,
                "/exts/atr.omx.mirror/playTimelineDelayTicks": 2,
            }
        ),
    )
    module = _load_extension_module()
    extension = module.AtrOmxMirrorExtension()

    try:
        extension.on_startup("atr.omx.mirror")
        assert [name for name, _callback in callbacks] == [
            "atr-isaac-omx-mirror-apply",
            "atr-isaac-omx-mirror-delayed-play",
        ]
        assert timeline_events == []

        callbacks[1][1](object())
        assert timeline_events == []

        callbacks[1][1](object())
        assert timeline_events == ["play"]

        callbacks[1][1](object())
        assert timeline_events == ["play"]
    finally:
        extension.on_shutdown()
