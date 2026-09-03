"""Tests for UTM ROS topic state observation."""

from __future__ import annotations

from types import SimpleNamespace

from device_bridges.utm_state_observer import (
    INSUFFICIENT_EVIDENCE,
    _parse_ros2_string_data,
    _parse_ros2_string_stream,
    read_compression_tester_summary_once,
    summarize_utm_state_sequence,
)


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
