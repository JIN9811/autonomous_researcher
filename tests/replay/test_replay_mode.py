"""
Replay mode integration tests.
"""

import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode


@pytest.mark.asyncio
async def test_replay_mode_runs_after_test_trace() -> None:
    controller = load_runtime()
    await controller.start(mode=Mode.TEST, goal="generate trace")

    # Wait until the source test run is complete before replay start.
    timeout_s = 8.0
    start = asyncio.get_running_loop().time()
    while True:
        snapshot = controller.snapshot()
        stage = snapshot["state"]["stage"]
        if stage in {"complete", "error"} and not snapshot["is_running"]:
            break
        if asyncio.get_running_loop().time() - start > timeout_s:
            raise TimeoutError("test run did not finish before replay")
        await asyncio.sleep(0.1)

    replay_start = await controller.start(mode=Mode.REPLAY, goal="replay trace")
    assert replay_start["ok"] is True
    await asyncio.sleep(1.0)
    events = controller.recent_events()
    assert any(event.get("event_type") in {"replay_event", "replay_complete"} for event in events)
