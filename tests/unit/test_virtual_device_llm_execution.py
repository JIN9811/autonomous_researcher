"""Virtual equipment must not turn a failed model decision into preflight success."""
import pytest


def virtualize(state, tmp_path):
    from utils.test_mode_execution_profiles import TestModeExecutionProfileStore
    profile = TestModeExecutionProfileStore(tmp_path / "profiles.json").resolve("virtual_bridge")
    state.current_experiment_spec.update(test_mode_profile=profile,
        execution_policy=profile["execution_policy"], printer_test_path="virtual_bridge",
        test_printer_transport="virtual")
    return state


@pytest.mark.parametrize("fault", ["", "schema", "profile_id", "printer_test_path", "test_printer_transport",
    "specimen", "vision", "manipulation", "lab_equipment", "teleop", "live", "bare"])
def test_virtual_execution_requires_complete_resolved_test_authority(tmp_path, fault):
    from tests.unit.test_vision_agent import _state
    from utils.test_mode_execution_profiles import is_resolved_all_virtual_bridge
    state = virtualize(_state(), tmp_path)
    spec = state.current_experiment_spec
    mode = state.mode
    if fault in {"schema", "profile_id"}: spec["test_mode_profile"][fault] = "other"
    elif fault in {"printer_test_path", "test_printer_transport"}: spec[fault] = "real"
    elif fault in {"specimen", "vision", "manipulation", "lab_equipment"}:
        spec["test_mode_profile"]["agents"][fault]["device_mode"] = "real"
    elif fault == "teleop": spec["test_mode_profile"]["derived"]["operator_teleop_required"] = True
    elif fault == "live": mode = "live"
    elif fault == "bare": spec.pop("test_mode_profile")
    assert is_resolved_all_virtual_bridge(spec, mode=mode) is (not fault)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["manipulation", "equipment"])
async def test_virtual_owner_cannot_report_preflight_success_on_model_failure(tmp_path, owner):
    from types import SimpleNamespace
    from agents.manipulation_agent import ManipulationAgent
    from agents.equipment_agent import LabEquipmentAgent
    from tests.unit.test_manipulation_lerobot_agent import _state as manipulation_state
    from tests.unit.test_equipment_agent import _state as equipment_state, _tools
    state = virtualize(manipulation_state() if owner == "manipulation" else equipment_state(experiment_spec={}), tmp_path)
    calls = []
    async def unavailable(task_type, prompt, **kwargs):
        calls.append(task_type)
        raise ConnectionError("controlled unavailable model")
    ctx = SimpleNamespace(tools=_tools(tmp_path), complete=unavailable, force_real_llm_in_test=True, knowledge_service=None)
    result = await (ManipulationAgent() if owner == "manipulation" else LabEquipmentAgent()).run(state, ctx)
    assert calls
    assert result.success is False


def test_explicit_virtual_camera_tools_never_enter_native_runtime(tmp_path):
    from mcp_tools.camera_tools import register_camera_tools
    from mcp_tools.tool_registry import ToolRegistry
    class NativeForbidden:
        def __getattr__(self, name):
            def fail(*a, **kw): pytest.fail("native camera boundary: " + name)
            return fail
    tools = ToolRegistry()
    register_camera_tools(tools, utm_runtime_manager=NativeForbidden(),
        utm_state_observer=NativeForbidden().observe)
    payload = {"runtime_mode": "test", "mode": "test", "prefer_virtual_bridge_in_test": True,
        "allow_virtual_bridge_in_test": True}
    assert tools.call("vision.utm_runtime.start", payload)["status"] == "virtual_bridge_selected"
    result = tools.call("vision.equipment_cross_check", {**payload, "checks": [{"check_id": "utm_pre_start"}]})
    assert result["ok"] and result["virtualized"]
    result = tools.call("vision.utm_specimen_presence.capture", {**payload, "output_dir": str(tmp_path)})
    assert result["ok"] and result["virtualized"]


