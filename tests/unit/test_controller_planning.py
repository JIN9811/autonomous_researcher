"""
Unit tests for Live GUI planning handoff adaptation.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

import pytest

from agents.base_agent import AgentResult
from app.bootstrap import load_runtime
from graphs import load_graph_config
from orchestrator.state import Mode, Stage


def test_live_gui_test_mode_flags_survive_design_adaptation() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-test",
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
        },
    )

    assert spec["test_mode_autofill"] is True
    assert spec["test_mode_llm_generated"] is True
    assert spec["layer_height_mm"] == 0.2
    assert spec["nozzle_diameter_mm"] == 0.4
    assert spec["printer_model"] == "Bambu Lab X2D"
    assert spec["storage"] == "ftps"
    assert spec["cell_size_mm"] == 10.0
    assert spec["print"]["start_immediately"] is False
    assert spec["print"]["physical_intent"] is False
    assert "printer_test_path" not in spec


def test_live_gui_regenerates_specimen_id_when_geometry_is_overridden() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-mismatch",
            "geometry_type": "honeycomb",
            "specimen_id": "specimen-cand-mismatch-honeycomb-old",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
        },
    )

    assert spec["geometry_type"] == "gyroid"
    assert "honeycomb" not in spec["specimen_id"]
    assert "gyroid" in spec["specimen_id"]


def test_equipment_alert_merge_persists_incident_records_and_guardian_event() -> None:
    controller = load_runtime()
    original_metadata = dict(controller._state.run_metadata)
    original_health = dict(controller._state.device_health)
    incident_id = "incident-equipment-merge-001"
    incident = {
        "schema": "incident_record.v1",
        "incident_id": incident_id,
        "device_class": "utm",
        "component": "utm_data_export",
        "failure_code": "UTM_DATA_TIMEOUT",
        "corrective_action": "Check Windows UTM export folder and retry the protocol.",
    }
    alert = {
        "schema": "hardware_alert.v1",
        "alert_id": "alert-equipment-merge-001",
        "device_class": "utm",
        "component": "utm_data_export",
        "severity": "blocking",
        "failure_code": "UTM_DATA_TIMEOUT",
        "status": "blocked",
        "blocks_workflow": True,
        "requires_ack": True,
        "guardian_decision": {
            "schema": "guardian_decision.v1",
            "decision": "safe_stop",
            "requires_human_approval": True,
            "risk_score": 0.82,
        },
        "incident_record": incident,
    }
    try:
        controller._state.run_metadata.pop("incident_records", None)
        controller._state.run_metadata.pop("hardware_alerts", None)
        controller._merge_planning_agent_data(
            Stage.EQUIPMENT,
            {
                "equipment_result": {
                    "ok": False,
                    "status": "blocked",
                    "program_id": "utm_compression_start_v1",
                    "failure_code": "UTM_DATA_TIMEOUT",
                },
                "equipment_report": {
                    "schema": "equipment_report.v1",
                    "decision": {"handoff_status": "blocked", "failure_code": "UTM_DATA_TIMEOUT"},
                },
                "utm_data_ready": {"schema": "utm_data_ready.v1", "status": "blocked", "guardian_status": "block"},
                "hardware_alerts": [alert],
                "incident_records": [incident],
            },
        )

        stored_incidents = controller._state.run_metadata["incident_records"]
        assert [item["incident_id"] for item in stored_incidents if item.get("incident_id") == incident_id] == [incident_id]
        assert controller._state.run_metadata["hardware_alerts"][0]["alert_id"] == "alert-equipment-merge-001"
        assert controller._state.run_metadata["latest_guardian_decision"]["schema"] == "guardian_decision.v1"
        assert controller._state.device_health["utm"] == "blocking:UTM_DATA_TIMEOUT"
        guardian_log = controller._logger_bundle.run_dir / "guardian_events.jsonl"
        assert guardian_log.exists()
        assert incident_id in guardian_log.read_text(encoding="utf-8")
    finally:
        controller._state.run_metadata.clear()
        controller._state.run_metadata.update(original_metadata)
        controller._state.device_health.clear()
        controller._state.device_health.update(original_health)


def test_live_gui_test_defaults_use_3dp_gui_saved_test_size(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()

    monkeypatch.setattr(
        "app.controller.load_prusa_print_profile",
        lambda: {
            "material": "PLA",
            "printer_model": "Prusa MK4S",
            "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
            "slicer_profile_hint": "0.2mm_quality",
            "nozzle_diameter_mm": 0.4,
            "layer_height_mm": 0.2,
            "first_layer_height_mm": 0.2,
            "slow_first_layer_enabled": True,
            "first_layer_speed_mm_s": 10.0,
            "bed_temperature_c": 60.0,
            "first_layer_bed_temperature_c": 65.0,
            "storage": "usb",
            "max_print_time_min": 120.0,
            "overwrite": True,
            "start_immediately_live": True,
            "allow_ejection": False,
            "skirt_enabled": False,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "skin_thickness_mm": 0.0,
            "require_flat_compression_faces": False,
            "test_specimen_size_mm": [22.0, 24.0, 26.0],
            "test_unit_cell_size_mm": 6.5,
            "notes": "",
        },
    )

    defaults = controller._default_test_constraints({})

    assert defaults["specimen_size_mm"] == [22.0, 24.0, 26.0]
    assert defaults["max_specimen_size_mm"] == [22.0, 24.0, 26.0]
    assert defaults["cell_size_mm"] == 6.5
    assert defaults["first_layer_height_mm"] == 0.2
    assert defaults["slow_first_layer_enabled"] is True
    assert defaults["bed_temperature_c"] == 60.0
    assert defaults["first_layer_bed_temperature_c"] == 65.0
    assert defaults["top_cap_enabled"] is False
    assert defaults["bottom_cap_enabled"] is False
    assert defaults["top_bottom_cap"] is False
    assert defaults["skin_thickness_mm"] == 0.0
    assert defaults["require_flat_compression_faces"] is False


def test_live_gui_live_spec_uses_active_bambu_bridge_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    monkeypatch.setattr(
        "app.controller.load_prusa_print_profile",
        lambda: {
            "material": "PLA",
            "printer_model": "Prusa MK4S",
            "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
            "slicer_profile_hint": "0.2mm_quality",
            "nozzle_diameter_mm": 0.4,
            "layer_height_mm": 0.2,
            "storage": "usb",
            "max_print_time_min": 120.0,
            "overwrite": True,
            "start_immediately_live": True,
            "allow_ejection": False,
            "skirt_enabled": False,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "skin_thickness_mm": 0.0,
            "require_flat_compression_faces": False,
            "notes": "",
        },
    )

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-live",
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "material": "PLA",
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
            "objective_type": "specific_energy_absorption",
        },
    )

    assert spec["printer_model"] == "Bambu Lab X2D"
    assert spec["printer_profile"] == "bambulab_x2d_pla_0p4_nozzle"
    assert spec["slicer_profile_hint"] == "0.2mm_quality"
    assert spec["nozzle_diameter_mm"] == 0.4
    assert spec["layer_height_mm"] == 0.2
    assert spec["storage"] == "ftps"
    assert spec["print"]["storage"] == "ftps"
    assert spec["print"]["start_immediately"] is False
    assert spec["print"]["confirm_physical_print"] is False
    assert spec["ejection"]["enabled"] is False
    assert spec["top_cap_enabled"] is False
    assert spec["bottom_cap_enabled"] is False
    assert spec["top_bottom_cap"] is False


def test_planning_specimen_display_preserves_bambu_spc_bridge_evidence() -> None:
    controller = load_runtime()
    specimen = {
        "specimen_id": "specimen-cand-1-01-gyroid",
        "candidate_id": "cand-1-01",
        "printer_prepare_status": "HTTP_ARTIFACT_READY_NOT_STARTED",
        "printer_mode": "live",
        "printer_path": "http_artifact",
        "fabrication_report": {
            "schema": "fabrication_report.v1",
            "fabrication_intent": {"printer_path": "http_artifact", "physical_intent": True},
            "digital_thread": {"specimen_id": "specimen-cand-1-01-gyroid", "gcode_path": "/tmp/specimen.3mf"},
            "printer_runtime": {
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
                "autoejection": {"status": "not_configured", "blockers": ["BAMBU_AUTOEJECTION_PROVIDER_REQUIRED"]},
                "autoejection_handoff": {
                    "schema": "bambu_autoejection_provider_handoff.v1",
                    "recommended_consumer_agent": "ManipulationAgent",
                    "next_tool": "lerobot.manipulation-agent.run",
                    "motion_started": False,
                },
            },
        },
        "tool_result": {
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
            "autoejection": {"status": "not_configured", "blockers": ["BAMBU_AUTOEJECTION_PROVIDER_REQUIRED"]},
            "autoejection_handoff": {
                "schema": "bambu_autoejection_provider_handoff.v1",
                "recommended_consumer_agent": "ManipulationAgent",
                "next_tool": "lerobot.manipulation-agent.run",
                "motion_started": False,
            },
        },
    }

    compact = controller._planning_display_specimen_result(specimen)

    assert compact["selected_printer"]["provider"] == "bambulab_x2d"
    assert compact["device_screen"]["actions"]["can_start_print"] is True
    assert compact["preprint_gate"]["state"] == "http_artifact_ready_not_started"
    assert compact["readiness_levels"][1]["level_id"] == "operator_approval"
    assert compact["autoejection"]["blockers"] == ["BAMBU_AUTOEJECTION_PROVIDER_REQUIRED"]
    assert compact["autoejection_handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert compact["autoejection_handoff"]["motion_started"] is False
    runtime = compact["fabrication_report"]["printer_runtime"]
    assert runtime["selected_printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert runtime["preprint_gate"]["technical_ready_for_start"] is True
    assert runtime["autoejection_handoff"]["next_tool"] == "lerobot.manipulation-agent.run"


def test_live_gui_text_parser_routes_explicit_bambu_choice_to_bambu_bridge() -> None:
    controller = load_runtime()

    values = controller._extract_design_values_from_text(
        "PLA 30 x 30 x 30 mm gyroid 시편. 프린터는 Bambu Lab X2D, nozzle 0.4 mm, layer 0.2 mm."
    )

    assert values["printer_model"] == "Bambu Lab X2D"
    assert values["printer_profile_id"] == "bambulab_x2d_lab_01"
    assert values["printer_profile"] == "bambulab_x2d_pla_0p4_nozzle"
    assert values["storage"] == "ftps"
    assert values["print"]["storage"] == "ftps"


def test_live_gui_live_spec_uses_saved_printer_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    monkeypatch.setattr(
        "app.controller.load_prusa_print_profile",
        lambda: {
            "material": "PETG",
            "printer_model": "Prusa MK4S",
            "printer_profile": "petg_quality_0p4",
            "slicer_profile_hint": "0.15mm_quality",
            "nozzle_diameter_mm": 0.6,
            "layer_height_mm": 0.15,
            "storage": "usb",
            "max_print_time_min": 180.0,
            "overwrite": False,
            "start_immediately_live": False,
            "allow_ejection": True,
            "notes": "",
        },
    )

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-live-profile",
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30, 30, 30],
            "objective_type": "specific_energy_absorption",
        },
    )

    assert spec["material"] == "PETG"
    assert spec["printer_model"] == "Bambu Lab X2D"
    assert spec["printer_profile"] == "bambulab_x2d_pla_0p4_nozzle"
    assert spec["slicer_profile_hint"] == "0.15mm_quality"
    assert spec["nozzle_diameter_mm"] == 0.6
    assert spec["layer_height_mm"] == 0.15
    assert spec["max_print_time_min"] == 180.0
    assert spec["print"]["overwrite"] is False
    assert spec["print"]["start_immediately"] is False
    assert spec["print"]["physical_intent"] is False
    assert spec["ejection"]["enabled"] is False


def test_live_gui_test_spec_uses_saved_auto_ejection_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    monkeypatch.setattr(
        "app.controller.load_prusa_print_profile",
        lambda: {
            "material": "PLA",
            "printer_model": "Prusa MK4S",
            "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
            "slicer_profile_hint": "0.2mm_quality",
            "nozzle_diameter_mm": 0.4,
            "layer_height_mm": 0.2,
            "storage": "usb",
            "max_print_time_min": 120.0,
            "overwrite": True,
            "start_immediately_live": True,
            "allow_ejection": True,
            "notes": "",
        },
    )

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-test-eject",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
        },
    )

    assert spec["test_mode_llm_generated"] is True
    assert spec["ejection"]["enabled"] is False


def test_specimen_runtime_message_focuses_on_slicer_and_printer_bridge() -> None:
    controller = load_runtime()
    content = controller._format_specimen_runtime_message(
        {"specimen_id": "sp-1", "printer_profile": "prusa_mk4s_pla_0p4_nozzle", "material": "PLA"},
        {
            "specimen_id": "sp-1",
            "printer_prepare_status": "simulated_printed",
            "printer_mode": "test_printer_live_virtual",
            "printer_path": "virtual_prusalink",
            "stl_path": "/tmp/sp-1.stl",
            "sliced_path": "/tmp/sp-1.gcode",
            "slicer_settings": {
                "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
                "material": "PLA",
                "slicer_profile_hint": "0.2mm_quality",
                "layer_height_mm": 0.2,
                "relative_density": 0.32,
                "expected_mass_g": 6.026,
                "output_gcode_path": "/tmp/sp-1.gcode",
                "resolved_command": ["prusa-slicer", "--export-gcode", "/tmp/sp-1.stl"],
            },
            "prusalink": {"transport": "virtual", "upload_endpoint": "/api/v1/files/usb/sp-1.gcode"},
            "step_trace": [{"step": "SLICE", "status": "ok"}, {"step": "UPLOAD", "status": "ok"}],
            "print_result": {"status": "virtual_finished"},
            "ejection_result": {"status": "disabled"},
        },
    )

    assert "Slicer / artifact 적용 설정값" in content
    assert "layer_height_mm: 0.2" in content
    assert "expected_mass_g: 6.026" in content
    assert "transfer_endpoint: /api/v1/files/usb/sp-1.gcode" in content
    assert "Printer Bridge 결과" in content
    assert "[ok] SLICE" in content
    assert "STL 형상 확인은 Design Agent artifact" in content


@pytest.mark.asyncio
async def test_printer_choice_routes_to_specimen_agent_when_pending_connection_info(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-test",
        "specimen_id": "specimen-test",
        "geometry_type": "lattice_bcc",
        "specimen_size_mm": [30, 30, 30],
    }
    controller._state.run_metadata["pending_specimen_input"] = {
        "type": "printer_connection_info",
        "specimen_id": "specimen-test",
        "input_request": {"type": "printer_connection_info"},
    }
    captured: dict[str, object] = {}

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        captured.update(experiment_spec)
        return {"ok": True, "message": "resumed", "session": controller.planning_snapshot(session_id=session_id)}

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)

    result = await controller._planning_message_locked(
        message="가상 브릿지",
        goal=None,
        constraints={},
        session_id="s-test",
    )

    assert result["ok"] is True
    assert captured["printer_test_path"] == "virtual_bridge"
    assert captured["test_printer_transport"] == "virtual"
    assert captured["test_mode_autofill"] is True
    assert captured["test_mode_llm_generated"] is True


@pytest.mark.asyncio
async def test_printer_choice_routes_to_specimen_agent_when_pending_state_was_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-test",
        "specimen_id": "specimen-test",
        "geometry_type": "lattice_bcc",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
    }
    captured: dict[str, object] = {}

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        captured.update(experiment_spec)
        return {"ok": True, "message": "resumed", "session": controller.planning_snapshot(session_id=session_id)}

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)

    result = await controller._planning_message_locked(
        message="설치 프린터",
        goal=None,
        constraints={},
        session_id="s-test",
    )

    assert result["ok"] is True
    assert captured["printer_test_path"] == "installed_printer"
    assert captured["test_printer_transport"] == "real"
    assert captured["allow_test_printer_live"] is True


@pytest.mark.asyncio
async def test_actual_print_choice_promotes_test_specimen_to_physical_print(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-test",
        "specimen_id": "specimen-test",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "print": {"start_immediately": False},
    }
    captured: dict[str, object] = {}

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        captured.update(experiment_spec)
        return {"ok": True, "message": "resumed", "session": controller.planning_snapshot(session_id=session_id)}

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)

    result = await controller._planning_message_locked(
        message="실제 출력",
        goal=None,
        constraints={},
        session_id="s-test",
    )

    assert result["ok"] is True
    assert captured["printer_test_path"] == "physical_print"
    assert captured["test_printer_transport"] == "real"
    assert captured["allow_test_printer_live"] is True
    print_request = captured["print"]
    assert isinstance(print_request, dict)
    assert print_request["start_immediately"] is True
    assert print_request["physical_intent"] is True
    assert print_request["confirm_physical_print"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "choice", "transport", "physical"),
    [
        ("테스트 모드, 가상 브릿지", "virtual_bridge", "virtual", False),
        ("테스트 모드, 설치 프린터", "installed_printer", "real", False),
        ("테스트 모드, 실제 출력", "physical_print", "real", True),
    ],
)
async def test_live_gui_test_mode_inline_printer_choice_handoffs_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    choice: str,
    transport: str,
    physical: bool,
) -> None:
    controller = load_runtime()
    monkeypatch.setattr(
        "app.controller.load_prusa_print_profile",
        lambda: {
            "material": "PLA",
            "printer_model": "Prusa MK4S",
            "printer_profile": "prusa_mk4s_pla_0p4_nozzle",
            "slicer_profile_hint": "0.2mm_quality",
            "nozzle_diameter_mm": 0.4,
            "layer_height_mm": 0.2,
            "first_layer_height_mm": 0.2,
            "slow_first_layer_enabled": True,
            "first_layer_speed_mm_s": 10.0,
            "bed_temperature_c": 60.0,
            "first_layer_bed_temperature_c": 60.0,
            "storage": "usb",
            "max_print_time_min": 120.0,
            "overwrite": True,
            "start_immediately_live": True,
            "allow_ejection": False,
            "skirt_enabled": False,
            "top_cap_enabled": False,
            "bottom_cap_enabled": True,
            "top_bottom_cap": True,
            "skin_thickness_mm": 0.8,
            "require_flat_compression_faces": False,
            "test_specimen_size_mm": [30.0, 30.0, 30.0],
            "test_unit_cell_size_mm": 10.0,
            "notes": "",
        },
    )
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {}
    controller._state.run_metadata.pop("pending_specimen_input", None)
    captured: dict[str, object] = {}

    async def fake_complete(*, prompt: str):
        return (
            SimpleNamespace(
                text=(
                    "테스트 실험값을 생성했습니다.\n"
                    "```json\n"
                    "{\"goal\":\"fake test\",\"constraints\":{\"cell_size_mm\":5.0,"
                    "\"geometry_type\":\"lattice_bcc\",\"print\":{\"start_immediately\":true}}}\n"
                    "```"
                ),
                raw={},
                model="fake-orchestrator",
            ),
            "ok",
        )

    async def fake_handoff(*, goal: str | None, constraints: dict) -> dict:
        captured["goal"] = goal
        captured["constraints"] = constraints
        return {"ok": True, "message": "handoff", "session": controller.planning_snapshot(session_id="s-inline")}

    monkeypatch.setattr(controller, "_complete_live_planning_prompt", fake_complete)
    monkeypatch.setattr(controller, "_handoff_planning_to_design", fake_handoff)

    result = await controller._planning_message_locked(
        message=message,
        goal=None,
        constraints={},
        session_id="s-inline",
    )
    for _ in range(10):
        if captured:
            break
        await asyncio.sleep(0)

    constraints = captured["constraints"]
    assert result["ok"] is True
    assert isinstance(constraints, dict)
    assert constraints["geometry_type"] == "gyroid"
    assert constraints["cell_size_mm"] == 10.0
    assert constraints["printer_test_path"] == choice
    assert constraints["test_printer_transport"] == transport
    assert constraints["allow_test_printer_live"] is (choice != "virtual_bridge")
    print_request = constraints["print"]
    assert isinstance(print_request, dict)
    assert print_request["start_immediately"] is physical
    assert print_request["physical_intent"] is physical
    assert print_request["confirm_physical_print"] is physical
    assert constraints["top_cap_enabled"] is False
    assert constraints["bottom_cap_enabled"] is True
    assert constraints["top_bottom_cap"] is True
    assert constraints["require_flat_compression_faces"] is False
    assert constraints["skin_thickness_mm"] == 0.8
    assert not controller._state.run_metadata.get("pending_specimen_input")


@pytest.mark.asyncio
async def test_live_gui_test_mode_virtual_bridge_handoff_returns_before_loop_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    release_handoff = asyncio.Event()
    handoff_started = asyncio.Event()

    async def fake_complete(*, prompt: str):
        return (
            SimpleNamespace(
                text=(
                    "테스트 실험값을 생성했습니다.\n"
                    "```json\n"
                    "{\"goal\":\"background virtual bridge test\",\"constraints\":{\"cell_size_mm\":10.0,\"geometry_type\":\"gyroid\",\"specimen_size_mm\":[30,30,30]}}\n"
                    "```"
                ),
                raw={},
                model="fake-orchestrator",
            ),
            "ok",
        )

    async def fake_handoff(*, goal: str | None, constraints: dict) -> dict:
        handoff_started.set()
        await release_handoff.wait()
        return {"ok": True, "message": "handoff completed", "session": controller.planning_snapshot(session_id="s-bg")}

    monkeypatch.setattr(controller, "_complete_live_planning_prompt", fake_complete)
    monkeypatch.setattr(controller, "_handoff_planning_to_design", fake_handoff)

    result = await asyncio.wait_for(
        controller._planning_message_locked(
            message="테스트 모드, 가상 브릿지",
            goal=None,
            constraints={},
            session_id="s-bg",
        ),
        timeout=1.0,
    )

    assert result["ok"] is True
    assert result["message"] == "Planning handoff started in background."
    assert controller._planning_handoff_task is not None
    await asyncio.wait_for(handoff_started.wait(), timeout=1.0)
    assert not controller._planning_handoff_task.done()

    release_handoff.set()
    await asyncio.wait_for(controller._planning_handoff_task, timeout=1.0)


@pytest.mark.asyncio
async def test_planning_tail_continues_original_loop_after_specimen() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-tail",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        },
    )
    controller._state.current_experiment_spec = spec
    controller._state.run_metadata["specimen_result"] = {
        "ok": True,
        "candidate_id": spec["candidate_id"],
        "specimen_id": spec["specimen_id"],
        "handoff_status": "ready",
        "stl_path": "/tmp/specimen-tail.stl",
    }

    result = await controller._run_planning_loop_tail(spec)

    assert result["ok"] is True
    assert controller._state.mode == Mode.LIVE
    assert controller._state.stage == Stage.COMPLETE
    assert controller._state.latest_observations["transfer_readiness"]["ready"] is True
    assert controller._state.run_metadata["manipulation_result"]["ok"] is True
    assert controller._state.run_metadata["equipment_handoff"]["status"] == "ready_for_analysis"
    assert controller._state.latest_analysis["cae_result"]["ok"] is True
    roles = [message["role"] for message in controller.planning_snapshot()["messages"]]
    assert "vision_ai" in roles
    assert "manipulation_ai" in roles
    assert "equipment_ai" in roles
    assert "analysis_ai" in roles
    assert "knowledge_ai" in roles
    assert "bo_ai" in roles
    assert "guardian" in roles
    assert controller._state.run_metadata["bo_agent"]["knowledge_context"]
    events = controller.recent_events()
    assert any(event.get("type") == "node.completed" and event.get("node_id") == "bo" for event in events)
    assert any(event.get("type") == "module.step.planned" and event.get("node_id") == "vision" for event in events)
    assert any(
        message.get("module_runtime", {}).get("module_id") == "vision"
        for message in controller.planning_snapshot()["messages"]
    )


@pytest.mark.asyncio
async def test_specimen_retry_merges_result_before_loop_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-retry-tail",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        },
    )
    controller._state.current_experiment_spec = spec

    class FakeSpecimenAgent:
        name = "specimen_agent"

        async def run(self, state, ctx):  # noqa: ANN001
            return AgentResult(
                success=True,
                summary="fake specimen ready",
                data={
                    "protocol_note": "fake specimen",
                    "specimen_result": {
                        "ok": True,
                        "candidate_id": spec["candidate_id"],
                        "specimen_id": spec["specimen_id"],
                        "handoff_status": "ready",
                        "printer_prepare_status": "simulated_printed",
                        "printer_path": "virtual_prusalink",
                        "stl_path": "/tmp/specimen-retry-tail.stl",
                        "sliced_path": "/tmp/specimen-retry-tail.gcode",
                    },
                },
            )

    async def fake_loop_tail(experiment_spec: dict, **_: object) -> dict:
        specimen = controller._state.run_metadata.get("specimen_result")
        assert isinstance(specimen, dict)
        assert specimen["specimen_id"] == spec["specimen_id"]
        return {"ok": True, "message": "tail completed", "decision": "continue"}

    controller._deps.agent_registry.register(FakeSpecimenAgent())
    monkeypatch.setattr(controller, "_run_planning_loop_tail", fake_loop_tail)

    result = await controller._run_specimen_guardian_tail(spec)

    assert result["ok"] is True
    system_messages = [message["content"] for message in controller.planning_snapshot()["messages"] if message["role"] == "system"]
    assert "SYSTEM_EVENT: HANDOFF\nfrom=OperatorInput\nto=SpecimenMakingAgent\nstatus=retry" in system_messages
    assert all("원래" not in content for content in system_messages)
    assert all("Handoff:" not in content for content in system_messages)
    assert any(
        event.get("type") == "node.completed" and event.get("node_id") == "specimen"
        for event in controller.recent_events()
    )


def test_planning_system_handoff_message_is_structured() -> None:
    content = load_runtime()._planning_stage_handoff_text("Specimen Making Agent", Stage.VISION)

    assert content == "SYSTEM_EVENT: HANDOFF\nfrom=Specimen Making Agent\nto=Vision Agent\nstatus=started"


def _write_graph_with_transition(tmp_path: Path, source: str, target: str) -> Path:
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    payload = config.model_dump(mode="json")
    payload["transitions"][source] = target
    graph_path = tmp_path / f"atr_{source}_to_{target}.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")
    return graph_path


def _write_graph_with_custom_quality_stage(tmp_path: Path) -> Path:
    module_dir = tmp_path / "modules" / "custom_quality"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "module.yaml").write_text(
        yaml.safe_dump(
            {
                "module": {
                    "id": "custom_quality",
                    "label": "Custom Quality Gate Module",
                    "handler": "agent.custom_quality_agent",
                    "io_contract": {
                        "input": "Specimen handoff plus quality camera metrics",
                        "output": ["quality_metrics", "handoff_packet"],
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    payload = config.model_dump(mode="json")
    payload["nodes"].append(
        {
            "id": "custom_quality_gate_node",
            "label": "Custom Quality Gate",
            "handler": "agent.custom_quality_agent",
            "stage": "custom_quality_gate",
            "kind": "agent",
            "description": "Custom quality inspection inserted by graph config.",
            "module_id": "modules/custom_quality",
            "position": {"x": 820.0, "y": 420.0},
            "metadata": {"icon": "guardian"},
        }
    )
    payload["stage_dispatch"]["custom_quality_gate"] = "custom_quality_gate_node"
    payload["transitions"]["specimen"] = "custom_quality_gate"
    payload["transitions"]["custom_quality_gate"] = "guardian"
    graph_path = tmp_path / "atr_with_custom_quality_gate.yaml"
    graph_path.write_text(yaml.safe_dump({"graph": payload}, sort_keys=False), encoding="utf-8")
    return graph_path


def test_live_gui_planning_route_text_uses_active_graph_config(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._active_graph_config_path = _write_graph_with_transition(tmp_path, "specimen", "analysis")

    route = controller._active_graph_stage_route_text(Stage.DESIGN, stop_at=Stage.GUARDIAN)
    contract = controller._live_runtime_contract_context()

    assert "Design Agent -> Specimen Making Agent -> Analysis Agent" in route
    assert "Vision Agent" not in route
    assert f"Active graph stage order is {route}." in contract
    assert controller._planning_tail_start_stage() == Stage.ANALYSIS


def test_orchestrator_plan_uses_active_graph_route_with_custom_stage(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._active_graph_config_path = _write_graph_with_custom_quality_stage(tmp_path)
    controller._state.stage = Stage.DESIGN
    controller._state.run_metadata.pop("latest_orchestration_plan", None)
    controller._state.run_metadata.pop("latest_orchestrator_control_plane", None)

    snapshot = controller.snapshot()

    plan = snapshot["state"]["run_metadata"]["latest_orchestration_plan"]
    route_stages = [step["stage"] for step in plan["route"]]
    assert route_stages[:4] == ["design", "specimen", "custom_quality_gate", "guardian"]
    custom_step = next(step for step in plan["route"] if step["stage"] == "custom_quality_gate")
    assert custom_step["agent"] == "custom_quality_agent"
    assert custom_step["label"] == "Custom Quality Gate"
    assert custom_step["required_outputs"] == ["quality_metrics", "handoff_packet"]
    control_plane = snapshot["state"]["run_metadata"]["latest_orchestrator_control_plane"]
    assert control_plane["route_state"]["route_count"] == len(plan["route"])
    assert any(item["stage"] == "custom_quality_gate" for item in control_plane["task_queue"]["items"])


def test_custom_planning_stage_role_uses_module_handler(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._active_graph_config_path = _write_graph_with_custom_quality_stage(tmp_path)
    custom_stage = Stage("custom_quality_gate")
    module_runtime = controller._module_runtime_for_stage(custom_stage)

    assert controller._planning_stage_role(custom_stage, module_runtime) == "custom_quality_agent"
    assert controller._planning_stage_label(custom_stage, module_runtime) == "Custom Quality Gate"


def test_live_gui_printer_defaults_follow_active_bambu_fleet_profile() -> None:
    controller = load_runtime()

    defaults = controller._validated_printer_defaults()

    assert defaults["printer_model"] == "Bambu Lab X2D"
    assert defaults["printer_profile"] == "bambulab_x2d_pla_0p4_nozzle"
    assert defaults["storage"] == "ftps"
    assert defaults["start_immediately_live"] is False
    assert defaults["allow_ejection"] is False


@pytest.mark.asyncio
async def test_live_gui_orchestrator_prompt_describes_selected_bambu_bridge() -> None:
    controller = load_runtime()

    prompt = await controller._build_live_orchestrator_prompt(
        operator_message="실험 수행",
        goal="TPMS 압축 시편",
        constraints={},
    )

    assert "Bambu Lab X2D" in prompt
    assert "selected printer bridge" in prompt
    assert "SPC Readiness" in prompt
    assert "PrusaLink upload/start" not in prompt


@pytest.mark.asyncio
async def test_live_gui_test_prompt_uses_active_graph_config_route(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._active_graph_config_path = _write_graph_with_transition(tmp_path, "specimen", "analysis")

    prompt = await controller._build_test_mode_orchestrator_prompt(
        operator_message="테스트 모드",
        goal="unit test",
        constraints={},
    )

    assert "Runtime pipeline after DesignAgent handoff: Design Agent -> Specimen Making Agent -> Analysis Agent" in prompt
    assert "Specimen Making Agent -> Vision Agent" not in prompt


@pytest.mark.asyncio
async def test_first_live_gui_test_design_cycle_uses_single_artifact() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    spec = await controller._run_planning_design_stage(
        previous_spec={},
        design_constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        },
        cycle_index=1,
        total_cycles=5,
        emit_handoff=False,
    )

    design_message = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "design_ai"][-1]

    assert spec["specimen_id"]
    assert "artifact_pair" not in design_message
    assert design_message.get("artifacts", {}).get("stl_url")
    assert "생성된 형상" in design_message["content"]
    assert "이전 형상" not in design_message["content"]
    assert any(
        event.get("type") == "node.completed" and event.get("node_id") == "design"
        for event in controller.recent_events()
    )


@pytest.mark.asyncio
async def test_live_gui_test_planning_series_runs_five_design_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-series-1",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        },
    )
    controller._state.current_experiment_spec = spec
    controller._state.run_metadata["specimen_result"] = {
        "ok": True,
        "candidate_id": spec["candidate_id"],
        "specimen_id": spec["specimen_id"],
        "handoff_status": "ready",
        "stl_path": "/tmp/specimen-series-1.stl",
    }

    async def fake_specimen_stage(experiment_spec: dict, *, emit_handoff: bool = True) -> dict:
        controller._merge_planning_agent_data(
            Stage.SPECIMEN,
            {
                "specimen_result": {
                    "ok": True,
                    "candidate_id": experiment_spec["candidate_id"],
                    "specimen_id": experiment_spec["specimen_id"],
                    "handoff_status": "ready",
                    "stl_path": f"/tmp/{experiment_spec['specimen_id']}.stl",
                }
            },
        )
        return {"pending": False}

    monkeypatch.setattr(controller, "_run_planning_specimen_stage", fake_specimen_stage)

    result = await controller._run_planning_cycle_series(
        first_spec=spec,
        design_constraints={**dict(spec.get("constraints", {})), **spec},
        start_cycle=1,
    )

    assert result["ok"] is True
    assert controller._state.loop_count == 5
    design_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "design_ai"]
    assert len(design_messages) == 4
    assert all(message.get("artifact_pair", {}).get("previous") for message in design_messages)
    assert all(message.get("artifact_pair", {}).get("next") for message in design_messages)
    signatures = {
        (
            message["experiment_spec"].get("relative_density"),
            message["experiment_spec"].get("wall_thickness_mm"),
            message["experiment_spec"].get("orientation_deg"),
            message["experiment_spec"].get("anisotropy_ratio"),
            message["experiment_spec"].get("tpms_thickness"),
        )
        for message in design_messages
    }
    assert len(signatures) > 1
    assert controller._state.run_metadata["bo_agent"]["knowledge_context"]
    assert controller._state.current_experiment_spec["cell_size_mm"] == spec["cell_size_mm"]
    assert controller._state.current_experiment_spec["top_bottom_cap"] is False
    assert controller._state.current_experiment_spec["test_loop_surface_caps_disabled"] is True
    assert "cell_size_mm" not in controller._state.run_metadata["bo_recommended_constraints"]
    bo_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "bo_ai"]
    assert bo_messages
    bo_trace = bo_messages[-1]["bo_result"]["benchmark"]["strategies"]["bo"]["surrogate_trace"]
    assert bo_trace
    assert bo_trace[-1]["selected"]["candidate_id"]
    analysis_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "analysis_ai"]
    assert any(message.get("fem_artifacts", {}).get("contour_url") for message in analysis_messages)


@pytest.mark.asyncio
async def test_live_gui_experiment_trigger_requests_missing_design_values(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    async def fail_handoff(*, goal: str | None, constraints: dict) -> dict:
        raise AssertionError("Design handoff should not run with missing values.")

    monkeypatch.setattr(controller, "_handoff_planning_to_design", fail_handoff)

    result = await controller._planning_message_locked(
        message="실험 수행",
        goal=None,
        constraints={},
        session_id="s-missing",
    )

    assert result["ok"] is True
    assert result["message"] == "Design handoff requires operator inputs."
    last_message = controller._planning_messages[-1]
    assert last_message["requires_design_inputs"] is True
    assert "현재 확인된 값" in last_message["content"]
    assert "추가로 필요한 값" in last_message["content"]
    missing_fields = {item["key"] for item in last_message["missing_design_inputs"]}
    assert {"objective", "specimen_size_mm", "geometry_or_domain"} <= missing_fields
    assert "Bambu Lab X2D" in last_message["content"]


@pytest.mark.asyncio
async def test_live_gui_experiment_trigger_uses_session_values(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._planning_messages.append(
        {
            "role": "operator",
            "content": (
                "PLA로 30 x 30 x 30 mm bending-dominated lattice 압축 시편을 만들고 "
                "specific energy absorption을 최대화하고 싶어. 프린터는 Prusa MK4S, nozzle 0.4 mm, layer 0.2 mm."
            ),
            "constraints": {},
        }
    )
    captured: dict[str, object] = {}

    async def fake_handoff(*, goal: str | None, constraints: dict) -> dict:
        captured["goal"] = goal
        captured["constraints"] = constraints
        return {"ok": True, "message": "handoff", "session": controller.planning_snapshot(session_id="s-ready")}

    monkeypatch.setattr(controller, "_handoff_planning_to_design", fake_handoff)

    result = await controller._planning_message_locked(
        message="실험 수행",
        goal=None,
        constraints={},
        session_id="s-ready",
    )

    constraints = captured["constraints"]
    assert result["ok"] is True
    assert "specific energy absorption" in captured["goal"]
    assert constraints["material"] == "PLA"
    assert constraints["specimen_size_mm"] == [30.0, 30.0, 30.0]
    assert constraints["max_specimen_size_mm"] == [30.0, 30.0, 30.0]
    assert constraints["experiment_domain"] == "bending_dominated_lattice"
    assert constraints["geometry_type"] == "gyroid"
    assert constraints["printer_model"] == "Prusa MK4S"
    assert constraints["nozzle_diameter_mm"] == 0.4
    assert constraints["layer_height_mm"] == 0.2
    assert constraints["storage"] == "usb"


def test_planning_vision_stage_message_summarizes_signal_board() -> None:
    controller = load_runtime()
    content = controller._format_planning_stage_message(
        Stage.VISION,
        {
            "observation": {
                "camera_key": "top",
                "source": "simulator",
                "anomaly": False,
                "transfer_readiness": {"ready": True, "pose_confidence": 0.86},
            },
            "vision_report": {
                "task": "post_ejection_basket_check",
                "camera_source": {"camera_key": "top", "source": "simulator"},
                "scene_map": {
                    "ejection_basket": {"state": "loaded", "confidence": 0.86},
                    "robot_workspace": {"state": "clear", "confidence": 0.82},
                },
                "signal_board": [
                    {
                        "signal": "pickup_ready",
                        "status": "ready",
                        "confidence": 0.86,
                        "expires_at": "2026-05-29T00:00:05+00:00",
                    }
                ],
                "artifacts": {"annotated_frame_path": "runs/run/vision/scene_map.svg"},
            },
            "vision_signal": {"expires_at": "2026-05-29T00:00:05+00:00"},
        },
        "Vision completed",
    )

    assert "lab perception signal" in content
    assert "zone_state" in content
    assert "pickup_ready: ready" in content
    assert "expires_at" in content
    assert "scene_map.svg" in content

@pytest.mark.asyncio
async def test_planning_success_tool_events_stay_out_of_agent_chat() -> None:
    controller = load_runtime()
    controller._planning_bootstrapped = True
    before_count = controller.planning_snapshot()["message_total"]
    event_cursor = len(controller.recent_events())

    await controller._on_tool_event(
        {
            "tool": "equipment.pyautogui.run",
            "step": "SCREEN_ASSERT_RUNNING",
            "status": "ok",
            "detail": "running_state",
            "sequence_id": "equipment-run-001",
            "program_id": "utm_compression_start_v1",
            "bridge_host": "192.168.50.58",
            "target_window": "UTM Controller",
            "confidence": 0.93,
            "screenshot_artifact": "screen-after-start",
        }
    )

    assert controller.planning_snapshot()["message_total"] == before_count

    await controller._on_tool_event(
        {
            "tool": "vision.equipment_cross_check",
            "step": "VISION_CHECK:utm_motion_confirm",
            "status": "ok",
            "detail": "confidence=0.91; frames=frame-utm-motion",
            "check_id": "utm_motion_confirm",
            "check_result": {"ok": True, "confidence": 0.91},
        }
    )

    assert controller.planning_snapshot()["message_total"] == before_count
    recent_tool_events = [
        event
        for event in controller.recent_events()[event_cursor:]
        if event.get("event_type") == "planning_tool_step"
    ]
    assert len(recent_tool_events) == 2
    assert recent_tool_events[0]["agent"] == "LabEquipmentAgent"
    assert recent_tool_events[0]["payload"]["tool"] == "equipment.pyautogui.run"
    assert recent_tool_events[0]["payload"]["step"] == "SCREEN_ASSERT_RUNNING"
    assert recent_tool_events[1]["agent"] == "LabEquipmentAgent"
    assert recent_tool_events[1]["payload"]["tool"] == "vision.equipment_cross_check"
    assert recent_tool_events[1]["payload"]["check_id"] == "utm_motion_confirm"


@pytest.mark.asyncio
async def test_planning_blocked_tool_event_carries_visual_data_recovery_metadata() -> None:
    controller = load_runtime()
    controller._planning_bootstrapped = True

    await controller._on_tool_event(
        {
            "tool": "equipment.pyautogui.run",
            "step": "PULL_ARTIFACT",
            "status": "blocked",
            "detail": "C:/ATR/utm_exports/run-001/specimen.csv",
            "sequence_id": "equipment-run-001",
            "program_id": "utm_compression_start_v1",
            "data_file_ref": "/home/jin/autonomous_researcher/artifacts/equipment/run-001/utm/specimen.csv",
            "windows_path": "C:/ATR/utm_exports/run-001/specimen.csv",
            "linux_path": "/home/jin/autonomous_researcher/artifacts/equipment/run-001/utm/specimen.csv",
            "sha256": "abc123",
            "row_count_probe": 80,
            "save_method": "manual_save_dialog",
            "artifact_pull_status": "pulled_parse_failed",
            "failure_code": "UTM_DATA_PARSE_FAILED",
        }
    )

    latest = controller.planning_snapshot()["messages"][-1]
    assert latest["message_type"] == "warning"
    assert latest["data_file_ref"].endswith("artifacts/equipment/run-001/utm/specimen.csv")
    assert latest["data_acquisition"]["artifact_or_path"].endswith("specimen.csv")
    assert latest["data_acquisition"]["windows_path"] == "C:/ATR/utm_exports/run-001/specimen.csv"
    assert latest["data_acquisition"]["linux_path"].endswith("artifacts/equipment/run-001/utm/specimen.csv")
    assert latest["data_acquisition"]["sha256"] == "abc123"
    assert latest["data_acquisition"]["row_count_probe"] == 80
    assert latest["data_acquisition"]["save_method"] == "manual_save_dialog"
    assert latest["data_acquisition"]["artifact_pull_status"] == "pulled_parse_failed"
    assert latest["recovery"]["status"] == "operator_review_required"
    assert latest["recovery"]["failure_code"] == "UTM_DATA_PARSE_FAILED"
    assert latest["ok"] is False


@pytest.mark.asyncio
async def test_planning_warning_vision_tool_event_becomes_live_chat_message() -> None:
    controller = load_runtime()
    controller._planning_bootstrapped = True

    await controller._on_tool_event(
        {
            "tool": "vision.equipment_cross_check",
            "step": "VISION_CHECK:utm_motion_confirm",
            "status": "warning",
            "detail": "confidence=0.51; frames=frame-utm-motion",
            "check_id": "utm_motion_confirm",
            "check_result": {"ok": False, "confidence": 0.51},
        }
    )

    latest = controller.planning_snapshot()["messages"][-1]
    assert latest["schema"] == "live_chat_message.v1"
    assert latest["role"] == "equipment_ai"
    assert latest["message_type"] == "signal"
    assert latest["check_id"] == "utm_motion_confirm"
    assert latest["vision_cross_check_event"]["tool"] == "vision.equipment_cross_check"
    assert latest["ok"] is False
    assert "Vision 물리검증" in latest["content"]


@pytest.mark.asyncio
async def test_planning_guardian_tool_shield_event_becomes_live_chat_message() -> None:
    controller = load_runtime()
    controller._planning_bootstrapped = True

    await controller._on_tool_event(
        {
            "tool": "guardian.tool_shield",
            "shielded_tool": "lerobot.rollout.start",
            "step": "pre_tool_call",
            "status": "approval_required",
            "decision": "require_human_approval",
            "reason_code": "HUMAN_APPROVAL_REQUIRED",
            "risk_score": 0.45,
            "requires_human_approval": True,
            "blocks_workflow": True,
            "guardian_gate": {"schema": "guardian_gate_result.v1", "decision": "require_human_approval", "risk_score": 0.45},
        }
    )

    latest = controller.planning_snapshot()["messages"][-1]
    assert latest["schema"] == "live_chat_message.v1"
    assert latest["role"] == "guardian_ai"
    assert latest["message_type"] == "approval"
    assert latest["shielded_tool"] == "lerobot.rollout.start"
    assert latest["requires_human_approval"] is True
    assert latest["blocks_workflow"] is True
    assert "Guardian action shield" in latest["content"]


@pytest.mark.asyncio
async def test_live_gui_busy_runtime_message_queues_operator_followup(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._logger_bundle.run_dir = tmp_path
    controller._planning_messages = []
    controller._planning_message_total = 0
    controller._state.mode = Mode.TEST
    controller._state.stage = Stage.DESIGN

    await controller._planning_request_lock.acquire()
    try:
        result = await controller.planning_message(
            message="다음 loop에서는 벽 두께를 조금 줄여서 진행해줘",
            goal="follow-up test",
            constraints={
                "live_is_running": True,
                "live_stage": "design",
                "live_chat_target": "orchestrator",
                "live_chat_target_resolved": "orchestrator",
                "live_chat_mode": "ask",
                "live_runtime_followup_queue_only": True,
            },
            session_id="s-followup",
        )
    finally:
        controller._planning_request_lock.release()

    assert result["ok"] is True
    assert result["message"] == "Runtime follow-up queued."
    queue = controller._state.run_metadata["operator_followup_queue"]
    assert queue[-1]["schema"] == "operator_runtime_followup.v1"
    assert queue[-1]["status"] == "queued"
    assert queue[-1]["message"].startswith("다음 loop")
    assert queue[-1]["target_agent"] == "orchestrator"
    page = controller.planning_snapshot(session_id="s-followup")["messages"]
    assert page[-2]["role"] == "operator"
    assert page[-1]["role"] == "orchestrator"
    assert "다음 안전한 stage boundary" in page[-1]["content"]

def test_live_gui_design_trigger_uses_operator_intent_state_machine() -> None:
    controller = load_runtime()

    assert controller._should_trigger_design("실험 수행") is True
    assert controller._should_trigger_design("설계 수행") is True
    assert controller._should_trigger_design("테스트 모드") is False
    assert controller._should_trigger_test_design("테스트 모드") is True
    assert controller._should_trigger_design("상태만 알려줘") is False


def test_live_gui_transcript_storage_compacts_large_payloads_and_limits_memory(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._logger_bundle.run_dir = tmp_path
    controller._planning_messages = []
    controller._planning_message_total = 0
    content = "operator-visible message " * 400

    stored = controller._record_planning_message(
        {
            "role": "bo_ai",
            "content": content,
            "timestamp": "2026-06-01T00:00:00Z",
            "raw_trace": [{"blob": "x" * 1024} for _ in range(120)],
            "bo_result": {"benchmark": {"rows": [{"value": idx} for idx in range(200)]}},
        }
    )

    assert stored["content"] == content
    assert "raw_trace" not in stored
    assert stored["bo_result"]["benchmark"] == {}
    assert controller.planning_messages_page(limit=80)["messages_loaded"] == 1

    for idx in range(60):
        controller._record_planning_message({"role": "system", "content": f"msg {idx}"})

    assert len(controller._planning_messages) == 50
    page = controller.planning_messages_page(limit=80)
    assert page["message_total"] == 61
    assert page["messages_loaded"] == 61
    assert (tmp_path / "live_planning_transcript.jsonl").exists()


def test_live_gui_message_routing_metadata_separates_chat_and_system_events(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._logger_bundle.run_dir = tmp_path
    controller._planning_messages = []
    controller._planning_message_total = 0

    handoff = controller._record_planning_message(
        {
            "role": "system",
            "content": "SYSTEM_EVENT: HANDOFF\nfrom=DesignAgent\nto=SpecimenMakingAgent\nstatus=started",
            "timestamp": "2026-06-01T00:00:00Z",
        }
    )
    assert handoff["message_class"] == "handoff_event"
    assert "chat" not in handoff["surface"]
    assert handoff["surface"] == ["timeline", "backend"]
    assert handoff["event_type"] == "planning.handoff"
    assert handoff["event_fields"] == {"from": "DesignAgent", "to": "SpecimenMakingAgent", "status": "started"}

    operator = controller._record_planning_message(
        {
            "role": "operator",
            "content": "테스트 모드, 가상 브릿지",
            "timestamp": "2026-06-01T00:00:01Z",
        }
    )
    assert operator["message_class"] == "operator_input"
    assert operator["surface"] == ["chat"]
    assert operator["visibility"] == "user"

    design = controller._record_planning_message(
        {
            "role": "design_ai",
            "content": "다음 후보 형상을 생성했습니다.",
            "timestamp": "2026-06-01T00:00:02Z",
            "experiment_spec": {"geometry_type": "tpms_gyroid", "specimen_size_mm": [30, 30, 30]},
            "artifacts": {"preview_url": "/api/planning/artifacts/run/design.png"},
        }
    )
    assert design["message_class"] == "agent_chat"
    assert design["surface"] == ["chat", "report", "artifacts"]
    assert design["agent_id"] == "DesignAgent"

    page = controller.planning_messages_page(limit=10)
    display_handoff = page["messages"][0]
    assert display_handoff["message_class"] == "handoff_event"
    assert "timeline" in display_handoff["surface"]


def test_live_gui_agent_stage_messages_remain_chat_visible(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._logger_bundle.run_dir = tmp_path
    controller._planning_messages = []
    controller._planning_message_total = 0

    expected_agents = {
        "orchestrator": "OrchestratorAgent",
        "design_ai": "DesignAgent",
        "printer_ai": "SpecimenMakingAgent",
        "vision_ai": "VisionAgent",
        "manipulation_ai": "ManipulationAgent",
        "equipment_ai": "LabEquipmentAgent",
        "analysis_ai": "AnalysisAgent",
        "knowledge_ai": "KnowledgeAgent",
        "bo_ai": "BOAgent",
        "guardian": "GuardianAgent",
        "guardian_ai": "GuardianAgent",
    }

    for role, agent_id in expected_agents.items():
        stored = controller._record_planning_message(
            {
                "role": role,
                "content": f"{role} stage summary",
                "timestamp": "2026-06-01T00:00:02Z",
            }
        )
        assert stored["message_class"] == "agent_chat"
        assert "chat" in stored["surface"]
        assert stored["agent_id"] == agent_id
