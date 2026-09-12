"""The opt-in verifier must exercise real local adapters, not echo tools."""
import json
from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("after_effect", [False, True])
@pytest.mark.parametrize("failure", [RuntimeError, TimeoutError, ConnectionError])
async def test_unexpected_controller_failure_never_passes_allowed_effect(tmp_path, monkeypatch, after_effect, failure):
    from scripts.orchestrator_decision_fixtures import exercise_intake_effect
    from scripts.verify_orchestrator_setup import controller_for
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        block_id, block = next(iter(request["context"]["setup_blocks"].items()))
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "propose_setup_change",
            "arguments": {"block_id": block_id, "revision": block["revision"], "changes": {"bo.acquisition": "expected_improvement"}},
            "reason": "A scoped next-run draft", "evidence_refs": ["chat:request"]}))
    controller = controller_for(SimpleNamespace(complete=complete, active_backend="controlled"), tmp_path)
    block = next(b for b in controller._planning_setup_projection()["blocks"] if b["topic_key"] == "bo.acquisition")
    original = controller.planning_message
    async def interrupted(**kwargs):
        if after_effect:
            await original(**kwargs)
        raise failure("explicit fixture execution failure")
    monkeypatch.setattr(controller, "planning_message", interrupted)
    case = {"message": "다음 실험의 acquisition을 ei로 제안해 주세요.", "allowed_effects": ["DRAFT"] if after_effect else ["NONE"]}
    result = await exercise_intake_effect(controller, case, {"intent": "change_setup" if after_effect else "question",
        "reason": "Scoped request", "pending_id": None}, {"setup_context": block} if after_effect else {})
    assert result["effect"] == ("DRAFT" if after_effect else "NONE")
    assert result["error_type"] == failure.__name__
    assert result["expectation_met"] is False
    assert result["effect_expectation_met"] is True
    assert result["execution_status"] == ("blocked" if failure is ConnectionError else "failed")


@pytest.mark.parametrize("execution_status,expected", [("completed", "passed"), ("failed", "failed"), ("blocked", "blocked")])
def test_intake_report_separates_execution_failure_from_allowed_effect(execution_status, expected):
    from scripts.verify_orchestrator_setup import intake_case_status
    assert intake_case_status(intent_ok=True, transport_blocked=False,
        raw_attempts=[{"text": "{}", "served_model": "registered"}],
        effect={"expectation_met": True, "execution_status": execution_status}) == expected


@pytest.mark.parametrize("attempts,outcome,expected", [
    ([{"error_type": "ConnectError"}], {"expectation_met": True, "containment_only": True}, "blocked"),
    ([{"error_type": "RuntimeError"}], {"expectation_met": True}, "failed"),
    ([{"text": "{}", "served_model": "registered"}], {"expectation_met": True, "decision": {"status": "failed"}}, "failed"),
    ([{"text": "{}", "served_model": "registered"}, {"error_type": "ConnectTimeout"}], {"expectation_met": True}, "blocked"),
    ([{"text": "{}", "served_model": "registered"}], {"expectation_met": True, "decision": {"status": "deferred"}}, "passed"),
    ([{"error_type": "ConnectError"}, {"text": "{}", "served_model": "registered-fallback"}], {"expectation_met": True}, "passed"),
    ([], {"expectation_met": True, "error_type": "ConnectionError"}, "blocked"),
    ([], {"expectation_met": True, "error_type": "TimeoutError"}, "failed"),
    ([{"text": "{}"}], {"expectation_met": True}, "blocked"),
    ([], {"expectation_met": True}, "blocked"),
])
def test_decision_report_requires_successful_model_execution_not_containment(attempts, outcome, expected):
    from scripts.verify_orchestrator_setup import decision_case_status
    assert decision_case_status(outcome=outcome, raw_attempts=attempts, transport_blocked=False) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, ConnectionError])
async def test_unsupported_decision_provider_failure_is_only_containment(tmp_path, failure):
    from scripts.orchestrator_decision_fixtures import run_case
    from scripts.verify_orchestrator_setup import controller_for
    async def unavailable(*args, **kwargs):
        raise failure("explicit model-boundary failure")
    controller = controller_for(SimpleNamespace(complete=unavailable, active_backend="controlled"), tmp_path)
    outcome = await run_case(controller, "unsupported_setup")
    assert outcome["containment_only"] is True
    assert outcome["expectation_met"] is False


