"""Unit tests for UTM-based AnalysisAgent behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.analysis_agent import AnalysisAgent
from mcp_tools.cae_tools import register_cae_tools
from mcp_tools.tool_registry import ToolRegistry
from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec
from objectives.service import ObjectiveService
from objectives.store import ObjectiveStore
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


def _active_objective_service(tmp_path: Path) -> ObjectiveService:
    service = ObjectiveService(
        store=ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs"),
        registry=MetricRegistry.default(),
    )
    service.create_draft(
        ObjectiveSpec(
            objective_id="analysis-objective",
            version=1,
            expression={
                "op": "normalize",
                "value": {"op": "metric", "metric_id": "compressive_strength_mpa"},
                "min": {"op": "literal", "value": 0.0, "unit": "MPa"},
                "max": {"op": "literal", "value": 2.0, "unit": "MPa"},
            },
        )
    )
    service.validate("analysis-objective", 1)
    service.preview(
        "analysis-objective",
        1,
        [
            {
                "observation_id": "preview-analysis",
                "metrics": {"compressive_strength_mpa": 1.0},
                "quality_ok": True,
                "provenance_refs": ["preview-artifact"],
            }
        ],
    )
    service.approve("analysis-objective", 1, operator="operator")
    service.activate("analysis-objective", 1, run_id="run-analysis", operator="operator")
    return service


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
    assert analysis["recommendation"] == "review_utm_curve_quality_before_model_update"
    assert analysis["utm_metrics"]["energy_absorption_limit_reached"] is False


@pytest.mark.asyncio
async def test_analysis_agent_evaluates_active_compiled_objective(tmp_path: Path) -> None:
    service = _active_objective_service(tmp_path)
    tools = ToolRegistry()
    tools.register_resource("objective.service", service)

    result = await AnalysisAgent().run(_state(), _CtxStub(tools=tools))

    analysis = result.data["analysis"]
    evaluation = analysis["objective_evaluation"]
    binding = service.status(run_id="run-analysis")["active_binding"]
    assert result.success is True
    assert analysis["objective_score"] == evaluation["score"]
    assert evaluation["objective_hash"] == binding["objective_hash"]
    assert evaluation["metrics"]["compressive_strength_mpa"] == 1.3
    assert evaluation["provenance_refs"]


@pytest.mark.asyncio
async def test_analysis_agent_blocks_requested_objective_without_binding() -> None:
    state = _state()
    state.current_experiment_objective = {
        "schema_version": "objective_spec.v1",
        "objective_id": "missing-objective",
        "version": 1,
        "objective_hash": "sha256:missing",
    }

    result = await AnalysisAgent().run(state, _CtxStub())

    assert result.success is False
    assert result.data["analysis"]["failure_code"] == "OBJECTIVE_BINDING_REQUIRED"
    assert result.data["analysis"]["objective_score"] is None


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
    assert result.data["bo_observation"]["schema"] == "bo_observation.v1"
    assert result.data["bo_observation"]["observed_metrics"] == {}
    assert result.data["experiment_evaluation"]["schema"] == "experiment_evaluation.v1"
    assert result.data["experiment_evaluation"]["metrics"]["peak_force_N"] == 240.0
    assert result.data["knowledge_payload"]["schema"] == "analysis_knowledge_payload.v1"
    assert result.data["knowledge_payload"]["raw_artifact_refs"][0]["path"] == str(csv_path)
    assert analysis["bo_observation"]["artifact_refs"][0]["kind"] == "utm_csv"


@pytest.mark.asyncio
async def test_analysis_agent_integrates_trapezium_curve_to_planned_50pct_height_for_bo(tmp_path: Path) -> None:
    csv_path = tmp_path / "trapezium_30mm.csv"
    rows = [
        '"1 _ 1",,,,',
        '"Time","Force","스트로크","Height"',
        '"sec","N","mm","mm"',
    ]
    rows.extend(
        f'"{displacement / 10:.1f}","{displacement * 10}","{displacement}","{30 - displacement}"'
        for displacement in range(0, 21, 2)
    )
    csv_path.write_bytes(("\r\n".join(rows) + "\r\n").encode("cp949"))
    state = _state(
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "output_artifacts": [
                {
                    "kind": "utm_csv",
                    "artifact_id": "real-trapezium-30mm",
                    "local_path": str(csv_path),
                    "pulled_to_linux": True,
                    "local_parse_ok": True,
                }
            ],
        }
    )
    state.current_experiment_spec["specimen_size_mm"] = [20.0, 20.0, 30.0]
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {"devices": {"cae": {"enabled": True, "mode": "test", "artifact_dir": str(tmp_path / "cae")}}},
        repo_root=tmp_path,
    )

    result = await AnalysisAgent().run(state, _CtxStub(tools=tools))

    analysis = result.data["analysis"]
    metrics = analysis["utm_metrics"]
    observation = result.data["bo_observation"]
    assert result.success is True
    assert analysis["source"]["parser_id"] == "analysis.parsers.lab_equipment_utm_csv"
    assert analysis["source"]["source_format"] == "trapeziumx_raw"
    assert metrics["peak_force_N"] == 200.0
    assert metrics["energy_absorption_mJ"] == pytest.approx(2000.0)
    assert metrics["energy_absorption_limit_mm"] == 15.0
    assert metrics["measured_displacement_max_mm"] == 20.0
    assert metrics["energy_absorption_limit_reached"] is True
    assert metrics["energy_absorption_50pct_mJ"] == pytest.approx(1125.0)
    assert observation["status"] == "ready"
    assert observation["metric_name"] == "energy_absorption_50pct_mJ"
    assert observation["unit"] == "mJ"
    assert observation["objective_score"] == pytest.approx(1125.0)
    assert observation["observed_metrics"] == {"energy_absorption_50pct_mJ": pytest.approx(1125.0)}
    assert "peak_at_curve_boundary" in metrics["curve_quality"]["warnings"]
    assert observation["candidate_id"] == "specimen-analysis"
    assert observation["observation_id"] == result.data["bo_handoff"]["observation_id"]
    assert observation["observation_id"] == result.data["experiment_evaluation"]["observation_id"]


@pytest.mark.asyncio
async def test_analysis_agent_blocks_bo_when_csv_ends_below_planned_50pct_height(tmp_path: Path) -> None:
    csv_path = tmp_path / "short_curve.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,4,40\n"
        "2,8,80\n"
        "3,12,120\n",
        encoding="utf-8",
    )
    state = _state(
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "output_artifacts": [{"kind": "utm_csv", "local_path": str(csv_path)}],
        }
    )
    state.current_experiment_spec["specimen_size_mm"] = [18.0, 18.0, 30.0]

    result = await AnalysisAgent().run(state, _CtxStub())

    metrics = result.data["analysis"]["utm_metrics"]
    observation = result.data["bo_observation"]
    assert result.success is True
    assert metrics["energy_absorption_limit_mm"] == 15.0
    assert metrics["measured_displacement_max_mm"] == 12.0
    assert metrics["energy_absorption_limit_reached"] is False
    assert metrics["energy_absorption_50pct_mJ"] is None
    assert observation["status"] == "blocked"
    assert observation["objective_score"] is None


@pytest.mark.asyncio
async def test_analysis_agent_does_not_replace_unreadable_equipment_csv_with_synthetic_data(tmp_path: Path) -> None:
    csv_path = tmp_path / "broken_equipment.csv"
    csv_path.write_text("not,a,utm,curve\n1,2,3,4\n", encoding="utf-8")
    state = _state(
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "output_artifacts": [{"kind": "utm_csv", "local_path": str(csv_path)}],
        }
    )

    result = await AnalysisAgent().run(state, _CtxStub())

    assert result.success is False
    assert result.data["analysis"]["failure_code"] == "UTM_DATA_PARSE_FAILED"
    assert result.data["analysis"]["source"]["source"] != "synthetic_test_utm_curve"


def test_analysis_agent_builds_canonical_curve_with_linear_input_scans() -> None:
    class CountingCurve(list[dict[str, float]]):
        def __init__(self, rows: list[dict[str, float]]) -> None:
            super().__init__(rows)
            self.iteration_count = 0

        def __iter__(self):
            self.iteration_count += 1
            return super().__iter__()

    curve = CountingCurve(
        [
            {"time_s": index * 0.01, "displacement_mm": index * 0.001, "force_N": float(index)}
            for index in range(200)
        ]
    )

    canonical = AnalysisAgent._canonical_curve(
        curve,
        {"cross_section_area_mm2": 400.0, "gauge_length_mm": 30.0},
    )

    assert len(canonical) == 200
    assert curve.iteration_count <= 2


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
    assert "synthetic_utm_curve" in result.data["bo_observation"]["failure_tags"]


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
    assert analysis["cae_result"]["analysis_platens"]["bottom"] is False
    assert analysis["cae_result"]["analysis_platens"]["top"] is False
    assert analysis["cae_result"]["request"]["target_strain"] == 0.5
    assert analysis["cae_result"]["request"]["boundary"] == {
        "bottom": "frictionless_axial_support",
        "top": "frictionless_displacement",
    }
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

@pytest.mark.asyncio
async def test_analysis_agent_reads_utm_csv_from_equipment_report_data_acquisition(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_report_result.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,90\n"
        "2,2,260\n"
        "3,3,230\n",
        encoding="utf-8",
    )
    state = _state(
        equipment_result={"ok": True, "tool": "equipment.pyautogui.run", "status": "verified_complete"}
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "data_acquisition": {
            "status": "pulled_to_linux",
            "linux_path": str(csv_path),
            "row_count_probe": 4,
            "columns_probe": ["time_s", "displacement_mm", "force_N"],
        },
    }

    result = await AnalysisAgent().run(state, _CtxStub())

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["source"]["source"] == "equipment_result.equipment_report.data_acquisition.linux_path"
    assert analysis["utm_metrics"]["peak_force_N"] == 260.0


@pytest.mark.asyncio
async def test_analysis_agent_reads_utm_csv_from_utm_packet_when_equipment_result_has_no_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_packet_result.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,110\n"
        "2,2,300\n",
        encoding="utf-8",
    )
    state = _state(equipment_result={"ok": True, "tool": "equipment.pyautogui.run", "status": "verified_complete"})
    state.run_metadata["utm_data_ready"] = {
        "schema": "utm_data_ready.v1",
        "status": "ready",
        "result_file": str(csv_path),
    }

    result = await AnalysisAgent().run(state, _CtxStub())

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["source"]["source"] == "equipment_result.utm_data_ready.result_file"
    assert analysis["utm_metrics"]["peak_force_N"] == 300.0
@pytest.mark.asyncio
async def test_analysis_agent_blocks_live_csv_when_equipment_handoff_not_ready(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_live_blocked.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,120\n"
        "2,2,280\n",
        encoding="utf-8",
    )
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "result_file": str(csv_path),
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "live_evidence_audit": {"required_for_handoff": True},
        "decision": {"handoff_status": "blocked", "failure_code": "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED"},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
            "screen_evidence_complete": True,
            "linux_artifact_pulled": True,
            "vision_evidence_complete": True,
            "request_audit_log_available": False,
            "request_audit_execute_identity_match": True,
        },
    }
    state.run_metadata["equipment_handoff"] = {"status": "blocked", "failure_code": "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED"}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is False
    assert analysis["ok"] is False
    assert analysis["failure_code"] == "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED"
    assert analysis["equipment_handoff_gate"]["status"] == "blocked"
    assert "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:request_audit_log_available" in analysis["equipment_handoff_gate"]["blockers"]
    assert result.data["knowledge_payload"]["schema"] == "analysis_knowledge_payload.v1"
    assert result.data["knowledge_payload"]["raw_artifact_refs"][0]["path"] == str(csv_path)
    assert "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" in result.data["knowledge_payload"]["failure_tags"]
    assert "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:request_audit_log_available" in result.data["knowledge_payload"]["failure_tags"]
    assert result.data["bo_observation"]["status"] == "blocked"
    assert analysis["knowledge_payload"] == result.data["knowledge_payload"]


@pytest.mark.asyncio
async def test_analysis_agent_blocks_live_csv_when_save_export_responsibility_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_live_missing_save_responsibility.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,125\n"
        "2,2,285\n",
        encoding="utf-8",
    )
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "result_file": str(csv_path),
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "live_evidence_audit": {"required_for_handoff": True},
        "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "verified_complete", "blocking_reasons": []},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": False,
            "screen_evidence_complete": True,
            "linux_artifact_pulled": True,
            "vision_evidence_complete": True,
            "request_audit_log_available": True,
            "request_audit_execute_identity_match": True,
        },
    }
    state.run_metadata["equipment_handoff"] = {"status": "ready_for_analysis"}
    state.run_metadata["utm_data_ready"] = {"schema": "utm_data_ready.v1", "status": "ready", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is False
    assert analysis["ok"] is False
    assert analysis["failure_code"] == "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:save_export_responsibility_ok"
    assert analysis["equipment_handoff_gate"]["status"] == "blocked"
    assert "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:save_export_responsibility_ok" in analysis["equipment_handoff_gate"]["blockers"]
    assert result.data["knowledge_payload"]["raw_artifact_refs"][0]["path"] == str(csv_path)
    assert "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:save_export_responsibility_ok" in result.data["knowledge_payload"]["failure_tags"]


@pytest.mark.asyncio
async def test_analysis_agent_allows_live_csv_when_equipment_handoff_ready(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_live_ready.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,130\n"
        "2,2,310\n",
        encoding="utf-8",
    )
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "result_file": str(csv_path),
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "live_evidence_audit": {"required_for_handoff": True},
        "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "verified_complete", "blocking_reasons": []},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
            "screen_evidence_complete": True,
            "linux_artifact_pulled": True,
            "vision_evidence_complete": True,
            "request_audit_log_available": True,
            "request_audit_execute_identity_match": True,
        },
    }
    state.run_metadata["equipment_handoff"] = {"status": "ready_for_analysis"}
    state.run_metadata["utm_data_ready"] = {"schema": "utm_data_ready.v1", "status": "ready", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["source"]["source"] == "equipment_result.result_file"
    assert analysis["equipment_handoff_gate"]["status"] == "ready_for_analysis"
    assert analysis["utm_metrics"]["peak_force_N"] == 310.0


@pytest.mark.asyncio
async def test_analysis_agent_allows_live_csv_when_extended_evidence_gates_are_in_audit(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_live_ready_audit.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,140\n"
        "2,2,320\n",
        encoding="utf-8",
    )
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "result_file": str(csv_path),
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "verified_complete", "blocking_reasons": []},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
        },
        "live_evidence_audit": {
            "required_for_handoff": False,
            "screen_evidence": {"ok": True},
            "linux_artifact_pull": {"ok": True},
            "vision_evidence": {"ok": True, "all_required_ok": True},
            "request_audit_log": {"ok": True, "execute_identity_match": True, "execute_identity_required": False},
        },
    }
    state.run_metadata["equipment_handoff"] = {
        "status": "ready_for_analysis",
        "result_file": str(csv_path),
        "live_evidence_audit": state.run_metadata["equipment_report"]["live_evidence_audit"],
    }
    state.run_metadata["utm_data_ready"] = {"schema": "utm_data_ready.v1", "status": "ready", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["equipment_handoff_gate"]["status"] == "ready_for_analysis"
    assert analysis["utm_metrics"]["peak_force_N"] == 320.0


@pytest.mark.asyncio
async def test_analysis_agent_blocks_zero_force_csv_even_when_equipment_handoff_ready(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_live_zero_force.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,0\n"
        "2,2,0\n",
        encoding="utf-8",
    )
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": True,
            "tool": "equipment.pyautogui.run",
            "status": "verified_complete",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "result_file": str(csv_path),
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "live_evidence_audit": {"required_for_handoff": True},
        "decision": {"handoff_status": "ready_for_analysis", "equipment_status": "verified_complete", "blocking_reasons": []},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
            "screen_evidence_complete": True,
            "linux_artifact_pulled": True,
            "vision_evidence_complete": True,
            "request_audit_log_available": True,
            "request_audit_execute_identity_match": True,
        },
    }
    state.run_metadata["equipment_handoff"] = {"status": "ready_for_analysis"}
    state.run_metadata["utm_data_ready"] = {"schema": "utm_data_ready.v1", "status": "ready", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is False
    assert analysis["ok"] is False
    assert analysis["failure_code"] == "UTM_DATA_NO_FORCE_SIGNAL"
    assert analysis["data_quality"]["force_nonzero"] is False
    assert analysis["source"]["signal_quality_probe"]["force_changes"] is False
    assert result.data["knowledge_payload"]["raw_artifact_refs"][0]["path"] == str(csv_path)
    assert "UTM_DATA_NO_FORCE_SIGNAL" in result.data["knowledge_payload"]["failure_tags"]


@pytest.mark.asyncio
async def test_analysis_agent_blocked_live_without_data_preserves_equipment_report_artifacts(tmp_path: Path) -> None:
    screen_path = tmp_path / "before_start.png"
    screen_path.write_bytes(b"fake-png")
    state = _state(
        mode=Mode.LIVE,
        equipment_result={
            "ok": False,
            "tool": "equipment.pyautogui.run",
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "program_id": "utm_compression_start_v1",
            "failure_code": "UTM_EXPORT_FILE_MISSING",
        },
    )
    state.run_metadata["equipment_report"] = {
        "schema": "equipment_report.v1",
        "bridge": {"provider": "windows_pyautogui"},
        "control_plan": {"program_id": "utm_compression_start_v1"},
        "live_evidence_audit": {"required_for_handoff": True},
        "artifact_refs": [{"kind": "screen_png", "path": str(screen_path), "artifact_id": "screen-before-start"}],
        "screen_evidence_refs": [{"kind": "screen_png", "path": str(screen_path), "artifact_id": "screen-before-start"}],
        "data_acquisition": {"status": "missing", "failure_code": "UTM_EXPORT_FILE_MISSING"},
        "decision": {"handoff_status": "blocked", "failure_code": "UTM_EXPORT_FILE_MISSING"},
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": False,
            "save_completed": False,
            "data_file_created": False,
            "data_parse_probe_ok": False,
            "save_export_responsibility_ok": False,
            "screen_evidence_complete": False,
            "linux_artifact_pulled": False,
            "vision_evidence_complete": False,
            "request_audit_log_available": True,
            "request_audit_execute_identity_match": True,
        },
    }
    state.run_metadata["equipment_handoff"] = {"status": "blocked", "failure_code": "UTM_EXPORT_FILE_MISSING"}

    result = await AnalysisAgent().run(state, _CtxStub(text="live summary"))

    analysis = result.data["analysis"]
    assert result.success is False
    assert analysis["failure_code"] == "UTM_DATA_REQUIRED"
    refs = result.data["knowledge_payload"]["raw_artifact_refs"]
    assert any(item.get("path") == str(screen_path) and item.get("artifact_id") == "screen-before-start" for item in refs)
    assert "UTM_DATA_REQUIRED" in result.data["knowledge_payload"]["failure_tags"]
    assert "UTM_EXPORT_FILE_MISSING" in result.data["knowledge_payload"]["failure_tags"]


@pytest.mark.asyncio
async def test_analysis_agent_accepts_negative_force_sign_convention(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_negative_force.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,-130\n"
        "2,2,-310\n",
        encoding="utf-8",
    )
    equipment = {"ok": True, "tool": "equipment.pyautogui.run", "result_file": str(csv_path)}

    result = await AnalysisAgent().run(_state(equipment_result=equipment), _CtxStub())

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["ok"] is True
    assert analysis["utm_metrics"]["peak_force_N"] == 310.0
    assert analysis["data_quality_gate"]["force_nonzero"] is True
    assert analysis["data_quality_gate"]["force_changes"] is True

@pytest.mark.asyncio
async def test_analysis_agent_emits_improvement06_artifacts_bo_handoff_and_calculix_cae(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_units.csv"
    csv_path.write_text(
        "Time (s),Extension (mm),Load (kN)\n"
        "0,0,0\n"
        "1,1,0.10\n"
        "2,2,0.24\n"
        "3,3,0.21\n",
        encoding="utf-8",
    )
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {
            "devices": {
                "cae": {
                    "enabled": True,
                    "mode": "test",
                    "artifact_dir": str(tmp_path / "cae"),
                }
            }
        },
        repo_root=tmp_path,
    )
    state = _state(equipment_result={"ok": True, "tool": "equipment.pyautogui.run", "result_file": str(csv_path)})
    state.run_id = "run-analysis-improvement06"
    state.experiment_id = "exp-analysis-improvement06"
    state.current_experiment_spec.update({"geometry_type": "gyroid", "cell_size_mm": 5.0, "tpms_thickness": 0.35})
    state.current_experiment_spec["gauge_length_mm"] = 6.0

    result = await AnalysisAgent().run(state, _CtxStub(tools=tools))

    analysis = result.data["analysis"]
    assert result.success is True
    assert analysis["utm_metrics"]["peak_force_N"] == 240.0
    assert analysis["source"]["parser_id"] == "analysis.parsers.csv_header"
    assert analysis["source"]["column_mapping"]["mappings"]["Load (kN)"]["multiplier"] == 1000.0
    assert analysis["quality_gate"]["ok_for_metrics"] is True
    assert "cae.run_static_analysis" in analysis["closed_loop_sources"]
    removed_solver_token = "fe" + "nics"
    assert not any(removed_solver_token in str(item).lower() for item in analysis["closed_loop_sources"])
    assert analysis["cae_result"]["ok"] is True
    assert analysis["cae_result"]["tool"] == "cae.run_static_analysis"
    assert analysis["fem_result"]["schema"] == "fem_result.v1"
    assert analysis["fem_agentic_loop"]["schema"] == "analysis_cae_simulation_loop.v1"
    assert analysis["fem_agentic_loop"]["status"] == "completed"
    assert analysis["fem_agentic_loop"]["selected_result"]["tool"] == "cae.run_static_analysis"
    assert analysis["fem_utm_comparison"]["schema"] == "fem_utm_comparison.v1"
    assert analysis["trust_score"]["schema"] == "trust_score.v1"
    assert analysis["trust_score"]["gate"] in {"allow_bo", "allow_physical"}
    assert analysis["multifidelity_comparison"]["schema"] == "multifidelity_comparison.v1"
    assert analysis["multifidelity_comparison"]["curve"]["peak_force_error_pct"] is not None
    assert analysis["fidelity_records"]["utm_high"]["schema"] == "utm_record.v1"
    assert analysis["fidelity_records"]["fea_mid"]["schema"] == "fea_result.v1"
    assert analysis["fidelity_records"]["pinn_low_or_surrogate"]["status"] == "unavailable"
    assert result.data["bo_handoff"]["schema_version"] == "analysis_bo_handoff_v2"
    measured_energy_50pct = analysis["utm_metrics"]["energy_absorption_50pct_mJ"]
    assert result.data["bo_handoff"]["objective"]["metric_name"] == "energy_absorption_50pct_mJ"
    assert result.data["bo_handoff"]["objective"]["unit"] == "mJ"
    assert result.data["bo_handoff"]["objective"]["score"] == measured_energy_50pct
    assert result.data["bo_handoff"]["metrics"] == {"energy_absorption_50pct_mJ": measured_energy_50pct}
    assert result.data["experiment_evaluation"]["objective"]["metric_name"] == "energy_absorption_50pct_mJ"
    assert result.data["experiment_evaluation"]["objective_score"] == measured_energy_50pct
    assert result.data["bo_handoff"]["trust_score"]["schema"] == "trust_score.v1"
    assert result.data["bo_handoff"]["multifidelity_comparison"]["schema"] == "multifidelity_comparison.v1"
    assert result.data["bo_handoff"]["fidelity"]["utm_high"]["objective_source"] is True
    artifacts = analysis["analysis_artifacts"]
    for key in (
        "raw_input_sidecar",
        "parse_report",
        "canonical_curve",
        "preprocessing_report",
        "quality_report",
        "metrics",
        "fem_result",
        "fem_request",
        "fem_agentic_loop",
        "fem_utm_comparison",
        "multifidelity_comparison",
        "trust_score",
        "comparison",
        "analysis_report",
        "experiment_evaluation",
        "bo_handoff",
        "analysis_trace",
    ):
        assert Path(artifacts[key]).exists(), key
    assert result.data["experiment_evaluation"]["fidelity_records"]["utm_high"] == "metrics"
    assert result.data["experiment_evaluation"]["trust_score"]["schema"] == "trust_score.v1"


@pytest.mark.asyncio
async def test_analysis_agent_does_not_call_removed_python_fem_tools(tmp_path: Path) -> None:
    csv_path = tmp_path / "utm_llm_plan.csv"
    csv_path.write_text(
        "time_s,displacement_mm,force_N\n"
        "0,0,0\n"
        "1,1,120\n"
        "2,2,260\n"
        "3,3,240\n",
        encoding="utf-8",
    )
    tools = ToolRegistry()
    register_cae_tools(
        tools,
        {
            "devices": {
                "cae": {
                    "enabled": True,
                    "mode": "test",
                    "artifact_dir": str(tmp_path / "cae"),
                }
            }
        },
        repo_root=tmp_path,
    )
    ctx = _CtxStub(force_real_llm_in_test=False, tools=tools)
    state = _state(equipment_result={"ok": True, "tool": "equipment.pyautogui.run", "result_file": str(csv_path)})

    result = await AnalysisAgent().run(state, ctx)

    analysis = result.data["analysis"]
    loop = analysis["fem_agentic_loop"]
    assert result.success is True
    assert ctx.prompts == []
    removed_solver_token = "fe" + "nics"
    assert removed_solver_token not in json.dumps(analysis, ensure_ascii=True).lower()
    assert loop["schema"] == "analysis_cae_simulation_loop.v1"
    assert loop["tool_sequence"] == ["cae.health", "cae.run_static_analysis"]
    assert loop["selected_result"]["tool"] == "cae.run_static_analysis"
    assert Path(analysis["analysis_artifacts"]["fem_agentic_loop"]).exists()


def test_cae_quasistatic_energy_is_included_in_utm_agreement() -> None:
    comparison = AnalysisAgent()._fem_utm_comparison(
        {
            "peak_force_N": 1_000.0,
            "initial_stiffness_N_per_mm": 100.0,
            "energy_absorption_50pct_mJ": 10_000.0,
            "energy_absorption_limit_reached": True,
        },
        None,
        {
            "ok": True,
            "tool": "cae.run_static_analysis",
            "cae_metrics": {
                "peak_reaction_force_N": 800.0,
                "initial_stiffness_N_per_mm": 120.0,
                "energy_absorption_50pct_mJ": 12_000.0,
                "endpoint_reached": True,
            },
        },
    )

    assert comparison["peak_force_error_pct"] == 20.0
    assert comparison["stiffness_error_pct"] == 20.0
    assert comparison["energy_absorption_50pct_error_pct"] == 20.0
    assert comparison["utm_energy_absorption_50pct_mJ"] == 10_000.0
    assert comparison["fea_energy_absorption_50pct_mJ"] == 12_000.0
    assert comparison["agreement_score"] == pytest.approx(0.833333, abs=1e-6)
