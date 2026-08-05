from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import lerobot_joint_telemetry as joint_telemetry
from utils.lerobot_joint_telemetry import (
    JointTelemetryFileObserver,
    annotate_motion_packets,
    finalize_policy_tracking_artifacts,
    normalize_action_event,
)


def _action_event(
    sequence: int,
    monotonic_s: float,
    *,
    actual_offset: float = 0.0,
    target_offset: float = 2.0,
) -> dict[str, object]:
    actual = {
        "shoulder_pan.pos": 10.0 + actual_offset,
        "shoulder_lift.pos": -20.0 + actual_offset,
        "elbow_flex.pos": 30.0 + actual_offset,
        "wrist_flex.pos": -10.0 + actual_offset,
        "wrist_roll.pos": 5.0 + actual_offset,
        "gripper.pos": 50.0 + actual_offset,
    }
    target = {key: float(value) + target_offset for key, value in actual.items()}
    sent = {key: float(value) - 0.5 for key, value in target.items()}
    return {
        "sequence": sequence,
        "session_id": "rollout-test",
        "timestamp": f"2026-07-13T00:00:{sequence:02d}+00:00",
        "monotonic_s": monotonic_s,
        "event": "action",
        "latest_observation": actual,
        "requested_action": target,
        "sent_action": sent,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_normalize_action_event_exposes_measured_requested_and_applied_targets() -> None:
    packet = normalize_action_event(_action_event(7, 101.5), origin_monotonic_s=100.0)

    assert packet is not None
    assert packet["schema"] == "atr.robot_joint_telemetry.v1"
    assert packet["type"] == "joint_sample"
    assert packet["session_id"] == "rollout-test"
    assert packet["sequence"] == 7
    assert packet["elapsed_s"] == pytest.approx(1.5)
    assert list(packet["actual_deg"]) == ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper"]
    assert packet["actual_deg"]["Joint1"] == pytest.approx(10.0)
    assert packet["target_deg"]["Joint1"] == pytest.approx(12.0)
    assert packet["applied_target_deg"]["Joint1"] == pytest.approx(11.5)
    assert packet["actual_rad"]["Joint1"] == pytest.approx(0.1745329252)
    assert packet["target_rad"]["Joint1"] == pytest.approx(0.2094395102)


def test_normalize_action_event_preserves_lerobot_native_values() -> None:
    packet = normalize_action_event(_action_event(7, 101.5), origin_monotonic_s=100.0)

    assert packet is not None
    assert packet["actual_source"] == {
        "Joint1": pytest.approx(10.0),
        "Joint2": pytest.approx(-20.0),
        "Joint3": pytest.approx(30.0),
        "Joint4": pytest.approx(-10.0),
        "Joint5": pytest.approx(5.0),
        "Gripper": pytest.approx(50.0),
    }
    assert packet["target_source"]["Joint2"] == pytest.approx(-18.0)
    assert packet["applied_target_source"]["Joint2"] == pytest.approx(-18.5)
    assert packet["actual_deg"]["Joint2"] != pytest.approx(packet["actual_source"]["Joint2"])


def _pose_event(
    sequence: int,
    monotonic_s: float,
    *,
    actual: dict[str, float],
    target: dict[str, float] | None = None,
) -> dict[str, object]:
    key_map = {
        "Joint1": "shoulder_pan.pos",
        "Joint2": "shoulder_lift.pos",
        "Joint3": "elbow_flex.pos",
        "Joint4": "wrist_flex.pos",
        "Joint5": "wrist_roll.pos",
        "Gripper": "gripper.pos",
    }
    requested = target or actual
    return {
        "sequence": sequence,
        "session_id": "motion-state-test",
        "timestamp": f"2026-07-14T00:00:{sequence:02d}+00:00",
        "monotonic_s": monotonic_s,
        "event": "action",
        "latest_observation": {key_map[key]: value for key, value in actual.items()},
        "requested_action": {key_map[key]: value for key, value in requested.items()},
        "sent_action": {key_map[key]: value for key, value in requested.items()},
    }


HOME_POSE = {
    "Joint1": -11.0,
    "Joint2": -57.0,
    "Joint3": 56.0,
    "Joint4": 47.5,
    "Joint5": -7.0,
    "Gripper": 60.0,
}

POLICY_HOME_POSE = {
    **HOME_POSE,
    "Joint2": -69.0,
}


def _motion_packet(
    sequence: int,
    *,
    session_id: str = "rollout-interlock",
    measured_base: str = "moving",
    measured_gripper: str = "idle",
    measured_home: bool = False,
    policy_gripper: str = "idle",
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "sequence": sequence,
        "motion_state": {
            "measured": {
                "base_state": measured_base,
                "gripper_state": measured_gripper,
                "home_gate": {"passed": measured_home},
            },
            "policy": {
                "base_state": "home" if measured_home else "moving",
                "gripper_state": policy_gripper,
                "home_gate": {"passed": measured_home},
            },
        },
    }


def _post_place_interlock():
    gate_type = getattr(joint_telemetry, "PostPlaceInterlock", None)
    assert gate_type is not None, "PostPlaceInterlock is not implemented"
    return gate_type()


def _task_cycle_annotator():
    annotator_type = getattr(joint_telemetry, "TaskCycleAnnotator", None)
    assert annotator_type is not None, "TaskCycleAnnotator is not implemented"
    return annotator_type()


def _task_cycle_packet(
    sequence: int,
    *,
    base: str,
    gripper: str = "idle",
    home: bool = False,
    grasp_status: str = "idle",
    grasp_index: int = 0,
) -> dict[str, object]:
    packet = _motion_packet(
        sequence,
        measured_base=base,
        measured_gripper=gripper,
        measured_home=home,
    )
    packet["motion_state"]["grasp_outcome"] = {
        "status": grasp_status,
        "attempt_index": grasp_index,
    }
    return packet


def test_task_cycle_counts_one_ordered_home_to_home_task() -> None:
    annotator = _task_cycle_annotator()
    packets = [
        _task_cycle_packet(1, base="home", home=True),
        _task_cycle_packet(2, base="moving"),
        _task_cycle_packet(3, base="moving", gripper="grasping", grasp_status="pending", grasp_index=1),
        _task_cycle_packet(4, base="moving", grasp_status="success", grasp_index=1),
        _task_cycle_packet(5, base="moving", gripper="ungrasping", grasp_status="success", grasp_index=1),
        _task_cycle_packet(6, base="home", home=True, grasp_status="success", grasp_index=1),
    ]

    result = {}
    for packet in packets:
        result = annotator.observe(packet)

    assert result["attempt_count"] == 1
    assert result["completed_count"] == 1
    assert result["success_rate"] == pytest.approx(1.0)
    assert result["state"] == "complete"
    assert result["milestones"] == {
        "home_start": True,
        "moving": True,
        "grasping": True,
        "ungrasping": True,
        "home_return": True,
    }
    assert result["grasp"] == {
        "task_index": 1,
        "attempt_count": 1,
        "completed_count": 1,
        "success_count": 1,
        "failed_count": 0,
        "pending_count": 0,
        "success_rate": pytest.approx(1.0),
    }


def test_task_cycle_deduplicates_samples_and_keeps_multiple_grasps_in_one_task() -> None:
    annotator = _task_cycle_annotator()
    packets = [
        _task_cycle_packet(1, base="home", home=True),
        _task_cycle_packet(2, base="moving"),
        _task_cycle_packet(3, base="moving"),
        _task_cycle_packet(4, base="moving", gripper="grasping", grasp_status="pending", grasp_index=1),
        _task_cycle_packet(5, base="moving", grasp_status="failed", grasp_index=1),
        _task_cycle_packet(6, base="moving", gripper="grasping", grasp_status="pending", grasp_index=2),
        _task_cycle_packet(7, base="moving", grasp_status="success", grasp_index=2),
        _task_cycle_packet(8, base="moving", gripper="ungrasping", grasp_status="success", grasp_index=2),
        _task_cycle_packet(9, base="home", home=True, grasp_status="success", grasp_index=2),
    ]

    result = {}
    for packet in packets:
        result = annotator.observe(packet)

    assert result["attempt_count"] == 1
    assert result["completed_count"] == 1
    assert result["grasp"]["attempt_count"] == 2
    assert result["grasp"]["completed_count"] == 2
    assert result["grasp"]["success_count"] == 1
    assert result["grasp"]["failed_count"] == 1
    assert result["grasp"]["success_rate"] == pytest.approx(0.5)


def test_task_cycle_accumulates_five_tasks_and_reports_latest_task_grasp_retry() -> None:
    annotator = _task_cycle_annotator()
    sequence = 0
    result: dict[str, object] = {}

    for task_index in range(1, 6):
        sequence += 1
        result = annotator.observe(_task_cycle_packet(sequence, base="home", home=True))
        sequence += 1
        result = annotator.observe(_task_cycle_packet(sequence, base="moving"))

        if task_index == 5:
            sequence += 1
            result = annotator.observe(
                _task_cycle_packet(
                    sequence,
                    base="moving",
                    gripper="grasping",
                    grasp_status="pending",
                    grasp_index=1,
                )
            )
            sequence += 1
            result = annotator.observe(
                _task_cycle_packet(sequence, base="moving", grasp_status="failed", grasp_index=1)
            )

        grasp_index = 2 if task_index == 5 else 1
        sequence += 1
        result = annotator.observe(
            _task_cycle_packet(
                sequence,
                base="moving",
                gripper="grasping",
                grasp_status="pending",
                grasp_index=grasp_index,
            )
        )
        sequence += 1
        result = annotator.observe(
            _task_cycle_packet(sequence, base="moving", grasp_status="success", grasp_index=grasp_index)
        )
        sequence += 1
        result = annotator.observe(
            _task_cycle_packet(
                sequence,
                base="moving",
                gripper="ungrasping",
                grasp_status="success",
                grasp_index=grasp_index,
            )
        )
        sequence += 1
        result = annotator.observe(
            _task_cycle_packet(
                sequence,
                base="home",
                home=True,
                grasp_status="success",
                grasp_index=grasp_index,
            )
        )

    assert result["attempt_count"] == 5
    assert result["completed_count"] == 5
    assert result["success_rate"] == pytest.approx(1.0)
    assert result["state"] == "complete"
    assert result["grasp"]["task_index"] == 5
    assert result["grasp"]["attempt_count"] == 2
    assert result["grasp"]["completed_count"] == 2
    assert result["grasp"]["success_count"] == 1
    assert result["grasp"]["failed_count"] == 1
    assert result["grasp"]["success_rate"] == pytest.approx(0.5)


def test_task_cycle_does_not_start_without_stable_measured_home() -> None:
    annotator = _task_cycle_annotator()

    result = annotator.observe(_task_cycle_packet(1, base="moving"))
    result = annotator.observe(
        _task_cycle_packet(2, base="moving", gripper="grasping", grasp_status="success", grasp_index=1)
    )

    assert result["attempt_count"] == 0
    assert result["completed_count"] == 0
    assert result["success_rate"] is None
    assert result["state"] == "not_started"


def test_post_place_interlock_requires_measured_ungrasping_before_stable_home() -> None:
    gate = _post_place_interlock()

    home_first = gate.observe(
        _motion_packet(10, measured_base="home", measured_home=True)
    )
    released = gate.observe(
        _motion_packet(11, measured_gripper="ungrasping")
    )

    assert home_first["ready_for_utm_snapshot"] is False
    assert released["ungrasping_seen"] is True
    assert released["home_after_ungrasping"] is False


def test_post_place_interlock_ignores_policy_only_ungrasping() -> None:
    gate = _post_place_interlock()

    gate.observe(_motion_packet(20, policy_gripper="ungrasping"))
    result = gate.observe(
        _motion_packet(21, measured_base="home", measured_home=True)
    )

    assert result["ungrasping_seen"] is False
    assert result["ready_for_utm_snapshot"] is False


def test_post_place_interlock_opens_after_measured_release_and_later_idle_home() -> None:
    gate = _post_place_interlock()

    gate.observe(_motion_packet(30, measured_gripper="ungrasping"))
    result = gate.observe(
        _motion_packet(
            31,
            measured_base="home",
            measured_gripper="idle",
            measured_home=True,
        )
    )

    assert result == {
        "schema": "post_place_interlock.v1",
        "session_id": "rollout-interlock",
        "ungrasping_seen": True,
        "ungrasping_sequence": 30,
        "measured_base_state": "home",
        "measured_gripper_state": "idle",
        "home_gate_passed": True,
        "home_after_ungrasping": True,
        "ready_for_utm_snapshot": True,
        "latest_sequence": 31,
    }


def test_post_place_interlock_resets_when_rollout_session_changes() -> None:
    gate = _post_place_interlock()
    gate.observe(_motion_packet(40, measured_gripper="ungrasping"))

    result = gate.observe(
        _motion_packet(
            1,
            session_id="rollout-next",
            measured_base="home",
            measured_home=True,
        )
    )

    assert result["session_id"] == "rollout-next"
    assert result["ungrasping_seen"] is False
    assert result["home_after_ungrasping"] is False
    assert result["ready_for_utm_snapshot"] is False


def _annotated_pair(
    first_actual: dict[str, float],
    second_actual: dict[str, float],
    *,
    first_target: dict[str, float] | None = None,
    second_target: dict[str, float] | None = None,
) -> dict[str, object]:
    packets = [
        normalize_action_event(
            _pose_event(1, 10.0, actual=first_actual, target=first_target),
            origin_monotonic_s=10.0,
        ),
        normalize_action_event(
            _pose_event(2, 10.6, actual=second_actual, target=second_target),
            origin_monotonic_s=10.0,
        ),
    ]
    clean = [packet for packet in packets if packet is not None]
    return annotate_motion_packets(clean)[-1]


def _annotated_sequence(
    samples: list[tuple[float, dict[str, float], dict[str, float] | None]],
) -> list[dict[str, object]]:
    origin = samples[0][0]
    packets = [
        normalize_action_event(
            _pose_event(index, monotonic_s, actual=actual, target=target),
            origin_monotonic_s=origin,
        )
        for index, (monotonic_s, actual, target) in enumerate(samples, start=1)
    ]
    return annotate_motion_packets([packet for packet in packets if packet is not None])


def _grasp_attempt_samples(
    *,
    start_s: float = 30.0,
    measured_gripper: float = 53.5,
    policy_gripper: float | None = 50.0,
    transport_overlap: bool = False,
) -> list[tuple[float, dict[str, float], dict[str, float] | None]]:
    open_pose = {**HOME_POSE, "Gripper": 60.0}
    closing_pose = {**HOME_POSE, "Gripper": 55.0}
    contact_pose = {**HOME_POSE, "Gripper": measured_gripper}
    if transport_overlap:
        contact_pose = {**contact_pose, "Joint1": -5.0}
    policy = {**POLICY_HOME_POSE, "Gripper": policy_gripper} if policy_gripper is not None else {
        joint: value for joint, value in POLICY_HOME_POSE.items() if joint != "Gripper"
    }
    return [
        (start_s, open_pose, policy),
        (start_s + 0.6, open_pose, policy),
        (start_s + 1.2, closing_pose, policy),
        (start_s + 1.8, contact_pose, policy),
        (start_s + 2.4, contact_pose, policy),
        (start_s + 2.65, contact_pose, policy),
    ]


def _append_release_samples(
    samples: list[tuple[float, dict[str, float], dict[str, float] | None]],
    *,
    start_s: float,
) -> None:
    open_pose = {**HOME_POSE, "Gripper": 60.0}
    policy_open = {**POLICY_HOME_POSE, "Gripper": 60.0}
    samples.extend(
        [
            (start_s, open_pose, policy_open),
            (start_s + 0.6, open_pose, policy_open),
            (start_s + 0.85, open_pose, policy_open),
        ]
    )


def test_motion_annotation_classifies_stable_home_and_populates_gate() -> None:
    packet = _annotated_pair(HOME_POSE, HOME_POSE)

    measured = packet["motion_state"]["measured"]
    assert measured["state"] == "home"
    assert measured["base_state"] == "home"
    assert measured["gripper_state"] == "idle"
    assert measured["stable_for_s"] == pytest.approx(0.6)
    assert measured["home_gate"]["passed"] is True
    assert measured["home_gate"]["joints"]["Joint1"] == {
        "value": pytest.approx(-11.0),
        "minimum": -15.0,
        "maximum": -1.0,
        "passed": True,
    }


def test_motion_annotation_keeps_observed_joint1_quantization_inside_home() -> None:
    quantized_home = {**HOME_POSE, "Joint1": -6.9}

    packet = _annotated_pair(quantized_home, quantized_home)
    measured = packet["motion_state"]["measured"]

    assert measured["base_state"] == "home"
    assert measured["home_gate"]["passed"] is True
    assert measured["home_gate"]["joints"]["Joint1"]["maximum"] == -1.0


def test_motion_annotation_uses_separate_measured_and_policy_joint2_home_ranges() -> None:
    packet = _annotated_pair(
        HOME_POSE,
        HOME_POSE,
        first_target=POLICY_HOME_POSE,
        second_target=POLICY_HOME_POSE,
    )

    measured = packet["motion_state"]["measured"]
    policy = packet["motion_state"]["policy"]

    assert measured["base_state"] == "home"
    assert policy["base_state"] == "home"
    assert measured["home_gate"]["joints"]["Joint2"] == {
        "value": pytest.approx(-57.0),
        "minimum": -64.0,
        "maximum": -53.0,
        "passed": True,
    }
    assert policy["home_gate"]["joints"]["Joint2"] == {
        "value": pytest.approx(-69.0),
        "minimum": -72.0,
        "maximum": -62.0,
        "passed": True,
    }


def test_motion_annotation_accepts_refreshed_measured_home_pose() -> None:
    refreshed_home_low = {
        "Joint1": -7.78,
        "Joint2": -61.86,
        "Joint3": 51.99,
        "Joint4": 41.05,
        "Joint5": -5.41,
        "Gripper": 59.88,
    }
    refreshed_home_high = {
        "Joint1": -2.33,
        "Joint2": -61.76,
        "Joint3": 56.34,
        "Joint4": 50.97,
        "Joint5": -2.59,
        "Gripper": 60.0,
    }

    packet = _annotated_pair(refreshed_home_low, refreshed_home_high)
    measured = packet["motion_state"]["measured"]

    assert measured["base_state"] == "home"
    assert measured["home_gate"]["passed"] is True
    assert measured["home_gate"]["joints"]["Joint2"] == {
        "value": pytest.approx(-61.76),
        "minimum": -64.0,
        "maximum": -53.0,
        "passed": True,
    }
    assert measured["home_gate"]["joints"]["Joint1"]["maximum"] == -1.0


def test_motion_annotation_prefers_home_after_position_dwell_under_servo_jitter() -> None:
    jittered_home = {**HOME_POSE, "Joint1": -8.0}
    packets = _annotated_sequence(
        [
            (10.0, HOME_POSE, None),
            (10.6, jittered_home, None),
        ]
    )

    measured = packets[-1]["motion_state"]["measured"]
    assert measured["arm_speed"] > joint_telemetry.ARM_MOTION_ENTER_THRESHOLD
    assert measured["base_state"] == "home"
    assert measured["home_gate"]["passed"] is True


def test_motion_annotation_uses_arm_enter_exit_hysteresis() -> None:
    mild_home_motion = {**HOME_POSE, "Joint1": -9.08}
    outside_home = {**HOME_POSE, "Joint1": 0.0}
    packets = _annotated_sequence(
        [
            (10.0, HOME_POSE, None),
            (10.6, HOME_POSE, None),
            (11.2, mild_home_motion, None),
            (11.8, outside_home, None),
            (12.4, outside_home, None),
            (12.6, outside_home, None),
            (12.75, outside_home, None),
        ]
    )

    states = [packet["motion_state"]["measured"]["base_state"] for packet in packets]

    assert states == ["moving", "home", "home", "moving", "moving", "moving", "moving"]


def test_motion_annotation_uses_gripper_enter_exit_hysteresis() -> None:
    closing = {**HOME_POSE, "Gripper": 58.5}
    packets = _annotated_sequence(
        [
            (20.0, HOME_POSE, None),
            (20.6, HOME_POSE, None),
            (21.2, closing, None),
            (21.8, closing, None),
            (21.9, closing, None),
            (22.05, closing, None),
        ]
    )

    states = [packet["motion_state"]["measured"]["gripper_state"] for packet in packets]

    assert states == ["idle", "idle", "grasping", "grasping", "grasping", "idle"]


def test_motion_annotation_classifies_every_non_home_arm_pose_as_moving() -> None:
    moving_pose = {**HOME_POSE, "Joint1": 0.0}
    moving = _annotated_pair(HOME_POSE, moving_pose)
    off_home_pose = {**HOME_POSE, "Joint1": 20.0}
    off_home = _annotated_pair(off_home_pose, off_home_pose)

    assert moving["motion_state"]["measured"]["state"] == "moving"
    assert moving["motion_state"]["measured"]["base_state"] == "moving"
    assert moving["motion_state"]["measured"]["gripper_state"] == "idle"
    assert off_home["motion_state"]["measured"]["state"] == "moving"
    assert off_home["motion_state"]["measured"]["base_state"] == "moving"
    assert off_home["motion_state"]["measured"]["home_gate"]["position_passed"] is False


def test_motion_annotation_keeps_gripper_direction_orthogonal_to_arm_state() -> None:
    closed = {**HOME_POSE, "Gripper": 50.0}
    open_pose = {**HOME_POSE, "Gripper": 60.0}
    policy_closed = {**POLICY_HOME_POSE, "Gripper": 50.0}
    policy_open = {**POLICY_HOME_POSE, "Gripper": 60.0}
    packet = _annotated_pair(
        open_pose,
        open_pose,
        first_target=policy_closed,
        second_target=policy_open,
    )
    moving_and_grasping = _annotated_pair(open_pose, {**closed, "Joint1": -6.0})
    off_home_open = {**open_pose, "Joint1": 20.0}
    off_home_closed = {**closed, "Joint1": 20.0}
    off_home_and_grasping = _annotated_pair(off_home_open, off_home_closed)

    assert packet["motion_state"]["measured"]["state"] == "home"
    assert packet["motion_state"]["measured"]["base_state"] == "home"
    assert packet["motion_state"]["measured"]["gripper_state"] == "idle"
    assert packet["motion_state"]["policy"]["state"] == "ungrasping"
    assert packet["motion_state"]["policy"]["base_state"] == "home"
    assert packet["motion_state"]["policy"]["gripper_state"] == "ungrasping"
    assert moving_and_grasping["motion_state"]["measured"]["state"] == "grasping"
    assert moving_and_grasping["motion_state"]["measured"]["base_state"] == "moving"
    assert moving_and_grasping["motion_state"]["measured"]["gripper_state"] == "grasping"
    assert off_home_and_grasping["motion_state"]["measured"]["base_state"] == "moving"
    assert off_home_and_grasping["motion_state"]["measured"]["gripper_state"] == "grasping"


def test_grasp_outcome_enters_pending_then_succeeds_from_contact_gap() -> None:
    packets = _annotated_sequence(_grasp_attempt_samples())

    assert packets[2]["motion_state"]["grasp_outcome"]["status"] == "pending"
    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result == {
        "status": "success",
        "reason": "absolute gripper gap met contact threshold",
        "attempt_index": 1,
        "observation_only": True,
        "contact_gap": pytest.approx(3.5),
        "contact_gap_threshold": pytest.approx(2.0),
        "measured_gripper": pytest.approx(53.5),
        "policy_target_gripper": pytest.approx(50.0),
        "transport_overlap": False,
        "started_s": pytest.approx(1.2),
        "completed_s": pytest.approx(2.65),
    }


def test_grasp_outcome_fails_when_contact_gap_is_below_threshold() -> None:
    packets = _annotated_sequence(
        _grasp_attempt_samples(measured_gripper=50.1, policy_gripper=50.0)
    )

    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result["status"] == "failed"
    assert result["reason"] == "absolute gripper gap below required threshold"
    assert result["contact_gap"] == pytest.approx(0.1)
    assert result["transport_overlap"] is False


def test_grasp_outcome_ignores_arm_transport_when_contact_gap_is_sufficient() -> None:
    packets = _annotated_sequence(
        _grasp_attempt_samples(measured_gripper=53.5, transport_overlap=True)
    )

    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result["status"] == "success"
    assert result["reason"] == "absolute gripper gap met contact threshold"
    assert result["contact_gap"] == pytest.approx(3.5)
    assert result["transport_overlap"] is True


def test_grasp_outcome_uses_absolute_gripper_gap() -> None:
    packets = _annotated_sequence(
        _grasp_attempt_samples(measured_gripper=47.5, policy_gripper=50.0)
    )

    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result["status"] == "success"
    assert result["contact_gap"] == pytest.approx(2.5)


def test_grasp_outcome_does_not_count_transport_starting_on_completion_packet() -> None:
    samples = _grasp_attempt_samples(measured_gripper=53.5)
    final_time, final_actual, final_target = samples[-1]
    samples[-1] = (final_time, {**final_actual, "Joint1": 0.0}, final_target)

    packets = _annotated_sequence(samples)

    assert packets[-1]["motion_state"]["measured"]["base_state"] == "moving"
    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result["status"] == "success"
    assert result["transport_overlap"] is False


def test_grasp_outcome_stays_pending_when_policy_target_is_missing() -> None:
    packets = _annotated_sequence(_grasp_attempt_samples(policy_gripper=None))

    result = packets[-1]["motion_state"]["grasp_outcome"]
    assert result["status"] == "pending"
    assert result["reason"] == "waiting for measured and policy Gripper evidence"
    assert result["policy_target_gripper"] is None
    assert result["completed_s"] is None


def test_grasp_outcome_persists_through_ungrasping_until_next_attempt() -> None:
    samples = _grasp_attempt_samples()
    _append_release_samples(samples, start_s=33.25)
    packets = _annotated_sequence(samples)

    assert packets[-1]["motion_state"]["measured"]["gripper_state"] == "idle"
    assert packets[-1]["motion_state"]["grasp_outcome"]["status"] == "success"
    assert packets[-1]["motion_state"]["grasp_outcome"]["attempt_index"] == 1


def test_grasp_outcome_finalizes_when_grasp_transitions_directly_to_ungrasping() -> None:
    samples = _grasp_attempt_samples()[:4]
    policy_open = {**POLICY_HOME_POSE, "Gripper": 60.0}
    samples.append((32.0, {**HOME_POSE, "Gripper": 60.0}, policy_open))

    packets = _annotated_sequence(samples)

    assert packets[-1]["motion_state"]["measured"]["gripper_state"] == "ungrasping"
    outcome = packets[-1]["motion_state"]["grasp_outcome"]
    assert outcome["status"] != "pending"
    assert outcome["attempt_index"] == 1
    assert outcome["completed_s"] == pytest.approx(2.0)


def test_normalize_action_event_rejects_non_action_and_incomplete_rows() -> None:
    assert normalize_action_event({"event": "observation"}) is None
    assert normalize_action_event({"event": "action", "latest_observation": {}}) is None


def test_file_observer_reads_only_new_complete_action_rows(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "lerobot_action_logs" / "rollout-test" / "motor_events.jsonl"
    rows = [
        {"event": "observation", "sequence": 1, "positions": {"shoulder_pan.pos": 1.0}},
        _action_event(2, 20.0),
    ]
    _write_jsonl(path, rows)
    observer = JointTelemetryFileObserver(max_initial_samples=8, max_batch_samples=8)
    session = {"session_id": "rollout-test", "workflow": "rollout", "status": "POLICY_ACTIVE", "mode": "live"}

    first = observer.poll(path, session)
    assert [packet["sequence"] for packet in first] == [2]
    assert first[0]["status"] == "live"

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_action_event(3, 20.05)) + "\n")
        handle.write('{"event":"action"')

    second = observer.poll(path, session)
    assert [packet["sequence"] for packet in second] == [3]
    assert observer.poll(path, session) == []


