"""Replay/event-buffer tests for LeRobot GUI actions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_lerobot_action_is_replayable_from_recent_events() -> None:
    client = TestClient(app)

    result = client.post(
        "/api/lerobot/rollout/start",
        json={"mode": "test", "profile_id": "fake_omx_ai", "policy_path": "fake://policy"},
    ).json()
    assert result["ok"] is True

    events = client.get("/api/events/recent").json()["events"]
    lerobot_events = [event for event in events if event.get("event_type") == "lerobot_step"]

    assert lerobot_events
    assert lerobot_events[-1]["payload"]["result"]["tool"] == "lerobot.rollout.start"
