"""Unit tests for UTM-based AnalysisAgent behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.analysis_agent import AnalysisAgent
from mcp_tools.cae_tools import register_cae_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(
        self,
        *,
        force_real_llm_in_test: bool = False,
        text: str = "UTM summary",
        tools: ToolRegistry | None = None,
    ) -> None:
        self.force_real_llm_in_test = force_real_llm_in_test
        self.text = text
        self.prompts: list[tuple[str, str]] = []
        self.tools = tools

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> Any:
        self.prompts.append((task_type, user_prompt))
        return SimpleNamespace(text=self.text)


def _curve() -> list[dict[str, float]]:
    return [
        {"time_s": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
        {"time_s": 0.5, "displacement_mm": 0.5, "force_N": 80.0},
        {"time_s": 1.0, "displacement_mm": 1.0, "force_N": 180.0},
        {"time_s": 1.5, "displacement_mm": 1.5, "force_N": 310.0},
        {"time_s": 2.0, "displacement_mm": 2.0, "force_N": 430.0},
        {"time_s": 2.5, "displacement_mm": 2.5, "force_N": 520.0},
        {"time_s": 3.0, "displacement_mm": 3.0, "force_N": 500.0},
        {"time_s": 3.5, "displacement_mm": 3.5, "force_N": 455.0},
        {"time_s": 4.0, "displacement_mm": 4.0, "force_N": 390.0},
        {"time_s": 4.5, "displacement_mm": 4.5, "force_N": 340.0},
        {"time_s": 5.0, "displacement_mm": 5.0, "force_N": 300.0},
    ]


def _state(*, mode: Mode = Mode.TEST, equipment_result: dict[str, Any] | None = None) -> OrchestratorState:
    return OrchestratorState(
        run_id="run-analysis",
        experiment_id="exp-analysis",
        mode=mode,
        stage=Stage.ANALYSIS,
        current_experiment_spec={
            "specimen_id": "specimen-analysis",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "expected_mass_g": 6.0,
            "relative_density": 0.32,
            "wall_thickness_mm": 1.2,
        },
        current_experiment_objective={"metric_name": "compressive_strength_MPa", "direction": "maximize"},
        run_metadata={"equipment_result": equipment_result or {"ok": True, "tool": "equipment.pyautogui.run", "utm_data": _curve()}},
    )


@pytest.mark.asyncio
async def test_analysis_agent_extracts_inline_utm_metrics() -> None:
    result = await AnalysisAgent().run(_state(), _CtxStub())

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["source"]["source"] == "equipment_result.inline"
    assert analysis["utm_metrics"]["peak_force_N"] == 520.0
    assert analysis["utm_metrics"]["compressive_strength_MPa"] == 1.3
    assert analysis["utm_metrics"]["energy_absorption_mJ"] > 1500
    assert analysis["specimen_geometry"]["cross_section_area_mm2"] == 400.0
    assert analysis["recommendation"] == "ready_for_knowledge_guardian"


@pytest.mark.asyncio
async def test_analysis_agent_reads_utm_csv_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_result.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,100\n"
        "2,2,240\n"
        "3,3,210\n",
        encoding="utf-8",
    )
    equipment = {"ok": True, "tool": "equipment.pyautogui.run", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(_state(equipment_result=equipment), _CtxStub())

    analysis = result.data["analysis"]
    assert analysis["ok"] is True
    assert analysis["source"]["source"] == "equipment_result.result_file"
    assert analysis["utm_metrics"]["peak_force_N"] == 240.0


@pytest.mark.asyncio
async def test_analysis_agent_uses_synthetic_curve_in_test_without_utm_data() -> None:
    equipment = {"ok": True, "tool": "equipment.pyautogui.run", "program_id": "program1"}

    result = await AnalysisAgent().run(_state(equipment_result=equipment), _CtxStub())

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["source"]["source"] == "synthetic_test_utm_curve"
    assert analysis["utm_curve"]["point_count"] == 80
    assert analysis["uncertainty"] >= 0.28


@pytest.mark.asyncio
async def test_analysis_agent_uses_cae_for_test_closed_loop(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {"devices": {"cae": {"enabled": True, "mode": "test", "artifact_dir": "artifacts/cae"}}},
        repo_root=tmp_path,
    )
    equipment = {"ok": True, "tool": "equipment.pyautogui.run", "program_id": "program1"}

    result = await AnalysisAgent().run(_state(equipment_result=equipment), _CtxStub(tools=tools))

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["source"]["source"] == "synthetic_test_utm_curve"
    assert analysis["cae_result"]["ok"] is True
    assert analysis["cae_result"]["boundary_condition"] == "bottom_fixed_support"
    assert analysis["cae_result"]["analysis_platens"]["bottom"] is True
    assert analysis["cae_result"]["analysis_platens"]["top"] is True
    assert analysis["cae_metrics"]["max_von_mises_MPa"] > 0
    assert analysis["cae_metrics"]["effective_modulus_MPa"] > 0
    assert "cae.run_static_analysis" in analysis["closed_loop_sources"]


@pytest.mark.asyncio
async def test_analysis_agent_blocks_live_without_utm_data() -> None:
    equipment = {"ok": True, "tool": "equipment.pyautogui.run", "program_id": "program1"}

    result = await AnalysisAgent().run(_state(mode=Mode.LIVE, equipment_result=equipment), _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is False
    assert analysis["ok"] is False
    assert analysis["failure_code"] == "UTM_DATA_REQUIRED"
