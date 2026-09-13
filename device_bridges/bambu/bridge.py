"""Compatibility import; the shared runtime belongs to Printer Fleet."""
import sys
from device_bridges.printer_fleet import bridge as _implementation

sys.modules[__name__] = _implementation
