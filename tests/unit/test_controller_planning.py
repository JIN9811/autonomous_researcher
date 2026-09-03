"""
Unit tests for Live GUI planning handoff adaptation.
"""

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import yaml

import pytest

from agents.base_agent import AgentResult
from agents.specimen_agent import SpecimenMakingAgent
from app.bootstrap import load_runtime
from graphs import load_graph_config
from orchestrator.state import AgentRuntimeStatus, Mode, Stage


def test_planning_snapshot_preserves_latest_bo_visualization_projection() -> None:
    controller = load_runtime()
    visualization = {
        "schema": "bo_visualization.v1",
        "run_id": controller._state.run_id,
        "step": 3,
        "posterior": {"x": [0.2], "mean": [0.7], "std": [0.1], "lower_95": [0.504], "upper_95": [0.896]},
        "acquisition": {"x": [0.2], "value": [0.3]},
    }
    controller._state.run_metadata["bo_visualization"] = visualization

    compact = controller.planning_snapshot()["state"]["run_metadata"]

    assert compact["bo_visualization"] == visualization


def test_live_gui_analysis_message_preserves_normalized_curve_contract() -> None:
    controller = load_runtime()
    preview = [
        {"strain_pct": float(index) * 70.0 / 199.0, "stress_MPa": float(index) / 10.0}
        for index in range(200)
    ]
    analysis = {
        "ok": True,
        "specimen_geometry": {
            "cross_section_area_mm2": 900.0,
            "gauge_length_mm": 30.0,
        },
        "stress_strain_curve": {
            "schema": "engineering_stress_strain_curve.v1",
            "preview": preview,
        },
    }

    stored = controller._compact_planning_message_for_storage(
        {"role": "analysis_ai", "content": "dry-run analysis", "analysis": analysis}
    )
    displayed = controller._compact_planning_message_for_display(stored)

    assert displayed["analysis"]["specimen_geometry"] == analysis["specimen_geometry"]
    displayed_curve = displayed["analysis"]["stress_strain_curve"]
    assert displayed_curve["schema"] == "engineering_stress_strain_curve.v1"
    assert len(displayed_curve["preview"]) <= 80
    assert displayed_curve["preview"][0] == preview[0]
    assert displayed_curve["preview"][-1] == preview[-1]


def test_force_bo_visualization_event_republishes_current_step() -> None:
    controller = load_runtime()
    visualization = {
        "schema": "bo_visualization.v1",
        "run_id": controller._state.run_id,
        "step": 3,
        "posterior": {"x": [0.2], "mean": [0.7], "std": [0.1], "lower_95": [0.504], "upper_95": [0.896]},
        "acquisition": {"x": [0.2], "value": [0.3]},
        "candidate_index_view": {
            "x": [1.0],
            "mean": [0.7],
            "std": [0.1],
            "lower_95": [0.504],
            "upper_95": [0.896],
            "acquisition": [0.3],
            "candidate_ids": ["bo-candidate-004"],
        },
        "parameter_slices": {},
        "view": {"selected_parameter": "relative_density"},
    }
    controller._state.run_metadata["bo_visualization"] = copy.deepcopy(visualization)

    result = asyncio.run(
        controller.emit_bo_visualization(
            visualization,
            source="planning_langgraph",
            force_event=True,
        )
    )

    assert result["emitted"] is True
    event = controller.recent_events()[-1]
    assert event["event_type"] == "bo.visualization.updated"
    assert event["payload"]["step"] == 3
    assert event["payload"]["source"] == "planning_langgraph"


def test_planning_cycle_contract_is_exposed_to_live_gui() -> None:
    controller = load_runtime()

    total_cycles = controller._bind_planning_cycle_contract(
        {
            "test_mode_llm_generated": True,
            "printer_test_path": "virtual_bridge",
        }
    )
    compact = controller.planning_snapshot()["state"]["run_metadata"]

    assert total_cycles == 20
    assert compact["planning_cycle_contract"] == {
        "schema": "planning_cycle_contract.v1",
        "mode": "test",
        "total_cycles": 20,
        "source": "planning_runtime",
    }
    assert compact["safety_budget"]["max_loop_count"] == 20


def test_safe_preflight_execution_policy_is_validated_and_preserved_for_redesign() -> None:
    controller = load_runtime()
    requested = {
        "printer": "preflight_only",
        "manipulation": "preflight_only",
        "lab_equipment": "preflight_only",
        "cae": "execute",
        "analysis": "execute",
        "bo": "execute",
    }

    normalized = controller._normalize_execution_policy(requested)
    constraints = controller._design_constraints_for_cycle(
        {
            "geometry_type": "gyroid",
            "specimen_size_mm": [30.0, 30.0, 30.0],
            "execution_policy": normalized,
        }
    )

    assert normalized == requested
    assert constraints["execution_policy"] == requested
    assert controller._default_test_constraints({})["equipment_profile_id"] == "utm_windows_v1"

    with pytest.raises(ValueError, match="unsupported execution policy"):
        controller._normalize_execution_policy({"lab_equipment": "pretend_complete"})

    assert controller._normalize_execution_policy({"printer": "execute"}) == {
        "printer": "execute",
        "manipulation": "preflight_only",
        "lab_equipment": "preflight_only",
        "cae": "execute",
        "analysis": "execute",
        "bo": "execute",
    }


def test_test_mode_json_declares_two_variable_lhs_then_gp_contract() -> None:
    controller = load_runtime()

    normalized = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {"cell_size_mm": 10.0, "relative_density": 0.35},
    )

    optimization = normalized["design_optimization"]
    assert optimization["schema"] == "design_optimization_contract.v1"
    assert optimization["objective"] == {
        "metric": "energy_density_50pct_MJ_per_m3",
        "direction": "maximize",
        "unit": "MJ/m3",
    }
    assert optimization["active_variables"]["cell_size_mm"]["feasible_values"] == [5.0, 6.0, 7.5, 10.0]
    assert optimization["active_variables"]["relative_density"]["bounds"] == [0.20, 0.48]
    assert optimization["initial_design"] == {
        "sampler": "latin_hypercube",
        "size": 8,
        "seed": 7,
    }
    assert optimization["surrogate"]["kernel"] == "ard_matern_5_2_plus_noise"
    assert optimization["acquisition"] == "expected_improvement"


def test_test_mode_partial_execution_policy_cannot_drop_safe_stage_defaults() -> None:
    controller = load_runtime()
    defaults = controller._default_test_constraints({})

    normalized = controller._normalize_test_mode_constraints(
        defaults,
        {"execution_policy": {"cae": "execute"}},
    )

    assert normalized["execution_policy"] == {
        "printer": "preflight_only",
        "manipulation": "preflight_only",
        "lab_equipment": "preflight_only",
        "cae": "execute",
        "analysis": "execute",
        "bo": "execute",
    }


def test_hardware_free_preflight_policy_is_not_a_live_gui_test_default() -> None:
    controller = load_runtime()

    constraints = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {"cell_size_mm": 10.0, "relative_density": 0.35},
    )

    assert "execution_policy" not in constraints


@pytest.mark.parametrize("choice", ["installed_printer", "physical_print"])
def test_real_printer_choice_overrides_validation_only_policy_with_full_execution(choice: str) -> None:
    controller = load_runtime()
    validation_only = {
        "printer": "preflight_only",
        "manipulation": "preflight_only",
        "lab_equipment": "preflight_only",
        "cae": "execute",
        "analysis": "execute",
        "bo": "execute",
    }

    selected = controller._apply_specimen_printer_choice_to_spec(
        {"test_mode_llm_generated": True, "execution_policy": validation_only},
        choice,
    )

    assert selected["execution_policy"] == {
        "printer": "execute",
        "manipulation": "execute",
        "lab_equipment": "execute",
        "cae": "execute",
        "analysis": "execute",
        "bo": "execute",
    }


def test_planning_spec_without_explicit_policy_keeps_legacy_full_execution() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-live-physical",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "material": "PLA",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "printer_test_path": "physical_print",
            "test_mode_llm_generated": True,
        },
    )

    assert "execution_policy" not in spec


