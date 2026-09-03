from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import threading
import time

import pytest

from device_bridges.plc_bridge import PLCBridge
from utils.plc_bridge_service import PLCBridgeService


def async_test(function):
    """Run async service scenarios without requiring pytest-asyncio in this checkout."""

    def runner(**kwargs):
        return asyncio.run(function(**kwargs))

    runner.__name__ = function.__name__
    runner.__doc__ = function.__doc__
    runner.__signature__ = inspect.signature(function)
    return runner


class ServiceTransport:
    """Synchronous PLC transport double with an explicitly controlled ladder."""

    def __init__(self) -> None:
        self.words = [0, 0, 0]
        self.connected = False
        self.connect_calls = 0
        self.close_calls = 0
        self.read_calls = 0
        self.writes: list[tuple[str, int]] = []
        self.release_on_ack = False

    def connect(self, host: str, port: int) -> None:
        assert host == "192.168.50.90"
        assert port == 4999
        self.connected = True
        self.connect_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    def read_words(self, headdevice: str, readsize: int) -> list[int]:
        assert headdevice == "D100"
        assert readsize == 3
        if not self.connected:
            raise ConnectionError("socket closed")
        self.read_calls += 1
        return list(self.words)

    def _write_word(self, device: str, value: int) -> None:
        if not self.connected:
            raise ConnectionError("socket closed")
        self.writes.append((device, value))
        self.words[{"D101": 1, "D102": 2}[device]] = value
        if device == "D102" and value == 1 and self.release_on_ack:
            self.words = [0, 0, 1]


class ImmediateReleaseTransport(ServiceTransport):
    """Model a ladder that clears D100-D102 before the first D102 readback."""

    def _write_word(self, device: str, value: int) -> None:
        super()._write_word(device, value)
        if (device, value) == ("D102", 1):
            self.words = [0, 0, 0]


class ControllerProbe:
    def __init__(self, *, recoverable: bool = True) -> None:
        self.recoverable = recoverable
        self.emergency_stop_calls: list[tuple[str, dict[str, object]]] = []
        self.readiness_calls: list[str] = []
        self.resume_calls: list[tuple[str, str]] = []
        self.reset_calls: list[tuple[str, str]] = []
        self.active_sources: set[str] = set()

    async def emergency_stop(self, source: str, details: dict[str, object]) -> dict[str, object]:
        self.emergency_stop_calls.append((source, details))
        self.active_sources.add(source)
        return {"ok": True}

    async def plc_recovery_readiness(self, command: str) -> dict[str, object]:
        self.readiness_calls.append(command)
        return {
            "ok": self.recoverable,
            "failure_code": None if self.recoverable else "PLC_RESUME_READINESS_FAILED",
            "physical_safety": {"ok": self.recoverable},
        }

    async def emergency_resume(self, source: str, transaction_id: str) -> dict[str, object]:
        self.resume_calls.append((source, transaction_id))
        self.active_sources.clear()
        return {"ok": True}

    async def emergency_reset(self, source: str, transaction_id: str) -> dict[str, object]:
        self.reset_calls.append((source, transaction_id))
        self.active_sources.clear()
        return {"ok": True}

    def plc_runtime_identity(self) -> dict[str, str]:
        return {"run_id": "run-probe", "session_id": "session-probe"}


class FailingStopProbe(ControllerProbe):
    async def emergency_stop(self, source: str, details: dict[str, object]) -> dict[str, object]:
        await super().emergency_stop(source, details)
        raise RuntimeError("Controller callback disconnected")


class RecoveryOutcomeProbe(ControllerProbe):
    def __init__(self, *, outcome: str) -> None:
        super().__init__()
        self.outcome = outcome

    async def emergency_resume(self, source: str, transaction_id: str) -> dict[str, object]:
        self.resume_calls.append((source, transaction_id))
        self.active_sources.clear()
        if self.outcome == "exception":
            raise RuntimeError("Controller resume exploded")
        return {
            "ok": False,
            "failure_code": "CONTROLLER_RECOVERY_REJECTED",
            "message": "Controller refused recovery",
        }


class MutatingClearReadbackTransport(ServiceTransport):
    def __init__(self, readback_words: list[int]) -> None:
        super().__init__()
        self.readback_words = list(readback_words)

    def _write_word(self, device: str, value: int) -> None:
        super()._write_word(device, value)
        if (device, value) == ("D102", 0):
            self.words = list(self.readback_words)


class BlockingWriteTransport(ServiceTransport):
    def __init__(self) -> None:
        super().__init__()
        self.assert_started = threading.Event()
        self.release_assert = threading.Event()

    def _write_word(self, device: str, value: int) -> None:
        if (device, value) == ("D102", 1):
            self.assert_started.set()
            assert self.release_assert.wait(timeout=1.0)
        super()._write_word(device, value)


