"""Decision-boundary tests: no device registry or physical callbacks."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from orchestrator.state import Mode, OrchestratorState, Stage


def state():
    return OrchestratorState(run_id="decision", experiment_id="exp", mode=Mode.TEST,
        stage=Stage.MANIPULATION, current_experiment_spec={"specimen_id": "s1"})


class Model:
    force_real_llm_in_test = True

    def __init__(self, choice=None, mutate=None):
        self.choice, self.mutate, self.calls = choice, mutate, []

    async def complete(self, task, prompt, **kwargs):
        context = json.loads(prompt.split("\nCONTEXT:\n")[1])
        self.calls.append((task, context))
        if self.mutate:
            self.mutate()
        choice = self.choice or next(iter(context["tools"]))
        return SimpleNamespace(model="fixture", raw={}, text=json.dumps({
            "tool": choice, "arguments": {"proposal_id": context["proposal_id"]},
            "reason": "Supplied execution and observation agree.",
            "evidence_refs": context["evidence_refs"]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["lerobot.rollout.start", "lerobot.replay.start", "robot.pick_place"])
async def test_selected_skill_is_exactly_bound_to_payload(tool):
    from agents.manipulation_decision import select_manipulation_tool, allows
    s, model = state(), Model()
    payload = {"session_id": "session", "task_instruction": "saved instruction", "replay_episode": 0}
    before = deepcopy(payload)
    decision = await select_manipulation_tool(s, model, tool, payload)
    assert allows(decision) and decision["request"]["tool"] == tool
    assert payload == before
    assert model.calls[0][0] == "manipulation_plan"


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["return_to_owner", "robot.move_joint", "lerobot.replay.start"])
async def test_rejection_or_unlisted_tool_cannot_authorize_rollout(choice):
    from agents.manipulation_decision import select_manipulation_tool, allows
    decision = await select_manipulation_tool(state(), Model(choice), "lerobot.rollout.start", {"session_id": "s"})
    assert not allows(decision)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "loop", "payload", "spec"])
async def test_inflight_changes_invalidate_selected_skill(change):
    from agents.manipulation_decision import select_manipulation_tool, allows
    s, payload = state(), {"session_id": "s"}
    def mutate():
        if change == "stop": s.stop_requested = True
        if change == "loop": s.loop_count += 1
        if change == "payload": payload["session_id"] = "other"
        if change == "spec": s.current_experiment_spec["specimen_id"] = "other"
    assert not allows(await select_manipulation_tool(s, Model(mutate=mutate), "lerobot.rollout.start", payload))


@pytest.mark.asyncio
async def test_result_review_requires_stopped_execution_and_accepted_vision():
    from agents.manipulation_decision import review_manipulation_result, allows
    s, model = state(), Model()
    for ended, visual in [(False, True), (True, False)]:
        result = await review_manipulation_result(s, model, "placement", {"session_id": "s"},
            {"detected": True}, execution_ended=ended, vision_accepted=visual)
        assert not allows(result)
    assert model.calls == []
    result = await review_manipulation_result(s, model, "placement", {"session_id": "s"},
        {"detected": True}, execution_ended=True, vision_accepted=True)
    assert allows(result) and model.calls[0][0] == "manipulation_plan"


@pytest.mark.asyncio
async def test_same_evidence_review_is_cached_but_new_loop_is_not():
    from agents.manipulation_decision import review_manipulation_result
    s, model = state(), Model()
    for _ in range(2):
        await review_manipulation_result(s, model, "placement", {"session_id": "s"},
            {"detected": True}, execution_ended=True, vision_accepted=True)
    assert len(model.calls) == 1
    s.loop_count += 1
    await review_manipulation_result(s, model, "placement", {"session_id": "s"},
        {"detected": True}, execution_ended=True, vision_accepted=True)
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_explicit_non_llm_test_is_not_reported_as_model_judgment():
    from agents.manipulation_decision import select_manipulation_tool
    result = await select_manipulation_tool(state(), SimpleNamespace(force_real_llm_in_test=False),
        "lerobot.rollout.start", {"session_id": "s"})
    assert result["status"] == "deterministic_test" and result["llm_used"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [True, False])
async def test_clearance_handoff_requires_manipulation_after_vision(tmp_path, monkeypatch, accept):
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from utils import utm_clear_cycle as cycle
    from agents.vision_agent import VisionAgent
    from agents import vision_decision
    s = state_with_placement()
    s.current_experiment_spec["execution_policy"] = {"vision": "execute", "manipulation": "execute"}
    cycle.merge_utm_clear_cycle(s, Stage.EQUIPMENT, equipment_data(s))
    s.run_metadata["utm_clear_execution"]["state"] = "running"
    tools = ReplayTools(s)
    tools.status, tools.home = "COMPLETED", True
    model = Model(None if accept else "return_to_owner")
    model.tools = tools
    async def visual(*args): return {"status": "accepted", "scope_valid": True}
    monkeypatch.setattr(vision_decision, "review_visual_evidence", visual)
    result = await VisionAgent().run(s, model)
    assert len(model.calls) == 1
    assert model.calls[0][0] == "manipulation_plan"
    assert bool(result.success) is accept
    assert (result.data.get("requested_next_stage") == "analysis") is accept
    assert result.data["utm_verification_2"]["record"]["confirmed"] is True
    assert all(call[0] != "lerobot.replay.start" for call in tools.calls)


@pytest.mark.asyncio
async def test_module_delegation_uses_owner_model_not_vision():
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from agents.manipulation_decision import review_manipulation_result, allows
    owner = Model()
    class Base:
        active_backend = "fixture"
        force_real_llm_in_test = True
    ctx = ModuleRuntimeContext(Base(), {"id": "vision", "llm_role": "vision_observation"}, Stage.VISION,
        decision_context_factory=lambda stage: owner if stage == Stage.MANIPULATION else None)
    result = await review_manipulation_result(state(), ctx, "placement", {"session_id": "s"},
        {"detected": True}, execution_ended=True, vision_accepted=True)
    assert allows(result) and owner.calls[0][0] == "manipulation_plan"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["malformed", "mock", "timeout", "empty", "foreign_session"])
async def test_untrustworthy_response_never_authorizes_handoff(kind):
    from agents.manipulation_decision import review_manipulation_result, allows
    s = state()
    class Broken(Model):
        async def complete(self, *args, **kwargs):
            if kind == "timeout": raise asyncio.TimeoutError()
            result = await super().complete(*args, **kwargs)
            if kind == "malformed": result.text = "not json"
            if kind == "mock": result.raw = {"mock": True}
            return result
    capture = {} if kind == "empty" else {"detected": True}
    if kind == "foreign_session": capture["session_id"] = "another"
    result = await review_manipulation_result(s, Broken(), "placement", {"session_id": "s"}, capture,
        execution_ended=True, vision_accepted=True)
    assert not allows(result)


@pytest.mark.asyncio
async def test_canceled_decision_does_not_leave_accepted_cache():
    from agents.manipulation_decision import review_manipulation_result
    s = state()
    def cancel(): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await review_manipulation_result(s, Model(mutate=cancel), "placement", {"session_id": "s"},
            {"detected": True}, execution_ended=True, vision_accepted=True)
    assert s.run_metadata["manipulation_decision_cache"] == {}


def test_execution_claim_blocks_duplicate_start_but_not_next_loop():
    from agents.manipulation_decision import claim_skill_execution
    s = state()
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "s"})
    assert not claim_skill_execution(s, "transfer_to_utm", {"session_id": "changed-attempt"})
    s.loop_count += 1
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "s"})


@pytest.mark.asyncio
async def test_same_session_stop_revocation_invalidates_review():
    from agents.manipulation_decision import review_manipulation_result, allows
    s = state()
    s.run_metadata["manipulation_result"] = {"session_id": "s", "status": "STOPPED", "stop_confirmed": True}
    def revoke(): s.run_metadata["manipulation_result"].update(status="RUNNING", stop_confirmed=False)
    result = await review_manipulation_result(s, Model(mutate=revoke), "placement", {"session_id": "s"},
        {"detected": True}, execution_ended=True, vision_accepted=True)
    assert not allows(result)


@pytest.mark.asyncio
async def test_explicit_virtual_clearance_runs_model_but_no_tools():
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data
    from utils import utm_clear_cycle as cycle
    s = state_with_placement()
    s.current_experiment_spec["execution_policy"] = {k: "virtual" for k in ("vision", "manipulation", "lab_equipment")}
    cycle.merge_utm_clear_cycle(s, Stage.EQUIPMENT, equipment_data(s))
    model = Model()
    started = await cycle.run_clear_manipulation(s, model, spec={})
    assert started.success and len(model.calls) == 1
    result = await cycle.run_clear_vision(s, model, artifact_dir="unused")
    assert result.success and len(model.calls) == 2
    assert result.data["observation"]["utm_clear_verification"]["simulated"] is True


@pytest.mark.asyncio
async def test_cancelled_replay_selection_ends_without_rearming():
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data
    from utils import utm_clear_cycle as cycle
    s = state_with_placement()
    s.current_experiment_spec["execution_policy"] = {"manipulation": "execute", "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(s, Stage.EQUIPMENT, equipment_data(s))
    def cancel(): raise asyncio.CancelledError()
    model = Model(mutate=cancel)
    with pytest.raises(asyncio.CancelledError):
        await cycle.run_clear_manipulation(s, model, spec={})
    result = await cycle.run_clear_manipulation(s, model, spec={})
    assert not result.success and len(model.calls) == 1
    assert result.data["utm_clear_execution"]["state"] == "error"


@pytest.mark.asyncio
async def test_decision_context_exposes_task_and_checkpoint_without_editing_payload():
    from agents.manipulation_decision import select_manipulation_tool
    payload = {"session_id": "s", "policy_checkpoint_path": "/saved/checkpoint", "replay_episode": 0}
    before, model = deepcopy(payload), Model()
    await select_manipulation_tool(state(), model, "lerobot.replay.start", payload,
        task_context={"task_id": "clear_utm_to_disposal", "source_location": "utm_fixture", "target_location": "discard_bin"})
    task = model.calls[0][1]["task"]
    assert task["task_id"] == "clear_utm_to_disposal"
    assert task["policy_checkpoint_path"] == "/saved/checkpoint"
    assert payload == before


@pytest.mark.asyncio
async def test_manual_completion_exposes_stop_and_resource_evidence():
    from agents.manipulation_decision import review_manipulation_result
    model = Model()
    await review_manipulation_result(state(), model, "placement", {"session_id": "s", "teleop_stop_verified": True,
        "robot_port_released": True, "camera_returned_to_vision": True}, {"detected": True},
        execution_ended=True, vision_accepted=True)
    task = model.calls[0][1]["task"]
    assert task["teleop_stop_verified"] and task["robot_port_released"] and task["camera_returned_to_vision"]
    assert task["required_visual_effect"] == "target_present"


@pytest.mark.asyncio
async def test_rejection_can_cite_specific_task_vision_conflict_without_irrelevant_execution_ref():
    from agents.manipulation_decision import review_manipulation_result
    class Conflict(Model):
        async def complete(self, *args, **kwargs):
            result = await super().complete(*args, **kwargs)
            request = json.loads(result.text)
            request["evidence_refs"] = ["task:configured", "vision:verified"]
            result.text = json.dumps(request)
            return result
    result = await review_manipulation_result(state(), Conflict("return_to_owner"), "placement", {"session_id": "s"},
        {"detected": False}, execution_ended=True, vision_accepted=True)
    assert result["request"]["tool"] == "return_to_owner"
    assert result["status"] == "review_required" and "error" not in result
