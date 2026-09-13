"""Legacy import shares the canonical Analysis FEM globals."""
import sys
from agents.analysis import fem as _implementation

sys.modules[__name__] = _implementation
