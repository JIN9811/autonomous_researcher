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

    timeout_s = 240.0
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
    assert snapshot["state"]["loop_count"] == 5
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
