"""Unit tests for LabEquipmentAgent Windows PyAutoGUI path."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.equipment_agent import LabEquipmentAgent
from backends.llm_backend import LLMResponse
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.equipment_skill_runtime import EquipmentSkillRegistry, canonical_sha256


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
async def test_equipment_skill_executes_segments_without_llm_call(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
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
    ctx = _CtxStub(tools, "must not be used")
    state = _state(
        experiment_spec={
            "equipment_skill": {
                "skill_id": "program1_skill",
                "version": "1.0.0",
                "target_profile": "local_program1",
                "registry_root": str(tmp_path / "skills"),
            }
        }
    )

    result = await LabEquipmentAgent().run(state, ctx)

    assert result.success is True
    assert result.data["equipment_skill_execution"]["state"] == "COMPLETED"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_equipment_skill_uses_one_exact_model_recovery_then_resumes(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    registry = EquipmentSkillRegistry(tmp_path / "skills")
    registry.create_draft(
        recording=_saved_recording(),
        skill_id="program1_skill",
        version="1.0.0",
        target_profile="local_program1",
        model_snapshot={"provider": "vllm", "model": "gemma4:e4b-it-nvfp4"},
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
                "target_profile": "local_program1",
                "registry_root": str(tmp_path / "skills"),
                "auto_recover": True,
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
    assert ctx.prompts == []
    assert result.data["equipment_skill_execution"]["state"] == "COMPLETED"
    assert result.data["equipment_skill_execution"]["recovery_history"][0]["operation"] == "focus_window"


@pytest.mark.asyncio
async def test_equipment_agent_executes_llm_selected_program(tmp_path: Path) -> None:
    plan = {
        "note": "use registered program1",
        "calls": [
            {"tool": "equipment.pyautogui.health", "payload": {}},
            {"tool": "equipment.pyautogui.list_programs", "payload": {}},
            {"tool": "equipment.pyautogui.run", "payload": {"program_id": "program1"}},
        ],
    }
    ctx = _CtxStub(_tools(tmp_path), json.dumps(plan))

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is False
    assert result.data["equipment_bridge"] == "windows_pyautogui"
    assert result.data["equipment_result"]["program_id"] == "program1"
    assert result.data["equipment_result"]["failure_code"] == "UTM_PROTOCOL_REQUIRED"
    assert result.data["protocol_note"] == "use registered program1"
    assert result.data["equipment_handoff"]["status"] == "blocked"
    assert result.data["equipment_handoff"]["program_id"] == "program1"
    assert result.data["equipment_report"]["decision"]["handoff_status"] == "blocked"
    assert result.data["hardware_alerts"][0]["schema"] == "hardware_alert.v1"
    assert result.data["hardware_alerts"][0]["failure_code"] == "UTM_PROTOCOL_REQUIRED"
    assert result.data["hardware_alerts"][0]["blocks_workflow"] is True
    assert result.data["incident_records"][0]["schema"] == "incident_record.v1"
    raw_run = next(item["result"] for item in result.data["tool_results"] if item["tool"] == "equipment.pyautogui.run")
    assert raw_run["program_log"] == "program1 completed"
    assert "program1" in result.data["program_catalog"]
    assert "utm_compression_start_v1" in result.data["program_catalog"]
    assert result.data["source_stage_context"]["specimen"]["specimen_id"] == "specimen-test"
    assert result.data["source_stage_context"]["vision"]["observation_id"] == "obs-test"
    assert result.data["source_stage_context"]["manipulation"]["completion_status"] == "reported_complete"
    assert ctx.prompts and "equipment.pyautogui.list_programs" in ctx.prompts[0][1]


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
async def test_equipment_agent_legacy_utm_when_pyautogui_tools_missing() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools, "legacy protocol note")

    result = await LabEquipmentAgent().run(_state(), ctx)

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
async def test_equipment_agent_legacy_utm_live_fails_closed_without_direct_backend() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    ctx = _CtxStub(tools, "legacy live protocol note")

    result = await LabEquipmentAgent().run(_state(mode=Mode.LIVE), ctx)

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

    result = await LabEquipmentAgent().run(state, ctx)

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
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

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
    ctx = _CtxStub(_live_tools_with_verified_utm(csv_path), json.dumps(plan))

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
