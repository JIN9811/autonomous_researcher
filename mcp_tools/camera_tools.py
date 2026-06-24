"""
MCP camera and equipment-vision cross-check tools.

UTM checks are backed by the cloned UTM ROS runtime when available. Non-UTM
checks keep the previous lightweight simulator behavior used by test loops.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp_tools.tool_registry import ToolRegistry

UTM_CHECK_IDS = {"utm_pre_start", "utm_motion_confirm", "utm_test_complete"}
UTM_MOTION_TRANSITIONS = {"NOT_WORKING_TO_WORKING", "WORKING_TO_NOT_WORKING"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_utm_check(item: dict[str, Any]) -> bool:
    check_id = str(item.get("check_id") or "")
    device = str(item.get("device") or "").lower()
    return check_id in UTM_CHECK_IDS or check_id.startswith("utm_") or device == "utm"


def _simulated_result(item: dict[str, Any], *, mode: str, ok: bool, confidence: float, timestamp: datetime, expires_at: datetime, ttl_ms: int) -> dict[str, Any]:
    check_id = str(item.get("check_id") or "unknown_check")
    return {
        "agent_signal_type": "equipment_vision_check_result",
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
    if check_id == "utm_test_complete":
        transition = "WORKING_TO_NOT_WORKING"
        final = "NOT_WORKING"
        working = 5
        not_working = 15
    else:
        transition = "NOT_WORKING_TO_WORKING"
        final = "WORKING"
        working = 15
        not_working = 5
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
