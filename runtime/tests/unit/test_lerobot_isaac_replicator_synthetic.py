"""Tests for the Isaac Sim Replicator worker wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lerobot_isaac_replicator_synthetic import run_replicator_worker


def _jsonl_write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_replicator_worker_writes_blocked_summary_when_runtime_import_is_missing(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": index,
                "timestamp": index / 15.0,
                "episode_success": True,
            }
            for index in range(3)
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"

    def missing_import(name: str):
        raise ModuleNotFoundError(name)

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top", "right"],
        variants=2,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=missing_import,
    )

    assert summary["ok"] is False
    assert summary["status"] == "blocked"
    assert summary["blocker"] == "REPLICATOR_REQUIRES_ISAAC_RUNTIME"
    assert summary["canonical_frame_count"] == 3
    assert summary["expected_render_rows"] == 12
    assert summary["rendered_count"] == 0
    assert summary["train_eligible_count"] == 0
    assert summary["runtime_probe"]["status"] == "blocked"
    assert summary["runtime_probe"]["import_checked"] is True
    assert summary["runtime_probe"]["required_modules"] == ["omni.replicator.core"]
    assert summary["request"]["cameras"] == ["top", "right"]
    assert summary["request"]["variants"] == 2
    assert (output_dir / "summary.json").is_file()
    written = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert written["blocker"] == "REPLICATOR_REQUIRES_ISAAC_RUNTIME"
    assert not (output_dir / "manifest.jsonl").exists()


def test_replicator_worker_writes_manifest_when_backend_renders_rgb_depth_pairs(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": index,
                "timestamp_s": index / 15.0,
                "episode_success": True,
            }
            for index in range(2)
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"

    def importer(name: str):
        if name == "omni.replicator.core":
            return object()
        raise ModuleNotFoundError(name)

    def render_backend(context: dict) -> list[dict]:
        augmentation = context["post_render_augmentation"]
        assert augmentation["owner"] == "isaac_sim_replicator_writer_annotators"
        assert augmentation["execution_stage"] == "replicator_writer_annotator"
        assert augmentation["rgb"]["strength"] == 0.2
        assert augmentation["depth"]["strength"] == 0.3
        assert augmentation["render"]["strength"] == 0.4
        assert augmentation["camera_pose"]["strength"] == 0.05
        rows = []
        for canonical in context["canonical_rows"]:
            for camera in context["cameras"]:
                for variant_index in range(context["variants"]):
                    episode_index = int(canonical["episode_index"])
                    frame_index = int(canonical["frame_index"])
                    stem = f"e{episode_index:06d}_f{frame_index:06d}_v{variant_index:03d}"
                    rgb_rel = Path("rgb") / camera / f"{stem}.png"
                    depth_rel = Path("depth") / camera / f"{stem}.png"
                    metadata_rel = Path("metadata") / camera / f"{stem}.json"
                    for rel, payload in [
                        (rgb_rel, b"rgb\n"),
                        (depth_rel, b"depth16\n"),
                        (metadata_rel, json.dumps({"camera": camera}).encode("utf-8")),
                    ]:
                        path = context["output_dir"] / rel
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(payload)
                    rows.append(
                        {
                            "canonical_episode_index": episode_index,
                            "canonical_frame_index": frame_index,
                            "timestamp_s": canonical["timestamp_s"],
                            "camera_name": camera,
                            "variant_index": variant_index,
                            "rgb_path": str(rgb_rel),
                            "depth_path": str(depth_rel),
                            "metadata_path": str(metadata_rel),
                        }
                    )
        return rows

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top", "right"],
        variants=2,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=importer,
        render_backend=render_backend,
    )

    assert summary["ok"] is True
    assert summary["status"] == "completed"
    assert summary["blocker"] == ""
    assert summary["canonical_frame_count"] == 2
    assert summary["expected_render_rows"] == 8
    assert summary["rendered_count"] == 8
    assert summary["train_eligible_count"] == 0
    assert summary["render_file_validation"]["ok"] is True
    assert summary["render_file_validation"]["valid_row_count"] == 8
    assert summary["runtime_probe"]["status"] == "passed"
    assert summary["replicator_available"] is True
    assert summary["writer_type"] == "BasicWriter"
    assert summary["annotators"] == ["rgb", "distance_to_image_plane", "semantic_segmentation"]
    assert summary["post_render_augmentation"]["schema"] == "atr.lerobot.replicator.post_render_augmentation.v1"
    assert summary["post_render_augmentation"]["rgb"]["annotator"] == "rgb"
    assert summary["post_render_augmentation"]["depth"]["annotator"] == "distance_to_image_plane"
    assert summary["post_render_augmentation"]["depth"]["source_profile"] == "d405_raw_depth_profile"
    assert summary["post_render_augmentation"]["trajectory_boundary"] == "render_only_not_action_trajectory"
    assert summary["render_products"]["requested_count"] == 8
    assert summary["render_products"]["camera_names"] == ["top", "right"]
    assert summary["rgb_output_count"] == 8
    assert summary["depth_output_count"] == 8
    assert summary["segmentation_output_count"] == 0
    assert summary["depth_units_replicator"]["unit"] == "meters"
    assert summary["teleop_sdg_replay_used"] is False
    assert summary["teleop_sdg_replay_boundary"] == "render_only_not_physics_rollout"
    assert (output_dir / "summary.json").is_file()
    manifest_path = output_dir / "manifest.jsonl"
    assert manifest_path.is_file()
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8
    assert rows[0]["schema"] == "atr.lerobot.replicator_frame.v1"
    assert rows[0]["source_type"] == "replicator_render_only"
    assert rows[0]["episode_index"] == 0
    assert rows[0]["frame_index"] == 0
    assert rows[0]["camera"] == "top"
    assert rows[0]["train_eligible"] is False
    assert rows[0]["train_exclusion_reason"] == "render_only_same_pose"
    assert rows[0]["post_render_augmentation"]["execution_stage"] == "replicator_writer_annotator"
    assert rows[0]["post_render_augmentation"]["rgb_strength"] == 0.2
    assert rows[0]["post_render_augmentation"]["depth_strength"] == 0.3
    assert rows[0]["post_render_augmentation"]["render_strength"] == 0.4
    assert rows[0]["post_render_augmentation"]["camera_pose_strength"] == 0.05
    assert rows[0]["post_render_augmentation"]["train_boundary"] == "render_only_same_action"
    assert (output_dir / rows[0]["rgb_path"]).is_file()
    assert (output_dir / rows[0]["depth_path"]).is_file()


def test_replicator_worker_initializes_simulation_app_before_replicator_import(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": 0,
                "timestamp_s": 0.0,
                "episode_success": True,
            }
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"
    state = {"simulation_app_started": False, "simulation_app_closed": False}

    class FakeSimulationApp:
        def __init__(self, launch_config):
            assert launch_config["headless"] is True
            state["simulation_app_started"] = True

        def close(self):
            state["simulation_app_closed"] = True

    class FakeIsaacSim:
        SimulationApp = FakeSimulationApp

    def importer(name: str):
        if name == "isaacsim":
            return FakeIsaacSim
        if name == "omni.replicator.core":
            assert state["simulation_app_started"] is True
            return object()
        raise ModuleNotFoundError(name)

    def render_backend(context: dict) -> list[dict]:
        rgb_path = context["output_dir"] / "rgb" / "top" / "e000000_f000000_v000.png"
        depth_path = context["output_dir"] / "depth" / "top" / "e000000_f000000_v000.png"
        for path, payload in [(rgb_path, b"rgb"), (depth_path, b"depth")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return [
            {
                "canonical_episode_index": 0,
                "canonical_frame_index": 0,
                "camera_name": "top",
                "variant_index": 0,
                "rgb_path": "rgb/top/e000000_f000000_v000.png",
                "depth_path": "depth/top/e000000_f000000_v000.png",
            }
        ]

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top"],
        variants=1,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=importer,
        render_backend=render_backend,
    )

    assert summary["ok"] is True
    assert summary["runtime_probe"]["simulation_app"]["status"] == "passed"
    assert summary["runtime_probe"]["simulation_app"]["module"] == "isaacsim"
    assert state["simulation_app_closed"] is True


def test_replicator_worker_visual_generation_starts_simulation_app_non_headless(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": 0,
                "timestamp_s": 0.0,
                "episode_success": True,
            }
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"
    state = {"headless": None}

    class FakeSimulationApp:
        def __init__(self, launch_config):
            state["headless"] = launch_config["headless"]

        def close(self):
            pass

    class FakeIsaacSim:
        SimulationApp = FakeSimulationApp

    def importer(name: str):
        if name == "isaacsim":
            return FakeIsaacSim
        if name == "omni.replicator.core":
            return object()
        raise ModuleNotFoundError(name)

    def render_backend(context: dict) -> list[dict]:
        rgb_path = context["output_dir"] / "rgb" / "top" / "e000000_f000000_v000.png"
        depth_path = context["output_dir"] / "depth" / "top" / "e000000_f000000_v000.png"
        for path, payload in [(rgb_path, b"rgb"), (depth_path, b"depth")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return [
            {
                "canonical_episode_index": 0,
                "canonical_frame_index": 0,
                "camera_name": "top",
                "variant_index": 0,
                "rgb_path": "rgb/top/e000000_f000000_v000.png",
                "depth_path": "depth/top/e000000_f000000_v000.png",
            }
        ]

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top"],
        variants=1,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=importer,
        render_backend=render_backend,
        visualize_generation=True,
    )

    assert summary["ok"] is True
    assert state["headless"] is False
    assert summary["runtime_probe"]["simulation_app"]["headless"] is False


def test_replicator_worker_persists_summary_before_simulation_app_close_can_exit(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": 0,
                "timestamp_s": 0.0,
                "episode_success": True,
            }
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"

    class FakeSimulationApp:
        def __init__(self, launch_config):
            assert launch_config["headless"] is True

        def close(self):
            raise SystemExit(0)

    class FakeIsaacSim:
        SimulationApp = FakeSimulationApp

    def importer(name: str):
        if name == "isaacsim":
            return FakeIsaacSim
        if name == "omni.replicator.core":
            return object()
        raise ModuleNotFoundError(name)

    def render_backend(context: dict) -> list[dict]:
        rgb_path = context["output_dir"] / "rgb" / "top" / "e000000_f000000_v000.png"
        depth_path = context["output_dir"] / "depth" / "top" / "e000000_f000000_v000.png"
        for path, payload in [(rgb_path, b"rgb"), (depth_path, b"depth")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return [
            {
                "canonical_episode_index": 0,
                "canonical_frame_index": 0,
                "camera_name": "top",
                "variant_index": 0,
                "rgb_path": "rgb/top/e000000_f000000_v000.png",
                "depth_path": "depth/top/e000000_f000000_v000.png",
            }
        ]

    with pytest.raises(SystemExit):
        run_replicator_worker(
            canonical_index=canonical_index,
            stage_url=stage,
            output_dir=output_dir,
            cameras=["top"],
            variants=1,
            rgb_strength=0.2,
            depth_strength=0.3,
            render_strength=0.4,
            camera_pose_strength=0.05,
            importer=importer,
            render_backend=render_backend,
        )

    written = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert written["status"] == "completed"
    assert written["rendered_count"] == 1
    assert written["runtime_probe"]["simulation_app_close"]["status"] in {
        "pending_process_shutdown",
        "process_exit_requested",
    }


def test_replicator_worker_default_backend_uses_basic_writer_and_orchestrator(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": 0,
                "timestamp_s": 0.0,
                "episode_success": True,
            }
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"
    calls: list[tuple] = []

    class FakeWriter:
        def __init__(self, rep):
            self.rep = rep
            self.output_dir = None

        def initialize(self, **kwargs):
            calls.append(("writer.initialize", kwargs))
            self.output_dir = Path(kwargs["output_dir"])

        def attach(self, products):
            calls.append(("writer.attach", tuple(products)))
            self.rep.active_writer = self

        def detach(self):
            calls.append(("writer.detach",))
            self.rep.active_writer = None

    class FakeWriters:
        def __init__(self, rep):
            self.rep = rep

        def get(self, name):
            calls.append(("writers.get", name))
            assert name == "BasicWriter"
            return FakeWriter(self.rep)

    class FakeCreate:
        def render_product(self, camera, resolution):
            calls.append(("create.render_product", camera, tuple(resolution)))
            return f"render_product:{camera}"

    class FakeOrchestrator:
        def __init__(self, rep):
            self.rep = rep

        def step(self):
            calls.append(("orchestrator.step",))
            writer = self.rep.active_writer
            assert writer is not None
            writer.output_dir.mkdir(parents=True, exist_ok=True)
            (writer.output_dir / "rgb_0000.png").write_bytes(b"rgb")
            (writer.output_dir / "distance_to_image_plane_0000.png").write_bytes(b"depth")
            (writer.output_dir / "metadata.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    class FakeRep:
        def __init__(self):
            self.active_writer = None
            self.writers = FakeWriters(self)
            self.create = FakeCreate()
            self.orchestrator = FakeOrchestrator(self)

    fake_rep = FakeRep()

    def importer(name: str):
        if name == "omni.replicator.core":
            return fake_rep
        raise ModuleNotFoundError(name)

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top"],
        variants=1,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=importer,
    )

    assert summary["ok"] is True
    assert summary["status"] == "completed"
    assert summary["rendered_count"] == 1
    assert ("writers.get", "BasicWriter") in calls
    assert ("create.render_product", "top", (640, 480)) in calls
    assert ("orchestrator.step",) in calls
    manifest_rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest_rows[0]["camera"] == "top"
    assert manifest_rows[0]["rgb_path"].endswith("rgb_0000.png")
    assert manifest_rows[0]["depth_path"].endswith("distance_to_image_plane_0000.png")
    assert (output_dir / manifest_rows[0]["metadata_path"]).is_file()


def test_replicator_worker_default_backend_opens_stage_and_resolves_camera_prim(tmp_path: Path) -> None:
    canonical_index = tmp_path / "canonical_episode_index" / "manifest.jsonl"
    _jsonl_write(
        canonical_index,
        [
            {
                "schema": "atr.lerobot.canonical_episode_frame.v1",
                "episode_index": 0,
                "frame_index": 0,
                "timestamp_s": 0.0,
                "episode_success": True,
            }
        ],
    )
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_dir = tmp_path / "replicator"
    calls: list[tuple] = []

    class FakePrim:
        def __init__(self, *, valid: bool, type_name: str = ""):
            self.valid = valid
            self.type_name = type_name

        def IsValid(self):
            return self.valid

        def GetTypeName(self):
            return self.type_name

    class FakeStage:
        def GetPrimAtPath(self, path):
            calls.append(("stage.GetPrimAtPath", path))
            if path == "/World/Cameras/top_camera":
                return FakePrim(valid=True, type_name="Camera")
            return FakePrim(valid=False)

    fake_stage = FakeStage()

    class FakeUsdContext:
        def open_stage(self, path):
            calls.append(("usd.open_stage", path))
            return True

        def get_stage(self):
            calls.append(("usd.get_stage",))
            return fake_stage

    class FakeOmniUsd:
        def get_context(self):
            calls.append(("usd.get_context",))
            return FakeUsdContext()

    class FakeWriter:
        def __init__(self, rep):
            self.rep = rep
            self.output_dir = None

        def initialize(self, **kwargs):
            self.output_dir = Path(kwargs["output_dir"])

        def attach(self, products):
            self.rep.active_writer = self

        def detach(self):
            self.rep.active_writer = None

    class FakeWriters:
        def __init__(self, rep):
            self.rep = rep

        def get(self, name):
            assert name == "BasicWriter"
            return FakeWriter(self.rep)

    class FakeCreate:
        def render_product(self, camera, resolution):
            calls.append(("create.render_product", camera, tuple(resolution)))
            return f"render_product:{camera}"

    class FakeOrchestrator:
        def __init__(self, rep):
            self.rep = rep

        def step(self):
            writer = self.rep.active_writer
            assert writer is not None
            writer.output_dir.mkdir(parents=True, exist_ok=True)
            (writer.output_dir / "rgb_0000.png").write_bytes(b"rgb")
            (writer.output_dir / "distance_to_image_plane_0000.png").write_bytes(b"depth")

    class FakeRep:
        def __init__(self):
            self.active_writer = None
            self.writers = FakeWriters(self)
            self.create = FakeCreate()
            self.orchestrator = FakeOrchestrator(self)

    fake_rep = FakeRep()

    def importer(name: str):
        if name == "omni.replicator.core":
            return fake_rep
        if name == "omni.usd":
            return FakeOmniUsd()
        raise ModuleNotFoundError(name)

    summary = run_replicator_worker(
        canonical_index=canonical_index,
        stage_url=stage,
        output_dir=output_dir,
        cameras=["top"],
        variants=1,
        rgb_strength=0.2,
        depth_strength=0.3,
        render_strength=0.4,
        camera_pose_strength=0.05,
        importer=importer,
    )

    assert summary["ok"] is True
    assert ("usd.open_stage", str(stage.resolve())) in calls
    assert ("stage.GetPrimAtPath", "/World/Cameras/top_camera") in calls
    assert ("create.render_product", "/World/Cameras/top_camera", (640, 480)) in calls
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["camera"] == "top"
    assert rows[0]["camera_path"] == "/World/Cameras/top_camera"
