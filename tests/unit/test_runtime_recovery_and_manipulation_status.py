"""Non-actuating regression tests for physical-cycle lifecycle boundaries."""
from copy import deepcopy
import asyncio

import pytest

from agents.base_agent import AgentResult
from agents.registry import AgentRegistry
from logging_system.structured_logger import StructuredLogger
from orchestrator.langgraph_runtime import LangGraphRunLoop
from orchestrator.state import Mode, OrchestratorState, Stage


class ResultAgent:
    def __init__(self, name, data, success=True):
        self.name, self.data, self.success = name, data, success

    async def run(self, state, ctx):
        return AgentResult(success=self.success, summary="fixture result", data=deepcopy(self.data))


def runtime_fixture(tmp_path, stage=Stage.GUARDIAN, agent=None):
    state = OrchestratorState(run_id="run-lifecycle", experiment_id="exp-lifecycle", mode=Mode.TEST, stage=stage)
    state.current_experiment_spec = {"specimen_id": "specimen-1"}
    registry = AgentRegistry()
    if agent:
        registry.register(agent)
    events = []
    runtime = LangGraphRunLoop(
        state=state, agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        ctx=object(), logger=StructuredLogger(tmp_path / "events.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml", on_event=events.append,
    )
    return runtime, state, events


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["recover", "retry"])
async def test_guardian_recovery_holds_same_specimen_without_starting_a_new_cycle(tmp_path, action):
    agent = ResultAgent("guardian_agent", {"guardian": {
        "decision": "continue", "action": action, "reason": "Camera evidence needs recovery",
        "graph_gate_pressure": {"active_gates": [{"stage": "vision", "reason_code": "ROS_IMAGE_TIMEOUT"}]},
    }})
    runtime, state, events = runtime_fixture(tmp_path, agent=agent)
    await runtime.step()
    assert state.stage == Stage.GUARDIAN
    assert state.is_paused is True
    assert state.loop_count == 0
    assert state.current_experiment_spec["specimen_id"] == "specimen-1"
    assert state.agent_status["guardian_agent"].state == "waiting"
    assert any(e["event_type"] == "operator_input_required" for e in events)
    assert not any(e.get("payload", {}).get("to_stage") == "design" for e in events)


@pytest.mark.asyncio
async def test_normal_guardian_continue_keeps_existing_next_cycle_route(tmp_path):
    runtime, state, _ = runtime_fixture(tmp_path, agent=ResultAgent("guardian_agent", {
        "guardian": {"decision": "continue", "action": "continue"},
    }))
    await runtime.step()
    assert state.stage == Stage.DESIGN
    assert state.loop_count == 1
    assert state.is_paused is False


@pytest.mark.asyncio
async def test_guardian_safe_stop_still_terminates(tmp_path):
    runtime, state, _ = runtime_fixture(tmp_path, agent=ResultAgent("guardian_agent", {
        "guardian": {"decision": "stop", "action": "safe_stop"},
    }))
    await runtime.step()
    assert state.stage == Stage.COMPLETE
    assert state.is_paused is False


def active_manipulation():
    return {
        "manipulation": {"ok": True, "status": "POLICY_ACTIVE", "session_id": "rollout-1", "stop_confirmed": False},
        "robot_task_result": {
            "run_id": "run-lifecycle", "loop_id": "loop-0", "specimen_id": "specimen-1",
            "rollout_session_id": "rollout-1", "completion_status": "awaiting_post_place_home",
        },
        "requested_next_stage": "vision",
    }


def completion_signal():
    return {
        "schema": "vision_manipulation_completion.v1", "run_id": "run-lifecycle",
        "loop_id": 0, "specimen_id": "specimen-1", "session_id": "rollout-1",
        "detected": True, "ready_to_stop_rollout": True, "rollout_stopped": True,
        "rollout_stop_status": "STOPPED", "blocking_reason": "",
        "post_place_interlock": {"ready_for_utm_snapshot": True},
    }


def test_live_snapshot_preserves_execution_and_recovery_context():
    from app.controller import MainController
    metadata = {
        "manipulation_execution": {"run_id": "run-lifecycle", "loop_id": 0, "session_id": "rollout-1", "state": "running"},
        "guardian_recovery_wait": {"run_id": "run-lifecycle", "loop_id": 0, "status": "waiting"},
    }
    snapshot = MainController._compact_planning_run_metadata(metadata)
    assert snapshot["manipulation_execution"] == metadata["manipulation_execution"]
    assert snapshot["guardian_recovery_wait"] == metadata["guardian_recovery_wait"]


