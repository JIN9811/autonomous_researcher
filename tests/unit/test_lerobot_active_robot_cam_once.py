from __future__ import annotations

from scripts import lerobot_active_robot_cam_once


def test_accepts_resume_timeout_within_tracker_soft_tolerance() -> None:
    wait_result = {
        "ok": False,
        "status": "timeout",
        "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
        "max_error_deg": 2.1001,
        "tolerance_deg": 2.0,
    }

    result = lerobot_active_robot_cam_once._accept_soft_resume_tolerance(wait_result, soft_tolerance_deg=3.0)

    assert result["ok"] is True
    assert result["status"] == "reached_within_soft_tolerance"
    assert result["warning_only"] is True
    assert result["max_error_deg"] == 2.1001
    assert result["soft_tolerance_deg"] == 3.0


def test_rejects_resume_timeout_outside_tracker_soft_tolerance() -> None:
    wait_result = {
        "ok": False,
        "status": "timeout",
        "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
        "max_error_deg": 3.1001,
        "tolerance_deg": 2.0,
    }

    result = lerobot_active_robot_cam_once._accept_soft_resume_tolerance(wait_result, soft_tolerance_deg=3.0)

    assert result == wait_result
