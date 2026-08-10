"""Contract tests for shared BO visualization cards in Live GUI."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING_JS = PROJECT_ROOT / "web" / "static" / "planning.js"


def _inspect_source() -> dict[str, object]:
    node = shutil.which("node")
    assert node, "node is required for Live GUI BO source-contract tests"
    script = f"""
const fs = require("fs");
const source = fs.readFileSync({json.dumps(str(PLANNING_JS))}, "utf8");
const start = source.indexOf("function renderBoDashboardCards");
const end = source.indexOf("function renderGuardianDashboardCards", start);
const body = source.slice(start, end);
console.log(JSON.stringify({{
  sharedEquation: body.includes("BOVisualization.renderEquationCard"),
  sharedPlot: body.includes("BOVisualization.renderPlot"),
  waiting: body.includes("Waiting for a completed BO step"),
  equationBeforeRanking: body.indexOf("BO Objective Equation") >= 0 && body.indexOf("BO Objective Equation") < body.indexOf("Candidate Ranking"),
  posteriorBeforeRanking: body.indexOf("Live Posterior") >= 0 && body.indexOf("Live Posterior") < body.indexOf("Candidate Ranking"),
  duplicateTrace: body.includes("renderBoTraceSvg"),
  restoresMetadata: source.includes("metadata.bo_visualization"),
}}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_live_gui_bo_dashboard_uses_shared_equation_and_posterior_renderer() -> None:
    assert _inspect_source() == {
        "sharedEquation": True,
        "sharedPlot": True,
        "waiting": True,
        "equationBeforeRanking": True,
        "posteriorBeforeRanking": True,
        "duplicateTrace": False,
        "restoresMetadata": True,
    }
