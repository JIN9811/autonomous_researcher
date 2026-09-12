"""Behavior at durable handoff boundaries; no owner execution doubles."""
import pytest
import asyncio
import json
from types import SimpleNamespace
import socket
import subprocess

from orchestrator import orchestrator_checkpoint as checkpoints


@pytest.fixture(autouse=True)
def deny_external(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Unlisted external effect in checkpoint tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    from agents.analysis_runtime import AnalysisRuntimeService
    monkeypatch.setattr(AnalysisRuntimeService, "resume", lambda *args, **kwargs: None)


def test_consumption_is_once_and_payload_is_detached():
    metadata = {}
    payload = {"next_stage": "design", "result": {"value": 1}}
    checkpoints.handoff_checkpoint(metadata, "run:1:result", action="prepare", payload=payload)
    payload["result"]["value"] = 99
    first = checkpoints.handoff_checkpoint(metadata, "run:1:result", action="consume")
    second = checkpoints.handoff_checkpoint(metadata, "run:1:result", action="consume")
    assert first["consume_now"] is True
    assert second["consume_now"] is False
    assert first["payload"]["result"] == {"value": 1}


def _planning_boundary_controller(tmp_path, responses):
    from app.controller import MainController, ControllerDeps
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.registry import AgentRegistry
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    calls = []
    async def complete(task, prompt, **kwargs):
        packet = json.loads(prompt)
        if packet.get("operation") == "classify_chat_request":
            assert packet["message"] == "Reviewed; please continue"
            return SimpleNamespace(model="controlled", text=json.dumps({"intent": "confirm_pending",
                "reason": "Explicit held-review continuation", "pending_id": packet["pending_id"]}))
        calls.append(packet)
        tool = responses[min(len(calls) - 1, len(responses) - 1)]
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": tool,
            "arguments": {"condition": "reply"} if tool == "defer" else {"candidate": "design"},
            "reason": "reviewed planning input", "evidence_refs": ["boundary:result"]}))
    controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(complete=complete, active_backend="controlled"), run_root=tmp_path / "runs",
        logging_config={}, system_config={}, runtime_profile={}))
    return controller, calls


@pytest.mark.parametrize("profile", ["virtual_bridge", "installed_printer", "physical_print"])
def test_initial_planning_reply_resumes_same_task_and_records_consumed_packet(tmp_path, monkeypatch, profile):
    controller, calls = _planning_boundary_controller(tmp_path, ["defer", "prepare_handoff"])
    design_entries = []
    async def stop_before_design(**kwargs):
        design_entries.append(kwargs)
        raise RuntimeError("test owner boundary stop")
    monkeypatch.setattr(controller, "_run_planning_design_stage", stop_before_design)
    constraints = controller._apply_specimen_printer_choice_to_spec({"test_mode_autofill": True}, profile)
    async def run():
        first = await controller._handoff_planning_to_design(goal="goal", constraints=constraints)
        assert first["status"] == "deferred"
        context = controller._state.run_metadata["orchestrator_planning_boundary"]
        task_id = context["task_id"]
        await controller._planning_message_locked(message="Reviewed; please continue", goal=None, constraints={}, session_id=None)
        assert len(calls) == 2
        assert len(design_entries) == 1
        assert controller._state.run_metadata["orchestrator_planning_boundary"]["task_id"] == task_id
        decision = controller._state.run_metadata["orchestrator_checkpoints"][context["key"]]["payload"]["decision"]
        assert controller._state.run_metadata["latest_orchestrator_handoff"] == decision["effect"]
        assert controller._state.run_metadata["latest_orchestrator_decision"]["decision_id"] == decision["decision_id"]
        assert calls[-1]["context"]["request"]["operator_followups"][-1]["message"] == "Reviewed; please continue"
    asyncio.run(run())


def test_new_planning_attempt_does_not_reuse_consumed_admission(tmp_path, monkeypatch):
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    entries = []
    async def stopped(**kwargs):
        entries.append(kwargs)
        raise RuntimeError("test owner boundary stop")
    monkeypatch.setattr(controller, "_run_planning_design_stage", stopped)
    async def run():
        original = controller._state.run_id
        await controller._handoff_planning_to_design(goal="first", constraints={})
        await controller._handoff_planning_to_design(goal="second", constraints={})
        assert len(entries) == 2
        assert len(calls) == 2
        assert controller._state.run_id == original
    asyncio.run(run())


def test_pre_design_recovery_never_activates_pending_next_run_setup(tmp_path, monkeypatch):
    controller, calls = _planning_boundary_controller(tmp_path, ["defer"])
    monkeypatch.setattr(controller, "_capture_pending_setup", lambda: (object(), ["next-run-only"]))
    async def forbidden(*args):
        pytest.fail("Recovery activated next-run setup")
    monkeypatch.setattr(controller, "_activate_captured_setup", forbidden)
    original = controller._state
    async def run():
        await controller._resume_planning_handoff_from_context({"goal": "interrupted", "current_spec": {}, "design_constraints": {}})
        assert controller._state is original
    asyncio.run(run())


def test_admitted_planning_cancel_before_design_resumes_without_new_admission(tmp_path, monkeypatch):
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    original_append = controller._append_planning_message
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(controller, "_append_planning_message", cancelled)
    entries = []
    async def stopped(**kwargs):
        entries.append(kwargs)
        raise RuntimeError("owner boundary reached")
    monkeypatch.setattr(controller, "_run_planning_design_stage", stopped)
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await controller._handoff_planning_to_design(goal="goal", constraints={})
        monkeypatch.setattr(controller, "_append_planning_message", original_append)
        await controller._resume_planning_handoff_from_context({"goal": "goal", "current_spec": {}, "design_constraints": {}})
        assert len(entries) == 1
        assert len(calls) == 1
    asyncio.run(run())


