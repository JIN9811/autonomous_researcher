"""Legacy import shares the canonical CalculiX tool-registration globals."""
import sys
from device_bridges.cae import calculix_tools as _implementation

sys.modules[__name__] = _implementation
