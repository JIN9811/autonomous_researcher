"""Shared chat admission and effective physical-mode regressions; no device I/O."""
from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.bootstrap import load_runtime
from agents.manipulation.agent import ManipulationAgent
from orchestrator.state import Mode, Stage
from tests.unit.test_manipulation_lerobot_agent import _post_specimen_state
from utils.manipulation_profile import normalize_manipulation_agent_profile

pytestmark = pytest.mark.usefixtures("handoff_no_external")


@pytest.mark.parametrize("path", ["physical_print", "installed_printer"])
def test_physical_test_missing_policy_is_blocked_before_tool_call(monkeypatch, path):
    controller = load_runtime()
    state = _post_specimen_state()
    state.mode = Mode.TEST
    state.current_experiment_spec = controller._apply_specimen_printer_choice_to_spec(
        {"confirm_live_execute": True}, path)
    state.current_experiment_spec["test_mode_autofill"] = True
    state.run_metadata["specimen_result"].update(printer_path=path, physical_intent=True)
    profile = normalize_manipulation_agent_profile({"profile_id": "robot", "policy_type": "smolvla",
                                                   "manipulation_strategy": "lerobot_policy"})
    monkeypatch.setattr("agents.manipulation.agent.load_manipulation_agent_profile", lambda: deepcopy(profile))
    agent = ManipulationAgent()
    payload = agent._lerobot_payload(state, "audit", "lerobot_policy")
    result = agent._preflight(state=state, strategy="lerobot_policy", payload=payload,
                             freshness={"fresh": True}, vision_context=agent._vision_observation(state))
    assert payload["runtime_mode"] == "live"
    assert not payload["policy_path"]
    assert result["status"] == "fail"
    assert "live_policy_ref_required" in result["blocking_reasons"]
    assert result["policy_ready"] is False


@pytest.mark.parametrize("explicit", [True, False])
def test_explicit_ejection_choice_survives_saved_default(monkeypatch, explicit):
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    defaults = controller._validated_printer_defaults()
    defaults.update(allow_ejection=not explicit, start_immediately_live=False)
    monkeypatch.setattr(controller, "_validated_printer_defaults", lambda: defaults)
    spec = controller._build_planning_spec(base_spec={"candidate_id": "audit"},
        constraints={"print": {"start_immediately": True}, "ejection": {"enabled": explicit}})
    assert spec["print"]["start_immediately"] is True
    assert spec["ejection"]["enabled"] is explicit


def test_explicit_live_start_enables_normal_ejection_without_changing_idle_defaults(monkeypatch):
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    defaults = controller._validated_printer_defaults()
    defaults.update(allow_ejection=False, start_immediately_live=False)
    monkeypatch.setattr(controller, "_validated_printer_defaults", lambda: defaults)
    idle = controller._build_planning_spec(base_spec={}, constraints={})
    assert idle["print"]["start_immediately"] is False
    assert idle["ejection"]["enabled"] is False
    approved = controller._build_planning_spec(base_spec={}, constraints={"print": {"start_immediately": True}})
    assert approved["ejection"]["enabled"] is True


def test_conditional_manipulation_is_eligible_for_planning_messages():
    controller = load_runtime()
    assert Stage.MANIPULATION in controller._planning_tail_stages(Stage.VISION)


