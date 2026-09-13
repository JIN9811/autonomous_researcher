"""Compatibility alias for the grouped Camera/Vision UTM runtime."""
import sys
from device_bridges.camera_vision import utm_runtime_bridge as _implementation

sys.modules[__name__] = _implementation
