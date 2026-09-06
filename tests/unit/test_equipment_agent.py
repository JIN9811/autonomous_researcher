"""Unit tests for LabEquipmentAgent Windows PyAutoGUI path."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.base_agent import AgentResult
from agents.equipment_agent import LabEquipmentAgent
from agents.analysis_agent import AnalysisAgent
from backends.llm_backend import LLMResponse
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import gate_blocks_execution, guardian_gate
from policies.validation_policy import validate_agent_output
from utils.equipment_skill_runtime import EquipmentSkillRegistry, SkillContractError, canonical_sha256
from utils.equipment_skill_flow import EquipmentSkillFlowStore
from utils.equipment_agentic_task import build_utm_compression_flow_template


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["", "wrong_specimen", "changed_csv", "missing_clearance", "missing_snapshot", "wrong_identity"])
async def test_live_cycle_binds_worker_csv_copies_and_emits_analysis_handoff(tmp_path, monkeypatch, fault):
    """Replay the live worker shape: per-call IDs/paths, no artifact identity fields."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": block["id"], "skill_version": "1.0.0"}
        block["vision"]["enabled"] = False
    state = _state(mode=Mode.LIVE, experiment_spec={
        "equipment_profile_id": "windows_desktop_v1", "specimen_id": "specimen-test",
    })
    state.run_metadata["robot_task_result"] = {
        "run_id": "run-test", "specimen_id": "specimen-test", "handoff_status": "ready_for_equipment",
    }
    state.active_session_id = "session-test"
    filename = "live_session-test_specimen-test_loop-0001_rep-0001.csv"
    csv_bytes = b"time_s,force_N,displacement_mm\n0,0,0\n1,100,15\n"
    windows_path = "C:/exports/" + filename
    agent = LabEquipmentAgent()

    async def replay_skill(_state, _ctx, request):
        block = request["skill_id"]
        raw = {"ok": True, "status": "completed", "bridge": "windows_pyautogui", "program_id": "utm_" + block,
               "output_artifacts": [], "step_trace": []}
        # Worker flags describe this skill, not the entire compression cycle.
        raw["cross_checks"] = {
            "screen_started": True,
            "physical_motion_started": block in {"monitor_contact_and_run", "save_raw_data"},
            "save_completed": block == "save_raw_data",
            "data_file_created": block in {"save_raw_data", "validate_raw_data"},
            "data_parse_probe_ok": block in {"save_raw_data", "validate_raw_data"},
            "save_export_responsibility_ok": True,
        }
        if block in {"save_raw_data", "validate_raw_data"}:
            local = tmp_path / block / filename
            local.parent.mkdir()
            content = csv_bytes + (b"2,120,16\n" if fault == "changed_csv" and block == "validate_raw_data" else b"")
            local.write_bytes(content)
            artifact = {"kind": "utm_csv", "artifact_id": block + "-timestamp", "local_path": str(local),
                        "windows_path": windows_path.replace("specimen-test", "specimen-other") if fault == "wrong_specimen" else windows_path,
                        "sha256": hashlib.sha256(content).hexdigest(), "pulled_to_linux": True,
                        "local_parse_ok": True, "row_count_probe": 2,
                        "columns_probe": ["time_s", "force_N", "displacement_mm"], "stable_for_sec": 2}
            if fault == "wrong_identity":
                artifact["run_id"] = "another-run"
            raw.update(result_file=str(local), utm_csv_path=str(local), output_artifacts=[artifact],
                       data_acquisition={"artifact_id": artifact["artifact_id"], "linux_path": str(local),
                                         "status": "pulled_to_linux"})
        if block == "restore_robot_clearance":
            raw["step_trace"] = [
                {"step": "SEQ_10_WAIT_UNTIL_IMAGE", "status": "ok", "detail": "target_inter_jig_distance_150_mm via image"},
                {"step": "SEQ_20_WAIT_UNTIL_IMAGE", "status": "failed" if fault == "missing_clearance" else "ok", "detail": "entry_height_150_mm via image"},
                {"step": "SEQ_21_WAIT_UNTIL_IMAGE", "status": "ok", "detail": "next_test_ready_loaded via image"},
                {"step": "SCREENSHOT_ROBOT_CLEARANCE_RESTORED", "status": "ok", "detail": "C:/screens/clearance.png"},
            ]
            if fault != "missing_snapshot":
                raw["output_artifacts"] = [{"kind": "screen_png", "windows_path": "C:/screens/clearance.png",
                                             "local_path": str(tmp_path / "clearance.png"), "pulled_to_linux": True}]
        return AgentResult(success=True, summary="registered skill complete", data=agent._build_skill_step_result_package(raw))

    monkeypatch.setattr(agent, "_run_equipment_skill", replay_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_: {"ok": True})
    result = await agent._run_equipment_skill_flow(state, _CtxStub(_tools(tmp_path), "unused"), flow)
    if fault:
        assert result.success is False
        assert result.data["equipment_handoff"]["status"] == "blocked"
        return
    assert result.success is True
    assert validate_agent_output("equipment", result.data) == (True, "ok")
    for name in ("screen_started", "physical_motion_started", "save_completed", "data_file_created", "data_parse_probe_ok"):
        assert result.data["equipment_report"]["cross_checks"][name] is True
        assert result.data["equipment_result"]["cross_checks"][name] is True
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["utm_data_ready"]["status"] == "ready"
    assert result.data["equipment_result"]["result_file"] == str(tmp_path / "save_raw_data" / filename)
    combined = {**result.data["equipment_result"], **{key: result.data[key] for key in ("equipment_report", "equipment_handoff", "utm_data_ready")}}
    assert AnalysisAgent._live_equipment_handoff_gate(combined)[0] is True
    curve, _ = AnalysisAgent()._curve_from_equipment(combined)
    assert len(curve) == 2
    for fault in ("missing_blocks", "blocked_workflow", "packet_path", "packet_identity", "blocking_vision"):
        invalid = deepcopy(combined)
        if fault == "missing_blocks":
            invalid["equipment_report"]["block_executions"] = []
        elif fault == "blocked_workflow":
            invalid["equipment_report"]["workflow_agentic_task"]["status"] = "blocked"
        elif fault == "packet_path":
            invalid["utm_data_ready"]["linux_path"] = "/wrong.csv"
        elif fault == "packet_identity":
            invalid["utm_data_ready"]["specimen_id"] = "another-specimen"
        else:
            invalid["equipment_report"]["block_executions"].append({
                "phase": "vision", "blocking": True, "outcome": "error", "target": "__blocked__",
            })
        assert AnalysisAgent._live_equipment_handoff_gate(invalid)[0] is False, fault


@pytest.fixture(autouse=True)
def _isolated_equipment_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(LabEquipmentAgent, "_RUNTIME_ROOT", tmp_path / "equipment_runtime")
    monkeypatch.setattr(
        LabEquipmentAgent,
        "_SKILL_FLOW_PATH",
        tmp_path / "equipment_skill_flows.json",
    )


class _CtxStub:
    def __init__(self, tools: ToolRegistry, response_text: str) -> None:
        self.tools = tools
        self.response_text = response_text
        self.prompts: list[tuple[str, str]] = []
        self.events: list[dict[str, Any]] = []

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        self.prompts.append((task_type, prompt))
        return SimpleNamespace(text=self.response_text)

    def on_tool_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _state(
    *,
    mode: Mode = Mode.TEST,
    active_goal: str = "program1 실행",
    experiment_spec: dict[str, Any] | None = None,
) -> OrchestratorState:
    return OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=mode,
        stage=Stage.EQUIPMENT,
        active_goal=active_goal,
        current_experiment_spec={"equipment_program_id": "program1"} if experiment_spec is None else experiment_spec,
        latest_observations={"observation_id": "obs-test", "transfer_readiness": {"ready": True}},
        latest_analysis={"last_grasp_score": 0.86},
        run_metadata={
            "specimen_result": {"specimen_id": "specimen-test", "handoff_status": "ready"},
            "manipulation_result": {"completion_status": "reported_complete"},
        },
    )


def _tools(tmp_path: Path) -> ToolRegistry:
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_equipment_tools(
        tools,
        {
            "devices": {
                "equipment": {
                    "mode": "simulator",
                    "windows_pyautogui": {"connection_memory_path": str(tmp_path / "conn.json")},
                }
            }
        },
        repo_root=tmp_path,
    )
    return tools


def _saved_recording() -> dict[str, Any]:
    return {
        "schema": "atr.equipment_recording.v1",
        "recording_id": "rec-agent-program1",
        "name": "Program 1 Skill",
        "target_app": "Program 1",
        "target_window": "Program 1",
        "status": "saved",
        "events": [{"kind": "key_press", "at_ms": 10, "key": "enter"}],
        "checkpoints": [],
    }


@pytest.mark.asyncio
async def test_equipment_agent_does_not_silently_fallback_to_direct_utm() -> None:
    tools = ToolRegistry()
    direct_calls: list[dict[str, Any]] = []
    tools.register(
        "utm.run_protocol",
        lambda payload: direct_calls.append(dict(payload)) or {"ok": True, "status": "completed"},
    )
    ctx = _CtxStub(tools, "{}")

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_WORKER_UNAVAILABLE"
    assert direct_calls == []