def test_cancelled_initial_planning_model_keeps_reply_resume_marker(tmp_path):
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()
    controller._deps.agent_context.complete = cancelled
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await controller._handoff_planning_to_design(goal="goal", constraints={})
        assert controller._state.run_metadata["orchestrator_planning_boundary"]["status"] == "deferred"
    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["goal", "constraints"])
def test_planning_latency_rejects_changed_admitted_inputs(tmp_path, mutation):
    from orchestrator.handoff_boundary import review_handoff
    controller, _ = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    state = controller._state
    state.active_goal = "initial"
    payload = {"goal": "initial", "constraints": {"size": 1}}
    async def complete(*args, **kwargs):
        if mutation == "goal":
            state.active_goal = "changed"
        else:
            payload["constraints"]["size"] = 2
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": "design"}, "reason": "old input", "evidence_refs": ["boundary:result"]}))
    async def run():
        record = await review_handoff(state=state, ctx=SimpleNamespace(complete=complete),
            registry=controller._deps.agent_registry, catalog=controller._run_owner_catalog(),
            key="latency", candidate="design", payload=payload, settings={})
        assert record["status"] == "deferred"
    asyncio.run(run())


@pytest.mark.parametrize("consumed", [False, True])
@pytest.mark.parametrize("changed", ["goal", "request"])
def test_cached_authorization_rejects_goal_or_scope_changes(tmp_path, consumed, changed):
    from orchestrator.handoff_boundary import review_handoff
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    async def run():
        kwargs = dict(state=controller._state, ctx=controller._deps.agent_context,
            registry=controller._deps.agent_registry, catalog=controller._run_owner_catalog(),
            key="cached", candidate="design", payload={"input": "fixed"}, settings={})
        assert (await review_handoff(**kwargs))["status"] == "prepared"
        if consumed:
            checkpoints.handoff_checkpoint(controller._state.run_metadata, "cached", action="consume")
        if changed == "goal":
            controller._state.active_goal = "different goal"
        else:
            kwargs["payload"]["input"] = "different planning request"
        assert (await review_handoff(**kwargs))["status"] not in {"prepared", "consumed"}
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["goal", "setup", "specimen", "availability", "policy"])
def test_runtime_incoming_authorization_rechecks_scope(tmp_path, mutation):
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff", "defer"])
    state = controller._state
    state.stage = Stage.DESIGN
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        assert await runtime._review_stage_entry(Stage.DESIGN)
        state.run_metadata["orchestrator_incoming_handoff"] = {"key": state.run_metadata["orchestrator_stage_entry_key"],
            "run_id": state.run_id, "loop": state.loop_count, "stage": "design"}
        if mutation == "goal":
            state.active_goal = "changed"
        elif mutation == "specimen":
            state.current_experiment_spec = {"cell_size_mm": 99}
        else:
            key = {"setup": "experimental_setup_snapshot", "availability": "availability_reports", "policy": "execution_policy"}[mutation]
            state.run_metadata[key] = {"changed": True}
        assert not await runtime._review_stage_entry(Stage.DESIGN)
        assert len(calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize("mutation", [None, "constraints", "previous_spec"])
def test_planning_input_materialization_keeps_one_admission(tmp_path, monkeypatch, mutation):
    from orchestrator.handoff_boundary import review_handoff
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff", "defer"])
    async def enter(stage, **kwargs):
        runtime = LangGraphRunLoop(state=controller._state, agent_registry=controller._deps.agent_registry,
            orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
            logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
        assert await runtime._review_stage_entry(Stage.DESIGN) is (mutation is None)
        assert len(calls) == (1 if mutation is None else 2)
        raise RuntimeError("checked actual materialization boundary")
    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", enter)
    async def run():
        state = controller._state
        record = await review_handoff(state=state, ctx=controller._deps.agent_context,
            registry=controller._deps.agent_registry, catalog=controller._run_owner_catalog(),
            key="materialize", candidate="design", payload={"constraints": {"cell_size_mm": 7}}, settings={})
        checkpoints.handoff_checkpoint(state.run_metadata, "materialize", action="consume")
        state.run_metadata["orchestrator_incoming_handoff"] = {"key": "materialize", "run_id": state.run_id,
            "loop": state.loop_count, "stage": "design"}
        with pytest.raises(RuntimeError, match="checked actual materialization boundary"):
            await controller._run_planning_design_stage(previous_spec={"size": 99} if mutation == "previous_spec" else {},
                design_constraints={"cell_size_mm": 99 if mutation == "constraints" else 7},
                cycle_index=1, total_cycles=1, emit_handoff=False)
    asyncio.run(run())


def test_planning_awaited_events_cannot_change_pinned_materialization_inputs(tmp_path, monkeypatch):
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    original_constraints = {"cell_size_mm": 7}
    original_spec = {"size": 1}
    controller._state.current_experiment_spec = original_spec
    original_append = controller._append_planning_message
    async def mutate_during_event(*args, **kwargs):
        original_constraints["cell_size_mm"] = 99
        original_spec["size"] = 99
        await original_append(*args, **kwargs)
    monkeypatch.setattr(controller, "_append_planning_message", mutate_during_event)
    observed = []
    async def observe(**kwargs):
        observed.append(kwargs)
        raise RuntimeError("bounded caller input check")
    monkeypatch.setattr(controller, "_run_planning_design_stage", observe)
    async def run():
        await controller._handoff_planning_to_design(goal="goal", constraints=original_constraints)
        assert observed[0]["design_constraints"]["cell_size_mm"] == 7
        assert observed[0]["previous_spec"] == {"size": 1}
    asyncio.run(run())


@pytest.mark.parametrize("pending_result", [False, True])
def test_explicit_observation_refresh_dispatch_retires_only_stale_handoff(tmp_path, pending_result):
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    state = controller._state
    state.current_experiment_spec = {"specimen_id": "specimen"}
    state.stage = Stage.VISION
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        calls.append(request)
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
            "reason": "review before capture", "evidence_refs": ["boundary:result"]}))
    controller._deps.agent_context.complete = complete
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        assert await runtime._review_stage_entry(Stage.VISION)
        state.stage = Stage.EQUIPMENT
        await controller._queue_runtime_operator_followup(message="What happened?", goal=None, constraints={}, session_id=None)
        await runtime._drain_operator_followups(stage=Stage.EQUIPMENT, phase="pre_stage")
        assert await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert len(calls) == 1  # discussion is not an execution-input change
        physical_result = {"ok": True, "handoff_status": "needs_post_place_vision", "session_id": "physical-completed"}
        state.run_metadata["manipulation_result"] = dict(physical_result)
        state.active_goal = "updated execution task"
        if pending_result:
            checkpoints.handoff_checkpoint(state.run_metadata, "physical-result", action="prepare", payload={
                "stage": "manipulation", "next_stage": "vision", "result_data": {"manipulation_result": physical_result},
                "reuse_observation_task": True, "selected_transition": {}, "transition_candidates": [], "guardian_context": {}})
            state.run_metadata["orchestrator_pending_handoff"] = "physical-result"
            state.stage = Stage.MANIPULATION
            await runtime.step()
        else:
            assert not await runtime._review_stage_entry(Stage.EQUIPMENT)
        held = dict(state.run_metadata["orchestrator_observation_refresh"])
        assert held["status"] == "waiting"
        assert len(calls) == 1
        request = {"action": "refresh_observation", "held_checkpoint": held["held_checkpoint"], **held["scope"]}
        await controller._queue_runtime_operator_followup(message="Please refresh this held observation", goal=None,
            constraints={"orchestrator_action": request}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.VISION
        assert state.run_metadata["manipulation_result"] == physical_result
        assert not state.run_metadata.get("orchestrator_pending_handoff")
        if pending_result:
            saved = checkpoints.handoff_checkpoint(state.run_metadata, "physical-result", action="read")
            assert saved["status"] == "consumed"
            assert saved["payload"]["result_data"]["manipulation_result"] == physical_result
            assert not checkpoints.handoff_checkpoint(state.run_metadata, "physical-result", action="consume")["consume_now"]
        assert await runtime._review_stage_entry(Stage.VISION)
        assert len(calls) == 2  # only now, before NEW capture
        state.run_metadata["vision_signal"] = {"fresh": True}
        assert await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert len(calls) == 2
    asyncio.run(run())


def test_refresh_runs_actual_clearance_vision_without_replaying_manipulation(tmp_path, monkeypatch):
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    from mcp_tools.tool_registry import ToolRegistry
    from utils.utm_clear_cycle import scope
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    state = controller._state
    state.stage = Stage.VISION
    state.current_experiment_spec = {"specimen_id": "s", "execution_policy": {
        "manipulation": "virtual", "vision": "virtual", "lab_equipment": "virtual"}}
    controller._deps.agent_context.tools = ToolRegistry()
    trace = []
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        trace.append("orchestrator")
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
            "reason": "review before capture", "evidence_refs": ["boundary:result"]}))
    controller._deps.agent_context.complete = complete
    for agent in (ManipulationAgent(), VisionAgent()):
        original = agent.run
        name = agent.name
        async def tracked(*args, _run=original, _name=name, **kwargs):
            trace.append(_name)
            result = await _run(*args, **kwargs)
            trace.append(_name + ":completed")
            return result
        monkeypatch.setattr(agent, "run", tracked)
        controller._deps.agent_registry.register(agent)
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        assert await runtime._review_stage_entry(Stage.VISION)
        state.stage = Stage.MANIPULATION
        state.run_metadata["utm_verifications"] = scope(state)
        state.run_metadata["utm_clear_execution"] = {**scope(state), "session_id": "completed-clear",
            "state": "requested", "task_id": "clear_utm_to_disposal"}
        # Execute the actual existing virtual-clear owner once, then model its
        # already-saved result boundary (no professional-agent replacement).
        result = await controller._deps.agent_registry.get("manipulation_agent").run(state, controller._deps.agent_context)
        runtime._merge_agent_data(Stage.MANIPULATION, result.data)
        assert state.run_metadata["utm_clear_execution"]["replay_home_verified"]
        completed_loop = state.loop_count
        completed_retries = dict(state.retry_counters)
        checkpoints.handoff_checkpoint(state.run_metadata, "completed-clear-result", action="prepare", payload={
            "stage": "manipulation", "next_stage": "vision", "result_data": result.data,
            "reuse_observation_task": True, "selected_transition": {}, "transition_candidates": [], "guardian_context": {}})
        state.run_metadata["orchestrator_pending_handoff"] = "completed-clear-result"
        state.active_goal = "revised task"
        await runtime.step()
        held = state.run_metadata["orchestrator_observation_refresh"]
        await runtime.step()  # polling never recaptures or replays
        assert trace.count("manipulation_agent") == 1 and trace.count("vision_agent") == 0
        action = {"action": "refresh_observation", "held_checkpoint": held["held_checkpoint"], **held["scope"]}
        await controller._queue_runtime_operator_followup(message="Explain the hold", goal=None, constraints={}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.MANIPULATION
        await controller._queue_runtime_operator_followup(message="Wrong task refresh", goal=None,
            constraints={"orchestrator_action": {**action, "held_checkpoint": "wrong"}}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.MANIPULATION
        await controller._queue_runtime_operator_followup(message="Refresh clearance observation", goal=None,
            constraints={"orchestrator_action": action}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.VISION
        await runtime.step()
        assert trace.count("manipulation_agent") == 1
        assert trace.count("vision_agent") == 1
        assert state.loop_count == completed_loop and state.retry_counters == completed_retries
        assert state.run_metadata["utm_clear_execution"]["state"] == "done"
        assert state.run_metadata["utm_clear_execution"]["session_id"] == "completed-clear"
        assert state.run_metadata["utm_verifications"]["verification_2"]["confirmed"] is True
        assert trace[trace.index("vision_agent") - 1] == "orchestrator"
        assert trace[trace.index("vision_agent") + 1] == "vision_agent:completed"
        await controller._queue_runtime_operator_followup(message="Duplicate refresh", goal=None,
            constraints={"orchestrator_action": action}, session_id=None)
        replies = await runtime._drain_operator_followups(stage=state.stage, phase="pre_stage")
        assert not runtime._apply_observation_refresh(replies)
        assert trace.count("vision_agent") == 1
    asyncio.run(run())


def test_refresh_preserves_actual_post_place_vision_branch(tmp_path, monkeypatch):
    from agents.vision_agent import VisionAgent
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    from mcp_tools.tool_registry import ToolRegistry
    from PIL import Image
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    state = controller._state
    state.stage = Stage.VISION
    state.current_experiment_spec = {"specimen_id": "s"}
    state.run_metadata["specimen_result"] = {"ok": True, "specimen_id": "s", "handoff_status": "ready"}
    tools = ToolRegistry()
    controller._deps.agent_context.tools = tools
    capture_requests = []
    interlock = {"session_id": "placed", "ungrasping_seen": True, "home_after_ungrasping": True, "ready_for_utm_snapshot": True}
    state.run_metadata["manipulation_result"] = {"ok": True, "session_id": "placed", "specimen_id": "s",
        "runtime_phase": "ACTION_ACTIVE", "action_count": 30, "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete", "post_place_interlock": interlock}
    frame = tmp_path / "frame.png"
    Image.new("RGB", (160, 120), "red").save(frame)
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    for name in ("vision.utm_runtime.start", "vision.utm_runtime.status"):
        tools.register(name, lambda payload: {"ok": True, "status": "running", "source": "controlled_test_io"})
    tools.register("lerobot.rollout.status", lambda payload: {"ok": True, "session_id": "placed", "status": "RUNNING",
        "post_place_interlock": interlock, "runtime_phase": "ACTION_ACTIVE", "action_count": 30})
    tools.register("lerobot.rollout.stop", lambda payload: {"ok": True, "status": "STOPPED", "session_id": "placed"})
    tools.register("vision.utm_specimen_presence.capture", lambda payload: capture_requests.append(dict(payload)) or {
        "ok": True, "status": "confirmed", "detected": True, "source": "controlled_test_io", "confidence": 0.95,
        "session_id": "placed", "specimen_id": "s", "frame_id": payload["frame_id"], "bbox_xyxy": [20, 30, 90, 110],
        "annotated_frame_path": str(frame), "raw_frame_path": str(frame), "width": 160, "height": 120})
    async def complete(task, prompt, **kwargs):
        if task != "orchestrator_plan":
            return SimpleNamespace(text="Controlled protocol note", raw={}, model="controlled")
        request = json.loads(prompt)
        calls.append((request, len(capture_requests)))
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
            "reason": "review before capture", "evidence_refs": ["boundary:result"]}))
    controller._deps.agent_context.complete = complete
    controller._deps.agent_registry.register(VisionAgent())
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        assert await runtime._review_stage_entry(Stage.VISION)
        state.stage = Stage.EQUIPMENT
        state.active_goal = "updated request"
        assert not await runtime._review_stage_entry(Stage.EQUIPMENT)
        held = state.run_metadata["orchestrator_observation_refresh"]
        await controller._queue_runtime_operator_followup(message="Refresh post-place observation", goal=None,
            constraints={"orchestrator_action": {"action": "refresh_observation", "held_checkpoint": held["held_checkpoint"], **held["scope"]}}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.VISION
        await runtime.step()
        assert len(capture_requests) == 1
        assert capture_requests[0]["session_id"] == "placed"
        assert state.run_metadata["vision_report"]["task"] == "post_manipulation_utm_verification"
        assert calls[-1][1] == 0  # both Orchestrator calls precede fresh capture
        assert state.run_metadata["manipulation_result"]["session_id"] == "placed"
    asyncio.run(run())


@pytest.mark.parametrize("pending_result", [False, True])
@pytest.mark.parametrize("queued_at_restoration", [False, True])
def test_natural_observation_resume_rejects_delayed_refresh_after_analysis_progress(tmp_path, monkeypatch, pending_result, queued_at_restoration):
    from agents.analysis_agent import AnalysisAgent
    from agents.equipment_agent import LabEquipmentAgent
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage
    from logging_system.structured_logger import StructuredLogger
    controller, calls = _planning_boundary_controller(tmp_path, ["prepare_handoff"])
    controller._deps.agent_registry.register(AnalysisAgent())
    controller._deps.agent_registry.register(LabEquipmentAgent())
    state = controller._state
    state.stage = Stage.VISION
    state.current_experiment_spec = {"specimen_id": "s"}
    state.active_goal = "A"
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        calls.append(request)
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
            "reason": "bounded admission", "evidence_refs": ["boundary:result"]}))
    controller._deps.agent_context.complete = complete
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name="orchestrator_agent", ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def pending_analysis_approval(**kwargs):
        return False  # Existing downstream owner gate; no Analysis work in this lifecycle test.
    monkeypatch.setattr(runtime, "_module_approval_ready", pending_analysis_approval)
    def result_boundary(key, stage, next_stage, reuse):
        from policies.guardian_gate import guardian_gate
        completed = {"completed": True}
        gate = guardian_gate(state=state, stage=stage, phase="post", payload=completed)
        checkpoints.handoff_checkpoint(state.run_metadata, key, action="prepare", payload={
            "stage": stage, "next_stage": next_stage, "result_data": completed,
            "reuse_observation_task": reuse, "selected_transition": {}, "transition_candidates": [], "guardian_context": gate})
        state.run_metadata["orchestrator_pending_handoff"] = key
    async def run():
        assert await runtime._review_stage_entry(Stage.VISION)
        state.active_goal = "B"
        if pending_result:
            result_boundary("vision-done", "vision", "equipment", True)
            await runtime.step()
        else:
            state.stage = Stage.EQUIPMENT
            assert not await runtime._review_stage_entry(Stage.EQUIPMENT)
        held = dict(state.run_metadata["orchestrator_observation_refresh"])
        action = {"action": "refresh_observation", "held_checkpoint": held["held_checkpoint"], **held["scope"]}
        state.active_goal = "A"  # Restore the original admitted inputs, not a manual recovery reset.
        if queued_at_restoration:
            await controller._queue_runtime_operator_followup(message="Old action already queued", goal=None,
                constraints={"orchestrator_action": action}, session_id=None)
            await runtime.step()
            assert state.stage == Stage.EQUIPMENT
        if pending_result:
            if not queued_at_restoration:
                await runtime.step()
            assert state.stage == Stage.EQUIPMENT
        else:
            assert await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert state.run_metadata["orchestrator_observation_refresh"]["status"] == "retired"
        result_boundary("equipment-done", "equipment", "analysis", False)
        await runtime.step()
        assert state.stage == Stage.ANALYSIS
        before_calls = len(calls)
        await controller._queue_runtime_operator_followup(message="Delayed old refresh", goal=None,
            constraints={"orchestrator_action": action}, session_id=None)
        await runtime.step()
        assert state.stage == Stage.ANALYSIS
        assert len(calls) == before_calls
        assert checkpoints.handoff_checkpoint(state.run_metadata, "equipment-done", action="read")["status"] == "consumed"
    asyncio.run(run())


