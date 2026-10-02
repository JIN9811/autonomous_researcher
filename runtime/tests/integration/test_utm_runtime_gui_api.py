"""Integration tests for UTM runtime GUI API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


class FakeUTMRuntimeManager:
    def __init__(self) -> None:
        self.started = False
        self.graph_hash = "hash-1"
        self.direct_frame_calls = 0
        self.ros_frame_calls = 0
        self.graph_calls = 0
        self.probe_calls = 0
        self.cleanup_calls = 0

    def status(self):
        return {"ok": True, "status": "running" if self.started else "stopped", "pid": 4321 if self.started else None}

    def start(self):
        self.started = True
        return {"ok": True, "status": "running", "pid": 4321, "already_running": False}

    def stop(self):
        was_running = self.started
        self.started = False
        return {"ok": True, "status": "stopped", "was_running": was_running}

    def cleanup_ports(self):
        self.cleanup_calls += 1
        self.started = False
        return {
            "ok": True,
            "tool": "utm.camera.cleanup",
            "status": "released",
            "runtime": self.status(),
            "terminated": [],
            "remaining": [],
        }

    def probe(self):
        self.probe_calls += 1
        snapshot = self.graph()
        return {
            "ok": True,
            "status": self.status()["status"],
            "diagnostics": {"ros2_available": True, "workspace_found": True, "script_found": True, "topic_seen": True},
            "graph_hash": snapshot["graph_hash"],
            "failure_code": None,
        }

    def graph(self, previous_hash: str = ""):
        self.graph_calls += 1
        return {
            "ok": True,
            "changed": previous_hash != self.graph_hash,
            "graph_hash": self.graph_hash,
            "expected_graph": {"nodes": [{"id": "camera/usb_cam", "kind": "node"}], "edges": []},
            "actual_graph": {"nodes": [], "edges": []},
            "diagnostics": {"ros2_available": True},
        }

    def frame(self):
        self.ros_frame_calls += 1
        return {"ok": True, "mode": "ros_image_topic", "topic": "/image_utm", "frame_available": True}

    def frame_stream_status(self, *, topic="", fps=None, quality=82):
        return {
            "ok": True,
            "status": "running",
            "topic": topic or "/image_utm",
            "requested_fps": float(fps or 30),
            "measured_fps": 27.5,
            "estimated_dropped_frames": 3,
            "clients": 1,
            "quality": quality,
        }

    def camera_direct_frame(self):
        self.direct_frame_calls += 1
        return {"ok": True, "mode": "direct_v4l2_frame", "frame_available": False, "failure_code": "FAKE_FRAME"}

    def camera_config(self):
        return {
            "ok": True,
            "active_profile": {
                "label": "Camera UTM Primary",
                "width": 640,
                "height": 480,
                "fps": 30,
                "device_path": "/dev/v4l/by-id/test-camera",
            },
        }

    def update_camera_config(self, payload):
        return {"ok": True, "tool": "utm.camera.config.save", "config": self.camera_config(), "payload": payload}

    def discover_camera_devices(self):
        return {
            "ok": True,
            "devices": [
                {
                    "label": "Camera physical candidate",
                    "by_id_path": "/dev/v4l/by-id/test-camera",
                    "recommended": False,
                }
            ],
            "device_count": 1,
        }

    def start_calibration(self, payload):
        return {"ok": True, "status": "running", "pid": 1234, "calibration_file": "/tmp/camera.yaml", "payload": payload}

    def stop_calibration(self):
        return {"ok": True, "status": "stopped", "calibration_file": "/tmp/camera.yaml"}

    def calibration_status(self):
        return {"ok": True, "status": "stopped", "calibration_file": "/tmp/camera.yaml"}


def test_utm_runtime_api_status_start_probe_graph_frame_stop(monkeypatch) -> None:
    fake = FakeUTMRuntimeManager()
    monkeypatch.setattr(app_main, "_utm_runtime_manager", fake, raising=False)
    client = TestClient(app)

    assert client.get("/api/equipment/utm-runtime/status").json()["status"] == "stopped"

    start = client.post("/api/equipment/utm-runtime/start").json()
    assert start["ok"] is True
    assert start["status"] == "running"

    probe = client.post("/api/equipment/utm-runtime/probe").json()
    assert probe["ok"] is True
    assert probe["diagnostics"]["topic_seen"] is True

    graph = client.get("/api/equipment/utm-runtime/graph").json()
    assert graph["ok"] is True
    assert graph["changed"] is True
    assert graph["expected_graph"]["nodes"][0]["id"] == "camera/usb_cam"

    graph_again = client.get("/api/equipment/utm-runtime/graph?previous_hash=hash-1").json()
    assert graph_again["changed"] is False

    frame = client.get("/api/equipment/utm-runtime/frame").json()
    assert frame["ok"] is True
    assert frame["topic"] == "/image_utm"

    stop = client.post("/api/equipment/utm-runtime/stop").json()
    assert stop["ok"] is True
    assert stop["status"] == "stopped"

    cleanup = client.post("/api/equipment/utm-runtime/camera/cleanup").json()
    assert cleanup["ok"] is True
    assert cleanup["tool"] == "utm.camera.cleanup"
    assert fake.cleanup_calls == 1


def test_utm_runtime_stream_status_api_reports_actual_preview_rate(monkeypatch) -> None:
    fake = FakeUTMRuntimeManager()
    monkeypatch.setattr(app_main, "_utm_runtime_manager", fake, raising=False)
    client = TestClient(app)

    payload = client.get(
        "/api/equipment/utm-runtime/frame-stream/status",
        params={"topic": "/image_utm", "fps": 30, "quality": 82},
    ).json()

    assert payload["ok"] is True
    assert payload["requested_fps"] == 30.0
    assert payload["measured_fps"] == 27.5
    assert payload["estimated_dropped_frames"] == 3


def test_utm_camera_device_bridge_api(monkeypatch) -> None:
    fake = FakeUTMRuntimeManager()
    monkeypatch.setattr(app_main, "_utm_runtime_manager", fake, raising=False)
    client = TestClient(app)

    config = client.get("/api/equipment/utm-runtime/camera-config").json()
    assert config["ok"] is True
    assert config["active_profile"]["label"] == "Camera UTM Primary"

    saved = client.post("/api/equipment/utm-runtime/camera-config", json={"profiles": {"camera_utm_primary": {"fps": 30}}}).json()
    assert saved["ok"] is True
    assert saved["payload"]["profiles"]["camera_utm_primary"]["fps"] == 30

    devices = client.get("/api/equipment/utm-runtime/camera/devices").json()
    assert devices["ok"] is True
    assert devices["devices"][0]["recommended"] is False

    probe = client.post("/api/equipment/utm-runtime/camera/probe").json()
    assert probe["tool"] == "utm.camera.pre_start_check"
    assert "config" in probe
    assert "devices" in probe
    assert "frame" in probe

    started = client.post("/api/equipment/utm-runtime/camera/calibrate/start", json={"checkerboard_size": "9x6"}).json()
    assert started["status"] == "running"

    stopped = client.post("/api/equipment/utm-runtime/camera/calibrate/stop").json()
    assert stopped["status"] == "stopped"


def test_utm_camera_probe_uses_ros_frame_first_when_runtime_is_running(monkeypatch) -> None:
    fake = FakeUTMRuntimeManager()
    fake.started = True
    monkeypatch.setattr(app_main, "_utm_runtime_manager", fake, raising=False)
    client = TestClient(app)

    probe = client.post("/api/equipment/utm-runtime/camera/probe").json()

    assert probe["ok"] is True
    assert probe["frame"]["mode"] == "ros_image_topic"
    assert fake.ros_frame_calls == 1
    assert fake.direct_frame_calls == 0


def test_utm_camera_probe_reuses_single_graph_snapshot(monkeypatch) -> None:
    fake = FakeUTMRuntimeManager()
    fake.started = True
    monkeypatch.setattr(app_main, "_utm_runtime_manager", fake, raising=False)
    client = TestClient(app)

    probe = client.post("/api/equipment/utm-runtime/camera/probe").json()

    assert probe["ok"] is True
    assert fake.probe_calls == 0
    assert fake.graph_calls == 1
