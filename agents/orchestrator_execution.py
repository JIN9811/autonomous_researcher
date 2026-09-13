"""Compatibility alias for the canonical core Orchestrator execution module."""

import sys

from agents.core.orchestrator import execution as _implementation

sys.modules[__name__] = _implementation
