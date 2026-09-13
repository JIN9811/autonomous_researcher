"""Legacy import shares the canonical LeRobot tool-registration globals."""
import sys

from device_bridges.lerobot import tools as _implementation

sys.modules[__name__] = _implementation