def test_test_mode_preserves_requested_lhs_count_in_design_contract() -> None:
    controller = load_runtime()
    normalized = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {
            "design_optimization": {
                "initial_design": {
                    "sampler": "latin_hypercube",
                    "size": 3,
                    "seed": 11,
                }
            }
        },
    )

    controller._publish_orchestrator_design_contract(
        normalized,
        cycle_index=1,
        total_cycles=20,
    )
    contract = controller._state.run_metadata["orchestrator_design_contract"]

    assert normalized["design_optimization"]["initial_design"]["size"] == 3
    assert contract["initial_design"]["target"] == 3
    assert len(contract["initial_design"]["points"]) == 3


def test_test_mode_initial_design_is_published_as_orchestrator_json_contract() -> None:
    controller = load_runtime()
    constraints = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {},
    )

    seeded = controller._seed_initial_bo_design_constraints(constraints, total_cycles=20)

    contract = controller._state.run_metadata["orchestrator_design_contract"]
    assert contract["schema"] == "orchestrator_design_contract.v1"
    assert contract["producer_agent"] == "orchestrator_agent"
    assert contract["consumer_agent"] == "design_agent"
    assert contract["phase"] == "initial_design"
    assert contract["cycle_index"] == 1
    assert contract["total_cycles"] == 20
    assert contract["source"] == "test_mode_deterministic_lhs"
    assert contract["requested_parameters"] == {
        "cell_size_mm": seeded["cell_size_mm"],
        "relative_density": seeded["relative_density"],
    }
    assert contract["initial_design"]["index"] == 1
    assert contract["initial_design"]["target"] == 8
    assert len(contract["initial_design"]["points"]) == 8
    assert contract["initial_design"]["points"][0]["status"] == "next"
    assert contract["initial_design"]["points"][1]["status"] == "planned"
    compact = controller.planning_snapshot()["state"]["run_metadata"]
    assert compact["orchestrator_design_contract"] == contract
    assert {
        key: compact["bo_initial_design"]["constraints"][key]
        for key in ("cell_size_mm", "relative_density")
    } == contract["requested_parameters"]


def test_first_test_loop_lhs_specimen_has_no_generated_surface_caps() -> None:
    controller = load_runtime()
    constraints = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {},
    )
    seeded = controller._seed_initial_bo_design_constraints(constraints, total_cycles=20)
    assert seeded["top_cap_enabled"] is False
    assert seeded["bottom_cap_enabled"] is False
    assert seeded["top_bottom_cap"] is False
    assert seeded["skin_thickness_mm"] == 0.0
    first_spec = controller._apply_test_cycle_surface_cap_policy(
        {
            **seeded,
            "test_mode_autofill": True,
            "top_cap_enabled": False,
            "bottom_cap_enabled": True,
            "top_bottom_cap": True,
            "skin_thickness_mm": 0.8,
            "constraints": {
                **seeded,
                "top_cap_enabled": False,
                "bottom_cap_enabled": True,
                "top_bottom_cap": True,
                "skin_thickness_mm": 0.8,
            },
        },
        cycle_index=1,
    )

    contract = controller._state.run_metadata["orchestrator_design_contract"]
    assert first_spec["cell_size_mm"] == contract["requested_parameters"]["cell_size_mm"]
    assert first_spec["relative_density"] == pytest.approx(
        contract["requested_parameters"]["relative_density"]
    )
    assert first_spec["top_cap_enabled"] is False
    assert first_spec["bottom_cap_enabled"] is False
    assert first_spec["top_bottom_cap"] is False
    assert first_spec["skin_thickness_mm"] == 0.0
    assert first_spec["constraints"]["bottom_cap_enabled"] is False
    assert first_spec["test_loop_surface_caps_disabled"] is True


def test_design_constraints_use_orchestrator_contract_as_authority() -> None:
    controller = load_runtime()
    controller._state.run_metadata["bo_recommended_constraints"] = {
        "cell_size_mm": 10.0,
        "relative_density": 0.24,
    }
    controller._state.run_metadata["orchestrator_design_contract"] = {
        "schema": "orchestrator_design_contract.v1",
        "requested_parameters": {
            "cell_size_mm": 6.0,
            "relative_density": 0.37,
        },
    }

    constraints = controller._design_constraints_for_cycle(
        {
            "geometry_type": "gyroid",
            "cell_size_mm": 7.5,
            "relative_density": 0.31,
        }
    )

    assert constraints["cell_size_mm"] == 6.0
    assert constraints["relative_density"] == pytest.approx(0.37)


def test_next_cycle_contract_republishes_bo_next_design_request() -> None:
    controller = load_runtime()
    constraints = controller._normalize_test_mode_constraints(
        controller._default_test_constraints({}),
        {},
    )
    controller._state.run_metadata["next_design_request"] = {
        "schema": "next_design_request.v1",
        "status": "ready",
        "constraints": {
            "cell_size_mm": 7.5,
            "relative_density": 0.413,
        },
    }
    controller._state.run_metadata["bo_agent"] = {
        "optimization_phase": "initial_design",
        "initial_design": {
            "sampler": "latin_hypercube",
            "completed": 1,
            "target": 8,
            "next_index": 2,
        },
        "visualization": {
            "initial_design": {
                "sampler": "latin_hypercube",
                "completed": 1,
                "target": 8,
                "points": [
                    {
                        "index": 1,
                        "status": "measured",
                        "parameters": {"cell_size_mm": 5.0, "relative_density": 0.28},
                    },
                    {
                        "index": 2,
                        "status": "next",
                        "parameters": {"cell_size_mm": 7.5, "relative_density": 0.413},
                    },
                ],
            }
        },
    }

    updated = controller._publish_orchestrator_design_contract(
        constraints,
        cycle_index=2,
        total_cycles=20,
    )

    contract = controller._state.run_metadata["orchestrator_design_contract"]
    assert contract["contract_id"].endswith("-c002")
    assert contract["phase"] == "initial_design"
    assert contract["source"] == "bo_agent_next_design_request"
    assert contract["requested_parameters"] == {
        "cell_size_mm": 7.5,
        "relative_density": pytest.approx(0.413),
    }
    assert contract["initial_design"]["completed"] == 1
    assert contract["initial_design"]["next_index"] == 2
    assert contract["initial_design"]["points"][1]["status"] == "next"
    assert updated["cell_size_mm"] == 7.5
    assert updated["relative_density"] == pytest.approx(0.413)


def test_planning_bo_message_reports_lhs_without_acquisition_scores() -> None:
    controller = load_runtime()
    message = controller._format_planning_bo_message(
        {
            "bo_result": {
                "strategy": "bo",
                "benchmark_strategy": "bo",
                "optimization_phase": "initial_design",
                "backend_active": "lhs",
                "initial_design": {
                    "sampler": "latin_hypercube",
                    "completed": 1,
                    "target": 8,
                    "next_index": 2,
                },
                "prior_summary": {"measured_count": 1, "failed_count": 0},
                "recommendation": {
                    "candidate_id": "bo-candidate-002",
                    "selection_method": "latin_hypercube",
                    "why_this_candidate": "Latin Hypercube initial design point 2/8.",
                    "parameters": {"cell_size_mm": 5.0, "relative_density": 0.3436},
                },
            }
        }
    )

    assert "Latin Hypercube initial design" in message
    assert "LHS progress: 1/8" in message
    assert "next LHS point: 2/8" in message
    assert "acquisition: inactive until LHS 8/8" in message
    assert "combined_score" not in message


def test_planning_bo_result_recovers_latest_nested_visualization() -> None:
    visualization = {
        "schema": "bo_visualization.v1",
        "run_id": "run-existing-bo",
        "step": 8,
        "view": {"selected_parameter": "relative_density"},
    }

    compact = load_runtime()._planning_display_bo_result(
        {
            "strategy": "bo",
            "benchmark": {
                "strategies": {
                    "bo": {
                        "surrogate_trace": [
                            {"iteration": 7},
                            {"iteration": 8, "visualization": visualization},
                        ]
                    }
                }
            },
        }
    )

    assert compact["visualization"] == visualization


