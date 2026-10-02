import pytest

from utils import lerobot_joint_telemetry as telemetry


def sample(latch, time, gap=1.5, state="idle", valid=True):
    return telemetry._update_grasp_outcome(latch, {
        "monotonic_s": time, "elapsed_s": time,
        "actual_source": {"Gripper": 50 + gap},
        "target_source": {"Gripper": 50} if valid else {},
    }, {"gripper_state": state, "arm_speed": 0})


def test_contact_requires_one_second_and_continues_after_closing_stops():
    latch = telemetry._GraspOutcomeLatch()
    sample(latch, 0, gap=.58, state="grasping")
    assert sample(latch, .1, gap=.58)["status"] == "pending"
    for i in range(2, 12):
        assert sample(latch, i / 10)["status"] == "pending"
    result = sample(latch, 1.2)
    assert result["status"] == "success"
    assert result["completed_s"] == pytest.approx(1.2)
    assert result["observation_only"] is True
    assert len(latch.completed_attempts) == 1
    assert sample(latch, 1.3, gap=0, state="ungrasping")["status"] == "success"


@pytest.mark.parametrize("interruption", ["below", "reverse", "missing", "gap"])
def test_contact_timer_restarts_after_invalid_evidence(interruption):
    latch = telemetry._GraspOutcomeLatch()
    sample(latch, 0, state="grasping")
    for i in range(1, 6):
        sample(latch, i / 10)
    if interruption == "gap":
        start = 2.0
        sample(latch, start)
    else:
        sample(latch, .6, gap=-2 if interruption == "reverse" else .1,
               valid=interruption != "missing")
        start = .7
        sample(latch, start)
    for i in range(1, 10):
        assert sample(latch, start + i / 10)["status"] == "pending"
    assert sample(latch, start + 1.01)["status"] == "success"


def test_no_success_after_release_or_from_reverse_gap():
    latch = telemetry._GraspOutcomeLatch()
    sample(latch, 0, gap=-2, state="grasping")
    for i in range(1, 15):
        assert sample(latch, i / 10, gap=-2)["status"] == "pending"
    assert sample(latch, 1.5, state="ungrasping")["status"] == "failed"
    for i in range(16, 30):
        assert sample(latch, i / 10)["status"] == "failed"
    assert len(latch.completed_attempts) == 1


def test_closing_resumes_without_splitting_same_hold_attempt():
    latch = telemetry._GraspOutcomeLatch()
    sample(latch, 0, state="grasping")
    for i in range(1, 11):
        result = sample(latch, i / 10, state="grasping" if i == 5 else "idle")
    assert result["status"] == "success"
    assert result["attempt_index"] == 1


def test_versioned_display_artifacts_do_not_overwrite_legacy_server_records(tmp_path):
    import json
    from tests.unit.test_lerobot_joint_telemetry import _grasp_attempt_samples, _pose_event, _write_jsonl
    raw = tmp_path / "motor_events.jsonl"
    _write_jsonl(raw, [_pose_event(i, t, actual=a, target=b)
        for i, (t, a, b) in enumerate(_grasp_attempt_samples(), 1)])
    legacy = tmp_path / "grasp_outcomes.json"
    legacy.write_text('{"rule_version":"absolute_contact_gap_v4"}')
    before = raw.read_bytes()
    result = telemetry.finalize_policy_tracking_artifacts(raw, {"session_id": "test"},
        artifact_dir=tmp_path / "grasp_display_v5")
    assert result["grasp_achievement"]["achieved"] is True
    assert json.loads(legacy.read_text())["rule_version"] == "absolute_contact_gap_v4"
    assert raw.read_bytes() == before
    assert result["grasp_outcomes_path"] == str(tmp_path / "grasp_display_v5/grasp_outcomes.json")