class ConcurrentWriteProbeTransport(ServiceTransport):
    def __init__(self) -> None:
        super().__init__()
        self.assert_started = threading.Event()
        self.release_assert = threading.Event()
        self._write_guard = threading.Lock()
        self.active_writes = 0
        self.max_concurrent_writes = 0

    def _write_word(self, device: str, value: int) -> None:
        with self._write_guard:
            self.active_writes += 1
            self.max_concurrent_writes = max(self.max_concurrent_writes, self.active_writes)
        try:
            if (device, value) == ("D102", 1):
                self.assert_started.set()
                assert self.release_assert.wait(timeout=1.0)
            super()._write_word(device, value)
        finally:
            with self._write_guard:
                self.active_writes -= 1


class LifecycleOverlapTransport(ServiceTransport):
    def __init__(self) -> None:
        super().__init__()
        self.old_worker_started = threading.Event()
        self.release_old_worker = threading.Event()
        self.connect_started = threading.Event()
        self._active_guard = threading.Lock()
        self.active_operations = 0
        self.max_concurrent_operations = 0

    def _enter_operation(self) -> None:
        with self._active_guard:
            self.active_operations += 1
            self.max_concurrent_operations = max(
                self.max_concurrent_operations,
                self.active_operations,
            )

    def _exit_operation(self) -> None:
        with self._active_guard:
            self.active_operations -= 1

    def block_old_worker(self) -> None:
        self._enter_operation()
        try:
            self.old_worker_started.set()
            assert self.release_old_worker.wait(timeout=2.0)
        finally:
            self._exit_operation()

    def connect(self, host: str, port: int) -> None:
        self._enter_operation()
        try:
            self.connect_started.set()
            super().connect(host, port)
        finally:
            self._exit_operation()


async def _wait_for_executor_detach(service: PLCBridgeService) -> None:
    while service._io_executor is not None:
        await asyncio.sleep(0)


@pytest.fixture
def transport() -> ServiceTransport:
    return ServiceTransport()


@pytest.fixture
def controller_probe() -> ControllerProbe:
    return ControllerProbe()


@pytest.fixture
def service(
    tmp_path: Path, transport: ServiceTransport, controller_probe: ControllerProbe
) -> PLCBridgeService:
    return PLCBridgeService(
        PLCBridge(transport),
        controller_probe,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
        event_limit=5,
    )


@async_test
async def test_fast_stop_monitor_runs_while_main_event_loop_is_blocked(
    tmp_path: Path,
) -> None:
    transport = ServiceTransport()
    callbacks = ControllerProbe()
    fast_stop_seen = threading.Event()
    fast_stop_payloads: list[dict[str, object]] = []

    def fast_stop(payload: dict[str, object]) -> dict[str, object]:
        fast_stop_payloads.append(payload)
        fast_stop_seen.set()
        return {"ok": True, "status": "STOPPED"}

    service = PLCBridgeService(
        PLCBridge(transport),
        callbacks,
        poll_interval_s=0.2,
        fast_stop_poll_interval_s=0.01,
        fast_stop_callback=fast_stop,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
    )

    try:
        await service.start()
        deadline = time.monotonic() + 1.0
        while service.status()["connection_state"] != "online" and time.monotonic() < deadline:
            await asyncio.sleep(0.005)

        assert service.status()["connection_state"] == "online"
        transport.words = [0, 1, 0]
        time.sleep(0.08)

        assert fast_stop_seen.is_set()
        assert len(fast_stop_payloads) == 1
        assert fast_stop_payloads[0]["source"] == "plc_pb2"
        snapshot = fast_stop_payloads[0]["snapshot"]
        assert isinstance(snapshot, dict)
        assert snapshot["d101"] == 1
    finally:
        await service.shutdown()


@async_test
async def test_normal_disconnect_preserves_legacy_controls(
    service: PLCBridgeService, controller_probe: ControllerProbe
) -> None:
    """Catches treating an optional PLC network fault as an E-STOP."""
    await service.accept_snapshot(words=(0, 0, 0))
    await service.mark_disconnected("socket closed")

    assert service.status()["plc_layer_active"] is False
    assert service.status()["safety_state"] == "disconnected"
    assert controller_probe.emergency_stop_calls == []


@async_test
async def test_disconnect_does_not_request_rollout_fast_stop(tmp_path: Path) -> None:
    fast_stop_payloads: list[dict[str, object]] = []
    service = PLCBridgeService(
        PLCBridge(ServiceTransport()),
        ControllerProbe(),
        fast_stop_callback=lambda payload: fast_stop_payloads.append(dict(payload)),
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
    )

    await service.accept_snapshot(words=(0, 0, 0))
    await service.mark_disconnected("socket closed")

    assert service.status()["plc_layer_active"] is False
    assert service.status()["connection_state"] == "offline"
    assert fast_stop_payloads == []


@async_test
async def test_preflight_orphan_ack_is_read_only(tmp_path: Path) -> None:
    """Catches preflight reconciling and clearing an orphaned D102 acknowledgement."""
    transport = ServiceTransport()
    transport.words = [0, 0, 1]
    callbacks = ControllerProbe()
    state_path = tmp_path / "memory" / "plc_bridge_state.json"
    service = PLCBridgeService(
        PLCBridge(transport), callbacks, state_path=state_path
    )

    result = await service.preflight()

    assert result["register_snapshot"] is not None
    assert result["register_snapshot"]["d100"] == 0
    assert result["register_snapshot"]["d101"] == 0
    assert result["register_snapshot"]["d102"] == 1
    assert transport.writes == []
    assert transport.words == [0, 0, 1]
    assert callbacks.emergency_stop_calls == []
    assert service._transaction is None
    assert service._active_estop_sources == set()
    assert not state_path.exists()

    await service.shutdown()


