"""Read-only OMX joint telemetry normalization and policy-tracking artifacts."""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from utils.isaac_omx_mirror_mapping import ISAAC_OMX_JOINT_MAP, action_to_joint_state


TELEMETRY_SCHEMA = "atr.robot_joint_telemetry.v1"
ARTIFACT_SCHEMA = "atr.policy_tracking_artifact.v1"
GRASP_OUTCOME_SCHEMA = "atr.grasp_outcomes.v1"
GRASP_ACHIEVEMENT_SCHEMA = "atr.grasp_achievement.v1"
GRASP_OUTCOME_RULE_VERSION = "absolute_contact_gap_v3"
GRASP_CONTACT_GAP_THRESHOLD = 2.0
JOINT_NAMES = tuple(str(item["isaac_joint_name"]) for item in ISAAC_OMX_JOINT_MAP)
TERMINAL_SESSION_STATUSES = {"STOPPED", "FAILED", "COMPLETED", "CANCELLED", "DATASET_COMPLETE"}
SOURCE_JOINT_KEYS = {
    "Joint1": "shoulder_pan.pos",
    "Joint2": "shoulder_lift.pos",
    "Joint3": "elbow_flex.pos",
    "Joint4": "wrist_flex.pos",
    "Joint5": "wrist_roll.pos",
    "Gripper": "gripper.pos",
}
SOURCE_UNITS = {
    "Joint1": "deg",
    "Joint2": "native",
    "Joint3": "native",
    "Joint4": "native",
    "Joint5": "deg",
    "Gripper": "%",
}
MEASURED_HOME_RANGES = {
    # HOME is a bounded physical pose, not one exact servo setpoint. These
    # bounds include the measured settling envelope from the current OMX arm.
    "Joint1": (-15.0, -1.0),
    "Joint2": (-64.0, -53.0),
    "Joint3": (50.0, 61.0),
    "Joint4": (40.0, 53.0),
    "Joint5": (-11.0, -1.0),
    "Gripper": (55.0, 65.0),
}
POLICY_HOME_RANGES = {
    **MEASURED_HOME_RANGES,
    # The follower's motor-2 limit shifts measured feedback away from the
    # requested home target. Keep the policy gate in requested-action space.
    "Joint2": (-72.0, -62.0),
}

# Compatibility alias for consumers that imported the original range table.
HOME_RANGES = MEASURED_HOME_RANGES
MOTION_WINDOW_S = 0.5
HOME_DWELL_S = 0.5
ARM_MOTION_ENTER_THRESHOLD = 4.0
ARM_MOTION_EXIT_THRESHOLD = 2.0
ARM_MOTION_EXIT_DWELL_S = 0.3
GRIPPER_MOTION_ENTER_THRESHOLD = 2.0
GRIPPER_MOTION_EXIT_THRESHOLD = 0.5
GRIPPER_MOTION_EXIT_DWELL_S = 0.2

# Compatibility aliases for consumers that imported the original constants.
ARM_SPEED_THRESHOLD = ARM_MOTION_ENTER_THRESHOLD
GRIPPER_SPEED_THRESHOLD = GRIPPER_MOTION_ENTER_THRESHOLD


