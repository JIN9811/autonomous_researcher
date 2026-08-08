from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORM_PATH = PROJECT_ROOT / "Pyautogui_server_for_window" / "demo" / "browser_form.html"
CAPABILITY_LAB_PATH = PROJECT_ROOT / "Pyautogui_server_for_window" / "demo" / "pyautogui_capability_lab.html"
ADVANCED_QUEUE_PATH = PROJECT_ROOT / "Pyautogui_server_for_window" / "demo" / "advanced_visual_work_queue.py"
EXAMPLE_ROOT = PROJECT_ROOT / "Pyautogui_server_for_window" / "demo" / "examples"


def test_browser_form_completes_with_submitted_values() -> None:
    assert FORM_PATH.is_file(), f"missing browser workflow asset: {FORM_PATH}"

    options = webdriver.FirefoxOptions()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service("/snap/bin/geckodriver"), options=options)
    try:
        driver.get(FORM_PATH.as_uri())
        driver.find_element(By.ID, "name").send_keys("ATR specimen")
        driver.find_element(By.ID, "sample_count").send_keys("12")
        Select(driver.find_element(By.ID, "mode")).select_by_value("validation")
        driver.find_element(By.ID, "submit").click()

        result = driver.find_element(By.ID, "result")
        assert result.get_attribute("data-status") == "completed"
        assert result.text == "FORM WORKFLOW COMPLETED | ATR specimen | 12 | validation"
    finally:
        driver.quit()


def test_capability_lab_contains_deterministic_targets_for_all_safe_families() -> None:
    html = CAPABILITY_LAB_PATH.read_text(encoding="utf-8")

    for element_id in (
        "click-target",
        "drag-source",
        "drag-target",
        "scroll-lane",
        "keyboard-input",
        "shortcut-status",
        "visual-target",
        "pixel-swatch",
        "lab-result",
    ):
        assert f'id="{element_id}"' in html
    assert "CAPABILITY LAB READY" in html
    assert "data-status" in html


def test_advanced_work_queue_demo_is_packaged_with_visual_recovery_targets() -> None:
    source = ADVANCED_QUEUE_PATH.read_text(encoding="utf-8")

    assert "specimen-beta" in source
    assert "ANALYSIS QUEUE" in source
    assert "EVIDENCE REQUIRED" in source
    assert "SAVE JSON + CSV" in source
    assert "WORKFLOW_VALIDATION_FAILED" in source


def _load_bridge_module():
    path = PROJECT_ROOT / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py"
    spec = importlib.util.spec_from_file_location("pyautogui_demo_asset_bridge", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_example_catalog_covers_all_exposed_safe_core_actions_with_valid_program_schema() -> None:
    expected = {
        "pointer_click",
        "drag_scroll",
        "keyboard_shortcuts",
        "visual_assertions",
        "image_location",
        "file_wait",
        "window_control",
        "manual_dialogs",
    }
    paths = sorted(EXAMPLE_ROOT.glob("*.json"))

    assert {path.stem for path in paths} == expected
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == "atr.pyautogui_program.v1"
        assert payload["program_id"] == f"example_{path.stem}"
        assert payload["example"]["family"]
        assert isinstance(payload["safe_test"], bool)
        assert 1 <= len(payload["sequence"]) <= 100

    bridge = _load_bridge_module()
    catalog_actions = {
        action
        for actions in bridge._capability_catalog()["families"].values()
        for action in actions
    }
    example_actions = {
        action["action"]
        for path in paths
        for action in json.loads(path.read_text(encoding="utf-8"))["sequence"]
    }
    assert catalog_actions <= example_actions

    manual = json.loads((EXAMPLE_ROOT / "manual_dialogs.json").read_text(encoding="utf-8"))
    assert manual["safe_test"] is False
    assert manual["example"]["manual_confirmation_required"] is True
