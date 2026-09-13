"""Compatibility alias for the canonical core Orchestrator agent module."""

import sys

from agents.core.orchestrator import agent as _implementation

sys.modules[__name__] = _implementation