@pytest.mark.asyncio
async def test_equipment_skill_executes_segments_without_llm_call(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="windows_desktop_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("program1_skill", "1.0.0")
    registry.validate("program1_skill", "1.0.0")
    for program in package["programs"]:
        assert tools.call("equipment.pyautogui.register_program", {"runtime_mode": "test", "program": program})["ok"] is True
    registry.mark_deployed(
        "program1_skill",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    run_payloads: list[dict[str, Any]] = []
    original_run = tools._tools["equipment.pyautogui.run"]
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_payloads.append(dict(payload)) or original_run(payload),
    )
    ctx = _CtxStub(tools, "must not be used")
    state = _state(
        experiment_spec={
            "equipment_skill": {
                "skill_id": "program1_skill",
                "version": "1.0.0",
                "target_profile": "windows_desktop_v1",
                "registry_root": str(tmp_path / "skills"),
            }
        }
    )
    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    assert result.data["equipment_skill_execution"]["state"] == "COMPLETED"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["equipment_skill_execution"]["runtime_execution"]["lifecycle"] == "COMPLETED"
    assert run_payloads and all(item["bridge_id"] == "simulator" for item in run_payloads)
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_equipment_skill_sends_declared_program_timeout_to_bridge(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry_root = tmp_path / "skills"
    registry = EquipmentSkillRegistry(registry_root)
    recording = _saved_recording()
    recording["events"] = [
        {"kind": "wait", "at_ms": 0, "seconds": 30},
        {"kind": "wait", "at_ms": 30_000, "seconds": 30},
        {"kind": "wait", "at_ms": 60_000, "seconds": 30},
    ]
    registry.create_draft(
        recording=recording,
        skill_id="long_wait_skill",
        version="1.0.0",
        target_profile="windows_desktop_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("long_wait_skill", "1.0.0")
    registry.validate("long_wait_skill", "1.0.0")
    registry.mark_deployed(
        "long_wait_skill",
        "1.0.0",
        bridge_id="equipment-worker",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    run_payloads: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_payloads.append(dict(payload))
        or {
            "ok": True,
            "status": "completed",
            "program_id": payload["program_id"],
            "sequence_id": payload["sequence_id"],
        },
    )
    request = {
        "skill_id": "long_wait_skill",
        "version": "1.0.0",
        "target_profile": "windows_desktop_v1",
        "registry_root": str(registry_root),
        "sequence_id": "run-test-long-wait",
        "skip_profile_vision_preflight": True,
        "completion_scope": "skill_step",
    }

    result = await LabEquipmentAgent()._run_equipment_skill(
        _state(mode=Mode.LIVE),
        _CtxStub(tools, "must not be used"),
        request,
    )

    assert result.success is True
    assert run_payloads[0]["declared_execution_timeout_s"] == 90.0


@pytest.mark.asyncio
async def test_physical_test_loop_runs_every_equipment_segment_live_with_explicit_approval(
    tmp_path: Path,
) -> None:
    """A GUI test loop with real hardware must keep the Guardian approval contract."""
    tools = ToolRegistry()
    registry_root = tmp_path / "skills"
    registry = EquipmentSkillRegistry(registry_root)
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="utm_prepare_next_specimen",
        version="1.0.0",
        target_profile="windows_desktop_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("utm_prepare_next_specimen", "1.0.0")
    registry.validate("utm_prepare_next_specimen", "1.0.0")
    registry.mark_deployed(
        "utm_prepare_next_specimen",
        "1.0.0",
        bridge_id="windows_192.168.50.201",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    run_payloads: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_payloads.append(dict(payload))
        or {"ok": True, "status": "completed", "program_id": payload["program_id"]},
    )
    state = _state(
        mode=Mode.TEST,
        experiment_spec={
            "test_mode_autofill": True,
            "printer_test_path": "installed_printer",
            "test_printer_transport": "real",
            "allow_test_equipment_live": True,
            "equipment_agentic_confirm_execute": True,
        },
    )

    result = await LabEquipmentAgent()._run_equipment_skill(
        state,
        _CtxStub(tools, "must not be used"),
        {
            "skill_id": "utm_prepare_next_specimen",
            "version": "1.0.0",
            "target_profile": "windows_desktop_v1",
            "registry_root": str(registry_root),
            "skip_profile_vision_preflight": True,
            "completion_scope": "skill_step",
        },
    )

    assert result.success is True
    assert run_payloads
    assert all(payload["runtime_mode"] == "live" for payload in run_payloads)
    assert all(payload["confirm_execute"] is True for payload in run_payloads)
    assert all(payload["confirm_live_execute"] is True for payload in run_payloads)
    gate = guardian_gate(
        state=state,
        stage="equipment",
        phase="action",
        agent="equipment_agent",
        tool="equipment.pyautogui.run",
        action="pre_tool_call",
        payload=run_payloads[0],
    )
    assert gate_blocks_execution(gate) is False
    assert not any(alarm["reason_code"] == "HUMAN_APPROVAL_REQUIRED" for alarm in gate["alarms"])


@pytest.mark.asyncio
async def test_agentic_flow_skill_step_does_not_require_whole_utm_cycle_evidence(
    tmp_path: Path,
) -> None:
    """A successful Move Jigs step must not be judged as the final UTM handoff."""
    tools = _tools(tmp_path)
    registry_root = tmp_path / "skills"
    registry = EquipmentSkillRegistry(registry_root)
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="utm_prepare_step",
        version="1.0.0",
        target_profile="utm_windows_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("utm_prepare_step", "1.0.0")
    registry.validate("utm_prepare_step", "1.0.0")
    for program in package["programs"]:
        assert tools.call(
            "equipment.pyautogui.register_program",
            {"runtime_mode": "test", "program": program},
        )["ok"]
    registry.mark_deployed(
        "utm_prepare_step",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: {
            "ok": True,
            "status": "completed",
            "program_id": payload["program_id"],
            "sequence_id": payload["sequence_id"],
            "screen_checks": [{"checkpoint": "move_jigs_complete", "ok": True}],
        },
    )
    request_log_calls: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.request_log",
        lambda payload: request_log_calls.append(dict(payload)) or {"ok": True},
    )
    request = {
        "skill_id": "utm_prepare_step",
        "version": "1.0.0",
        "target_profile": "utm_windows_v1",
        "registry_root": str(registry_root),
        "sequence_id": "run-test-flow-prepare-0",
        "task": "Move Jigs for Next Specimen",
        "skip_profile_vision_preflight": True,
        "completion_scope": "skill_step",
    }
    agent = LabEquipmentAgent()
    ctx = _CtxStub(tools, "must not be used")

    state = _state(mode=Mode.LIVE)
    first = await agent._run_equipment_skill(state, ctx, request)
    resumed = await agent._run_equipment_skill(state, ctx, request)

    assert first.success is True
    assert first.data["equipment_handoff"]["status"] == "execution_complete"
    assert first.data["equipment_handoff"]["ready_for_analysis"] is False
    assert first.data["equipment_skill_execution"]["runtime_execution"]["lifecycle"] == "COMPLETED"
    assert resumed.success is True
    assert resumed.data["equipment_skill_execution"]["idempotent"] is True
    assert request_log_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vision_enabled", "vision_blocking", "vision_response", "expected_outcome", "expected_success"),
    [
        (False, True, None, "bypass", True),
        (True, True, {"ok": True, "results": [{"ok": True}]}, "detected", True),
        (True, True, {"ok": False, "results": [{"ok": False}]}, "not_detected", False),
        (True, False, {"ok": False, "results": [{"ok": False}]}, "not_detected", True),
        (
            True,
            True,
            {
                "ok": False,
                "failure_code": "TOPIC_TIMEOUT",
                "results": [{"ok": False}],
            },
            "timeout",
            False,
        ),
        (
            True,
            True,
            {
                "ok": False,
                "failure_code": "UTM_MOTION_NOT_CONFIRMED",
                "results": [{"ok": False}],
            },
            "not_detected",
            False,
        ),
        (
            True,
            True,
            {
                "ok": False,
                "failure_code": "UTM_OBSERVER_NOT_CONFIGURED",
                "results": [],
            },
            "error",
            False,
        ),
    ],
)
async def test_equipment_skill_flow_executes_composite_block_and_vision_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    vision_enabled: bool,
    vision_blocking: bool,
    vision_response: dict[str, Any] | None,
    expected_outcome: str,
    expected_success: bool,
) -> None:
    tools = _tools(tmp_path)
    registry_root = tmp_path / "skills"
    registry = EquipmentSkillRegistry(registry_root)
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="windows_desktop_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("program1_skill", "1.0.0")
    registry.validate("program1_skill", "1.0.0")
    for program in package["programs"]:
        assert tools.call("equipment.pyautogui.register_program", {"runtime_mode": "test", "program": program})["ok"]
    registry.mark_deployed(
        "program1_skill",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    flow_path = tmp_path / "equipment_skill_flows.json"
    EquipmentSkillFlowStore(flow_path).save(
        "windows_desktop_v1",
        {
            "schema": "atr.equipment_skill_flow.v1",
            "flow_id": "windows_desktop_v1",
            "profile_id": "windows_desktop_v1",
            "agentic_task_id": "",
            "blocks": [
                {
                    "id": "run_program",
                    "label": "Run program",
                    "skill": {"skill_id": "program1_skill", "skill_version": "1.0.0"},
                    "agentic": {
                        "task": "Run bounded equipment demonstration",
                        "completed": "__complete__",
                        "failed": "__blocked__",
                    },
                    "vision": {
                        "enabled": vision_enabled,
                        "blocking": vision_blocking,
                        "task_id": "utm_motion_confirm",
                        "detected": "__complete__",
                        "not_detected": "__blocked__",
                        "timeout": "__blocked__",
                        "error": "__blocked__",
                    },
                },
            ],
        },
    )
    settings_path = tmp_path / "equipment_workspace_settings.json"
    settings_path.write_text(
        json.dumps({"profiles": {"windows_desktop_v1": {"vision_link_enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", flow_path, raising=False)
    monkeypatch.setattr(LabEquipmentAgent, "_WORKSPACE_SETTINGS_PATH", settings_path, raising=False)
    vision_payloads: list[dict[str, Any]] = []
    if vision_response is not None:
        vision_response = dict(vision_response)
        raw_results = vision_response.get("results")
        if isinstance(raw_results, list) and len(raw_results) == 1 and isinstance(raw_results[0], dict):
            result_item = dict(raw_results[0])
            result_item.update(
                {
                    "task_id": "utm_motion_confirm",
                    "check_id": "utm_motion_confirm",
                    "run_id": "run-test",
                    "specimen_id": "specimen-test",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                }
            )
            vision_response["results"] = [result_item]
        tools.register(
            "vision.equipment_cross_check",
            lambda payload: vision_payloads.append(dict(payload)) or vision_response,
        )
    ctx = _CtxStub(tools, "must not be used")
    state = _state(
        experiment_spec={
            "equipment_profile_id": "windows_desktop_v1",
            "equipment_skill_registry_root": str(registry_root),
        }
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is expected_success
    execution = result.data["equipment_skill_flow_execution"]
    assert [(item["block_id"], item["phase"]) for item in execution["transitions"]] == [
        ("run_program", "skill"),
        ("run_program", "vision"),
    ]
    assert execution["transitions"][1]["outcome"] == expected_outcome
    if vision_enabled:
        assert len(vision_payloads) == 1
        assert [item["check_id"] for item in vision_payloads[0]["checks"]] == [
            "utm_motion_confirm"
        ]
        assert vision_payloads[0]["checks"][0]["task_id"] == "utm_motion_confirm"
        assert execution["transitions"][1]["vision_task_id"] == "utm_motion_confirm"
        assert execution["transitions"][1]["check_id"] == "utm_motion_confirm"
        assert execution["transitions"][1]["vision_task_label"] == (
            "UTM Motion Confirmation"
        )
        assert execution["transitions"][1]["blocking"] is vision_blocking
        assert execution["transitions"][1]["kind"] == (
            "vision_gate" if vision_blocking else "vision_observation"
        )
    else:
        assert vision_payloads == []
    assert all(
        item["task"] == "Run bounded equipment demonstration"
        for item in execution["transitions"]
    )
    assert result.data["equipment_skill_execution"]["agentic_task"] == (
        "Run bounded equipment demonstration"
    )
    assert execution["terminal"] == ("__complete__" if expected_success else "__blocked__")
    assert "workflow_agentic_task" not in execution
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_equipment_agentic_task_blocks_before_skill_binding_without_verified_live_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch the overlay sending equipment input before its locked upstream gate."""
    flow_path = tmp_path / "equipment_skill_flows.json"
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    EquipmentSkillFlowStore(flow_path).save(
        "windows_desktop_v1",
        flow,
    )
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", flow_path, raising=False)
    tools = _tools(tmp_path)
    equipment_calls: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: equipment_calls.append(dict(payload)) or {"ok": True},
    )
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "equipment_profile_id": "windows_desktop_v1",
            "equipment_skill_registry_root": str(tmp_path / "skills"),
        },
    )
    state.run_metadata["manipulation_result"] = {
        "handoff_status": "reported_complete",
        "run_id": "run-test",
        "specimen_id": "specimen-test",
    }

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_HANDOFF_NOT_READY"
    assert result.data["equipment_skill_flow_execution"]["workflow_agentic_task"]["entry_gate"]["locked"] is True
    valid, message = validate_agent_output("equipment", result.data)
    assert valid is False
    assert "EQUIPMENT_HANDOFF_NOT_READY" in message
    assert "Missing required keys" not in message
    assert equipment_calls == []


@pytest.mark.asyncio
async def test_equipment_entry_gate_uses_complete_robot_handoff_when_execution_result_lacks_identity(
    tmp_path: Path,
) -> None:
    """Catch an identity-less execution result masking the canonical robot handoff."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "equipment_profile_id": "windows_desktop_v1",
            "specimen_id": "specimen-test",
        },
    )
    state.run_metadata["manipulation_result"] = {
        "handoff_status": "ready_for_equipment",
        "completion_status": "verified_complete",
    }
    state.run_metadata["robot_task_result"] = {
        "run_id": "run-test",
        "specimen_id": "specimen-test",
        "handoff_status": "ready_for_equipment",
        "completion_status": "verified_complete",
    }

    result = await LabEquipmentAgent()._run_equipment_skill_flow(
        state,
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_SKILL_FLOW_UNBOUND"
    assert result.data["required_entry_gate"]["ok"] is True
    assert result.data["required_entry_gate"]["source"] == "robot_task_result"


@pytest.mark.asyncio
async def test_equipment_agentic_task_preserves_cycle_evidence_failure_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch a specific Raw CSV failure being overwritten by the generic flow code."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}

    agent = LabEquipmentAgent()

    async def fake_skill(*_args: Any, **_kwargs: Any) -> AgentResult:
        return AgentResult(
            success=True,
            summary="simulated step complete",
            data={"equipment_result": {}, "equipment_report": {}},
        )

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    result = await agent._run_equipment_skill_flow(
        _state(
            experiment_spec={
                "equipment_profile_id": "windows_desktop_v1",
                "specimen_id": "specimen-test",
            }
        ),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.success is False
    assert result.data["handoff_eligibility"]["failure_code"] == "RAW_CSV_VALIDATION_FAILED"
    assert result.data["equipment_handoff"]["failure_code"] == "RAW_CSV_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_raw_csv_skill_payload_gets_context_from_agentic_state(tmp_path: Path) -> None:
    """Catch agentic Raw CSV saves dispatching without the required export_context."""
    tools = ToolRegistry()
    run_calls: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_calls.append(dict(payload)) or {"ok": True, "status": "completed"},
    )
    registry_root = tmp_path / "skills"
    registry = EquipmentSkillRegistry(registry_root)
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="utm_save_raw_data",
        version="1.0.11",
        target_profile="utm_windows_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("utm_save_raw_data", "1.0.11")
    registry.validate("utm_save_raw_data", "1.0.11")
    registry.mark_deployed(
        "utm_save_raw_data",
        "1.0.11",
        bridge_id="windows_192.168.50.201",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "specimen_id": "cube-03",
            "equipment_profile_id": "utm_windows_v1",
            "equipment_agentic_confirm_execute": True,
        },
    )
    state.active_session_id = "session-20260902-A"
    state.loop_count = 1

    await LabEquipmentAgent()._run_equipment_skill(
        state,
        _CtxStub(tools, "must not be used"),
        {
            "skill_id": "utm_save_raw_data",
            "version": "1.0.11",
            "target_profile": "utm_windows_v1",
            "registry_root": str(registry_root),
            "skip_profile_vision_preflight": True,
            "completion_scope": "skill_step",
        },
    )

    assert len(run_calls) == 1
    assert run_calls[0]["confirm_execute"] is True
    assert run_calls[0]["export_context"] == {
        "mode": "live",
        "session_id": "session-20260902-A",
        "specimen_id": "cube-03",
        "loop_index": 2,
        "repeat_index": 1,
    }


@pytest.mark.asyncio
async def test_equipment_flow_passes_saved_windows_csv_path_to_validation_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}
    requests: list[dict[str, Any]] = []
    agent = LabEquipmentAgent()

    async def fake_skill(_state: Any, _ctx: Any, request: dict[str, Any]) -> AgentResult:
        requests.append(dict(request))
        equipment_result: dict[str, Any] = {}
        if request.get("task") == "Save Raw Data CSV":
            equipment_result["output_artifacts"] = [
                {
                    "kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "run_id": "run-test",
                    "specimen_id": "specimen-test",
                    "windows_path": "C:/worker/artifacts/raw_csv/test_run_specimen_loop-0001_rep-0001.csv",
                    "linux_path": "/tmp/raw.csv",
                }
            ]
        return AgentResult(
            success=True,
            summary="simulated step complete",
            data={"equipment_result": equipment_result, "equipment_report": {}},
        )

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    await agent._run_equipment_skill_flow(
        _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1", "specimen_id": "specimen-test"}),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    validation = next(item for item in requests if item.get("task") == "Validate Raw Data CSV")
    assert validation["runtime_context"]["raw_csv_path"] == "C:/worker/artifacts/raw_csv/test_run_specimen_loop-0001_rep-0001.csv"


@pytest.mark.asyncio
async def test_equipment_flow_cancellation_prevents_the_next_registered_skill_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}
    calls: list[dict[str, Any]] = []
    agent = LabEquipmentAgent()

    async def fake_skill(_state: Any, _ctx: Any, request: dict[str, Any]) -> AgentResult:
        calls.append(dict(request))
        return AgentResult(success=True, summary="unexpected", data={})

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    result = await agent._run_equipment_skill_flow(
        _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1", "specimen_id": "specimen-test"}),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
        cancel_requested=lambda: True,
    )

    assert result.success is False
    assert result.summary == "Equipment Skill Flow cancelled"
    assert result.data["equipment_skill_flow_execution"]["failure_code"] == "EQUIPMENT_AGENTIC_RUN_CANCELLED"
    assert calls == []


@pytest.mark.asyncio
async def test_device_bridge_flow_starts_first_registered_block_without_orchestration_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}
    calls: list[dict[str, Any]] = []
    agent = LabEquipmentAgent()

    async def fake_skill(_state: Any, _ctx: Any, request: dict[str, Any]) -> AgentResult:
        calls.append(dict(request))
        return AgentResult(success=True, summary="simulated", data={"equipment_result": {}, "equipment_report": {}})

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    state = _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1"})
    state.mode = Mode.LIVE
    state.run_metadata.pop("specimen_result", None)
    state.run_metadata.pop("manipulation_result", None)

    blocked = await agent._run_equipment_skill_flow(state, _CtxStub(_tools(tmp_path), "unused"), flow)
    assert blocked.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_HANDOFF_NOT_READY"
    assert calls == []

    standalone = await agent._run_equipment_skill_flow(
        state,
        _CtxStub(_tools(tmp_path), "unused"),
        flow,
        require_entry_handoff=False,
    )
    assert calls[0]["task"] == flow["blocks"][0]["agentic"]["task"]
    assert calls[0]["completion_scope"] == "skill_step"
    assert standalone.success is True
    assert standalone.data["equipment_skill_flow_execution"]["terminal"] == "__complete__"
    assert standalone.data["workflow_agentic_task"]["status"] == "completed"


@pytest.mark.asyncio
async def test_each_agent_start_condition_creates_a_new_idle_equipment_flow_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh agent call must not inherit completed/failed blocks from an earlier call."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}
    requests: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    agent = LabEquipmentAgent()

    async def fake_skill(_state: Any, _ctx: Any, request: dict[str, Any]) -> AgentResult:
        requests.append(dict(request))
        return AgentResult(
            success=True,
            summary="simulated",
            data={"equipment_result": {}, "equipment_report": {}},
        )

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(
        agent,
        "_write_skill_flow_execution",
        lambda _profile_id, execution: projections.append(dict(execution)),
    )
    state = _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1"})
    ctx = _CtxStub(_tools(tmp_path), "must not be used")

    first = await agent._run_equipment_skill_flow(
        state,
        ctx,
        flow,
        require_entry_handoff=False,
    )
    first_request_count = len(requests)
    second = await agent._run_equipment_skill_flow(
        state,
        ctx,
        flow,
        require_entry_handoff=False,
    )

    first_execution = first.data["equipment_skill_flow_execution"]
    second_execution = second.data["equipment_skill_flow_execution"]
    assert first.data["protocol_note"] == "agentic UTM equipment skill flow"
    assert second.data["protocol_note"] == "agentic UTM equipment skill flow"
    assert first_execution["flow_execution_id"] != second_execution["flow_execution_id"]
    assert requests[0]["sequence_id"] != requests[first_request_count]["sequence_id"]
    idle = [item for item in projections if item.get("status") == "idle"]
    assert [item["flow_execution_id"] for item in idle] == [
        first_execution["flow_execution_id"],
        second_execution["flow_execution_id"],
    ]
    assert all(item["terminal"] == "" and item["transitions"] == [] for item in idle)


@pytest.mark.asyncio
async def test_equipment_preflight_only_resolves_agentic_flow_without_worker_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch a safe-validation cycle crossing the Windows/UTM actuation boundary."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": f"skill-{block['id']}", "skill_version": "1.0.0"}
    calls: list[dict[str, Any]] = []
    tools = _tools(tmp_path)
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: calls.append(dict(payload))
        or (_ for _ in ()).throw(AssertionError("equipment execution is forbidden in preflight_only mode")),
    )
    agent = LabEquipmentAgent()
    monkeypatch.setattr(agent, "_equipment_skill_flow", lambda _state: flow)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    state = _state(
        experiment_spec={
            "equipment_profile_id": "windows_desktop_v1",
            "specimen_id": "specimen-test",
            "execution_policy": {"lab_equipment": "preflight_only"},
        }
    )
    state.run_metadata["manipulation_preflight"] = {
        "schema": "manipulation_preflight.v1",
        "run_id": "run-test",
        "specimen_id": "specimen-test",
        "status": "execution_ready_pending_approval",
        "actuation_performed": False,
    }

    result = await agent.run(state, _CtxStub(tools, "must not be used"))

    assert result.success is True
    assert calls == []
    preflight = result.data["equipment_preflight"]
    assert preflight["schema"] == "equipment_preflight.v1"
    assert preflight["status"] == "execution_ready_pending_approval"
    assert preflight["actuation_performed"] is False
    assert preflight["resolved_program_id"] == "run_utm_compression_cycle"
    assert [step["block_id"] for step in preflight["planned_steps"]] == [
        block["id"] for block in flow["blocks"]
    ]
    assert all(step["would_execute"]["skill_id"] for step in preflight["planned_steps"])
    assert result.data["equipment_handoff"]["ready_for_analysis"] is False
    assert result.data["protocol_note"] == "agentic UTM flow validated; execution deferred by policy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("schema", "manipulation_preflight.v0"),
        ("run_id", "run-other"),
        ("specimen_id", "specimen-other"),
    ],
)
async def test_equipment_preflight_rejects_mismatched_manipulation_lineage_without_actuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
    changed_value: str,
) -> None:
    """Catch stale or cross-specimen Manipulation readiness authorizing Equipment."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": f"skill-{block['id']}", "skill_version": "1.0.0"}
    calls: list[str] = []
    tools = ToolRegistry()
    for tool_name in (
        "equipment.pyautogui.run",
        "vision.equipment_cross_check",
        "utm.run_protocol",
    ):
        tools.register(
            tool_name,
            lambda _payload, name=tool_name: calls.append(name)
            or (_ for _ in ()).throw(AssertionError(f"{name} is forbidden in preflight_only mode")),
        )
    agent = LabEquipmentAgent()
    monkeypatch.setattr(agent, "_equipment_skill_flow", lambda _state: flow)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "equipment_profile_id": "windows_desktop_v1",
            "specimen_id": "specimen-test",
            "execution_policy": {"lab_equipment": "preflight_only"},
        },
    )
    state.run_metadata["manipulation_preflight"] = {
        "schema": "manipulation_preflight.v1",
        "run_id": "run-test",
        "specimen_id": "specimen-test",
        "status": "execution_ready_pending_approval",
        "actuation_performed": False,
    }
    state.run_metadata["manipulation_preflight"][changed_field] = changed_value

    result = await agent.run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert calls == []
    assert result.data["equipment_preflight"]["status"] == "preflight_not_ready"
    assert result.data["equipment_preflight"]["failure_code"] == "MANIPULATION_PREFLIGHT_REQUIRED"
    assert result.data["equipment_handoff"]["ready_for_analysis"] is False


@pytest.mark.asyncio
async def test_equipment_preflight_only_blocks_explicit_skill_when_saved_flow_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch an explicit Equipment Skill bypassing the no-actuation entry policy."""
    calls: list[str] = []
    tools = ToolRegistry()
    for tool_name in (
        "equipment.pyautogui.run",
        "vision.equipment_cross_check",
        "utm.run_protocol",
    ):
        tools.register(
            tool_name,
            lambda _payload, name=tool_name: calls.append(name)
            or (_ for _ in ()).throw(AssertionError(f"{name} is forbidden in preflight_only mode")),
        )
    agent = LabEquipmentAgent()

    async def forbidden_skill(*_args: Any, **_kwargs: Any) -> AgentResult:
        raise AssertionError("explicit Equipment Skill execution is forbidden in preflight_only mode")

    monkeypatch.setattr(agent, "_run_equipment_skill", forbidden_skill)
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "equipment_skill": {"skill_id": "utm_start", "version": "1.0.0"},
            "execution_policy": {"lab_equipment": "preflight_only"},
        },
    )
    ctx = _CtxStub(tools, "must not be used")

    result = await agent.run(state, ctx)

    assert result.success is False
    assert calls == []
    assert ctx.prompts == []
    assert result.data["equipment_preflight"] == {
        "schema": "equipment_preflight.v1",
        "status": "preflight_not_ready",
        "actuation_performed": False,
        "run_id": "run-test",
        "profile_id": "",
        "failure_code": "EQUIPMENT_PREFLIGHT_FLOW_REQUIRED",
        "message": "A saved, enabled Equipment Skill Flow is required by preflight_only policy.",
        "requested_branch": "explicit_skill",
    }
    assert result.data["equipment_result"]["status"] == "preflight_not_ready"
    assert result.data["equipment_handoff"]["ready_for_analysis"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("experiment_spec", "requested_branch"),
    [
        (
            {
                "equipment_profile_id": "utm_windows_v1",
                "equipment_program_id": "utm_compression_start_v1",
                "execution_policy": {"lab_equipment": "preflight_only"},
            },
            "profile",
        ),
        (
            {
                "utm": {"direct_backend_configured": True, "profile": "vendor_direct_profile"},
                "execution_policy": {"lab_equipment": "preflight_only"},
            },
            "legacy",
        ),
    ],
)
async def test_equipment_preflight_only_blocks_profile_or_legacy_path_when_saved_flow_is_missing(
    experiment_spec: dict[str, Any],
    requested_branch: str,
) -> None:
    """Catch profile and legacy fallbacks crossing any hardware boundary without a saved flow."""
    calls: list[str] = []
    tools = ToolRegistry()
    for tool_name in (
        "equipment.pyautogui.run",
        "vision.equipment_cross_check",
        "utm.run_protocol",
    ):
        tools.register(
            tool_name,
            lambda _payload, name=tool_name: calls.append(name)
            or (_ for _ in ()).throw(AssertionError(f"{name} is forbidden in preflight_only mode")),
        )
    ctx = _CtxStub(tools, "must not be used")

    result = await LabEquipmentAgent().run(
        _state(mode=Mode.LIVE, experiment_spec=experiment_spec),
        ctx,
    )

    assert result.success is False
    assert calls == []
    assert ctx.prompts == []
    assert result.data["equipment_preflight"]["status"] == "preflight_not_ready"
    assert result.data["equipment_preflight"]["actuation_performed"] is False
    assert result.data["equipment_preflight"]["requested_branch"] == requested_branch
    assert result.data["equipment_preflight"]["failure_code"] == "EQUIPMENT_PREFLIGHT_FLOW_REQUIRED"
    assert result.data["equipment_handoff"]["ready_for_analysis"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("artifact_case", "expected_success"),
    [
        ("valid", True),
        ("missing_identity", False),
        ("mismatched_acquisition", False),
        ("multiple_candidates", False),
    ],
)
async def test_canonical_agentic_task_completes_only_with_bound_csv_and_clearance_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_case: str,
    expected_success: bool,
) -> None:
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}

    agent = LabEquipmentAgent()

    async def fake_skill(_state: Any, _ctx: Any, request: dict[str, Any]) -> AgentResult:
        task = str(request.get("task") or "")
        equipment_result: dict[str, Any] = {}
        equipment_report: dict[str, Any] = {}
        if task == "Save Raw Data CSV":
            artifact_identity = (
                {"run_id": "run-test", "specimen_id": "specimen-test"}
                if artifact_case != "missing_identity"
                else {}
            )
            equipment_result["output_artifacts"] = [
                {
                    "kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "linux_path": "/tmp/raw.csv",
                    **artifact_identity,
                }
            ]
            if artifact_case == "multiple_candidates":
                equipment_result["output_artifacts"].append(
                    {
                        "kind": "utm_csv",
                        "artifact_id": "raw-2",
                        "linux_path": "/tmp/raw-2.csv",
                        **artifact_identity,
                    }
                )
            equipment_report["data_acquisition"] = {
                "artifact_id": "raw-1",
                "run_id": "run-test",
                "specimen_id": "specimen-test",
                "linux_path": "/tmp/stale.csv" if artifact_case == "mismatched_acquisition" else "/tmp/raw.csv",
            }
        elif task == "Validate Raw Data CSV":
            artifact_identity = (
                {"run_id": "run-test", "specimen_id": "specimen-test"}
                if artifact_case != "missing_identity"
                else {}
            )
            equipment_result["output_artifacts"] = [
                {
                    "kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "linux_path": "/tmp/raw.csv",
                    **artifact_identity,
                }
            ]
            if artifact_case == "multiple_candidates":
                equipment_result["output_artifacts"].append(
                    {
                        "kind": "utm_csv",
                        "artifact_id": "raw-2",
                        "linux_path": "/tmp/raw-2.csv",
                        **artifact_identity,
                    }
                )
            equipment_report["data_acquisition"] = {
                "status": "pulled_to_linux",
                "artifact_id": "raw-1",
                "run_id": "run-test",
                "specimen_id": "specimen-test",
                "linux_path": "/tmp/stale.csv" if artifact_case == "mismatched_acquisition" else "/tmp/raw.csv",
                "row_count_probe": 2,
                "columns_probe": ["time_s", "displacement_mm", "force_N"],
            }
            equipment_report["cross_checks"] = {"data_parse_probe_ok": True}
        elif task == "Restore configured robot-entry clearance":
            equipment_result["height"] = {"observed": 1.0, "target": 1.0}
        return AgentResult(
            success=True,
            summary="simulated step complete",
            data={"equipment_result": equipment_result, "equipment_report": equipment_report},
        )

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    result = await agent._run_equipment_skill_flow(
        _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1", "specimen_id": "specimen-test"}),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.success is expected_success
    assert result.data["raw_data_export"]["validated"] is expected_success
    if expected_success:
        assert result.data["next_specimen_readiness"]["clearance_restored"] is True
        assert result.data["handoff_eligibility"]["eligible"] is True
    else:
        assert result.data["handoff_eligibility"]["failure_code"] == "RAW_CSV_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_unbound_agentic_task_still_projects_locked_gate_for_live_gui(
    tmp_path: Path,
) -> None:
    """Catch readiness blocks dropping the workflow contract from report projections."""
    flow = build_utm_compression_flow_template("windows_desktop_v1")

    result = await LabEquipmentAgent()._run_equipment_skill_flow(
        _state(
            experiment_spec={
                "equipment_profile_id": "windows_desktop_v1",
                "specimen_id": "specimen-test",
            }
        ),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_SKILL_FLOW_UNBOUND"
    assert result.data["workflow_agentic_task"]["task_id"] == "run_utm_compression_cycle"
    assert result.data["required_entry_gate"]["locked"] is True
    assert result.data["equipment_report"]["workflow_agentic_task"] == result.data["workflow_agentic_task"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_id", "shorten", "expected_code"),
    [
        ("unknown_task", False, "EQUIPMENT_AGENTIC_TASK_UNSUPPORTED"),
        ("run_utm_compression_cycle", True, "EQUIPMENT_FLOW_REVISION_INVALID"),
    ],
)
async def test_agentic_task_contract_blocks_unsupported_revision_before_any_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_id: str,
    shorten: bool,
    expected_code: str,
) -> None:
    flow = build_utm_compression_flow_template("windows_desktop_v1")
    flow["agentic_task_id"] = task_id
    if shorten:
        flow["blocks"] = flow["blocks"][:-1]
    for block in flow["blocks"]:
        block["skill"] = {"skill_id": "fake", "skill_version": "1.0.0"}

    agent = LabEquipmentAgent()
    skill_calls: list[str] = []

    async def fake_skill(*_args: Any, **_kwargs: Any) -> AgentResult:
        skill_calls.append("called")
        return AgentResult(success=True, summary="unexpected", data={})

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    result = await agent._run_equipment_skill_flow(
        _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1", "specimen_id": "specimen-test"}),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == expected_code
    assert skill_calls == []


@pytest.mark.asyncio
async def test_skill_flow_preflights_every_exact_skill_before_first_device_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "windows_desktop_v1",
        "profile_id": "windows_desktop_v1",
        "agentic_task_id": "",
        "blocks": [
            {
                "id": "first",
                "skill": {"skill_id": "valid", "skill_version": "1.0.0"},
                "agentic": {"task": "First", "completed": "next", "failed": "__blocked__"},
                "vision": {"enabled": False, "detected": "next", "not_detected": "__blocked__", "timeout": "__blocked__", "error": "__blocked__"},
            },
            {
                "id": "second",
                "skill": {"skill_id": "missing", "skill_version": "1.0.0"},
                "agentic": {"task": "Second", "completed": "__complete__", "failed": "__blocked__"},
                "vision": {"enabled": False, "detected": "__complete__", "not_detected": "__blocked__", "timeout": "__blocked__", "error": "__blocked__"},
            },
        ],
    }
    package = {
        "manifest": {
            "lifecycle": "deployed",
            "enabled": True,
            "target_profile": "windows_desktop_v1",
        },
        "annotations": {},
    }

    def fake_get(_registry: EquipmentSkillRegistry, skill_id: str, _version: str) -> dict[str, Any]:
        if skill_id == "missing":
            raise SkillContractError("exact Skill version missing")
        return package

    monkeypatch.setattr(EquipmentSkillRegistry, "get", fake_get)
    agent = LabEquipmentAgent()
    skill_calls: list[str] = []

    async def fake_skill(*_args: Any, **_kwargs: Any) -> AgentResult:
        skill_calls.append("called")
        return AgentResult(success=True, summary="unexpected", data={})

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    result = await agent._run_equipment_skill_flow(
        _state(
            experiment_spec={
                "equipment_profile_id": "windows_desktop_v1",
                "equipment_skill_registry_root": str(tmp_path / "skills"),
            }
        ),
        _CtxStub(_tools(tmp_path), "must not be used"),
        flow,
    )

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_SKILL_FLOW_PREFLIGHT_FAILED"
    assert result.data["equipment_handoff"]["block_id"] == "second"
    assert skill_calls == []


