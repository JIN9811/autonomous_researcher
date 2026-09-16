import pytest
from app.bootstrap import load_runtime
from orchestrator.state import Stage

pytestmark = pytest.mark.usefixtures("handoff_no_external")

@pytest.mark.asyncio
async def test_failed_result_with_evidence_never_reaches_printer_wait_or_vision(monkeypatch):
    controller = load_runtime()
    async def stage(_):
        controller._state.run_metadata["specimen_result"] = {
            "ok": False, "status": "blocked", "fabrication_report": {"wall": 0.289}}
    async def forbidden(*args, **kwargs):
        pytest.fail("Failed fabrication must not advance")
    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", stage)
    monkeypatch.setattr(controller, "_await_specimen_printer_completion_before_vision", forbidden)
    monkeypatch.setattr(controller, "_record_planning_orchestrator_transition", forbidden)
    with pytest.raises(RuntimeError, match="blocked"):
        await controller._run_planning_specimen_stage({"specimen_id": "failed"}, emit_handoff=False)
    assert controller._state.stage == Stage.SPECIMEN