@async_test
async def test_monitor_reconciles_orphan_ack_after_read_only_preflight(
    tmp_path: Path,
) -> None:
    """Catches a preflight-opened transport bypassing startup reconciliation."""
    transport = ServiceTransport()
    transport.words = [0, 0, 1]
    callbacks = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(transport),
        callbacks,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
        poll_interval_s=0.001,
    )

    try:
        await service.preflight()

        assert transport.writes == []
        assert service._transaction is None
        assert callbacks.emergency_stop_calls == []

        assert await service.start() is True
        deadline = time.monotonic() + 1.0
        while transport.writes != [("D102", 0)] and time.monotonic() < deadline:
            await asyncio.sleep(0.001)

        assert transport.writes == [("D102", 0)]
        assert callbacks.active_sources == {"plc_pb2"}
        assert service.status()["failure_code"] == "PLC_RECONCILIATION_REQUIRED"
        assert service.status()["transaction"]["phase"] == (
            "release_observed_recovery_required"
        )
    finally:
        await service.shutdown()


@async_test
async def test_disconnect_after_d101_keeps_local_latch(
    service: PLCBridgeService, controller_probe: ControllerProbe
) -> None:
    """Catches dropping a physical E-STOP because its PLC connection disappears."""
    await service.accept_snapshot(words=(0, 1, 0))
    await service.mark_disconnected("socket closed")

    assert service.status()["safety_state"] == "estop_latched"
    assert service.status()["active_estop_sources"] == ["plc_pb2"]
    assert len(controller_probe.emergency_stop_calls) == 1


@async_test
async def test_callback_failure_keeps_observed_plc_latch_locally(tmp_path: Path) -> None:
    """Catches losing D101 because Controller E-STOP delivery fails."""
    transport = ServiceTransport()
    callbacks = FailingStopProbe()
    service = PLCBridgeService(
        PLCBridge(transport), callbacks, state_path=tmp_path / "memory" / "plc_bridge_state.json"
    )

    with pytest.raises(RuntimeError, match="Controller callback disconnected"):
        await service.accept_snapshot(words=(0, 1, 0))
    await service.mark_disconnected("callback failure")

    assert service.status()["active_estop_sources"] == ["plc_pb2"]
    assert service.status()["safety_state"] == "estop_latched"


@async_test
async def test_reconnect_acknowledges_pending_d100_after_fresh_idle_readiness(
    service: PLCBridgeService, transport: ServiceTransport, controller_probe: ControllerProbe
) -> None:
    """Catches an idle physical Resume remaining stranded after reconnect."""
    transport.connected = True
    transport.words = [1, 1, 0]

    await service.reconcile()

    assert controller_probe.emergency_stop_calls
    assert controller_probe.readiness_calls == ["resume"]
    assert transport.writes == [("D102", 1)]
    assert service.status()["failure_code"] is None
    assert service.status()["transaction"]["phase"] == "acknowledged"
    assert service.status()["pending_command"] == "resume"


@async_test
async def test_reconnect_release_requires_recovery_without_invoking_callback(
    tmp_path: Path,
) -> None:
    """Catches startup reconciliation replaying an acknowledged Resume."""
    state_path = tmp_path / "memory" / "plc_bridge_state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "transaction_id": "plc-restart",
                "command": "resume",
                "phase": "acknowledged",
                "acknowledged_at_wall": time.time(),
            }
        ),
        encoding="utf-8",
    )
    transport = ServiceTransport()
    transport.connected = True
    transport.words = [0, 0, 1]
    callbacks = ControllerProbe()
    service = PLCBridgeService(PLCBridge(transport), callbacks, state_path=state_path)

    await service.reconcile()

    assert transport.writes == [("D102", 0)]
    assert callbacks.readiness_calls == []
    assert callbacks.resume_calls == []
    assert callbacks.active_sources == {"plc_pb2"}
    assert service.status()["safety_state"] == "estop_latched"
    assert service.status()["failure_code"] == "PLC_RECONCILIATION_REQUIRED"
    assert service.status()["transaction"]["phase"] == "release_observed_recovery_required"


@async_test
async def test_reconnect_recovers_verified_immediate_release_from_legacy_write_failure(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "memory" / "plc_bridge_state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "transaction_id": "plc-fast-release",
                "command": "resume",
                "phase": "write_failed",
                "source_set": ["plc_pb2"],
                "write_evidence": [
                    {
                        "device": "D102",
                        "value": 1,
                        "outcome": "verified_readback",
                        "after": {"d100": 0, "d101": 0, "d102": 0},
                    }
                ],
                "final_failure": {
                    "failure_code": "PLC_WRITE_FAILED",
                    "message": "D102 assertion was not observed in a fresh readback",
                },
            }
        ),
        encoding="utf-8",
    )
    transport = ServiceTransport()
    transport.connected = True
    transport.words = [0, 0, 0]
    callbacks = ControllerProbe()
    service = PLCBridgeService(PLCBridge(transport), callbacks, state_path=state_path)

    await service.reconcile()

    status = service.status()
    assert transport.writes == []
    assert len(callbacks.resume_calls) == 1
    assert status["safety_state"] == "normal"
    assert status["failure_code"] is None
    assert status["transaction"]["phase"] == "completed"


