from fastapi.testclient import TestClient

from app.main import app


def test_printer_gui_route_loads() -> None:
    client = TestClient(app)

    response = client.get("/printer")

    assert response.status_code == 200
    assert "3DP Printer GUI" in response.text
    assert "/static/printer.js" in response.text


def test_printer_status_api_redacts_connection_and_reports_gates() -> None:
    client = TestClient(app)

    response = client.get("/api/printer/status?mode=test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "prusa_mk4s"
    assert "password" not in payload["connection"]
    assert "password_set" in payload["connection"]
    assert payload["live_gates"]["allow_upload"] is True
    assert payload["live_gates"]["allow_start_print"] is True
    assert payload["live_gates"]["allow_ejection"] is False
    assert payload["slicer"]["executable_path"] == "install/prusaslicer/prusa-slicer-docker"


def test_printer_profile_api_reports_saved_print_defaults() -> None:
    client = TestClient(app)

    response = client.get("/api/printer/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"]["printer_model"] == "Prusa MK4S"
    assert payload["profile"]["storage"] == "usb"
    assert isinstance(payload["profile"]["allow_ejection"], bool)
    assert payload["profile_path"].endswith("memory/prusa_print_profile.json")
    assert payload["connection_memory_path"].endswith("memory/prusa_connection.json")
