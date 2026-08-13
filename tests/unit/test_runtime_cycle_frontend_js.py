"""Runtime cycle labels must follow the backend cycle contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml

from orchestrator.runtime_defaults import TEST_MODE_LOOP_CYCLES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_CYCLE_JS = PROJECT_ROOT / "web" / "static" / "runtime_cycle.js"


def test_runtime_cycle_budget_comes_from_test_mode_config() -> None:
    raw = yaml.safe_load((PROJECT_ROOT / "configs" / "test_modes.yaml").read_text(encoding="utf-8"))
    assert TEST_MODE_LOOP_CYCLES == raw["test_modes"]["dry_run"]["max_cycles"]


def test_runtime_cycle_formatter_uses_contract_without_fixed_denominator() -> None:
    node = shutil.which("node")
    assert node, "node is required for runtime cycle frontend tests"
    script = f"""
global.window = global;
require({json.dumps(str(RUNTIME_CYCLE_JS))});
const state = {{
  mode: "test",
  stage: "design",
  loop_count: 6,
  run_metadata: {{
    planning_cycle_contract: {{ total_cycles: 20 }}
  }}
}};
console.log(JSON.stringify({{
  planning: ATRRuntimeCycle.format(state, true, {{ prefix: "Cycle " }}),
  compact: ATRRuntimeCycle.format(state, true, {{ prefix: "C:" }}),
  total: ATRRuntimeCycle.total(state),
  live: ATRRuntimeCycle.format({{
    mode: "live",
    stage: "design",
    loop_count: 6,
    run_metadata: {{ planning_cycle_contract: {{ mode: "live", total_cycles: 1 }} }}
  }}, true, {{ prefix: "Cycle " }}),
  unbounded: ATRRuntimeCycle.format({{
    mode: "test",
    stage: "idle",
    loop_count: 0,
    run_metadata: {{ latest_mission_contract: {{ safety_budget: {{ max_loop_count: 1 }} }} }}
  }}, false, {{ prefix: "C:" }})
}}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {
        "planning": "Cycle 7/20",
        "compact": "C:7/20",
        "total": 20,
        "live": "Cycle 7",
        "unbounded": "C:0",
    }


def test_all_runtime_surfaces_load_shared_cycle_formatter_before_page_script() -> None:
    pairs = {
        "web/templates/index.html": "/static/app.js",
        "web/templates/runtime_ide.html": "/static/runtime_ide.js",
        "web/templates/planning.html": "/static/planning.js",
    }
    for relative_path, page_script in pairs.items():
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "/static/runtime_cycle.js" in text
        assert text.index('<script src="/static/runtime_cycle.js') < text.index(f'<script src="{page_script}')


def test_runtime_surface_formatters_have_no_fixed_five_cycle_label() -> None:
    for relative_path in (
        "web/static/app.js",
        "web/static/runtime_ide.js",
        "web/static/planning.js",
    ):
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "ATRRuntimeCycle.format" in text
        assert "/5`" not in text
