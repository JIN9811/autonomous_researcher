"""Final-review I1/M1 regressions: real setup/controller, no external effects."""
import asyncio
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        from scripts.verify_orchestrator_setup import controller_for
        async def complete(*args, **kwargs):
            pytest.fail("Admission must precede any model call")
        controller = controller_for(SimpleNamespace(complete=complete, active_backend="controlled"), tmp_path)
        controller.planning_snapshot()
        effects = []
        async def runtime():
            effects.append(("runtime", deepcopy(controller._state.run_metadata)))
        async def review(**kwargs):
            effects.append(("review", deepcopy(controller._state.run_metadata)))
            return {"status": "deferred"}
        def lhs(*args, **kwargs):
            effects.append(("lhs", {}))
            pytest.fail("Held setup reached initial LHS")
        async def design(**kwargs):
            effects.append(("design", {}))
            pytest.fail("Held setup reached Design")
        monkeypatch.setattr(controller, "_run_live_or_test", runtime)
        monkeypatch.setattr(importlib.import_module("app.controller"), "review_handoff", review)
        monkeypatch.setattr(controller, "_seed_initial_bo_design_constraints", lhs)
        monkeypatch.setattr(controller, "_run_planning_design_stage", design)
        yield controller, effects
        assert guard.physical_call_count == 0
        assert guard.denied == []


async def confirm(controller, topic, value, suffix=""):
    from orchestrator.setup_application import SetupApplication
    store = controller._setup_store()
    block = next(b for b in store.snapshot()["blocks"] if b["topic_key"] == topic)
    proposal = store.propose(block["block_id"], block["revision"], {topic: value}, "propose-" + topic + suffix)
    result = await SetupApplication(store, controller._planning_setup_catalog()).confirm(
        proposal["proposal_id"], proposal["block_revision"], "confirm-" + topic + suffix, controller._state)
    assert not result.get("requires_confirmation")
    return proposal


async def launch(controller, entry):
    from orchestrator.state import Mode
    if entry == "start":
        result = await controller.start(mode=Mode.TEST)
        if controller._run_task:
            await controller._run_task
        return result
    return await controller._handoff_planning_to_design(goal=None, constraints={}, new_series=True)


def bo(controller):
    return controller._deps.agent_registry.get("bo_agent")


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["start", "planning"])
async def test_two_confirmed_bo_topics_admit_requested_bounds_not_defaults(rig, entry):
    """Receipt/proposal bookkeeping in a jointly confirmed owner cannot erase bounds."""
    controller, effects = rig
    space = deepcopy(bo(controller).read_setup(controller._state)["parameter_space"])
    space.update(cell_size_mm=[7.0, 8.0], relative_density=[0.30, 0.40])
    await confirm(controller, "bo.parameter_space", space)
    await confirm(controller, "bo.acquisition", "upper_confidence_bound")
    await launch(controller, entry)
    assert len(effects) == 1
    actual = effects[0][1]["bo_settings"]
    assert actual["parameter_space"]["cell_size_mm"] == [7.0, 8.0]
    assert actual["parameter_space"]["relative_density"] == [0.30, 0.40]
    assert actual["acquisition"] == "upper_confidence_bound"
    blocks = controller._setup_store().snapshot()["blocks"]
    assert all(b["application_status"] == "applied" for b in blocks if b["topic_key"].startswith("bo."))


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["start", "planning"])
@pytest.mark.parametrize("failure", ["dependency", "binding", "invalid", "normalized"])
async def test_stale_or_changed_validation_holds_all_captured_settings_before_effects(rig, monkeypatch, entry, failure):
    """A valid sibling must not be applied before every captured setting passes validation."""
    controller, effects = rig
    await confirm(controller, "research.goal", "confirmed goal")
    await confirm(controller, "bo.acquisition", "upper_confidence_bound")
    store = controller._setup_store()
    if failure == "dependency":
        block = next(b for b in store.snapshot()["blocks"] if b["topic_key"] == "bo.parameter_space")
        store.propose(block["block_id"], block["revision"], {"bo.parameter_space": {"cell_size_mm": [7, 8]}}, "changed-dependency")
    elif failure == "binding":
        original = bo(controller).setup_descriptor
        def changed():
            descriptor = original()
            descriptor["revision"] = "different-contract"
            return descriptor
        monkeypatch.setattr(bo(controller), "setup_descriptor", changed)
    else:
        original = bo(controller).validate_setup
        def changed(changes, state):
            if failure == "invalid":
                raise ValueError("Owner no longer accepts this acquisition")
            result = original(changes, state)
            result["values"]["acquisition"] = "expected_improvement"
            return result
        monkeypatch.setattr(bo(controller), "validate_setup", changed)
    for _ in range(2):
        result = await launch(controller, entry)
        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert result["failure_code"] == "SETUP_ADMISSION_REQUIRED"
        assert effects == []
    assert all(not block["receipts"] for block in store.snapshot()["blocks"])
    assert controller._state.active_goal != "confirmed goal"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["start", "planning"])