def test_planning_bo_result_preserves_live_dashboard_phase_and_candidate_fields() -> None:
    compact = load_runtime()._planning_display_bo_result(
        {
            "strategy": "bo",
            "acquisition": "expected_improvement",
            "optimization_phase": "acquisition",
            "backend_active": "botorch",
            "initial_design": {
                "sampler": "latin_hypercube",
                "completed": 3,
                "target": 3,
                "next_index": 4,
            },
            "recommendation": {
                "candidate_id": "bo-candidate-004",
                "parameters": {"cell_size_mm": 7.5, "relative_density": 0.36},
                "combined_score": 0.91,
                "selection_method": "expected_improvement",
            },
            "candidate_ranking": [
                {
                    "candidate_id": "bo-candidate-004",
                    "parameters": {"cell_size_mm": 7.5, "relative_density": 0.36},
                    "combined_score": 0.91,
                    "acquisition_score": 0.14,
                }
            ],
            "next_design_request": {
                "schema": "next_design_request.v1",
                "status": "ready",
                "candidate_id": "bo-candidate-004",
                "constraints": {"cell_size_mm": 7.5, "relative_density": 0.36},
            },
        }
    )

    assert compact["optimization_phase"] == "acquisition"
    assert compact["backend_active"] == "botorch"
    assert compact["initial_design"] == {
        "sampler": "latin_hypercube",
        "completed": 3,
        "target": 3,
        "next_index": 4,
    }
    assert compact["recommendation"]["parameters"] == {
        "cell_size_mm": 7.5,
        "relative_density": 0.36,
    }
    assert compact["candidate_ranking"][0]["acquisition_score"] == pytest.approx(0.14)
    assert compact["next_design_request"]["constraints"]["relative_density"] == pytest.approx(0.36)


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


def test_controller_merge_vision_confirmation_marks_specimen_completion() -> None:
    controller = load_runtime()
    controller._state.run_metadata["specimen_result"] = {
        "ok": True,
        "specimen_id": "specimen-vision-001",
        "handoff_status": "ready",
        "fabrication_report": {
            "fabrication_outcome": {
                "print_completion_status": "complete",
                "autoejection_status": "awaiting_vision_confirmation",
            }
        },
        "specimen_agent_report": {
            "autoejection_gate": {"status": "waiting"},
        },
    }

    controller._merge_planning_agent_data(
        Stage.VISION,
        {
            "observation": {
                "active_cam_ejection_check": {
                    "schema": "active_cam_ejection_check.v1",
                    "status": "confirmed",
                    "specimen_detected": True,
                    "spc_autoejection_confirmed": True,
                    "image_path": "/tmp/active-cam.png",
                },
                "spc_autoejection_confirmation": {
                    "schema": "spc_autoejection_confirmation.v1",
                    "signal": "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM",
                    "status": "confirmed",
                    "confirmed": True,
                    "specimen_detected": True,
                    "consumer_agent": "specimen_agent",
                },
            },
            "vision_signal": {
                "schema": "vision_signal.v1",
                "signal": "pickup_ready",
                "value": True,
            },
        },
    )

    specimen = controller._state.run_metadata["specimen_result"]
    assert specimen["vision_completion_signal"]["confirmed"] is True
    assert specimen["vision_completion_signal"]["signal"] == "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM"
    assert specimen["vision_verification"]["status"] == "confirmed"
    assert specimen["active_cam_ejection_check"]["spc_autoejection_confirmed"] is True
    assert specimen["autoejection_completion_verified"] is True
    assert specimen["fabrication_report"]["fabrication_outcome"]["autoejection_status"] == "complete"
    assert specimen["specimen_agent_report"]["autoejection_gate"]["status"] == "complete"

    controller._merge_planning_agent_data(
        Stage.VISION,
        {
            "observation": {
                "active_cam_ejection_check": {
                    "status": "not_checked",
                    "specimen_detected": False,
                    "spc_autoejection_confirmed": False,
                },
                "spc_autoejection_confirmation": {
                    "status": "not_checked",
                    "confirmed": False,
                },
            }
        },
    )

    specimen = controller._state.run_metadata["specimen_result"]
    assert specimen["vision_verification"]["status"] == "confirmed"
    assert specimen["autoejection_completion_verified"] is True
    assert specimen["active_cam_ejection_check"]["spc_autoejection_confirmed"] is True


def test_controller_retains_active_cam_artifact_until_explicit_failure() -> None:
    controller = load_runtime()
    stored = {
        "schema": "active_cam_run_artifact.v1",
        "status": "stored",
        "path": "/runs/new.jpg",
        "url": "/api/runs/run-active-cam/artifact-file/vision/frame/new.jpg",
    }

    controller._merge_planning_agent_data(Stage.VISION, {"active_cam_artifact_update": stored})
    controller._merge_planning_agent_data(
        Stage.MANIPULATION,
        {"manipulation_report": {"status": "running"}},
    )

    assert controller._state.run_metadata["latest_active_cam_artifact"] == stored
    assert controller._compact_planning_run_metadata(controller._state.run_metadata)["latest_active_cam_artifact"] == stored

    controller._merge_planning_agent_data(
        Stage.VISION,
        {"active_cam_artifact_update": {"schema": "active_cam_run_artifact.v1", "status": "failed"}},
    )

    assert "latest_active_cam_artifact" not in controller._state.run_metadata


def test_controller_retains_utm_completion_artifact_for_live_gui() -> None:
    controller = load_runtime()
    stored = {
        "schema": "utm_completion_run_artifact.v1",
        "status": "stored",
        "path": "/runs/utm-confirmed.png",
        "url": "/api/runs/run-utm/artifact-file/vision/frame/utm-confirmed.png",
        "run_id": "run-utm",
        "session_id": "rollout-utm-001",
        "specimen_id": "specimen-utm-001",
    }

    controller._merge_planning_agent_data(
        Stage.VISION,
        {"utm_completion_artifact_update": stored},
    )

    assert controller._state.run_metadata["latest_utm_completion_artifact"] == stored
    assert (
        controller._compact_planning_run_metadata(controller._state.run_metadata)[
            "latest_utm_completion_artifact"
        ]
        == stored
    )


def test_controller_exposes_vision_operator_intervention_to_live_gui() -> None:
    controller = load_runtime()
    intervention = {
        "schema": "vision_operator_intervention.v1",
        "run_id": controller._state.run_id,
        "checkpoint": "active_cam_ejection",
        "status": "waiting_for_specimen",
        "reason": "specimen_not_detected",
        "placement_status": "outside",
        "detection_failure_code": "SPECIMEN_OUTSIDE_A4",
        "capture_path": "/tmp/active-cam-outside.png",
        "capture_url": "/api/runs/run-test/artifact-file/vision/active-cam-outside.png",
        "camera_key": "wrist",
        "requested_at": "2026-07-21T13:17:07+00:00",
        "retry_count": 0,
    }

    controller._merge_planning_agent_data(
        Stage.VISION,
        {"vision_operator_intervention": intervention},
    )

    assert controller.planning_snapshot()["state"]["run_metadata"]["vision_operator_intervention"] == intervention


def test_specimen_agent_test_mode_handoff_requires_printer_choice_in_mode_test() -> None:
    state = load_runtime()._state
    state.mode = Mode.TEST
    spec = {
        "test_mode_llm_generated": True,
        "candidate_id": "cand-test",
        "specimen_id": "specimen-test",
    }

    assert SpecimenMakingAgent._is_live_gui_test_spec(state, spec) is True


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


def test_printer_status_hms_code_does_not_create_blocking_hardware_alert() -> None:
    controller = load_runtime()

    alert = controller._hardware_alert_for_result(
        workspace="printer",
        tool="printer.status",
        result={
            "ok": True,
            "status": "COMMUNICATION_READY",
            "device_screen": {
                "health": {
                    "hms_count": 1,
                    "hms": [{"code": 131184, "attr": 83887616}],
                    "error": "0",
                    "fail_reason": "0",
                },
                "job": {"state": "IDLE"},
            },
        },
        stage=Stage.IDLE,
        agent="printer_status_monitor",
        workflow="printer_status_monitor",
        status="COMMUNICATION_READY",
    )

    assert alert is None


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
async def test_installed_printer_connection_info_pending_reprompts_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-installed",
        "specimen_id": "specimen-installed",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }
    controller._state.run_metadata["pending_specimen_input"] = {
        "type": "printer_connection_info",
        "specimen_id": "specimen-installed",
        "input_request": {
            "type": "printer_connection_info",
            "connection_memory_path": "/home/jin/autonomous_researcher/memory/printer_connection.json",
            "provider": "selected active printer",
        },
    }
    resume_called = False

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        nonlocal resume_called
        resume_called = True
        return {"ok": False, "message": "resume should not run", "session": controller.planning_snapshot(session_id=session_id)}

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)

    result = await controller._planning_message_locked(
        message="아직 연결정보 입력 전",
        goal=None,
        constraints={},
        session_id="s-installed-pending",
    )

    assert result["ok"] is True
    assert result["message"] == "SpecimenMakingAgent waiting for selected printer bridge connection info."
    assert resume_called is False
    assert controller._state.run_metadata["pending_specimen_input"]["type"] == "printer_connection_info"
    assert any(
        "/home/jin/autonomous_researcher/memory/printer_connection.json" in str(entry.get("content", ""))
        for entry in controller._planning_messages
    )