def test_defer_retains_completed_result_until_explicit_prepare():
    metadata = {}
    checkpoints.handoff_checkpoint(metadata, "result", action="prepare", payload={"next_stage": "design"})
    checkpoints.handoff_checkpoint(metadata, "result", action="defer", payload={"condition": "owner reply"})
    assert checkpoints.handoff_checkpoint(metadata, "result", action="consume")["consume_now"] is False
    waiting = checkpoints.handoff_checkpoint(metadata, "result", action="read")
    assert waiting["status"] == "deferred"
    assert waiting["payload"]["next_stage"] == "design"
    checkpoints.handoff_checkpoint(metadata, "result", action="prepare")
    assert checkpoints.handoff_checkpoint(metadata, "result", action="consume")["consume_now"] is True
    checkpoints.handoff_checkpoint(metadata, "result", action="prepare", payload={"next_stage": "specimen"})
    assert checkpoints.handoff_checkpoint(metadata, "result", action="consume")["consume_now"] is False


def test_missing_consume_and_invalid_payload_cannot_authorize_effect():
    metadata = {}
    assert checkpoints.handoff_checkpoint(metadata, "absent", action="consume")["consume_now"] is False
    with pytest.raises((ValueError, TypeError)):
        checkpoints.handoff_checkpoint(metadata, "bad", action="prepare", payload={"callback": lambda: None})
    assert "bad" not in metadata.get("orchestrator_checkpoints", {})


