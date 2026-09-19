"""Offline, synthetic display sources only. Never contact a ROS or printer device."""
import hashlib
import json
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from device_bridges.utm_runtime_bridge import UTMRuntimeConfig, UTMRuntimeProcessManager
from utils.monitor_process import close_monitor_processes, monitor_process
from utils.vision_monitor_stream import RemoteVisionStream


@pytest.fixture(autouse=True)
def cleanup_workers():
    yield
    close_monitor_processes()


def settings(tmp_path, *, silent=False):
    jpeg = b"\xff\xd8unchanged-ROI-preview\xff\xd9"
    multipart = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    script = "import sys,time\n" + ("time.sleep(30)" if silent else
        f"for _ in range(600):\n sys.stdout.buffer.write({multipart!r}); sys.stdout.flush(); time.sleep(.02)")
    return dict(key="offline", command=[sys.executable, "-u", "-c", script], cwd=str(tmp_path),
                topic="/image_utm", target_fps=30, jpeg_quality=82), multipart


def eventually(check):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except ConnectionError:
            pass
        time.sleep(.04)
    pytest.fail("Display worker did not reach expected state")


@pytest.mark.parametrize("printer_first", [True, False])
def test_printer_and_vision_share_process_preserve_bytes_and_independent_stop(tmp_path, printer_first):
    printer = dict(command=[sys.executable, "-u", "-c",
        "import sys,time\nfor _ in range(600):\n sys.stdout.buffer.write(b'\\xff\\xd8printer\\xff\\xd9'); sys.stdout.flush(); time.sleep(.02)"], timeout=2)
    if printer_first:
        first_worker = monitor_process("video", printer)
    config, expected = settings(tmp_path)
    remote = RemoteVisionStream(**config)
    worker = monitor_process("video", printer)
    assert remote.worker is worker
    if printer_first:
        assert worker is first_worker
    pid = worker.process.pid
    with urlopen(remote.url(), timeout=3) as stream:
        actual = stream.read(len(expected))
        assert hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest()
        with urlopen(worker.url("frame.jpg"), timeout=3) as response:
            assert response.read() == b"\xff\xd8printer\xff\xd9"
        assert remote.stats()["clients"] == 1
        # No new decoder/subscriber for a second viewer of the same topic.
        duplicate = RemoteVisionStream(**config)
        assert duplicate.source_id == remote.source_id
        with urlopen(duplicate.url(), timeout=3) as second:
            assert second.read(len(expected)) == expected
            assert remote.stats()["clients"] == 2
    eventually(lambda: remote.stats()["clients"] == 0)
    remote.stop()
    with pytest.raises(HTTPError) as exc:
        urlopen(remote.url(), timeout=3)
    assert exc.value.code == 404
    assert worker.process.pid == pid and worker.process.poll() is None
    with urlopen(worker.url("frame.jpg"), timeout=3) as response:
        assert response.read() == b"\xff\xd8printer\xff\xd9"


def test_silent_ros_source_releases_disconnected_viewer(tmp_path):
    config, _ = settings(tmp_path, silent=True)
    remote = RemoteVisionStream(**config)
    # Headers are available before a frame: closing here simulates a tab closed
    # while ROS is silent, without waiting for another image to release next().
    stream = urlopen(remote.url(), timeout=3)
    eventually(lambda: remote.stats()["clients"] == 1)
    stream.close()
    eventually(lambda: remote.stats()["clients"] == 0)
    remote.stop()


def test_display_registration_does_not_change_raw_capture_or_roi(tmp_path, monkeypatch):
    from device_bridges.camera_vision import utm_runtime_bridge as module
    manager = UTMRuntimeProcessManager(UTMRuntimeConfig(workspace_root=tmp_path,
        script_path=tmp_path / "fake.sh", log_dir=tmp_path / "logs", ros_setup_paths=[]))
    monkeypatch.setattr(manager, "status", lambda: {"status": "running", "pid": 42})
    captured_commands = []
    def capture(command, **kwargs):
        captured_commands.append(command)
        return 0, json.dumps({"ok": True, "data_url": "data:image/jpeg;base64,c2FtZS1yYXc=",
                              "topic": command[-2], "width": 640, "height": 480}), ""
    monkeypatch.setattr(manager, "_run_ros_frame_command", capture)
    before = manager.raw_frame()
    camera_before = manager.camera_config()
    script_before = module.ROS_IMAGE_CAPTURE_SCRIPT
    key, inline_settings = manager._frame_stream_settings(topic="/camera/image_raw", fps=15)
    registered = []
    class FakeRemote:
        def __init__(self, **kwargs): registered.append(kwargs)
        def url(self): return "http://127.0.0.1:1/preview"
        def alive(self): return True
        def stop(self): pass
    monkeypatch.setattr("utils.vision_monitor_stream.RemoteVisionStream", FakeRemote)
    assert manager.frame_stream_url(topic="/camera/image_raw", fps=15).endswith("/preview")
    after = manager.raw_frame()
    assert captured_commands[0] == captured_commands[1]
    assert before["data_url"] == after["data_url"]
    assert before["topic"] == after["topic"] != "/image_utm"
    assert manager.camera_config() == camera_before
    assert module.ROS_IMAGE_CAPTURE_SCRIPT == script_before
    assert registered == [inline_settings]
    assert inline_settings["topic"] == "/image_utm"
    assert inline_settings["command"][-1].endswith("/image_utm 15.000 82")
    assert not manager._mjpeg_streams
    manager._stop_mjpeg_streams_locked()
    assert manager._remote_mjpeg_streams == {}