@pytest.mark.parametrize("runtime_mode", ["test", "live"])
def test_explicit_virtual_transport_vetoes_saved_promotion_and_conflicting_live_authority(tmp_path, runtime_mode, monkeypatch):
    from device_bridges.windows_pyautogui_bridge import WindowsPyAutoGUIBridge, WindowsPyAutoGUIBridgeConfig
    bridge = WindowsPyAutoGUIBridge(WindowsPyAutoGUIBridgeConfig.from_devices_config({"devices": {"equipment": {"mode": "simulator",
        "windows_pyautogui": {"connection_memory_path": str(tmp_path / "connection.json"),
            "test_live_promotion": {"enabled": True, "transport": "real", "allow_real_network_in_test": True}}}}}, repo_root=tmp_path))
    assert bridge._should_use_live({"runtime_mode": "test"}, for_execution=True)
    assert not bridge._should_use_live({"runtime_mode": runtime_mode, "virtual_bridge_simulation": True,
        "force_live_bridge": True, "confirm_live_execute": True}, for_execution=True)
    def forbidden(*a, **kw): pytest.fail("virtual equipment entered live transport")
    monkeypatch.setattr(bridge, "_live_precheck", forbidden)
    monkeypatch.setattr(bridge, "_live_post", forbidden)
    result = bridge.run({"runtime_mode": runtime_mode, "virtual_bridge_simulation": True,
        "force_live_bridge": True, "confirm_live_execute": True, "program_id": "program1"})
    assert result["ok"] and result["mode"] == "simulator"


def test_virtual_screenshot_renders_same_run_success_and_failure_without_physical_claims(tmp_path):
    from tests.unit.test_equipment_pyautogui_bridge import _bridge
    from PIL import Image
    bridge = _bridge(tmp_path)
    for program, status in (("program1", "completed"), ("missing", "blocked")):
        bridge.run({"run_id": "virtual-screenshot", "runtime_mode": "test", "program_id": program})
        shot = bridge.screenshot({"run_id": "virtual-screenshot", "runtime_mode": "test"})
        assert shot["simulated"] is True
        assert shot["simulator_state"]["status"] == status
        with Image.open(shot["artifact"]["local_path"]) as raster:
            assert raster.size == (960, 540)
    other = bridge.screenshot({"run_id": "different-run", "runtime_mode": "test"})
    assert other["simulator_state"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["live", "installed_printer", "no_state"])
async def test_nonvirtual_equipment_dispatch_strips_model_virtual_authority(tmp_path, host):
    from agents.equipment_agent import LabEquipmentAgent
    from tests.unit.test_equipment_agent import _state
    from tests.unit.test_equipment_pyautogui_bridge import _bridge
    from types import SimpleNamespace
    from orchestrator.state import Mode
    bridge = _bridge(tmp_path)
    state = _state(experiment_spec={})
    state.mode = Mode.LIVE if host == "live" else Mode.TEST
    if host == "installed_printer": state.current_experiment_spec["printer_test_path"] = host
    dispatched = []
    def call(tool, payload):
        dispatched.append(dict(payload))
        return bridge.run(payload)
    result = await LabEquipmentAgent()._call_tool(SimpleNamespace(tools=SimpleNamespace(call=call)),
        "equipment.pyautogui.run", {"runtime_mode": "live", "program_id": "program1",
        "virtual_bridge_simulation": True, "allow_virtual_bridge_in_test": True,
        "prefer_virtual_bridge_in_test": True}, state=None if host == "no_state" else state)
    assert not set(dispatched[0]) & {"virtual_bridge_simulation", "allow_virtual_bridge_in_test", "prefer_virtual_bridge_in_test"}
    assert result["mode"] == "live" and result["ok"] is False


@pytest.mark.parametrize("changed", ["workflow_execution_id", "loop_id", "specimen_id"])
def test_virtual_screenshot_never_relabels_another_observed_scope(tmp_path, changed):
    from tests.unit.test_equipment_pyautogui_bridge import _bridge
    bridge = _bridge(tmp_path)
    identity = {"run_id": "same-run", "loop_id": 0, "specimen_id": "s1", "workflow_execution_id": "w1"}
    bridge.run({**identity, "runtime_mode": "test", "program_id": "program1"})
    matched = bridge.screenshot({**identity, "runtime_mode": "test"})
    assert matched["simulator_state"]["status"] == "completed"
    assert all(matched[key] == value for key, value in identity.items())
    other = {**identity, changed: 1 if changed == "loop_id" else "different"}
    mismatch = bridge.screenshot({**other, "runtime_mode": "test"})
    assert mismatch["ok"] is False and mismatch["status"] == "unknown"
    assert not mismatch["simulator_state"]


