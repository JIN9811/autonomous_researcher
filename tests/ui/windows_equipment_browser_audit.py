#!/usr/bin/env python3
"""Browser audit for the Linux-side `/equipment/windows` workspace.

This page is the operator management surface for selecting a Windows
PyAutoGUI bridge, tuning the UTM profile, running passive readiness checks, and
reviewing proof/evidence before Analysis handoff. The audit is non-actuating:
it renders the page, injects representative readiness/evidence/proof payloads
into the browser-side renderers, and verifies that the operator can see the
same gates required by the Lab Equipment Agent.
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


def wait_for_workspace(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return Boolean(document.getElementById('equipment-command-banner'))"))
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return typeof renderUtmEvidenceAudit === 'function'"))


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str) -> dict[str, Any]:
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    try:
        driver.get(f"{base_url.rstrip('/')}/equipment/windows")
        wait_for_workspace(driver)
        result = driver.execute_script(
            r"""
            const readiness = {
              ok: true,
              status: "ready",
              gates: {
                connection_saved: true,
                token_configured: true,
                utm_program_registered: true,
                locator_count: 4,
                required_locator_names: ["ready_state", "start_button", "running_state", "complete_state"],
                required_locators_complete: true,
                missing_required_locators: [],
                require_screen_assertions: true,
                simulate_utm_protocol: false
              },
              blockers: [],
              warnings: []
            };
            const evidence = {
              ok: false,
              status: "blocked",
              gates: {
                screen_evidence_complete: true,
                physical_motion_started: true,
                linux_artifact_pulled: true,
                save_export_responsibility_ok: false,
                vision_evidence_complete: true,
                request_audit_log_available: true,
                data_parse_probe_ok: false
              },
              request_audit_log: {execute_event_seen: true},
              proof_ready: false,
              proof_checklist: [
                {id: "screen_evidence", label: "Screen evidence", ok: true},
                {id: "save_export", label: "Save/Export responsibility", ok: false, detail: "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED"},
                {id: "csv_parse", label: "CSV parse probe", ok: false, detail: "UTM_DATA_NO_FORCE_SIGNAL"}
              ],
              blockers: ["UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED", "UTM_DATA_NO_FORCE_SIGNAL"],
              warnings: []
            };
            const verification = {
              ok: false,
              status: "blocked",
              blockers: ["UTM_DATA_NO_FORCE_SIGNAL"],
              checks: [
                {id: "package_schema", status: "ok"},
                {id: "csv_probe", status: "blocked"}
              ],
              csv_probe: {
                path: "/home/jin/autonomous_researcher/artifacts/equipment/run-audit/utm/specimen.csv",
                row_count: 3
              }
            };
            renderUtmReadiness(readiness);
            renderUtmEvidenceAudit(evidence);
            renderUtmLiveValidation({
              ok: true,
              tool: "equipment.pyautogui.live_validation",
              status: "preflight_passed",
              non_actuating: true,
              summary: {required_gate_count: 3, passed_required_gate_count: 3, blocker_count: 0},
              gates: [
                {name: "bridge_health_pyautogui", ok: true, required: true, detail: "PyAutoGUI available"},
                {name: "program_registered", ok: true, required: true, detail: "program_id=utm_compression_start_v1"},
                {name: "execution_not_sent", ok: true, required: false, detail: "non-actuating preflight only"}
              ],
              report_artifact: {path: "/home/jin/autonomous_researcher/artifacts/equipment/run-audit/live_validation/lab_equipment_utm_live_validation.json"},
              request_audit_log: {ok: true, status: "ready", request_log: "/tmp/atr_windows_bridge_audit/bridge_requests.jsonl", event_count: 8, recent_paths: ["/health", "/programs"]}
            });
            renderRequestAudit({
              ok: true,
              status: "ready",
              request_log: "/tmp/atr_windows_bridge_audit/bridge_requests.jsonl",
              event_count: 8,
              recent_paths: ["/health", "/readiness", "/execute"],
              execute_event_seen: true
            });
            renderProofPackageVerification(verification);
            writeLog({ok: false, status: "blocked", tool: "equipment.pyautogui.run", failure_code: "UTM_DATA_NO_FORCE_SIGNAL"});
            const doc = document.documentElement;
            const requiredIds = [
              "equipment-command-banner",
              "equipment-command-pill",
              "equipment-proof-dashboard",
              "equipment-gate-windows-bridge",
              "equipment-gate-utm-program",
              "equipment-gate-vision-preconditions",
              "equipment-gate-screen-state",
              "equipment-gate-physical-crosscheck",
              "equipment-gate-data-artifact",
              "equipment-gate-analysis-handoff",
              "equipment-utm-readiness-card",
              "equipment-utm-live-validation-card",
              "equipment-utm-live-validation-status",
              "equipment-utm-live-validation-detail",
              "equipment-utm-live-validation-gates",
              "equipment-utm-evidence-card",
              "equipment-proof-verify-card",
              "equipment-request-audit-card",
              "equipment-utm-proof-checklist",
              "equipment-result-log",
              "equipment-local-bridge-panel",
              "equipment-local-bridge-status",
              "equipment-local-bridge-detail",
              "btn-equipment-local-start",
              "btn-equipment-local-stop",
              "btn-equipment-local-health",
              "btn-equipment-local-select",
              "btn-equipment-open-bridge-gui",
              "btn-equipment-live-preflight",
              "btn-equipment-live-validation",
              "btn-equipment-live-physical-validation",
              "equipment-live-physical-safe",
              "equipment-live-vision-proof",
              "btn-equipment-evidence-audit",
              "btn-equipment-proof-package",
              "btn-equipment-verify-proof-package",
              "btn-equipment-abort"
            ];
            const missingIds = requiredIds.filter((id) => !document.getElementById(id));
            const commandCards = Array.from(document.querySelectorAll(".equipment-command-card")).map((item) => {
              const rect = item.getBoundingClientRect();
              return {text: item.textContent || "", width: rect.width, height: rect.height};
            });
            const text = document.body ? (document.body.innerText || document.body.textContent || "") : "";
            return {
              ok: missingIds.length === 0,
              title: document.title,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              missingIds,
              commandCards,
              text,
            };
            """
        )
        required_text = [
            "Windows PyAutoGUI Bridge",
            "Operator Console",
            "Readiness",
            "Preflight",
            "UTM Run",
            "Validation",
            "Evidence",
            "Abort",
            "UTM readiness: ready",
            "UTM live validation: preflight_passed",
            "lab_equipment_utm_live_validation.json",
            "Run Physical Validation",
            "Physical UTM setup safe",
            "UTM evidence audit: blocked",
            "request_log=execute-ok",
            "save_export=missing",
            "parse=missing",
            "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED",
            "UTM_DATA_NO_FORCE_SIGNAL",
            "Proof package verification: blocked",
            "Build Proof Package",
            "Verify Proof Package",
            "Open Windows GUI",
            "PyAutoGUI Bridge on This PC",
            "Local Development Target",
            "Run UTM Stop/Abort",
            "UTM Proof Gates",
            "Windows Bridge",
            "UTM Program",
            "Vision Preconditions",
            "Screen State",
            "Physical Cross-check",
            "Data Artifact",
            "Analysis Handoff",
            "UTM motion is confirmed beyond the click event",
            "linux_pull=ok",
        ]
        body_text = result.get("text", "")
        body_text_lower = body_text.lower()
        missing_text = [token for token in required_text if token not in body_text and token.lower() not in body_text_lower]
        if missing_text:
            raise AssertionError(f"Windows Equipment workspace missing required text: {missing_text}")
        if result.get("missingIds"):
            raise AssertionError(f"Windows Equipment workspace missing required DOM ids: {result['missingIds']}")
        if result.get("scrollWidth", 0) > result.get("clientWidth", 0) + 24:
            raise AssertionError(f"Windows Equipment workspace horizontally overflows viewport: {result}")
        too_small = [item for item in result.get("commandCards", []) if item.get("width", 0) < 96 or item.get("height", 0) < 54]
        if too_small:
            raise AssertionError(f"Operator command cards are too small: {too_small}")
        out_dir.mkdir(parents=True, exist_ok=True)
        time.sleep(0.7)
        screenshot = out_dir / "windows_equipment_browser_audit.png"
        driver.save_screenshot(str(screenshot))
        result["screenshot"] = str(screenshot)
        return result
    finally:
        time.sleep(0.1)
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7862")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    args = parser.parse_args()
    result = run_audit(args.base_url, Path(args.out_dir), width=args.width, height=args.height, geckodriver=args.geckodriver)
    print("windows_equipment_browser_audit: PASS")
    print({key: value for key, value in result.items() if key != "text"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
