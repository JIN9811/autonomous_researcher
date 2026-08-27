"""Main GUI entry checks for the PLC device workspace."""

from fastapi.testclient import TestClient

from app.main import app


def test_main_gui_exposes_working_plc_device_workspace_entry() -> None:
    client = TestClient(app)

    dashboard = client.get("/")
    workspace = client.get("/plc")

    assert dashboard.status_code == 200
    device_section = dashboard.text.split("<h2>Device Workspaces</h2>", 1)[1].split("</section>", 1)[0]
    assert 'id="btn-open-plc"' in device_section
    assert 'href="/plc"' in device_section
    assert "PLC Safety Bridge" in device_section
    assert workspace.status_code == 200
    assert 'id="plc-workspace"' in workspace.text
