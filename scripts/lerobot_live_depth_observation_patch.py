"""Patch LeRobot OMX observations to expose live RealSense depth features.

The raw-depth training adapter consumes 16-bit depth and exposes model-facing
3-channel visual features named ``<camera>_depth``. During live rollout there is
no dataset sidecar yet, so this patch converts the latest RealSense depth frame
in-process and appends the same observation keys before the policy runs.
"""

from __future__ import annotations

import logging
import os
import importlib
from contextlib import nullcontext
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s.", name, value, default)
        return default


def _allowed_camera_keys() -> set[str]:
    return {item.strip() for item in os.environ.get("ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS", "").split(",") if item.strip()}


def _camera_allowed(camera_key: str) -> bool:
    allowed = _allowed_camera_keys()
    return not allowed or camera_key in allowed


def _camera_uses_depth(camera_config: Any) -> bool:
    return bool(getattr(camera_config, "use_depth", False))


def _depth_feature_key(camera_key: str) -> str:
    return f"{camera_key}_depth"


def _parse_camera_float_map(name: str) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for raw_item in os.environ.get(name, "").split(","):
        item = raw_item.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        if not key:
            continue
        try:
            value = float(raw_value.strip())
        except ValueError:
            logger.warning("Invalid %s camera value %r.", name, item)
            continue
        if value > 0.0:
            parsed[key] = value
    return parsed


def _parse_camera_clip_map(name: str) -> dict[str, tuple[float, float]]:
    parsed: dict[str, tuple[float, float]] = {}
    for raw_item in os.environ.get(name, "").split(","):
        item = raw_item.strip()
        if not item or "=" not in item or ":" not in item:
            continue
        key, raw_range = item.split("=", 1)
        raw_min, raw_max = raw_range.split(":", 1)
        key = key.strip()
        if not key:
            continue
        try:
            clip_min = float(raw_min.strip())
            clip_max = float(raw_max.strip())
        except ValueError:
            logger.warning("Invalid %s camera clip %r.", name, item)
            continue
        if clip_max > clip_min:
            parsed[key] = (clip_min, clip_max)
    return parsed


def _global_depth_clip_range_mm() -> tuple[float, float]:
    clip_min = _env_float("ATR_LEROBOT_DEPTH_CLIP_MIN_MM", 0.0)
    clip_max = _env_float("ATR_LEROBOT_DEPTH_CLIP_MAX_MM", 2000.0)
    if clip_max <= clip_min:
        logger.warning("Invalid live depth clip range min=%s max=%s; using 0..2000 mm.", clip_min, clip_max)
        return 0.0, 2000.0
    return clip_min, clip_max


def _camera_depth_clip_range_mm(camera_key: str, camera_config: Any) -> tuple[float, float]:
    env_range = _parse_camera_clip_map("ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM").get(camera_key)
    if env_range is not None:
        return env_range
    try:
        clip_min = float(getattr(camera_config, "depth_clip_min_mm"))
        clip_max = float(getattr(camera_config, "depth_clip_max_mm"))
    except (AttributeError, TypeError, ValueError):
        return _global_depth_clip_range_mm()
    return (clip_min, clip_max) if clip_max > clip_min else _global_depth_clip_range_mm()


def _camera_depth_scale_m_per_unit(camera_key: str, camera_config: Any, camera: Any) -> float:
    env_scales = _parse_camera_float_map("ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT")
    if camera_key in env_scales:
        return env_scales[camera_key]
    for candidate in (
        getattr(camera_config, "depth_scale_m_per_unit", None),
        getattr(camera, "depth_scale_m_per_unit", None),
        getattr(camera, "depth_scale", None),
    ):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return _env_float("ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT", 0.001)


