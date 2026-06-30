"""Tests for the Isaac Sim in-process ROBOTIS OMX mirror extension."""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
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


class _FakeAttr:
    def __init__(self, value=None) -> None:
        self.value = value

    def Set(self, value):  # noqa: N802 - USD-style fake
        self.value = value

    def Get(self):  # noqa: N802 - USD-style fake
        return self.value


class _FakePrim:
    def __init__(self, path: str) -> None:
        self.path = path
        self.attrs = {"xformOp:translate": _FakeAttr((0.4, 0.3, 0.015))}

    def IsValid(self):  # noqa: N802 - USD-style fake
        return True

    def GetAttribute(self, name: str):  # noqa: N802 - USD-style fake
        return self.attrs.get(name)

    def CreateAttribute(self, name: str, _type_name):  # noqa: N802 - USD-style fake
        attr = _FakeAttr()
        self.attrs[name] = attr
        return attr


class _FakeStage:
    def __init__(self, paths: list[str]) -> None:
        self.prims = {path: _FakePrim(path) for path in paths}

    def GetPrimAtPath(self, path: str):  # noqa: N802 - USD-style fake
        return self.prims.get(path)


class _FakeXformOp:
    def __init__(self, prim: _FakePrim, name: str) -> None:
        self.prim = prim
        self.name = name

    def GetOpName(self):  # noqa: N802 - USD-style fake
        return self.name

    def Set(self, value):  # noqa: N802 - USD-style fake
        attr = self.prim.attrs.get(self.name)
        if attr is None:
            attr = self.prim.CreateAttribute(self.name, "double")
        attr.Set(value)


class _FakeUsdXformable:
    def __init__(self, prim: _FakePrim) -> None:
        self.prim = prim

    def GetOrderedXformOps(self):  # noqa: N802 - USD-style fake
        order_attr = self.prim.attrs.get("xformOpOrder")
        if order_attr is not None:
            names = [str(name) for name in (order_attr.Get() or [])]
        else:
            names = [name for name in self.prim.attrs if name.startswith("xformOp:")]
        return [_FakeXformOp(self.prim, name) for name in names if name in self.prim.attrs]

    def AddRotateZOp(self, precision=None):  # noqa: N802 - USD-style fake
        if "xformOp:rotateZ" not in self.prim.attrs:
            self.prim.CreateAttribute("xformOp:rotateZ", precision or "double")
        order_attr = self.prim.attrs.get("xformOpOrder")
        order = list(order_attr.Get() or []) if order_attr is not None else []
        if "xformOp:rotateZ" not in order:
            order.append("xformOp:rotateZ")
            if order_attr is None:
                order_attr = self.prim.CreateAttribute("xformOpOrder", "token[]")
            order_attr.Set(order)
        return _FakeXformOp(self.prim, "xformOp:rotateZ")

    def SetXformOpOrder(self, ops):  # noqa: N802 - USD-style fake
        order_attr = self.prim.attrs.get("xformOpOrder")
        if order_attr is None:
            order_attr = self.prim.CreateAttribute("xformOpOrder", "token[]")
        order_attr.Set([op.GetOpName() for op in ops])


def _install_fake_pxr_usdgeom(monkeypatch) -> None:
    usd_geom_module = types.SimpleNamespace(
        Xformable=_FakeUsdXformable,
        XformOp=types.SimpleNamespace(PrecisionDouble="double"),
    )
    pxr_module = types.ModuleType("pxr")
    pxr_module.UsdGeom = usd_geom_module
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", usd_geom_module)


def _install_fake_isaac_modules(monkeypatch, settings: _FakeSettings, current_stage=None) -> tuple[list, list[str], list[str]]:
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

    omni_usd.get_context = lambda: types.SimpleNamespace(get_stage=lambda: current_stage, open_stage=_open_stage)
    omni.usd = omni_usd

    omni_timeline = types.ModuleType("omni.timeline")

    class _FakeTimelineEventType:
        PLAY = 1
        STOP = 2

    class _FakeTimelineEventStream:
        def create_subscription_to_pop_by_type(self, event_type, callback):
            callbacks.append((f"timeline-event:{event_type}", callback))
            return {"event_type": event_type, "callback": callback}

    class _FakeTimeline:
        def get_timeline_event_stream(self):
            return _FakeTimelineEventStream()

        def play(self):
            timeline_events.append("play")

        def stop(self):
            timeline_events.append("stop")

        def is_playing(self):
            return "play" in timeline_events and (not timeline_events or timeline_events[-1] != "stop")

    omni_timeline.TimelineEventType = _FakeTimelineEventType
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
    assert "specimenPoseOnPlay = true" in text
    assert "specimenPoseAutostartRealsense = false" in text
    assert 'specimenPoseFrameManifest = "/tmp/atr_lerobot_latest_frame/latest_frame.json"' in text
    assert '"omni.kit.app"' not in text
    assert '"omni.usd"' not in text


