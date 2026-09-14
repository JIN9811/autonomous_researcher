"""Exercise the real stacked Flow; replace only model and device boundaries."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agents.equipment.agent import LabEquipmentAgent
from tests.unit.test_equipment_agent import _state, _tools, _saved_recording
from utils.equipment_skill_runtime import EquipmentSkillRegistry, canonical_sha256
from utils.equipment_skill_flow import EquipmentSkillFlowStore


class Model:
    force_real_llm_in_test = True

    def __init__(self, tools, choices=()):
        self.tools, self.choices = tools, list(choices)
        self.calls = []

    async def complete(self, task, prompt, **kwargs):
        envelope = json.loads(prompt.split("CONTEXT:\n")[-1])
        self.calls.append((envelope, kwargs))
        proposals = envelope["tools"]
        choice = self.choices.pop(0) if self.choices else (
            "execute_stacked_workflow" if "execute_stacked_workflow" in proposals
            else "accept_workflow_result" if "accept_workflow_result" in proposals else "request_operator")
        return SimpleNamespace(model="fixture", raw={}, text=json.dumps({
            "tool": choice, "arguments": proposals.get(choice, {}),
            "reason": "Matches the supplied terminal evidence.",
            "evidence_refs": envelope["evidence_refs"],
        }))


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_change", [False, True])
async def test_model_telemetry_does_not_invalidate_but_approval_changes_do(tmp_path, monkeypatch, authority_change):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    class UpdatingModel(Model):
        async def complete(self, *args, **kwargs):
            state.run_metadata["llm_last_call_telemetry"] = {"tokens": len(self.calls) + 1}
            if authority_change:
                state.run_metadata["runtime_approvals"] = {"operator": "revoked"}
            return await super().complete(*args, **kwargs)
    result = await agent.run(state, UpdatingModel(tools))
    assert result.success is (not authority_change)
    assert executed == ([] if authority_change else ["prepare", "measure", "export"])


def setup_flow(tmp_path, monkeypatch, *, multi_segment=False):
    agent = LabEquipmentAgent()
    monkeypatch.setattr(agent, "_RUNTIME_ROOT", tmp_path / "runtime")
    # classmethod runtime access must see the same isolated root.
    monkeypatch.setattr(LabEquipmentAgent, "_RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", tmp_path / "flows.json")
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    blocks = []
    for name in ("prepare", "measure", "export"):
        recording = _saved_recording()
        if multi_segment and name == "prepare":
            recording["events"] = [{"kind": "key_press", "at_ms": i * 10, "key": "enter"} for i in range(150)]
        registry.create_draft(recording=recording, skill_id=name, version="1.0.0",
            target_profile="windows_desktop_v1", model_snapshot={"provider": "vllm", "model": "registered"})
        package = registry.compile(name, "1.0.0")
        registry.validate(name, "1.0.0")
        registry.mark_deployed(name, "1.0.0", bridge_id="simulator",
            deployment_sha256=canonical_sha256(package["programs"]))
        blocks.append({"id": name, "label": name,
            "skill": {"skill_id": name, "skill_version": "1.0.0"},
            "agentic": {"completed": "__complete__" if name == "export" else "next", "failed": "__blocked__"},
            "vision": {"enabled": False}})
    flow = EquipmentSkillFlowStore(agent._SKILL_FLOW_PATH).save("windows_desktop_v1", {
        "schema": "atr.equipment_skill_flow.v1", "flow_id": "stack", "profile_id": "windows_desktop_v1",
        "blocks": blocks})["flow"]
    state = _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1",
        "equipment_skill_registry_root": str(tmp_path / "skills")})
    executed = []
    def worker(payload):
        executed.append(payload.get("equipment_skill_id", "recovery"))
        return {"ok": True, "status": "completed", "executed_action_count": 1,
            "program_id": payload.get("program_id"), "step_trace": []}
    tools.register("equipment.pyautogui.run", worker)
    # This fixture replaces the Windows worker, so its screen must come from
    # that same controlled worker result, not an unexecuted real simulator.
    observed = {}
    original_call = tools.call
    def tracked_call(name, payload):
        result = original_call(name, payload)
        if name == "equipment.pyautogui.run":
            observed.update(payload=deepcopy(payload), result=deepcopy(result))
        return result
    monkeypatch.setattr(tools, "call", tracked_call)
    def screenshot(payload):
        import hashlib
        from PIL import Image, ImageDraw
        identity = observed.get("payload", {})
        if not identity or any(identity.get(key) != payload.get(key) for key in ("run_id", "workflow_execution_id")):
            return {"ok": False, "status": "unknown", "synthetic": True}
        image = Image.new("RGB", (640, 240), "white")
        ImageDraw.Draw(image).text((10, 10), "CONTROLLED WORKER / " + str(observed["result"].get("status")), fill="black")
        path = tmp_path / "controlled-worker-screen.png"
        image.save(path)
        return {"ok": True, "mode": "simulator", "simulated": True,
            **{key: identity[key] for key in ("run_id", "loop_id", "specimen_id", "workflow_execution_id") if key in identity},
            "artifact": {"local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "artifact_id": "controlled-worker-screen", "content_type": "image/png"}}
    tools.register("equipment.pyautogui.screenshot", screenshot)
    return agent, state, tools, executed, worker, flow


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", [None, "alias_digest", "artifact_id", "run_id", "missing_file", "directory"])
async def test_terminal_review_uses_downloaded_image_not_remote_artifact_alias(tmp_path, monkeypatch, corruption):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    # The Windows response retains a metadata-only singular artifact while
    # the bridge places the downloaded, hash-bound file in output_artifacts.
    original_call = tools.call
    def windows_shape(name, payload):
        raw = original_call(name, payload)
        if name == "equipment.pyautogui.screenshot":
            local = raw["artifact"]
            raw["output_artifacts"] = [local]
            raw["artifact"] = {"artifact_id": local["artifact_id"],
                "content_type": "image/png", "sha256": local["sha256"]}
            if corruption == "alias_digest":
                raw["artifact"]["sha256"] = "0" * 64
            elif corruption == "artifact_id":
                local["artifact_id"] = "another-image"
            elif corruption == "run_id":
                raw["run_id"] = "another-run"
            elif corruption == "missing_file":
                local["local_path"] = str(tmp_path / "missing.png")
            elif corruption == "directory":
                local["local_path"] = str(tmp_path)
        return raw
    monkeypatch.setattr(tools, "call", windows_shape)
    result = await agent.run(state, Model(tools))
    assert result.success is (corruption is None)
    assert executed == ["prepare", "measure", "export"]
    assert result.data["equipment_workflow_recovery"]["diagnostics"][-1]["screenshot"]["ok"] is (corruption is None)


@pytest.mark.asyncio
async def test_not_working_observation_is_taken_after_skill_completion(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    agent, state, tools, _, _, flow = setup_flow(tmp_path, monkeypatch)
    flow["blocks"][-1]["vision"] = {"enabled": True, "blocking": False,
        "task_id": "utm_state_not_working"}
    flow = EquipmentSkillFlowStore(agent._SKILL_FLOW_PATH).save("windows_desktop_v1", flow)["flow"]
    completed = False
    original_skill = agent._run_equipment_skill
    async def delayed_skill(*args, **kwargs):
        nonlocal completed
        result = await original_skill(*args, **kwargs)
        await asyncio.sleep(0)
        completed = True
        return result
    monkeypatch.setattr(agent, "_run_equipment_skill", delayed_skill)
    # Keep only the final block: a real Skill executes against the controlled
    # worker, and the external observation depends on its completion boundary.
    flow["blocks"] = flow["blocks"][-1:]
    def vision(payload):
        now = datetime.now(timezone.utc)
        check = payload["checks"][0]
        return {"ok": completed, "results": [{**check, "ok": completed,
            "status": "verified" if completed else "attention_required",
            "confidence": 0.92, "timestamp": now.isoformat(),
            "expires_at": (now + timedelta(seconds=5)).isoformat(),
            "source": "controlled_sensor"}]}
    tools.register("vision.equipment_cross_check", vision)
    result = await agent._run_equipment_skill_flow(state, Model(tools), flow)
    observations = [t for t in result.data["equipment_skill_flow_execution"]["transitions"] if t["phase"] == "vision"]
    assert observations[-1]["outcome"] == "detected"


@pytest.mark.asyncio
async def test_stacked_workflow_model_runs_only_before_and_after_and_reuses_completed_call(tmp_path, monkeypatch):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    model = Model(tools)
    observed = []
    def record(payload):
        observed.append(len(model.calls))
        return worker(payload)
    tools.register("equipment.pyautogui.run", record)
    result = await agent.run(state, model)
    assert result.success
    assert executed == ["prepare", "measure", "export"]
    assert observed == [1, 1, 1]
    assert len(model.calls) == 2
    assert model.calls[-1][1]["images"][0].mime_type == "image/png"
    # Same identity in a fresh state object must hit the persistent record.
    repeated = await agent.run(deepcopy(state), model)
    assert repeated.success and repeated.data["equipment_workflow_cached"] is True
    assert executed == ["prepare", "measure", "export"]
    state.loop_count += 1
    assert (await agent.run(state, model)).success
    assert executed == ["prepare", "measure", "export"] * 2


@pytest.mark.asyncio
async def test_standalone_test_workflow_binds_actual_simulator_screen_to_host_identity(tmp_path, monkeypatch):
    from tests.unit.test_equipment_pyautogui_bridge import _bridge
    agent, state, tools, _, _, _ = setup_flow(tmp_path, monkeypatch)
    state.current_experiment_spec["specimen_id"] = "standalone-specimen"
    bridge = _bridge(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    for name in ("prepare", "measure", "export"):
        package = registry.get(name, "1.0.0")
        bridge.config.registered_programs.update({program["program_id"]: program for program in package["programs"]})
    tools.register("equipment.pyautogui.run", bridge.run)
    tools.register("equipment.pyautogui.screenshot", bridge.screenshot)
    result = await agent.run(state, Model(tools))
    assert result.success, result.data
    screenshot = result.data["equipment_workflow_recovery"]["diagnostics"][-1]["screenshot"]
    assert screenshot["response_identity"] == {"run_id": state.run_id, "loop_id": state.loop_count,
        "specimen_id": "standalone-specimen", "workflow_execution_id": result.data["equipment_workflow_execution_id"]}


@pytest.mark.asyncio
async def test_terminal_recovery_retries_only_proven_unexecuted_block(tmp_path, monkeypatch):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    model = Model(tools, ["execute_stacked_workflow", "recover_wait", "resume_failed_block", "accept_workflow_result"])
    failed = False
    def fail_once(payload):
        nonlocal failed
        if payload.get("equipment_skill_id") == "measure" and not failed:
            failed = True
            executed.append("measure")
            return {"ok": False, "status": "blocked", "executed_action_count": 0,
                "failure_code": "PYAUTOGUI_LOCATOR_NOT_FOUND"}
        return worker(payload)
    tools.register("equipment.pyautogui.run", fail_once)
    result = await agent.run(state, model)
    assert result.success
    assert executed == ["prepare", "measure", "measure", "export"]
    assert len(model.calls) == 4
    assert len(model.calls[2][1]["images"]) == 2
    assert [x["block_id"] for x in result.data["equipment_skill_flow_execution"]["transitions"] if x["phase"] == "skill"] == ["prepare", "measure", "export"]
    assert result.data["equipment_workflow_recovery"]["attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["unknown", "partial", "cancelled"])
async def test_uncertain_or_partial_actions_never_replayed(tmp_path, monkeypatch, fault):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    def fail(payload):
        if payload.get("equipment_skill_id") != "measure":
            return worker(payload)
        executed.append("measure")
        if fault == "cancelled":
            state.stop_requested = True
        return {"ok": False, "status": "effect_unknown" if fault == "unknown" else "blocked",
            "executed_action_count": -1 if fault == "unknown" else 1,
            "failure_code": "PYAUTOGUI_LOCATOR_NOT_FOUND"}
    tools.register("equipment.pyautogui.run", fail)
    model = Model(tools, ["execute_stacked_workflow", "recover_wait", "resume_failed_block"])
    result = await agent.run(state, model)
    assert not result.success
    assert executed == ["prepare", "measure"]
    assert not (await agent.run(deepcopy(state), model)).success
    assert executed == ["prepare", "measure"]


@pytest.mark.asyncio
async def test_model_rejection_preserves_terminal_evidence_but_blocks_handoff(tmp_path, monkeypatch):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    result = await agent.run(state, Model(tools, ["execute_stacked_workflow", "request_operator"]))
    assert not result.success
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["equipment_skill_flow_execution"]["terminal"] == "__complete__"
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_concurrent_duplicate_cannot_start_while_selection_is_pending(tmp_path, monkeypatch):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    model = Model(tools)
    complete = model.complete
    async def delayed(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await complete(*args, **kwargs)
    model.complete = delayed
    pending = asyncio.create_task(agent.run(state, model))
    await entered.wait()
    duplicate = await agent.run(deepcopy(state), model)
    assert not duplicate.success and executed == []
    release.set()
    assert (await pending).success
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_registered_module_exposes_terminal_screenshot_and_log_tools(tmp_path, monkeypatch):
    import yaml
    from pathlib import Path
    from orchestrator.langgraph_runtime import ModuleToolRegistryProxy
    from orchestrator.state import Stage
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    module = yaml.safe_load(Path("graphs/modules/equipment/module.yaml").read_text())["module"]
    proxy = ModuleToolRegistryProxy(tools, module["tools"], Stage.EQUIPMENT, state=state)
    model = Model(proxy)
    result = await agent.run(state, model)
    assert result.success
    assert model.calls[-1][1]["images"]
    assert "equipment.pyautogui.request_log" in proxy.list_tools()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["active_session_id", "device_health", "current_experiment_objective"])
async def test_authority_change_during_worker_prevents_next_block(tmp_path, monkeypatch, field):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    def change(payload):
        raw = worker(payload)
        setattr(state, field, "changed" if field == "active_session_id" else {"changed": True})
        return raw
    tools.register("equipment.pyautogui.run", change)
    result = await agent.run(state, Model(tools))
    assert not result.success
    assert executed == ["prepare"]


@pytest.mark.asyncio
async def test_mode_change_does_not_create_second_claim_for_same_work(tmp_path, monkeypatch):
    from orchestrator.state import Mode
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    assert (await agent.run(state, Model(tools))).success
    state.mode = Mode.LIVE
    result = await agent.run(state, Model(tools))
    assert not result.success
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_bad_screenshot_cannot_trigger_successful_work_replay(tmp_path, monkeypatch):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    tools.register("equipment.pyautogui.screenshot", lambda payload: {"ok": False})
    result = await agent.run(state, Model(tools))
    assert not result.success and executed == ["prepare", "measure", "export"]
    assert not (await agent.run(deepcopy(state), Model(tools))).success
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "scope", "stop", "wrong_execution"])
async def test_explicit_terminal_review_retry_never_replays_worker(tmp_path, monkeypatch, change):
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    original_call = tools.call
    broken = True
    def screen(name, payload):
        if name == "equipment.pyautogui.screenshot" and broken:
            return {"ok": False}
        return original_call(name, payload)
    monkeypatch.setattr(tools, "call", screen)
    first = await agent.run(state, Model(tools))
    assert not first.success
    broken = False
    execution = first.data["equipment_workflow_execution_id"]
    state.run_metadata["equipment_terminal_review_retry"] = execution
    if change == "scope":
        state.active_session_id = "another-session"
    elif change == "stop":
        state.stop_requested = True
    elif change == "wrong_execution":
        state.run_metadata["equipment_terminal_review_retry"] = "wrong-execution"
    second = await agent.run(state, Model(tools))
    assert second.success is (change is None)
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_live_review_rejects_simulated_screenshot(tmp_path, monkeypatch):
    from agents.equipment.workflow import _capture
    from orchestrator.state import Mode
    agent, state, tools, _, _, _ = setup_flow(tmp_path, monkeypatch)
    state.mode = Mode.LIVE
    request = {"runtime_mode": "test", "run_id": state.run_id, "workflow_execution_id": "test-execution"}
    tools.call("equipment.pyautogui.run", request)
    original = tools.call("equipment.pyautogui.screenshot", request)
    assert original["ok"] and original["simulated"]
    tools.register("equipment.pyautogui.screenshot", lambda payload: original)
    images, evidence = await _capture(agent, state, Model(tools), None, "test-execution")
    assert images == [] and evidence["ok"] is False


@pytest.mark.asyncio
async def test_read_only_review_failure_remains_retryable_without_worker_replay(tmp_path, monkeypatch):
    from agents.equipment import recovery
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    first = await agent.run(state, Model(tools, ["execute_stacked_workflow", "request_operator"]))
    assert not first.success
    execution = first.data["equipment_workflow_execution_id"]
    async def unavailable(*args):
        raise ValueError("Sensor is starting")
    original = recovery.refresh_terminal_observations
    monkeypatch.setattr(recovery, "refresh_terminal_observations", unavailable)
    state.run_metadata["equipment_terminal_review_retry"] = execution
    second = await agent.run(state, Model(tools))
    assert second.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED"
    monkeypatch.setattr(recovery, "refresh_terminal_observations", original)
    state.run_metadata["equipment_terminal_review_retry"] = execution
    assert (await agent.run(state, Model(tools))).success
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_completed_work_can_be_revalidated_without_reopening_actuation_claim(tmp_path, monkeypatch):
    from utils.equipment_runtime_service import EquipmentRuntimeService
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    first = await agent.run(state, Model(tools))
    assert first.success
    execution = first.data["equipment_workflow_execution_id"]
    service = EquipmentRuntimeService(agent._RUNTIME_ROOT / "workflow_decisions")
    original = deepcopy(service.get(execution)["workflow_result"])
    state.run_metadata["equipment_terminal_review_retry"] = execution
    rejected = await agent.run(state, Model(tools, ["request_operator"]))
    assert not rejected.success
    assert service.get(execution)["lifecycle"] == "COMPLETED"
    assert service.get(execution)["workflow_result"] == original
    state.run_metadata["equipment_terminal_review_retry"] = execution
    model = Model(tools)
    reviewed = await agent.run(state, model)
    assert reviewed.success and len(model.calls) == 1
    assert service.get(execution)["lifecycle"] == "COMPLETED"
    assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_error_resume_accepts_completed_review_but_not_changed_authority(tmp_path, monkeypatch, revoked):
    from app.run_recovery import prepare_error_resume
    from orchestrator.state import Stage
    agent, state, tools, _, _, _ = setup_flow(tmp_path, monkeypatch)
    first = await agent.run(state, Model(tools))
    archive_data = deepcopy(first.data)
    archive_data["equipment_handoff"] = {"status": "ready_for_analysis", "ready_for_analysis": True}
    archive = tmp_path / state.run_id / "runtime/loops/loop-000001/equipment_agent/attempt-000001/result.json"
    archive.parent.mkdir(parents=True)
    archive.write_text(json.dumps({"status": "completed", "data": archive_data}))
    state.stage = Stage.ERROR
    if revoked:
        state.active_session_id = "another-session"
    controller = SimpleNamespace(_state=state,
        _deps=SimpleNamespace(run_root=tmp_path, agent_registry={"equipment_agent": agent}),
        snapshot=lambda: {"is_running": False, "state": state.model_dump(mode="json")},
        _is_planning_test_spec=lambda spec: True)
    if revoked:
        with pytest.raises(ValueError, match="scope"):
            prepare_error_resume(controller)
    else:
        assert prepare_error_resume(controller) == first.data["equipment_workflow_execution_id"]


@pytest.mark.asyncio
async def test_legacy_read_only_review_exception_requires_durable_no_actuation_proof(tmp_path, monkeypatch):
    from agents.equipment.recovery import completed_candidate
    from utils.equipment_runtime_service import EquipmentRuntimeService
    agent, state, tools, _, _, _ = setup_flow(tmp_path, monkeypatch)
    first = await agent.run(state, Model(tools, ["execute_stacked_workflow", "request_operator"]))
    record = EquipmentRuntimeService(agent._RUNTIME_ROOT / "workflow_decisions").get(first.data["equipment_workflow_execution_id"])
    record["workflow_result"]["data"]["equipment_handoff"]["failure_code"] = "EQUIPMENT_WORKFLOW_EFFECT_UNKNOWN"
    flow = agent._equipment_skill_flow(state)
    with pytest.raises(ValueError):
        completed_candidate(record, flow, state)
    record["recovery"] = {"operation": "terminal_review_only", "actuation_performed": False}
    assert completed_candidate(record, flow, state).success


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected_calls", [
    ("UTM_INSUFFICIENT_TEMPORAL_EVIDENCE", 2), ("UTM_EXPECTED_VISION_RESULT_MISMATCH", 1)])
async def test_terminal_sensor_warmup_retries_missing_samples_not_contradictions(tmp_path, monkeypatch, failure, expected_calls):
    from datetime import datetime, timedelta, timezone
    from agents.base_agent import AgentResult
    from agents.equipment.recovery import refresh_terminal_observations
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    calls = []
    async def observe(ctx, name, payload, **kwargs):
        assert name == "vision.equipment_cross_check"
        calls.append(name)
        good = len(calls) > 1
        result = {**payload["checks"][0], "ok": good,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat()}
        return {"ok": good, "results": [result], "failure_code": None if good else failure}
    monkeypatch.setattr(agent, "_call_tool", observe)
    flow = {"blocks": [{"id": "clearance", "vision": {"enabled": True, "task_id": "utm_state_not_working"}}]}
    result = AgentResult(success=True, summary="Completed", data={})
    if expected_calls == 1:
        with pytest.raises(ValueError):
            await refresh_terminal_observations(agent, state, Model(tools), flow, result)
    else:
        assert (await refresh_terminal_observations(agent, state, Model(tools), flow, result)).success
    assert len(calls) == expected_calls and not executed


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_age,accepted", [(0, True), (20, False)])
async def test_terminal_review_uses_measured_sample_time_not_request_start(tmp_path, monkeypatch, sample_age, accepted):
    from datetime import datetime, timedelta, timezone
    from agents.base_agent import AgentResult
    from agents.equipment.recovery import refresh_terminal_observations
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    async def observe(ctx, name, payload, **kwargs):
        now = datetime.now(timezone.utc)
        return {"ok": True, "results": [{**payload["checks"][0], "ok": True, "source": "ros_topic",
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
            "expires_at": (now - timedelta(seconds=25)).isoformat(), "freshness_ttl_ms": 5000,
            "evidence": {"ok": True, "samples": [{"summary_fresh": True,
                "timestamp": (now - timedelta(seconds=sample_age)).isoformat()}]}}]}
    monkeypatch.setattr(agent, "_call_tool", observe)
    flow = {"blocks": [{"id": "clearance", "vision": {"enabled": True, "task_id": "utm_state_not_working"}}]}
    result = AgentResult(success=True, summary="Completed", data={})
    if accepted:
        assert (await refresh_terminal_observations(agent, state, Model(tools), flow, result)).success
    else:
        with pytest.raises(ValueError):
            await refresh_terminal_observations(agent, state, Model(tools), flow, result)
    assert not executed


@pytest.mark.asyncio
@pytest.mark.parametrize("independent_failure", [False, True])
async def test_refreshed_terminal_observation_replaces_report_not_unrelated_alarms(tmp_path, monkeypatch, independent_failure):
    from datetime import datetime, timedelta, timezone
    from agents.base_agent import AgentResult
    from agents.equipment.recovery import refresh_terminal_observations
    from policies.guardian_gate import guardian_gate, gate_blocks_execution
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    old = {"block_id": "clearance", "phase": "vision", "vision_task_id": "utm_state_not_working",
        "check_id": "utm_state_not_working", "outcome": "error", "confidence": 0.0,
        "failure_code": "UTM_EXPECTED_VISION_RESULT_MISMATCH",
        "operator_attention": {"failure_code": "UTM_EXPECTED_VISION_RESULT_MISMATCH"}}
    transitions = [deepcopy(old)]
    if independent_failure:
        transitions.append({"block_id": "other", "phase": "skill", "failure_code": "UTM_MOTION_FAILED"})
    result = AgentResult(success=True, summary="Completed", data={
        "equipment_skill_flow_execution": {"transitions": transitions},
        "equipment_report": {"block_executions": deepcopy(transitions)}})
    async def observe(ctx, name, payload, **kwargs):
        assert name == "vision.equipment_cross_check"
        now = datetime.now(timezone.utc)
        return {"ok": True, "results": [{**payload["checks"][0], "ok": True, "confidence": 0.93,
            "timestamp": now.isoformat(), "expires_at": (now + timedelta(seconds=5)).isoformat()}]}
    monkeypatch.setattr(agent, "_call_tool", observe)
    flow = {"blocks": [{"id": "clearance", "vision": {"enabled": True, "task_id": "utm_state_not_working"}}]}
    await refresh_terminal_observations(agent, state, Model(tools), flow, result)
    current = result.data["equipment_report"]["block_executions"][0]
    assert current["outcome"] == "detected"
    assert current["failure_code"] is None and current["operator_attention"] is None
    assert current["confidence"] == 0.93
    assert old["failure_code"] == "UTM_EXPECTED_VISION_RESULT_MISMATCH"
    gate = guardian_gate(state=state, stage="equipment", phase="post", payload=result.data)
    assert gate_blocks_execution(gate) is independent_failure
    assert not executed


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "scope"])
async def test_managed_multisegment_skill_stops_before_next_segment(tmp_path, monkeypatch, change):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch, multi_segment=True)
    package = EquipmentSkillRegistry(tmp_path / "skills").get("prepare", "1.0.0")
    assert len(package["workflow"]["program_ids"]) > 1
    def change_after_segment(payload):
        raw = worker(payload)
        if change == "stop":
            state.stop_requested = True
        else:
            state.active_session_id = "different-session"
        return raw
    tools.register("equipment.pyautogui.run", change_after_segment)
    result = await agent.run(state, Model(tools))
    assert not result.success
    assert executed == ["prepare"]


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["during_execution", "cached_reuse"])
async def test_runtime_approval_change_invalidates_execution_authority(tmp_path, monkeypatch, when):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    state.run_metadata["runtime_approvals"] = {"operator": "approved"}
    if when == "during_execution":
        def revoke(payload):
            result = worker(payload)
            state.run_metadata["runtime_approvals"] = {"operator": "revoked"}
            return result
        tools.register("equipment.pyautogui.run", revoke)
        result = await agent.run(state, Model(tools))
        assert not result.success and executed == ["prepare"]
    else:
        assert (await agent.run(state, Model(tools))).success
        state.run_metadata["runtime_approvals"] = {"operator": "revoked"}
        result = await agent.run(state, Model(tools))
        assert not result.success
        assert executed == ["prepare", "measure", "export"]


@pytest.mark.asyncio
async def test_terminal_prompt_omits_credentials_and_inline_image_bytes(tmp_path, monkeypatch):
    agent, state, tools, _, worker, _ = setup_flow(tmp_path, monkeypatch)
    def verbose(payload):
        return {**worker(payload), "api_key": "credential-must-not-leak", "content_base64": "encoded-frame-must-not-leak"}
    tools.register("equipment.pyautogui.run", verbose)
    model = Model(tools)
    assert (await agent.run(state, model)).success
    prompt_context = json.dumps(model.calls[-1][0])
    assert "credential-must-not-leak" not in prompt_context
    assert "encoded-frame-must-not-leak" not in prompt_context


@pytest.mark.asyncio
async def test_transport_exception_and_restart_do_not_reissue_worker_action(tmp_path, monkeypatch):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    def lost_response(payload):
        worker(payload)
        raise TimeoutError("response lost after dispatch")
    tools.register("equipment.pyautogui.run", lost_response)
    result = await agent.run(state, Model(tools))
    assert not result.success and executed == ["prepare"]
    assert not (await agent.run(deepcopy(state), Model(tools))).success
    assert executed == ["prepare"]


@pytest.mark.asyncio
async def test_failed_recovery_does_not_retry_forever(tmp_path, monkeypatch):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    def stuck(payload):
        if payload.get("equipment_skill_id") == "measure":
            executed.append("measure")
            return {"ok": False, "status": "blocked", "executed_action_count": 0,
                    "failure_code": "PYAUTOGUI_LOCATOR_NOT_FOUND"}
        return worker(payload)
    tools.register("equipment.pyautogui.run", stuck)
    result = await agent.run(state, Model(tools, ["execute_stacked_workflow", "recover_wait", "resume_failed_block", "recover_wait"]))
    assert not result.success
    assert executed == ["prepare", "measure", "measure"]
    assert result.data["equipment_workflow_recovery"]["attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", [{"actuation_performed": True}, {"effects_known": False}, {"effect_unknown": True}])
async def test_zero_counter_does_not_override_contradictory_effect_evidence(tmp_path, monkeypatch, effect):
    agent, state, tools, executed, worker, _ = setup_flow(tmp_path, monkeypatch)
    def fail(payload):
        executed.append(payload.get("equipment_skill_id"))
        return {"ok": False, "status": "blocked", "executed_action_count": 0,
                "failure_code": "PYAUTOGUI_LOCATOR_NOT_FOUND", **effect}
    tools.register("equipment.pyautogui.run", fail)
    model = Model(tools, ["execute_stacked_workflow", "recover_wait", "resume_failed_block"])
    result = await agent.run(state, model)
    assert not result.success and executed == ["prepare"]
    assert result.data["equipment_workflow_recovery"]["attempts"] == 0


def test_terminal_projection_deduplicates_worker_artifacts_but_keeps_failure_and_gate_evidence():
    from agents.equipment.workflow import _terminal_evidence
    from agents.base_agent import AgentResult
    raw = {"ok": False, "failure_code": "UI_ERROR", "executed_action_count": 0,
           "output_artifacts": [{"path": "large/repeated/path" * 100}] * 50}
    result = AgentResult(success=False, summary="blocked", data={"equipment_result": raw,
        "tool_results": [{"tool": "equipment.pyautogui.run", "result": raw, "payload": {"sequence_id": "one"}}],
        "raw_data_export": {"validated": False}, "next_specimen_readiness": {"ready": False},
        "equipment_skill_flow_execution": {"terminal": "__blocked__", "transitions": [
            {"block_id": "measure", "phase": "skill", "success": False, "outcome": "failed"}]}})
    projected = _terminal_evidence(result)
    assert len(json.dumps(projected)) < 12000
    assert projected["equipment_result"]["failure_code"] == "UI_ERROR"
    assert projected["last_worker_call"]["result"]["executed_action_count"] == 0
    assert projected["raw_data_export"]["validated"] is False
    assert projected["equipment_skill_flow_execution"]["transitions"][0]["success"] is False
