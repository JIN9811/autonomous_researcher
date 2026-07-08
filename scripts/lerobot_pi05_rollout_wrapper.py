"""
File purpose:
- Launch the local Pi0.5 RTC real-robot evaluation script after registering ATR robot classes.

Key behavior:
- Imports OMX follower support before draccus parses --robot.type=omx_follower.
- Delegates CLI parsing/execution to /home/jin/lerobot_pi05/examples/rtc/eval_with_real_robot.py.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Importing the module registers the ROBOTIS OMX robot config with LeRobot's parser.
try:  # pragma: no cover - depends on the installed Pi0.5 LeRobot package.
    from lerobot.robots import omx_follower as _omx_follower  # noqa: F401
except Exception:
    # The delegated script will raise a clearer parser/runtime error if OMX is unavailable.
    pass

from scripts.lerobot_live_depth_observation_patch import install_live_depth_observation_patch
from scripts.lerobot_omx_runtime_units_patch import install_omx_follower_runtime_units_patch


def _install_atr_action_logger() -> None:
    """Log real motor command deltas without modifying LeRobot's external source tree."""
    try:
        interval = int(os.environ.get("ATR_PI05_ACTION_LOG_INTERVAL", "30") or "0")
    except ValueError:
        interval = 30
    if interval <= 0:
        return
    try:
        from lerobot.robots.omx_follower.omx_follower import OmxFollower
    except Exception:
        return
    original = OmxFollower.send_action
    if getattr(original, "_atr_logged", False):
        return

    import logging

    logger = logging.getLogger("atr.pi05.action")

    def _logged_send_action(self, action):  # type: ignore[no-untyped-def]
        count = int(getattr(self, "_atr_action_count", 0)) + 1
        setattr(self, "_atr_action_count", count)
        should_log = count == 1 or count % interval == 0
        present = {}
        goal = {}
        if should_log:
            try:
                present = self.bus.sync_read("Present_Position")
            except Exception as exc:  # pragma: no cover - live hardware diagnostic only.
                logger.warning("[ATR_ACTION] count=%s present_read_failed=%s", count, exc)
            for key, value in dict(action).items():
                if str(key).endswith(".pos"):
                    motor = str(key).removesuffix(".pos")
                    try:
                        goal[motor] = float(value)
                    except Exception:
                        goal[motor] = value
            deltas = {}
            for motor, target in goal.items():
                if motor in present:
                    try:
                        deltas[motor] = float(target) - float(present[motor])
                    except Exception:
                        pass
            max_abs_delta = max((abs(v) for v in deltas.values()), default=0.0)
            logger.info(
                "[ATR_ACTION] count=%s max_abs_delta=%.3f goal=%s present=%s delta=%s",
                count,
                max_abs_delta,
                goal,
                present,
                {k: round(v, 3) for k, v in deltas.items()},
            )
        return original(self, action)

    _logged_send_action._atr_logged = True  # type: ignore[attr-defined]
    OmxFollower.send_action = _logged_send_action


install_omx_follower_runtime_units_patch()
_install_atr_action_logger()
install_live_depth_observation_patch()

DEFAULT_RTC_SCRIPT = "/home/jin/lerobot_pi05/examples/rtc/eval_with_real_robot.py"
script_path = Path(os.environ.get("ATR_PI05_RTC_SCRIPT", DEFAULT_RTC_SCRIPT)).expanduser()
runpy.run_path(str(script_path), run_name="__main__")
