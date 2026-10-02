"""Compatibility alias for the grouped Camera/Vision RealSense bridge."""
import sys
from device_bridges.camera_vision import realsense_bridge as _implementation

sys.modules[__name__] = _implementation
