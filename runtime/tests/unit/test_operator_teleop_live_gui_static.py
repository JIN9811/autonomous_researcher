from __future__ import annotations

from pathlib import Path
import subprocess
from test_planning_design_report_js import _extract_function


def test_live_gui_opens_each_pending_operator_teleop_handoff_once() -> None:
    script = Path("web/static/planning.js").read_text(encoding="utf-8")
    program = """
const assert = require('node:assert/strict');
const openedOperatorTeleopHandoffTokens = new Set();
const popups = [], statuses = [];
const window = {open: (...args) => {popups.push(args); return {};}};
const setChatStatus = (...args) => statuses.push(args);
""" + _extract_function(script, "openPendingOperatorTeleopHandoff") + """
const metadata = {pending_operator_teleop_handoff: {
  status: 'pending_operator_teleop_handoff', handoff_token: 'one', popup_url: '/lerobot?handoff=one'
}};
assert.equal(openPendingOperatorTeleopHandoff({}), false);
assert.equal(openPendingOperatorTeleopHandoff(metadata), true);
assert.equal(openPendingOperatorTeleopHandoff(metadata), false);
assert.equal(popups.length, 1);
assert.deepEqual(popups[0].slice(0, 2), ['/lerobot?handoff=one', 'atr-operator-teleop-handoff']);
metadata.pending_operator_teleop_handoff.handoff_token = 'two';
metadata.pending_operator_teleop_handoff.status = 'completed';
assert.equal(openPendingOperatorTeleopHandoff(metadata), false);
metadata.pending_operator_teleop_handoff.status = 'pending_operator_teleop_handoff';
assert.equal(openPendingOperatorTeleopHandoff(metadata), true);
assert.equal(popups.length, 2);
"""
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
