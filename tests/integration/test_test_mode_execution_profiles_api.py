from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


def _installed_hybrid_profile() -> dict:
    return {
        "agents": {
            "specimen": {"device_mode": "real"},
            "vision": {"device_mode": "real"},
            "manipulation": {"device_mode": "virtual"},
            "lab_equipment": {"device_mode": "real"},
        },
        "printer_flow": {
            "print_body": "skip",
            "cooling_wait": "skip",
            "auto_ejection": True,
        },
        "handoff": {"strategy": "operator_teleop"},
    }


def test_settings_route_and_profile_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_main,
        "TEST_MODE_EXECUTION_PROFILES_PATH",
        tmp_path / "memory" / "profiles.json",
    )
    client = TestClient(app)

    page = client.get("/test-mode-settings")
    initial = client.get("/api/test-mode-execution-profiles")
    saved = client.put(
        "/api/test-mode-execution-profiles/installed_printer",
        json={"expected_revision": 0, "profile": _installed_hybrid_profile()},
    )
    reset = client.post(
        "/api/test-mode-execution-profiles/reset",
        json={"expected_revision": 1, "profile_id": "installed_printer"},
    )

    assert page.status_code == 200
    assert "Test Mode Settings" in page.text
    assert initial.status_code == 200
    assert initial.json()["revision"] == 0
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["profiles"]["installed_printer"]["agents"]["manipulation"] == {
        "device_mode": "virtual"
    }
    assert reset.status_code == 200
    assert reset.json()["revision"] == 2
    assert reset.json()["profiles"]["installed_printer"]["agents"]["manipulation"] == {
        "device_mode": "real"
    }


def test_profile_api_rejects_stale_revision_and_unsafe_cooling(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "TEST_MODE_EXECUTION_PROFILES_PATH", tmp_path / "profiles.json")
    client = TestClient(app)
    valid = _installed_hybrid_profile()
    assert client.put(
        "/api/test-mode-execution-profiles/installed_printer",
        json={"expected_revision": 0, "profile": valid},
    ).status_code == 200

    stale = client.put(
        "/api/test-mode-execution-profiles/installed_printer",
        json={"expected_revision": 0, "profile": valid},
    )
    unsafe = _installed_hybrid_profile()
    unsafe["printer_flow"] = {
        "print_body": "execute",
        "cooling_wait": "skip",
        "auto_ejection": True,
    }
    invalid = client.put(
        "/api/test-mode-execution-profiles/installed_printer",
        json={"expected_revision": 1, "profile": unsafe},
    )

    assert stale.status_code == 409
    assert invalid.status_code == 422
