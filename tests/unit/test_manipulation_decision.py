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
    from agents.manipulation.decision import select_manipulation_tool, allows
    s, model = state(), Model()
    payload = {"session_id": "session", "task_instruction": "saved instruction", "replay_episode": 0}
    before = deepcopy(payload)
    decision = await select_manipulation_tool(s, model, tool, payload)
    assert allows(decision) and decision["request"]["tool"] == tool
    assert payload == before
    assert model.calls[0][0] == "manipulation_plan"


@pytest.mark.asyncio
async def test_selection_prompt_omits_raw_vision_dump_without_losing_observed_gates():
    from agents.manipulation.decision import select_manipulation_tool, allows
    signal = {"signal": "pickup_ready", "value": True, "confidence": .86,
              "run_id": "decision", "loop_id": 0, "blocking_reason": None}
    observation = {"anomaly": False, "pose_estimate": {"x": .1, "frame": "camera"},
        "transfer_readiness": {"ready": True, "camera_ok": True},
        "vision_signal": {"status": "ready", "signals": [signal]},
        "agent_signals": [signal], "raw": {"vision_report": "raw diagnostic " * 15000}}
    payload = {"session_id": "s", "task_instruction": "pick and place", "observation": observation}
    original = deepcopy(payload)
    model = Model()
    decision = await select_manipulation_tool(state(), model, "lerobot.rollout.start", payload)
    context = model.calls[0][1]
    assert len(json.dumps(context)) < 6000
    assert context["task"]["observation"]["transfer_readiness"] == {"ready": True, "camera_ok": True}
    assert context["task"]["observation"]["vision_signal"]["signals"] == [signal]
    assert context["task"]["observation"]["pose_estimate"] == {"x": .1, "frame": "camera"}
    assert payload == original
    assert decision["evidence"]["task"]["observation"] == original["observation"]
    assert allows(decision)


@pytest.mark.asyncio
async def test_prompt_preserves_conflicting_signal_lists_and_review_verdicts():
    from agents.manipulation.decision import select_manipulation_tool, allows
    observation = {"anomaly": True, "transfer_readiness": {"ready": False, "blocking_reason": "occluded"},
        "vision_signal": {"signals": [{"signal": "pickup_ready", "value": True}]},
        "agent_signals": [{"signal": "pickup_ready", "value": False}], "raw": {"dump": "x" * 90000}}
    model = Model("return_to_owner")
    result = await select_manipulation_tool(state(), model, "lerobot.rollout.start", {"observation": observation})
    rendered = model.calls[0][1]["task"]["observation"]
    assert "raw" not in rendered
    assert rendered["anomaly"] is True
    assert rendered["agent_signals"] == [{"signal": "pickup_ready", "value": False}]
    assert rendered["transfer_readiness"]["blocking_reason"] == "occluded"
    assert not allows(result)


def test_signal_table_is_lossless_including_missing_and_conflicting_fields():
    from agents.manipulation.decision import _prompt_context
    signals = [{"run_id": "run", "loop_id": 12, "signal": f"s{i}", "value": i % 2 == 0,
                "blocking_reason": None if i != 4 else "blocked"} for i in range(16)]
    signals[-1].pop("blocking_reason")
    context = {"task": {"observation": {"vision_signal": {"signals": signals}}}}
    table = _prompt_context(context)["task"]["observation"]["vision_signal"]["signals"]
    assert isinstance(table, dict)
    restored = [{**table["shared"], **{k: v for k, v in zip(table["columns"], row)
                 if k not in table["missing_fields"].get(str(i), [])}} for i, row in enumerate(table["rows"])]
    assert restored == signals
    assert context["task"]["observation"]["vision_signal"]["signals"] == signals


