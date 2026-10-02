from types import SimpleNamespace

from utils.vision_capture_preview import publish_capture_preview


def test_preview_never_overwrites_verification_authority():
    record = {"confirmed": True, "status": "confirmed"}
    state = SimpleNamespace(run_id="run", loop_count=1,
        current_experiment_spec={"specimen_id": "spec"}, run_metadata={
            "utm_verifications": {"run_id": "run", "loop_id": 1,
                "specimen_id": "spec", "verification_1": record}})
    assert publish_capture_preview(state, {"frame_path": "/capture.png"}, "verification_1")
    scope = state.run_metadata["utm_verifications"]
    assert scope["verification_1"] is record
    assert scope["previews"]["verification_1"]["confirmed"] is False
    assert scope["previews"]["verification_1"]["status"] == "pending"
    assert not publish_capture_preview(state, {"frame_path": "/old.png", "run_id": "other"}, "verification_2")
    assert not publish_capture_preview(state, {"frame_path": "/old.png", "capture_skipped": True}, "verification_2")
    assert "verification_2" not in scope["previews"]
