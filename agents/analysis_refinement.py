"""Legacy import shares the canonical Analysis refinement globals."""
import sys
from agents.analysis import refinement as _implementation

sys.modules[__name__] = _implementation
