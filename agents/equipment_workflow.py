"""Legacy import shares the canonical Equipment workflow globals."""
import sys
from agents.equipment import workflow as _implementation

sys.modules[__name__] = _implementation