def test_specimen_pose_snapshot_updates_red_cube_translate() -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    snapshot = {
        "ok": True,
        "pose": {
            "position_isaac_world_mm": {
                "x": 123.0,
                "y": -45.0,
                "z": 18.5,
            }
        },
    }

    result = module._apply_specimen_pose_snapshot_to_stage(stage, snapshot, cube_path)

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["translate_m"] == [0.123, -0.045, 0.0185]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.123, -0.045, 0.0185)


def test_specimen_pose_snapshot_updates_red_cube_yaw_rotate_z(monkeypatch) -> None:
    _install_fake_pxr_usdgeom(monkeypatch)
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:scale"] = _FakeAttr((0.03, 0.03, 0.03))
    stage.prims[cube_path].attrs["xformOpOrder"] = _FakeAttr(["xformOp:translate", "xformOp:scale"])
    snapshot = {
        "ok": True,
        "pose": {
            "position_isaac_world_mm": {"x": 123.0, "y": -45.0, "z": 18.5},
            "orientation_deg": {"yaw": -24.0},
        },
    }

    result = module._apply_specimen_pose_snapshot_to_stage(stage, snapshot, cube_path)

    assert result["ok"] is True
    assert result["orientation_deg"]["yaw"] == -24.0
    assert stage.prims[cube_path].attrs["xformOp:rotateZ"].value == -24.0
    assert stage.prims[cube_path].attrs["xformOpOrder"].value == ["xformOp:translate", "xformOp:rotateZ", "xformOp:scale"]


def test_specimen_pose_snapshot_failure_keeps_cube_translate_and_reports_alarm() -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    before = stage.prims[cube_path].attrs["xformOp:translate"].value
    snapshot = {
        "ok": False,
        "failure_code": "SPECIMEN_NOT_DETECTED",
        "message": "No red specimen contour was detected.",
    }

    result = module._apply_specimen_pose_snapshot_to_stage(stage, snapshot, cube_path)

    assert result["ok"] is False
    assert result["status"] == "snapshot_failed"
    assert result["failure_code"] == "SPECIMEN_NOT_DETECTED"
    assert "큐브가 제 위치에 없거나 검출되지 않았습니다" in result["message"]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == before


def test_run_specimen_pose_snapshot_uses_existing_ros_wrapper() -> None:
    module = _load_extension_module()
    calls = []

    def _fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 10,
                    "y": 20,
                    "z": 30,
                }
            },
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=f"status line\n{json.dumps(payload)}\n", stderr="")

    result = module._run_specimen_pose_snapshot(
        REPO_ROOT,
        REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh",
        {"specimen_id": "redcube-play"},
        timeout_sec=3.5,
        runner=_fake_runner,
    )

    assert result["ok"] is True
    assert result["pose"]["position_isaac_world_mm"] == {"x": 10, "y": 20, "z": 30}
    assert calls[0][0] == [
        str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
        json.dumps({"specimen_id": "redcube-play"}, ensure_ascii=True),
    ]
    assert calls[0][1]["cwd"] == str(REPO_ROOT)
    assert calls[0][1]["timeout"] == 3.5


def test_run_and_apply_specimen_pose_uses_pending_file_before_snapshot(tmp_path: Path, monkeypatch) -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 111,
                        "y": 222,
                        "z": 15.2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_current_gui_stage", lambda: stage)

    result = module._run_and_apply_specimen_pose_snapshot(
        REPO_ROOT,
        tmp_path / "missing_snapshot_script.sh",
        {"pending_pose_path": str(pending_path)},
        timeout_sec=0.5,
        red_cube_path=cube_path,
    )

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["snapshot_path"] == str(pending_path)
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.111, 0.222, 0.0152)


def test_delayed_timeline_play_runs_specimen_snapshot_before_play(monkeypatch) -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    callbacks, _opened_stages, timeline_events = _install_fake_isaac_modules(monkeypatch, _FakeSettings({}), current_stage=stage)
    module = _load_extension_module()
    events = []

    def _before_play():
        events.append("snapshot")
        return module._apply_specimen_pose_snapshot_to_stage(
            stage,
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 77,
                        "y": 88,
                        "z": 19,
                    }
                },
            },
            cube_path,
        )

    module.install_delayed_timeline_play_subscription(1, before_play=_before_play)

    callbacks[0][1](object())

    assert events == ["snapshot"]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.077, 0.088, 0.019)
    assert timeline_events == ["play"]


