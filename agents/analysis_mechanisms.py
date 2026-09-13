"""Legacy import shares the canonical Analysis mechanism globals."""
import sys
from agents.analysis import mechanisms as _implementation

sys.modules[__name__] = _implementation
