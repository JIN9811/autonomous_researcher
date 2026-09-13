"""Legacy import shares the canonical BO owner's runtime globals."""
import sys
from agents.bo import agent as _implementation

sys.modules[__name__] = _implementation