def test_delayed_timeline_play_warns_when_specimen_snapshot_fails(monkeypatch) -> None:
    warnings = []
    callbacks, _opened_stages, timeline_events = _install_fake_isaac_modules(monkeypatch, _FakeSettings({}))
    module = _load_extension_module()
    monkeypatch.setattr(module, "_log_warn", warnings.append)

    module.install_delayed_timeline_play_subscription(
        1,
        before_play=lambda: {
            "ok": False,
            "status": "snapshot_failed",
            "message": "큐브가 제 위치에 없거나 검출되지 않았습니다: SPECIMEN_NOT_DETECTED",
        },
    )

    callbacks[0][1](object())

    assert timeline_events == ["play"]
    assert len(warnings) == 1
    assert "큐브가 제 위치에 없거나 검출되지 않았습니다" in warnings[0]


def test_timeline_play_event_runs_specimen_snapshot_every_play(monkeypatch) -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    callbacks, _opened_stages, _timeline_events = _install_fake_isaac_modules(monkeypatch, _FakeSettings({}), current_stage=stage)
    module = _load_extension_module()
    calls: list[int] = []

    def _before_play():
        calls.append(len(calls) + 1)
        return module._apply_specimen_pose_snapshot_to_stage(
            stage,
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 200 + len(calls),
                        "y": 300 + len(calls),
                        "z": 15.2,
                    }
                },
            },
            cube_path,
        )

    module.install_timeline_play_specimen_pose_subscription(before_play=_before_play)

    assert callbacks[0][0] == "timeline-event:1"
    callbacks[0][1](types.SimpleNamespace(type=1))
    callbacks[0][1](types.SimpleNamespace(type=1))

    assert calls == [1, 2]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.202, 0.302, 0.0152)


def test_timeline_stop_event_does_not_run_specimen_snapshot(monkeypatch) -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    callbacks, _opened_stages, _timeline_events = _install_fake_isaac_modules(monkeypatch, _FakeSettings({}), current_stage=stage)
    module = _load_extension_module()
    calls: list[str] = []

    module.install_timeline_play_specimen_pose_subscription(
        before_play=lambda: calls.append("play") or {"ok": True, "translate_m": [0.23, 0.34, 0.0152]},
    )

    assert [name for name, _callback in callbacks if name.startswith("timeline-event:")] == ["timeline-event:1"]
    assert calls == []
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.4, 0.3, 0.015)
    assert not any(name == "timeline-event:2" for name, _callback in callbacks)


def test_extension_startup_does_not_subscribe_specimen_pose_stop_hook(tmp_path: Path, monkeypatch) -> None:
    port = _free_tcp_port()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 131,
                        "y": 242,
                        "z": 15.2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    callbacks, _opened_stages, _timeline_events = _install_fake_isaac_modules(
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
                "/exts/atr.omx.mirror/playTimelineDelayTicks": 1,
                "/exts/atr.omx.mirror/specimenPoseOnPlay": True,
                "/exts/atr.omx.mirror/specimenPoseRedCubePath": cube_path,
                "/exts/atr.omx.mirror/specimenPosePendingPath": str(pending_path),
                "/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing": True,
            }
        ),
        current_stage=stage,
    )
    module = _load_extension_module()
    extension = module.AtrOmxMirrorExtension()

    try:
        extension.on_startup("atr.omx.mirror")

        timeline_event_names = [name for name, _callback in callbacks if name.startswith("timeline-event:")]
        assert timeline_event_names == ["timeline-event:1"]
    finally:
        extension.on_shutdown()


def test_timeline_play_event_reapplies_cube_translate_after_physics_reset(monkeypatch) -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    callbacks, _opened_stages, _timeline_events = _install_fake_isaac_modules(monkeypatch, _FakeSettings({}), current_stage=stage)
    module = _load_extension_module()

    module.install_timeline_play_specimen_pose_subscription(
        before_play=lambda: module._apply_specimen_pose_snapshot_to_stage(
            stage,
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 210,
                        "y": 320,
                        "z": 15.2,
                    }
                },
            },
            cube_path,
        ),
        red_cube_path=cube_path,
        post_play_reapply_ticks=2,
    )

    callbacks[0][1](types.SimpleNamespace(type=1))
    stage.prims[cube_path].attrs["xformOp:translate"].value = (0.4, 0.3, 0.0152)

    assert callbacks[1][0] == "atr-isaac-omx-mirror-specimen-post-play-reapply"
    callbacks[1][1](object())
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.21, 0.32, 0.0152)


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


