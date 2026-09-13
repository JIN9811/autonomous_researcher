"""Compatibility alias for the canonical core Knowledge agent module."""

import sys

from agents.core.knowledge import agent as _implementation

sys.modules[__name__] = _implementation
