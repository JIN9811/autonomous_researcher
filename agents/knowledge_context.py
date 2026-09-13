"""Compatibility alias for the canonical core Knowledge context module."""

import sys

from agents.core.knowledge import context as _implementation

sys.modules[__name__] = _implementation
