from __future__ import annotations

import pytest

from utils.manipulation_runtime_view import build_manipulation_runtime_view


def test_first_grasp_achievement_does_not_replace_attempt_rate_or_verify_transfer():
    achievement = {"achieved": True, "status": "achieved", "first_success": {"attempt_index": 1, "status": "success"}}
    view = build_manipulation_runtime_view(
        session={"session_id": "transfer-1", "status": "POLICY_ACTIVE"}, state={}, artifacts={},
        packet={"motion_state": {
            "grasp_achievement": achievement,
            "grasp_attempt_summary": {"total_attempts": 2, "completed_attempts": 2, "success_count": 1, "failed_count": 1, "pending_count": 0, "success_rate": 0.5},
            "task_cycle": {"state": "not_started"},
        }},
    )
    assert view["metrics"]["grasp_achievement"] == achievement
    assert view["metrics"]["grasp"]["attempt_count"] == 2
    assert view["metrics"]["grasp"]["success_rate"] == 0.5
    assert view["result"]["vision_verification_status"] == "waiting"


def test_idle_runtime_view_keeps_fixed_schema_without_inventing_metrics() -> None:
    view = build_manipulation_runtime_view(session={}, state={}, packet=None, artifacts={})

    assert view["schema"] == "manipulation_runtime_view.v1"
    assert view["status"] == "not_started"
    assert view["execution"]["runtime_status"] == "not_started"
    assert [gate["id"] for gate in view["interlocks"]] == [
        "follower_port_lease",
        "camera_lease",
        "policy_process",
        "measured_home",
        "emergency_stop",
        "safe_stop",
        "vision_pickup",
        "workspace_clear",
    ]
    assert [step["id"] for step in view["completion"]["steps"]] == [
        "ungrasping_seen",
        "home_after_ungrasping",
        "utm_snapshot_requested",
        "specimen_detected_at_utm",
        "ready_to_stop_rollout",
        "rollout_stop_confirmed",
        "ready_for_equipment",
    ]
    assert view["metrics"]["task_cycle"]["attempt_count"] == 0
    assert view["metrics"]["task_cycle"]["success_rate"] is None
    assert view["metrics"]["grasp"]["attempt_count"] == 0
    assert view["metrics"]["grasp"]["success_rate"] is None


def test_running_runtime_view_uses_configured_and_measured_sources() -> None:
    state = {
        "run_id": "run-42",
        "stage": "manipulation",
        "safe_stop_requested": False,
        "emergency_stop_requested": False,
        "run_metadata": {
            "manipulation_report": {
                "run_id": "run-42",
                "session_id": "rollout-42",
                "task": {
                    "task_id": "transfer_to_utm",
                    "canonical_instruction": "Move the specimen to the UTM fixture",
                    "specimen_id": "specimen-42",
                    "source_location": "printer_output",
                    "target_location": "utm_fixture",
                },
                "policy_plan": {"policy_type": "smolvla", "policy_ref": "/models/checkpoint-40000"},
                "rollout_runtime": {
                    "status": "POLICY_ACTIVE",
                    "started_at": "2026-07-20T01:00:00+00:00",
                    "duration_s": 12.5,
                    "policy_runtime": {"pid": 4321, "status": "POLICY_ACTIVE"},
                },
                "stage_machine": {"current_stage": "transfer_to_fixture"},
                "port_lease": {"status": "ready", "current_availability": "leased"},
                "active_camera_lease": {"status": "ready", "returned_to_vla": True},
                "vision_context": {"pickup_target_ready": True},
            },
        },
    }
    packet = {
        "sequence": 88,
        "elapsed_s": 12.5,
        "motion_state": {
            "measured": {"home_gate": {"passed": False}},
            "task_cycle": {
                "state": "active",
                "current_task_index": 2,
                "attempt_count": 2,
                "completed_count": 1,
                "failed_count": 0,
                "success_rate": 0.5,
                "milestones": {"home_start": True, "moving": True},
                "grasp": {
                    "task_index": 2,
                    "attempt_count": 2,
                    "completed_count": 1,
                    "success_count": 1,
                    "failed_count": 0,
                    "pending_count": 1,
                    "success_rate": 1.0,
                },
            },
        },
    }

    view = build_manipulation_runtime_view(
        session={"session_id": "rollout-42", "status": "POLICY_ACTIVE", "policy_path": "/models/checkpoint-40000"},
        state=state,
        packet=packet,
        artifacts={},
    )

    assert view["status"] == "running"
    assert view["execution"] == {
        "run_id": "run-42",
        "rollout_session_id": "rollout-42",
        "task_id": "transfer_to_utm",
        "task_instruction": "Move the specimen to the UTM fixture",
        "specimen_id": "specimen-42",
        "source_location": "printer_output",
        "target_location": "utm_fixture",
        "policy_type": "smolvla",
        "policy_checkpoint_path": "/models/checkpoint-40000",
        "process_pid": 4321,
        "runtime_status": "POLICY_ACTIVE",
        "current_stage": "transfer_to_fixture",
        "started_at": "2026-07-20T01:00:00+00:00",
        "elapsed_s": pytest.approx(12.5),
    }
    gates = {gate["id"]: gate for gate in view["interlocks"]}
    assert gates["follower_port_lease"]["status"] == "pass"
    assert gates["camera_lease"]["status"] == "pass"
    assert gates["policy_process"]["status"] == "pass"
    assert gates["measured_home"]["status"] == "waiting"
    assert gates["emergency_stop"]["status"] == "pass"
    assert gates["safe_stop"]["status"] == "pass"
    assert gates["vision_pickup"]["status"] == "pass"
    assert gates["workspace_clear"]["status"] == "unknown"
    assert view["metrics"]["task_cycle"]["attempt_count"] == 2
    assert view["metrics"]["task_cycle"]["completed_count"] == 1
    assert view["metrics"]["task_cycle"]["pending_count"] == 1
    assert view["metrics"]["grasp"]["attempt_count"] == 2
    assert view["metrics"]["grasp"]["success_count"] == 1
    assert view["metrics"]["sample_count"] == 88
    assert view["provenance"]["task_cycle"] == "DERIVED"