@async_test
async def test_reconnect_orphan_release_never_invokes_recovery_callback(tmp_path: Path) -> None:
    """Catches orphan D102 release state being accepted as a recoverable transaction."""
    transport = ServiceTransport()
    transport.connected = True
    transport.words = [0, 0, 1]
    callbacks = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(transport), callbacks, state_path=tmp_path / "memory" / "plc-state.json"
    )

    await service.reconcile()

    assert transport.writes == [("D102", 0)]
    assert callbacks.readiness_calls == []
    assert callbacks.resume_calls == []
    assert callbacks.reset_calls == []
    assert service.status()["safety_state"] == "estop_latched"
    assert service.status()["failure_code"] == "PLC_RECONCILIATION_REQUIRED"
    assert service.status()["transaction"]["phase"] == "release_observed_recovery_required"


@async_test
async def test_reconciliation_clears_d102_when_controller_relatch_delivery_fails(
    tmp_path: Path,
) -> None:
    """Catches a Controller callback error stranding a persisted D102 acknowledgement."""
    state_path = tmp_path / "memory" / "plc-state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "transaction_id": "plc-relatch-failure",
                "command": "reset",
                "phase": "acknowledged",
                "acknowledged_at_wall": time.time(),
            }
        ),
        encoding="utf-8",
    )
    transport = ServiceTransport()
    transport.connected = True
    transport.words = [0, 0, 1]
    service = PLCBridgeService(
        PLCBridge(transport), FailingStopProbe(), state_path=state_path
    )

    await service.reconcile()

    status = service.status()
    assert transport.writes == [("D102", 0)]
    assert status["failure_code"] == "PLC_RECONCILIATION_REQUIRED"
    assert status["transaction"]["phase"] == "release_observed_recovery_required"
    assert status["transaction"]["relatch_errors"]


