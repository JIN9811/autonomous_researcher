#!/usr/bin/env python3
"""Run generic LeRobot policy rollout with ATR live depth observation patches."""

from __future__ import annotations

import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Importing this module registers the ROBOTIS OMX config before draccus parses
# --robot.type=omx_follower in LeRobot.
try:  # pragma: no cover - depends on the installed LeRobot package.
    from lerobot.robots import omx_follower as _omx_follower  # noqa: F401
except Exception:
    pass

from scripts.lerobot_live_depth_observation_patch import install_live_depth_observation_patch  # noqa: E402
from scripts.lerobot_omx_action_logger import install_omx_follower_action_logger  # noqa: E402
from scripts.lerobot_omx_runtime_units_patch import install_omx_follower_runtime_units_patch  # noqa: E402


_OMX_ACTION_LOG_MOTORS = "shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper"


def _lerobot_record_main():
    try:
        from lerobot.scripts.lerobot_record import main as record_main

        return record_main
    except ModuleNotFoundError:
        import lerobot.record as record_module

        return record_module.main


def _ensure_omx_action_log_env_defaults() -> None:
    os.environ.setdefault("ATR_LEROBOT_OMX_ACTION_LOG", "1")
    os.environ.setdefault("ATR_LEROBOT_OMX_ACTION_LOG_MOTORS", _OMX_ACTION_LOG_MOTORS)
    session_id = os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID", "").strip()
    if not session_id:
        session_id = f"{_rollout_dataset_name_from_argv()}-pid{os.getpid()}"
        os.environ["ATR_LEROBOT_OMX_ACTION_LOG_SESSION_ID"] = session_id
    if not os.environ.get("ATR_LEROBOT_OMX_ACTION_LOG_DIR", "").strip():
        os.environ["ATR_LEROBOT_OMX_ACTION_LOG_DIR"] = str(REPO_ROOT / "runs" / "lerobot_action_logs" / session_id)


def _rollout_dataset_name_from_argv() -> str:
    for index, item in enumerate(sys.argv):
        if item.startswith("--dataset.repo_id="):
            return _safe_name(item.split("=", 1)[1].rsplit("/", 1)[-1])
        if item == "--dataset.repo_id" and index + 1 < len(sys.argv):
            return _safe_name(sys.argv[index + 1].rsplit("/", 1)[-1])
    return "live-rollout"


def _safe_name(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip()).strip(".-")
    return clean or "live-rollout"


def main() -> None:
    _ensure_omx_action_log_env_defaults()
    install_omx_follower_runtime_units_patch()
    install_live_depth_observation_patch()
    install_omx_follower_action_logger()
    _lerobot_record_main()()


if __name__ == "__main__":
    main()
