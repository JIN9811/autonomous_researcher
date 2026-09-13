"""Compatibility alias for the canonical core Orchestrator capability module."""

import sys

from agents.core.orchestrator import capabilities as _implementation

sys.modules[__name__] = _implementation