def test_declared_but_missing_orchestrator_does_not_execute_design(tmp_path):
    from agents.design_agent import DesignAgent
    from agents.registry import AgentRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Stage, Mode
    from logging_system.structured_logger import StructuredLogger
    registry = AgentRegistry()
    registry.register(DesignAgent())
    state = OrchestratorState(run_id="missing-owner", experiment_id="exp", mode=Mode.TEST, stage=Stage.DESIGN)
    runtime = LangGraphRunLoop(state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent", ctx=object(),
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    asyncio.run(runtime.step())
    assert state.stage == Stage.DESIGN
    assert state.run_metadata["orchestrator_waiting_entry"]
    assert not state.current_experiment_spec
    assert not state.run_metadata.get("design_agent_payload")


def test_overlay_only_orchestrator_is_visible_but_not_a_runtime_participant(tmp_path, monkeypatch):
    import shutil
    import yaml
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.registry import AgentRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Stage, Mode
    from logging_system.structured_logger import StructuredLogger
    shutil.copytree("graphs/modules", tmp_path / "modules")
    design = tmp_path / "modules/design/module.yaml"
    document = yaml.safe_load(design.read_text())
    document["module"]["pre_execution"] = []
    design.write_text(yaml.safe_dump(document))
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    state = OrchestratorState(run_id="overlay-only", experiment_id="exp", mode=Mode.TEST, stage=Stage.DESIGN)
    async def complete(*args, **kwargs):
        pytest.fail("Overlay visibility cannot authorize invocation")
    runtime = LangGraphRunLoop(state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        ctx=SimpleNamespace(complete=complete), module_root=tmp_path,
        logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    assert any(row["owner"] == "orchestrator_agent" and row["role"] == "overlay"
               for row in runtime._owner_catalog.describe(state, None))
    assert asyncio.run(runtime._review_stage_entry(Stage.DESIGN)) is True
    assert not state.run_metadata.get("orchestrator_checkpoints")
    from app.controller import MainController, ControllerDeps
    controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(complete=complete, active_backend="controlled"), run_root=tmp_path / "runs",
        logging_config={}, system_config={}, runtime_profile={}))
    monkeypatch.setattr(controller, "_run_owner_catalog", lambda: runtime._owner_catalog)
    controller._execution_orchestrator_settings = {}
    async def reached_existing_flow(*args, **kwargs):
        raise RuntimeError("existing planning flow reached")
    monkeypatch.setattr(controller, "_append_planning_message", reached_existing_flow)
    with pytest.raises(RuntimeError, match="existing planning flow reached"):
        asyncio.run(controller._handoff_planning_to_design(goal="goal", constraints={}))
    assert not controller._state.run_metadata.get("orchestrator_checkpoints")


