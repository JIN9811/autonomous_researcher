from __future__ import annotations

import asyncio

import pytest

from backends.llm_lease import LLMLeaseBusy, LLMLeaseCoordinator


@pytest.mark.asyncio
async def test_higher_priority_waiter_runs_before_background_waiter() -> None:
    lease = LLMLeaseCoordinator()
    order: list[str] = []
    release_holder = asyncio.Event()

    async def holder() -> None:
        async with lease.acquire(priority=10, owner="workflow"):
            order.append("workflow")
            await release_holder.wait()

    async def waiter(owner: str, priority: int) -> None:
        async with lease.acquire(priority=priority, owner=owner):
            order.append(owner)

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0)
    background_task = asyncio.create_task(waiter("reconciliation", 30))
    await asyncio.sleep(0)
    chat_task = asyncio.create_task(waiter("operator-chat", 20))
    await asyncio.sleep(0)
    release_holder.set()
    await asyncio.gather(holder_task, background_task, chat_task)

    assert order == ["workflow", "operator-chat", "reconciliation"]


@pytest.mark.asyncio
async def test_nonblocking_background_lease_skips_when_busy() -> None:
    lease = LLMLeaseCoordinator()

    async with lease.acquire(priority=10, owner="workflow"):
        with pytest.raises(LLMLeaseBusy):
            async with lease.acquire(priority=30, owner="reconciliation", wait=False):
                raise AssertionError("busy lease must not be entered")

    status = lease.status()
    assert status["active"] is False
    assert status["waiting"] == []


@pytest.mark.asyncio
async def test_cancelled_waiter_is_removed() -> None:
    lease = LLMLeaseCoordinator()
    entered = asyncio.Event()

    async with lease.acquire(priority=10, owner="workflow"):
        task = asyncio.create_task(_wait_for_lease(lease, entered))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert lease.status()["waiting"] == []


async def _wait_for_lease(lease: LLMLeaseCoordinator, entered: asyncio.Event) -> None:
    async with lease.acquire(priority=30, owner="background"):
        entered.set()

