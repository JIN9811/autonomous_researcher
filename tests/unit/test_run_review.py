import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from app.run_review_routes import review_router
from utils.run_review import RunReviewRecorder, bounded, safe_child
from utils import run_review
from utils.vision_capture_preview import publish_capture_preview


def event(run="new-run", cycle=0, **kwargs):
    return {"run_id": run, "event_type": "agent.attention_requested", "agent": "vision",
            "payload": {"checkpoint": "verification_1"},
            "state": {"run_id": run, "mode": "live", "loop_count": cycle, "stage": "vision"}, **kwargs}


@pytest.fixture
def recorder(tmp_path):
    (tmp_path / "new-run").mkdir()
    (tmp_path / "current-run").mkdir()
    return RunReviewRecorder(tmp_path, "current-run")


def read_point(recorder, number=1):
    return json.loads((recorder.root / "new-run" / "review" / f"{number:06}.json").read_text())


def test_no_existing_run_recording_or_state_mutation(recorder):
    original = event(run="current-run")
    saved = copy.deepcopy(original)
    recorder.offer(original)
    recorder.record(original)
    assert recorder.queue.empty()
    assert not (recorder.root / "current-run" / "review").exists()
    assert original == saved


def test_queue_is_bounded_and_never_waits(recorder):
    for _ in range(100):
        recorder.offer(event())
    assert recorder.queue.qsize() == 8
    assert recorder.dropped == 92
    assert recorder.errors == 0


def test_assets_are_immutable_and_foreign_run_is_rejected(recorder):
    image = recorder.root / "new-run" / "frame.png"
    image.write_bytes(b"first image")
    foreign = recorder.root / "current-run" / "frame.png"
    foreign.write_bytes(b"foreign image")
    original = event(payload={"frame_path": str(image), "other": str(foreign), "api_key": "hidden"})
    saved = copy.deepcopy(original)
    recorder.record(original)
    first = read_point(recorder)
    asset = first["cards"]["vision"]["images"][0]["name"]
    image.write_bytes(b"second image")
    recorder.record(original)
    assert len(first["cards"]["vision"]["images"]) == 1
    assert (recorder.root / "new-run" / "review" / "assets" / asset).read_bytes() == b"first image"
    assert read_point(recorder) == first
    assert "hidden" not in json.dumps(first)
    assert original == saved


def test_cycle_boundary_does_not_reuse_previous_cards_or_chat(recorder):
    recorder.record(event(agent="design", payload={"latest": {"role": "design", "content": "old cycle"}}))
    next_event = event(cycle=1)
    next_event["state"]["run_metadata"] = {"latest_design_agent_report": {"run_id": "new-run", "loop_index": 0, "result": "old"},
        "utm_verifications": {"run_id": "new-run", "loop_id": 0, "result": "old"}}
    recorder.record(next_event)
    point = read_point(recorder, 2)
    assert "design" not in point["cards"]
    assert point["chat"] == []
    assert point["cards"]["vision"]["event"]["verification"] is None


def test_worker_io_failure_does_not_propagate_to_producer(recorder, monkeypatch):
    def fail(_):
        raise OSError("Disk full")
    monkeypatch.setattr(recorder, "record", fail)
    recorder.start()
    recorder.offer(event())
    recorder.queue.join()
    recorder.stop()
    recorder.thread.join(2)
    assert recorder.errors == 1


def test_existing_archive_never_overwritten(recorder):
    recorder.record(event())
    first = read_point(recorder)
    second = RunReviewRecorder(recorder.root, "different-current-run")
    second.record(event(payload={"message": "do not overwrite"}))
    assert read_point(recorder) == first
    assert "new-run" in second.blocked_runs


def test_capture_is_recorded_pending_without_granting_success(recorder, monkeypatch):
    monkeypatch.setattr(run_review, "capture_sink", recorder.offer)
    state = SimpleNamespace(run_id="new-run", loop_count=0, mode="live", current_experiment_spec={"specimen_id":"cube"},run_metadata={})
    assert publish_capture_preview(state, {"frame_path": "not-available.png"}, "verification_2")
    captured = recorder.queue.get_nowait()
    assert captured["payload"]["checkpoint"] == "verification_2"
    assert captured["payload"]["preview"]["confirmed"] is False
    assert captured["payload"]["preview"]["review_pending"] is True
    assert state.run_metadata["utm_verifications"]["previews"]["verification_2"]["status"] == "pending"


