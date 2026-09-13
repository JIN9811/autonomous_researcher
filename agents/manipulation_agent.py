"""Legacy import shares the canonical Manipulation owner's runtime globals."""
import sys
from agents.manipulation import agent as _implementation

sys.modules[__name__] = _implementation
