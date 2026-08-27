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
from selenium.webdriver.support.ui import Select, WebDriverWait


def audit(base_url: str, screenshot_path: Path, *, geckodriver: str) -> dict[str, object]:
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(1920, 1080)
    try:
        driver.get(f"{base_url.rstrip('/')}/knowledge")
        wait = WebDriverWait(driver, 20)
        wait.until(lambda item: item.find_element(By.ID, "knowledge-backend-status").text.lower() not in {"", "loading"})
        wait.until(lambda item: item.execute_script("return document.querySelectorAll('#knowledge-graph canvas').length") > 0)
        wait.until(lambda item: "waiting" not in item.find_element(By.ID, "knowledge-query-summary").text.lower())

        for tab_name in ("memory", "ontology", "project", "manuals", "relations"):
            driver.find_element(By.CSS_SELECTOR, f'[data-knowledge-tab="{tab_name}"]').click()
            wait.until(lambda item, name=tab_name: item.find_element(By.CSS_SELECTOR, f'[data-knowledge-panel="{name}"]').is_displayed())
            time.sleep(0.15)
        relation_queue_width = driver.find_element(By.ID, "knowledge-relation-queue").rect["width"]

        driver.find_element(By.CSS_SELECTOR, '[data-knowledge-tab="manuals"]').click()
        wait.until(lambda item: item.find_element(By.CSS_SELECTOR, '[data-knowledge-panel="manuals"]').is_displayed())
        wait.until(lambda item: item.execute_script("return document.querySelectorAll('#knowledge-manual-graph canvas').length") > 0)
        Select(driver.find_element(By.ID, "knowledge-manual-purpose")).select_by_value("recovery")
        manual_query = driver.find_element(By.ID, "knowledge-manual-query")
        manual_query.clear()
        manual_query.send_keys("통신 연결 실패 원인과 복구 조치")
        driver.find_element(By.ID, "knowledge-manual-run-query").click()
        wait.until(lambda item: "citations" in item.find_element(By.ID, "knowledge-manual-query-summary").text.lower())
        wait.until(
            lambda item: item.execute_script(
                "return (echarts.getInstanceByDom(document.getElementById('knowledge-manual-graph'))?.getOption()?.series?.[0]?.data || []).length"
            ) > 0
        )
        manual_inspection = driver.execute_script(
            """
            const chart = echarts.getInstanceByDom(document.getElementById('knowledge-manual-graph'));
            const nodes = chart?.getOption()?.series?.[0]?.data || [];
            const chunkNodes = nodes.filter((node) => node.kind === 'ManualChunk').length;
            const first = nodes[0];
            if (first) renderManualInspector(first, 'node');
            return {nodeCount: nodes.length, chunkNodes};
            """
        )
        wait.until(lambda item: "confidence" in item.find_element(By.ID, "knowledge-manual-inspector").text.lower())
        inspector_text = driver.find_element(By.ID, "knowledge-manual-inspector").text.lower()
        if "[object object]" in inspector_text:
            raise AssertionError(f"manual inspector rendered a chart style object as a semantic label: {inspector_text}")
        if "p." not in inspector_text:
            raise AssertionError(f"manual inspector lacks page citation: {inspector_text}")
        manual_layout = driver.execute_script(
            """
            const graph = document.getElementById('knowledge-manual-graph').getBoundingClientRect();
            const results = document.getElementById('knowledge-manual-results').getBoundingClientRect();
            const inspector = document.getElementById('knowledge-manual-inspector').getBoundingClientRect();
            return {graphWidth: graph.width, graphHeight: graph.height, resultsWidth: results.width, inspectorWidth: inspector.width};
            """
        )

        driver.find_element(By.CSS_SELECTOR, '[data-knowledge-tab="graph"]').click()
        wait.until(lambda item: item.find_element(By.CSS_SELECTOR, '[data-knowledge-panel="graph"]').is_displayed())

        driver.find_element(By.ID, "knowledge-edit-mode").click()
        wait.until(lambda item: item.find_element(By.ID, "knowledge-edit-toolbar").is_displayed())
        if driver.find_element(By.ID, "knowledge-edit-apply").is_enabled():
            raise AssertionError("graph edit apply must remain disabled until server validation")
        staged = driver.execute_script(
            """
            const chart = echarts.getInstanceByDom(document.getElementById('knowledge-graph'));
            const node = chart?.getOption()?.series?.[0]?.data?.[0];
            if (!node) return false;
            stageGraphEdit({operation: 'update_node_metadata', node_id: String(node.id), metadata: {note: 'browser audit draft'}}, 'Browser audit draft staged.');
            return true;
            """
        )
        if not staged:
            raise AssertionError("no bounded graph node available for edit validation audit")
        wait.until(lambda item: item.find_element(By.ID, "knowledge-edit-validate").is_enabled())
        driver.find_element(By.ID, "knowledge-edit-validate").click()
        wait.until(lambda item: item.find_element(By.ID, "knowledge-edit-apply").is_enabled())
        driver.find_element(By.ID, "knowledge-edit-discard").click()
        wait.until(lambda item: not item.find_element(By.ID, "knowledge-edit-apply").is_enabled())

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
              editMode: document.getElementById('knowledge-edit-mode').getAttribute('aria-pressed'),
              relationQueue: arguments[0],
              manualLayout: arguments[1],
              manualInspection: arguments[2],
            };
            """,
            relation_queue_width,
            manual_layout,
            manual_inspection,
        )
        if layout["scrollWidth"] > layout["viewportWidth"] + 2:
            raise AssertionError(f"horizontal overflow detected: {layout}")
        if layout["graphWidth"] < 900 or layout["graphHeight"] < 500:
            raise AssertionError(f"graph canvas is undersized: {layout}")
        if layout["inspectorWidth"] < 280 or layout["canvasCount"] < 1 or layout["tabs"] != 7:
            raise AssertionError(f"workspace contract failed: {layout}")
        if layout["manualLayout"]["graphWidth"] < 700 or layout["manualLayout"]["graphHeight"] < 500 or layout["manualLayout"]["resultsWidth"] < 360 or layout["manualLayout"]["inspectorWidth"] < 280:
            raise AssertionError(f"manual workspace contract failed: {layout}")
        if layout["manualInspection"]["chunkNodes"] or layout["manualInspection"]["nodeCount"] < 1:
            raise AssertionError(f"manual semantic projection failed: {layout}")
        if layout["editMode"] != "true" or layout["relationQueue"] < 260:
            raise AssertionError(f"workspace contract failed: {layout}")

        driver.find_element(By.CSS_SELECTOR, '[data-knowledge-tab="manuals"]').click()
        wait.until(lambda item: item.find_element(By.CSS_SELECTOR, '[data-knowledge-panel="manuals"]').is_displayed())
        time.sleep(0.2)
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
