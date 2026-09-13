"""Compatibility alias for the canonical core Knowledge decision module."""

import sys

from agents.core.knowledge import decision as _implementation

sys.modules[__name__] = _implementation
