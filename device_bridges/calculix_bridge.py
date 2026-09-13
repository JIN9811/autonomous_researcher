"""Legacy import shares the canonical CalculiX bridge runtime globals."""
import sys
from device_bridges.cae import calculix as _implementation

sys.modules[__name__] = _implementation
