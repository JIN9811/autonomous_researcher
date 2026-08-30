#!/usr/bin/env python3
"""Browser audit for the Linux-side `/equipment/windows` workspace.

This page is the Linux-owned operator surface for connecting an equipment
worker, building and deploying Skills, running a bounded Profile action, and
reviewing evidence before Analysis handoff. The audit is non-actuating: it
injects representative runtime/Skill/evidence payloads and verifies the
frontend projection without calling an equipment execute endpoint.
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
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return Boolean(document.getElementById('equipment-agentic-progress'))"))
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return typeof renderEquipmentRuntimeOverview === 'function' && typeof renderEquipmentSkills === 'function'"))
    WebDriverWait(driver, 20).until(
        lambda item: item.execute_script(
            """
            const status = document.getElementById('equipment-vision-link-status');
            const checkbox = document.getElementById('equipment-vision-link-enabled');
            return Boolean(status && checkbox && !status.textContent.startsWith('Loading') && !checkbox.disabled);
            """
        )
    )


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str) -> dict[str, Any]:
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    try:
        driver.get(f"{base_url.rstrip('/')}/equipment/windows")
        wait_for_workspace(driver)
        initial_vision_selection = bool(
            driver.execute_script("return document.getElementById('equipment-vision-link-enabled').checked;")
        )
        driver.execute_script("document.getElementById('equipment-vision-link-enabled').click();")
        WebDriverWait(driver, 20).until(
            lambda item: "saved automatically" in item.find_element("id", "equipment-vision-link-status").text
        )
        driver.refresh()
        wait_for_workspace(driver)
        persisted_vision_selection = bool(
            driver.execute_script("return document.getElementById('equipment-vision-link-enabled').checked;")
        )
        if persisted_vision_selection == initial_vision_selection:
            raise AssertionError("Vision Link selection did not persist across a browser refresh")
        driver.execute_script("document.getElementById('equipment-vision-link-enabled').click();")
        WebDriverWait(driver, 20).until(
            lambda item: "saved automatically" in item.find_element("id", "equipment-vision-link-status").text
        )
        driver.refresh()
        wait_for_workspace(driver)
        restored_vision_selection = bool(
            driver.execute_script("return document.getElementById('equipment-vision-link-enabled').checked;")
        )
        if restored_vision_selection != initial_vision_selection:
            raise AssertionError("Vision Link selection could not be restored after persistence audit")
        driver.execute_script(
            """
            document.getElementById('equipment-vision-link-enabled').checked = true;
            document.getElementById('btn-equipment-profile-preflight').click();
            """
        )
        WebDriverWait(driver, 20).until(
            lambda item: "vision_link_request" in item.find_element("id", "equipment-result-log").get_attribute("textContent")
        )
        frontend_backend = driver.execute_script(
            "return JSON.parse(document.getElementById('equipment-result-log').textContent);"
        )
        expected_vision = {
            "requested": True,
            "profile_enabled": True,
            "required": False,
            "effective": True,
        }
        if frontend_backend.get("vision_link_request") != expected_vision:
            raise AssertionError(f"Vision Link frontend/backend contract mismatch: {frontend_backend}")
        result = driver.execute_script(
            r"""
            renderEquipmentRuntimeOverview({
              execution: {lifecycle: "EXECUTING", metadata: {agentic_progress: "EXECUTING"}},
              projection: {
                execution_id: "eq-audit-0001",
                lifecycle: "EXECUTING",
                status: "active",
                profile_id: "utm_windows_v1",
                mode: "test",
                execution_ref: {type: "skill", skill_id: "compression_test", version: "1.2.0"},
                worker: {worker_id: "local_development"},
                evidence_count: 3,
                failure_code: ""
              }
            });
            renderEquipmentSkills({skills: [
              {skill_id: "compression_test", version: "1.2.0", name: "Compression Test", target_profile: "utm_windows_v1", lifecycle: "validated", enabled: true},
              {skill_id: "export_result", version: "1.0.0", name: "Export Result", target_profile: "utm_windows_v1", lifecycle: "deployed", enabled: true}
            ]});
            document.querySelector("#equipment-skill-list .equipment-skill-row").click();
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
            const storyboardCanvas = document.createElement("canvas");
            storyboardCanvas.width = 640;
            storyboardCanvas.height = 360;
            const storyboardContext = storyboardCanvas.getContext("2d");
            storyboardContext.fillStyle = "#0b1320";
            storyboardContext.fillRect(0, 0, 640, 360);
            storyboardContext.fillStyle = "#24c8a5";
            storyboardContext.fillRect(24, 24, 136, 136);
            storyboardContext.fillStyle = "#eef6ff";
            storyboardContext.font = "24px sans-serif";
            storyboardContext.fillText("00:00.0 PRE", 184, 96);
            storyboardContext.fillText("00:07.5 POST", 184, 140);
            renderSkillStoryboardPage({
              cursor: 0,
              limit: 1,
              total_count: 2,
              next_cursor: 1,
              items: [{
                name: "chunk-0001.jpg",
                media_type: "image/png",
                data_base64: storyboardCanvas.toDataURL("image/png").split(",")[1]
              }]
            });
            writeLog({ok: false, status: "blocked", tool: "equipment.pyautogui.run", failure_code: "UTM_DATA_NO_FORCE_SIGNAL"});
            const doc = document.documentElement;
            const requiredIds = [
              "equipment-runtime-overview",
              "equipment-connection-workspace",
              "equipment-agentic-progress",
              "equipment-agentic-progress-stages",
              "equipment-skill-recording",
              "equipment-skill-storyboard-preview",
              "equipment-skill-storyboard-image",
              "equipment-skill-storyboard-meta",
              "btn-equipment-skill-storyboard-previous",
              "btn-equipment-skill-storyboard-next",
              "equipment-skill-management",
              "equipment-skill-list",
              "equipment-selected-skill",
              "btn-equipment-skill-workflow-editor",
              "equipment-main-progress",
              "equipment-vision-link",
              "equipment-vision-link-enabled",
              "equipment-error-recovery",
              "equipment-evidence-workspace",
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
            const progressCards = Array.from(document.querySelectorAll("[data-equipment-stage]")).map((item) => {
              const rect = item.getBoundingClientRect();
              return {text: item.textContent || "", width: rect.width, height: rect.height};
            });
            const savedWorkers = document.getElementById("equipment-saved-candidates");
            const savedWorkerCards = savedWorkers ? Array.from(savedWorkers.querySelectorAll(".equipment-candidate-card")) : [];
            const selectedWorkerIndex = savedWorkerCards.findIndex((card) => card.classList.contains("selected"));
            const savedWorkerStyle = savedWorkers ? getComputedStyle(savedWorkers) : null;
            const storyboard = document.getElementById("equipment-skill-storyboard-preview");
            const storyboardRect = storyboard ? storyboard.getBoundingClientRect() : null;
            if (document.getElementById("btn-equipment-skill-workflow-editor")?.disabled) {
              renderEquipmentSkills({skills: [
                {skill_id: "compression_test", version: "1.2.0", name: "Compression Test", target_profile: "utm_windows_v1", lifecycle: "validated", enabled: true}
              ]});
              document.querySelector("#equipment-skill-list .equipment-skill-row").click();
            }
            const workflowEditorButton = document.getElementById("btn-equipment-skill-workflow-editor");
            const workflowSelectionTrace = {
              rowCount: document.querySelectorAll(".equipment-skill-row").length,
              selectedCount: document.querySelectorAll(".equipment-skill-row.selected").length,
              selectedText: document.getElementById("equipment-selected-skill")?.textContent || "",
              buttonDisabled: workflowEditorButton?.disabled,
            };
            const text = document.body ? (document.body.innerText || document.body.textContent || "") : "";
            return {
              ok: missingIds.length === 0,
              title: document.title,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              missingIds,
              progressCards,
              savedWorkers: {
                count: savedWorkerCards.length,
                selectedIndex: selectedWorkerIndex,
                overflowY: savedWorkerStyle ? savedWorkerStyle.overflowY : "",
                maxHeight: savedWorkerStyle ? savedWorkerStyle.maxHeight : "",
              },
              storyboard: storyboardRect ? {
                hidden: storyboard.hidden,
                width: storyboardRect.width,
                height: storyboardRect.height,
              } : null,
              workflowEditor: workflowEditorButton ? {
                title: workflowEditorButton.getAttribute("title"),
                disabled: workflowEditorButton.disabled,
                compileButtons: document.querySelectorAll("#btn-equipment-skill-compile").length,
                validateButtons: document.querySelectorAll("#btn-equipment-skill-validate").length,
              } : null,
              workflowSelectionTrace,
              text,
            };
            """
        )
        WebDriverWait(driver, 20).until(
            lambda item: item.execute_script(
                "return document.getElementById('equipment-skill-storyboard-image').naturalWidth >= 640;"
            )
        )
        result["storyboard"] = driver.execute_script(
            """
            const item = document.getElementById("equipment-skill-storyboard-preview");
            const rect = item.getBoundingClientRect();
            return {hidden: item.hidden, width: rect.width, height: rect.height};
            """
        )
        required_text = [
            "Lab Equipment Workspace",
            "Connection & Profile",
            "Agentic Progress",
            "Skill Recording",
            "Skill Management",
            "Main Progress",
            "Vision Link",
            "Error Recovery",
            "Evidence & Data Transfer",
            "Compression Test",
            "eq-audit-0001",
            "Preflight",
            "Evidence",
            "Stop / Abort Active Skill",
            "UTM evidence audit: blocked",
            "request_log=execute-ok",
            "save_export=missing",
            "parse=missing",
            "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED",
            "UTM_DATA_NO_FORCE_SIGNAL",
            "Build Package",
            "Verify Package",
            "Open Windows GUI",
            "Bridge on This PC",
            "Worker",
            "Skill / Program",
            "Equipment Effect",
            "Data Transfer",
            "Analysis Handoff",
            "linux_pull=ok",
            "chunk-0001.jpg",
            "1/2",
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
        too_small = [item for item in result.get("progressCards", []) if item.get("width", 0) < 96 or item.get("height", 0) < 72]
        if too_small:
            raise AssertionError(f"Agentic progress cards are too small: {too_small}")
        saved_workers = result.get("savedWorkers", {})
        if saved_workers.get("selectedIndex", -1) > 0:
            raise AssertionError(f"Selected saved worker is not first: {saved_workers}")
        if saved_workers.get("overflowY") != "auto" or saved_workers.get("maxHeight") != "258px":
            raise AssertionError(f"Saved worker list is not limited to the three-card scroll viewport: {saved_workers}")
        storyboard = result.get("storyboard") or {}
        if storyboard.get("hidden") or storyboard.get("width", 0) < 240 or storyboard.get("height", 0) < 120:
            raise AssertionError(f"Timeline storyboard preview is hidden or clipped: {storyboard}")
        workflow_editor = result.get("workflowEditor") or {}
        if workflow_editor.get("title") != "Edit selected Skill workflow":
            raise AssertionError(f"Workflow Editor button title is incorrect: {workflow_editor}")
        if workflow_editor.get("disabled"):
            raise AssertionError(
                "Workflow Editor button was not enabled after exact Skill selection: "
                f"{workflow_editor}; trace={result.get('workflowSelectionTrace')}"
            )
        if workflow_editor.get("compileButtons") or workflow_editor.get("validateButtons"):
            raise AssertionError(f"Standalone Compile/Validate controls remain visible: {workflow_editor}")
        out_dir.mkdir(parents=True, exist_ok=True)
        time.sleep(0.7)
        screenshot = out_dir / "windows_equipment_browser_audit.png"
        driver.save_screenshot(str(screenshot))
        driver.execute_script(
            "document.getElementById('equipment-skill-recording').scrollIntoView({block: 'center'});"
        )
        time.sleep(0.4)
        storyboard_screenshot = out_dir / "windows_equipment_storyboard_audit.png"
        driver.save_screenshot(str(storyboard_screenshot))
        result["screenshot"] = str(screenshot)
        result["storyboard_screenshot"] = str(storyboard_screenshot)
        result["frontend_backend"] = frontend_backend.get("vision_link_request")
        result["vision_link_persistence"] = {
            "initial": initial_vision_selection,
            "persisted_after_refresh": persisted_vision_selection,
            "restored": restored_vision_selection,
        }
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