def test_file_observer_bounds_initial_backlog(tmp_path: Path) -> None:
    path = tmp_path / "motor_events.jsonl"
    _write_jsonl(path, [_action_event(index, 50.0 + index * 0.05) for index in range(1, 11)])
    observer = JointTelemetryFileObserver(max_initial_samples=3, max_batch_samples=2)

    packets = observer.poll(path, {"session_id": "rollout-test", "workflow": "rollout", "status": "POLICY_ACTIVE"})

    assert [packet["sequence"] for packet in packets] == [8, 9, 10]


def test_file_observer_replays_bounded_preroll_for_task_cycle_totals(tmp_path: Path) -> None:
    path = tmp_path / "motor_events.jsonl"
    moving = {**HOME_POSE, "Joint1": 20.0}
    closing = {**moving, "Gripper": 55.0}
    contact = {**moving, "Gripper": 53.5}
    policy_moving = {**POLICY_HOME_POSE, "Joint1": 20.0}
    policy_contact = {**policy_moving, "Gripper": 50.0}
    samples = [
        (0.0, HOME_POSE, POLICY_HOME_POSE),
        (0.6, HOME_POSE, POLICY_HOME_POSE),
        (1.2, moving, policy_moving),
        (1.8, closing, policy_contact),
        (2.4, contact, policy_contact),
        (3.0, contact, policy_contact),
        (3.6, moving, policy_moving),
        (4.2, moving, policy_moving),
        (4.8, HOME_POSE, POLICY_HOME_POSE),
        (5.4, HOME_POSE, POLICY_HOME_POSE),
        (6.0, HOME_POSE, POLICY_HOME_POSE),
    ]
    _write_jsonl(
        path,
        [
            _pose_event(index, monotonic_s, actual=actual, target=target)
            for index, (monotonic_s, actual, target) in enumerate(samples, start=1)
        ],
    )
    observer = JointTelemetryFileObserver(max_initial_samples=2, max_batch_samples=2)

    packets = observer.poll(
        path,
        {"session_id": "motion-state-test", "workflow": "rollout", "status": "POLICY_ACTIVE"},
    )

    assert [packet["sequence"] for packet in packets] == [10, 11]
    assert packets[-1]["motion_state"]["task_cycle"]["attempt_count"] == 1
    assert packets[-1]["motion_state"]["task_cycle"]["completed_count"] == 1


