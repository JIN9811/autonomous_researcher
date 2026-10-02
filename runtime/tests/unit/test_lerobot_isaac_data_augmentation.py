"""Tests for Isaac Sim sidecar data augmentation generation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.lerobot_isaac_data_augmentation import build_augmentation_sidecar


def _write_rendered_source(dataset: Path) -> Path:
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_one"
    files: list[dict[str, object]] = []
    for camera in ("top", "front", "right"):
        camera_dir = render_dir / camera
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / "frame_000000_rgb.png"
        depth_path = camera_dir / "frame_000000_depth.png"
        Image.fromarray(np.full((8, 8, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
        Image.fromarray(np.full((8, 8), 430, dtype=np.uint16)).save(depth_path)
        files.extend(
            [
                {"camera": camera, "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
                {"camera": camera, "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
            ]
        )
    row = {
        "schema": "atr.isaac_rgbd.render_manifest.v1",
        "status": "rendered",
        "session_id": "record_one",
        "attempt_id": "attempt_one",
        "episode_index": 0,
        "frame_index": 0,
        "sample_index": 1,
        "record_timestamp": "2026-06-28T00:00:00+00:00",
        "target_fps": 15.0,
        "cameras": ["top", "front", "right"],
        "output_dir": str(render_dir),
        "files": files,
    }
    (render_dir / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (dataset / "meta").mkdir(parents=True, exist_ok=True)
    (dataset / "meta" / "atr_pipeline.json").write_text(
        json.dumps({"isaac_rgbd_sidecar": {"enabled": True, "cameras": ["top", "front", "right"], "target_fps": 15.0}}),
        encoding="utf-8",
    )
    return render_dir


def _write_rendered_source_for_episode(dataset: Path, *, episode_index: int, frame_index: int = 0) -> Path:
    render_dir = dataset / "sidecar" / "isaac_rgbd" / f"episode_{episode_index:03d}" / "attempt_filter"
    camera_dir = render_dir / "top"
    camera_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
    depth_path = camera_dir / f"frame_{frame_index:06d}_depth.png"
    Image.fromarray(np.full((8, 8, 3), [80 + episode_index, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.full((8, 8), 430 + episode_index, dtype=np.uint16)).save(depth_path)
    row = {
        "schema": "atr.isaac_rgbd.render_manifest.v1",
        "status": "rendered",
        "attempt_id": "attempt_filter",
        "episode_index": episode_index,
        "frame_index": frame_index,
        "sample_index": frame_index + 1,
        "record_timestamp": "2026-06-28T00:00:00+00:00",
        "target_fps": 15.0,
        "cameras": ["top"],
        "output_dir": str(render_dir),
        "files": [
            {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
    }
    (render_dir / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return render_dir


def _write_rendered_source_with_files(
    dataset: Path,
    *,
    files: list[dict[str, object]],
    specimen_pose: dict[str, object] | None = None,
) -> Path:
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_custom"
    render_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": "atr.isaac_rgbd.render_manifest.v1",
        "status": "rendered",
        "attempt_id": "attempt_custom",
        "episode_index": 0,
        "frame_index": 0,
        "sample_index": 1,
        "record_timestamp": "2026-06-28T00:00:00+00:00",
        "target_fps": 15.0,
        "cameras": ["top"],
        "output_dir": str(render_dir),
        "files": files,
    }
    if specimen_pose is not None:
        row["specimen_pose"] = specimen_pose
    (render_dir / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return render_dir


def _read_single_variant(output_dir: Path) -> dict[str, object]:
    return json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0])


def test_isaac_augmentation_excludes_contact_flagged_source_episodes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source_for_episode(dataset, episode_index=0)
    _write_rendered_source_for_episode(dataset, episode_index=1)
    exclusion_path = dataset / "sidecar" / "train_exclusions" / "contact_audit.json"
    exclusion_path.parent.mkdir(parents=True, exist_ok=True)
    exclusion_path.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.training_exclusions.contact_audit.v1",
                "policy": "exclude_severe_contact_episodes",
                "source": "isaac_rgbd_contact_audit",
                "episode_indices": [0],
                "episode_count": 1,
                "original_data_preserved": True,
            }
        ),
        encoding="utf-8",
    )

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=dataset / "sidecar" / "isaac_augmentation" / "latest",
        variants_per_frame=1,
        max_source_frames=10,
        seed=7,
        cameras=["top"],
    )

    rows = [
        json.loads(line)
        for line in Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert result["ok"] is True
    assert result["source_frame_count"] == 1
    assert result["excluded_source_episode_indices"] == [0]
    assert result["excluded_source_frame_count"] == 1
    assert [row["source"]["episode_index"] for row in rows] == [1]


def _write_single_camera_rendered_source(
    dataset: Path,
    *,
    camera: str,
    depth: np.ndarray,
    camera_model: str = "",
) -> Path:
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / f"attempt_{camera}"
    camera_dir = render_dir / camera
    camera_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = camera_dir / "frame_000000_rgb.png"
    depth_path = camera_dir / "frame_000000_depth.png"
    Image.fromarray(np.full((*depth.shape, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(depth.astype(np.uint16)).save(depth_path)
    row = {
        "schema": "atr.isaac_rgbd.render_manifest.v1",
        "status": "rendered",
        "attempt_id": f"attempt_{camera}",
        "episode_index": 0,
        "frame_index": 0,
        "sample_index": 1,
        "record_timestamp": "2026-06-28T00:00:00+00:00",
        "target_fps": 15.0,
        "cameras": [camera],
        "output_dir": str(render_dir),
        "files": [
            {"camera": camera, "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": camera, "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
    }
    (render_dir / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    if camera_model:
        raw_depth_dir = dataset / "sidecar" / "raw_depth"
        raw_depth_dir.mkdir(parents=True, exist_ok=True)
        (raw_depth_dir / "transform_manifest.json").write_text(
            json.dumps({"camera_keys": [camera], "camera_models": {camera: camera_model}}),
            encoding="utf-8",
        )
    return render_dir


def test_build_augmentation_sidecar_writes_common_image_depth_and_camera_pose_variants(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=2,
        max_source_frames=1,
        seed=123,
        cameras=["top", "front", "right"],
        augmentation_profile="sim2real",
        image_augmentation_enabled=True,
        photometric_enabled=True,
        sensor_noise_enabled=True,
        depth_noise_enabled=True,
        render_domain_enabled=True,
        camera_pose_enabled=True,
        rgb_strength=1.0,
        depth_strength=1.0,
        render_domain_strength=1.0,
        camera_pose_strength=1.0,
    )

    assert result["ok"] is True
    assert result["source_frame_count"] == 1
    assert result["variant_count"] == 2
    assert result["summary_path"] == str(output_dir / "summary.json")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["augmentation_recipe_version"] == "standard_sim2real_v2"
    assert summary["domain_randomization_version"] == "sim2real_domain_randomization_v1"
    assert summary["augmentation_profile"] == "sim2real"
    assert summary["augmentation_options"]["photometric_enabled"] is True
    assert summary["augmentation_options"]["sensor_noise_enabled"] is True
    assert summary["augmentation_options"]["depth_noise_enabled"] is True
    assert summary["augmentation_options"]["render_domain_enabled"] is True
    assert summary["common_augmentation_families"] == [
        "photometric",
        "sensor_noise",
        "depth_noise",
        "render_domain",
        "camera_pose",
    ]
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    first = rows[0]
    assert first["schema"] == "atr.isaac_data_augmentation.variant.v1"
    assert first["augmentation_recipe_version"] == "standard_sim2real_v2"
    assert first["augmentation_profile"] == "sim2real"
    assert first["family_mask"] == {
        "photometric": True,
        "sensor_noise": True,
        "depth_noise": True,
        "render_domain": True,
        "camera_pose": True,
    }
    assert set(first["image_augmentations"]) >= {
        "brightness",
        "contrast",
        "saturation",
        "gamma",
        "hue_shift_deg",
        "channel_gains",
        "blur_radius",
        "gaussian_noise_std",
        "jpeg_quality",
    }
    assert set(first["depth_augmentations"]) >= {
        "scale",
        "bias_mm",
        "noise_mm",
        "dropout_prob",
        "hole_kernel_px",
        "quantization_mm",
        "clip_min_mm",
        "clip_max_mm",
    }
    assert set(first["render_domain_augmentations"]) >= {
        "object_xy_jitter_mm",
        "light_intensity_scale",
        "light_color_temperature_shift_k",
        "material_roughness",
        "surface_specular_scale",
        "lighting",
        "specimen_material",
        "table_material",
        "gripper_pad_material",
        "specimen_physics",
    }
    assert first["domain_randomization_version"] == "sim2real_domain_randomization_v1"
    assert first["render_request"]["domain_randomization_version"] == "sim2real_domain_randomization_v1"
    assert set(first["render_domain_augmentations"]["lighting"]) >= {
        "intensity_scale",
        "color_temperature_shift_k",
        "shadow_softness_scale",
    }
    assert set(first["render_domain_augmentations"]["specimen_material"]) >= {
        "albedo_scale",
        "roughness",
        "specular_scale",
    }
    assert set(first["render_domain_augmentations"]["table_material"]) >= {
        "albedo_scale",
        "roughness",
    }
    assert set(first["render_domain_augmentations"]["gripper_pad_material"]) >= {
        "static_friction",
        "dynamic_friction",
    }
    assert set(first["render_domain_augmentations"]["specimen_physics"]) >= {
        "mass_scale",
        "static_friction",
        "dynamic_friction",
        "contact_offset_scale",
    }
    assert "object_yaw_jitter_deg" not in first["render_domain_augmentations"]
    assert first["orientation_source"] == "disabled_no_orientation"
    assert first["cameras"] == ["top", "front", "right"]
    assert set(first["render_request"]["camera_specs"]) == {"top", "front", "right"}
    assert first["render_request"]["camera_specs"]["top"]["position"] != [0.315, 0.205, 0.72]
    assert first["render_request"]["camera_specs"]["front"]["position"] != [0.18, -0.2, 0.36]
    assert first["render_request"]["camera_specs"]["front"]["focal_length"] == 14.0
    assert first["render_request"]["camera_specs"]["right"]["position"] != [0.68, 0.12, 0.36]
    assert first["render_request"]["camera_specs"]["right"]["focal_length"] == 10.0
    assert first["render_request"]["camera_specs"]["front"]["position"] != [0.42, -0.08, 0.42]
    assert first["render_request"]["camera_specs"]["right"]["position"] != [0.42, -0.08, 0.42]
    assert first["camera_pose_source"] == "isaac_rgbd_render_manifest"
    assert Path(first["image_outputs"]["top"]["rgb_path"]).is_file()
    assert Path(first["image_outputs"]["top"]["depth_path"]).is_file()
    assert np.asarray(Image.open(first["image_outputs"]["top"]["depth_path"])).dtype == np.uint16

    second = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=123,
        cameras=["top", "front", "right"],
        image_augmentation_enabled=True,
        camera_pose_enabled=True,
    )

    assert second["variant_count"] == 1
    assert len((output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_build_augmentation_sidecar_reports_progress_counters(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"
    events: list[dict[str, object]] = []

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=3,
        max_source_frames=1,
        seed=7,
        progress_callback=events.append,
    )

    assert result["ok"] is True
    assert result["progress"]["stage"] == "complete"
    assert result["progress"]["done"] == 3
    assert result["progress"]["total"] == 3
    assert result["progress"]["percent"] == 100.0
    assert events[0]["stage"] == "prepare"
    assert any(event["stage"] == "build_manifest" and event["done"] == 2 for event in events)
    assert events[-1]["stage"] == "complete"


def test_build_augmentation_sidecar_uses_d405_depth_profile_for_wrist_camera(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    depth = np.full((12, 12), 360, dtype=np.uint16)
    depth[3:9, 3:9] = 300
    _write_single_camera_rendered_source(dataset, camera="wrist", depth=depth, camera_model="Intel RealSense D405")
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=31,
        cameras=["wrist"],
        augmentation_profile="sim2real",
        image_augmentation_enabled=True,
        photometric_enabled=False,
        sensor_noise_enabled=False,
        depth_noise_enabled=True,
        render_domain_enabled=False,
        camera_pose_enabled=False,
        depth_strength=1.0,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    depth_params = row["depth_augmentations_by_camera"]["wrist"]
    depth_out = np.asarray(Image.open(row["image_outputs"]["wrist"]["depth_path"]))

    assert summary["depth_sensor_profiles"]["wrist"] == "d405_close_range"
    assert row["depth_sensor_profiles"]["wrist"] == "d405_close_range"
    assert depth_params["profile"] == "d405_close_range"
    assert {"edge_dropout_prob", "dark_surface_dropout_prob", "close_range_noise_mm"} <= set(depth_params)
    assert depth_out.dtype == np.uint16
    assert depth_out.max() <= 65535
    assert np.count_nonzero(depth_out) > 0
    assert not np.array_equal(depth_out, depth)
    assert Path(row["image_outputs"]["wrist"]["source_depth_preview_path"]).is_file()
    assert Path(row["image_outputs"]["wrist"]["depth_preview_path"]).is_file()


def test_build_augmentation_sidecar_records_default_depth_profiles_per_camera(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=37,
        cameras=["top", "front", "right"],
        image_augmentation_enabled=True,
        depth_noise_enabled=True,
        camera_pose_enabled=False,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    row = _read_single_variant(output_dir)

    assert summary["depth_sensor_profiles"] == {
        "top": "d455f_fallback",
        "front": "generic_realsense",
        "right": "generic_realsense",
    }
    assert row["depth_sensor_profiles"] == summary["depth_sensor_profiles"]


def test_build_augmentation_sidecar_clips_object_jitter_inside_a4_bounds(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    source_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_a4_clip"
    source_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = source_dir / "rgb.png"
    depth_path = source_dir / "depth.png"
    Image.fromarray(np.full((8, 8, 3), 127, dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.full((8, 8), 430, dtype=np.uint16)).save(depth_path)
    _write_rendered_source_with_files(
        dataset,
        files=[
            {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
        specimen_pose={
            "a4_xy_mm": [170.0, 250.0],
            "yaw_deg": 5.0,
            "confidence": 0.95,
            "orientation_confidence": 0.95,
            "orientation_source": "active_robot_cam",
        },
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=41,
        cameras=["top"],
        image_augmentation_enabled=True,
        render_domain_enabled=True,
        camera_pose_enabled=False,
    )

    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    render_domain = row["render_domain_augmentations"]
    x_mm, y_mm = render_domain["object_a4_xy_mm"]

    assert row["qa_ok"] is True
    assert row["source_pose_confidence"] == 0.95
    assert row["orientation_source"] == "active_robot_cam"
    assert 0.0 <= x_mm <= 170.0
    assert 0.0 <= y_mm <= 250.0
    assert render_domain["object_xy_jitter_mm"][0] <= 0.0
    assert render_domain["object_xy_jitter_mm"][1] <= 0.0


def test_build_augmentation_sidecar_disables_yaw_when_orientation_confidence_is_low(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    source_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_low_yaw"
    source_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = source_dir / "rgb.png"
    depth_path = source_dir / "depth.png"
    Image.fromarray(np.full((8, 8, 3), 127, dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.full((8, 8), 430, dtype=np.uint16)).save(depth_path)
    _write_rendered_source_with_files(
        dataset,
        files=[
            {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
        specimen_pose={
            "a4_xy_mm": [100.0, 140.0],
            "yaw_deg": 22.0,
            "confidence": 0.9,
            "orientation_confidence": 0.2,
            "orientation_source": "pca",
        },
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=43,
        cameras=["top"],
        image_augmentation_enabled=True,
        render_domain_enabled=True,
        camera_pose_enabled=False,
    )

    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])

    assert row["source_pose_confidence"] == 0.9
    assert row["orientation_source"] == "disabled_low_confidence"
    assert "object_yaw_jitter_deg" not in row["render_domain_augmentations"]
    assert row["render_domain_augmentations"]["orientation_source"] == "disabled_low_confidence"


def test_build_augmentation_sidecar_writes_manifest_qa_for_valid_variants(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=19,
        cameras=["top"],
        augmentation_profile="sim2real",
        image_augmentation_enabled=True,
        photometric_enabled=True,
        sensor_noise_enabled=True,
        depth_noise_enabled=True,
    )

    qa_summary = json.loads((output_dir / "qa_summary.json").read_text(encoding="utf-8"))
    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    assert result["qa_summary_path"] == str(output_dir / "qa_summary.json")
    assert result["valid_variant_count"] == 1
    assert result["failed_variant_count"] == 0
    assert qa_summary["total_count"] == 1
    assert qa_summary["passed_count"] == 1
    assert qa_summary["failed_count"] == 0
    assert qa_summary["failure_counts"] == {}
    assert row["qa_ok"] is True
    assert row["qa_failure_code"] == ""
    assert row["rgb_exists"] is True
    assert row["depth_exists"] is True
    assert row["depth_valid_ratio"] > 0.95


def test_build_augmentation_sidecar_marks_variants_without_required_images_as_failed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_meta"
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "status": "metadata_only",
                "attempt_id": "attempt_meta",
                "episode_index": 0,
                "frame_index": 3,
                "cameras": ["top"],
                "output_dir": str(render_dir),
                "files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=7,
        cameras=["top"],
        image_augmentation_enabled=True,
        camera_pose_enabled=True,
    )

    qa_summary = json.loads((output_dir / "qa_summary.json").read_text(encoding="utf-8"))
    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    assert result["valid_variant_count"] == 0
    assert result["failed_variant_count"] == 1
    assert qa_summary["passed_count"] == 0
    assert qa_summary["failed_count"] == 1
    assert qa_summary["failure_counts"] == {"MISSING_AUGMENTED_RGB": 1}
    assert row["qa_ok"] is False
    assert row["qa_failure_code"] == "MISSING_AUGMENTED_RGB"
    assert row["rgb_exists"] is False
    assert row["depth_exists"] is False
    assert row["depth_valid_ratio"] == 0.0


def test_build_augmentation_sidecar_marks_missing_depth_as_failed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    source_dir = dataset / "source"
    source_dir.mkdir(parents=True)
    rgb_path = source_dir / "rgb.png"
    Image.fromarray(np.full((8, 8, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    _write_rendered_source_with_files(
        dataset,
        files=[{"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"}],
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=20,
        cameras=["top"],
        image_augmentation_enabled=True,
        photometric_enabled=True,
        depth_noise_enabled=True,
    )

    qa_summary = json.loads((output_dir / "qa_summary.json").read_text(encoding="utf-8"))
    row = _read_single_variant(output_dir)
    assert result["valid_variant_count"] == 0
    assert result["failed_variant_count"] == 1
    assert qa_summary["failure_counts"] == {"MISSING_AUGMENTED_DEPTH": 1}
    assert row["qa_ok"] is False
    assert row["qa_failure_code"] == "MISSING_AUGMENTED_DEPTH"
    assert row["rgb_exists"] is True
    assert row["depth_exists"] is False


def test_build_augmentation_sidecar_marks_invalid_depth_as_failed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    source_dir = dataset / "source"
    source_dir.mkdir(parents=True)
    rgb_path = source_dir / "rgb.png"
    depth_path = source_dir / "depth.png"
    Image.fromarray(np.full((8, 8, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.zeros((8, 8), dtype=np.uint16)).save(depth_path)
    _write_rendered_source_with_files(
        dataset,
        files=[
            {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=21,
        cameras=["top"],
        image_augmentation_enabled=True,
        photometric_enabled=True,
        depth_noise_enabled=True,
        depth_strength=0.0,
    )

    qa_summary = json.loads((output_dir / "qa_summary.json").read_text(encoding="utf-8"))
    row = _read_single_variant(output_dir)
    assert result["valid_variant_count"] == 0
    assert result["failed_variant_count"] == 1
    assert qa_summary["failure_counts"] == {"INVALID_AUGMENTED_DEPTH": 1}
    assert row["qa_ok"] is False
    assert row["qa_failure_code"] == "INVALID_AUGMENTED_DEPTH"
    assert row["rgb_exists"] is True
    assert row["depth_exists"] is True
    assert row["depth_valid_ratio"] == 0.0


def test_build_augmentation_sidecar_marks_out_of_a4_source_pose_as_failed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    source_dir = dataset / "source"
    source_dir.mkdir(parents=True)
    rgb_path = source_dir / "rgb.png"
    depth_path = source_dir / "depth.png"
    Image.fromarray(np.full((8, 8, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.full((8, 8), 430, dtype=np.uint16)).save(depth_path)
    _write_rendered_source_with_files(
        dataset,
        files=[
            {"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
            {"camera": "top", "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
        ],
        specimen_pose={"a4_xy_mm": [180.0, 120.0], "yaw_deg": 0.0, "confidence": 0.95},
    )
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=22,
        cameras=["top"],
        image_augmentation_enabled=True,
        photometric_enabled=True,
        depth_noise_enabled=True,
        render_domain_enabled=True,
        camera_pose_enabled=True,
    )

    qa_summary = json.loads((output_dir / "qa_summary.json").read_text(encoding="utf-8"))
    row = _read_single_variant(output_dir)
    assert result["valid_variant_count"] == 0
    assert result["failed_variant_count"] == 1
    assert qa_summary["failure_counts"] == {"SOURCE_POSE_OUT_OF_A4_BOUNDS": 1}
    assert row["qa_ok"] is False
    assert row["qa_failure_code"] == "SOURCE_POSE_OUT_OF_A4_BOUNDS"
    assert row["source_pose"]["a4_xy_mm"] == [180.0, 120.0]


def test_build_augmentation_sidecar_can_disable_each_augmentation_family(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    _write_rendered_source(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=output_dir,
        variants_per_frame=1,
        max_source_frames=1,
        seed=321,
        cameras=["top"],
        augmentation_profile="conservative",
        photometric_enabled=False,
        sensor_noise_enabled=False,
        depth_noise_enabled=False,
        render_domain_enabled=False,
        camera_pose_enabled=False,
        rgb_strength=0.25,
        depth_strength=0.25,
        render_domain_strength=0.25,
        camera_pose_strength=0.25,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    assert result["ok"] is True
    assert summary["augmentation_profile"] == "conservative"
    assert summary["common_augmentation_families"] == []
    assert summary["augmentation_options"] == {
        "photometric_enabled": False,
        "sensor_noise_enabled": False,
        "depth_noise_enabled": False,
        "render_domain_enabled": False,
        "camera_pose_enabled": False,
        "rgb_strength": 0.25,
        "depth_strength": 0.25,
        "render_domain_strength": 0.25,
        "camera_pose_strength": 0.25,
    }
    assert row["family_mask"] == {
        "photometric": False,
        "sensor_noise": False,
        "depth_noise": False,
        "render_domain": False,
        "camera_pose": False,
    }
    assert row["image_augmentations"] == {}
    assert row["depth_augmentations"] == {}
    assert row["render_domain_augmentations"] == {}
    assert row["render_request"]["camera_specs"] == {}
    assert row["image_outputs"] == {}


def test_build_augmentation_sidecar_keeps_render_metadata_when_images_are_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_meta"
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "status": "metadata_only",
                "attempt_id": "attempt_meta",
                "episode_index": 0,
                "frame_index": 3,
                "cameras": ["top"],
                "output_dir": str(render_dir),
                "files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_augmentation_sidecar(
        dataset_path=dataset,
        output_dir=dataset / "sidecar" / "isaac_augmentation" / "latest",
        variants_per_frame=1,
        max_source_frames=1,
        seed=7,
        cameras=["top"],
        image_augmentation_enabled=True,
        camera_pose_enabled=True,
    )

    row = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()[0])
    assert result["ok"] is True
    assert row["image_outputs"] == {}
    assert row["render_request"]["camera_specs"]["top"]["position"] != [0.315, 0.265, 0.62]
