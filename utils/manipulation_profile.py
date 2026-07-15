"""
File purpose:
- Persist operator-controlled Manipulation Agent bridge defaults for live/test loops.

Key classes/functions:
- load_manipulation_agent_profile
- save_manipulation_agent_profile

Inputs/outputs:
- Input: JSON-compatible GUI payload fields
- Output: normalized profile stored under memory/manipulation_agent_bridge.json

Dependencies:
- utils.paths.resolve_path

Modification guide:
- Safe places to edit: default values and allowed profile keys.
- Risky places to edit: field names consumed by ManipulationAgent and web/static/lerobot.js.
"""

from __future__ import annotations

import json
from typing import Any

from utils.paths import resolve_path


MANIPULATION_AGENT_PROFILE_PATH = resolve_path("memory/manipulation_agent_bridge.json")
MANIPULATION_TASK_IDS = ("transfer_to_utm", "clear_utm_to_disposal")
MANIPULATION_TASK_LOCATIONS = {
    "transfer_to_utm": ("3dp_output_area", "utm_fixture"),
    "clear_utm_to_disposal": ("utm_fixture", "discard_bin"),
}

DEFAULT_MANIPULATION_AGENT_PROFILE: dict[str, Any] = {
    "manipulation_strategy": "lerobot_policy",
    "profile_id": "robotis_omx_ai",
    "observation_pipeline_id": "rgbd_sidecar",
    "policy_type": "smolvla",
    "policy_path": "",
    "policy_checkpoint_path": "",
    "policy_repo_id": "",
    "dataset_root": "",
    "dataset_repo_id": "jin/3dp_to_utm_smolvla_rollout",
    "device": "cuda",
    "fps": 30,
    "camera_fps": 30,
    "task_id": "transfer_to_utm",
    "skill_id": "transfer_to_utm",
    "source_location": "3dp_output_area",
    "target_location": "utm_fixture",
    "task_instruction": "",
    "policy_backend": "lerobot_cli",
    "camera_enabled": True,
    "display_data": False,
    "continuous_rollout": True,
    "rollout_action_clamp": False,
    "rollout_max_relative_target": 5,
    "rollout_shoulder_lift_backstop": True,
    "rollout_temporal_ensemble": True,
    "rollout_temporal_ensemble_coeff": 0.01,
    "rollout_inference_type": "",
    "rollout_rtc_execution_horizon": 20,
    "rollout_rtc_max_guidance_weight": 1.0,
    "rollout_action_queue_size_to_get_new_actions": 60,
    "max_duration_s": 30.0,
    "observation": {"observation_id": "manual-transfer", "anomaly": False},
    "task_profiles": {},
}

_STRING_LIMITS = {
    "manipulation_strategy": 80,
    "profile_id": 120,
    "observation_pipeline_id": 80,
    "policy_type": 40,
    "policy_path": 1000,
    "policy_checkpoint_path": 1000,
    "policy_repo_id": 240,
    "dataset_root": 1000,
    "dataset_repo_id": 240,
    "device": 40,
    "task_id": 80,
    "skill_id": 80,
    "source_location": 120,
    "target_location": 120,
    "task_instruction": 2000,
    "policy_backend": 80,
    "rollout_inference_type": 40,
}

_TASK_PROFILE_KEYS = {
    "manipulation_strategy",
    "policy_type",
    "policy_path",
    "policy_checkpoint_path",
    "policy_repo_id",
    "dataset_root",
    "dataset_repo_id",
    "task_id",
    "skill_id",
    "source_location",
    "target_location",
    "task_instruction",
    "policy_backend",
    "continuous_rollout",
    "rollout_action_clamp",
    "rollout_max_relative_target",
    "rollout_shoulder_lift_backstop",
    "rollout_temporal_ensemble",
    "rollout_temporal_ensemble_coeff",
    "rollout_inference_type",
    "rollout_rtc_execution_horizon",
    "rollout_rtc_max_guidance_weight",
    "rollout_action_queue_size_to_get_new_actions",
    "max_duration_s",
    "observation",
}


def _clean_string(value: Any, default: str, *, max_len: int) -> str:
    text = str(value if value is not None else default).strip()
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
    if value is None:
        return default
    return bool(value)


def _clean_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    if parsed < min_value or parsed > max_value:
        return int(default)
    return parsed


