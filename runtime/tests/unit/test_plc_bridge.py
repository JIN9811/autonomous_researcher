from __future__ import annotations

import pytest

from device_bridges.plc_bridge import (
    PLCBridge,
    PLCConnectionError,
    PLCWriteRejected,
    VirtualPLCTransport,
)


class FakeTransport:
    def __init__(self) -> None:
        self.words = [0, 0, 0]
        self.read_calls: list[tuple[str, int]] = []
        self.write_calls: list[tuple[str, int]] = []

    def read_words(self, headdevice: str, readsize: int) -> list[int]:
        self.read_calls.append((headdevice, readsize))
        return self.words[:readsize]

    def _write_word(self, device: str, value: int) -> None:
        self.write_calls.append((device, value))


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()


def test_bridge_reads_three_words_atomically(fake_transport: FakeTransport) -> None:
    fake_transport.words = [2, 1, 0]

    snapshot = PLCBridge(fake_transport).read_snapshot()

    assert (snapshot.d100, snapshot.d101, snapshot.d102) == (2, 1, 0)
    assert fake_transport.read_calls == [("D100", 3)]


@pytest.mark.parametrize(
    ("device", "value"),
    [("D100", 1), ("D101", 0), ("D102", 2), ("D200", 1)],
)
def test_bridge_rejects_unapproved_writes(
    fake_transport: FakeTransport, device: str, value: int
) -> None:
    with pytest.raises(PLCWriteRejected):
        PLCBridge(fake_transport).write_register(device, value)

    assert fake_transport.write_calls == []


@pytest.mark.parametrize("device,value", [("D101", 1), ("D102", 0), ("D102", 1)])
def test_bridge_forwards_allowlisted_write(
    fake_transport: FakeTransport, device: str, value: int
) -> None:
    PLCBridge(fake_transport).write_register(device, value)

    assert fake_transport.write_calls == [(device, value)]


def test_virtual_transport_releases_ladder_latch_after_recovery_ack() -> None:
    transport = VirtualPLCTransport(d100=1, d101=1)
    transport.connect("virtual", 0)

    PLCBridge(transport).write_register("D102", 1)

    assert transport.read_words("D100", 3) == [0, 0, 1]


@pytest.mark.parametrize("d100,d101", [(0, 1), (1, 0)])
def test_virtual_transport_keeps_latch_when_recovery_preconditions_are_not_met(
    d100: int, d101: int
) -> None:
    transport = VirtualPLCTransport(d100=d100, d101=d101)
    transport.connect("virtual", 0)

    PLCBridge(transport).write_register("D102", 1)

    assert transport.read_words("D100", 3) == [d100, d101, 1]


def test_virtual_transport_releases_reset_request_after_recovery_ack() -> None:
    transport = VirtualPLCTransport(d100=2, d101=1)
    transport.connect("virtual", 0)

    PLCBridge(transport).write_register("D102", 1)

    assert transport.read_words("D100", 3) == [0, 0, 1]


def test_transport_write_operation_is_private() -> None:
    assert not hasattr(VirtualPLCTransport(), "write_word")


def test_virtual_transport_rejects_writes_outside_safety_allowlist() -> None:
    with pytest.raises(PLCWriteRejected):
        VirtualPLCTransport()._write_word("D100", 1)


def test_bridge_execute_rejects_generic_write_command(fake_transport: FakeTransport) -> None:
    with pytest.raises(ValueError, match="unsupported PLC bridge command"):
        PLCBridge(fake_transport).execute("write_register", {"device": "D102", "value": 1})


@pytest.mark.parametrize(
    ("device", "value"),
    [("D101", True), ("D102", False), ("D102", 0.0), ("D102", 1.0)],
)
def test_bridge_write_allowlist_requires_exact_non_bool_integers(
    fake_transport: FakeTransport,
    device: str,
    value: object,
) -> None:
    """Catches bools/floats comparing equal to an allowlisted integer."""
    with pytest.raises(PLCWriteRejected):
        PLCBridge(fake_transport).write_register(device, value)  # type: ignore[arg-type]

    assert fake_transport.write_calls == []


def test_virtual_transport_rejects_io_before_connect_and_after_close() -> None:
    """Catches the virtual transport accepting I/O with no live connection."""
    transport = VirtualPLCTransport()
    bridge = PLCBridge(transport)

    with pytest.raises(PLCConnectionError):
        bridge.read_snapshot()
    with pytest.raises(PLCConnectionError):
        bridge.write_register("D101", 1)

    transport.connect("virtual", 0)
    assert bridge.read_snapshot().d101 == 0
    transport.close()

    with pytest.raises(PLCConnectionError):
        bridge.read_snapshot()