@pytest.fixture
def scenario_controller(monkeypatch):
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._bind_planning_session(None)
    from agents.base_agent import AgentContext
    original = AgentContext.complete
    async def complete(self, task_type, prompt, **kwargs):
        packet = json.loads(prompt)
        if packet.get("operation") == "classify_chat_request":
            return SimpleNamespace(text=json.dumps({"intent": "confirm_pending" if packet.get("pending_id") else "start_run",
                "reason": "Controlled operator intent", "pending_id": packet.get("pending_id")}), model="fixture", raw={})
        return await original(self, task_type, prompt, **kwargs)
    monkeypatch.setattr(AgentContext, "complete", complete)
    async def generate(*, prompt):
        return SimpleNamespace(text=json.dumps({"goal": "Compare specimen energy absorption", "constraints": {
            "geometry_type": "gyroid", "material": "PLA", "specimen_size_mm": [30,30,30]}}), model="fixture", raw={}), "generated"
    monkeypatch.setattr(controller, "_complete_live_planning_prompt", generate)
    return controller


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword,path", [("가상 브릿지", "virtual_bridge"), ("실제 프린터", "installed_printer"), ("실제 출력", "physical_print")])
async def test_generated_scenario_reenters_chat_admission(scenario_controller, monkeypatch, keyword, path):
    controller = scenario_controller
    admitted = []
    async def handoff(*, goal, constraints):
        admitted.append(deepcopy(constraints))
        return {"ok": True}
    monkeypatch.setattr(controller, "_handoff_planning_to_design", handoff)
    result = await controller.planning_message(message=f"테스트 모드, {keyword}")
    # Only model and physical/long-running boundary replaced; the chat classifier,
    # readiness checks, transcript and mode policy construction remain real.
    driver = getattr(controller, "_test_scenario", None)
    if driver and driver.task:
        await asyncio.wait_for(asyncio.shield(driver.task), 3)
    elif controller._planning_handoff_task:
        await asyncio.wait_for(controller._planning_handoff_task, 3)
    automatic = [m for m in controller._planning_messages if m.get("role") == "operator" and m.get("input_source") == "test_scenario"]
    assert automatic, "Scenario must be submitted as operator chat, not a direct Design handoff"
    assert result["ok"] is True
    assert len(admitted) == 1
    assert admitted[0]["printer_test_path"] == path
    assert admitted[0]["print"]["start_immediately"] is (path != "virtual_bridge")
    assert admitted[0]["print"]["use_ejection_only_project_file"] is (path == "installed_printer")
    assert "테스트 모드" in automatic[0]["content"]


@pytest.mark.asyncio
async def test_explicit_experiment_start_resolves_physical_intent(scenario_controller, monkeypatch):
    c = scenario_controller
    defaults = c._validated_printer_defaults()
    defaults.update(start_immediately_live=False, allow_ejection=False)
    monkeypatch.setattr(c, "_validated_printer_defaults", lambda: defaults)
    specs = []
    async def handoff(*, goal, constraints):
        specs.append(c._build_planning_spec(base_spec={}, constraints=constraints))
        return {"ok": True}
    monkeypatch.setattr(c, "_handoff_planning_to_design", handoff)
    await c.planning_message(message="실험 수행", goal="Compare energy absorption", constraints={
        "material": "PLA", "geometry_type": "gyroid", "specimen_size_mm": [30,30,30]})
    assert len(specs) == 1
    assert specs[0]["print"]["start_immediately"] is True
    assert specs[0]["ejection"]["enabled"] is True


@pytest.mark.asyncio
async def test_stale_pending_reply_never_reaches_handoff(scenario_controller, monkeypatch):
    c = scenario_controller
    async def forbidden(**kwargs):
        pytest.fail("Stale input must not enter execution")
    monkeypatch.setattr(c, "_handoff_planning_to_design", forbidden)
    result = await c.planning_message(message="실험 수행", expected_pending_id="obsolete")
    assert result["ok"] is False


def configure_reply_driver(c):
    driver = c._test_scenario
    driver.goal = "Compare energy absorption"
    driver.constraints = {"material": "PLA", "printer_test_path": "virtual_bridge", "confirm_live_execute": True}
    driver.session_id = c._planning_session_id
    c._state.run_metadata["orchestrator_waiting_entry"] = "held-request"
    return driver, c._planning_pending_request()


