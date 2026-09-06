from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from utils.operator_teleop_handoff import OperatorTeleopHandoffRegistry


class _FakeStoppedBridge:
    def __init__(self, status: str = "STOPPED") -> None:
        self.status = status

    def teleoperate_status(self, payload: dict) -> dict:
        return {
            "ok": True,
            "workflow": "teleoperate",
            "status": self.status,
            "session_id": payload["session_id"],
            "port_released": self.status == "STOPPED",
            "camera_returned_to_vision": self.status == "STOPPED",
            "teleop_stopped_at": "2026-09-04T02:00:00Z",
        }


def _install_pending(monkeypatch, *, bridge_status: str = "STOPPED") -> dict:
    registry = OperatorTeleopHandoffRegistry()
    monkeypatch.setattr(app_main.controller, "_operator_teleop_handoffs", registry)
    monkeypatch.setattr(app_main, "_lerobot_bridge", lambda: _FakeStoppedBridge(bridge_status))
    pending = registry.create(
        run_id="run-api",
        cycle_index=2,
        specimen_id="specimen-api",
        candidate_id="candidate-api",
        materialization_evidence={"status": "confirmed", "fresh": True},
    )
    registry.bind_session(
        run_id="run-api",
        handoff_token=pending["handoff_token"],
        teleop_session_id="teleop-api",
    )
    return pending


def test_handoff_api_returns_bounded_context_and_accepts_matching_stopped_session(monkeypatch):
    pending = _install_pending(monkeypatch)
    client = TestClient(app)

    context = client.get(
        "/api/planning/runs/run-api/teleop-handoff",
        params={"handoff_token": pending["handoff_token"]},
    )
    confirmed = client.post(
        "/api/planning/runs/run-api/teleop-handoff/confirm",
        json={
            "handoff_token": pending["handoff_token"],
            "teleop_session_id": "teleop-api",
            "confirmed_by": "local_operator",
        },
    )

    assert context.status_code == 200
    assert context.json()["specimen_id"] == "specimen-api"
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "operator_confirmed"
    assert confirmed.json()["teleop_session_id"] == "teleop-api"


def test_handoff_api_rejects_active_session_wrong_token_and_replay(monkeypatch):
    pending = _install_pending(monkeypatch, bridge_status="TELEOP_ACTIVE")
    client = TestClient(app)
    body = {
        "handoff_token": pending["handoff_token"],
        "teleop_session_id": "teleop-api",
        "confirmed_by": "local_operator",
    }

    assert client.get(
        "/api/planning/runs/run-api/teleop-handoff",
        params={"handoff_token": "wrong"},
    ).status_code == 404
    active = client.post("/api/planning/runs/run-api/teleop-handoff/confirm", json=body)
    assert active.status_code == 409
    assert "TELEOP_SESSION_ACTIVE" in active.json()["detail"]


def test_teleoperate_start_binds_the_popup_session_to_its_pending_handoff(monkeypatch):
    registry = OperatorTeleopHandoffRegistry()
    monkeypatch.setattr(app_main.controller, "_operator_teleop_handoffs", registry)
    pending = registry.create(
        run_id="run-bind",
        cycle_index=1,
        specimen_id="specimen-bind",
        candidate_id="candidate-bind",
        materialization_evidence={"status": "confirmed", "fresh": True},
    )

    async def fake_backend(tool_name: str, payload: dict, **_kwargs) -> dict:
        assert tool_name == "lerobot.teleoperate.start"
        return {"ok": True, "status": "TELEOP_ACTIVE", "session_id": "teleop-bound"}

    monkeypatch.setattr(app_main, "_call_lerobot_backend_tool", fake_backend)
    client = TestClient(app)

    response = client.post(
        "/api/lerobot/teleoperate/start",
        json={
            "mode": "live",
            "runtime_mode": "live",
            "handoff_token": pending["handoff_token"],
            "handoff_run_id": "run-bind",
        },
    )

    assert response.status_code == 200
    assert registry.status("run-bind", pending["handoff_token"])["teleop_session_id"] == "teleop-bound"
