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


def test_specimen_fabrication_report_includes_bambu_spc_readiness_contract() -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec.update({"printer_profile": "bambulab_x2d_pla_0p4_nozzle", "storage": "ftps"})
    spec["bambu_autoejection_readiness"] = {
        "schema": "bambu_autoejection_design_readiness.v1",
        "status": "ready",
        "ejection_contact_edge": "front",
        "bed_contact_area_mm2": 900.0,
        "minimum_pushable_height_mm": 5.0,
        "object_height_mm": 30.0,
        "skirt_brim_raft_policy": {"skirt_enabled": False, "brim_enabled": False, "raft_enabled": False},
        "blockers": [],
    }
    state = OrchestratorState(
        run_id="run-bambu",
        experiment_id="exp-bambu",
        mode=Mode.LIVE,
        stage=Stage.SPECIMEN,
        active_goal="bambu spc bridge",
        current_experiment_spec=spec,
    )
    printer_response = {
        "ok": True,
        "status": "HTTP_ARTIFACT_READY_NOT_STARTED",
        "mode": "live",
        "printer_path": "http_artifact",
        "provider": "bambulab_x2d",
        "selected_printer": {
            "profile_id": "bambulab_x2d_lab_01",
            "label": "Bambu Lab X2D - Lab 01",
            "provider": "bambulab_x2d",
        },
        "device_screen": {
            "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
            "actions": {"can_upload": True, "can_start_print": True},
        },
        "preprint_gate": {
            "state": "http_artifact_ready_not_started",
            "technical_ready_for_start": True,
            "ready_for_live_print": False,
            "blockers": ["BAMBU_OPERATOR_CONFIRMATION_REQUIRED"],
        },
        "readiness_levels": [
            {"level_id": "connection", "status": "ready"},
            {"level_id": "operator_approval", "status": "blocked"},
        ],
        "operator_actions": [{"action_id": "confirm_start", "status": "required"}],
        "autoejection": {"status": "not_configured", "blockers": ["BAMBU_AUTOEJECTION_PROVIDER_REQUIRED"]},
        "autoejection_handoff": {
            "schema": "bambu_autoejection_provider_handoff.v1",
            "recommended_consumer_agent": "ManipulationAgent",
            "next_tool": "lerobot.manipulation-agent.run",
            "requires_guardian_approval": True,
            "requires_operator_confirmation": True,
            "motion_started": False,
            "dry_run_only": True,
        },
        "slicer_settings": {
            "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
            "material": "PLA",
            "layer_height_mm": 0.2,
            "nozzle_diameter_mm": 0.4,
            "output_gcode_path": "/tmp/specimen.3mf",
        },
        "slicer_result": {"ok": True, "sliced_path": "/tmp/specimen.3mf"},
        "gcode_validation": {"ok": True, "violations": []},
        "printer": {"provider": "bambulab_x2d", "storage": {"ok": True}, "transfer": "http_artifact"},
        "print_result": {"status": "http_artifact_ready_not_started", "remote_path": "cache/specimen.3mf"},
        "step_trace": [{"step": "SPC_READINESS", "status": "ok", "detail": "technical path verified"}],
    }

    fabrication_report = agent._build_fabrication_report(
        state=state,
        spec=spec,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        geometry_result={
            "ok": True,
            "stl_path": "/tmp/specimen.stl",
            "geometry_hash": "geom-hash",
            "viewer_capture_path": "/tmp/specimen.png",
        },
        mesh_result={"ok": True, "mesh_status": "pass", "warnings": []},
        manufacturability_result={"ok": True, "manufacturability_status": "pass", "warnings": []},
        handoff_result={"handoff_package_path": "/tmp/handoff.json", "status": "ready"},
        experiment_response={"job": {"device": "printer:bambulab_x2d"}},
        printer_response=printer_response,
        printer_payload={"runtime_mode": "live", "print": {"physical_intent": True}},
        protocol_note="bambu spc test",
        live_gui_test_spec=False,
        printer_test_path="physical_print",
        top_cap_enabled=False,
        bottom_cap_enabled=True,
        geometry_payload={"skin_thickness_mm": 0.8},
    )
    screen_report = agent._specimen_agent_report_snapshot(
        state=state,
        spec=spec,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        fabrication_report=fabrication_report,
        handoff_packet={"status": "ready", "consumer_agent": "vision_agent"},
        preview_image_path="/tmp/specimen.png",
        viewer_capture_path="/tmp/specimen.png",
    )

    runtime = fabrication_report["printer_runtime"]
    assert runtime["provider"] == "bambulab_x2d"
    assert runtime["selected_printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert runtime["device_screen"]["actions"]["can_start_print"] is True
    assert runtime["preprint_gate"]["technical_ready_for_start"] is True
    assert runtime["readiness_levels"][1]["status"] == "blocked"
    assert runtime["operator_actions"][0]["action_id"] == "confirm_start"
    assert runtime["autoejection"]["blockers"] == ["BAMBU_AUTOEJECTION_PROVIDER_REQUIRED"]
    assert runtime["autoejection_handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert runtime["autoejection_handoff"]["motion_started"] is False
    assert fabrication_report["process_plan"]["bambu_autoejection_readiness"] == spec["bambu_autoejection_readiness"]
    assert screen_report["printer_status"]["provider"] == "bambulab_x2d"
    assert screen_report["spc_readiness"]["readiness_levels"][0]["level_id"] == "connection"
    assert screen_report["bambu_autoejection_readiness"] == spec["bambu_autoejection_readiness"]
    assert screen_report["autoejection_gate"]["status"] == "not_configured"
    assert screen_report["autoejection_gate"]["handoff"]["next_tool"] == "lerobot.manipulation-agent.run"


def test_installed_printer_standalone_autoejection_marks_a4_workspace_for_vision() -> None:
    agent = SpecimenMakingAgent()
    state = OrchestratorState(run_id="run-bambu-tail", experiment_id="exp-bambu-tail", mode=Mode.TEST, stage=Stage.SPECIMEN)
    spec = {
        **_valid_spec(),
        "printer_test_path": "installed_printer",
        "allow_test_printer_live": True,
        "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
    }
    printer_response = {
        "ok": True,
        "provider": "bambulab_x2d",
        "mode": "test",
        "path": "installed_printer",
        "physical_transport": True,
        "selected_printer": {"profile_id": "bambulab_x2d_lab_01", "provider": "bambulab_x2d", "label": "Bambu Lab X2D - Lab 01"},
        "slicer_result": {"ok": True, "sliced_artifact_path": "/tmp/specimen.gcode.3mf"},
        "gcode_validation": {"ok": True, "violations": []},
        "print_result": {
            "published": True,
            "status": "published_then_stopped",
            "stop_after_start": True,
            "stop": {"ok": True, "published": True},
            "upload": {"remote_path": "specimen.gcode.3mf"},
        },
        "ejection_result": {
            "ok": True,
            "status": "standalone_motion_started",
            "transport": "project_file",
            "source_object_bounds_mm": {"center_x_mm": 50.0, "center_y_mm": 60.0, "max_z": 30.0},
        },
        "autoejection": {"enabled": True, "status": "configured", "provider": "bambu_gcode_patch"},
        "step_trace": [
            {"step": "BAMBU_FTPS_UPLOAD", "status": "ok", "detail": "specimen.gcode.3mf"},
            {"step": "BAMBU_STANDALONE_AUTOEJECTION", "status": "published", "detail": "standalone_motion_started"},
        ],
    }

    report = agent._build_fabrication_report(
        state=state,
        spec=spec,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        geometry_result={"ok": True, "stl_path": "/tmp/specimen.stl", "geometry_hash": "geom-hash"},
        mesh_result={"ok": True, "mesh_status": "pass", "warnings": []},
        manufacturability_result={"ok": True, "manufacturability_status": "pass", "warnings": []},
        handoff_result={"handoff_package_path": "/tmp/handoff.json", "status": "ready"},
        experiment_response={"job": {"device": "printer:bambulab_x2d"}},
        printer_response=printer_response,
        printer_payload={
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "print": {"physical_intent": True, "stop_after_start": True},
        },
        protocol_note="installed printer tail",
        live_gui_test_spec=True,
        printer_test_path="installed_printer",
        top_cap_enabled=False,
        bottom_cap_enabled=False,
        geometry_payload={"skin_thickness_mm": 0.0},
    )
    handoff = agent._build_specimen_fabricated_packet(
        state=state,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        report=report,
        decisions=[],
        evidence_refs=[],
    )

    assert report["fabrication_outcome"]["status"] == "ready_for_vision"
    assert report["fabrication_outcome"]["location"] == "a4_workspace"
    assert report["fabrication_outcome"]["autoejection_status"] == "complete"
    assert report["process_plan"]["ejection_policy"]["status"] == "standalone_motion_started"
    assert handoff["physical_location"] == "a4_workspace"
    assert handoff["fabrication_summary"]["printer_path"] == "installed_printer"


def test_virtual_bridge_marks_autoejected_workspace_for_active_cam_handoff() -> None:
    agent = SpecimenMakingAgent()
    state = OrchestratorState(run_id="run-virtual", experiment_id="exp-virtual", mode=Mode.TEST, stage=Stage.SPECIMEN)
    spec = {
        **_valid_spec(),
        "printer_test_path": "virtual_bridge",
        "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
    }
    printer_response = {
        "ok": True,
        "provider": "bambulab_x2d",
        "mode": "test",
        "printer_path": "virtual_bridge",
        "status": "VIRTUAL_BAMBU_READY",
        "selected_printer": {"profile_id": "bambulab_x2d_lab_01", "provider": "bambulab_x2d", "label": "Bambu Lab X2D - Lab 01"},
        "slicer_result": {"ok": True, "sliced_artifact_path": ""},
        "gcode_validation": {"ok": True, "violations": []},
        "printer": {"provider": "bambulab_x2d", "transport": "virtual"},
        "print_result": {"status": "virtual_bridge_ack"},
        "ejection_result": {"ok": True, "status": "virtual_ack", "transport": "virtual"},
        "autoejection": {"enabled": True, "status": "virtual_ack", "provider": "virtual_bambu_bridge"},
        "step_trace": [{"step": "VIRTUAL_BAMBU_AUTOEJECTION", "status": "ok", "detail": "virtual_ack"}],
    }

    report = agent._build_fabrication_report(
        state=state,
        spec=spec,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        geometry_result={"ok": True, "stl_path": "/tmp/specimen.stl", "geometry_hash": "geom-hash"},
        mesh_result={"ok": True, "mesh_status": "pass", "warnings": []},
        manufacturability_result={"ok": True, "manufacturability_status": "pass", "warnings": []},
        handoff_result={"handoff_package_path": "/tmp/handoff.json", "status": "ready"},
        experiment_response={"job": {"device": "printer:bambulab_x2d"}},
        printer_response=printer_response,
        printer_payload={"runtime_mode": "test", "test_printer_path": "virtual_bridge"},
        protocol_note="virtual printer handoff",
        live_gui_test_spec=True,
        printer_test_path="virtual_bridge",
        top_cap_enabled=False,
        bottom_cap_enabled=False,
        geometry_payload={"skin_thickness_mm": 0.0},
    )
    handoff = agent._build_specimen_fabricated_packet(
        state=state,
        candidate="cand-1-01",
        specimen_id="specimen-cand-1-01-gyroid",
        report=report,
        decisions=[],
        evidence_refs=[],
    )

    outcome = report["fabrication_outcome"]
    assert outcome["status"] == "ready_for_vision"
    assert outcome["location"] == "a4_workspace"
    assert outcome["autoejection_status"] == "complete"
    assert report["monitoring_plan"]["expected_location"] == "a4_workspace"
    assert report["monitoring_plan"]["active_cam_verification_required"] is True
    assert handoff["physical_location"] == "a4_workspace"


def test_preflight_complete_emits_logical_preflight_handoff_without_claiming_fabrication() -> None:
    state = OrchestratorState(run_id="run-preflight", experiment_id="exp-preflight", mode=Mode.TEST, stage=Stage.SPECIMEN)
    report = {
        "schema": "fabrication_report.v1",
        "fabrication_intent": {"physical_intent": True, "printer_path": "physical_print"},
        "fabrication_outcome": {"status": "preflight_complete", "location": "not_actuated", "warnings": []},
        "digital_thread": {"stl_path": "/tmp/specimen.stl", "gcode_path": "/tmp/specimen.gcode.3mf"},
        "quality_gates": [],
    }

    packet = SpecimenMakingAgent()._build_specimen_fabricated_packet(
        state=state,
        candidate="candidate-preflight",
        specimen_id="specimen-preflight",
        report=report,
        decisions=[],
        evidence_refs=[],
    )

    assert packet["status"] == "preflight_ready"
    assert packet["next_action"] == "physical_start_pending_approval"
    assert packet["physical_location"] == "not_actuated"


@pytest.mark.asyncio
async def test_specimen_agent_installed_printer_uses_single_ejection_only_project_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["test_mode_autofill"] = True
    spec["printer_test_path"] = "설치 프린터"
    spec["printer_profile"] = "bambulab_x2d_pla_0p4_nozzle"
    spec["tpms_resolution"] = 18
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.LIVE,
        stage=Stage.SPECIMEN,
        active_goal="live gui test mode",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()
    captured_payloads: list[dict[str, Any]] = []

    def fake_printer_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        captured_payloads.append(payload)
        stl_path = str(payload.get("stl_path") or "")
        return {
            "ok": True,
            "tool": "printer.prepare",
            "mode": payload.get("runtime_mode", "test"),
            "printer_path": "installed_printer",
            "path": "installed_printer",
            "provider": "bambulab_x2d",
            "selected_printer": {"profile_id": "bambulab_x2d_lab_01", "provider": "bambulab_x2d"},
            "physical_transport": True,
            "specimen_id": payload.get("specimen_id"),
            "stl_path": stl_path,
            "sliced_path": "/tmp/specimen.gcode.3mf",
            "slicer_result": {"ok": True, "sliced_artifact_path": "/tmp/specimen.gcode.3mf"},
            "gcode_validation": {"ok": True, "violations": []},
            "print_result": {
                "published": True,
                "status": "started",
                "stop_after_start": False,
                "post_publish_status": {
                    "status": "running",
                    "progress_observed": True,
                    "progress_percent": 1,
                },
            },
            "ejection_result": {},
            "autoejection_patch": {
                "ok": True,
                "schema": "bambu_ejection_only_project_file.v1",
                "status": "ejection_only_validated",
            },
            "autoejection": {"enabled": True, "status": "configured", "provider": "bambu_gcode_patch"},
            "step_trace": [{"step": "BAMBU_NATIVE_AUTOEJECTION_PATCH", "status": "ok"}],
            "status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
            "ejection_only_project_file": True,
        }

    ctx.tools.register("printer.prepare", fake_printer_prepare)
    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)

    assert result.success is True
    assert captured_payloads, "SpecimenAgent must call printer.prepare for installed printer path"
    payload = captured_payloads[0]
    assert payload["test_printer_path"] == "installed_printer"
    assert payload["allow_test_printer_live"] is True
    assert payload["test_printer_transport"] == "real"
    assert payload["prefer_http_artifact"] is True
    assert payload["print"]["start_immediately"] is True
    assert payload["print"]["physical_intent"] is True
    assert payload["print"]["confirm_physical_print"] is True
    assert payload["print"]["stop_after_start"] is False
    assert payload["print"]["use_ejection_only_project_file"] is True
    assert payload["print"]["prefer_http_artifact"] is True
    assert payload["ejection"]["enabled"] is True
    assert payload["ejection"]["allow_ejection"] is True
    assert "standalone_after_start_stop" not in payload["ejection"]
    assert payload["ejection"]["use_ejection_only_project_file"] is True
    assert payload["ejection"]["source"] == "installed_printer_ejection_only_project_file"
    assert result.data["specimen_result"]["printer_path"] == "installed_printer"
    assert "printer_preflight" not in result.data
    assert "printer_preflight" not in result.data["specimen_result"]


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
    assert specimen_result["experiment_evaluation"]["job"]["device"] == "printer:fleet"
    assert specimen_result["provider"] == "prusa_mk4s"
    assert specimen_result["selected_printer"]["provider"] == "prusa_mk4s"

    fabrication_report = specimen_result["fabrication_report"]
    assert fabrication_report["schema"] == "fabrication_report.v1"
    assert fabrication_report["digital_thread"]["candidate_id"] == "cand-1-01"
    assert fabrication_report["digital_thread"]["specimen_id"] == "specimen-cand-1-01-gyroid"
    assert fabrication_report["digital_thread"]["stl_path"] == specimen_result["stl_path"]
    assert fabrication_report["digital_thread"]["gcode_path"] == specimen_result["sliced_path"]
    assert fabrication_report["process_plan"]["layer_height_mm"] == 0.2
    assert fabrication_report["process_plan"]["nozzle_diameter_mm"] == 0.4
    assert fabrication_report["process_plan"]["cap_skin_policy"]["bottom_cap_enabled"] is True
    gate_names = {gate["gate"] for gate in fabrication_report["quality_gates"]}
    assert {"required_fields", "geometry", "mesh", "manufacturability", "slicer", "gcode", "printer_storage", "execution_gate", "ejection"} <= gate_names
    assert fabrication_report["monitoring_plan"]["observe_camera_after_print"] is True
    assert fabrication_report["monitoring_plan"]["layerwise_monitoring_available"] is False
    assert fabrication_report["fabrication_outcome"]["status"] in {"virtual_finished", "ready_for_vision"}
    assert isinstance(fabrication_report["feedback_to_design"], dict)
    screen_report = result.data["specimen_agent_report"]
    expected_sections = {
        "slicer_configuration",
        "printer_profile",
        "build_queue",
        "estimated_print_time",
        "filament_usage",
        "gcode_validation",
        "print_readiness",
        "build_timeline",
        "layer_preview",
        "artifact_ledger",
        "printer_status",
        "handoff_status",
    }
    assert screen_report["schema"] == "specimen_agent_report.v1"
    assert expected_sections.issubset(screen_report)
    assert screen_report["print_readiness"]["gate_count"] >= 8
    assert screen_report["estimated_print_time"]["estimated_print_time_min"] == fabrication_report["process_plan"]["estimated_print_time_min"]
    assert screen_report["filament_usage"]["estimated_mass_g"] == fabrication_report["process_plan"]["estimated_mass_g"]
    assert screen_report["gcode_validation"]["gcode_path"] == specimen_result["sliced_path"]
    assert screen_report["layer_preview"]["stl_path"] == specimen_result["stl_path"]
    assert screen_report["artifact_ledger"]
    assert specimen_result["specimen_agent_report"] == screen_report
    assert {item["type"] for item in screen_report["visualization_manifest"]} >= {
        "layer_preview",
        "material_donut",
        "readiness_donut",
        "timeline_bars",
        "print_time_bars",
    }
    assert result.data["handoff_packet"]["schema"] == "specimen_fabricated.v1"
    assert result.data["handoff_packet"]["fabrication_report_ref"] == "run_metadata.fabrication_report"
    assert result.data["handoff_packet"]["fabrication_summary"]["stl_path"] == specimen_result["stl_path"]
    assert result.data["handoff_packet"]["fabrication_summary"]["outcome_status"] == fabrication_report["fabrication_outcome"]["status"]
    assert result.data["handoff_packet"]["consumer_agent"] == ["vision_agent", "manipulation_agent", "knowledge_agent", "bo_agent"]
    assert result.data["metrics"]["quality_gate_count"] >= 8
    assert result.data["decisions"]


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
    assert specimen_result["fabrication_report"]["schema"] == "fabrication_report.v1"
    assert specimen_result["fabrication_report"]["fabrication_outcome"]["status"] == "blocked"
    assert result.data["specimen_agent_report"]["schema"] == "specimen_agent_report.v1"
    assert result.data["specimen_agent_report"]["print_readiness"]["blocked_count"] >= 1
    assert result.data["specimen_agent_report"]["handoff_status"]["status"] == "blocked"
    assert specimen_result["specimen_agent_report"] == result.data["specimen_agent_report"]
    assert result.data["handoff_packet"]["schema"] == "specimen_fabricated.v1"
    assert result.data["handoff_packet"]["status"] == "blocked"


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
async def test_specimen_agent_live_gui_test_mode_physical_print_enables_print_tail_autoejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["test_mode_autofill"] = True
    spec["printer_test_path"] = "실제 출력"
    spec["printer_profile"] = "bambulab_x2d_pla_0p4_nozzle"
    spec["tpms_resolution"] = 18
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.LIVE,
        stage=Stage.SPECIMEN,
        active_goal="live gui test mode",
        current_experiment_spec=spec,
    )
    ctx = _CtxStub()
    captured_payloads: list[dict[str, Any]] = []

    def fake_printer_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        captured_payloads.append(payload)
        stl_path = str(payload.get("stl_path") or "")
        sliced_path = str(Path(stl_path).with_suffix(".autoeject.gcode.3mf")) if stl_path else "/tmp/specimen.autoeject.gcode.3mf"
        return {
            "ok": True,
            "tool": "printer.prepare",
            "mode": payload.get("runtime_mode", "test"),
            "printer_path": "physical_print",
            "path": "physical_print",
            "provider": "bambulab_x2d",
            "selected_printer": {"profile_id": "bambulab_x2d_lab_01", "provider": "bambulab_x2d"},
            "physical_transport": True,
            "specimen_id": payload.get("specimen_id"),
            "stl_path": stl_path,
            "sliced_path": sliced_path,
            "slicer_result": {"ok": True, "sliced_artifact_path": sliced_path, "sliced_path": sliced_path},
            "gcode_validation": {"ok": True, "violations": []},
            "slicer_settings": {"output_gcode_path": sliced_path, "printer_profile": payload.get("printer_profile")},
            "printer": {"provider": "bambulab_x2d", "state": "MOCK_READY"},
            "print_result": {"published": True, "status": "started", "stop_after_start": False},
            "ejection_result": {"ok": True, "status": "appended_to_print_gcode", "transport": "project_file"},
            "autoejection": {"enabled": True, "status": "configured", "provider": "bambu_gcode_patch"},
            "step_trace": [{"step": "BAMBU_NATIVE_AUTOEJECTION_PATCH", "status": "ok"}],
            "status": "PRINT_STARTED_WITH_AUTOEJECTION_TAIL",
        }

    ctx.tools.register("printer.prepare", fake_printer_prepare)
    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )

    result = await agent.run(state, ctx)

    assert result.success is True
    assert captured_payloads, "SpecimenAgent must call printer.prepare for physical print"
    payload = captured_payloads[0]
    assert payload["test_printer_path"] == "physical_print"
    assert payload["allow_test_printer_live"] is True
    assert payload["test_printer_transport"] == "real"
    assert payload["prefer_http_artifact"] is True
    assert payload["print"]["physical_intent"] is True
    assert payload["print"]["confirm_physical_print"] is True
    assert payload["print"]["prefer_http_artifact"] is True
    assert payload["print"]["stop_after_start"] is False
    assert payload["ejection"]["enabled"] is True
    assert payload["ejection"]["allow_ejection"] is True
    assert payload["ejection"].get("standalone_after_start_stop") in {None, False}
    assert result.data["specimen_result"]["printer_path"] == "physical_print"


