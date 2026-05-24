"""Unit tests for LabEquipmentAgent Windows PyAutoGUI path."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.equipment_agent import LabEquipmentAgent
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


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


def _state(*, mode: Mode = Mode.TEST) -> OrchestratorState:
    return OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=mode,
        stage=Stage.EQUIPMENT,
        active_goal="program1 실행",
        current_experiment_spec={"equipment_program_id": "program1"},
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

    assert result.success is True
    assert result.data["equipment_bridge"] == "windows_pyautogui"
    assert result.data["equipment_result"]["program_id"] == "program1"
    assert result.data["equipment_result"]["program_log"] == "program1 completed"
    assert result.data["protocol_note"] == "use registered program1"
    assert result.data["equipment_handoff"]["status"] == "ready_for_analysis"
    assert result.data["equipment_handoff"]["program_id"] == "program1"
    assert result.data["program_catalog"] == ["program1"]
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

    result = await LabEquipmentAgent().run(_state(), ctx)

    assert result.success is True
    assert result.data["equipment_result"]["program_id"] == "program1"
    assert "using safe equipment tool plan" in result.data["protocol_note"]


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
    assert result.data["equipment_bridge"] == "utm"
    assert result.data["equipment_result"]["tool"] == "utm.run_protocol"
