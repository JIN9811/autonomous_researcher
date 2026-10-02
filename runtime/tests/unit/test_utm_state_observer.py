"""Tests for UTM ROS topic state observation."""

from __future__ import annotations

from types import SimpleNamespace
import pytest

from device_bridges.utm_state_observer import (
    INSUFFICIENT_EVIDENCE,
    apply_quasistatic_motion_threshold,
    _parse_ros2_string_data,
    _parse_ros2_string_stream,
    read_compression_tester_summary_once,
    summarize_utm_state_sequence,
)


@pytest.mark.parametrize("drift,expected", [(-0.4, "DOWN"), (-0.25, "DOWN"),
    (-0.249, "STABLE"), (0.0, "STABLE"), (0.249, "STABLE"), (0.25, "UP"), (0.4, "UP")])
def test_quasistatic_motion_compares_endpoints(drift, expected):
    samples = [{"state": "WORKING", "point_count": 4,
                "span_y": 95 + (drift if i >= 50 else 0)} for i in range(100)]
    original = summarize_utm_state_sequence(samples)
    original["duration_sec"] = 10.0
    result = apply_quasistatic_motion_threshold(original)
    assert result["motion_direction"] == expected
    assert result["motion_delta_px"] == pytest.approx(drift)
    assert result["motion_threshold_px"] == 0.25
    assert original["motion_direction"] == "STABLE"


@pytest.mark.parametrize("jitter", [-0.5, 0.5])
def test_quasistatic_motion_rejects_endpoint_jitter_and_short_windows(jitter):
    samples = [{"state": "WORKING", "point_count": 4, "span_y": 95.0} for _ in range(100)]
    for sample in samples[-1:]:
        sample["span_y"] += jitter
    observation = summarize_utm_state_sequence(samples)
    observation["duration_sec"] = 10.0
    assert apply_quasistatic_motion_threshold(observation)["motion_direction"] == "STABLE"
    observation["duration_sec"] = 3.0
    assert apply_quasistatic_motion_threshold(observation) == observation


def test_quasistatic_motion_uses_final_position_not_intermediate_excursion():
    samples = [{"state": "WORKING", "point_count": 4,
                "span_y": 95.0 if i < 3 or i >= 97 else 85.0} for i in range(100)]
    observation = summarize_utm_state_sequence(samples)
    observation["duration_sec"] = 10.0
    result = apply_quasistatic_motion_threshold(observation)
    assert result["motion_direction"] == "STABLE"
    assert result["motion_delta_px"] == 0.0


def test_quasistatic_downward_requires_valid_marker_evidence():
    samples = [{"state": "UNKNOWN", "point_count": 0, "span_y": 95 - i} for i in range(100)]
    observation = summarize_utm_state_sequence(samples)
    observation["duration_sec"] = 10.0
    assert apply_quasistatic_motion_threshold(observation) == observation


def test_quasistatic_downward_preserves_clear_upward_motion():
    samples = [{"state": "WORKING", "point_count": 4, "span_y": 95 + i} for i in range(100)]
    observation = summarize_utm_state_sequence(samples)
    observation["duration_sec"] = 10.0
    assert apply_quasistatic_motion_threshold(observation)["motion_direction"] == "UP"


def test_parse_ros2_string_stream_returns_each_summary_sample() -> None:
    output = (
        'data: "{\\"state\\": \\"WORKING\\", \\"span_y\\": 210.0, \\"point_count\\": 2}"\n---\n'
        'data: "{\\"state\\": \\"NOT_WORKING\\", \\"span_y\\": 290.0, \\"point_count\\": 2}"\n---\n'
    )

    samples = _parse_ros2_string_stream(output)

    assert [sample["state"] for sample in samples] == ["WORKING", "NOT_WORKING"]
    assert all(sample["summary_fresh"] is True for sample in samples)


