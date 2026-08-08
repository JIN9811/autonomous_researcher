"""Priority-aware cooperative lease for shared LLM inference capacity."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator


GUARDIAN_PRIORITY = 0
WORKFLOW_PRIORITY = 10
OPERATOR_CHAT_PRIORITY = 20
RECONCILIATION_PRIORITY = 30


class LLMLeaseBusy(RuntimeError):
    """Raised when a non-blocking lease cannot be acquired immediately."""


@dataclass(frozen=True, slots=True)
class _Waiter:
    ticket: int
    priority: int
    owner: str


class LLMLeaseCoordinator:
    """Serialize LLM calls while letting safety and active work run first."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._waiters: list[_Waiter] = []
        self._active: _Waiter | None = None
        self._next_ticket = 0
        self._last_owner = ""
        self._last_priority: int | None = None

    @asynccontextmanager
    async def acquire(self, priority: int, owner: str, *, wait: bool = True) -> AsyncIterator[None]:
        waiter = await self._enter(priority=int(priority), owner=str(owner or "anonymous"), wait=wait)
        try:
            yield
        finally:
            await self._leave(waiter)

    async def _enter(self, *, priority: int, owner: str, wait: bool) -> _Waiter:
        async with self._condition:
            waiter = _Waiter(ticket=self._next_ticket, priority=priority, owner=owner)
            self._next_ticket += 1
            if not wait:
                if self._active is not None or self._waiters:
                    raise LLMLeaseBusy(f"LLM lease busy: owner={self._active.owner if self._active else 'queued'}")
                self._active = waiter
                return waiter
            self._waiters.append(waiter)
            try:
                while self._active is not None or waiter != min(
                    self._waiters,
                    key=lambda item: (item.priority, item.ticket),
                ):
                    await self._condition.wait()
                self._waiters.remove(waiter)
                self._active = waiter
                return waiter
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                raise

    async def _leave(self, waiter: _Waiter) -> None:
        async with self._condition:
            if self._active == waiter:
                self._last_owner = waiter.owner
                self._last_priority = waiter.priority
                self._active = None
                self._condition.notify_all()

    def status(self) -> dict[str, object]:
        active = self._active
        waiting = sorted(self._waiters, key=lambda item: (item.priority, item.ticket))
        return {
            "active": active is not None,
            "active_owner": active.owner if active else "",
            "active_priority": active.priority if active else None,
            "last_owner": self._last_owner,
            "last_priority": self._last_priority,
            "waiting": [
                {"owner": item.owner, "priority": item.priority, "ticket": item.ticket}
                for item in waiting
            ],
        }