def test_controller_pins_decision_settings_with_owner_catalog(monkeypatch):
    from app.controller import MainController
    from agents.registry import AgentRegistry
    from agents.orchestrator_agent import OrchestratorAgent
    from orchestrator.state import OrchestratorState
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    controller = MainController.__new__(MainController)
    controller._deps = SimpleNamespace(agent_registry=registry, agent_context=object(), orchestrator_agent_name="orchestrator_agent")
    controller._state = OrchestratorState(run_id="settings", experiment_id="exp")
    controller._active_graph_config_path = None
    current = {"max_steps": 2}
    monkeypatch.setattr("app.controller.load_module_config", lambda path: SimpleNamespace(
        model_dump=lambda **kwargs: {"handler": "agent.orchestrator_agent", "decision_settings": dict(current)}))
    controller._run_owner_catalog()
    assert controller._execution_orchestrator_settings == {"max_steps": 2}
    current["max_steps"] = 8
    controller._run_owner_catalog()
    assert controller._execution_orchestrator_settings == {"max_steps": 2}
    controller._state.run_id = "next"
    controller._run_owner_catalog()
    assert controller._execution_orchestrator_settings == {"max_steps": 8}


def test_real_orchestrator_boundary_defers_without_recalling_model_until_reply(tmp_path):
    # Removing the checkpoint's wait fingerprint would turn each runtime tick
    # into another model invocation, even though the completed owner is unchanged.
    from orchestrator import handoff_boundary
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from graphs import load_graph_config
    from orchestrator.state import OrchestratorState, Mode, Stage
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    catalog = OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml")).snapshot()
    state = OrchestratorState(run_id="boundary", experiment_id="exp", mode=Mode.TEST, stage=Stage.BO)
    calls = []
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        calls.append(request)
        tool, arguments = ("defer", {"condition": "operator reply"}) if len(calls) == 1 else ("prepare_handoff", {"candidate": "guardian"})
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": tool, "arguments": arguments,
            "reason": "test boundary", "evidence_refs": ["boundary:result"]}))
    ctx = SimpleNamespace(complete=complete)
    async def run():
        kwargs = dict(state=state, ctx=ctx, registry=registry, catalog=catalog, key="done", candidate="guardian",
                      payload={"result": {"completed": True}}, settings={})
        first = await handoff_boundary.review_handoff(**kwargs)
        assert first["status"] == "deferred"
        assert (await handoff_boundary.review_handoff(**kwargs))["status"] == "deferred"
        assert len(calls) == 1
        state.run_metadata["orchestrator_review_revision"] = 1
        state.run_metadata["operator_followup_context"] = [{"message": "Owner reviewed the completed result"}]
        assert (await handoff_boundary.review_handoff(**kwargs))["status"] == "prepared"
        assert len(calls) == 2
        assert calls[-1]["context"]["request"]["operator_followups"] == [{"message": "Owner reviewed the completed result"}]
        json.dumps(state.run_metadata)
    asyncio.run(run())