@pytest.mark.asyncio
async def test_pending_printer_choice_phrase_routes_to_specimen_before_new_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-installed",
        "specimen_id": "specimen-installed",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }
    controller._state.run_metadata["pending_specimen_input"] = {
        "type": "printer_connection_info",
        "specimen_id": "specimen-installed",
        "input_request": {
            "type": "printer_connection_info",
            "connection_memory_path": "/home/jin/autonomous_researcher/memory/printer_connection.json",
            "provider": "selected active printer",
        },
    }
    captured: dict[str, object] = {}

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        captured.update(experiment_spec)
        return {"ok": True, "message": "resumed installed printer choice", "session": controller.planning_snapshot(session_id=session_id)}

    async def fail_test_mode(**_: object) -> dict:
        raise AssertionError("pending specimen input must not restart a fresh test-mode workflow")

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)
    monkeypatch.setattr(controller, "_run_test_mode_planning", fail_test_mode)

    result = await controller._planning_message_locked(
        message="테스트 모드, 설치 프린터",
        goal=None,
        constraints={},
        session_id="s-installed-priority",
    )

    assert result["ok"] is True
    assert result["message"] == "resumed installed printer choice"
    assert captured["printer_test_path"] == "installed_printer"
    assert captured["test_printer_transport"] == "real"


@pytest.mark.asyncio
async def test_installed_printer_connection_info_done_retries_same_specimen_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-installed",
        "specimen_id": "specimen-installed",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }
    controller._state.run_metadata["pending_specimen_input"] = {
        "type": "printer_connection_info",
        "specimen_id": "specimen-installed",
        "input_request": {
            "type": "printer_connection_info",
            "connection_memory_path": "/home/jin/autonomous_researcher/memory/printer_connection.json",
            "provider": "selected active printer",
        },
    }
    captured: dict[str, object] = {}

    async def fake_resume(*, experiment_spec: dict, session_id: str | None) -> dict:
        captured.update(experiment_spec)
        return {"ok": True, "message": "resumed installed printer", "session": controller.planning_snapshot(session_id=session_id)}

    monkeypatch.setattr(controller, "_resume_specimen_after_operator_input", fake_resume)

    result = await controller._planning_message_locked(
        message="연결정보 입력 완료",
        goal=None,
        constraints={},
        session_id="s-installed-done",
    )

    assert result["ok"] is True
    assert result["message"] == "resumed installed printer"
    assert captured["printer_test_path"] == "installed_printer"
    assert "pending_specimen_input" not in controller._state.run_metadata


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
async def test_planning_langgraph_stage_syncs_returned_runloop_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.controller as controller_module

    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.current_experiment_spec = {
        "candidate_id": "cand-sync",
        "specimen_id": "specimen-sync",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }

    class FakeRunLoop:
        def __init__(self, *, state, **_: object) -> None:
            self._state = state

        async def step(self) -> None:
            returned_state = copy.deepcopy(self._state)
            returned_state.stage = Stage.VISION
            returned_state.run_metadata["specimen_result"] = {
                "ok": True,
                "requires_operator_input": False,
                "printer_prepare_status": "prepared",
            }
            returned_state.current_experiment_spec["printer_test_path"] = "installed_printer"
            self._state = returned_state

    monkeypatch.setattr(controller_module, "RunLoop", FakeRunLoop)

    await controller._run_planning_langgraph_stage(Stage.SPECIMEN)

    assert controller._state.stage == Stage.VISION
    assert controller._state.run_metadata["specimen_result"]["printer_prepare_status"] == "prepared"
    assert controller._state.current_experiment_spec["printer_test_path"] == "installed_printer"


@pytest.mark.asyncio
async def test_specimen_stage_does_not_reuse_stale_operator_prompt_after_agent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.TEST
    spec = {
        "candidate_id": "cand-stale",
        "specimen_id": "specimen-stale",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }
    controller._state.current_experiment_spec = spec
    controller._state.run_metadata["specimen_result"] = {
        "ok": False,
        "requires_operator_input": True,
        "printer_prepare_status": "printer_test_path_required",
        "input_request": {"type": "printer_test_path_choice"},
    }

    async def fake_langgraph_stage(stage: Stage) -> None:
        assert stage == Stage.SPECIMEN
        controller._state.agent_status["specimen_agent"] = AgentRuntimeStatus(
            state="error",
            success=False,
            mode="test",
            last_result="printer.prepare failed: BAMBU_FTPS_TOO_MANY_CONNECTIONS",
        )

    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", fake_langgraph_stage)

    with pytest.raises(RuntimeError, match="BAMBU_FTPS_TOO_MANY_CONNECTIONS"):
        await controller._run_planning_specimen_stage(spec, emit_handoff=False)


@pytest.mark.asyncio
async def test_specimen_stage_waits_for_physical_printer_completion_before_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-wait",
        "specimen_id": "specimen-wait",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
        "printer_completion_timeout_sec": 5,
        "printer_completion_poll_sec": 0,
    }

    async def fake_langgraph_stage(stage: Stage) -> None:
        assert stage == Stage.SPECIMEN
        controller._state.run_metadata["specimen_result"] = {
            "ok": True,
            "printer_path": "installed_printer",
            "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
            "print_result": {
                "published": True,
                "post_publish_status": {"status": "running", "progress_percent": 5},
            },
            "fabrication_report": {
                "fabrication_intent": {"printer_path": "installed_printer", "physical_intent": True},
                "fabrication_outcome": {"status": "ready_for_vision", "location": "printer_bed", "autoejection_status": "not_requested"},
                "monitoring_plan": {"observe_camera_after_print": True},
            },
            "specimen_fabricated": {
                "schema": "specimen_fabricated.v1",
                "fabrication_summary": {"outcome_status": "ready_for_vision", "location": "printer_bed"},
            },
        }

    statuses = [
        {
            "ok": True,
            "status": "PRINT_STARTED",
            "device_screen": {"progress_panel": {"state": "RUNNING", "progress_percent": 42, "job_name": "specimen.gcode.3mf"}},
        },
        {
            "ok": True,
            "status": "ready",
            "device_screen": {"progress_panel": {"state": "FINISH", "progress_percent": 100, "job_name": "specimen.gcode.3mf"}},
        },
    ]

    async def fake_completion_status() -> dict:
        return statuses.pop(0)

    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", fake_langgraph_stage)
    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fake_completion_status)

    result = await controller._run_planning_specimen_stage(spec, emit_handoff=False)

    assert result["pending"] is False
    specimen = result["specimen"]
    assert specimen["printer_completion_wait"]["status"] == "complete"
    outcome = specimen["fabrication_report"]["fabrication_outcome"]
    assert outcome["location"] == "a4_workspace"
    assert outcome["autoejection_status"] == "awaiting_vision_confirmation"
    assert specimen["printer_completion_verified"] is True
    assert specimen.get("autoejection_completion_verified") is not True
    assert controller._state.run_metadata["fabrication_report"]["fabrication_outcome"]["location"] == "a4_workspace"


