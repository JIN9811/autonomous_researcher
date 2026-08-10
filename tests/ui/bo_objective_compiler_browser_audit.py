"""Browser audit for the BO Objective Compiler and Live objective status card."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import uuid

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import Select
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

        objective_id = f"browser-audit-{uuid.uuid4().hex[:10]}"
        driver.find_element(By.CSS_SELECTOR, '[data-objective-mode="visual"]').click()
        wait.until(conditions.visibility_of_element_located((By.ID, "objective-manual-builder")))
        identity = driver.find_element(By.ID, "objective-manual-id")
        identity.clear()
        identity.send_keys(objective_id)
        driver.execute_script("arguments[0].blur();", identity)
        name = driver.find_element(By.ID, "objective-manual-name")
        name.send_keys("Browser audit weighted objective")
        driver.execute_script("arguments[0].blur();", name)
        root_operator = wait.until(conditions.presence_of_element_located((By.CSS_SELECTOR, '[data-node-path="expression"] > .bo-tree-node-head .bo-tree-operator')))
        Select(root_operator).select_by_value("weighted_sum")
        term_operator = wait.until(conditions.presence_of_element_located((By.CSS_SELECTOR, '[data-node-path="expression.terms.0.expression"] .bo-tree-operator')))
        Select(term_operator).select_by_value("metric")
        driver.find_element(By.ID, "btn-objective-add-constraint").click()
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, "#objective-constraints-builder .bo-tree-node")) >= 3)

        driver.find_element(By.CSS_SELECTOR, '[data-objective-mode="json"]').click()
        json_editor = wait.until(conditions.visibility_of_element_located((By.ID, "objective-json-editor")))
        valid_json = json_editor.get_attribute("value")
        json_editor.clear()
        json_editor.send_keys('{"expression":')
        driver.find_element(By.ID, "btn-objective-json-apply").click()
        wait.until(lambda item: "JSON parse error" in item.find_element(By.ID, "objective-json-errors").text)
        if driver.find_element(By.ID, "objective-json-editor").get_attribute("value") == valid_json:
            raise AssertionError("Invalid JSON replaced its buffer instead of remaining visible")
        driver.find_element(By.ID, "btn-objective-json-restore").click()
        wait.until(lambda item: item.find_element(By.ID, "objective-json-editor").get_attribute("value") == valid_json)

        driver.find_element(By.ID, "btn-objective-manual-save").click()
        wait.until(lambda item: objective_id in item.find_element(By.ID, "objective-active-identity").text)
        wait.until(lambda item: "Saved" in item.find_element(By.ID, "objective-manual-status").text)
        driver.find_element(By.ID, "btn-objective-load-revision").click()
        wait.until(lambda item: "Revision of" in item.find_element(By.ID, "objective-manual-revision-label").text)
        manual_layout = driver.execute_script(
            """
            const workspace = document.getElementById('objective-compiler-workspace');
            const rect = workspace.getBoundingClientRect();
            return {
              authorMode: document.querySelector('[data-objective-mode].active')?.dataset.objectiveMode,
              nodeCount: document.querySelectorAll('#objective-expression-builder .bo-tree-node').length,
              constraintCount: document.querySelectorAll('#objective-constraints-builder > .bo-tree-node').length,
              dirty: document.getElementById('objective-builder-dirty').textContent.trim(),
              workspaceWidth: rect.width,
              workspaceScrollWidth: workspace.scrollWidth,
            };
            """
        )
        if manual_layout["authorMode"] != "visual" or manual_layout["nodeCount"] < 2 or manual_layout["constraintCount"] != 1:
            raise AssertionError(f"Manual builder interaction did not persist: {manual_layout}")
        if manual_layout["workspaceScrollWidth"] > manual_layout["workspaceWidth"] + 2:
            raise AssertionError(f"Manual builder horizontal overflow: {manual_layout}")
        manual_screenshot = out_dir / "bo_manual_objective_builder_1920x1080.png"
        driver.save_screenshot(str(manual_screenshot))

        driver.set_window_size(390, 844)
        driver.execute_script("document.getElementById('objective-compiler-workspace').scrollIntoView({block: 'start'});")
        mobile_layout = driver.execute_script(
            """
            return {
              viewportWidth: window.innerWidth,
              bodyScrollWidth: document.body.scrollWidth,
              workspaceWidth: document.getElementById('objective-compiler-workspace').getBoundingClientRect().width,
              workspaceScrollWidth: document.getElementById('objective-compiler-workspace').scrollWidth,
            };
            """
        )
        if mobile_layout["bodyScrollWidth"] > mobile_layout["viewportWidth"] + 2:
            raise AssertionError(f"Manual builder mobile page overflow: {mobile_layout}")
        if mobile_layout["workspaceScrollWidth"] > mobile_layout["workspaceWidth"] + 2:
            raise AssertionError(f"Manual builder mobile workspace overflow: {mobile_layout}")
        mobile_screenshot = out_dir / "bo_manual_objective_builder_390x844.png"
        driver.save_screenshot(str(mobile_screenshot))
        driver.set_window_size(1920, 1080)

        driver.refresh()
        wait.until(conditions.visibility_of_element_located((By.ID, "objective-compiler-workspace")))
        wait.until(lambda item: item.find_element(By.ID, "objective-lifecycle-chip").text != "")

        budget = driver.find_element(By.ID, "bo-budget-input")
        budget.clear()
        budget.send_keys("3")
        driver.find_element(By.ID, "btn-bo-benchmark").click()
        wait.until(lambda item: "Benchmark complete" in item.find_element(By.ID, "bo-status-label").text)
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, "#bo-posterior-plot svg.bo-viz-svg")) == 1)
        posterior_layout = driver.execute_script(
            """
            const card = document.getElementById('bo-posterior-card');
            const equation = document.getElementById('bo-objective-equation-card');
            const plot = document.getElementById('bo-posterior-plot');
            return {
              svgCount: plot.querySelectorAll('svg.bo-viz-svg').length,
              confidenceBands: plot.querySelectorAll('.bo-viz-confidence-band').length,
              observations: plot.querySelectorAll('.bo-viz-observation').length,
              nextPoints: plot.querySelectorAll('.bo-viz-next').length,
              equation: equation.textContent.trim(),
              cardWidth: card.getBoundingClientRect().width,
              cardScrollWidth: card.scrollWidth,
            };
            """
        )
        if posterior_layout["svgCount"] != 1 or posterior_layout["confidenceBands"] < 1 or posterior_layout["nextPoints"] < 1:
            raise AssertionError(f"BO posterior plot contract missing: {posterior_layout}")
        if not posterior_layout["equation"]:
            raise AssertionError(f"BO objective equation did not render: {posterior_layout}")
        if posterior_layout["cardScrollWidth"] > posterior_layout["cardWidth"] + 2:
            raise AssertionError(f"BO posterior card overflow: {posterior_layout}")
        Select(driver.find_element(By.ID, "bo-posterior-view")).select_by_value("candidate_index")
        wait.until(lambda item: "Candidate pool index" in item.find_element(By.ID, "bo-posterior-plot").text)
        posterior_screenshot = out_dir / "bo_posterior_1920x1080.png"
        driver.find_element(By.ID, "bo-posterior-card").screenshot(str(posterior_screenshot))

        driver.set_window_size(390, 844)
        driver.execute_script("document.getElementById('bo-posterior-card').scrollIntoView({block: 'start'});")
        posterior_mobile = driver.execute_script(
            """
            const card = document.getElementById('bo-posterior-card');
            return {
              viewportWidth: window.innerWidth,
              bodyScrollWidth: document.body.scrollWidth,
              cardWidth: card.getBoundingClientRect().width,
              cardScrollWidth: card.scrollWidth,
              svgCount: card.querySelectorAll('svg.bo-viz-svg').length,
            };
            """
        )
        if posterior_mobile["bodyScrollWidth"] > posterior_mobile["viewportWidth"] + 2:
            raise AssertionError(f"BO posterior mobile page overflow: {posterior_mobile}")
        if posterior_mobile["cardScrollWidth"] > posterior_mobile["cardWidth"] + 2 or posterior_mobile["svgCount"] != 1:
            raise AssertionError(f"BO posterior mobile card invalid: {posterior_mobile}")
        posterior_mobile_screenshot = out_dir / "bo_posterior_390x844.png"
        driver.find_element(By.ID, "bo-posterior-card").screenshot(str(posterior_mobile_screenshot))
        driver.set_window_size(1920, 1080)

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
        driver.find_element(By.CSS_SELECTOR, '[data-agent-id="bo"]').click()
        wait.until(lambda item: "BO Agent" in item.find_element(By.ID, "live-center-title").text)
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, "[data-live-bo-posterior] svg.bo-viz-svg")) == 1)
        live_bo_layout = driver.execute_script(
            """
            const report = document.getElementById('live-report-panel');
            const equation = report.querySelector('[data-live-bo-equation]');
            const posterior = report.querySelector('[data-live-bo-posterior]');
            return {
              equation: equation?.textContent.trim() || '',
              svgCount: posterior?.querySelectorAll('svg.bo-viz-svg').length || 0,
              reportWidth: report.getBoundingClientRect().width,
              reportScrollWidth: report.scrollWidth,
            };
            """
        )
        if not live_bo_layout["equation"] or live_bo_layout["svgCount"] != 1:
            raise AssertionError(f"Live BO cards did not restore the latest projection: {live_bo_layout}")
        if live_bo_layout["reportScrollWidth"] > live_bo_layout["reportWidth"] + 2:
            raise AssertionError(f"Live BO report overflow: {live_bo_layout}")
        live_bo_screenshot = out_dir / "live_bo_posterior_1920x1080.png"
        driver.save_screenshot(str(live_bo_screenshot))
        return {
            "ok": True,
            "bo": bo_layout,
            "manual": manual_layout,
            "mobile": mobile_layout,
            "posterior": posterior_layout,
            "posterior_mobile": posterior_mobile,
            "live": live_layout,
            "live_bo": live_bo_layout,
            "screenshots": [
                bo_screenshot.as_posix(),
                manual_screenshot.as_posix(),
                mobile_screenshot.as_posix(),
                posterior_screenshot.as_posix(),
                posterior_mobile_screenshot.as_posix(),
                live_screenshot.as_posix(),
                live_bo_screenshot.as_posix(),
            ],
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
