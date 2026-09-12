"""Verification of existing orchestration paths; simulated I/O is not hardware proof."""
from copy import deepcopy
import itertools
import time
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_guard_rejects_network_native_camera_process_and_unlisted_tool_before_bootstrap():
    import socket
    import subprocess
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        import cv2
        from mcp_tools.tool_registry import ToolRegistry
        tools = ToolRegistry()
        touched = []
        tools.register("printer.send", lambda request: touched.append(request))
        for effect in (lambda: socket.create_connection(("127.0.0.1", 8000)),
                       lambda: subprocess.run(["true"]), lambda: cv2.VideoCapture(0),
                       lambda: open("/dev/video0", "rb"), lambda: tools.call("printer.send", {})):
            with pytest.raises(AssertionError, match="Physical tool invocation"):
                effect()
        assert touched == []
        assert len(guard.denied) == 5
        assert guard.physical_call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "busy", "unavailable", "unknown", "blocked"])
async def test_owner_availability_preserves_fresh_meaning_without_manufacturing_readiness(status):
    """Collapsing a trustworthy busy/unavailable report loses the owner's decision evidence."""
    from agents.orchestrator_capabilities import OwnerCatalog
    from agents.registry import AgentRegistry
    from agents.bo_agent import BOAgent
    from graphs.schema import load_graph_config
    from orchestrator.state import OrchestratorState
    state = OrchestratorState(run_id="availability-verification", experiment_id="availability")
    registry = AgentRegistry()
    registry.register(BOAgent())
    catalog = OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml"))
    now = time.time()
    report = dict(owner="bo_agent", capability="inspect", run_id=state.run_id,
        status=status, observed_at=now - 1, expires_at=now + 60, evidence_refs=["owner:reported"])
    state.run_metadata["availability_reports"] = {"bo_agent": {"inspect": report}}
    original = deepcopy(report)
    assert (await catalog.inspect("bo_agent", "inspect", state, None))["status"] == status
    assert report == original
    report["expires_at"] = now - 0.5
    assert (await catalog.inspect("bo_agent", "inspect", state, None))["status"] == "unknown"
    state.run_metadata.clear()
    assert (await catalog.inspect("bo_agent", "inspect", state, None))["status"] == "unknown"


@pytest.mark.parametrize("modes", list(itertools.product(("real", "virtual"), repeat=4)))
def test_all_sixteen_mode_combinations_preserve_resolver_admission(tmp_path, modes):
    """Changing a boundary policy or admitting virtual-vision real-robot is unsafe."""
    from utils.test_mode_execution_profiles import TestModeExecutionProfileStore
    specimen, vision, manipulation, equipment = modes
    profile = {"agents": {name: {"device_mode": mode} for name, mode in zip(
        ("specimen", "vision", "manipulation", "lab_equipment"), modes)},
        "printer_flow": {"print_body": "execute", "cooling_wait": "execute", "auto_ejection": True},
        "handoff": {"strategy": "operator_teleop"}}
    store = TestModeExecutionProfileStore(tmp_path / "profiles.json")
    if vision == "virtual" and manipulation == "real":
        with pytest.raises(ValueError):
            store.save_profile("physical_print", profile, expected_revision=0)
        return
    store.save_profile("physical_print", profile, expected_revision=0)
    resolved = store.resolve("physical_print")
    assert resolved["execution_policy"] == {name: "execute" if mode == "real" else "preflight_only"
        for name, mode in zip(("printer", "vision", "manipulation", "lab_equipment"), modes)}
    assert resolved["derived"]["operator_teleop_required"] is (manipulation == "virtual" and equipment == "real")


def test_equipment_module_admits_its_registered_enabled_vision_observer():
    from graphs import load_module_config
    from utils.equipment_agentic_task import build_utm_compression_flow_template
    flow = build_utm_compression_flow_template("utm_windows_v1")
    assert any(block["vision"]["enabled"] for block in flow["blocks"])
    module = load_module_config("graphs/modules/equipment/module.yaml")
    assert "vision.equipment_cross_check" in module.tools


def test_live_state_compaction_preserves_exact_setup_and_once_only_authority(actual_controller):
    controller, _ = actual_controller
    keys = ("experimental_setup_snapshot", "bo_settings", "execution_policy", "test_mode_profile",
        "orchestrator_checkpoints", "orchestrator_planning_boundary", "orchestrator_observation_refresh",
        "orchestrator_review_revision", "availability_reports", "orchestrator_incoming_handoff",
        "orchestrator_pending_handoff", "orchestrator_waiting_entry", "experimental_setup_source")
    values = {key: {"nested": {"complete_untruncated": list(range(40))}, "identity": key} for key in keys}
    controller._state.run_metadata.update(deepcopy(values), raw_trace=["unbounded presentation"] * 40)
    metadata = controller._state.run_metadata
    checkpoint = metadata["orchestrator_checkpoints"]
    controller._compact_planning_runtime_state()
    assert {key: controller._state.run_metadata.get(key) for key in keys} == values
    assert controller._state.run_metadata is metadata
    assert metadata["orchestrator_checkpoints"] is checkpoint
    assert "raw_trace" not in controller._state.run_metadata
    public = controller._compact_planning_run_metadata(controller._state.run_metadata)
    assert "orchestrator_checkpoints" not in public


