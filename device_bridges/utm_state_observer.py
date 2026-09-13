"""Compatibility alias for the grouped Camera/Vision state observer."""
import sys
from device_bridges.camera_vision import utm_state_observer as _implementation

sys.modules[__name__] = _implementation
