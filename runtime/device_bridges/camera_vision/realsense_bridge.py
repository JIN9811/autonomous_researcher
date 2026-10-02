"""
File purpose:
- Safe RealSense camera bridge for live camera discovery and guarded capture.

Key classes/functions:
- RealSenseBridge

Inputs/outputs:
- Input: camera bridge command payload
- Output: RealSense device/profile metadata or guarded capture result dictionary

Dependencies:
- device_bridges.base_bridge.BaseBridge
- optional pyrealsense2 runtime package

Modification guide:
- Safe places to edit: metadata fields and profile preference rules
- Risky places to edit: command names and fail-closed stream gating
- Related files: mcp_tools/camera_tools.py, device_bridges/simulator/camera_sim.py
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

from device_bridges.base_bridge import BaseBridge


@dataclass(frozen=True)
class _StreamProfile:
    sensor_name: str
    stream_type: Any
    stream_name: str
    fmt: Any
    format_name: str
    fps: int | None
    width: int | None
    height: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sensor_name": self.sensor_name,
            "stream": self.stream_name,
            "format": self.format_name,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
        }


class RealSenseBridge(BaseBridge):
    """Live RealSense bridge with fail-closed stream handling.

    Health/enumeration never starts a streaming pipeline. Actual frame capture is
    blocked unless payload.allow_stream is explicitly true and the requested
    stream is present in the device's advertised profiles.
    """

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = str(command or "").strip().lower().replace("-", "_")
        payload = payload if isinstance(payload, dict) else {}
        if normalized in {"", "health", "enumerate", "list_devices", "status"}:
            return self.enumerate_devices(payload)
        if normalized in {"validate_profile", "profile"}:
            return self.validate_profile(payload)
        if normalized in {"capture", "capture_one_frame", "frame"}:
            return self.capture_one_frame(payload)
        return {
            "ok": False,
            "bridge": "realsense",
            "command": command,
            "failure_code": "REALSENSE_UNKNOWN_COMMAND",
            "message": f"Unsupported RealSense command: {command}",
        }

    def enumerate_devices(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return devices/profiles without opening a streaming pipeline."""
        rs = self._import_rs()
        if isinstance(rs, dict):
            return rs
        try:
            ctx = rs.context()
            devices = list(ctx.query_devices())
        except Exception as exc:
            return self._error("REALSENSE_ENUMERATION_FAILED", str(exc))

        reports = [self._device_report(rs, device) for device in devices]
        return {
            "ok": bool(reports),
            "bridge": "realsense",
            "command": "enumerate",
            "status": "ready" if reports else "no_devices",
            "device_count": len(reports),
            "devices": reports,
            "streaming_started": False,
            "message": "RealSense devices enumerated without opening streams."
            if reports
            else "No RealSense devices were detected by pyrealsense2.",
        }

    def validate_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Select a supported profile without starting a stream."""
        rs = self._import_rs()
        if isinstance(rs, dict):
            return rs
        selected = self._select_profile(rs, payload)
        if isinstance(selected, dict):
            return selected
        device, profile = selected
        return {
            "ok": True,
            "bridge": "realsense",
            "command": "validate_profile",
            "status": "profile_supported",
            "device": self._device_identity(rs, device),
            "profile": profile.as_dict(),
            "streaming_started": False,
        }

    def capture_one_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture one frame only when explicitly allowed.

        This method intentionally fails closed by default. The previous unsafe
        workflow opened requested streams directly, which can hang some USB host
        controllers when the stream does not exist or the bus is unstable.
        """
        allow_stream = bool(payload.get("allow_stream") or payload.get("live_stream_confirmed"))
        selected = self.validate_profile(payload)
        if not selected.get("ok"):
            return selected
        if not allow_stream:
            return {
                **selected,
                "ok": False,
                "command": "capture_one_frame",
                "status": "blocked",
                "failure_code": "REALSENSE_STREAM_NOT_EXPLICITLY_ALLOWED",
                "message": "Profile is valid, but live stream start is blocked unless allow_stream=true.",
            }

        rs = self._import_rs()
        if isinstance(rs, dict):
            return rs
        profile_info = selected["profile"]
        serial = selected["device"].get("serial_number")
        timeout_ms = max(250, min(int(payload.get("timeout_ms") or 1500), 5000))
        pipeline = rs.pipeline()
        config = rs.config()
        try:
            if serial:
                config.enable_device(str(serial))
            stream_type = self._rs_stream_from_name(rs, str(profile_info["stream"]))
            fmt = self._rs_format_from_name(rs, str(profile_info["format"]))
            if profile_info.get("width") and profile_info.get("height") and profile_info.get("fps"):
                config.enable_stream(
                    stream_type,
                    int(profile_info["width"]),
                    int(profile_info["height"]),
                    fmt,
                    int(profile_info["fps"]),
                )
            else:
                config.enable_stream(stream_type)
            pipeline.start(config)
            frames = pipeline.wait_for_frames(timeout_ms)
            frame = self._frame_from_frameset(frames, str(profile_info["stream"]))
            if frame is None:
                return {
                    **selected,
                    "ok": False,
                    "command": "capture_one_frame",
                    "status": "no_frame",
                    "failure_code": "REALSENSE_FRAME_NOT_AVAILABLE",
                    "timeout_ms": timeout_ms,
                }
            return {
                **selected,
                "ok": True,
                "command": "capture_one_frame",
                "status": "captured",
                "frame": {
                    "frame_number": int(frame.get_frame_number()),
                    "timestamp_ms": float(frame.get_timestamp()),
                    "width": int(frame.get_width()) if hasattr(frame, "get_width") else None,
                    "height": int(frame.get_height()) if hasattr(frame, "get_height") else None,
                },
                "timeout_ms": timeout_ms,
            }
        except Exception as exc:
            return {
                **selected,
                "ok": False,
                "command": "capture_one_frame",
                "status": "failed",
                "failure_code": "REALSENSE_CAPTURE_FAILED",
                "message": str(exc),
                "timeout_ms": timeout_ms,
            }
        finally:
            try:
                pipeline.stop()
            except Exception:
                pass

    @staticmethod
    def _import_rs() -> Any:
        try:
            return importlib.import_module("pyrealsense2")
        except Exception as exc:
            return {
                "ok": False,
                "bridge": "realsense",
                "status": "sdk_missing",
                "failure_code": "REALSENSE_SDK_MISSING",
                "message": f"pyrealsense2 is not available: {exc}",
                "streaming_started": False,
            }

    def _select_profile(self, rs: Any, payload: dict[str, Any]) -> tuple[Any, _StreamProfile] | dict[str, Any]:
        try:
            devices = list(rs.context().query_devices())
        except Exception as exc:
            return self._error("REALSENSE_ENUMERATION_FAILED", str(exc))
        if not devices:
            return self._error("REALSENSE_NO_DEVICES", "No RealSense devices detected.")

        serial = str(payload.get("serial") or payload.get("serial_number") or "").strip()
        stream_kind = str(payload.get("stream") or payload.get("stream_kind") or "depth").strip().lower()
        width = self._optional_int(payload.get("width"))
        height = self._optional_int(payload.get("height"))
        fps = self._optional_int(payload.get("fps"))

        matching_devices = [
            device
            for device in devices
            if not serial or self._safe_info(rs, device, rs.camera_info.serial_number) == serial
        ]
        if not matching_devices:
            return self._error("REALSENSE_DEVICE_NOT_FOUND", f"No RealSense device with serial {serial}.")

        candidates: list[tuple[Any, _StreamProfile]] = []
        for device in matching_devices:
            for profile in self._stream_profiles(rs, device):
                if not self._stream_matches(profile.stream_name, stream_kind):
                    continue
                if width is not None and profile.width != width:
                    continue
                if height is not None and profile.height != height:
                    continue
                if fps is not None and profile.fps != fps:
                    continue
                candidates.append((device, profile))

        if not candidates:
            return {
                "ok": False,
                "bridge": "realsense",
                "command": "validate_profile",
                "status": "unsupported_stream",
                "failure_code": "REALSENSE_UNSUPPORTED_STREAM",
                "requested": {"serial": serial, "stream": stream_kind, "width": width, "height": height, "fps": fps},
                "devices": [self._device_report(rs, device) for device in matching_devices],
                "streaming_started": False,
                "message": "Requested stream/profile is not advertised by the selected RealSense device.",
            }
        return self._prefer_profile(candidates)

    def _device_report(self, rs: Any, device: Any) -> dict[str, Any]:
        identity = self._device_identity(rs, device)
        profiles = [profile.as_dict() for profile in self._stream_profiles(rs, device)]
        sensors = sorted({profile["sensor_name"] for profile in profiles})
        return {**identity, "sensors": sensors, "stream_profiles": profiles}

    @staticmethod
    def _device_identity(rs: Any, device: Any) -> dict[str, str]:
        return {
            "name": RealSenseBridge._safe_info(rs, device, rs.camera_info.name),
            "serial_number": RealSenseBridge._safe_info(rs, device, rs.camera_info.serial_number),
            "product_line": RealSenseBridge._safe_info(rs, device, rs.camera_info.product_line),
        }

    @staticmethod
    def _stream_profiles(rs: Any, device: Any) -> list[_StreamProfile]:
        profiles: list[_StreamProfile] = []
        try:
            sensors = list(device.query_sensors())
        except Exception:
            return profiles
        for sensor in sensors:
            sensor_name = RealSenseBridge._safe_sensor_name(rs, sensor)
            try:
                sensor_profiles = list(sensor.get_stream_profiles())
            except Exception:
                continue
            for raw in sensor_profiles:
                stream_type = RealSenseBridge._safe_call(raw, "stream_type")
                fmt = RealSenseBridge._safe_call(raw, "format")
                stream_name = RealSenseBridge._enum_name(stream_type)
                format_name = RealSenseBridge._enum_name(fmt)
                fps = RealSenseBridge._safe_call(raw, "fps")
                width = None
                height = None
                try:
                    video = raw.as_video_stream_profile()
                    width = int(video.width())
                    height = int(video.height())
                except Exception:
                    pass
                profiles.append(
                    _StreamProfile(
                        sensor_name=sensor_name,
                        stream_type=stream_type,
                        stream_name=stream_name,
                        fmt=fmt,
                        format_name=format_name,
                        fps=int(fps) if fps is not None else None,
                        width=width,
                        height=height,
                    )
                )
        return profiles

    @staticmethod
    def _prefer_profile(candidates: list[tuple[Any, _StreamProfile]]) -> tuple[Any, _StreamProfile]:
        def score(item: tuple[Any, _StreamProfile]) -> tuple[int, int, int]:
            _, profile = item
            size_score = 0 if (profile.width, profile.height) == (640, 480) else 1
            fps_score = 0 if profile.fps == 30 else 1
            return (size_score, fps_score, (profile.width or 9999) * (profile.height or 9999))

        return sorted(candidates, key=score)[0]

    @staticmethod
    def _stream_matches(stream_name: str, requested: str) -> bool:
        normalized = stream_name.lower()
        requested = requested.lower()
        aliases = {
            "rgb": "color",
            "colour": "color",
            "ir": "infrared",
            "infra": "infrared",
        }
        requested = aliases.get(requested, requested)
        return requested in normalized

    @staticmethod
    def _rs_stream_from_name(rs: Any, stream_name: str) -> Any:
        return getattr(rs.stream, stream_name.split(".")[-1])

    @staticmethod
    def _rs_format_from_name(rs: Any, format_name: str) -> Any:
        return getattr(rs.format, format_name.split(".")[-1])

    @staticmethod
    def _frame_from_frameset(frames: Any, stream_name: str) -> Any:
        if "depth" in stream_name:
            return frames.get_depth_frame()
        if "color" in stream_name:
            return frames.get_color_frame()
        if "infrared" in stream_name:
            return frames.get_infrared_frame()
        return None

    @staticmethod
    def _safe_info(rs: Any, obj: Any, info: Any) -> str:
        try:
            if hasattr(obj, "supports") and not obj.supports(info):
                return ""
            return str(obj.get_info(info))
        except Exception:
            return ""

    @staticmethod
    def _safe_sensor_name(rs: Any, sensor: Any) -> str:
        try:
            return str(sensor.get_info(rs.camera_info.name))
        except Exception:
            return "unknown_sensor"

    @staticmethod
    def _safe_call(obj: Any, method: str) -> Any:
        try:
            return getattr(obj, method)()
        except Exception:
            return None

    @staticmethod
    def _enum_name(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        return text.split(".")[-1] if "." in text else text

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "bridge": "realsense",
            "status": "failed",
            "failure_code": code,
            "message": message,
            "streaming_started": False,
        }