def _clean_float(value: Any, default: float, *, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if parsed < min_value or parsed > max_value:
        return float(default)
    return parsed


def _clean_observation(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return dict(default or {})


def _normalize_policy_reference(profile: dict[str, Any]) -> None:
    """Keep one persisted policy reference authoritative for every runtime call."""
    policy_path = str(profile.get("policy_path") or "").strip()
    checkpoint_path = str(profile.get("policy_checkpoint_path") or "").strip()
    policy_repo_id = str(profile.get("policy_repo_id") or "").strip()

    if policy_path:
        profile["policy_path"] = policy_path
        profile["policy_checkpoint_path"] = "" if policy_path.startswith("fake://") else policy_path
        profile["policy_repo_id"] = ""
        return
    if checkpoint_path:
        profile["policy_path"] = checkpoint_path
        profile["policy_checkpoint_path"] = checkpoint_path
        profile["policy_repo_id"] = ""
        return
    profile["policy_path"] = ""
    profile["policy_checkpoint_path"] = ""
    profile["policy_repo_id"] = policy_repo_id


def _normalize_task_profile(task_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    source_location, target_location = MANIPULATION_TASK_LOCATIONS.get(
        task_id,
        MANIPULATION_TASK_LOCATIONS["transfer_to_utm"],
    )
    profile = {
        key: DEFAULT_MANIPULATION_AGENT_PROFILE[key]
        for key in _TASK_PROFILE_KEYS
        if key in DEFAULT_MANIPULATION_AGENT_PROFILE
    }
    profile.update(
        {
            "task_id": task_id,
            "skill_id": task_id,
            "source_location": source_location,
            "target_location": target_location,
        }
    )
    profile.update({key: value for key, value in source.items() if key in _TASK_PROFILE_KEYS})

    for key, max_len in _STRING_LIMITS.items():
        if key in profile:
            profile[key] = _clean_string(profile.get(key), str(DEFAULT_MANIPULATION_AGENT_PROFILE.get(key, "")), max_len=max_len)
    _normalize_policy_reference(profile)

    profile["task_id"] = task_id
    profile["skill_id"] = task_id
    profile["source_location"] = source_location
    profile["target_location"] = target_location
    if profile["policy_type"] not in {"pi05", "act", "diffusion", "pi0", "pi0fast", "vqbet", "xvla", "smolvla"}:
        profile["policy_type"] = DEFAULT_MANIPULATION_AGENT_PROFILE["policy_type"]
    if profile["policy_backend"] not in {"lerobot_cli", "openpi_server", "fixed_kinematic", "act_policy"}:
        profile["policy_backend"] = DEFAULT_MANIPULATION_AGENT_PROFILE["policy_backend"]
    if profile["manipulation_strategy"] not in {"pi05_lerobot_policy", "lerobot_policy", "fixed_kinematic"}:
        profile["manipulation_strategy"] = DEFAULT_MANIPULATION_AGENT_PROFILE["manipulation_strategy"]
    if profile["rollout_inference_type"] not in {"", "sync", "rtc"}:
        profile["rollout_inference_type"] = DEFAULT_MANIPULATION_AGENT_PROFILE["rollout_inference_type"]

    profile["rollout_max_relative_target"] = _clean_int(profile.get("rollout_max_relative_target"), 5, min_value=1, max_value=180)
    profile["rollout_temporal_ensemble_coeff"] = _clean_float(profile.get("rollout_temporal_ensemble_coeff"), 0.01, min_value=0.0, max_value=1.0)
    profile["rollout_rtc_execution_horizon"] = _clean_int(profile.get("rollout_rtc_execution_horizon"), 20, min_value=1, max_value=200) if profile.get("rollout_rtc_execution_horizon") not in (None, "") else None
    profile["rollout_action_queue_size_to_get_new_actions"] = _clean_int(profile.get("rollout_action_queue_size_to_get_new_actions"), 60, min_value=1, max_value=300) if profile.get("rollout_action_queue_size_to_get_new_actions") not in (None, "") else None
    profile["rollout_rtc_max_guidance_weight"] = _clean_float(profile.get("rollout_rtc_max_guidance_weight"), 1.0, min_value=0.0, max_value=20.0) if profile.get("rollout_rtc_max_guidance_weight") not in (None, "") else None
    profile["max_duration_s"] = _clean_float(profile.get("max_duration_s"), 30.0, min_value=1.0, max_value=86400.0) if profile.get("max_duration_s") not in (None, "") else None
    for key in ("continuous_rollout", "rollout_action_clamp", "rollout_shoulder_lift_backstop", "rollout_temporal_ensemble"):
        profile[key] = _clean_bool(profile.get(key), bool(DEFAULT_MANIPULATION_AGENT_PROFILE[key]))
    profile["observation"] = _clean_observation(profile.get("observation"), DEFAULT_MANIPULATION_AGENT_PROFILE["observation"])
    return profile


def normalize_manipulation_agent_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize GUI-supplied Manipulation Agent defaults."""
    source = raw if isinstance(raw, dict) else {}
    profile = dict(DEFAULT_MANIPULATION_AGENT_PROFILE)
    profile.update({key: value for key, value in source.items() if key in profile})

    for key, max_len in _STRING_LIMITS.items():
        profile[key] = _clean_string(profile.get(key), str(DEFAULT_MANIPULATION_AGENT_PROFILE[key]), max_len=max_len)
    _normalize_policy_reference(profile)

    profile["fps"] = _clean_int(profile.get("fps"), 30, min_value=1, max_value=240)
    profile["camera_fps"] = _clean_int(profile.get("camera_fps"), 30, min_value=1, max_value=240)
    profile["rollout_max_relative_target"] = _clean_int(
        profile.get("rollout_max_relative_target"),
        5,
        min_value=1,
        max_value=180,
    )
    profile["rollout_temporal_ensemble_coeff"] = _clean_float(
        profile.get("rollout_temporal_ensemble_coeff"),
        0.01,
        min_value=0.0,
        max_value=1.0,
    )
    profile["rollout_rtc_execution_horizon"] = _clean_int(
        profile.get("rollout_rtc_execution_horizon"),
        20,
        min_value=1,
        max_value=200,
    ) if profile.get("rollout_rtc_execution_horizon") not in (None, "") else None
    profile["rollout_action_queue_size_to_get_new_actions"] = _clean_int(
        profile.get("rollout_action_queue_size_to_get_new_actions"),
        60,
        min_value=1,
        max_value=300,
    ) if profile.get("rollout_action_queue_size_to_get_new_actions") not in (None, "") else None
    profile["rollout_rtc_max_guidance_weight"] = _clean_float(
        profile.get("rollout_rtc_max_guidance_weight"),
        1.0,
        min_value=0.0,
        max_value=20.0,
    ) if profile.get("rollout_rtc_max_guidance_weight") not in (None, "") else None
    profile["max_duration_s"] = _clean_float(
        profile.get("max_duration_s"),
        30.0,
        min_value=1.0,
        max_value=86400.0,
    ) if profile.get("max_duration_s") not in (None, "") else None
    for key in (
        "camera_enabled",
        "display_data",
        "continuous_rollout",
        "rollout_action_clamp",
        "rollout_shoulder_lift_backstop",
        "rollout_temporal_ensemble",
    ):
        profile[key] = _clean_bool(profile.get(key), bool(DEFAULT_MANIPULATION_AGENT_PROFILE[key]))

    if profile["manipulation_strategy"] not in {"pi05_lerobot_policy", "lerobot_policy", "fixed_kinematic"}:
        profile["manipulation_strategy"] = DEFAULT_MANIPULATION_AGENT_PROFILE["manipulation_strategy"]
    if profile["task_id"] not in {"transfer_to_utm", "clear_utm_to_disposal"}:
        profile["task_id"] = DEFAULT_MANIPULATION_AGENT_PROFILE["task_id"]
    if profile["skill_id"] not in {"transfer_to_utm", "clear_utm_to_disposal"}:
        profile["skill_id"] = profile["task_id"]
    if profile["policy_type"] not in {"pi05", "act", "diffusion", "pi0", "pi0fast", "vqbet", "xvla", "smolvla"}:
        profile["policy_type"] = DEFAULT_MANIPULATION_AGENT_PROFILE["policy_type"]
    if profile["policy_backend"] not in {"lerobot_cli", "openpi_server", "fixed_kinematic", "act_policy"}:
        profile["policy_backend"] = DEFAULT_MANIPULATION_AGENT_PROFILE["policy_backend"]
    if profile["rollout_inference_type"] not in {"", "sync", "rtc"}:
        profile["rollout_inference_type"] = DEFAULT_MANIPULATION_AGENT_PROFILE["rollout_inference_type"]
    if profile["observation_pipeline_id"] not in {"legacy_lerobot", "rgbd_sidecar", "raw_depth_adapter"}:
        profile["observation_pipeline_id"] = DEFAULT_MANIPULATION_AGENT_PROFILE["observation_pipeline_id"]
    profile["observation"] = _clean_observation(profile.get("observation"), DEFAULT_MANIPULATION_AGENT_PROFILE["observation"])
    raw_task_profiles = source.get("task_profiles") if isinstance(source.get("task_profiles"), dict) else {}
    task_profiles = {
        task_id: _normalize_task_profile(task_id, raw_task_profiles.get(task_id) if isinstance(raw_task_profiles, dict) else {})
        for task_id in MANIPULATION_TASK_IDS
    }
    current_task = profile["task_id"]
    # Only fields explicitly supplied at the profile root represent edits to the
    # selected task. Normalized root defaults must not erase task-specific data.
    current_task_overrides = {key: source[key] for key in _TASK_PROFILE_KEYS if key in source}
    task_profiles[current_task] = _normalize_task_profile(
        current_task,
        {**task_profiles.get(current_task, {}), **current_task_overrides},
    )
    profile["task_profiles"] = task_profiles
    profile["skill_id"] = current_task
    profile["source_location"] = task_profiles[current_task]["source_location"]
    profile["target_location"] = task_profiles[current_task]["target_location"]
    return profile


def load_manipulation_agent_profile() -> dict[str, Any]:
    """Load saved Manipulation Agent defaults, falling back to safe defaults."""
    if not MANIPULATION_AGENT_PROFILE_PATH.exists():
        return normalize_manipulation_agent_profile({})
    try:
        raw = json.loads(MANIPULATION_AGENT_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return normalize_manipulation_agent_profile(raw if isinstance(raw, dict) else {})


def save_manipulation_agent_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Persist normalized Manipulation Agent defaults."""
    profile = normalize_manipulation_agent_profile(raw)
    MANIPULATION_AGENT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIPULATION_AGENT_PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile
