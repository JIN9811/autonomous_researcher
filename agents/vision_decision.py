"""Legacy import shares the canonical Vision decision module identity."""
import sys
from agents.vision import decision as _owner

sys.modules[__name__] = _owner
