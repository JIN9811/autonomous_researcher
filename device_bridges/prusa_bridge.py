"""Compatibility alias: old imports and monkeypatches share the provider module."""
import sys
from device_bridges.prusa import bridge as _implementation

sys.modules[__name__] = _implementation
