"""Regression tests for LeRobot port API event-loop responsiveness."""

from __future__ import annotations

import asyncio
from threading import Event

import pytest

import app.main as main_module


@pytest.mark.asyncio
async def test_ports_detect_does_not_block_safety_event_loop(monkeypatch) -> None:
    """Slow hardware discovery must not starve PLC safety polling/recovery."""
    started = Event()
    release = Event()

    class SlowBridge:
        def ports_detect(self, payload: dict[str, object]) -> dict[str, object]:
            started.set()
            release.wait(timeout=1.0)
            return {"ok": True, "tool": "lerobot.ports.detect", "payload": payload}

    async def publish(result: dict[str, object]) -> dict[str, object]:
        return result

    monkeypatch.setattr(main_module, "_lerobot_bridge", lambda: SlowBridge())
    monkeypatch.setattr(main_module, "_publish_lerobot_result", publish)
    request = main_module.LeRobotDevicePortAPIRequest(
        mode="live",
        profile_id="robotis_omx_ai",
        device_role="camera",
        camera_key="top",
    )

    task = asyncio.create_task(main_module.post_lerobot_ports_detect(request))
    try:
        assert await asyncio.to_thread(started.wait, 0.5)
        await asyncio.sleep(0)
        assert not task.done(), "hardware discovery blocked the shared safety event loop"
    finally:
        release.set()

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result["ok"] is True
