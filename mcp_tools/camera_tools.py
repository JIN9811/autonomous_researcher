"""Compatibility alias for Camera/Vision tool registration."""
import sys
from device_bridges.camera_vision import tools as _implementation

sys.modules[__name__] = _implementation
