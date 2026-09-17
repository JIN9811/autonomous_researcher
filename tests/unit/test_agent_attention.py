from types import SimpleNamespace

import pytest

from agents.attention import CHECKPOINTS, request_attention
from orchestrator.state import Mode, OrchestratorState, Stage


@pytest.mark.asyncio
async def test_checkpoint_scope_once_per_cycle_and_no_control_effects():
    events = []
    state = OrchestratorState(run_id="attention-test", experiment_id="test", mode=Mode.TEST, stage=Stage.DESIGN)
    ctx = SimpleNamespace(emit_execution_event=events.append)
    for owner, checkpoints in CHECKPOINTS.items():
        for checkpoint, action in checkpoints.items():
            assert await request_attention(state, ctx, owner, checkpoint)
            assert not await request_attention(state, ctx, owner, checkpoint)
            assert events[-1]["payload"]["view_action"] == action
            assert events[-1]["payload"]["presentation_only"] is True
    assert state.stage == Stage.DESIGN
    assert not await request_attention(state, ctx, "specimen", "printability")
    state.loop_count += 1
    assert await request_attention(state, ctx, "design", "handoff")
    state.stop_requested = True
    assert not await request_attention(state, ctx, "bo", "handoff")


@pytest.mark.asyncio
async def test_attention_failure_does_not_fail_agent_and_is_retryable():
    state = OrchestratorState(run_id="attention-test", experiment_id="test", mode=Mode.TEST)
    async def fail(event):
        raise RuntimeError("UI disconnected")
    assert not await request_attention(state, SimpleNamespace(emit_execution_event=fail), "bo", "handoff")
    events = []
    assert await request_attention(state, SimpleNamespace(emit_execution_event=events.append), "bo", "handoff")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_preflight_agent_calls_do_not_claim_handoff():
    from agents.design.agent import DesignAgent
    events = []
    state = OrchestratorState(run_id="attention-test", experiment_id="test", mode=Mode.TEST, stage=Stage.IDLE)
    ctx = SimpleNamespace(emit_execution_event=events.append)
    assert not await DesignAgent().request_attention(state, ctx, "handoff")
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,published,observed,expected", [
    ("PRINT_STARTED", True, "running", True),
    ("PRINT_STARTED", True, "completed", True),
    ("PRINT_STARTED", False, "running", False),
    ("COMMUNICATION_READY", True, "running", False),
    ("INSTALLED_PRINTER_COMMUNICATION_READY", False, "completed", False),
    ("TEST_PRINTER_EJECTION_PROJECT_STARTED", True, "running", False),
])
async def test_specimen_attention_requires_current_print_start(monkeypatch, status, published, observed, expected):
    from agents.specimen import agent as module
    response = {"ok": True, "bridge_result": {"status": status,
        "print_result": {"published": published, "post_publish_status": {"status": observed}}}}
    async def decide(state, ctx, specimen_id, evidence, execute):
        return {"status": "accepted"}, await execute()
    monkeypatch.setattr(module, "decide_specimen", decide)
    monkeypatch.setattr(module, "fabrication_evidence", lambda *args: {})
    events = []
    ctx = SimpleNamespace(tools=SimpleNamespace(call=lambda *args: response), emit_execution_event=events.append)
    state = OrchestratorState(run_id="current-print", experiment_id="test", mode=Mode.TEST, stage=Stage.SPECIMEN)
    prepared = {key: {} for key in ("spec", "candidate", "specimen_id", "printer_payload",
                                   "geometry_result", "mesh_result", "manufacturability_result")}
    prepared.update(evaluation_payload={"execution": {}}, printer_runtime_mode="live",
                    live_gui_test_spec=True, printer_test_path="actual_print")
    await module.SpecimenMakingAgent()._decide_fabrication(state, ctx, prepared)
    assert bool(events) is expected