@pytest.mark.parametrize("section", ["task", "vision"])
def test_signal_references_are_scoped_to_their_own_section(section):
    from agents.manipulation.decision import _prompt_context
    signals = [{"signal": f"s{i}", "value": False, "consumer_agents": ["vision"]} for i in range(6)]
    agents = [{**row, "consumer_agents": ["manipulation"]} for row in signals]
    context = {section: {"observation": {"vision_signal": {"signals": signals}, "agent_signals": agents}}}
    projected = _prompt_context(context)[section]["observation"]
    assert projected["vision_signal"]["signals"]["rows_ref"] == f"{section}.observation.agent_signals"
    context[section]["observation"]["agent_signals"] = deepcopy(signals)
    projected = _prompt_context(context)[section]["observation"]
    assert projected["agent_signals_ref"] == f"{section}.observation.vision_signal.signals"


def test_signal_table_repeated_strings_decode_exactly_without_rounding():
    from agents.manipulation.decision import _signal_table
    signals = [{"signal_id": f"sig-long-run-identity-20260923-11-signal-{i}",
                "expires_at": "2026-09-26T07:22:11.223904+00:00" if i % 2 else None,
                "consumer_agents": ["manipulation_agent"], "confidence": 0.123456789 + i,
                "blocking_reason": "not_observed_in_current_stage" if i % 3 else None}
               for i in range(16)]
    signals[-1].pop("expires_at")
    before = deepcopy(signals)
    table = _signal_table(signals)
    assert table.get("string_prefixes", {}).get("signal_id")
    assert "expires_at" in table.get("column_dictionaries", {})
    restored = []
    for i, row in enumerate(table["rows"]):
        item = deepcopy(table["shared"])
        for key, value in zip(table["columns"], row):
            if key in table["missing_fields"].get(str(i), []):
                continue
            if key in table.get("column_dictionaries", {}):
                value = table["column_dictionaries"][key][value]
            if key in table.get("string_prefixes", {}):
                value = table["string_prefixes"][key] + value
            item[key] = value
        restored.append(item)
    assert restored == signals == before


def test_prompt_refs_deduplicate_only_equal_pose_interlock_and_review_json():
    from agents.manipulation.decision import _prompt_context
    pose = {"x": .123456789, "frame": "camera"}
    target = {"id": "specimen", "detected": True}
    interlock = {"ready": True, "session_id": "same-session"}
    request = {"tool": "accept_visual_evidence", "arguments": {"contract_id": "placement"},
               "reason": "Observed target is consistent.", "evidence_refs": ["frame:current"]}
    context = {"task": {"session_id": "same-session", "pickup_pose": pose, "pickup_target": target,
        "observation": {"pose_estimate": pose, "pickup_target": target},
        "post_place_interlock": interlock, "rollout_stop": {"session_id": "same-session", "post_place_interlock": interlock}},
        "vision": {"session_id": "same-session", "post_place_interlock": interlock, "vision_decision": {
            "request": request, "response": json.dumps(request), "reason": request["reason"]}}}
    original = deepcopy(context)
    projected = _prompt_context(context)
    assert projected["task"]["pickup_pose_ref"] == "task.observation.pose_estimate"
    assert projected["task"]["pickup_target_ref"] == "task.observation.pickup_target"
    assert projected["vision"]["post_place_interlock_ref"] == "task.post_place_interlock"
    assert projected["vision"]["session_id_ref"] == "task.session_id"
    assert projected["task"]["rollout_stop"]["session_id_ref"] == "task.session_id"
    assert projected["task"]["rollout_stop"]["post_place_interlock_ref"] == "task.post_place_interlock"
    review = projected["vision"]["vision_decision"]
    assert review["response_ref"] == "vision.vision_decision.request"
    assert review["reason_ref"] == "vision.vision_decision.request.reason"
    assert review["request"] == request
    assert context == original
    context["task"]["pickup_pose"] = {"x": .999, "frame": "camera"}
    context["vision"]["post_place_interlock"] = {"ready": False, "session_id": "same-session"}
    context["vision"]["session_id"] = "different-session"
    context["vision"]["vision_decision"]["response"] = '{"tool":"return_to_owner"}'
    context["vision"]["vision_decision"]["reason"] = "Contradictory review"
    changed = _prompt_context(context)
    assert changed["task"]["pickup_pose"] == {"x": .999, "frame": "camera"}
    assert changed["vision"]["post_place_interlock"]["ready"] is False
    assert changed["vision"]["session_id"] == "different-session"
    assert changed["vision"]["vision_decision"]["response"] == '{"tool":"return_to_owner"}'
    assert changed["vision"]["vision_decision"]["reason"] == "Contradictory review"


