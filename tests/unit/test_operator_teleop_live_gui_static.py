from __future__ import annotations

from pathlib import Path


def test_live_gui_opens_each_pending_operator_teleop_handoff_once() -> None:
    script = Path("web/static/planning.js").read_text(encoding="utf-8")
    template = Path("web/templates/planning.html").read_text(encoding="utf-8")

    assert "function openPendingOperatorTeleopHandoff" in script
    assert 'metadata.pending_operator_teleop_handoff' in script
    assert 'handoff.status !== "pending_operator_teleop_handoff"' in script
    assert 'window.open(handoff.popup_url, "atr-operator-teleop-handoff"' in script
    assert "openedOperatorTeleopHandoffTokens.add(token)" in script
    assert "openPendingOperatorTeleopHandoff(metadata)" in script
    assert '/static/planning.js?v=20260904-teleop-handoff-1' in template