@async_test
async def test_d102_handshake_timeout_clears_ack_and_keeps_estop(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches a hung ladder acknowledgement leaving D102 asserted or resuming motion."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    await service.accept_snapshot(words=(1, 1, 0))

    await asyncio.sleep(0.01)
    await service.accept_snapshot(words=(1, 1, 1), handshake_timeout_s=0.001)

    assert transport.writes == [("D102", 1), ("D102", 0)]
    assert service.status()["failure_code"] == "PLC_HANDSHAKE_TIMEOUT"
    assert service.status()["safety_state"] == "estop_latched"
    assert controller_probe.resume_calls == []


@async_test
async def test_release_completes_handshake_before_resume_callback(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches invoking Controller Resume before the ladder releases D100 and D101."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True

    await service.accept_snapshot(words=(1, 1, 0))
    await service.accept_snapshot(words=(0, 0, 1))

    assert transport.writes == [("D102", 1), ("D102", 0)]
    assert len(controller_probe.resume_calls) == 1
    assert service.status()["safety_state"] == "normal"


@async_test
async def test_immediate_ladder_release_completes_resume_without_false_write_failure(
    tmp_path: Path,
) -> None:
    transport = ImmediateReleaseTransport()
    transport.connected = True
    callbacks = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(transport),
        callbacks,
        state_path=tmp_path / "memory" / "plc-state.json",
    )

    await service.accept_snapshot(words=(0, 1, 0))
    await service.accept_snapshot(words=(1, 1, 0))

    status = service.status()
    assert transport.writes == [("D102", 1)]
    assert len(callbacks.resume_calls) == 1
    assert status["safety_state"] == "normal"
    assert status["failure_code"] is None
    assert status["transaction"]["phase"] == "completed"


@async_test
async def test_reestop_during_acknowledged_transaction_preserves_transaction_and_completes(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches re-E-STOP replacing a handshake that can still release safely."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True
    await service.accept_snapshot(words=(1, 1, 0))
    acknowledged = service.status()["transaction"]

    await service.sync_estop("gui_estop", {"reason": "operator_reestop"})

    preserved = service.status()["transaction"]
    assert preserved["transaction_id"] == acknowledged["transaction_id"]
    assert preserved["phase"] == "acknowledged"
    assert set(preserved["source_set"]) == {"gui_estop", "plc_pb2"}
    assert preserved["estop_sync_evidence"][-1]["source"] == "gui_estop"
    assert preserved["estop_sync_evidence"][-1]["details"] == {
        "reason": "operator_reestop"
    }

    transport.words = [0, 0, 1]
    await service.accept_snapshot(words=(0, 0, 1))

    completed = service.status()
    assert transport.writes == [("D102", 1), ("D101", 1), ("D102", 0)]
    assert controller_probe.resume_calls == [
        ("plc", acknowledged["transaction_id"])
    ]
    assert completed["transaction"]["phase"] == "completed"
    assert completed["register_snapshot"]["d102"] == 0
    assert completed["active_estop_sources"] == []


@async_test
async def test_reestop_during_acknowledged_transaction_times_out_without_stranding_d102(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches re-E-STOP disabling timeout cleanup and leaving D102 asserted."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    await service.accept_snapshot(words=(1, 1, 0))
    transaction_id = service.status()["transaction"]["transaction_id"]

    await service.sync_estop("gui_estop", {"reason": "operator_reestop"})
    await asyncio.sleep(0.01)
    await service.accept_snapshot(words=(1, 1, 1), handshake_timeout_s=0.001)

    timed_out = service.status()
    assert transport.writes == [("D102", 1), ("D101", 1), ("D102", 0)]
    assert transport.words[2] == 0
    assert timed_out["transaction"]["transaction_id"] == transaction_id
    assert timed_out["transaction"]["phase"] == "timed_out"
    assert timed_out["failure_code"] == "PLC_HANDSHAKE_TIMEOUT"
    assert set(timed_out["active_estop_sources"]) == {"gui_estop", "plc_pb2"}
    assert controller_probe.active_sources == {"gui_estop", "plc_pb2"}
    assert controller_probe.resume_calls == []


@async_test
async def test_concurrent_release_reestop_serializes_state_and_keeps_new_latch(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches a release clearing re-E-STOP while its D101 write is in flight."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True
    await service.accept_snapshot(words=(1, 1, 0))

    d101_write_waiting = asyncio.Event()
    d102_clear_started = asyncio.Event()
    allow_d101_write = asyncio.Event()
    recovery_completed = asyncio.Event()
    write_with_evidence = service._write_with_evidence
    emergency_resume = controller_probe.emergency_resume

    async def write_with_barrier(
        device: str,
        value: int,
        *,
        before,
        require_readback: bool,
    ):
        if (device, value) == ("D101", 1):
            d101_write_waiting.set()
            await allow_d101_write.wait()
        elif (device, value) == ("D102", 0):
            d102_clear_started.set()
        return await write_with_evidence(
            device,
            value,
            before=before,
            require_readback=require_readback,
        )

    async def resume_with_barrier(
        source: str, transaction_id: str
    ) -> dict[str, object]:
        result = await emergency_resume(source, transaction_id)
        recovery_completed.set()
        return result

    service._write_with_evidence = write_with_barrier
    controller_probe.emergency_resume = resume_with_barrier
    sync_task = asyncio.create_task(
        service.sync_estop("gui_estop", {"reason": "concurrent_reestop"})
    )
    await asyncio.wait_for(d101_write_waiting.wait(), timeout=1.0)
    release_task = asyncio.create_task(service.accept_snapshot(words=(0, 0, 1)))
    try:
        await asyncio.sleep(0)
        if d102_clear_started.is_set():
            await asyncio.wait_for(recovery_completed.wait(), timeout=1.0)
    finally:
        allow_d101_write.set()
    await asyncio.gather(sync_task, release_task)

    status = service.status()
    assert controller_probe.resume_calls == []
    assert "gui_estop" in controller_probe.active_sources
    assert "gui_estop" in status["active_estop_sources"]
    assert status["safety_state"] == "estop_latched"
    assert transport.words[2] == 0
    assert all(
        write in {("D101", 1), ("D102", 0), ("D102", 1)}
        for write in transport.writes
    )


@async_test
async def test_release_requires_full_zero_readback_and_relatches_both_sides(
    tmp_path: Path,
) -> None:
    """Catches D101 reassertion or a new D100 command after D102 clear."""
    for index, readback_words in enumerate(([0, 1, 0], [1, 0, 0])):
        transport = MutatingClearReadbackTransport(list(readback_words))
        transport.connected = True
        callbacks = ControllerProbe()
        service = PLCBridgeService(
            PLCBridge(transport),
            callbacks,
            state_path=tmp_path / "memory" / f"plc-state-{index}.json",
        )
        await service.accept_snapshot(words=(0, 1, 0))
        transport.release_on_ack = True
        await service.accept_snapshot(words=(1, 1, 0))

        await service.accept_snapshot(words=(0, 0, 1))

        status = service.status()
        assert callbacks.resume_calls == []
        assert callbacks.active_sources == {"plc_pb2"}
        assert status["active_estop_sources"] == ["plc_pb2"]
        assert status["safety_state"] == "estop_latched"
        assert status["failure_code"] == "PLC_HANDSHAKE_CLEAR_NOT_OBSERVED"
        assert status["transaction"]["phase"] == "readback_failed"
        assert status["transaction"]["final_outcome"] == "failed"
        assert transport.writes[-1] == ("D101", 1)


@async_test
async def test_recovery_callback_failure_relatches_controller_and_service(
    tmp_path: Path,
) -> None:
    """Catches callback rejection/exception leaving either safety latch cleared."""
    for outcome in ("ok_false", "exception"):
        transport = ServiceTransport()
        transport.connected = True
        callbacks = RecoveryOutcomeProbe(outcome=outcome)
        service = PLCBridgeService(
            PLCBridge(transport),
            callbacks,
            state_path=tmp_path / "memory" / f"plc-state-{outcome}.json",
        )
        await service.accept_snapshot(words=(0, 1, 0))
        transport.release_on_ack = True
        await service.accept_snapshot(words=(1, 1, 0))

        await service.accept_snapshot(words=(0, 0, 1))

        status = service.status()
        assert callbacks.active_sources == {"plc_pb2"}
        assert status["active_estop_sources"] == ["plc_pb2"]
        assert status["safety_state"] == "estop_latched"
        assert status["failure_code"] == "PLC_RUNTIME_RESUME_FAILED"
        assert status["transaction"]["phase"] == "controller_failed"
        assert status["transaction"]["final_outcome"] == "failed"
        assert transport.writes[-1] == ("D101", 1)
        assert all(
            event["event"] != "plc.handshake.completed" for event in service.events()
        )


@async_test
async def test_d101_reassertion_adds_physical_source_to_pc_origin_failure(
    tmp_path: Path,
) -> None:
    """Catches a new physical D101 assertion retaining only its earlier PC origin."""
    transport = MutatingClearReadbackTransport([0, 1, 0])
    transport.connected = True
    callbacks = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(transport), callbacks, state_path=tmp_path / "memory" / "plc-state.json"
    )
    await service.accept_snapshot(words=(0, 0, 0))
    await service.set_terminal_estop({"reason": "uncertain effect"})
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True
    await service.accept_snapshot(words=(1, 1, 0))

    await service.accept_snapshot(words=(0, 0, 1))

    expected_sources = {"plc_pb2", "runtime_terminal_error"}
    assert set(service.status()["active_estop_sources"]) == expected_sources
    assert callbacks.active_sources == expected_sources
    assert service.status()["failure_code"] == "PLC_HANDSHAKE_CLEAR_NOT_OBSERVED"


@async_test
async def test_shutdown_waits_for_cancelled_d102_assert_before_clearing(
    tmp_path: Path, controller_probe: ControllerProbe
) -> None:
    """Catches D102=0 racing a cancelled but still-running D102=1 worker-thread write."""
    transport = BlockingWriteTransport()
    transport.connected = True
    service = PLCBridgeService(
        PLCBridge(transport), controller_probe, state_path=tmp_path / "memory" / "plc_bridge_state.json"
    )
    await service.accept_snapshot(words=(0, 0, 0))

    assert_task = asyncio.create_task(service._write_register("D102", 1))
    await asyncio.to_thread(transport.assert_started.wait, 1.0)
    assert_task.cancel()
    shutdown_task = asyncio.create_task(service.shutdown())
    try:
        await asyncio.sleep(0.01)
        assert not shutdown_task.done()
    finally:
        transport.release_assert.set()
    with pytest.raises(asyncio.CancelledError):
        await assert_task
    await shutdown_task

    assert transport.writes == [("D102", 1), ("D102", 0)]


@async_test
async def test_repeated_cancellation_never_overlaps_physical_writes(
    tmp_path: Path, controller_probe: ControllerProbe
) -> None:
    """Catches a second cancellation releasing serialization while D102=1 still runs."""
    transport = ConcurrentWriteProbeTransport()
    transport.connected = True
    service = PLCBridgeService(
        PLCBridge(transport), controller_probe, state_path=tmp_path / "memory" / "plc_bridge_state.json"
    )
    await service.accept_snapshot(words=(0, 0, 0))

    assert_task = asyncio.create_task(service._write_register("D102", 1))
    await asyncio.to_thread(transport.assert_started.wait, 1.0)
    assert_task.cancel()
    await asyncio.sleep(0)
    assert_task.cancel()
    shutdown_task = asyncio.create_task(service.shutdown())
    try:
        await asyncio.sleep(0.01)
        assert transport.max_concurrent_writes == 1
        assert not shutdown_task.done()
    finally:
        transport.release_assert.set()
    with pytest.raises(asyncio.CancelledError):
        await assert_task
    await shutdown_task

    assert transport.max_concurrent_writes == 1
    assert transport.writes == [("D102", 1), ("D102", 0)]


@async_test
async def test_preflight_waits_for_old_executor_shutdown_before_replacement(
    tmp_path: Path,
    controller_probe: ControllerProbe,
) -> None:
    """Catches concurrent disconnect/preflight running I/O on two executors."""
    transport = LifecycleOverlapTransport()
    service = PLCBridgeService(
        PLCBridge(transport),
        controller_probe,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
    )
    old_worker_task = asyncio.create_task(service._run_io(transport.block_old_worker))
    assert await asyncio.to_thread(transport.old_worker_started.wait, 1.0)
    old_worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await old_worker_task

    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.wait_for(_wait_for_executor_detach(service), timeout=1.0)
    preflight_task = asyncio.create_task(service.preflight())
    try:
        await asyncio.sleep(0)
        assert service._io_executor is None
        assert not transport.connect_started.is_set()
    finally:
        transport.release_old_worker.set()
        await shutdown_task
    result = await preflight_task

    assert result["ok"] is True
    assert transport.max_concurrent_operations == 1
    assert service.status()["poll_worker_starts"] == 0
    await service.shutdown()


@async_test
async def test_cancelled_shutdown_keeps_preflight_behind_old_executor(
    tmp_path: Path,
    controller_probe: ControllerProbe,
) -> None:
    """Catches cancellation releasing lifecycle serialization before worker termination."""
    transport = LifecycleOverlapTransport()
    service = PLCBridgeService(
        PLCBridge(transport),
        controller_probe,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
    )
    old_worker_task = asyncio.create_task(service._run_io(transport.block_old_worker))
    assert await asyncio.to_thread(transport.old_worker_started.wait, 1.0)
    old_worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await old_worker_task

    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.wait_for(_wait_for_executor_detach(service), timeout=1.0)
    shutdown_task.cancel()
    preflight_task = asyncio.create_task(service.preflight())
    try:
        await asyncio.sleep(0)
        assert not shutdown_task.done()
        assert service._io_executor is None
        assert not transport.connect_started.is_set()
    finally:
        transport.release_old_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await shutdown_task
    result = await preflight_task

    assert result["ok"] is True
    assert transport.max_concurrent_operations == 1
    await service.shutdown()


@async_test
async def test_rebooted_acknowledged_transaction_uses_wall_clock_timeout(tmp_path: Path) -> None:
    """Catches rebooted transactions retaining an unusable prior-process monotonic timestamp."""
    state_path = tmp_path / "memory" / "plc_bridge_state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "transaction_id": "plc-reboot",
                "command": "resume",
                "phase": "acknowledged",
                "acknowledged_at_wall": time.time() - 10,
            }
        ),
        encoding="utf-8",
    )
    transport = ServiceTransport()
    transport.connected = True
    transport.words = [1, 1, 1]
    service = PLCBridgeService(
        PLCBridge(transport),
        ControllerProbe(),
        state_path=state_path,
        handshake_timeout_s=1.0,
    )

    await service.reconcile()

    assert transport.writes == [("D102", 0)]
    assert service.status()["failure_code"] == "PLC_HANDSHAKE_TIMEOUT"


