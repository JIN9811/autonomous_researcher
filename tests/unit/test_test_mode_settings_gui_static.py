from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_main_run_control_opens_test_mode_settings_after_gpu_clear():
    page = TestClient(app).get("/").text

    gpu_index = page.index('id="btn-gpu-clear"')
    settings_index = page.index('id="btn-test-mode-settings"')
    end_of_button_row = page.index("</div>", settings_index)

    assert gpu_index < settings_index < end_of_button_row
    assert "Test Mode Settings" in page
    assert '/static/app.js?v=20260904-test-mode-profiles-1' in page


def test_settings_page_exposes_complete_nonconditional_profile_editor():
    page = TestClient(app).get("/test-mode-settings").text

    for value in ("virtual_bridge", "installed_printer", "physical_print"):
        assert f'data-profile-id="{value}"' in page
    for agent in ("specimen", "vision", "manipulation", "lab_equipment"):
        assert f'data-agent-id="{agent}"' in page
    for element_id in (
        "test-mode-print-body",
        "test-mode-cooling-wait",
        "test-mode-auto-ejection",
        "test-mode-handoff-strategy",
        "test-mode-profile-revision",
        "test-mode-derived-flow",
        "test-mode-validation",
        "btn-test-mode-save",
        "btn-test-mode-reload",
        "btn-test-mode-restore",
        "btn-test-mode-restore-all",
    ):
        assert f'id="{element_id}"' in page
    assert "/static/test_mode_settings.js" in page