@pytest.mark.asyncio
async def test_printer_completion_wait_ignores_stale_finished_job_before_current_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-current",
        "specimen_id": "specimen-current",
        "printer_test_path": "installed_printer",
        "printer_completion_timeout_sec": 5,
        "printer_completion_poll_sec": 0,
    }
    specimen_payload = {
        "ok": True,
        "specimen_id": "specimen-current",
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "print_result": {
            "published": True,
            "upload": {"filename": "specimen-current.ejection-test.gcode.3mf"},
            "post_publish_status": {"status": "running", "progress_percent": 0},
        },
    }
    statuses = [
        {
            "ok": True,
            "status": "ready",
            "device_screen": {
                "progress_panel": {
                    "state": "FINISH",
                    "progress_percent": 100,
                    "job_name": "specimen-previous",
                }
            },
        },
        {
            "ok": True,
            "status": "PRINT_STARTED",
            "device_screen": {
                "progress_panel": {
                    "state": "RUNNING",
                    "progress_percent": 10,
                    "job_name": "specimen-current",
                }
            },
        },
        {
            "ok": True,
            "status": "ready",
            "device_screen": {
                "progress_panel": {
                    "state": "FINISH",
                    "progress_percent": 100,
                    "job_name": "specimen-current",
                }
            },
        },
    ]

    async def fake_completion_status() -> dict:
        return statuses.pop(0)

    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fake_completion_status)

    result = await controller._await_specimen_printer_completion_before_vision(spec, specimen_payload)

    assert result["status"] == "complete"
    assert result["poll_count"] == 3
    assert result["samples"][0]["status"] == "stale_job"
    assert result["last_status"]["job_name"] == "specimen-current"


def test_printer_completion_classifier_treats_communication_ready_as_complete_after_start() -> None:
    controller = load_runtime()

    result = type(controller)._classify_specimen_printer_completion_status(
        {
            "ok": True,
            "status": "COMMUNICATION_READY",
            "device_screen": {
                "progress_panel": {
                    "state": "COMMUNICATION_READY",
                    "job_name": "specimen.gcode.3mf",
                }
            },
        },
        started_seen=True,
    )

    assert result["status"] == "complete"
    assert result["state"] == "COMMUNICATION_READY"


@pytest.mark.asyncio
async def test_printer_completion_wait_recovers_from_transient_mqtt_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-wait",
        "specimen_id": "specimen-wait",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
        "printer_completion_timeout_sec": 5,
        "printer_completion_poll_sec": 0,
    }
    specimen_payload = {
        "ok": True,
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "print_result": {
            "published": True,
            "post_publish_status": {"status": "running", "progress_percent": 5},
        },
    }
    statuses = [
        {
            "ok": False,
            "status": "preprint_communication_failed",
            "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT",
            "message": "Timed out waiting for Bambu MQTT report.",
        },
        {
            "ok": False,
            "status": "preprint_communication_failed",
            "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT",
            "message": "Timed out waiting for Bambu MQTT report.",
        },
        {
            "ok": True,
            "status": "ready",
            "device_screen": {"progress_panel": {"state": "RUNNING", "progress_percent": 24, "job_name": "specimen.gcode.3mf"}},
        },
        {
            "ok": True,
            "status": "ready",
            "device_screen": {"progress_panel": {"state": "FINISH", "progress_percent": 100, "job_name": "specimen.gcode.3mf"}},
        },
    ]

    async def fake_completion_status() -> dict:
        return statuses.pop(0)

    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fake_completion_status)

    result = await controller._await_specimen_printer_completion_before_vision(spec, specimen_payload)

    assert result["status"] == "complete"
    assert result["samples"][0]["status"] == "transient"
    assert result["last_status"]["status"] == "complete"


@pytest.mark.asyncio
async def test_printer_completion_wait_short_circuits_completed_post_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-wait",
        "specimen_id": "specimen-wait",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
    }
    specimen_payload = {
        "ok": True,
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_COMPLETED",
        "print_result": {
            "published": True,
            "post_publish_status": {
                "status": "completed",
                "state": "FINISH",
                "progress_percent": 100,
                "file_name": "specimen.gcode.3mf",
            },
        },
    }

    async def fail_if_polled() -> dict:
        raise AssertionError("completed post-publish evidence should not poll MQTT again")

    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fail_if_polled)

    result = await controller._await_specimen_printer_completion_before_vision(spec, specimen_payload)

    assert result["status"] == "complete"
    assert result["poll_count"] == 0
    assert result["last_status"]["status"] == "completed"
    assert result["source"] == "prepare_post_publish_status"


def test_merge_planning_agent_data_preserves_printer_completion_evidence_from_stale_specimen_payload() -> None:
    controller = load_runtime()
    controller._state.run_metadata["specimen_result"] = {
        "specimen_id": "specimen-wait",
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "printer_completion_wait": {
            "schema": "specimen_printer_completion_wait.v1",
            "status": "complete",
            "source": "prepare_post_publish_status",
        },
        "autoejection_completion_verified": True,
        "fabrication_report": {
            "fabrication_outcome": {
                "status": "ready_for_vision",
                "location": "a4_workspace",
                "autoejection_status": "complete",
            }
        },
        "specimen_fabricated": {
            "fabrication_summary": {
                "outcome_status": "ready_for_vision",
                "location": "a4_workspace",
                "autoejection_status": "complete",
            }
        },
    }
    stale_payload = {
        "specimen_id": "specimen-wait",
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "fabrication_report": {
            "fabrication_outcome": {
                "status": "ready_for_vision",
                "location": "printer_bed",
                "autoejection_status": "not_requested",
            }
        },
    }

    controller._merge_planning_agent_data(Stage.VISION, {"specimen_result": stale_payload})

    specimen = controller._state.run_metadata["specimen_result"]
    assert specimen["printer_completion_wait"]["status"] == "complete"
    assert specimen["autoejection_completion_verified"] is True
    assert specimen["fabrication_report"]["fabrication_outcome"]["location"] == "a4_workspace"
    assert specimen["fabrication_report"]["fabrication_outcome"]["autoejection_status"] == "complete"


@pytest.mark.asyncio
async def test_printer_completion_wait_tolerates_extended_transient_printer_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-wait",
        "specimen_id": "specimen-wait",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
        "printer_completion_timeout_sec": 5,
        "printer_completion_poll_sec": 0,
    }
    specimen_payload = {
        "ok": True,
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "print_result": {
            "published": True,
            "post_publish_status": {"status": "running", "progress_percent": 5},
        },
    }
    statuses = [
        {
            "ok": False,
            "status": "preprint_communication_failed",
            "failure_code": "BAMBU_PORT_UNREACHABLE",
            "message": "The printer did not answer a short MQTT probe.",
        }
        for _ in range(6)
    ]
    statuses.append(
        {
            "ok": True,
            "status": "ready",
            "device_screen": {"progress_panel": {"state": "FINISH", "progress_percent": 100, "job_name": "specimen.gcode.3mf"}},
        }
    )

    async def fake_completion_status() -> dict:
        return statuses.pop(0)

    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fake_completion_status)

    result = await controller._await_specimen_printer_completion_before_vision(spec, specimen_payload)

    assert result["status"] == "complete"
    assert result["last_status"]["status"] == "complete"


@pytest.mark.asyncio
async def test_printer_completion_wait_fails_after_repeated_transient_mqtt_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = {
        "candidate_id": "cand-wait",
        "specimen_id": "specimen-wait",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "installed_printer",
        "printer_completion_timeout_sec": 5,
        "printer_completion_poll_sec": 0,
    }
    specimen_payload = {
        "ok": True,
        "printer_path": "installed_printer",
        "printer_prepare_status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
        "print_result": {"published": True},
    }

    async def fake_completion_status() -> dict:
        return {
            "ok": False,
            "status": "preprint_communication_failed",
            "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT",
            "message": "Timed out waiting for Bambu MQTT report.",
        }

    monkeypatch.setattr(controller, "_read_specimen_printer_completion_status", fake_completion_status)

    with pytest.raises(RuntimeError, match="transient printer communication did not recover"):
        await controller._await_specimen_printer_completion_before_vision(spec, specimen_payload)


