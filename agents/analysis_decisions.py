"""Legacy import shares the canonical Analysis decision globals."""
import sys
from agents.analysis import decisions as _implementation

sys.modules[__name__] = _implementation
