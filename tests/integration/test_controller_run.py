"""
Integration tests for controller-driven test mode loop execution.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode, Stage


@pytest.mark.asyncio
async def test_controller_completes_test_run() -> None:
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

    timeout_s = 8.0
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
    assert snapshot["state"]["run_metadata"]["equipment_handoff"]["status"] == "ready_for_analysis"
    assert snapshot["state"]["latest_analysis"]["equipment_ok"] is True
    assert snapshot["state"]["latest_analysis"]["cae_result"]["ok"] is True
    assert snapshot["state"]["latest_analysis"]["cae_result"]["boundary_condition"] == "bottom_fixed_support"

    run_dir = json_log_path.parent
    artifact_paths = {item.relative_to(run_dir).as_posix() for item in run_dir.rglob("*") if item.is_file()}
    runtime_artifacts = snapshot["state"]["run_metadata"].get("runtime_artifacts", [])
    runtime_artifact_paths = {str(item.get("path") or "") for item in runtime_artifacts if isinstance(item, dict)}
    assert any(path.startswith("runtime/bo/") and path.endswith("_bo_progress.svg") for path in artifact_paths)
    assert any(path.startswith("runtime/analysis/") and path.endswith(".contour.svg") for path in artifact_paths)
    assert any(path.startswith("runtime/analysis/") and path.endswith(".report.json") for path in artifact_paths)
    assert any(path.startswith("runtime/bo/") and path.endswith("_bo_progress.svg") for path in runtime_artifact_paths)
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
