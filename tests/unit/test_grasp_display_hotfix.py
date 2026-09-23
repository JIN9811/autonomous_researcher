from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_grasp_display_hotfix_leaves_live_workflow_untouched(monkeypatch):
    from app import safe_hot_reload
    from utils import lerobot_joint_telemetry as telemetry
    from utils import monitor_process

    monkeypatch.setattr(telemetry, "GRASP_CONTACT_GAP_THRESHOLD", 2.0)
    monkeypatch.setattr(telemetry, "GRASP_OUTCOME_RULE_VERSION", "absolute_contact_gap_v3")
    closed = []
    worker = SimpleNamespace(close=lambda: closed.append("robot"))
    monkeypatch.setattr(monitor_process, "existing_monitor_process", lambda kind: worker if kind == "robot" else None)
    state = {"run_id": "active-run", "stage": "manipulation", "is_running": True}
    controller = SimpleNamespace(_state=state, _emit_control_event=AsyncMock())
    result = await safe_hot_reload.reload_equipment_support(controller)
    assert result["scope"] == "grasp_display_only"
    assert result["contact_gap_threshold"] == 1.2
    assert result["actuation_performed"] is False
    assert closed == ["robot"]
    assert controller._state is state
    assert state == {"run_id": "active-run", "stage": "manipulation", "is_running": True}
    latch = telemetry._GraspOutcomeLatch()
    telemetry._finalize_grasp_outcome(latch, {"actual_source": {"Gripper": 53.84615384615385},
        "target_source": {"Gripper": 52.41880798339844}})
    assert latch.current["status"] == "success"
    assert latch.current["observation_only"] is True


@pytest.mark.asyncio
async def test_grasp_hotfix_rejects_unapproved_source_without_mutation(monkeypatch, tmp_path):
    from app.safe_hot_reload import reload_grasp_display_threshold
    from utils import lerobot_joint_telemetry as telemetry
    source = tmp_path / "telemetry.py"
    source.write_text('GRASP_CONTACT_GAP_THRESHOLD = 0.0\nGRASP_OUTCOME_RULE_VERSION = "absolute_contact_gap_v4"\n')
    monkeypatch.setattr(telemetry, "__file__", str(source))
    monkeypatch.setattr(telemetry, "GRASP_CONTACT_GAP_THRESHOLD", 2.0)
    monkeypatch.setattr(telemetry, "GRASP_OUTCOME_RULE_VERSION", "absolute_contact_gap_v3")
    with pytest.raises(ValueError, match="approved constants"):
        await reload_grasp_display_threshold(object())
    assert telemetry.GRASP_CONTACT_GAP_THRESHOLD == 2.0
    assert telemetry.GRASP_OUTCOME_RULE_VERSION == "absolute_contact_gap_v3"
