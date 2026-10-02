"""Pure decoding for the PLC safety register contract."""

from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real
from typing import Optional


class PLCCommand(str, Enum):
    NONE = "none"
    RESUME = "resume"
    RESET = "reset"


class PLCSafetyState(str, Enum):
    DISCONNECTED = "disconnected"
    NORMAL = "normal"
    ESTOP_LATCHED = "estop_latched"
    RESUME_REQUESTED = "resume_requested"
    RESET_REQUESTED = "reset_requested"
    HANDSHAKE_ASSERTED = "handshake_asserted"
    RELEASE_OBSERVED = "release_observed"
    PROTOCOL_FAULT = "protocol_fault"


@dataclass(frozen=True, slots=True)
class PLCRegisterSnapshot:
    d100: int
    d101: int
    d102: int
    sequence: int
    received_monotonic: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if (
            isinstance(self.received_monotonic, bool)
            or not isinstance(self.received_monotonic, Real)
            or not math.isfinite(self.received_monotonic)
            or self.received_monotonic < 0
        ):
            raise ValueError("received_monotonic must be non-negative")


@dataclass(frozen=True, slots=True)
class PLCTransition:
    state: PLCSafetyState
    command: PLCCommand = PLCCommand.NONE
    event: str = "unchanged"
    failure_code: Optional[str] = None


def _invalid_register(current: PLCRegisterSnapshot) -> Optional[str]:
    if type(current.d100) is not int or current.d100 not in {0, 1, 2}:
        return "D100"
    if type(current.d101) is not int or current.d101 not in {0, 1}:
        return "D101"
    if type(current.d102) is not int or current.d102 not in {0, 1}:
        return "D102"
    return None


def _classify(current: PLCRegisterSnapshot) -> PLCTransition:
    invalid_register = _invalid_register(current)
    if invalid_register is not None:
        return PLCTransition(
            state=PLCSafetyState.PROTOCOL_FAULT,
            failure_code="PLC_INVALID_REGISTER_VALUE",
            event="protocol_fault",
        )

    if current.d101 == 0 and current.d100 != 0:
        return PLCTransition(
            state=PLCSafetyState.PROTOCOL_FAULT,
            failure_code="PLC_COMMAND_WITHOUT_ESTOP",
            event="protocol_fault",
        )

    if current.d102 == 1:
        return PLCTransition(state=PLCSafetyState.HANDSHAKE_ASSERTED, event="handshake_asserted")

    if current.d101 == 1 and current.d100 == 1:
        return PLCTransition(
            state=PLCSafetyState.RESUME_REQUESTED,
            command=PLCCommand.RESUME,
            event="resume_requested",
        )

    if current.d101 == 1 and current.d100 == 2:
        return PLCTransition(
            state=PLCSafetyState.RESET_REQUESTED,
            command=PLCCommand.RESET,
            event="reset_requested",
        )

    if current.d101 == 1:
        return PLCTransition(state=PLCSafetyState.ESTOP_LATCHED, event="estop_latched")

    return PLCTransition(state=PLCSafetyState.NORMAL)


def classify_snapshot(snapshot: PLCRegisterSnapshot) -> PLCTransition:
    """Classify one validated PLC snapshot without consulting external state."""
    return _classify(snapshot)


def decode_snapshot(
    previous: Optional[PLCRegisterSnapshot], current: PLCRegisterSnapshot
) -> PLCTransition:
    """Decode a snapshot and emit a D100 command only when it is newly observed."""
    transition = _classify(current)
    if (
        previous is not None
        and transition.command is not PLCCommand.NONE
        and previous.d101 == current.d101 == 1
        and previous.d100 == current.d100
        and previous.d102 == current.d102
    ):
        return PLCTransition(state=transition.state, event="unchanged")

    if (
        previous is not None
        and previous.d101 == 1
        and previous.d102 == 1
        and current.d101 == current.d102 == 0
        and current.d100 == 0
    ):
        return PLCTransition(state=PLCSafetyState.RELEASE_OBSERVED, event="release_observed")

    if previous is not None and previous.d101 == 0 and current.d101 == 1:
        return PLCTransition(state=transition.state, command=transition.command, event="estop_latched")

    return transition
