from __future__ import annotations

import json

from utils.recording_specimen_pose import load_recording_specimen_pose


def test_load_recording_specimen_pose_reads_accepted_active_cam_attempt(tmp_path) -> None:
    result_path = tmp_path / "latest_active_robot_cam_result.json"
    result_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "applied",
                "attempts": [
                    {
                        "camera": "d405",
                        "result": {
                            "ok": True,
                            "snapshot": {
                                "ok": True,
                                "pose": {
                                    "schema": "specimen_pose.v1",
                                    "frame_id": "frame-42",
                                    "position_isaac_world_mm": {"x": 247.724, "y": 306.265, "z": 15.2},
                                    "orientation_deg": {"yaw": 12.047},
                                    "confidence": 0.91,
                                },
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pose = load_recording_specimen_pose(result_path)

    assert pose["schema"] == "specimen_pose.v1"
    assert pose["frame_id"] == "frame-42"
    assert pose["position_isaac_world_mm"] == {"x": 247.724, "y": 306.265, "z": 15.2}
    assert pose["orientation_deg"] == {"yaw": 12.047}


def test_load_recording_specimen_pose_rejects_failed_or_incomplete_results(tmp_path) -> None:
    result_path = tmp_path / "latest_active_robot_cam_result.json"
    result_path.write_text(
        json.dumps(
            {
                "ok": True,
                "attempts": [
                    {
                        "result": {
                            "ok": True,
                            "snapshot": {
                                "ok": True,
                                "pose": {
                                    "schema": "specimen_pose.v1",
                                    "position_isaac_world_mm": {"x": 10.0, "y": 20.0},
                                },
                            },
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_recording_specimen_pose(result_path) == {}
