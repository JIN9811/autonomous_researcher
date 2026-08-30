#!/usr/bin/env python3
"""Non-actuating browser audit for the compact Windows bridge console."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


REQUIRED_IDS = (
    "essentialConsole",
    "bridgeStatusPanel",
    "health",
    "refreshAll",
    "bridgeServerState",
    "bridgeAtrState",
    "bridgeDesktopState",
    "bridgePyAutoGuiState",
    "pairingPanel",
    "pairingState",
    "pairingCode",
    "newPairingCode",
    "programManagerPanel",
    "managerProgramRegistry",
    "managerStats",
    "managerSearch",
    "newProgram",
    "browseProgram",
    "downloadProgramTemplate",
    "programFile",
    "programEditor",
    "programDefinition",
    "validateProgram",
    "registerProgram",
    "closeProgramEditor",
    "refreshPrograms",
    "recordingPanel",
    "recordingStatus",
    "recordingName",
    "recordingTargetApp",
    "recordingTargetWindow",
    "recordingImageTracking",
    "recordingCoordinateFallback",
    "recordToggle",
    "recordCheckpoint",
    "refreshRecordings",
    "recordingList",
    "recordingPreview",
    "recordingPreviewImage",
    "recordingPreviewPrevious",
    "recordingPreviewNext",
    "recordingPreviewClose",
    "latestLocalResultPanel",
    "latestResultStatus",
    "latestResultSummary",
    "managerLatestResult",
    "diagnosticsPanel",
    "diagnosticHealth",
    "diagnosticRequestLog",
    "diagnosticOutput",
)

REQUIRED_TEXT = (
    "ATR Windows PyAutoGUI Bridge",
    "Bridge Status",
    "Program Manager",
    "Recording",
    "Latest Local Result",
    "Diagnostics",
)

REMOVED_TEXT = (
    "Bridge Token",
    "ATR Controller",
    "UTM Live",
    "UTM Preflight",
    "Skill Proxy",
    "Handoff Proof",
)


def wait_for_bridge_gui(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(
        lambda item: item.execute_script(
            "return Boolean(document.getElementById('programManagerPanel'))"
        )
    )
    WebDriverWait(driver, 20).until(
        lambda item: "program1"
        in (item.find_element(By.ID, "managerProgramRegistry").text or "")
    )


def _write_import_definition(out_dir: Path) -> Path:
    path = out_dir / "browser_audit_program.json"
    path.write_text(
        json.dumps(
            {
                "schema": "atr.pyautogui_program.v1",
                "program_id": "browser_audit_macro",
                "name": "Browser Audit Program",
                "description": "Imported by the non-actuating Selenium audit",
                "enabled": True,
                "program_type": "macro",
                "safe_test": True,
                "sequence": [{"action": "log", "message": "browser audit"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _audit_program_manager(driver: webdriver.Firefox, definition: Path) -> dict[str, Any]:
    builtin_selector = '#managerProgramRegistry [data-program-id="program1"]'
    builtin = driver.find_element(By.CSS_SELECTOR, builtin_selector)
    if not builtin.find_element(By.CSS_SELECTOR, '[data-action="test"]').is_enabled():
        raise AssertionError("Built-in program1 test action is unavailable")
    if builtin.find_elements(By.CSS_SELECTOR, '[data-action="edit"], [data-action="delete"]'):
        raise AssertionError("Built-in program1 must remain read-only")

    driver.find_element(By.ID, "programFile").send_keys(str(definition.resolve()))
    WebDriverWait(driver, 10).until(
        lambda item: "browser_audit_macro"
        in item.find_element(By.ID, "programDefinition").get_attribute("value")
    )
    if not driver.find_element(By.ID, "programEditor").is_displayed():
        raise AssertionError("Browse JSON did not open the local program editor")

    custom_selector = '#managerProgramRegistry [data-program-id="browser_audit_macro"]'
    if driver.find_elements(By.CSS_SELECTOR, custom_selector):
        raise AssertionError("Browsing a JSON file must not register it automatically")

    driver.find_element(By.ID, "validateProgram").click()
    WebDriverWait(driver, 10).until(
        lambda item: '"status": "valid"'
        in (
            item.find_element(By.ID, "managerLatestResult").get_attribute("textContent")
            or ""
        )
    )
    driver.find_element(By.ID, "registerProgram").click()
    WebDriverWait(driver, 10).until(
        lambda item: len(item.find_elements(By.CSS_SELECTOR, custom_selector)) == 1
    )
    custom = driver.find_element(By.CSS_SELECTOR, custom_selector)
    actions = {
        button.get_attribute("data-action")
        for button in custom.find_elements(By.CSS_SELECTOR, "[data-action]")
    }
    if actions != {"test", "edit", "delete"}:
        raise AssertionError(f"Custom program actions are incomplete: {sorted(actions)}")

    custom.find_element(By.CSS_SELECTOR, '[data-action="delete"]').click()
    WebDriverWait(driver, 10).until(
        lambda item: not item.find_elements(By.CSS_SELECTOR, custom_selector)
    )
    return {"builtin": "program1", "custom_actions": sorted(actions)}


def _collect_layout(driver: webdriver.Firefox) -> dict[str, Any]:
    return driver.execute_script(
        """
        const requiredIds = arguments[0];
        const doc = document.documentElement;
        const visible = (node) => {
          const style = window.getComputedStyle(node);
          const rect = node.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden'
            && rect.width > 0 && rect.height > 0;
        };
        const buttons = Array.from(document.querySelectorAll('button'))
          .filter(visible)
          .map((node) => {
            const rect = node.getBoundingClientRect();
            return {id: node.id, text: node.textContent.trim(), width: rect.width, height: rect.height};
          });
        const clipped = Array.from(document.querySelectorAll('h1,h2,label,button,.pill,.muted'))
          .filter(visible)
          .filter((node) => {
            const style = window.getComputedStyle(node);
            const masks = ['hidden', 'clip'].includes(style.overflowX)
              || ['hidden', 'clip'].includes(style.overflow);
            return masks && node.scrollWidth > node.clientWidth + 2;
          })
          .map((node) => ({
            id: node.id || '',
            text: node.textContent.trim().slice(0, 120),
            clientWidth: node.clientWidth,
            scrollWidth: node.scrollWidth,
          }));
        const pairingCode = document.getElementById('pairingCode')?.textContent.trim() || '';
        return {
          title: document.title,
          text: document.body?.innerText || '',
          missingIds: requiredIds.filter((id) => !document.getElementById(id)),
          scrollWidth: doc.scrollWidth,
          clientWidth: doc.clientWidth,
          scrollHeight: doc.scrollHeight,
          clientHeight: doc.clientHeight,
          viewport: {width: window.innerWidth, height: window.innerHeight},
          buttons,
          clipped,
          programCards: document.querySelectorAll('#managerProgramRegistry [data-program-id]').length,
          pairingCode,
          diagnosticsOpen: document.getElementById('diagnosticsPanel')?.open === true,
          recording: {
            imageTracking: document.getElementById('recordingImageTracking')?.checked === true,
            coordinateFallback: document.getElementById('recordingCoordinateFallback')?.checked === true,
            toggleText: document.getElementById('recordToggle')?.textContent.trim() || '',
            checkpointDisabled: document.getElementById('recordCheckpoint')?.disabled === true,
            previewVisible: visible(document.getElementById('recordingPreview')),
          },
          panelOrder: Array.from(document.querySelectorAll('#essentialConsole > section, #essentialConsole > details'))
            .map((node) => node.id),
        };
        """,
        list(REQUIRED_IDS),
    )


def run_audit(
    base_url: str,
    out_dir: Path,
    *,
    width: int,
    height: int,
    geckodriver: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    definition = _write_import_definition(out_dir)
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(
        service=Service(executable_path=geckodriver),
        options=options,
    )
    driver.set_window_size(width, height)
    try:
        driver.get(base_url.rstrip("/") + "/")
        wait_for_bridge_gui(driver)
        program_manager = _audit_program_manager(driver, definition)
        pairing_code = driver.find_element(By.ID, "pairingCode").text.strip()
        if not (len(pairing_code) == 4 and pairing_code.isdigit()):
            driver.find_element(By.ID, "newPairingCode").click()
            WebDriverWait(driver, 10).until(
                lambda item: (
                    len(item.find_element(By.ID, "pairingCode").text.strip()) == 4
                    and item.find_element(By.ID, "pairingCode").text.strip().isdigit()
                )
            )
        result = _collect_layout(driver)

        if result["missingIds"]:
            raise AssertionError(f"Missing compact console elements: {result['missingIds']}")
        missing_text = [value for value in REQUIRED_TEXT if value not in result["text"]]
        if missing_text:
            raise AssertionError(f"Missing compact console text: {missing_text}")
        stale_text = [value for value in REMOVED_TEXT if value in result["text"]]
        if stale_text:
            raise AssertionError(f"Removed proxy/operator UI is still visible: {stale_text}")
        if result["diagnosticsOpen"]:
            raise AssertionError("Diagnostics must be collapsed by default")
        if not result["recording"]["imageTracking"]:
            raise AssertionError("Image tracking must be enabled by default")
        if result["recording"]["coordinateFallback"]:
            raise AssertionError("Coordinate fallback must be disabled by default")
        if result["recording"]["toggleText"] != "START RECORDING":
            raise AssertionError(f"Recording control is not idle: {result['recording']}")
        if not result["recording"]["checkpointDisabled"]:
            raise AssertionError("Recording checkpoint must be disabled while idle")
        if result["recording"]["previewVisible"]:
            raise AssertionError("Recording preview must remain hidden until a recording is selected")
        if not (len(result["pairingCode"]) == 4 and result["pairingCode"].isdigit()):
            raise AssertionError(f"Temporary pairing code is not four digits: {result['pairingCode']!r}")
        expected_order = [
            "bridgeStatusPanel",
            "programManagerPanel",
            "recordingPanel",
            "latestLocalResultPanel",
            "diagnosticsPanel",
        ]
        if result["panelOrder"] != expected_order:
            raise AssertionError(f"Compact console panel order changed: {result['panelOrder']}")
        if result["scrollWidth"] > result["clientWidth"] + 16:
            raise AssertionError(f"Console horizontally overflows: {result}")
        if result["clipped"]:
            raise AssertionError(f"Console clips visible labels: {result['clipped']}")
        undersized = [
            item
            for item in result["buttons"]
            if item["width"] < 40 or item["height"] < 26
        ]
        if undersized:
            raise AssertionError(f"Console buttons are too small: {undersized}")
        if result["programCards"] < 1:
            raise AssertionError("Built-in program1 card was not rendered")

        driver.execute_script("window.scrollTo(0, 0)")
        WebDriverWait(driver, 5).until(
            lambda item: item.execute_script("return window.scrollY") == 0
        )
        screenshot = out_dir / f"windows_bridge_gui_{width}x{height}.png"
        driver.save_screenshot(str(screenshot))
        result["programManager"] = program_manager
        result["screenshot"] = str(screenshot)
        return result
    finally:
        time.sleep(0.1)
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    args = parser.parse_args()
    result = run_audit(
        args.base_url,
        Path(args.out_dir),
        width=args.width,
        height=args.height,
        geckodriver=args.geckodriver,
    )
    print("windows_bridge_gui_browser_audit: PASS")
    print({key: value for key, value in result.items() if key != "text"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