def _depth_map_to_uint8_rgb(
    depth_map: np.ndarray,
    *,
    depth_scale_m_per_unit: float,
    depth_clip_range_mm: tuple[float, float],
) -> np.ndarray:
    depth = np.asarray(depth_map)
    if depth.ndim == 3 and depth.shape[-1] == 3 and depth.dtype == np.uint8:
        return depth
    if depth.ndim == 3 and depth.shape[-1] == 1:
        depth = depth[..., 0]
    if depth.ndim != 2:
        raise ValueError(f"Depth map must be HxW or HxWx1, got shape={depth.shape}.")

    values_mm = np.nan_to_num(depth.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    if depth_scale_m_per_unit > 0.0:
        values_mm = values_mm * float(depth_scale_m_per_unit) * 1000.0
    clip_min, clip_max = depth_clip_range_mm
    clipped = np.clip(values_mm, clip_min, clip_max)
    depth_u8 = np.rint((clipped - clip_min) / (clip_max - clip_min) * 255.0).astype(np.uint8)
    return np.repeat(depth_u8[..., None], 3, axis=2)


def _latest_depth_frame(camera: Any) -> np.ndarray | None:
    lock = getattr(camera, "frame_lock", None)
    context = lock if hasattr(lock, "__enter__") else nullcontext()
    with context:
        depth = getattr(camera, "latest_depth_frame", None)
        if depth is None:
            return None
        return np.array(depth, copy=True)


def _camera_config_for(robot: Any, camera_key: str) -> Any:
    cameras = getattr(getattr(robot, "config", None), "cameras", {})
    if isinstance(cameras, dict):
        return cameras.get(camera_key)
    return getattr(cameras, camera_key, None)


def _base_camera_features(descriptor: Any, robot: Any) -> dict[str, Any]:
    if isinstance(descriptor, property) and descriptor.fget is not None:
        return dict(descriptor.fget(robot))
    bound = descriptor.__get__(robot, type(robot)) if hasattr(descriptor, "__get__") else descriptor
    if callable(bound):
        return dict(bound())
    return dict(bound or {})


def install_live_depth_observation_patch(*, force: bool = False) -> bool:
    if not force and not _env_bool("ATR_LEROBOT_LIVE_DEPTH_FEATURES", False):
        return False
    try:
        module = importlib.import_module("lerobot.robots.omx_follower.omx_follower")
        OmxFollower = module.OmxFollower
    except Exception as exc:  # pragma: no cover - depends on installed LeRobot package.
        logger.warning("Could not install ATR live depth patch: %s", exc)
        return False

    if getattr(OmxFollower, "_atr_live_depth_observation_patched", False):
        return True

    original_cameras_ft = getattr(OmxFollower, "_cameras_ft", None)
    original_get_observation = OmxFollower.get_observation

    def _patched_cameras_ft(self: Any) -> dict[str, Any]:
        features = _base_camera_features(original_cameras_ft, self) if original_cameras_ft is not None else {}
        for camera_key in getattr(self, "cameras", {}):
            camera_key = str(camera_key)
            config = _camera_config_for(self, camera_key)
            if config is None or not _camera_uses_depth(config) or not _camera_allowed(camera_key):
                continue
            depth_key = _depth_feature_key(camera_key)
            features.setdefault(
                depth_key,
                features.get(camera_key)
                or (
                    int(getattr(config, "height", 0) or 0),
                    int(getattr(config, "width", 0) or 0),
                    3,
                ),
            )
        return features

    def _patched_get_observation(self: Any) -> dict[str, Any]:
        obs = original_get_observation(self)
        if not isinstance(obs, dict):
            return obs
        strict = _env_bool("ATR_LEROBOT_LIVE_DEPTH_STRICT", True)
        for camera_key, camera in getattr(self, "cameras", {}).items():
            camera_key = str(camera_key)
            config = _camera_config_for(self, camera_key)
            if config is None or not _camera_uses_depth(config) or not _camera_allowed(camera_key):
                continue
            depth_key = _depth_feature_key(camera_key)
            if depth_key in obs:
                continue
            depth = _latest_depth_frame(camera)
            if depth is None:
                if strict:
                    raise RuntimeError(f"Live RealSense depth frame is unavailable for camera {camera_key!r}.")
                color = obs.get(camera_key)
                if isinstance(color, np.ndarray) and color.ndim >= 2:
                    obs[depth_key] = np.zeros((*color.shape[:2], 3), dtype=np.uint8)
                continue
            obs[depth_key] = _depth_map_to_uint8_rgb(
                depth,
                depth_scale_m_per_unit=_camera_depth_scale_m_per_unit(camera_key, config, camera),
                depth_clip_range_mm=_camera_depth_clip_range_mm(camera_key, config),
            )
        return obs

    OmxFollower._cameras_ft = property(_patched_cameras_ft)
    OmxFollower.get_observation = _patched_get_observation
    OmxFollower._atr_live_depth_observation_patched = True
    logger.info("Installed ATR live RealSense depth observation patch for OMX follower.")
    return True
