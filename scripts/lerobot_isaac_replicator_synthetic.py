#!/usr/bin/env python3
"""Isaac Sim Replicator worker wrapper for LeRobot synthetic outputs.

This script is safe to call from the bridge or from an Isaac Sim Python runtime.
It never fabricates render outputs: when `omni.replicator.core` cannot be
imported it writes a structured blocked summary and exits non-zero from the CLI.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPLICATOR_SUMMARY_SCHEMA = "atr.lerobot.replicator_synthetic.summary.v1"
REPLICATOR_MANIFEST_ROW_SCHEMA = "atr.lerobot.replicator_frame.v1"
REPLICATOR_REQUIRED_MODULES = ["omni.replicator.core"]
REPLICATOR_WRITER_TYPE = "BasicWriter"
REPLICATOR_ANNOTATORS = ["rgb", "distance_to_image_plane", "semantic_segmentation"]
REPLICATOR_RENDER_RESOLUTION = [640, 480]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        with tmp_path.open("r+", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    tmp_path.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n")


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _default_importer(name: str) -> Any:
    return importlib.import_module(name)


def _probe_replicator_runtime(importer: Callable[[str], Any]) -> dict[str, Any]:
    try:
        importer("omni.replicator.core")
    except Exception as exc:  # noqa: BLE001 - report exact runtime import failure in summary.
        return {
            "status": "blocked",
            "import_checked": True,
            "required_modules": list(REPLICATOR_REQUIRED_MODULES),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "passed",
        "import_checked": True,
        "required_modules": list(REPLICATOR_REQUIRED_MODULES),
    }


def _start_simulation_app(importer: Callable[[str], Any], *, enabled: bool, headless: bool = True) -> tuple[Any | None, dict[str, Any]]:
    if not enabled:
        return None, {
            "status": "skipped",
            "reason": "SimulationApp initialization disabled by caller.",
            "headless": bool(headless),
        }
    errors: list[dict[str, str]] = []
    for module_name in ("isaacsim", "omni.isaac.kit"):
        try:
            module = importer(module_name)
        except ImportError as exc:
            errors.append({"module": module_name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        simulation_app_cls = getattr(module, "SimulationApp", None)
        if not callable(simulation_app_cls):
            errors.append({"module": module_name, "error": "SimulationApp attribute is not callable."})
            continue
        launch_config = {"headless": bool(headless)}
        try:
            app = simulation_app_cls(launch_config)
        except TypeError:
            try:
                app = simulation_app_cls(launch_config=launch_config)
            except Exception as exc:  # noqa: BLE001 - preserve Isaac runtime startup failure.
                return None, {
                    "status": "blocked",
                    "module": module_name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "headless": bool(headless),
                }
        except Exception as exc:  # noqa: BLE001 - preserve Isaac runtime startup failure.
            return None, {
                "status": "blocked",
                "module": module_name,
                "error": f"{type(exc).__name__}: {exc}",
                "headless": bool(headless),
            }
        return app, {
            "status": "passed",
            "module": module_name,
            "headless": bool(headless),
        }
    return None, {
        "status": "unavailable",
        "reason": "SimulationApp module is unavailable; continuing with Replicator import probe.",
        "errors": errors,
    }


def _close_simulation_app(app: Any | None) -> dict[str, Any]:
    if app is None:
        return {"status": "skipped"}
    close = getattr(app, "close", None)
    if not callable(close):
        return {"status": "skipped", "reason": "SimulationApp has no close() method."}
    try:
        close()
    except Exception as exc:  # noqa: BLE001 - report cleanup failure without hiding render result.
        return {"status": "blocked", "error": f"{type(exc).__name__}: {exc}"}
    return {"status": "passed"}


def _base_summary(
    *,
    canonical_index: Path,
    stage_url: Path,
    output_dir: Path,
    cameras: list[str],
    variants: int,
    rgb_strength: float,
    depth_strength: float,
    render_strength: float,
    camera_pose_strength: float,
    post_render_augmentation: dict[str, Any],
    canonical_rows: list[dict[str, Any]],
    runtime_probe: dict[str, Any],
) -> dict[str, Any]:
    expected_render_rows = len(canonical_rows) * len(cameras) * int(variants)
    replicator_available = runtime_probe.get("status") == "passed"
    return {
        "schema": REPLICATOR_SUMMARY_SCHEMA,
        "generated_at": _now(),
        "replicator_available": replicator_available,
        "writer_type": REPLICATOR_WRITER_TYPE,
        "annotators": list(REPLICATOR_ANNOTATORS),
        "post_render_augmentation": post_render_augmentation,
        "render_products": {
            "requested_count": expected_render_rows,
            "created_count": 0,
            "resolution": list(REPLICATOR_RENDER_RESOLUTION),
            "camera_names": list(cameras),
        },
        "camera_names": list(cameras),
        "rgb_output_count": 0,
        "depth_output_count": 0,
        "segmentation_output_count": 0,
        "depth_units_replicator": {
            "annotator": "distance_to_image_plane",
            "unit": "meters",
            "conversion": "identity",
        },
        "teleop_sdg_replay_used": False,
        "teleop_sdg_replay_boundary": "render_only_not_physics_rollout",
        "canonical_index_path": str(canonical_index),
        "stage_path": str(stage_url),
        "output_root": str(output_dir),
        "manifest_path": str(output_dir / "manifest.jsonl"),
        "canonical_frame_count": len(canonical_rows),
        "expected_render_rows": expected_render_rows,
        "rendered_count": 0,
        "train_eligible_count": 0,
        "source_type": "replicator_render_only",
        "runtime_probe": runtime_probe,
        "request": {
            "cameras": list(cameras),
            "variants": int(variants),
            "rgb_strength": float(rgb_strength),
            "depth_strength": float(depth_strength),
            "render_strength": float(render_strength),
            "camera_pose_strength": float(camera_pose_strength),
        },
    }


def _post_render_augmentation_config(
    *,
    output_dir: Path,
    cameras: list[str],
    rgb_strength: float,
    depth_strength: float,
    render_strength: float,
    camera_pose_strength: float,
    augmentation_config: Path | None = None,
) -> dict[str, Any]:
    loaded = _read_json(augmentation_config) if augmentation_config is not None else {}
    if loaded:
        return loaded
    return {
        "schema": "atr.lerobot.replicator.post_render_augmentation.v1",
        "owner": "isaac_sim_replicator_writer_annotators",
        "execution_stage": "replicator_writer_annotator",
        "manifest_path": str(output_dir / "post_render_augmentation.json"),
        "rgb": {
            "enabled": rgb_strength > 0.0,
            "annotator": "rgb",
            "strength": float(rgb_strength),
            "operations": ["exposure_jitter", "color_jitter", "sensor_noise"],
        },
        "depth": {
            "enabled": depth_strength > 0.0,
            "annotator": "distance_to_image_plane",
            "strength": float(depth_strength),
            "source_profile": "d405_raw_depth_profile",
            "unit": "meters",
            "operations": ["quantization_noise", "dropout", "range_noise"],
        },
        "render": {
            "enabled": render_strength > 0.0,
            "strength": float(render_strength),
            "operations": ["lighting", "material", "texture"],
        },
        "camera_pose": {
            "enabled": camera_pose_strength > 0.0,
            "strength": float(camera_pose_strength),
            "cameras": list(cameras),
            "operations": ["pose_jitter", "intrinsics_jitter"],
        },
        "trajectory_boundary": "render_only_not_action_trajectory",
        "train_boundary": "render_only_same_action",
    }


def _manifest_post_render_augmentation(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_stage": str(config.get("execution_stage") or "replicator_writer_annotator"),
        "rgb_strength": float(((config.get("rgb") if isinstance(config.get("rgb"), dict) else {}) or {}).get("strength") or 0.0),
        "depth_strength": float(((config.get("depth") if isinstance(config.get("depth"), dict) else {}) or {}).get("strength") or 0.0),
        "render_strength": float(((config.get("render") if isinstance(config.get("render"), dict) else {}) or {}).get("strength") or 0.0),
        "camera_pose_strength": float(((config.get("camera_pose") if isinstance(config.get("camera_pose"), dict) else {}) or {}).get("strength") or 0.0),
        "train_boundary": str(config.get("train_boundary") or "render_only_same_action"),
    }


def _blocked_summary(base: dict[str, Any], *, blocker: str, message: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **base,
        "ok": False,
        "status": "blocked",
        "blocker": blocker,
        "message": message,
        "checks": checks,
    }


def _replicator_artifact_path(output_dir: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else output_dir / path


def _render_file_validation(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_rows: list[dict[str, Any]] = []
    missing_rgb_count = 0
    missing_depth_count = 0
    missing_metadata_count = 0
    valid_row_count = 0
    for index, row in enumerate(rows):
        rgb_path = _replicator_artifact_path(output_dir, row.get("rgb_path"))
        depth_path = _replicator_artifact_path(output_dir, row.get("depth_path"))
        metadata_raw = str(row.get("metadata_path") or "").strip()
        metadata_path = _replicator_artifact_path(output_dir, metadata_raw) if metadata_raw else Path()
        missing: list[str] = []
        if not rgb_path.is_file():
            missing.append("rgb_path")
            missing_rgb_count += 1
        if not depth_path.is_file():
            missing.append("depth_path")
            missing_depth_count += 1
        if metadata_raw and not metadata_path.is_file():
            missing.append("metadata_path")
            missing_metadata_count += 1
        if missing:
            invalid_rows.append(
                {
                    "row_index": index,
                    "episode_index": row.get("episode_index"),
                    "frame_index": row.get("frame_index"),
                    "camera": row.get("camera") or row.get("camera_name") or "",
                    "variant_index": row.get("variant_index"),
                    "missing": missing,
                }
            )
        else:
            valid_row_count += 1
    return {
        "schema": "atr.lerobot.replicator.render_file_validation.v1",
        "ok": not invalid_rows,
        "row_count": len(rows),
        "valid_row_count": valid_row_count,
        "invalid_row_count": len(invalid_rows),
        "missing_rgb_count": missing_rgb_count,
        "missing_depth_count": missing_depth_count,
        "missing_metadata_count": missing_metadata_count,
        "invalid_rows": invalid_rows[:50],
    }


def _render_output_counts(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"rgb_output_count": 0, "depth_output_count": 0, "segmentation_output_count": 0}
    for row in rows:
        rgb_raw = str(row.get("rgb_path") or "").strip()
        depth_raw = str(row.get("depth_path") or "").strip()
        segmentation_raw = str(row.get("segmentation_path") or "").strip()
        if rgb_raw and _replicator_artifact_path(output_dir, rgb_raw).is_file():
            counts["rgb_output_count"] += 1
        if depth_raw and _replicator_artifact_path(output_dir, depth_raw).is_file():
            counts["depth_output_count"] += 1
        if segmentation_raw and _replicator_artifact_path(output_dir, segmentation_raw).is_file():
            counts["segmentation_output_count"] += 1
    return counts


def _normalize_render_row(
    row: dict[str, Any],
    *,
    default_source: dict[str, Any],
    post_render_augmentation: dict[str, Any],
) -> dict[str, Any]:
    episode_index = row.get("episode_index", row.get("canonical_episode_index", default_source.get("episode_index", 0)))
    frame_index = row.get("frame_index", row.get("canonical_frame_index", default_source.get("frame_index", 0)))
    camera = row.get("camera", row.get("camera_name", ""))
    row_augmentation = row.get("post_render_augmentation") if isinstance(row.get("post_render_augmentation"), dict) else {}
    normalized = {
        **row,
        "schema": REPLICATOR_MANIFEST_ROW_SCHEMA,
        "source_type": "replicator_render_only",
        "episode_index": int(episode_index),
        "frame_index": int(frame_index),
        "canonical_episode_index": int(episode_index),
        "canonical_frame_index": int(frame_index),
        "camera": str(camera),
        "camera_name": str(camera),
        "variant_index": int(row.get("variant_index", 0)),
        "train_eligible": False,
        "train_exclusion_reason": "render_only_same_pose",
        "post_render_augmentation": {
            **_manifest_post_render_augmentation(post_render_augmentation),
            **row_augmentation,
        },
    }
    if "timestamp_s" not in normalized and default_source.get("timestamp_s") is not None:
        normalized["timestamp_s"] = default_source.get("timestamp_s")
    return normalized


def _normalize_render_rows(
    rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
    *,
    post_render_augmentation: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        default_source = canonical_rows[min(index, len(canonical_rows) - 1)] if canonical_rows else {}
        normalized_rows.append(
            _normalize_render_row(
                row,
                default_source=default_source,
                post_render_augmentation=post_render_augmentation,
            )
        )
    return normalized_rows


def _relative_to_output(output_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except (OSError, ValueError):
        return str(path)


def _find_first_file(root: Path, keywords: tuple[str, ...], suffixes: tuple[str, ...]) -> Path | None:
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and any(keyword in path.name.lower() for keyword in keywords)
    )
    return candidates[0] if candidates else None


def _get_basic_writer(rep: Any) -> Any:
    registry = getattr(rep, "WriterRegistry", None)
    if registry is not None and hasattr(registry, "get"):
        return registry.get("BasicWriter")
    writers = getattr(rep, "writers", None)
    if writers is not None and hasattr(writers, "get"):
        return writers.get("BasicWriter")
    raise RuntimeError("Replicator BasicWriter registry is unavailable.")


def _replicator_orchestrator_step(rep: Any) -> None:
    orchestrator = getattr(rep, "orchestrator", None)
    if orchestrator is None:
        raise RuntimeError("Replicator orchestrator is unavailable.")
    if hasattr(orchestrator, "step"):
        orchestrator.step()
        return
    if hasattr(orchestrator, "run"):
        orchestrator.run()
        return
    raise RuntimeError("Replicator orchestrator has neither step() nor run().")


def _open_usd_stage(importer: Callable[[str], Any], stage_url: Path) -> Any:
    try:
        omni_usd = importer("omni.usd")
    except (ImportError, ModuleNotFoundError):
        return None
    context_factory = getattr(omni_usd, "get_context", None)
    if not callable(context_factory):
        return None
    context = context_factory()
    if context is None:
        return None
    open_stage = getattr(context, "open_stage", None)
    if callable(open_stage):
        opened = open_stage(str(stage_url))
        if opened is False:
            raise RuntimeError(f"Isaac USD context failed to open stage: {stage_url}")
    get_stage = getattr(context, "get_stage", None)
    return get_stage() if callable(get_stage) else None


def _prim_is_valid(prim: Any) -> bool:
    if prim is None:
        return False
    is_valid = getattr(prim, "IsValid", None)
    if callable(is_valid):
        try:
            return bool(is_valid())
        except Exception:
            return False
    return True


def _prim_type_name(prim: Any) -> str:
    get_type_name = getattr(prim, "GetTypeName", None)
    if not callable(get_type_name):
        return ""
    try:
        return str(get_type_name())
    except Exception:
        return ""


def _camera_candidate_paths(camera_key: str) -> list[str]:
    key = str(camera_key or "").strip()
    if not key:
        return []
    if key.startswith("/"):
        return [key]
    return [
        f"/World/Cameras/{key}",
        f"/World/Cameras/{key}_camera",
        f"/World/{key}_camera",
        f"/World/ATRRenderCameras/{key}",
    ]


def _find_stage_camera_path(stage: Any, camera_key: str) -> str:
    get_prim_at_path = getattr(stage, "GetPrimAtPath", None)
    if stage is None or not callable(get_prim_at_path):
        return ""
    for path in _camera_candidate_paths(camera_key):
        try:
            prim = get_prim_at_path(path)
        except Exception:
            continue
        if _prim_is_valid(prim) and (_prim_type_name(prim) in {"", "Camera"}):
            return path
    return ""


def _default_camera_spec(camera_key: str) -> dict[str, Any]:
    key = str(camera_key or "").lower()
    if key == "top":
        return {"position": (0.315, 0.205, 0.72), "look_at": (0.315, 0.265, 0.0)}
    if key == "front":
        return {"position": (0.36, 0.96, 0.52), "look_at": (0.36, 0.28, 0.025), "focal_length": 14.0}
    if key == "right":
        return {"position": (0.86, 0.58, 0.52), "look_at": (0.38, 0.24, 0.02), "focal_length": 10.0}
    if key == "wrist":
        return {"position": (0.19, 0.08, 0.28), "look_at": (0.36, 0.28, 0.02)}
    if key == "sim_overhead":
        return {"position": (0.315, 0.265, 0.82), "look_at": (0.315, 0.265, 0.0)}
    if key == "sim_top_oblique":
        return {"position": (0.05, -0.12, 0.58), "look_at": (0.315, 0.265, 0.02)}
    if key == "sim_wrist_offset":
        return {"position": (0.14, 0.02, 0.32), "look_at": (0.36, 0.28, 0.02)}
    return {"position": (0.42, -0.08, 0.42), "look_at": (0.315, 0.265, 0.0)}


def _camera_create_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
    position = tuple(spec.get("position") or (0.315, 0.265, 0.62))
    look_at = tuple(spec.get("look_at") or (0.315, 0.265, 0.0))
    dx = float(position[0]) - float(look_at[0])
    dy = float(position[1]) - float(look_at[1])
    dz = float(position[2]) - float(look_at[2])
    focus_distance = max(0.001, math.sqrt(dx * dx + dy * dy + dz * dz))
    return {
        "position": position,
        "look_at": look_at,
        "look_at_up_axis": tuple(spec.get("look_at_up_axis") or (0.0, 0.0, 1.0)),
        "focal_length": float(spec.get("focal_length") or 18.0),
        "focus_distance": float(spec.get("focus_distance") or focus_distance),
        "clipping_range": tuple(spec.get("clipping_range") or (0.001, 10.0)),
    }


def _define_camera_parent(stage: Any) -> None:
    try:
        from pxr import UsdGeom  # type: ignore

        UsdGeom.Xform.Define(stage, "/World/ATRRenderCameras")
    except Exception:
        pass


def _resolve_or_create_camera(rep: Any, stage: Any, camera_key: str) -> dict[str, Any]:
    camera_path = _find_stage_camera_path(stage, camera_key)
    if camera_path:
        return {"camera": camera_path, "camera_path": camera_path}
    functional = getattr(rep, "functional", None)
    create = getattr(functional, "create", None)
    create_camera = getattr(create, "camera", None)
    if stage is not None and callable(create_camera):
        key = str(camera_key or "camera").strip() or "camera"
        _define_camera_parent(stage)
        camera = create_camera(
            **_camera_create_kwargs(_default_camera_spec(key)),
            parent="/World/ATRRenderCameras",
            name=key,
        )
        return {"camera": camera, "camera_path": f"/World/ATRRenderCameras/{key}"}
    raw = str(camera_key or "").strip()
    return {"camera": raw, "camera_path": raw if raw.startswith("/") else ""}


def _default_replicator_render_backend(context: dict[str, Any]) -> list[dict[str, Any]]:
    importer = context["importer"]
    rep = importer("omni.replicator.core")
    stage = _open_usd_stage(importer, Path(context["stage_url"]))
    output_dir = Path(context["output_dir"])
    canonical_rows = list(context["canonical_rows"])
    cameras = list(context["cameras"])
    variants = int(context["variants"])
    post_render_augmentation = dict(context.get("post_render_augmentation") or {})
    rows: list[dict[str, Any]] = []
    for canonical in canonical_rows:
        episode_index = int(canonical.get("episode_index", 0))
        frame_index = int(canonical.get("frame_index", canonical.get("canonical_frame_index", 0)))
        timestamp_s = canonical.get("timestamp_s", canonical.get("timestamp", 0.0))
        for camera in cameras:
            camera_target = _resolve_or_create_camera(rep, stage, str(camera))
            for variant_index in range(variants):
                row_dir = output_dir / "basic_writer" / str(camera) / f"e{episode_index:06d}_f{frame_index:06d}_v{variant_index:03d}"
                writer = _get_basic_writer(rep)
                render_product = rep.create.render_product(camera_target["camera"], (640, 480))
                writer.initialize(
                    output_dir=str(row_dir),
                    rgb=True,
                    distance_to_image_plane=True,
                    semantic_segmentation=True,
                )
                writer.attach([render_product])
                try:
                    _replicator_orchestrator_step(rep)
                finally:
                    if hasattr(writer, "detach"):
                        writer.detach()
                rgb_path = _find_first_file(row_dir, ("rgb",), (".png", ".jpg", ".jpeg"))
                depth_path = _find_first_file(row_dir, ("depth", "distance"), (".png", ".npy", ".exr"))
                segmentation_path = _find_first_file(row_dir, ("semantic", "segmentation"), (".png", ".npy", ".json"))
                metadata_path = _find_first_file(row_dir, ("metadata", "json"), (".json",))
                rows.append(
                    {
                        "canonical_episode_index": episode_index,
                        "canonical_frame_index": frame_index,
                        "timestamp_s": timestamp_s,
                        "camera_name": str(camera),
                        "camera_path": str(camera_target.get("camera_path") or ""),
                        "variant_index": variant_index,
                        "rgb_path": _relative_to_output(output_dir, rgb_path) if rgb_path is not None else "",
                        "depth_path": _relative_to_output(output_dir, depth_path) if depth_path is not None else "",
                        "segmentation_path": _relative_to_output(output_dir, segmentation_path) if segmentation_path is not None else "",
                        "metadata_path": _relative_to_output(output_dir, metadata_path) if metadata_path is not None else "",
                        "randomization": {
                            "rgb_strength": float(context["rgb_strength"]),
                            "depth_strength": float(context["depth_strength"]),
                            "render_strength": float(context["render_strength"]),
                            "camera_pose_strength": float(context["camera_pose_strength"]),
                        },
                        "post_render_augmentation": _manifest_post_render_augmentation(post_render_augmentation),
                    }
                )
    return rows


def run_replicator_worker(
    *,
    canonical_index: Path,
    stage_url: Path,
    output_dir: Path,
    cameras: list[str],
    variants: int,
    rgb_strength: float,
    depth_strength: float,
    render_strength: float,
    camera_pose_strength: float,
    augmentation_config: Path | None = None,
    importer: Callable[[str], Any] = _default_importer,
    render_backend: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    initialize_simulation_app: bool = True,
    visualize_generation: bool = False,
) -> dict[str, Any]:
    """Run the Replicator worker contract and write `summary.json`.

    The current wrapper intentionally blocks before rendering unless it is
    running inside an Isaac Sim Python runtime where Replicator imports.
    """

    canonical_index = canonical_index.expanduser().resolve()
    stage_url = stage_url.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cameras = [camera.strip() for camera in cameras if camera.strip()]
    variants = max(1, int(variants))
    canonical_rows = _read_jsonl(canonical_index)
    post_render_augmentation = _post_render_augmentation_config(
        output_dir=output_dir,
        cameras=cameras,
        rgb_strength=rgb_strength,
        depth_strength=depth_strength,
        render_strength=render_strength,
        camera_pose_strength=camera_pose_strength,
        augmentation_config=augmentation_config.expanduser().resolve() if augmentation_config is not None else None,
    )
    _atomic_write_json(output_dir / "post_render_augmentation.json", post_render_augmentation)
    simulation_app, simulation_app_probe = _start_simulation_app(
        importer,
        enabled=initialize_simulation_app,
        headless=not bool(visualize_generation),
    )
    if simulation_app_probe.get("status") == "blocked":
        runtime_probe = {
            "status": "blocked",
            "import_checked": False,
            "required_modules": list(REPLICATOR_REQUIRED_MODULES),
            "error": str(simulation_app_probe.get("error") or "SimulationApp initialization failed."),
            "simulation_app": simulation_app_probe,
        }
    else:
        runtime_probe = _probe_replicator_runtime(importer)
        runtime_probe["simulation_app"] = simulation_app_probe
    base = _base_summary(
        canonical_index=canonical_index,
        stage_url=stage_url,
        output_dir=output_dir,
        cameras=cameras,
        variants=variants,
        rgb_strength=rgb_strength,
        depth_strength=depth_strength,
        render_strength=render_strength,
        camera_pose_strength=camera_pose_strength,
        post_render_augmentation=post_render_augmentation,
        canonical_rows=canonical_rows,
        runtime_probe=runtime_probe,
    )

    if not canonical_index.is_file():
        summary = _blocked_summary(
            base,
            blocker="CANONICAL_INDEX_MISSING",
            message="Canonical episode index manifest does not exist.",
            checks=[{"id": "canonical_index", "status": "blocked"}],
        )
    elif not stage_url.is_file():
        summary = _blocked_summary(
            base,
            blocker="DIGITAL_TWIN_STAGE_MISSING",
            message="Isaac Sim stage file does not exist.",
            checks=[{"id": "stage", "status": "blocked"}],
        )
    elif runtime_probe.get("status") != "passed":
        summary = _blocked_summary(
            base,
            blocker="REPLICATOR_REQUIRES_ISAAC_RUNTIME",
            message="Isaac Sim Replicator cannot be imported from this Python runtime.",
            checks=[
                {"id": "canonical_index", "status": "passed"},
                {"id": "stage", "status": "passed"},
                {
                    "id": "replicator_import",
                    "status": "blocked",
                    "required_modules": list(REPLICATOR_REQUIRED_MODULES),
                },
            ],
        )
    else:
        backend = render_backend or _default_replicator_render_backend
        try:
            render_rows = backend(
                {
                    "canonical_index": canonical_index,
                    "stage_url": stage_url,
                    "output_dir": output_dir,
                    "canonical_rows": canonical_rows,
                    "cameras": cameras,
                    "variants": variants,
                    "rgb_strength": float(rgb_strength),
                    "depth_strength": float(depth_strength),
                    "render_strength": float(render_strength),
                    "camera_pose_strength": float(camera_pose_strength),
                    "post_render_augmentation": post_render_augmentation,
                    "importer": importer,
                }
            )
        except NotImplementedError as exc:
            summary = _blocked_summary(
                base,
                blocker="REPLICATOR_RENDER_WORKER_PENDING",
                message=str(exc),
                checks=[
                    {"id": "canonical_index", "status": "passed"},
                    {"id": "stage", "status": "passed"},
                    {"id": "replicator_import", "status": "passed"},
                    {"id": "render_products", "status": "blocked", "blocker": "REPLICATOR_RENDER_WORKER_PENDING"},
                ],
            )
        except Exception as exc:  # noqa: BLE001 - preserve render worker failure in structured summary.
            summary = _blocked_summary(
                base,
                blocker="REPLICATOR_RENDER_FAILED",
                message=f"{type(exc).__name__}: {exc}",
                checks=[
                    {"id": "canonical_index", "status": "passed"},
                    {"id": "stage", "status": "passed"},
                    {"id": "replicator_import", "status": "passed"},
                    {"id": "render_products", "status": "blocked", "blocker": "REPLICATOR_RENDER_FAILED"},
                ],
            )
        else:
            manifest_rows = _normalize_render_rows(
                list(render_rows or []),
                canonical_rows,
                post_render_augmentation=post_render_augmentation,
            )
            validation = _render_file_validation(output_dir, manifest_rows)
            render_counts = _render_output_counts(output_dir, manifest_rows)
            if not validation["ok"]:
                summary = _blocked_summary(
                    {
                        **base,
                        "rendered_count": len(manifest_rows),
                        "render_products": {
                            **dict(base.get("render_products") or {}),
                            "created_count": len(manifest_rows),
                        },
                        **render_counts,
                        "render_file_validation": validation,
                    },
                    blocker="REPLICATOR_OUTPUT_FILES_MISSING",
                    message="Replicator backend returned rows that do not reference existing RGB/depth files.",
                    checks=[
                        {"id": "canonical_index", "status": "passed"},
                        {"id": "stage", "status": "passed"},
                        {"id": "replicator_import", "status": "passed"},
                        {"id": "render_products", "status": "blocked", "blocker": "REPLICATOR_OUTPUT_FILES_MISSING"},
                    ],
                )
            else:
                _atomic_write_jsonl(output_dir / "manifest.jsonl", manifest_rows)
                summary = {
                    **base,
                    "ok": True,
                    "status": "completed",
                    "blocker": "",
                    "message": "Replicator backend wrote RGB/depth render outputs and manifest rows.",
                    "rendered_count": len(manifest_rows),
                    "render_products": {
                        **dict(base.get("render_products") or {}),
                        "created_count": len(manifest_rows),
                    },
                    **render_counts,
                    "train_eligible_count": sum(1 for row in manifest_rows if row.get("train_eligible") is True),
                    "render_file_validation": validation,
                    "checks": [
                        {"id": "canonical_index", "status": "passed"},
                        {"id": "stage", "status": "passed"},
                        {"id": "replicator_import", "status": "passed"},
                        {"id": "render_products", "status": "passed"},
                        {"id": "render_rgb_depth_pairs", "status": "passed"},
                    ],
                }

    runtime_probe["simulation_app_close"] = {
        "status": "pending_process_shutdown",
        "reason": "Summary persisted before SimulationApp.close() because Isaac Sim may terminate the process during shutdown.",
    }
    summary["runtime_probe"] = runtime_probe
    _atomic_write_json(output_dir / "summary.json", summary)
    try:
        close_probe = _close_simulation_app(simulation_app)
    except BaseException as exc:
        runtime_probe["simulation_app_close"] = {
            "status": "process_exit_requested",
            "error": f"{type(exc).__name__}: {exc}",
        }
        summary["runtime_probe"] = runtime_probe
        _atomic_write_json(output_dir / "summary.json", summary)
        raise
    runtime_probe["simulation_app_close"] = close_probe
    summary["runtime_probe"] = runtime_probe
    _atomic_write_json(output_dir / "summary.json", summary)
    return summary


def _parse_cameras(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Isaac Sim Replicator synthetic RGB-D worker for LeRobot.")
    parser.add_argument("--canonical-index", required=True, help="Path to canonical_episode_index/manifest.jsonl.")
    parser.add_argument("--stage-url", required=True, help="Isaac Sim USD/USDA stage path.")
    parser.add_argument("--output-dir", required=True, help="Replicator output directory.")
    parser.add_argument("--augmentation-config", default="", help="Optional post-render augmentation contract JSON.")
    parser.add_argument("--cameras", default="top,front,right")
    parser.add_argument("--variants", type=int, default=1)
    parser.add_argument("--rgb-strength", type=float, default=1.0)
    parser.add_argument("--depth-strength", type=float, default=1.0)
    parser.add_argument("--render-strength", type=float, default=1.0)
    parser.add_argument("--camera-pose-strength", type=float, default=1.0)
    parser.add_argument(
        "--visualize-generation",
        action="store_true",
        help="Open an Isaac Sim viewport while generating instead of launching SimulationApp headless.",
    )
    args = parser.parse_args(argv)

    summary = run_replicator_worker(
        canonical_index=Path(args.canonical_index),
        stage_url=Path(args.stage_url),
        output_dir=Path(args.output_dir),
        cameras=_parse_cameras(args.cameras),
        variants=args.variants,
        rgb_strength=args.rgb_strength,
        depth_strength=args.depth_strength,
        render_strength=args.render_strength,
        camera_pose_strength=args.camera_pose_strength,
        augmentation_config=Path(args.augmentation_config) if args.augmentation_config else None,
        visualize_generation=bool(args.visualize_generation),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))
    return 0 if summary.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