def test_capture_observer_failure_does_not_change_preview(monkeypatch):
    def fail(_):
        raise RuntimeError("Archive unavailable")
    monkeypatch.setattr(run_review, "capture_sink", fail)
    state = SimpleNamespace(run_id="new",loop_count=0,mode="live",current_experiment_spec={},run_metadata={})
    assert publish_capture_preview(state, {"frame_path":"frame.png"}, "active_cam")
    assert state.run_metadata["utm_verifications"]["previews"]["active_cam"]["confirmed"] is False


def test_routes_are_archive_only_and_reject_mutations(recorder):
    recorder.record(event())
    app = FastAPI()
    app.include_router(review_router(recorder.root, Jinja2Templates(directory="web/templates")))
    with TestClient(app) as client:
        response = client.get("/replay")
        assert response.status_code == 200
        assert 'replay-brand' in response.text
        assert 'planning.js' in response.text
        assert 'live-agent-binder' in response.text
        csp = response.headers['content-security-policy']
        assert 'http://testserver/api/review/' in csp
        assert "form-action 'none'" in csp
        assert '/api/run/' not in csp
        assert client.get('/api/review/layout').json()['agents']
        assert client.get("/api/review/runs").json()["runs"][0]["run_id"] == "new-run"
        assert client.get("/api/review/new-run/points").json()["points"][0]["cycle"] == 0
        assert client.get("/api/review/new-run/points/000001").json()["read_only"] is True
        assert client.get("/api/review/new-run/points/missing").status_code == 404
        assert client.post("/api/review/new-run/points/000001").status_code == 405
        assert client.get("/api/review/current-run/points").status_code == 404
        assert client.get("/api/run/start").status_code == 404


def test_symlink_and_traversal_rejected(recorder, tmp_path):
    with pytest.raises(ValueError):
        safe_child(tmp_path, "../outside")
    (tmp_path / "alias").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError):
        safe_child(tmp_path, "alias")
    recorder.record(event())
    archive = tmp_path / "new-run" / "review"
    (archive / "leak.png").symlink_to(tmp_path.parent / "private.png")
    with pytest.raises(ValueError):
        safe_child(archive, "leak.png")


def test_bounded_redacted_projection():
    result = bounded({"password":"secret", "nested":{"access_code":"123", "safe":list(range(10000))}})
    assert "password" not in result
    assert "access_code" not in result["nested"]
    assert len(result["nested"]["safe"]) == 60


def test_queued_point_never_uses_a_newer_overwritten_frame(recorder):
    path = recorder.root / "new-run" / "capture.png"
    path.write_bytes(b"later frame")
    recorder.record(event(payload={"frame_path":str(path)}, review_received_ns=1))
    assert read_point(recorder)["cards"]["vision"]["images"] == []


def test_review_reuses_live_template_with_archive_transport_and_csp():
    js = Path("web/static/run_review.js").read_text()
    html = Path("web/templates/planning.html").read_text()
    assert 'method !== "GET"' in js
    assert 'window.EventSource = OfflineStream' in js
    assert 'window.WebSocket = OfflineStream' in js
    assert 'replay-point-select' in html
    assert '/static/planning.js' in html
    assert 'if (!window.AX4LABReplay) setInterval' in Path('web/static/planning.js').read_text()
    main = Path("web/static/app.js").read_text()
    replay = main[main.index('if (selectedMode === "replay")'):]
    assert replay.index("return;") < replay.index('postJson("/api/run/start"')


def test_broken_sink_preserves_existing_broadcast():
    from app.controller import MainController
    delivered = []
    def broken(_):
        raise OSError("Sink failed")
    controller = SimpleNamespace(review_event_sink=broken,
        _compact_event_for_buffer=lambda e:e, _trace=SimpleNamespace(add=delivered.append), _event_queues=set())
    original = {"event_type":"example", "payload":{}}
    asyncio.run(MainController._broadcast_event(controller, original))
    assert delivered == [original]
