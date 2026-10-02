"""Tests for persisted standalone LeRobot rollout defaults."""

from __future__ import annotations

from pathlib import Path

import utils.lerobot_rollout_profile as rollout_profile_module


def test_rollout_profile_uses_saved_manipulation_policy_as_first_migration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile_path = tmp_path / "memory" / "lerobot_rollout_profile.json"
    monkeypatch.setattr(rollout_profile_module, "LEROBOT_ROLLOUT_PROFILE_PATH", profile_path)

    profile = rollout_profile_module.load_lerobot_rollout_profile(
        fallback={
            "profile_id": "robotis_omx_ai",
            "policy_type": "smolvla",
            "policy_path": "/tmp/train/checkpoints/040000/pretrained_model",
            "policy_checkpoint_path": "/tmp/train/checkpoints/040000/pretrained_model",
            "task_instruction": "pick and place specimen",
            "continuous_rollout": True,
        }
    )

    assert profile["policy_type"] == "smolvla"
    assert profile["policy_path"].endswith("/040000/pretrained_model")
    assert profile["policy_checkpoint_path"].endswith("/040000/pretrained_model")
    assert profile["continuous_rollout"] is True


def test_rollout_profile_save_is_loaded_instead_of_newer_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile_path = tmp_path / "memory" / "lerobot_rollout_profile.json"
    monkeypatch.setattr(rollout_profile_module, "LEROBOT_ROLLOUT_PROFILE_PATH", profile_path)

    saved = rollout_profile_module.save_lerobot_rollout_profile(
        {
            "policy_type": "smolvla",
            "policy_path": "/tmp/train/checkpoints/040000/pretrained_model",
            "policy_checkpoint_path": "/tmp/train/checkpoints/040000/pretrained_model",
            "task_instruction": "saved rollout",
            "continuous_rollout": False,
            "max_duration_s": 90,
            "rollout_action_clamp": True,
            "rollout_max_relative_target": 4,
        }
    )
    loaded = rollout_profile_module.load_lerobot_rollout_profile(
        fallback={
            "policy_type": "smolvla",
            "policy_path": "/tmp/train/checkpoints/085000/pretrained_model",
            "policy_checkpoint_path": "/tmp/train/checkpoints/085000/pretrained_model",
        }
    )

    assert profile_path.exists()
    assert saved == loaded
    assert loaded["policy_path"].endswith("/040000/pretrained_model")
    assert loaded["task_instruction"] == "saved rollout"
    assert loaded["continuous_rollout"] is False
    assert loaded["max_duration_s"] == 90.0
    assert loaded["rollout_action_clamp"] is True
    assert loaded["rollout_max_relative_target"] == 4