def test_estop_and_resume_change_only_the_gate_not_task_cycle_counts() -> None:
    packet = {
        "sequence": 44,
        "motion_state": {
            "task_cycle": {
                "state": "active",
                "attempt_count": 3,
                "completed_count": 2,
                "success_rate": 2 / 3,
                "grasp": {
                    "attempt_count": 1,
                    "completed_count": 1,
                    "success_count": 1,
                    "failed_count": 0,
                    "pending_count": 0,
                    "success_rate": 1.0,
                },
            }
        },
    }
    stopped = build_manipulation_runtime_view(
        session={"status": "POLICY_ACTIVE"},
        state={"emergency_stop_requested": True, "safe_stop_requested": False},
        packet=packet,
        artifacts={},
    )
    resumed = build_manipulation_runtime_view(
        session={"status": "POLICY_ACTIVE"},
        state={"emergency_stop_requested": False, "safe_stop_requested": False},
        packet=packet,
        artifacts={},
    )

    stopped_gates = {gate["id"]: gate["status"] for gate in stopped["interlocks"]}
    resumed_gates = {gate["id"]: gate["status"] for gate in resumed["interlocks"]}
    assert stopped_gates["emergency_stop"] == "block"
    assert resumed_gates["emergency_stop"] == "pass"
    assert stopped["metrics"]["task_cycle"] == resumed["metrics"]["task_cycle"]
    assert resumed["metrics"]["task_cycle"]["attempt_count"] == 3
    assert resumed["metrics"]["task_cycle"]["completed_count"] == 2


def test_failed_only_grasp_preserves_explicit_zero_success_count() -> None:
    packet = {
        "motion_state": {
            "task_cycle": {
                "attempt_count": 1,
                "completed_count": 0,
                "grasp": {
                    "attempt_count": 1,
                    "completed_count": 1,
                    "success_count": 0,
                    "failed_count": 1,
                    "pending_count": 0,
                    "success_rate": 0.0,
                },
            }
        }
    }

    view = build_manipulation_runtime_view(session={}, state={}, packet=packet, artifacts={})

    assert view["metrics"]["grasp"]["success_count"] == 0
    assert view["metrics"]["grasp"]["failed_count"] == 1
    assert view["metrics"]["grasp"]["success_rate"] == 0.0


def test_terminal_runtime_view_preserves_result_and_completion_evidence() -> None:
    state = {
        "run_id": "run-terminal",
        "stage": "vision",
        "run_metadata": {
            "manipulation_report": {
                "rollout_stop": {"ok": True, "status": "STOPPED"},
                "active_camera_lease": {"returned_to_vla": True},
            },
            "robot_task_result": {
                "status": "complete",
                "handoff_status": "ready_for_equipment",
                "next_action": "lab_equipment_agent",
                "post_place_interlock": {
                    "ungrasping_seen": True,
                    "home_after_ungrasping": True,
                    "ready_for_utm_snapshot": True,
                    "latest_sequence": 321,
                },
                "completion_signal_identity": {
                    "requested": True,
                    "detected": True,
                    "ready_to_stop_rollout": True,
                    "camera_key": "utm",
                    "confidence": 0.94,
                    "evidence_path": "/runs/utm.png",
                },
                "evidence_refs": [{"type": "run_dir", "path": "/runs/run-terminal"}],
            },
        },
    }
    packet = {
        "sequence": 321,
        "elapsed_s": 18.0,
        "motion_state": {
            "task_cycle": {
                "state": "complete",
                "attempt_count": 1,
                "completed_count": 1,
                "failed_count": 0,
                "success_rate": 1.0,
                "grasp": {
                    "attempt_count": 2,
                    "completed_count": 2,
                    "success_count": 1,
                    "failed_count": 1,
                    "pending_count": 0,
                    "success_rate": 0.5,
                },
            }
        },
    }
    artifacts = {"ok": True, "sample_count": 321, "plot_png_path": "/runs/policy.png"}

    view = build_manipulation_runtime_view(
        session={"session_id": "rollout-terminal", "status": "COMPLETED"},
        state=state,
        packet=packet,
        artifacts=artifacts,
    )

    assert view["status"] == "complete"
    assert all(step["status"] == "pass" for step in view["completion"]["steps"])
    assert view["completion"]["terminal"] is True
    assert view["result"]["status"] == "complete"
    assert view["result"]["rollout_stop_status"] == "STOPPED"
    assert view["result"]["vision_verification_status"] == "pass"
    assert view["result"]["home_return_status"] == "pass"
    assert view["result"]["next_agent"] == "lab_equipment_agent"
    assert view["result"]["artifact_directory"] == "/runs/run-terminal"
    assert view["metrics"]["task_cycle"]["success_rate"] == pytest.approx(1.0)
    assert view["metrics"]["grasp"]["success_rate"] == pytest.approx(0.5)
    assert view["metrics"]["sample_count"] == 321
