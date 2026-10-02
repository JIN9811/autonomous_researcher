from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


class FakeSpecimenPoseTracker:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.release_calls = 0

    def status(self):
        return {"ok": True, "tool": "vision.specimen_pose.status", "lease": {"owner": "vla_runtime"}}

    def snapshot(self, payload):
        self.snapshot_calls += 1
        return {
            "ok": True,
            "tool": "vision.specimen_pose_snapshot",
            "pose": {
                "schema": "specimen_pose.v1",
                "specimen_id": payload.get("specimen_id", "specimen"),
                "port_released": True,
                "vla_camera_precheck_ok": True,
                "camera_owner_after": "vla_runtime",
                "position_robot_base_mm": {"x": 1.0, "y": 2.0, "z": 3.0},
                "confidence": 0.91,
            },
            "lease": {"owner": "vla_runtime"},
        }

    def release(self, payload):
        self.release_calls += 1
        return {"ok": True, "tool": "vision.specimen_pose.release", "camera_returned_to_vla": True, "lease": {"owner": "vla_runtime"}}


def test_specimen_pose_tracker_api(monkeypatch) -> None:
    fake = FakeSpecimenPoseTracker()
    monkeypatch.setattr(app_main, "_specimen_pose_tracker", fake, raising=False)
    client = TestClient(app)

    status = client.get("/api/vision/specimen-pose/status").json()
    assert status["ok"] is True
    assert status["lease"]["owner"] == "vla_runtime"

    snapshot = client.post("/api/vision/specimen-pose/snapshot", json={"mode": "test", "specimen_id": "specimen-1"}).json()
    assert snapshot["ok"] is True
    assert snapshot["pose"]["schema"] == "specimen_pose.v1"
    assert snapshot["pose"]["port_released"] is True
    assert fake.snapshot_calls == 1

    release = client.post("/api/vision/specimen-pose/release", json={"mode": "test"}).json()
    assert release["camera_returned_to_vla"] is True
    assert fake.release_calls == 1
