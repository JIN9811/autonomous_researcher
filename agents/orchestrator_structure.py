"""Compatibility alias for the canonical core Orchestrator structure module."""

import sys

from agents.core.orchestrator import structure as _implementation

sys.modules[__name__] = _implementation
