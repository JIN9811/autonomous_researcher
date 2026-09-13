"""Compatibility alias for the canonical core Guardian agent module."""

import sys

from agents.core.guardian import agent as _implementation

sys.modules[__name__] = _implementation
