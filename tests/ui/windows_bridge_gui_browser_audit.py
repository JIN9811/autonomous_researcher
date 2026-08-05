#!/usr/bin/env python3
"""Non-actuating browser audit for the complete Windows bridge console."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


REQUIRED_IDS = (
    "essentialConsole",
    "token",
    "health",
    "refreshAll",
    "clearToken",
    "essentialBridgeState",
    "essentialPyAutoGUI",
    "essentialResult",
    "essentialProgramManagerSlot",
    "advancedToolsPanel",
    "connectionPanel",
    "token",
    "health",
    "authPill",
    "programManagerPanel",
    "managerProgramRegistry",
    "refreshPrograms",
    "managerSearch",
    "managerFilter",
    "managerStats",
    "newProgram",
    "browseProgram",
    "downloadProgramTemplate",
    "programFile",
    "programEditor",
    "programForm",
    "programDefinition",
    "validateProgram",
    "registerProgram",
    "managerLatestResult",
    "safePreflight",
    "utmSim",
    "utmLive",
    "utmAbort",
    "screenshot",
    "captureLocator",
    "artifacts",
    "requestLog",
    "execute",
    "timelineTrack",
)


def wait_for_bridge_gui(driver: webdriver.Firefox) -> None:
    WebDriverWait(driver, 20).until(
        lambda item: item.execute_script("return Boolean(document.getElementById('programManagerPanel'))")
    )


def run_audit(
    base_url: str,
    out_dir: Path,
    *,
    width: int,
    height: int,
    geckodriver: str,
    token: str = "",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    import_definition = out_dir / "browser_audit_program.json"
    import_definition.write_text(
        '{"schema":"atr.pyautogui_program.v1","program_id":"browser_audit_macro","name":"Browser Audit Program","description":"Imported by Selenium audit","enabled":true,"program_type":"macro","safe_test":true,"sequence":[{"action":"log","message":"browser audit"}]}',
        encoding="utf-8",
    )
    options = Options()
    options.add_argument("-headless")
    service = Service(executable_path=geckodriver)
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(width, height)
    try:
        root = base_url.rstrip("/") + "/"
        driver.get(root)
        wait_for_bridge_gui(driver)
        if token:
            driver.execute_script("localStorage.setItem('bridgeToken', arguments[0]);", token)
            driver.refresh()
            wait_for_bridge_gui(driver)
            WebDriverWait(driver, 20).until(
                lambda item: "reachable" in item.find_element("id", "authPill").text
                or "check failed" in item.find_element("id", "authPill").text
            )

            builtin_selector = '#managerProgramRegistry [data-manager-program-id="program1"]'
            builtin = driver.find_element(By.CSS_SELECTOR, builtin_selector)
            builtin.find_element(By.CSS_SELECTOR, '[data-manager-action="edit"]').click()
            WebDriverWait(driver, 20).until(
                lambda item: '"program_id": "program1"' in item.find_element(By.ID, "programDefinition").get_attribute("value")
            )
            assert driver.find_element(By.ID, "programDefinition").get_attribute("readonly")
            assert not driver.find_element(By.ID, "registerProgram").is_enabled()
            assert not driver.find_element(By.CSS_SELECTOR, builtin_selector).find_element(By.CSS_SELECTOR, '[data-manager-action="toggle"]').is_enabled()
            driver.find_element(By.CSS_SELECTOR, builtin_selector).find_element(By.CSS_SELECTOR, '[data-manager-action="revalidate"]').click()
            WebDriverWait(driver, 20).until(lambda item: "BUILT-IN" in item.find_element(By.CSS_SELECTOR, builtin_selector).text)
            assert not driver.find_element(By.CSS_SELECTOR, builtin_selector).find_element(By.CSS_SELECTOR, '[data-manager-action="delete"]').is_enabled()

            audit_program_id = "browser_audit_macro"
            driver.find_element(By.ID, "programFile").send_keys(str(import_definition.resolve()))
            WebDriverWait(driver, 20).until(
                lambda item: audit_program_id in item.find_element(By.ID, "programDefinition").get_attribute("value")
            )
            card_selector = f'#managerProgramRegistry [data-manager-program-id="{audit_program_id}"]'
            assert not driver.find_elements(By.CSS_SELECTOR, card_selector), "Browse must not register the macro"
            driver.find_element(By.ID, "validateProgram").click()
            WebDriverWait(driver, 20).until(
                lambda item: '"status": "valid"'
                in (item.find_element(By.ID, "managerLatestResult").get_attribute("textContent") or "")
            )
            driver.find_element(By.ID, "registerProgram").click()
            WebDriverWait(driver, 20).until(lambda item: item.find_element(By.CSS_SELECTOR, card_selector))
            card = driver.find_element(By.CSS_SELECTOR, card_selector)
            WebDriverWait(driver, 20).until(lambda _item: "CUSTOM" in card.text and "ENABLED" in card.text)
            assert card.find_element(By.CSS_SELECTOR, '[data-manager-action="run"]').is_enabled()
            driver.find_element(By.CSS_SELECTOR, card_selector).find_element(By.CSS_SELECTOR, '[data-manager-action="delete"]').click()
            WebDriverWait(driver, 20).until(
                lambda item: len(item.find_elements(By.CSS_SELECTOR, card_selector)) == 0
            )

        result = driver.execute_script(
            """
            const requiredIds = arguments[0];
            const missingIds = requiredIds.filter((id) => !document.getElementById(id));
            const doc = document.documentElement;
            const text = document.body ? (document.body.innerText || document.body.textContent || '') : '';
            const panels = Array.from(document.querySelectorAll('.panel')).map((item) => {
              const rect = item.getBoundingClientRect();
              return {id: item.id, width: rect.width, height: rect.height};
            });
            const buttons = Array.from(document.querySelectorAll('button')).filter((item) => {
              const style = window.getComputedStyle(item);
              const rect = item.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            }).map((item) => {
              const rect = item.getBoundingClientRect();
              return {id: item.id, text: item.textContent || '', width: rect.width, height: rect.height};
            });
            return {
              title: document.title,
              text,
              missingIds,
              panels,
              buttons,
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              viewport: {width: window.innerWidth, height: window.innerHeight},
              programCards: document.querySelectorAll('.program-card').length,
              completeOperatorConsole: Boolean(document.getElementById('utmLive')),
              advancedOpen: document.getElementById('advancedToolsPanel')?.open === true,
              managerInEssentialSurface: document.getElementById('programManagerPanel')?.parentElement?.id === 'essentialProgramManagerSlot',
              managerStats: document.getElementById('managerStats')?.textContent || '',
              deviceBridgeShell: document.body?.classList.contains('device-bridge-shell') || false,
              shellStyle: {
                headerRadius: parseFloat(window.getComputedStyle(document.querySelector('header')).borderRadius) || 0,
                cardRadius: parseFloat(window.getComputedStyle(document.querySelector('.essential-card')).borderRadius) || 0,
                healthBackground: window.getComputedStyle(document.getElementById('health')).backgroundColor,
                bodyBackground: window.getComputedStyle(document.body).backgroundImage,
              },
            };
            """,
            list(REQUIRED_IDS),
        )
        missing_text = [
            item
            for item in ("ATR Windows PyAutoGUI Bridge", "Bridge Connection", "Program Manager", "Browse JSON", "Download Template", "Program Manager Result")
            if item not in result.get("text", "")
        ]
        if result.get("missingIds"):
            raise AssertionError(f"Missing complete console elements: {result['missingIds']}")
        if missing_text:
            raise AssertionError(f"Missing complete console text: {missing_text}")
        if not result.get("completeOperatorConsole"):
            raise AssertionError("UTM operator controls are missing from the bridge root")
        if result.get("advancedOpen"):
            raise AssertionError("Advanced Tools must be closed by default")
        if not result.get("managerInEssentialSurface"):
            raise AssertionError("Program Manager is not attached to the essential operator surface")
        if not result.get("deviceBridgeShell"):
            raise AssertionError("Windows bridge root is not using the Device Bridge shell theme")
        shell_style = result.get("shellStyle") or {}
        if shell_style.get("headerRadius", 0) < 18 or shell_style.get("cardRadius", 0) < 18:
            raise AssertionError(f"Windows bridge shell cards do not match Device Bridge geometry: {shell_style}")
        if "rgb(13, 118, 97)" in shell_style.get("healthBackground", ""):
            raise AssertionError(f"Legacy green console action style remains: {shell_style}")
        if "radial-gradient" not in shell_style.get("bodyBackground", ""):
            raise AssertionError(f"Device Bridge page atmosphere is missing: {shell_style}")
        if result.get("scrollWidth", 0) > result.get("clientWidth", 0) + 16:
            raise AssertionError(f"Console horizontally overflows viewport: {result}")
        undersized = [
            item for item in result.get("buttons", []) if item.get("width", 0) < 40 or item.get("height", 0) < 26
        ]
        if undersized:
            raise AssertionError(f"Console buttons are too small: {undersized}")
        if width >= 1200:
            connection_buttons = [
                item for item in result.get("buttons", []) if item.get("id") in {"health", "refreshAll", "clearToken"}
            ]
            unreadable_connection_buttons = [
                item
                for item in connection_buttons
                if item.get("width", 0) < 70 or item.get("height", 0) > 64
            ]
            if unreadable_connection_buttons:
                raise AssertionError(
                    f"Bridge Connection actions are not readable at desktop width: {unreadable_connection_buttons}"
                )
        if token and result.get("programCards", 0) < 1:
            raise AssertionError("Authenticated console did not render built-in program cards")

        driver.execute_script("window.scrollTo(0, 0);")
        WebDriverWait(driver, 5).until(lambda item: item.execute_script("return window.scrollY") == 0)
        screenshot = out_dir / "windows_bridge_gui_browser_audit.png"
        driver.save_screenshot(str(screenshot))
        result["screenshot"] = str(screenshot)

        advanced_result = driver.execute_script(
            """
            const panel = document.getElementById('advancedToolsPanel');
            panel.open = true;
            panel.scrollIntoView({block: 'start'});
            const selectors = [
              'button',
              '.section-intro',
              '.hint',
              '.operator-compact-note',
              '.identity-pill',
              '.runbook-step small',
              '.next-action-button span',
              '.control-rail button small',
              '.ops-card span',
              '.proof-gate span',
              '.command-banner span'
            ];
            const nodes = Array.from(panel.querySelectorAll(selectors.join(',')));
            const visible = nodes.filter((item) => {
              const style = window.getComputedStyle(item);
              const rect = item.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            });
            const clipped = visible.filter((item) => {
              const style = window.getComputedStyle(item);
              const horizontalOverflow = item.scrollWidth > item.clientWidth + 2;
              const masksOverflow = ['hidden', 'clip'].includes(style.overflowX)
                || ['hidden', 'clip'].includes(style.overflow)
                || style.whiteSpace === 'nowrap';
              return horizontalOverflow && masksOverflow;
            }).map((item) => ({
              id: item.id || '',
              className: item.className || '',
              text: (item.textContent || '').trim().slice(0, 180),
              clientWidth: item.clientWidth,
              scrollWidth: item.scrollWidth,
              whiteSpace: window.getComputedStyle(item).whiteSpace,
              overflowX: window.getComputedStyle(item).overflowX,
            }));
            return {
              open: panel.open,
              clipped,
              scrollWidth: document.documentElement.scrollWidth,
              clientWidth: document.documentElement.clientWidth,
              panelWidth: panel.getBoundingClientRect().width,
              commandCopyWidth: panel.querySelector('.command-banner > div')?.getBoundingClientRect().width || 0,
              commandPosition: window.getComputedStyle(panel.querySelector('.command-shell')).position,
            };
            """
        )
        if not advanced_result.get("open"):
            raise AssertionError("Advanced Tools did not open for layout audit")
        if advanced_result.get("scrollWidth", 0) > advanced_result.get("clientWidth", 0) + 16:
            raise AssertionError(f"Advanced Tools horizontally overflows viewport: {advanced_result}")
        if advanced_result.get("clipped"):
            raise AssertionError(f"Advanced Tools clips operational text: {advanced_result['clipped']}")
        if width >= 1200 and advanced_result.get("commandCopyWidth", 0) < 220:
            raise AssertionError(f"Advanced command copy is too narrow to read: {advanced_result}")
        if advanced_result.get("commandPosition") != "static":
            raise AssertionError(
                f"Advanced command guidance must remain in document flow: {advanced_result}"
            )
        driver.execute_script(
            "document.getElementById('advancedToolsPanel').scrollIntoView({block: 'start', behavior: 'instant'});"
        )
        WebDriverWait(driver, 5).until(lambda item: item.execute_script("return window.scrollY") > 0)
        advanced_screenshot = out_dir / f"windows_bridge_gui_advanced_{width}x{height}.png"
        driver.save_screenshot(str(advanced_screenshot))
        result["advanced"] = advanced_result
        result["advanced_screenshot"] = str(advanced_screenshot)
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
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    result = run_audit(
        args.base_url,
        Path(args.out_dir),
        width=args.width,
        height=args.height,
        geckodriver=args.geckodriver,
        token=args.token,
    )
    print("windows_bridge_gui_browser_audit: PASS")
    print({key: value for key, value in result.items() if key != "text"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
