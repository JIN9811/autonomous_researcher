"""Shared handoff expiry must not extend fast-changing safety observations."""
from datetime import datetime, timedelta, timezone

import pytest

from agents.vision.agent import VisionAgent
from agents.manipulation.agent import ManipulationAgent
from agents.manipulation import agent as manipulation_module
from orchestrator.state import Mode, OrchestratorState


CAPTURED = datetime(2026, 9, 15, tzinfo=timezone.utc)


def signal(name):
    return VisionAgent()._signal(
        state=OrchestratorState(run_id="freshness-test", experiment_id="exp-test"), signal=name,
        zone_id="input", value=True, confidence=0.9, stable_for_ms=1000,
        target_agent="manipulation_agent", status="ready", timestamp=CAPTURED.isoformat())


@pytest.mark.parametrize("name", ["pickup_ready", "spc_autoejection_confirmed", "specimen_on_utm_platen"])
def test_handoff_expiry_is_180_seconds_from_original_observation(name):
    item = signal(name)
    assert item["timestamp"] == "2026-09-15T00:00:00+00:00"
    assert item["expires_at"] == "2026-09-15T00:03:00+00:00"


@pytest.mark.parametrize("name", ["robot_workspace_clear", "anomaly_detected", "utm_motion_observed", "unknown_future_signal"])
def test_safety_and_unknown_signals_keep_short_expiry(name):
    assert signal(name)["expires_at"] == "2026-09-15T00:00:05+00:00"


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.TEST])
@pytest.mark.parametrize("age,fresh", [(179.999, True), (180, False), (181, False)])
def test_producer_and_consumer_share_boundary_without_mode_grace(monkeypatch, mode, age, fresh):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return CAPTURED + timedelta(seconds=age)
    monkeypatch.setattr(manipulation_module, "datetime", Clock)
    item = signal("pickup_ready")
    state = OrchestratorState(run_id="freshness-test", experiment_id="exp-test", mode=mode,
        latest_observations={"transfer_readiness": item, "vision_signal": item})
    result = ManipulationAgent._vision_signal_freshness(state)
    assert result["fresh"] is fresh
    assert result["expires_at"] == "2026-09-15T00:03:00+00:00"
    assert "grace_s" not in result