@pytest.mark.asyncio
async def test_manipulation_handoff_to_vision_remains_running_until_verified_stop(tmp_path):
    runtime, state, events = runtime_fixture(tmp_path, stage=Stage.MANIPULATION,
        agent=ResultAgent("manipulation_agent", active_manipulation()))
    await runtime.step()
    assert state.stage == Stage.VISION  # Preserve concurrent Vision monitoring.
    assert state.agent_status["manipulation_agent"].state == "running"
    assert state.agent_status["manipulation_agent"].success is None
    result = next(e for e in events if e["event_type"] == "agent_result")
    assert result["payload"]["status"] == "running"
    runtime._merge_agent_data(Stage.VISION, {"observation": {"vision_manipulation_completion": completion_signal()}})
    assert state.agent_status["manipulation_agent"].state == "done"
    assert state.agent_status["manipulation_agent"].success is True


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("run_id", "other-run"), ("loop_id", 1), ("specimen_id", "other-specimen"),
    ("session_id", "other-rollout"), ("session_id", ""), ("rollout_stopped", False),
    ("rollout_stop_status", "STOPPING"), ("detected", False), ("blocking_reason", "not_home"),
    ("post_place_interlock", {"ready_for_utm_snapshot": False}),
])
async def test_unverified_or_other_execution_cannot_mark_manipulation_done(tmp_path, field, value):
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.MANIPULATION,
        agent=ResultAgent("manipulation_agent", active_manipulation()))
    await runtime.step()
    signal = completion_signal()
    signal[field] = value
    runtime._merge_agent_data(Stage.VISION, {"observation": {"vision_manipulation_completion": signal}})
    assert state.agent_status["manipulation_agent"].state in {"running", "waiting"}
    assert state.agent_status["manipulation_agent"].success is None


@pytest.mark.asyncio
async def test_operator_retry_merge_also_finishes_matching_manipulation(tmp_path):
    from app.controller import MainController
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.MANIPULATION,
        agent=ResultAgent("manipulation_agent", active_manipulation()))
    await runtime.step()
    controller = MainController.__new__(MainController)
    controller._state = state
    controller._merge_planning_agent_data(Stage.VISION, {
        "observation": {"vision_manipulation_completion": completion_signal()},
        "requested_next_stage": "equipment", "transition_decision": "vision_equipment_handoff",
    })
    assert state.agent_status["manipulation_agent"].state == "done"


@pytest.mark.asyncio
async def test_current_manipulation_failure_overrides_previously_running_execution(tmp_path):
    data = active_manipulation()
    agent = ResultAgent("manipulation_agent", data)
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.MANIPULATION, agent=agent)
    await runtime.step()
    state.stage = Stage.MANIPULATION
    agent.success = False
    agent.data["manipulation"].update(ok=False, failure_code="STOP_FAILED")
    await runtime.step()
    assert state.run_metadata["manipulation_execution"]["state"] == "error"
    assert state.agent_status["manipulation_agent"].success is False


@pytest.mark.parametrize("consumer", ["runtime", "controller"])
def test_new_manipulation_result_cannot_consume_old_completion(tmp_path, consumer):
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.MANIPULATION)
    merge = runtime._merge_agent_data
    if consumer == "controller":
        from app.controller import MainController
        controller = MainController.__new__(MainController)
        controller._state = state
        merge = controller._merge_planning_agent_data
    state.latest_observations["vision_manipulation_completion"] = completion_signal()
    merge(Stage.MANIPULATION, active_manipulation())
    assert state.agent_status["manipulation_agent"].state == "running"
    assert state.agent_status["manipulation_agent"].success is None
    merge(Stage.VISION, {"observation": {"unrelated_snapshot": {"status": "captured"}}})
    assert state.agent_status["manipulation_agent"].state == "running"
    assert state.agent_status["manipulation_agent"].success is None
    merge(Stage.VISION, {"observation": {"vision_manipulation_completion": completion_signal()}})
    assert state.agent_status["manipulation_agent"].state == "done"


@pytest.mark.asyncio
async def test_failed_start_without_session_is_an_error_not_done(tmp_path):
    runtime, state, events = runtime_fixture(tmp_path, stage=Stage.MANIPULATION,
        agent=ResultAgent("manipulation_agent", {"manipulation": {
            "ok": False, "status": "FAILED", "failure_code": "ROBOT_UNAVAILABLE",
        }}, success=False))
    await runtime.step()
    assert state.agent_status["manipulation_agent"].state == "error"
    result = next(e for e in events if e["event_type"] == "agent_result")
    assert result["payload"]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_state", ["STOPPING", "STOPPED"])
async def test_stop_without_transfer_verification_waits_instead_of_completing(tmp_path, stop_state):
    data = active_manipulation()
    data["manipulation"]["status"] = stop_state
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.MANIPULATION,
        agent=ResultAgent("manipulation_agent", data))
    await runtime.step()
    assert state.agent_status["manipulation_agent"].state == "waiting"
    assert state.agent_status["manipulation_agent"].success is None


@pytest.mark.asyncio
async def test_live_tail_stays_alive_during_guardian_review_and_honors_stop(tmp_path):
    from app.controller import MainController
    runtime, state, _ = runtime_fixture(tmp_path, agent=ResultAgent("guardian_agent", {
        "guardian": {"decision": "continue", "action": "recover"},
    }))
    await runtime.step()
    controller = MainController.__new__(MainController)
    controller._state = state
    controller._vision_intervention_resume_event = asyncio.Event()
    waiting = asyncio.create_task(controller._wait_for_vision_intervention_resume())
    try:
        await asyncio.sleep(0.01)
        assert not waiting.done()
        state.stop_requested = True
        controller._vision_intervention_resume_event.set()
        assert await asyncio.wait_for(waiting, 1) is False
        assert state.loop_count == 0
        assert state.stage == Stage.GUARDIAN
    finally:
        if not waiting.done():
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