@pytest.mark.asyncio
async def test_printer_monitor_transient_mqtt_snapshot_does_not_raise_hardware_alert() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE

    await controller.emit_workspace_result(
        workspace="printer",
        tool="printer.status",
        result={
            "ok": False,
            "tool": "printer.status",
            "status": "preprint_communication_failed",
            "failure_code": "BAMBU_MQTT_REPORT_TIMEOUT",
            "message": "Timed out waiting for Bambu MQTT report.",
        },
        stage=Stage.SPECIMEN,
        module_id="specimen",
        agent="specimen_agent",
        workflow="printer_status_monitor",
        event_type="workspace_monitor_snapshot",
        mirror_live_message=False,
    )

    assert controller._state.run_metadata.get("hardware_alerts") in (None, [])
    event = controller.recent_events()[-1]
    assert event["level"] == "WARNING"
    assert event["type"] == "tool.warning"


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
    ("message", "choice", "transport", "physical", "stop_after_start"),
    [
        ("테스트 모드, 가상 브릿지", "virtual_bridge", "virtual", False, False),
        ("테스트 모드, 설치 프린터", "installed_printer", "real", True, False),
        ("테스트 모드, 실제 프린터", "installed_printer", "real", True, False),
        ("테스트 모드, 실제 출력", "physical_print", "real", True, False),
    ],
)
async def test_live_gui_test_mode_inline_printer_choice_handoffs_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    choice: str,
    transport: str,
    physical: bool,
    stop_after_start: bool,
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
    assert constraints["allow_test_equipment_live"] is (choice != "virtual_bridge")
    assert constraints["equipment_agentic_confirm_execute"] is (choice != "virtual_bridge")
    assert constraints["prefer_http_artifact"] is (choice in {"installed_printer", "physical_print"})
    print_request = constraints["print"]
    assert isinstance(print_request, dict)
    assert print_request["start_immediately"] is physical
    assert print_request["physical_intent"] is physical
    assert print_request["confirm_physical_print"] is physical
    assert print_request.get("stop_after_start", False) is stop_after_start
    if physical:
        assert print_request["post_publish_observation_timeout_sec"] >= 120
    if choice == "installed_printer":
        assert print_request["use_ejection_only_project_file"] is True
        assert print_request["prefer_http_artifact"] is True
        assert constraints["ejection"]["enabled"] is True
        assert constraints["ejection"]["allow_ejection"] is True
        assert "standalone_after_start_stop" not in constraints["ejection"]
        assert constraints["ejection"]["use_ejection_only_project_file"] is True
        assert constraints["ejection"]["source"] == "installed_printer_ejection_only_project_file"
    elif choice == "physical_print":
        assert print_request["use_ejection_only_project_file"] is False
        assert print_request["prefer_http_artifact"] is True
        assert constraints["ejection"]["enabled"] is True
        assert constraints["ejection"]["allow_ejection"] is True
        assert constraints["ejection"]["use_ejection_only_project_file"] is False
        assert constraints["ejection"]["source"] == "physical_print_tail"
    assert constraints["top_cap_enabled"] is False
    assert constraints["bottom_cap_enabled"] is False
    assert constraints["top_bottom_cap"] is False
    assert constraints["require_flat_compression_faces"] is False
    assert constraints["skin_thickness_mm"] == 0.0
    assert not controller._state.run_metadata.get("pending_specimen_input")


@pytest.mark.asyncio
async def test_live_gui_bare_test_mode_ignores_remembered_printer_choice_and_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.run_metadata["last_specimen_printer_choice"] = "virtual_bridge"
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-bare-test",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
        },
    )
    assert "printer_test_path" not in spec

    async def fake_langgraph_stage(stage: Stage) -> None:
        current_spec = controller._state.current_experiment_spec
        if controller._specimen_printer_path(current_spec):
            controller._state.run_metadata["specimen_result"] = {
                "ok": True,
                "requires_operator_input": False,
                "printer_test_path": controller._specimen_printer_path(current_spec),
            }
            return
        controller._state.run_metadata["specimen_result"] = {
            "ok": False,
            "requires_operator_input": True,
            "printer_prepare_status": "printer_test_path_required",
            "input_request": {
                "type": "printer_test_path_choice",
                "prompt": "가상 브릿지, 설치 프린터, 실제 출력 중 하나를 선택해주세요.",
                "choices": ["virtual_bridge", "installed_printer", "physical_print"],
            },
        }

    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", fake_langgraph_stage)

    result = await controller._run_planning_specimen_stage(spec, emit_handoff=False)

    assert result["pending"] is True
    assert "printer_test_path" not in controller._state.current_experiment_spec
    pending = controller._state.run_metadata.get("pending_specimen_input")
    assert isinstance(pending, dict)
    assert pending["input_request"]["type"] == "printer_test_path_choice"


@pytest.mark.asyncio
async def test_live_gui_bare_test_mode_strips_llm_printer_choice_until_agent_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    captured: dict[str, object] = {}

    async def fake_complete(*, prompt: str):
        return (
            SimpleNamespace(
                text=(
                    "테스트 실험값을 생성했습니다.\n"
                    "```json\n"
                    "{\"goal\":\"fake test\",\"constraints\":{\"geometry_type\":\"gyroid\","
                    "\"printer_test_path\":\"virtual_bridge\",\"test_printer_transport\":\"virtual\","
                    "\"allow_test_printer_live\":true}}\n"
                    "```"
                ),
                raw={},
                model="fake-orchestrator",
            ),
            "ok",
        )

    async def fake_handoff(*, goal: str | None, constraints: dict) -> dict:
        captured["constraints"] = constraints
        return {"ok": True, "message": "handoff", "session": controller.planning_snapshot(session_id="s-bare")}

    monkeypatch.setattr(controller, "_complete_live_planning_prompt", fake_complete)
    monkeypatch.setattr(controller, "_handoff_planning_to_design", fake_handoff)

    result = await controller._planning_message_locked(
        message="테스트 모드",
        goal=None,
        constraints={},
        session_id="s-bare",
    )

    assert result["ok"] is True
    constraints = captured["constraints"]
    assert isinstance(constraints, dict)
    assert "printer_test_path" not in constraints
    assert "test_printer_transport" not in constraints
    assert "allow_test_printer_live" not in constraints


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
async def test_planning_tail_continues_original_loop_after_specimen(tmp_path: Path) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    rollout_session_id = "rollout-cand-tail"
    utm_frame = tmp_path / "utm-confirmed.png"
    utm_frame.write_bytes(b"utm-confirmed")
    controller._deps.agent_context.tools.register(
        "lerobot.rollout.start",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.start",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "ACTION_ACTIVE",
            "action_count": 120,
            "session_id": rollout_session_id,
            "profile_id": payload.get("profile_id", ""),
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": rollout_session_id,
                "ungrasping_seen": True,
                "home_after_ungrasping": True,
                "ready_for_utm_snapshot": True,
            },
        },
    )
    controller._deps.agent_context.tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "confirmed",
            "detected": True,
            "source": "virtual_utm_camera",
            "frame_id": payload["frame_id"],
            "annotated_frame_path": str(utm_frame),
            "raw_frame_path": str(utm_frame),
            "confidence": 0.95,
            "width": 640,
            "height": 480,
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "specimen_id": payload["specimen_id"],
        },
    )
    controller._deps.agent_context.tools.register(
        "lerobot.rollout.stop",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "workflow": "rollout",
            "status": "STOPPED",
            "session_id": payload["session_id"],
        },
    )
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
    events = controller.recent_events()
    completed_stages = [
        event.get("node_id")
        for event in events
        if event.get("type") == "node.completed"
    ]
    post_place_vision_index = max(index for index, stage in enumerate(completed_stages) if stage == "vision")
    assert completed_stages[post_place_vision_index : post_place_vision_index + 6] == [
        "vision",
        "equipment",
        "analysis",
        "knowledge",
        "bo",
        "guardian",
    ], completed_stages

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
async def test_live_gui_planning_series_clears_stale_control_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.safe_stop_requested = True
    controller._state.stop_requested = True
    controller._state.is_paused = True
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-stale-stop",
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
    observed_flags: list[tuple[bool, bool, bool]] = []

    async def fake_loop_tail(experiment_spec: dict, **_: object) -> dict:
        observed_flags.append(
            (
                bool(controller._state.safe_stop_requested),
                bool(controller._state.stop_requested),
                bool(controller._state.is_paused),
            )
        )
        return {"ok": True, "message": "tail stopped for test", "decision": "stop"}

    monkeypatch.setattr(controller, "_run_planning_loop_tail", fake_loop_tail)

    result = await controller._run_planning_cycle_series(
        first_spec=spec,
        design_constraints={**dict(spec.get("constraints", {})), **spec},
        start_cycle=1,
    )

    assert result["decision"] == "stop"
    assert observed_flags == [(False, False, False)]


