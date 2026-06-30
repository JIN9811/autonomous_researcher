"""Tests for in-process LeRobot -> Isaac mirror publication."""

from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

from scripts import lerobot_isaac_mirror_runtime_wrapper as runtime_wrapper
from scripts.lerobot_isaac_mirror_runtime_wrapper import (
    ActiveRobotCamTracker,
    IsaacRgbdRenderContext,
    IsaacRgbdRenderWorker,
    IsaacMirrorPublisher,
    LatestFrameSidecar,
    RecordAttemptSidecar,
    SpecimenPoseFrameUpdater,
    patch_omx_observation,
    patch_omx_send_action,
    patch_record_loop,
)


@pytest.fixture(autouse=True)
def _isolate_default_pending_pose_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ATR_SPECIMEN_POSE_PENDING_PATH", str(tmp_path / "pending" / "latest_specimen_pose_payload.json"))


def test_isaac_mirror_runtime_wrapper_does_not_precreate_record_parent_before_first_sample(tmp_path: Path, monkeypatch) -> None:
    record_path = tmp_path / "dataset" / "sidecar" / "isaac_mirror" / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))

    IsaacMirrorPublisher()

    assert not record_path.parent.exists()
    assert not (tmp_path / "dataset").exists()


def test_isaac_mirror_runtime_wrapper_applies_calibration_to_payload_and_sidecar(tmp_path: Path, monkeypatch) -> None:
    calibration_path = tmp_path / "isaac_omx_mirror_calibration.json"
    record_path = tmp_path / "mirror.jsonl"
    calibration_path.write_text(json.dumps({"joints": {"shoulder_pan": {"offset_deg": 10.0}}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_CALIBRATION_PATH", str(calibration_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SESSION_ID", "mirror-test-session")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_PROFILE_ID", "robotis_omx_ai")

    publisher = IsaacMirrorPublisher()
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: posted.append(payload) or {"ok": True, "status_code": 200})

    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    assert publisher.flush(timeout_s=1.0) is True

    assert len(posted) == 1
    assert posted[0]["session_id"] == "mirror-test-session"
    assert posted[0]["calibration"]["loaded"] is True  # type: ignore[index]
    assert posted[0]["joint_state"][0]["motor_name"] == "shoulder_pan"  # type: ignore[index]
    assert posted[0]["joint_state"][0]["position_deg"] == 15.0  # type: ignore[index]
    record = json.loads(record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["calibration"]["path"] == str(calibration_path)
    assert record["sync_metrics"]["receiver_accepted"] is True


def test_isaac_mirror_publish_offloads_post_and_record_io(tmp_path: Path, monkeypatch) -> None:
    record_path = tmp_path / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")

    publisher = IsaacMirrorPublisher()
    calls: list[dict[str, object]] = []

    def slow_post(payload: dict[str, object]) -> dict[str, object]:
        calls.append(payload)
        time.sleep(0.2)
        return {"ok": True, "status_code": 200}

    monkeypatch.setattr(publisher, "_post", slow_post)

    started = time.monotonic()
    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    elapsed = time.monotonic() - started

    assert elapsed < 0.05
    assert publisher.flush(timeout_s=1.0) is True
    assert len(calls) == 1
    assert record_path.is_file()


def test_isaac_mirror_publish_tolerates_control_loop_jitter(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "15")

    now = [100.0]
    monkeypatch.setattr(runtime_wrapper.time, "monotonic", lambda: now[0])
    publisher = IsaacMirrorPublisher()

    assert publisher.should_publish() is True
    publisher._last_post_monotonic = now[0]

    now[0] = 100.0 + publisher.period_s * 0.5
    assert publisher.should_publish() is False

    now[0] = 100.0 + publisher.period_s * 0.95
    assert publisher.should_publish() is True


def test_isaac_mirror_publisher_caps_legacy_timeout_for_live_post(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_MIRROR_TIMEOUT_S", "0.5")
    monkeypatch.delenv("ATR_ISAAC_MIRROR_POST_TIMEOUT_S", raising=False)

    publisher = IsaacMirrorPublisher()

    assert publisher.timeout_s == pytest.approx(0.15)


def test_isaac_mirror_runtime_wrapper_queues_rgbd_render_request_separately(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    record_path = tmp_path / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_abc")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "2")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_TARGET_FPS", "15")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_CAMERAS", "wrist,top")

    publisher = IsaacMirrorPublisher()
    mirror_posts: list[dict[str, object]] = []
    render_posts: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: mirror_posts.append(payload) or {"ok": True, "status_code": 200})
    monkeypatch.setattr(
        publisher.render_worker,
        "_post",
        lambda payload: render_posts.append(payload) or {"ok": True, "status_code": 200, "response": {"status": "render_queued"}},
    )

    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    assert publisher.flush(timeout_s=1.0) is True

    assert len(mirror_posts) == 1
    assert "render_request" not in mirror_posts[0]
    assert len(render_posts) == 1
    render_request = render_posts[0]["render_request"]  # type: ignore[index]
    assert render_request["schema"] == "atr.isaac_rgbd.render_request.v1"  # type: ignore[index]
    assert render_request["attempt_id"] == "attempt_abc"  # type: ignore[index]
    assert render_request["episode_index"] == 2  # type: ignore[index]
    assert render_request["sample_index"] == 1  # type: ignore[index]
    assert render_request["target_fps"] == 15.0  # type: ignore[index]
    assert render_request["cameras"] == ["wrist", "top"]  # type: ignore[index]
    assert Path(str(render_request["output_dir"])) == dataset / "sidecar" / "isaac_rgbd" / "episode_002" / "attempt_abc"  # type: ignore[index]
    assert publisher.render_worker.endpoint == "http://127.0.0.1:8766/render"
    record = json.loads(record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["render_queue"]["attempt_id"] == "attempt_abc"
    assert "render_request" not in record


def test_isaac_mirror_runtime_wrapper_defers_rgbd_render_until_after_record(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    record_path = tmp_path / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_deferred")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "0")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_MODE", "deferred_after_record")

    publisher = IsaacMirrorPublisher()
    mirror_posts: list[dict[str, object]] = []
    render_posts: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: mirror_posts.append(payload) or {"ok": True, "status_code": 200})
    monkeypatch.setattr(
        publisher.render_worker,
        "_post",
        lambda payload: render_posts.append(payload) or {"ok": True, "status_code": 200, "response": {"status": "render_queued"}},
    )

    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    assert publisher.flush(timeout_s=1.0) is True

    assert len(mirror_posts) == 1
    assert render_posts == []
    record = json.loads(record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["render_queue"]["status"] == "deferred_after_record"
    assert record["render_queue"]["attempt_id"] == "attempt_deferred"
    assert record["render_queue"]["render_request"]["schema"] == "atr.isaac_rgbd.render_request.v1"
    assert record["render_queue"]["render_request"]["frame_index"] == 0


def test_isaac_mirror_rgbd_render_context_refreshes_per_record_episode(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    record_path = tmp_path / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_base_ep000")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "0")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")

    publisher = IsaacMirrorPublisher()
    mirror_posts: list[dict[str, object]] = []
    render_posts: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: mirror_posts.append(payload) or {"ok": True, "status_code": 200})
    monkeypatch.setattr(
        publisher.render_worker,
        "_post",
        lambda payload: render_posts.append(payload) or {"ok": True, "status_code": 200, "response": {"status": "render_queued"}},
    )

    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    assert publisher.flush(timeout_s=1.0) is True

    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_base_ep001")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "1")
    monkeypatch.setenv(
        "ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR",
        str(dataset / "sidecar" / "isaac_rgbd" / "episode_001" / "attempt_base_ep001"),
    )
    publisher.maybe_publish({"shoulder_pan.pos": 6.0})
    assert publisher.flush(timeout_s=1.0) is True

    assert all("render_request" not in payload for payload in mirror_posts)
    assert render_posts[0]["render_request"]["attempt_id"] == "attempt_base_ep000"  # type: ignore[index]
    assert render_posts[0]["render_request"]["episode_index"] == 0  # type: ignore[index]
    assert render_posts[0]["render_request"]["frame_index"] == 0  # type: ignore[index]
    assert render_posts[1]["render_request"]["attempt_id"] == "attempt_base_ep001"  # type: ignore[index]
    assert render_posts[1]["render_request"]["episode_index"] == 1  # type: ignore[index]
    assert render_posts[1]["render_request"]["frame_index"] == 0  # type: ignore[index]
    assert Path(str(render_posts[1]["render_request"]["output_dir"])) == dataset / "sidecar" / "isaac_rgbd" / "episode_001" / "attempt_base_ep001"  # type: ignore[index]


def test_isaac_mirror_rgbd_render_worker_does_not_block_mirror_post(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(tmp_path / "mirror.jsonl"))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_async")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")

    publisher = IsaacMirrorPublisher()
    mirror_posts: list[dict[str, object]] = []
    render_posts: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: mirror_posts.append(payload) or {"ok": True, "status_code": 200})

    def slow_render_post(payload: dict[str, object]) -> dict[str, object]:
        render_posts.append(payload)
        time.sleep(0.2)
        return {"ok": True, "status_code": 200, "response": {"status": "render_queued"}}

    monkeypatch.setattr(publisher.render_worker, "_post", slow_render_post)

    started = time.monotonic()
    publisher.maybe_publish({"shoulder_pan.pos": 5.0})
    elapsed = time.monotonic() - started

    assert elapsed < 0.05
    assert publisher.flush(timeout_s=1.0) is True
    assert len(mirror_posts) == 1
    assert len(render_posts) == 1


