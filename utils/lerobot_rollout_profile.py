"""Persist standalone LeRobot inference/rollout defaults."""

from __future__ import annotations

import json
from typing import Any

from utils.paths import resolve_path


LEROBOT_ROLLOUT_PROFILE_PATH = resolve_path("memory/lerobot_rollout_profile.json")

DEFAULT_LEROBOT_ROLLOUT_PROFILE: dict[str, Any] = {
    "profile_id": "robotis_omx_ai",
    "observation_pipeline_id": "raw_depth_adapter",
    "policy_type": "smolvla",
    "policy_path": "",
    "policy_checkpoint_path": "",
    "policy_repo_id": "",
    "task_instruction": "Pick up the cube and place it",
    "continuous_rollout": True,
    "max_duration_s": None,
    "rollout_action_clamp": False,
    "rollout_max_relative_target": 5,
    "rollout_shoulder_lift_backstop": True,
    "rollout_temporal_ensemble": False,
    "rollout_temporal_ensemble_coeff": 0.01,
    "rollout_inference_type": "",
    "rollout_rtc_execution_horizon": None,
    "rollout_rtc_max_guidance_weight": None,
    "rollout_action_queue_size_to_get_new_actions": None,
    "observation": {"observation_id": "manual", "anomaly": False},
}

_STRING_LIMITS = {
    "profile_id": 120,
    "observation_pipeline_id": 80,
    "policy_type": 40,
    "policy_path": 1000,
    "policy_checkpoint_path": 1000,
    "policy_repo_id": 240,
    "task_instruction": 2000,
    "rollout_inference_type": 40,
}


def _clean_string(value: Any, default: str, max_len: int) -> str:
    text = str(default if value is None else value).strip()
    return (text or default)[:max_len]


def _clean_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default if value is None else bool(value)


def _clean_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


def _clean_optional_int(value: Any, minimum: int, maximum: int) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


def _clean_optional_float(value: Any, minimum: float, maximum: float) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


def normalize_lerobot_rollout_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize fields used by the standalone Inference / Rollout panel."""
    source = raw if isinstance(raw, dict) else {}
    profile = dict(DEFAULT_LEROBOT_ROLLOUT_PROFILE)
    profile.update({key: value for key, value in source.items() if key in profile})

    for key, max_len in _STRING_LIMITS.items():
        profile[key] = _clean_string(
            profile.get(key),
            str(DEFAULT_LEROBOT_ROLLOUT_PROFILE[key]),
            max_len,
        )

    if profile["policy_type"] not in {"act", "diffusion", "smolvla", "pi0", "pi05", "pi0fast", "xvla", "vqbet"}:
        profile["policy_type"] = DEFAULT_LEROBOT_ROLLOUT_PROFILE["policy_type"]
    if profile["observation_pipeline_id"] not in {"legacy_lerobot", "rgbd_sidecar", "raw_depth_adapter"}:
        profile["observation_pipeline_id"] = DEFAULT_LEROBOT_ROLLOUT_PROFILE["observation_pipeline_id"]
    if profile["rollout_inference_type"] not in {"", "sync", "rtc"}:
        profile["rollout_inference_type"] = ""

    for key in (
        "continuous_rollout",
        "rollout_action_clamp",
        "rollout_shoulder_lift_backstop",
        "rollout_temporal_ensemble",
    ):
        profile[key] = _clean_bool(profile.get(key), bool(DEFAULT_LEROBOT_ROLLOUT_PROFILE[key]))

    profile["rollout_max_relative_target"] = _clean_int(
        profile.get("rollout_max_relative_target"), 5, 1, 180
    )
    temporal_coeff = _clean_optional_float(profile.get("rollout_temporal_ensemble_coeff"), 0.0, 1.0)
    profile["rollout_temporal_ensemble_coeff"] = 0.01 if temporal_coeff is None else temporal_coeff
    profile["rollout_rtc_execution_horizon"] = _clean_optional_int(
        profile.get("rollout_rtc_execution_horizon"), 1, 200
    )
    profile["rollout_action_queue_size_to_get_new_actions"] = _clean_optional_int(
        profile.get("rollout_action_queue_size_to_get_new_actions"), 1, 300
    )
    profile["rollout_rtc_max_guidance_weight"] = _clean_optional_float(
        profile.get("rollout_rtc_max_guidance_weight"), 0.0, 20.0
    )
    profile["max_duration_s"] = _clean_optional_float(profile.get("max_duration_s"), 1.0, 86400.0)
    profile["observation"] = dict(profile.get("observation")) if isinstance(profile.get("observation"), dict) else dict(DEFAULT_LEROBOT_ROLLOUT_PROFILE["observation"])
    return profile


def load_lerobot_rollout_profile(*, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load persisted rollout defaults, using an existing saved task profile once for migration."""
    if not LEROBOT_ROLLOUT_PROFILE_PATH.exists():
        return normalize_lerobot_rollout_profile(fallback)
    try:
        raw = json.loads(LEROBOT_ROLLOUT_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = fallback or {}
    return normalize_lerobot_rollout_profile(raw if isinstance(raw, dict) else fallback)


def save_lerobot_rollout_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Persist normalized standalone rollout defaults."""
    profile = normalize_lerobot_rollout_profile(raw)
    LEROBOT_ROLLOUT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEROBOT_ROLLOUT_PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return profile