@pytest.mark.parametrize("mutation", [None, "run", "specimen", "loop", "session", "stale", "missing_file", "not_stopped", "not_verified"])
def test_real_manipulation_equipment_preflight_requires_scoped_stop_and_fresh_vision(actual_controller, tmp_path, mutation):
    from agents.equipment_agent import LabEquipmentAgent
    from datetime import datetime, timezone, timedelta
    controller, _ = actual_controller
    state = controller._state
    state.current_experiment_spec = {"specimen_id": "scoped-specimen"}
    artifact = tmp_path / "observed.png"
    artifact.write_bytes(b"controlled artifact reference, not detector proof")
    robot = {"run_id": state.run_id, "specimen_id": "scoped-specimen", "handoff_status": "ready_for_equipment",
        "completion_status": "verified_complete", "session_id": "scoped-session"}
    stop = {"ok": True, "status": "STOPPED", "session_id": "scoped-session"}
    signal = {"run_id": state.run_id, "specimen_id": "scoped-specimen", "loop_id": state.loop_count,
        "session_id": "scoped-session", "detected": True, "rollout_stopped": True,
        "timestamp": datetime.now(timezone.utc).isoformat(), "evidence_path": str(artifact)}
    if mutation in {"run", "specimen", "loop", "session"}:
        signal[{"run": "run_id", "specimen": "specimen_id", "loop": "loop_id", "session": "session_id"}[mutation]] = "foreign"
    if mutation == "stale":
        signal["timestamp"] = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    if mutation == "missing_file":
        signal["evidence_path"] += ".missing"
    if mutation == "not_stopped":
        stop["status"] = "POLICY_ACTIVE"
    if mutation == "not_verified":
        robot["completion_status"] = "stopped_pending_task_review"
    state.run_metadata.update(robot_task_result=robot,
        manipulation_result={**robot, "rollout_stop": stop},
        latest_vision_observation={"vision_manipulation_completion": signal})
    assert LabEquipmentAgent()._real_manipulation_preflight_ready(state, "scoped-specimen") is (mutation is None)


@pytest.mark.asyncio
async def test_original_replay_copies_trace_without_owners_or_setup_activation(actual_controller, monkeypatch):
    from orchestrator.state import Mode, Stage
    controller, guard = actual_controller
    block = next(b for b in controller._planning_setup_projection()["blocks"] if b["topic_key"] == "research.goal")
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "Next live experiment only"}, "replay-propose")
    await controller.planning_setup_action({"action": "confirm", "proposal_id": proposal["proposal_id"],
        "expected_revision": proposal["block_revision"], "request_id": "replay-confirm",
        "session_id": controller._planning_session_id, "target": "next_run"})
    before = store.snapshot()
    trace = [{"event_id": "controlled-recorded-event", "event_type": "node.completed",
        "payload": {"fixture": "supplied_trace_not_historical_run"}}]
    controller._last_completed_trace = deepcopy(trace)
    recorded = []
    original = controller._broadcast_event
    async def observe(event):
        recorded.append(deepcopy(event))
        return await original(event)
    monkeypatch.setattr(controller, "_broadcast_event", observe)
    result = await controller.start(mode=Mode.REPLAY)
    assert result["ok"]
    await asyncio.wait_for(controller._run_task, timeout=3)
    assert controller._state.mode == Mode.REPLAY and controller._state.stage == Stage.COMPLETE
    assert controller._state.agent_status == {}
    assert store.snapshot() == before
    assert "experimental_setup_snapshot" not in controller._state.run_metadata
    assert controller._last_completed_trace == trace
    assert [e["event_type"] for e in recorded if e.get("event_type", "").startswith("replay")] == ["replay_event", "replay_complete"]
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_original_persistent_fault_retries_before_owner_and_model(actual_controller, monkeypatch, tmp_path):
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Mode, Stage
    from logging_system.structured_logger import StructuredLogger
    from agents.bo_agent import BOAgent
    controller, guard = actual_controller
    state = controller._state
    state.mode, state.stage = Mode.FAULT_INJECTION, Stage.BO
    state.fault_injection = {"fault": "model_timeout", "stage": "bo"}
    called = []
    original = BOAgent.run
    async def owner(self, *args):
        called.append("owner")
        return await original(self, *args)
    monkeypatch.setattr(BOAgent, "run", owner)
    events = []
    async def event(payload):
        events.append(payload)
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name=controller._deps.orchestrator_agent_name, ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "fault.jsonl", tmp_path / "fault.log"),
        max_retry_per_stage=1, on_event=event)
    await runtime.step()
    assert state.stage == Stage.BO and state.retry_counters["bo"] == 1
    await runtime.step()
    # Counter records retries admitted, not the terminal failed attempt.
    assert state.stage == Stage.ERROR and state.retry_counters["bo"] == 1
    assert state.mode == Mode.FAULT_INJECTION and called == []
    assert not any(e.get("type") == "node.completed" for e in events)
    assert "orchestrator_pending_handoff" not in state.run_metadata
    assert guard.physical_call_count == 0


