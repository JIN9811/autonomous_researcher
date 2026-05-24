"""
Integration tests for controller-driven test mode loop execution.
"""

import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode, Stage


@pytest.mark.asyncio
async def test_controller_completes_test_run() -> None:
    controller = load_runtime()
    result = await controller.start(mode=Mode.TEST, goal="integration test run")
    assert result["ok"] is True

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