def test_parse_ros2_string_stream_ignores_lost_message_warnings() -> None:
    output = (
        'data: "{\\"state\\": \\"WORKING\\", \\"span_y\\": 210.0, \\"point_count\\": 2}"\n---\n'
        "A message was lost!!!\n\ttotal count change:7\n\ttotal count: 7---\n"
        'data: "{\\"state\\": \\"NOT_WORKING\\", \\"span_y\\": 290.0, \\"point_count\\": 2}"\n---\n'
    )

    samples = _parse_ros2_string_stream(output)

    assert [sample["state"] for sample in samples] == ["WORKING", "NOT_WORKING"]


def test_parse_ros2_string_stream_accepts_field_only_json_output() -> None:
    output = (
        '{"state": "NOT_WORKING", "span_y": 290.0, "point_count": 4}\n---\n'
        '{"state": "NOT_WORKING", "span_y": 291.0, "point_count": 4}\n---\n'
    )

    samples = _parse_ros2_string_stream(output)

    assert len(samples) == 2
    assert all(sample["state"] == "NOT_WORKING" for sample in samples)


def test_summary_reader_sources_ros_environment(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='data: "{\\"state\\": \\"WORKING\\", \\"point_count\\": 2}"')

    monkeypatch.setattr("device_bridges.utm_state_observer.subprocess.run", fake_run)

    payload = read_compression_tester_summary_once()

    assert payload["state"] == "WORKING"
    assert calls[0][0][:2] == ["bash", "-lc"]
    assert "source /opt/ros/jazzy/setup.bash" in calls[0][0][2]
    assert "ros2 topic echo /compression_tester/summary --once --field data" in calls[0][0][2]


def test_parse_ros2_string_json_payload_marks_fresh_summary() -> None:
    payload = _parse_ros2_string_data('data: "{\\"state\\": \\"WORKING\\", \\"span_y\\": 210.5, \\"point_count\\": 2}"\n---')

    assert payload["state"] == "WORKING"
    assert payload["span_y"] == 210.5
    assert payload["point_count"] == 2
    assert payload["summary_fresh"] is True
    assert payload["upper_marker_detected"] is True
    assert payload["lower_marker_detected"] is True
    assert payload["timestamp"]


def test_summarize_utm_state_sequence_detects_not_working_to_working_transition() -> None:
    samples = [
        {"state": "NOT_WORKING", "point_count": 2, "span_y": 320.0},
        {"state": "NOT_WORKING", "point_count": 2, "span_y": 315.0},
        {"state": "NOT_WORKING", "point_count": 2, "span_y": 305.0},
        {"state": "WORKING", "point_count": 2, "span_y": 240.0},
        {"state": "WORKING", "point_count": 2, "span_y": 220.0},
        {"state": "WORKING", "point_count": 2, "span_y": 205.0},
        {"state": "WORKING", "point_count": 2, "span_y": 200.0},
        {"state": "WORKING", "point_count": 2, "span_y": 198.0},
    ]

    result = summarize_utm_state_sequence(samples, minimum_samples=8)

    assert result["ok"] is True
    assert result["transition"] == "NOT_WORKING_TO_WORKING"
    assert result["initial_state"] == "NOT_WORKING"
    assert result["final_state"] == "WORKING"
    assert result["span_y_delta"] >= 120.0
    assert result["motion_direction"] == "DOWN"


def test_summarize_utm_state_sequence_detects_up_direction() -> None:
    samples = [
        {"state": "WORKING", "point_count": 2, "span_y": span}
        for span in (198.0, 200.0, 205.0, 220.0, 240.0, 305.0, 315.0, 320.0)
    ]

    result = summarize_utm_state_sequence(samples, minimum_samples=8)

    assert result["motion_direction"] == "UP"


def test_summarize_utm_state_sequence_requires_temporal_evidence() -> None:
    result = summarize_utm_state_sequence(
        [{"state": "WORKING", "point_count": 2, "span_y": 210.0}],
        minimum_samples=8,
    )

    assert result["ok"] is False
    assert result["failure_code"] == INSUFFICIENT_EVIDENCE
    assert result["transition"] == "INSUFFICIENT_EVIDENCE"
    assert result["valid_sample_count"] == 1