def test_result_prompt_keeps_stop_conflicts_but_not_driver_dumps():
    from agents.manipulation.decision import _prompt_context
    context = {"checkpoint": "result_review", "task": {"rollout_stop": {
        "ok": True, "session_id": "s1", "status": "STOPPED", "returncode": -15,
        "runtime": {"phase": "RUNNING", "warnings": ["contradiction"], "action_count_observed": False},
        "active_camera_lease": {"status": "blocked", "conflict_reason": "camera in use"},
        "port_lease": {"status": "occupied"}, "error": "driver warning",
        "log_tail": "diagnostic text " * 10000, "command_preview": "shell config " * 10000,
        "joint_telemetry": {"status": "available", "session_id": "s2", "packet": {
            "sequence": 22, "home_gate_passed": False, "measured_base_state": "moving",
            "samples": [0] * 10000}}}}, "vision": {"detected": False}}
    before = deepcopy(context)
    projected = _prompt_context(context)
    stop = projected["task"]["rollout_stop"]
    assert len(json.dumps(projected)) < 4000
    assert stop["status"] == "STOPPED" and stop["runtime"]["phase"] == "RUNNING"
    assert stop["error"] == "driver warning" and stop["returncode"] == -15
    assert stop["active_camera_lease"]["status"] == "blocked"
    assert stop["joint_telemetry"]["session_id"] == "s2"
    assert stop["joint_telemetry"]["packet"]["home_gate_passed"] is False
    assert stop["joint_telemetry"]["packet"]["measured_base_state"] == "moving"
    assert projected["vision"]["detected"] is False
    assert context == before


@pytest.mark.asyncio
async def test_replay_selection_exposes_task_to_executor_binding_without_changing_recording():
    from agents.manipulation.decision import select_manipulation_tool, allows
    s, model = state(), Model()
    payload = {"session_id": "clear-session", "dataset_repo_id": "jin/utm_clear", "replay_episode": 0,
               "profile_id": "robotis_omx_ai"}
    task = {"task_id": "clear_utm_to_disposal", "source_location": "utm_fixture", "target_location": "discard_bin"}
    decision = await select_manipulation_tool(s, model, "lerobot.replay.start", payload, task_context=task)
    binding = model.calls[0][1]["skill_binding"]
    assert binding["executor"] == "lerobot.replay.start"
    assert binding["kind"] == "recorded_episode_replay"
    assert binding["task_contract"] == task
    assert binding["configured_parameters"]["dataset_repo_id"] == "jin/utm_clear"
    assert binding["configured_parameters"]["replay_episode"] == 0
    assert payload["replay_episode"] == 0
    assert allows(decision)


@pytest.mark.asyncio
async def test_explicit_replay_binding_does_not_override_model_rejection():
    from agents.manipulation.decision import select_manipulation_tool, allows
    decision = await select_manipulation_tool(state(), Model("return_to_owner"), "lerobot.replay.start",
        {"session_id": "clear", "dataset_repo_id": "jin/utm_clear", "replay_episode": 0},
        task_context={"task_id": "clear_utm_to_disposal"})
    assert not allows(decision)


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["return_to_owner", "robot.move_joint", "lerobot.replay.start"])
async def test_rejection_or_unlisted_tool_cannot_authorize_rollout(choice):
    from agents.manipulation.decision import select_manipulation_tool, allows
    decision = await select_manipulation_tool(state(), Model(choice), "lerobot.rollout.start", {"session_id": "s"})
    assert not allows(decision)


