"""Legacy import shares the canonical CAE bridge runtime globals."""
import sys
from device_bridges.cae import bridge as _implementation

sys.modules[__name__] = _implementation
