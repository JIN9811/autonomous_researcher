"""Legacy import shares the canonical LeRobot bridge runtime globals."""
import sys

from device_bridges.lerobot import bridge as _implementation

sys.modules[__name__] = _implementation
