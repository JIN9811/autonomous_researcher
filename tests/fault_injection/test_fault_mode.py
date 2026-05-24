"""
Fault injection integration tests.
"""

import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode


@pytest.mark.asyncio
async def test_fault_injection_emits_retry_or_error() -> None:
    controller = load_runtime()
    await controller.start(
        mode=Mode.FAULT_INJECTION,
        goal="fault mode",
        fault="model_timeout",
        fault_stage="manipulation",
    )
    await asyncio.sleep(2.0)
    events = controller.recent_events()
    assert any(event.get("event_type") in {"retry", "fatal_error"} for event in events)