def test_cli_without_execute_only_lists_frozen_fixtures(monkeypatch, capsys):
    from scripts import verify_orchestrator_setup as verifier
    async def forbidden(*args):
        pytest.fail("No-execute must not construct runtime or access providers")
    monkeypatch.setattr(verifier, "verify", forbidden)
    monkeypatch.setattr("sys.argv", ["verify_orchestrator_setup.py", "--backend", "vllm"])
    assert verifier.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution"] is False and len(output["fixtures"]) == 48
    assert len(output["decision_cases"]) == 6 and output["denied_boundaries"]


@pytest.mark.asyncio
async def test_cli_refuses_existing_output_before_provider_construction(tmp_path, monkeypatch):
    from scripts.verify_orchestrator_setup import verify
    import app.bootstrap
    path = tmp_path / "retained.json"
    path.write_text("retained evidence")
    monkeypatch.setattr(app.bootstrap, "_build_backend", lambda *a, **k: pytest.fail("Must reject output first"))
    with pytest.raises(FileExistsError):
        await verify(SimpleNamespace(output=str(path), backend=["vllm"]))
    assert path.read_text() == "retained evidence"


@pytest.mark.asyncio
async def test_proposal_prompt_projects_only_declared_editable_blocks(tmp_path):
    from scripts.verify_orchestrator_setup import controller_for
    from app.planning_setup import propose_from_chat
    observed = []
    async def complete(task, prompt, **kwargs):
        observed.append(json.loads(prompt))
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "defer", "arguments": {
            "condition": "Inspect scoped proposal"}, "reason": "No mutation", "evidence_refs": ["chat:request"]}))
    controller = controller_for(SimpleNamespace(complete=complete, active_backend="controlled"), tmp_path)
    projection = controller._planning_setup_projection()
    block = next(b for b in projection["blocks"] if b["topic_key"] == "bo.acquisition")
    scope = controller._planning_intake_scope()
    await propose_from_chat(store=controller._setup_store(), catalog=controller._planning_setup_catalog(), projection=projection, state=controller._state,
        ctx=controller._deps.agent_context, message="Suggest a supported acquisition change", scope=scope,
        current_scope=controller._planning_intake_scope, settings={}, block_id=block["block_id"])
    setup = observed[0]["evidence"]["chat:request"]["setup"]
    assert "owners" not in setup and len(setup["blocks"]) == 1
    selected = setup["blocks"][0]
    assert selected["block_id"] == block["block_id"]
    assert selected["draft_values"] == block["draft_values"]
    assert selected["fields"] == block["fields"]
    assert observed[0]["scope"]["context"] == scope


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope,accepted", [
    ("{payload}", True), ("```json\n{payload}\n```", True),
    ("Explanation\n```json\n{payload}\n```", False),
    ("```json\n{payload}\n```\nExtra text", False),
    ("```json\n{payload}\n```\n```json\n{payload}\n```", False),
])
async def test_registered_single_json_envelope_preserves_strict_schema(envelope, accepted):
    from agents.orchestrator_decision import classify_chat_request
    from orchestrator.state import OrchestratorState
    payload = json.dumps({"intent": "question", "reason": "An explanation request", "pending_id": None})
    async def complete(*args, **kwargs):
        return SimpleNamespace(model="controlled", text=envelope.replace("{payload}", payload))
    value = await classify_chat_request(OrchestratorState(run_id="envelope", experiment_id="envelope"),
        SimpleNamespace(complete=complete), message="Explain test mode")
    assert value["intent"] == ("question" if accepted else "unclear")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"intent": "question", "reason": "x", "pending_id": None, "execute": True},
    {"intent": "confirm_pending", "reason": "x", "pending_id": "foreign"},
    {"tool": "printer.send", "arguments": {}, "reason": "x", "evidence_refs": ["e"]},
])
async def test_json_fence_never_relaxes_intake_authority(payload):
    from agents.orchestrator_decision import classify_chat_request
    from orchestrator.state import OrchestratorState
    async def complete(*args, **kwargs):
        return SimpleNamespace(model="controlled", text="```json\n" + json.dumps(payload) + "\n```")
    value = await classify_chat_request(OrchestratorState(run_id="envelope", experiment_id="envelope"),
        SimpleNamespace(complete=complete), message="continue", pending_id="current")
    assert value["intent"] == "unclear"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["test", "live"])
