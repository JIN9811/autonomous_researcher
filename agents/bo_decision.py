"""Legacy import shares the canonical BO decision globals."""
import sys
from agents.bo import decision as _implementation

sys.modules[__name__] = _implementation
