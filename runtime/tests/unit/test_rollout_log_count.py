"""A missing counter in the bounded log tail is not proof of zero robot actions."""
from device_bridges.lerobot.bridge import LeRobotBridge


def test_stopped_log_without_counter_reports_unknown_not_zero_actions():
    result = LeRobotBridge._runtime_status_from_log(None, {"workflow": "rollout", "status": "STOPPED"}, "camera disconnected")
    assert result["action_count_observed"] is False
    assert "0 actions" not in result["message"]


def test_explicit_counter_is_retained_after_stop():
    result = LeRobotBridge._runtime_status_from_log(None, {"workflow": "rollout", "status": "STOPPED"},
        "[ATR_ACTION] count=24 max_abs_delta=0.2")
    assert result["action_count_observed"] is True
    assert result["action_count"] == 24
