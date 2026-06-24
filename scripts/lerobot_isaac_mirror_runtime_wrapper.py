#!/usr/bin/env python3
"""
Run LeRobot teleoperate/record with ATR Isaac mirror publication in the same process.

The wrapper patches the OMX follower send_action path instead of opening a second
Dynamixel connection. This keeps teleop/record hardware ownership identical to
normal LeRobot usage while still streaming joint targets to Isaac Sim.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.isaac_omx_mirror_mapping import (  # noqa: E402
    action_to_joint_state,
    default_isaac_omx_mirror_calibration_path,
    load_isaac_omx_mirror_calibration,
)


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _mirror_source_from_env() -> str:
    raw = os.getenv("ATR_ISAAC_MIRROR_SOURCE", "follower_present_position").strip().lower().replace("-", "_")
    aliases = {
        "present": "follower_present_position",
        "present_position": "follower_present_position",
        "follower_present": "follower_present_position",
        "follower_present_position": "follower_present_position",
        "sent": "sent_action",
        "sent_action": "sent_action",
        "goal": "sent_action",
        "goal_position": "sent_action",
    }
    return aliases.get(raw, "follower_present_position")


class IsaacMirrorPublisher:
    def __init__(self) -> None:
        self.enabled = os.getenv("ATR_ISAAC_MIRROR_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.endpoint = os.getenv("ATR_ISAAC_MIRROR_ENDPOINT", "http://127.0.0.1:8766/joints").strip()
        self.timeout_s = _env_float("ATR_ISAAC_MIRROR_TIMEOUT_S", 0.5, minimum=0.05)
        self.sample_hz = _env_float("ATR_ISAAC_MIRROR_SAMPLE_HZ", 15.0, minimum=0.1)
        self.period_s = 1.0 / self.sample_hz
        self.source = _mirror_source_from_env()
        self.session_id = os.getenv("ATR_ISAAC_MIRROR_SESSION_ID", "").strip()
        self.attached_to_session_id = os.getenv("ATR_ISAAC_MIRROR_ATTACHED_TO_SESSION_ID", "").strip()
        self.profile_id = os.getenv("ATR_ISAAC_MIRROR_PROFILE_ID", "").strip()
        self.record_path = Path(os.getenv("ATR_ISAAC_MIRROR_RECORD_PATH", "").strip()).expanduser()
        calibration_path = os.getenv("ATR_ISAAC_MIRROR_CALIBRATION_PATH", "").strip()
        self.calibration = load_isaac_omx_mirror_calibration(calibration_path or default_isaac_omx_mirror_calibration_path(REPO_ROOT))
        self._last_post_monotonic = 0.0
        self._sample_count = 0

    def should_publish(self) -> bool:
        if not self.enabled:
            return False
        now = time.monotonic()
        if self._last_post_monotonic and now - self._last_post_monotonic < self.period_s:
            return False
        return True

    def action_from_follower(self, follower: Any, sent_action: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        if self.source != "follower_present_position":
            return sent_action, "in_process_send_action", ""
        try:
            present_pos = follower.bus.sync_read("Present_Position")
        except Exception as exc:
            return sent_action, "in_process_send_action_fallback", f"{exc.__class__.__name__}: {exc}"
        action = {key if str(key).endswith(".pos") else f"{key}.pos": value for key, value in present_pos.items()}
        return action, "in_process_follower_present_position", ""

    def maybe_publish(self, sent_action: dict[str, Any], *, source: str = "in_process_send_action", source_error: str = "") -> None:
        if not self.should_publish():
            return
        self.publish_action(sent_action, source=source, source_error=source_error)

    def publish_action(self, action: dict[str, Any], *, source: str, source_error: str = "") -> None:
        joint_state = action_to_joint_state(action, calibration=self.calibration)
        if not joint_state:
            return
        self._last_post_monotonic = time.monotonic()
        self._sample_count += 1
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "session_id": self.session_id or self.attached_to_session_id,
            "attached_to_session_id": self.attached_to_session_id,
            "sample_index": self._sample_count,
            "timestamp": timestamp,
            "elapsed_s": 0.0,
            "mode": "live",
            "profile_id": self.profile_id,
            "scene_path": "",
            "articulation_root": "/World/Robot/Geometry/link0",
            "follower_port": source,
            "calibration": self.calibration,
            "joint_state": joint_state,
        }
        post_started = time.monotonic()
        post_result = self._post(payload)
        sync_metrics = {
            "target_sample_hz": self.sample_hz,
            "sample_period_s": self.period_s,
            "sample_index": self._sample_count,
            "post_latency_ms": round((time.monotonic() - post_started) * 1000.0, 3),
            "receiver_accepted": bool(post_result.get("ok")),
            "receiver_status_code": post_result.get("status_code"),
            "source": source,
        }
        if source_error:
            sync_metrics["source_error"] = source_error
        record = {
            **payload,
            "sync_metrics": sync_metrics,
            "isaac_post": post_result,
        }
        if self.record_path:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            with self.record_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = Request(self.endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body) if body else {}
                return {"ok": 200 <= response.status < 300, "status_code": response.status, "response": parsed}
        except Exception as exc:
            return {"ok": False, "status_code": None, "error": f"{exc.__class__.__name__}: {exc}"}


def patch_omx_send_action(publisher: IsaacMirrorPublisher) -> None:
    if not publisher.enabled:
        return
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    original_send_action = OmxFollower.send_action

    def mirrored_send_action(self, action):  # type: ignore[no-untyped-def]
        sent_action = original_send_action(self, action)
        if publisher.should_publish():
            mirror_action, source, source_error = publisher.action_from_follower(self, sent_action)
            publisher.publish_action(mirror_action, source=source, source_error=source_error)
        return sent_action

    OmxFollower.send_action = mirrored_send_action


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"teleoperate", "record"}:
        raise SystemExit("usage: lerobot_isaac_mirror_runtime_wrapper.py {teleoperate|record} [lerobot args...]")
    workflow = sys.argv[1]
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    publisher = IsaacMirrorPublisher()
    patch_omx_send_action(publisher)
    if workflow == "teleoperate":
        from lerobot.teleoperate import main as lerobot_main
    else:
        from lerobot.record import main as lerobot_main
    lerobot_main()


if __name__ == "__main__":
    main()