def test_file_observer_uses_a_bounded_initial_file_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "motor_events.jsonl"
    _write_jsonl(path, [_action_event(index, 50.0 + index * 0.05) for index in range(1, 80)])
    original_open = Path.open
    read_sizes: list[int] = []

    class TrackingHandle:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def __enter__(self) -> "TrackingHandle":
            self._handle.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._handle.__exit__(*args)

        def __getattr__(self, name: str) -> object:
            return getattr(self._handle, name)

        def read(self, size: int = -1) -> object:
            read_sizes.append(size)
            return self._handle.read(size)

    def tracking_open(target: Path, *args: object, **kwargs: object) -> object:
        handle = original_open(target, *args, **kwargs)
        return TrackingHandle(handle) if target == path else handle

    monkeypatch.setattr(Path, "open", tracking_open)
    observer = JointTelemetryFileObserver(
        max_initial_samples=3,
        max_batch_samples=2,
        max_initial_bytes=4096,
        max_batch_bytes=2048,
    )

    packets = observer.poll(path, {"session_id": "rollout-test", "workflow": "rollout", "status": "POLICY_ACTIVE"})

    assert [packet["sequence"] for packet in packets] == [77, 78, 79]
    assert read_sizes
    assert all(0 < size <= 4096 for size in read_sizes)


