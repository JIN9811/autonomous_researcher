import asyncio
import json
import os
import sys
import time
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from utils.monitor_process import MonitorProcess
from utils.monitor_worker import create_monitor_app
from utils.robot_monitor_stream import stream_robot_samples
from tests.unit.test_lerobot_joint_telemetry import _action_event


@pytest.fixture(autouse=True)
def isolate_video_diagnostic_log(monkeypatch, tmp_path):
    monkeypatch.setenv("ATR_VIDEO_LOG_PATH", str(tmp_path / "video.log"))


def test_video_runs_in_separate_process_and_stops_without_device_io():
    # Synthetic JPEG byte stream only; no printer, camera or network device.
    command = [sys.executable, "-u", "-c",
               "import sys,time\nfor i in range(200):\n sys.stdout.buffer.write(b'\\xff\\xd8fake\\xff\\xd9'); sys.stdout.flush(); time.sleep(.033)"]
    worker = MonitorProcess("video", {"command": command, "timeout": 2})
    try:
        assert worker.process.pid != os.getpid()
        assert worker.process.args == [sys.executable, "-m", "utils.monitor_worker"]
        for attempt in range(30):
            try:
                with urlopen(worker.url("frame.jpg"), timeout=3) as response:
                    assert response.read() == b"\xff\xd8fake\xff\xd9"
                break
            except ConnectionError:
                time.sleep(.02)
        else:
            pytest.fail("Worker did not start")
        with urlopen(worker.url("stream.mjpeg"), timeout=3) as response:
            assert b"Content-Type: image/jpeg" in response.read(128)
    finally:
        worker.close()
    assert worker.process.poll() is not None


def test_robot_worker_has_no_actuation_routes_and_rejects_other_origins(tmp_path):
    path = tmp_path / "motor_events.jsonl"
    path.write_text(json.dumps(_action_event(1, 100)) + "\n")
    latest = [{"context": {"session": {"session_id": "rollout-test", "status": "POLICY_ACTIVE"},
                            "log_path": str(path)}, "reset_at_ms": 4}, time.monotonic()]
    app = create_monitor_app("robot", {"origins": ["http://localhost:7860"]}, "secret", latest)
    assert [route.path for route in app.routes] == ["/secret/joints"]
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/secret/joints", headers={"origin": "http://evil.test"}):
                pass
        with client.websocket_connect("/secret/joints?sample_format=compact-v1", headers={"origin": "http://localhost:7860"}) as ws:
            history = ws.receive_json()
            assert history["type"] == "joint_history"
            assert history["samples"][0]["sequence"] == 1
            latest[:] = [{"context": None, "reset_at_ms": 5}, time.monotonic()]
            cleared = ws.receive_json()
            assert cleared["reset_at_ms"] == 5
            assert cleared["session"] == {}
    assert path.read_text().count('"event": "action"') == 1


def test_robot_worker_publishes_real_graph_artifacts_from_saved_samples(tmp_path):
    path = tmp_path / "motor_events.jsonl"
    path.write_text("".join(json.dumps(_action_event(i + 1, 100 + i / 10)) + "\n" for i in range(4)))
    latest = [{"context": {"session": {"session_id": "rollout-test", "status": "COMPLETED"},
                            "log_path": str(path)}}, time.monotonic()]
    app = create_monitor_app("robot", {"origins": ["http://localhost:7860"]}, "key", latest)
    with TestClient(app) as client:
        with client.websocket_connect("/key/joints?sample_format=compact-v1", headers={"origin": "http://localhost:7860"}) as ws:
            assert len(ws.receive_json()["samples"]) == 4
            result = ws.receive_json()
            assert result["type"] == "telemetry_artifacts"
            assert result["artifacts"]["ok"]
            assert result["artifacts"]["plot_png_url"].startswith("/api/lerobot/visualization/file?")
    artifact_dir = tmp_path / "grasp_display_v5"
    assert (artifact_dir / "policy_tracking.png").is_file()
    assert json.loads((artifact_dir / "policy_tracking_summary.json").read_text())["sample_count"] == 4
    assert not (tmp_path / "policy_tracking_summary.json").exists()
    assert result["artifacts"]["grasp_outcome_rule_version"] == "sustained_closing_contact_v5"


