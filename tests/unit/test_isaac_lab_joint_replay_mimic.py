from __future__ import annotations

import json
import sys
import threading
import types
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def _write_source_hdf5(path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    path.parent.mkdir(parents=True, exist_ok=True)
    env_args = {"env_name": "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0", "type": 2, "env_kwargs": {}}
    actions = np.asarray(
        [
            [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, -0.50],
            [0.1, 0.11, 0.21, 0.31, 0.41, 0.51, -0.51],
            [0.2, 0.12, 0.22, 0.32, 0.42, 0.52, -0.52],
            [0.3, 0.13, 0.23, 0.33, 0.43, 0.53, -0.53],
            [0.4, 0.14, 0.24, 0.34, 0.44, 0.54, -0.54],
            [0.5, 0.15, 0.25, 0.35, 0.45, 0.55, -0.55],
        ],
        dtype=np.float32,
    )
    states = actions + np.float32(1.0)
    pose = np.eye(4, dtype=np.float32)[None, :, :].repeat(actions.shape[0], axis=0)
    signals = {
        "approach": np.asarray([[False], [False], [True], [True], [True], [True]], dtype=np.bool_),
        "grasp": np.asarray([[False], [False], [False], [True], [True], [True]], dtype=np.bool_),
        "lift": np.asarray([[False], [False], [False], [False], [True], [True]], dtype=np.bool_),
        "place": np.asarray([[False], [False], [False], [False], [False], [True]], dtype=np.bool_),
    }
    with h5py.File(path, "w") as handle:
        handle.attrs["env_args"] = json.dumps(env_args)
        handle.attrs["total"] = int(actions.shape[0])
        data = handle.create_group("data")
        data.attrs["env_args"] = json.dumps(env_args)
        data.attrs["total"] = int(actions.shape[0])
        demo = data.create_group("demo_000000")
        demo.attrs["num_samples"] = int(actions.shape[0])
        demo.attrs["success"] = True
        initial = demo.create_group("initial_state")
        robot = initial.create_group("articulation").create_group("robot")
        robot.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        robot.create_dataset("joint_position", data=actions[:1])
        robot.create_dataset("joint_velocity", data=np.zeros((1, 7), dtype=np.float32))
        cube = initial.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        cube.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        demo.create_dataset("actions", data=actions)
        demo.create_dataset("states", data=states)
        demo.create_dataset("timestamps", data=np.arange(actions.shape[0], dtype=np.float32) / 15.0)
        obs = demo.create_group("obs")
        obs.create_dataset("joint_pos", data=actions)
        obs.create_dataset("robot_state", data=states)
        obs.create_dataset("gripper_state", data=actions[:, -1:])
        obs.create_dataset("eef_pose", data=pose)
        obs.create_dataset("object_pose", data=pose)
        datagen = obs.create_group("datagen_info")
        datagen.create_group("object_pose").create_dataset("red_cube", data=pose)
        datagen.create_group("eef_pose").create_dataset("omx", data=pose)
        datagen.create_group("target_eef_pose").create_dataset("omx", data=pose)
        signal_group = datagen.create_group("subtask_term_signals")
        for name, values in signals.items():
            signal_group.create_dataset(name, data=values)


def test_joint_replay_mimic_writes_trainable_joint_position_hdf5(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    source = tmp_path / "source_real_success_annotated.hdf5"
    output = tmp_path / "mimic" / "generated_dataset.hdf5"
    successes = tmp_path / "mimic" / "successes.jsonl"
    failures = tmp_path / "mimic" / "failures.jsonl"
    _write_source_hdf5(source)

    summary = generate_joint_replay_mimic_dataset(
        input_path=source,
        output_path=output,
        success_manifest_path=successes,
        failure_manifest_path=failures,
        trials=2,
        seed=7,
        env_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
    )

    assert summary["ok"] is True
    assert summary["backend"] == "joint_replay"
    assert summary["success_count"] == 2
    assert output.is_file()
    success_rows = [json.loads(line) for line in successes.read_text(encoding="utf-8").splitlines()]
    assert len(success_rows) == 2
    assert success_rows[0]["training"]["eligible"] is True
    assert success_rows[0]["artifacts"]["hdf5_path"] == "mimic/generated_dataset.hdf5"
    assert failures.read_text(encoding="utf-8") == ""
    with h5py.File(output, "r") as handle:
        assert json.loads(handle.attrs["env_args"])["env_name"] == "ATR-Robotis-OMX-PickPlace-Physical-State-v0"
        demo = handle["data"]["demo_000000"]
        assert demo.attrs["success"] == np.bool_(True)
        assert demo.attrs["generator"] == "isaac_lab_mimic_joint_replay"
        assert demo["actions"].dtype == np.dtype("float32")
        assert demo["actions"].shape[1] == 7
        np.testing.assert_allclose(demo["actions"][:], handle["data"]["demo_000001"]["actions"][:])
        np.testing.assert_allclose(demo["obs"]["joint_pos"][:], demo["actions"][:])
        assert "datagen_info" in demo["obs"]


def test_joint_replay_rgbd_extractor_normalizes_camera_observations() -> None:
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _extract_rgbd_camera_frames

    obs = {
        "policy": {
            "top_rgb": np.asarray([[[[0.5, 0.25, 1.0], [0.0, 1.0, 0.0]]]], dtype=np.float32),
            "top_depth": np.asarray([[[[1.234], [0.25]]]], dtype=np.float32),
            "front_camera": {
                "rgb": np.asarray([[[10, 20], [30, 40]], [[50, 60], [70, 80]], [[90, 100], [110, 120]]], dtype=np.uint8),
                "distance_to_image_plane": np.asarray([[[0.001, 0.002], [0.003, 0.004]]], dtype=np.float32),
            },
        }
    }

    frames = _extract_rgbd_camera_frames(obs, ["top", "front", "right"])

    assert sorted(frames.keys()) == ["front", "top"]
    assert frames["top"]["rgb"].dtype == np.dtype("uint8")
    assert frames["top"]["rgb"].shape == (1, 2, 3)
    assert frames["top"]["rgb"][0, 0].tolist() == [128, 64, 255]
    assert frames["top"]["depth"].dtype == np.dtype("uint16")
    assert frames["top"]["depth"].shape == (1, 2)
    assert frames["top"]["depth"][0, 0] == 1234
    assert frames["front"]["rgb"].shape == (2, 2, 3)
    assert frames["front"]["depth"][1, 1] == 4


def test_joint_replay_rgbd_scene_camera_output_preferred_over_stale_observation() -> None:
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import (
        _extract_rgbd_camera_frames,
        _extract_rgbd_camera_frames_from_scene,
        _merge_rgbd_camera_frames,
    )

    stale_obs = {
        "policy": {
            "top_rgb": np.zeros((1, 2, 2, 3), dtype=np.uint8),
            "top_depth": np.ones((1, 2, 2, 1), dtype=np.float32),
        }
    }

    class FakeCameraData:
        output = {
            "rgb": np.full((1, 2, 2, 3), 200, dtype=np.uint8),
            "depth": np.full((1, 2, 2, 1), 0.25, dtype=np.float32),
        }

    class FakeCamera:
        def __init__(self) -> None:
            self.data = FakeCameraData()
            self.update_calls = 0
            self.update_dts: list[float] = []
            self.force_recompute_flags: list[bool] = []

        def update(self, dt: float, force_recompute: bool = False) -> None:
            self.update_calls += 1
            self.update_dts.append(float(dt))
            self.force_recompute_flags.append(bool(force_recompute))

    class FakeUnwrapped:
        def __init__(self) -> None:
            self.scene = {"top_cam": FakeCamera()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    env = FakeEnv()
    scene_frames = _extract_rgbd_camera_frames_from_scene(env, ["top"])
    obs_frames = _extract_rgbd_camera_frames(stale_obs, ["top"])
    frames = _merge_rgbd_camera_frames(scene_frames, obs_frames)

    assert env.unwrapped.scene["top_cam"].update_calls == 1
    assert env.unwrapped.scene["top_cam"].update_dts == [pytest.approx(1.0 / 15.0)]
    assert env.unwrapped.scene["top_cam"].force_recompute_flags == [True]
    assert frames["top"]["rgb"][0, 0].tolist() == [200, 200, 200]
    assert frames["top"]["depth"][0, 0] == 250


def test_joint_replay_rgbd_motion_audit_blocks_static_frames_when_actions_move() -> None:
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _rgb_motion_audit, _record_rgb_motion_samples

    samples = {"top": []}
    static_frame = {"top": {"rgb": np.zeros((2, 2, 3), dtype=np.uint8)}}
    for frame_index in (0, 2, 4):
        _record_rgb_motion_samples(samples, static_frame, frame_index=frame_index, cameras=["top"])

    audit = _rgb_motion_audit(
        demo_name="demo_0",
        actions=np.asarray([[0.0], [0.5], [1.0]], dtype=np.float32),
        samples_by_camera=samples,
    )

    assert audit["status"] == "blocked"
    assert audit["changed_camera_count"] == 0
    assert audit["cameras"]["top"]["unique_frame_hash_count"] == 1


def test_joint_replay_rgbd_motion_audit_ignores_tiny_render_noise_when_actions_move() -> None:
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _rgb_motion_audit, _record_rgb_motion_samples

    samples = {"top": []}
    for frame_index, pixel_value in enumerate((0, 32, 64)):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[frame_index, frame_index] = pixel_value
        _record_rgb_motion_samples(samples, {"top": {"rgb": frame}}, frame_index=frame_index, cameras=["top"])

    audit = _rgb_motion_audit(
        demo_name="demo_0",
        actions=np.asarray([[0.0], [0.5], [1.0]], dtype=np.float32),
        samples_by_camera=samples,
    )

    assert audit["status"] == "blocked"
    assert audit["changed_camera_count"] == 0
    assert audit["cameras"]["top"]["unique_frame_hash_count"] == 3
    assert audit["cameras"]["top"]["motion_delta_mean_max"] < 2.0


def test_joint_replay_rgbd_mirror_endpoint_reuses_sim_render_route() -> None:
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _mirror_render_endpoint

    assert _mirror_render_endpoint("http://127.0.0.1:8766/joints") == "http://127.0.0.1:8766/render"
    assert _mirror_render_endpoint("http://127.0.0.1:8766/render") == "http://127.0.0.1:8766/render"


def test_joint_replay_rgbd_mirror_joint_state_uses_lab_radians_and_omits_mimic_column() -> None:
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _mirror_joint_state_from_lab_action

    row = np.asarray([0.0, np.pi / 2.0, -np.pi / 2.0, np.pi, -np.pi, 0.25, -0.25], dtype=np.float32)

    joint_state = _mirror_joint_state_from_lab_action(row)

    assert [int(item["motor_id"]) for item in joint_state] == [11, 12, 13, 14, 15, 16]
    assert all("source_value" not in item for item in joint_state)
    assert all(item["source_value_is_isaac_target"] is True for item in joint_state)
    assert joint_state[1]["target_value"] == pytest.approx(90.0)
    assert joint_state[2]["target_value"] == pytest.approx(-90.0)
    assert joint_state[5]["target_value"] == pytest.approx(np.degrees(0.25))
    assert joint_state[5]["mimic_joint_path"].endswith("/Gripper_mimic")
    assert joint_state[5]["source_unit"] == "lab_action_rad"
    assert joint_state[5]["source_value_rad"] == pytest.approx(0.25)


def test_joint_replay_rgbd_specimen_pose_uses_hdf5_red_cube_root_pose(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _mirror_specimen_pose_from_hdf5_demo

    source = tmp_path / "source.hdf5"
    _write_source_hdf5(source)
    with h5py.File(source, "a") as handle:
        root_pose = handle["data"]["demo_000000"]["initial_state"]["rigid_object"]["red_cube"]["root_pose"]
        root_pose[...] = np.asarray([[0.417, 0.311, 0.0152, 1.0, 0.0, 0.0, 0.0]], dtype=np.float32)

    with h5py.File(source, "r") as handle:
        payload = _mirror_specimen_pose_from_hdf5_demo(handle["data"]["demo_000000"])

    assert payload["pose"]["position_isaac_world_mm"] == pytest.approx({"x": 417.0, "y": 311.0, "z": 15.2})
    assert payload["pose"]["source"] == "isaac_lab_mimic_hdf5_initial_state"


def test_joint_replay_rgbd_source_episode_lookup_uses_mimic_success_manifest(tmp_path: Path) -> None:
    from scripts.lerobot_isaac_lab_joint_replay_mimic import (
        _mimic_source_episode_index_by_demo,
        _source_episode_index_for_generated_demo,
    )

    dataset_path = tmp_path / "mimic" / "generated_dataset.hdf5"
    dataset_path.parent.mkdir(parents=True)
    (dataset_path.parent / "successes.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"generated_demo": "demo_4", "source_episode_index": 0}),
                json.dumps({"generated_demo": "demo_7", "source_episode_index": 0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    mapping = _mimic_source_episode_index_by_demo(dataset_path)

    assert mapping == {"demo_4": 0, "demo_7": 0}
    assert _source_episode_index_for_generated_demo(
        object(),
        demo_name="demo_4",
        source_episode_by_demo=mapping,
    ) == 0
    assert _source_episode_index_for_generated_demo(
        object(),
        demo_name="demo_8",
        source_episode_by_demo={},
    ) == 0


def test_joint_replay_rgbd_mirror_renderer_posts_actions_and_writes_hdf5_paths(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _render_generated_dataset_rgbd_via_mirror

    source = tmp_path / "mimic" / "generated_dataset.hdf5"
    output = tmp_path / "mimic_rgbd" / "generated_dataset_rgbd.hdf5"
    successes = tmp_path / "mimic_rgbd" / "successes.jsonl"
    failures = tmp_path / "mimic_rgbd" / "failures.jsonl"
    renders = tmp_path / "mimic_rgbd" / "renders"
    manifest = tmp_path / "mimic_rgbd" / "manifest.jsonl"
    _write_source_hdf5(source)
    posted_payloads: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(
                {
                    "ok": True,
                    "last_apply_result": {
                        "joint_readback": [
                            {
                                "target_value": 0.0,
                                "state_position": 0.0,
                                "target_minus_state": 0.0,
                                "state_velocity": 0.0,
                            }
                        ]
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if "render_request" not in payload:
                body = json.dumps({"ok": True, "status": "ok"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            posted_payloads.append(payload)
            request = payload["render_request"]
            frame_index = int(request["frame_index"])
            output_dir = Path(request["output_dir"])
            camera_dir = output_dir / "top"
            camera_dir.mkdir(parents=True, exist_ok=True)
            rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
            depth_path = camera_dir / f"frame_{frame_index:06d}_depth.png"
            rgb = np.full((4, 4, 3), frame_index * 40, dtype=np.uint8)
            depth = np.full((4, 4), 400 + frame_index, dtype=np.uint16)
            Image.fromarray(rgb).save(rgb_path)
            Image.fromarray(depth).save(depth_path)
            row = {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "status": "rendered",
                "attempt_id": request["attempt_id"],
                "episode_index": request["episode_index"],
                "frame_index": frame_index,
                "sample_index": request["sample_index"],
                "files": [
                    {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
                    {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
                ],
            }
            with (output_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            body = json.dumps({"ok": True, "status": "rendered", "render_request": row}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        summary = _render_generated_dataset_rgbd_via_mirror(
            dataset_path=source,
            output_path=output,
            success_manifest_path=successes,
            failure_manifest_path=failures,
            render_output_dir=renders,
            render_manifest_path=manifest,
            cameras=["top"],
            camera_width=4,
            camera_height=4,
            fps=0,
            max_demos=1,
            mirror_endpoint=f"http://127.0.0.1:{server.server_port}/joints",
            mirror_timeout_s=0.5,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2.0)

    assert summary["ok"] is True
    assert summary["backend"] == "isaac_sim_mirror_http"
    assert len(posted_payloads) == 6
    assert "specimen_pose" in posted_payloads[0]
    assert "specimen_pose" not in posted_payloads[1]
    assert len(posted_payloads[0]["joint_state"]) == 6
    assert all(item["source_unit"] == "lab_action_rad" for item in posted_payloads[0]["joint_state"])
    assert all("source_value" not in item for item in posted_payloads[0]["joint_state"])
    assert posted_payloads[0]["render_request"]["render_source"] == "isaac_sim_mirror_http"
    assert successes.read_text(encoding="utf-8").strip()
    assert failures.read_text(encoding="utf-8") == ""
    with h5py.File(output, "r") as handle:
        obs = handle["data"]["demo_000000"]["obs"]
        assert obs["top_rgb_path"].shape == (6,)
        first_rgb_path = Path(obs["top_rgb_path"][0].decode("utf-8"))
        last_depth_path = Path(obs["top_depth_path"][5].decode("utf-8"))
        assert first_rgb_path.is_file()
        assert last_depth_path.is_file()
        assert ".render_staging" not in first_rgb_path.parts
        assert first_rgb_path.is_relative_to(renders)
    demo_manifest = renders / "demo_000000" / "manifest.jsonl"
    assert demo_manifest.is_file()
    assert ".render_staging" not in demo_manifest.read_text(encoding="utf-8")


def test_joint_replay_rgbd_mirror_renderer_preserves_existing_outputs_on_failed_render(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _render_generated_dataset_rgbd_via_mirror

    source = tmp_path / "mimic" / "generated_dataset.hdf5"
    output = tmp_path / "mimic_rgbd" / "generated_dataset_rgbd.hdf5"
    successes = tmp_path / "mimic_rgbd" / "successes.jsonl"
    failures = tmp_path / "mimic_rgbd" / "failures.jsonl"
    renders = tmp_path / "mimic_rgbd" / "renders"
    manifest = tmp_path / "mimic_rgbd" / "manifest.jsonl"
    _write_source_hdf5(source)
    renders.mkdir(parents=True)
    preserved_frame = renders / "demo_000000" / "top" / "frame_000000_rgb.png"
    preserved_frame.parent.mkdir(parents=True)
    preserved_frame.write_text("old-frame", encoding="utf-8")
    successes.parent.mkdir(parents=True, exist_ok=True)
    successes.write_text('{"old": true}\n', encoding="utf-8")
    failures.write_text("", encoding="utf-8")
    manifest.write_text('{"old_manifest": true}\n', encoding="utf-8")
    with h5py.File(output, "w") as handle:
        handle.attrs["old_output"] = 1

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(
                {
                    "ok": True,
                    "last_apply_result": {
                        "joint_readback": [
                            {
                                "target_value": 0.0,
                                "state_position": 0.0,
                                "target_minus_state": 0.0,
                                "state_velocity": 0.0,
                            }
                        ]
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            status = "post_failed" if "render_request" in payload else "ok"
            body = json.dumps({"ok": status == "ok", "status": status}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        summary = _render_generated_dataset_rgbd_via_mirror(
            dataset_path=source,
            output_path=output,
            success_manifest_path=successes,
            failure_manifest_path=failures,
            render_output_dir=renders,
            render_manifest_path=manifest,
            cameras=["top"],
            camera_width=4,
            camera_height=4,
            fps=0,
            max_demos=1,
            mirror_endpoint=f"http://127.0.0.1:{server.server_port}/joints",
            mirror_timeout_s=0.1,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2.0)

    assert summary["ok"] is False
    assert preserved_frame.read_text(encoding="utf-8") == "old-frame"
    assert successes.read_text(encoding="utf-8") == '{"old": true}\n'
    assert manifest.read_text(encoding="utf-8") == '{"old_manifest": true}\n'
    with h5py.File(output, "r") as handle:
        assert int(handle.attrs["old_output"]) == 1
    assert not (tmp_path / "mimic_rgbd" / ".render_staging").exists()


def test_joint_replay_rgbd_mirror_renderer_preplays_first_frame_before_render(tmp_path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")

    from scripts.lerobot_isaac_lab_joint_replay_mimic import _render_generated_dataset_rgbd_via_mirror

    source = tmp_path / "mimic" / "generated_dataset.hdf5"
    output = tmp_path / "mimic_rgbd" / "generated_dataset_rgbd.hdf5"
    successes = tmp_path / "mimic_rgbd" / "successes.jsonl"
    failures = tmp_path / "mimic_rgbd" / "failures.jsonl"
    renders = tmp_path / "mimic_rgbd" / "renders"
    manifest = tmp_path / "mimic_rgbd" / "manifest.jsonl"
    _write_source_hdf5(source)
    calls: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            calls.append({"method": "GET", "path": self.path})
            body = json.dumps(
                {
                    "ok": True,
                    "sample_count": 1,
                    "last_apply_result": {
                        "joint_readback": [
                            {
                                "motor_id": 12,
                                "target_value": 10.0,
                                "state_position": 9.8,
                                "target_minus_state": 0.2,
                                "state_velocity": 0.4,
                            }
                        ]
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            calls.append({"method": "POST", "path": self.path, "payload": payload})
            if self.path == "/render":
                request = payload["render_request"]
                frame_index = int(request["frame_index"])
                output_dir = Path(request["output_dir"])
                camera_dir = output_dir / "top"
                camera_dir.mkdir(parents=True, exist_ok=True)
                rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
                depth_path = camera_dir / f"frame_{frame_index:06d}_depth.png"
                Image.fromarray(np.full((4, 4, 3), frame_index * 40, dtype=np.uint8)).save(rgb_path)
                Image.fromarray(np.full((4, 4), 400 + frame_index, dtype=np.uint16)).save(depth_path)
                row = {
                    "schema": "atr.isaac_rgbd.render_manifest.v1",
                    "status": "rendered",
                    "attempt_id": request["attempt_id"],
                    "episode_index": request["episode_index"],
                    "frame_index": frame_index,
                    "sample_index": request["sample_index"],
                    "files": [
                        {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
                        {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
                    ],
                }
                with (output_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")
                body = json.dumps({"ok": True, "status": "rendered", "render_request": row}).encode("utf-8")
            else:
                body = json.dumps({"ok": True, "status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        summary = _render_generated_dataset_rgbd_via_mirror(
            dataset_path=source,
            output_path=output,
            success_manifest_path=successes,
            failure_manifest_path=failures,
            render_output_dir=renders,
            render_manifest_path=manifest,
            cameras=["top"],
            camera_width=4,
            camera_height=4,
            fps=0,
            max_demos=1,
            mirror_endpoint=f"http://127.0.0.1:{server.server_port}/render",
            mirror_timeout_s=0.5,
            mirror_settle_timeout_s=0.5,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2.0)

    assert summary["ok"] is True
    assert summary["preplay_count"] == 1
    assert summary["last_preplay"]["status"] == "preplay_stable"
    post_paths = [call["path"] for call in calls if call["method"] == "POST"]
    assert post_paths[:4] == ["/timeline/stop", "/specimen_pose", "/timeline/play", "/joints"]
    assert post_paths[4] == "/render"
    preplay_joint_payload = calls[3]["payload"]
    assert "render_request" not in preplay_joint_payload
    assert preplay_joint_payload["joint_state"]
    first_render_payload = calls[4]["payload"]
    assert first_render_payload["render_request"]["frame_index"] == 0


def test_joint_replay_mimic_expands_all_source_demos_by_domain_variants_and_trials(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    source = tmp_path / "source_real_success_annotated.hdf5"
    output = tmp_path / "mimic" / "generated_dataset.hdf5"
    successes = tmp_path / "mimic" / "successes.jsonl"
    failures = tmp_path / "mimic" / "failures.jsonl"
    _write_source_hdf5(source)
    with h5py.File(source, "a") as handle:
        source_demo = handle["data"]["demo_000000"]
        handle["data"].copy(source_demo, "demo_000001")
        copied = handle["data"]["demo_000001"]
        copied.attrs["episode_index"] = 1

    summary = generate_joint_replay_mimic_dataset(
        input_path=source,
        output_path=output,
        success_manifest_path=successes,
        failure_manifest_path=failures,
        trials=3,
        domain_variants=3,
        seed=7,
        env_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
    )

    success_rows = [json.loads(line) for line in successes.read_text(encoding="utf-8").splitlines()]
    assert summary["ok"] is True
    assert summary["source_demo_count"] == 2
    assert summary["trial_count"] == 18
    assert summary["domain_variants"] == 3
    assert summary["mimic_trials_per_source"] == 3
    assert len(success_rows) == 18
    assert Counter(row["source_episode_index"] for row in success_rows) == {0: 9, 1: 9}
    assert failures.read_text(encoding="utf-8") == ""
    with h5py.File(output, "r") as handle:
        assert len(handle["data"].keys()) == 18
        first = handle["data"]["demo_000000"]
        assert first.attrs["source_episode_index"] == 0
        assert first.attrs["domain_variant_index"] == 0
        assert first.attrs["mimic_trial_index"] == 0
        last = handle["data"]["demo_000017"]
        assert last.attrs["source_episode_index"] == 1
        assert last.attrs["domain_variant_index"] == 2
        assert last.attrs["mimic_trial_index"] == 2


def test_joint_replay_mimic_recombines_subtask_segments_across_source_demos(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    source = tmp_path / "source_real_success_annotated.hdf5"
    output = tmp_path / "mimic" / "generated_dataset.hdf5"
    successes = tmp_path / "mimic" / "successes.jsonl"
    failures = tmp_path / "mimic" / "failures.jsonl"
    _write_source_hdf5(source)
    with h5py.File(source, "a") as handle:
        source_demo = handle["data"]["demo_000000"]
        for index, offset in [(1, 10.0), (2, 20.0)]:
            handle["data"].copy(source_demo, f"demo_{index:06d}")
            copied = handle["data"][f"demo_{index:06d}"]
            copied.attrs["episode_index"] = index
            copied["actions"][...] = copied["actions"][:] + np.float32(offset)
            copied["states"][...] = copied["states"][:] + np.float32(offset)
            copied["initial_state/articulation/robot/joint_position"][...] = copied["actions"][:1]
            copied["obs/joint_pos"][...] = copied["actions"][:]
            copied["obs/robot_state"][...] = copied["states"][:]
            copied["obs/gripper_state"][...] = copied["actions"][:, -1:]

    summary = generate_joint_replay_mimic_dataset(
        input_path=source,
        output_path=output,
        success_manifest_path=successes,
        failure_manifest_path=failures,
        trials=3,
        domain_variants=1,
        seed=7,
        env_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
    )

    assert summary["ok"] is True
    with h5py.File(output, "r") as handle:
        first_source_trials = [
            handle["data"]["demo_000000"],
            handle["data"]["demo_000001"],
            handle["data"]["demo_000002"],
        ]
        unique_actions = {
            tuple(np.round(demo["actions"][:].reshape(-1), 5).tolist())
            for demo in first_source_trials
        }
        mixed_segment_trials = [
            json.loads(demo.attrs["source_segments"])
            for demo in first_source_trials
            if len({segment["source_demo"] for segment in json.loads(demo.attrs["source_segments"])}) > 1
        ]

    assert len(unique_actions) > 1
    assert mixed_segment_trials


def test_joint_replay_domain_variants_change_cube_initial_pose_and_record_metadata(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    source = tmp_path / "source_real_success_annotated.hdf5"
    output = tmp_path / "mimic" / "generated_dataset.hdf5"
    successes = tmp_path / "mimic" / "successes.jsonl"
    failures = tmp_path / "mimic" / "failures.jsonl"
    _write_source_hdf5(source)
    base_cube_pose = np.asarray([[0.4, 0.0, 0.025, 0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    with h5py.File(source, "a") as handle:
        handle["data"]["demo_000000"]["initial_state/rigid_object/red_cube/root_pose"][...] = base_cube_pose

    summary = generate_joint_replay_mimic_dataset(
        input_path=source,
        output_path=output,
        success_manifest_path=successes,
        failure_manifest_path=failures,
        trials=1,
        domain_variants=3,
        seed=7,
        env_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        domain_randomization_profile="mimic_pose",
    )

    success_rows = [json.loads(line) for line in successes.read_text(encoding="utf-8").splitlines()]
    assert summary["ok"] is True
    assert summary["domain_randomization_profile"] == "mimic_pose"
    with h5py.File(output, "r") as handle:
        variant_poses = [
            handle["data"][f"demo_{index:06d}"]["initial_state/rigid_object/red_cube/root_pose"][:]
            for index in range(3)
        ]
        variant_metadata = [
            json.loads(handle["data"][f"demo_{index:06d}"].attrs["domain_randomization"])
            for index in range(3)
        ]

    assert len({tuple(np.round(pose.reshape(-1), 5).tolist()) for pose in variant_poses}) == 3
    for metadata, pose, row in zip(variant_metadata, variant_poses, success_rows):
        assert metadata["profile"] == "mimic_pose"
        assert row["domain_randomization"]["profile"] == "mimic_pose"
        assert abs(metadata["cube_xy_offset_m"][0]) <= 0.015
        assert abs(metadata["cube_xy_offset_m"][1]) <= 0.015
        assert abs(metadata["cube_yaw_rad"]) <= 0.12
        np.testing.assert_allclose(pose[0, :2], base_cube_pose[0, :2] + np.asarray(metadata["cube_xy_offset_m"], dtype=np.float32), atol=1e-6)


def test_joint_replay_accepts_lab_export_state_groups(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    from device_bridges.isaac_lab_joint_replay_mimic import generate_joint_replay_mimic_dataset

    source = tmp_path / "source_real_success_annotated.hdf5"
    output = tmp_path / "mimic" / "generated_dataset.hdf5"
    successes = tmp_path / "mimic" / "successes.jsonl"
    failures = tmp_path / "mimic" / "failures.jsonl"
    actions = np.asarray(
        [
            [0.0, -1.0, 0.5, 0.2, 0.1, 0.8, -0.8],
            [0.4, -0.6, 0.6, 0.3, 0.1, 0.8, -0.8],
            [0.8, -0.2, 0.7, 0.4, 0.1, 0.8, -0.8],
        ],
        dtype=np.float32,
    )
    with h5py.File(source, "w") as handle:
        data = handle.create_group("data")
        demo = data.create_group("demo_0")
        demo.attrs["num_samples"] = int(actions.shape[0])
        demo.create_dataset("actions", data=actions)
        demo.create_dataset("processed_actions", data=actions)
        demo.create_group("states").create_group("rigid_object")
        obs = demo.create_group("obs")
        obs.create_dataset("joint_pos", data=actions[:, :6])
        obs.create_dataset("gripper_state", data=actions[:, -1:])
        datagen = obs.create_group("datagen_info")
        signals = datagen.create_group("subtask_term_signals")
        signals.create_dataset("approach", data=np.asarray([[False], [True], [True]], dtype=np.bool_))

    summary = generate_joint_replay_mimic_dataset(
        input_path=source,
        output_path=output,
        success_manifest_path=successes,
        failure_manifest_path=failures,
        trials=1,
        seed=7,
        env_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
    )

    assert summary["ok"] is True
    with h5py.File(output, "r") as handle:
        demo = handle["data"]["demo_000000"]
        assert demo["actions"].shape == (3, 7)
        assert demo["states"].shape == (3, 7)
        np.testing.assert_allclose(demo["states"][:], demo["actions"][:])


def test_visual_joint_replay_uses_unwrapped_num_envs_for_gym_wrappers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _visualize_generated_dataset

    dataset = tmp_path / "generated_dataset.hdf5"
    with h5py.File(dataset, "w") as handle:
        data = handle.create_group("data")
        demo = data.create_group("demo_000000")
        demo.create_dataset("actions", data=np.zeros((2, 7), dtype=np.float32))

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeApp:
        def __init__(self) -> None:
            self.update_calls = 0

        def is_running(self) -> bool:
            return True

        def update(self) -> None:
            self.update_calls += 1

    class FakeAppLauncher:
        def __init__(self, _: dict[str, object]) -> None:
            self.app = FakeApp()

    fake_app_launcher: FakeAppLauncher | None = None

    class CapturingFakeAppLauncher:
        def __init__(self, args: dict[str, object]) -> None:
            nonlocal fake_app_launcher
            fake_app_launcher = FakeAppLauncher(args)
            self.app = fake_app_launcher.app

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1

    class FakeWrappedEnv:
        unwrapped = FakeUnwrapped()

        def __init__(self) -> None:
            self.steps = 0

        def reset(self) -> None:
            return None

        def step(self, action: object) -> None:
            self.steps += 1

        def close(self) -> None:
            return None

    fake_env = FakeWrappedEnv()

    app_module = types.ModuleType("isaaclab.app")
    app_module.AppLauncher = CapturingFakeAppLauncher
    tasks_utils_module = types.ModuleType("isaaclab_tasks.utils")
    tasks_utils_module.parse_env_cfg = lambda *_args, **_kwargs: object()
    gym_module = types.ModuleType("gymnasium")
    gym_module.make = lambda *_args, **_kwargs: fake_env
    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda row, **_kwargs: FakeTensor(row)
    monkeypatch.setitem(sys.modules, "isaaclab.app", app_module)
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks_utils_module)
    monkeypatch.setitem(sys.modules, "gymnasium", gym_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    summary = _visualize_generated_dataset(
        dataset_path=dataset,
        task_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        num_envs=1,
        external_callback="",
        domain_randomization_profile="conservative",
        camera_mode="off",
        camera_width=320,
        camera_height=240,
        enable_cameras=False,
        rendering_mode="balanced",
        visualizer="kit",
        kit_args="",
        fps=120.0,
        max_demos=3,
    )

    assert summary["ok"] is True
    assert summary["replayed_frames"] == 2
    assert summary["viewport_update_count"] == 2
    assert fake_env.steps == 2
    assert fake_app_launcher is not None
    assert fake_app_launcher.app.update_calls == 2


def test_visual_joint_replay_caps_preview_demo_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _visualize_generated_dataset

    dataset = tmp_path / "generated_dataset.hdf5"
    with h5py.File(dataset, "w") as handle:
        data = handle.create_group("data")
        for index in range(5):
            demo = data.create_group(f"demo_{index:06d}")
            demo.create_dataset("actions", data=np.full((2, 7), index, dtype=np.float32))

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeApp:
        def is_running(self) -> bool:
            return True

        def update(self) -> None:
            return None

    class FakeAppLauncher:
        def __init__(self, _args: dict[str, object]) -> None:
            self.app = FakeApp()

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1
        scene: dict[str, object] = {}

    class FakeEnv:
        unwrapped = FakeUnwrapped()

        def __init__(self) -> None:
            self.reset_calls = 0
            self.step_calls = 0

        def reset(self) -> None:
            self.reset_calls += 1

        def step(self, _action: object) -> None:
            self.step_calls += 1

        def close(self) -> None:
            return None

    fake_env = FakeEnv()
    app_module = types.ModuleType("isaaclab.app")
    app_module.AppLauncher = FakeAppLauncher
    tasks_utils_module = types.ModuleType("isaaclab_tasks.utils")
    tasks_utils_module.parse_env_cfg = lambda *_args, **_kwargs: object()
    gym_module = types.ModuleType("gymnasium")
    gym_module.make = lambda *_args, **_kwargs: fake_env
    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda row, **_kwargs: FakeTensor(row)
    torch_module.zeros_like = lambda value: FakeTensor(np.zeros_like(value.array))
    monkeypatch.setitem(sys.modules, "isaaclab.app", app_module)
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks_utils_module)
    monkeypatch.setitem(sys.modules, "gymnasium", gym_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    summary = _visualize_generated_dataset(
        dataset_path=dataset,
        task_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        num_envs=1,
        external_callback="",
        domain_randomization_profile="conservative",
        camera_mode="off",
        camera_width=320,
        camera_height=240,
        enable_cameras=False,
        rendering_mode="balanced",
        visualizer="kit",
        kit_args="",
        fps=120.0,
        max_demos=2,
    )

    assert summary["ok"] is True
    assert summary["visual_demo_count"] == 2
    assert summary["visual_total_demo_count"] == 5
    assert summary["replayed_frames"] == 4
    assert fake_env.reset_calls == 2
    assert fake_env.step_calls == 4


def test_visual_joint_replay_applies_initial_cube_state_for_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _visualize_generated_dataset

    dataset = tmp_path / "generated_dataset.hdf5"
    joint = np.asarray([[0.1, -0.2, 0.3, -0.4, 0.5, 0.6, -0.6]], dtype=np.float32)
    robot_root = np.asarray([[0.31, 0.06, -0.02, 0.0, 0.0, 0.7071, 0.7071]], dtype=np.float32)
    cube_root = np.asarray([[0.4, 0.3, 0.015, 0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        initial = demo.create_group("initial_state")
        robot = initial.create_group("articulation").create_group("robot")
        robot.create_dataset("joint_position", data=joint)
        robot.create_dataset("joint_velocity", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("root_pose", data=robot_root)
        robot.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        cube = initial.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=cube_root)
        cube.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        demo.create_dataset("actions", data=joint)

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeAsset:
        def __init__(self) -> None:
            self.calls: list[tuple[str, np.ndarray | None]] = []

        def write_root_pose_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_pose", value.array.copy()))

        def write_root_velocity_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_velocity", value.array.copy()))

        def write_joint_state_to_sim(self, position: FakeTensor, velocity: FakeTensor) -> None:
            self.calls.append(("joint_position", position.array.copy()))
            self.calls.append(("joint_velocity", velocity.array.copy()))

        def set_joint_position_target(self, target: FakeTensor) -> None:
            self.calls.append(("joint_target", target.array.copy()))

        def write_data_to_sim(self) -> None:
            self.calls.append(("write_data_to_sim", None))

    class FakeApp:
        def is_running(self) -> bool:
            return True

        def update(self) -> None:
            return None

    class FakeAppLauncher:
        def __init__(self, _args: dict[str, object]) -> None:
            self.app = FakeApp()

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1

        def __init__(self) -> None:
            self.scene = {"robot": FakeAsset(), "red_cube": FakeAsset()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

        def reset(self) -> None:
            return None

        def step(self, _action: object) -> None:
            return None

        def close(self) -> None:
            return None

    fake_env = FakeEnv()
    app_module = types.ModuleType("isaaclab.app")
    app_module.AppLauncher = FakeAppLauncher
    tasks_utils_module = types.ModuleType("isaaclab_tasks.utils")
    tasks_utils_module.parse_env_cfg = lambda *_args, **_kwargs: object()
    gym_module = types.ModuleType("gymnasium")
    gym_module.make = lambda *_args, **_kwargs: fake_env
    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    torch_module.zeros_like = lambda value: FakeTensor(np.zeros_like(value.array))
    monkeypatch.setitem(sys.modules, "isaaclab.app", app_module)
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks_utils_module)
    monkeypatch.setitem(sys.modules, "gymnasium", gym_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    summary = _visualize_generated_dataset(
        dataset_path=dataset,
        task_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        num_envs=1,
        external_callback="",
        domain_randomization_profile="conservative",
        camera_mode="off",
        camera_width=320,
        camera_height=240,
        enable_cameras=False,
        rendering_mode="balanced",
        visualizer="kit",
        kit_args="",
        fps=120.0,
        max_demos=1,
    )

    assert summary["ok"] is True
    assert summary["visual_preplay_frame_applied_count"] == 1
    assert summary["visual_preplay_last"]["robot_joint_target"] is True
    assert summary["initial_state_last"]["red_cube_root_pose"] is True
    assert summary["initial_state_last"]["red_cube_root_velocity"] is True
    cube_calls = dict(fake_env.unwrapped.scene["red_cube"].calls)
    np.testing.assert_allclose(cube_calls["root_pose"], cube_root)


def test_visual_joint_replay_applies_hdf5_initial_state_to_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _apply_hdf5_demo_initial_state

    dataset = tmp_path / "generated_dataset.hdf5"
    robot_joint = np.asarray([[0.1, -0.2, 0.3, -0.4, 0.5, 0.6, -0.6]], dtype=np.float32)
    robot_joint_vel = np.zeros((1, 7), dtype=np.float32)
    robot_root = np.asarray([[0.31, 0.06, -0.02, 0.0, 0.0, 0.7071, 0.7071]], dtype=np.float32)
    robot_root_vel = np.zeros((1, 6), dtype=np.float32)
    cube_root = np.asarray([[0.4, 0.3, 0.015, 0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
    cube_root_vel = np.zeros((1, 6), dtype=np.float32)
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        demo.create_dataset("actions", data=robot_joint)
        initial = demo.create_group("initial_state")
        robot = initial.create_group("articulation").create_group("robot")
        robot.create_dataset("joint_position", data=robot_joint)
        robot.create_dataset("joint_velocity", data=robot_joint_vel)
        robot.create_dataset("root_pose", data=robot_root)
        robot.create_dataset("root_velocity", data=robot_root_vel)
        cube = initial.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=cube_root)
        cube.create_dataset("root_velocity", data=cube_root_vel)

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeAsset:
        def __init__(self) -> None:
            self.calls: list[tuple[str, np.ndarray]] = []

        def write_root_pose_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_pose", value.array.copy()))

        def write_root_velocity_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_velocity", value.array.copy()))

        def write_joint_state_to_sim(self, position: FakeTensor, velocity: FakeTensor) -> None:
            self.calls.append(("joint_position", position.array.copy()))
            self.calls.append(("joint_velocity", velocity.array.copy()))

        def set_joint_position_target(self, target: FakeTensor) -> None:
            self.calls.append(("joint_target", target.array.copy()))

        def write_data_to_sim(self) -> None:
            self.calls.append(("write_data_to_sim", None))

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 2

        def __init__(self) -> None:
            self.scene = {"robot": FakeAsset(), "red_cube": FakeAsset()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    env = FakeEnv()
    with h5py.File(dataset, "r") as handle:
        applied = _apply_hdf5_demo_initial_state(env, handle["data"]["demo_000000"], apply_rigid_objects=True)

    assert applied == {
        "robot_root_pose": True,
        "robot_root_velocity": True,
        "robot_joint_state": True,
        "robot_joint_target": True,
        "red_cube_root_pose": True,
        "red_cube_root_velocity": True,
    }
    robot_calls = dict(env.unwrapped.scene["robot"].calls)
    cube_calls = dict(env.unwrapped.scene["red_cube"].calls)
    np.testing.assert_allclose(robot_calls["joint_position"], np.repeat(robot_joint, 2, axis=0))
    np.testing.assert_allclose(robot_calls["joint_target"], np.repeat(robot_joint, 2, axis=0))
    np.testing.assert_allclose(robot_calls["root_pose"], np.repeat(robot_root, 2, axis=0))
    np.testing.assert_allclose(cube_calls["root_pose"], np.repeat(cube_root, 2, axis=0))
    assert [name for name, _value in env.unwrapped.scene["red_cube"].calls] == [
        "root_pose",
        "root_velocity",
        "write_data_to_sim",
    ]


def test_visual_joint_replay_applies_hdf5_frame_state_to_robot_and_cube(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _apply_hdf5_demo_frame_state

    dataset = tmp_path / "generated_dataset.hdf5"
    robot_joint = np.asarray(
        [
            [0.0, -0.1, 0.2, -0.3, 0.4, 0.5, -0.5],
            [0.1, -0.2, 0.3, -0.4, 0.5, 0.4, -0.4],
            [0.2, -0.3, 0.4, -0.5, 0.6, 0.3, -0.3],
        ],
        dtype=np.float32,
    )
    robot_root = np.asarray(
        [
            [0.31, 0.06, -0.02, 0.0, 0.0, 0.0, 1.0],
            [0.31, 0.06, -0.02, 0.0, 0.0, 0.1, 0.995],
            [0.31, 0.06, -0.02, 0.0, 0.0, 0.2, 0.980],
        ],
        dtype=np.float32,
    )
    cube_root = np.asarray(
        [
            [0.40, 0.30, 0.015, 0.0, 0.0, 0.0, 1.0],
            [0.44, 0.26, 0.110, 0.0, 0.0, 0.1, 0.995],
            [0.58, 0.09, 0.119, 0.0, 0.0, 0.2, 0.980],
        ],
        dtype=np.float32,
    )
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        states = demo.create_group("states")
        robot = states.create_group("articulation").create_group("robot")
        robot.create_dataset("joint_position", data=robot_joint)
        robot.create_dataset("joint_velocity", data=np.zeros((3, 7), dtype=np.float32))
        robot.create_dataset("root_pose", data=robot_root)
        robot.create_dataset("root_velocity", data=np.zeros((3, 6), dtype=np.float32))
        cube = states.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=cube_root)
        cube.create_dataset("root_velocity", data=np.zeros((3, 6), dtype=np.float32))

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeAsset:
        def __init__(self) -> None:
            self.calls: list[tuple[str, np.ndarray | None]] = []

        def write_root_pose_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_pose", value.array.copy()))

        def write_root_velocity_to_sim(self, value: FakeTensor) -> None:
            self.calls.append(("root_velocity", value.array.copy()))

        def write_joint_state_to_sim(self, position: FakeTensor, velocity: FakeTensor) -> None:
            self.calls.append(("joint_position", position.array.copy()))
            self.calls.append(("joint_velocity", velocity.array.copy()))

        def set_joint_position_target(self, target: FakeTensor) -> None:
            self.calls.append(("joint_target", target.array.copy()))

        def write_data_to_sim(self) -> None:
            self.calls.append(("write_data_to_sim", None))

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 2

        def __init__(self) -> None:
            self.scene = {"robot": FakeAsset(), "red_cube": FakeAsset()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    env = FakeEnv()
    with h5py.File(dataset, "r") as handle:
        applied = _apply_hdf5_demo_frame_state(
            env,
            handle["data"]["demo_000000"],
            frame_index=2,
            apply_rigid_objects=True,
        )

    assert applied == {
        "robot_root_pose": True,
        "robot_root_velocity": True,
        "robot_joint_state": True,
        "robot_joint_target": True,
        "red_cube_root_pose": True,
        "red_cube_root_velocity": True,
    }
    robot_calls = dict(env.unwrapped.scene["robot"].calls)
    cube_calls = dict(env.unwrapped.scene["red_cube"].calls)
    np.testing.assert_allclose(robot_calls["joint_position"], np.repeat(robot_joint[2:3], 2, axis=0))
    np.testing.assert_allclose(robot_calls["joint_target"], np.repeat(robot_joint[2:3], 2, axis=0))
    np.testing.assert_allclose(robot_calls["root_pose"], np.repeat(robot_root[2:3], 2, axis=0))
    np.testing.assert_allclose(cube_calls["root_pose"], np.repeat(cube_root[2:3], 2, axis=0))


def test_visual_joint_replay_writes_each_action_frame_to_robot_joint_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _apply_visual_joint_frame

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeRobot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, np.ndarray | None]] = []

        def write_joint_state_to_sim(self, position: FakeTensor, velocity: FakeTensor) -> None:
            self.calls.append(("joint_position", position.array.copy()))
            self.calls.append(("joint_velocity", velocity.array.copy()))

        def set_joint_position_target(self, target: FakeTensor) -> None:
            self.calls.append(("joint_target", target.array.copy()))

        def write_data_to_sim(self) -> None:
            self.calls.append(("write_data_to_sim", None))

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 2

        def __init__(self) -> None:
            self.scene = {"robot": FakeRobot()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    torch_module.zeros_like = lambda value: FakeTensor(np.zeros_like(value.array))
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    env = FakeEnv()
    action = FakeTensor(np.asarray([[0.1, -0.2, 0.3, -0.4, 0.5, 0.6, -0.6]], dtype=np.float32))
    applied = _apply_visual_joint_frame(env, action)

    assert applied == {
        "robot_joint_state": True,
        "robot_joint_target": True,
        "robot_write_data": True,
    }
    calls = dict(env.unwrapped.scene["robot"].calls)
    np.testing.assert_allclose(calls["joint_position"], np.repeat(action.array, 2, axis=0))
    np.testing.assert_allclose(calls["joint_velocity"], np.zeros((2, 7), dtype=np.float32))
    np.testing.assert_allclose(calls["joint_target"], np.repeat(action.array, 2, axis=0))


def test_visual_joint_replay_refreshes_observation_buffer_after_hdf5_initial_state() -> None:
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _refresh_env_after_hdf5_initial_state

    calls: list[tuple[str, object | None]] = []
    refreshed_obs = {"policy": {"object_pose": "updated"}}

    class FakeScene:
        def write_data_to_sim(self) -> None:
            calls.append(("scene_write_data_to_sim", None))

        def update(self, dt: float) -> None:
            calls.append(("scene_update", dt))

    class FakeSim:
        class RenderContext:
            def reset_transform_cadence(self) -> None:
                calls.append(("render_context_reset_transform_cadence", None))

        def __init__(self) -> None:
            self.render_context = self.RenderContext()

        def forward(self) -> None:
            calls.append(("sim_forward", None))

    class FakeObservationManager:
        def compute(self, *, update_history: bool) -> dict[str, object]:
            calls.append(("observation_compute", update_history))
            return refreshed_obs

    class FakeUnwrapped:
        def __init__(self) -> None:
            self.scene = FakeScene()
            self.sim = FakeSim()
            self.observation_manager = FakeObservationManager()
            self.obs_buf = {"policy": {"object_pose": "stale"}}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    env = FakeEnv()
    result = _refresh_env_after_hdf5_initial_state(env)

    assert result == {
        "scene_write_data_to_sim": True,
        "sim_forward": True,
        "render_context_reset_transform_cadence": True,
        "scene_update": True,
        "observation_compute": True,
    }
    assert calls == [
        ("scene_write_data_to_sim", None),
        ("sim_forward", None),
        ("render_context_reset_transform_cadence", None),
        ("scene_update", 0.0),
        ("observation_compute", True),
    ]
    assert env.unwrapped.obs_buf is refreshed_obs
    assert env.obs_buf is refreshed_obs


def test_lab_step_generation_copies_domain_randomization_attrs_to_recorder_output(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _copy_domain_randomization_attrs_to_lab_output

    source_path = tmp_path / "generated_dataset_joint_plan.hdf5"
    output_path = tmp_path / "generated_dataset.hdf5"
    metadata = {
        "profile": "standard",
        "cube_xy_offset_m": [0.01, 0.02],
        "cube_yaw_rad": 0.3,
    }
    with h5py.File(source_path, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        demo.attrs["domain_randomization"] = json.dumps(metadata, sort_keys=True)
    with h5py.File(output_path, "w") as handle:
        handle.create_group("data").create_group("demo_0")

    result = _copy_domain_randomization_attrs_to_lab_output(
        source_path,
        output_path,
        [{"source_demo": "demo_000000", "generated_demo": "demo_0"}],
    )

    assert result == {"copied": 1, "missing": 0}
    with h5py.File(output_path, "r") as handle:
        copied = json.loads(handle["data"]["demo_0"].attrs["domain_randomization"])
    assert copied == metadata


def test_visual_joint_replay_summary_records_robot_readback_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _visualize_generated_dataset

    dataset = tmp_path / "generated_dataset.hdf5"
    actions = np.asarray(
        [
            [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, -0.50],
            [0.2, 0.12, 0.22, 0.32, 0.42, 0.52, -0.52],
            [0.4, 0.14, 0.24, 0.34, 0.44, 0.54, -0.54],
        ],
        dtype=np.float32,
    )
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        demo.create_dataset("actions", data=actions)

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeRobotData:
        def __init__(self) -> None:
            self.joint_pos = FakeTensor(np.zeros((1, 7), dtype=np.float32))

    class FakeRobot:
        def __init__(self) -> None:
            self.data = FakeRobotData()

        def write_joint_state_to_sim(self, position: FakeTensor, _velocity: FakeTensor) -> None:
            self.data.joint_pos = FakeTensor(position.array.copy())

        def set_joint_position_target(self, target: FakeTensor) -> None:
            self.data.joint_pos = FakeTensor(target.array.copy())

        def write_data_to_sim(self) -> None:
            return None

    class FakeApp:
        def is_running(self) -> bool:
            return True

        def update(self) -> None:
            return None

    class FakeAppLauncher:
        def __init__(self, _args: dict[str, object]) -> None:
            self.app = FakeApp()

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1

        def __init__(self) -> None:
            self.scene = {"robot": FakeRobot()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

        def reset(self) -> None:
            return None

        def step(self, _action: object) -> None:
            return None

        def close(self) -> None:
            return None

    app_module = types.ModuleType("isaaclab.app")
    app_module.AppLauncher = FakeAppLauncher
    tasks_utils_module = types.ModuleType("isaaclab_tasks.utils")
    tasks_utils_module.parse_env_cfg = lambda *_args, **_kwargs: object()
    gym_module = types.ModuleType("gymnasium")
    gym_module.make = lambda *_args, **_kwargs: FakeEnv()
    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    torch_module.zeros_like = lambda value: FakeTensor(np.zeros_like(value.array))
    monkeypatch.setitem(sys.modules, "isaaclab.app", app_module)
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks_utils_module)
    monkeypatch.setitem(sys.modules, "gymnasium", gym_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    summary = _visualize_generated_dataset(
        dataset_path=dataset,
        task_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        num_envs=1,
        external_callback="",
        domain_randomization_profile="conservative",
        camera_mode="off",
        camera_width=320,
        camera_height=240,
        enable_cameras=False,
        rendering_mode="balanced",
        visualizer="kit",
        kit_args="",
        fps=120.0,
        max_demos=1,
    )

    assert summary["ok"] is True
    samples = summary["visual_readback_samples"]
    assert {sample["frame_index"] for sample in samples} == {0, 1, 2}
    assert all(sample["phase"] == "after_env_step" for sample in samples)
    assert summary["visual_readback_sample_count"] == 3
    assert summary["visual_readback_target_error_max"] == pytest.approx(0.0)
    np.testing.assert_allclose(samples[-1]["joint_pos"], actions[-1])


def test_visual_joint_replay_applies_viewer_camera_and_records_render_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _visualize_generated_dataset

    dataset = tmp_path / "generated_dataset.hdf5"
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        demo.create_dataset("actions", data=np.zeros((2, 7), dtype=np.float32))

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

        def reshape(self, *shape: int) -> "FakeTensor":
            return FakeTensor(self.array.reshape(*shape))

        def repeat(self, *repeats: int) -> "FakeTensor":
            return FakeTensor(np.tile(self.array, repeats))

    class FakeSim:
        def __init__(self) -> None:
            self.camera_views: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
            self.render_calls = 0

        def set_camera_view(self, *, eye: tuple[float, float, float], target: tuple[float, float, float]) -> None:
            self.camera_views.append((tuple(eye), tuple(target)))

        def render(self) -> None:
            self.render_calls += 1

    class FakeViewportCameraController:
        def __init__(self, sim: FakeSim) -> None:
            self.sim = sim
            self.update_calls = 0

        def update_view_location(self) -> None:
            self.update_calls += 1
            self.sim.set_camera_view(eye=(0.9, -1.2, 0.8), target=(0.315, 0.22, 0.02))

    class FakeViewer:
        eye = (0.9, -1.2, 0.8)
        lookat = (0.315, 0.22, 0.02)

    class FakeCfg:
        viewer = FakeViewer()

    class FakeApp:
        def __init__(self) -> None:
            self.update_calls = 0

        def is_running(self) -> bool:
            return True

        def update(self) -> None:
            self.update_calls += 1

    class FakeAppLauncher:
        def __init__(self, _args: dict[str, object]) -> None:
            self.app = FakeApp()

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1
        scene: dict[str, object] = {}
        cfg = FakeCfg()

        def __init__(self) -> None:
            self.sim = FakeSim()
            self.viewport_camera_controller = FakeViewportCameraController(self.sim)

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

        def reset(self) -> None:
            return None

        def step(self, _action: object) -> None:
            return None

        def close(self) -> None:
            return None

    fake_env = FakeEnv()
    app_module = types.ModuleType("isaaclab.app")
    app_module.AppLauncher = FakeAppLauncher
    tasks_utils_module = types.ModuleType("isaaclab_tasks.utils")
    tasks_utils_module.parse_env_cfg = lambda *_args, **_kwargs: object()
    gym_module = types.ModuleType("gymnasium")
    gym_module.make = lambda *_args, **_kwargs: fake_env
    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    torch_module.zeros_like = lambda value: FakeTensor(np.zeros_like(value.array))
    monkeypatch.setitem(sys.modules, "isaaclab.app", app_module)
    monkeypatch.setitem(sys.modules, "isaaclab_tasks.utils", tasks_utils_module)
    monkeypatch.setitem(sys.modules, "gymnasium", gym_module)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    summary = _visualize_generated_dataset(
        dataset_path=dataset,
        task_name="ATR-Robotis-OMX-PickPlace-Physical-State-v0",
        num_envs=1,
        external_callback="",
        domain_randomization_profile="conservative",
        camera_mode="off",
        camera_width=320,
        camera_height=240,
        enable_cameras=False,
        rendering_mode="balanced",
        visualizer="kit",
        kit_args="",
        fps=120.0,
        max_demos=1,
    )

    assert summary["ok"] is True
    assert summary["visual_camera_view_applied"] is True
    assert summary["visual_camera_view"]["eye"] == [0.9, -1.2, 0.8]
    assert summary["visual_camera_view"]["target"] == [0.315, 0.22, 0.02]
    assert summary["visual_render_method_last"] == "sim.render"
    assert summary["viewport_update_count"] == 2
    assert fake_env.unwrapped.viewport_camera_controller.update_calls >= 1
    assert fake_env.unwrapped.sim.render_calls == 2


def test_guided_grasp_follow_writes_cube_to_finger_center(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    from scripts.lerobot_isaac_lab_joint_replay_mimic import _apply_guided_grasp_follow

    dataset = tmp_path / "generated_dataset.hdf5"
    with h5py.File(dataset, "w") as handle:
        demo = handle.create_group("data").create_group("demo_000000")
        signals = demo.create_group("obs").create_group("datagen_info").create_group("subtask_term_signals")
        signals.create_dataset("grasp", data=np.asarray([[False], [True], [True]], dtype=np.bool_))
        signals.create_dataset("place", data=np.asarray([[False], [False], [True]], dtype=np.bool_))

    class FakeTensor:
        def __init__(self, array: object) -> None:
            self.array = np.asarray(array, dtype=np.float32)
            self.shape = self.array.shape

    class FakeCube:
        def __init__(self) -> None:
            self.poses: list[np.ndarray] = []

        def write_root_pose_to_sim(self, value: FakeTensor) -> None:
            self.poses.append(value.array.copy())

    class FakeData:
        body_pos_w = FakeTensor(
            np.asarray(
                [
                    [
                        [0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0],
                        [0.30, 0.40, 0.05],
                        [0.50, 0.60, 0.07],
                    ]
                ],
                dtype=np.float32,
            )
        )

    class FakeRobot:
        body_names = ["link0", "link1", "link2", "link3", "link4", "link5", "link6", "link7"]
        data = FakeData()

    class FakeUnwrapped:
        device = "cpu"
        num_envs = 1

        def __init__(self) -> None:
            self.scene = {"robot": FakeRobot(), "red_cube": FakeCube()}

    class FakeEnv:
        def __init__(self) -> None:
            self.unwrapped = FakeUnwrapped()

    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.as_tensor = lambda value, **_kwargs: FakeTensor(value)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    env = FakeEnv()
    state: dict[str, object] = {}
    with h5py.File(dataset, "r") as handle:
        demo = handle["data"]["demo_000000"]
        assert _apply_guided_grasp_follow(env, demo, frame_index=0, state=state)["held"] is False
        grasp_result = _apply_guided_grasp_follow(env, demo, frame_index=1, state=state)
        place_result = _apply_guided_grasp_follow(env, demo, frame_index=2, state=state)

    assert grasp_result["held"] is True
    assert grasp_result["wrote_pose"] is True
    assert place_result["held"] is False
    assert place_result["wrote_pose"] is False
    cube_poses = env.unwrapped.scene["red_cube"].poses
    assert len(cube_poses) == 1
    np.testing.assert_allclose(cube_poses[0][0, :3], [0.40, 0.50, 0.06])
    np.testing.assert_allclose(cube_poses[0][0, 3:], [0.0, 0.0, 0.0, 1.0])
