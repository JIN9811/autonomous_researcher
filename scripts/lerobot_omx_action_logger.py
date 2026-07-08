"""In-process ROBOTIS OMX follower motor logger for live policy rollout."""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MOTOR_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_LOGGER_ATTR = "_atr_omx_action_logger"
_INSTALLED_ATTR = "_atr_omx_action_logger_installed"
_ORIGINAL_GET_ATTR = "_atr_omx_action_logger_original_get_observation"
_ORIGINAL_SEND_ATTR = "_atr_omx_action_logger_original_send_action"
_LAST_OBSERVATION_ATTR = "_atr_omx_action_logger_latest_observation"


class _OmxActionLogger:
    def __init__(self, log_dir: Path, *, session_id: str, motor_names: tuple[str, ...]) -> None:
        self.log_dir = log_dir
        self.session_id = session_id
        self.motor_names = motor_names
        self.jsonl_path = log_dir / "motor_events.jsonl"
        self.csv_path = log_dir / "motor_events.csv"
        self.manifest_path = log_dir / "manifest.json"
        self._lock = threading.Lock()
        self._sequence = 0
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._write_manifest()

    def log_observation(self, robot: Any, positions: Mapping[str, Any], *, duration_ms: float) -> None:
        clean_positions = _position_values(positions)
        self._write_event(
            {
                "event": "observation",
                "duration_ms": duration_ms,
                "motors": _motor_metadata(robot, self.motor_names),
                "positions": clean_positions,
                "raw_positions": _raw_position_values(robot, clean_positions),
            }
        )

    def log_action(
        self,
        robot: Any,
        requested_action: Mapping[str, Any],
        sent_action: Mapping[str, Any],
        latest_observation: Mapping[str, Any],
        *,
        duration_ms: float,
    ) -> None:
        clean_latest = _position_values(latest_observation)
        clean_requested = _position_values(requested_action)
        clean_sent = _position_values(sent_action)
        self._write_event(
            {
                "event": "action",
                "duration_ms": duration_ms,
                "motors": _motor_metadata(robot, self.motor_names),
                "latest_observation": clean_latest,
                "requested_action": clean_requested,
                "sent_action": clean_sent,
                "raw_latest_observation": _raw_position_values(robot, clean_latest),
                "raw_requested_action": _raw_position_values(robot, clean_requested),
                "raw_sent_action": _raw_position_values(robot, clean_sent),
            }
        )

    def log_action_error(
        self,
        robot: Any,
        requested_action: Mapping[str, Any],
        latest_observation: Mapping[str, Any],
        error: BaseException,
        *,
        duration_ms: float,
    ) -> None:
        clean_latest = _position_values(latest_observation)
        clean_requested = _position_values(requested_action)
        self._write_event(
            {
                "event": "action_error",
                "duration_ms": duration_ms,
                "motors": _motor_metadata(robot, self.motor_names),
                "latest_observation": clean_latest,
                "requested_action": clean_requested,
                "raw_latest_observation": _raw_position_values(robot, clean_latest),
                "raw_requested_action": _raw_position_values(robot, clean_requested),
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )

    def _write_event(self, payload: dict[str, Any]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        monotonic_s = time.monotonic()
        with self._lock:
            self._sequence += 1
            row = {
                "sequence": self._sequence,
                "session_id": self.session_id,
                "timestamp": timestamp,
                "monotonic_s": monotonic_s,
                **payload,
            }
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
            self._append_csv(row)

    def _append_csv(self, event: Mapping[str, Any]) -> None:
        fieldnames = self._csv_fieldnames()
        row = {
            "sequence": event.get("sequence", ""),
            "session_id": event.get("session_id", ""),
            "timestamp": event.get("timestamp", ""),
            "monotonic_s": event.get("monotonic_s", ""),
            "event": event.get("event", ""),
            "duration_ms": event.get("duration_ms", ""),
        }
        for prefix, source_key in (
            ("observed", "positions"),
            ("latest", "latest_observation"),
            ("requested", "requested_action"),
            ("sent", "sent_action"),
            ("raw_observed", "raw_positions"),
            ("raw_latest", "raw_latest_observation"),
            ("raw_requested", "raw_requested_action"),
            ("raw_sent", "raw_sent_action"),
        ):
            source = event.get(source_key)
            if not isinstance(source, Mapping):
                source = {}
            for motor in self.motor_names:
                row[f"{prefix}.{motor}"] = source.get(f"{motor}.pos", "")
        write_header = not self.csv_path.exists()
        with self.csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _csv_fieldnames(self) -> list[str]:
        fields = ["sequence", "session_id", "timestamp", "monotonic_s", "event", "duration_ms"]
        for prefix in ("observed", "latest", "requested", "sent", "raw_observed", "raw_latest", "raw_requested", "raw_sent"):
            fields.extend(f"{prefix}.{motor}" for motor in self.motor_names)
        return fields

    def _write_manifest(self) -> None:
        manifest = {
            "session_id": self.session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "motor_names": list(self.motor_names),
            "jsonl_path": str(self.jsonl_path),
            "csv_path": str(self.csv_path),
            "schema": {
                "observation": "present follower positions returned by OmxFollower.get_observation()",
                "action": "requested policy action, action actually returned by send_action(), and latest observation",
                "raw_*": "raw Dynamixel Goal/Present_Position tick estimates computed with the runtime bus calibration path; no extra serial read is performed",
            },
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def install_omx_follower_action_logger() -> bool:
    """Patch OmxFollower methods when ATR_LEROBOT_OMX_ACTION_LOG is enabled."""

    if str(os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG", "")).strip().lower() not in _TRUE_VALUES:
        return False
    logger = _logger_from_env()
    try:
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
    except Exception as exc:  # pragma: no cover - depends on runtime package availability.
        print(f"ATR OMX action logger disabled: could not import OmxFollower: {exc}", flush=True)
        return False

    setattr(OmxFollower, _LOGGER_ATTR, logger)
    if getattr(OmxFollower, _INSTALLED_ATTR, False):
        print(f"ATR OMX action logger enabled: {logger.jsonl_path}", flush=True)
        return True

    original_get_observation = OmxFollower.get_observation
    original_send_action = OmxFollower.send_action
    setattr(OmxFollower, _ORIGINAL_GET_ATTR, original_get_observation)
    setattr(OmxFollower, _ORIGINAL_SEND_ATTR, original_send_action)

    def get_observation_with_logging(self: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        observation = original_get_observation(self, *args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000.0
        positions = _position_values(observation if isinstance(observation, Mapping) else {})
        setattr(self, _LAST_OBSERVATION_ATTR, positions)
        _safe_log(lambda: getattr(type(self), _LOGGER_ATTR).log_observation(self, positions, duration_ms=duration_ms))
        return observation

    def send_action_with_logging(self: Any, action: Any, *args: Any, **kwargs: Any) -> Any:
        requested = _position_values(action if isinstance(action, Mapping) else {})
        latest = getattr(self, _LAST_OBSERVATION_ATTR, {})
        if not isinstance(latest, Mapping):
            latest = {}
        start = time.perf_counter()
        try:
            sent = original_send_action(self, action, *args, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            _safe_log(
                lambda: getattr(type(self), _LOGGER_ATTR).log_action_error(
                    self,
                    requested,
                    latest,
                    exc,
                    duration_ms=duration_ms,
                )
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        sent_positions = _position_values(sent if isinstance(sent, Mapping) else {})
        _safe_log(
            lambda: getattr(type(self), _LOGGER_ATTR).log_action(
                self,
                requested,
                sent_positions,
                latest,
                duration_ms=duration_ms,
            )
        )
        return sent

    OmxFollower.get_observation = get_observation_with_logging
    OmxFollower.send_action = send_action_with_logging
    setattr(OmxFollower, _INSTALLED_ATTR, True)
    print(f"ATR OMX action logger enabled: {logger.jsonl_path}", flush=True)
    return True


def _logger_from_env() -> _OmxActionLogger:
    session_id = _clean_session_id(os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID", "manual"))
    raw_dir = str(os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG_DIR", "")).strip()
    log_dir = Path(raw_dir).expanduser() if raw_dir else Path.cwd() / "runs" / "lerobot_action_logs" / session_id
    motor_names = _motor_names_from_env()
    return _OmxActionLogger(log_dir, session_id=session_id, motor_names=motor_names)


def _motor_names_from_env() -> tuple[str, ...]:
    raw = str(os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG_MOTORS", "")).strip()
    if not raw:
        return DEFAULT_MOTOR_NAMES
    names = tuple(item.strip() for item in raw.split(",") if item.strip())
    return names or DEFAULT_MOTOR_NAMES


def _clean_session_id(value: Any) -> str:
    text = str(value or "manual").strip()
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in text).strip(".-")
    return clean or "manual"


def _motor_metadata(robot: Any, motor_names: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    bus = getattr(robot, "bus", None)
    motors = getattr(bus, "motors", {})
    calibration = getattr(bus, "calibration", {})
    metadata: dict[str, dict[str, Any]] = {}
    for motor_name in motor_names:
        motor = motors.get(motor_name) if isinstance(motors, Mapping) else None
        motor_calibration = calibration.get(motor_name) if isinstance(calibration, Mapping) else None
        metadata[motor_name] = {
            "id": _safe_scalar(getattr(motor, "id", None)),
            "model": _safe_scalar(getattr(motor, "model", None)),
            "norm_mode": _safe_scalar(getattr(motor, "norm_mode", None)),
            "calibration": {
                "drive_mode": _safe_scalar(getattr(motor_calibration, "drive_mode", None)),
                "homing_offset": _safe_scalar(getattr(motor_calibration, "homing_offset", None)),
                "range_min": _safe_scalar(getattr(motor_calibration, "range_min", None)),
                "range_max": _safe_scalar(getattr(motor_calibration, "range_max", None)),
            },
        }
    return metadata


def _position_values(values: Mapping[str, Any]) -> dict[str, Any]:
    positions: dict[str, Any] = {}
    for key, value in values.items():
        text_key = str(key)
        if not text_key.endswith(".pos"):
            continue
        positions[text_key] = _safe_scalar(value)
    return positions


def _raw_position_values(robot: Any, positions: Mapping[str, Any]) -> dict[str, Any]:
    bus = getattr(robot, "bus", None)
    motors = getattr(bus, "motors", {})
    unnormalize = getattr(bus, "_unnormalize", None)
    if not isinstance(motors, Mapping) or not callable(unnormalize):
        return {}

    id_to_key: dict[int, str] = {}
    id_values: dict[int, float] = {}
    for key, value in positions.items():
        text_key = str(key)
        if not text_key.endswith(".pos"):
            continue
        motor_name = text_key[: -len(".pos")]
        motor = motors.get(motor_name)
        motor_id = getattr(motor, "id", None)
        try:
            clean_id = int(motor_id)
            clean_value = float(_safe_scalar(value))
        except Exception:
            continue
        id_to_key[clean_id] = text_key
        id_values[clean_id] = clean_value

    if not id_values:
        return {}
    try:
        raw_ids = unnormalize(id_values)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(raw_ids, Mapping):
        return {}
    return {id_to_key[id_]: _safe_scalar(raw_value) for id_, raw_value in raw_ids.items() if id_ in id_to_key}


def _safe_scalar(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (bool, int, float, str)):
        return value
    try:
        return float(value)
    except Exception:
        return str(value)


def _safe_log(callback: Any) -> None:
    try:
        callback()
    except Exception as exc:
        print(f"ATR OMX action logger write failed: {exc}", flush=True)
