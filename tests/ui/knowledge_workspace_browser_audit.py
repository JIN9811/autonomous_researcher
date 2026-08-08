"""Headless browser audit for the dedicated Knowledge Workspace."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import WebDriverWait


def audit(base_url: str, screenshot_path: Path, *, geckodriver: str) -> dict[str, object]:
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(1920, 1080)
    try:
        driver.get(f"{base_url.rstrip('/')}/knowledge")
        wait = WebDriverWait(driver, 20)
        wait.until(conditions.text_to_be_present_in_element((By.ID, "knowledge-backend-status"), "neo4j"))
        wait.until(lambda item: item.execute_script("return document.querySelectorAll('#knowledge-graph canvas').length") > 0)
        wait.until(lambda item: "waiting" not in item.find_element(By.ID, "knowledge-query-summary").text.lower())

        for tab_name in ("memory", "ontology", "project", "graph"):
            driver.find_element(By.CSS_SELECTOR, f'[data-knowledge-tab="{tab_name}"]').click()
            wait.until(lambda item, name=tab_name: item.find_element(By.CSS_SELECTOR, f'[data-knowledge-panel="{name}"]').is_displayed())
            time.sleep(0.15)

        layout = driver.execute_script(
            """
            const body = document.body;
            const graph = document.getElementById('knowledge-graph').getBoundingClientRect();
            const inspector = document.getElementById('knowledge-node-inspector').getBoundingClientRect();
            return {
              viewportWidth: window.innerWidth,
              viewportHeight: window.innerHeight,
              scrollWidth: body.scrollWidth,
              graphWidth: graph.width,
              graphHeight: graph.height,
              inspectorWidth: inspector.width,
              canvasCount: document.querySelectorAll('#knowledge-graph canvas').length,
              tabs: document.querySelectorAll('[data-knowledge-tab]').length,
            };
            """
        )
        if layout["scrollWidth"] > layout["viewportWidth"] + 2:
            raise AssertionError(f"horizontal overflow detected: {layout}")
        if layout["graphWidth"] < 900 or layout["graphHeight"] < 500:
            raise AssertionError(f"graph canvas is undersized: {layout}")
        if layout["inspectorWidth"] < 280 or layout["canvasCount"] < 1 or layout["tabs"] != 5:
            raise AssertionError(f"workspace contract failed: {layout}")

        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(screenshot_path))
        return {
            "ok": True,
            "url": driver.current_url,
            "layout": layout,
            "screenshot": screenshot_path.as_posix(),
        }
    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("artifacts/ui/knowledge_workspace_1920x1080.png"),
    )
    args = parser.parse_args()
    print(json.dumps(audit(args.base_url, args.screenshot, geckodriver=args.geckodriver), indent=2))


if __name__ == "__main__":
    main()
