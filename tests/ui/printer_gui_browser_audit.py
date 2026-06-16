#!/usr/bin/env python3
"""Browser audit for the 3DP Printer / Bambu proof package workspace.

The audit is intentionally non-actuating. It opens `/printer`, verifies that the
Bambu physical-proof controls render, creates a fail-closed proof template at a
caller-controlled local path, and runs the completion audit against that file.
It must not publish MQTT, upload an artifact, capture a live camera frame, or
move printer axes.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


def wait_for_printer_workspace(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(
        lambda item: item.execute_script("return Boolean(document.getElementById('btn-printer-autoejection-proof-template'))")
    )
    WebDriverWait(driver, 20).until(lambda item: item.execute_script("return typeof runBambuProofTemplate === 'function'"))


def _visible_text(driver: webdriver.Firefox) -> str:
    return driver.execute_script("return document.body ? (document.body.innerText || document.body.textContent || '') : ''")


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str, proof_path: str = "") -> dict[str, Any]:
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    selected_proof_path = Path(proof_path).expanduser() if proof_path else out_dir / f"bambu_autoejection_physical_validation_browser_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    selected_proof_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        driver.get(f"{base_url.rstrip('/')}/printer")
        wait_for_printer_workspace(driver)
        body_text = _visible_text(driver)
        required_text = [
            "3DP Printer GUI",
            "Bambu Lab Device Bridge",
            "Bambu G-code Autoejection",
            "Physical Proof Package",
            "Build Fail-Closed Proof Template",
            "Run Completion Audit",
        ]
        missing = [token for token in required_text if token not in body_text]
        if missing:
            raise AssertionError(f"Printer workspace missing required text: {missing}")
        result = driver.execute_script(
            r"""
            const proofInput = document.getElementById('printer-autoejection-proof-path-input');
            const proofSection = document.getElementById('btn-printer-autoejection-proof-template');
            proofInput.value = arguments[0];
            proofSection.scrollIntoView({block: 'center', inline: 'nearest'});
            const doc = document.documentElement;
            return {
              title: document.title,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              proofInputValue: proofInput.value,
            };
            """,
            str(selected_proof_path),
        )
        if result.get("scrollWidth", 0) > result.get("clientWidth", 0) + 24:
            raise AssertionError(f"Printer workspace horizontally overflows viewport: {result}")

        driver.find_element(By.ID, "btn-printer-autoejection-proof-template").click()
        WebDriverWait(driver, 20).until(
            lambda item: "template_written_fail_closed" in item.find_element(By.ID, "printer-autoejection-proof-summary").text
        )
        template_summary = driver.find_element(By.ID, "printer-autoejection-proof-summary").text
        template_detail = driver.find_element(By.ID, "printer-autoejection-proof-detail").text
        if "evidence verified" in template_summary.lower():
            raise AssertionError(f"Fail-closed proof template must not claim evidence verification: {template_summary}")
        if not selected_proof_path.exists():
            raise AssertionError(f"Proof template path was not written: {selected_proof_path}")

        driver.find_element(By.ID, "btn-printer-autoejection-completion-audit").click()
        WebDriverWait(driver, 20).until(
            lambda item: "incomplete" in item.find_element(By.ID, "printer-autoejection-proof-summary").text.lower()
        )
        audit_summary = driver.find_element(By.ID, "printer-autoejection-proof-summary").text
        audit_detail = driver.find_element(By.ID, "printer-autoejection-proof-detail").text
        if "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" not in audit_detail:
            raise AssertionError(f"Completion audit did not surface physical-ejection blocker: {audit_detail}")

        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot = out_dir / "printer_gui_browser_audit.png"
        driver.save_screenshot(str(screenshot))
        return {
            **result,
            "ok": True,
            "proof_path": str(selected_proof_path),
            "template_summary": template_summary,
            "template_detail": template_detail,
            "audit_summary": audit_summary,
            "audit_detail": audit_detail,
            "screenshot": str(screenshot),
        }
    finally:
        time.sleep(0.1)
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7862")
    parser.add_argument("--out-dir", default=str(Path(tempfile.gettempdir()) / "atr_printer_gui_audit"))
    parser.add_argument("--proof-path", default="")
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
        proof_path=args.proof_path,
    )
    print("printer_gui_browser_audit: PASS")
    print({key: value for key, value in result.items() if key not in {"template_detail", "audit_detail"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
