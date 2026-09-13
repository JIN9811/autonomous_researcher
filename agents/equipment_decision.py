"""Legacy import shares the canonical Equipment decision globals."""
import sys
from agents.equipment import decision as _implementation

sys.modules[__name__] = _implementation