@pytest.fixture
def actual_controller(tmp_path, monkeypatch):
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        import app.bootstrap as bootstrap
        from agents.analysis_runtime import AnalysisRuntimeService
        from knowledge.stores import JsonlKnowledgeStore
        memory = JsonlKnowledgeStore(memory_root=tmp_path / "memory/knowledge", run_root=tmp_path / "runs")
        monkeypatch.setattr(JsonlKnowledgeStore, "default", classmethod(lambda cls, project_root=None: memory))
        from device_bridges.calculix_bridge import CalculiXBridge
        def version_process(self, command, **kwargs):
            assert kwargs["phase"] == "version" and command[-1] in {"-v", "--version"}, command
            guard.simulated_boundary_requests.append({"tool": "solver.version", "command": command})
            stdout = kwargs["workdir"] / "version.stdout.log"
            stderr = kwargs["workdir"] / "version.stderr.log"
            stdout.write_text("controlled non-executed solver version")
            stderr.write_text("")
            return {"status": "completed", "returncode": 0, "stdout_path": str(stdout), "stderr_path": str(stderr)}
        monkeypatch.setattr(CalculiXBridge, "_run_process", version_process)
        # Background compute is an explicit non-actuating boundary, not an owner.
        monkeypatch.setattr(AnalysisRuntimeService, "resume", lambda *a, **k: False)
        configurations = bootstrap._load_configs()
        monkeypatch.setattr(bootstrap, "_load_configs", lambda: deepcopy(configurations))
        original_resolve = bootstrap.resolve_path
        def resolve(path):
            value = str(path).removeprefix("./")
            if value == ".":
                return tmp_path
            if value.startswith(("memory", "runs", "output", "logs")):
                return tmp_path / value
            return original_resolve(path)
        monkeypatch.setattr(bootstrap, "resolve_path", resolve)
        import agents.analysis_agent as analysis_module
        monkeypatch.setattr(analysis_module, "resolve_path", resolve)
        from agents.vision_agent import VisionAgent
        monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
        controller = bootstrap.load_runtime()
        controller._state.active_session_id = "controlled-session"
        controller._state.run_id = "controlled-run"
        controller._state.experiment_id = "controlled-experiment"
        decision_prompts = []
        guard.allowed_tools.update({"experiment.benchmark", "experiment.evaluate", "source.query", "cae.run_static_analysis"})
        from agents.base_agent import AgentContext
        original_complete = AgentContext.complete
        async def complete(self, task_type, prompt, **kwargs):
            if task_type == "design_reasoning":
                data = json.loads(prompt[prompt.index('{"context"'):])["context"]
                candidate = next(c for c in data["candidates"] if c["evaluation"]["validity"]["status"] == "pass")
                cid = candidate["candidate_id"]
                return SimpleNamespace(model="controlled-design", raw={}, text=json.dumps({"tool": "accept_candidate",
                    "arguments": {"candidate_id": cid}, "reason": "Requested coordinates and domain checks pass",
                    "evidence_refs": [f"candidate:{cid}"]}))
            try:
                packet = json.loads(prompt)
            except (TypeError, ValueError):
                packet = {}
            if packet.get("operation") == "decide_orchestration":
                decision_prompts.append({"prompt": prompt, "utf8_bytes": len(prompt.encode("utf-8")),
                    "characters": len(prompt), "sections": {key: len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                        for key, value in packet.items()}})
                candidates = packet["context"].get("handoff_candidates", [])
                return SimpleNamespace(model="controlled-json", raw={}, text=json.dumps({
                    "tool": "prepare_handoff" if candidates else "defer",
                    "arguments": {"candidate": candidates[0]} if candidates else {"condition": "No dispatcher candidate"},
                    "reason": "Preserve existing admitted owner preconditions", "evidence_refs": list(packet["evidence"])}))
            from backends.mock_llm import MockLLMBackend
            from backends.prompt_registry import get_system_prompt
            return await MockLLMBackend().complete(model="controlled-tail", system_prompt=get_system_prompt(task_type),
                user_prompt=prompt, metadata={"task_type": task_type})
        monkeypatch.setattr(AgentContext, "complete", complete)
        from orchestrator.langgraph_runtime import ModuleRuntimeContext
        monkeypatch.setattr(ModuleRuntimeContext, "complete", complete)
        yield controller, guard
        (tmp_path / "controlled-decision-prompts.json").write_text(json.dumps(decision_prompts, ensure_ascii=False, indent=2))
        assert not guard.denied, guard.denied


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_stage,profile", [("design", "virtual_bridge"), ("specimen", "virtual_bridge"),
    ("specimen", "installed_printer"), ("specimen", "physical_print"), ("next_design", "virtual_bridge")])
