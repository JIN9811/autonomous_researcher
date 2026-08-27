"""Single-owner polling and recovery service for the bounded PLC bridge."""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import inspect
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Protocol
from uuid import uuid4

from device_bridges.plc_bridge import PLCBridge, VirtualPLCTransport
from utils.plc_safety_state import (
    PLCCommand,
    PLCRegisterSnapshot,
    PLCSafetyState,
    PLCTransition,
    classify_snapshot,
    decode_snapshot,
)


PLC_PHYSICAL_SOURCE = "plc_pb2"
_ACTIVE_HANDSHAKE_PHASES = frozenset({"validated", "acknowledged", "release_observed"})
_SAMPLE_FAILURE_CODES = frozenset(
    {
        "PLC_STATE_STALE",
        "PLC_INVALID_COMMAND_VALUE",
        "PLC_INVALID_REGISTER_VALUE",
        "PLC_COMMAND_WITHOUT_ESTOP",
    }
)
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


class PLCControllerCallbacks(Protocol):
    """Controller-owned operations the PLC transport may request."""

    async def emergency_stop(
        self, source: str, details: dict[str, object]
    ) -> bool | dict[str, object]: ...

    async def plc_recovery_readiness(
        self, command: str
    ) -> bool | dict[str, object]: ...

    async def emergency_resume(
        self, source: str, transaction_id: str | None = None
    ) -> bool | dict[str, object]: ...

    async def emergency_reset(
        self, source: str, transaction_id: str | None = None
    ) -> bool | dict[str, object]: ...


