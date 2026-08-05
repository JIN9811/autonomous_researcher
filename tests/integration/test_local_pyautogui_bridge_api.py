"""API contract tests for the ATR-owned local PyAutoGUI bridge."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module


class _FakeBridge:
    def connection_status(self):
        return {"ok": True, "selected_candidate": "windows_lab", "candidates": []}


class _FakeSupervisor:
    def __init__(self, *, running: bool = True, healthy: bool = True) -> None:
        self.running = running
        self.healthy = healthy
        self.calls: list[tuple[str, bool | None]] = []

    def status(self):
        self.calls.append(("status", None))
        return {"ok": True, "status": "running" if self.running else "stopped", "running": self.running, "healthy": self.healthy}

    def start(self):
        self.calls.append(("start", None))
        self.running = True
        return {"ok": True, "status": "running", "running": True, "healthy": self.healthy}

    def stop(self):
        self.calls.append(("stop", None))
        self.running = False
        return {"ok": True, "status": "stopped", "running": False, "healthy": False}

    def ensure_candidate(self, _bridge, *, select: bool):
        self.calls.append(("ensure_candidate", select))
        return {"ok": True, "candidate_alias": "local_development", "selected": select}


def _client(monkeypatch, supervisor: _FakeSupervisor) -> TestClient:
    monkeypatch.setattr(main_module, "_local_pyautogui_bridge_supervisor", lambda: supervisor)
    monkeypatch.setattr(main_module, "_equipment_bridge", lambda: _FakeBridge())
    return TestClient(main_module.app)


def test_local_bridge_start_registers_standby_candidate(monkeypatch) -> None:
    supervisor = _FakeSupervisor()
    response = _client(monkeypatch, supervisor).post("/api/equipment/windows/local-bridge/start")

    assert response.status_code == 200
    assert response.json()["candidate"]["selected"] is False
    assert ("ensure_candidate", False) in supervisor.calls


def test_local_bridge_select_requires_healthy_running_process(monkeypatch) -> None:
    supervisor = _FakeSupervisor(running=False, healthy=False)
    response = _client(monkeypatch, supervisor).post("/api/equipment/windows/local-bridge/select")

    assert response.status_code == 409
    assert response.json()["detail"]["failure_code"] == "LOCAL_PYAUTOGUI_NOT_READY"
    assert ("ensure_candidate", True) not in supervisor.calls


def test_local_bridge_select_changes_candidate_only_when_ready(monkeypatch) -> None:
    supervisor = _FakeSupervisor(running=True, healthy=True)
    response = _client(monkeypatch, supervisor).post("/api/equipment/windows/local-bridge/select")

    assert response.status_code == 200
    assert response.json()["candidate"]["selected"] is True
    assert ("ensure_candidate", True) in supervisor.calls


def test_local_bridge_status_and_stop_are_exposed(monkeypatch) -> None:
    supervisor = _FakeSupervisor(running=True, healthy=True)
    client = _client(monkeypatch, supervisor)

    assert client.get("/api/equipment/windows/local-bridge/status").json()["running"] is True
    assert client.post("/api/equipment/windows/local-bridge/stop").json()["running"] is False