def test_missing_pre_step_entry_key_propagates_defer_to_dispatcher(tmp_path):
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.registry import AgentRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Stage, Mode
    from logging_system.structured_logger import StructuredLogger
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    async def complete(task, prompt, **kwargs):
        assert task == "orchestrator_plan"
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "defer", "arguments": {"condition": "review"},
            "reason": "defer entry", "evidence_refs": ["boundary:result"]}))
    state = OrchestratorState(run_id="pre-defer", experiment_id="exp", mode=Mode.TEST, stage=Stage.DESIGN)
    runtime = LangGraphRunLoop(state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        ctx=SimpleNamespace(complete=complete), logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        ready = await runtime._execute_module_pre_steps(stage=Stage.DESIGN, module_runtime=runtime._module_runtime_payload(Stage.DESIGN))
        assert ready is False
        assert state.run_metadata["orchestrator_waiting_entry"]
    asyncio.run(run())


def test_delayed_model_cannot_prepare_after_specimen_input_changes(tmp_path):
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from graphs import load_graph_config
    from orchestrator.handoff_boundary import review_handoff
    from orchestrator.state import OrchestratorState, Mode, Stage
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    state = OrchestratorState(run_id="delay", experiment_id="exp", mode=Mode.TEST, stage=Stage.VISION,
                              current_experiment_spec={"specimen_id": "s"})
    async def complete(task, prompt, **kwargs):
        await asyncio.sleep(0)
        state.current_experiment_spec["specimen_id"] = "replacement"
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff", "arguments": {"candidate": "vision"},
            "reason": "stale completion", "evidence_refs": ["boundary:result"]}))
    async def run():
        result = await review_handoff(state=state, ctx=SimpleNamespace(complete=complete), registry=registry,
            catalog=OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml")).snapshot(),
            key="delayed", candidate="vision", payload={"specimen_id": "s"}, settings={})
        assert result["status"] == "deferred"
        assert result["payload"]["decision"]["status"] == "failed"
        assert not checkpoints.handoff_checkpoint(state.run_metadata, "delayed", action="consume")["consume_now"]
    asyncio.run(run())


