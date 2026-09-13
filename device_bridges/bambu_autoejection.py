"""Compatibility alias for the grouped Bambu G-code autoejection implementation."""
import sys
from device_bridges.bambu import autoejection as _implementation

sys.modules[__name__] = _implementation