@pytest.mark.asyncio
async def test_unlisted_evidence_path_is_diagnosed_without_accepting_it():
    from agents.manipulation.decision import select_manipulation_tool, allows
    class BadCitation(Model):
        async def complete(self, task, prompt, **kwargs):
            response = await super().complete(task, prompt, **kwargs)
            request = json.loads(response.text)
            request["evidence_refs"].append("task.execution_evidence.observed=false")
            response.text = json.dumps(request)
            return response
    result = await select_manipulation_tool(state(), BadCitation("return_to_owner"),
                                           "lerobot.rollout.start", {"session_id": "s"})
    assert not allows(result)
    assert "unlisted evidence_refs" in result["error"]


@pytest.mark.asyncio
async def test_required_execution_evidence_cannot_be_replaced_by_model_acceptance():
    from agents.manipulation.decision import review_manipulation_result, allows
    model = Model()
    result = await review_manipulation_result(state(), model, "transfer_to_utm",
        {"session_id": "s", "execution_evidence": {"required": True, "observed": False}},
        {"detected": True}, execution_ended=True, vision_accepted=True)
    assert not allows(result)
    assert model.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "loop", "payload", "spec"])
async def test_inflight_changes_invalidate_selected_skill(change):
    from agents.manipulation.decision import select_manipulation_tool, allows
    s, payload = state(), {"session_id": "s"}
    def mutate():
        if change == "stop": s.stop_requested = True
        if change == "loop": s.loop_count += 1
        if change == "payload": payload["session_id"] = "other"
        if change == "spec": s.current_experiment_spec["specimen_id"] = "other"
    assert not allows(await select_manipulation_tool(s, Model(mutate=mutate), "lerobot.rollout.start", payload))


@pytest.mark.asyncio
async def test_result_review_requires_stopped_execution_and_accepted_vision():
    from agents.manipulation.decision import review_manipulation_result, allows
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
    from agents.manipulation.decision import review_manipulation_result
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
    from agents.manipulation.decision import select_manipulation_tool
    result = await select_manipulation_tool(state(), SimpleNamespace(force_real_llm_in_test=False),
        "lerobot.rollout.start", {"session_id": "s"})
    assert result["status"] == "deterministic_test" and result["llm_used"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [True, False])
async def test_clearance_handoff_requires_manipulation_after_vision(tmp_path, monkeypatch, accept):
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data, ReplayTools
    from utils import utm_clear_cycle as cycle
    from agents.vision.agent import VisionAgent
    from agents.vision import decision as vision_decision
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
    from agents.manipulation.decision import review_manipulation_result, allows
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
    from agents.manipulation.decision import review_manipulation_result, allows
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
    from agents.manipulation.decision import review_manipulation_result
    s = state()
    def cancel(): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await review_manipulation_result(s, Model(mutate=cancel), "placement", {"session_id": "s"},
            {"detected": True}, execution_ended=True, vision_accepted=True)
    assert s.run_metadata["manipulation_decision_cache"] == {}


def test_execution_claim_blocks_duplicate_start_but_not_next_loop():
    from agents.manipulation.decision import claim_skill_execution
    s = state()
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "s"})
    assert not claim_skill_execution(s, "transfer_to_utm", {"session_id": "changed-attempt"})
    s.loop_count += 1
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "s"})


@pytest.mark.asyncio
async def test_same_session_stop_revocation_invalidates_review():
    from agents.manipulation.decision import review_manipulation_result, allows
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
    from agents.manipulation.decision import select_manipulation_tool
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
    from agents.manipulation.decision import review_manipulation_result
    model = Model()
    await review_manipulation_result(state(), model, "placement", {"session_id": "s", "teleop_stop_verified": True,
        "robot_port_released": True, "camera_returned_to_vision": True}, {"detected": True},
        execution_ended=True, vision_accepted=True)
    task = model.calls[0][1]["task"]
    assert task["teleop_stop_verified"] and task["robot_port_released"] and task["camera_returned_to_vision"]
    assert task["required_visual_effect"] == "target_present"


@pytest.mark.asyncio
async def test_rejection_can_cite_specific_task_vision_conflict_without_irrelevant_execution_ref():
    from agents.manipulation.decision import review_manipulation_result
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
