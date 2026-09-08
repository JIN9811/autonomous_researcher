"""Bounded model decisions must not acquire printer authority."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.specimen_decision import decide_specimen, fabrication_evidence
from orchestrator.state import Mode, OrchestratorState


def request(tool="execute_fabrication", arguments=None, refs=None):
    return json.dumps({"tool": tool, "arguments": arguments if arguments is not None else {"specimen_id": "s1"},
                       "reason": "Manufacturing checks passed for the requested specimen.",
                       "evidence_refs": refs or ["context:request", "manufacturability:checks"]})


def setup(responses, *, mode=Mode.LIVE):
    state = OrchestratorState(run_id="decision-test", experiment_id="non-actuating", mode=mode,
                              current_experiment_spec={"specimen_id": "s1", "candidate_id": "c1"})
    ctx = SimpleNamespace(force_real_llm_in_test=True,
                          complete=AsyncMock(side_effect=[SimpleNamespace(text=r, model="test-model", raw={}) for r in responses]))
    evidence = {"context:request": {"specimen_id": "s1"},
                "manufacturability:checks": {"status": "pass"}}
    execute = AsyncMock(return_value={"ok": True, "status": "prepared"})
    return state, ctx, evidence, execute


@pytest.mark.asyncio
async def test_model_tool_dispatch_executes_existing_callback_once():
    state, ctx, evidence, execute = setup([request()])
    decision, response = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "executed"
    assert decision["llm_used"] is True
    assert response == {"ok": True, "status": "prepared"}
    execute.assert_awaited_once_with()
    assert ctx.complete.call_args.args[0] == "specimen_reasoning"


@pytest.mark.asyncio
async def test_inspect_then_execute_and_return_without_effect():
    state, ctx, evidence, execute = setup([
        request("inspect_fabrication_evidence", {"evidence_ref": "manufacturability:checks"}), request()])
    decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["trace"][0]["result"] == {"status": "pass"}
    assert ctx.complete.await_count == 2
    execute.assert_awaited_once()
    state, ctx, evidence, execute = setup([request("return_to_owner", {})])
    decision, response = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "returned" and response is None
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["not json", request("printer.prepare"),
    request(arguments={"specimen_id": "s1", "allow_physical": True}),
    request(arguments={"specimen_id": "another"}), request(refs=["invented:evidence"]),
    request("inspect_fabrication_evidence", {"evidence_ref": "connection:secret"})])
async def test_invalid_call_never_executes(reply):
    state, ctx, evidence, execute = setup([reply])
    decision, response = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "failed" and response is None
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["stop_requested", "safe_stop_requested", "emergency_stop_requested"])
async def test_stop_received_during_reasoning_prevents_execution(flag):
    state, ctx, evidence, execute = setup([])
    async def complete(*args, **kwargs):
        setattr(state, flag, True)
        return SimpleNamespace(text=request(), raw={})
    ctx.complete = complete
    decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "failed"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_spec_changed_during_reasoning_prevents_execution():
    state, ctx, evidence, execute = setup([])
    async def complete(*args, **kwargs):
        state.current_experiment_spec["specimen_id"] = "changed"
        return SimpleNamespace(text=request(), raw={})
    ctx.complete = complete
    decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "failed"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mode_changed_during_reasoning_prevents_stale_live_payload():
    state, ctx, evidence, execute = setup([])
    async def complete(*args, **kwargs):
        state.mode = Mode.REPLAY
        return SimpleNamespace(text=request(), raw={})
    ctx.complete = complete
    decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["status"] == "failed"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_timeout_mock_and_budget_do_not_fallback_to_execution():
    for kind in ("timeout", "mock", "budget"):
        state, ctx, evidence, execute = setup([request("inspect_fabrication_evidence", {"evidence_ref": "context:request"})])
        state.run_metadata["specimen_decision_settings"] = {"max_calls": 1}
        if kind == "timeout":
            ctx.complete.side_effect = TimeoutError()
        elif kind == "mock":
            ctx.complete.side_effect = None
            ctx.complete.return_value = SimpleNamespace(text=request(), raw={"mock": True})
        decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
        assert decision["status"] == "failed"
        execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_exception_and_cancellation_propagate_without_retry():
    state, ctx, evidence, execute = setup([request()])
    execute.side_effect = OSError("unknown command effect")
    with pytest.raises(OSError):
        await decide_specimen(state, ctx, "s1", evidence, execute)
    execute.assert_awaited_once()
    state, ctx, evidence, execute = setup([])
    ctx.complete.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await decide_specimen(state, ctx, "s1", evidence, execute)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_deterministic_test_is_labeled():
    state, ctx, evidence, execute = setup([], mode=Mode.TEST)
    ctx.force_real_llm_in_test = False
    decision, _ = await decide_specimen(state, ctx, "s1", evidence, execute)
    assert decision["mode"] == "deterministic_test" and decision["llm_used"] is False
    ctx.complete.assert_not_awaited()
    execute.assert_awaited_once()


def test_model_evidence_excludes_connection_and_arbitrary_payloads():
    evidence = fabrication_evidence(
        {"specimen_id": "s1", "printer_connection": {"password": "SECRET"},
         "print": {"arbitrary_gcode": "G1 X999"}},
        {"ok": True, "geometry_hash": "hash", "connection_info": "SECRET"},
        {"ok": True, "mesh_status": "pass"},
        {"ok": True, "manufacturability_status": "pass", "expected_mass_g": 3},
        {"mode": "test", "_event_callback": object(), "api_key": "SECRET"})
    encoded = json.dumps(evidence)
    assert "SECRET" not in encoded and "G1 X999" not in encoded
    assert evidence["manufacturability:checks"]["expected_mass_g"] == 3


def test_model_can_distinguish_ejection_only_and_profile_driven_print_intent():
    evidence = fabrication_evidence({"specimen_id": "s1"}, {}, {}, {}, {"mode": "test"}, {
        "test_printer_path": "installed_printer", "execution_policy_mode": "execute",
        "connection_info": {"password": "SECRET"},
        "print": {"start_immediately": True, "use_ejection_only_project_file": True, "token": "SECRET"},
        "ejection": {"enabled": True, "allow_ejection": True, "gcode": "SECRET"}})
    intent = evidence["execution:intent"]
    assert intent["test_printer_path"] == "installed_printer"
    assert intent["print"]["use_ejection_only_project_file"] is True
    assert intent["ejection"]["enabled"] is True
    assert "SECRET" not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_model_timeout_does_not_limit_existing_execution_duration():
    state, ctx, evidence, execute = setup([request()])
    state.run_metadata["specimen_decision_settings"] = {"timeout_s": .05, "total_timeout_s": .05}
    async def existing_execution():
        await asyncio.sleep(.06)
        return {"ok": True}
    decision, response = await decide_specimen(state, ctx, "s1", evidence, existing_execution)
    assert decision["status"] == "executed" and response["ok"]
