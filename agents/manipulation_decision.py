"""Legacy import shares the canonical Manipulation decision globals."""
import sys
from agents.manipulation import decision as _implementation

sys.modules[__name__] = _implementation
