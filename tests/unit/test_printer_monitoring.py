import asyncio
import json
import sys
import time
from types import SimpleNamespace

import pytest

from device_bridges.printer_fleet import monitoring as m
from device_bridges.printer_fleet.bridge import BambuMqttConfig


class FakeClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.commands = []
        self.closed = False
        self.instances.append(self)

    def username_pw_set(self, *args): pass
    def tls_set(self, **kwargs): pass
    def tls_insecure_set(self, *args): pass
    def reconnect_delay_set(self, **kwargs): pass
    def connect_async(self, *args, **kwargs): pass

    def loop_start(self):
        self.on_connect(self, None, None, 0)

    def subscribe(self, topic, **kwargs):
        self.topic = topic
        self.on_subscribe(self, None, 1, [0])

    def publish(self, topic, payload, **kwargs):
        self.commands.append(json.loads(payload))
        self.emit({"print": {"gcode_state": "RUNNING", "mc_percent": 12, "nested": {"a": 1}}})

    def emit(self, payload, retain=False):
        self.on_message(self, None, SimpleNamespace(topic=self.topic, retain=retain, payload=json.dumps(payload).encode()))

    def disconnect(self):
        self.closed = True
        self.on_disconnect(self, None, 0)

    def loop_stop(self): pass


@pytest.fixture(autouse=True)
def cleanup():
    m.close_monitors()
    FakeClient.instances.clear()
    yield
    m.close_monitors()


def read(**overrides):
    args = dict(host="printer", serial="serial", username="bblp", access_code="secret", timeout_sec=0)
    args.update(overrides)
    return m.read_mqtt_monitor(SimpleNamespace(Client=FakeClient), BambuMqttConfig(), **args)


def test_mqtt_reuses_subscription_and_only_requests_state():
    assert read()["ok"]
    assert read()["ok"]
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].commands == [{"pushing": {"sequence_id": "1", "command": "pushall"}, "user_id": "atr"}]


def test_mqtt_merges_deltas_and_copies_results():
    initial = read()
    FakeClient.instances[0].emit({"print": {"mc_percent": 13, "nested": {"b": 2}}})
    current = read()
    assert current["report"]["print"]["mc_percent"] == 13
    assert current["report"]["print"]["gcode_state"] == "RUNNING"
    assert current["report"]["print"]["nested"] == {"a": 1, "b": 2}
    current["report"]["print"]["mc_percent"] = 99
    assert read()["report"]["print"]["mc_percent"] == 13
    assert initial["report"]["print"]["mc_percent"] == 12


def test_mqtt_disconnected_and_stale_never_healthy():
    read()
    monitor = next(iter(m._mqtt_monitors.values()))
    monitor.received -= 20
    assert not read()["ok"]
    FakeClient.instances[0].emit({"print": {"mc_percent": 14}})
    assert read()["ok"]
    FakeClient.instances[0].disconnect()
    assert not read()["ok"]


def test_mqtt_reconnect_clears_old_fields_and_ignores_retained():
    read()
    client = FakeClient.instances[0]
    client.emit({"print": {"old_field": 1}})
    client.on_connect(client, None, None, 0)
    client.emit({"print": {"mc_percent": 99}}, retain=True)
    current = read()["report"]["print"]
    assert "old_field" not in current
    assert current["mc_percent"] == 12


def test_mqtt_credential_change_closes_old_connection():
    read()
    assert read(access_code="changed")["ok"]
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].closed
    assert len(m._mqtt_monitors) == 1


def test_mqtt_force_refresh_requires_new_observation():
    read()
    assert read(force_refresh=True)["ok"]
    assert len(FakeClient.instances[0].commands) == 2


def test_mqtt_missing_credentials_does_not_connect():
    assert not read(access_code="")["ok"]
    assert not FakeClient.instances


def video_command():
    return [sys.executable, "-u", "-c", "import sys,time\nfor n in range(100):\n sys.stdout.buffer.write(b'\\xff\\xd8'+str(n).encode()+b'\\xff\\xd9');sys.stdout.buffer.flush();time.sleep(.02)\ntime.sleep(1)"]