def test_extension_startup_wires_specimen_pose_snapshot_before_delayed_play(tmp_path: Path, monkeypatch) -> None:
    port = _free_tcp_port()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
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
                "/exts/atr.omx.mirror/playTimelineDelayTicks": 1,
                "/exts/atr.omx.mirror/specimenPoseOnPlay": True,
                "/exts/atr.omx.mirror/specimenPoseTimeoutSec": 2.0,
                "/exts/atr.omx.mirror/specimenPoseRedCubePath": cube_path,
                "/exts/atr.omx.mirror/specimenPosePendingPath": str(tmp_path / "missing_pending_pose.json"),
            }
        ),
        current_stage=stage,
    )
    module = _load_extension_module()
    calls = []

    def _fake_snapshot(repo_root, script_path, payload, *, timeout_sec, runner=None):
        calls.append(
            {
                "repo_root": repo_root,
                "script_path": script_path,
                "payload": payload,
                "timeout_sec": timeout_sec,
            }
        )
        return {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 111,
                    "y": 222,
                    "z": 33,
                }
            },
        }

    monkeypatch.setattr(module, "_run_specimen_pose_snapshot", _fake_snapshot)
    extension = module.AtrOmxMirrorExtension()

    try:
        extension.on_startup("atr.omx.mirror")
        assert [name for name, _callback in callbacks] == [
            "atr-isaac-omx-mirror-apply",
            "timeline-event:1",
            "atr-isaac-omx-mirror-delayed-play",
        ]

        callbacks[1][1](types.SimpleNamespace(type=1))
        callbacks[2][1](object())

        assert timeline_events == ["play"]
        assert calls
        assert calls[0]["timeout_sec"] == 2.0
        assert calls[0]["payload"]["specimen_id"] == "redcube-play"
        assert calls[0]["payload"]["autostart_realsense"] is False
        assert calls[0]["payload"]["confidence_threshold"] == 0.05
        assert calls[0]["payload"]["frame_manifest_path"] == "/tmp/atr_lerobot_latest_frame/latest_frame.json"
        assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.111, 0.222, 0.033)
    finally:
        extension.on_shutdown()


def test_extension_startup_runs_specimen_pose_before_delayed_auto_play(tmp_path: Path, monkeypatch) -> None:
    port = _free_tcp_port()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
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
                "/exts/atr.omx.mirror/playTimelineDelayTicks": 1,
                "/exts/atr.omx.mirror/specimenPoseOnPlay": True,
                "/exts/atr.omx.mirror/specimenPoseRedCubePath": cube_path,
                "/exts/atr.omx.mirror/specimenPosePendingPath": str(tmp_path / "missing_pending_pose.json"),
            }
        ),
        current_stage=stage,
    )
    module = _load_extension_module()
    calls = []

    def _fake_snapshot(repo_root, script_path, payload, *, timeout_sec, runner=None):
        calls.append(payload)
        return {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 111,
                    "y": 222,
                    "z": 15.2,
                }
            },
        }

    monkeypatch.setattr(module, "_run_specimen_pose_snapshot", _fake_snapshot)
    extension = module.AtrOmxMirrorExtension()

    try:
        extension.on_startup("atr.omx.mirror")
        delayed = next(callback for name, callback in callbacks if name == "atr-isaac-omx-mirror-delayed-play")

        delayed(object())

        assert calls
        assert timeline_events == ["play"]
        assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.111, 0.222, 0.0152)
    finally:
        extension.on_shutdown()


