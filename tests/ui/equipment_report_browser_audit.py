#!/usr/bin/env python3
"""Browser-level audit for the Live GUI Lab Equipment UTM report.

This verifies the operator-facing report surface that cannot be fully proven by
backend tests alone:
- `/live` renders the Equipment selected-agent report at 1920x1080
- the report uses the UTM visual-control/data-loop vocabulary, not generic macro text
- screen assertions, Vision physical checks, UTM data ledger, and handoff gate
  are visible in the actual DOM
- the page does not horizontally overflow the viewport

It expects the FastAPI server to be running, default http://127.0.0.1:7862.
The script launches a local headless Firefox through Selenium/geckodriver.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


def equipment_payload() -> dict[str, Any]:
    """Return a minimal complete Equipment report payload for DOM rendering."""
    equipment_report = {
        "schema": "equipment_report.v1",
        "report_version": "lab_equipment_utm_visual_control_v1",
        "run_id": "run-equipment-browser-audit",
        "mode": "test",
        "task_id": "utm_compression_test",
        "bridge": {
            "provider": "windows_pyautogui",
            "connection_status": "ready",
            "pyautogui_available": True,
            "live_execute_enabled": False,
        },
        "preconditions": {"fixture_ready": True, "robot_clear_of_utm": True},
        "control_plan": {
            "program_id": "utm_compression_start_v1",
            "locator_backend": "image",
            "macro_version": "v1",
            "max_retries": 1,
            "profile": {
                "program_id": "utm_compression_start_v1",
                "profile_memory_path": "memory/equipment_utm_profile.json",
                "profile_memory_applied": True,
                "locator_count": 4,
                "locator_names": ["ready_state", "start_button", "running_state", "complete_state"],
            },
        },
        "vision_requests": [{"check_id": "utm_pre_start"}, {"check_id": "utm_motion_confirm"}, {"check_id": "utm_test_complete"}],
        "vision_cross_checks": {
            "required": ["utm_pre_start", "utm_motion_confirm", "utm_test_complete"],
            "checks": {
                "utm_pre_start": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
                "utm_motion_confirm": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
                "utm_test_complete": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
            },
            "all_required_ok": True,
            "blocking_reasons": [],
            "evidence_frame_ids": ["frame-pre", "frame-motion", "frame-done"],
        },
        "screen_checks": [
            {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "screen-before"},
            {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"},
            {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": "screen-complete"},
        ],
        "physical_checks": {
            "vision_motion_confirmed": True,
            "specimen_alignment_ok": True,
            "fixture_safe_to_access": True,
            "evidence_frame_ids": ["frame-pre", "frame-motion", "frame-done"],
        },
        "data_acquisition": {
            "status": "exported_on_windows",
            "save_method": "windows_export_watch",
            "save_attempted_by_agent": True,
            "save_confirmation_screen_ok": True,
            "windows_path": "C:/ATR/utm_exports/specimen-audit.csv",
            "linux_path": "/home/jin/autonomous_researcher/artifacts/equipment/run-equipment-browser-audit/utm/specimen-audit.csv",
            "sha256": "audit-sha256",
            "size_bytes": 4096,
            "row_count_probe": 80,
            "columns_probe": ["time_s", "displacement_mm", "force_N"],
        },
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
        },
        "decision": {
            "equipment_status": "verified_complete",
            "handoff_status": "ready_for_analysis",
            "failure_code": None,
            "blocking_reasons": [],
            "recommended_next_agent": "analysis_agent",
        },
    }
    return {
        "session": {
            "messages": [
                {
                    "role": "equipment_ai",
                    "content": "Lab Equipment Agent verified UTM screen, physical, and CSV data gates.",
                    "timestamp": "2026-05-30T00:15:00+09:00",
                    "equipment_report": equipment_report,
                }
            ],
            "state": {
                "run_id": "run-equipment-browser-audit",
                "experiment_id": "exp-equipment-browser-audit",
                "mode": "test",
                "stage": "equipment",
                "active_goal": "Verify UTM Equipment report rendering",
                "current_experiment_spec": {"specimen_id": "specimen-audit", "geometry_type": "gyroid_tpms"},
                "run_metadata": {
                    "equipment_result": {
                        "tool": "equipment.pyautogui.run",
                        "status": "verified_complete",
                        "program_id": "utm_compression_start_v1",
                        "result_file": equipment_report["data_acquisition"]["linux_path"],
                    },
                    "equipment_report": equipment_report,
                    "utm_data_ready": {
                        "schema": "utm_data_ready.v1",
                        "status": "ready",
                        "result_file": equipment_report["data_acquisition"]["linux_path"],
                        "evidence_refs": [equipment_report["data_acquisition"]["linux_path"]],
                    },
                    "equipment_handoff": {
                        "schema": "utm_data_ready.v1",
                        "status": "ready_for_analysis",
                        "program_id": "utm_compression_start_v1",
                        "result_file": equipment_report["data_acquisition"]["linux_path"],
                    },
                },
            },
            "runtime": {"backend": {"name": "vllm", "label": "NemoClaw/vLLM"}},
            "is_running": True,
            "planning_session_id": "session-equipment-browser-audit",
        },
        "snapshot": {"system_resources": {"gpu": {"status": "ready"}, "ram": {"status": "ready"}}},
        "events": [
            {
                "event_id": "evt-equipment-audit",
                "trace_id": "trace-equipment-audit",
                "event_type": "agent_completed",
                "level": "INFO",
                "node_id": "equipment",
                "agent_id": "equipment",
                "message": "Equipment UTM report browser audit event",
                "ts": "2026-05-30T00:15:00+09:00",
                "payload": {"node_id": "equipment", "agent_id": "equipment", "equipment_report": equipment_report},
            }
        ],
        "artifacts": [],
        "approvals": {"pending": [], "approvals": [], "resolved": []},
    }


def wait_for_live_gui(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return typeof window.__liveGuiDebugSetState === 'function'"))


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str) -> dict[str, Any]:
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    try:
        driver.get(f"{base_url.rstrip('/')}/live")
        wait_for_live_gui(driver)
        result = driver.execute_script(
            r"""
            const payload = arguments[0];
            try {
              localStorage.removeItem('autonomousLiveGuiUiState');
              sessionStorage.removeItem('autonomousLiveGuiUiState');
            } catch (err) {}
            window.__liveGuiDebugSetState(payload);
            window.__liveGuiDebugRestoreOperatorReportState('equipment', 'report');
            const report = document.querySelector('.live-agent-specific-equipment-details');
            const panel = document.getElementById('live-report-panel');
            const text = panel ? (panel.innerText || panel.textContent || '') : '';
            const headings = Array.from(document.querySelectorAll('.live-agent-specific-equipment-details h5')).map((item) => item.textContent || '');
            const doc = document.documentElement;
            const reportRect = report ? report.getBoundingClientRect() : null;
            return {
              ok: Boolean(report),
              title: document.title,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              reportRect: reportRect ? {x: reportRect.x, y: reportRect.y, width: reportRect.width, height: reportRect.height} : null,
              headings,
              text,
            };
            """,
            equipment_payload(),
        )
        required_text = [
            "Lab Equipment / UTM Visual Control",
            "Bridge / Protocol Profile",
            "Screen-State Assertions",
            "Vision Physical Cross-Checks",
            "UTM Data Ledger",
            "Handoff Gate / Blocking Reasons",
            "Safety Gate / Guardian",
            "Live Evidence Audit",
            "Artifact / Evidence Ledger",
            "Failure / Recovery",
            "utm_compression_start_v1",
            "ready_for_analysis",
            "data_parse_probe_ok",
            "save_export_responsibility_ok",
            "Save/Export",
            "time_s",
            "displacement_mm",
            "force_N",
        ]
        missing = [token for token in required_text if token not in result.get("text", "")]
        if missing:
            raise AssertionError(f"Equipment report missing required text: {missing}")
        if not result.get("ok"):
            raise AssertionError("Equipment report detail container was not rendered")
        if result.get("scrollWidth", 0) > result.get("clientWidth", 0) + 24:
            raise AssertionError(f"Live GUI report horizontally overflows viewport: {result}")
        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot = out_dir / "equipment_report_browser_audit.png"
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
    print("equipment_report_browser_audit: PASS")
    print({key: value for key, value in result.items() if key != "text"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