@pytest.mark.asyncio
async def test_specimen_agent_virtual_bridge_degrades_on_windows_slicer_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SpecimenMakingAgent()
    spec = _valid_spec()
    spec["test_mode_autofill"] = True
    spec["printer_test_path"] = "virtual_bridge"
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

    def raise_oserror(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OSError(193, "%1 is not a valid Win32 application")

    monkeypatch.setattr(
        SpecimenMakingAgent,
        "_artifact_dir",
        staticmethod(lambda _state, specimen_id: tmp_path / specimen_id),
    )
    monkeypatch.setattr(PrusaSlicerRunner, "slice", raise_oserror)

    result = await agent.run(state, ctx)
    specimen_result = result.data["specimen_result"]
    screen_report = result.data["specimen_agent_report"]

    assert result.success is True
    assert specimen_result["ok"] is True
    assert specimen_result["printer_path"] == "virtual_bridge"
    assert specimen_result["printer_prepare_status"] == "virtual_bridge_degraded"
    assert specimen_result["slicer_result"]["status"] == "degraded_virtual_slice"
    assert specimen_result["gcode_validation"]["status"] == "degraded_virtual_validation"
    assert specimen_result["experiment_evaluation"]["status"] == "evaluated_degraded"
    assert screen_report["schema"] == "specimen_agent_report.v1"
    assert screen_report["handoff_status"]["status"] in {"ready", "virtual_finished", "ready_for_vision"}


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