@pytest.mark.parametrize("failure", ["rejected", "unknown", "persistent_unknown", "partial"])
async def test_failed_receipts_hold_repeated_launch_without_reapplying_successful_owners(rig, monkeypatch, entry, failure):
    """A second start must retain failed setup, not drop receipts and enter defaults."""
    controller, effects = rig
    store = controller._setup_store()
    if failure == "partial":
        from orchestrator.setup_application import SetupApplication
        block = store.ensure_block("multi-owner", ["orchestrator_agent", "bo_agent"], {})
        proposal = store.propose(block["block_id"], block["block_revision"],
            {"research.goal": "confirmed goal", "bo.acquisition": "upper_confidence_bound"}, "multi")
        await SetupApplication(store, controller._planning_setup_catalog()).confirm(
            proposal["proposal_id"], proposal["block_revision"], "confirm-multi", controller._state)
    else:
        await confirm(controller, "research.goal", "confirmed goal")
        await confirm(controller, "bo.acquisition", "upper_confidence_bound")
    calls = []
    lose_next_readback = [False]
    for owner in ("orchestrator_agent", "bo_agent"):
        agent = controller._deps.agent_registry.get(owner)
        original = agent.apply_setup
        def apply(changes, state, request_id, original=original, owner=owner):
            calls.append((owner, request_id))
            result = original(changes, state, request_id)
            if owner == "bo_agent" and failure in {"unknown", "partial"}:
                lose_next_readback[0] = True
            return result
        monkeypatch.setattr(agent, "apply_setup", apply)
    if failure == "persistent_unknown":
        monkeypatch.setattr(bo(controller), "read_setup", lambda state: None)
    elif failure in {"unknown", "partial"}:
        original_read = bo(controller).read_setup
        def read(state):
            if lose_next_readback[0]:
                lose_next_readback[0] = False
                return None
            return original_read(state)
        monkeypatch.setattr(bo(controller), "read_setup", read)
    else:
        original_read = bo(controller).read_setup
        monkeypatch.setattr(bo(controller), "read_setup", lambda state: {
            **original_read(state), "acquisition": "expected_improvement"})
    attempted_run_ids = []
    for _ in range(2):
        result = await launch(controller, entry)
        attempted_run_ids.append(controller._state.run_id)
        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert result["failure_code"] == "SETUP_ADMISSION_REQUIRED"
        assert effects == []
    assert attempted_run_ids[0] == attempted_run_ids[1], "Readback recovery must retain the failed run's inputs"
    assert sorted(owner for owner, _ in calls) == ["bo_agent", "orchestrator_agent"]
    receipts = [receipt for block in store.snapshot()["blocks"] for receipt in block["receipts"].values()]
    assert sorted(r["status"] for r in receipts) == ["applied", "rejected" if failure == "rejected" else "unknown"]
    if failure == "partial":
        assert next(b for b in store.snapshot()["blocks"] if b["topic_key"] == "multi-owner")["application_status"] == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,message,guidance", [
    ("unclear", "yes", "Please clarify"),
    ("out_of_scope", "Tell me a joke", "current research workflow"),
])
async def test_nonaction_api_session_and_durable_chat_contain_visible_guidance(rig, monkeypatch, intent, message, guidance):
    """API session is the GUI's render input; top-level message alone is invisible."""
    controller, effects = rig
    import app.bootstrap
    monkeypatch.setattr(app.bootstrap, "load_runtime", lambda: controller)
    api = importlib.import_module("app.main")
    monkeypatch.setattr(api, "controller", controller)
    async def complete(task, prompt, **kwargs):
        assert json.loads(prompt)["operation"] == "classify_chat_request"
        return SimpleNamespace(model="controlled", raw={}, text=json.dumps({
            "intent": intent, "reason": "fixture", "pending_id": None}))
    controller._deps.agent_context.complete = complete
    before = deepcopy(controller._planning_intake_scope())
    setup = controller._setup_store().snapshot()
    result = await api.post_planning_message(api.PlanningMessageRequest(
        message=message, session_id=controller._planning_session_id))
    messages = result["session"]["messages"]
    assert len(messages) == 2
    assert (messages[0]["role"], messages[0]["content"]) == ("operator", message)
    assert messages[-1]["role"] == "orchestrator"
    assert guidance in messages[-1]["content"]
    assert "chat" in messages[-1]["surface"]
    assert messages[-1]["visibility"] == "user"
    controller._planning_messages = []
    restored = await api.get_planning_messages(session_id=controller._planning_session_id)
    assert [(m["role"], m["content"]) for m in restored["messages"]][-2:] == [
        ("operator", message), ("orchestrator", messages[-1]["content"])]
    assert controller._planning_intake_scope() == before
    assert controller._setup_store().snapshot() == setup
    assert not controller._state.run_metadata.get("operator_followup_queue")
    assert effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("topic,value", [
    ("bo.parameter_space", {"teleport_speed": 99}),
    ("bo.parameter_space", {"cell_size_mm": ["fast", "slow"]}),
    ("bo.acquisition", "unsupported_acquisition"),
])
async def test_chat_draft_rejects_owner_invalid_values_before_store_write(rig, topic, value):
    """Declared public keys alone do not authorize arbitrary nested owner settings."""
    controller, effects = rig
    block = next(b for b in controller._planning_setup_projection()["blocks"] if b["topic_key"] == topic)
    store = controller._setup_store()
    before = store.snapshot()
    async def complete(task, prompt, **kwargs):
        operation = json.loads(prompt)["operation"]
        if operation == "classify_chat_request":
            choice = {"intent": "change_setup", "reason": "requested edit", "pending_id": None}
        else:
            assert operation == "decide_orchestration"
            choice = {"tool": "propose_setup_change", "arguments": {
                "block_id": block["block_id"], "revision": block["revision"], "changes": {topic: value}},
                "reason": "requested edit", "evidence_refs": ["chat:request"]}
        return SimpleNamespace(model="controlled", raw={}, text=json.dumps(choice))
    controller._deps.agent_context.complete = complete
    result = await controller.planning_message(message="Change this owner setting", session_id=controller._planning_session_id)
    assert result["ok"] is False
    assert result["decision"]["status"] == "failed"
    assert store.snapshot() == before
    assert effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_kind", ["missing", "foreign_run", "foreign_loop", "foreign_specimen"])
