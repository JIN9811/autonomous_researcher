"""
MCP camera and equipment-vision cross-check tools.

UTM checks are backed by the cloned UTM ROS runtime when available. Non-UTM
checks keep the previous lightweight simulator behavior used by test loops.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Any

from mcp_tools.tool_registry import ToolRegistry
from utils.equipment_vision_tasks import EQUIPMENT_VISION_TASK_IDS
from utils.utm_specimen_presence import inspect_specimen_presence, virtual_specimen_frame_data_url

UTM_CHECK_IDS = set(EQUIPMENT_VISION_TASK_IDS)
UTM_MOTION_TRANSITIONS = {"NOT_WORKING_TO_WORKING", "WORKING_TO_NOT_WORKING"}
UTM_PASSIVE_VERIFICATIONS = {
    "utm_state_working": ("WORKING", "state"),
    "utm_motion_down": ("DOWN", "motion_direction"),
    "utm_state_not_working": ("NOT WORKING", "state"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_utm_check(item: dict[str, Any]) -> bool:
    check_id = str(item.get("check_id") or "")
    device = str(item.get("device") or "").lower()
    return check_id in UTM_CHECK_IDS or check_id.startswith("utm_") or device == "utm"


def _equipment_result_identity(item: dict[str, Any]) -> dict[str, Any]:
    """Mirror request identity while reversing producer/consumer for the result."""
    return {
        "task_id": str(item.get("task_id") or item.get("check_id") or ""),
        "run_id": str(item.get("run_id") or ""),
        "loop_id": int(item.get("loop_id") or 0),
        "specimen_id": str(item.get("specimen_id") or ""),
        "producer_agent": str(item.get("consumer_agent") or "vision_agent"),
        "consumer_agent": str(item.get("producer_agent") or "equipment_agent"),
    }


def _simulated_result(item: dict[str, Any], *, mode: str, ok: bool, confidence: float, timestamp: datetime, expires_at: datetime, ttl_ms: int) -> dict[str, Any]:
    check_id = str(item.get("check_id") or "unknown_check")
    return {
        "agent_signal_type": "equipment_vision_check_result",
        **_equipment_result_identity(item),
        "check_id": check_id,
        "status": "verified" if ok else "attention_required",
        "ok": ok,
        "confidence": confidence if ok else 0.0,
        "signals": {"simulated_or_external_check": ok, "anomaly": False},
        "evidence": {"observation_id": f"obs-{check_id}", "frame_ids": [f"frame-{check_id}"] if ok else []},
        "timestamp": timestamp.isoformat(),
        "expires_at": expires_at.isoformat(),
        "freshness_ttl_ms": ttl_ms,
        "source": "simulator" if mode != "live" else "live_required_external_vision",
    }


def _virtual_utm_observation(check_id: str) -> dict[str, Any]:
    if check_id in {"utm_test_complete", "utm_state_not_working"}:
        transition = "WORKING_TO_NOT_WORKING"
        final = "NOT_WORKING"
        working = 5
        not_working = 15
        motion_direction = "UP"
    else:
        transition = "NOT_WORKING_TO_WORKING"
        final = "WORKING"
        working = 15
        not_working = 5
        motion_direction = "DOWN"
    return {
        "ok": True,
        "duration_sec": 5.0,
        "sample_count": 20,
        "valid_sample_count": 20,
        "working_count": working,
        "not_working_count": not_working,
        "unknown_count": 0,
        "initial_state": "NOT_WORKING",
        "final_state": final,
        "transition": transition,
        "stable_state": "",
        "motion_direction": motion_direction,
        "span_y_delta": 90.0,
        "source": "virtual_utm_bridge",
        "virtual_frame_id": f"virtual-frame-{check_id}",
    }


def _utm_result_from_observation(
    item: dict[str, Any],
    observation: dict[str, Any],
    *,
    source: str,
    timestamp: datetime,
    expires_at: datetime,
    ttl_ms: int,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    check_id = str(item.get("check_id") or "utm_motion_confirm")
    transition = str(observation.get("transition") or "")
    ok = bool(observation.get("ok"))
    failure_code: str | None = None
    message = "UTM visual evidence verified."

    if not ok:
        failure_code = str(observation.get("failure_code") or "UTM_EVIDENCE_UNAVAILABLE")
        message = "UTM ROS topic evidence is not yet sufficient."
    elif check_id in UTM_PASSIVE_VERIFICATIONS:
        verification_label, observation_kind = UTM_PASSIVE_VERIFICATIONS[check_id]
        if observation_kind == "state":
            expected = verification_label.replace(" ", "_")
            observed = str(observation.get("stable_state") or observation.get("final_state") or "UNKNOWN").upper()
        else:
            expected = verification_label
            observed = str(observation.get("motion_direction") or "UNKNOWN").upper()
        if observed != expected:
            ok = False
            failure_code = "UTM_EXPECTED_VISION_RESULT_MISMATCH"
            message = f"Expected UTM Vision result {verification_label}, observed {observed}."
    elif check_id == "utm_motion_confirm" and transition not in UTM_MOTION_TRANSITIONS:
        ok = False
        failure_code = "UTM_MOTION_NOT_CONFIRMED"
        message = "UTM motion was not confirmed by a state transition."
    elif check_id == "utm_test_complete" and source != "virtual_utm_bridge":
        ready = payload.get("utm_data_ready") or payload.get("data_ready") or {}
        if not (isinstance(ready, dict) and str(ready.get("status") or "").lower() in {"ready", "ok", "verified"}):
            ok = False
            failure_code = "UTM_TEST_COMPLETE_EVIDENCE_REQUIRED"
            message = "UTM test completion requires exported data or software evidence."

    result = {
        "agent_signal_type": "equipment_vision_check_result",
        **_equipment_result_identity(item),
        "check_id": check_id,
        "status": "verified" if ok else "attention_required",
        "ok": ok,
        "confidence": 0.92 if ok else 0.0,
        "signals": {
            "utm_crosshead_motion": transition in UTM_MOTION_TRANSITIONS,
            "utm_topic_evidence": bool(observation.get("ok")),
            "anomaly": False if ok else True,
        },
        "evidence": observation,
        "message": message,
        "timestamp": timestamp.isoformat(),
        "expires_at": expires_at.isoformat(),
        "freshness_ttl_ms": ttl_ms,
        "source": source,
    }
    if check_id in UTM_PASSIVE_VERIFICATIONS:
        verification_label, observation_kind = UTM_PASSIVE_VERIFICATIONS[check_id]
        result["verification_label"] = verification_label
        result["observed_result"] = (
            str(observation.get("stable_state") or observation.get("final_state") or "UNKNOWN").upper().replace("_", " ")
            if observation_kind == "state"
            else str(observation.get("motion_direction") or "UNKNOWN").upper()
        )
    if failure_code:
        result["failure_code"] = failure_code
    return result, failure_code


def _fallback_trace(reason_code: str, message: str) -> dict[str, Any]:
    return {
        "event_type": "utm.runtime.fallback",
        "severity": "warning",
        "from_observer_mode": "ros_topic",
        "to_observer_mode": "virtual_utm_bridge",
        "reason_code": reason_code,
        "message": message,
        "timestamp": _now().isoformat(),
    }


def _operator_attention(failure_code: str, message: str) -> dict[str, Any]:
    return {
        "status": "attention_required",
        "failure_code": failure_code,
        "message": message,
        "actions": ["Retry UTM probe", "Open UTM runtime log", "Check camera/topic graph", "Use virtual bridge only in test mode"],
    }


def _utm_specimen_presence_capture(
    payload: dict[str, Any],
    *,
    utm_runtime_manager: Any | None,
) -> dict[str, Any]:
    mode = str(payload.get("runtime_mode") or payload.get("mode") or "test").strip().lower()
    clear_verification = payload.get("purpose") == "utm_clear_verification"
    allow_virtual = not clear_verification and mode == "test" and bool(payload.get("allow_virtual_bridge_in_test", False))
    prefer_virtual = allow_virtual and bool(payload.get("prefer_virtual_bridge_in_test", False))
    runtime_status: dict[str, Any] = {}
    frame: dict[str, Any] = {}
    frame_attempt_count = 0
    if prefer_virtual:
        runtime_status = {
            "ok": True,
            "status": "virtual_bridge_selected",
            "observer_mode": "virtual_utm_bridge",
        }
    elif utm_runtime_manager is not None:
        runtime_status = dict(
            utm_runtime_manager.start()
            if not clear_verification and bool(payload.get("auto_start_runtime", True))
            else utm_runtime_manager.status()
        )
        try:
            frame_attempts = max(1, min(int(payload.get("frame_attempts") or 1), 5))
        except (TypeError, ValueError):
            frame_attempts = 1
        try:
            frame_retry_delay_sec = max(0.0, min(float(payload.get("frame_retry_delay_sec") or 0.0), 2.0))
        except (TypeError, ValueError):
            frame_retry_delay_sec = 0.0
        for attempt_index in range(frame_attempts):
            frame_attempt_count = attempt_index + 1
            raw_frame = getattr(utm_runtime_manager, "raw_frame", None)
            if not callable(raw_frame):
                frame = {
                    "ok": False,
                    "frame_available": False,
                    "failure_code": "UTM_RAW_FRAME_CAPTURE_UNAVAILABLE",
                    "message": "UTM runtime does not expose the required raw camera frame capture path.",
                }
                break
            frame = dict(raw_frame())
            if frame.get("ok") and frame.get("data_url"):
                break
            if attempt_index + 1 < frame_attempts and frame_retry_delay_sec:
                time.sleep(frame_retry_delay_sec)
    else:
        runtime_status = {
            "ok": False,
            "status": "not_configured",
            "failure_code": "UTM_RUNTIME_MANAGER_NOT_CONFIGURED",
        }

    virtualized = False
    if not (frame.get("ok") and frame.get("data_url")):
        if not allow_virtual:
            failure_code = str(
                frame.get("failure_code")
                or runtime_status.get("failure_code")
                or "UTM_FRAME_UNAVAILABLE"
            )
            return {
                "ok": False,
                "tool": "vision.utm_specimen_presence.capture",
                "schema": "vision_utm_specimen_presence.v1",
                "runtime_mode": mode,
                "status": "frame_unavailable",
                "detected": False,
                "virtualized": False,
                "source": "utm_ros_raw_frame",
                "failure_code": failure_code,
                "message": str(frame.get("message") or "UTM observation frame is unavailable."),
                "runtime_status": runtime_status,
                "frame_capture": frame,
                "frame_attempt_count": frame_attempt_count,
                "run_id": str(payload.get("run_id") or ""),
                "session_id": str(payload.get("session_id") or ""),
                "specimen_id": str(payload.get("specimen_id") or ""),
            }
        virtualized = True
        frame = {
            "ok": True,
            "frame_available": True,
            "frame_id": str(payload.get("frame_id") or "virtual-utm-specimen-frame"),
            "topic": "virtual://utm-observation",
            "width": 640,
            "height": 480,
            "data_url": virtual_specimen_frame_data_url(),
        }

    output_dir = Path(str(payload.get("output_dir") or "runs/utm_specimen_presence")).expanduser()
    frame_id = str(frame.get("frame_id") or f"utm-frame-{int(_now().timestamp() * 1000)}")
    if clear_verification:
        from uuid import uuid4
        frame_id = f"utm-clear-{uuid4().hex}"
    try:
        result = inspect_specimen_presence(
            str(frame.get("data_url") or ""),
            output_dir=output_dir,
            specimen_id=str(payload.get("specimen_id") or ""),
            frame_id=frame_id,
            min_area_px=float(payload.get("min_area_px") or 300.0),
            roi_normalized=payload.get("roi_normalized"),
            purpose=str(payload.get("purpose") or ""),
            capture_evidence={"topic": frame.get("topic"), "camera_profile_id": frame.get("camera_profile_id"),
                "frame_timestamp": frame.get("frame_timestamp"), "frame_age_ms": frame.get("frame_age_ms"),
                "material": payload.get("material"), "after_timestamp": payload.get("after_timestamp")},
        )
    except Exception as exc:
        return {
            "ok": False,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "runtime_mode": mode,
            "status": "inspection_failed",
            "detected": False,
            "virtualized": virtualized,
            "source": "virtual_utm_bridge" if virtualized else "utm_ros_raw_frame",
            "failure_code": "UTM_SPECIMEN_PRESENCE_INSPECTION_FAILED",
            "message": f"{type(exc).__name__}: {exc}",
            "runtime_status": runtime_status,
            "frame_capture": {key: value for key, value in frame.items() if key != "data_url"},
            "frame_attempt_count": frame_attempt_count,
            "run_id": str(payload.get("run_id") or ""),
            "session_id": str(payload.get("session_id") or ""),
            "specimen_id": str(payload.get("specimen_id") or ""),
        }
    result.update(
        {
            "tool": "vision.utm_specimen_presence.capture",
            "runtime_mode": mode,
            "virtualized": virtualized,
            "source": "virtual_utm_bridge" if virtualized else "utm_ros_raw_frame",
            "topic": str(frame.get("topic") or ""),
            "runtime_status": runtime_status,
            "frame_capture": {key: value for key, value in frame.items() if key != "data_url"},
            "frame_attempt_count": frame_attempt_count,
            "run_id": str(payload.get("run_id") or ""),
            "session_id": str(payload.get("session_id") or ""),
        }
    )
    if clear_verification:
        result["loop_id"] = payload.get("loop_id")
    return result


def _equipment_cross_check(
    payload: dict[str, Any],
    *,
    utm_state_observer: Callable[..., dict[str, Any]] | None = None,
    utm_runtime_manager: Any | None = None,
) -> dict[str, Any]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    mode = str(payload.get("runtime_mode") or payload.get("mode") or "test").lower()
    confidence = float(payload.get("confidence", 0.9 if mode != "live" else 0.0))
    ok_default = bool(payload.get("force_ok", mode != "live"))
    ttl_ms = int(payload.get("freshness_ttl_ms") or payload.get("ttl_ms") or 5000)
    timestamp = _now()
    expires_at = timestamp + timedelta(milliseconds=max(1, ttl_ms))
    duration_sec = float(payload.get("duration_sec", 5.0))
    sample_interval_sec = float(payload.get("sample_interval_sec", 0.2))
    minimum_samples = int(payload.get("minimum_samples", 8))
    auto_start = bool(payload.get("auto_start_runtime", True))
    allow_virtual = bool(payload.get("allow_virtual_bridge_in_test", True))

    results: list[dict[str, Any]] = []
    failure_codes: list[str] = []
    observer_mode = "simulator"
    runtime_status: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    fallback: dict[str, Any] | None = None
    attention: dict[str, Any] | None = None
    virtualized = False

    for item in checks:
        if not isinstance(item, dict) or not item.get("check_id"):
            continue
        if not _is_utm_check(item):
            results.append(
                _simulated_result(
                    item,
                    mode=mode,
                    ok=ok_default,
                    confidence=confidence,
                    timestamp=timestamp,
                    expires_at=expires_at,
                    ttl_ms=ttl_ms,
                )
            )
            if not ok_default:
                failure_codes.append("VISION_EQUIPMENT_CROSS_CHECK_REQUIRED")
            continue

        check_id = str(item.get("check_id") or "utm_motion_confirm")
        observer_mode = "ros_topic"
        if utm_runtime_manager is not None:
            if auto_start:
                runtime_status = dict(utm_runtime_manager.start())
            else:
                runtime_status = dict(utm_runtime_manager.status())
            try:
                probe = dict(utm_runtime_manager.probe())
                diagnostics = dict(probe.get("diagnostics", {}))
            except Exception as exc:  # pragma: no cover - defensive boundary for hardware tools
                diagnostics = {"probe_error": type(exc).__name__, "message": str(exc)}

        observation: dict[str, Any]
        observation_error: str | None = None
        if utm_state_observer is None:
            observation = {"ok": False, "failure_code": "UTM_OBSERVER_NOT_CONFIGURED", "transition": "INSUFFICIENT_EVIDENCE"}
        else:
            try:
                observation = dict(
                    utm_state_observer(
                        duration_sec=duration_sec,
                        sample_interval_sec=sample_interval_sec,
                        minimum_samples=minimum_samples,
                    )
                )
            except Exception as exc:  # Hardware/topic timeout should become explicit evidence, not a traceback.
                observation_error = type(exc).__name__
                observation = {"ok": False, "failure_code": "TOPIC_TIMEOUT", "error": observation_error, "message": str(exc)}

        result, failure_code = _utm_result_from_observation(
            item,
            observation,
            source="ros_topic",
            timestamp=timestamp,
            expires_at=expires_at,
            ttl_ms=ttl_ms,
            payload=payload,
        )

        if result["ok"]:
            results.append(result)
            continue

        reason_code = str(diagnostics.get("failure_code") or observation.get("failure_code") or failure_code or "UTM_EVIDENCE_UNAVAILABLE")
        if mode != "live" and allow_virtual:
            observer_mode = "virtual_utm_bridge"
            virtualized = True
            virtual_observation = _virtual_utm_observation(check_id)
            virtual_result, virtual_failure = _utm_result_from_observation(
                item,
                virtual_observation,
                source="virtual_utm_bridge",
                timestamp=timestamp,
                expires_at=expires_at,
                ttl_ms=ttl_ms,
                payload=payload,
            )
            fallback = _fallback_trace(
                reason_code,
                f"UTM ROS evidence was unavailable ({reason_code}); this test-mode loop is continuing with the virtual UTM bridge.",
            )
            results.append(virtual_result)
            if virtual_failure:
                failure_codes.append(virtual_failure)
            continue

        result["status"] = "attention_required"
        results.append(result)
        failure_codes.append(reason_code)
        attention = _operator_attention(reason_code, result.get("message") or "UTM evidence requires operator attention.")

    ok = bool(results) and all(bool(item.get("ok")) for item in results)
    failure_code = None if ok else (failure_codes[0] if failure_codes else "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED")
    return {
        "ok": ok,
        "tool": "vision.equipment_cross_check",
        "runtime_mode": mode,
        "observer_mode": observer_mode,
        "virtualized": virtualized,
        "runtime_status": runtime_status,
        "diagnostics": diagnostics,
        "results": results,
        "fallback_trace": fallback,
        "operator_attention": attention,
        "failure_code": failure_code,
    }


def register_camera_tools(
    registry: ToolRegistry,
    *,
    utm_state_observer: Callable[..., dict[str, Any]] | None = None,
    utm_runtime_manager: Any | None = None,
    specimen_pose_tracker: Any | None = None,
) -> None:
    """Register camera capture and equipment cross-check tools."""
    registry.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload.get("frame_id", "mock"),
            "observation_id": f"obs-{payload.get('frame_id', 'mock')}",
            "camera_key": payload.get("camera_key", "top"),
            "purpose": payload.get("purpose", "3dp_output_pickup_check"),
            "source": "simulator",
            "timestamp": _now().isoformat(),
            "stable_for_ms": 1200,
            "confidence": 0.86,
            "pose_confidence": 0.86,
            "anomaly": False,
        },
    )
    registry.register(
        "vision.utm_runtime.start",
        lambda payload: (
            {
                **dict(utm_runtime_manager.start()),
                "tool": "vision.utm_runtime.start",
                "request": payload if isinstance(payload, dict) else {},
            }
            if utm_runtime_manager is not None
            else {
                "ok": False,
                "tool": "vision.utm_runtime.start",
                "status": "not_configured",
                "failure_code": "UTM_RUNTIME_MANAGER_NOT_CONFIGURED",
            }
        ),
    )
    registry.register(
        "vision.utm_runtime.status",
        lambda payload: (
            {
                **dict(utm_runtime_manager.status()),
                "tool": "vision.utm_runtime.status",
            }
            if utm_runtime_manager is not None
            else {
                "ok": False,
                "tool": "vision.utm_runtime.status",
                "status": "not_configured",
                "failure_code": "UTM_RUNTIME_MANAGER_NOT_CONFIGURED",
            }
        ),
    )
    registry.register(
        "vision.utm_runtime.stop",
        lambda payload: (
            {
                **dict(utm_runtime_manager.stop()),
                "tool": "vision.utm_runtime.stop",
                "request": payload if isinstance(payload, dict) else {},
            }
            if utm_runtime_manager is not None
            else {
                "ok": False,
                "tool": "vision.utm_runtime.stop",
                "status": "not_configured",
                "failure_code": "UTM_RUNTIME_MANAGER_NOT_CONFIGURED",
            }
        ),
    )
    registry.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: _utm_specimen_presence_capture(
            payload if isinstance(payload, dict) else {},
            utm_runtime_manager=utm_runtime_manager,
        ),
    )
    registry.register(
        "vision.specimen_pose_snapshot",
        lambda payload: specimen_pose_tracker.snapshot(payload if isinstance(payload, dict) else {})
        if specimen_pose_tracker is not None
        else {
            "ok": False,
            "tool": "vision.specimen_pose_snapshot",
            "failure_code": "SPECIMEN_POSE_TRACKER_NOT_CONFIGURED",
            "message": "Specimen pose tracker bridge is not configured.",
        },
    )
    registry.register(
        "vision.specimen_pose.release",
        lambda payload: specimen_pose_tracker.release(payload if isinstance(payload, dict) else {})
        if specimen_pose_tracker is not None
        else {
            "ok": False,
            "tool": "vision.specimen_pose.release",
            "failure_code": "SPECIMEN_POSE_TRACKER_NOT_CONFIGURED",
            "message": "Specimen pose tracker bridge is not configured.",
        },
    )
    registry.register(
        "vision.equipment_cross_check",
        lambda payload: _equipment_cross_check(
            payload,
            utm_state_observer=utm_state_observer,
            utm_runtime_manager=utm_runtime_manager,
        ),
    )
