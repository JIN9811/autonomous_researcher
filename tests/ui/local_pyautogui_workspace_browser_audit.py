#!/usr/bin/env python3
"""Actuating browser audit for the localhost PyAutoGUI development target."""

from __future__ import annotations

import argparse
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


def run_audit(base_url: str, out_dir: Path, *, geckodriver: str) -> dict[str, object]:
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(1920, 1080)
    wait = WebDriverWait(driver, 30)
    try:
        driver.get(f"{base_url.rstrip('/')}/equipment/windows")
        wait.until(lambda item: "Ready" in item.find_element(By.ID, "equipment-local-bridge-status").text)

        select = driver.find_element(By.ID, "btn-equipment-local-select")
        if select.is_enabled():
            select.click()
        wait.until(lambda item: "selected" in item.find_element(By.ID, "equipment-local-bridge-detail").text)

        driver.execute_script("window.confirm = () => true;")
        driver.find_element(By.ID, "btn-equipment-program1").click()
        wait.until(lambda item: "program1 completed" in item.find_element(By.ID, "equipment-result-log").text)

        original_handles = set(driver.window_handles)
        driver.find_element(By.ID, "btn-equipment-open-bridge-gui").click()
        wait.until(lambda item: len(item.window_handles) > len(original_handles))
        new_handle = next(handle for handle in driver.window_handles if handle not in original_handles)
        driver.switch_to.window(new_handle)
        wait.until(lambda item: item.find_element(By.ID, "programManagerPanel"))
        wait.until(lambda item: len(item.find_elements(By.CSS_SELECTOR, ".program-card")) >= 5)

        out_dir.mkdir(parents=True, exist_ok=True)
        screenshot = out_dir / "local_pyautogui_workspace_full_path.png"
        driver.save_screenshot(str(screenshot))
        return {
            "ok": True,
            "selected": True,
            "program1_completed": True,
            "program_cards": len(driver.find_elements(By.CSS_SELECTOR, ".program-card")),
            "screenshot": str(screenshot),
        }
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7862")
    parser.add_argument("--out-dir", default="artifacts/ui/local_pyautogui_bridge/full_path")
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    args = parser.parse_args()
    result = run_audit(args.base_url, Path(args.out_dir), geckodriver=args.geckodriver)
    print("local_pyautogui_workspace_browser_audit: PASS")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
