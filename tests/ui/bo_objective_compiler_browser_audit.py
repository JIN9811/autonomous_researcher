"""Browser audit for the BO Objective Compiler and Live objective status card."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import WebDriverWait


def audit(base_url: str, out_dir: Path, *, geckodriver: str) -> dict[str, object]:
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(1920, 1080)
    wait = WebDriverWait(driver, 25)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        driver.get(f"{base_url.rstrip('/')}/bo")
        wait.until(conditions.visibility_of_element_located((By.ID, "objective-compiler-workspace")))
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, "#objective-metric-browser .bo-metric-entry")) > 0)
        wait.until(
            lambda item: item.execute_script(
                "return getComputedStyle(document.getElementById('objective-compiler-workspace')).opacity === '1'"
            )
        )
        workspace = driver.find_element(By.ID, "objective-compiler-workspace")
        driver.execute_script("arguments[0].scrollIntoView({block: 'start'});", workspace)
        bo_layout = driver.execute_script(
            """
            const workspace = document.getElementById('objective-compiler-workspace');
            const rect = workspace.getBoundingClientRect();
            return {
              viewportWidth: window.innerWidth,
              bodyScrollWidth: document.body.scrollWidth,
              workspaceWidth: rect.width,
              workspaceScrollWidth: workspace.scrollWidth,
              metricCount: document.querySelectorAll('#objective-metric-browser .bo-metric-entry').length,
              composeEnabled: !document.getElementById('btn-objective-compose').disabled,
              approveDisabled: document.getElementById('btn-objective-approve').disabled,
              activateDisabled: document.getElementById('btn-objective-activate').disabled,
            };
            """
        )
        if bo_layout["bodyScrollWidth"] > bo_layout["viewportWidth"] + 2:
            raise AssertionError(f"BO page horizontal overflow: {bo_layout}")
        if bo_layout["workspaceScrollWidth"] > bo_layout["workspaceWidth"] + 2:
            raise AssertionError(f"Objective workspace overflow: {bo_layout}")
        if bo_layout["metricCount"] < 1 or not bo_layout["composeEnabled"]:
            raise AssertionError(f"Objective compiler did not initialize: {bo_layout}")
        if not bo_layout["approveDisabled"] or not bo_layout["activateDisabled"]:
            raise AssertionError(f"Lifecycle gates opened before validation: {bo_layout}")
        bo_screenshot = out_dir / "bo_objective_compiler_1920x1080.png"
        driver.save_screenshot(str(bo_screenshot))

        driver.refresh()
        wait.until(conditions.visibility_of_element_located((By.ID, "objective-compiler-workspace")))
        wait.until(lambda item: item.find_element(By.ID, "objective-lifecycle-chip").text != "")

        driver.get(f"{base_url.rstrip('/')}/live")
        card = wait.until(conditions.visibility_of_element_located((By.ID, "live-objective-runtime-card")))
        wait.until(lambda item: item.find_element(By.ID, "live-objective-readiness").text != "")
        wait.until(
            lambda item: item.execute_script(
                "return getComputedStyle(document.querySelector('.live-center-panel')).opacity === '1'"
            )
        )
        wait.until(lambda item: item.find_element(By.ID, "planning-stage-label").text != "Mission loading")
        live_layout = driver.execute_script(
            """
            const card = document.getElementById('live-objective-runtime-card').getBoundingClientRect();
            const report = document.getElementById('live-report-panel').getBoundingClientRect();
            return {
              viewportWidth: window.innerWidth,
              bodyScrollWidth: document.body.scrollWidth,
              cardWidth: card.width,
              cardHeight: card.height,
              cardBottom: card.bottom,
              reportTop: report.top,
              readiness: document.getElementById('live-objective-readiness').textContent.trim(),
            };
            """
        )
        if live_layout["bodyScrollWidth"] > live_layout["viewportWidth"] + 2:
            raise AssertionError(f"Live page horizontal overflow: {live_layout}")
        if live_layout["cardWidth"] < 600 or live_layout["cardHeight"] > 150:
            raise AssertionError(f"Live objective card is not compact: {live_layout}")
        if live_layout["cardBottom"] > live_layout["reportTop"] + 2:
            raise AssertionError(f"Live objective card overlaps report: {live_layout}")
        live_screenshot = out_dir / "live_objective_card_1920x1080.png"
        driver.save_screenshot(str(live_screenshot))
        return {
            "ok": True,
            "bo": bo_layout,
            "live": live_layout,
            "screenshots": [bo_screenshot.as_posix(), live_screenshot.as_posix()],
            "card_text": card.text,
        }
    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/ui/objective_compiler"))
    args = parser.parse_args()
    print(json.dumps(audit(args.base_url, args.out_dir, geckodriver=args.geckodriver), indent=2))


if __name__ == "__main__":
    main()
