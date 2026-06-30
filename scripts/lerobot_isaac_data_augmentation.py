"""Build Isaac Sim data-augmentation sidecars for LeRobot recordings.

The runner keeps the recorded LeRobot dataset immutable. It reads Isaac RGB-D
render manifests and writes deterministic augmentation metadata under
``sidecar/isaac_augmentation``. When rendered RGB/depth files are present it
also writes augmented image copies for inspection or later dataset mixing.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


DEFAULT_CAMERA_SPECS: dict[str, dict[str, Any]] = {
    "top": {"position": [0.315, 0.205, 0.72], "look_at": [0.315, 0.265, 0.0]},
    "front": {"position": [0.36, 0.96, 0.52], "look_at": [0.36, 0.28, 0.025], "focal_length": 14.0},
    "right": {"position": [0.86, 0.58, 0.52], "look_at": [0.38, 0.24, 0.02], "focal_length": 10.0},
    "wrist": {"position": [0.19, 0.08, 0.28], "look_at": [0.36, 0.28, 0.02]},
}
FALLBACK_CAMERA_SPEC = {"position": [0.42, -0.08, 0.42], "look_at": [0.315, 0.265, 0.0]}
AUGMENTATION_RECIPE_VERSION = "standard_sim2real_v2"
DOMAIN_RANDOMIZATION_VERSION = "sim2real_domain_randomization_v1"
AUGMENTATION_PROFILES: dict[str, dict[str, float]] = {
    "conservative": {
        "rgb_strength": 0.65,
        "depth_strength": 0.55,
        "render_domain_strength": 0.55,
        "camera_pose_strength": 0.55,
    },
    "sim2real": {
        "rgb_strength": 1.0,
        "depth_strength": 1.0,
        "render_domain_strength": 1.0,
        "camera_pose_strength": 1.0,
    },
    "stress": {
        "rgb_strength": 1.35,
        "depth_strength": 1.3,
        "render_domain_strength": 1.35,
        "camera_pose_strength": 1.25,
    },
}
DEPTH_SENSOR_PROFILES: dict[str, dict[str, float]] = {
    "generic_realsense": {
        "scale_radius": 0.003,
        "bias_mm": 1.0,
        "noise_mm": 1.5,
        "dropout_prob": 0.001,
        "edge_dropout_prob": 0.004,
        "edge_kernel_px": 1.0,
        "dark_surface_dropout_prob": 0.001,
        "close_range_noise_mm": 0.8,
        "close_range_threshold_mm": 450.0,
        "quantization_mm": 3.0,
    },
    "d455f_fallback": {
        "scale_radius": 0.004,
        "bias_mm": 1.6,
        "noise_mm": 2.4,
        "dropout_prob": 0.002,
        "edge_dropout_prob": 0.006,
        "edge_kernel_px": 1.0,
        "dark_surface_dropout_prob": 0.002,
        "close_range_noise_mm": 1.2,
        "close_range_threshold_mm": 520.0,
        "quantization_mm": 4.0,
    },
    "d405_close_range": {
        "scale_radius": 0.008,
        "bias_mm": 3.0,
        "noise_mm": 5.0,
        "dropout_prob": 0.022,
        "edge_dropout_prob": 0.055,
        "edge_kernel_px": 2.0,
        "dark_surface_dropout_prob": 0.018,
        "close_range_noise_mm": 4.0,
        "close_range_threshold_mm": 430.0,
        "quantization_mm": 6.0,
    },
}
FAMILY_ORDER = ["photometric", "sensor_noise", "depth_noise", "render_domain", "camera_pose"]
QA_DEPTH_VALID_RATIO_MIN = 0.01
ORIENTATION_CONFIDENCE_MIN = 0.5
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _safe_float(
    value: Any,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    digits: int = 6,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return round(parsed, digits)


def _camera_list(value: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value or [])
    cameras: list[str] = []
    for item in items:
        camera = str(item or "").strip()
        if camera and camera not in cameras:
            cameras.append(camera)
    return cameras or ["wrist", "top"]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _resolve_file_path(raw_path: Any, *, dataset_path: Path, manifest_path: Path) -> Path | None:
    clean = str(raw_path or "").strip()
    if not clean:
        return None
    path = Path(clean).expanduser()
    candidates = [path] if path.is_absolute() else [manifest_path.parent / path, dataset_path / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _source_frames(dataset_path: Path, cameras: list[str], max_source_frames: int) -> list[dict[str, Any]]:
    selected_cameras = set(cameras)
    by_key: dict[tuple[str, int, int], dict[str, Any]] = {}
    manifest_paths = sorted((dataset_path / "sidecar" / "isaac_rgbd").glob("**/manifest.jsonl"))
    for manifest_path in manifest_paths:
        for row in _read_jsonl(manifest_path):
            row_cameras = [camera for camera in _camera_list(row.get("cameras")) if camera in selected_cameras]
            if not row_cameras:
                continue
            attempt_id = str(row.get("attempt_id") or manifest_path.parent.name)
            episode_index = _safe_int(row.get("episode_index"), 0, minimum=0)
            frame_index = _safe_int(row.get("frame_index"), _safe_int(row.get("sample_index"), 0, minimum=0), minimum=0)
            files: dict[str, dict[str, Path]] = {}
            if isinstance(row.get("files"), list):
                for file_info in row["files"]:
                    if not isinstance(file_info, dict):
                        continue
                    camera = str(file_info.get("camera") or "").strip()
                    if camera not in selected_cameras:
                        continue
                    kind = str(file_info.get("kind") or "").strip()
                    if kind not in {"rgb", "depth"}:
                        continue
                    resolved = _resolve_file_path(file_info.get("path"), dataset_path=dataset_path, manifest_path=manifest_path)
                    if resolved is not None:
                        files.setdefault(camera, {})[kind] = resolved
            key = (attempt_id, episode_index, frame_index)
            source = {
                "source_id": f"{attempt_id}:e{episode_index:03d}:f{frame_index:06d}",
                "manifest_path": str(manifest_path),
                "row": row,
                "attempt_id": attempt_id,
                "episode_index": episode_index,
                "frame_index": frame_index,
                "sample_index": row.get("sample_index"),
                "record_timestamp": str(row.get("record_timestamp") or ""),
                "target_fps": row.get("target_fps", 15.0),
                "cameras": row_cameras,
                "files": files,
                "has_images": bool(files),
            }
            current = by_key.get(key)
            if current is None or (not current.get("has_images") and source["has_images"]):
                by_key[key] = source
    frames = sorted(by_key.values(), key=lambda item: (int(item["episode_index"]), int(item["frame_index"]), str(item["attempt_id"])))
    return frames[: max(1, max_source_frames)]


def _raw_depth_camera_hints(dataset_path: Path) -> dict[str, str]:
    hints: dict[str, str] = {}
    for manifest_path in (
        dataset_path / "sidecar" / "raw_depth" / "transform_manifest.json",
        dataset_path / "sidecar" / "depth_raw" / "transform_manifest.json",
        dataset_path / "sidecar" / "raw_depth" / "manifest.json",
    ):
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        for field in ("camera_models", "camera_model", "camera_names", "camera_serials", "camera_devices"):
            values = manifest.get(field)
            if isinstance(values, dict):
                for camera, value in values.items():
                    if str(camera).strip():
                        hints[str(camera).strip()] = f"{hints.get(str(camera).strip(), '')} {value}".strip()
        camera_keys = manifest.get("camera_keys") if isinstance(manifest.get("camera_keys"), list) else []
        for camera in camera_keys:
            clean = str(camera or "").strip()
            if clean and clean not in hints:
                hints[clean] = clean
    return hints


def _depth_sensor_profile(camera: str, hints: dict[str, str]) -> str:
    clean = str(camera or "").strip().lower()
    hint = str(hints.get(str(camera or "").strip()) or "").lower()
    text = f"{clean} {hint}"
    if "d405" in text or "405" in text or "wrist" in text:
        return "d405_close_range"
    if "d455" in text or "455" in text or clean == "top":
        return "d455f_fallback"
    return "generic_realsense"


def _depth_sensor_profiles(dataset_path: Path, cameras: list[str]) -> dict[str, str]:
    hints = _raw_depth_camera_hints(dataset_path)
    return {camera: _depth_sensor_profile(camera, hints) for camera in cameras}


def _uniform(rng: random.Random, low: float, high: float, digits: int = 6) -> float:
    return round(rng.uniform(low, high), digits)


def _clean_profile(value: str | None) -> str:
    profile = str(value or "conservative").strip().lower()
    return profile if profile in AUGMENTATION_PROFILES else "conservative"


def _augmentation_options(
    *,
    augmentation_profile: str | None,
    image_augmentation_enabled: bool,
    photometric_enabled: bool,
    sensor_noise_enabled: bool,
    depth_noise_enabled: bool,
    render_domain_enabled: bool,
    camera_pose_enabled: bool,
    rgb_strength: float | None,
    depth_strength: float | None,
    render_domain_strength: float | None,
    camera_pose_strength: float | None,
) -> dict[str, Any]:
    profile = _clean_profile(augmentation_profile)
    return {
        "profile": profile,
        "photometric_enabled": bool(image_augmentation_enabled and photometric_enabled),
        "sensor_noise_enabled": bool(image_augmentation_enabled and sensor_noise_enabled),
        "depth_noise_enabled": bool(image_augmentation_enabled and depth_noise_enabled),
        "render_domain_enabled": bool(render_domain_enabled),
        "camera_pose_enabled": bool(camera_pose_enabled),
        "rgb_strength": _safe_float(rgb_strength, 1.0, minimum=0.0, maximum=2.0),
        "depth_strength": _safe_float(depth_strength, 1.0, minimum=0.0, maximum=2.0),
        "render_domain_strength": _safe_float(render_domain_strength, 1.0, minimum=0.0, maximum=2.0),
        "camera_pose_strength": _safe_float(camera_pose_strength, 1.0, minimum=0.0, maximum=2.0),
    }


def _effective_strengths(options: dict[str, Any]) -> dict[str, float]:
    profile = _clean_profile(str(options.get("profile") or "conservative"))
    profile_strengths = AUGMENTATION_PROFILES[profile]
    return {
        "rgb_strength": round(float(options["rgb_strength"]) * profile_strengths["rgb_strength"], 6),
        "depth_strength": round(float(options["depth_strength"]) * profile_strengths["depth_strength"], 6),
        "render_domain_strength": round(float(options["render_domain_strength"]) * profile_strengths["render_domain_strength"], 6),
        "camera_pose_strength": round(float(options["camera_pose_strength"]) * profile_strengths["camera_pose_strength"], 6),
    }


def _family_mask(options: dict[str, Any]) -> dict[str, bool]:
    return {
        "photometric": bool(options.get("photometric_enabled")),
        "sensor_noise": bool(options.get("sensor_noise_enabled")),
        "depth_noise": bool(options.get("depth_noise_enabled")),
        "render_domain": bool(options.get("render_domain_enabled")),
        "camera_pose": bool(options.get("camera_pose_enabled")),
    }


def _families_from_mask(mask: dict[str, bool]) -> list[str]:
    return [family for family in FAMILY_ORDER if mask.get(family)]


def _centered_uniform(rng: random.Random, center: float, radius: float, strength: float, digits: int = 6) -> float:
    scaled = max(0.0, radius * strength)
    return _uniform(rng, center - scaled, center + scaled, digits)


def _nonnegative_uniform(rng: random.Random, high: float, strength: float, digits: int = 6) -> float:
    return _uniform(rng, 0.0, max(0.0, high * strength), digits)


def _augmentation_recipe(options: dict[str, Any]) -> dict[str, Any]:
    effective = _effective_strengths(options)
    return {
        "version": AUGMENTATION_RECIPE_VERSION,
        "profile": options["profile"],
        "profile_strength_multipliers": AUGMENTATION_PROFILES[options["profile"]],
        "effective_strengths": effective,
        "ranges": {
            "photometric": {
                "brightness": [round(1.0 - 0.28 * effective["rgb_strength"], 6), round(1.0 + 0.28 * effective["rgb_strength"], 6)],
                "contrast": [round(1.0 - 0.28 * effective["rgb_strength"], 6), round(1.0 + 0.35 * effective["rgb_strength"], 6)],
                "saturation": [round(1.0 - 0.35 * effective["rgb_strength"], 6), round(1.0 + 0.45 * effective["rgb_strength"], 6)],
                "gamma": [round(1.0 - 0.22 * effective["rgb_strength"], 6), round(1.0 + 0.22 * effective["rgb_strength"], 6)],
                "hue_shift_deg": [round(-4.0 * effective["rgb_strength"], 6), round(4.0 * effective["rgb_strength"], 6)],
                "channel_gains": [round(1.0 - 0.055 * effective["rgb_strength"], 6), round(1.0 + 0.055 * effective["rgb_strength"], 6)],
            },
            "sensor_noise": {
                "blur_radius": [0.0, round(1.1 * effective["rgb_strength"], 6)],
                "gaussian_noise_std": [0.0, round(0.025 * effective["rgb_strength"], 6)],
                "jpeg_quality": [max(70, int(round(100 - 14 * effective["rgb_strength"]))), 100],
            },
            "depth_noise": {
                "scale": [round(1.0 - 0.005 * effective["depth_strength"], 6), round(1.0 + 0.005 * effective["depth_strength"], 6)],
                "bias_mm": [round(-2.0 * effective["depth_strength"], 6), round(2.0 * effective["depth_strength"], 6)],
                "noise_mm": [0.0, round(3.0 * effective["depth_strength"], 6)],
                "dropout_prob": [0.0, round(0.012 * effective["depth_strength"], 6)],
                "quantization_mm": [1.0, round(4.0 * effective["depth_strength"], 6)],
            },
            "render_domain": {
                "object_xy_jitter_mm": [round(-5.0 * effective["render_domain_strength"], 6), round(5.0 * effective["render_domain_strength"], 6)],
                "object_yaw_jitter_deg": [round(-8.0 * effective["render_domain_strength"], 6), round(8.0 * effective["render_domain_strength"], 6)],
                "light_intensity_scale": [round(1.0 - 0.35 * effective["render_domain_strength"], 6), round(1.0 + 0.55 * effective["render_domain_strength"], 6)],
                "light_color_temperature_shift_k": [round(-650.0 * effective["render_domain_strength"], 6), round(650.0 * effective["render_domain_strength"], 6)],
                "lighting.shadow_softness_scale": [round(1.0 - 0.3 * effective["render_domain_strength"], 6), round(1.0 + 0.45 * effective["render_domain_strength"], 6)],
                "specimen_material.albedo_scale": [round(1.0 - 0.12 * effective["render_domain_strength"], 6), round(1.0 + 0.12 * effective["render_domain_strength"], 6)],
                "table_material.albedo_scale": [round(1.0 - 0.08 * effective["render_domain_strength"], 6), round(1.0 + 0.08 * effective["render_domain_strength"], 6)],
                "gripper_pad_material.friction": [round(max(0.2, 1.0 - 0.25 * effective["render_domain_strength"]), 6), round(1.0 + 0.4 * effective["render_domain_strength"], 6)],
                "specimen_physics.mass_scale": [round(max(0.5, 1.0 - 0.2 * effective["render_domain_strength"]), 6), round(1.0 + 0.25 * effective["render_domain_strength"], 6)],
                "specimen_physics.contact_offset_scale": [round(max(0.5, 1.0 - 0.2 * effective["render_domain_strength"]), 6), round(1.0 + 0.25 * effective["render_domain_strength"], 6)],
            },
            "camera_pose": {
                "position_m": "camera-specific base range multiplied by camera_pose_strength",
                "look_at_m": "camera-specific base range multiplied by camera_pose_strength",
            },
        },
    }


def _augmentation_params(rng: random.Random, options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    effective = _effective_strengths(options)
    image: dict[str, Any] = {}
    if options["photometric_enabled"]:
        rgb_strength = effective["rgb_strength"]
        image.update(
            {
                "brightness": _centered_uniform(rng, 1.0, 0.28, rgb_strength, 4),
                "contrast": _uniform(rng, 1.0 - 0.28 * rgb_strength, 1.0 + 0.35 * rgb_strength, 4),
                "saturation": _uniform(rng, 1.0 - 0.35 * rgb_strength, 1.0 + 0.45 * rgb_strength, 4),
                "gamma": _centered_uniform(rng, 1.0, 0.22, rgb_strength, 4),
                "hue_shift_deg": _centered_uniform(rng, 0.0, 4.0, rgb_strength, 4),
                "channel_gains": [_centered_uniform(rng, 1.0, 0.055, rgb_strength, 5) for _ in range(3)],
            }
        )
    if options["sensor_noise_enabled"]:
        rgb_strength = effective["rgb_strength"]
        image.update(
            {
                "blur_radius": _nonnegative_uniform(rng, 1.1, rgb_strength, 4),
                "gaussian_noise_std": _nonnegative_uniform(rng, 0.025, rgb_strength, 5),
                "jpeg_quality": _safe_int(round(_uniform(rng, max(70, 100 - 14 * rgb_strength), 100, 3)), 95, minimum=70),
            }
        )
    depth: dict[str, Any] = {}
    if options["depth_noise_enabled"]:
        depth_strength = effective["depth_strength"]
        depth.update(
            {
                "scale": _centered_uniform(rng, 1.0, 0.005, depth_strength, 5),
                "bias_mm": _centered_uniform(rng, 0.0, 2.0, depth_strength, 4),
                "noise_mm": _nonnegative_uniform(rng, 3.0, depth_strength, 4),
                "dropout_prob": _nonnegative_uniform(rng, 0.012, depth_strength, 5),
                "hole_kernel_px": _safe_int(round(_nonnegative_uniform(rng, 2.0, depth_strength, 4)), 0, minimum=0),
                "quantization_mm": max(1.0, _nonnegative_uniform(rng, 4.0, depth_strength, 4)),
                "clip_min_mm": 0.0,
                "clip_max_mm": 65535.0,
            }
        )
    render_domain: dict[str, Any] = {}
    if options["render_domain_enabled"]:
        render_strength = effective["render_domain_strength"]
        light_intensity = _uniform(rng, 1.0 - 0.35 * render_strength, 1.0 + 0.55 * render_strength, 4)
        light_temperature_shift = _centered_uniform(rng, 0.0, 650.0, render_strength, 2)
        roughness = _uniform(rng, max(0.05, 0.55 - 0.1 * render_strength), min(1.0, 0.8 + 0.18 * render_strength), 4)
        specular = _uniform(rng, max(0.0, 1.0 - 0.45 * render_strength), 1.0 + 0.35 * render_strength, 4)
        pad_static_friction = _uniform(rng, max(0.2, 1.2 - 0.25 * render_strength), 1.2 + 0.4 * render_strength, 4)
        pad_dynamic_friction = _uniform(rng, max(0.2, 1.0 - 0.2 * render_strength), 1.0 + 0.32 * render_strength, 4)
        specimen_static_friction = _uniform(rng, max(0.2, 0.9 - 0.18 * render_strength), 0.9 + 0.28 * render_strength, 4)
        specimen_dynamic_friction = _uniform(rng, max(0.2, 0.7 - 0.15 * render_strength), 0.7 + 0.24 * render_strength, 4)
        render_domain.update(
            {
                "object_xy_jitter_mm": [
                    _centered_uniform(rng, 0.0, 5.0, render_strength, 4),
                    _centered_uniform(rng, 0.0, 5.0, render_strength, 4),
                ],
                "object_yaw_jitter_deg": _centered_uniform(rng, 0.0, 8.0, render_strength, 4),
                "light_intensity_scale": light_intensity,
                "light_color_temperature_shift_k": light_temperature_shift,
                "material_roughness": roughness,
                "surface_specular_scale": specular,
                "lighting": {
                    "intensity_scale": light_intensity,
                    "color_temperature_shift_k": light_temperature_shift,
                    "shadow_softness_scale": _uniform(rng, max(0.2, 1.0 - 0.3 * render_strength), 1.0 + 0.45 * render_strength, 4),
                },
                "specimen_material": {
                    "albedo_scale": [_centered_uniform(rng, 1.0, 0.12, render_strength, 4) for _ in range(3)],
                    "roughness": roughness,
                    "specular_scale": specular,
                },
                "table_material": {
                    "albedo_scale": [_centered_uniform(rng, 1.0, 0.08, render_strength, 4) for _ in range(3)],
                    "roughness": _uniform(rng, max(0.05, 0.65 - 0.08 * render_strength), min(1.0, 0.9 + 0.08 * render_strength), 4),
                },
                "gripper_pad_material": {
                    "static_friction": pad_static_friction,
                    "dynamic_friction": pad_dynamic_friction,
                },
                "specimen_physics": {
                    "mass_scale": _uniform(rng, max(0.5, 1.0 - 0.2 * render_strength), 1.0 + 0.25 * render_strength, 4),
                    "static_friction": specimen_static_friction,
                    "dynamic_friction": specimen_dynamic_friction,
                    "contact_offset_scale": _uniform(rng, max(0.5, 1.0 - 0.2 * render_strength), 1.0 + 0.25 * render_strength, 4),
                },
            }
        )
    return image, depth, render_domain


def _depth_params_for_camera(
    base_params: dict[str, Any],
    *,
    profile: str,
    rng: random.Random,
    strength: float,
) -> dict[str, Any]:
    if not base_params:
        return {}
    profile_name = profile if profile in DEPTH_SENSOR_PROFILES else "generic_realsense"
    profile_params = DEPTH_SENSOR_PROFILES[profile_name]
    params = dict(base_params)
    params["profile"] = profile_name
    scale_jitter = _centered_uniform(rng, 1.0, profile_params["scale_radius"], strength, 6)
    params["scale"] = round(float(params.get("scale") or 1.0) * scale_jitter, 6)
    params["bias_mm"] = round(float(params.get("bias_mm") or 0.0) + _centered_uniform(rng, 0.0, profile_params["bias_mm"], strength, 4), 4)
    params["noise_mm"] = round(float(params.get("noise_mm") or 0.0) + _nonnegative_uniform(rng, profile_params["noise_mm"], strength, 4), 4)
    params["dropout_prob"] = round(min(0.9, float(params.get("dropout_prob") or 0.0) + _nonnegative_uniform(rng, profile_params["dropout_prob"], strength, 5)), 6)
    params["quantization_mm"] = max(float(params.get("quantization_mm") or 1.0), _nonnegative_uniform(rng, profile_params["quantization_mm"], strength, 4), 1.0)
    params["edge_dropout_prob"] = _nonnegative_uniform(rng, profile_params["edge_dropout_prob"], strength, 5)
    params["edge_kernel_px"] = _safe_int(round(_nonnegative_uniform(rng, profile_params["edge_kernel_px"], strength, 4)), 0, minimum=0)
    params["dark_surface_dropout_prob"] = _nonnegative_uniform(rng, profile_params["dark_surface_dropout_prob"], strength, 5)
    params["close_range_noise_mm"] = _nonnegative_uniform(rng, profile_params["close_range_noise_mm"], strength, 4)
    params["close_range_threshold_mm"] = round(float(profile_params["close_range_threshold_mm"]), 4)
    if profile_name != "d405_close_range":
        params["dropout_prob"] = min(float(params.get("dropout_prob") or 0.0), round(0.004 * strength, 6))
        params["hole_kernel_px"] = 0
    return params


def _depth_params_by_camera(
    cameras: list[str],
    profiles: dict[str, str],
    base_params: dict[str, Any],
    *,
    rng: random.Random,
    strength: float,
) -> dict[str, dict[str, Any]]:
    if not base_params:
        return {}
    return {
        camera: _depth_params_for_camera(base_params, profile=profiles.get(camera, "generic_realsense"), rng=rng, strength=strength)
        for camera in cameras
    }


def _jitter_camera_spec(camera: str, rng: random.Random, strength: float) -> dict[str, list[float]]:
    base = DEFAULT_CAMERA_SPECS.get(camera, FALLBACK_CAMERA_SPEC)
    pos_range = (0.015, 0.015, 0.025) if camera == "top" else (0.012, 0.012, 0.014)
    look_range = (0.012, 0.012, 0.004) if camera == "top" else (0.014, 0.014, 0.01)
    position = [round(float(value) + rng.uniform(-pos_range[idx] * strength, pos_range[idx] * strength), 6) for idx, value in enumerate(base["position"])]
    look_at = [round(float(value) + rng.uniform(-look_range[idx] * strength, look_range[idx] * strength), 6) for idx, value in enumerate(base["look_at"])]
    spec: dict[str, Any] = {"position": position, "look_at": look_at}
    if "focal_length" in base:
        spec["focal_length"] = float(base["focal_length"])
    return spec


def _apply_rgb_augmentation(src: Path, dst: Path, params: dict[str, Any], np_rng: np.random.Generator) -> None:
    image = Image.open(src).convert("RGB")
    if "brightness" in params:
        image = ImageEnhance.Brightness(image).enhance(float(params["brightness"]))
    if "contrast" in params:
        image = ImageEnhance.Contrast(image).enhance(float(params["contrast"]))
    if "saturation" in params:
        image = ImageEnhance.Color(image).enhance(float(params["saturation"]))
    if "gamma" in params:
        gamma = max(0.05, float(params["gamma"]))
        lut = [min(255, max(0, int(((value / 255.0) ** gamma) * 255.0))) for value in range(256)]
        image = image.point(lut * 3)
    hue_shift = float(params.get("hue_shift_deg") or 0.0)
    if abs(hue_shift) > 0.001:
        hsv = image.convert("HSV")
        hsv_array = np.asarray(hsv).copy()
        hsv_array[..., 0] = (hsv_array[..., 0].astype(np.int16) + int(round(hue_shift / 360.0 * 255.0))) % 256
        image = Image.fromarray(hsv_array.astype(np.uint8), mode="HSV").convert("RGB")
    if float(params.get("blur_radius") or 0.0) > 0.05:
        image = image.filter(ImageFilter.GaussianBlur(radius=float(params["blur_radius"])))
    array = np.asarray(image).astype(np.float32)
    channel_gains = params.get("channel_gains")
    if isinstance(channel_gains, list) and len(channel_gains) == 3:
        array *= np.asarray([float(item) for item in channel_gains], dtype=np.float32).reshape(1, 1, 3)
    noise_std = float(params.get("gaussian_noise_std") or 0.0) * 255.0
    if noise_std > 0.0:
        array += np_rng.normal(0.0, noise_std, size=array.shape)
    image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGB")
    jpeg_quality = int(params.get("jpeg_quality") or 100)
    if jpeg_quality < 100:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=max(70, min(100, jpeg_quality)))
        buffer.seek(0)
        image = Image.open(buffer).convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    image.save(dst)


def _apply_depth_augmentation(src: Path, dst: Path, params: dict[str, Any], np_rng: np.random.Generator) -> None:
    depth = np.asarray(Image.open(src))
    depth = depth.astype(np.float32)
    depth *= float(params.get("scale") or 1.0)
    depth += float(params.get("bias_mm") or 0.0)
    noise_mm = float(params.get("noise_mm") or 0.0)
    if noise_mm > 0.0:
        depth += np_rng.normal(0.0, noise_mm, size=depth.shape)
    close_range_noise_mm = float(params.get("close_range_noise_mm") or 0.0)
    close_range_threshold_mm = float(params.get("close_range_threshold_mm") or 0.0)
    if close_range_noise_mm > 0.0 and close_range_threshold_mm > 0.0:
        close_mask = (depth > 0.0) & (depth <= close_range_threshold_mm)
        if np.any(close_mask):
            depth[close_mask] += np_rng.normal(0.0, close_range_noise_mm, size=int(np.count_nonzero(close_mask)))
    dropout_prob = float(params.get("dropout_prob") or 0.0)
    if dropout_prob > 0.0:
        dropout = np_rng.random(depth.shape) < dropout_prob
        hole_kernel = _safe_int(params.get("hole_kernel_px"), 0, minimum=0)
        if hole_kernel > 0:
            dilated = dropout.copy()
            for dy in range(-hole_kernel, hole_kernel + 1):
                for dx in range(-hole_kernel, hole_kernel + 1):
                    dilated |= np.roll(np.roll(dropout, dy, axis=0), dx, axis=1)
            dropout = dilated
        depth[dropout] = 0.0
    edge_dropout_prob = float(params.get("edge_dropout_prob") or 0.0)
    if edge_dropout_prob > 0.0 and depth.ndim == 2 and min(depth.shape) > 1:
        grad_y, grad_x = np.gradient(depth)
        gradient = np.abs(grad_x) + np.abs(grad_y)
        nonzero_gradient = gradient[gradient > 0.0]
        if nonzero_gradient.size > 0:
            threshold = float(np.percentile(nonzero_gradient, 50))
            edge_mask = gradient >= threshold
            edge_kernel = _safe_int(params.get("edge_kernel_px"), 0, minimum=0)
            if edge_kernel > 0:
                dilated_edges = edge_mask.copy()
                for dy in range(-edge_kernel, edge_kernel + 1):
                    for dx in range(-edge_kernel, edge_kernel + 1):
                        dilated_edges |= np.roll(np.roll(edge_mask, dy, axis=0), dx, axis=1)
                edge_mask = dilated_edges
            depth[edge_mask & (np_rng.random(depth.shape) < edge_dropout_prob)] = 0.0
    dark_surface_dropout_prob = float(params.get("dark_surface_dropout_prob") or 0.0)
    if dark_surface_dropout_prob > 0.0:
        valid = depth > 0.0
        depth[valid & (np_rng.random(depth.shape) < dark_surface_dropout_prob)] = 0.0
    quantization = max(1.0, float(params.get("quantization_mm") or 1.0))
    depth = np.round(depth / quantization) * quantization
    clip_min = float(params.get("clip_min_mm") or 0.0)
    clip_max = float(params.get("clip_max_mm") or 65535.0)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(depth, clip_min, clip_max).astype(np.uint16)).save(dst)


def _write_depth_preview(src: Path, dst: Path) -> None:
    depth = np.asarray(Image.open(src)).astype(np.float32)
    valid = depth[depth > 0.0]
    if valid.size > 0:
        low = float(np.percentile(valid, 2))
        high = float(np.percentile(valid, 98))
        if high <= low:
            high = low + 1.0
        normalized = np.clip((depth - low) / (high - low), 0.0, 1.0)
    else:
        normalized = np.zeros(depth.shape, dtype=np.float32)
    preview = (normalized * 255.0).astype(np.uint8)
    preview[depth <= 0.0] = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(preview, mode="L").save(dst)


def _write_augmented_images(
    *,
    source: dict[str, Any],
    variant_dir: Path,
    image_params: dict[str, Any],
    depth_params: dict[str, Any],
    np_seed: int,
    depth_params_by_camera: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    files = source.get("files") if isinstance(source.get("files"), dict) else {}
    for camera, camera_files in files.items():
        if not isinstance(camera_files, dict):
            continue
        camera_output: dict[str, str] = {}
        camera_dir = variant_dir / str(camera)
        camera_seed = sum((index + 1) * ord(char) for index, char in enumerate(str(camera)))
        np_rng = np.random.default_rng(np_seed + camera_seed)
        rgb_path = camera_files.get("rgb")
        if image_params and isinstance(rgb_path, Path) and rgb_path.is_file():
            dst = camera_dir / "rgb.png"
            _apply_rgb_augmentation(rgb_path, dst, image_params, np_rng)
            camera_output["rgb_path"] = str(dst)
        depth_path = camera_files.get("depth")
        camera_depth_params = (depth_params_by_camera or {}).get(str(camera), depth_params)
        if camera_depth_params and isinstance(depth_path, Path) and depth_path.is_file():
            dst = camera_dir / "depth.png"
            _apply_depth_augmentation(depth_path, dst, camera_depth_params, np_rng)
            camera_output["depth_path"] = str(dst)
            source_preview = camera_dir / "source_depth_preview.png"
            depth_preview = camera_dir / "depth_preview.png"
            _write_depth_preview(depth_path, source_preview)
            _write_depth_preview(dst, depth_preview)
            camera_output["source_depth_preview_path"] = str(source_preview)
            camera_output["depth_preview_path"] = str(depth_preview)
        if camera_output:
            outputs[str(camera)] = camera_output
    return outputs


def _read_depth_valid_ratio(path: Path) -> float:
    try:
        depth = np.asarray(Image.open(path))
    except Exception:
        return 0.0
    if depth.size <= 0:
        return 0.0
    return round(float(np.count_nonzero(depth)) / float(depth.size), 6)


def _source_pose_from_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("specimen_pose", "object_pose", "pose"):
        value = row.get(key)
        if not isinstance(value, dict):
            continue
        pose = dict(value)
        xy = pose.get("a4_xy_mm") or pose.get("xy_mm")
        if isinstance(xy, (list, tuple)) and len(xy) >= 2:
            pose["a4_xy_mm"] = [_safe_float(xy[0], 0.0), _safe_float(xy[1], 0.0)]
        elif "a4_x_mm" in pose and "a4_y_mm" in pose:
            pose["a4_xy_mm"] = [_safe_float(pose["a4_x_mm"], 0.0), _safe_float(pose["a4_y_mm"], 0.0)]
        elif "x_mm" in pose and "y_mm" in pose:
            pose["a4_xy_mm"] = [_safe_float(pose["x_mm"], 0.0), _safe_float(pose["y_mm"], 0.0)]
        return pose
    return {}


def _source_pose_confidence(source_pose: dict[str, Any]) -> float:
    for key in ("confidence", "pose_confidence", "position_confidence"):
        if key in source_pose:
            return _safe_float(source_pose.get(key), 0.0, minimum=0.0, maximum=1.0)
    return 0.0


def _orientation_confidence(source_pose: dict[str, Any]) -> float:
    for key in ("orientation_confidence", "yaw_confidence"):
        if key in source_pose:
            return _safe_float(source_pose.get(key), 0.0, minimum=0.0, maximum=1.0)
    if "yaw_deg" in source_pose:
        return _source_pose_confidence(source_pose)
    return 0.0


def _bounded_render_domain_for_source(
    render_domain: dict[str, Any],
    source_pose: dict[str, Any],
) -> tuple[dict[str, Any], float, float, str]:
    updated = dict(render_domain)
    pose_confidence = _source_pose_confidence(source_pose)
    orientation_confidence = _orientation_confidence(source_pose)
    raw_orientation_source = str(source_pose.get("orientation_source") or source_pose.get("yaw_source") or "source_pose")
    if not updated:
        return {}, pose_confidence, orientation_confidence, raw_orientation_source
    xy = source_pose.get("a4_xy_mm")
    if isinstance(xy, list) and len(xy) >= 2:
        base_x = _safe_float(xy[0], 0.0)
        base_y = _safe_float(xy[1], 0.0)
        jitter = updated.get("object_xy_jitter_mm")
        if isinstance(jitter, list) and len(jitter) >= 2 and 0.0 <= base_x <= A4_WIDTH_MM and 0.0 <= base_y <= A4_HEIGHT_MM:
            original_x = _safe_float(jitter[0], 0.0)
            original_y = _safe_float(jitter[1], 0.0)
            clipped_x = min(max(original_x, -base_x), A4_WIDTH_MM - base_x)
            clipped_y = min(max(original_y, -base_y), A4_HEIGHT_MM - base_y)
            updated["object_xy_jitter_mm"] = [round(clipped_x, 4), round(clipped_y, 4)]
            updated["object_a4_xy_mm"] = [round(base_x + clipped_x, 4), round(base_y + clipped_y, 4)]
            updated["object_xy_jitter_clipped"] = abs(clipped_x - original_x) > 1e-6 or abs(clipped_y - original_y) > 1e-6
    orientation_source = raw_orientation_source
    if "object_yaw_jitter_deg" in updated:
        if "yaw_deg" not in source_pose:
            updated.pop("object_yaw_jitter_deg", None)
            orientation_source = "disabled_no_orientation"
        elif orientation_confidence < ORIENTATION_CONFIDENCE_MIN:
            updated.pop("object_yaw_jitter_deg", None)
            orientation_source = "disabled_low_confidence"
    updated["orientation_source"] = orientation_source
    updated["source_pose_confidence"] = pose_confidence
    updated["orientation_confidence"] = orientation_confidence
    return updated, pose_confidence, orientation_confidence, orientation_source


def _a4_pose_failure(source_pose: dict[str, Any], render_domain: dict[str, Any]) -> str:
    xy = source_pose.get("a4_xy_mm")
    if not isinstance(xy, list) or len(xy) < 2:
        return ""
    x_mm = _safe_float(xy[0], 0.0)
    y_mm = _safe_float(xy[1], 0.0)
    jitter = render_domain.get("object_xy_jitter_mm")
    if isinstance(jitter, list) and len(jitter) >= 2:
        x_mm += _safe_float(jitter[0], 0.0)
        y_mm += _safe_float(jitter[1], 0.0)
    if x_mm < 0.0 or x_mm > A4_WIDTH_MM or y_mm < 0.0 or y_mm > A4_HEIGHT_MM:
        return "SOURCE_POSE_OUT_OF_A4_BOUNDS"
    yaw = source_pose.get("yaw_deg")
    if yaw is not None:
        yaw_deg = _safe_float(yaw, 0.0)
        if yaw_deg < -180.0 or yaw_deg > 180.0:
            return "SOURCE_POSE_OUT_OF_A4_BOUNDS"
    return ""


def _qa_variant_row(row: dict[str, Any], *, require_rgb: bool, require_depth: bool) -> dict[str, Any]:
    image_outputs = row.get("image_outputs") if isinstance(row.get("image_outputs"), dict) else {}
    cameras = [str(item) for item in row.get("cameras", []) if str(item).strip()]
    rgb_exists = True
    depth_exists = True
    depth_ratios: list[float] = []
    for camera in cameras:
        camera_outputs = image_outputs.get(camera) if isinstance(image_outputs.get(camera), dict) else {}
        rgb_path = Path(str(camera_outputs.get("rgb_path") or "")).expanduser()
        depth_path = Path(str(camera_outputs.get("depth_path") or "")).expanduser()
        if require_rgb and not rgb_path.is_file():
            rgb_exists = False
        if require_depth:
            if not depth_path.is_file():
                depth_exists = False
            else:
                depth_ratios.append(_read_depth_valid_ratio(depth_path))
    depth_valid_ratio = round(min(depth_ratios), 6) if depth_ratios else 0.0
    failure_code = ""
    if require_rgb and not rgb_exists:
        failure_code = "MISSING_AUGMENTED_RGB"
    elif require_depth and not depth_exists:
        failure_code = "MISSING_AUGMENTED_DEPTH"
    elif require_depth and depth_valid_ratio < QA_DEPTH_VALID_RATIO_MIN:
        failure_code = "INVALID_AUGMENTED_DEPTH"
    else:
        source_pose = row.get("source_pose") if isinstance(row.get("source_pose"), dict) else {}
        render_domain = row.get("render_domain_augmentations") if isinstance(row.get("render_domain_augmentations"), dict) else {}
        failure_code = _a4_pose_failure(source_pose, render_domain)
    return {
        "qa_ok": failure_code == "",
        "qa_failure_code": failure_code,
        "rgb_exists": bool(rgb_exists if require_rgb else bool(image_outputs)),
        "depth_exists": bool(depth_exists if require_depth else False),
        "depth_valid_ratio": depth_valid_ratio,
    }


def _qa_summary_payload(
    *,
    dataset: Path,
    output: Path,
    manifest_path: Path,
    qa_summary_path: Path,
    qa_rows: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    failure_counts: dict[str, int] = {}
    for qa in qa_rows:
        code = str(qa.get("qa_failure_code") or "").strip()
        if code:
            failure_counts[code] = failure_counts.get(code, 0) + 1
    total_count = len(qa_rows)
    failed_count = sum(1 for qa in qa_rows if not qa.get("qa_ok"))
    passed_count = total_count - failed_count
    return {
        "ok": failed_count == 0,
        "schema": "atr.isaac_data_augmentation.qa_summary.v1",
        "created_at": created_at,
        "dataset_path": str(dataset),
        "output_dir": str(output),
        "manifest_path": str(manifest_path),
        "qa_summary_path": str(qa_summary_path),
        "total_count": total_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "failure_counts": failure_counts,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_augmentation_sidecar(
    *,
    dataset_path: Path | str,
    output_dir: Path | str,
    variants_per_frame: int = 8,
    max_source_frames: int = 200,
    seed: int | None = None,
    cameras: list[str] | tuple[str, ...] | str | None = None,
    augmentation_profile: str = "conservative",
    image_augmentation_enabled: bool = True,
    photometric_enabled: bool = True,
    sensor_noise_enabled: bool = True,
    depth_noise_enabled: bool = True,
    render_domain_enabled: bool = True,
    camera_pose_enabled: bool = True,
    rgb_strength: float | None = 1.0,
    depth_strength: float | None = 1.0,
    render_domain_strength: float | None = 1.0,
    camera_pose_strength: float | None = 1.0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    selected_cameras = _camera_list(cameras)
    variants = _safe_int(variants_per_frame, 8, minimum=1)
    max_frames = _safe_int(max_source_frames, 200, minimum=1)
    run_seed = int(seed if seed is not None else 0)
    options = _augmentation_options(
        augmentation_profile=augmentation_profile,
        image_augmentation_enabled=image_augmentation_enabled,
        photometric_enabled=photometric_enabled,
        sensor_noise_enabled=sensor_noise_enabled,
        depth_noise_enabled=depth_noise_enabled,
        render_domain_enabled=render_domain_enabled,
        camera_pose_enabled=camera_pose_enabled,
        rgb_strength=rgb_strength,
        depth_strength=depth_strength,
        render_domain_strength=render_domain_strength,
        camera_pose_strength=camera_pose_strength,
    )
    mask = _family_mask(options)
    families = _families_from_mask(mask)
    recipe = _augmentation_recipe(options)
    depth_profiles = _depth_sensor_profiles(dataset, selected_cameras)
    progress: dict[str, Any] = {
        "stage": "prepare",
        "done": 0,
        "total": 0,
        "percent": 0.0,
        "message": "Preparing Isaac augmentation sidecar",
    }
    if progress_callback is not None:
        progress_callback(dict(progress))
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    sources = _source_frames(dataset, selected_cameras, max_frames)
    manifest_path = output / "manifest.jsonl"
    summary_path = output / "summary.json"
    qa_summary_path = output / "qa_summary.json"
    if not sources:
        progress = {
            "stage": "no_source_frames",
            "done": 0,
            "total": 0,
            "percent": 100.0,
            "message": "No Isaac RGB-D source frames found",
        }
        if progress_callback is not None:
            progress_callback(dict(progress))
        qa_summary = _qa_summary_payload(
            dataset=dataset,
            output=output,
            manifest_path=manifest_path,
            qa_summary_path=qa_summary_path,
            qa_rows=[],
            created_at=_now_iso(),
        )
        summary = {
            "ok": False,
            "schema": "atr.isaac_data_augmentation.summary.v1",
            "augmentation_recipe_version": AUGMENTATION_RECIPE_VERSION,
            "augmentation_profile": options["profile"],
            "augmentation_options": {key: value for key, value in options.items() if key != "profile"},
            "augmentation_recipe": recipe,
            "failure_code": "ISAAC_AUGMENTATION_NO_SOURCE_FRAMES",
            "message": f"No Isaac RGBD render manifests found under {dataset / 'sidecar' / 'isaac_rgbd'}",
            "dataset_path": str(dataset),
            "output_dir": str(output),
            "manifest_path": str(manifest_path),
            "summary_path": str(summary_path),
            "qa_summary_path": str(qa_summary_path),
            "source_frame_count": 0,
            "variant_count": 0,
            "valid_variant_count": 0,
            "failed_variant_count": 0,
            "depth_sensor_profiles": depth_profiles,
            "common_augmentation_families": families,
            "progress": progress,
        }
        _write_json(qa_summary_path, qa_summary)
        _write_json(summary_path, summary)
        return summary

    created_at = _now_iso()
    variant_count = 0
    qa_rows: list[dict[str, Any]] = []
    total_variants = len(sources) * variants
    progress = {
        "stage": "build_manifest",
        "done": 0,
        "total": total_variants,
        "percent": 0.0,
        "message": "Building Isaac augmentation manifest",
    }
    if progress_callback is not None:
        progress_callback(dict(progress))
    with manifest_path.open("w", encoding="utf-8") as handle:
        for source_index, source in enumerate(sources):
            for variant_index in range(variants):
                variant_seed = run_seed + source_index * 10_000 + variant_index
                rng = random.Random(variant_seed)
                np_seed = variant_seed + 1_000_000
                image_params, depth_params, render_domain = _augmentation_params(rng, options)
                source_depth_profiles = {camera: depth_profiles.get(camera, "generic_realsense") for camera in source["cameras"]}
                depth_params_by_camera = _depth_params_by_camera(
                    list(source["cameras"]),
                    source_depth_profiles,
                    depth_params,
                    rng=rng,
                    strength=_effective_strengths(options)["depth_strength"],
                )
                episode_index = int(source["episode_index"])
                frame_index = int(source["frame_index"])
                variant_id = f"e{episode_index:03d}_f{frame_index:06d}_v{variant_index:03d}"
                variant_dir = output / "images" / f"episode_{episode_index:03d}" / f"frame_{frame_index:06d}" / f"variant_{variant_index:03d}"
                image_outputs = (
                    _write_augmented_images(
                        source=source,
                        variant_dir=variant_dir,
                        image_params=image_params,
                        depth_params=depth_params,
                        np_seed=np_seed,
                        depth_params_by_camera=depth_params_by_camera,
                    )
                    if image_augmentation_enabled and (image_params or depth_params)
                    else {}
                )
                camera_pose_strength_value = _effective_strengths(options)["camera_pose_strength"]
                camera_specs = {
                    camera: _jitter_camera_spec(camera, rng, camera_pose_strength_value)
                    for camera in source["cameras"]
                } if options["camera_pose_enabled"] else {}
                source_pose = _source_pose_from_row(source["row"] if isinstance(source.get("row"), dict) else {})
                render_domain, source_pose_confidence, orientation_confidence, orientation_source = _bounded_render_domain_for_source(
                    render_domain,
                    source_pose,
                )
                render_request = {
                    "schema": "atr.isaac_rgbd.render_request.v1",
                    "domain_randomization_version": DOMAIN_RANDOMIZATION_VERSION,
                    "enabled": bool(options["render_domain_enabled"] or options["camera_pose_enabled"]),
                    "augmentation_variant_id": variant_id,
                    "attempt_id": f"{source['attempt_id']}_aug_v{variant_index:03d}",
                    "episode_index": episode_index,
                    "frame_index": frame_index,
                    "sample_index": source.get("sample_index"),
                    "timestamp": source.get("record_timestamp") or created_at,
                    "target_fps": source.get("target_fps", 15.0),
                    "cameras": list(source["cameras"]),
                    "output_dir": str(output / "renders" / variant_id),
                    "camera_specs": camera_specs,
                    "render_domain_augmentations": render_domain,
                }
                row = {
                    "schema": "atr.isaac_data_augmentation.variant.v1",
                    "augmentation_recipe_version": AUGMENTATION_RECIPE_VERSION,
                    "domain_randomization_version": DOMAIN_RANDOMIZATION_VERSION,
                    "augmentation_profile": options["profile"],
                    "augmentation_options": {key: value for key, value in options.items() if key != "profile"},
                    "family_mask": dict(mask),
                    "severity": max(_effective_strengths(options).values()),
                    "created_at": created_at,
                    "dataset_path": str(dataset),
                    "variant_id": variant_id,
                    "variant_seed": variant_seed,
                    "source": {
                        "source_id": source["source_id"],
                        "manifest_path": source["manifest_path"],
                        "attempt_id": source["attempt_id"],
                        "episode_index": episode_index,
                        "frame_index": frame_index,
                        "sample_index": source.get("sample_index"),
                        "record_timestamp": source.get("record_timestamp"),
                    },
                    "source_pose": source_pose,
                    "source_pose_confidence": source_pose_confidence,
                    "orientation_confidence": orientation_confidence,
                    "orientation_source": orientation_source,
                    "cameras": list(source["cameras"]),
                    "image_augmentations": image_params if image_augmentation_enabled else {},
                    "depth_augmentations": depth_params if image_augmentation_enabled else {},
                    "depth_sensor_profiles": source_depth_profiles if image_augmentation_enabled and depth_params else {},
                    "depth_augmentations_by_camera": depth_params_by_camera if image_augmentation_enabled else {},
                    "render_domain_augmentations": render_domain,
                    "camera_pose_source": "isaac_rgbd_render_manifest" if options["camera_pose_enabled"] else "disabled",
                    "render_request": render_request,
                    "image_outputs": image_outputs,
                }
                qa = _qa_variant_row(
                    row,
                    require_rgb=bool(image_augmentation_enabled and image_params),
                    require_depth=bool(image_augmentation_enabled and depth_params),
                )
                row.update(qa)
                qa_rows.append(qa)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                variant_count += 1
                progress = {
                    "stage": "build_manifest",
                    "done": variant_count,
                    "total": total_variants,
                    "percent": round((variant_count / total_variants) * 100.0, 2) if total_variants else 100.0,
                    "message": "Building Isaac augmentation manifest",
                }
                if progress_callback is not None:
                    progress_callback(dict(progress))
    qa_summary = _qa_summary_payload(
        dataset=dataset,
        output=output,
        manifest_path=manifest_path,
        qa_summary_path=qa_summary_path,
        qa_rows=qa_rows,
        created_at=created_at,
    )
    failed_variant_count = int(qa_summary["failed_count"])
    valid_variant_count = int(qa_summary["passed_count"])
    progress = {
        "stage": "complete",
        "done": variant_count,
        "total": total_variants,
        "percent": 100.0,
        "message": "Isaac augmentation manifest complete",
    }
    if progress_callback is not None:
        progress_callback(dict(progress))
    summary = {
        "ok": True,
        "schema": "atr.isaac_data_augmentation.summary.v1",
        "augmentation_recipe_version": AUGMENTATION_RECIPE_VERSION,
        "domain_randomization_version": DOMAIN_RANDOMIZATION_VERSION,
        "augmentation_profile": options["profile"],
        "augmentation_options": {key: value for key, value in options.items() if key != "profile"},
        "augmentation_recipe": recipe,
        "created_at": created_at,
        "dataset_path": str(dataset),
        "output_dir": str(output),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "qa_summary_path": str(qa_summary_path),
        "source_frame_count": len(sources),
        "variant_count": variant_count,
        "valid_variant_count": valid_variant_count,
        "failed_variant_count": failed_variant_count,
        "qa_failure_counts": dict(qa_summary["failure_counts"]),
        "variants_per_frame": variants,
        "max_source_frames": max_frames,
        "seed": run_seed,
        "cameras": selected_cameras,
        "depth_sensor_profiles": depth_profiles,
        "image_augmentation_enabled": bool(image_augmentation_enabled),
        "camera_pose_enabled": bool(options["camera_pose_enabled"]),
        "common_augmentation_families": families,
        "progress": progress,
    }
    _write_json(qa_summary_path, qa_summary)
    _write_json(summary_path, summary)
    return summary


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Isaac Sim augmentation sidecars for a LeRobot dataset.")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--variants-per-frame", type=int, default=8)
    parser.add_argument("--max-source-frames", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cameras", default="top,front,right")
    parser.add_argument("--augmentation-profile", default="conservative", choices=sorted(AUGMENTATION_PROFILES))
    parser.add_argument("--image-augmentation-enabled", type=int, default=1)
    parser.add_argument("--photometric-enabled", type=int, default=1)
    parser.add_argument("--sensor-noise-enabled", type=int, default=1)
    parser.add_argument("--depth-noise-enabled", type=int, default=1)
    parser.add_argument("--render-domain-enabled", type=int, default=1)
    parser.add_argument("--camera-pose-enabled", type=int, default=1)
    parser.add_argument("--rgb-strength", type=float, default=1.0)
    parser.add_argument("--depth-strength", type=float, default=1.0)
    parser.add_argument("--render-domain-strength", type=float, default=1.0)
    parser.add_argument("--camera-pose-strength", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    result = build_augmentation_sidecar(
        dataset_path=Path(args.dataset_path),
        output_dir=Path(args.output_dir),
        variants_per_frame=args.variants_per_frame,
        max_source_frames=args.max_source_frames,
        seed=args.seed,
        cameras=args.cameras,
        augmentation_profile=args.augmentation_profile,
        image_augmentation_enabled=bool(args.image_augmentation_enabled),
        photometric_enabled=bool(args.photometric_enabled),
        sensor_noise_enabled=bool(args.sensor_noise_enabled),
        depth_noise_enabled=bool(args.depth_noise_enabled),
        render_domain_enabled=bool(args.render_domain_enabled),
        camera_pose_enabled=bool(args.camera_pose_enabled),
        rgb_strength=args.rgb_strength,
        depth_strength=args.depth_strength,
        render_domain_strength=args.render_domain_strength,
        camera_pose_strength=args.camera_pose_strength,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