def test_completed_robot_stream_refreshes_task_totals_without_new_joint_samples(tmp_path):
    path = tmp_path / 'motor_events.jsonl'
    path.write_text(json.dumps(_action_event(1, 100)) + '\n')
    state = {'run_id': 'r', 'task_progress_projection_version': 1, 'run_metadata': {}}
    latest = [{'state': state, 'context': {'session': {'session_id': 's', 'status': 'COMPLETED'},
                                         'log_path': str(path)}}, time.monotonic()]
    app = create_monitor_app('robot', {'origins': ['http://localhost:7860']}, 'key', latest)
    with TestClient(app) as client:
        with client.websocket_connect('/key/joints', headers={'origin': 'http://localhost:7860'}) as ws:
            ws.receive_json()
            assert ws.receive_json()['type'] == 'telemetry_artifacts'
            assert ws.receive_json()['type'] == 'telemetry_state'
            state['run_metadata']['manipulation_task_progress'] = {'one': {
                'run_id': 'r', 'session_id': 's', 'state': 'done', 'success': True}}
            packet = ws.receive_json()
            assert packet['runtime_view']['metrics']['task_progress']['success_count'] == 1
            assert packet['type'] == 'telemetry_state'


def test_delayed_publisher_keeps_pose_and_log_without_replaying_history(tmp_path):
    path = tmp_path / "motor_events.jsonl"
    path.write_text(json.dumps(_action_event(1, 100)) + "\n")
    payload = {"context": {"session": {"session_id": "same-session", "status": "POLICY_ACTIVE"},
                           "log_path": str(path)}, "reset_at_ms": 4}
    latest = [payload, time.monotonic() - 10]
    app = create_monitor_app("robot", {"origins": ["http://localhost:7860"]}, "key", latest)
    with TestClient(app) as client:
        with client.websocket_connect("/key/joints", headers={"origin": "http://localhost:7860"}) as ws:
            first = ws.receive_json()
            assert first["type"] == "joint_history" and first["status"] == "stale"
            assert first["session"]["session_id"] == "same-session"
            with path.open("a") as stream:
                stream.write(json.dumps(_action_event(2, 101)) + "\n")
            next_packet = ws.receive_json()
            if next_packet["type"] == "telemetry_state":
                next_packet = ws.receive_json()
            assert next_packet["type"] == "joint_samples"
            assert [p["sequence"] for p in next_packet["samples"]] == [2]
            latest[1] = time.monotonic()
            resumed = ws.receive_json()
            while resumed["publisher_stale"]:
                resumed = ws.receive_json()
            assert resumed["type"] == "telemetry_state"
            assert resumed["session"]["session_id"] == "same-session"
            assert resumed["status"] != "idle"
            latest[:] = [{"context": None, "reset_at_ms": 5}, time.monotonic()]
            cleared = ws.receive_json()
            assert cleared["status"] == "idle" and cleared["reset_at_ms"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("initially_empty", [False, True])
@pytest.mark.parametrize("compact", [False, True])
async def test_isolated_stream_keeps_same_history_contract(tmp_path, monkeypatch, initially_empty, compact):
    import app.main as main
    from tests.integration.test_joint_telemetry_history import test_late_open_and_reconnect_replay_all_samples_then_follow_live
    async def isolated(socket):
        await stream_robot_samples(socket,
            context=main._joint_telemetry_session_context,
            reset=lambda: 0, public_session=main._joint_telemetry_public_session,
            runtime_view=main._manipulation_runtime_view, artifacts=main._joint_telemetry_artifacts)
    monkeypatch.setattr(main, "stream_lerobot_joint_telemetry", isolated)
    await test_late_open_and_reconnect_replay_all_samples_then_follow_live(tmp_path, monkeypatch, initially_empty, compact)


@pytest.mark.asyncio
async def test_local_video_redirect_bypasses_control_stream(monkeypatch):
    import app.main as main
    from starlette.requests import Request
    from types import SimpleNamespace
    monkeypatch.setattr(main, "_printer_bridge_manager", lambda: object())
    monkeypatch.setattr(main, "_bambu_video_config", lambda manager: {})
    monkeypatch.setattr(main, "monitor_process", lambda *args: SimpleNamespace(url=lambda path: "http://127.0.0.1:1234/key/" + path))
    monkeypatch.setattr(main, "_shared_bambu_video", lambda *args: pytest.fail("Decoder started in control process"))
    req = Request({"type": "http", "method": "GET", "path": "/api/printer/video-stream.mjpeg", "scheme": "http",
                   "headers": [(b"host", b"127.0.0.1:7860")], "client": ("127.0.0.1", 50), "server": ("127.0.0.1", 7860), "query_string": b""})
    response = await main.get_printer_video_stream(req)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/stream.mjpeg")
    req.scope["client"] = ("192.168.1.50", 50)
    assert not main._local_monitor_client(req)
