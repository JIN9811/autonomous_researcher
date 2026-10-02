"""Compatibility alias for the grouped Camera/Vision pose tracker."""
import sys
from device_bridges.camera_vision import specimen_pose_tracker as _implementation

sys.modules[__name__] = _implementation
