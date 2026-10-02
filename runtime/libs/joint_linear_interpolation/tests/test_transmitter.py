"""Regression: interpolation must not replace the observation/connection path."""
import threading
import time

import pytest

from joint_linear_interpolation import LinearTransmit


class Bus:
    def __init__(self):
        self.position = {'joint': 0.0}
        self.writes = []
        self.fail = False
        self.busy = False
        self.overlap = False

    def sync_read(self, register, *args, **kwargs):
        self.overlap |= self.busy
        self.busy = True
        try:
            time.sleep(.001)
            return dict(self.position)
        finally:
            self.busy = False

    def sync_write(self, register, values, *args, **kwargs):
        self.overlap |= self.busy
        self.busy = True
        try:
            if self.fail:
                raise OSError('serial disconnected')
            time.sleep(.001)
            self.writes.append((time.monotonic(), register, dict(values)))
            self.position.update(values)
        finally:
            self.busy = False


def transmitter(bus, **kwargs):
    factory = LinearTransmit
    assert factory is not None, 'linear backend needs an in-process transmit-only adapter'
    return factory(bus, input_hz=12.5, **kwargs)


def wait_until(predicate):
    deadline = time.monotonic() + 1
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.002)
    assert predicate()


def test_original_bus_feedback_stays_live_and_no_commands_before_first_target():
    bus = Bus()
    tx = transmitter(bus)
    try:
        time.sleep(.04)  # camera/model startup is not a feedback deadline
        assert bus.writes == []
        bus.position['joint'] = 3.
        assert bus.sync_read('Present_Position') == {'joint': 3.}
        bus.sync_write('Goal_Position', {'joint': 4.})
        wait_until(lambda: bus.writes and bus.writes[-1][2]['joint'] == 4.)
        values = [row[2]['joint'] for row in bus.writes]
        assert 3. < values[0] < 4.
        assert values == sorted(values)
        assert len(values) >= 4
        count = len(bus.writes)
        time.sleep(.04)
        assert len(bus.writes) == count  # no extrapolation or repeating old queue
    finally:
        tx.close()


def test_reader_and_100hz_writer_share_the_existing_serial_bus_without_overlap():
    bus = Bus()
    tx = transmitter(bus)
    try:
        bus.sync_write('Goal_Position', {'joint': 1.})
        deadline = time.monotonic() + .12
        while time.monotonic() < deadline:
            bus.sync_read('Present_Position')
            time.sleep(.001)
        assert not bus.overlap
        assert bus.writes[-1][2] == {'joint': 1.}
    finally:
        tx.close()
    count = len(bus.writes)
    time.sleep(.025)
    assert len(bus.writes) == count
    bus.sync_write('Goal_Position', {'joint': 2.})
    assert bus.writes[-1][2] == {'joint': 2.}  # originals restored


def test_serial_error_surfaces_on_existing_observation_path_without_retry():
    bus = Bus()
    tx = transmitter(bus)
    try:
        bus.fail = True
        bus.sync_write('Goal_Position', {'joint': 1.})
        wait_until(lambda: tx.error is not None)
        with pytest.raises(RuntimeError, match='linear transmission failed'):
            bus.sync_read('Present_Position')
        assert bus.writes == []
    finally:
        tx.close()


def test_nonfinite_target_never_reaches_motor_and_partial_update_is_supported():
    bus = Bus()
    bus.position['second'] = 8.
    tx = transmitter(bus)
    try:
        with pytest.raises(ValueError):
            bus.sync_write('Goal_Position', {'joint': float('nan')})
        assert not bus.writes
        bus.sync_write('Goal_Position', {'joint': 1.})
        wait_until(lambda: bus.writes and bus.writes[-1][2]['joint'] == 1.)
        assert bus.position['second'] == 8.
    finally:
        tx.close()


def test_retarget_discards_old_goal_and_does_not_jump_to_it():
    bus = Bus()
    tx = transmitter(bus)
    try:
        bus.sync_write('Goal_Position', {'joint': 8.})
        wait_until(lambda: len(bus.writes) >= 2)
        with tx.lock:
            count = len(bus.writes)
            previous = bus.writes[-1][2]['joint']
            bus.sync_write('Goal_Position', {'joint': -1.})
        wait_until(lambda: bus.writes[-1][2]['joint'] == -1.)
        values = [row[2]['joint'] for row in bus.writes[count:]]
        assert max(values) <= previous
        assert values == sorted(values, reverse=True)
    finally:
        tx.close()


@pytest.mark.parametrize("input_hz,output_hz", [(0,100), (30,20), (30,float("nan")), (float("inf"),100)])
def test_invalid_rates_fail_before_attaching_bus(input_hz, output_hz):
    bus = Bus()
    original = bus.sync_write
    with pytest.raises(ValueError):
        LinearTransmit(bus, input_hz=input_hz, output_hz=output_hz)
    assert bus.sync_write == original


def test_output_frequency_changes_real_send_cadence():
    counts = []
    for hz in (40, 80):
        bus = Bus()
        tx = LinearTransmit(bus, input_hz=4, output_hz=hz)
        try:
            bus.sync_write('Goal_Position', {'joint':1.})
            wait_until(lambda: bus.writes and bus.writes[-1][2]['joint'] == 1.)
            counts.append(len(bus.writes))
        finally:
            tx.close()
    assert 8 <= counts[0] <= 12
    assert counts[1] >= counts[0]*1.5


@pytest.mark.parametrize('input_hz,expected', [(15,1/15), (30,1/30)])
def test_input_rate_controls_segment_not_output_rate(input_hz, expected):
    bus = Bus()
    tx = LinearTransmit(bus, input_hz=input_hz, output_hz=100)
    try:
        start = time.monotonic()
        bus.sync_write('Goal_Position', {'joint':1.})
        wait_until(lambda: bus.writes and bus.writes[-1][2]['joint'] == 1.)
        elapsed = bus.writes[-1][0]-start
        assert expected <= elapsed <= expected+.04
    finally:
        tx.close()


def test_log_write_failure_does_not_stop_sender_or_block_cleanup():
    class FullLog:
        def write(self, *_):
            raise OSError('disk full')
        def flush(self):
            raise OSError('disk full')
        def close(self):
            raise OSError('disk full')
    bus = Bus()
    tx = LinearTransmit(bus, input_hz=30, output_hz=100)
    tx.log = FullLog()
    try:
        bus.sync_write('Goal_Position', {'joint':1.})
        wait_until(lambda: bus.writes and bus.writes[-1][2]['joint'] == 1.)
        assert tx.error is None
        assert isinstance(tx.logging_error, OSError)
    finally:
        tx.close()
    bus.sync_write('Goal_Position', {'joint':2.})
    assert bus.writes[-1][2] == {'joint':2.}
