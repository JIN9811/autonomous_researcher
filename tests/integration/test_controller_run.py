"""
Integration tests for controller-driven test mode loop execution.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.bootstrap import load_runtime
from device_bridges.lerobot_bridge import LeRobotBridge
from orchestrator.state import Mode, Stage


@pytest.mark.asyncio
async def test_controller_completes_test_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def virtual_post_place_telemetry(_bridge: LeRobotBridge, session: dict[str, object]) -> dict[str, object]:
        session_id = str(session.get("session_id") or "test-rollout")
        packet = {
            "schema": "atr.robot_joint_telemetry.v1",
            "type": "joint_sample",
            "session_id": session_id,
            "sequence": 2,
            "actual_source": {"source": "virtual_controller_fixture"},
            "target_source": {"source": "virtual_controller_fixture"},
            "motion_state": {
                "measured": {"base_state": "home", "gripper_state": "idle", "home_gate": {"passed": True}},
                "policy": {"base_state": "home", "gripper_state": "idle", "home_gate": {"passed": True}},
            },
        }
        return {
            "joint_telemetry": {
                "schema": "atr.robot_joint_telemetry.v1",
                "status": "available",
                "session_id": session_id,
                "log_path": "virtual://controller-test-rollout",
                "packet": packet,
            },
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": session_id,
                "ungrasping_seen": True,
                "ungrasping_sequence": 1,
                "measured_base_state": "home",
                "measured_gripper_state": "idle",
                "home_gate_passed": True,
                "home_after_ungrasping": True,
                "ready_for_utm_snapshot": True,
                "latest_sequence": 2,
            },
        }

    monkeypatch.setattr(LeRobotBridge, "_rollout_joint_telemetry_contract", virtual_post_place_telemetry)
    controller = load_runtime()
    result = await controller.start(mode=Mode.TEST, goal="integration test run")
    assert result["ok"] is True
    created_events = [event for event in controller.recent_events() if event.get("type") == "run.created"]
    assert created_events
    assert created_events[-1]["payload"]["mode"] == Mode.TEST.value
    assert created_events[-1]["payload"]["graph_id"] == "atr_closed_loop"
    json_log_path = Path(controller.snapshot()["logs"]["json"])
    log_records = [json.loads(line) for line in json_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(record["event_type"] == "run.created" for record in log_records)

    timeout_s = 1200.0
    start = asyncio.get_running_loop().time()
    while True:
        snapshot = controller.snapshot()
        stage = snapshot["state"]["stage"]
        if stage in {Stage.COMPLETE.value, Stage.ERROR.value}:
            break
        if asyncio.get_running_loop().time() - start > timeout_s:
            raise TimeoutError(f"run did not finish within {timeout_s}s; stage={stage}")
        await asyncio.sleep(0.1)

    assert snapshot["state"]["stage"] == Stage.COMPLETE.value
    assert snapshot["state"]["loop_count"] == 20
    assert snapshot["state"]["run_metadata"]["bo_agent"]["tool"] == "bo.agent"
    assert snapshot["state"]["run_metadata"]["bo_agent"]["knowledge_context"]
    assert snapshot["state"]["run_metadata"]["equipment_result"]["tool"] == "equipment.pyautogui.run"
    assert snapshot["state"]["run_metadata"]["equipment_result"]["status"] == "verified_complete"
    assert snapshot["state"]["run_metadata"]["equipment_handoff"]["status"] == "ready_for_analysis"
    assert snapshot["state"]["run_metadata"]["equipment_report"]["schema"] == "equipment_report.v1"
    assert snapshot["state"]["run_metadata"]["utm_data_ready"]["schema"] == "utm_data_ready.v1"
    assert snapshot["state"]["run_metadata"]["equipment_report"]["cross_checks"]["data_parse_probe_ok"] is True
    assert snapshot["state"]["run_metadata"].get("hardware_alerts", []) == []
    assert any(packet["packet"]["schema"] == "utm_data_ready.v1" for packet in snapshot["state"]["run_metadata"]["handoff_packets"])
    assert snapshot["state"]["latest_analysis"]["equipment_ok"] is True
    assert snapshot["state"]["latest_analysis"]["equipment_result_file"]
    assert snapshot["state"]["latest_analysis"]["cae_result"]["ok"] is True
    assert snapshot["state"]["latest_analysis"]["cae_result"]["boundary_condition"] == "bottom_fixed_support"
    assert snapshot["state"]["latest_analysis"]["bo_observation"]["schema"] == "bo_observation.v1"
    assert any(
        item.get("schema") == "experiment_evaluation.v1" and item.get("source") == "analysis_agent"
        for item in snapshot["state"].get("experiment_evaluations", [])
    )
    assert snapshot["state"]["latest_observations"]["vision_report"]["schema"] == "vision_report.v1"
    assert snapshot["state"]["latest_observations"]["vision_signal"]["schema"] == "vision_signal.v1"
    assert snapshot["state"]["run_metadata"]["vision_report"]["schema"] == "vision_report.v1"
    assert snapshot["state"]["run_metadata"]["vision_signal"]["schema"] == "vision_signal.v1"
    assert snapshot["state"]["run_metadata"]["vision_handoff_packet"]["schema"] == "vision_signal.v1"
    assert any(packet["packet"]["schema"] == "vision_signal.v1" for packet in snapshot["state"]["run_metadata"]["handoff_packets"])

    run_dir = json_log_path.parent
    artifact_paths = {item.relative_to(run_dir).as_posix() for item in run_dir.rglob("*") if item.is_file()}
    runtime_artifacts = snapshot["state"]["run_metadata"].get("runtime_artifacts", [])
    runtime_artifact_paths = {str(item.get("path") or "") for item in runtime_artifacts if isinstance(item, dict)}
    posterior_artifacts = {
        path for path in artifact_paths if path.startswith("runtime/bo/") and "_posterior." in path
    }
    assert {path.rsplit(".", 1)[-1] for path in posterior_artifacts} == {"png", "svg", "csv"}
    assert any(path.startswith("runtime/analysis/") and path.endswith(".contour.svg") for path in artifact_paths)
    assert any(path.startswith("runtime/analysis/") and path.endswith(".report.json") for path in artifact_paths)
    assert any(path.startswith("vision/") and path.endswith("detection.json") for path in artifact_paths)
    assert any(path.startswith("vision/") and path.endswith("scene_map.svg") for path in artifact_paths)
    runtime_posterior_artifacts = {
        path for path in runtime_artifact_paths if path.startswith("runtime/bo/") and "_posterior." in path
    }
    assert {path.rsplit(".", 1)[-1] for path in runtime_posterior_artifacts} == {"png", "svg", "csv"}
    assert any(path.startswith("runtime/analysis/") and path.endswith(".contour.svg") for path in runtime_artifact_paths)

    await controller.emit_workspace_result(
        workspace="unit_workspace",
        tool="unit.tool",
        result={"ok": True, "status": "done", "workflow": "unit-workflow"},
        stage=Stage.BO,
        module_id="bo",
        agent="bo_agent",
        node_event=True,
    )
    log_records = [json.loads(line) for line in json_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(
        record["event_type"] == "tool.completed" and record["payload"].get("workspace") == "unit_workspace"
        for record in log_records
    )
    assert any(
        record["event_type"] == "node.completed" and record["payload"].get("workspace") == "unit_workspace"
        for record in log_records
    )


@pytest.mark.asyncio
async def test_safe_physical_printer_preflight_completes_twenty_redesign_cycles_without_actuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real post-print agent chain while every physical boundary is a tripwire."""
    controller = load_runtime()
    controller.TEST_MODE_LOOP_CYCLES = 20
    tools = controller._deps.agent_context.tools

    def forbidden_actuation(_payload: dict[str, object]) -> dict[str, object]:
        raise AssertionError("safe preflight cycle crossed a physical or camera execution boundary")

    for tool_name in (
        "camera.capture",
        "lerobot.active_robot_cam.capture",
        "vision.utm_runtime.start",
        "lerobot.rollout.start",
        "robot.pick_place",
        "equipment.pyautogui.run",
        "utm.run_protocol",
    ):
        tools.register(tool_name, forbidden_actuation)

    first_spec = controller._apply_specimen_printer_choice_to_spec(
        controller._default_test_constraints({}),
        "physical_print",
    )
    first_spec.update(
        {
            "test_mode_llm_generated": True,
            "candidate_id": "safe-cycle-01",
            "specimen_id": "specimen-safe-cycle-01",
            "execution_policy": {
                "printer": "preflight_only",
                "manipulation": "preflight_only",
                "lab_equipment": "preflight_only",
                "cae": "execute",
                "analysis": "execute",
                "bo": "execute",
            },
        }
    )
    controller._state.mode = Mode.TEST
    controller._state.active_goal = "maximize exact 50 percent compression energy density"
    controller._state.current_experiment_spec = dict(first_spec)
    controller._bind_planning_cycle_contract(first_spec)

    def install_specimen_contract(spec: dict[str, object]) -> None:
        specimen_id = str(spec["specimen_id"])
        for key in ("vision_preflight", "manipulation_preflight", "equipment_preflight"):
            controller._state.run_metadata.pop(key, None)
        controller._state.latest_observations = {}
        controller._state.run_metadata["specimen_result"] = {
            "ok": True,
            "specimen_id": specimen_id,
            "candidate_id": str(spec["candidate_id"]),
            "handoff_status": "ready",
            "stl_path": f"virtual://{specimen_id}.stl",
            "fabrication_report": {
                "schema": "fabrication_report.v1",
                "fabrication_outcome": {"status": "preflight_complete", "location": "not_actuated"},
            },
        }
        controller._state.run_metadata["printer_preflight"] = {
            "schema": "printer_preflight.v1",
            "run_id": controller._state.run_id,
            "status": "execution_ready_pending_approval",
            "actuation_performed": False,
            "upload_performed": False,
            "start_command_published": False,
            "specimen_id": specimen_id,
            "candidate_id": str(spec["candidate_id"]),
            "plate_id": 1,
            "immutable_artifact_path": f"virtual://{specimen_id}.autoeject.gcode.3mf",
            "artifact_sha256": f"{int(str(spec['candidate_id']).rsplit('-', 1)[-1]):064x}",
            "source_object_bounds_mm": {
                "min_x": 120.0,
                "max_x": 150.0,
                "min_y": 110.0,
                "max_y": 140.0,
                "center_x_mm": 135.0,
                "center_y_mm": 125.0,
            },
        }

    install_specimen_contract(first_spec)
    applied_recommendations: list[dict[str, float]] = []

    async def fast_design_stage(
        *,
        previous_spec: dict[str, object] | None,
        design_constraints: dict[str, object],
        cycle_index: int,
        total_cycles: int,
        emit_handoff: bool,
    ) -> dict[str, object]:
        del total_cycles, emit_handoff
        spec = dict(previous_spec or first_spec)
        recommendation = controller._state.run_metadata.get("bo_recommended_constraints")
        assert isinstance(recommendation, dict)
        applied = {
            "cell_size_mm": float(recommendation["cell_size_mm"]),
            "relative_density": float(recommendation["relative_density"]),
        }
        applied_recommendations.append(applied)
        spec.update(design_constraints)
        spec.update(recommendation)
        spec["candidate_id"] = f"safe-cycle-{cycle_index:02d}"
        spec["specimen_id"] = f"specimen-safe-cycle-{cycle_index:02d}"
        spec["execution_policy"] = dict(first_spec["execution_policy"])
        return spec

    async def fast_specimen_stage(spec: dict[str, object], *, emit_handoff: bool = True) -> dict[str, object]:
        del emit_handoff
        controller._state.current_experiment_spec = dict(spec)
        install_specimen_contract(spec)
        return {"pending": False, "specimen": controller._state.run_metadata["specimen_result"]}

    original_tail = controller._run_planning_loop_tail
    cycle_records: list[dict[str, object]] = []

    async def audited_tail(
        spec: dict[str, object],
        *,
        cycle_index: int = 1,
        total_cycles: int = 1,
    ) -> dict[str, object]:
        result = await original_tail(spec, cycle_index=cycle_index, total_cycles=total_cycles)
        observation = controller._state.latest_analysis.get("bo_observation", {})
        assert observation["status"] == "ready"
        assert observation["metric_name"] == "energy_density_50pct_MJ_per_m3"
        assert observation["fidelity"] == "cae_mid"
        assert observation["objective_score"] > 0.0
        for key, schema in (
            ("printer_preflight", "printer_preflight.v1"),
            ("vision_preflight", "vision_preflight.v1"),
            ("manipulation_preflight", "manipulation_preflight.v1"),
            ("equipment_preflight", "equipment_preflight.v1"),
        ):
            record = controller._state.run_metadata[key]
            assert record["schema"] == schema
            assert record["status"] == "execution_ready_pending_approval"
            assert record["actuation_performed"] is False
        assert controller._state.current_experiment_spec["execution_policy"] == first_spec["execution_policy"]
        cycle_records.append(
            {
                "cycle_index": cycle_index,
                "cell_size_mm": float(spec["cell_size_mm"]),
                "relative_density": float(spec["relative_density"]),
                "objective_score": float(observation["objective_score"]),
            }
        )
        return result

    monkeypatch.setattr(controller, "_run_planning_design_stage", fast_design_stage)
    monkeypatch.setattr(controller, "_run_planning_specimen_stage", fast_specimen_stage)
    monkeypatch.setattr(controller, "_run_planning_loop_tail", audited_tail)

    result = await controller._run_planning_cycle_series(
        first_spec=first_spec,
        design_constraints=first_spec,
        start_cycle=1,
    )

    assert result["ok"] is True
    assert len(cycle_records) == 20
    assert controller._state.loop_count == 20
    assert len(applied_recommendations) == 19
    for applied, cycle in zip(applied_recommendations, cycle_records[1:], strict=True):
        assert cycle["cell_size_mm"] == pytest.approx(applied["cell_size_mm"])
        assert cycle["relative_density"] == pytest.approx(applied["relative_density"])