@pytest.mark.asyncio
async def test_skill_flow_preflights_enabled_vision_runtime_tool_before_first_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": "windows_desktop_v1",
        "profile_id": "windows_desktop_v1",
        "agentic_task_id": "",
        "blocks": [
            {
                "id": "verify",
                "skill": {"skill_id": "valid", "skill_version": "1.0.0"},
                "agentic": {"task": "Verify", "completed": "__complete__", "failed": "__blocked__"},
                "vision": {
                    "enabled": True,
                    "task_id": "utm_motion_confirm",
                    "detected": "__complete__",
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            }
        ],
    }
    agent = LabEquipmentAgent()
    skill_calls: list[str] = []

    async def fake_skill(*_args: Any, **_kwargs: Any) -> AgentResult:
        skill_calls.append("called")
        return AgentResult(success=True, summary="unexpected", data={})

    monkeypatch.setattr(agent, "_run_equipment_skill", fake_skill)
    monkeypatch.setattr(agent, "_preflight_skill_flow_resources", lambda **_kwargs: {"ok": True})
    result = await agent._run_equipment_skill_flow(
        _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1"}),
        _CtxStub(ToolRegistry(), "must not be used"),
        flow,
    )

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_VISION_LINK_UNAVAILABLE"
    assert result.data["equipment_handoff"]["block_id"] == "verify"
    assert skill_calls == []


