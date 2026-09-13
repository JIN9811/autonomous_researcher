"""Legacy import shares the canonical Windows/PyAutoGUI bridge globals."""
import sys

from device_bridges.windows_pyautogui import bridge as _implementation

sys.modules[__name__] = _implementation
