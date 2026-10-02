"""Dependency-free causal joint interpolation on an existing serial bus."""
import atexit
import json
import math
from pathlib import Path
import threading
import time


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("joint values and rates must be finite")
    return number


class LinearInterpolator:
    def __init__(self, duration):
        self.duration = finite(duration)
        if self.duration <= 0:
            raise ValueError('interpolation duration must be positive')
        self.start = self.goal = None
        self.started = None

    def retarget(self, applied, goal, now):
        # Start at the last bus command, never an unissued intermediate sample.
        if not applied or set(applied) != set(goal):
            raise ValueError('incomplete interpolation vector')
        self.start = {key: finite(value) for key, value in applied.items()}
        self.goal = {key: finite(value) for key, value in goal.items()}
        self.started = finite(now)

    def sample(self, now):
        if self.started is None:
            raise ValueError('interpolation target missing')
        fraction = max(0., min(1., (finite(now) - self.started) / self.duration))
        return {key: value + fraction * (self.goal[key] - value)
                for key, value in self.start.items()}


class LinearTransmit:
    """Interpolate only Goal_Position writes on the existing connected bus.

    Observation reads stay synchronous and use the original driver. One lock
    serializes those reads with the 100 Hz writer; there is no feedback cache,
    child process, replacement calibration or policy scheduling hook.
    """
    def __init__(self, bus, *, input_hz, output_hz=100, session_id='', log_dir=None):
        input_hz, output_hz = finite(input_hz), finite(output_hz)
        if not 0 < input_hz <= output_hz <= 1000:
            raise ValueError('require 0 < input_hz <= output_hz <= 1000')
        duration = 1. / input_hz
        self.output_hz = output_hz
        self.bus = bus
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.error = None
        self.ramp = LinearInterpolator(duration)
        self.read_original = bus.sync_read
        self.write_original = bus.sync_write
        self.applied = {}
        self.pending = False
        self.closed = False
        self.seq = self.writes = 0
        self.first_write = None
        self.session_id = session_id
        self.log = None
        self.logging_error = None
        if log_dir:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            self.log = (directory / 'linear_io.jsonl').open('a')
        bus.sync_read = self.read
        bus.sync_write = self.write
        self.thread = threading.Thread(target=self.run, name='linear-transmit', daemon=True)
        self.thread.start()
        atexit.register(self.close)

    def check(self):
        if self.error is not None:
            raise RuntimeError('linear transmission failed') from self.error
        if self.closed:
            raise RuntimeError('linear transmission closed')

    def read(self, register, *args, **kwargs):
        with self.lock:
            self.check()
            return self.read_original(register, *args, **kwargs)

    def write(self, register, values, *args, **kwargs):
        with self.lock:
            self.check()
            if register != 'Goal_Position':
                return self.write_original(register, values, *args, **kwargs)
            if args or kwargs:
                raise ValueError('linear interpolation requires normalized Goal_Position writes')
            goal = {name: finite(value) for name, value in values.items()}
            if not goal:
                return
            missing = goal.keys() - self.applied.keys()
            if missing:
                measured = self.read_original('Present_Position')
                self.applied.update({name: finite(measured[name]) for name in missing})
            # Include any previous target so partial updates do not drop a ramp.
            combined = {**(self.ramp.goal or {}), **goal}
            self.ramp.retarget({name: self.applied[name] for name in combined}, combined, time.monotonic())
            self.seq += 1
            self.pending = True

    def _log_io(self, method, *args):
        if self.log is None:
            return
        try:
            getattr(self.log, method)(*args)
        except (OSError, ValueError) as exc:
            self.logging_error = exc
            handle, self.log = self.log, None
            try:
                handle.close()
            except (OSError, ValueError):
                pass

    def record(self, event, state, now, **extra):
        if self.log:
            elapsed = now - self.first_write if self.first_write is not None else 0
            self._log_io('write', json.dumps({
                'event': event, 'state': state, 'time': now,
                'backend': 'linear_interpolation', 'session_id': self.session_id,
                'seq': self.seq, 'writes': self.writes, 'output_hz': self.output_hz,
                'write_hz': (self.writes - 1) / elapsed if elapsed > 0 else None,
                'applied': self.applied, **extra,
            }, allow_nan=False) + '\n')

    def run(self):
        period = 1. / self.output_hz
        next_tick = time.monotonic() + period
        last_flush = 0.
        try:
            while not self.stop.wait(max(0., next_tick - time.monotonic())):
                with self.lock:
                    if self.stop.is_set():
                        break
                    now = time.monotonic()
                    if self.pending:
                        positions = self.ramp.sample(now)
                        self.write_original('Goal_Position', positions)
                        self.applied.update(positions)
                        self.writes += 1
                        if self.first_write is None:
                            self.first_write = now
                        self.pending = now < self.ramp.started + self.ramp.duration
                        self.record('write', 'RUNNING', now, goal=self.ramp.goal)
                    elif now - last_flush >= .2:
                        self.record('status', 'READY', now)
                    if now - last_flush >= .2:
                        if self.log:
                            self._log_io('flush')
                        last_flush = now
                # Skip missed deadlines rather than burst old commands.
                next_tick += period
                if next_tick <= time.monotonic():
                    next_tick = time.monotonic() + period
        except Exception as exc:
            self.error = exc
            self.stop.set()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('linear transmitter did not stop; bus must not be reused')
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.bus.sync_read = self.read_original
            self.bus.sync_write = self.write_original
            try:
                self.record('stop', 'FAULT' if self.error else 'READY', time.monotonic(),
                            reason=str(self.error or ''))
            finally:
                if self.log:
                    self._log_io('close')
                    self.log = None
                atexit.unregister(self.close)
