from __future__ import annotations

from types import SimpleNamespace

from device_bridges.realsense_bridge import RealSenseBridge


class _Enum:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class _VideoProfile:
    def __init__(self, stream: _Enum, fmt: _Enum, width: int, height: int, fps: int) -> None:
        self._stream = stream
        self._fmt = fmt
        self._width = width
        self._height = height
        self._fps = fps

    def stream_type(self) -> _Enum:
        return self._stream

    def format(self) -> _Enum:
        return self._fmt

    def fps(self) -> int:
        return self._fps

    def as_video_stream_profile(self) -> "_VideoProfile":
        return self

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _Sensor:
    def __init__(self, name: str, profiles: list[_VideoProfile]) -> None:
        self._name = name
        self._profiles = profiles

    def get_info(self, info: str) -> str:
        if info == "name":
            return self._name
        return ""

    def get_stream_profiles(self) -> list[_VideoProfile]:
        return self._profiles


class _Device:
    def __init__(self, *, name: str, serial: str, sensors: list[_Sensor]) -> None:
        self._info = {"name": name, "serial_number": serial, "product_line": "D400"}
        self._sensors = sensors

    def supports(self, info: str) -> bool:
        return info in self._info

    def get_info(self, info: str) -> str:
        return self._info[info]

    def query_sensors(self) -> list[_Sensor]:
        return self._sensors


def _install_fake_rs(monkeypatch, devices: list[_Device]) -> None:
    module = SimpleNamespace(
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_line="product_line"),
        stream=SimpleNamespace(depth=_Enum("depth"), color=_Enum("color"), infrared=_Enum("infrared")),
        format=SimpleNamespace(z16=_Enum("z16"), rgb8=_Enum("rgb8"), y8=_Enum("y8")),
        context=lambda: SimpleNamespace(query_devices=lambda: devices),
    )
    monkeypatch.setitem(__import__("sys").modules, "pyrealsense2", module)


def test_enumerate_devices_does_not_start_streaming(monkeypatch) -> None:
    depth = _VideoProfile(_Enum("depth"), _Enum("z16"), 640, 480, 30)
    d405 = _Device(name="Intel RealSense D405", serial="352122273019", sensors=[_Sensor("Stereo Module", [depth])])
    _install_fake_rs(monkeypatch, [d405])

    result = RealSenseBridge().execute("enumerate", {})

    assert result["ok"] is True
    assert result["device_count"] == 1
    assert result["streaming_started"] is False
    assert result["devices"][0]["stream_profiles"][0]["stream"] == "depth"


def test_unsupported_color_stream_fails_before_capture(monkeypatch) -> None:
    depth = _VideoProfile(_Enum("depth"), _Enum("z16"), 640, 480, 30)
    d405 = _Device(name="Intel RealSense D405", serial="352122273019", sensors=[_Sensor("Stereo Module", [depth])])
    _install_fake_rs(monkeypatch, [d405])

    result = RealSenseBridge().execute("validate_profile", {"serial": "352122273019", "stream": "color"})

    assert result["ok"] is False
    assert result["failure_code"] == "REALSENSE_UNSUPPORTED_STREAM"
    assert result["streaming_started"] is False


def test_capture_requires_explicit_stream_permission(monkeypatch) -> None:
    depth = _VideoProfile(_Enum("depth"), _Enum("z16"), 640, 480, 30)
    d405 = _Device(name="Intel RealSense D405", serial="352122273019", sensors=[_Sensor("Stereo Module", [depth])])
    _install_fake_rs(monkeypatch, [d405])

    result = RealSenseBridge().execute("capture", {"serial": "352122273019", "stream": "depth"})

    assert result["ok"] is False
    assert result["failure_code"] == "REALSENSE_STREAM_NOT_EXPLICITLY_ALLOWED"
    assert result["streaming_started"] is False
