"""
Unit tests for SpecimenMakingAgent tool-chain behavior.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any

import pytest

from agents.specimen_agent import SpecimenMakingAgent
from device_bridges.prusa_bridge import PrusaSlicerRunner
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.printer_tools import register_printer_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


def _normal_counts_from_stl(stl_path: Path) -> tuple[int, int]:
    data = stl_path.read_bytes()
    axis_facets = 0
    curved_facets = 0

    def add_normal(normal: tuple[float, float, float]) -> None:
        nonlocal axis_facets, curved_facets
        is_axis = sum(abs(abs(value) - 1.0) < 1e-6 for value in normal) == 1 and sum(
            abs(value) < 1e-6 for value in normal
        ) == 2
        if is_axis:
            axis_facets += 1
        else:
            curved_facets += 1

    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        if 84 + triangle_count * 50 == len(data):
            offset = 84
            for _idx in range(triangle_count):
                offset += 12
                points = []
                for _vertex in range(3):
                    points.append(struct.unpack_from("<fff", data, offset))
                    offset += 12
                offset += 2
                ax, ay, az = points[0]
                bx, by, bz = points[1]
                cx, cy, cz = points[2]
                ux, uy, uz = bx - ax, by - ay, bz - az
                vx, vy, vz = cx - ax, cy - ay, cz - az
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                add_normal((nx / length, ny / length, nz / length))
            return axis_facets, curved_facets

    for line in data.decode("utf-8").splitlines():
        if not line.lstrip().startswith("facet normal"):
            continue
        _, _, nx, ny, nz = line.split()
        add_normal((float(nx), float(ny), float(nz)))
    return axis_facets, curved_facets


class _CtxStub:
    def __init__(self) -> None:
        tools = ToolRegistry()
        register_mock_tools(tools)
        register_experiment_tools(tools)
        self.tools = tools

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        return SimpleNamespace(text=f"{task_type}: {prompt[:80]}")


def _fake_slice(tmp_path: Path):
    def fake_slice(
        self,
        stl_path,
        *,
        specimen_id,
        simulate,
        printer_profile="",
        material="",
        slicer_profile_hint="",
        experiment_spec=None,
    ):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("M84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": bool(simulate),
            "slicer_settings": {"simulated": bool(simulate), "output_gcode_path": str(output)},
        }

    return fake_slice


def _valid_spec() -> dict[str, Any]:
    return {
        "candidate_id": "cand-1-01",
        "specimen_id": "specimen-cand-1-01-gyroid",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30.0, 30.0, 30.0],
        "cell_size_mm": 5.0,
        "wall_thickness_mm": 1.2,
        "relative_density": 0.32,
        "porosity": 0.68,
        "anisotropy_ratio": 1.0,
        "orientation_deg": 0.0,
        "defect_seed": 1,
        "defect_ratio": 0.0,
        "skin_thickness_mm": 0.8,
        "top_cap_enabled": False,
        "bottom_cap_enabled": True,
        "top_bottom_cap": True,
        "material": "PLA",
        "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
        "slicer_profile_hint": "0.2mm_quality",
        "layer_height_mm": 0.2,
        "nozzle_diameter_mm": 0.4,
        "expected_mass_g": 12.0,
        "expected_print_time_min": 65.0,
        "constraints": {
            "minimum_feature_size_mm": 0.8,
            "fdm_max_gyroid_wall_cell_ratio": 0.28,
            "max_print_time_min": 120.0,
            "max_mass_g": 50.0,
        },
    }


def test_mock_geometry_generates_curved_gyroid_tpms_stl(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)

    result = tools.call(
        "geometry.generate_metamaterial_stl",
        {
            "run_id": "run-test",
            "experiment_id": "exp-test",
            "candidate_id": "cand-gyroid",
            "specimen_id": "specimen-gyroid",
            "geometry_type": "gyroid",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "cell_size_mm": 5.0,
            "wall_thickness_mm": 1.0,
            "relative_density": 0.32,
            "anisotropy_ratio": 1.0,
            "orientation_deg": 0.0,
            "defect_seed": 1,
            "defect_ratio": 0.0,
            "skin_thickness_mm": 0.8,
            "top_cap_enabled": False,
            "bottom_cap_enabled": True,
            "top_bottom_cap": True,
            "material": "PLA",
            "output_dir": str(tmp_path / "gyroid"),
            "output_format": "stl",
            "tpms_resolution": 18,
        },
    )

    report = result["geometry_report"]
    stl_path = Path(result["stl_path"])
    axis_facets, curved_facets = _normal_counts_from_stl(stl_path)

    assert result["ok"] is True
    assert report["geometry_type"] == "gyroid"
    assert report["top_cap_enabled"] is False
    assert report["bottom_cap_enabled"] is True
    assert report["top_bottom_cap"] is True
    assert report["skin_thickness_mm"] == 0.8
    assert report["cap_skin_applied"] is True
    assert report["cap_skin_thickness_mm"] == 0.8
    assert report["generator_backend"] in {
        "tpms_gyroid_marching_cubes",
        "tpms_gyroid_marching_tetra_fallback",
    }
    assert report["triangle_count"] > 1000
    assert curved_facets / max(axis_facets + curved_facets, 1) > 0.90


def test_mock_geometry_preserves_zero_flat_skin_for_open_tpms(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)

    result = tools.call(
        "geometry.generate_metamaterial_stl",
        {
            "run_id": "run-test",
            "experiment_id": "exp-test",
            "candidate_id": "cand-open-gyroid",
            "specimen_id": "specimen-open-gyroid",
            "geometry_type": "gyroid",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "cell_size_mm": 5.0,
            "wall_thickness_mm": 1.2,
            "relative_density": 0.32,
            "skin_thickness_mm": 0.0,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "material": "PLA",
            "output_dir": str(tmp_path / "open-gyroid"),
            "output_format": "stl",
            "tpms_resolution": 18,
        },
    )

    assert result["ok"] is True
    assert result["geometry_report"]["skin_thickness_mm"] == 0.0
    assert result["geometry_report"]["top_cap_enabled"] is False
    assert result["geometry_report"]["bottom_cap_enabled"] is False
    assert result["geometry_report"]["top_bottom_cap"] is False
    assert result["geometry_report"]["cap_skin_applied"] is False
    assert result["geometry_report"]["cap_skin_thickness_mm"] == 0.0


def test_gyroid_manufacturability_rejects_non_fdm_wall() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)

    result = tools.call(
        "geometry.check_manufacturability",
        {
            "constraints": {
                "geometry_type": "gyroid",
                "wall_thickness_mm": 0.6,
                "cell_size_mm": 7.5,
                "relative_density": 0.32,
                "top_bottom_cap": True,
                "nozzle_diameter_mm": 0.4,
                "layer_height_mm": 0.2,
                "minimum_feature_size_mm": 0.8,
                "fdm_min_wall_thickness_mm": 1.2,
                "fdm_max_bridge_distance_mm": 10.0,
                "expected_print_time_min": 60.0,
                "expected_mass_g": 8.0,
            },
            "mesh_report": {"bbox": [30.0, 30.0, 30.0]},
        },
    )

    assert result["ok"] is False
    assert "wall_thickness_mm below FDM printable wall rule" in result["reject_reasons"]


@pytest.mark.asyncio
async def test_specimen_agent_executes_geometry_handoff_and_printer_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SpecimenMakingAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
        active_goal="test specimen",
        current_experiment_spec=_valid_spec(),
    )
    ctx = _CtxStub()

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]

    assert result.success is True
    assert specimen_result["ok"] is True
    assert specimen_result["mesh_status"] == "pass"
    assert specimen_result["manufacturability_status"] == "pass"
    assert specimen_result["handoff_status"] == "ready"
    assert specimen_result["geometry_hash"]
    assert specimen_result["stl_path"]
    assert specimen_result["handoff_package_path"]
    assert Path(specimen_result["stl_path"]).stat().st_size > 1024


@pytest.mark.asyncio
async def test_specimen_agent_disables_generated_caps_after_first_test_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["tpms_resolution"] = 18
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
        loop_count=1,
        active_goal="test specimen",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]
    report = specimen_result["geometry_report"]

    assert result.success is True
    assert specimen_result["surface_cap_policy"]["generated_model_caps_disabled"] is True
    assert report["top_cap_enabled"] is False
    assert report["bottom_cap_enabled"] is False
    assert report["top_bottom_cap"] is False
    assert report["cap_skin_applied"] is False
    assert state.current_experiment_spec["test_loop_surface_caps_disabled"] is True


@pytest.mark.asyncio
async def test_specimen_agent_clamps_low_gyroid_density_before_manufacturability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["relative_density"] = 0.18
    spec["constraints"]["relative_density"] = 0.18
    spec["tpms_resolution"] = 18
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
        active_goal="test specimen",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)

    assert result.success is True
    assert state.current_experiment_spec["relative_density"] == 0.20
    assert result.data["specimen_result"]["manufacturability_status"] == "pass"


@pytest.mark.asyncio
async def test_specimen_agent_uses_phase1_printer_prepare_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SpecimenMakingAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
        active_goal="test specimen",
        current_experiment_spec=_valid_spec(),
    )
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_printer_tools(
        tools,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                }
            }
        },
        repo_root=tmp_path,
    )
    register_experiment_tools(tools)
    ctx = _CtxStub()
    ctx.tools = tools

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]

    assert result.success is True
    assert specimen_result["printer_path"] == "virtual_prusalink"
    assert specimen_result["printer_mode"] == "test_printer_live_virtual"
    assert specimen_result["print_result"]["status"] == "virtual_finished"
    assert isinstance(specimen_result["step_trace"], list)
    assert specimen_result["sliced_path"]
    assert specimen_result["slicer_settings"]["printer_profile"] == "prusa_mk4s_pla_0p4_nozzle"
    assert specimen_result["gcode_validation"]["ok"] is True
    assert specimen_result["operator_messages"]
    assert specimen_result["experiment_evaluation"]["bridge"] == "printer"
    assert specimen_result["experiment_evaluation"]["job"]["device"] == "printer:prusa_mk4s"


@pytest.mark.asyncio
async def test_specimen_agent_live_gui_test_mode_asks_for_printer_path() -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["test_mode_autofill"] = True
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.LIVE,
        stage=Stage.SPECIMEN,
        active_goal="live gui test mode",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]

    assert result.success is True
    assert specimen_result["requires_operator_input"] is True
    assert specimen_result["input_request"]["type"] == "printer_test_path_choice"
    assert "가상 브릿지" in specimen_result["input_request"]["prompt"]
    assert "실제 출력" in specimen_result["input_request"]["prompt"]
    assert "physical_print" in specimen_result["input_request"]["choices"]


@pytest.mark.asyncio
async def test_specimen_agent_live_gui_test_mode_virtual_choice_runs_virtual_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["test_mode_autofill"] = True
    spec["printer_test_path"] = "가상 브릿지"
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.LIVE,
        stage=Stage.SPECIMEN,
        active_goal="live gui test mode",
        current_experiment_spec=spec,
    )
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_printer_tools(
        tools,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "slicer": {"enabled": True, "output_dir": str(tmp_path / "gcode")},
                }
            }
        },
        repo_root=tmp_path,
    )
    register_experiment_tools(tools)
    ctx = _CtxStub()
    ctx.tools = tools

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )
    monkeypatch.setattr(PrusaSlicerRunner, "slice", _fake_slice(tmp_path))

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]

    assert result.success is True
    assert specimen_result["printer_path"] == "virtual_prusalink"
    assert specimen_result["printer_mode"] == "test_printer_live_virtual"
    assert specimen_result["print_result"]["status"] == "virtual_finished"


@pytest.mark.asyncio
async def test_specimen_agent_raises_on_missing_required_fields() -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec.pop("wall_thickness_mm")
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
        active_goal="test specimen",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()

    with pytest.raises(RuntimeError, match="missing required"):
        await agent.run(state, ctx)
