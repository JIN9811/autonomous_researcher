"""
Integration tests for immediate stop control behavior.
"""

import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode


@pytest.mark.asyncio
async def test_stop_terminates_active_run_quickly() -> None:
    controller = load_runtime()
    started = await controller.start(mode=Mode.TEST, goal="stop-control")
    assert started["ok"] is True

    await asyncio.sleep(0.2)
    stop_resp = await controller.stop()
    assert stop_resp["ok"] is True

    timeout_s = 2.0
    start_t = asyncio.get_running_loop().time()
    while True:
        snap = controller.snapshot()
        if not snap["is_running"]:
            break
        if asyncio.get_running_loop().time() - start_t > timeout_s:
            raise TimeoutError("controller did not stop within timeout")
        await asyncio.sleep(0.05)

    assert controller.snapshot()["state"]["stage"] == "complete"