def test_equipment_vision_response_rejects_mismatched_or_stale_identity() -> None:
    now = datetime.now(timezone.utc)
    request = {
        "task_id": "utm_motion_confirm",
        "check_id": "utm_motion_confirm",
        "run_id": "run-identity",
        "specimen_id": "specimen-identity",
    }
    valid = {
        "ok": True,
        "results": [
            {
                "ok": True,
                **request,
                "expires_at": (now + timedelta(minutes=1)).isoformat(),
            }
        ],
    }

    assert LabEquipmentAgent._equipment_vision_response_valid(valid, request) is True

    mismatched = {**valid, "results": [{**valid["results"][0], "run_id": "other-run"}]}
    stale = {
        **valid,
        "results": [
            {
                **valid["results"][0],
                "expires_at": (now - timedelta(seconds=1)).isoformat(),
            }
        ],
    }
    assert LabEquipmentAgent._equipment_vision_response_valid(mismatched, request) is False
    assert LabEquipmentAgent._equipment_vision_response_valid(stale, request) is False
    assert LabEquipmentAgent._equipment_vision_response_valid(
        stale,
        request,
        evaluated_at=now - timedelta(seconds=2),
    ) is True


@pytest.mark.asyncio
async def test_invalid_equipment_skill_flow_blocks_instead_of_falling_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tools(tmp_path)
    run_calls: list[dict[str, Any]] = []
    tools.register("equipment.pyautogui.run", lambda payload: run_calls.append(dict(payload)) or {"ok": True})
    flow_path = tmp_path / "equipment_skill_flows.json"
    flow_path.write_text(
        json.dumps(
            {
                "schema": "atr.equipment_skill_flows.v1",
                "flows": {
                    "windows_desktop_v1": {
                        "schema": "atr.equipment_skill_flow.v1",
                        "profile_id": "windows_desktop_v1",
                        "flow_id": "windows_desktop_v1",
                        "entry_node": "broken",
                        "nodes": [
                            {
                                "id": "broken",
                                "kind": "skill",
                                "skill_id": "missing",
                                "skill_version": "1.0.0",
                                "routes": {"completed": "unknown", "failed": "__blocked__"},
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", flow_path)
    state = _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1"})

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_SKILL_FLOW_INVALID"
    assert run_calls == []


@pytest.mark.asyncio
async def test_unbound_equipment_skill_flow_blocks_without_invoking_a_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tools(tmp_path)
    run_calls: list[dict[str, Any]] = []
    tools.register("equipment.pyautogui.run", lambda payload: run_calls.append(dict(payload)) or {"ok": True})
    flow_path = tmp_path / "equipment_skill_flows.json"
    EquipmentSkillFlowStore(flow_path).save(
        "windows_desktop_v1",
        {
            "schema": "atr.equipment_skill_flow.v1",
            "profile_id": "windows_desktop_v1",
            "flow_id": "windows_desktop_v1",
            "blocks": [
                {
                    "id": "empty_block",
                    "label": "Unbound block",
                    "skill": {"skill_id": "", "skill_version": ""},
                    "agentic": {"completed": "__complete__", "failed": "__blocked__"},
                    "vision": {
                        "enabled": False,
                        "condition": "equipment_specimen_detected",
                        "detected": "__complete__",
                        "not_detected": "__blocked__",
                        "timeout": "__blocked__",
                        "error": "__blocked__",
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", flow_path)
    state = _state(experiment_spec={"equipment_profile_id": "windows_desktop_v1"})

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "EQUIPMENT_SKILL_FLOW_UNBOUND"
    assert run_calls == []


@pytest.mark.asyncio
async def test_live_equipment_skill_blocks_before_worker_when_profile_vision_preflight_fails(
    tmp_path: Path,
) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="utm_skill",
        version="1.0.0",
        target_profile="utm_windows_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("utm_skill", "1.0.0")
    registry.validate("utm_skill", "1.0.0")
    for program in package["programs"]:
        assert tools.call("equipment.pyautogui.register_program", {"runtime_mode": "test", "program": program})["ok"]
    registry.mark_deployed(
        "utm_skill",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    run_calls: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_calls.append(dict(payload)) or {"ok": True, "status": "completed"},
    )
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "equipment_skill": {
                "skill_id": "utm_skill",
                "version": "1.0.0",
                "target_profile": "utm_windows_v1",
                "registry_root": str(tmp_path / "skills"),
            }
        },
    )

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED"
    assert result.data["equipment_skill_execution"]["runtime_execution"]["lifecycle"] == "BLOCKED"
    assert run_calls == []


@pytest.mark.asyncio
async def test_equipment_skill_rejects_unknown_profile_before_worker(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="unknown_profile_skill",
        version="1.0.0",
        target_profile="profile_typo",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("unknown_profile_skill", "1.0.0")
    registry.validate("unknown_profile_skill", "1.0.0")
    registry.mark_deployed(
        "unknown_profile_skill",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    run_calls: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_calls.append(dict(payload)) or {"ok": True, "status": "completed"},
    )
    state = _state(
        experiment_spec={
            "equipment_skill": {
                "skill_id": "unknown_profile_skill",
                "version": "1.0.0",
                "target_profile": "profile_typo",
                "registry_root": str(tmp_path / "skills"),
            }
        }
    )

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is False
    assert result.data["equipment_handoff"]["failure_code"] == "SKILL_CONTRACT_INVALID"
    assert run_calls == []


@pytest.mark.asyncio
async def test_equipment_skill_uses_one_exact_model_recovery_then_resumes(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="windows_desktop_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    registry.annotate(
        "program1_skill",
        "1.0.0",
        {
            "workflow_summary": {
                "intent": "Run the recorded equipment demonstration.",
                "completion_state": "The result view is visible.",
            },
            "steps": [],
        },
    )
    package = registry.compile("program1_skill", "1.0.0")
    registry.validate("program1_skill", "1.0.0")
    registry.mark_deployed(
        "program1_skill",
        "1.0.0",
        bridge_id="simulator",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    program_id = package["programs"][0]["program_id"]
    run_calls: list[dict[str, Any]] = []

    def run(payload: dict[str, Any]) -> dict[str, Any]:
        run_calls.append(dict(payload))
        if payload.get("program_id") == program_id and sum(call.get("program_id") == program_id for call in run_calls) == 1:
            return {
                "ok": False,
                "status": "blocked",
                "failure_code": "PYAUTOGUI_WINDOW_NOT_FOUND",
                "message": "target window focus was lost before actuation",
                "executed_action_count": 0,
                "screen_artifacts": [{"artifact_id": "screen-failure", "sha256": "a" * 64}],
            }
        return {"ok": True, "status": "completed", "program_id": payload.get("program_id", "recovery")}

    tools.register("equipment.pyautogui.run", run)

    class ExactBackend:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def complete(self, **kwargs: Any) -> LLMResponse:
            self.calls.append(dict(kwargs))
            return LLMResponse(
                text=json.dumps(
                    {
                        "schema": "atr.equipment_skill_recovery.v1",
                        "operation": "focus_window",
                        "payload": {"target_window": "Program 1"},
                        "expected_verification": {"window_focused": True},
                        "confidence": 0.93,
                        "attempt": 1,
                    }
                ),
                model=kwargs["model"],
            )

    backend = ExactBackend()
    ctx = _CtxStub(tools, "fallback path must not be used")
    ctx.active_backend = "vllm"
    ctx.primary_backends = {"vllm": backend}
    ctx.primary_backend = backend
    state = _state(
        experiment_spec={
            "equipment_skill": {
                "skill_id": "program1_skill",
                "version": "1.0.0",
                "target_profile": "windows_desktop_v1",
                "registry_root": str(tmp_path / "skills"),
                "auto_recover": True,
                "task": "Run bounded equipment demonstration",
            }
        }
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    assert [call.get("program_id", "recovery") for call in run_calls] == [program_id, "recovery", program_id]
    assert run_calls[1]["sequence"][0]["action"] == "focus_window"
    assert len(backend.calls) == 1
    assert backend.calls[0]["model"] == "gemma4:e4b-it-nvfp4"
    assert backend.calls[0]["metadata"]["no_fallback"] is True
    recovery_context = json.loads(backend.calls[0]["user_prompt"])
    assert recovery_context["agentic_task"] == "Run bounded equipment demonstration"
    assert recovery_context["annotation_context"]["workflow_summary"]["intent"] == (
        "Run the recorded equipment demonstration."
    )
    assert result.data["equipment_skill_execution"]["agentic_task"] == (
        "Run bounded equipment demonstration"
    )
    assert ctx.prompts == []
    assert result.data["equipment_skill_execution"]["state"] == "COMPLETED"
    assert result.data["equipment_skill_execution"]["recovery_history"][0]["operation"] == "focus_window"


@pytest.mark.asyncio
async def test_equipment_agent_executes_generic_profile_without_hidden_utm_or_vision_dependency(tmp_path: Path) -> None:
    plan = {
        "note": "use registered program1",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program1"}},
        ],
    }
    tools = _tools(tmp_path)
    run_payloads: list[dict[str, Any]] = []

    def capture_run(payload: dict[str, Any]) -> dict[str, Any]:
        run_payloads.append(dict(payload))
        return {
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "completed",
            "program_id": str(payload.get("program_id") or ""),
            "program_log": "program1 completed",
        }

    tools.register("equipment.pyautogui.run", capture_run)
    ctx = _CtxStub(tools, json.dumps(plan))

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is True
    assert result.data["equipment_bridge"] == "windows_pyautogui"
    assert result.data["equipment_result"]["program_id"] == "program1"
    assert result.data["equipment_result"]["status"] == "verified_complete"
    assert result.data["equipment_profile"]["profile_id"] == "windows_desktop_v1"
    assert result.data["equipment_report"]["completion_policy"]["interpreter"] == "program_result_v1"
    assert result.data["protocol_note"] == "use registered program1"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["equipment_handoff"]["program_id"] == "program1"
    assert result.data["equipment_report"]["decision"]["handoff_status"] == "ready_for_analysis"
    assert result.data["hardware_alerts"] == []
    assert result.data["incident_records"] == []
    assert [item["tool"] for item in result.data["tool_results"] if item["tool"] == "vision.equipment_cross_check"] == []
    assert run_payloads[0]["equipment_profile"]["profile_id"] == "windows_desktop_v1"
    assert "simulate_utm_protocol" not in run_payloads[0]
    raw_run = next(item["result"] for item in result.data["tool_results"] if item["tool"] == "equipment.pyautogui.run")
    assert raw_run["program_log"] == "program1 completed"
    assert "program1" in result.data["program_catalog"]
    assert "utm_compression_start_v1" in result.data["program_catalog"]
    assert result.data["source_stage_context"]["specimen"]["specimen_id"] == "specimen-test"
    assert result.data["source_stage_context"]["vision"]["observation_id"] == "obs-test"
    assert result.data["source_stage_context"]["manipulation"]["completion_status"] == "reported_complete"
    assert ctx.prompts and "equipment.pyautogui.list_programs" in ctx.prompts[0][1]


@pytest.mark.asyncio
async def test_equipment_agent_blocks_when_selected_profile_requires_unavailable_vision_link(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_equipment_tools(
        tools,
        {
            "devices": {
                "equipment": {
                    "mode": "simulator",
                    "windows_pyautogui": {"connection_memory_path": str(tmp_path / "conn.json")},
                }
            }
        },
        repo_root=tmp_path,
    )
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={
            "equipment_profile_id": "utm_windows_v1",
            "equipment_program_id": "utm_compression_start_v1",
        },
    )

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "{}"))

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "EQUIPMENT_VISION_LINK_UNAVAILABLE"
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["equipment_profile"]["profile_id"] == "utm_windows_v1"


@pytest.mark.asyncio
async def test_equipment_agent_blocks_program_outside_explicit_profile_before_worker_execution(tmp_path: Path) -> None:
    plan = {
        "note": "invalid profile/program combination",
        "calls": [
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program1"}},
        ],
    }
    tools = _tools(tmp_path)
    run_payloads: list[dict[str, Any]] = []
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_payloads.append(dict(payload))
        or {"ok": True, "tool": "equipment.pyautogui.run", "status": "completed", "program_id": "program1"},
    )
    state = _state(experiment_spec={"equipment_profile_id": "utm_windows_v1", "equipment_program_id": "program1"})

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, json.dumps(plan)))

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "EQUIPMENT_PROFILE_PROGRAM_NOT_ALLOWED"
    assert result.data["equipment_result"]["profile_id"] == "utm_windows_v1"
    assert run_payloads == []


@pytest.mark.asyncio
async def test_equipment_agent_blocks_program_not_in_catalog(tmp_path: Path) -> None:
    plan = {
        "note": "try missing program",
        "calls": [
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program404"}},
        ],
    }
    ctx = _CtxStub(_tools(tmp_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "PYAUTOGUI_PROGRAM_NOT_FOUND"
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_test_mode_falls_back_to_safe_plan(tmp_path: Path) -> None:
    ctx = _CtxStub(_tools(tmp_path), "not-json")

    result = await LabEquipmentAgent().run(_state(active_goal="run UTM compression test", experiment_spec={}), ctx)

    assert result.success is True
    assert result.data["equipment_result"]["program_id"] == "utm_compression_start_v1"
    assert result.data["equipment_profile"]["profile_id"] == "utm_windows_v1"
    assert result.data["equipment_result"]["status"] == "verified_complete"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["tool_results"][0]["tool"] == "vision.equipment_cross_check"
    assert result.data["equipment_report"]["vision_cross_checks"]["all_required_ok"] is True
    tool_vision_results = result.data["tool_results"][0]["result"]["results"]
    assert tool_vision_results
    assert all(item["timestamp"] and item["expires_at"] and item["freshness_ttl_ms"] > 0 for item in tool_vision_results)
    assert result.data["equipment_report"]["cross_checks"]["save_export_responsibility_ok"] is True
    assert result.data["utm_data_ready"]["save_export_responsibility_ok"] is True
    assert result.data["equipment_handoff"]["save_export_responsibility_ok"] is True
    assert result.data["equipment_report"]["control_plan"]["profile"]["program_id"] == "utm_compression_start_v1"
    assert "profile_memory_path" in result.data["equipment_report"]["control_plan"]["profile"]
    assert result.data["utm_data_ready"]["schema"] == "utm_data_ready.v1"
    assert {item["check_id"] for item in result.data["equipment_report"]["vision_requests"]} == {
        "utm_pre_start",
        "utm_motion_confirm",
        "utm_test_complete",
    }
    assert result.data["utm_data_ready"]["vision_requests"][0]["agent_signal_type"] == "equipment_vision_check_request"
    assert Path(result.data["equipment_result"]["result_file"]).exists()
    assert "using safe equipment tool plan" in result.data["protocol_note"]
    assert "equipment.pyautogui.request_log" in [item["tool"] for item in result.data["tool_results"]]
    bridge_report = result.data["equipment_report"]["bridge"]
    assert bridge_report["pyautogui_available"] is True
    assert bridge_report["pyautogui_failsafe"] is True
    assert bridge_report["pyautogui_pause"] == 0.1
    assert bridge_report["pyautogui_simulated"] is True
    assert bridge_report["remote_server_version"] == "simulator"
    assert bridge_report["bridge_url_host"] == "simulator"
    assert bridge_report["client_latency_ms"] == 0.0
    assert bridge_report["artifact_root"]
    assert bridge_report["request_log_path"].endswith("bridge_requests.jsonl")
    assert bridge_report["locator_root"].endswith("simulated_locators")
    assert bridge_report["utm_export_root"].endswith("simulated_utm_exports")
    assert result.data["utm_data_ready"]["bridge_request_log_ref"].endswith("bridge_requests.jsonl")
    assert result.data["equipment_handoff"]["bridge_request_log_ref"].endswith("bridge_requests.jsonl")
    report = result.data["equipment_report"]
    assert report["control_trace"]["program_id"] == "utm_compression_start_v1"
    assert report["control_trace"]["tool_result_count"] == len(result.data["tool_results"])
    assert any(item["tool"] == "equipment.pyautogui.run" for item in report["control_trace"]["tool_sequence"])
    assert report["visual_verification"]["screen_started"] is True
    assert report["physical_verification"]["all_required_ok"] is True
    assert report["data_ledger"]["parse_ready"] is True
    assert report["data_ledger"]["save_export_responsibility_ok"] is True
    assert report["handoff_gate"]["ready_for_analysis"] is True
    assert report["safety_gate"]["guardian_status"] == "allow"
    assert result.data["utm_data_ready"]["data_ledger"]["parse_ready"] is True
    await asyncio.sleep(0)
    vision_events = [event for event in ctx.events if event.get("tool") == "vision.equipment_cross_check"]
    assert [event.get("step") for event in vision_events][:1] == ["VISION_PRECHECK_REQUEST"]
    assert "VISION_PRECHECK_DONE" in [event.get("step") for event in vision_events]
    assert {event.get("check_id") for event in vision_events if str(event.get("step", "")).startswith("VISION_CHECK:")} == {
        "utm_pre_start",
        "utm_motion_confirm",
        "utm_test_complete",
    }
    assert all(event.get("status") in {"running", "ok"} for event in vision_events)


@pytest.mark.asyncio
async def test_equipment_agent_live_gui_test_mode_uses_safe_plan_on_non_json(tmp_path: Path) -> None:
    ctx = _CtxStub(_tools(tmp_path), "not-json")
    state = _state(
        mode=Mode.LIVE,
        active_goal="테스트 모드, 가상 브릿지",
        experiment_spec={
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        },
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    assert result.data["equipment_result"]["program_id"] == "utm_compression_start_v1"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["utm_data_ready"]["status"] == "ready"
    assert result.data["hardware_alerts"] == []
    assert "using safe equipment tool plan" in result.data["protocol_note"]
    assert result.data["equipment_report"]["mode"] == "test"
    assert result.data["equipment_report"]["physical_verification"]["all_required_ok"] is True
    assert result.data["equipment_report"]["data_ledger"]["parse_ready"] is True


@pytest.mark.asyncio
async def test_equipment_agent_stops_before_run_when_health_fails() -> None:
    tools = ToolRegistry()
    tools.register(
        "equipment.pyautogui.health",
        lambda payload: {
            "ok": False,
            "tool": "equipment.pyautogui.health",
            "status": "unreachable",
            "failure_code": "PYAUTOGUI_BRIDGE_UNREACHABLE",
        },
    )
    tools.register("equipment.pyautogui.list_programs", lambda payload: {"ok": True, "programs": [{"program_id": "program1"}]})
    tools.register("equipment.pyautogui.run", lambda payload: {"ok": True, "program_id": "program1"})
    plan = {
        "note": "health first",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program1"}},
        ],
    }
    ctx = _CtxStub(tools, json.dumps(plan))

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "PYAUTOGUI_BRIDGE_UNREACHABLE"
    assert [item["tool"] for item in result.data["tool_results"]] == ["equipment.pyautogui.health"]


@pytest.mark.asyncio
async def test_equipment_agent_preserves_effect_unknown_without_retry_or_handoff(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    run_calls: list[dict[str, Any]] = []
    tools.register("equipment.pyautogui.health", lambda payload: {"ok": True, "status": "ready"})
    tools.register(
        "equipment.pyautogui.list_programs",
        lambda payload: {"ok": True, "programs": [{"program_id": "program1"}]},
    )

    def uncertain_run(payload: dict[str, Any]) -> dict[str, Any]:
        run_calls.append(dict(payload))
        return {
            "ok": False,
            "tool": "equipment.pyautogui.run",
            "status": "effect_unknown",
            "failure_code": "PYAUTOGUI_EFFECT_UNKNOWN",
            "attempted": True,
            "retryable": False,
            "message": "worker response timed out after dispatch",
        }

    tools.register("equipment.pyautogui.run", uncertain_run)
    tools.register("equipment.pyautogui.request_log", lambda payload: {"ok": True, "events": []})
    plan = {
        "note": "bounded execution",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program1"}},
        ],
    }

    result = await LabEquipmentAgent().run(_state(mode=Mode.LIVE), _CtxStub(tools, json.dumps(plan)))

    assert result.success is False
    assert len(run_calls) == 1
    assert result.data["equipment_result"]["status"] == "effect_unknown"
    assert result.data["equipment_handoff"]["status"] == "effect_unknown"
    assert result.data["equipment_runtime_execution"]["lifecycle"] == "EFFECT_UNKNOWN"
    assert result.data["equipment_runtime_projection"]["failure_code"] == "PYAUTOGUI_EFFECT_UNKNOWN"


@pytest.mark.asyncio
async def test_legacy_utm_compatibility_path_remains_explicitly_callable() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools, "legacy protocol note")

    result = await LabEquipmentAgent()._legacy_utm(_state(), ctx)

    assert result.success is True
    assert result.data["equipment_bridge"] == "utm_direct"
    assert result.data["equipment_result"]["tool"] == "utm.run_protocol"
    assert result.data["equipment_result"]["status"] == "verified_complete"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["utm_data_ready"]["schema"] == "utm_data_ready.v1"
    assert result.data["equipment_report"]["bridge"]["provider"] == "utm_direct"
    assert result.data["equipment_report"]["cross_checks"]["save_export_responsibility_ok"] is True
    assert result.data["utm_data_ready"]["save_export_responsibility_ok"] is True
    assert result.data["equipment_handoff"]["save_export_responsibility_ok"] is True
    assert Path(result.data["equipment_result"]["result_file"]).exists()


@pytest.mark.asyncio
async def test_equipment_agent_legacy_utm_includes_cited_manual_context_without_changing_tool_payload(monkeypatch) -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools, "manual-grounded protocol note")
    manual_context = {
        "schema": "manual_context.v1",
        "equipment_type": "utm",
        "purpose": "procedure",
        "context_hash": "ctx-procedure",
        "insufficient_evidence": False,
        "chunks": [
            {
                "chunk_id": "manual:procedure:p6",
                "text": "시험 순서를 확인한다.",
                "citation": {"source_id": "software", "title": "Software Manual", "page": 6, "section_path": ["시험순서"]},
            }
        ],
    }
    monkeypatch.setattr(LabEquipmentAgent, "_manual_context", staticmethod(lambda _query, *, purpose: {**manual_context, "purpose": purpose}))

    result = await LabEquipmentAgent()._legacy_utm(_state(), ctx)

    assert "manual:procedure:p6" in ctx.prompts[0][1]
    assert result.data["manual_context"]["context_hash"] == "ctx-procedure"
    assert result.data["tool_plan"][0]["payload"]["program_id"] == "utm_compression_start_v1"


@pytest.mark.asyncio
async def test_equipment_agent_legacy_utm_live_fails_closed_without_direct_backend() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools, "legacy live protocol note")

    result = await LabEquipmentAgent()._legacy_utm(_state(mode=Mode.LIVE), ctx)

    assert result.success is False
    assert result.data["equipment_bridge"] == "utm_direct"
    assert result.data["equipment_result"]["status"] == "blocked"
    assert result.data["equipment_result"]["failure_code"] == "UTM_DIRECT_BACKEND_NOT_CONFIGURED"
    assert result.data["equipment_report"]["bridge"]["provider"] == "utm_direct"
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["utm_data_ready"]["status"] == "blocked"
    assert result.data["hardware_alerts"][0]["tool"] == "utm.run_protocol"


@pytest.mark.asyncio
async def test_equipment_agent_legacy_utm_live_allows_explicit_direct_backend_with_vision(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    tools = ToolRegistry()
    register_mock_tools(tools)
    state = _state(
        mode=Mode.LIVE,
        experiment_spec={
            "utm": {
                "direct_backend_configured": True,
                "result_file": str(csv_path),
                "profile": "vendor_direct_profile",
            }
        },
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(tools, "legacy direct live protocol note")

    result = await LabEquipmentAgent()._legacy_utm(state, ctx)

    assert result.success is True
    assert result.data["equipment_bridge"] == "utm_direct"
    assert result.data["equipment_result"]["status"] == "verified_complete"
    assert result.data["equipment_result"]["profile"] == "vendor_direct_profile"
    assert result.data["equipment_result"]["result_file"] == str(csv_path)
    assert result.data["equipment_report"]["bridge"]["provider"] == "utm_direct"
    assert result.data["equipment_report"]["bridge"]["connection_status"] == "ready"
    assert result.data["equipment_report"]["bridge"]["pyautogui_available"] is False
    assert result.data["equipment_report"]["vision_cross_checks"]["all_required_ok"] is True
    assert result.data["equipment_report"]["cross_checks"]["save_export_responsibility_ok"] is True
    assert result.data["utm_data_ready"]["save_export_responsibility_ok"] is True
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["equipment_handoff"]["save_export_responsibility_ok"] is True
    assert result.data["hardware_alerts"] == []


def _write_live_utm_csv(tmp_path: Path) -> Path:
    path = tmp_path / "live_utm.csv"
    path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,2.5\n", encoding="utf-8")
    return path


def _fresh_vision_checks(*, ttl_minutes: int = 5) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
    return [
        {"check_id": "utm_pre_start", "ok": True, "confidence": 0.91, "run_id": "run-test", "specimen_id": "specimen-test", "timestamp": now.isoformat(), "expires_at": expires_at, "freshness_ttl_ms": ttl_minutes * 60_000, "evidence": {"frame_ids": ["frame-pre"]}},
        {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.88, "run_id": "run-test", "specimen_id": "specimen-test", "timestamp": now.isoformat(), "expires_at": expires_at, "freshness_ttl_ms": ttl_minutes * 60_000, "evidence": {"frame_ids": ["frame-motion"]}},
        {"check_id": "utm_test_complete", "ok": True, "confidence": 0.86, "run_id": "run-test", "specimen_id": "specimen-test", "timestamp": now.isoformat(), "expires_at": expires_at, "freshness_ttl_ms": ttl_minutes * 60_000, "evidence": {"frame_ids": ["frame-done"]}},
    ]


def test_unrelated_agent_signals_do_not_satisfy_equipment_vision_preflight() -> None:
    assert LabEquipmentAgent._has_equipment_vision_results(
        {
            "vision": {
                "agent_signals": [
                    {"signal": "printer_door_closed", "value": True},
                    {"signal": "camera_online", "value": True},
                ]
            }
        }
    ) is False


def _live_tools_with_verified_utm(
    csv_path: Path,
    *,
    screen_evidence_complete: bool = True,
    data_status: str = "pulled_to_linux",
    save_method: str = "windows_export_watch",
    save_attempted_by_agent: bool = True,
    save_confirmation_screen_ok: bool = True,
    windows_path: str = "C:/ATR/utm_exports/run-test/specimen-test.csv",
    request_log_events: list[dict[str, Any]] | None = None,
    include_run_request_log_context: bool = True,
    request_log_summary_only: bool = False,
    response_step_trace: list[dict[str, Any]] | None = None,
) -> ToolRegistry:
    tools = ToolRegistry()
    if request_log_events is None:
        request_log_events = [
            {"path": "/health", "auth_ok": True},
            {"path": "/programs", "auth_ok": True},
            {
                "path": "/execute",
                "auth_ok": True,
                "audit_kind": "execute_payload",
                "sequence_id": "seq-live-utm",
                "run_id": "run-test",
                "specimen_id": "specimen-test",
                "program_id": "utm_compression_start_v1",
                "payload_sha256": "pytest-payload",
            },
            {"path": "/request-log", "auth_ok": True},
        ]
    tools.register("equipment.pyautogui.health", lambda payload: {"ok": True, "tool": "equipment.pyautogui.health", "status": "ready"})
    tools.register(
        "equipment.pyautogui.list_programs",
        lambda payload: {"ok": True, "programs": [{"program_id": "utm_compression_start_v1", "program_type": "utm_protocol"}]},
    )
    screen_checks = [
        {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "screen-before"},
        {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"},
        {"checkpoint": "after_complete", "ok": True, "state": "complete", "screenshot_artifact": "screen-complete"},
    ]
    if not screen_evidence_complete:
        screen_checks = [{"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"}]
    screen_artifacts = [
        {"kind": "screen_png", "artifact_id": item["screenshot_artifact"], "local_path": f"artifacts/equipment/run-test/screens/{item['screenshot_artifact']}.png"}
        for item in screen_checks
    ]
    def _run_result(payload):
        result = {
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "program_id": "utm_compression_start_v1",
            "sequence_id": "seq-live-utm",
            "result_file": str(csv_path),
            "utm_csv_path": str(csv_path),
            "screen_checks": screen_checks,
            "output_artifacts": [*screen_artifacts, {"kind": "utm_csv", "artifact_id": "utm-csv-live", "local_path": str(csv_path), "row_count_probe": 2}],
            "physical_checks": {"vision_motion_confirmed": True, "specimen_alignment_ok": True, "fixture_safe_to_access": True},
            "data_acquisition": {
                "status": data_status,
                "save_method": save_method,
                "save_attempted_by_agent": save_attempted_by_agent,
                "save_confirmation_screen_ok": save_confirmation_screen_ok,
                "windows_path": windows_path,
                "linux_path": str(csv_path),
            },
            "control_profile": {
                "program_id": "utm_compression_start_v1",
                "profile_memory_path": "memory/equipment_utm_profile.json",
                "profile_memory_applied": True,
                "export_glob": "*.csv",
                "locator_count": 4,
            },
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": True,
                "save_completed": True,
                "data_file_created": True,
                "data_parse_probe_ok": True,
            },
        }
        if response_step_trace is not None:
            result.update({"mode": "live", "bridge_host": "192.168.50.58", "step_trace": response_step_trace})
        if include_run_request_log_context:
            result.update(
                {
                    "bridge_request_log_ref": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
                    "request_log_event_count": len(request_log_events),
                    "request_log_recent_paths": [str(item.get("path") or "") for item in request_log_events],
                }
            )
        return result

    tools.register("equipment.pyautogui.run", _run_result)
    def _request_log_result(payload):
        execute_events = [item for item in request_log_events if str(item.get("path") or "") == "/execute"]
        payload_events = [item for item in execute_events if str(item.get("audit_kind") or "") == "execute_payload"] or execute_events
        def _unique(key: str) -> list[str]:
            values: list[str] = []
            for item in payload_events:
                value = str(item.get(key) or "").strip()
                if value and value not in values:
                    values.append(value)
            return values
        result = {
            "ok": True,
            "tool": "equipment.pyautogui.request_log",
            "status": "ready",
            "request_log": "C:/ATR/bridge_artifacts/bridge_requests.jsonl",
            "event_count": len(request_log_events),
            "recent_paths": [str(item.get("path") or "") for item in request_log_events],
            "execute_event_seen": bool(execute_events),
            "execute_event_count": len(execute_events),
            "execute_payload_event_count": sum(1 for item in execute_events if str(item.get("audit_kind") or "") == "execute_payload"),
            "execute_run_ids": _unique("run_id"),
            "execute_sequence_ids": _unique("sequence_id"),
            "execute_specimen_ids": _unique("specimen_id"),
            "execute_program_ids": _unique("program_id"),
            "last_execute_context": dict(payload_events[-1]) if payload_events else {},
            "last_execute_at": "2026-05-30T00:00:00Z" if execute_events else "",
        }
        if not request_log_summary_only:
            result["events"] = request_log_events
        return result

    tools.register("equipment.pyautogui.request_log", _request_log_result)
    return tools


@pytest.mark.asyncio
async def test_live_equipment_skill_reuses_preflight_vision_evidence_for_completion(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    tools = _live_tools_with_verified_utm(
        csv_path,
        request_log_events=[
            {"path": "/health", "auth_ok": True},
            {
                "path": "/execute",
                "auth_ok": True,
                "audit_kind": "execute_payload",
                "sequence_id": "run-test-utm_skill-1.0.0",
                "run_id": "run-test",
                "specimen_id": "specimen-test",
                "program_id": "utm_compression_start_v1",
            },
            {"path": "/request-log", "auth_ok": True},
        ],
    )
    tools.register(
        "vision.equipment_cross_check",
        lambda payload: {
            "ok": True,
            "tool": "vision.equipment_cross_check",
            "runtime_mode": "live",
            "results": _fresh_vision_checks(),
            "failure_code": None,
        },
    )
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="utm_skill",
        version="1.0.0",
        target_profile="utm_windows_v1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
    )
    package = registry.compile("utm_skill", "1.0.0")
    registry.validate("utm_skill", "1.0.0")
    registry.mark_deployed(
        "utm_skill",
        "1.0.0",
        bridge_id="worker-1",
        deployment_sha256=canonical_sha256(package["programs"]),
    )
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression Skill",
        experiment_spec={
            "equipment_skill": {
                "skill_id": "utm_skill",
                "version": "1.0.0",
                "target_profile": "utm_windows_v1",
                "registry_root": str(tmp_path / "skills"),
            }
        },
    )

    result = await LabEquipmentAgent().run(state, _CtxStub(tools, "must not be used"))

    assert result.success is True
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["equipment_report"]["vision_cross_checks"]["all_required_ok"] is True


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_without_vision_cross_checks(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    tools = _live_tools_with_verified_utm(csv_path)
    tools.register(
        "vision.equipment_cross_check",
        lambda payload: {
            "ok": False,
            "tool": "vision.equipment_cross_check",
            "runtime_mode": "live",
            "results": [],
            "failure_code": "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED",
        },
    )
    ctx = _CtxStub(tools, json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_REQUIRED"
    assert result.data["equipment_report"]["vision_cross_checks"]["all_required_ok"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["hardware_alerts"][0]["device_class"] == "vision"
    assert result.data["hardware_alerts"][0]["component"] == "utm_physical_cross_check"
    assert result.data["hardware_alerts"][0]["guardian_decision"]["schema"] == "guardian_decision.v1"
    assert result.data["incident_records"][0]["failure_code"] == "VISION_UTM_PRE_START_REQUIRED"


@pytest.mark.asyncio
async def test_equipment_agent_live_allows_verified_utm_with_vision_cross_checks(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    assert result.data["equipment_result"]["status"] == "verified_complete"
    assert result.data["equipment_report"]["vision_cross_checks"]["all_required_ok"] is True
    assert result.data["equipment_report"]["physical_checks"]["evidence_frame_ids"] == ["frame-done", "frame-motion", "frame-pre"]
    assert result.data["equipment_report"]["control_plan"]["profile"]["profile_memory_applied"] is True
    assert result.data["equipment_report"]["live_evidence_audit"]["screen_evidence"]["ok"] is True
    assert result.data["equipment_report"]["live_evidence_audit"]["linux_artifact_pull"]["ok"] is True
    assert result.data["equipment_report"]["live_evidence_audit"]["save_export"]["ok"] is True
    assert result.data["equipment_report"]["cross_checks"]["save_export_responsibility_ok"] is True
    assert result.data["equipment_report"]["live_evidence_audit"]["request_audit_log"]["ok"] is True
    assert result.data["equipment_report"]["live_evidence_audit"]["request_audit_log"]["execute_event_seen"] is True
    assert result.data["equipment_report"]["cross_checks"]["screen_evidence_complete"] is True
    assert result.data["equipment_report"]["cross_checks"]["request_audit_log_available"] is True
    assert result.data["equipment_handoff"]["bridge_request_log_ref"].endswith("bridge_requests.jsonl")
    report = result.data["equipment_report"]
    assert report["visual_verification"]["screen_evidence_complete"] is True
    assert report["physical_verification"]["evidence_frame_ids"] == ["frame-done", "frame-motion", "frame-pre"]
    assert report["data_ledger"]["recognized_save_method"] is True
    assert report["handoff_gate"]["handoff_status"] == "ready_for_analysis"
    assert report["safety_gate"]["blocks_workflow"] is False
    assert result.data["hardware_alerts"] == []
    assert result.data["incident_records"] == []


@pytest.mark.asyncio
async def test_equipment_agent_replays_live_bridge_step_trace_events_to_gui(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    response_trace = [
        {"step": "SCREEN_ASSERT_RUNNING", "status": "ok", "detail": "running_state"},
        {"step": "SAVE_EXPORT", "status": "ok", "detail": str(csv_path)},
        {"step": "PULL_ARTIFACT", "status": "ok", "detail": str(csv_path)},
        {"step": "PARSE_PROBE", "status": "ok", "detail": "rows=2"},
        {"step": "DONE", "status": "ok", "detail": "UTM protocol verified complete"},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, response_step_trace=response_trace), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)
    await asyncio.sleep(0)

    assert result.success is True
    replayed = [event for event in ctx.events if event.get("source") == "bridge_response_trace"]
    assert [event.get("step") for event in replayed] == [item["step"] for item in response_trace]
    assert {event.get("tool") for event in replayed} == {"equipment.pyautogui.run"}
    assert {event.get("program_id") for event in replayed} == {"utm_compression_start_v1"}
    assert {event.get("bridge_host") for event in replayed} == {"192.168.50.58"}
    assert all(event.get("run_id") == "run-test" for event in replayed)
    assert all(event.get("experiment_id") == "exp-test" for event in replayed)
    assert next(event for event in replayed if event.get("step") == "SAVE_EXPORT")["data_file_ref"] == str(csv_path)


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_expired_explicit_vision_cross_check(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    expired = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["equipment_vision_check_results"] = [
        {"check_id": "utm_pre_start", "ok": True, "confidence": 0.95, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": expired, "evidence": {"frame_ids": ["frame-pre-old"]}},
        {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.9, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-motion"]}},
        {"check_id": "utm_test_complete", "ok": True, "confidence": 0.88, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-done"]}},
    ]
    tools = _live_tools_with_verified_utm(csv_path)
    run_calls: list[dict[str, Any]] = []
    original_run = tools._tools["equipment.pyautogui.run"]
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: run_calls.append(dict(payload)) or original_run(payload),
    )
    ctx = _CtxStub(tools, json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_STALE"
    check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_pre_start"]
    assert check["ok"] is False
    assert check["stale"] is True
    assert check["fresh"] is False
    assert result.data["equipment_report"]["physical_verification"]["blocking_reasons"] == ["VISION_UTM_PRE_START_STALE"]
    assert result.data["hardware_alerts"][0]["device_class"] == "vision"
    assert result.data["incident_records"][0]["failure_code"] == "VISION_UTM_PRE_START_STALE"
    assert run_calls == []


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_explicit_vision_cross_check_without_freshness_bound(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["equipment_vision_check_results"] = [
        {"check_id": "utm_pre_start", "ok": True, "confidence": 0.95, "run_id": "run-test", "specimen_id": "specimen-test", "evidence": {"frame_ids": ["frame-pre-no-ttl"]}},
        {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.9, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-motion"]}},
        {"check_id": "utm_test_complete", "ok": True, "confidence": 0.88, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-done"]}},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_FRESHNESS_REQUIRED"
    check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_pre_start"]
    assert check["ok"] is False
    assert check["freshness_missing"] is True
    assert check["fresh"] is False
    assert result.data["equipment_report"]["physical_verification"]["blocking_reasons"] == ["VISION_UTM_PRE_START_FRESHNESS_REQUIRED"]
    assert result.data["hardware_alerts"][0]["device_class"] == "vision"
    assert result.data["incident_records"][0]["failure_code"] == "VISION_UTM_PRE_START_FRESHNESS_REQUIRED"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_explicit_vision_cross_check_without_identity(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["equipment_vision_check_results"] = [
        {"check_id": "utm_pre_start", "ok": True, "confidence": 0.95, "expires_at": future, "evidence": {"frame_ids": ["frame-pre-no-id"]}},
        {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.9, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-motion"]}},
        {"check_id": "utm_test_complete", "ok": True, "confidence": 0.88, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-done"]}},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_IDENTITY_REQUIRED"
    check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_pre_start"]
    assert check["identity_missing"] is True
    assert check["identity"]["missing_fields"] == ["run_id", "specimen_id"]
    assert result.data["equipment_report"]["physical_verification"]["blocking_reasons"] == ["VISION_UTM_PRE_START_IDENTITY_REQUIRED"]


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_explicit_vision_cross_check_identity_mismatch(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["equipment_vision_check_results"] = [
        {"check_id": "utm_pre_start", "ok": True, "confidence": 0.95, "run_id": "other-run", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-pre-other-run"]}},
        {"check_id": "utm_motion_confirm", "ok": True, "confidence": 0.9, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-motion"]}},
        {"check_id": "utm_test_complete", "ok": True, "confidence": 0.88, "run_id": "run-test", "specimen_id": "specimen-test", "expires_at": future, "evidence": {"frame_ids": ["frame-done"]}},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_IDENTITY_MISMATCH"
    check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_pre_start"]
    assert check["identity_mismatch"] is True
    assert check["identity"]["mismatched_fields"] == ["run_id"]
    assert check["identity"]["observed"]["run_id"] == "other-run"
    assert result.data["hardware_alerts"][0]["component"] == "utm_physical_cross_check"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_expired_vision_signal_board(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    expired = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["vision_report"] = {
        "signal_board": [
            {"signal": "specimen_on_utm_platen", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.95, "expires_at": future},
            {"signal": "fixture_alignment_ok", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.93, "expires_at": future},
            {"signal": "utm_motion_observed", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.9, "expires_at": expired},
            {"signal": "utm_home_restored", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.91, "expires_at": future},
        ]
    }
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_MOTION_CONFIRM_STALE"
    motion_check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_motion_confirm"]
    assert motion_check["ok"] is False
    assert motion_check["stale"] is True
    assert motion_check["stale_signals"] == ["utm_motion_observed"]
    assert result.data["equipment_report"]["cross_checks"]["physical_motion_started"] is False
    assert result.data["hardware_alerts"][0]["guardian_route_hint"] == "recover"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_vision_signal_board_without_freshness_bound(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["vision_report"] = {
        "signal_board": [
            {"signal": "specimen_on_utm_platen", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.95, "expires_at": future},
            {"signal": "fixture_alignment_ok", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.93, "expires_at": future},
            {"signal": "utm_motion_observed", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.9},
            {"signal": "utm_home_restored", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.91, "expires_at": future},
        ]
    }
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_MOTION_CONFIRM_FRESHNESS_REQUIRED"
    motion_check = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_motion_confirm"]
    assert motion_check["ok"] is False
    assert motion_check["freshness_missing"] is True
    assert motion_check["freshness_missing_signals"] == ["utm_motion_observed"]
    assert result.data["equipment_report"]["physical_verification"]["blocking_reasons"] == ["VISION_UTM_MOTION_CONFIRM_FRESHNESS_REQUIRED"]


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_vision_signal_board_identity_mismatch(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    state.latest_observations["vision_report"] = {
        "signal_board": [
            {"signal": "specimen_on_utm_platen", "run_id": "other-run", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.95, "expires_at": future},
            {"signal": "fixture_alignment_ok", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.93, "expires_at": future},
            {"signal": "utm_motion_observed", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.9, "expires_at": future},
            {"signal": "utm_home_restored", "run_id": "run-test", "specimen_id": "specimen-test", "value": True, "status": "ok", "confidence": 0.91, "expires_at": future},
        ]
    }
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "VISION_UTM_PRE_START_IDENTITY_MISMATCH"
    pre_start = result.data["equipment_report"]["vision_cross_checks"]["checks"]["utm_pre_start"]
    assert pre_start["identity_mismatch"] is True
    assert pre_start["identity_mismatched_signals"] == ["specimen_on_utm_platen"]


@pytest.mark.asyncio
async def test_equipment_agent_live_accepts_summary_only_request_log_execute_gate(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(
        _live_tools_with_verified_utm(
            csv_path,
            include_run_request_log_context=False,
            request_log_summary_only=True,
        ),
        json.dumps(plan),
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    audit = result.data["equipment_report"]["live_evidence_audit"]["request_audit_log"]
    assert audit["ok"] is True
    assert audit["execute_event_seen"] is True
    assert audit["execute_event_count"] == 1
    assert audit["last_execute_at"] == "2026-05-30T00:00:00Z"
    assert audit["execute_identity_match"] is True
    assert result.data["equipment_report"]["bridge"]["request_log_execute_seen"] is True
    assert result.data["equipment_report"]["bridge"]["request_log_execute_identity_match"] is True
    assert result.data["utm_data_ready"]["bridge_request_log_execute_event_seen"] is True
    assert result.data["utm_data_ready"]["bridge_request_log_execute_identity_match"] is True
    assert result.data["equipment_handoff"]["bridge_request_log_execute_event_seen"] is True
    assert result.data["equipment_handoff"]["bridge_request_log_execute_identity_match"] is True


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_request_log_execute_identity_mismatch(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    request_log_events = [
        {"path": "/health", "auth_ok": True},
        {
            "path": "/execute",
            "auth_ok": True,
            "audit_kind": "execute_payload",
            "sequence_id": "seq-live-utm",
            "run_id": "other-run",
            "specimen_id": "specimen-test",
            "program_id": "utm_compression_start_v1",
            "payload_sha256": "pytest-mismatch",
        },
        {"path": "/request-log", "auth_ok": True},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, request_log_events=request_log_events), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED"
    audit = result.data["equipment_report"]["live_evidence_audit"]["request_audit_log"]
    assert audit["execute_event_seen"] is True
    assert audit["execute_identity_present"] is True
    assert audit["execute_identity_match"] is False
    assert audit["execute_identity_detail"]["expected"]["run_id"] == "run-test"
    assert audit["execute_identity_detail"]["observed"]["run_ids"] == ["other-run"]
    assert result.data["equipment_report"]["cross_checks"]["request_audit_execute_identity_match"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_request_log_execute_sequence_mismatch(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    request_log_events = [
        {"path": "/health", "auth_ok": True},
        {
            "path": "/execute",
            "auth_ok": True,
            "audit_kind": "execute_payload",
            "sequence_id": "other-seq-live-utm",
            "run_id": "run-test",
            "specimen_id": "specimen-test",
            "program_id": "utm_compression_start_v1",
            "payload_sha256": "pytest-sequence-mismatch",
        },
        {"path": "/request-log", "auth_ok": True},
    ]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, request_log_events=request_log_events), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED"
    audit = result.data["equipment_report"]["live_evidence_audit"]["request_audit_log"]
    assert audit["execute_identity_present"] is True
    assert audit["execute_identity_match"] is False
    assert audit["execute_identity_detail"]["expected"]["sequence_id"] == "seq-live-utm"
    assert audit["execute_identity_detail"]["observed"]["sequence_ids"] == ["other-seq-live-utm"]
    assert result.data["equipment_report"]["cross_checks"]["request_audit_execute_identity_match"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_without_complete_screen_evidence(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, screen_evidence_complete=False), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_SCREEN_EVIDENCE_INCOMPLETE"
    audit = result.data["equipment_report"]["live_evidence_audit"]
    assert audit["required_for_handoff"] is True
    assert audit["screen_evidence"]["ok"] is False
    assert audit["screen_evidence"]["missing_checkpoints"] == ["before_start", "after_complete"]
    assert result.data["equipment_report"]["cross_checks"]["screen_evidence_complete"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_windows_export_before_linux_pull(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, data_status="exported_on_windows"), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_LINUX_ARTIFACT_PULL_REQUIRED"
    audit = result.data["equipment_report"]["live_evidence_audit"]
    assert audit["linux_artifact_pull"]["ok"] is False
    assert audit["linux_artifact_pull"]["status"] == "exported_on_windows"
    assert result.data["equipment_report"]["cross_checks"]["linux_artifact_pulled"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_without_save_export_responsibility_evidence(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(
        _live_tools_with_verified_utm(
            csv_path,
            save_method="unknown",
            save_attempted_by_agent=False,
            save_confirmation_screen_ok=False,
            windows_path="",
        ),
        json.dumps(plan),
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED"
    audit = result.data["equipment_report"]["live_evidence_audit"]
    assert audit["save_export"]["ok"] is False
    assert audit["save_export"]["save_method"] == "unknown"
    assert audit["save_export"]["recognized_save_method"] is False
    assert result.data["equipment_report"]["cross_checks"]["save_export_responsibility_ok"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_equipment_agent_live_blocks_without_execute_request_audit_event(tmp_path: Path) -> None:
    csv_path = _write_live_utm_csv(tmp_path)
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    request_log_events = [{"path": "/health", "auth_ok": True}, {"path": "/programs", "auth_ok": True}]
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path, request_log_events=request_log_events), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED"
    audit = result.data["equipment_report"]["live_evidence_audit"]
    assert audit["request_audit_log"]["ok"] is False
    assert audit["request_audit_log"]["event_count"] == 2
    assert audit["request_audit_log"]["execute_event_seen"] is False
    assert result.data["equipment_report"]["cross_checks"]["request_audit_log_available"] is False
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["hardware_alerts"][0]["component"] == "windows_pyautogui_request_audit"



def _live_tools_with_blocked_utm_screen_evidence() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register("equipment.pyautogui.health", lambda payload: {"ok": True, "tool": "equipment.pyautogui.health", "status": "ready"})
    tools.register(
        "equipment.pyautogui.list_programs",
        lambda payload: {"ok": True, "programs": [{"program_id": "utm_compression_start_v1", "program_type": "utm_protocol"}]},
    )
    tools.register(
        "equipment.pyautogui.run",
        lambda payload: {
            "ok": False,
            "tool": "equipment.pyautogui.run",
            "status": "blocked",
            "program_id": "utm_compression_start_v1",
            "sequence_id": "seq-live-blocked",
            "failure_code": "UTM_EXPORT_FILE_MISSING",
            "message": "Export file missing after manual save fallback.",
            "screen_checks": [
                {"checkpoint": "before_start", "ok": True, "state": "ready", "screenshot_artifact": "screen-before"},
                {"checkpoint": "after_start", "ok": True, "state": "running", "screenshot_artifact": "screen-running"},
                {"checkpoint": "failure", "ok": False, "state": "blocked", "screenshot_artifact": "screen-failure"},
            ],
            "output_artifacts": [
                {"kind": "screen_png", "artifact_id": "screen-before", "local_path": "artifacts/equipment/run-test/screens/before.png"},
                {"kind": "screen_png", "artifact_id": "screen-running", "local_path": "artifacts/equipment/run-test/screens/running.png"},
                {"kind": "screen_png", "artifact_id": "screen-failure", "local_path": "artifacts/equipment/run-test/screens/failure.png"},
            ],
            "step_trace": [
                {"step": "SEQ_5_WAIT_UNTIL", "status": "ok", "detail": "running_state"},
                {"step": "AUTO_SAVE_MISSING", "status": "warning", "detail": "UTM_EXPORT_FILE_MISSING"},
                {"step": "MANUAL_SAVE_EXPORT", "status": "ok", "detail": "C:/ATR/utm_exports/run-test/specimen.csv"},
                {"step": "SAVE_EXPORT", "status": "blocked", "detail": "UTM_EXPORT_FILE_MISSING"},
            ],
            "data_acquisition": {
                "status": "missing",
                "save_method": "manual_save_dialog",
                "save_attempted_by_agent": True,
                "save_confirmation_screen_ok": False,
                "windows_path": "",
            },
            "cross_checks": {
                "screen_started": True,
                "physical_motion_started": False,
                "save_completed": False,
                "data_file_created": False,
                "data_parse_probe_ok": False,
            },
        },
    )
    return tools


@pytest.mark.asyncio
async def test_equipment_agent_propagates_failure_screen_evidence_to_guardian() -> None:
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(_live_tools_with_blocked_utm_screen_evidence(), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_result"]["failure_code"] == "UTM_EXPORT_FILE_MISSING"
    report = result.data["equipment_report"]
    assert report["screen_evidence_refs"] == [
        "artifacts/equipment/run-test/screens/before.png",
        "artifacts/equipment/run-test/screens/running.png",
        "artifacts/equipment/run-test/screens/failure.png",
    ]
    assert report["failure_retry_table"]
    assert any(item["fallback_macro"] == "utm_manual_save_csv_v1" for item in report["failure_retry_table"])
    assert report["recovery"]["operator_intervention_required"] is True
    assert "artifacts/equipment/run-test/screens/failure.png" in result.data["utm_data_ready"]["evidence_refs"]
    alert = result.data["hardware_alerts"][0]
    assert "artifacts/equipment/run-test/screens/failure.png" in alert["guardian_contract"]["artifact_refs"]
    assert "artifacts/equipment/run-test/screens/failure.png" in result.data["incident_records"][0]["artifact_refs"]
    assert result.data["equipment_handoff"]["screen_evidence_refs"] == report["screen_evidence_refs"]
    assert report["handoff_gate"]["ready_for_analysis"] is False
    assert report["safety_gate"]["guardian_status"] == "block"
    assert report["safety_gate"]["hardware_alert_count"] == 1
    assert report["data_ledger"]["save_export_responsibility_ok"] is False
    assert result.data["utm_data_ready"]["safety_gate"]["blocks_workflow"] is True


@pytest.mark.asyncio
async def test_equipment_agent_blocks_live_handoff_when_utm_csv_has_no_force_signal(tmp_path: Path) -> None:
    csv_path = tmp_path / "zero_force_live_utm.csv"
    csv_path.write_text("time_s,displacement_mm,force_N\n0,0.0,0.0\n1,0.1,0.0\n2,0.2,0.0\n", encoding="utf-8")
    plan = {
        "note": "run live UTM",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "utm_compression_start_v1"}},
        ],
    }
    state = _state(
        mode=Mode.LIVE,
        active_goal="run UTM compression test",
        experiment_spec={"equipment_program_id": "utm_compression_start_v1"},
    )
    state.latest_observations["equipment_vision_check_results"] = _fresh_vision_checks()
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is False
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["equipment_report"]["cross_checks"]["data_parse_probe_ok"] is False
    assert "UTM_DATA_NO_FORCE_SIGNAL" in result.data["equipment_report"]["handoff_gate"]["blocking_reasons"]
    assert result.data["equipment_report"]["data_ledger"]["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
    assert result.data["equipment_report"]["data_ledger"]["data_quality"]["force_nonzero"] is False
    alert = result.data["hardware_alerts"][0]
    assert alert["component"] == "utm_data_export"
    assert alert["device"] == "utm_export_file"
    assert alert["risk_vector"]["data_integrity"] == 0.9
    assert result.data["utm_data_ready"]["status"] == "blocked"


def test_replay_pyautogui_step_trace_enriches_live_visual_and_data_events() -> None:
    emitted: list[dict[str, Any]] = []
    result = {
        "mode": "live",
        "sequence_id": "seq-live-utm",
        "program_id": "utm_compression_start_v1",
        "bridge_host": "192.168.50.58",
        "bridge_url": "http://192.168.50.58:8765",
        "target_window": "UTM Controller",
        "failure_code": None,
        "step_trace": [
            {"step": "SCREEN_ASSERT_RUNNING", "status": "ok", "detail": "running_state"},
            {"step": "PULL_ARTIFACT", "status": "ok", "detail": "/tmp/utm/specimen.csv"},
            {"step": "PARSE_PROBE", "status": "ok", "detail": "rows=80"},
        ],
        "screen_checks": [
            {"checkpoint": "after_start", "ok": True, "state": "running", "confidence": 0.91, "screenshot_artifact": "screen-running"},
        ],
        "output_artifacts": [
            {
                "kind": "screen_png",
                "artifact_id": "screen-running",
                "local_path": "/tmp/screens/running.png",
                "windows_path": "C:/ATR/bridge_artifacts/running.png",
            },
            {
                "kind": "utm_csv",
                "artifact_id": "utm-csv-live",
                "local_path": "/tmp/utm/specimen.csv",
                "windows_path": "C:/ATR/utm_exports/specimen.csv",
            },
        ],
        "data_acquisition": {
            "status": "pulled_to_linux",
            "windows_path": "C:/ATR/utm_exports/specimen.csv",
            "linux_path": "/tmp/utm/specimen.csv",
            "local_path": "/tmp/utm/specimen.csv",
            "sha256": "abc123",
            "size_bytes": 2048,
            "row_count_probe": 80,
            "columns_probe": ["time_s", "displacement_mm", "force_N"],
            "save_method": "manual_save_dialog",
            "artifact_pull_status": "pulled_parse_ok",
            "artifact_id": "utm-csv-live",
        },
    }

    LabEquipmentAgent._replay_pyautogui_step_trace(
        result=result,
        payload={"sequence_id": "seq-live-utm", "program_id": "utm_compression_start_v1"},
        emit_tool_event=emitted.append,
    )

    assert len(emitted) == 3
    visual = emitted[0]
    assert visual["tool"] == "equipment.pyautogui.run"
    assert visual["source"] == "bridge_response_trace"
    assert visual["target_window"] == "UTM Controller"
    assert visual["target_ui"] == "UTM Controller"
    assert visual["checkpoint"] == "after_start"
    assert visual["state"] == "running"
    assert visual["confidence"] == 0.91
    assert visual["screenshot_artifact"] == "screen-running"
    assert visual["artifact_id"] == "screen-running"
    assert visual["local_path"] == "/tmp/screens/running.png"

    pull = emitted[1]
    assert pull["data_file_ref"] == "/tmp/utm/specimen.csv"
    assert pull["windows_path"] == "C:/ATR/utm_exports/specimen.csv"
    assert pull["linux_path"] == "/tmp/utm/specimen.csv"
    assert pull["sha256"] == "abc123"
    assert pull["row_count_probe"] == 80
    assert pull["columns_probe"] == ["time_s", "displacement_mm", "force_N"]
    assert pull["save_method"] == "manual_save_dialog"
    assert pull["artifact_pull_status"] == "pulled_parse_ok"

    parse = emitted[2]
    assert parse["artifact_id"] == "utm-csv-live"
    assert parse["row_count_probe"] == 80
    assert parse["sha256"] == "abc123"
