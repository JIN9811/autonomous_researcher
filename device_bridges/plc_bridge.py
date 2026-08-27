"""Bounded Mitsubishi PLC transport and register bridge."""

from __future__ import annotations

from importlib import import_module
import time
from typing import Any, Protocol, Sequence

from device_bridges.base_bridge import BaseBridge
from utils.plc_safety_state import PLCRegisterSnapshot


class PLCTransportError(RuntimeError):
    """Base exception for PLC transport failures that callers can recover from."""


class PLCTransportImportError(PLCTransportError):
    """Raised when the optional pymcprotocol dependency is unavailable."""


class PLCConnectionError(PLCTransportError):
    """Raised when a production PLC connection cannot be opened or closed."""


class PLCReadError(PLCTransportError):
    """Raised when the contiguous safety-register read fails."""


class PLCWriteError(PLCTransportError):
    """Raised when an approved PLC register write fails."""


class PLCWriteRejected(ValueError):
    """Raised when a caller attempts a write outside the safety allowlist."""


_ALLOWED_WRITES = frozenset({("D101", 1), ("D102", 0), ("D102", 1)})


def _validate_write(device: str, value: int) -> None:
    if type(value) is not int or (device, value) not in _ALLOWED_WRITES:
        raise PLCWriteRejected(f"PLC write {device}={value} is not permitted")


class PLCTransport(Protocol):
    """Internal, minimal interface shared by live and virtual transports."""

    def connect(self, host: str, port: int) -> None: ...

    def close(self) -> None: ...

    def read_words(self, headdevice: str, readsize: int) -> Sequence[int]: ...

    def _write_word(self, device: str, value: int) -> None: ...


class PymcProtocolTransport:
    """Production adapter for pymcprotocol's Mitsubishi Type 3E client."""

    def __init__(self) -> None:
        self._client: Any | None = None

    def connect(self, host: str, port: int) -> None:
        if self._client is not None:
            self.close()
        try:
            pymcprotocol = import_module("pymcprotocol")
        except ImportError as exc:
            raise PLCTransportImportError(
                "pymcprotocol is required for the configured live PLC transport"
            ) from exc

        try:
            client = pymcprotocol.Type3E()
            client.connect(host, port)
        except Exception as exc:
            raise PLCConnectionError(f"could not connect to PLC at {host}:{port}") from exc
        self._client = client

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.close()
        except Exception as exc:
            raise PLCConnectionError("could not close PLC connection") from exc
        finally:
            self._client = None

    def read_words(self, headdevice: str, readsize: int) -> Sequence[int]:
        client = self._require_client()
        try:
            return client.batchread_wordunits(headdevice=headdevice, readsize=readsize)
        except Exception as exc:
            raise PLCReadError(f"could not read {readsize} PLC words from {headdevice}") from exc

    def _write_word(self, device: str, value: int) -> None:
        _validate_write(device, value)
        client = self._require_client()
        try:
            client.batchwrite_wordunits(headdevice=device, values=[value])
        except Exception as exc:
            raise PLCWriteError(f"could not write {value} to PLC register {device}") from exc

    def _require_client(self) -> Any:
        if self._client is None:
            raise PLCConnectionError("PLC transport is not connected")
        return self._client


class VirtualPLCTransport:
    """Explicit in-memory transport used only when selected by the caller."""

    def __init__(self, *, d100: int = 0, d101: int = 0, d102: int = 0) -> None:
        self.words = {"D100": d100, "D101": d101, "D102": d102}
        self.connected = False

    def connect(self, host: str, port: int) -> None:
        del host, port
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def read_words(self, headdevice: str, readsize: int) -> Sequence[int]:
        self._require_connection()
        if headdevice != "D100" or readsize != 3:
            raise PLCReadError("virtual PLC supports only a three-word D100-D102 snapshot")
        return [self.words["D100"], self.words["D101"], self.words["D102"]]

    def _write_word(self, device: str, value: int) -> None:
        _validate_write(device, value)
        self._require_connection()
        if device not in self.words:
            raise PLCWriteError(f"unknown virtual PLC register {device}")
        self.words[device] = value
        if (
            device == "D102"
            and value == 1
            and self.words["D101"] == 1
            and self.words["D100"] in {1, 2}
        ):
            self.words["D100"] = 0
            self.words["D101"] = 0

    def _require_connection(self) -> None:
        if not self.connected:
            raise PLCConnectionError("virtual PLC transport is not connected")


class PLCBridge(BaseBridge):
    """Safety-only bridge that exposes atomic snapshots and allowlisted writes."""

    def __init__(self, transport: PLCTransport) -> None:
        self._transport = transport
        self._sequence = 0

    def connect(self, host: str, port: int) -> None:
        self._transport.connect(host, port)

    def disconnect(self) -> None:
        self._transport.close()

    def read_snapshot(self) -> PLCRegisterSnapshot:
        words = self._transport.read_words("D100", 3)
        if len(words) != 3:
            raise PLCReadError("PLC did not return the complete D100-D102 snapshot")
        self._sequence += 1
        return PLCRegisterSnapshot(
            d100=words[0],
            d101=words[1],
            d102=words[2],
            sequence=self._sequence,
            received_monotonic=time.monotonic(),
        )

    def write_register(self, device: str, value: int) -> None:
        _validate_write(device, value)
        self._transport._write_word(device, value)

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "read_snapshot":
            snapshot = self.read_snapshot()
            return {
                "d100": snapshot.d100,
                "d101": snapshot.d101,
                "d102": snapshot.d102,
                "sequence": snapshot.sequence,
                "received_monotonic": snapshot.received_monotonic,
            }
        raise ValueError(f"unsupported PLC bridge command: {command}")