@pytest.mark.parametrize("profile", ["virtual_bridge", "installed_printer", "physical_print"])
@pytest.mark.parametrize("with_setup", [True, False])
def test_planning_new_series_applies_setup_before_review_preserving_profile(tmp_path, profile, with_setup):
    from app.controller import MainController, ControllerDeps
    from agents.bo_agent import BOAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from graphs import load_graph_config
    from orchestrator.setup_application import SetupApplication
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    registry.register(BOAgent())
    prompts = []
    async def complete(task, prompt, **kwargs):
        prompts.append(json.loads(prompt))
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "defer", "arguments": {"condition": "review"},
            "reason": "wait before design", "evidence_refs": ["boundary:result"]}))
    controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(complete=complete, active_backend="controlled"), run_root=tmp_path / "runs", logging_config={}, system_config={}, runtime_profile={}))
    controller._bind_planning_session("session")
    store = controller._setup_store()
    original_path = controller._planning_transcript_path()
    old = controller._state
    old.run_metadata["old_approval"] = True
    constraints = controller._apply_specimen_printer_choice_to_spec({"test_mode_autofill": True}, profile)
    original_constraints = json.loads(json.dumps(constraints))
    async def run():
        if with_setup:
            block = store.ensure_block("experiment", ["orchestrator_agent", "bo_agent"], {})
            space = {**BOAgent.defaults()["parameter_space"], "cell_size_mm": [7, 8], "relative_density": [0.3, 0.4]}
            p = store.propose(block["block_id"], block["block_revision"], {"research.goal": "new confirmed goal",
                "bo.parameter_space": space}, "draft")
            confirmed = await SetupApplication(store, OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml")).snapshot()).confirm(
                p["proposal_id"], p["block_revision"], "confirm", old)
            assert confirmed.get("proposal", {}).get("target") == "next_run", confirmed
        result = await controller._handoff_planning_to_design(goal="generated goal", constraints=constraints)
        assert result["status"] == "deferred"
        assert len(prompts) == 1
        assert constraints == original_constraints
        assert controller._planning_transcript_path() == original_path
        if with_setup:
            assert controller._state.run_id != old.run_id
            assert controller._state.active_goal == "new confirmed goal"
            assert "old_approval" not in controller._state.run_metadata
            assert controller._state.run_metadata["bo_settings"]["parameter_space"]["cell_size_mm"] == [7, 8]
            seeded = controller._seed_initial_bo_design_constraints(constraints, total_cycles=20)
            assert 7 <= seeded["cell_size_mm"] <= 8
            assert 0.3 <= seeded["relative_density"] <= 0.4
        else:
            assert controller._state is old
    asyncio.run(run())


@pytest.mark.parametrize("mode_name", ["live", "test", "replay", "fault-injection"])
def test_controller_start_activates_captured_setup_only_after_fresh_reset(tmp_path, mode_name):
    from app.controller import MainController, ControllerDeps
    from agents.bo_agent import BOAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from graphs import load_graph_config
    from orchestrator.setup_application import SetupApplication
    from orchestrator.state import Mode
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    registry.register(BOAgent())
    controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(), run_root=tmp_path / "runs", logging_config={}, system_config={}, runtime_profile={}))
    controller._bind_planning_session("canonical")
    store = controller._setup_store()
    owners = OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml")).snapshot()
    old = controller._state
    old.run_metadata["old_approval"] = {"approved": True}
    block = store.ensure_block("research", ["orchestrator_agent"], {})
    proposal = store.propose(block["block_id"], block["block_revision"], {"research.goal": "confirmed goal"}, "draft")
    async def run():
        await SetupApplication(store, owners).confirm(proposal["proposal_id"], proposal["block_revision"], "confirm", old)
        result = await controller.start(mode=Mode(mode_name), goal="generated old default")
        assert result["ok"] is True
        controller._run_task.cancel()
        try:
            await controller._run_task
        except asyncio.CancelledError:
            pass
        assert controller._state.run_id != old.run_id
        assert "old_approval" not in controller._state.run_metadata
        assert controller._state.mode == Mode(mode_name)
        if mode_name == "replay":
            assert "experimental_setup_snapshot" not in controller._state.run_metadata
            assert not store.snapshot()["blocks"][0]["receipts"]
        else:
            assert controller._state.active_goal == "confirmed goal"
            assert controller._state.run_metadata["experimental_setup_snapshot"]["blocks"][0]["application_status"] == "applied"
            assert controller._state.run_metadata["experimental_setup_source"]["proposal_ids"] == [proposal["proposal_id"]]
            assert controller._setup_store() is store
    asyncio.run(run())


