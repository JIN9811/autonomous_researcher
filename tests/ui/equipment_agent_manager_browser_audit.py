#!/usr/bin/env python3
"""Browser audit for Equipment Agent Manager and its read-only projections."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.equipment_skill_runtime import EquipmentSkillRegistry  # noqa: E402


PROFILE_ID = "utm_windows_v1"
FLOW_PATH = ROOT / "graphs/modules/equipment/equipment_skill_flows.json"
SKILL_ROOT = ROOT / "memory/equipment_skills"


def _install_audit_skill() -> tuple[str, str, Path]:
    skill_id = f"agent_manager_audit_{uuid4().hex[:8]}"
    version = "0.0.1"
    registry = EquipmentSkillRegistry(SKILL_ROOT)
    recording = {
        "schema": "atr.equipment_recording.v1",
        "recording_id": f"recording-{skill_id}",
        "name": "Agent Manager Browser Audit",
        "status": "saved",
        "events": [{"kind": "wait", "seconds": 0.1}],
    }
    registry.create_draft(
        recording=recording,
        skill_id=skill_id,
        version=version,
        target_profile=PROFILE_ID,
        model_snapshot={"provider": "browser_audit", "model": "none"},
    )
    registry.compile(skill_id, version)
    registry.validate(skill_id, version)
    registry.mark_deployed(
        skill_id,
        version,
        bridge_id="browser_audit",
        deployment_sha256=hashlib.sha256(f"{skill_id}@{version}".encode()).hexdigest(),
    )
    return skill_id, version, SKILL_ROOT / skill_id


def _wait(driver: webdriver.Firefox, script: str, timeout: float = 20.0) -> Any:
    return WebDriverWait(driver, timeout).until(lambda item: item.execute_script(script))


def run_audit(base_url: str, out_dir: Path, *, width: int, height: int, geckodriver: str) -> dict[str, Any]:
    original_flow = FLOW_PATH.read_bytes() if FLOW_PATH.exists() else None
    skill_id = ""
    skill_dir: Path | None = None
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(executable_path=geckodriver), options=options)
    driver.set_window_size(width, height)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        skill_id, version, skill_dir = _install_audit_skill()
        manager_url = f"{base_url.rstrip('/')}/equipment/agent-manager?profile_id={PROFILE_ID}"
        driver.get(manager_url)
        _wait(driver, "return document.getElementById('equipment-manager-readiness')?.textContent !== 'loading';")
        _wait(driver, "return !document.getElementById('equipment-manager-add-skill')?.disabled;")
        driver.find_element("id", "equipment-manager-add-skill").click()
        _wait(driver, "return document.querySelectorAll('.equipment-manager-block:not(.is-placeholder)').length === 1;")
        blank_skill = driver.execute_script(
            "return document.querySelector('.equipment-manager-block [data-field=\"skill\"]')?.value || '';"
        )
        if blank_skill:
            raise AssertionError(f"New block unexpectedly auto-bound a Skill: {blank_skill}")
        driver.find_element("id", "equipment-manager-save").click()
        _wait(driver, "return document.getElementById('equipment-manager-readiness')?.textContent === 'unbound';")
        driver.refresh()
        reopened_blank = _wait(
            driver,
            """
            const field = document.querySelector('.equipment-manager-block [data-field="skill"]');
            return field ? {value: field.value} : null;
            """,
        )
        if reopened_blank["value"]:
            raise AssertionError(f"Unbound Skill Slot did not survive save/reopen: {reopened_blank}")
        expected_skill = f"{skill_id}@@{version}"
        driver.execute_script(
            """
            const block = document.querySelector('.equipment-manager-block:not(.is-placeholder)');
            const skill = block.querySelector('[data-field="skill"]');
            skill.value = arguments[0];
            skill.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            expected_skill,
        )
        driver.execute_script(
            """
            const block = document.querySelector('.equipment-manager-block:not(.is-placeholder)');
            const task = block.querySelector('[data-field="agentic.task"]');
            task.value = 'Audit Composite Task';
            task.dispatchEvent(new Event('change', {bubbles: true}));
            const current = document.querySelector('.equipment-manager-block:not(.is-placeholder)');
            const vision = current.querySelector('[data-field="vision.enabled"]');
            if (!vision.checked) vision.click();
            const rendered = document.querySelector('.equipment-manager-block:not(.is-placeholder)');
            const visionTask = rendered.querySelector('[data-field="vision.task_id"]');
            visionTask.value = 'utm_motion_confirm';
            visionTask.dispatchEvent(new Event('change', {bubbles: true}));
            """
        )
        driver.find_element("id", "equipment-manager-save").click()
        _wait(driver, "return document.getElementById('equipment-manager-readiness')?.textContent === 'saved';")
        manager_shot = out_dir / "equipment_agent_manager_browser_audit.png"
        driver.save_screenshot(str(manager_shot))

        driver.refresh()
        reopened = _wait(
            driver,
            """
            const block = document.querySelector('.equipment-manager-block:not(.is-placeholder)');
            if (!block) return null;
            return {
              count: document.querySelectorAll('.equipment-manager-block:not(.is-placeholder)').length,
              task: block.querySelector('[data-field="agentic.task"]')?.value || '',
              skill: block.querySelector('[data-field="skill"]')?.value || '',
              vision: Boolean(block.querySelector('[data-field="vision.enabled"]')?.checked),
              visionTask: block.querySelector('[data-field="vision.task_id"]')?.value || '',
              visionDetail: block.querySelector('[data-vision-task-detail]')?.innerText || block.querySelector('.equipment-manager-task-detail')?.innerText || '',
              standaloneVisionActions: document.querySelectorAll('[data-add-vision], #equipment-manager-add-vision').length,
            };
            """,
        )
        expected_reopened = {
            "count": 1,
            "task": "Audit Composite Task",
            "skill": expected_skill,
            "vision": True,
            "visionTask": "utm_motion_confirm",
            "standaloneVisionActions": 0,
        }
        if {key: reopened.get(key) for key in expected_reopened} != expected_reopened or "UTM Motion Confirmation" not in reopened.get("visionDetail", ""):
            raise AssertionError(f"Agent Manager did not reopen the saved composite block: {reopened}")

        driver.get(f"{base_url.rstrip('/')}/equipment/windows")
        _wait(driver, "return typeof loadEquipmentSkillFlow === 'function';")
        driver.execute_script("return loadEquipmentSkillFlow();")
        bridge = _wait(
            driver,
            """
            const host = document.getElementById('equipment-skill-flow-progress');
            if (!host || !host.innerText.includes('Audit Composite Task')) return null;
            return {
              text: host.innerText,
              manager: Boolean(document.getElementById('btn-open-equipment-agent-manager')),
              mutationControls: document.querySelectorAll('#btn-equipment-flow-add-skill, [data-flow-remove], [data-flow-move]').length,
            };
            """,
        )
        if not bridge["manager"] or bridge["mutationControls"] or "Vision" not in bridge["text"]:
            raise AssertionError(f"Equipment Bridge projection is not read-only or incomplete: {bridge}")
        bridge_shot = out_dir / "equipment_agent_manager_bridge_projection.png"
        driver.save_screenshot(str(bridge_shot))

        driver.get(f"{base_url.rstrip('/')}/ide")
        _wait(driver, "return typeof openModuleGraphTab === 'function';")
        driver.execute_script(
            """
            window.__equipmentAudit = {done: false, error: ''};
            Promise.resolve(openModuleGraphTab('equipment'))
              .then(() => { window.__equipmentAudit.done = true; })
              .catch((error) => {
                window.__equipmentAudit.error = String(error?.message || error);
                window.__equipmentAudit.done = true;
              });
            """
        )
        ide_state = _wait(driver, "return window.__equipmentAudit?.done ? window.__equipmentAudit : null;")
        if ide_state.get("error"):
            raise AssertionError(f"Runtime IDE Equipment projection failed to load: {ide_state['error']}")
        ide = _wait(
            driver,
            """
            const host = document.getElementById('ide-equipment-flow-editor');
            if (!host || !host.innerText.includes('Audit Composite Task')) return null;
            return {
              text: host.innerText,
              manager: Boolean(document.getElementById('ide-open-equipment-agent-manager')),
              mutationControls: document.querySelectorAll('#ide-equipment-flow-add-skill, [data-flow-remove], [data-flow-move]').length,
              graphNodes: document.querySelectorAll('[data-node-id]').length,
            };
            """,
        )
        if not ide["manager"] or ide["mutationControls"] or "Vision" not in ide["text"] or ide["graphNodes"] < 4:
            raise AssertionError(f"Runtime IDE projection is not read-only or incomplete: {ide}")
        ide_shot = out_dir / "equipment_agent_manager_runtime_projection.png"
        driver.save_screenshot(str(ide_shot))
        return {
            "ok": True,
            "skill": expected_skill,
            "manager": reopened,
            "bridge": bridge,
            "runtime_ide": ide,
            "screenshots": [str(manager_shot), str(bridge_shot), str(ide_shot)],
        }
    finally:
        driver.quit()
        if original_flow is None:
            FLOW_PATH.unlink(missing_ok=True)
        else:
            FLOW_PATH.write_bytes(original_flow)
        if skill_dir is not None:
            shutil.rmtree(skill_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--geckodriver", default="/snap/bin/geckodriver")
    args = parser.parse_args()
    result = run_audit(args.base_url, Path(args.out_dir), width=args.width, height=args.height, geckodriver=args.geckodriver)
    print("equipment_agent_manager_browser_audit: PASS")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