def test_video_shared_decoder_latest_frame_and_slow_viewer_skips_backlog():
    video = m.shared_video(video_command(), 2)
    assert m.shared_video(video_command(), 2) is video
    sequence, frame = video.read()
    assert frame.startswith(b"\xff\xd8")
    time.sleep(.15)
    newer, _ = video.read(sequence)
    assert newer > sequence + 1
    assert len(m._videos) == 1
    video.close()
    assert not video.thread.is_alive()


def test_video_high_frame_count_retains_only_latest_jpeg(monkeypatch):
    monkeypatch.setattr(m.LatestVideo, "_run", lambda self: None)
    video = m.LatestVideo(["unused"], 1)
    try:
        for index in range(10000):
            video._publish(b"\xff\xd8" + str(index).encode() + b"\xff\xd9")
        assert video.sequence == 10000
        assert video.frame == b"\xff\xd89999\xff\xd9"
        assert video.read()[1] == video.frame
        assert not any(isinstance(value, list) for key, value in vars(video).items() if key != "command")
    finally:
        video.close()


def test_video_idle_process_is_reaped(monkeypatch):
    monkeypatch.setattr(m.LatestVideo, "IDLE_TIMEOUT", .1)
    video = m.shared_video(video_command(), 2)
    video.read()
    video.thread.join(timeout=2)
    assert video.closed
    assert not video.thread.is_alive()


def test_video_source_exit_returns_error_not_old_frame():
    video = m.shared_video([sys.executable, "-c", "pass"], 1)
    with pytest.raises(RuntimeError):
        video.read()


@pytest.mark.parametrize("gap", [299.0, 301.0])
def test_established_video_reader_waits_five_minutes(monkeypatch, gap):
    monkeypatch.setattr(m.LatestVideo, "_run", lambda self: None)
    clock = [1000.0]
    monkeypatch.setattr(m, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    video = m.LatestVideo(["unused"], 60)
    video._publish(b"old")

    def wait(timeout):
        clock[0] += min(gap, timeout)
        if gap < timeout:
            video._publish(b"new")

    monkeypatch.setattr(video.condition, "wait", wait)
    try:
        if gap < 300:
            assert video.read(1) == (2, b"new")
        else:
            with pytest.raises(TimeoutError):
                video.read(1)
            assert clock[0] == 1300.0
    finally:
        video.close()


@pytest.mark.parametrize("gap, publishes", [(299.0, True), (301.0, False)])
def test_established_decoder_survives_gap_under_five_minutes(monkeypatch, gap, publishes):
    monkeypatch.setattr(m.threading.Thread, "start", lambda self: None)
    clock = [1000.0]
    monkeypatch.setattr(m, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    video = m.LatestVideo(["unused"], 60)
    video.readers = 1
    video._publish(b"old")
    process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 7, close=lambda: None), poll=lambda: 0)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(m.os, "set_blocking", lambda *a: None)
    calls = []

    def read(fd, size):
        calls.append(1)
        if len(calls) == 1:
            clock[0] += gap
            raise BlockingIOError
        if len(calls) == 2:
            return b"\xff\xd8new\xff\xd9"
        return b""

    monkeypatch.setattr(m.os, "read", read)
    video._run()
    assert video.sequence == (2 if publishes else 1)
    assert video.closed


def test_waiting_first_viewer_is_not_reaped_by_short_idle_timeout(monkeypatch):
    monkeypatch.setattr(m.LatestVideo, "IDLE_TIMEOUT", .05)
    command = [sys.executable, "-u", "-c",
               "import sys,time;time.sleep(.2);sys.stdout.buffer.write(b'\\xff\\xd8frame\\xff\\xd9');sys.stdout.buffer.flush();time.sleep(1)"]
    video = m.shared_video(command, 2)
    _, frame = video.read()
    assert frame == b"\xff\xd8frame\xff\xd9"
    assert video.readers == 0


def test_frame_endpoint_does_not_block_event_loop(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "_printer_bridge_manager", lambda: None)
    def capture(manager):
        time.sleep(.15)
        return b"jpeg"
    monkeypatch.setattr(main, "_capture_bambu_video_frame_bytes", capture)
    async def check():
        task = asyncio.create_task(main.get_printer_video_frame())
        await asyncio.sleep(.03)
        assert not task.done(), "frame capture blocked the event loop"
        response = await task
        assert response.body == b"jpeg"
    asyncio.run(check())