def test_virtual_screenshot_invalidates_success_before_early_validation_failure(tmp_path):
    from tests.unit.test_equipment_pyautogui_bridge import _bridge
    bridge = _bridge(tmp_path)
    payload = {"run_id": "same-run", "loop_id": 0, "specimen_id": "s1", "workflow_execution_id": "w1",
        "runtime_mode": "test", "program_id": "program1"}
    assert bridge.run(payload)["ok"]
    bridge.config.enabled = False
    assert not bridge.run(payload)["ok"]
    # Inspection after re-enabling must not resurrect the old successful operation.
    bridge.config.enabled = True
    shot = bridge.screenshot(payload)
    assert shot["ok"] is False and shot["status"] == "unknown"
    assert not shot["simulator_state"]


@pytest.mark.parametrize("contour", [None, "", ".", "valid"])
def test_csv_analysis_without_optional_fem_contour_does_not_fail_publication(tmp_path, contour):
    from app.controller import MainController
    from types import SimpleNamespace
    from pathlib import Path
    controller = MainController.__new__(MainController)
    controller._state = SimpleNamespace(run_id="virtual-csv")
    controller._deps = SimpleNamespace(run_root=tmp_path)
    artifacts = {}
    if contour == "valid":
        source = tmp_path / "source.svg"
        source.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        artifacts["contour_svg_path"] = str(source)
    elif contour is not None:
        artifacts["contour_svg_path"] = contour
    result = controller._write_planning_fem_artifacts({"specimen_id": "s1"}, {"analysis": {"cae_result": {"artifacts": artifacts}}})
    if contour == "valid":
        assert Path(result["contour_svg_path"]).read_text() == source.read_text()
        assert result["report_path"] == ""
    else:
        assert result == {}


