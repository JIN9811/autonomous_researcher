"""Compatibility import for Printer Fleet's file-only Bambu patcher."""
import sys
from device_bridges.printer_fleet.providers import bambu_autoejection as _implementation

sys.modules[__name__] = _implementation
