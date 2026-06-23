"""Tests for UTM ROS topic state observation."""

from __future__ import annotations

from device_bridges.utm_state_observer import (
    INSUFFICIENT_EVIDENCE,
    _parse_ros2_string_data,
    summarize_utm_state_sequence,
)


def test_parse_ros2_string_json_payload_marks_fresh_summary() -> None:
    payload = _parse_ros2_string_data('data: "{\\"state\\": \\"WORKING\\", \\"span_y\\": 210.5, \\"point_count\\": 2}"')

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


def test_summarize_utm_state_sequence_requires_temporal_evidence() -> None:
    result = summarize_utm_state_sequence(
        [{"state": "WORKING", "point_count": 2, "span_y": 210.0}],
        minimum_samples=8,
    )

    assert result["ok"] is False
    assert result["failure_code"] == INSUFFICIENT_EVIDENCE
    assert result["transition"] == "INSUFFICIENT_EVIDENCE"
    assert result["valid_sample_count"] == 1
