"""Legacy import shares the canonical Analysis calibration globals."""
import sys
from agents.analysis import calibration as _implementation

sys.modules[__name__] = _implementation
