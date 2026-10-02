from types import SimpleNamespace
import pytest
from starlette.websockets import WebSocketDisconnect


def test_reset_excludes_old_rollouts_but_preserves_new_sessions(monkeypatch):
    import app.main as main
    sessions = [{"session_id": "old", "workflow": "rollout", "status": "STOPPED", "created_at": "2026-09-15T00:00:00+00:00"}]
    bridge = SimpleNamespace(sessions_recent=lambda: sessions)
    monkeypatch.setattr(main, "controller", SimpleNamespace(telemetry_reset_at_ms=1789430460000))
    monkeypatch.setattr(main, "_lerobot_bridge", lambda: bridge)
    monkeypatch.setattr(main, "_registered_lerobot_bridge", lambda: bridge)
    assert main._joint_telemetry_session_context() is None
    sessions.append({"session_id": "new", "workflow": "rollout", "status": "POLICY_ACTIVE", "created_at": "2026-09-15T00:02:00+00:00"})
    assert main._joint_telemetry_session_context()["session"]["session_id"] == "new"


@pytest.mark.asyncio
async def test_idle_socket_broadcasts_each_reset_and_snapshot_keeps_epoch(monkeypatch):
    import app.main as main
    controller = SimpleNamespace(telemetry_reset_at_ms=100)
    monkeypatch.setattr(main, "controller", controller)
    monkeypatch.setattr(main, "_joint_telemetry_session_context", lambda: None)
    monkeypatch.setattr(main, "_manipulation_runtime_view", lambda *args: {})
    epochs = []

    class Socket:
        query_params = {}

        async def accept(self):
            pass

        async def send_json(self, payload):
            epochs.append(payload.get("reset_at_ms"))
            if len(epochs) == 2:
                raise WebSocketDisconnect()
            controller.telemetry_reset_at_ms = 200

    import asyncio
    await asyncio.wait_for(main.stream_lerobot_joint_telemetry(Socket()), timeout=2)
    assert epochs == [100, 200]
    snapshot = await main.get_lerobot_joint_telemetry_snapshot()
    assert snapshot["reset_at_ms"] == 200
    assert snapshot["packet"] is None
