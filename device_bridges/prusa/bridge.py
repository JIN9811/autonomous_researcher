"""Compatibility import for Printer Fleet's internal Prusa provider."""
import sys
from device_bridges.printer_fleet.providers import prusa as _implementation

sys.modules[__name__] = _implementation