class PLCBridgeService:
    """Own exactly one PLC poll task while exposing cached, bounded state."""

    def __init__(
        self,
        bridge: PLCBridge,
        callbacks: PLCControllerCallbacks,
        *,
        host: str = "192.168.50.90",
        port: int = 4999,
        poll_interval_s: float = 0.2,
        stale_after_s: float = 1.0,
        handshake_timeout_s: float = 5.0,
        state_path: Path | str = Path("memory/plc_bridge_state.json"),
        event_path: Path | str | None = None,
        event_limit: int = 100,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")
        if stale_after_s <= 0:
            raise ValueError("stale_after_s must be positive")
        if handshake_timeout_s <= 0:
            raise ValueError("handshake_timeout_s must be positive")
        if event_limit <= 0:
            raise ValueError("event_limit must be positive")

        self._bridge = bridge
        self._callbacks = callbacks
        self._host = host
        self._port = port
        self._poll_interval_s = poll_interval_s
        self._stale_after_s = stale_after_s
        self._handshake_timeout_s = handshake_timeout_s
        self._state_path = Path(state_path)
        self._event_path = (
            Path(event_path)
            if event_path is not None
            else self._state_path.with_name("plc_bridge_events.json")
        )
        self._event_limit = event_limit
        loaded_events = self._load_events()
        self._events: deque[dict[str, object]] = deque(
            loaded_events[-event_limit:], maxlen=event_limit
        )
        self._event_revision = max(
            (
                int(event.get("revision", 0))
                for event in self._events
                if type(event.get("revision")) is int
            ),
            default=0,
        )
        self._io_executor: ThreadPoolExecutor | None = self._new_io_executor()
        self._lifecycle_lock = asyncio.Lock()
        self._state_machine_lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._running = False
        self._connected = False
        self._transport_open = False
        self._stale = False
        self._sequence = 0
        self._previous: PLCRegisterSnapshot | None = None
        self._latest: PLCRegisterSnapshot | None = None
        self._last_fresh_processed_monotonic: float | None = None
        self._safety_state = PLCSafetyState.DISCONNECTED
        self._active_estop_sources: set[str] = set()
        self._controller_latch_confirmed_sources: set[str] = set()
        self._pc_estop_origins: set[str] = set()
        self._failure_code: str | None = None
        self._last_error: str | None = None
        self._transaction = self._load_transaction()
        self._restore_persisted_latch()
        self._reconnect_attempt = 0
        self._poll_worker_starts = 0
        self._last_latency_ms: float | None = None

    async def start(self) -> bool:
        """Start the sole polling task, returning false when it already exists."""
        async with self._lifecycle_lock:
            if self.monitor_running:
                return False
            self._ensure_io_executor()
            self._running = True
            self._poll_worker_starts += 1
            self._poll_task = asyncio.create_task(
                self._poll_loop(), name="plc-bridge-poller"
            )
            return True

    async def shutdown(self) -> None:
        """Stop polling and lower D102 best-effort without ever clearing D101."""
        async with self._lifecycle_lock:
            cleanup_task = asyncio.create_task(
                self._shutdown_unlocked(), name="plc-bridge-shutdown"
            )
            cancelled = False
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    cancelled = True
            await cleanup_task
            if cancelled:
                raise asyncio.CancelledError

    async def _shutdown_unlocked(self) -> None:
        self._running = False
        task = self._poll_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        if self._connected or self._transport_open:
            try:
                await self._write_register("D102", 0)
            except Exception:
                pass
            try:
                await self._run_io(self._bridge.disconnect)
            except Exception:
                pass
            finally:
                self._transport_open = False
        await self._close_io_executor()
        await self.mark_disconnected("service shutdown")

    async def preflight(self) -> dict[str, object]:
        """Connect and validate the register contract without acknowledging input."""
        async with self._lifecycle_lock:
            async with self._state_machine_lock:
                if self.active_handshake:
                    return {
                        "ok": False,
                        "failure_code": "PLC_PREFLIGHT_HANDSHAKE_ACTIVE",
                        "message": "PLC preflight is blocked during a recovery handshake.",
                        "register_snapshot": self._snapshot_payload(self._latest),
                        "status": self.status(),
                    }
                self._ensure_io_executor()
                if not self._connected:
                    await self._connect()
                snapshot = await self._read_snapshot()
                transition = self._observe_preflight_snapshot(snapshot)
                return {
                    "ok": transition.state is not PLCSafetyState.PROTOCOL_FAULT,
                    "failure_code": transition.failure_code,
                    "register_snapshot": self._snapshot_payload(snapshot),
                    "status": self.status(),
                }

    async def reconcile(self) -> dict[str, object]:
        """Read a fresh snapshot after reconnect without replaying physical commands."""
        snapshot = await self._read_snapshot()
        await self._observe_snapshot(snapshot, allow_recovery=False, reconciling=True)
        return self.status()

    async def set_terminal_estop(
        self, details: dict[str, object]
    ) -> dict[str, object]:
        """Synchronize a Controller-latched qualifying terminal error to D101."""
        return await self.sync_estop("runtime_terminal_error", details)

    async def sync_estop(
        self, source: str, details: dict[str, object]
    ) -> dict[str, object]:
        """Latch locally and perform the internal set-only D101 synchronization."""
        async with self._state_machine_lock:
            return await self._sync_estop_locked(source, details)

    async def request_gui_recovery(self, command: str) -> dict[str, object]:
        """Route GUI recovery through the service latch and handshake authority."""
        clean_command = str(command or "").strip().lower()
        if clean_command not in {"resume", "reset"}:
            raise ValueError("GUI recovery command must be resume or reset")

        async with self._state_machine_lock:
            if self.active_handshake:
                return self._gui_recovery_rejection(
                    "PLC_RECOVERY_HANDSHAKE_ACTIVE",
                    "PLC recovery is already waiting for the physical handshake.",
                )
            blocking_states = {
                PLCSafetyState.ESTOP_LATCHED,
                PLCSafetyState.RESUME_REQUESTED,
                PLCSafetyState.RESET_REQUESTED,
                PLCSafetyState.HANDSHAKE_ASSERTED,
                PLCSafetyState.RELEASE_OBSERVED,
                PLCSafetyState.PROTOCOL_FAULT,
            }
            if self._active_estop_sources or self._safety_state in blocking_states:
                return self._gui_recovery_rejection(
                    "PLC_PHYSICAL_RECOVERY_REQUIRED",
                    "The PLC safety latch requires a completed physical recovery handshake.",
                )

            # Transaction-bearing callbacks remain exclusive to _advance_handshake.
            callback = (
                self._callbacks.emergency_resume
                if clean_command == "resume"
                else self._callbacks.emergency_reset
            )
            try:
                result = await self._maybe_await(callback("gui_estop", None))
            except Exception as exc:
                return self._gui_recovery_rejection(
                    f"GUI_RUNTIME_{clean_command.upper()}_FAILED", str(exc)
                )
            if isinstance(result, dict):
                return result
            if result is True:
                return {
                    "ok": True,
                    "message": f"Emergency {clean_command} complete.",
                }
            return self._gui_recovery_rejection(
                f"GUI_RUNTIME_{clean_command.upper()}_FAILED",
                f"Controller rejected GUI emergency {clean_command}.",
            )

    async def _sync_estop_locked(
        self, source: str, details: dict[str, object]
    ) -> dict[str, object]:
        clean_source = str(source or "").strip()
        if not clean_source:
            raise ValueError("E-STOP source is required")
        clean_details = self._sanitize(details)
        assert isinstance(clean_details, dict)
        await self._ensure_estop(clean_source, clean_details)
        self._pc_estop_origins.add(clean_source)
        preserve_recovery = self.active_handshake
        identity = self._runtime_identity()
        phase = (
            "terminal_estop"
            if clean_source == "runtime_terminal_error"
            else "estop_sync"
        )
        if preserve_recovery:
            assert self._transaction is not None
            transaction_sources = {
                str(item)
                for item in self._transaction.get("source_set", [])
                if str(item).strip()
            }
            transaction_sources.update(self._active_estop_sources)
            self._transaction["source_set"] = sorted(transaction_sources)
        else:
            self._transaction = {
                "schema": "plc_bridge_transaction.v1",
                "transaction_id": f"plc-{uuid4().hex}",
                "phase": phase,
                "source": clean_source,
                "source_set": sorted(self._active_estop_sources),
                "details": clean_details,
                "created_at": time.time(),
                "run_id": identity["run_id"],
                "session_id": identity["session_id"],
                "snapshot_before_ack": self._snapshot_payload(self._latest),
                "write_evidence": [],
                "validation_result": {"ok": True, "kind": "local_estop_latched"},
                "final_outcome": "pending_sync",
                "final_failure": None,
            }
        self._persist_transaction()
        if not self._connected:
            self._pc_estop_origins.discard(clean_source)
            if preserve_recovery:
                self._record_estop_sync_evidence(
                    clean_source,
                    clean_details,
                    outcome="failed",
                    message="PLC transport is not connected",
                )
            else:
                self._finish_estop_sync_failure("PLC transport is not connected")
            return self.status()

        try:
            readback = await self._write_with_evidence(
                "D101", 1, before=self._latest, require_readback=True
            )
            if readback is None or readback.d101 != 1:
                raise RuntimeError("D101 set was not observed in a fresh readback")
        except Exception as exc:
            if preserve_recovery:
                self._record_estop_sync_evidence(
                    clean_source,
                    clean_details,
                    outcome="failed",
                    message=str(exc),
                )
            else:
                self._finish_estop_sync_failure(str(exc))
            return self.status()

        if preserve_recovery:
            self._record_estop_sync_evidence(
                clean_source,
                clean_details,
                outcome="synchronized",
            )
        else:
            self._transaction["phase"] = phase
            self._transaction["final_outcome"] = "synchronized"
            self._transaction["completed_at"] = time.time()
            self._transaction["final_failure"] = None
            self._persist_transaction()
        self._emit(
            "plc.estop.synchronized",
            {"source": clean_source, "details": clean_details},
        )
        return self.status()

    async def accept_snapshot(
        self,
        *,
        words: tuple[int, int, int],
        handshake_timeout_s: float | None = None,
    ) -> None:
        """Accept a fresh snapshot; used by the poll owner and virtual test helpers."""
        self._sequence += 1
        snapshot = PLCRegisterSnapshot(
            d100=words[0],
            d101=words[1],
            d102=words[2],
            sequence=self._sequence,
            received_monotonic=time.monotonic(),
        )
        await self._observe_snapshot(
            snapshot,
            allow_recovery=True,
            reconciling=False,
            handshake_timeout_s=handshake_timeout_s,
        )

    async def mark_disconnected(self, reason: str) -> None:
        """Disable the optional layer while retaining any observed physical latch."""
        was_connected = self._connected
        self._connected = False
        self._stale = False
        self._last_error = str(reason)
        if self._active_estop_sources:
            self._safety_state = PLCSafetyState.ESTOP_LATCHED
        else:
            self._safety_state = PLCSafetyState.DISCONNECTED
        if was_connected:
            self._emit("plc.bridge.disconnected", {"reason": str(reason)})

    async def virtual_estop(self) -> None:
        await self._set_virtual_words(0, 1)

    async def virtual_resume(self) -> None:
        await self._set_virtual_words(1, 1)

    async def virtual_reset(self) -> None:
        await self._set_virtual_words(2, 1)

    @property
    def monitor_running(self) -> bool:
        return self._poll_task is not None and not self._poll_task.done()

    @property
    def active_handshake(self) -> bool:
        return bool(
            self._transaction
            and self._transaction.get("phase") in _ACTIVE_HANDSHAKE_PHASES
        )

    def status(self) -> dict[str, object]:
        self._refresh_stale_state()
        transaction = (
            self._sanitize(self._transaction) if self._transaction is not None else None
        )
        sample_age_s = (
            max(0.0, time.monotonic() - self._latest.received_monotonic)
            if self._latest is not None
            else None
        )
        if self._connected:
            connection_state = "stale" if self._stale else "online"
        elif self.monitor_running:
            connection_state = "reconnecting"
        else:
            connection_state = "offline"
        return {
            "plc_layer_active": self._connected and not self._stale,
            "connection_state": connection_state,
            "monitor_state": "running" if self.monitor_running else "stopped",
            "active_handshake": self.active_handshake,
            "transport": self._transport_name(),
            "safety_state": self._safety_state.value,
            "active_estop_sources": sorted(self._active_estop_sources),
            "failure_code": self._failure_code,
            "last_error": self._last_error,
            "register_snapshot": self._snapshot_payload(self._latest),
            "pending_command": self._pending_command(),
            "transaction": transaction,
            "reconnect_attempt": self._reconnect_attempt,
            "poll_worker_starts": self._poll_worker_starts,
            "last_latency_ms": self._last_latency_ms,
            "sample_age_s": sample_age_s,
            "stale_after_s": self._stale_after_s,
            "event_revision": self._event_revision,
        }

    def events(self) -> list[dict[str, object]]:
        return [dict(event) for event in self._events]

    def _gui_recovery_rejection(self, code: str, message: str) -> dict[str, object]:
        transaction_id = (
            self._transaction.get("transaction_id")
            if isinstance(self._transaction, dict)
            else None
        )
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": code,
            "message": message,
            "transaction_id": transaction_id,
            "active_estop_sources": sorted(self._active_estop_sources),
        }

    async def _poll_loop(self) -> None:
        backoff_s = self._poll_interval_s
        needs_initial_reconciliation = True
        while self._running:
            try:
                if not self._connected or needs_initial_reconciliation:
                    if not self._connected:
                        await self._connect()
                    await self.reconcile()
                    needs_initial_reconciliation = False
                else:
                    snapshot = await self._read_snapshot()
                    await self._observe_snapshot(
                        snapshot, allow_recovery=True, reconciling=False
                    )
                self._reconnect_attempt = 0
                backoff_s = self._poll_interval_s
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.mark_disconnected(str(exc))
                self._reconnect_attempt += 1
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 5.0)

    async def _connect(self) -> None:
        if self._transport_open:
            try:
                await self._run_io(self._bridge.disconnect)
            finally:
                self._transport_open = False
        await self._run_io(self._bridge.connect, self._host, self._port)
        self._transport_open = True
        self._connected = True
        self._stale = False
        self._last_error = None
        self._emit("plc.bridge.connected", {"host": self._host, "port": self._port})

    async def _read_snapshot(self) -> PLCRegisterSnapshot:
        started_monotonic = time.monotonic()
        snapshot = await self._run_io(self._bridge.read_snapshot)
        self._last_latency_ms = max(
            0.0, (time.monotonic() - started_monotonic) * 1000
        )
        self._sequence = max(self._sequence, snapshot.sequence)
        return snapshot

    async def _write_register(self, device: str, value: int) -> None:
        await self._run_io(self._bridge.write_register, device, value)

    async def _run_io(self, operation: Any, *args: object) -> Any:
        executor = self._io_executor
        if executor is None:
            raise RuntimeError("PLC I/O worker is shut down")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, partial(operation, *args))

    async def _close_io_executor(self) -> None:
        executor = self._io_executor
        if executor is None:
            return
        self._io_executor = None
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=False)

    async def _observe_snapshot(
        self,
        snapshot: PLCRegisterSnapshot,
        *,
        allow_recovery: bool,
        reconciling: bool,
        handshake_timeout_s: float | None = None,
    ) -> None:
        async with self._state_machine_lock:
            await self._observe_snapshot_locked(
                snapshot,
                allow_recovery=allow_recovery,
                reconciling=reconciling,
                handshake_timeout_s=handshake_timeout_s,
            )

    def _observe_preflight_snapshot(self, snapshot: PLCRegisterSnapshot) -> PLCTransition:
        """Cache and validate preflight input without advancing safety recovery."""
        transition = classify_snapshot(snapshot)
        self._cache_fresh_snapshot(
            snapshot,
            valid=transition.state is not PLCSafetyState.PROTOCOL_FAULT,
        )
        self._set_observed_safety_state(transition.state)
        return transition

    async def _observe_snapshot_locked(
        self,
        snapshot: PLCRegisterSnapshot,
        *,
        allow_recovery: bool,
        reconciling: bool,
        handshake_timeout_s: float | None = None,
    ) -> None:
        previous = self._previous
        transition = decode_snapshot(previous, snapshot)
        self._cache_fresh_snapshot(
            snapshot,
            valid=transition.state is not PLCSafetyState.PROTOCOL_FAULT,
        )

        if transition.state is PLCSafetyState.PROTOCOL_FAULT:
            failure_code = transition.failure_code or "PLC_INVALID_COMMAND_VALUE"
            fault_changed = (
                self._safety_state is not PLCSafetyState.PROTOCOL_FAULT
                or self._failure_code != failure_code
            )
            self._safety_state = transition.state
            self._set_failure(failure_code, "invalid PLC snapshot")
            if fault_changed:
                self._emit(
                    "plc.protocol_fault", {"failure_code": self._failure_code}
                )
            return

        if snapshot.d101 == 0:
            self._pc_estop_origins.clear()
        elif self._pc_estop_origins:
            for source in sorted(self._pc_estop_origins):
                await self._ensure_estop(
                    source,
                    {
                        "snapshot": self._snapshot_payload(snapshot),
                        "origin": "pc",
                    },
                )
        else:
            await self._ensure_estop(
                PLC_PHYSICAL_SOURCE,
                {"snapshot": self._snapshot_payload(snapshot), "origin": "plc"},
            )

        if reconciling and (
            snapshot.d102 == 1
            or (
                self._transaction is not None
                and self._transaction.get("phase") in _ACTIVE_HANDSHAKE_PHASES
            )
            or self._verified_immediate_release_write_failure(snapshot)
        ):
            await self._reconcile_uncertain_handshake(snapshot)
            return

        if (
            self._transaction is not None
            and self._transaction.get("phase") == "acknowledged"
        ):
            await self._advance_handshake(snapshot, handshake_timeout_s)
            return

        self._set_observed_safety_state(transition.state)
        if reconciling and snapshot.d100 in {1, 2} and snapshot.d101 == 1:
            if snapshot.d100 == 1:
                await self._start_handshake(PLCCommand.RESUME, snapshot)
                return
            await self._record_reconciliation_required(snapshot)
            return

        if allow_recovery and transition.command is not PLCCommand.NONE:
            await self._start_handshake(transition.command, snapshot)

    async def _ensure_estop(
        self, source: str, details: dict[str, object]
    ) -> None:
        if source not in self._active_estop_sources:
            self._active_estop_sources.add(source)
            self._emit("plc.estop.latched", {"source": source, "details": details})
            self._safety_state = PLCSafetyState.ESTOP_LATCHED
        if source not in self._controller_latch_confirmed_sources:
            result = await self._maybe_await(
                self._callbacks.emergency_stop(source, details)
            )
            if isinstance(result, dict) and result.get("ok") is not True:
                raise RuntimeError(
                    str(result.get("failure_code") or "PLC_CONTROLLER_RELATCH_FAILED")
                )
            self._controller_latch_confirmed_sources.add(source)
        self._safety_state = PLCSafetyState.ESTOP_LATCHED

    async def _start_handshake(
        self, command: PLCCommand, snapshot: PLCRegisterSnapshot
    ) -> None:
        command_name = command.value
        try:
            readiness = await self._maybe_await(
                self._callbacks.plc_recovery_readiness(command_name)
            )
        except Exception as exc:
            readiness = {
                "ok": False,
                "failure_code": "PLC_RESUME_READINESS_FAILED",
                "message": str(exc),
            }
        ready, failure_code = self._result_status(
            readiness, "PLC_RESUME_READINESS_FAILED"
        )
        if not ready:
            self._set_failure(
                failure_code, f"Controller rejected PLC {command_name}"
            )
            self._emit(
                "plc.request.rejected",
                {"command": command_name, "failure_code": failure_code},
            )
            return

        identity = self._runtime_identity()
        prior_details = (
            self._transaction.get("details")
            if isinstance(self._transaction, dict)
            else None
        )
        sources = sorted(self._active_estop_sources or {PLC_PHYSICAL_SOURCE})
        self._transaction = {
            "schema": "plc_bridge_transaction.v1",
            "transaction_id": f"plc-{uuid4().hex}",
            "command": command_name,
            "phase": "validated",
            "created_at": time.time(),
            "acknowledged_at_wall": None,
            "run_id": identity["run_id"],
            "session_id": identity["session_id"],
            "source_set": sources,
            "source_context": self._sanitize(prior_details),
            "validation_result": self._sanitize(readiness),
            "snapshot_before_ack": self._snapshot_payload(snapshot),
            "write_evidence": [],
            "final_outcome": "pending",
            "final_failure": None,
        }
        self._persist_transaction()
        try:
            readback = await self._write_with_evidence(
                "D102", 1, before=snapshot, require_readback=True
            )
            if readback is None or (
                readback.d102 != 1 and self._words(readback) != (0, 0, 0)
            ):
                raise RuntimeError(
                    "D102 assertion was not observed in a fresh readback"
                )
        except Exception as exc:
            try:
                await self._write_register("D102", 0)
            except Exception:
                pass
            self._set_failure("PLC_WRITE_FAILED", str(exc))
            self._finish_transaction_failure(
                "write_failed", "PLC_WRITE_FAILED", str(exc)
            )
            return

        self._transaction["phase"] = "acknowledged"
        self._transaction["acknowledged_at_wall"] = time.time()
        self._persist_transaction()
        self._safety_state = PLCSafetyState.HANDSHAKE_ASSERTED
        self._emit("plc.handshake.asserted", {"command": command_name})
        if readback is not None and self._words(readback) == (0, 0, 0):
            await self._advance_handshake(readback, None)

    async def _advance_handshake(
        self, snapshot: PLCRegisterSnapshot, handshake_timeout_s: float | None
    ) -> None:
        assert self._transaction is not None
        words = self._words(snapshot)
        if words in {(0, 0, 1), (0, 0, 0)}:
            self._transaction["phase"] = "release_observed"
            self._transaction["snapshot_release_observed"] = self._snapshot_payload(
                snapshot
            )
            self._persist_transaction()
            self._safety_state = PLCSafetyState.RELEASE_OBSERVED
            self._emit(
                "plc.handshake.release_observed",
                self._snapshot_payload(snapshot) or {},
            )
            readback = snapshot
            if words == (0, 0, 1):
                try:
                    readback = await self._write_with_evidence(
                        "D102", 0, before=snapshot, require_readback=True
                    )
                except Exception as exc:
                    await self._fail_recovery(
                        phase="clear_failed",
                        failure_code="PLC_D102_CLEAR_FAILED",
                        message=str(exc),
                    )
                    return
            if readback is None or self._words(readback) != (0, 0, 0):
                if readback is not None and readback.d101 == 1:
                    self._active_estop_sources.add(PLC_PHYSICAL_SOURCE)
                    source_set = {
                        str(source)
                        for source in self._transaction.get("source_set", [])
                        if str(source).strip()
                    }
                    source_set.add(PLC_PHYSICAL_SOURCE)
                    self._transaction["source_set"] = sorted(source_set)
                    self._emit(
                        "plc.estop.latched",
                        {
                            "source": PLC_PHYSICAL_SOURCE,
                            "reason": "d101_reasserted_during_recovery",
                        },
                    )
                observed = self._snapshot_payload(readback)
                await self._fail_recovery(
                    phase="readback_failed",
                    failure_code="PLC_HANDSHAKE_CLEAR_NOT_OBSERVED",
                    message=f"expected D100-D102 all zero, observed {observed}",
                )
                return

            await self._complete_released_handshake()
            return

        timeout_s = (
            handshake_timeout_s
            if handshake_timeout_s is not None
            else self._handshake_timeout_s
        )
        acknowledged_at = self._transaction.get("acknowledged_at_wall")
        if (
            not isinstance(acknowledged_at, (int, float))
            or isinstance(acknowledged_at, bool)
            or time.time() - acknowledged_at > timeout_s
        ):
            try:
                await self._write_with_evidence(
                    "D102", 0, before=snapshot, require_readback=False
                )
            except Exception as exc:
                self._last_error = str(exc)
            self._set_failure(
                "PLC_HANDSHAKE_TIMEOUT", "ladder did not clear D100/D101"
            )
            self._safety_state = PLCSafetyState.ESTOP_LATCHED
            self._finish_transaction_failure(
                "timed_out",
                "PLC_HANDSHAKE_TIMEOUT",
                "ladder did not clear D100/D101",
            )

    async def _complete_released_handshake(self) -> None:
        """Complete Controller recovery after a verified all-zero PLC snapshot."""
        assert self._transaction is not None
        command = str(self._transaction["command"])
        transaction_id = str(self._transaction["transaction_id"])
        try:
            readiness = await self._maybe_await(
                self._callbacks.plc_recovery_readiness(command)
            )
        except Exception as exc:
            readiness = {
                "ok": False,
                "failure_code": "PLC_RESUME_READINESS_FAILED",
                "message": str(exc),
            }
        self._transaction["post_release_validation_result"] = self._sanitize(readiness)
        ready, failure_code = self._result_status(
            readiness, "PLC_RESUME_READINESS_FAILED"
        )
        self._persist_transaction()
        if not ready:
            await self._fail_recovery(
                phase="release_recovery_rejected",
                failure_code=failure_code,
                message=f"Controller rejected released PLC {command}",
            )
            return

        try:
            if command == PLCCommand.RESUME.value:
                callback_result = await self._maybe_await(
                    self._callbacks.emergency_resume("plc", transaction_id)
                )
                callback_failure = "PLC_RUNTIME_RESUME_FAILED"
            else:
                callback_result = await self._maybe_await(
                    self._callbacks.emergency_reset("plc", transaction_id)
                )
                callback_failure = "PLC_RUNTIME_RESET_FAILED"
        except Exception as exc:
            await self._fail_recovery(
                phase="controller_failed",
                failure_code=(
                    "PLC_RUNTIME_RESUME_FAILED"
                    if command == PLCCommand.RESUME.value
                    else "PLC_RUNTIME_RESET_FAILED"
                ),
                message=str(exc),
            )
            return

        self._transaction["controller_result"] = self._sanitize(callback_result)
        callback_ok, callback_detail = self._result_status(
            callback_result, callback_failure
        )
        self._persist_transaction()
        if not callback_ok:
            await self._fail_recovery(
                phase="controller_failed",
                failure_code=callback_failure,
                message=f"Controller rejected recovery: {callback_detail}",
            )
            return

        transaction_sources = {
            str(source)
            for source in self._transaction.get("source_set", [])
            if str(source).strip()
        }
        self._active_estop_sources.difference_update(transaction_sources)
        self._controller_latch_confirmed_sources.difference_update(transaction_sources)
        self._pc_estop_origins.difference_update(transaction_sources)
        self._failure_code = None
        self._last_error = None
        self._safety_state = (
            PLCSafetyState.ESTOP_LATCHED
            if self._active_estop_sources
            else PLCSafetyState.NORMAL
        )
        self._transaction["phase"] = "completed"
        self._transaction["completed_at"] = time.time()
        self._transaction["final_outcome"] = "success"
        self._transaction["final_failure"] = None
        self._persist_transaction()
        self._emit(
            "plc.handshake.completed",
            {"command": command, "transaction_id": transaction_id},
        )

    async def _fail_recovery(
        self, *, phase: str, failure_code: str, message: str
    ) -> None:
        assert self._transaction is not None
        sources = {
            str(source)
            for source in self._transaction.get("source_set", [])
            if str(source).strip()
        }
        if not sources:
            sources = set(self._active_estop_sources) or {PLC_PHYSICAL_SOURCE}
        self._active_estop_sources.update(sources)
        self._safety_state = PLCSafetyState.ESTOP_LATCHED
        self._set_failure(failure_code, message)
        self._finish_transaction_failure(phase, failure_code, message)

        relatch_errors: list[str] = []
        for source in sorted(sources):
            try:
                relatch_result = await self._maybe_await(
                    self._callbacks.emergency_stop(
                        source,
                        {
                            "reason": "plc_recovery_failed",
                            "failure_code": failure_code,
                            "transaction_id": self._transaction["transaction_id"],
                        },
                    )
                )
                relatch_ok, relatch_failure = self._result_status(
                    relatch_result, "PLC_CONTROLLER_RELATCH_FAILED"
                )
                if isinstance(relatch_result, dict) and not relatch_ok:
                    raise RuntimeError(relatch_failure)
                self._controller_latch_confirmed_sources.add(source)
            except Exception as exc:
                self._controller_latch_confirmed_sources.discard(source)
                relatch_errors.append(f"Controller {source}: {exc}")

        self._pc_estop_origins.update(sources)
        if self._connected:
            try:
                readback = await self._write_with_evidence(
                    "D101", 1, before=self._latest, require_readback=True
                )
                if readback is None or readback.d101 != 1:
                    raise RuntimeError("D101 relatch was not observed")
            except Exception as exc:
                relatch_errors.append(f"D101: {exc}")
        if relatch_errors:
            self._transaction["relatch_errors"] = self._sanitize(relatch_errors)
        self._transaction["source_set"] = sorted(self._active_estop_sources)
        self._persist_transaction()
        self._emit(
            "plc.handshake.failed",
            {
                "failure_code": failure_code,
                "phase": phase,
                "transaction_id": self._transaction["transaction_id"],
            },
        )

    async def _reconcile_uncertain_handshake(
        self, snapshot: PLCRegisterSnapshot
    ) -> None:
        existing = self._transaction or {}
        verified_immediate_release = self._verified_immediate_release_write_failure(
            snapshot
        )
        sources = {
            str(source)
            for source in existing.get("source_set", [])
            if str(source).strip()
        }
        if not sources and isinstance(existing.get("source"), str):
            sources.add(str(existing["source"]))
        if not sources:
            sources = set(self._active_estop_sources) or {PLC_PHYSICAL_SOURCE}
        controller_relatch_errors: list[str] = []
        for source in sorted(sources):
            try:
                await self._ensure_estop(
                    source,
                    {
                        "reason": "plc_reconciliation",
                        "snapshot": self._snapshot_payload(snapshot),
                    },
                )
            except Exception as exc:
                controller_relatch_errors.append(f"Controller {source}: {exc}")

        identity = self._runtime_identity()
        self._transaction = {
            **existing,
            "schema": "plc_bridge_transaction.v1",
            "transaction_id": str(
                existing.get("transaction_id") or f"plc-{uuid4().hex}"
            ),
            "created_at": existing.get("created_at", time.time()),
            "run_id": str(existing.get("run_id") or identity["run_id"]),
            "session_id": str(
                existing.get("session_id") or identity["session_id"]
            ),
            "source_set": sorted(sources),
            "reconciled_snapshot": self._snapshot_payload(snapshot),
            "write_evidence": (
                list(existing.get("write_evidence", []))
                if isinstance(existing.get("write_evidence"), list)
                else []
            ),
            "final_outcome": "recovery_required",
        }
        if controller_relatch_errors:
            self._transaction["relatch_errors"] = self._sanitize(
                controller_relatch_errors
            )

        if verified_immediate_release:
            self._transaction["phase"] = "release_observed"
            self._transaction["reconciled_fast_release"] = True
            self._transaction["final_outcome"] = "pending"
            self._transaction["final_failure"] = None
            self._safety_state = PLCSafetyState.RELEASE_OBSERVED
            self._persist_transaction()
            self._emit(
                "plc.handshake.release_observed",
                self._snapshot_payload(snapshot) or {},
            )
            await self._complete_released_handshake()
            return

        acknowledged_at = existing.get("acknowledged_at_wall")
        expired_active_ack = (
            existing.get("phase") == "acknowledged"
            and snapshot.d102 == 1
            and (snapshot.d100 != 0 or snapshot.d101 != 0)
            and (
                not isinstance(acknowledged_at, (int, float))
                or isinstance(acknowledged_at, bool)
                or time.time() - acknowledged_at > self._handshake_timeout_s
            )
        )
        if expired_active_ack:
            phase = "timed_out"
            failure_code = "PLC_HANDSHAKE_TIMEOUT"
            message = "persisted acknowledgement expired before ladder release"
        elif self._words(snapshot) == (0, 0, 1):
            phase = "release_observed_recovery_required"
            failure_code = "PLC_RECONCILIATION_REQUIRED"
            message = "released acknowledgement requires explicit operator recovery"
        else:
            phase = "recovery_required"
            failure_code = "PLC_RECONCILIATION_REQUIRED"
            message = "persisted acknowledgement requires explicit operator recovery"

        self._transaction["phase"] = phase
        self._transaction["final_failure"] = {
            "failure_code": failure_code,
            "message": message,
            "at": time.time(),
        }
        self._persist_transaction()
        if snapshot.d102 == 1:
            try:
                readback = await self._write_with_evidence(
                    "D102", 0, before=snapshot, require_readback=True
                )
                if readback is None or readback.d102 != 0:
                    raise RuntimeError(
                        "D102 remained asserted during reconciliation"
                    )
            except Exception as exc:
                phase = "reconciliation_clear_failed"
                failure_code = "PLC_D102_CLEAR_FAILED"
                message = str(exc)
                self._transaction["phase"] = phase
                self._transaction["final_failure"] = {
                    "failure_code": failure_code,
                    "message": message,
                    "at": time.time(),
                }
        self._active_estop_sources.update(sources)
        self._safety_state = PLCSafetyState.ESTOP_LATCHED
        self._set_failure(failure_code, message)
        self._persist_transaction()
        self._emit(
            "plc.reconciliation.required",
            {
                "failure_code": failure_code,
                "phase": phase,
                "transaction_id": self._transaction["transaction_id"],
            },
        )

    async def _record_reconciliation_required(
        self, snapshot: PLCRegisterSnapshot
    ) -> None:
        command = "resume" if snapshot.d100 == 1 else "reset"
        identity = self._runtime_identity()
        sources = sorted(self._active_estop_sources or {PLC_PHYSICAL_SOURCE})
        self._transaction = {
            "schema": "plc_bridge_transaction.v1",
            "transaction_id": f"plc-{uuid4().hex}",
            "command": command,
            "phase": "recovery_required",
            "created_at": time.time(),
            "run_id": identity["run_id"],
            "session_id": identity["session_id"],
            "source_set": sources,
            "reconciled_snapshot": self._snapshot_payload(snapshot),
            "write_evidence": [],
            "final_outcome": "recovery_required",
            "final_failure": {
                "failure_code": "PLC_RECONCILIATION_REQUIRED",
                "message": "pending physical request requires fresh context",
                "at": time.time(),
            },
        }
        self._set_failure(
            "PLC_RECONCILIATION_REQUIRED",
            "pending physical request requires fresh context",
        )
        self._safety_state = PLCSafetyState.ESTOP_LATCHED
        self._persist_transaction()
        self._emit(
            "plc.request.rejected", {"command": command, "reason": "reconnect"}
        )

    async def _write_with_evidence(
        self,
        device: str,
        value: int,
        *,
        before: PLCRegisterSnapshot | None,
        require_readback: bool,
    ) -> PLCRegisterSnapshot | None:
        evidence: dict[str, object] = {
            "device": device,
            "value": value,
            "at": time.time(),
            "before": self._snapshot_payload(before),
            "after": None,
            "outcome": "pending",
        }
        self._append_write_evidence(evidence)
        try:
            await self._write_register(device, value)
            evidence["outcome"] = "written"
            readback: PLCRegisterSnapshot | None = None
            try:
                readback = await self._read_snapshot()
                evidence["after"] = self._snapshot_payload(readback)
                evidence["outcome"] = "verified_readback"
                self._cache_fresh_snapshot(
                    readback,
                    valid=(
                        classify_snapshot(readback).state
                        is not PLCSafetyState.PROTOCOL_FAULT
                    ),
                )
            except Exception as exc:
                evidence["readback_error"] = str(exc)
                if require_readback:
                    raise
            return readback
        except Exception as exc:
            evidence["outcome"] = "failed"
            evidence["error"] = str(exc)
            raise
        finally:
            self._persist_transaction()

    def _append_write_evidence(self, evidence: dict[str, object]) -> None:
        if self._transaction is None:
            return
        records = self._transaction.setdefault("write_evidence", [])
        if not isinstance(records, list):
            records = []
            self._transaction["write_evidence"] = records
        records.append(evidence)
        if len(records) > 20:
            del records[:-20]

    async def _set_virtual_words(self, d100: int, d101: int) -> None:
        transport = getattr(self._bridge, "_transport", None)
        if not isinstance(transport, VirtualPLCTransport):
            raise RuntimeError(
                "virtual PLC inputs require an explicitly configured virtual transport"
            )
        if not transport.connected or not self._connected:
            raise RuntimeError("virtual PLC transport is not connected")
        transport.words["D100"] = d100
        transport.words["D101"] = d101
        await self.accept_snapshot(words=(d100, d101, transport.words["D102"]))

    def _cache_fresh_snapshot(
        self, snapshot: PLCRegisterSnapshot, *, valid: bool
    ) -> None:
        changed = self._latest is None or self._words(self._latest) != self._words(
            snapshot
        )
        was_stale = self._stale
        self._connected = True
        self._stale = False
        self._latest = snapshot
        self._previous = snapshot
        self._sequence = max(self._sequence, snapshot.sequence)
        if valid:
            if self._failure_code in _SAMPLE_FAILURE_CODES:
                self._failure_code = None
            if was_stale or self._last_error == "PLC sample exceeded stale_after_s":
                self._last_error = None
            elif self._failure_code is None:
                self._last_error = None
        if was_stale:
            self._emit(
                "plc.bridge.stale",
                {"stale": False, "stale_after_s": self._stale_after_s},
            )
        if changed:
            self._emit(
                "plc.snapshot.changed", self._snapshot_payload(snapshot) or {}
            )
        self._last_fresh_processed_monotonic = time.monotonic()

    def _refresh_stale_state(self) -> None:
        if not self._connected or self._latest is None:
            return
        freshness_reference = (
            self._last_fresh_processed_monotonic
            if self._last_fresh_processed_monotonic is not None
            else self._latest.received_monotonic
        )
        sample_age_s = max(0.0, time.monotonic() - freshness_reference)
        if sample_age_s <= self._stale_after_s or self._stale:
            return
        self._stale = True
        if self._failure_code is None or self._failure_code in _SAMPLE_FAILURE_CODES:
            self._set_failure(
                "PLC_STATE_STALE", "PLC sample exceeded stale_after_s"
            )
        self._emit(
            "plc.bridge.stale",
            {
                "stale": True,
                "sample_age_s": sample_age_s,
                "stale_after_s": self._stale_after_s,
            },
        )

    def _finish_estop_sync_failure(self, message: str) -> None:
        self._set_failure("PLC_ESTOP_SYNC_FAILED", message)
        if self._transaction is not None:
            self._transaction["phase"] = "estop_sync_failed"
            self._transaction["final_outcome"] = "failed"
            self._transaction["final_failure"] = {
                "failure_code": "PLC_ESTOP_SYNC_FAILED",
                "message": message,
                "at": time.time(),
            }
            self._persist_transaction()
        self._emit(
            "plc.estop.sync_failed",
            {"failure_code": "PLC_ESTOP_SYNC_FAILED", "message": message},
        )

    def _record_estop_sync_evidence(
        self,
        source: str,
        details: dict[str, object],
        *,
        outcome: str,
        message: str | None = None,
    ) -> None:
        """Attach bounded E-STOP synchronization evidence without replacing recovery."""
        assert self._transaction is not None
        records = self._transaction.setdefault("estop_sync_evidence", [])
        if not isinstance(records, list):
            records = []
            self._transaction["estop_sync_evidence"] = records
        evidence: dict[str, object] = {
            "source": source,
            "details": details,
            "outcome": outcome,
            "at": time.time(),
        }
        if message is not None:
            evidence["failure_code"] = "PLC_ESTOP_SYNC_FAILED"
            evidence["message"] = message
            self._set_failure("PLC_ESTOP_SYNC_FAILED", message)
            self._emit(
                "plc.estop.sync_failed",
                {"failure_code": "PLC_ESTOP_SYNC_FAILED", "message": message},
            )
        records.append(evidence)
        if len(records) > 20:
            del records[:-20]
        self._persist_transaction()

    def _finish_transaction_failure(
        self, phase: str, failure_code: str, message: str
    ) -> None:
        if self._transaction is None:
            identity = self._runtime_identity()
            self._transaction = {
                "schema": "plc_bridge_transaction.v1",
                "transaction_id": f"plc-{uuid4().hex}",
                "run_id": identity["run_id"],
                "session_id": identity["session_id"],
                "source_set": sorted(self._active_estop_sources),
                "write_evidence": [],
            }
        self._transaction["phase"] = phase
        self._transaction["final_outcome"] = "failed"
        self._transaction["final_failure"] = {
            "failure_code": failure_code,
            "message": message,
            "at": time.time(),
        }
        self._persist_transaction()

    def _restore_persisted_latch(self) -> None:
        transaction = self._transaction
        if not isinstance(transaction, dict):
            return
        phase = str(transaction.get("phase") or "")
        if phase == "completed":
            return
        sources = {
            str(source)
            for source in transaction.get("source_set", [])
            if str(source).strip()
        }
        source = transaction.get("source")
        if not sources and isinstance(source, str) and source.strip():
            sources.add(source.strip())
        evidence = transaction.get("write_evidence")
        if not sources and phase in _ACTIVE_HANDSHAKE_PHASES | {
            "timed_out",
            "readback_failed",
            "controller_failed",
            "recovery_required",
            "release_observed_recovery_required",
        }:
            sources.add(PLC_PHYSICAL_SOURCE)
        self._active_estop_sources.update(sources)
        if sources:
            self._safety_state = PLCSafetyState.ESTOP_LATCHED
        if phase in {"terminal_estop", "estop_sync"}:
            self._pc_estop_origins.update(sources)
        if isinstance(evidence, list):
            for item in evidence[-20:]:
                if not isinstance(item, dict) or item.get("device") != "D101":
                    continue
                if item.get("value") == 1 and item.get("outcome") != "failed":
                    self._pc_estop_origins.update(sources)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _result_status(result: object, default_failure: str) -> tuple[bool, str]:
        if isinstance(result, dict):
            if result.get("ok") is True:
                return True, ""
            return False, str(result.get("failure_code") or default_failure)
        if result is True:
            return True, ""
        return False, default_failure

    def _runtime_identity(self) -> dict[str, str]:
        provider = getattr(self._callbacks, "plc_runtime_identity", None)
        if not callable(provider):
            return {"run_id": "", "session_id": ""}
        try:
            identity = provider()
        except Exception:
            return {"run_id": "", "session_id": ""}
        if not isinstance(identity, dict):
            return {"run_id": "", "session_id": ""}
        return {
            "run_id": str(identity.get("run_id") or "")[:160],
            "session_id": str(identity.get("session_id") or "")[:160],
        }

    def _set_failure(self, code: str, message: str) -> None:
        self._failure_code = code
        self._last_error = str(message)[:1000]

    def _set_observed_safety_state(self, state: PLCSafetyState) -> None:
        self._safety_state = (
            PLCSafetyState.ESTOP_LATCHED
            if state is PLCSafetyState.NORMAL and self._active_estop_sources
            else state
        )

    @staticmethod
    def _new_io_executor() -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="plc-bridge-io")

    def _ensure_io_executor(self) -> None:
        if self._io_executor is None:
            self._io_executor = self._new_io_executor()

    def _pending_command(self) -> str | None:
        if (
            self._transaction is not None
            and self._transaction.get("phase")
            not in {
                "completed",
                "terminal_estop",
                "estop_sync",
                "estop_sync_failed",
            }
            and isinstance(self._transaction.get("command"), str)
        ):
            return str(self._transaction["command"])
        if (
            self._latest is not None
            and self._latest.d101 == 1
            and self._latest.d100 in {1, 2}
        ):
            return "resume" if self._latest.d100 == 1 else "reset"
        return None

    def _persist_transaction(self) -> None:
        if self._transaction is None:
            return
        payload = self._sanitize(self._transaction)
        assert isinstance(payload, dict)
        self._transaction = payload
        self._atomic_write_json(self._state_path, payload)

    def _load_transaction(self) -> dict[str, object] | None:
        try:
            loaded = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        sanitized = self._sanitize(loaded)
        return sanitized if isinstance(sanitized, dict) else None

    def _load_events(self) -> list[dict[str, object]]:
        try:
            loaded = json.loads(self._event_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = loaded.get("events") if isinstance(loaded, dict) else None
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    def _emit(self, event: str, details: dict[str, object]) -> None:
        self._event_revision += 1
        identity = self._runtime_identity()
        record = {
            "event": str(event)[:160],
            "at": time.time(),
            "revision": self._event_revision,
            "run_id": identity["run_id"],
            "session_id": identity["session_id"],
            "details": self._sanitize(details),
        }
        self._events.append(record)
        try:
            self._atomic_write_json(
                self._event_path,
                {
                    "schema": "plc_bridge_events.v1",
                    "events": list(self._events),
                },
            )
        except OSError:
            # Runtime safety state must not unwind because audit storage is unavailable.
            pass

    @classmethod
    def _sanitize(
        cls,
        value: object,
        *,
        key: str = "",
        depth: int = 0,
    ) -> object:
        if key and any(
            fragment in key.lower() for fragment in _SECRET_KEY_FRAGMENTS
        ):
            return "[REDACTED]"
        if depth >= 8:
            return "[TRUNCATED]"
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, str):
            return value[:2000]
        if isinstance(value, dict):
            sanitized: dict[str, object] = {}
            for index, (raw_key, child) in enumerate(value.items()):
                if index >= 80:
                    sanitized["_truncated"] = True
                    break
                child_key = str(raw_key)[:160]
                sanitized[child_key] = cls._sanitize(
                    child, key=child_key, depth=depth + 1
                )
            return sanitized
        if isinstance(value, (list, tuple, set, frozenset, deque)):
            return [
                cls._sanitize(child, depth=depth + 1)
                for child in list(value)[:80]
            ]
        return str(value)[:2000]

    @staticmethod
    def _atomic_write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                json.dump(payload, temporary, sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def _transport_name(self) -> str:
        transport = getattr(self._bridge, "_transport", None)
        return (
            "virtual"
            if isinstance(transport, VirtualPLCTransport)
            else "pymcprotocol_type3e"
        )

    @staticmethod
    def _words(snapshot: PLCRegisterSnapshot) -> tuple[int, int, int]:
        return snapshot.d100, snapshot.d101, snapshot.d102

    def _verified_immediate_release_write_failure(
        self, snapshot: PLCRegisterSnapshot
    ) -> bool:
        transaction = self._transaction
        if not isinstance(transaction, dict):
            return False
        if self._words(snapshot) != (0, 0, 0):
            return False
        if transaction.get("command") != PLCCommand.RESUME.value:
            return False
        if transaction.get("phase") != "write_failed":
            return False
        failure = transaction.get("final_failure")
        if not isinstance(failure, dict) or failure.get("failure_code") != "PLC_WRITE_FAILED":
            return False
        evidence = transaction.get("write_evidence")
        if not isinstance(evidence, list):
            return False
        for item in reversed(evidence[-20:]):
            if not isinstance(item, dict):
                continue
            after = item.get("after")
            if (
                item.get("device") == "D102"
                and item.get("value") == 1
                and item.get("outcome") == "verified_readback"
                and isinstance(after, dict)
                and (after.get("d100"), after.get("d101"), after.get("d102"))
                == (0, 0, 0)
            ):
                return True
        return False

    @staticmethod
    def _snapshot_payload(
        snapshot: PLCRegisterSnapshot | None,
    ) -> dict[str, object] | None:
        if snapshot is None:
            return None
        return {
            "d100": snapshot.d100,
            "d101": snapshot.d101,
            "d102": snapshot.d102,
            "sequence": snapshot.sequence,
            "received_monotonic": snapshot.received_monotonic,
        }