@pytest.mark.asyncio
async def test_local_route_redirects_without_capture_and_keeps_remote_fallback(monkeypatch):
    from types import SimpleNamespace
    from starlette.requests import Request
    import app.main as main
    calls = []
    bridge = SimpleNamespace(frame_stream_url=lambda **kw: calls.append(kw) or "http://127.0.0.1:1234/key/vision/a/stream.mjpeg",
        frame_stream=lambda **kw: iter([b"unchanged-preview"]),
        raw_frame=lambda: pytest.fail("Decision capture must not run for a preview"))
    monkeypatch.setattr(main, "_utm_runtime_bridge", lambda: bridge)
    req = Request({"type": "http", "method": "GET", "path": "/api/equipment/utm-runtime/frame-stream.mjpeg",
        "scheme": "http", "headers": [(b"host", b"127.0.0.1:7860")], "client": ("127.0.0.1", 55),
        "server": ("127.0.0.1", 7860), "query_string": b""})
    response = await main.get_utm_runtime_frame_stream(req, topic="/image_utm", fps=15)
    assert response.status_code == 307
    assert calls == [{"topic": "/image_utm", "fps": 15}]
    assert response.headers["location"].endswith("/vision/a/stream.mjpeg")
    req.scope["client"] = ("192.168.1.10", 55)
    response = await main.get_utm_runtime_frame_stream(req, topic="/image_utm", fps=15)
    assert response.status_code == 200
    assert len(calls) == 1


def test_worker_limits_sources_and_has_no_configuration_http_api(tmp_path):
    from fastapi.testclient import TestClient
    from utils.monitor_worker import create_monitor_app
    app = create_monitor_app("video", {}, "secret", [{}, 0])
    config, _ = settings(tmp_path)
    for i in range(4):
        app.state.video_control({"operation": "vision_register", "config": {**config, "key": str(i)}})
    with pytest.raises(ValueError, match="limit"):
        app.state.video_control({"operation": "vision_register", "config": {**config, "key": "5"}})
    with TestClient(app) as client:
        assert client.post("/secret/vision/register", json=config).status_code == 404
        assert client.get("/wrong/vision/a/status").status_code == 404


def test_slow_preview_start_does_not_lock_capture_or_survive_runtime_reload(tmp_path, monkeypatch):
    manager = UTMRuntimeProcessManager(UTMRuntimeConfig(workspace_root=tmp_path,
        script_path=tmp_path / "fake.sh", log_dir=tmp_path / "logs", ros_setup_paths=[]))
    monkeypatch.setattr(manager, "status", lambda: {"status": "running"})
    entered, release, acquired, stopped = (threading.Event() for _ in range(4))
    class SlowRemote:
        def __init__(self, **kwargs):
            entered.set()
            assert release.wait(3)
        def url(self): return "must-not-be-used"
        def stop(self): stopped.set()
    monkeypatch.setattr("utils.vision_monitor_stream.RemoteVisionStream", SlowRemote)
    result = []
    registration = threading.Thread(target=lambda: result.append(manager.frame_stream_url(fps=15)))
    def capture_and_reload():
        with manager._lock:
            acquired.set()
            manager._stop_mjpeg_streams_locked()
    registration.start()
    assert entered.wait(3)
    capture = threading.Thread(target=capture_and_reload)
    capture.start()
    try:
        assert acquired.wait(1), "Display startup blocked the decision capture lock"
    finally:
        release.set()
        registration.join(3)
        capture.join(3)
    assert result == [""]
    assert stopped.is_set()
    assert not manager._remote_mjpeg_streams
