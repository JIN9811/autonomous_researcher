"""
Unit tests for Live GUI planning handoff adaptation.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode


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
    assert spec["printer_model"] == "Prusa MK4S"
    assert spec["storage"] == "usb"
    assert spec["cell_size_mm"] == 10.0
    assert spec["print"]["start_immediately"] is False
    assert spec["print"]["physical_intent"] is False
    assert "printer_test_path" not in spec


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


def test_live_gui_live_spec_arms_prusalink_upload_start(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert spec["printer_model"] == "Prusa MK4S"
    assert spec["printer_profile"] == "prusa_mk4s_pla_0p4_nozzle"
    assert spec["slicer_profile_hint"] == "0.2mm_quality"
    assert spec["nozzle_diameter_mm"] == 0.4
    assert spec["layer_height_mm"] == 0.2
    assert spec["storage"] == "usb"
    assert spec["print"]["storage"] == "usb"
    assert spec["print"]["start_immediately"] is True
    assert spec["print"]["confirm_physical_print"] is True
    assert spec["ejection"]["enabled"] is False
    assert spec["top_cap_enabled"] is False
    assert spec["bottom_cap_enabled"] is False
    assert spec["top_bottom_cap"] is False


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
    assert spec["printer_profile"] == "petg_quality_0p4"
    assert spec["slicer_profile_hint"] == "0.15mm_quality"
    assert spec["nozzle_diameter_mm"] == 0.6
    assert spec["layer_height_mm"] == 0.15
    assert spec["max_print_time_min"] == 180.0
    assert spec["print"]["overwrite"] is False
    assert spec["print"]["start_immediately"] is False
    assert spec["print"]["physical_intent"] is False
    assert spec["ejection"]["enabled"] is True


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
    assert spec["ejection"]["enabled"] is True


def test_specimen_runtime_message_focuses_on_slicer_and_prusalink() -> None:
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

    assert "PrusaSlicer 적용 설정값" in content
    assert "layer_height_mm: 0.2" in content
    assert "expected_mass_g: 6.026" in content
    assert "upload_endpoint: /api/v1/files/usb/sp-1.gcode" in content
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
    if physical:
        for _ in range(5):
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
    assert "Prusa MK4S" in last_message["content"]


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
