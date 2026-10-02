"""Executable regressions for Live GUI decision-register classification."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING_JS = PROJECT_ROOT / "web" / "static" / "planning.js"


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"{name} helper is missing from planning.js"
    brace = source.find("{", start)
    assert brace >= 0
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{name} helper body is incomplete")


def test_recovery_warning_is_not_counted_as_a_blocked_decision() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helpers = "\n".join(
        _extract_function(source, name)
        for name in ("isBlockedDecisionEvent", "decisionRegisterCounts")
    )
    node = shutil.which("node")
    assert node, "node is required for planning.js decision-register tests"
    script = f"""
const liveApprovals = {{ pending: [], resolved: [], approvals: [] }};
{helpers}
const recovery = decisionRegisterCounts({{
  warnings: ["Emergency stop latch cleared"],
  decisionItems: [],
  state: {{ run_metadata: {{ orchestrator_decision_register: [] }} }},
  events: [
    {{
      event_type: "guardian_gate_decision",
      level: "WARNING",
      payload: {{ guardian_decision: {{ decision: "block" }} }},
    }},
    {{
      event_type: "run_emergency_resume",
      level: "WARNING",
      payload: {{ status: "resumed", control: "emergency_resume" }},
    }},
  ],
}});
const blocked = decisionRegisterCounts({{
  warnings: ["Guardian blocked unsafe action"],
  decisionItems: [],
  state: {{ run_metadata: {{ orchestrator_decision_register: [{{ decision: "block" }}] }} }},
  events: [{{
    event_type: "guardian_gate_decision",
    level: "WARNING",
    payload: {{ guardian_decision: {{ decision: "block" }} }},
  }}],
}});
console.log(JSON.stringify({{ recovery, blocked }}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    counts = json.loads(result.stdout)

    assert counts["recovery"]["blocked"] == 0
    assert counts["recovery"]["info"] == 2
    assert counts["blocked"]["blocked"] == 1
    assert counts["blocked"]["info"] == 0


def test_historical_guardian_event_does_not_restore_active_block_verdict() -> None:
    source = PLANNING_JS.read_text(encoding="utf-8")
    helpers = "\n".join(
        _extract_function(source, name)
        for name in ("orchestratorLatestObject", "orchestratorPrimaryDecision")
    )
    node = shutil.which("node")
    assert node, "node is required for planning.js decision-register tests"
    script = f"""
const latestReportPayload = () => ({{ decision: "block", reason_code: "OLD_EVENT" }});
{helpers}
const result = orchestratorPrimaryDecision({{
  metadata: {{}},
  controlPlane: {{}},
  decisions: [],
  handoffs: [{{ next_action: "block" }}],
}}, {{
  events: [{{ payload: {{ guardian_decision: {{ decision: "block" }} }} }}],
}});
console.log(JSON.stringify(result));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    primary = json.loads(result.stdout)

    assert primary["decision"] == ""
    assert primary["latestDecision"] == {}