@pytest.mark.asyncio
async def test_virtual_equipment_model_plan_executes_simulator_csv_with_host_transport(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from pathlib import Path
    from agents.equipment_agent import LabEquipmentAgent
    from tests.unit.test_equipment_agent import _state, _tools
    tools = _tools(tmp_path)
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", tmp_path / "flows.json")
    async def decide(*a, **kw):
        return SimpleNamespace(text=json.dumps({"calls": [{"tool": "equipment.pyautogui.run", "payload": {
            "program_id": "utm_compression_start_v1", "runtime_mode": "live", "force_live_bridge": True,
            "confirm_live_execute": True}}]}), raw={}, model="offline-decision-fixture")
    state = virtualize(_state(active_goal="run UTM compression test", experiment_spec={"equipment_profile_id": "utm_windows_v1",
        "specimen_size_mm": [30, 30, 30]}), tmp_path)
    result = await LabEquipmentAgent().run(state, SimpleNamespace(tools=tools, complete=decide,
        force_real_llm_in_test=True, knowledge_service=None))
    assert result.success, result.data
    assert result.data["utm_data_ready"]["schema"] == "utm_data_ready.v1"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    raw = result.data["equipment_result"]
    assert raw["mode"] == "simulator"
    assert Path(raw["result_file"]).is_file()
    assert "force_N" in Path(raw["result_file"]).read_text()


@pytest.mark.asyncio
async def test_virtual_manipulation_model_choice_runs_existing_lerobot_simulator_once(tmp_path):
    import json
    from types import SimpleNamespace
    from agents.manipulation_agent import ManipulationAgent
    from tests.unit.test_manipulation_lerobot_agent import _state, _tools
    state = virtualize(_state(), tmp_path)
    async def decide(task_type, prompt, **kw):
        context = json.loads(prompt.split("\nCONTEXT:\n")[1])
        return SimpleNamespace(text=json.dumps({"tool": "lerobot.rollout.start",
            "arguments": {"proposal_id": context["proposal_id"]}, "reason": "Run configured virtual transfer",
            "evidence_refs": context["evidence_refs"]}), raw={}, model="offline-decision-fixture")
    ctx = SimpleNamespace(tools=_tools(tmp_path), complete=decide, force_real_llm_in_test=True, knowledge_service=None)
    result = await ManipulationAgent().run(state, ctx)
    assert result.success, result.data
    assert result.data["manipulation_decision"]["llm_used"]
    assert result.data["manipulation"]["post_place_interlock"]["ready_for_utm_snapshot"]
    repeated = await ManipulationAgent().run(state, ctx)
    assert not repeated.success and repeated.data["failure_code"] == "MANIPULATION_START_ALREADY_ATTEMPTED"


@pytest.mark.asyncio
async def test_virtual_vision_reviews_existing_synthetic_capture_pair(tmp_path, monkeypatch):
    from agents.vision_agent import VisionAgent
    from tests.unit.test_vision_agent import _state, _CtxStub
    from tests.unit.test_manipulation_lerobot_agent import _tools
    from mcp_tools.camera_tools import register_camera_tools
    state = virtualize(_state(), tmp_path)
    state.current_experiment_spec["lerobot_profile_id"] = "fake_omx_ai"
    tools = _tools(tmp_path)
    register_camera_tools(tools)
    ctx = _CtxStub(tools)
    ctx.force_real_llm_in_test = True
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    result = await VisionAgent().run(state, ctx)
    assert result.success, result.data
    assert result.data["vision_tool_decision"]["llm_used"]
    assert result.data["vision_decision"]["llm_used"]


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_dataset", [True, False])
async def test_resolved_virtual_clearance_runs_replay_and_visual_decisions_or_blocks(tmp_path, valid_dataset):
    import json
    from types import SimpleNamespace
    from tests.unit.test_utm_clear_cycle import state_with_placement, equipment_data
    from tests.unit.test_lerobot_replay import dataset_at
    from tests.unit.test_manipulation_lerobot_agent import _tools
    from mcp_tools.camera_tools import register_camera_tools
    from utils import utm_clear_cycle as cycle
    from orchestrator.state import Mode, Stage
    state = state_with_placement()
    state.mode = Mode.TEST
    virtualize(state, tmp_path)
    state.current_experiment_spec.update(lerobot_dataset_root=str(tmp_path), lerobot_profile_id="robotis_omx_ai")
    if valid_dataset: dataset_at(tmp_path / "jin/utm_clear")
    tools = _tools(tmp_path)
    register_camera_tools(tools)
    calls = []
    async def decide(task_type, prompt, **kw):
        context = json.loads(prompt.split("\nCONTEXT:\n")[1])
        calls.append((task_type, bool(kw.get("images"))))
        if task_type == "vision_observation":
            tool, arguments = "accept_visual_evidence", {"contract_id": context["contract_id"]}
        else:
            tool = "accept_task_result" if kw.get("images") else "lerobot.replay.start"
            if "accept_task_result" in context.get("tools", {}): tool = "accept_task_result"
            arguments = {"proposal_id": context["proposal_id"]}
        return SimpleNamespace(text=json.dumps({"tool": tool, "arguments": arguments,
            "reason": "Scoped offline decision fixture", "evidence_refs": context["evidence_refs"]}),
            raw={}, model="offline-decision-fixture")
    ctx = SimpleNamespace(tools=tools, complete=decide, force_real_llm_in_test=True, knowledge_service=None)
    cycle.merge_utm_clear_cycle(state, Stage.EQUIPMENT, equipment_data(state))
    result = await cycle.run_clear_manipulation(state, ctx, spec=state.current_experiment_spec)
    assert calls
    if not valid_dataset:
        assert not result.success
        assert cycle.current_clear(state)["state"] == "error"
        assert not cycle.current_clear(state).get("visual_clearance_confirmed")
        return
    assert result.success, result.data
    result = await cycle.run_clear_vision(state, ctx, artifact_dir=tmp_path / "clear")
    assert result.success and cycle.current_clear(state)["success"] is True, result.data
    assert ("vision_observation", True) in calls
    assert result.data["utm_verification_2"]["record"]["evidence"]["virtualized"]


@pytest.mark.asyncio
async def test_virtual_vision_cannot_bypass_unavailable_real_model(tmp_path):
    from types import SimpleNamespace
    from tests.unit.test_vision_agent import _state
    from agents.vision_agent import VisionAgent
    from mcp_tools.tool_registry import ToolRegistry
    from utils.test_mode_execution_profiles import TestModeExecutionProfileStore
    from scripts.orchestrator_verification_guard import VerificationGuard

    state = _state()
    profile = TestModeExecutionProfileStore(tmp_path / "profiles.json").resolve("virtual_bridge")
    state.current_experiment_spec.update(test_mode_profile=profile,
        execution_policy=profile["execution_policy"], printer_test_path="virtual_bridge",
        test_printer_transport="virtual")
    calls = []

    async def unavailable(task_type, prompt, **kwargs):
        calls.append(task_type)
        raise ConnectionError("Model unavailable in controlled regression")

    with VerificationGuard() as guard:
        ctx = SimpleNamespace(tools=ToolRegistry(), force_real_llm_in_test=True,
                              complete=unavailable, knowledge_service=None)
        result = await VisionAgent().run(state, ctx)
        assert calls, "Virtual-device profile bypassed the existing LLM decision"
        assert result.success is False, "Model failure must not become successful virtual preflight"
        assert guard.physical_call_count == 0 and not guard.denied
