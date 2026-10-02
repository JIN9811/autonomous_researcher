"""Legacy import shares the canonical Windows/PyAutoGUI tool globals."""
import sys

from device_bridges.windows_pyautogui import tools as _implementation

sys.modules[__name__] = _implementation