def test_isaac_mirror_rgbd_render_worker_caps_legacy_timeout_for_queue_post(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_TIMEOUT_S", "0.5")
    monkeypatch.delenv("ATR_ISAAC_RGBD_RENDER_POST_TIMEOUT_S", raising=False)

    context = IsaacRgbdRenderContext()
    worker = IsaacRgbdRenderWorker(context, mirror_endpoint="http://127.0.0.1:8766/joints", default_timeout_s=0.5)

    assert worker.timeout_s == pytest.approx(0.15)


def test_isaac_mirror_rgbd_render_worker_replaces_stale_queued_jobs(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_latest")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "0")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")

    context = IsaacRgbdRenderContext()
    worker = IsaacRgbdRenderWorker(context, mirror_endpoint="http://127.0.0.1:8766/joints", default_timeout_s=0.5)
    worker._worker_started = True

    first = worker.enqueue({"joint_state": []}, 1, "2026-06-29T00:00:01Z")
    second = worker.enqueue({"joint_state": []}, 2, "2026-06-29T00:00:02Z")

    assert first["status"] == "queued"
    assert second["status"] == "queued_replaced_stale"
    assert worker._jobs.qsize() == 1
    queued = worker._jobs.get_nowait()
    assert queued["request"]["sample_index"] == 2
    assert queued["request"]["frame_index"] == 1


def test_isaac_mirror_runtime_wrapper_defaults_to_leader_action(monkeypatch) -> None:
    monkeypatch.delenv("ATR_ISAAC_MIRROR_SOURCE", raising=False)

    class FakeFollower:
        _atr_latest_present_position_action = {"shoulder_lift.pos": -55.0, "elbow_flex.pos": 45.0}

    publisher = IsaacMirrorPublisher()

    action, source, source_error, selection = publisher.action_from_follower(
        FakeFollower(),
        {"shoulder_lift.pos": -54.0, "elbow_flex.pos": 44.0},
        leader_action={"shoulder_lift": -58.0, "elbow_flex": 47.0},
    )

    assert action == {"shoulder_lift.pos": -58.0, "elbow_flex.pos": 47.0}
    assert source == "in_process_leader_action"
    assert source_error == ""
    assert selection == {}


def test_isaac_mirror_runtime_wrapper_uses_follower_present_position_source(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SOURCE", "follower_present_position")

    class FakeBus:
        def sync_read(self, register: str) -> dict[str, float]:
            raise AssertionError("mirror must not sync-read the motor bus from send_action")

    class FakeFollower:
        bus = FakeBus()
        _atr_latest_present_position_action = {"shoulder_pan.pos": 5.0, "gripper.pos": 42.5}

    publisher = IsaacMirrorPublisher()

    action, source, source_error, selection = publisher.action_from_follower(
        FakeFollower(),
        {"shoulder_pan.pos": 1.0, "gripper.pos": 60.0},
    )

    assert action == {"shoulder_pan.pos": 5.0, "gripper.pos": 42.5}
    assert source == "in_process_follower_present_position"
    assert source_error == ""
    assert selection["mode"] == "follower_present_position"


def test_isaac_mirror_runtime_wrapper_uses_leader_joint_when_it_is_lower_than_sagged_follower(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SOURCE", "follower_present_position")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_LEADER_SAG_MIN_DELTA", "0.25")

    class FakeFollower:
        _atr_latest_present_position_action = {
            "shoulder_lift.pos": -55.0,
            "elbow_flex.pos": 45.0,
            "wrist_flex.pos": 30.0,
            "wrist_roll.pos": 3.0,
        }

    publisher = IsaacMirrorPublisher()

    action, source, source_error, selection = publisher.action_from_follower(
        FakeFollower(),
        {"shoulder_lift.pos": -54.0, "elbow_flex.pos": 44.0, "wrist_flex.pos": 30.1, "wrist_roll.pos": 10.0},
        leader_action={"shoulder_lift.pos": -58.0, "elbow_flex.pos": 47.0, "wrist_flex.pos": 30.1, "wrist_roll.pos": 10.0},
    )

    assert action == {
        "shoulder_lift.pos": -58.0,
        "elbow_flex.pos": 47.0,
        "wrist_flex.pos": 30.0,
        "wrist_roll.pos": 3.0,
    }
    assert source == "in_process_hybrid_follower_present_position_leader_sag"
    assert source_error == ""
    assert selection["mode"] == "leader_when_lower_than_follower"
    assert selection["selected_source_by_joint"] == {
        "shoulder_lift.pos": "leader",
        "elbow_flex.pos": "leader",
        "wrist_flex.pos": "follower",
        "wrist_roll.pos": "follower",
    }


def test_isaac_mirror_runtime_wrapper_records_leader_follower_source_selection(tmp_path: Path, monkeypatch) -> None:
    record_path = tmp_path / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")

    publisher = IsaacMirrorPublisher()
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: posted.append(payload) or {"ok": True, "status_code": 200})

    publisher.maybe_publish(
        {"shoulder_lift.pos": -58.0},
        source="in_process_hybrid_follower_present_position_leader_sag",
        source_selection={
            "mode": "leader_when_lower_than_follower",
            "selected_source_by_joint": {"shoulder_lift.pos": "leader"},
        },
    )
    assert publisher.flush(timeout_s=1.0) is True

    assert posted[0]["source_selection"]["selected_source_by_joint"] == {"shoulder_lift.pos": "leader"}  # type: ignore[index]
    record = json.loads(record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["source_selection"]["mode"] == "leader_when_lower_than_follower"


def test_record_attempt_sidecar_writes_active_cam_result_and_specimen_pose(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_SESSION_ID", "lr-record-1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_one")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "3")

    sidecar = RecordAttemptSidecar()
    started = sidecar.begin(reason="record_start")
    result = {
        "ok": True,
        "attempts": [
            {
                "camera": "d405",
                "result": {
                    "ok": True,
                    "snapshot": {
                        "source": "active_robot_cam",
                        "pose": {"position_isaac_world_mm": {"x": 10.0, "y": 20.0, "z": 4.0}},
                    },
                },
            }
        ],
    }

    written = sidecar.write_active_cam_result(result)

    attempt_dir = dataset / "sidecar" / "attempts" / "episode_003" / "attempt_one"
    assert started["ok"] is True
    assert written["ok"] is True
    assert Path(written["attempt_dir"]) == attempt_dir
    assert json.loads((attempt_dir / "active_cam_result.json").read_text(encoding="utf-8"))["ok"] is True
    assert json.loads((attempt_dir / "specimen_pose.json").read_text(encoding="utf-8"))["pose"]["position_isaac_world_mm"]["x"] == 10.0
    status = json.loads((attempt_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "active_cam_result_written"
    events = [json.loads(line) for line in (dataset / "sidecar" / "attempts" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["record_attempt_started", "active_cam_result_written"]


def test_record_attempt_sidecar_overwrites_prior_attempt_outputs(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    attempt_dir = dataset / "sidecar" / "attempts" / "episode_001" / "attempt_same"
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_001" / "attempt_same"
    attempt_dir.mkdir(parents=True)
    render_dir.mkdir(parents=True)
    (attempt_dir / "active_cam_result.json").write_text('{"ok": false}', encoding="utf-8")
    (attempt_dir / "stale.txt").write_text("old", encoding="utf-8")
    (render_dir / "frame_000000_rgb.png").write_text("old-rgb", encoding="utf-8")
    manifest_path = dataset / "sidecar" / "attempts" / "manifest.jsonl"
    manifest_path.write_text(
        "\n".join(
            [
                json.dumps({"schema": "atr.record_attempt.event.v1", "event": "old", "attempt_id": "attempt_same", "episode_index": 1}),
                json.dumps({"schema": "atr.record_attempt.event.v1", "event": "keep", "attempt_id": "attempt_other", "episode_index": 1}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_SESSION_ID", "lr-record-1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_same")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_OVERWRITE", "1")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR", str(render_dir))

    started = RecordAttemptSidecar().begin(reason="record_start")

    assert started["ok"] is True
    assert not (attempt_dir / "stale.txt").exists()
    assert not (render_dir / "frame_000000_rgb.png").exists()
    assert json.loads((attempt_dir / "status.json").read_text(encoding="utf-8"))["status"] == "started"
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert [(row["attempt_id"], row["event"]) for row in rows] == [
        ("attempt_other", "keep"),
        ("attempt_same", "record_attempt_started"),
    ]


def test_record_attempt_sidecar_can_update_episode_context_between_record_loops(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "dataset"
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_SESSION_ID", "lr-record-episode-context")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_base")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "0")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_OVERWRITE", "1")

    sidecar = RecordAttemptSidecar()

    first = sidecar.begin_episode(episode_index=0, reason="record_start")
    second = sidecar.begin_episode(episode_index=1, reason="record_start")

    assert first["attempt_id"] == "attempt_base_ep000"
    assert second["attempt_id"] == "attempt_base_ep001"
    assert Path(first["attempt_dir"]) == dataset / "sidecar" / "attempts" / "episode_000" / "attempt_base_ep000"
    assert Path(second["attempt_dir"]) == dataset / "sidecar" / "attempts" / "episode_001" / "attempt_base_ep001"
    assert sidecar.render_output_dir == dataset / "sidecar" / "isaac_rgbd" / "episode_001" / "attempt_base_ep001"
    rows = [json.loads(line) for line in (dataset / "sidecar" / "attempts" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["attempt_id"], row["episode_index"], row["event"]) for row in rows] == [
        ("attempt_base_ep000", 0, "record_attempt_started"),
        ("attempt_base_ep001", 1, "record_attempt_started"),
    ]


def test_latest_frame_sidecar_writes_top_frame_manifest(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_HZ", "999")

    sidecar = LatestFrameSidecar()
    color = np.zeros((24, 32, 3), dtype=np.uint8)
    color[10:14, 12:16] = (255, 0, 0)
    depth = np.full((24, 32, 3), 128, dtype=np.uint8)
    manifest_path = sidecar.write_observation({"top": color, "top_depth": depth}, force=True, reason="record_start")

    assert manifest_path == root / "latest_frame.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "atr_lerobot_latest_frame.v1"
    assert manifest["camera_key"] == "top"
    assert manifest["reason"] == "record_start"
    assert manifest["color_space"] == "rgb"
    assert Path(manifest["color_image_path"]).is_file()
    assert Path(manifest["depth_visual_image_path"]).is_file()


def test_latest_frame_sidecar_offloads_periodic_png_io(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_HZ", "999")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ASYNC_ENABLED", "1")

    from PIL import Image

    original_save = Image.Image.save

    def slow_save(self, fp, *args, **kwargs):
        time.sleep(0.15)
        return original_save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", slow_save)

    sidecar = LatestFrameSidecar()
    color = np.zeros((24, 32, 3), dtype=np.uint8)
    depth = np.full((24, 32, 3), 128, dtype=np.uint8)

    started = time.monotonic()
    manifest_path = sidecar.write_observation({"top": color, "top_depth": depth}, reason="latest")
    elapsed = time.monotonic() - started

    assert manifest_path == root / "latest_frame.json"
    assert elapsed < 0.05
    assert sidecar.flush(timeout_s=1.0) is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["color_image_path"]).is_file()
    assert Path(manifest["depth_visual_image_path"]).is_file()


def test_latest_frame_sidecar_uses_unique_tmp_image_paths(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")

    from PIL import Image

    original_save = Image.Image.save
    saved_names: list[str] = []

    def spy_save(self, fp, *args, **kwargs):
        saved_names.append(Path(fp).name)
        return original_save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", spy_save)

    sidecar = LatestFrameSidecar()
    color = np.zeros((24, 32, 3), dtype=np.uint8)
    depth = np.full((24, 32, 3), 128, dtype=np.uint8)

    sidecar.write_observation({"top": color, "top_depth": depth}, force=True, reason="active_robot_cam")
    sidecar.write_observation({"top": color, "top_depth": depth}, force=True, reason="latest")

    color_tmp_names = [name for name in saved_names if name.startswith("top_color.")]
    assert len(color_tmp_names) == 2
    assert "top_color.tmp.png" not in color_tmp_names
    assert len(set(color_tmp_names)) == 2


def test_latest_frame_sidecar_allows_forced_write_while_async_writer_is_active(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_HZ", "999")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ASYNC_ENABLED", "1")

    from PIL import Image

    original_save = Image.Image.save
    first_save_started = runtime_wrapper.threading.Event()

    def slow_first_save(self, fp, *args, **kwargs):
        if not first_save_started.is_set():
            first_save_started.set()
            time.sleep(0.1)
        return original_save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", slow_first_save)

    sidecar = LatestFrameSidecar()
    color = np.zeros((24, 32, 3), dtype=np.uint8)
    depth = np.full((24, 32, 3), 128, dtype=np.uint8)

    sidecar.write_observation({"top": color, "top_depth": depth}, reason="latest")
    assert first_save_started.wait(timeout=1.0) is True
    manifest_path = sidecar.write_observation({"top": color, "top_depth": depth}, force=True, reason="active_robot_cam")

    assert sidecar.flush(timeout_s=1.0) is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["reason"] in {"latest", "active_robot_cam"}
    assert Path(manifest["color_image_path"]).is_file()
    assert not list(root.glob("*.tmp.*"))


def test_latest_frame_sidecar_does_not_enable_raw_depth_sidecar_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ATR_LEROBOT_RAW_DEPTH_DIR", raising=False)
    monkeypatch.delenv("ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS", raising=False)
    monkeypatch.delenv("ATR_LEROBOT_RAW_DEPTH_FORMAT", raising=False)
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(tmp_path / "latest_frame"))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "wrist")

    LatestFrameSidecar()

    assert "ATR_LEROBOT_RAW_DEPTH_DIR" not in os.environ
    assert "ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS" not in os.environ
    assert "ATR_LEROBOT_RAW_DEPTH_FORMAT" not in os.environ


def test_latest_frame_sidecar_accepts_camera_specific_depth_scale(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "wrist")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", "0.001")

    sidecar = LatestFrameSidecar()
    color = np.zeros((24, 32, 3), dtype=np.uint8)
    manifest_path = sidecar.write_observation(
        {"wrist": color},
        force=True,
        reason="active_robot_cam_d405",
        depth_scale_m_per_unit=0.0001,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["camera_key"] == "wrist"
    assert manifest["depth_scale_m_per_unit"] == 0.0001


def test_record_start_updater_runs_frame_detector_and_posts_specimen_pose(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    capture = tmp_path / "payload.json"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' \"$1\" > {capture}\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"position_isaac_world_mm\": {\"x\": 1, \"y\": 2, \"z\": 3}}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    manifest_path = tmp_path / "latest_frame.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_RECORD_START_ENABLED", "1")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(script))
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENDPOINT", "http://127.0.0.1:8766/joints")

    updater = SpecimenPoseFrameUpdater()
    posted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(updater, "_post_json", lambda endpoint, payload: posted.append((endpoint, payload)) or {"ok": True})

    result = updater.update_from_manifest(manifest_path, reason="record_start")

    detector_payload = json.loads(capture.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert detector_payload["frame_manifest_path"] == str(manifest_path)
    assert detector_payload["autostart_realsense"] is False
    assert detector_payload["specimen_id"] == "redcube-record-start"
    assert posted[0][0] == "http://127.0.0.1:8766/specimen_pose"
    assert posted[0][1]["pose"]["schema"] == "specimen_pose.v1"  # type: ignore[index]


def test_specimen_frame_updater_can_force_d405_direct_a4_mapping(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    capture = tmp_path / "payload.json"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' \"$1\" > {capture}\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"a4_camera_to_isaac_transform\": \"direct\", \"position_isaac_world_mm\": {\"x\": 1, \"y\": 2, \"z\": 3}}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    manifest_path = tmp_path / "latest_frame.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(script))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENDPOINT", "http://127.0.0.1:8766/joints")

    updater = SpecimenPoseFrameUpdater()
    monkeypatch.setattr(updater, "_post_json", lambda endpoint, payload: {"ok": True})

    result = updater.update_from_manifest(
        manifest_path,
        reason="active_robot_cam_d405",
        pose_payload_overrides={
            "camera_id": "active_robot_cam_d405",
            "a4_camera_to_isaac_transform": "direct",
            "a4_width_mm": 297.0,
            "a4_height_mm": 210.0,
            "a4_isaac_width_mm": 297.0,
            "a4_isaac_height_mm": 210.0,
        },
    )

    detector_payload = json.loads(capture.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert detector_payload["camera_id"] == "active_robot_cam_d405"
    assert detector_payload["a4_camera_to_isaac_transform"] == "direct"
    assert detector_payload["a4_width_mm"] == 297.0
    assert detector_payload["a4_height_mm"] == 210.0
    assert detector_payload["a4_isaac_width_mm"] == 297.0
    assert detector_payload["a4_isaac_height_mm"] == 210.0


def test_specimen_frame_updater_saves_pending_pose_when_isaac_post_fails(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    pending_path = tmp_path / "pending" / "latest_specimen_pose_payload.json"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"position_isaac_world_mm\": {\"x\": 11, \"y\": 22, \"z\": 15.2}}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    manifest_path = tmp_path / "latest_frame.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(script))
    monkeypatch.setenv("ATR_SPECIMEN_POSE_PENDING_PATH", str(pending_path))

    updater = SpecimenPoseFrameUpdater()
    monkeypatch.setattr(updater, "_post_json", lambda endpoint, payload: {"ok": False, "error": "URLError: connection refused"})

    result = updater.update_from_manifest(manifest_path, reason="active_robot_cam_d405")

    assert result["ok"] is True
    assert result["status"] == "pose_saved_pending_isaac"
    assert result["pending_pose_path"] == str(pending_path)
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert pending["reason"] == "active_robot_cam_d405"
    assert pending["pose"]["position_isaac_world_mm"] == {"x": 11, "y": 22, "z": 15.2}


def test_specimen_frame_updater_rejects_pose_without_world_position(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    pending_path = tmp_path / "pending" / "latest_specimen_pose_payload.json"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"a4_camera_to_isaac_transform\": \"direct\"}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    manifest_path = tmp_path / "latest_frame.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(script))
    monkeypatch.setenv("ATR_SPECIMEN_POSE_PENDING_PATH", str(pending_path))

    updater = SpecimenPoseFrameUpdater()
    result = updater.update_from_manifest(manifest_path, reason="active_robot_cam_d405")

    assert result["ok"] is False
    assert result["failure_code"] == "SPECIMEN_POSE_FRAME_POSITION_MISSING"
    assert not pending_path.exists()


def test_active_robot_cam_default_motion_uses_70_percent_speed_scale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "10")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.delenv("ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE", raising=False)

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

    class FakeUpdater:
        pass

    class FakeBus:
        def sync_read(self, register: str):
            assert register == "Present_Position"
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

    sent: list[dict[str, float]] = []
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    tracker._move_to_action(FakeRobot(), lambda _robot, action: sent.append(dict(action)) or dict(action), {"shoulder_pan.pos": 70.0})

    assert len(sent) == 22
    assert sent[-1] == {"shoulder_pan.pos": 70.0}


def test_active_robot_cam_hardcoded_motion_uses_cosine_ease(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "4")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MAX_STEP", "100")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

    class FakeUpdater:
        pass

    class FakeBus:
        def sync_read(self, register: str):
            assert register == "Present_Position"
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

    sent: list[dict[str, float]] = []
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    tracker._move_to_action(FakeRobot(), lambda _robot, action: sent.append(dict(action)) or dict(action), {"shoulder_pan.pos": 100.0})

    values = [action["shoulder_pan.pos"] for action in sent]
    assert values == pytest.approx([14.64466, 50.0, 85.35534, 100.0], abs=1e-4)


def test_active_robot_cam_resume_motion_uses_slower_default_speed_scale(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 100.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "4")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MAX_STEP", "100")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", "0")
    monkeypatch.delenv("ATR_ACTIVE_ROBOT_CAM_RESUME_SPEED_SCALE", raising=False)

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            return {"ok": True, "pose": {"schema": "specimen_pose.v1"}}

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    sent: list[dict[str, float]] = []
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = tracker.capture_once(
        FakeRobot(),
        send_action=lambda _robot, action: sent.append(dict(action)) or dict(action),
        current_action={"shoulder_pan.pos": 100.0},
        reason="teleop",
    )

    assert result["ok"] is True
    assert len(sent) == 12
    assert sent[-1] == {"shoulder_pan.pos": 100.0}


def test_active_robot_cam_consumes_external_isaac_capture_request(tmp_path: Path, monkeypatch) -> None:
    request_path = tmp_path / "active_robot_cam_request.json"
    request_path.write_text(json.dumps({"reason": "isaac_timeline_play"}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_REQUEST_PATH", str(request_path))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

    class FakeUpdater:
        pass

    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    assert tracker.consume_capture_request_reason() == "isaac_timeline_play"
    assert not request_path.exists()


def test_active_robot_cam_ignores_expired_external_isaac_capture_request(tmp_path: Path, monkeypatch) -> None:
    request_path = tmp_path / "active_robot_cam_request.json"
    request_path.write_text(
        json.dumps({"reason": "isaac_timeline_play", "expires_at": time.time() - 1.0}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_REQUEST_PATH", str(request_path))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

    class FakeUpdater:
        pass

    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    assert tracker.consume_capture_request_reason() == ""
    assert not request_path.exists()


def test_active_robot_cam_skips_first_action_capture_when_pending_pose_exists(tmp_path: Path, monkeypatch) -> None:
    pending_path = tmp_path / "latest_specimen_pose_payload.json"
    pending_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_TRIGGER_ON_FIRST_ACTION", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

    class FakeUpdater:
        def __init__(self) -> None:
            self.pending_path = pending_path

    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    assert tracker.should_run_on_action() is False


def test_active_robot_cam_waits_one_second_before_and_after_stable_capture(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 1.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.delenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", raising=False)
    monkeypatch.delenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", raising=False)

    events: list[str] = []
    monkeypatch.setattr(runtime_wrapper.time, "sleep", lambda seconds: events.append(f"sleep:{seconds:g}"))

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            events.append("write_observation")
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            events.append("update_from_manifest")
            return {"ok": True, "pose": {"schema": "specimen_pose.v1"}}

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            events.append("get_observation")
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = tracker.capture_once(FakeRobot(), send_action=lambda _robot, action: dict(action), current_action=None, reason="teleop")

    assert result["ok"] is True
    assert events == ["sleep:1", "get_observation", "write_observation", "update_from_manifest", "sleep:1"]


def test_active_robot_cam_pose_overrides_include_camera_specific_world_offset(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_X_MM", "10.0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_Y_MM", "-5.0")

    overrides = ActiveRobotCamTracker._pose_overrides_with_world_offset(
        ActiveRobotCamTracker.D405_DIRECT_OVERRIDES,
        "ATR_ACTIVE_ROBOT_CAM_D405",
    )

    assert overrides["a4_camera_to_isaac_transform"] == "direct"
    assert overrides["a4_world_offset_x_mm"] == 10.0
    assert overrides["a4_world_offset_y_mm"] == -5.0


def test_omx_observation_sidecar_uses_robot_camera_depth_scale(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "wrist")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", "0.001")
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_robots = types.ModuleType("lerobot.robots")
    fake_robots.__path__ = []
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_pkg.__path__ = []
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")

    class FakeDepthSensor:
        def get_depth_scale(self) -> float:
            return 0.0001

    class FakeDevice:
        def first_depth_sensor(self) -> FakeDepthSensor:
            return FakeDepthSensor()

    class FakeProfile:
        def get_device(self) -> FakeDevice:
            return FakeDevice()

    class FakeCamera:
        rs_profile = FakeProfile()

    class OmxFollower:
        cameras = {"wrist": FakeCamera()}

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    fake_omx_module.OmxFollower = OmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    sidecar = LatestFrameSidecar()
    patch_omx_observation(sidecar)
    OmxFollower().get_observation()
    assert sidecar.flush(timeout_s=1.0) is True

    manifest = json.loads((root / "latest_frame.json").read_text(encoding="utf-8"))
    assert manifest["depth_scale_m_per_unit"] == 0.0001


def test_active_robot_cam_uses_d405_direct_then_resumes_to_current_teleop_action(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(
        json.dumps(
            {
                "present_position_lerobot": {
                    "shoulder_pan.pos": 10.0,
                    "shoulder_lift.pos": -20.0,
                    "elbow_flex.pos": 30.0,
                    "wrist_flex.pos": 40.0,
                    "wrist_roll.pos": 5.0,
                    "gripper.pos": 60.0,
                }
            }
        ),
        encoding="utf-8",
    )
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            assert "wrist" in observation
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            self.calls.append({"manifest_path": manifest_path, "reason": reason, "overrides": pose_payload_overrides or {}})
            return {"ok": True, "pose": {"schema": "specimen_pose.v1"}}

    class FakeBus:
        def sync_read(self, register: str):
            assert register == "Present_Position"
            return {
                "shoulder_pan": 0.0,
                "shoulder_lift": 0.0,
                "elbow_flex": 0.0,
                "wrist_flex": 0.0,
                "wrist_roll": 0.0,
                "gripper": 60.0,
            }

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    sent: list[dict[str, float]] = []

    def fake_send_action(_robot, action):
        sent.append(dict(action))
        return dict(action)

    updater = FakeUpdater()
    tracker = ActiveRobotCamTracker(FakeSidecar(), updater)  # type: ignore[arg-type]
    current_action = {"shoulder_pan.pos": 2.5, "shoulder_lift.pos": -1.0}

    result = tracker.capture_once(FakeRobot(), send_action=fake_send_action, current_action=current_action, reason="teleop")

    assert result["ok"] is True
    assert updater.calls[0]["reason"] == "active_robot_cam_d405"
    overrides = updater.calls[0]["overrides"]
    assert overrides["a4_camera_to_isaac_transform"] == "direct"  # type: ignore[index]
    assert overrides["a4_width_mm"] == 297.0  # type: ignore[index]
    assert overrides["a4_height_mm"] == 210.0  # type: ignore[index]
    assert any(action["shoulder_pan.pos"] == 10.0 for action in sent)
    assert sent[-1] == current_action


def test_active_robot_cam_returns_home_when_specimen_is_missing_during_teleop(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 10.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            return {"ok": False, "failure_code": "SPECIMEN_NOT_DETECTED"}

    class FakeBus:
        def sync_read(self, register: str):
            assert register == "Present_Position"
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    sent: list[dict[str, float]] = []
    current_action = {"shoulder_pan.pos": 99.0}
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = tracker.capture_once(
        FakeRobot(),
        send_action=lambda _robot, action: sent.append(dict(action)) or dict(action),
        current_action=current_action,
        reason="teleop",
    )

    assert result["ok"] is False
    assert result["failure_code"] == "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED"
    assert sent[-1] == {"shoulder_pan.pos": 0.0}
    assert result["resume_mode"] == "home_pose"
    assert tracker.held_action() == {}
    assert tracker.limit_teleop_action({"shoulder_pan.pos": 99.0}) == {"shoulder_pan.pos": 3.0}


def test_active_robot_cam_failure_overrides_explicit_current_resume_mode(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 10.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESUME_MODE", "current")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            return {"ok": False, "failure_code": "SPECIMEN_NOT_DETECTED"}

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    sent: list[dict[str, float]] = []
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = tracker.capture_once(
        FakeRobot(),
        send_action=lambda _robot, action: sent.append(dict(action)) or dict(action),
        current_action={"shoulder_pan.pos": 99.0},
        reason="teleop",
    )

    assert result["ok"] is False
    assert sent[-1] == {"shoulder_pan.pos": 0.0}
    assert result["resume_mode"] == "home_pose"


def test_omx_send_action_returns_to_teleop_after_failed_active_cam(monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_robots = types.ModuleType("lerobot.robots")
    fake_robots.__path__ = []
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_pkg.__path__ = []
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    sent: list[dict[str, float]] = []

    class OmxFollower:
        def send_action(self, action):
            sent.append(dict(action))
            return dict(action)

    fake_omx_module.OmxFollower = OmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    class FakeActiveRobotCam:
        enabled = True

        def __init__(self) -> None:
            self.capture_count = 0

        def consume_capture_request_reason(self) -> str:
            return ""

        def should_run_on_action(self) -> bool:
            return self.capture_count == 0

        def held_action(self) -> dict[str, float]:
            return {}

        def limit_teleop_action(self, target_action):
            return dict(target_action)

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            self.capture_count += 1
            home_action = {"shoulder_pan.pos": 0.0}
            send_action(robot, home_action)
            return {
                "ok": False,
                "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
                "resume_mode": "home_pose",
                "resume_action": home_action,
            }

    monkeypatch.delenv("ATR_ISAAC_MIRROR_ENABLED", raising=False)
    publisher = IsaacMirrorPublisher()
    active_cam = FakeActiveRobotCam()
    patch_omx_send_action(publisher, active_cam)  # type: ignore[arg-type]

    follower = OmxFollower()
    first_return = follower.send_action({"shoulder_pan.pos": 99.0})
    second_return = follower.send_action({"shoulder_pan.pos": 55.0})

    assert first_return == {"shoulder_pan.pos": 0.0}
    assert second_return == {"shoulder_pan.pos": 55.0}
    assert sent == [{"shoulder_pan.pos": 0.0}, {"shoulder_pan.pos": 55.0}]


def test_omx_send_action_clears_stale_hold_after_failed_active_cam(monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_robots = types.ModuleType("lerobot.robots")
    fake_robots.__path__ = []
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_pkg.__path__ = []
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    sent: list[dict[str, float]] = []

    class OmxFollower:
        def send_action(self, action):
            sent.append(dict(action))
            return dict(action)

    fake_omx_module.OmxFollower = OmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    class FakeActiveRobotCam:
        enabled = True

        def __init__(self) -> None:
            self.capture_count = 0
            self.clear_count = 0
            self._hold = {"shoulder_pan.pos": 0.0}

        def consume_capture_request_reason(self) -> str:
            return ""

        def should_run_on_action(self) -> bool:
            return self.capture_count == 0

        def held_action(self) -> dict[str, float]:
            return dict(self._hold)

        def clear_hold(self) -> None:
            self.clear_count += 1
            self._hold = {}

        def limit_teleop_action(self, target_action):
            return dict(target_action)

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            self.capture_count += 1
            home_action = {"shoulder_pan.pos": 0.0}
            send_action(robot, home_action)
            return {
                "ok": False,
                "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
                "resume_mode": "home_pose",
                "resume_action": home_action,
            }

    monkeypatch.delenv("ATR_ISAAC_MIRROR_ENABLED", raising=False)
    publisher = IsaacMirrorPublisher()
    active_cam = FakeActiveRobotCam()
    patch_omx_send_action(publisher, active_cam)  # type: ignore[arg-type]

    follower = OmxFollower()
    assert follower.send_action({"shoulder_pan.pos": 99.0}) == {"shoulder_pan.pos": 0.0}
    assert follower.send_action({"shoulder_pan.pos": 55.0}) == {"shoulder_pan.pos": 55.0}

    assert active_cam.clear_count == 1
    assert sent == [{"shoulder_pan.pos": 0.0}, {"shoulder_pan.pos": 55.0}]


def test_omx_send_action_mirrors_raw_leader_action_while_active_cam_holds_robot(monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_robots = types.ModuleType("lerobot.robots")
    fake_robots.__path__ = []
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_pkg.__path__ = []
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    sent: list[dict[str, float]] = []

    class OmxFollower:
        def send_action(self, action):
            sent.append(dict(action))
            return dict(action)

    fake_omx_module.OmxFollower = OmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    class FakeActiveRobotCam:
        enabled = True
        _active = False

        def consume_capture_request_reason(self) -> str:
            return ""

        def should_run_on_action(self) -> bool:
            return False

        def held_action(self) -> dict[str, float]:
            return {"shoulder_pan.pos": 3.0, "shoulder_lift.pos": -62.0}

        def limit_teleop_action(self, target_action):
            return dict(target_action)

    class FakePublisher:
        enabled = True
        source = "leader_action"

        def __init__(self) -> None:
            self.leader_actions: list[dict[str, float]] = []
            self.published: list[dict[str, float]] = []

        def should_publish(self) -> bool:
            return True

        def action_from_follower(self, follower, sent_action, *, leader_action=None):
            self.leader_actions.append(dict(leader_action or {}))
            return dict(leader_action or {}), "in_process_leader_action", "", {}

        def publish_action(self, action, *, source, source_error="", source_selection=None) -> None:
            self.published.append(dict(action))

    publisher = FakePublisher()
    patch_omx_send_action(publisher, FakeActiveRobotCam())  # type: ignore[arg-type]

    follower = OmxFollower()
    returned = follower.send_action({"shoulder_pan.pos": 9.0, "shoulder_lift.pos": -67.0})

    assert returned == {"shoulder_pan.pos": 3.0, "shoulder_lift.pos": -62.0}
    assert sent == [{"shoulder_pan.pos": 3.0, "shoulder_lift.pos": -62.0}]
    assert publisher.leader_actions == [{"shoulder_pan.pos": 9.0, "shoulder_lift.pos": -67.0}]
    assert publisher.published == [{"shoulder_pan.pos": 9.0, "shoulder_lift.pos": -67.0}]


def test_omx_send_action_limits_joint_delta_when_returning_to_teleop(tmp_path: Path, monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_robots = types.ModuleType("lerobot.robots")
    fake_robots.__path__ = []
    fake_omx_pkg = types.ModuleType("lerobot.robots.omx_follower")
    fake_omx_pkg.__path__ = []
    fake_omx_module = types.ModuleType("lerobot.robots.omx_follower.omx_follower")
    sent: list[dict[str, float]] = []

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class OmxFollower:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

        def send_action(self, action):
            sent.append(dict(action))
            return dict(action)

    fake_omx_module.OmxFollower = OmxFollower
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.robots", fake_robots)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", fake_omx_pkg)
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower.omx_follower", fake_omx_module)

    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_TELEOP_TRANSITION_MAX_STEP", "3")
    monkeypatch.delenv("ATR_ISAAC_MIRROR_ENABLED", raising=False)

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            return {"ok": True, "pose": {"schema": "specimen_pose.v1"}}

    publisher = IsaacMirrorPublisher()
    active_cam = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]
    patch_omx_send_action(publisher, active_cam)

    follower = OmxFollower()
    first_return = follower.send_action({"shoulder_pan.pos": 10.0})
    second_return = follower.send_action({"shoulder_pan.pos": 25.0})

    assert first_return == {"shoulder_pan.pos": 10.0}
    assert second_return == {"shoulder_pan.pos": 13.0}
    assert sent[-1] == {"shoulder_pan.pos": 13.0}


def test_active_robot_cam_returns_home_when_pose_update_raises(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 10.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            raise RuntimeError("detector crashed")

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    sent: list[dict[str, float]] = []
    tracker = ActiveRobotCamTracker(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = tracker.capture_once(
        FakeRobot(),
        send_action=lambda _robot, action: sent.append(dict(action)) or dict(action),
        current_action={"shoulder_pan.pos": 99.0},
        reason="teleop",
    )

    assert result["ok"] is False
    assert result["failure_code"] == "ACTIVE_ROBOT_CAM_ERROR"
    assert sent[-1] == {"shoulder_pan.pos": 0.0}
    assert tracker.held_action() == {}
    assert tracker.limit_teleop_action({"shoulder_pan.pos": 99.0}) == {"shoulder_pan.pos": 3.0}


def test_active_robot_cam_uses_d405_sdk_depth_scale_for_latest_frame(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 10.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "wrist")
    monkeypatch.setenv("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", "0.001")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")

    class FakeDepthSensor:
        def get_depth_scale(self) -> float:
            return 0.0001

    class FakeDevice:
        def first_depth_sensor(self) -> FakeDepthSensor:
            return FakeDepthSensor()

    class FakeProfile:
        def get_device(self) -> FakeDevice:
            return FakeDevice()

    class FakeCamera:
        rs_profile = FakeProfile()

    class FakeUpdater:
        def __init__(self) -> None:
            self.manifest_path: Path | None = None

        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            self.manifest_path = manifest_path
            return {"ok": True, "pose": {"schema": "specimen_pose.v1"}}

    class FakeBus:
        def sync_read(self, register: str):
            assert register == "Present_Position"
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()
        cameras = {"wrist": FakeCamera()}

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    updater = FakeUpdater()
    sidecar = LatestFrameSidecar()
    tracker = ActiveRobotCamTracker(sidecar, updater)  # type: ignore[arg-type]

    result = tracker.capture_once(FakeRobot(), send_action=lambda _robot, action: dict(action), current_action=None, reason="standalone")

    assert result["ok"] is True
    assert updater.manifest_path == root / "latest_frame.json"
    manifest = json.loads((root / "latest_frame.json").read_text(encoding="utf-8"))
    assert manifest["depth_scale_m_per_unit"] == 0.0001


def test_active_robot_cam_falls_back_to_d455f_right_plane_when_d405_fails(tmp_path: Path, monkeypatch) -> None:
    capture_pose = tmp_path / "capture.json"
    home_pose = tmp_path / "home.json"
    fallback_manifest = tmp_path / "d455f_latest.json"
    capture_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 10.0}}), encoding="utf-8")
    home_pose.write_text(json.dumps({"present_position_lerobot": {"shoulder_pan.pos": 0.0}}), encoding="utf-8")
    fallback_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_ENABLED", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_CAPTURE_POSE_PATH", str(capture_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_HOME_POSE_PATH", str(home_pose))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_D455F_MANIFEST_PATH", str(fallback_manifest))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_RESULT_DIR", str(tmp_path / "active_cam_result"))
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_MIN_STEPS", "1")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_STEP_SLEEP_S", "0")
    monkeypatch.setenv("ATR_ACTIVE_ROBOT_CAM_SETTLE_S", "0")

    class FakeSidecar:
        camera_key = "wrist"
        root = tmp_path

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            path = tmp_path / f"{reason}.json"
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def update_from_manifest(self, manifest_path: Path, *, reason: str, pose_payload_overrides=None) -> dict[str, object]:
            self.calls.append({"manifest_path": manifest_path, "reason": reason, "overrides": pose_payload_overrides or {}})
            return {"ok": len(self.calls) > 1}

    class FakeBus:
        def sync_read(self, register: str):
            return {"shoulder_pan": 0.0}

    class FakeRobot:
        bus = FakeBus()

        def get_observation(self):
            return {"wrist": np.zeros((8, 8, 3), dtype=np.uint8)}

    updater = FakeUpdater()
    tracker = ActiveRobotCamTracker(FakeSidecar(), updater)  # type: ignore[arg-type]

    result = tracker.capture_once(FakeRobot(), send_action=lambda _robot, action: dict(action), current_action=None, reason="standalone")

    assert result["ok"] is True
    assert [call["reason"] for call in updater.calls] == ["active_robot_cam_d405", "active_robot_cam_d455f_fallback"]
    assert updater.calls[1]["manifest_path"] == fallback_manifest
    overrides = updater.calls[1]["overrides"]
    assert overrides["a4_camera_to_isaac_transform"] == "robot_right_plane"  # type: ignore[index]
    assert overrides["a4_width_mm"] == 210.0  # type: ignore[index]
    assert overrides["a4_height_mm"] == 297.0  # type: ignore[index]


def test_record_loop_patch_captures_one_frame_before_dataset_episode(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    calls: list[str] = []

    def _original_record_loop(*args, **kwargs):
        calls.append("original")
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeUpdater:
        enabled = True

        def __init__(self) -> None:
            self.manifests: list[Path] = []

        def update_from_manifest(self, manifest_path: Path, *, reason: str) -> dict[str, object]:
            self.manifests.append(manifest_path)
            return {"ok": True, "reason": reason}

    class FakeRobot:
        def get_observation(self) -> dict[str, np.ndarray]:
            calls.append("observation")
            color = np.zeros((24, 32, 3), dtype=np.uint8)
            color[10:14, 12:16] = (255, 0, 0)
            return {"top": color}

    sidecar = LatestFrameSidecar()
    updater = FakeUpdater()
    patch_record_loop(sidecar, updater)  # type: ignore[arg-type]

    result = fake_record.record_loop(robot=FakeRobot(), dataset=object(), events={}, fps=15)

    assert result == "recorded"
    assert calls == ["observation", "original"]
    assert updater.manifests == [root / "latest_frame.json"]
    assert (root / "record_start_specimen_pose_result.json").is_file()


def test_record_loop_patch_scopes_active_cam_and_render_to_each_episode_before_recording(tmp_path: Path, monkeypatch) -> None:
    dataset_root = tmp_path / "dataset"
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ENABLED", "1")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_DATASET_PATH", str(dataset_root))
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_SESSION_ID", "lr-record-episode-scope")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_ID", "attempt_scope")
    monkeypatch.setenv("ATR_RECORD_ATTEMPT_EPISODE_INDEX", "0")
    monkeypatch.setenv("ATR_ISAAC_RGBD_RENDER_ENABLED", "1")
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []

    class FakeDataset:
        def __init__(self) -> None:
            self.num_episodes = 0

    dataset = FakeDataset()

    def _original_record_loop(*args, **kwargs):
        events.append(f"record:{kwargs['dataset'].num_episodes}")
        kwargs["dataset"].num_episodes += 1
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeActiveRobotCam:
        enabled = True
        record_start_enabled = True

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            events.append(f"capture:{robot.num_episodes_seen}:{reason}:force={force}")
            return {
                "ok": True,
                "snapshot": {
                    "pose": {
                        "position_isaac_world_mm": {
                            "x": float(robot.num_episodes_seen),
                            "y": 0.0,
                            "z": 0.0,
                        }
                    }
                },
            }

    class FakeRobot:
        def __init__(self, source_dataset: FakeDataset) -> None:
            self.source_dataset = source_dataset
            self.num_episodes_seen = 0

        def sync_episode_index(self) -> None:
            self.num_episodes_seen = self.source_dataset.num_episodes

    robot = FakeRobot(dataset)

    class FakeSidecar:
        enabled = True
        root = tmp_path / "latest_frame"

    class FakeUpdater:
        enabled = True

    attempt_sidecar = RecordAttemptSidecar()
    patch_record_loop(FakeSidecar(), FakeUpdater(), FakeActiveRobotCam(), attempt_sidecar)  # type: ignore[arg-type]

    robot.sync_episode_index()
    assert fake_record.record_loop(robot=robot, dataset=dataset, events={}, fps=15) == "recorded"
    robot.sync_episode_index()
    assert fake_record.record_loop(robot=robot, dataset=dataset, events={}, fps=15) == "recorded"

    assert events == ["capture:0:record_start:force=True", "record:0", "capture:1:record_start:force=True", "record:1"]
    first_attempt = dataset_root / "sidecar" / "attempts" / "episode_000" / "attempt_scope_ep000"
    second_attempt = dataset_root / "sidecar" / "attempts" / "episode_001" / "attempt_scope_ep001"
    assert (first_attempt / "active_cam_result.json").is_file()
    assert (second_attempt / "active_cam_result.json").is_file()
    assert json.loads((second_attempt / "status.json").read_text(encoding="utf-8"))["isaac_rgbd_render_output_dir"].endswith(
        "sidecar/isaac_rgbd/episode_001/attempt_scope_ep001"
    )


def test_record_loop_patch_waits_for_active_cam_return_to_teleop_pose_before_recording(tmp_path: Path, monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []
    captured_current_action: dict[str, float] = {}

    def _original_record_loop(*args, **kwargs):
        events.append("record")
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeActiveRobotCam:
        enabled = True
        record_start_enabled = True

        def present_action(self, robot):
            events.append("present")
            return {"shoulder_pan.pos": 17.0}

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            events.append(f"capture:{reason}")
            captured_current_action.update(dict(current_action))
            return {"ok": True, "status": "applied", "resume_action": dict(current_action)}

        def wait_until_action_reached(self, robot, target_action, *, reason):
            events.append(f"wait:{reason}")
            assert target_action == {"shoulder_pan.pos": 17.0}
            return {"ok": True, "status": "reached", "target_action": dict(target_action)}

    class FakeSidecar:
        enabled = True
        root = tmp_path / "latest_frame"

    class FakeUpdater:
        enabled = True

    patch_record_loop(FakeSidecar(), FakeUpdater(), FakeActiveRobotCam())  # type: ignore[arg-type]

    result = fake_record.record_loop(robot=object(), dataset=object(), events={}, fps=15)

    assert result == "recorded"
    assert captured_current_action == {"shoulder_pan.pos": 17.0}
    assert events == ["present", "capture:record_start", "wait:record_start", "record"]


def test_record_loop_patch_blocks_when_active_cam_return_pose_is_not_reached(tmp_path: Path, monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []

    def _original_record_loop(*args, **kwargs):
        events.append("record")
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeActiveRobotCam:
        enabled = True
        record_start_enabled = True

        def present_action(self, robot):
            events.append("present")
            return {"shoulder_pan.pos": 17.0}

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            events.append(f"capture:{reason}")
            return {"ok": True, "status": "applied", "resume_action": dict(current_action)}

        def wait_until_action_reached(self, robot, target_action, *, reason):
            events.append(f"wait:{reason}")
            return {
                "ok": False,
                "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
                "target_action": dict(target_action),
            }

    class FakeSidecar:
        enabled = True
        root = tmp_path / "latest_frame"

    class FakeUpdater:
        enabled = True

    patch_record_loop(FakeSidecar(), FakeUpdater(), FakeActiveRobotCam())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED"):
        fake_record.record_loop(robot=object(), dataset=object(), events={}, fps=15)

    assert events == ["present", "capture:record_start", "wait:record_start"]
    assert (tmp_path / "latest_frame" / "record_start_specimen_pose_result.json").is_file()


def test_record_loop_patch_does_not_start_episode_when_active_cam_fails(tmp_path: Path, monkeypatch) -> None:
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []

    def _original_record_loop(*args, **kwargs):
        events.append("record")
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeActiveRobotCam:
        enabled = True
        record_start_enabled = True

        def capture_once(self, robot, *, send_action, current_action, reason, force=False):
            events.append(f"capture:{reason}")
            return {
                "ok": False,
                "status": "failed",
                "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
                "resume_mode": "home_pose",
                "resume_action": {"shoulder_pan.pos": 0.0},
            }

    class FakeSidecar:
        enabled = True
        root = tmp_path / "latest_frame"

    class FakeUpdater:
        enabled = True

    patch_record_loop(FakeSidecar(), FakeUpdater(), FakeActiveRobotCam())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED"):
        fake_record.record_loop(robot=object(), dataset=object(), events={}, fps=15)

    assert events == ["capture:record_start"]
    assert (tmp_path / "latest_frame" / "record_start_specimen_pose_result.json").is_file()


def test_record_loop_patch_warns_when_passive_specimen_pose_fails(tmp_path: Path, monkeypatch) -> None:
    sidecar_root = tmp_path / "latest_frame"
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []

    def _original_record_loop(*args, **kwargs):
        events.append("record")
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeSidecar:
        enabled = True

        def __init__(self) -> None:
            self.root = sidecar_root

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            events.append("write_observation")
            path = sidecar_root / "latest_frame.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        enabled = True

        def update_from_manifest(self, manifest_path: Path, *, reason: str) -> dict[str, object]:
            events.append("update_pose")
            return {"ok": False, "failure_code": "SPECIMEN_OUTSIDE_A4", "message": "outside"}

    class FakeRobot:
        def get_observation(self):
            events.append("observation")
            return {"top": np.zeros((8, 8, 3), dtype=np.uint8)}

    patch_record_loop(FakeSidecar(), FakeUpdater())  # type: ignore[arg-type]

    result = fake_record.record_loop(robot=FakeRobot(), dataset=object(), events={}, fps=15)

    assert result == "recorded"
    assert events == ["observation", "write_observation", "update_pose", "record"]
    result_path = sidecar_root / "record_start_specimen_pose_result.json"
    assert result_path.is_file()
    saved_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved_result["ok"] is False
    assert saved_result["warning_only"] is True
    assert saved_result["failure_code"] == "SPECIMEN_OUTSIDE_A4"


def test_record_loop_patch_suppresses_first_action_active_cam_inside_recording(tmp_path: Path, monkeypatch) -> None:
    sidecar_root = tmp_path / "latest_frame"
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    events: list[str] = []

    def _original_record_loop(*args, **kwargs):
        events.append("record")
        assert kwargs["active_cam"].suppressed is True
        return "recorded"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeActiveRobotCam:
        enabled = True
        record_start_enabled = False

        def __init__(self) -> None:
            self.suppressed = False

        def suppress_first_action_capture(self) -> None:
            events.append("suppress_first_action")
            self.suppressed = True

    class FakeSidecar:
        enabled = True

        def __init__(self) -> None:
            self.root = sidecar_root

        def write_observation(self, observation, *, force=False, reason="latest", depth_scale_m_per_unit=None):
            events.append("write_observation")
            path = sidecar_root / "latest_frame.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            return path

    class FakeUpdater:
        enabled = True

        def update_from_manifest(self, manifest_path: Path, *, reason: str) -> dict[str, object]:
            events.append("update_pose")
            return {"ok": True}

    class FakeRobot:
        def get_observation(self):
            events.append("observation")
            return {"top": np.zeros((8, 8, 3), dtype=np.uint8)}

    active_cam = FakeActiveRobotCam()
    patch_record_loop(FakeSidecar(), FakeUpdater(), active_cam)  # type: ignore[arg-type]

    result = fake_record.record_loop(robot=FakeRobot(), dataset=object(), events={}, fps=15, active_cam=active_cam)

    assert result == "recorded"
    assert events == ["suppress_first_action", "observation", "write_observation", "update_pose", "record"]


def test_record_loop_patch_skips_processor_positional_reset_loop_without_dataset(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    calls: list[str] = []

    def _original_record_loop(
        robot,
        events,
        fps,
        teleop_action_processor,
        robot_action_processor,
        robot_observation_processor,
        dataset=None,
        **kwargs,
    ):
        calls.append("original")
        return "reset"

    fake_record.record_loop = _original_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeUpdater:
        enabled = True

        def update_from_manifest(self, manifest_path: Path, *, reason: str) -> dict[str, object]:
            calls.append("update")
            return {"ok": True}

    class FakeRobot:
        def get_observation(self) -> dict[str, np.ndarray]:
            calls.append("observation")
            return {"top": np.zeros((24, 32, 3), dtype=np.uint8)}

    sidecar = LatestFrameSidecar()
    patch_record_loop(sidecar, FakeUpdater())  # type: ignore[arg-type]

    result = fake_record.record_loop(
        FakeRobot(),
        {},
        15,
        object(),
        object(),
        object(),
        control_time_s=1,
    )

    assert result == "reset"
    assert calls == ["original"]
    assert not (root / "record_start_specimen_pose_result.json").exists()


def test_record_loop_patch_handles_decorated_legacy_positional_dataset(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "latest_frame"
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_ENABLED", "1")
    monkeypatch.setenv("ATR_LEROBOT_LATEST_FRAME_DIR", str(root))
    monkeypatch.setenv("ATR_LEROBOT_SPECIMEN_CAMERA_KEY", "top")
    fake_lerobot = types.ModuleType("lerobot")
    fake_lerobot.__path__ = []
    fake_record = types.ModuleType("lerobot.record")
    calls: list[str] = []

    def _decorated_record_loop(*args, **kwargs):
        calls.append("original")
        return "recorded"

    fake_record.record_loop = _decorated_record_loop
    monkeypatch.setitem(sys.modules, "lerobot", fake_lerobot)
    monkeypatch.setitem(sys.modules, "lerobot.record", fake_record)

    class FakeUpdater:
        enabled = True

        def __init__(self) -> None:
            self.manifests: list[Path] = []

        def update_from_manifest(self, manifest_path: Path, *, reason: str) -> dict[str, object]:
            self.manifests.append(manifest_path)
            calls.append("update")
            return {"ok": True, "reason": reason}

    class FakeRobot:
        def get_observation(self) -> dict[str, np.ndarray]:
            calls.append("observation")
            return {"top": np.zeros((24, 32, 3), dtype=np.uint8)}

    sidecar = LatestFrameSidecar()
    updater = FakeUpdater()
    patch_record_loop(sidecar, updater)  # type: ignore[arg-type]

    result = fake_record.record_loop(FakeRobot(), {}, 15, object())

    assert result == "recorded"
    assert calls == ["observation", "update", "original"]
    assert updater.manifests == [root / "latest_frame.json"]
