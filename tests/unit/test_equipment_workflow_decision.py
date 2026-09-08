"""Exercise the real stacked Flow; replace only model and device boundaries."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agents.equipment_agent import LabEquipmentAgent
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
    return agent, state, tools, executed, worker, flow


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
async def test_live_review_rejects_simulated_screenshot(tmp_path, monkeypatch):
    from agents.equipment_workflow import _capture
    from orchestrator.state import Mode
    agent, state, tools, _, _, _ = setup_flow(tmp_path, monkeypatch)
    state.mode = Mode.LIVE
    original = tools.call("equipment.pyautogui.screenshot", {"runtime_mode": "test"})
    tools.register("equipment.pyautogui.screenshot", lambda payload: original)
    images, evidence = await _capture(agent, state, Model(tools), None, "test-execution")
    assert images == [] and evidence["ok"] is False


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
    from agents.equipment_workflow import _terminal_evidence
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
