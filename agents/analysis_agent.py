"""Legacy import shares the canonical Analysis owner's runtime globals."""
import sys
from agents.analysis import agent as _implementation

sys.modules[__name__] = _implementation