@pytest.mark.asyncio
async def test_specimen_stage_discards_previous_cycle_vision_and_manipulation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new specimen must not consume the prior cycle's robot/vision handoff."""
    controller = load_runtime()
    controller._state.mode = Mode.TEST
    controller._state.run_metadata.update(
        {
            "specimen_result": {"ok": True, "specimen_id": "specimen-cycle-1"},
            "latest_vision_observation": {"specimen_id": "specimen-cycle-1", "detected": True},
            "vision_signal": {"specimen_id": "specimen-cycle-1", "value": True},
            "vision_operator_intervention": {"checkpoint": "utm_post_place"},
            "manipulation_result": {"session_id": "rollout-cycle-1", "status": "ACTIVE"},
            "robot_task_result": {
                "specimen_id": "specimen-cycle-1",
                "rollout_session_id": "rollout-cycle-1",
            },
        }
    )
    spec = {
        "candidate_id": "cand-cycle-2",
        "specimen_id": "specimen-cycle-2",
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_llm_generated": True,
        "printer_test_path": "virtual_bridge",
    }

    async def fake_langgraph_stage(stage: Stage) -> None:
        assert stage == Stage.SPECIMEN
        controller._state.run_metadata["specimen_result"] = {
            "ok": True,
            "specimen_id": "specimen-cycle-2",
            "printer_path": "virtual_bridge",
        }

    monkeypatch.setattr(controller, "_run_planning_langgraph_stage", fake_langgraph_stage)

    await controller._run_planning_specimen_stage(spec, emit_handoff=False)

    for key in (
        "latest_vision_observation",
        "vision_signal",
        "vision_operator_intervention",
        "manipulation_result",
        "robot_task_result",
    ):
        assert key not in controller._state.run_metadata


@pytest.mark.asyncio
async def test_live_gui_planning_series_preserves_stop_after_workflow_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._reset_planning_workflow_controls()
    controller._state.safe_stop_requested = True
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-real-stop",
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
    observed_flags: list[bool] = []

    async def fake_loop_tail(experiment_spec: dict, **_: object) -> dict:
        observed_flags.append(bool(controller._state.safe_stop_requested))
        return {"ok": True, "message": "tail stopped for test", "decision": "stop"}

    monkeypatch.setattr(controller, "_run_planning_loop_tail", fake_loop_tail)

    result = await controller._run_planning_cycle_series(
        first_spec=spec,
        design_constraints={**dict(spec.get("constraints", {})), **spec},
        start_cycle=1,
    )

    assert result["decision"] == "stop"
    assert observed_flags == [True]


@pytest.mark.asyncio
async def test_live_gui_planning_series_does_not_start_next_design_for_pending_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-utm-pending",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "installed_printer",
        },
    )
    design_calls: list[int] = []

    async def fake_loop_tail(experiment_spec: dict, **_: object) -> dict:
        controller._state.run_metadata["vision_operator_intervention"] = {
            "schema": "vision_operator_intervention.v1",
            "checkpoint": "utm_post_place",
            "status": "retrying",
            "reason": "specimen_not_detected",
        }
        return {
            "ok": True,
            "message": "UTM placement verification is still active.",
            "decision": "continue",
        }

    async def unexpected_design_stage(**kwargs: object) -> dict:
        design_calls.append(int(kwargs.get("cycle_index", 0)))
        return spec

    async def fake_specimen_stage(experiment_spec: dict, *, emit_handoff: bool = True) -> dict:
        return {"pending": False, "specimen": {"specimen_id": experiment_spec["specimen_id"]}}

    monkeypatch.setattr(controller, "_run_planning_loop_tail", fake_loop_tail)
    monkeypatch.setattr(controller, "_run_planning_design_stage", unexpected_design_stage)
    monkeypatch.setattr(controller, "_run_planning_specimen_stage", fake_specimen_stage)

    result = await controller._run_planning_cycle_series(
        first_spec=spec,
        design_constraints={**dict(spec.get("constraints", {})), **spec},
        start_cycle=1,
    )

    assert result["decision"] == "pending_vision_verification"
    assert design_calls == []


@pytest.mark.asyncio
async def test_live_gui_planning_tail_reports_operator_safe_stop_without_silent_cycle_continue() -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    controller._state.safe_stop_requested = True
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-safe-stop",
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

    result = await controller._run_planning_loop_tail(spec, cycle_index=2, total_cycles=5)

    assert result["ok"] is True
    assert result["decision"] == "stop"
    assert "safe_stop_requested" in result["message"]
    system_messages = [message["content"] for message in controller.planning_snapshot()["messages"] if message["role"] == "system"]
    assert any("SYSTEM_EVENT: WORKFLOW_HALTED" in content and "safe_stop_requested" in content for content in system_messages)


@pytest.mark.asyncio
async def test_live_gui_planning_tail_preserves_runtime_terminal_complete_without_restarting_design(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-vision-safe-stop",
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
        },
        constraints={
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "test_mode_autofill": True,
            "test_mode_llm_generated": True,
            "printer_test_path": "installed_printer",
        },
    )

    class TerminalVisionRunLoop:
        def __init__(self, *, state, **_: object) -> None:
            self._state = state

        async def step(self) -> None:
            assert self._state.stage == Stage.VISION
            self._state.stage = Stage.COMPLETE

    monkeypatch.setattr("app.controller.RunLoop", TerminalVisionRunLoop)

    result = await controller._run_planning_loop_tail(spec, cycle_index=1, total_cycles=5)

    assert result["ok"] is True
    assert result["decision"] == "stop"
    assert controller._state.stage == Stage.COMPLETE
    system_messages = [message["content"] for message in controller.planning_snapshot()["messages"] if message["role"] == "system"]
    assert not any("SYSTEM_EVENT: CYCLE_COMPLETE" in content for content in system_messages)