async def test_confirmed_setup_enters_original_initial_lhs_and_real_design(actual_controller, monkeypatch, tmp_path, stop_stage, profile):
    """The genuine new-series entry must apply captured setup before owner sampling."""
    from agents.bo_agent import BOAgent
    from agents.design_agent import DesignAgent
    controller, guard = actual_controller
    if stop_stage != "design":
        from orchestrator_setup_fixtures import printer_io
        printer = printer_io(controller, monkeypatch, tmp_path, guard)
    snapshot = controller.planning_snapshot()["state"]["setup"]
    block = next(b for b in snapshot["blocks"] if b["topic_key"] == "bo.parameter_space")
    values = deepcopy(block["draft_values"]["bo.parameter_space"])
    values.update(cell_size_mm=[7, 8], relative_density=[.30, .40])
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"bo.parameter_space": values}, "propose-bounds")
    old_state = controller._state
    before = old_state.model_dump()
    await controller.planning_setup_action({"action": "confirm", "proposal_id": proposal["proposal_id"],
        "expected_revision": proposal["block_revision"], "request_id": "confirm-bounds",
        "session_id": controller._planning_session_id, "target": "next_run"})
    assert old_state.model_dump() == before
    seeds, designs, bo_runs, specimen_runs = [], [], [], []
    from agents.specimen_agent import SpecimenMakingAgent
    original_specimen = SpecimenMakingAgent.run
    async def observed_specimen(self, state, ctx):
        result = await original_specimen(self, state, ctx)
        specimen_runs.append(result)
        return result
    monkeypatch.setattr(SpecimenMakingAgent, "run", observed_specimen)
    original_bo = BOAgent.run
    async def observed_bo(self, state, ctx):
        entry_settings = deepcopy(state.run_metadata["bo_settings"])
        entry_spec = deepcopy(state.current_experiment_spec)
        result = await original_bo(self, state, ctx)
        bo_runs.append({"result": result, "next": deepcopy(result.data.get("next_design_request")),
            "entry_settings": entry_settings, "entry_spec": entry_spec})
        return result
    monkeypatch.setattr(BOAgent, "run", observed_bo)
    initial = BOAgent.initial_design_request
    def observed_initial(cls, state, *args, **kwargs):
        result = initial(state, *args, **kwargs)
        seeds.append({"space": deepcopy(state.run_metadata["bo_settings"]["parameter_space"]), "result": deepcopy(result)})
        return result
    monkeypatch.setattr(BOAgent, "initial_design_request", classmethod(observed_initial))
    original_design = DesignAgent.run
    async def observed_design(self, state, ctx):
        result = await original_design(self, state, ctx)
        designs.append({"result": result, "contract": deepcopy(state.run_metadata["orchestrator_design_contract"]),
            "snapshot": deepcopy(state.run_metadata["experimental_setup_snapshot"])})
        return result
    monkeypatch.setattr(DesignAgent, "run", observed_design)
    guard.allowed_tools.update({"geometry.generate_metamaterial_stl", "geometry.check_mesh_quality", "geometry.check_manufacturability"})
    if stop_stage != "design":
        guard.allowed_tools.update({"artifact.create_specimen_handoff", "printer.prepare"})
    append = controller._append_planning_message
    reached = asyncio.Event()
    async def stop_after_design(*args, **kwargs):
        await append(*args, **kwargs)
        if (kwargs.get("event_type") == f"planning_{stop_stage}_result" or
                (stop_stage == "next_design" and kwargs.get("event_type") == "planning_design_result" and len(designs) == 2)):
            reached.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(controller, "_append_planning_message", stop_after_design)
    constraints = controller._apply_specimen_printer_choice_to_spec(
        controller._default_test_constraints({"test_mode_autofill": True, "test_mode_llm_generated": True}), profile)
    if stop_stage == "next_design":
        from orchestrator_setup_fixtures import equipment_io
        from utils.utm_reference_calibration import build_reference_calibration
        equipment = equipment_io(controller, monkeypatch, tmp_path, guard)
        reference = tmp_path / "controlled-reference.csv"
        reference.write_text("time_s,force_N,displacement_mm\n" + "".join(f"{i},{100*i},{i}\n" for i in range(17)))
        calibration = build_reference_calibration([reference], target_strain=.5, specimen_size_mm=[30, 30, 30])
        assert calibration["status"] == "ready"
        calibration["limitations"].append("controlled_fixture_not_measured")
        constraints.update(cae_reference_calibration=calibration, equipment_skill_registry_root=equipment["skills"],
            equipment_profile_id="utm_windows_v1")
        from mcp_tools.cae_tools import register_cae_tools
        register_cae_tools(controller._deps.agent_context.tools, {"devices": {"cae": {
            "enabled": True, "mode": "test", "artifact_dir": str(tmp_path / "cae"),
            "reference_utm_globs": [str(reference)], "reference_target_strain": .5,
            "reference_specimen_size_mm": [30, 30, 30]}}}, repo_root=tmp_path)
        from mcp_tools.mock_tools import _device_health
        def health(payload):
            guard.simulated_boundary_requests.append({"tool": "device.health", "payload": deepcopy(payload)})
            return _device_health(payload)
        guard.allowed_tools.add("device.health")
        controller._deps.agent_context.tools.register("device.health", health)
    task = asyncio.create_task(controller._handoff_planning_to_design(goal="controlled bounds verification", constraints=constraints))
    event_task = asyncio.create_task(reached.wait())
    try:
        done, _ = await asyncio.wait({task, event_task}, timeout=120 if stop_stage == "next_design" else 40,
            return_when=asyncio.FIRST_COMPLETED)
        assert reached.is_set(), (task.result() if task.done() else "No Design result within bound", designs)
        # Admission and stage publication read the same pure deterministic seed;
        # they must not perform a second Design or select different coordinates.
        assert len(seeds) == 2 and len(designs) == (2 if stop_stage == "next_design" else 1)
        assert seeds[0] == seeds[1]
        assert designs[0]["result"].success, designs[0]["result"]
        assert seeds[0]["result"]["parameter_space"] == seeds[0]["space"] == values
        assert controller._state.run_id != old_state.run_id
        # Existing new-series entry clears transient UI/safety metadata on the
        # retired state; it must retain that run's domain/execution inputs.
        for key in ("run_id", "experiment_id", "mode", "active_goal", "current_experiment_spec"):
            assert old_state.model_dump()[key] == before[key]
        for key in ("experimental_setup_snapshot", "bo_settings", "test_mode_profile", "execution_policy"):
            assert old_state.run_metadata.get(key) == before["run_metadata"].get(key)
        assert designs[0]["contract"]["requested_parameters"] == {
            key: seeds[0]["result"]["constraints"][key] for key in ("cell_size_mm", "relative_density")}
        if stop_stage == "next_design":
            assert len(bo_runs) == 1 and bo_runs[0]["result"].success
            assert designs[1]["result"].success
            assert designs[1]["contract"]["requested_parameters"] == {
                key: bo_runs[0]["next"]["constraints"][key] for key in ("cell_size_mm", "relative_density")}
            assert designs[1]["snapshot"] == designs[0]["snapshot"]
            assert bo_runs[0]["entry_settings"]["parameter_space"] == values
            # Baseline BO._fixed_surface_space_for_state deliberately carries
            # non-optimized manufacturing geometry from the completed specimen.
            expected = deepcopy(values)
            entry_spec = bo_runs[0]["entry_spec"]
            for key in set(values) - {"cell_size_mm", "relative_density"}:
                for source in (entry_spec, entry_spec.get("constraints", {})):
                    if key in source and source[key] not in (None, "", []):
                        expected[key] = [source[key]]
                        break
            assert {k for k in values if values[k] != expected[k]} == {"tpms_thickness", "skin_thickness_mm", "bottom_cap_enabled"}
            expected_settings = {**bo_runs[0]["entry_settings"], "parameter_space": expected}
            assert controller._state.run_metadata["bo_settings"] == expected_settings
            assert {key: bo_runs[0]["next"]["parameter_space"][key] for key in ("cell_size_mm", "relative_density")} == {
                key: values[key] for key in ("cell_size_mm", "relative_density")}
            assert equipment["calls"] == []
        else:
            assert bo_runs == []
        if stop_stage == "specimen":
            assert len(specimen_runs) == 1 and specimen_runs[0].success
            if profile != "virtual_bridge":
                # Printer completion is not after-print camera confirmation.
                assert controller._state.agent_status["specimen_agent"].success is None
            assert controller._state.run_metadata["specimen_result"]["ok"] is True
            publishes = [call for call in printer["calls"] if call["tool"] == "printer.publish_project_file"]
            assert len(publishes) == (0 if profile == "virtual_bridge" else 1)
            if profile != "virtual_bridge":
                import zipfile
                suffix = ".ejection-test.gcode.3mf" if profile == "installed_printer" else ".autoeject.gcode.3mf"
                archives = list(printer["root"].rglob("*" + suffix))
                # Original patch and HTTP-export copy must have identical bytes.
                assert len(archives) == 2, archives
                assert archives[0].read_bytes() == archives[1].read_bytes()
                with zipfile.ZipFile(archives[0]) as archive:
                    gcode = archive.read("Metadata/plate_1.gcode").decode()
                assert "atr.bambu.autoejection.v1" in gcode
                assert ("atr_print_body_omitted=true" in gcode) is (profile == "installed_printer")
                assert ("M190 R40" in gcode) is (profile == "physical_print")
    finally:
        task.cancel()
        event_task.cancel()
        await asyncio.gather(task, event_task, return_exceptions=True)
        (tmp_path / "prefix-evidence.json").write_text(json.dumps({"state": controller._state.model_dump(),
            "events": controller.recent_events(), "seeds": seeds, "designs": designs, "bo_runs": bo_runs,
            "simulated_boundary_requests": guard.simulated_boundary_requests,
            "old_metadata_changed_keys": sorted(key for key in old_state.run_metadata.keys() | before["run_metadata"].keys()
                if old_state.run_metadata.get(key) != before["run_metadata"].get(key))}, default=str, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["virtual_profile", "legacy_tail", "real_manip_virtual_equipment", "virtual_manip_real_equipment"])
async def test_actual_tail_preserves_profile_preflight_or_deployed_csv_contract(actual_controller, monkeypatch, tmp_path, path):
    """A missing compiled skill, wrong CSV or skipped owner must fail the real tail."""
    from orchestrator.state import Mode
    from orchestrator_setup_fixtures import equipment_io
    from PIL import Image, ImageDraw
    controller, guard = actual_controller
    equipment = equipment_io(controller, monkeypatch, tmp_path, guard)
    controller._state.mode = Mode.LIVE
    tools = controller._deps.agent_context.tools
    frame = tmp_path / "utm.png"
    pixels = Image.new("RGB", (640, 480), (205, 205, 205))
    draw = ImageDraw.Draw(pixels)
    draw.rectangle((360, 85, 439, 179), fill=(210, 25, 30))
    draw.rectangle((50, 350, 209, 469), fill=(225, 20, 25))
    draw.rectangle((455, 350, 619, 469), fill=(225, 20, 25))
    pixels.save(frame)
    def simulated(name, callback):
        guard.allowed_tools.add(name)
        def call(payload):
            guard.simulated_boundary_requests.append({"tool": name, "payload": deepcopy(payload)})
            return callback(payload)
        tools.register(name, call)
    for name in ("vision.utm_runtime.start", "vision.utm_runtime.status"):
        simulated(name, lambda p: {"ok": True, "status": "running", "source": "controlled_test_io"})
    from mcp_tools.mock_tools import _camera_capture, _device_health
    simulated("camera.capture", _camera_capture)
    simulated("device.health", _device_health)
    simulated("lerobot.camera.test", lambda p: {"ok": True, "tool": "lerobot.camera.test", "mode": p["runtime_mode"],
        "port_released": True, "camera_returned_to_vla": True, "camera_owner_after": "vla_runtime",
        "capture": {"ok": True, "path": str(frame), "width": 640, "height": 480, "synthetic": True,
            "port_released": True, "camera_returned_to_vla": True, "camera_owner_after": "vla_runtime"}})
    simulated("lerobot.rollout.start", lambda p: {"ok": True, "tool": "lerobot.rollout.start", "workflow": "rollout",
        "status": "POLICY_ACTIVE", "runtime_phase": "ACTION_ACTIVE", "action_count": 120,
        "session_id": "controlled-rollout", "profile_id": p.get("profile_id", ""),
        "post_place_interlock": {"schema": "post_place_interlock.v1", "session_id": "controlled-rollout",
            "ungrasping_seen": True, "home_after_ungrasping": True, "ready_for_utm_snapshot": True}})
    simulated("lerobot.rollout.status", lambda p: {"ok": True, "tool": "lerobot.rollout.status", "workflow": "rollout",
        "status": "POLICY_ACTIVE", "runtime_phase": "ACTION_ACTIVE", "action_count": 120,
        "session_id": p["session_id"], "post_place_interlock": {"schema": "post_place_interlock.v1",
            "session_id": p["session_id"], "ungrasping_seen": True, "home_after_ungrasping": True,
            "ready_for_utm_snapshot": True}})
    simulated("vision.utm_specimen_presence.capture", lambda p: {"ok": True,
        "tool": "vision.utm_specimen_presence.capture", "schema": "vision_utm_specimen_presence.v1",
        "status": "confirmed", "detected": True, "source": "virtual_utm_camera", "frame_id": p["frame_id"],
        "annotated_frame_path": str(frame), "raw_frame_path": str(frame), "confidence": .95,
        "width": 640, "height": 480, "run_id": p["run_id"], "session_id": p["session_id"], "specimen_id": p["specimen_id"]})
    simulated("lerobot.rollout.stop", lambda p: {"ok": True, "tool": "lerobot.rollout.stop", "workflow": "rollout",
        "status": "STOPPED", "session_id": p["session_id"]})
    spec = controller._build_planning_spec(base_spec={"candidate_id": "controlled-candidate", "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30]}, constraints={"geometry_type": "gyroid", "specimen_size_mm": [30, 30, 30],
        "test_mode_autofill": True, "test_mode_llm_generated": True, "printer_test_path": "virtual_bridge"})
    hybrid = path in {"real_manip_virtual_equipment", "virtual_manip_real_equipment"}
    if hybrid:
        from utils.test_mode_execution_profiles import TestModeExecutionProfileStore
        controller._test_mode_execution_profiles_path = tmp_path / "hybrid-profiles.json"
        modes = {"specimen": "real", "vision": "real", "manipulation": "real" if path.startswith("real_manip") else "virtual",
            "lab_equipment": "virtual" if path.startswith("real_manip") else "real"}
        TestModeExecutionProfileStore(controller._test_mode_execution_profiles_path).save_profile("physical_print", {
            "agents": {k: {"device_mode": v} for k, v in modes.items()},
            "printer_flow": {"print_body": "execute", "cooling_wait": "execute", "auto_ejection": True},
            "handoff": {"strategy": "operator_teleop"}}, expected_revision=0)
        spec = controller._apply_specimen_printer_choice_to_spec(spec, "physical_print")
    if path in {"virtual_profile", "real_manip_virtual_equipment"}:
        if not hybrid:
            spec = controller._apply_specimen_printer_choice_to_spec(spec, "virtual_bridge")
        from utils.utm_reference_calibration import build_reference_calibration
        reference = tmp_path / "controlled-reference.csv"
        reference.write_text("time_s,force_N,displacement_mm\n" + "".join(
            f"{i},{100 * i},{i}\n" for i in range(17)))
        calibration = build_reference_calibration([reference], target_strain=.5, specimen_size_mm=[30, 30, 30])
        assert calibration["status"] == "ready"
        calibration["limitations"].append("controlled_fixture_not_measured")
        spec["cae_reference_calibration"] = calibration
    spec.update(equipment_skill_registry_root=equipment["skills"], equipment_profile_id="utm_windows_v1",
        raw_csv_session_id="controlled-session", specimen_id="controlled-specimen")
    controller._state.current_experiment_spec = spec
    controller._state.run_metadata["specimen_result"] = {"ok": True, "candidate_id": spec["candidate_id"],
        "specimen_id": spec["specimen_id"], "handoff_status": "ready", "stl_path": str(tmp_path / "upstream.stl")}
    result = None
    try:
        if hybrid:
            reached, held = asyncio.Event(), asyncio.Event()
            barrier = asyncio.Event()
            original_event = controller._broadcast_event
            async def observed_event(event):
                await original_event(event)
                if event.get("event_type") == "pending_operator_teleop_handoff":
                    held.set()
                if path == "real_manip_virtual_equipment" and event.get("type") == "node.completed" and event.get("node_id") == "equipment":
                    reached.set()
                    await barrier.wait()
            monkeypatch.setattr(controller, "_broadcast_event", observed_event)
            if path == "virtual_manip_real_equipment":
                from agents.equipment_agent import LabEquipmentAgent
                original_equipment = LabEquipmentAgent.run
                async def observed_equipment(self, state, ctx):
                    assert state.run_metadata["operator_teleop_handoff"]["status"] == "confirmed"
                    reached.set()
                    await barrier.wait()
                    return await original_equipment(self, state, ctx)
                monkeypatch.setattr(LabEquipmentAgent, "run", observed_equipment)
            tail_task = asyncio.create_task(controller._run_planning_loop_tail(spec))
            try:
                if path == "virtual_manip_real_equipment":
                    held_task = asyncio.create_task(held.wait())
                    try:
                        await asyncio.wait({tail_task, held_task}, timeout=45, return_when=asyncio.FIRST_COMPLETED)
                        assert held.is_set(), tail_task.result() if tail_task.done() else "No teleop hold event"
                    finally:
                        held_task.cancel()
                        await asyncio.gather(held_task, return_exceptions=True)
                    assert equipment["calls"] == [] and not reached.is_set()
                    pending = deepcopy(controller._state.run_metadata["pending_operator_teleop_handoff"])
                    before_identity = (controller._state.run_id, controller._state.loop_count, spec["specimen_id"])
                    from orchestrator_setup_fixtures import confirm_original_teleop_api
                    await confirm_original_teleop_api(controller, monkeypatch, guard, pending)
                reached_task = asyncio.create_task(reached.wait())
                try:
                    await asyncio.wait({tail_task, reached_task}, timeout=45, return_when=asyncio.FIRST_COMPLETED)
                    assert reached.is_set(), tail_task.result() if tail_task.done() else "No Equipment boundary"
                finally:
                    reached_task.cancel()
                    await asyncio.gather(reached_task, return_exceptions=True)
                assert equipment["calls"] == []
                if path == "virtual_manip_real_equipment":
                    handoff = controller._state.run_metadata["operator_teleop_handoff"]
                    assert handoff["status"] == "confirmed" and handoff["handoff_token"] == pending["handoff_token"]
                    assert before_identity == (controller._state.run_id, controller._state.loop_count, spec["specimen_id"])
                    manipulation = controller._state.run_metadata["manipulation_result"]
                    assert manipulation["workflow"] == "teleoperate"
                    assert manipulation["pre_teleop_execution_provenance"]["workflow"] == "rollout"
                    completion = controller._state.run_metadata["latest_vision_observation"]["vision_manipulation_completion"]
                    assert completion["rollout_execution"]["required"] is False
                    assert completion["rollout_execution"]["action_count"] == 0
                else:
                    assert "pending_operator_teleop_handoff" not in controller._state.run_metadata
                    assert controller._state.run_metadata["equipment_handoff"]["status"] == "execution_ready_pending_approval"
                result = {"ok": True, "fixture_prefix": "equipment_preflight_complete" if path.startswith("real_manip") else "equipment_admission_after_confirmed_teleop_and_actual_vision"}
            finally:
                tail_task.cancel()
                await asyncio.gather(tail_task, return_exceptions=True)
        elif path == "legacy_tail":
            waiting = asyncio.Event()
            original_wait = controller._wait_for_vision_intervention_resume
            async def observed_wait():
                waiting.set()
                return await original_wait()
            monkeypatch.setattr(controller, "_wait_for_vision_intervention_resume", observed_wait)
            tail_task = asyncio.create_task(controller._run_planning_loop_tail(spec))
            wait_task = asyncio.create_task(waiting.wait())
            try:
                await asyncio.wait({tail_task, wait_task}, timeout=50, return_when=asyncio.FIRST_COMPLETED)
                assert waiting.is_set(), tail_task.result() if tail_task.done() else "No native hold"
                assert controller._state.run_metadata["utm_clear_execution"]["failure_code"] == "UTM_CLEAR_MANUAL_CLEARANCE_REQUIRED"
                calls_before = deepcopy(equipment["calls"])
                await asyncio.sleep(.05)
                assert equipment["calls"] == calls_before and not tail_task.done()
                result = {"ok": False, "decision": "manual_clearance_hold", "fixture_cancelled_after_native_wait": True}
            finally:
                tail_task.cancel()
                wait_task.cancel()
                await asyncio.gather(tail_task, wait_task, return_exceptions=True)
        else:
            result = await asyncio.wait_for(controller._run_planning_loop_tail(spec), timeout=40)
    finally:
        (tmp_path / "tail-evidence.json").write_text(json.dumps({"result": result,
            "metadata": controller._state.run_metadata, "events": controller.recent_events(),
            "simulated_boundary_requests": guard.simulated_boundary_requests}, default=str, indent=2))
    stages = [e.get("node_id") for e in controller.recent_events() if e.get("type") == "node.completed"]
    if hybrid:
        assert stages[:3] == ["vision", "manipulation", "vision"], stages
        assert stages == (["vision", "manipulation", "vision", "equipment"] if path.startswith("real_manip") else ["vision", "manipulation", "vision"])
        names = [row["tool"] for row in guard.simulated_boundary_requests]
        assert names.count("lerobot.rollout.start") == (1 if path.startswith("real_manip") else 0)
    elif path == "virtual_profile":
        assert result["ok"], (result, stages, controller._state.run_metadata.get("equipment_result"), guard.denied)
        assert stages[-5:] == ["equipment", "analysis", "knowledge", "bo", "guardian"], stages
        assert equipment["calls"] == []
        assert controller._state.run_metadata["equipment_handoff"]["status"] == "execution_ready_pending_approval"
    else:
        assert stages == ["vision", "manipulation", "vision", "equipment", "manipulation", "guardian"]
        assert "analysis" not in stages and controller._state.run_metadata["utm_data_ready"]["status"] == "ready"
        assert len(equipment["calls"]) == len(equipment["programs"])
    assert len({p["sequence_id"] for p in equipment["calls"]}) == len(equipment["calls"])
    assert guard.physical_call_count == 0
