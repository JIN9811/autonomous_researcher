"""Non-actuating same-cycle clearance contracts; synthetic negatives are not commissioning."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from graphs.schema import load_graph_config
from orchestrator.state import OrchestratorState, Stage


def state_with_placement():
    state = OrchestratorState(run_id="clear-test", experiment_id="test", current_experiment_spec={"specimen_id": "s1"})
    scope = {"run_id": state.run_id, "loop_id": state.loop_count, "specimen_id": "s1"}
    state.run_metadata["utm_verifications"] = {
        **scope, "verification_1": {"verification_index": 1, "status": "confirmed", "confirmed": True,
        "captured_at": "2026-09-06T00:00:00+00:00", "artifact": {"path": "first.png"},
        "evidence": {"detected": True, "detector": "high_chroma_red_hsv_largest_component"}},
    }
    state.run_metadata["manipulation_execution"] = {**scope, "session_id": "transfer", "state": "done", "success": True}
    return state


def equipment_data(state):
    return {"protocol_note": "verified", "equipment_result": {"ok": True, "status": "verified_complete", "run_id": state.run_id, "specimen_id": "s1"},
        "equipment_handoff": {"status": "ready_for_analysis", "ready_for_analysis": True},
        "utm_data_ready": {"status": "ready", "run_id": state.run_id, "specimen_id": "s1"},
        "raw_data_export": {"validated": True, "run_id": state.run_id, "specimen_id": "s1"},
        "next_specimen_readiness": {"clearance_restored": True, "next_test_completed": True},
        "handoff_eligibility": {"eligible": True}}


def state_with_completed_clear():
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    execution = state.run_metadata["utm_clear_execution"]
    execution.update(
        state="done",
        success=True,
        replay_home_verified=True,
        replay_evidence={"measured": True},
    )
    state.run_metadata["utm_verifications"]["verification_2"] = {
        "verification_index": 2,
        "status": "clear",
        "confirmed": True,
        "captured_at": "2026-09-06T00:01:00+00:00",
        "artifact": {"path": "second.png"},
        "evidence": {"detected": False, "clear_confirmed": True},
    }
    state.run_metadata["utm_clear_next_stage"] = "analysis"
    return state


def test_verified_equipment_routes_to_same_cycle_clear_not_analysis():
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    execution = state.run_metadata["utm_clear_execution"]
    assert execution["task_id"] == "clear_utm_to_disposal"
    assert execution["state"] == "requested"
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    assert graph.next_stage("equipment", state_metadata=state.run_metadata) == "manipulation"
    execution.update(state="error", success=False)
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    assert execution["state"] == "error"


@pytest.mark.parametrize("broken", ["identity", "csv", "clearance", "placement"])
def test_incomplete_equipment_never_arms_clear(broken):
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    data = equipment_data(state)
    if broken == "identity": data["equipment_result"]["run_id"] = "old"
    if broken == "csv": data["raw_data_export"]["validated"] = False
    if broken == "clearance": data["next_specimen_readiness"]["clearance_restored"] = False
    if broken == "placement": state.run_metadata["utm_verifications"]["loop_id"] = 99
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, data)
    assert state.run_metadata.get("utm_clear_execution", {}).get("state") != "requested"


def test_direct_analysis_guard_requires_clearance():
    from utils import utm_clear_cycle as cycle
    from policies.guardian_gate import guardian_gate
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    gate = guardian_gate(state=state, stage="analysis", phase="pre", payload={})
    assert gate["ok_for_next_stage"] is False


@pytest.mark.parametrize("kind", ["runtime", "controller"])
def test_real_merge_and_snapshot_preserve_scoped_handoff(kind, tmp_path):
    from tests.unit.test_runtime_recovery_and_manipulation_status import runtime_fixture
    from app.controller import MainController
    runtime, _, _ = runtime_fixture(tmp_path, stage=Stage.EQUIPMENT)
    state = state_with_placement()
    if kind == "runtime":
        runtime._state = state
        merge = runtime._merge_agent_data
    else:
        controller = MainController.__new__(MainController)
        controller._state = state
        merge = controller._merge_planning_agent_data
    merge(Stage.EQUIPMENT, equipment_data(state))
    assert state.run_metadata["utm_clear_execution"]["state"] == "requested"
    assert state.run_metadata["utm_verifications"]["verification_1"]["artifact"]["path"] == "first.png"
    assert MainController._compact_planning_run_metadata(state.run_metadata)["utm_clear_execution"]["task_id"] == "clear_utm_to_disposal"


class ReplayTools:
    def __init__(self, state):
        self.state, self.calls = state, []
        self.status = "REPLAY_ACTIVE"
        self.home = False
        self.topic = "/camera/image_rect"
    def list_tools(self): return ["lerobot.replay.start", "lerobot.replay.status", "vision.utm_specimen_presence.capture"]
    def call(self, name, payload):
        self.calls.append((name, deepcopy(payload)))
        identity = {k: payload[k] for k in ("run_id", "loop_id", "specimen_id", "session_id")}
        if name.startswith("lerobot.replay"):
            return {**identity, "ok": True, "status": self.status, "exit_code": 0 if self.status == "COMPLETED" else None,
                "replay_home_verified": self.home, "replay_evidence": {"measured": True}, "replay_max_duration_s": 60.0}
        from datetime import datetime, timezone
        return {**identity, "ok": True, "status": "clear", "clear_confirmed": True, "detected": False,
            "captured_at": datetime.now(timezone.utc).isoformat(), "frame_timestamp": datetime.now(timezone.utc).timestamp(),
            "registered": True, "topic": self.topic, "camera_profile_id": "camera_utm_primary",
            "raw_frame_path": "synthetic.png", "evidence_path": "synthetic.json", "failure_code": ""}


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
async def test_replay_launch_poll_return_then_fresh_clear_routes_analysis(topic):
    from utils import utm_clear_cycle as cycle
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    from policies.validation_policy import validate_agent_output
    from policies.guardian_gate import guardian_gate
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"manipulation": "execute", "vision": "execute", "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    tools = ReplayTools(state)
    tools.topic = topic
    ctx = SimpleNamespace(tools=tools)
    result = await ManipulationAgent().run(state, ctx)
    assert result.success
    assert result.data["requested_next_stage"] == "vision"
    assert tools.calls[0][0] == "lerobot.replay.start"
    assert tools.calls[0][1]["dataset_repo_id"] == "jin/utm_clear"
    assert tools.calls[0][1]["replay_episode"] == 0
    assert "policy_path" not in tools.calls[0][1]
    cycle.merge_utm_clear_cycle(state, Stage.MANIPULATION, result.data)
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    assert graph.next_stage("manipulation", state_metadata={**state.run_metadata, "requested_next_stage": "equipment"}) == "vision"
    waiting = await VisionAgent().run(state, ctx)
    assert waiting.data["requested_next_stage"] == "vision"
    assert all(name != "vision.utm_specimen_presence.capture" for name, _ in tools.calls)
    tools.status, tools.home = "COMPLETED", True
    result = await VisionAgent().run(state, ctx)
    assert validate_agent_output("vision", result.data)[0]
    cycle.merge_utm_clear_cycle(state, Stage.VISION, result.data)
    assert result.data["requested_next_stage"] == "analysis"
    assert state.run_metadata["utm_verifications"]["verification_2"]["confirmed"] is True
    assert guardian_gate(state=state, stage="vision", phase="post", payload=result.data)["ok_for_next_stage"]
    assert not cycle.clearance_missing(state)
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    assert graph.next_stage("vision", state_metadata={**state.run_metadata, "requested_next_stage": "equipment"}) == "analysis"
    await ManipulationAgent().run(state, ctx)
    assert sum(name == "lerobot.replay.start" for name, _ in tools.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["preflight_only", "virtual", "off", ""])
async def test_mixed_policy_cannot_actuate_or_simulate_real_clear(policy):
    from utils import utm_clear_cycle as cycle
    from agents.manipulation_agent import ManipulationAgent
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"manipulation": policy, "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    tools = ReplayTools(state)
    result = await ManipulationAgent().run(state, SimpleNamespace(tools=tools))
    assert not result.success
    assert not tools.calls
    assert result.data["utm_clear_execution"]["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,physical", [("live", False), ("test", True)])
async def test_existing_execution_mode_maps_to_live_transport_and_local_dataset(mode, physical):
    from orchestrator.state import Mode
    from agents.manipulation_agent import ManipulationAgent
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    state.mode = Mode(mode)
    if physical:
        state.current_experiment_spec.update(printer_test_path="installed_printer", execution_policy={"manipulation": "execute", "lab_equipment": "execute"})
        state.run_metadata["specimen_result"] = {"ok": True, "specimen_id": "s1", "printer_path": "installed_printer", "physical_intent": True,
            "fabrication_report": {"fabrication_outcome": {"status": "ready_for_vision"}}}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    tools = ReplayTools(state)
    result = await ManipulationAgent().run(state, SimpleNamespace(tools=tools))
    assert result.success
    request = tools.calls[0][1]
    assert request["runtime_mode"] == "live"
    assert request["confirm_live_execute"] is True
    assert request["dataset_path"].endswith("/jin/utm_clear")


def test_stage_module_allowlists_accept_managed_replay_tools():
    from graphs.schema import load_module_config
    from orchestrator.langgraph_runtime import ModuleToolRegistryProxy
    from mcp_tools.tool_registry import ToolRegistry
    for stage, tool in [(Stage.MANIPULATION, "lerobot.replay.start"), (Stage.VISION, "lerobot.replay.status")]:
        module = load_module_config(f"graphs/modules/{stage.value}/module.yaml")
        registry = ToolRegistry()
        registry.register(tool, lambda payload: {"ok": True, "status": "REPLAY_ACTIVE"})
        proxy = ModuleToolRegistryProxy(registry, module.tools, stage)
        assert proxy.call(tool, {})["status"] == "REPLAY_ACTIVE"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,home", [("STOPPED", True), ("FAILED", False), ("COMPLETED", False)])
async def test_stop_failure_or_missing_return_never_captures(status, home):
    from utils import utm_clear_cycle as cycle
    from agents.vision_agent import VisionAgent
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"vision": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"]["state"] = "running"
    tools = ReplayTools(state)
    tools.status, tools.home = status, home
    result = await VisionAgent().run(state, SimpleNamespace(tools=tools))
    assert not result.success
    assert result.data["requested_next_stage"] == "vision"
    assert all(name != "vision.utm_specimen_presence.capture" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_explicit_fully_virtual_cycle_has_simulated_evidence_and_no_tools():
    from utils import utm_clear_cycle as cycle
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {key: "virtual" for key in ("manipulation", "vision", "lab_equipment")}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    tools = ReplayTools(state)
    launched = await ManipulationAgent().run(state, SimpleNamespace(tools=tools))
    cycle.merge_utm_clear_cycle(state, Stage.MANIPULATION, launched.data)
    result = await VisionAgent().run(state, SimpleNamespace(tools=tools))
    assert result.data["requested_next_stage"] == "analysis"
    assert result.data["utm_verification_2"]["record"]["evidence"]["simulated"] is True
    assert not tools.calls


def test_missing_placement_record_blocks_equipment_route_and_analysis():
    from utils import utm_clear_cycle as cycle
    from policies.guardian_gate import guardian_gate
    state = state_with_placement()
    state.run_metadata.pop("utm_verifications")
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    assert graph.next_stage("equipment", state_metadata=state.run_metadata) == "vision"
    assert not guardian_gate(state=state, stage="analysis", phase="pre")["ok_for_next_stage"]
    state.run_metadata.pop("utm_clear_execution")
    assert not guardian_gate(state=state, stage="analysis", phase="pre")["ok_for_next_stage"]


@pytest.mark.parametrize("kind", ["runtime", "controller"])
def test_clear_lifecycle_pending_and_initial_observation_are_preserved(kind, tmp_path):
    from utils import utm_clear_cycle as cycle
    from tests.unit.test_runtime_recovery_and_manipulation_status import runtime_fixture
    from app.controller import MainController
    state = state_with_placement()
    state.latest_observations = {"vision_manipulation_completion": {"detected": True, "session_id": "transfer"}}
    if kind == "runtime":
        runtime, _, _ = runtime_fixture(tmp_path)
        runtime._state = state
        merge = runtime._merge_agent_data
    else:
        controller = MainController.__new__(MainController)
        controller._state = state
        merge = controller._merge_planning_agent_data
    merge(Stage.EQUIPMENT, equipment_data(state))
    execution = state.run_metadata["utm_clear_execution"]
    merge(Stage.MANIPULATION, {"utm_clear_execution": {**execution, "state": "running"}, "requested_next_stage": "vision"})
    assert state.agent_status["manipulation_agent"].state == "running"
    merge(Stage.VISION, {"utm_clear_execution": {**execution, "state": "waiting"}, "observation": {"utm_clear_verification": {"status": "unknown"}}})
    assert state.agent_status["manipulation_agent"].state == "waiting"
    assert state.agent_status["manipulation_agent"].success is None
    assert state.latest_observations["vision_manipulation_completion"]["session_id"] == "transfer"
    assert state.run_metadata["initial_manipulation_execution"]["success"] is True


@pytest.mark.asyncio
async def test_actual_runtime_equipment_success_enters_clear_in_same_loop(tmp_path):
    from tests.unit.test_runtime_recovery_and_manipulation_status import runtime_fixture, ResultAgent
    state = state_with_placement()
    runtime, _, events = runtime_fixture(tmp_path, stage=Stage.EQUIPMENT, agent=ResultAgent("equipment_agent", equipment_data(state)))
    state.stage = Stage.EQUIPMENT
    runtime._state = state
    await runtime.step()
    assert state.stage == Stage.MANIPULATION
    assert state.loop_count == 0


def test_controller_configured_route_uses_clear_context():
    from app.controller import MainController
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    controller = MainController.__new__(MainController)
    controller._state = state
    controller._active_graph_config_path = None
    assert controller._next_configured_stage_after(Stage.EQUIPMENT) == Stage.MANIPULATION


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["stop_requested", "safe_stop_requested", "emergency_stop_requested"])
async def test_control_stop_flags_never_start_clear(flag):
    from utils import utm_clear_cycle as cycle
    from agents.manipulation_agent import ManipulationAgent
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"manipulation": "execute", "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    setattr(state, flag, True)
    tools = ReplayTools(state)
    result = await ManipulationAgent().run(state, SimpleNamespace(tools=tools))
    assert not result.success
    assert not tools.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["stop_requested", "safe_stop_requested", "emergency_stop_requested"])
@pytest.mark.parametrize("entry", ["helper", "manipulation", "vision"])
async def test_later_stop_preserves_completed_clear_history_without_tools(flag, entry):
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    from utils import utm_clear_cycle as cycle
    state = state_with_completed_clear()
    setattr(state, flag, True)
    execution_before = deepcopy(state.run_metadata["utm_clear_execution"])
    verifications_before = deepcopy(state.run_metadata["utm_verifications"])
    tools = ReplayTools(state)
    ctx = SimpleNamespace(tools=tools)

    if entry == "helper":
        result = None
        await cycle.stop_pending_clear(state, ctx, reason="UTM_CLEAR_OPERATOR_STOPPED")
    elif entry == "manipulation":
        result = await ManipulationAgent().run(state, ctx)
    else:
        result = await VisionAgent().run(state, ctx)

    assert state.run_metadata["utm_clear_execution"] == execution_before
    assert state.run_metadata["utm_verifications"] == verifications_before
    assert not tools.calls
    if result is not None:
        assert result.success is True
        assert result.data["requested_next_stage"] == "analysis"


@pytest.mark.asyncio
async def test_repeated_pending_cleanup_stops_owned_child_once_without_restart():
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"].update(state="running", success=None)
    tools = ReplayTools(state)
    ctx = SimpleNamespace(tools=tools)

    await cycle.stop_pending_clear(state, ctx, reason="UTM_CLEAR_OPERATOR_STOPPED")
    await cycle.stop_pending_clear(state, ctx, reason="UTM_CLEAR_OPERATOR_STOPPED")

    execution = state.run_metadata["utm_clear_execution"]
    assert execution["state"] == "error"
    assert execution["success"] is False
    assert execution["stop_attempted"] is True
    assert sum(name == "lerobot.replay.stop" for name, _ in tools.calls) == 1
    assert all(name != "lerobot.replay.start" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_controller_downstream_stop_preserves_completed_clear_history():
    from app.controller import MainController
    state = state_with_completed_clear()
    state.stage = Stage.ANALYSIS
    state.stop_requested = True
    execution_before = deepcopy(state.run_metadata["utm_clear_execution"])
    verifications_before = deepcopy(state.run_metadata["utm_verifications"])
    tools = ReplayTools(state)
    controller = MainController.__new__(MainController)
    controller._state = state
    controller._deps = SimpleNamespace(agent_context=SimpleNamespace(tools=tools))
    controller._planning_tail_start_stage = lambda: Stage.ANALYSIS
    controller._planning_tail_stages = lambda start: {start}
    controller._planning_stage_label = lambda *args, **kwargs: "Analysis"

    async def sink(*args, **kwargs):
        return None

    controller._append_planning_message = sink
    result = await controller._run_planning_loop_tail(state.current_experiment_spec)

    assert result["decision"] == "stop"
    assert state.run_metadata["utm_clear_execution"] == execution_before
    assert state.run_metadata["utm_verifications"] == verifications_before
    assert not tools.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"frame_timestamp": 1}, {"registered": False}, {"status": "occupied", "detected": True},
    {"ok": False}, {"run_id": "old"}, {"loop_id": 9}, {"session_id": "transfer"}, {"topic": "/image_utm"}])
async def test_bad_clear_capture_is_archived_but_never_confirms(change):
    from utils import utm_clear_cycle as cycle
    from agents.vision_agent import VisionAgent
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"vision": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    state.run_metadata["utm_clear_execution"]["state"] = "running"
    class BadTools(ReplayTools):
        def call(self, name, payload):
            result = super().call(name, payload)
            if name == "vision.utm_specimen_presence.capture": result.update(change)
            return result
    tools = BadTools(state)
    tools.status, tools.home = "COMPLETED", True
    result = await VisionAgent().run(state, SimpleNamespace(tools=tools))
    cycle.merge_utm_clear_cycle(state, Stage.VISION, result.data)
    assert result.data["requested_next_stage"] == "vision"
    assert state.run_metadata["utm_verifications"]["verification_2"]["confirmed"] is False
    assert state.run_metadata["utm_verifications"]["verification_1"]["confirmed"] is True


def test_real_archived_first_verification_captures_red_material_and_is_immutable():
    import json
    from pathlib import Path
    from utils import utm_clear_cycle as cycle
    path = Path("runs/run-20260906T122533Z-c0effd/runtime/loops/loop-000001/vision_agent/attempt-000012/result.json")
    if not path.exists(): pytest.skip("Archived read-only reference unavailable")
    data = json.loads(path.read_text())["data"]
    completion = data["observation"]["vision_manipulation_completion"]
    state = OrchestratorState(run_id=completion["run_id"], experiment_id="reference", current_experiment_spec={"specimen_id": completion["specimen_id"]})
    cycle.merge_utm_clear_cycle(state, Stage.VISION, data)
    first = deepcopy(state.run_metadata["utm_verifications"]["verification_1"])
    assert first["confirmed"] is True
    assert first["artifact"]["detector"] == "high_chroma_red_hsv_largest_component"
    data["observation"]["vision_manipulation_completion"]["detected"] = False
    cycle.merge_utm_clear_cycle(state, Stage.VISION, data)
    assert state.run_metadata["utm_verifications"]["verification_1"] == first


@pytest.mark.asyncio
async def test_legacy_direct_clear_request_cannot_fall_back_to_policy_or_pick_place():
    from agents.manipulation_agent import ManipulationAgent
    state = state_with_placement()
    state.current_experiment_spec["manipulation_task_id"] = "clear_utm_to_disposal"
    tools = ReplayTools(state)
    result = await ManipulationAgent().run(state, SimpleNamespace(tools=tools))
    assert result.success is False
    assert result.data["failure_code"] == "UTM_CLEAR_HANDOFF_REQUIRED"
    assert not tools.calls


@pytest.mark.parametrize("record", ["equipment_result", "utm_data_ready", "raw_data_export", "equipment_handoff"])
@pytest.mark.parametrize("key,value", [("run_id", "old-run"), ("specimen_id", "other"), ("loop_id", 99)])
def test_contradictory_equipment_handoff_identity_blocks_route_and_analysis(record, key, value):
    from utils import utm_clear_cycle as cycle
    from policies.guardian_gate import guardian_gate
    state = state_with_placement()
    data = equipment_data(state)
    data[record][key] = value
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, data)
    assert state.run_metadata["utm_clear_execution"]["state"] == "error"
    assert state.run_metadata["utm_clear_requirement"]["run_id"] == state.run_id
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    assert graph.next_stage("equipment", state_metadata=state.run_metadata) == "vision"
    assert guardian_gate(state=state, stage="analysis", phase="pre")["ok_for_next_stage"] is False


@pytest.mark.parametrize("loop", [None, 0])
def test_legacy_absent_or_matching_equipment_loop_remains_eligible(loop):
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    data = equipment_data(state)
    if loop is not None:
        for key in ("equipment_result", "utm_data_ready", "raw_data_export", "equipment_handoff"):
            data[key]["loop_id"] = loop
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, data)
    assert state.run_metadata["utm_clear_execution"]["state"] == "requested"


def test_contradictory_repeat_equipment_cannot_leave_clear_armed():
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    data = equipment_data(state)
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, data)
    session = state.run_metadata["utm_clear_execution"]["session_id"]
    data["equipment_result"]["loop_id"] = 99
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, data)
    assert state.run_metadata["utm_clear_execution"]["state"] == "error"
    assert state.run_metadata["utm_clear_execution"]["session_id"] == session


@pytest.mark.asyncio
async def test_replay_deadline_does_not_extend_on_status_refresh(monkeypatch):
    from utils import utm_clear_cycle as cycle
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    import asyncio
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"manipulation": "execute", "vision": "execute", "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    tools = ReplayTools(state)
    ctx = SimpleNamespace(tools=tools)
    await ManipulationAgent().run(state, ctx)
    execution = state.run_metadata["utm_clear_execution"]
    deadline = execution["pending_deadline_at"]
    async def yield_only(seconds): await asyncio.sleep(0)
    monkeypatch.setattr(cycle, "asyncio", SimpleNamespace(sleep=yield_only, to_thread=asyncio.to_thread))
    await VisionAgent().run(state, ctx)
    await VisionAgent().run(state, ctx)
    assert execution["pending_deadline_at"] == deadline
    assert execution["pending_timeout_s"] == 120.0


def test_bridge_projects_its_computed_replay_time_bound():
    from device_bridges.lerobot_bridge import LeRobotBridge
    bridge = LeRobotBridge.__new__(LeRobotBridge)
    result = bridge._replay_evidence({"status": "REPLAY_ACTIVE", "replay_max_duration_s": 77.5})
    assert result["replay_max_duration_s"] == 77.5


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["complete", "stop", "timeout"])
async def test_full_controller_tail_waits_for_replay_beyond_step_budget(tmp_path, monkeypatch, ending):
    """Real controller tail, LangGraph, agents, merges and routing; only device/time/UI sinks injected."""
    import asyncio
    from agents.manipulation_agent import ManipulationAgent
    from agents.vision_agent import VisionAgent
    from agents.registry import AgentRegistry
    from app.controller import MainController
    from logging_system.structured_logger import StructuredLogger
    from tests.unit.test_runtime_recovery_and_manipulation_status import ResultAgent
    from utils import utm_clear_cycle as cycle
    state = state_with_placement()
    state.current_experiment_spec["execution_policy"] = {"manipulation": "execute", "vision": "execute", "lab_equipment": "execute"}
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    now = [__import__("time").time()]
    sleeps = []
    async def simulated_sleep(seconds):
        assert 0 < seconds <= 0.25
        sleeps.append(seconds)
        now[0] += seconds
        await asyncio.sleep(0)  # Other GUI/control tasks remain schedulable.
    monkeypatch.setattr(cycle, "time", SimpleNamespace(time=lambda: now[0]))
    monkeypatch.setattr(cycle, "asyncio", SimpleNamespace(sleep=simulated_sleep, to_thread=asyncio.to_thread))
    class LongReplay(ReplayTools):
        active = False
        polls = 0
        def call(self, name, payload):
            if name == "lerobot.replay.start": self.active = True
            if name == "lerobot.replay.status":
                self.polls += 1
                if ending == "stop" and self.polls == 40: state.stop_requested = True
                if ending == "complete" and self.polls > 40:
                    self.status, self.home, self.active = "COMPLETED", True, False
            if name == "lerobot.replay.stop":
                self.status, self.active = "STOPPED", False
            result = super().call(name, payload)
            result["replay_max_duration_s"] = 20.0
            if name == "vision.utm_specimen_presence.capture": result["frame_timestamp"] = now[0] + 0.001
            return result
    tools = LongReplay(state)
    registry = AgentRegistry()
    registry.register(ManipulationAgent())
    registry.register(VisionAgent())
    registry.register(ResultAgent("analysis_agent", {"analysis": {"ok": True}}))
    registry.register(ResultAgent("knowledge_agent", {"knowledge": {"ok": True}}))
    registry.register(ResultAgent("bo_agent", {"bo_result": {"ok": True}}))
    registry.register(ResultAgent("guardian_agent", {"guardian": {"decision": "continue", "action": "continue"}}))
    controller = MainController.__new__(MainController)
    controller._state = state
    controller._active_graph_config_path = None
    controller._active_graph_id = "atr_closed_loop"
    controller._deps = SimpleNamespace(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(tools=tools), system_config={})
    controller._logger_bundle = SimpleNamespace(logger=StructuredLogger(tmp_path / "events.jsonl", tmp_path / "summary.log"))
    controller._planning_tail_start_stage = lambda: Stage.MANIPULATION
    async def sink(*args, **kwargs): return None
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    monkeypatch.setattr(LangGraphRunLoop, "_emit", sink)  # Inject the event transport, not graph steps or safety gates.
    controller._broadcast_event = sink
    controller._append_planning_message = sink
    controller._write_planning_fem_artifacts = lambda *a, **k: {}
    controller._wait_for_vision_intervention_resume = lambda: asyncio.sleep(0, result=False)
    result = await controller._run_planning_loop_tail(state.current_experiment_spec)
    assert tools.polls > 32  # Exceeds the ordinary full-tail stage budget.
    assert sleeps and sum(sleeps) >= 8
    assert sum(name == "lerobot.replay.start" for name, _ in tools.calls) == 1
    assert tools.active is False
    assert state.stage != Stage.EQUIPMENT
    if ending == "complete":
        assert result["ok"]
        assert state.run_metadata["utm_verifications"]["verification_2"]["confirmed"] is True
        assert state.latest_analysis["ok"] is True
    else:
        assert state.run_metadata["utm_clear_execution"]["success"] is not True
        assert not any(name == "vision.utm_specimen_presence.capture" for name, _ in tools.calls)
        assert sum(name == "lerobot.replay.stop" for name, _ in tools.calls) == 1
