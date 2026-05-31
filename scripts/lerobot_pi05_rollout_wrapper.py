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
from pathlib import Path

# Importing the module registers the ROBOTIS OMX robot config with LeRobot's parser.
try:  # pragma: no cover - depends on the installed Pi0.5 LeRobot package.
    from lerobot.robots import omx_follower as _omx_follower  # noqa: F401
except Exception:
    # The delegated script will raise a clearer parser/runtime error if OMX is unavailable.
    pass

DEFAULT_RTC_SCRIPT = "/home/jin/lerobot_pi05/examples/rtc/eval_with_real_robot.py"
script_path = Path(os.environ.get("ATR_PI05_RTC_SCRIPT", DEFAULT_RTC_SCRIPT)).expanduser()
runpy.run_path(str(script_path), run_name="__main__")
