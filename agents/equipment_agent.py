"""Legacy import shares the canonical Equipment owner's runtime globals."""
import sys
from agents.equipment import agent as _implementation

sys.modules[__name__] = _implementation