def normalize_action_event(
    event: Mapping[str, Any],
    *,
    origin_monotonic_s: float | None = None,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Convert one existing OMX action-log row into a browser telemetry packet."""

    if str(event.get("event") or "").lower() != "action":
        return None
    actual_source = _position_mapping(event.get("latest_observation"))
    requested_source = _position_mapping(event.get("requested_action"))
    applied_source = _position_mapping(event.get("sent_action"))
    if not actual_source:
        return None
    target_source = requested_source or applied_source
    actual_deg = _joint_degrees(actual_source, calibration=calibration)
    target_deg = _joint_degrees(target_source, calibration=calibration)
    applied_deg = _joint_degrees(applied_source, calibration=calibration)
    if not actual_deg:
        return None

    monotonic_s = _safe_float(event.get("monotonic_s"), 0.0)
    origin = monotonic_s if origin_monotonic_s is None else float(origin_monotonic_s)
    return {
        "schema": TELEMETRY_SCHEMA,
        "type": "joint_sample",
        "session_id": str(event.get("session_id") or ""),
        "sequence": _safe_int(event.get("sequence"), 0),
        "timestamp": str(event.get("timestamp") or ""),
        "monotonic_s": monotonic_s,
        "elapsed_s": max(0.0, monotonic_s - origin),
        "source": "omx_action_log",
        "actual_source": _native_joint_values(actual_source),
        "target_source": _native_joint_values(target_source),
        "applied_target_source": _native_joint_values(applied_source),
        "source_units": dict(SOURCE_UNITS),
        "actual_deg": actual_deg,
        "target_deg": target_deg,
        "applied_target_deg": applied_deg,
        "actual_rad": {name: math.radians(value) for name, value in actual_deg.items()},
        "target_rad": {name: math.radians(value) for name, value in target_deg.items()},
        "applied_target_rad": {name: math.radians(value) for name, value in applied_deg.items()},
    }


def _position_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if str(key).endswith(".pos")}


def _native_joint_values(values: Mapping[str, Any]) -> dict[str, float]:
    return {
        joint: _safe_float(values[source_key], 0.0)
        for joint, source_key in SOURCE_JOINT_KEYS.items()
        if source_key in values
    }


def _joint_degrees(values: dict[str, Any], *, calibration: dict[str, Any] | None) -> dict[str, float]:
    rows = action_to_joint_state(values, calibration=calibration)
    by_name = {str(row.get("isaac_joint_name") or ""): _safe_float(row.get("target_value"), 0.0) for row in rows}
    return {name: by_name[name] for name in JOINT_NAMES if name in by_name}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _home_gate(
    values: Mapping[str, Any],
    *,
    stable_for_s: float,
    home_ranges: Mapping[str, tuple[float, float]] = MEASURED_HOME_RANGES,
) -> dict[str, Any]:
    joints: dict[str, dict[str, Any]] = {}
    for joint, (minimum, maximum) in home_ranges.items():
        raw_value = values.get(joint)
        value = _safe_float(raw_value, math.nan) if raw_value is not None else math.nan
        passed = math.isfinite(value) and minimum <= value <= maximum
        joints[joint] = {
            "value": value if math.isfinite(value) else None,
            "minimum": minimum,
            "maximum": maximum,
            "passed": passed,
        }
    position_passed = bool(joints) and all(item["passed"] for item in joints.values())
    stability_passed = stable_for_s >= HOME_DWELL_S
    return {
        "passed": position_passed and stability_passed,
        "position_passed": position_passed,
        "stability_passed": stability_passed,
        "dwell_required_s": HOME_DWELL_S,
        "joints": joints,
    }


def _arm_home_position_passed(
    values: Mapping[str, Any],
    *,
    home_ranges: Mapping[str, tuple[float, float]] = MEASURED_HOME_RANGES,
) -> bool:
    return all(
        joint in values and minimum <= _safe_float(values.get(joint), math.nan) <= maximum
        for joint, (minimum, maximum) in home_ranges.items()
        if joint != "Gripper"
    )


@dataclass
class _ChannelMotionLatch:
    base_state: str = "moving"
    gripper_state: str = "idle"
    arm_exit_started_s: float | None = None
    gripper_exit_started_s: float | None = None
    arm_stable_started_s: float | None = None
    fully_stable_started_s: float | None = None
    home_candidate_started_s: float | None = None
    last_time_s: float | None = None

    def reset(self) -> None:
        self.base_state = "moving"
        self.gripper_state = "idle"
        self.arm_exit_started_s = None
        self.gripper_exit_started_s = None
        self.arm_stable_started_s = None
        self.fully_stable_started_s = None
        self.home_candidate_started_s = None
        self.last_time_s = None


def _grasp_outcome_state(
    *,
    status: str = "idle",
    reason: str = "waiting for measured grasp attempt",
    attempt_index: int = 0,
    contact_gap: float | None = None,
    measured_gripper: float | None = None,
    policy_target_gripper: float | None = None,
    transport_overlap: bool = False,
    started_s: float | None = None,
    completed_s: float | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "attempt_index": attempt_index,
        "observation_only": True,
        "contact_gap": contact_gap,
        "contact_gap_threshold": GRASP_CONTACT_GAP_THRESHOLD,
        "measured_gripper": measured_gripper,
        "policy_target_gripper": policy_target_gripper,
        "transport_overlap": transport_overlap,
        "started_s": started_s,
        "completed_s": completed_s,
    }


@dataclass
class _GraspOutcomeLatch:
    attempt_index: int = 0
    active: bool = False
    awaiting_evidence: bool = False
    previous_gripper_state: str = "idle"
    last_time_s: float | None = None
    current: dict[str, Any] = field(default_factory=_grasp_outcome_state)
    completed_attempts: list[dict[str, Any]] = field(default_factory=list)

    def reset(self) -> None:
        self.attempt_index = 0
        self.active = False
        self.awaiting_evidence = False
        self.previous_gripper_state = "idle"
        self.last_time_s = None
        self.current = _grasp_outcome_state()
        self.completed_attempts.clear()

    def attempts(self) -> list[dict[str, Any]]:
        rows = [dict(item) for item in self.completed_attempts]
        if self.attempt_index and not any(
            _safe_int(item.get("attempt_index"), 0) == self.attempt_index for item in rows
        ):
            rows.append(dict(self.current))
        return rows


def _empty_task_cycle_milestones() -> dict[str, bool]:
    return {
        "home_start": False,
        "moving": False,
        "grasping": False,
        "ungrasping": False,
        "home_return": False,
    }


@dataclass
class TaskCycleAnnotator:
    """Count ordered measured home-to-home manipulation cycles."""

    session_id: str = ""
    attempt_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    active: bool = False
    home_armed: bool = False
    state: str = "not_started"
    last_sequence: int = -1
    ungrasping_sequence: int | None = None
    milestones: dict[str, bool] = field(default_factory=_empty_task_cycle_milestones)
    grasp_attempts: dict[int, str] = field(default_factory=dict)

    def reset(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.attempt_count = 0
        self.completed_count = 0
        self.failed_count = 0
        self.active = False
        self.home_armed = False
        self.state = "not_started"
        self.last_sequence = -1
        self.ungrasping_sequence = None
        self.milestones = _empty_task_cycle_milestones()
        self.grasp_attempts.clear()

    def _start_task(self) -> None:
        self.attempt_count += 1
        self.active = True
        self.home_armed = False
        self.state = "active"
        self.ungrasping_sequence = None
        self.milestones = {
            **_empty_task_cycle_milestones(),
            "home_start": True,
            "moving": True,
        }
        self.grasp_attempts.clear()

    def _grasp_summary(self) -> dict[str, int | float | None]:
        statuses = list(self.grasp_attempts.values())
        success_count = sum(status == "success" for status in statuses)
        failed_count = sum(status == "failed" for status in statuses)
        completed_count = success_count + failed_count
        pending_count = len(statuses) - completed_count
        return {
            "task_index": self.attempt_count,
            "attempt_count": len(statuses),
            "completed_count": completed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "success_rate": success_count / completed_count if completed_count else None,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "current_task_index": self.attempt_count,
            "attempt_count": self.attempt_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "success_rate": self.completed_count / self.attempt_count if self.attempt_count else None,
            "milestones": dict(self.milestones),
            "grasp": self._grasp_summary(),
        }

    def observe(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        packet_session_id = str(packet.get("session_id") or "")
        sequence = _safe_int(packet.get("sequence"), self.last_sequence + 1)
        if packet_session_id and self.session_id and packet_session_id != self.session_id:
            self.reset(packet_session_id)
        elif packet_session_id and not self.session_id:
            self.session_id = packet_session_id
        if sequence <= self.last_sequence:
            return self.snapshot()
        self.last_sequence = sequence

        motion = packet.get("motion_state") if isinstance(packet.get("motion_state"), Mapping) else {}
        measured = motion.get("measured") if isinstance(motion.get("measured"), Mapping) else {}
        home_gate = measured.get("home_gate") if isinstance(measured.get("home_gate"), Mapping) else {}
        base_state = str(measured.get("base_state") or "unknown")
        gripper_state = str(measured.get("gripper_state") or "idle")
        stable_home = base_state == "home" and gripper_state == "idle" and bool(home_gate.get("passed"))

        if not self.active:
            if stable_home:
                self.home_armed = True
                if self.state == "not_started":
                    self.milestones["home_start"] = True
            elif self.home_armed and base_state == "moving":
                self._start_task()

        if self.active:
            if base_state == "moving":
                self.milestones["moving"] = True
            if gripper_state == "grasping":
                self.milestones["grasping"] = True

            outcome = motion.get("grasp_outcome") if isinstance(motion.get("grasp_outcome"), Mapping) else {}
            attempt_index = _safe_int(outcome.get("attempt_index"), 0)
            if attempt_index > 0:
                status = str(outcome.get("status") or "pending")
                self.grasp_attempts[attempt_index] = status if status in {"success", "failed"} else "pending"

            if gripper_state == "ungrasping" and self.milestones["grasping"]:
                self.milestones["ungrasping"] = True
                self.ungrasping_sequence = sequence

            if (
                self.milestones["ungrasping"]
                and self.ungrasping_sequence is not None
                and sequence > self.ungrasping_sequence
                and stable_home
            ):
                self.milestones["home_return"] = True
                self.completed_count += 1
                self.active = False
                self.home_armed = True
                self.state = "complete"

        return self.snapshot()


def _gripper_value(packet: Mapping[str, Any], field: str) -> float | None:
    values = packet.get(field)
    if not isinstance(values, Mapping) or values.get("Gripper") is None:
        return None
    value = _safe_float(values.get("Gripper"), math.nan)
    return value if math.isfinite(value) else None


def _packet_elapsed_s(packet: Mapping[str, Any]) -> float:
    return _safe_float(packet.get("elapsed_s"), _safe_float(packet.get("monotonic_s"), 0.0))


def _finalize_grasp_outcome(latch: _GraspOutcomeLatch, packet: Mapping[str, Any]) -> None:
    measured = _gripper_value(packet, "actual_source")
    target = _gripper_value(packet, "target_source")
    if measured is None or target is None:
        latch.awaiting_evidence = True
        latch.current.update(
            {
                "status": "pending",
                "reason": "waiting for measured and policy Gripper evidence",
                "measured_gripper": measured,
                "policy_target_gripper": target,
                "contact_gap": None,
                "completed_s": None,
            }
        )
        return

    contact_gap = abs(measured - target)
    if contact_gap < GRASP_CONTACT_GAP_THRESHOLD:
        status = "failed"
        reason = "absolute gripper gap below required threshold"
    else:
        status = "success"
        reason = "absolute gripper gap met contact threshold"
    latch.awaiting_evidence = False
    latch.current.update(
        {
            "status": status,
            "reason": reason,
            "contact_gap": contact_gap,
            "measured_gripper": measured,
            "policy_target_gripper": target,
            "completed_s": _packet_elapsed_s(packet),
        }
    )
    latch.completed_attempts.append(dict(latch.current))


def _update_grasp_outcome(
    latch: _GraspOutcomeLatch,
    packet: Mapping[str, Any],
    measured_motion: Mapping[str, Any],
) -> dict[str, Any]:
    current_time = _safe_float(packet.get("monotonic_s"), 0.0)
    if latch.last_time_s is not None and current_time < latch.last_time_s:
        latch.reset()
    latch.last_time_s = current_time
    gripper_state = str(measured_motion.get("gripper_state") or "idle")

    entering_grasp = gripper_state == "grasping" and latch.previous_gripper_state != "grasping"
    if entering_grasp:
        if latch.attempt_index and latch.current.get("status") == "pending":
            latch.completed_attempts.append(dict(latch.current))
        latch.attempt_index += 1
        latch.active = True
        latch.awaiting_evidence = False
        latch.current = _grasp_outcome_state(
            status="pending",
            reason="measured grasp in progress",
            attempt_index=latch.attempt_index,
            measured_gripper=_gripper_value(packet, "actual_source"),
            policy_target_gripper=_gripper_value(packet, "target_source"),
            started_s=_packet_elapsed_s(packet),
        )

    leaving_grasp = (
        latch.active
        and latch.previous_gripper_state == "grasping"
        and gripper_state != "grasping"
    )
    if latch.active:
        latch.current["measured_gripper"] = _gripper_value(packet, "actual_source")
        latch.current["policy_target_gripper"] = _gripper_value(packet, "target_source")
        if (
            not leaving_grasp
            and _safe_float(measured_motion.get("arm_speed"), 0.0) >= ARM_MOTION_ENTER_THRESHOLD
        ):
            latch.current["transport_overlap"] = True

    if leaving_grasp:
        latch.active = False
        _finalize_grasp_outcome(latch, packet)
    elif latch.awaiting_evidence:
        _finalize_grasp_outcome(latch, packet)

    latch.previous_gripper_state = gripper_state
    return dict(latch.current)


def _elapsed_since(started_s: float | None, current_s: float) -> float:
    return max(0.0, current_s - started_s) if started_s is not None else 0.0


def _channel_motion_state(
    history: list[Mapping[str, Any]],
    field: str,
    latch: _ChannelMotionLatch,
    *,
    window_s: float = MOTION_WINDOW_S,
    home_ranges: Mapping[str, tuple[float, float]] = MEASURED_HOME_RANGES,
) -> dict[str, Any]:
    available = [packet for packet in history if isinstance(packet.get(field), Mapping) and packet.get(field)]
    if not available:
        return {
            "state": "moving",
            "base_state": "moving",
            "base_confidence": 0.0,
            "base_reason": "joint telemetry unavailable",
            "gripper_state": "idle",
            "gripper_confidence": 0.0,
            "gripper_reason": "joint telemetry unavailable",
            "confidence": 0.0,
            "reason": "joint telemetry unavailable",
            "arm_speed": 0.0,
            "gripper_speed": 0.0,
            "stable_for_s": 0.0,
            "home_gate": _home_gate({}, stable_for_s=0.0, home_ranges=home_ranges),
        }

    current = available[-1]
    current_time = _safe_float(current.get("monotonic_s"), 0.0)
    if latch.last_time_s is not None and current_time < latch.last_time_s:
        latch.reset()
    latch.last_time_s = current_time

    cutoff = current_time - window_s
    prior = [packet for packet in available if _safe_float(packet.get("monotonic_s"), 0.0) < cutoff]
    window = [packet for packet in available if _safe_float(packet.get("monotonic_s"), 0.0) >= cutoff]
    if prior:
        window.insert(0, prior[-1])
    first = window[0] if window else current
    elapsed = max(0.0, current_time - _safe_float(first.get("monotonic_s"), current_time))
    first_values = first.get(field) if isinstance(first.get(field), Mapping) else {}
    current_values = current.get(field) if isinstance(current.get(field), Mapping) else {}

    arm_speeds = [
        abs(_safe_float(current_values.get(joint), 0.0) - _safe_float(first_values.get(joint), 0.0)) / elapsed
        for joint in JOINT_NAMES
        if joint != "Gripper" and elapsed > 0.0 and joint in current_values and joint in first_values
    ]
    arm_speed = max(arm_speeds, default=0.0)
    gripper_speed = 0.0
    if elapsed > 0.0 and "Gripper" in current_values and "Gripper" in first_values:
        gripper_speed = (
            _safe_float(current_values.get("Gripper"), 0.0)
            - _safe_float(first_values.get("Gripper"), 0.0)
        ) / elapsed
    arm_below_exit = arm_speed <= ARM_MOTION_EXIT_THRESHOLD
    gripper_below_exit = abs(gripper_speed) <= GRIPPER_MOTION_EXIT_THRESHOLD

    if arm_below_exit:
        if latch.arm_stable_started_s is None:
            latch.arm_stable_started_s = current_time
    else:
        latch.arm_stable_started_s = None
    arm_stable_for_s = _elapsed_since(latch.arm_stable_started_s, current_time)

    if arm_below_exit and gripper_below_exit:
        if latch.fully_stable_started_s is None:
            latch.fully_stable_started_s = current_time
    else:
        latch.fully_stable_started_s = None
    stable_for_s = _elapsed_since(latch.fully_stable_started_s, current_time)
    previous_base_state = latch.base_state
    moving_active = previous_base_state == "moving"
    if arm_speed >= ARM_MOTION_ENTER_THRESHOLD:
        moving_active = True
        latch.arm_exit_started_s = None
    elif moving_active:
        if arm_below_exit:
            if latch.arm_exit_started_s is None:
                latch.arm_exit_started_s = current_time
            if _elapsed_since(latch.arm_exit_started_s, current_time) >= ARM_MOTION_EXIT_DWELL_S:
                moving_active = False
                latch.arm_exit_started_s = None
        else:
            latch.arm_exit_started_s = None
    else:
        latch.arm_exit_started_s = None

    home_position_passed = _arm_home_position_passed(current_values, home_ranges=home_ranges)
    preserve_latched_home = previous_base_state == "home" and home_position_passed
    if home_position_passed:
        if latch.home_candidate_started_s is None:
            latch.home_candidate_started_s = current_time
    else:
        latch.home_candidate_started_s = None
    home_candidate_for_s = _elapsed_since(latch.home_candidate_started_s, current_time)
    gate = _home_gate(
        current_values,
        stable_for_s=home_candidate_for_s,
        home_ranges=home_ranges,
    )

    if preserve_latched_home or gate["passed"]:
        base_state = "home"
        base_reason = "arm joints remained inside home ranges for required dwell"
        base_confidence = 1.0
    elif moving_active:
        base_state = "moving"
        if arm_speed >= ARM_MOTION_ENTER_THRESHOLD:
            base_reason = f"arm speed {arm_speed:.2f} native units/s"
        else:
            exit_for_s = _elapsed_since(latch.arm_exit_started_s, current_time)
            base_reason = (
                f"arm motion latched; exit dwell {exit_for_s:.2f}/{ARM_MOTION_EXIT_DWELL_S:.2f} s"
            )
        base_confidence = max(0.5, min(1.0, arm_speed / (ARM_MOTION_ENTER_THRESHOLD * 2.0)))
    else:
        base_state = "moving"
        if home_position_passed and home_candidate_for_s > 0.0:
            base_reason = f"waiting for home dwell {home_candidate_for_s:.2f}/{HOME_DWELL_S:.2f} s"
        elif not home_position_passed:
            base_reason = "arm outside home range"
        else:
            base_reason = "waiting for arm stable dwell"
        base_confidence = 0.75 if arm_stable_for_s >= HOME_DWELL_S else 0.4
    latch.base_state = base_state

    previous_gripper_state = latch.gripper_state
    if gripper_speed <= -GRIPPER_MOTION_ENTER_THRESHOLD:
        gripper_state = "grasping"
        gripper_reason = f"gripper closing at {gripper_speed:.2f} native units/s"
        gripper_confidence = min(1.0, abs(gripper_speed) / (GRIPPER_MOTION_ENTER_THRESHOLD * 2.0))
        latch.gripper_exit_started_s = None
    elif gripper_speed >= GRIPPER_MOTION_ENTER_THRESHOLD:
        gripper_state = "ungrasping"
        gripper_reason = f"gripper opening at {gripper_speed:.2f} native units/s"
        gripper_confidence = min(1.0, gripper_speed / (GRIPPER_MOTION_ENTER_THRESHOLD * 2.0))
        latch.gripper_exit_started_s = None
    elif previous_gripper_state in {"grasping", "ungrasping"}:
        gripper_state = previous_gripper_state
        if gripper_below_exit:
            if latch.gripper_exit_started_s is None:
                latch.gripper_exit_started_s = current_time
            exit_for_s = _elapsed_since(latch.gripper_exit_started_s, current_time)
            if exit_for_s >= GRIPPER_MOTION_EXIT_DWELL_S:
                gripper_state = "idle"
                gripper_reason = "gripper stable"
                gripper_confidence = 1.0
                latch.gripper_exit_started_s = None
            else:
                gripper_reason = (
                    f"gripper motion latched; exit dwell "
                    f"{exit_for_s:.2f}/{GRIPPER_MOTION_EXIT_DWELL_S:.2f} s"
                )
                gripper_confidence = 0.5
        else:
            latch.gripper_exit_started_s = None
            direction = "closing" if gripper_state == "grasping" else "opening"
            gripper_reason = f"gripper {direction} at {gripper_speed:.2f} native units/s"
            gripper_confidence = max(
                0.5,
                min(1.0, abs(gripper_speed) / (GRIPPER_MOTION_ENTER_THRESHOLD * 2.0)),
            )
    else:
        gripper_state = "idle"
        gripper_reason = "gripper stable"
        gripper_confidence = 1.0
        latch.gripper_exit_started_s = None
    latch.gripper_state = gripper_state

    state = gripper_state if gripper_state != "idle" else base_state
    confidence = gripper_confidence if gripper_state != "idle" else base_confidence
    reason = gripper_reason if gripper_state != "idle" else base_reason

    return {
        "state": state,
        "base_state": base_state,
        "base_confidence": base_confidence,
        "base_reason": base_reason,
        "gripper_state": gripper_state,
        "gripper_confidence": gripper_confidence,
        "gripper_reason": gripper_reason,
        "confidence": confidence,
        "reason": reason,
        "arm_speed": arm_speed,
        "gripper_speed": gripper_speed,
        "arm_stable_for_s": arm_stable_for_s,
        "stable_for_s": stable_for_s,
        "home_dwell_for_s": home_candidate_for_s,
        "home_gate": gate,
    }


@dataclass
class MotionStateAnnotator:
    window_s: float = MOTION_WINDOW_S
    _history: list[dict[str, Any]] = field(default_factory=list, init=False)
    _measured_latch: _ChannelMotionLatch = field(default_factory=_ChannelMotionLatch, init=False)
    _policy_latch: _ChannelMotionLatch = field(default_factory=_ChannelMotionLatch, init=False)
    _grasp_latch: _GraspOutcomeLatch = field(default_factory=_GraspOutcomeLatch, init=False)
    _task_cycle: TaskCycleAnnotator = field(default_factory=TaskCycleAnnotator, init=False)
    _session_id: str = field(default="", init=False)
    _last_sequence: int = field(default=-1, init=False)
    _execution_index: int = field(default=0, init=False)
    _execution_origin_s: float | None = field(default=None, init=False)

    @property
    def grasp_attempts(self) -> list[dict[str, Any]]:
        return self._grasp_latch.attempts()

    def annotate(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        annotated = dict(packet)
        session_id = str(packet.get("session_id") or "")
        sequence = _safe_int(packet.get("sequence"), self._last_sequence + 1)
        current_time = _safe_float(annotated.get("monotonic_s"), 0.0)
        if (self._execution_index == 0 or session_id != self._session_id or sequence < self._last_sequence):
            # A reused session name can contain a fresh logger invocation.
            # Window reconnects replay the same records, not a new execution.
            self._history.clear()
            self._measured_latch = _ChannelMotionLatch()
            self._policy_latch = _ChannelMotionLatch()
            self._grasp_latch.reset()
            self._task_cycle.reset(session_id)
            self._execution_index += 1
            self._execution_origin_s = current_time - _safe_float(packet.get("elapsed_s"), 0.0) if self._last_sequence < 0 else current_time
        self._session_id = session_id
        self._last_sequence = sequence
        annotated["execution_index"] = self._execution_index
        annotated["elapsed_s"] = max(0.0, current_time - self._execution_origin_s)
        self._history.append(annotated)
        retain_after = current_time - max(self.window_s * 2.0, 1.0)
        self._history = [
            item for item in self._history if _safe_float(item.get("monotonic_s"), 0.0) >= retain_after
        ]
        measured_motion = _channel_motion_state(
            self._history,
            "actual_source",
            self._measured_latch,
            window_s=self.window_s,
            home_ranges=MEASURED_HOME_RANGES,
        )
        policy_motion = _channel_motion_state(
            self._history,
            "target_source",
            self._policy_latch,
            window_s=self.window_s,
            home_ranges=POLICY_HOME_RANGES,
        )
        annotated["motion_state"] = {
            "measured": measured_motion,
            "policy": policy_motion,
            "grasp_outcome": _update_grasp_outcome(
                self._grasp_latch,
                annotated,
                measured_motion,
            ),
        }
        annotated["motion_state"]["task_cycle"] = self._task_cycle.observe(annotated)
        annotated["motion_state"]["grasp_achievement"] = grasp_achievement(self.grasp_attempts, session_id)
        annotated["motion_state"]["grasp_attempt_summary"] = _summarize_grasp_attempts(self.grasp_attempts)
        self._history[-1] = annotated
        return annotated


@dataclass
class PostPlaceInterlock:
    """Latch measured ungrasping followed by a later stable measured home pose."""

    session_id: str = ""
    ungrasping_seen: bool = False
    ungrasping_sequence: int | None = None
    home_after_ungrasping: bool = False
    latest_sequence: int = 0
    measured_base_state: str = "unknown"
    measured_gripper_state: str = "idle"
    home_gate_passed: bool = False

    def reset(self, session_id: str = "") -> None:
        self.session_id = str(session_id or "")
        self.ungrasping_seen = False
        self.ungrasping_sequence = None
        self.home_after_ungrasping = False
        self.latest_sequence = 0
        self.measured_base_state = "unknown"
        self.measured_gripper_state = "idle"
        self.home_gate_passed = False

    def observe(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        packet_session_id = str(packet.get("session_id") or "")
        if packet_session_id and packet_session_id != self.session_id:
            self.reset(packet_session_id)
        elif packet_session_id and not self.session_id:
            self.session_id = packet_session_id

        sequence = _safe_int(packet.get("sequence"), self.latest_sequence)
        motion = packet.get("motion_state") if isinstance(packet.get("motion_state"), Mapping) else {}
        measured = motion.get("measured") if isinstance(motion.get("measured"), Mapping) else {}
        home_gate = measured.get("home_gate") if isinstance(measured.get("home_gate"), Mapping) else {}
        self.latest_sequence = sequence
        self.measured_base_state = str(measured.get("base_state") or "unknown")
        self.measured_gripper_state = str(measured.get("gripper_state") or "idle")
        self.home_gate_passed = bool(home_gate.get("passed"))

        if self.measured_gripper_state == "ungrasping":
            self.ungrasping_seen = True
            self.ungrasping_sequence = sequence

        later_than_release = bool(
            self.ungrasping_sequence is not None
            and sequence > self.ungrasping_sequence
        )
        if (
            self.ungrasping_seen
            and later_than_release
            and self.measured_base_state == "home"
            and self.measured_gripper_state == "idle"
            and self.home_gate_passed
        ):
            self.home_after_ungrasping = True

        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "post_place_interlock.v1",
            "session_id": self.session_id,
            "ungrasping_seen": self.ungrasping_seen,
            "ungrasping_sequence": self.ungrasping_sequence,
            "measured_base_state": self.measured_base_state,
            "measured_gripper_state": self.measured_gripper_state,
            "home_gate_passed": self.home_gate_passed,
            "home_after_ungrasping": self.home_after_ungrasping,
            "ready_for_utm_snapshot": self.home_after_ungrasping,
            "latest_sequence": self.latest_sequence,
        }


def annotate_motion_packets(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotator = MotionStateAnnotator()
    return [annotator.annotate(packet) for packet in packets]


def _annotate_motion_packets_with_attempts(
    packets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    annotator = MotionStateAnnotator()
    annotated = [annotator.annotate(packet) for packet in packets]
    return annotated, annotator.grasp_attempts


def session_status_label(status: Any) -> str:
    clean = str(status or "").upper()
    if clean in TERMINAL_SESSION_STATUSES:
        return "complete" if clean not in {"FAILED", "CANCELLED"} else "failed"
    if clean in {"POLICY_ACTIVE", "RUNNING", "RECORDING", "TELEOP_ACTIVE", "ACTION_ACTIVE"}:
        return "live"
    return "idle"


@dataclass
class _TailState:
    offset: int = 0
    pending: str = ""
    origin_monotonic_s: float | None = None
    initialized: bool = False
    inode: int | None = None
    motion_annotator: MotionStateAnnotator = field(default_factory=MotionStateAnnotator)


@dataclass
class JointTelemetryFileObserver:
    """Incrementally tail action logs without touching the robot process."""

    max_initial_samples: int = 300
    max_batch_samples: int = 128
    max_initial_bytes: int = 2 * 1024 * 1024
    max_batch_bytes: int = 1024 * 1024
    preserve_history: bool = False
    _states: dict[str, _TailState] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def poll(self, path: Path | str, session: Mapping[str, Any]) -> list[dict[str, Any]]:
        log_path = Path(path).expanduser()
        if not log_path.is_file():
            return []
        key = str(log_path.resolve())
        with self._lock:
            state = self._states.setdefault(key, _TailState())
            stat = log_path.stat()
            if state.inode is not None and (state.inode != stat.st_ino or stat.st_size < state.offset):
                state = _TailState()
                self._states[key] = state
            state.inode = stat.st_ino
            initial_read = not state.initialized
            byte_limit = self.max_initial_bytes if initial_read else self.max_batch_bytes
            read_start = state.offset
            available = max(0, stat.st_size - read_start)
            truncated = byte_limit > 0 and available > byte_limit
            if truncated and self.preserve_history:
                # GUI backfill advances from the beginning in bounded chunks.
                # Keep partial lines for the next poll instead of seeking to tail.
                available = byte_limit
                truncated = False
            elif truncated:
                read_start = stat.st_size - byte_limit
                available = byte_limit
            if available > 0:
                with log_path.open("rb") as handle:
                    handle.seek(read_start)
                    chunk = handle.read(available).decode("utf-8", errors="replace")
                    state.offset = handle.tell()
            else:
                chunk = ""
            if truncated:
                state.pending = ""
                newline = chunk.find("\n")
                chunk = chunk[newline + 1 :] if newline >= 0 else ""
            if not chunk and not state.pending:
                return []
            complete_lines, state.pending = _complete_lines(state.pending + chunk)
            events = _json_objects(complete_lines)
            action_events = [event for event in events if str(event.get("event") or "").lower() == "action"]
            if state.origin_monotonic_s is None:
                state.origin_monotonic_s = _first_action_monotonic(action_events)
            limit = self.max_initial_samples if not state.initialized else self.max_batch_samples
            state.initialized = True
            packets = [
                normalize_action_event(event, origin_monotonic_s=state.origin_monotonic_s)
                for event in action_events
            ]
            session_id = str(session.get("session_id") or "")
            workflow = str(session.get("workflow") or "rollout")
            mode = str(session.get("mode") or "")
            status = session_status_label(session.get("status"))
            annotated = [
                state.motion_annotator.annotate({
                    **packet,
                    "session_id": str(packet.get("session_id") or session_id),
                    "workflow": workflow,
                    "mode": mode,
                    "status": status,
                })
                for packet in packets
                if packet is not None
            ]
            # Replay the bounded initial chunk through the state machines, then
            # retain only the display-sized tail for the browser.
            if not self.preserve_history and limit > 0 and len(annotated) > limit:
                return annotated[-limit:]
            return annotated

    def reset(self, path: Path | str | None = None) -> None:
        with self._lock:
            if path is None:
                self._states.clear()
                return
            self._states.pop(str(Path(path).expanduser().resolve()), None)


def _complete_lines(text: str) -> tuple[list[str], str]:
    if not text:
        return [], ""
    lines = text.splitlines(keepends=True)
    pending = ""
    if lines and not lines[-1].endswith(("\n", "\r")):
        pending = lines.pop()
    return [line.rstrip("\r\n") for line in lines if line.strip()], pending


def _json_objects(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _first_action_monotonic(events: list[dict[str, Any]]) -> float | None:
    for event in events:
        if event.get("monotonic_s") is not None:
            return _safe_float(event.get("monotonic_s"), 0.0)
    return None


def _read_normalized_action_packets(path: Path | str) -> list[dict[str, Any]]:
    log_path = Path(path).expanduser()
    if not log_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(event, dict) and str(event.get("event") or "").lower() == "action":
                rows.append(event)
    origin = _first_action_monotonic(rows)
    packets = [normalize_action_event(row, origin_monotonic_s=origin) for row in rows]
    return [packet for packet in packets if packet is not None]


def read_all_action_packets(path: Path | str) -> list[dict[str, Any]]:
    packets = _read_normalized_action_packets(path)
    return annotate_motion_packets(packets)


def empty_grasp_outcome_summary() -> dict[str, int | float | None]:
    return {
        "total_attempts": 0,
        "completed_attempts": 0,
        "success_count": 0,
        "failed_count": 0,
        "pending_count": 0,
        "success_rate": None,
    }


def _summarize_grasp_attempts(attempts: list[dict[str, Any]]) -> dict[str, int | float | None]:
    summary = empty_grasp_outcome_summary()
    success_count = sum(str(item.get("status")) == "success" for item in attempts)
    failed_count = sum(str(item.get("status")) == "failed" for item in attempts)
    pending_count = sum(str(item.get("status")) not in {"success", "failed"} for item in attempts)
    completed_attempts = success_count + failed_count
    summary.update(
        {
            "total_attempts": len(attempts),
            "completed_attempts": completed_attempts,
            "success_count": success_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "success_rate": success_count / completed_attempts if completed_attempts else None,
        }
    )
    return summary


def grasp_achievement(attempts: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    """Preserve first contact success as historical evidence, not object custody."""
    first = next((item for item in attempts if item.get("status") == "success"), None)
    return {
        "schema": GRASP_ACHIEVEMENT_SCHEMA,
        "scope": "rollout_execution",
        "session_id": session_id,
        "achieved": first is not None,
        "status": "achieved" if first is not None else "not_observed",
        "observation_only": True,
        "first_success": dict(first) if first is not None else None,
    }


def _grasp_artifact_response(payload: Mapping[str, Any], *, cached: bool) -> dict[str, Any]:
    attempts = [dict(item) for item in payload.get("attempts", []) if isinstance(item, Mapping)]
    return {
        "ok": True,
        "cached": cached,
        "schema": str(payload.get("schema") or GRASP_OUTCOME_SCHEMA),
        "rule_version": str(payload.get("rule_version") or ""),
        "attempts": attempts,
        "latest_grasp_outcome": dict(attempts[-1]) if attempts else _grasp_outcome_state(),
        "grasp_achievement": dict(payload.get("grasp_achievement") or {}),
        "summary": dict(payload.get("summary") or empty_grasp_outcome_summary()),
        "artifact_path": str(payload.get("artifact_path") or ""),
        "source_size": _safe_int(payload.get("source_size"), 0),
        "source_mtime_ns": _safe_int(payload.get("source_mtime_ns"), 0),
    }


def _write_grasp_outcome_artifact(
    log_path: Path,
    session: Mapping[str, Any],
    attempts: list[dict[str, Any]],
    stat: Any,
) -> dict[str, Any]:
    artifact_path = log_path.with_name("grasp_outcomes.json")
    payload = {
        "schema": GRASP_OUTCOME_SCHEMA,
        "rule_version": GRASP_OUTCOME_RULE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(session.get("session_id") or log_path.parent.name),
        "workflow": str(session.get("workflow") or "rollout"),
        "mode": str(session.get("mode") or ""),
        "status": str(session.get("status") or ""),
        "source_log_path": str(log_path),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "contact_gap_threshold": GRASP_CONTACT_GAP_THRESHOLD,
        "artifact_path": str(artifact_path),
        "attempts": attempts,
        "summary": _summarize_grasp_attempts(attempts),
        "grasp_achievement": grasp_achievement(attempts, str(session.get("session_id") or log_path.parent.name)),
    }
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return _grasp_artifact_response(payload, cached=False)


def finalize_grasp_outcome_artifact(path: Path | str, session: Mapping[str, Any]) -> dict[str, Any]:
    """Replay an action log into a deterministic, read-only grasp outcome artifact."""

    log_path = Path(path).expanduser().resolve()
    if not log_path.is_file():
        return {"ok": False, "failure_code": "JOINT_TELEMETRY_LOG_NOT_FOUND", "path": str(log_path)}
    stat = log_path.stat()
    artifact_path = log_path.with_name("grasp_outcomes.json")
    cached = _read_json(artifact_path)
    if (
        cached.get("schema") == GRASP_OUTCOME_SCHEMA
        and cached.get("rule_version") == GRASP_OUTCOME_RULE_VERSION
        and cached.get("grasp_achievement", {}).get("schema") == GRASP_ACHIEVEMENT_SCHEMA
        and cached.get("source_size") == stat.st_size
        and cached.get("source_mtime_ns") == stat.st_mtime_ns
    ):
        return _grasp_artifact_response(cached, cached=True)

    packets = _read_normalized_action_packets(log_path)
    if not packets:
        return {"ok": False, "failure_code": "JOINT_TELEMETRY_EMPTY", "path": str(log_path)}
    _, attempts = _annotate_motion_packets_with_attempts(packets)
    return _write_grasp_outcome_artifact(log_path, session, attempts, stat)


def finalize_policy_tracking_artifacts(path: Path | str, session: Mapping[str, Any]) -> dict[str, Any]:
    """Write an idempotent six-joint publication figure and metric summary."""

    log_path = Path(path).expanduser().resolve()
    if not log_path.is_file():
        return {"ok": False, "failure_code": "JOINT_TELEMETRY_LOG_NOT_FOUND", "path": str(log_path)}
    stat = log_path.stat()
    png_path = log_path.with_name("policy_tracking.png")
    summary_path = log_path.with_name("policy_tracking_summary.json")
    grasp_path = log_path.with_name("grasp_outcomes.json")
    cached_summary = _read_json(summary_path)
    if (
        cached_summary.get("source_size") == stat.st_size
        and cached_summary.get("source_mtime_ns") == stat.st_mtime_ns
        and cached_summary.get("value_space") == "lerobot_native"
        and cached_summary.get("grasp_outcome_schema") == GRASP_OUTCOME_SCHEMA
        and cached_summary.get("grasp_outcome_rule_version") == GRASP_OUTCOME_RULE_VERSION
        and cached_summary.get("grasp_achievement", {}).get("schema") == GRASP_ACHIEVEMENT_SCHEMA
        and png_path.is_file()
        and grasp_path.is_file()
    ):
        return _artifact_response(cached_summary, cached=True)

    normalized_packets = _read_normalized_action_packets(log_path)
    packets, grasp_attempts = _annotate_motion_packets_with_attempts(normalized_packets)
    if not packets:
        return {"ok": False, "failure_code": "JOINT_TELEMETRY_EMPTY", "path": str(log_path)}

    metrics = _tracking_metrics(packets)
    source_metrics = _source_tracking_metrics(packets)
    grasp_artifact = _write_grasp_outcome_artifact(log_path, session, grasp_attempts, stat)
    _write_tracking_figure(packets, png_path, session_id=str(session.get("session_id") or log_path.parent.name))
    summary = {
        "schema": ARTIFACT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(session.get("session_id") or log_path.parent.name),
        "workflow": str(session.get("workflow") or "rollout"),
        "status": str(session.get("status") or ""),
        "sample_count": len(packets),
        "duration_s": float(packets[-1].get("elapsed_s") or 0.0),
        "value_space": "lerobot_native",
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "plot_png_path": str(png_path),
        "summary_json_path": str(summary_path),
        "raw_jsonl_path": str(log_path),
        "raw_csv_path": str(log_path.with_name("motor_events.csv")),
        "grasp_outcomes_path": str(grasp_path),
        "grasp_outcome_schema": GRASP_OUTCOME_SCHEMA,
        "grasp_outcome_rule_version": GRASP_OUTCOME_RULE_VERSION,
        "grasp_outcomes": dict(grasp_artifact.get("summary") or empty_grasp_outcome_summary()),
        "latest_grasp_outcome": dict(grasp_artifact.get("latest_grasp_outcome") or _grasp_outcome_state()),
        "grasp_achievement": dict(grasp_artifact["grasp_achievement"]),
        "metrics": metrics,
        "source_metrics": source_metrics,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return _artifact_response(summary, cached=False)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _artifact_response(summary: Mapping[str, Any], *, cached: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "cached": cached,
        "sample_count": _safe_int(summary.get("sample_count"), 0),
        "source_size": _safe_int(summary.get("source_size"), 0),
        "source_mtime_ns": _safe_int(summary.get("source_mtime_ns"), 0),
        "plot_png_path": str(summary.get("plot_png_path") or ""),
        "summary_json_path": str(summary.get("summary_json_path") or ""),
        "raw_jsonl_path": str(summary.get("raw_jsonl_path") or ""),
        "raw_csv_path": str(summary.get("raw_csv_path") or ""),
        "grasp_outcomes_path": str(summary.get("grasp_outcomes_path") or ""),
        "grasp_outcomes": dict(summary.get("grasp_outcomes") or empty_grasp_outcome_summary()),
        "latest_grasp_outcome": dict(summary.get("latest_grasp_outcome") or _grasp_outcome_state()),
        "grasp_achievement": dict(summary.get("grasp_achievement") or {}),
        "metrics": dict(summary.get("metrics") or {}),
        "source_metrics": dict(summary.get("source_metrics") or {}),
        "value_space": str(summary.get("value_space") or ""),
    }


def _tracking_metrics(packets: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for joint in JOINT_NAMES:
        errors = []
        for packet in packets:
            actual = packet.get("actual_deg") or {}
            target = packet.get("target_deg") or {}
            if joint not in actual or joint not in target:
                continue
            errors.append(float(target[joint]) - float(actual[joint]))
        if not errors:
            continue
        absolute = [abs(value) for value in errors]
        result[joint] = {
            "samples": len(errors),
            "mae_deg": sum(absolute) / len(absolute),
            "rmse_deg": math.sqrt(sum(value * value for value in errors) / len(errors)),
            "max_abs_error_deg": max(absolute),
        }
    return result


def _source_tracking_metrics(packets: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for joint in JOINT_NAMES:
        actual_values: list[float] = []
        target_values: list[float] = []
        for packet in packets:
            actual = packet.get("actual_source") or {}
            target = packet.get("target_source") or {}
            if joint not in actual or joint not in target:
                continue
            actual_values.append(float(actual[joint]))
            target_values.append(float(target[joint]))
        if not actual_values:
            continue
        errors = [target - actual for actual, target in zip(actual_values, target_values, strict=True)]
        absolute = [abs(value) for value in errors]
        result[joint] = {
            "samples": len(errors),
            "mae_native": sum(absolute) / len(absolute),
            "rmse_native": math.sqrt(sum(value * value for value in errors) / len(errors)),
            "max_abs_error_native": max(absolute),
            "actual_min": min(actual_values),
            "actual_max": max(actual_values),
            "target_min": min(target_values),
            "target_max": max(target_values),
        }
    return result


def _write_tracking_figure(packets: list[dict[str, Any]], output_path: Path, *, session_id: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    elapsed = [float(packet.get("elapsed_s") or 0.0) for packet in packets]
    with plt.rc_context(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#4b5563",
            "axes.labelcolor": "#111827",
            "xtick.color": "#374151",
            "ytick.color": "#374151",
            "font.size": 8.5,
            "axes.titlesize": 9.5,
            "axes.labelsize": 8.5,
            "legend.fontsize": 8.5,
            "lines.linewidth": 1.15,
        }
    ):
        figure, axes = plt.subplots(3, 2, figsize=(7.2, 7.3), dpi=180, sharex=True)
        for axis, joint in zip(axes.flat, JOINT_NAMES, strict=True):
            actual = [float((packet.get("actual_source") or {}).get(joint, math.nan)) for packet in packets]
            target = [float((packet.get("target_source") or {}).get(joint, math.nan)) for packet in packets]
            axis.plot(elapsed, actual, color="#1f77b4", label="Measured follower")
            axis.plot(elapsed, target, color="#ff7f0e", label="Policy target")
            axis.set_title(joint, loc="left", fontweight="semibold")
            axis.set_ylabel("Position (%)" if joint == "Gripper" else "LeRobot value")
            axis.grid(True, color="#e5e7eb", linewidth=0.6)
            axis.spines["top"].set_visible(False)
            axis.spines["right"].set_visible(False)
        axes[-1, 0].set_xlabel("Elapsed time (s)")
        axes[-1, 1].set_xlabel("Elapsed time (s)")
        handles, labels = axes[0, 0].get_legend_handles_labels()
        figure.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.987))
        figure.suptitle(f"OMX Policy Tracking | {session_id}", y=0.998, fontsize=10.5, fontweight="semibold")
        figure.tight_layout(rect=(0.02, 0.02, 0.98, 0.955))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, facecolor="white", bbox_inches="tight")
        plt.close(figure)
