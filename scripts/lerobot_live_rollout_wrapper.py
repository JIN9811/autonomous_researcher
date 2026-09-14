#!/usr/bin/env python3
"""Run generic LeRobot policy rollout with ATR live depth observation patches."""

from __future__ import annotations

import sys
import os
import runpy
import logging
import time
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
DEFAULT_RTC_SCRIPT = "~/lerobot_pi05/examples/rtc/eval_with_real_robot.py"


def _lerobot_record_main():
    try:
        from lerobot.scripts.lerobot_record import main as record_main

        return record_main
    except ModuleNotFoundError:
        import lerobot.record as record_module

        return record_module.main


def _rtc_requested(argv: list[str] | None = None) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(args):
        if item.startswith("--rtc.enabled="):
            return item.split("=", 1)[1].strip().lower() in {"1", "true", "yes", "on"}
        if item == "--rtc.enabled" and index + 1 < len(args):
            return args[index + 1].strip().lower() in {"1", "true", "yes", "on"}
    return False


def _lerobot_rtc_main():
    script_path = Path(os.environ.get("ATR_LEROBOT_RTC_SCRIPT", DEFAULT_RTC_SCRIPT)).expanduser()

    def run() -> None:
        runpy.run_path(str(script_path), run_name="__main__")

    return run


def _install_rtc_observation_retry() -> bool:
    """Keep a transient RealSense frame miss from killing the RTC inference thread."""
    try:
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
    except Exception:
        return False
    original = OmxFollower.get_observation
    if getattr(original, "_atr_rtc_retry", False):
        return True
    try:
        attempts = max(1, int(os.environ.get("ATR_LEROBOT_RTC_OBSERVATION_RETRIES", "3")))
    except ValueError:
        attempts = 3
    try:
        delay_s = max(0.0, float(os.environ.get("ATR_LEROBOT_RTC_OBSERVATION_RETRY_DELAY_S", "0.05")))
    except ValueError:
        delay_s = 0.05
    logger = logging.getLogger("atr.lerobot.rtc")

    def get_observation_with_retry(self):  # type: ignore[no-untyped-def]
        for attempt in range(1, attempts + 1):
            try:
                return original(self)
            except TimeoutError:
                if attempt >= attempts:
                    raise
                logger.warning("[RTC_CAMERA] observation timeout; retrying %s/%s", attempt, attempts - 1)
                if delay_s:
                    time.sleep(delay_s)
        raise RuntimeError("unreachable RTC observation retry state")

    get_observation_with_retry._atr_rtc_retry = True  # type: ignore[attr-defined]
    OmxFollower.get_observation = get_observation_with_retry
    return True


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
    if _rtc_requested():
        _install_rtc_observation_retry()
        _lerobot_rtc_main()()
    else:
        _lerobot_record_main()()


if __name__ == "__main__":
    main()
