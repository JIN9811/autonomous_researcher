"""Legacy import shares the canonical Analysis improvement globals."""
import sys
from agents.analysis import improvement as _implementation

sys.modules[__name__] = _implementation