async def test_natural_start_reaches_original_missing_input_admission(tmp_path, mode):
    from scripts.orchestrator_decision_fixtures import exercise_intake_effect
    from scripts.verify_orchestrator_setup import controller_for
    from orchestrator.state import Mode
    async def forbidden(*args, **kwargs):
        pytest.fail("Missing required inputs must hold before another model/owner call")
    ctx = SimpleNamespace(complete=forbidden, active_backend="controlled")
    controller = controller_for(ctx, tmp_path)
    controller._state.mode = Mode(mode)
    controller.planning_snapshot()
    case = {"message": "현재 설정으로 새 실험을 시작해 주세요.", "allowed_effects": ["START"], "context": "N"}
    result = await exercise_intake_effect(controller, case,
        {"intent": "start_run", "reason": "Actual new experiment request", "pending_id": None}, {})
    assert result["effect"] == "START"
    assert result["expectation_met"]
    assert any(e.get("type") == "planning_design_inputs_required" for e in controller.recent_events())
    assert controller._state.mode.value == mode


@pytest.mark.asyncio
@pytest.mark.parametrize("case,choices", [
    ("ready", ["prepare_handoff"]), ("busy", ["defer"]),
    ("unknown_stale", ["defer", "defer"]),
    ("completed_defer_resume", ["defer", "prepare_handoff"]),
])
async def test_decision_probe_has_real_scoped_checkpoint_effect(tmp_path, case, choices):
    from scripts.orchestrator_decision_fixtures import run_case
    from scripts.verify_orchestrator_setup import controller_for
    async def complete(task, prompt, **kwargs):
        assert kwargs.get("timeout_s") is None, "Verifier must inherit the registered provider budget"
        request = json.loads(prompt)
        tool = choices.pop(0)
        return SimpleNamespace(model="controlled-fixture", text=json.dumps({"tool": tool,
            "arguments": {"candidate": "bo"} if tool == "prepare_handoff" else {"condition": "Wait for required owner evidence"},
            "reason": "Scenario decision", "evidence_refs": ["boundary:result"]}))
    ctx = SimpleNamespace(complete=complete, active_backend="controlled", artifact_run_root=str(tmp_path))
    controller = controller_for(ctx, tmp_path)
    result = await run_case(controller, case)
    assert result["expectation_met"], result
    assert result["tool_trace"]
    records = controller._state.run_metadata["orchestrator_checkpoints"]
    assert records
    if case in {"ready", "completed_defer_resume"}:
        assert result["consumption_count"] == 1
        assert result["duplicate_consumption_count"] == 0
        assert any(r["status"] == "consumed" for r in records.values())
    else:
        assert all(r["status"] == "deferred" for r in records.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["supported_proposal", "unsupported_setup"])
async def test_decision_probe_proposes_only_declared_next_run_draft(tmp_path, case):
    from scripts.orchestrator_decision_fixtures import run_case
    from scripts.verify_orchestrator_setup import controller_for
    async def complete(task, prompt, **kwargs):
        assert kwargs.get("timeout_s") is None, "Verifier must inherit the registered provider budget"
        request = json.loads(prompt)
        if case == "supported_proposal":
            block_id, block = next(iter(request["context"]["setup_blocks"].items()))
            setup = request["evidence"]["chat:request"]["setup"]
            space = next(b for b in setup["blocks"] if b["block_id"] == block_id)["draft_values"]["bo.parameter_space"]
            space.update(cell_size_mm=[7, 8], relative_density=[.3, .4])
            choice = {"tool": "propose_setup_change", "arguments": {"block_id": block_id,
                "revision": block["revision"], "changes": {"bo.parameter_space": space}}}
        else:
            choice = {"tool": "defer", "arguments": {"condition": "Undeclared field and bridge authority"}}
        return SimpleNamespace(model="controlled-fixture", text=json.dumps({**choice,
            "reason": "Supported next-run scope only", "evidence_refs": ["chat:request"]}))
    controller = controller_for(SimpleNamespace(complete=complete, active_backend="controlled"), tmp_path)
    original = controller._state.active_goal
    result = await run_case(controller, case)
    assert result["expectation_met"], result
    assert result["confirmed_values"] is None
    assert controller._state.active_goal == original
    assert bool(result["proposal_id"]) is (case == "supported_proposal")