def test_runtime_entry_reviews_once_and_reuses_before_fresh_vision_consumption(tmp_path):
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.registry import AgentRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Stage, Mode
    from logging_system.structured_logger import StructuredLogger
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    state = OrchestratorState(run_id="fresh", experiment_id="exp", mode=Mode.TEST, stage=Stage.VISION,
                              current_experiment_spec={"specimen_id": "s"})
    calls = []
    async def complete(task, prompt, **kwargs):
        request = json.loads(prompt)
        calls.append(request)
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "prepare_handoff",
            "arguments": {"candidate": request["context"]["handoff_candidates"][0]},
            "reason": "review enclosing task before capture", "evidence_refs": ["boundary:result"]}))
    runtime = LangGraphRunLoop(state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        ctx=SimpleNamespace(complete=complete), logger=StructuredLogger(tmp_path / "events", tmp_path / "summary"))
    async def run():
        assert await runtime._review_stage_entry(Stage.VISION)
        state.run_metadata["vision_signal"] = {"signal_id": "fresh-signal"}
        state.stage = Stage.MANIPULATION
        assert await runtime._review_stage_entry(Stage.MANIPULATION)
        state.stage = Stage.VISION
        assert await runtime._review_stage_entry(Stage.VISION)
        state.stage = Stage.EQUIPMENT
        assert await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert len(calls) == 1
        state.active_goal = "changed after capture"
        assert not await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert len(calls) == 1
        checkpoints.handoff_checkpoint(state.run_metadata, "fresh-result", action="prepare", payload={
            "stage": "vision", "next_stage": "equipment", "reuse_observation_task": True,
            "result_data": {}, "selected_transition": {}, "transition_candidates": [], "guardian_context": {}})
        await runtime._resume_completed_handoff("fresh-result")
        assert len(calls) == 1
        state.active_goal = ""
        state.current_experiment_spec["specimen_id"] = "different"
        assert await runtime._review_stage_entry(Stage.EQUIPMENT)
        assert len(calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize("executor,outcome", [
    ("runtime", "defer"), ("runtime", "review"), ("runtime", "failure"), ("runtime", "cancel"),
    ("runtime", "stop"),
    ("controller", "defer"), ("controller", "review"), ("controller", "failure"),
])
def test_actual_guardian_result_wait_resume_does_not_rerun_owner_or_increment(tmp_path, outcome, executor):
    from agents.guardian_agent import GuardianAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.registry import AgentRegistry
    from knowledge.failure_memory import FailureMemory
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Stage, Mode
    from logging_system.structured_logger import StructuredLogger
    registry = AgentRegistry()
    registry.register(GuardianAgent())
    registry.register(OrchestratorAgent())
    tools = ToolRegistry()
    io = []
    def health(payload):
        io.append(payload)
        return {"printer": "ready", "camera": "ready", "robot": "ready", "utm": "ready"}
    tools.register("device.health", health)
    calls = []
    async def complete(task, prompt, **kwargs):
        calls.append(task)
        if task == "guardian_reasoning":
            return SimpleNamespace(text="Checks clear", model="controlled")
        request = json.loads(prompt)
        first = calls.count(task) == 1
        if first and outcome == "failure":
            raise RuntimeError("controlled model failure")
        if first and outcome == "cancel":
            raise asyncio.CancelledError()
        choice = ("defer", {"condition": "explicit reply"}) if first else ("prepare_handoff", {"candidate": request["context"]["handoff_candidates"][0]})
        if first and outcome == "review":
            choice = ("request_owner_review", {"owner": "guardian_agent", "issues": ["operator review"]})
        return SimpleNamespace(text=json.dumps({"tool": choice[0], "arguments": choice[1],
            "reason": "test review", "evidence_refs": ["boundary:result"]}), model="controlled")
    ctx = SimpleNamespace(complete=complete, tools=tools, failure_memory=FailureMemory())
    state = OrchestratorState(run_id="guardian-result", experiment_id="exp", mode=Mode.TEST, stage=Stage.GUARDIAN,
        current_experiment_spec={"candidate_id": "c", "specimen_id": "s", "geometry_type": "lattice_bcc",
                                "specimen_size_mm": [20, 20, 20], "cell_size_mm": 5, "wall_thickness_mm": 1})
    runtime = LangGraphRunLoop(state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent", ctx=ctx,
        logger=StructuredLogger(tmp_path / "events.jsonl", tmp_path / "summary.log"))
    async def run():
        if outcome == "stop":
            state.loop_count = GuardianAgent.TEST_LOOP_CYCLE_LIMIT - 1
            await runtime.step()
            assert state.stage == Stage.COMPLETE
            assert state.loop_count == GuardianAgent.TEST_LOOP_CYCLE_LIMIT
            assert calls == ["guardian_reasoning"]
            assert len(io) == 1
            return
        if executor == "controller" and outcome != "cancel":
            from app.controller import MainController, ControllerDeps
            controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
                agent_context=ctx, run_root=tmp_path / "runs", logging_config={}, system_config={}, runtime_profile={}))
            controller._state = state
            task = asyncio.create_task(controller._run_planning_langgraph_stage(Stage.GUARDIAN))
            for _ in range(100):
                if "orchestrator_plan" in calls:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.02)
            assert not task.done(), "Controller must retain completed owner while handoff waits"
            assert state.loop_count == 1
            state.run_metadata["orchestrator_review_revision"] = 1
            await asyncio.wait_for(task, timeout=3)
            assert state.stage == Stage.DESIGN
            assert calls.count("guardian_reasoning") == 1
            assert state.loop_count == 1
            return
        if outcome == "cancel":
            from langgraph.errors import NodeCancelledError
            with pytest.raises(NodeCancelledError):
                await runtime.step()
        else:
            await runtime.step()
        assert state.stage == Stage.GUARDIAN
        assert state.loop_count == 1
        await runtime.step()
        assert state.stage == Stage.GUARDIAN
        assert calls == ["guardian_reasoning", "orchestrator_plan"]
        state.run_metadata["orchestrator_review_revision"] = 1
        await runtime.step()
        assert state.stage == Stage.DESIGN
        assert state.loop_count == 1
        assert len(io) == 1
        assert calls.count("guardian_reasoning") == 1
        assert calls.count("orchestrator_plan") == 2
        record = next(record for record in state.run_metadata["orchestrator_checkpoints"].values()
                      if record["payload"].get("next_stage") == "design")
        assert state.run_metadata["latest_orchestrator_handoff"] == record["payload"]["decision"]["effect"]
    asyncio.run(run())