@pytest.mark.asyncio
async def test_emergency_resume_restarts_interrupted_planning_test_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-estop-resume",
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
    controller._state.current_experiment_spec = dict(spec)
    controller._state.active_goal = "resume interrupted virtual-printer test loop"
    controller._state.stage = Stage.VISION
    stale_decision = {
        "decision_id": "decision-before-estop",
        "decision": "planning_route_next_stage",
        "selected": "vision",
    }
    controller._state.run_metadata["orchestrator_decision_register"] = [dict(stale_decision)]
    controller._state.run_metadata["latest_orchestrator_decision"] = dict(stale_decision)
    controller._state.run_metadata["latest_orchestrator_control_plane"] = {
        "schema": "orchestrator_control_plane.v1",
        "decision_register": {
            "decision_count": 1,
            "items": [dict(stale_decision)],
        },
    }
    controller._state.run_metadata["_planning_resume_context"] = {
        "kind": "planning_cycle_series",
        "goal": controller._state.active_goal,
        "current_spec": dict(spec),
        "design_constraints": {**dict(spec.get("constraints", {})), **spec},
        "cycle_index": 2,
        "total_cycles": 5,
        "interrupted_stage": "vision",
    }
    controller._state.emergency_stop_requested = True
    controller._state.stop_requested = True

    started = asyncio.Event()
    release = asyncio.Event()
    observed: list[tuple[int, str, bool, bool]] = []

    async def fake_cycle_series(*, first_spec: dict, design_constraints: dict, start_cycle: int) -> dict:
        observed.append(
            (
                start_cycle,
                controller._state.stage.value,
                bool(controller._state.emergency_stop_requested),
                bool(controller._state.stop_requested),
            )
        )
        started.set()
        await release.wait()
        return {"ok": True, "decision": "stop", "message": "resumed test loop"}

    monkeypatch.setattr(controller, "_run_planning_cycle_series", fake_cycle_series)

    response = await controller.emergency_resume()
    assert response["ok"] is True
    assert response["resume"]["started"] is True
    response_metadata = response["state"]["run_metadata"]
    assert response_metadata["orchestrator_decision_register"] == []
    assert response_metadata["latest_orchestrator_control_plane"]["decision_register"]["decision_count"] == 0
    assert response_metadata["latest_orchestrator_control_plane"]["decision_register"]["items"] == []
    session_metadata = controller.planning_snapshot()["state"]["run_metadata"]
    assert session_metadata["orchestrator_decision_register"] == []
    assert session_metadata["latest_orchestrator_control_plane"]["decision_register"]["decision_count"] == 0
    await asyncio.wait_for(started.wait(), timeout=1.0)

    assert observed == [(2, "vision", False, False)]
    assert controller._planning_handoff_active() is True

    release.set()
    task = controller._planning_handoff_task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_live_gui_planning_tail_agent_messages_keep_cycle_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    spec = controller._build_planning_spec(
        base_spec={
            "candidate_id": "cand-tail-cycle",
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

    def fake_stage_data(stage: Stage) -> dict:
        if stage == Stage.VISION:
            return {"observation": {"anomaly": False}, "vision_report": {"camera_source": {"camera_key": "top"}}, "vision_signal": {"signal_id": "sig-1"}}
        if stage == Stage.MANIPULATION:
            return {"manipulation": {"strategy": "pi0.5", "status": "done"}, "sarm": {"progress_score": 0.4}}
        if stage == Stage.EQUIPMENT:
            return {
                "equipment_result": {"ok": True, "status": "done", "program_id": "utm"},
                "equipment_handoff": {"status": "ready_for_analysis", "result_file": "/tmp/utm.csv"},
                "equipment_report": {"decision": {"handoff_status": "ready_for_analysis"}},
            }
        if stage == Stage.ANALYSIS:
            return {"analysis": {"ok": True, "objective_score": 0.7, "uncertainty": 0.1, "utm_metrics": {"peak_force_N": 120.0}}}
        if stage == Stage.KNOWLEDGE:
            return {"knowledge": {"retrieval_coverage": 1.0, "memory_summary": "ok"}}
        if stage == Stage.BO:
            return {"bo_result": {"strategy": "bo", "recommendation": {"candidate_id": "cand-next", "parameters": {}}}}
        if stage == Stage.GUARDIAN:
            return {"guardian": {"decision": "continue", "action": "continue", "reason": "ok"}}
        return {stage.value: {"ok": True}}

    class FakeRunLoop:
        order = [Stage.VISION, Stage.MANIPULATION, Stage.EQUIPMENT, Stage.ANALYSIS, Stage.KNOWLEDGE, Stage.BO, Stage.GUARDIAN]

        def __init__(self, *, state, on_event=None, **_: object) -> None:
            self._state = state
            self._on_event = on_event

        async def step(self) -> None:
            stage = self._state.stage if self._state.stage in self.order else self.order[0]
            if self._on_event:
                await self._on_event({"type": "node.started", "payload": {"node_id": stage.value}})
                await self._on_event({"type": "node.completed", "payload": {"node_id": stage.value, "result": fake_stage_data(stage)}})
            index = self.order.index(stage)
            self._state.stage = self.order[index + 1] if index + 1 < len(self.order) else Stage.COMPLETE

    monkeypatch.setattr("app.controller.RunLoop", FakeRunLoop)
    monkeypatch.setattr(controller, "_write_planning_fem_artifacts", lambda *_args, **_kwargs: {})

    result = await controller._run_planning_loop_tail(spec, cycle_index=2, total_cycles=5)

    assert result["ok"] is True
    expected_roles = {"vision_ai", "manipulation_ai", "equipment_ai", "analysis_ai", "knowledge_ai", "bo_ai", "guardian"}
    messages = controller.planning_snapshot()["messages"]
    roles_seen = {message["role"] for message in messages if message.get("role") in expected_roles}
    assert roles_seen == expected_roles
    for message in messages:
        if message.get("role") in expected_roles or message.get("event_type") in {"planning_handoff", "planning.workflow_complete"}:
            assert message.get("cycle_index") == 2
            assert message.get("total_cycles") == 5


@pytest.mark.asyncio
async def test_live_gui_test_planning_series_runs_twenty_design_cycles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller = load_runtime()
    controller._state.mode = Mode.LIVE
    utm_frame = tmp_path / "utm-confirmed.png"
    utm_frame.write_bytes(b"utm-confirmed")
    controller._deps.agent_context.tools.register(
        "lerobot.rollout.start",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.start",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "ACTION_ACTIVE",
            "action_count": 120,
            "session_id": payload["session_id"],
            "profile_id": payload.get("profile_id", ""),
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": payload["session_id"],
                "ungrasping_seen": True,
                "home_after_ungrasping": True,
                "ready_for_utm_snapshot": True,
            },
        },
    )
    controller._deps.agent_context.tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "confirmed",
            "detected": True,
            "source": "virtual_utm_camera",
            "frame_id": payload["frame_id"],
            "annotated_frame_path": str(utm_frame),
            "raw_frame_path": str(utm_frame),
            "confidence": 0.95,
            "width": 640,
            "height": 480,
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "specimen_id": payload["specimen_id"],
        },
    )
    controller._deps.agent_context.tools.register(
        "lerobot.rollout.stop",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "workflow": "rollout",
            "status": "STOPPED",
            "session_id": payload["session_id"],
        },
    )
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
    assert controller._state.loop_count == 20
    design_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "design_ai"]
    # Completed loops are compacted in the session transcript; only the recent
    # expanded Design messages remain even though loop_count is authoritative.
    assert 1 <= len(design_messages) <= 19
    assert all(message.get("artifact_pair", {}).get("previous") for message in design_messages)
    assert all(message.get("artifact_pair", {}).get("next") for message in design_messages)
    signatures = {
        (
            message["experiment_spec"].get("cell_size_mm"),
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
    assert controller._state.current_experiment_spec["cell_size_mm"] in {5.0, 6.0, 7.5, 10.0}
    assert controller._state.current_experiment_spec["top_bottom_cap"] is False
    assert controller._state.current_experiment_spec["test_loop_surface_caps_disabled"] is True
    assert controller._state.run_metadata["bo_recommended_constraints"]["cell_size_mm"] in {5.0, 6.0, 7.5, 10.0}
    bo_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "bo_ai"]
    assert bo_messages
    bo_trace = bo_messages[-1]["bo_result"]["benchmark"]["strategies"]["bo"]["surrogate_trace"]
    assert bo_trace
    assert bo_trace[-1]["selected"]["candidate_id"]
    analysis_messages = [message for message in controller.planning_snapshot()["messages"] if message["role"] == "analysis_ai"]
    assert any(message.get("fem_artifacts", {}).get("contour_url") for message in analysis_messages)


def test_design_constraints_for_cycle_preserves_both_bo_active_variables() -> None:
    controller = load_runtime()
    controller._state.run_metadata["bo_recommended_constraints"] = {
        "cell_size_mm": 6.0,
        "relative_density": 0.37,
        "wall_thickness_mm": 1.2,
    }

    constraints = controller._design_constraints_for_cycle(
        {
            "geometry_type": "gyroid",
            "cell_size_mm": 10.0,
            "relative_density": 0.24,
        }
    )

    assert constraints["cell_size_mm"] == 6.0
    assert constraints["relative_density"] == pytest.approx(0.37)


def test_closed_loop_static_constraints_release_both_bo_active_variables() -> None:
    controller = load_runtime()
    static = controller._closed_loop_static_design_constraints(
        {
            "geometry_type": "gyroid",
            "specimen_size_mm": [30, 30, 30],
            "cell_size_mm": 10.0,
            "relative_density": 0.28,
            "material": "PLA",
        }
    )

    assert "cell_size_mm" not in static
    assert "relative_density" not in static
    assert static["geometry_type"] == "gyroid"
    assert static["specimen_size_mm"] == [30, 30, 30]
    assert static["material"] == "PLA"


def test_test_mode_initial_cycle_is_seeded_from_bo_lhs() -> None:
    controller = load_runtime()
    constraints = {
        "geometry_type": "gyroid",
        "specimen_size_mm": [30, 30, 30],
        "test_mode_autofill": True,
        "test_mode_llm_generated": True,
    }

    seeded = controller._seed_initial_bo_design_constraints(constraints, total_cycles=5)

    assert seeded["cell_size_mm"] in {5.0, 6.0, 7.5, 10.0}
    assert 0.20 <= seeded["relative_density"] <= 0.48
    assert controller._state.run_metadata["bo_initial_design"]["index"] == 1
    assert controller._state.run_metadata["bo_recommended_constraints"]["cell_size_mm"] == seeded["cell_size_mm"]


@pytest.mark.parametrize("printer_path", ["virtual_bridge", "installed_printer"])
def test_test_mode_printer_routes_use_twenty_cycle_bo_budget(printer_path: str) -> None:
    controller = load_runtime()

    assert controller._planning_cycle_limit(
        {
            "test_mode_llm_generated": True,
            "printer_test_path": printer_path,
        }
    ) == 20


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
