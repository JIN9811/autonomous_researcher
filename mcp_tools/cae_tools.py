"""Legacy import shares the canonical CAE tool-registration globals."""
import sys
from device_bridges.cae import tools as _implementation

sys.modules[__name__] = _implementation