def test_extension_startup_skips_duplicate_play_after_delayed_pending_apply(tmp_path: Path, monkeypatch) -> None:
    port = _free_tcp_port()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 131,
                        "y": 242,
                        "z": 15.2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
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
                "/exts/atr.omx.mirror/playTimelineDelayTicks": 1,
                "/exts/atr.omx.mirror/specimenPoseOnPlay": True,
                "/exts/atr.omx.mirror/specimenPoseRedCubePath": cube_path,
                "/exts/atr.omx.mirror/specimenPosePendingPath": str(pending_path),
                "/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing": True,
            }
        ),
        current_stage=stage,
    )
    module = _load_extension_module()
    requests = []

    def _fake_request(payload, *, reason: str):
        requests.append({"payload": payload, "reason": reason})
        return {"ok": False, "message": "request recorded"}

    monkeypatch.setattr(module, "_request_active_robot_cam_capture", _fake_request)
    extension = module.AtrOmxMirrorExtension()

    try:
        extension.on_startup("atr.omx.mirror")
        delayed = next(callback for name, callback in callbacks if name == "atr-isaac-omx-mirror-delayed-play")
        play = next(callback for name, callback in callbacks if name == "timeline-event:1")

        delayed(object())
        play(types.SimpleNamespace(type=1))

        assert timeline_events == ["play"]
        assert requests == []
        assert not pending_path.exists()
        assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.131, 0.242, 0.0152)

        play(types.SimpleNamespace(type=1))

        assert len(requests) == 1
    finally:
        extension.on_shutdown()


def test_active_robot_cam_request_timeout_removes_current_request(tmp_path: Path) -> None:
    module = _load_extension_module()
    request_path = tmp_path / "active_robot_cam_request.json"
    pending_path = tmp_path / "latest_specimen_pose_payload.json"

    result = module._request_active_robot_cam_capture(
        {
            "active_robot_cam_request_path": str(request_path),
            "pending_pose_path": str(pending_path),
            "active_robot_cam_wait_timeout_s": 0.01,
        },
        reason="isaac_timeline_play",
    )

    assert result["ok"] is False
    assert result["failure_code"] == "ACTIVE_ROBOT_CAM_PENDING_TIMEOUT"
    assert not request_path.exists()


def test_specimen_pose_pending_file_is_consumed_after_first_play(tmp_path: Path, monkeypatch) -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pose": {
                    "position_isaac_world_mm": {
                        "x": 101,
                        "y": 202,
                        "z": 15.2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_current_gui_stage", lambda: stage)

    result = module._run_and_apply_specimen_pose_snapshot(
        REPO_ROOT,
        tmp_path / "missing_snapshot_script.sh",
        {"pending_pose_path": str(pending_path), "consume_pending_pose": True},
        timeout_sec=0.5,
        red_cube_path=cube_path,
    )

    assert result["ok"] is True
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.101, 0.202, 0.0152)
    assert not pending_path.exists()


def test_specimen_pose_invalid_pending_file_is_consumed_before_snapshot_fallback(tmp_path: Path, monkeypatch) -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(
        json.dumps(
            {
                "ok": True,
                "pose": {
                    "schema": "specimen_pose.v1",
                    "a4_camera_to_isaac_transform": "direct",
                },
            }
        ),
        encoding="utf-8",
    )

    def _fake_snapshot(repo_root, script_path, payload, *, timeout_sec, runner=None):
        return {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 151,
                    "y": 252,
                    "z": 15.2,
                }
            },
        }

    monkeypatch.setattr(module, "_current_gui_stage", lambda: stage)
    monkeypatch.setattr(module, "_run_specimen_pose_snapshot", _fake_snapshot)

    result = module._run_and_apply_specimen_pose_snapshot(
        REPO_ROOT,
        tmp_path / "snapshot_script.sh",
        {"pending_pose_path": str(pending_path), "consume_pending_pose": True},
        timeout_sec=0.5,
        red_cube_path=cube_path,
    )

    assert result["ok"] is True
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.151, 0.252, 0.0152)
    assert not pending_path.exists()


def test_specimen_pose_requests_active_cam_when_pending_has_been_consumed(tmp_path: Path, monkeypatch) -> None:
    module = _load_extension_module()
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeStage([cube_path])
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    requests = []

    def _fake_request(payload, *, reason: str):
        requests.append({"payload": payload, "reason": reason})
        pending_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "pose": {
                        "position_isaac_world_mm": {
                            "x": 303,
                            "y": 404,
                            "z": 15.2,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return {"ok": True, "status": "active_robot_cam_applied"}

    monkeypatch.setattr(module, "_current_gui_stage", lambda: stage)
    monkeypatch.setattr(module, "_request_active_robot_cam_capture", _fake_request)

    result = module._run_and_apply_specimen_pose_snapshot(
        REPO_ROOT,
        tmp_path / "missing_snapshot_script.sh",
        {
            "pending_pose_path": str(pending_path),
            "active_robot_cam_trigger": True,
            "active_robot_cam_trigger_reason": "isaac_timeline_play",
        },
        timeout_sec=0.5,
        red_cube_path=cube_path,
    )

    assert result["ok"] is True
    assert requests[0]["reason"] == "isaac_timeline_play"
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.303, 0.404, 0.0152)
