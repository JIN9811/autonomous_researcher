#!/usr/bin/env python3
"""Browser-level audit for the standalone Windows PyAutoGUI bridge GUI.

This is intentionally non-actuating. It opens the Windows bridge root page,
verifies that the operator-facing UTM control/evidence surface renders at
1920x1080, injects a fake step_trace into the browser timeline, and checks that
the page does not horizontally overflow.

It expects ``install/windows_pyautogui_bridge_server.py`` or the packaged
Windows bridge copy to be running. The default URL is http://127.0.0.1:8765.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


def wait_for_bridge_gui(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return Boolean(document.getElementById('operatorConsolePanel'))"))
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return typeof appendTimelineFromResult === 'function'"))


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str) -> dict[str, Any]:
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    try:
        driver.get(base_url.rstrip("/") + "/")
        wait_for_bridge_gui(driver)
        result = driver.execute_script(
            r"""
            const fake = {
              ok: false,
              tool: "equipment.pyautogui.run",
              status: "blocked",
              sequence_id: "browser-audit-sequence",
              run_id: "browser-audit-run",
              failure_code: "UTM_DATA_NO_FORCE_SIGNAL",
              step_trace: [
                {step: "SAFE_PREFLIGHT", status: "ok", detail: "non-actuating checks passed"},
                {step: "SCREEN_ASSERTION", status: "ok", detail: "running_state observed"},
                {step: "WAIT_FOR_EXPORT", status: "blocked", detail: "UTM_DATA_NO_FORCE_SIGNAL"}
              ],
              data_acquisition: {
                status: "pulled_to_linux_parse_failed",
                save_method: "manual_save_dialog",
                row_count_probe: 3,
                columns_probe: ["time_s", "displacement_mm", "force_N"]
              }
            };
            appendTimelineFromResult(fake);
            render(fake);
            const doc = document.documentElement;
            const requiredIds = [
              "connectionPanel",
              "safeDiagnosticsPanel",
              "utmProtocolPanel",
              "operatorConsolePanel",
              "fieldRunbookPanel",
              "bridgeCommandKit",
              "copyCurlHealth",
              "copyPowerShellHealth",
              "copyCurlExecute",
              "runbookConnect",
              "runbookCalibrate",
              "runbookExecute",
              "runbookVerify",
              "programRegistry",
              "timelinePanel",
              "overview",
              "evidencePanel",
              "resultPanel",
              "operatorLogPanel",
              "controlRail",
              "nextActionButton",
              "nextActionLabel",
              "proofChecklist",
              "proofGateStrip",
              "proofGateHealth",
              "proofGateLocators",
              "proofGateSafety",
              "proofGateRequestLog",
              "proofGateScreen",
              "proofGateSave",
              "proofGateCsv",
              "operatorSituationPanel",
              "situationBridge",
              "situationLocators",
              "situationAudit",
              "situationExport",
              "situationLive",
              "missingLocatorShortcuts",
              "requestAuditRunIds",
              "requestAuditSpecimenIds",
              "requestAuditProgramIds",
              "requestAuditLastAt"
            ];
            const missingIds = requiredIds.filter((id) => !document.getElementById(id));
            const headings = Array.from(document.querySelectorAll("h1,h2,strong")).map((item) => item.textContent || "");
            const buttonTexts = Array.from(document.querySelectorAll("button")).map((item) => item.textContent || "");
            const text = document.body ? (document.body.innerText || document.body.textContent || "") : "";
            const timelineRows = Array.from(document.querySelectorAll("#timelineTrack .timeline-item")).map((item) => item.textContent || "");
            const controlButtons = Array.from(document.querySelectorAll("#controlRail button")).map((button) => {
              const rect = button.getBoundingClientRect();
              return {text: button.textContent || "", width: rect.width, height: rect.height, x: rect.x, y: rect.y};
            });
            const navLinks = Array.from(document.querySelectorAll(".quick-nav a")).map((item) => item.textContent || "");
            const nextAction = document.getElementById("nextActionButton");
            return {
              ok: missingIds.length === 0,
              title: document.title,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              missingIds,
              headings,
              buttonTexts,
              navLinks,
              text,
              timelineRows,
              controlButtons,
              nextActionText: nextAction ? (nextAction.textContent || "") : "",
              nextActionTarget: nextAction ? (nextAction.dataset.nextAction || "") : "",
            };
            """
        )
        required_text = [
            "ATR Windows PyAutoGUI Bridge",
            "Local Operator Console",
            "Field Runbook",
            "Bridge Command Kit",
            "Copy curl Health",
            "Copy PowerShell Health",
            "Copy curl Execute",
            "Connect bridge",
            "Calibrate UTM locators",
            "Execute registered protocol",
            "Verify handoff evidence",
            "Program registry",
            "Payload Preview",
            "Run Timeline",
            "UTM Protocol",
            "Preflight + Run Live UTM",
            "Stop / Abort",
            "Live Proof Checklist",
            "Bridge",
            "Locators",
            "Safety",
            "Request",
            "Screen",
            "Save",
            "CSV",
            "Request Audit",
            "Bridge Files",
            "Step Trace",
            "Artifacts",
            "Artifact Preview",
            "Operator Log",
            "Manual Save As fallback",
            "Live UTM situation matrix",
            "Readiness locator shortcuts",
            "Recent live execute identity",
            "UTM_DATA_NO_FORCE_SIGNAL",
            "WAIT_FOR_EXPORT",
            "pulled_to_linux_parse_failed",
        ]
        missing_text = [token for token in required_text if token not in result.get("text", "")]
        if missing_text:
            raise AssertionError(f"Windows bridge GUI missing required text: {missing_text}")
        if result.get("missingIds"):
            raise AssertionError(f"Windows bridge GUI missing required DOM ids: {result['missingIds']}")
        if result.get("scrollWidth", 0) > result.get("clientWidth", 0) + 24:
            raise AssertionError(f"Windows bridge GUI horizontally overflows viewport: {result}")
        too_small = [item for item in result.get("controlButtons", []) if item.get("width", 0) < 44 or item.get("height", 0) < 44]
        if too_small:
            raise AssertionError(f"Control rail buttons are too small for operator use: {too_small}")
        if "recommended next action" not in result.get("nextActionText", "").lower():
            raise AssertionError(f"Recommended next action control did not render correctly: {result}")
        if result.get("nextActionTarget") not in {"health", "readiness", "confirmLive", "utmLive", "screenshot", "refreshEvidence", "token"}:
            raise AssertionError(f"Recommended next action target is invalid: {result}")
        if not any("WAIT_FOR_EXPORT" in row for row in result.get("timelineRows", [])):
            raise AssertionError("Run Timeline did not render injected bridge step_trace rows")
        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot = out_dir / "windows_bridge_gui_browser_audit.png"
        driver.save_screenshot(str(screenshot))
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
    result = run_audit(args.base_url, Path(args.out_dir), width=args.width, height=args.height, geckodriver=args.geckodriver)
    print("windows_bridge_gui_browser_audit: PASS")
    print({key: value for key, value in result.items() if key != "text"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
