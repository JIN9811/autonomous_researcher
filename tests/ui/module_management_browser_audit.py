#!/usr/bin/env python3
"""Browser-level Module Management Tool audit.

Verifies that /module-management renders the real module catalog, selected module
configuration workspace, designer controls, and validate/dry-run actions in a
headless browser.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from runtime_ide_browser_audit import WebDriverAudit  # noqa: E402


def scenario_module_management(audit: WebDriverAudit, base_url: str, out_dir: Path) -> dict[str, Any]:
    audit.open(f"{base_url.rstrip('/')}/module-management", wait_s=2.5)
    audit.js("document.querySelector('[data-module-id=\"design\"]')?.click(); return true;")
    time.sleep(0.5)
    # Keep browser probes intentionally small. geckodriver can return an opaque
    # 500 when a large script returns nested DOM-derived objects.
    state = {
        "status": audit.js("return document.querySelector('#mm-status-label')?.innerText || '';"),
        "detail": audit.js("return document.querySelector('#mm-status-detail')?.innerText || '';"),
        "itemIds": audit.js("return Array.from(document.querySelectorAll('[data-module-id]')).map((el) => el.getAttribute('data-module-id'));"),
        "itemText": audit.js("return Array.from(document.querySelectorAll('[data-module-id]')).map((el) => el.innerText).join('\\n');"),
        "selected": audit.js("return document.querySelector('.module-management-item.active')?.getAttribute('data-module-id') || '';"),
        "configOptions": audit.js("return Array.from(document.querySelector('#mm-config-module-select')?.options || []).map((opt) => opt.value);"),
        "handlerOptions": audit.js("return Array.from(document.querySelector('#mm-designer-handler')?.options || []).map((opt) => opt.value);"),
        "summary": audit.js("return document.querySelector('#mm-config-summary')?.innerText || '';"),
        "summaryBox": audit.js("const r=document.querySelector('#mm-config-summary')?.getBoundingClientRect(); return r ? {w:r.width,h:r.height} : {w:0,h:0};"),
        "configGridColumns": audit.js("const el=document.querySelector('.module-management-config-grid'); return el ? getComputedStyle(el).gridTemplateColumns : '';"),
        "stepCount": audit.js("return document.querySelectorAll('#mm-config-steps .runtime-module-step, #mm-config-steps [data-mm-module-step-index]').length;"),
        "rawJsonPrefix": audit.js("return (document.querySelector('#mm-config-json')?.value || '').slice(0, 260);"),
        "hasDesigner": audit.js("return Boolean(document.querySelector('#mm-create-btn') && document.querySelector('#mm-designer-python-file'));"),
        "hasConfigActions": audit.js("return Boolean(document.querySelector('#mm-config-apply-btn') && document.querySelector('#mm-config-validate-btn') && document.querySelector('#mm-config-dry-run-btn') && document.querySelector('#mm-save-config-btn'));"),
        "hasRegisterGenerated": audit.js("return Boolean(document.querySelector('#mm-register-generated-btn'));"),
    }
    state["itemCount"] = len(state.get("itemIds") or [])

    failures: list[str] = []
    if state.get("status") != "Ready":
        failures.append(f"status is not Ready: {state.get('status')} / {state.get('detail')}")
    if state.get("itemCount", 0) < 8:
        failures.append(f"module catalog too small: {state.get('itemCount')}")
    for module_id in ["design", "specimen", "analysis", "bo", "guardian"]:
        if module_id not in state.get("itemIds", []):
            failures.append(f"module missing from catalog: {module_id}")
        if module_id not in state.get("configOptions", []):
            failures.append(f"module missing from config selector: {module_id}")
    if "runtime.step_complete" not in state.get("handlerOptions", []):
        failures.append("runtime.step_complete missing from designer handler options")
    if "agent.design_agent" not in state.get("handlerOptions", []):
        failures.append("agent.design_agent missing from designer handler options")
    if "module.generated_adapter" not in state.get("handlerOptions", []):
        failures.append("module.generated_adapter missing from designer handler options")
    if not state.get("hasDesigner"):
        failures.append("Module Designer controls missing")
    if not state.get("hasConfigActions"):
        failures.append("Module config action buttons missing")
    if not state.get("hasRegisterGenerated"):
        failures.append("Register Generated button missing")
    if "Design Agent Module" not in state.get("summary", "") and "design" not in state.get("rawJsonPrefix", ""):
        failures.append("selected module summary/raw JSON missing design module evidence")
    summary_box = state.get("summaryBox") or {}
    if float(summary_box.get("w") or 0) < 900 or float(summary_box.get("h") or 0) < 420:
        failures.append(f"module config summary is too small: {summary_box}")
    if " " in str(state.get("configGridColumns") or "").strip():
        failures.append(f"module config workspace should be single-column, got: {state.get('configGridColumns')}")
    if state.get("stepCount", 0) < 1:
        failures.append("module runtime steps did not render")

    validate_click = audit.js(
        """
        const btn = document.querySelector('#mm-config-validate-btn');
        if (!btn) return {ok:false, error:'validate button missing'};
        btn.click();
        return {ok:true};
        """
    )
    time.sleep(0.8)
    validate = audit.js(
        """
        return {
          ok: true,
          clickOk: arguments[0].ok,
          clickError: arguments[0].error || '',
          status: document.querySelector('#mm-config-status')?.innerText || '',
          action: document.querySelector('#mm-action-output')?.innerText || '',
        };
        """,
        [validate_click],
    )
    if not validate.get("ok") or "validate OK" not in validate.get("status", ""):
        failures.append(f"validate action did not report OK: {validate}")

    dry_run_click = audit.js(
        """
        const btn = document.querySelector('#mm-config-dry-run-btn');
        if (!btn) return {ok:false, error:'dry-run button missing'};
        btn.click();
        return {ok:true};
        """
    )
    time.sleep(0.8)
    dry_run = audit.js(
        """
        return {
          ok: true,
          clickOk: arguments[0].ok,
          clickError: arguments[0].error || '',
          status: document.querySelector('#mm-config-status')?.innerText || '',
          action: document.querySelector('#mm-action-output')?.innerText || '',
          evidence: document.querySelector('#mm-dry-run-evidence')?.innerText || '',
        };
        """,
        [dry_run_click],
    )
    if not dry_run.get("ok") or "dry-run OK" not in dry_run.get("status", ""):
        failures.append(f"dry-run action did not report OK: {dry_run}")
    if "steps=" not in dry_run.get("action", "") and "Step" not in dry_run.get("evidence", ""):
        failures.append(f"dry-run evidence missing step summary: {dry_run}")

    if failures:
        audit.screenshot(out_dir / "module_management_browser_audit_failure.png")
        raise AssertionError("; ".join(failures))
    audit.screenshot(out_dir / "module_management_browser_audit.png")
    return {"initial": state, "validate": validate, "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4448")
    parser.add_argument("--out-dir", default="artifacts/ui")
    parser.add_argument("--width", type=int, default=1500)
    parser.add_argument("--height", type=int, default=1100)
    args = parser.parse_args()

    audit = WebDriverAudit(args.webdriver_url, width=args.width, height=args.height)
    try:
        audit.start()
        result = scenario_module_management(audit, args.base_url, Path(args.out_dir))
        print("module_management_browser_audit: PASS")
        print({"modules": result["initial"].get("itemCount"), "selected": result["initial"].get("selected"), "validate": result["validate"].get("status"), "dry_run": result["dry_run"].get("status")})
        return 0
    finally:
        time.sleep(0.1)
        audit.stop()


if __name__ == "__main__":
    raise SystemExit(main())