async def test_conditional_refresh_rejects_incomplete_or_stale_server_scope_without_queue(rig, scope_kind):
    """Even a model confirmation cannot create authority from malformed/stale pending data."""
    controller, effects = rig
    held = {"status": "waiting", "held_checkpoint": "held", "action": "refresh_observation"}
    if scope_kind != "missing":
        held["scope"] = {"run_id": controller._state.run_id, "loop": 0, "specimen_id": ""}
        held["scope"][{"foreign_run": "run_id", "foreign_loop": "loop", "foreign_specimen": "specimen_id"}[scope_kind]] = {
            "foreign_run": "old-run", "foreign_loop": 99, "foreign_specimen": "old-specimen"}[scope_kind]
    controller._state.run_metadata["orchestrator_observation_refresh"] = held
    before = deepcopy(controller._planning_intake_scope())
    async def complete(task, prompt, **kwargs):
        packet = json.loads(prompt)
        assert packet["operation"] == "classify_chat_request"
        return SimpleNamespace(model="controlled", raw={}, text=json.dumps({
            "intent": "confirm_pending", "reason": "model reply cannot override server scope", "pending_id": "held"}))
    controller._deps.agent_context.complete = complete
    result = await controller.planning_message(message="Request a fresh observation", session_id=controller._planning_session_id)
    assert result["session"]["messages"][-1]["role"] == "orchestrator"
    assert not controller._state.run_metadata.get("operator_followup_queue")
    assert controller._planning_intake_scope() == before
    assert effects == []
