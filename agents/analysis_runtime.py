"""Legacy import shares the canonical Analysis runtime globals."""
import sys
from agents.analysis import runtime as _implementation

sys.modules[__name__] = _implementation