def test_finalize_policy_tracking_artifacts_writes_publication_figure_and_summary(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "lerobot_action_logs" / "rollout-test" / "motor_events.jsonl"
    _write_jsonl(
        path,
        [
            _action_event(1, 100.0, actual_offset=0.0, target_offset=2.0),
            _action_event(2, 100.1, actual_offset=1.0, target_offset=2.0),
            _action_event(3, 100.2, actual_offset=2.0, target_offset=2.0),
        ],
    )
    session = {"session_id": "rollout-test", "workflow": "rollout", "status": "COMPLETED", "mode": "live"}

    artifacts = finalize_policy_tracking_artifacts(path, session)

    assert artifacts["ok"] is True
    assert artifacts["sample_count"] == 3
    png_path = Path(artifacts["plot_png_path"])
    summary_path = Path(artifacts["summary_json_path"])
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema"] == "atr.policy_tracking_artifact.v1"
    assert summary["session_id"] == "rollout-test"
    assert summary["sample_count"] == 3
    assert summary["value_space"] == "lerobot_native"
    assert summary["source_metrics"]["Joint2"]["mae_native"] == pytest.approx(2.0)
    assert summary["source_metrics"]["Joint2"]["actual_min"] == pytest.approx(-20.0)
    assert summary["source_metrics"]["Joint2"]["actual_max"] == pytest.approx(-18.0)
    assert summary["metrics"]["Joint1"]["mae_deg"] == pytest.approx(2.0)
    assert summary["metrics"]["Joint1"]["rmse_deg"] == pytest.approx(2.0)
    assert summary["raw_jsonl_path"] == str(path)
    assert summary["raw_csv_path"].endswith("motor_events.csv")


def test_finalize_policy_tracking_artifacts_persists_grasp_attempts_and_aggregate(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "lerobot_action_logs" / "grasp-summary" / "motor_events.jsonl"
    samples: list[tuple[float, dict[str, float], dict[str, float] | None]] = []
    for index, measured in enumerate((53.5, 50.1, 53.2, 53.8)):
        start_s = 100.0 + index * 5.0
        samples.extend(
            _grasp_attempt_samples(
                start_s=start_s,
                measured_gripper=measured,
                policy_gripper=50.0,
            )
        )
        if index < 3:
            _append_release_samples(samples, start_s=start_s + 3.25)
    rows = [
        _pose_event(index, monotonic_s, actual=actual, target=target)
        for index, (monotonic_s, actual, target) in enumerate(samples, start=1)
    ]
    _write_jsonl(path, rows)
    session = {"session_id": "grasp-summary", "workflow": "rollout", "status": "COMPLETED", "mode": "live"}

    artifacts = finalize_policy_tracking_artifacts(path, session)

    grasp_path = Path(artifacts["grasp_outcomes_path"])
    payload = json.loads(grasp_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "atr.grasp_outcomes.v1"
    assert [attempt["status"] for attempt in payload["attempts"]] == [
        "success",
        "failed",
        "success",
        "success",
    ]
    assert payload["summary"] == {
        "total_attempts": 4,
        "completed_attempts": 4,
        "success_count": 3,
        "failed_count": 1,
        "pending_count": 0,
        "success_rate": pytest.approx(0.75),
    }
    assert artifacts["latest_grasp_outcome"]["attempt_index"] == 4
    assert artifacts["latest_grasp_outcome"]["status"] == "success"
    summary = json.loads(Path(artifacts["summary_json_path"]).read_text(encoding="utf-8"))
    assert summary["grasp_outcomes"] == payload["summary"]


def test_finalize_policy_tracking_artifacts_is_idempotent_for_unchanged_log(tmp_path: Path) -> None:
    path = tmp_path / "motor_events.jsonl"
    _write_jsonl(path, [_action_event(1, 1.0), _action_event(2, 1.1)])
    session = {"session_id": "rollout-test", "workflow": "rollout", "status": "STOPPED"}

    first = finalize_policy_tracking_artifacts(path, session)
    second = finalize_policy_tracking_artifacts(path, session)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cached"] is True
    assert second["source_size"] == first["source_size"]
