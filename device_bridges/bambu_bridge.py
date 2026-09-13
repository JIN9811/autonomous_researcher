"""Compatibility alias: old imports and monkeypatches share the provider module."""
import sys
from device_bridges.bambu import bridge as _implementation

sys.modules[__name__] = _implementation
