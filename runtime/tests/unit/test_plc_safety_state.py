import pytest

from utils.plc_safety_state import (
    PLCCommand,
    PLCRegisterSnapshot,
    PLCSafetyState,
    classify_snapshot,
    decode_snapshot,
)


def snapshot(d100=0, d101=0, d102=0, sequence=1, received_monotonic=1.0):
    return PLCRegisterSnapshot(d100, d101, d102, sequence, received_monotonic)


def test_d101_latches_estop_and_d100_decodes_only_inside_estop():
    normal = snapshot(sequence=1, received_monotonic=1.0)
    estop = snapshot(d101=1, sequence=2, received_monotonic=1.2)
    resume = snapshot(d100=1, d101=1, sequence=3, received_monotonic=1.4)

    assert decode_snapshot(normal, estop).event == "estop_latched"
    assert decode_snapshot(estop, resume).command is PLCCommand.RESUME


def test_command_without_estop_is_protocol_fault():
    current = snapshot(d100=1)

    assert classify_snapshot(current).failure_code == "PLC_COMMAND_WITHOUT_ESTOP"


def test_reset_is_decoded_only_while_estop_is_latched():
    previous = snapshot(d101=1)
    current = snapshot(d100=2, d101=1, sequence=2, received_monotonic=2.0)

    transition = decode_snapshot(previous, current)

    assert transition.command is PLCCommand.RESET
    assert transition.state is PLCSafetyState.RESET_REQUESTED


def test_repeated_d100_request_is_deduplicated():
    previous = snapshot(d100=1, d101=1)
    current = snapshot(d100=1, d101=1, sequence=2, received_monotonic=2.0)

    transition = decode_snapshot(previous, current)

    assert transition.command is PLCCommand.NONE
    assert transition.event == "unchanged"


def test_release_handshake_is_observed_after_estop_clears():
    previous = snapshot(d101=1, d102=1)
    current = snapshot(d102=0, sequence=2, received_monotonic=2.0)

    transition = decode_snapshot(previous, current)

    assert transition.event == "release_observed"
    assert transition.state is PLCSafetyState.RELEASE_OBSERVED


@pytest.mark.parametrize(
    "field,value",
    [
        ("d100", -1),
        ("d100", 3),
        ("d101", -1),
        ("d101", 2),
        ("d102", -1),
        ("d102", 2),
    ],
)
def test_invalid_register_values_are_protocol_faults(field, value):
    values = {"d100": 0, "d101": 0, "d102": 0}
    values[field] = value
    current = PLCRegisterSnapshot(**values, sequence=1, received_monotonic=1.0)

    classified = classify_snapshot(current)
    decoded = decode_snapshot(None, current)

    assert classified.state is PLCSafetyState.PROTOCOL_FAULT
    assert classified.failure_code == "PLC_INVALID_REGISTER_VALUE"
    assert decoded.state is PLCSafetyState.PROTOCOL_FAULT
    assert decoded.failure_code == "PLC_INVALID_REGISTER_VALUE"


def test_register_snapshot_is_immutable():
    current = snapshot()

    with pytest.raises((AttributeError, TypeError)):
        current.d100 = 1
