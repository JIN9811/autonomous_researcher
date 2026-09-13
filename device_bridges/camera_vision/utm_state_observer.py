"""
UTM ROS state observer for /compression_tester/summary.

The cloned UTM program publishes JSON through a ROS std_msgs/String topic. This
module turns a short stream of those samples into evidence for ATR's
vision.equipment_cross_check tool.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
import json
import shlex
from statistics import median
import subprocess
import time
from typing import Any

VALID_STATES = {"WORKING", "NOT_WORKING"}
INSUFFICIENT_EVIDENCE = "UTM_INSUFFICIENT_TEMPORAL_EVIDENCE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_state(sample: dict[str, Any]) -> str:
    return str(sample.get("state", "UNKNOWN")).upper()


def _sample_marker_count(sample: dict[str, Any]) -> int:
    value = sample.get("point_count", sample.get("marker_count", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _valid_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        sample
        for sample in samples
        if _sample_state(sample) in VALID_STATES and _sample_marker_count(sample) >= 2
    ]


def summarize_utm_state_sequence(
    samples: list[dict[str, Any]],
    *,
    minimum_samples: int = 8,
    stable_ratio: float = 0.8,
) -> dict[str, Any]:
    """Summarize UTM state samples into transition/stability evidence."""
    valid = _valid_samples(samples)
    if len(valid) < minimum_samples:
        return {
            "ok": False,
            "failure_code": INSUFFICIENT_EVIDENCE,
            "sample_count": len(samples),
            "valid_sample_count": len(valid),
            "working_count": 0,
            "not_working_count": 0,
            "unknown_count": len(samples) - len(valid),
            "transition": "INSUFFICIENT_EVIDENCE",
            "stable_state": "",
            "samples": samples,
        }

    states = [_sample_state(sample) for sample in valid]
    counts = Counter(states)
    working_count = counts["WORKING"]
    not_working_count = counts["NOT_WORKING"]
    threshold = max(1, int(round(len(valid) * stable_ratio)))

    first_segment = states[:3]
    last_segment = states[-3:]
    transition = "UNSTABLE"
    stable_state = ""
    if first_segment.count("NOT_WORKING") >= 2 and last_segment.count("WORKING") >= 2:
        transition = "NOT_WORKING_TO_WORKING"
    elif first_segment.count("WORKING") >= 2 and last_segment.count("NOT_WORKING") >= 2:
        transition = "WORKING_TO_NOT_WORKING"
    elif working_count >= threshold:
        transition = "STABLE_WORKING"
        stable_state = "WORKING"
    elif not_working_count >= threshold:
        transition = "STABLE_NOT_WORKING"
        stable_state = "NOT_WORKING"

    span_values = [
        float(sample["span_y"])
        for sample in valid
        if isinstance(sample.get("span_y"), (int, float))
    ]
    span_y_delta = max(span_values) - min(span_values) if span_values else 0.0
    motion_direction = "UNKNOWN"
    span_y_start = None
    span_y_end = None
    if len(span_values) >= 6:
        span_y_start = float(median(span_values[:3]))
        span_y_end = float(median(span_values[-3:]))
        directed_delta = span_y_end - span_y_start
        if directed_delta >= 4.0:
            motion_direction = "UP"
        elif directed_delta <= -4.0:
            motion_direction = "DOWN"
        else:
            motion_direction = "STABLE"

    return {
        "ok": True,
        "sample_count": len(samples),
        "valid_sample_count": len(valid),
        "working_count": working_count,
        "not_working_count": not_working_count,
        "unknown_count": len(samples) - len(valid),
        "initial_state": states[0],
        "final_state": states[-1],
        "transition": transition,
        "stable_state": stable_state,
        "span_y_delta": span_y_delta,
        "span_y_start": span_y_start,
        "span_y_end": span_y_end,
        "motion_direction": motion_direction,
        "samples": samples,
    }


def _decode_ros_string_payload(text: str) -> Any:
    """Decode ros2 echo output that may be raw, JSON-quoted, or repr-quoted."""
    stripped = "\n".join(
        line for line in text.strip().splitlines() if line.strip() != "---"
    ).strip()
    if stripped.startswith("---"):
        stripped = stripped.removeprefix("---").strip()
    if stripped.startswith("data:"):
        stripped = stripped.split(":", 1)[1].strip()

    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            decoded = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            decoded = stripped

    if isinstance(decoded, str):
        return json.loads(decoded)
    return decoded


def _parse_ros2_string_data(stdout: str) -> dict[str, Any]:
    payload = _decode_ros_string_payload(stdout)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("ROS String payload is not a JSON object", str(payload), 0)

    payload = dict(payload)
    payload["timestamp"] = _now_iso()
    payload["summary_fresh"] = True
    marker_count = _sample_marker_count(payload)
    payload["upper_marker_detected"] = marker_count >= 2
    payload["lower_marker_detected"] = marker_count >= 2
    return payload


def _parse_ros2_string_stream(stdout: str) -> list[dict[str, Any]]:
    """Parse every message emitted by a bounded ros2 topic echo stream."""
    samples: list[dict[str, Any]] = []
    for line in str(stdout or "").splitlines():
        record = line.strip()
        if not record.startswith(("data:", "{", '"{', "'{")):
            continue
        try:
            samples.append(_parse_ros2_string_data(record))
        except (json.JSONDecodeError, SyntaxError, ValueError):
            continue
    return samples


def read_compression_tester_summary_once(
    *,
    topic: str = "/compression_tester/summary",
    timeout_sec: float = 1.0,
) -> dict[str, Any]:
    command = (
        "source /opt/ros/jazzy/setup.bash; "
        f"exec ros2 topic echo {shlex.quote(topic)} --once --field data"
    )
    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        check=True,
        text=True,
        timeout=timeout_sec + 0.5,
    )
    return _parse_ros2_string_data(completed.stdout)


def read_compression_tester_summary_window(
    *,
    duration_sec: float,
    topic: str = "/compression_tester/summary",
) -> list[dict[str, Any]]:
    """Collect a bounded ROS echo stream without restarting ros2 per sample."""
    bounded_duration = max(float(duration_sec), 0.5)
    command = (
        "source /opt/ros/jazzy/setup.bash; "
        f"exec timeout --signal=TERM {bounded_duration:.3f}s "
        f"ros2 topic echo {shlex.quote(topic)} --field data"
    )
    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        check=False,
        text=True,
        timeout=bounded_duration + 2.0,
    )
    if completed.returncode not in {0, 124}:
        raise subprocess.CalledProcessError(
            completed.returncode,
            ["bash", "-lc", command],
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return _parse_ros2_string_stream(completed.stdout)


def observe_utm_state_window(
    *,
    duration_sec: float = 5.0,
    sample_interval_sec: float = 0.2,
    minimum_samples: int = 8,
    read_sample: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect UTM state samples for a bounded time window."""
    reader = read_sample or read_compression_tester_summary_once
    if read_sample is None:
        try:
            samples = read_compression_tester_summary_window(duration_sec=duration_sec)
        except (
            json.JSONDecodeError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
            OSError,
        ) as exc:
            samples = [
                {
                    "timestamp": _now_iso(),
                    "state": "UNKNOWN",
                    "point_count": 0,
                    "summary_fresh": False,
                    "error": type(exc).__name__,
                }
            ]
        result = summarize_utm_state_sequence(samples, minimum_samples=minimum_samples)
        result["duration_sec"] = duration_sec
        return result

    deadline = time.monotonic() + max(duration_sec, 0.0)
    samples: list[dict[str, Any]] = []

    while time.monotonic() < deadline:
        try:
            samples.append(reader())
        except (
            json.JSONDecodeError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
            OSError,
        ) as exc:
            samples.append(
                {
                    "timestamp": _now_iso(),
                    "state": "UNKNOWN",
                    "point_count": 0,
                    "summary_fresh": False,
                    "error": type(exc).__name__,
                }
            )
        time.sleep(max(sample_interval_sec, 0.0))

    result = summarize_utm_state_sequence(samples, minimum_samples=minimum_samples)
    result["duration_sec"] = duration_sec
    return result