@pytest.mark.asyncio
async def test_pending_answer_uses_existing_facts_and_shared_chat(scenario_controller, monkeypatch):
    c = scenario_controller
    driver, pending = configure_reply_driver(c)
    queued = []
    async def complete(*, prompt):
        packet = json.loads(prompt)
        assert packet["pending_request"]["pending_id"] == "held-request"
        assert "confirm_live_execute" not in packet["available_scenario_inputs"]
        return SimpleNamespace(text='{"action":"reply","fields":["material"]}'), "reply"
    async def queue(**kwargs):
        queued.append(kwargs)
        return {"ok": True}
    monkeypatch.setattr(c, "_complete_live_planning_prompt", complete)
    monkeypatch.setattr(c, "_queue_runtime_operator_followup", queue)
    assert await driver.answer_pending(pending)
    assert len(queued) == 1
    assert '"material": "PLA"' in queued[0]["message"]
    assert "confirm_live_execute" not in queued[0]["message"]
    assert any(m.get("input_source") == "test_scenario" for m in c._planning_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stale", "stop", "invented", "wait", "physical_confirmation"])
async def test_unsafe_or_outdated_auto_answers_are_not_submitted(scenario_controller, monkeypatch, case):
    c = scenario_controller
    driver, pending = configure_reply_driver(c)
    if case == "physical_confirmation":
        pending = {"kind": "specimen", "pending_id": "transfer", "request": {"type": "operator_teleop"}}
    async def complete(*, prompt):
        if case == "stale":
            c._state.run_metadata["orchestrator_waiting_entry"] = "different"
        if case == "stop":
            c._state.stop_requested = True
        return SimpleNamespace(text=json.dumps({"action": "wait" if case == "wait" else "reply",
            "fields": ["transfer_complete"] if case == "invented" else ["material"]})), "reply"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", complete)
    assert not await driver.answer_pending(pending)
    assert not [m for m in c._planning_messages if m.get("input_source") == "test_scenario"]


@pytest.mark.asyncio
async def test_reset_cancels_queued_automatic_input(scenario_controller):
    c = scenario_controller
    await c._planning_request_lock.acquire()
    driver = c._test_scenario
    assert driver.start(goal="test", constraints={})
    assert not driver.start(goal="duplicate", constraints={})
    c._reset_planning_transcript()
    c._planning_request_lock.release()
    await asyncio.gather(driver.task, return_exceptions=True)
    assert driver.status == "stopped"
    assert not [m for m in c._planning_messages if m.get("input_source") == "test_scenario"]


@pytest.mark.asyncio
async def test_pending_reply_classified_as_new_run_is_rejected(scenario_controller, monkeypatch):
    c = scenario_controller
    _, pending = configure_reply_driver(c)
    from agents.base_agent import AgentContext
    async def misclassified(*args, **kwargs):
        return SimpleNamespace(text='{"intent":"start_run","reason":"fixture","pending_id":null}', model="fixture", raw={})
    monkeypatch.setattr(AgentContext, "complete", misclassified)
    result = await c.planning_message(message="existing scenario", expected_pending_id=pending["pending_id"])
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_explicit_test_start_after_previous_stop_can_reach_shared_admission(scenario_controller, monkeypatch):
    c = scenario_controller
    c._state.stop_requested = True
    admitted = []
    async def handoff(**kwargs):
        admitted.append(kwargs)
        return {"ok": True}
    monkeypatch.setattr(c, "_handoff_planning_to_design", handoff)
    await c.planning_message(message="테스트 모드, 가상 브릿지")
    await asyncio.wait_for(c._test_scenario.task, 3)
    assert len(admitted) == 1


@pytest.mark.asyncio
async def test_normal_experiment_does_not_inherit_previous_auto_test_policy(scenario_controller, monkeypatch):
    c = scenario_controller
    old = c._apply_specimen_printer_choice_to_spec({"test_mode_autofill": True}, "installed_printer")
    c._record_planning_message({"role": "operator", "content": "previous automatic scenario",
                               "input_source": "test_scenario", "constraints": old})
    admitted = []
    async def handoff(**kwargs):
        admitted.append(kwargs["constraints"])
        return {"ok": True}
    monkeypatch.setattr(c, "_handoff_planning_to_design", handoff)
    await c.planning_message(message="실험 수행", goal="Compare energy absorption", constraints={
        "material": "PLA", "geometry_type": "gyroid", "specimen_size_mm": [30,30,30]})
    assert len(admitted) == 1
    assert not admitted[0].get("test_mode_autofill")
    assert not admitted[0].get("printer_test_path")
    assert not admitted[0].get("print", {}).get("use_ejection_only_project_file")


@pytest.mark.asyncio
async def test_automatic_replies_follow_run_allocated_by_shared_admission(scenario_controller, monkeypatch):
    c = scenario_controller
    release, observed = asyncio.Event(), asyncio.Event()
    generate = c._complete_live_planning_prompt
    async def complete(*, prompt):
        if '"operation": "test_scenario_reply"' in prompt:
            observed.set()
            return SimpleNamespace(text='{"action":"wait","fields":[]}'), "wait"
        return await generate(prompt=prompt)
    async def handoff(**kwargs):
        # Shared admission allocates a run when activating a setup snapshot.
        c._state.run_id = "newly-admitted-run"
        c._state.run_metadata["orchestrator_waiting_entry"] = "new-run-question"
        await release.wait()
        return {"ok": True}
    monkeypatch.setattr(c, "_complete_live_planning_prompt", complete)
    monkeypatch.setattr(c, "_handoff_planning_to_design", handoff)
    await c.planning_message(message="테스트 모드, 가상 브릿지")
    try:
        await asyncio.wait_for(observed.wait(), 5)
    finally:
        release.set()
        await asyncio.wait_for(c._test_scenario.task, 2)


@pytest.mark.asyncio
async def test_repeated_start_keeps_same_input_task(scenario_controller):
    c = scenario_controller
    await c.planning_message(message="테스트 모드, 가상 브릿지")
    task = c._test_scenario.task
    # Hold it at the chat lock while the second identical command arrives.
    await c._planning_request_lock.acquire()
    try:
        result = await c.planning_message(message="테스트 모드, 가상 브릿지")
        assert result["ok"] is True
        assert not task.cancelling()
        assert c._test_scenario.task is task
    finally:
        c._test_scenario.cancel()
        c._planning_request_lock.release()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_fast_deferred_admission_then_runtime_question_stays_automatic(scenario_controller, monkeypatch):
    c = scenario_controller
    released = asyncio.Event()
    runtime_answered = asyncio.Event()
    calls = []
    generate = c._complete_live_planning_prompt
    async def complete(*, prompt):
        if '"operation": "test_scenario_reply"' in prompt:
            return SimpleNamespace(text='{"action":"reply","fields":["material"]}'), "reply"
        return await generate(prompt=prompt)
    async def handoff(*, goal, constraints, new_series=True):
        calls.append(new_series)
        if new_series:
            c._state.run_id = "own-fast-admission"
            c._state.run_metadata["orchestrator_planning_boundary"] = {
                "status": "deferred", "task_id": "first-question", "goal": goal,
                "constraints": constraints}
            return {"ok": True, "pending": True}
        c._state.run_metadata.pop("orchestrator_planning_boundary")
        c._state.run_metadata["orchestrator_waiting_entry"] = "second-question"
        await released.wait()
        return {"ok": True}
    async def queue(**kwargs):
        runtime_answered.set()
        released.set()
        c._state.run_metadata.pop("orchestrator_waiting_entry", None)
        return {"ok": True}
    monkeypatch.setattr(c, "_complete_live_planning_prompt", complete)
    monkeypatch.setattr(c, "_handoff_planning_to_design", handoff)
    monkeypatch.setattr(c, "_queue_runtime_operator_followup", queue)
    await c.planning_message(message="테스트 모드, 가상 브릿지")
    try:
        try:
            await asyncio.wait_for(runtime_answered.wait(), 15)
        except TimeoutError:
            pytest.fail(str({"calls": calls, "driver_status": c._test_scenario.status,
                "run_id": c._state.run_id, "admitted_run_id": c._test_scenario.admission_run_id,
                "pending": c._planning_pending_request(),
                "messages": [(m.get("role"), str(m.get("content"))[:250]) for m in c._planning_messages[-5:]]}))
        assert calls == [True, False]
    finally:
        released.set()
        c._test_scenario.cancel()
        await asyncio.gather(c._test_scenario.task, return_exceptions=True)
        if c._planning_handoff_task:
            await asyncio.gather(c._planning_handoff_task, return_exceptions=True)
