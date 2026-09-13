"""Internal Bambu provider shares the fleet's existing runtime and patch points.

Transport classes remain with the shared manager to preserve their global
dependencies; this alias does not register a second bridge or create a client.
"""
import sys
from device_bridges.printer_fleet import bridge as _implementation

sys.modules[__name__] = _implementation