@async_test
async def test_start_has_one_poll_owner_and_bounded_change_only_events(
    tmp_path: Path, transport: ServiceTransport, controller_probe: ControllerProbe
) -> None:
    """Catches duplicate monitor tasks and unbounded no-change polling history."""
    service = PLCBridgeService(
        PLCBridge(transport),
        controller_probe,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
        poll_interval_s=0.001,
        event_limit=3,
    )

    assert await service.start() is True
    assert await service.start() is False
    deadline = time.monotonic() + 1.0
    while transport.read_calls < 100 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    await service.shutdown()

    assert transport.read_calls >= 100
    assert service.status()["poll_worker_starts"] == 1
    assert len(service.events()) <= 3
    assert [event["event"] for event in service.events()].count("plc.snapshot.changed") == 1


@async_test
async def test_protocol_fault_events_emit_on_fault_change_or_recovery(
    tmp_path: Path,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches unchanged invalid polls flooding the bounded event history."""
    service = PLCBridgeService(
        PLCBridge(transport),
        controller_probe,
        state_path=tmp_path / "memory" / "plc_bridge_state.json",
        event_limit=20,
    )

    await service.accept_snapshot(words=(3, 0, 0))
    await service.accept_snapshot(words=(3, 0, 0))
    await service.accept_snapshot(words=(0, 0, 0))
    await service.accept_snapshot(words=(3, 0, 0))
    await service.accept_snapshot(words=(1, 0, 0))

    fault_codes = [
        event["details"]["failure_code"]
        for event in service.events()
        if event["event"] == "plc.protocol_fault"
    ]
    assert fault_codes == [
        "PLC_INVALID_REGISTER_VALUE",
        "PLC_INVALID_REGISTER_VALUE",
        "PLC_COMMAND_WITHOUT_ESTOP",
    ]


@async_test
async def test_terminal_estop_persists_transaction_by_atomic_replace(
    service: PLCBridgeService, transport: ServiceTransport, tmp_path: Path
) -> None:
    """Catches losing terminal E-STOP context to an interrupted persistence write."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 0, 0))

    await service.set_terminal_estop({"reason": "device_unknown"})

    state_path = tmp_path / "memory" / "plc_bridge_state.json"
    record = json.loads(state_path.read_text(encoding="utf-8"))
    assert transport.writes == [("D101", 1)]
    assert record["phase"] == "terminal_estop"
    assert not list(state_path.parent.glob(".plc_bridge_state.json.*.tmp"))


@async_test
async def test_pc_origin_d101_is_not_reclassified_as_physical_pb2(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches a confirmed PC D101 synchronization acquiring false PB2 priority."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 0, 0))
    await service.set_terminal_estop({"reason": "device_unknown"})

    await service.accept_snapshot(words=(0, 1, 0))

    assert service.status()["active_estop_sources"] == ["runtime_terminal_error"]
    assert controller_probe.active_sources == {"runtime_terminal_error"}
    assert [call[0] for call in controller_probe.emergency_stop_calls] == [
        "runtime_terminal_error"
    ]


@async_test
async def test_paired_terminal_recovery_converges_controller_and_service_sources(
    service: PLCBridgeService,
    transport: ServiceTransport,
    controller_probe: ControllerProbe,
) -> None:
    """Catches physical recovery clearing Controller but not the paired service source."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 0, 0))
    await service.set_terminal_estop({"reason": "device_unknown"})
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True

    await service.accept_snapshot(words=(1, 1, 0))
    await service.accept_snapshot(words=(0, 0, 1))

    assert service.status()["active_estop_sources"] == []
    assert controller_probe.active_sources == set()
    assert service.status()["safety_state"] == "normal"


@async_test
async def test_normal_poll_after_paired_recovery_stays_converged(
    service: PLCBridgeService,
    transport: ServiceTransport,
) -> None:
    """Catches a later normal sample resurrecting a cleared paired source."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 0, 0))
    await service.set_terminal_estop({"reason": "device_unknown"})
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True
    await service.accept_snapshot(words=(1, 1, 0))
    await service.accept_snapshot(words=(0, 0, 1))

    await service.accept_snapshot(words=(0, 0, 0))

    assert service.status()["active_estop_sources"] == []
    assert service.status()["safety_state"] == "normal"


@async_test
async def test_release_caches_verified_d102_zero_readback(
    service: PLCBridgeService,
    transport: ServiceTransport,
) -> None:
    """Catches publishing NORMAL while status still caches the released D102=1 snapshot."""
    transport.connected = True
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True

    await service.accept_snapshot(words=(1, 1, 0))
    await service.accept_snapshot(words=(0, 0, 1))

    assert service.status()["register_snapshot"]["d102"] == 0


@async_test
async def test_stale_state_is_change_driven_and_valid_sample_clears_sample_failures(
    tmp_path: Path,
) -> None:
    """Catches configured stale_after_s being ignored or remaining sticky after recovery."""
    service = PLCBridgeService(
        PLCBridge(ServiceTransport()),
        ControllerProbe(),
        state_path=tmp_path / "memory" / "plc-state.json",
        stale_after_s=0.01,
        event_limit=20,
    )
    await service.accept_snapshot(words=(0, 0, 0))
    await asyncio.sleep(0.02)

    first_stale = service.status()
    second_stale = service.status()

    assert first_stale["connection_state"] == "stale"
    assert first_stale["failure_code"] == "PLC_STATE_STALE"
    assert second_stale["failure_code"] == "PLC_STATE_STALE"
    assert [event["event"] for event in service.events()].count("plc.bridge.stale") == 1

    await service.accept_snapshot(words=(3, 0, 0))
    assert service.status()["failure_code"] == "PLC_INVALID_REGISTER_VALUE"
    await service.accept_snapshot(words=(0, 0, 0))

    recovered = service.status()
    assert recovered["connection_state"] == "online"
    assert recovered["failure_code"] is None
    assert recovered["last_error"] is None


@async_test
async def test_reconnect_closes_previous_transport_before_opening_new_connection(
    tmp_path: Path,
) -> None:
    """Catches reconnect overwriting a live client without closing its socket."""
    transport = ServiceTransport()
    service = PLCBridgeService(
        PLCBridge(transport), ControllerProbe(), state_path=tmp_path / "memory" / "plc-state.json"
    )
    await service._connect()
    await service.mark_disconnected("read failed")

    await service._connect()

    assert transport.connect_calls == 2
    assert transport.close_calls == 1


@async_test
async def test_transaction_and_event_journal_persist_bounded_redacted_evidence(
    tmp_path: Path,
) -> None:
    """Catches missing recovery evidence, unbounded journals, or persisted secrets."""
    state_path = tmp_path / "memory" / "plc-state.json"
    event_path = tmp_path / "memory" / "plc-events.json"
    transport = ServiceTransport()
    transport.connected = True
    callbacks = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(transport),
        callbacks,
        state_path=state_path,
        event_path=event_path,
        event_limit=3,
    )
    await service.accept_snapshot(words=(0, 0, 0))
    await service.set_terminal_estop(
        {"reason": "uncertain effect", "api_token": "must-not-persist"}
    )
    await service.accept_snapshot(words=(0, 1, 0))
    transport.release_on_ack = True

    await service.accept_snapshot(words=(1, 1, 0))

    transaction = json.loads(state_path.read_text(encoding="utf-8"))
    journal = json.loads(event_path.read_text(encoding="utf-8"))
    serialized = state_path.read_text(encoding="utf-8") + event_path.read_text(
        encoding="utf-8"
    )
    assert transaction["run_id"] == "run-probe"
    assert transaction["session_id"] == "session-probe"
    assert transaction["source_set"] == ["runtime_terminal_error"]
    assert transaction["validation_result"]["ok"] is True
    assert transaction["snapshot_before_ack"]["d100"] == 1
    assert transaction["write_evidence"][0]["device"] == "D102"
    assert transaction["write_evidence"][0]["before"]["d102"] == 0
    assert transaction["write_evidence"][0]["after"]["d102"] == 1
    assert transaction["phase"] == "acknowledged"
    assert len(journal["events"]) <= 3
    assert all(event["run_id"] == "run-probe" for event in journal["events"])
    assert "must-not-persist" not in serialized
    assert "[REDACTED]" in serialized
